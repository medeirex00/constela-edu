"""Importação da PLANILHA DE MATRÍCULAS da escola ("Lista Piloto").

A secretaria mantém um Excel com UMA ABA POR TURMA. Cada aba tem um
cabeçalho (escola, professor, ano/turma, turno, nº da classe SED) e, a
partir de uma linha de títulos, uma linha por aluno com muitos campos
cadastrais:

    N.º | RM | RA | Nome | Data de Nasc. | Responsável | Endereço | Bairro |
    Telefone | Matrícula | Transferência | Remanejamento | RG | CPF | SUS |
    RESPONSÁVEL NOME COMPLETO | SEXO | RAÇA COR | BOLSA FAMÍLIA

Este módulo lê o arquivo (`.xls` legado via xlrd; `.xlsx` via openpyxl),
reconhece cada turma e seus alunos e devolve uma estrutura pronta para
criar as turmas e matricular os alunos — o número de chamada e a data de
nascimento vão para os campos próprios do aluno; o restante fica na
`ficha` cadastral (JSON). Abas de resumo (ex.: "QE") são ignoradas por
não terem a coluna "Nome".
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.models import Aluno, Turma
from app.services.importacao import chave_nome, normalizar_nome
from app.services.planilhas import (
    MAX_COLUNAS_LIDAS,
    OrcamentoLeitura,
    PlanilhaRecusada,
    exigir_xlsx_contido,
    limitar_celula,
    linhas_contidas,
)

logger = logging.getLogger(__name__)

# Teto de células do arquivo: uma escola tem centenas/milhares de alunos; muito
# acima disso é planilha inválida ou tentativa de exaustão de memória (uma
# .xlsx é um zip e pode inflar muito). Barra antes de materializar tudo.
# Conta o PERCORRIDO em cada linha com conteúdo (.xlsx e .xls) — até a última
# célula preenchida, inclusive as vazias no meio (``planilhas.OrcamentoLeitura``).
# Linha vazia e colunas vazias à direita não contam: é comum um Excel real declarar
# a planilha inteira (ex.: formatação aplicada nas 16.384 colunas de uma aba), e
# isso não pode barrar o arquivo à toa.
_MAX_CELULAS = 2_000_000
# Ignora colunas/linhas muito além de qualquer lista de matrícula real (uma
# formatação de coluna/linha inteira não deve ser lida nem contada).
_MAX_COLS = MAX_COLUNAS_LIDAS
_MAX_LINHAS = 50_000
# Linhas percorridas no arquivo inteiro (todas as abas, inclusive as vazias que o
# leitor completa entre duas linhas do XML): uma Lista Piloto tem dezenas de abas
# de dezenas de linhas.
_MAX_LINHAS_ARQUIVO = 500_000

# Tamanho das COLUNAS onde a importação grava. A Lista Piloto grava direto no
# banco (não passa pelos schemas com ``max_length``) e o corte de célula
# (``planilhas.MAX_TEXTO_CELULA``, 1000) fica acima de todas elas: no PostgreSQL o
# valor maior que a coluna era DataError no commit, e o arquivo inteiro caía com
# 500, sem dizer qual célula (o SQLite aceita qualquer tamanho e não via). Os
# tetos saem dos MODELOS — fonte única — e o excesso vira AVISO:
#   * nome do aluno acima da coluna → a LINHA fica de fora;
#   * nº de chamada fora do INTEGER → o número é ignorado, o aluno entra;
#   * nº da classe (SED) acima da coluna → o código é ignorado, a turma entra;
#   * turma NOVA com nome acima da coluna → a ABA fica de fora;
#   * turma NOVA com série acima da coluna → a série é cortada, se o corte não
#     mudar a leitura dela (série, premiação, etapa); senão a ABA fica de fora.
# Turma que JÁ existe não grava nome nem série (``conferir_turma_nova``).
MAX_NOME_ALUNO = Aluno.__table__.c.nome.type.length              # 200
MAX_NOME_TURMA = Turma.__table__.c.nome.type.length              # 100
MAX_SERIE = Turma.__table__.c.ano_escolar.type.length            # 30
MAX_CODIGO_SED = Turma.__table__.c.codigo_externo.type.length    # 40
#: ``Aluno.numero_chamada`` é INTEGER: 32 bits com sinal no PostgreSQL.
MAX_NUMERO_CHAMADA = 2**31 - 1

# --------------------------------------------------------------------------
# Estruturas de resultado
# --------------------------------------------------------------------------

@dataclass
class AlunoMatricula:
    nome: str
    numero_chamada: int | None = None
    data_nascimento: str | None = None      # ISO "AAAA-MM-DD"
    ficha: dict = field(default_factory=dict)


@dataclass
class TurmaMatriculas:
    nome: str
    ano_escolar: str
    turno: str | None = None
    professor: str = ""
    sed: str = ""
    alunos: list[AlunoMatricula] = field(default_factory=list)
    aba: str = ""                 # título da aba, para os avisos
    # Linhas de aluno que ficaram de fora por não caberem nas colunas: com
    # alguma, a reconciliação não marca ninguém desta turma "fora da lista".
    linhas_puladas: int = 0


@dataclass
class ListaPilotoAnalise:
    escola_detectada: str = ""
    ano_letivo: int | None = None
    turmas: list[TurmaMatriculas] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def total_alunos(self) -> int:
        return sum(len(t.alunos) for t in self.turmas)


# --------------------------------------------------------------------------
# Leitura uniforme de .xls (xlrd) e .xlsx (openpyxl)
# --------------------------------------------------------------------------

def _abrir(conteudo: bytes) -> list[tuple[str, list[list]]]:
    """Devolve [(nome_aba, linhas)], cada linha uma lista de células já
    normalizadas (datas viram date; inteiros viram int; resto, str/valor)."""
    if conteudo[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":  # OLE2 = .xls legado
        return _abrir_xls(conteudo)
    return _abrir_xlsx(conteudo)  # zip (.xlsx) e demais


def _abrir_xls(conteudo: bytes) -> list[tuple[str, list[list]]]:
    import xlrd
    from xlrd.xldate import xldate_as_datetime

    # ragged_rows: sem ele, o xlrd completa TODA linha até a coluna mais à direita da
    # aba — uma célula em (65535, 255), ou um intervalo mesclado até lá, criava 16,7
    # milhões de células (um .xls de 5,6 KB levava 33 s e +259 MB, e97). Com ele,
    # cada linha termina na última célula escrita, e o orçamento é o do .xlsx.
    wb = xlrd.open_workbook(file_contents=conteudo, ragged_rows=True)
    vazias = (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK)
    orcamento = OrcamentoLeitura(_MAX_LINHAS_ARQUIVO, _MAX_CELULAS)
    abas: list[tuple[str, list[list]]] = []
    for s in wb.sheets():
        linhas = []
        for r in range(min(s.nrows, _MAX_LINHAS)):
            orcamento.linhas += 1
            if orcamento.linhas > orcamento.max_linhas:
                orcamento.recusar()
            tipos = s.row_types(r, 0, min(s.row_len(r), _MAX_COLS))
            fim = len(tipos)
            while fim and tipos[fim - 1] in vazias:
                fim -= 1
            if not fim:
                continue                           # linha vazia some, como no .xlsx
            orcamento.celulas += fim
            if orcamento.celulas > orcamento.max_celulas:
                orcamento.recusar()
            celulas = []
            for tipo, valor in zip(tipos[:fim], s.row_values(r, 0, fim)):
                if tipo in vazias:
                    valor = None                   # vazia como no .xlsx
                elif tipo == xlrd.XL_CELL_DATE:
                    valor = xldate_as_datetime(valor, wb.datemode).date()
                elif tipo == xlrd.XL_CELL_NUMBER and valor == int(valor):
                    valor = int(valor)
                celulas.append(limitar_celula(valor))
            linhas.append(celulas)
        abas.append((limitar_celula(s.name), linhas))
    return abas


def _data_sem_hora(valor):
    return valor.date() if isinstance(valor, datetime) else valor


def _abrir_xlsx(conteudo: bytes) -> list[tuple[str, list[list]]]:
    import openpyxl

    # Teto do DESCOMPRIMIDO antes do openpyxl: o teto de células acima conta
    # células, não bytes — uma única célula gigante na sharedStrings passava
    # (300 KB enviados levaram o processo a +4,8 GB, e97).
    exigir_xlsx_contido(conteudo)
    wb = openpyxl.load_workbook(io.BytesIO(conteudo), data_only=True, read_only=True)
    # O orçamento conta o PERCORRIDO no arquivo inteiro: um .xlsx de 2 KB que
    # declarava A1:XFD50000 com uma célula em A50000 levava 33 s, percorrendo 50.000
    # linhas de 256 colunas vazias (e97). Linha vazia some (aqui a posição da linha
    # não importa) e as colunas vazias à direita não contam.
    orcamento = OrcamentoLeitura(_MAX_LINHAS_ARQUIVO, _MAX_CELULAS)
    abas: list[tuple[str, list[list]]] = []
    try:
        for aba in wb.worksheets:
            linhas = linhas_contidas(aba, orcamento, _MAX_LINHAS, manter_vazias=False,
                                     converter=_data_sem_hora)
            abas.append((limitar_celula(aba.title), linhas))
    finally:
        wb.close()
    return abas


# --------------------------------------------------------------------------
# Reconhecimento das colunas e dos metadados da aba
# --------------------------------------------------------------------------

def _txt(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float):
        # NaN/Inf (célula corrompida) não são dados úteis e quebrariam int().
        if valor != valor or valor in (float("inf"), float("-inf")):
            return ""
        if valor == int(valor):
            valor = int(valor)
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor).strip()


def _plano(valor) -> str:
    """Texto normalizado (sem acento/caixa/espaço extra) para casar rótulos."""
    return normalizar_nome(_txt(valor))


def _rotulo(valor) -> str:
    """Rótulo de cabeçalho sem pontuação (º ª ° . : ( )) — 'N.º' → 'n',
    'N.º da Classe (SED):' → 'n da classe sed'."""
    limpo = re.sub(r"[.º°ª:()/]", " ", _plano(valor))
    return re.sub(r"\s+", " ", limpo).strip()


_RA_PLACEHOLDER = {"sra", "semra", "na", "nao", "sn", "xxx", "xxxx",
                   "999", "9999", "99999"}


def ra_util(ra_texto) -> str:
    """RA utilizável como IDENTIDADE única. Placeholders comuns que a secretaria
    digita quando o RA ainda não saiu ('0', '00', 'S/RA', 'N/A', valores muito
    curtos) NÃO identificam ninguém — devolve "" para não colar crianças
    distintas que compartilham o mesmo texto de preenchimento."""
    ra = re.sub(r"[^0-9a-z]", "", _plano(ra_texto))
    if not ra or len(ra) < 3 or ra.strip("0") == "" or ra in _RA_PLACEHOLDER:
        return ""
    return ra


# Colunas conhecidas → sinônimos do cabeçalho (texto normalizado, sem acento).
# A ordem importa: o 1º sinônimo que casar vence. `ra`/`rm`/`rg` são exatos
# para não colidirem entre si.
_COLUNAS = {
    "numero": ("n", "no", "numero"),
    "rm": ("rm",),
    "ra": ("ra",),
    "nome": ("nome", "nome do aluno", "nome do estudante", "nome completo do aluno",
             "nome do a", "aluno"),
    # "dt nasc" é o rótulo do MODELO OFICIAL da rede ("DT. NASC."). Sem ele a
    # coluna não era mapeada e a importação saía sem nascimento para a escola
    # inteira, em silêncio — perdendo o corroborador e o veto de identidade mais
    # fortes do motor (``matching.conflito_identidade``).
    "nascimento": ("data de nasc", "data de nascimento", "nascimento", "data nasc",
                   "dt nasc"),
    "responsavel_completo": ("responsavel nome completo", "nome completo do responsavel"),
    "responsavel": ("responsavel", "nome da mae", "nome do responsavel",
                    "nome da mae ou responsavel", "mae", "filiacao"),
    "endereco": ("endereco",),
    "bairro": ("bairro",),
    "telefone": ("telefone", "fone", "contato"),
    "matricula": ("matricula",),
    "transferencia": ("transferencia",),
    "remanejamento": ("remanejamento",),
    "rg": ("rg",),
    "cpf": ("cpf",),
    "sus": ("sus", "cartao sus"),
    "sexo": ("sexo",),
    "raca_cor": ("raca cor", "raca", "cor"),
    "bolsa_familia": ("bolsa fam", "bolsa familia", "bolsa"),
}

# Rótulos legíveis da ficha (para exibir no perfil do aluno).
# MINIMIZAÇÃO DE DADOS (LGPD Art. 5º/6º/11): o produto guarda do aluno APENAS o
# necessário para premiar e identificar — nome e nº de chamada (colunas próprias)
# e o RA (identidade única entre plataformas). Categorias SENSÍVEIS (raça/cor,
# saúde/SUS) e documentos (CPF, RG) NÃO são coletados: colunas dessas nas
# planilhas são simplesmente ignoradas na importação. A migração 0014 purga o que
# já havia sido gravado. Para reintroduzir qualquer campo, exige base legal
# documentada (ROPA) — não basta acrescentar aqui.
ROTULOS_FICHA = {
    "ra": "RA",
}

_NAO_ALUNO = ("total", "toda a turma", "whole class", "toda la clase")

# Marcadores de rodapé que algumas planilhas anexam ao nome (asterisco de
# "observação", bolinha, cerquilha). NÃO fazem parte do nome — e, se ficassem
# colados nele, quebrariam o casamento por nome com Matific/Elefante (a nota
# não colaria no aluno). Removidos só das pontas, nunca do miolo.
_MARCADORES_NOME = " \t*#•·‧∙°º"


def _limpar_nome(bruto: str) -> str:
    """Colapsa espaços e tira marcadores de rodapé das pontas do nome."""
    return " ".join((bruto or "").split()).strip(_MARCADORES_NOME)


def _casar_coluna(rotulo: str, ja_usadas: set[str]) -> str | None:
    """Casa o cabeçalho com o campo cujo sinônimo casado é o MAIS específico
    (mais longo). Assim "Nome da mãe (Responsável)" cai em `responsavel` (via
    "nome da mae") em vez de ser engolido pelo genérico `nome`."""
    p = _rotulo(rotulo)
    if not p:
        return None
    melhor_campo: str | None = None
    melhor_len = -1
    for campo, sinonimos in _COLUNAS.items():
        if campo in ja_usadas:
            continue
        for s in sinonimos:
            if (p == s or p.startswith(s + " ")) and len(s) > melhor_len:
                melhor_campo, melhor_len = campo, len(s)
    return melhor_campo


def _linha_cabecalho(linhas: list[list]) -> int | None:
    """Índice da linha de títulos: a que tem a coluna 'Nome' e uma data/RA.
    Usa _rotulo (sem pontuação) para reconhecer também 'R.A.'/'N.º'/'Data de
    Nasc.' com pontos.

    Os rótulos de nascimento saem de ``_COLUNAS`` — não de uma lista própria.
    Quando havia duas listas, acrescentar um sinônimo lá (o 'dt nasc' do modelo
    oficial) fazia a coluna ser MAPEADA mas a linha de títulos não ser
    RECONHECIDA: uma planilha com 'DT. NASC.' e sem coluna de RA era recusada
    inteira, com o aviso enganoso de que faltava a coluna 'Nome'."""
    for i, linha in enumerate(linhas):
        rotulos = {_rotulo(v) for v in linha if v is not None}  # vazia não é rótulo
        tem_nascimento = any(p == s or p.startswith(s + " ")
                             for p in rotulos for s in _COLUNAS["nascimento"])
        if "nome" in rotulos and (tem_nascimento or "ra" in rotulos):
            return i
    return None


def _valor_apos_rotulo(linha: list, alvo: str, contains: bool = False) -> str:
    """Numa linha de metadados, o valor à DIREITA do rótulo (ou o que sobra
    após ':' na própria célula, ex. 'Turno:       TARDE'). `contains`=True
    casa o rótulo em qualquer posição da célula (ex.: 'N.º da Classe (SED)')."""
    for idx, celula in enumerate(linha):
        if celula is None:  # vazia nunca é rótulo
            continue
        p = _rotulo(celula)
        casa = (alvo in p) if contains else p.startswith(alvo)
        if p and casa:
            bruto = _txt(celula)
            if ":" in bruto:
                depois = bruto.split(":", 1)[1].strip()
                if depois:
                    return depois
            for prox in linha[idx + 1:]:
                if _txt(prox):
                    return _txt(prox)
    return ""


_TURNOS = {
    "manha": "manha", "manhã": "manha", "matutino": "manha",
    "tarde": "tarde", "vespertino": "tarde",
    "noite": "noite", "noturno": "noite",
    "integral": "integral",
}


def _turno_normalizado(bruto: str) -> str | None:
    p = normalizar_nome(bruto)
    for chave, valor in _TURNOS.items():
        if chave in p:
            return valor
    return None


# "1º Ano A" / "1º ANO B" / "4° ANO B" / "2 ano c" → forma canônica única, para
# não duplicar turmas por diferença de caixa/acento/grau ao reimportar ou casar
# com turmas já criadas.
_RE_TURMA = re.compile(r"^\s*(\d+)\s*[ºªo°]?\s*ano\s*([A-Za-z])?\s*$", re.IGNORECASE)


def _canonizar_turma(nome: str) -> tuple[str, str]:
    """(nome_turma, serie) canônicos. '1º ANO B' → ('1º Ano B', '1º Ano').
    Formatos fora do padrão "Nº Ano X" ficam como estão (série = nome)."""
    nome = " ".join(nome.split())
    casado = _RE_TURMA.match(nome)
    if not casado:
        return nome, re.sub(r"\s+[A-Za-z]$", "", nome).strip() or nome
    serie = f"{casado.group(1)}º Ano"
    letra = (casado.group(2) or "").upper()
    return (f"{serie} {letra}" if letra else serie), serie


# --------------------------------------------------------------------------
# Análise
# --------------------------------------------------------------------------

_MIMETYPE_ODS = b"application/vnd.oasis.opendocument.spreadsheet"


def _eh_ods(conteudo: bytes) -> bool:
    """O .ods (LibreOffice) é um zip cuja entrada ``mimetype`` diz o formato. Lida com
    teto: o arquivo já passou pela guarda de planilha inflada antes do leitor falhar."""
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
            with pacote.open("mimetype") as entrada:
                return entrada.read(len(_MIMETYPE_ODS) + 16).strip() == _MIMETYPE_ODS
    except Exception:  # noqa: BLE001 — não é zip, ou não tem a entrada: não é .ods
        return False


def _aviso_planilha_ilegivel(conteudo: bytes) -> str:
    if _eh_ods(conteudo):
        return ("A planilha está no formato do LibreOffice (.ods). Abra no LibreOffice, "
                "salve como Excel (.xlsx) e envie de novo.")
    return ("Não foi possível ler a planilha. Abra o arquivo no Excel, salve como .xlsx "
            "e envie de novo.")


def analisar_matriculas(conteudo: bytes, nome_arquivo: str = "") -> ListaPilotoAnalise:
    analise = ListaPilotoAnalise()
    try:
        abas = _abrir(conteudo)
    except PlanilhaRecusada:
        raise  # inflada ou grande demais: a rota recusa (413/400) com a mensagem
    except Exception as exc:  # noqa: BLE001 — arquivo ilegível vira aviso, não 500
        # O aviso diz o que fazer; o tipo do erro do leitor vai para o log — sem o
        # nome do arquivo nem a mensagem do leitor, que podem trazer dado de aluno
        # (o xlrd cita os primeiros bytes do arquivo).
        logger.warning("Lista Piloto ilegível (%d bytes): %s", len(conteudo),
                       type(exc).__name__)
        analise.avisos.append(_aviso_planilha_ilegivel(conteudo))
        return analise

    ano_arquivo = _ano_do_texto(nome_arquivo)
    for nome_aba, linhas in abas:
        hr = _linha_cabecalho(linhas)
        if hr is None:
            continue  # aba de resumo/legenda — sem coluna "Nome"

        # Metadados no topo (linhas antes do cabeçalho).
        topo = linhas[:hr]
        for linha in topo:
            if not analise.escola_detectada:
                v = _valor_apos_rotulo(linha, "escola")
                if v:
                    analise.escola_detectada = v
            if analise.ano_letivo is None:
                v = _valor_apos_rotulo(linha, "lista piloto")
                # isdecimal, não isdigit: "2026²" é dígito para o isdigit e o int()
                # levantava — sem try aqui, a prévia inteira dava 500.
                if v.strip().isdecimal():
                    analise.ano_letivo = int(v.strip())
        turma = _extrair_turma(nome_aba, topo)
        # Aba AUXILIAR (ex.: "COMPARAR COM INEP", "DESENHOS", "Etiqueta"): tem
        # uma coluna "Nome", mas NENHUM metadado de turma (turno/professor/SED)
        # do bloco de matrícula. Não é uma turma de verdade — não importar.
        if not (turma.turno or turma.professor or turma.sed):
            continue
        if len(turma.sed) > MAX_CODIGO_SED:
            # Só o código some (é a chave de reimportação, cortá-lo inventaria
            # outro): a turma continua sendo reconhecida pelo nome.
            analise.avisos.append(
                f"Aba “{turma.aba}”: o nº da classe (SED) tem {len(turma.sed)} "
                f"dígitos (o máximo é {MAX_CODIGO_SED}) e é ignorado — a turma é "
                "reconhecida pelo nome.")
            turma.sed = ""

        # Mapa de colunas do cabeçalho.
        colunas: dict[str, int] = {}
        usadas: set[str] = set()
        for c, celula in enumerate(linhas[hr]):
            campo = _casar_coluna(_txt(celula), usadas)
            if campo:
                colunas[campo] = c
                usadas.add(campo)
        if "nome" not in colunas:
            continue

        vistos: set[str] = set()
        # ``posicao``: a linha PREENCHIDA abaixo dos títulos (a leitura descarta as
        # vazias), para o aviso apontar a célula sem citar dado pessoal.
        for posicao, linha in enumerate(linhas[hr + 1:], start=1):
            try:
                aluno = _extrair_aluno(linha, colunas)
            except Exception as exc:  # noqa: BLE001 — linha corrompida não derruba a aba
                # Mas não some em silêncio: aviso (aba e posição, sem nome) e log; e,
                # como a criança da linha não foi vista, a turma não marca ninguém
                # "fora da lista piloto" neste envio (``linhas_puladas``).
                logger.warning("Lista Piloto: aba %r, %dª linha abaixo dos títulos não "
                               "pôde ser lida: %s", turma.aba[:60], posicao,
                               type(exc).__name__)
                turma.linhas_puladas += 1
                analise.avisos.append(
                    f"Aba “{turma.aba}”, {posicao}ª linha preenchida abaixo dos títulos: "
                    "a linha não pôde ser lida e fica fora da importação. Confira a "
                    "planilha e envie de novo; até lá, ninguém desta turma é marcado "
                    "“fora da lista piloto”.")
                continue
            if aluno is None:
                continue
            if not _aluno_cabe_nas_colunas(analise, turma, posicao, aluno):
                continue
            chave = (ra_util(aluno.ficha.get("ra")) or chave_nome(aluno.nome))
            if chave in vistos:
                analise.avisos.append(
                    f"{turma.nome}: “{aluno.nome}” aparece mais de uma vez na aba "
                    "— contado uma vez.")
                continue
            vistos.add(chave)
            turma.alunos.append(aluno)

        if turma.alunos:
            analise.turmas.append(turma)

    # Mesmo aluno em DUAS turmas: a escola às vezes lista quem está trocando de
    # sala. Com RA, é o mesmo aluno (cadastrado uma vez, matriculado na 1ª). Sem
    # RA, pode ser homônimo — avisamos para o gestor conferir (não deduplicamos
    # sozinhos, para não fundir crianças diferentes).
    grupos: dict[tuple[str, str], list[str]] = {}
    for turma in analise.turmas:
        for aluno in turma.alunos:
            ra = ra_util(aluno.ficha.get("ra"))
            chave = ("ra", ra) if ra else ("nome", chave_nome(aluno.nome))
            grupos.setdefault(chave, []).append((turma.nome, aluno.nome))
    for (tipo, _), ocs in grupos.items():
        turmas_distintas = sorted({t for t, _ in ocs})
        if len(turmas_distintas) < 2:
            continue
        turmas_str = ", ".join(turmas_distintas)
        nome0 = ocs[0][1]
        if tipo == "ra":
            analise.avisos.append(
                f"“{nome0}” aparece em mais de uma turma ({turmas_str}) — será "
                f"cadastrado(a) uma vez e matriculado(a) em {ocs[0][0]}.")
        else:
            analise.avisos.append(
                f"“{nome0}” aparece em mais de uma turma ({turmas_str}) sem RA — "
                "confira se é a mesma pessoa (será cadastrado(a) em cada turma).")

    if analise.ano_letivo is None:
        analise.ano_letivo = ano_arquivo
    if not analise.turmas:
        analise.avisos.append(
            "Nenhuma turma reconhecida. Confira se a planilha tem uma aba por "
            "turma com a coluna “Nome”.")
    return analise


def _extrair_turma(nome_aba: str, topo: list[list]) -> TurmaMatriculas:
    nome = ""
    turno = None
    professor = ""
    sed = ""
    for linha in topo:
        if not nome:
            v = _valor_apos_rotulo(linha, "ano")
            # "Ano:" às vezes casa com "Ano letivo:", cujo valor é só "2026".
            # Exige formato de turma (a palavra "ano" no valor) para não batizar
            # a turma com o ano letivo.
            if v and re.search(r"\bano\b", _plano(v)):
                nome = v
        if turno is None:
            v = _valor_apos_rotulo(linha, "turno")
            if v:
                turno = _turno_normalizado(v)
        if not professor:
            professor = _valor_apos_rotulo(linha, "professor")
        if not sed:
            v = _valor_apos_rotulo(linha, "classe", contains=True)
            if v.strip().isdecimal():      # "123456¹" (rodapé) não é o código da classe
                sed = v.strip()
    nome_turma, serie = _canonizar_turma(nome or nome_aba)
    return TurmaMatriculas(nome=nome_turma, ano_escolar=serie,
                           turno=turno, professor=professor, sed=sed, aba=nome_aba)


def _aluno_cabe_nas_colunas(analise: ListaPilotoAnalise, turma: TurmaMatriculas,
                            posicao: int, aluno: AlunoMatricula) -> bool:
    """Confere os campos do aluno contra as colunas onde a confirmação grava.

    Nome acima de ``Aluno.nome``: a LINHA fica de fora (cortar o nome mudaria a
    identidade da criança — o casamento é por nome). Como ela não é vista, a
    reconciliação não marca ninguém desta turma "fora da lista" neste envio
    (``turma.linhas_puladas``): a criança da linha pulada não some das visões.
    Nº de chamada fora do INTEGER: não é número de chamada — fica sem ele.
    O aviso aponta aba, posição e N.º; não cita nome, RA nem o valor da célula."""
    onde = f"Aba “{turma.aba}”, {posicao}ª linha preenchida abaixo dos títulos"
    if len(aluno.nome) > MAX_NOME_ALUNO:
        turma.linhas_puladas += 1
        numero = (f" (N.º {aluno.numero_chamada})"
                  if aluno.numero_chamada is not None
                  and aluno.numero_chamada <= MAX_NUMERO_CHAMADA else "")
        analise.avisos.append(
            f"{onde}{numero}: o nome do aluno tem {len(aluno.nome)} caracteres "
            f"(o máximo é {MAX_NOME_ALUNO}) e a linha fica fora da importação. "
            "Corrija a célula e envie de novo; até lá, ninguém desta turma é "
            "marcado “fora da lista piloto”.")
        return False
    if aluno.numero_chamada is not None and aluno.numero_chamada > MAX_NUMERO_CHAMADA:
        aluno.numero_chamada = None
        analise.avisos.append(
            f"{onde}: o N.º não é um número de chamada válido e é ignorado — o "
            "aluno entra sem ele.")
    return True


def _leitura_da_serie(rotulo: str) -> tuple:
    """O que o sistema LÊ de uma série: o número (fator de série do motor), a
    série que concorre à premiação e a etapa fora dela. Cortar a série não pode
    mudar nada disso — seria mudar critério pedagógico por causa do tamanho."""
    # Import tardio: ``dificuldade_livro`` puxa o motor de pontuação.
    from app.services import elegibilidade
    from app.services.dificuldade_livro import serie_numero

    return (serie_numero(rotulo), elegibilidade.ano_premiavel(rotulo),
            elegibilidade.e_etapa_fora_da_premiacao(rotulo))


def conferir_turma_nova(turma: TurmaMatriculas, *,
                        previa: bool = False) -> tuple[str | None, list[str]]:
    """(série a gravar, avisos) da turma que a importação vai CRIAR — ``None`` na
    série quando a turma não cabe nas colunas e a ABA fica de fora.

    Só para turma nova: a que já existe (mesma chave de turma) não grava nome nem
    série, e recusá-la por tamanho quebraria um envio que hoje funciona.
      * nome acima de ``Turma.nome`` → aba de fora (o nome é a identidade da
        turma; cortá-lo poderia colar a aba noutra turma);
      * série acima de ``Turma.ano_escolar`` → cortada no tamanho da coluna se o
        corte não mudar a leitura (``_leitura_da_serie``); senão, aba de fora.
    ``previa`` só muda o tempo verbal do aviso (a prévia não grava nada)."""
    aba = turma.aba or turma.nome
    sera = "será" if previa else "foi"
    if len(turma.nome) > MAX_NOME_TURMA:
        return None, [
            f"Aba “{aba}”: o nome da turma tem {len(turma.nome)} caracteres (o "
            f"máximo é {MAX_NOME_TURMA}) e a aba não {sera} importada. Encurte o "
            "campo “Ano:” (ex.: “4º Ano B”) e envie de novo."]
    serie = turma.ano_escolar
    if len(serie) <= MAX_SERIE:
        return serie, []
    cortada = serie[:MAX_SERIE].rstrip()
    if _leitura_da_serie(cortada) != _leitura_da_serie(serie):
        return None, [
            f"Aba “{aba}”: a série tem {len(serie)} caracteres (o máximo é "
            f"{MAX_SERIE}) e, cortada, mudaria a série ou a premiação da turma — "
            f"a aba não {sera} importada. Encurte o campo “Ano:” (ex.: “4º Ano "
            "B”) e envie de novo."]
    return cortada, [
        f"Aba “{aba}”: a série tem {len(serie)} caracteres (o máximo é "
        f"{MAX_SERIE}) e {sera} gravada como “{cortada}”."]


def _extrair_aluno(linha: list, colunas: dict[str, int]) -> AlunoMatricula | None:
    def val(campo: str) -> str:
        c = colunas.get(campo)
        return _txt(linha[c]) if c is not None and c < len(linha) else ""

    nome = _limpar_nome(val("nome"))
    if not nome or normalizar_nome(nome).startswith(_NAO_ALUNO):
        return None
    if not any(ch.isalpha() for ch in nome):
        return None

    aluno = AlunoMatricula(nome=nome)
    numero = val("numero")
    # isdecimal, não isdigit: o "2¹" de rodapé é dígito para o isdigit e o int()
    # levantava — a linha inteira (a criança) ficava de fora. Como "2a", fica sem nº.
    if numero.isdecimal():
        aluno.numero_chamada = int(numero)

    c_nasc = colunas.get("nascimento")
    if c_nasc is not None and c_nasc < len(linha):
        bruto = linha[c_nasc]
        if isinstance(bruto, date):
            aluno.data_nascimento = bruto.isoformat()
        elif isinstance(bruto, (int, float)) and not isinstance(bruto, bool) \
                and 10000 <= bruto <= 60000:
            # Serial de data do Excel sem formato de data (~1927–2064): a coluna
            # "Data de Nasc." perdeu a formatação e chegou como número cru.
            aluno.data_nascimento = (
                date(1899, 12, 30) + timedelta(days=int(bruto))).isoformat()
        else:
            iso = _data_iso(_txt(bruto))
            if iso:
                aluno.data_nascimento = iso

    for campo in ROTULOS_FICHA:
        v = val(campo)
        if v:
            aluno.ficha[campo] = v
    return aluno


_RE_DATA_BR = re.compile(r"^([0-3]?\d)/([01]?\d)/(\d{2,4})$")


def _data_iso(bruto: str) -> str | None:
    par = _RE_DATA_BR.match(bruto.strip())
    if not par:
        return None
    dia, mes, ano = par.groups()
    ano = int(ano)
    if ano < 100:
        ano += 1900 if ano > 30 else 2000
    try:
        return date(ano, int(mes), int(dia)).isoformat()
    except ValueError:
        return None


def _ano_do_texto(texto: str) -> int | None:
    achado = re.search(r"20\d{2}", texto or "")
    return int(achado.group()) if achado else None
