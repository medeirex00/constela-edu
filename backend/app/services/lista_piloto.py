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
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.services.importacao import normalizar_nome

# Teto de células COM CONTEÚDO: uma escola tem centenas/milhares de alunos; muito
# acima disso é planilha inválida ou tentativa de exaustão de memória (uma
# .xlsx é um zip e pode inflar muito). Barra antes de materializar tudo.
# IMPORTANTE: conta só células NÃO vazias — é comum um Excel real declarar a
# planilha inteira (ex.: formatação aplicada nas 16.384 colunas de uma aba),
# o que inflaria o total com milhões de células vazias e barraria o arquivo à toa.
_MAX_CELULAS = 2_000_000
# Ignora colunas/linhas muito além de qualquer lista de matrícula real (uma
# formatação de coluna/linha inteira não deve ser lida nem contada).
_MAX_COLS = 256
_MAX_LINHAS = 50_000

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

    wb = xlrd.open_workbook(file_contents=conteudo)
    abas: list[tuple[str, list[list]]] = []
    total = 0
    for s in wb.sheets():
        ncols = min(s.ncols, _MAX_COLS)
        nrows = min(s.nrows, _MAX_LINHAS)
        linhas = []
        for r in range(nrows):
            celulas = []
            for c in range(ncols):
                tipo = s.cell_type(r, c)
                valor = s.cell_value(r, c)
                if tipo == xlrd.XL_CELL_DATE:
                    valor = xldate_as_datetime(valor, wb.datemode).date()
                elif tipo == xlrd.XL_CELL_NUMBER and valor == int(valor):
                    valor = int(valor)
                if valor not in (None, ""):        # só conteúdo conta pro teto
                    total += 1
                celulas.append(valor)
            linhas.append(celulas)
        if total > _MAX_CELULAS:
            raise ValueError("planilha grande demais")
        abas.append((s.name, linhas))
    return abas


def _abrir_xlsx(conteudo: bytes) -> list[tuple[str, list[list]]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(conteudo), data_only=True, read_only=True)
    abas: list[tuple[str, list[list]]] = []
    total = 0
    for aba in wb.worksheets:
        linhas = []
        # max_col/max_row limitam a leitura: uma aba com formatação nas 16.384
        # colunas (inchaço comum de Excel) não é lida inteira nem conta pro teto.
        for linha in aba.iter_rows(values_only=True, max_row=_MAX_LINHAS, max_col=_MAX_COLS):
            total += sum(1 for valor in linha if valor is not None)  # só conteúdo
            if total > _MAX_CELULAS:
                wb.close()
                raise ValueError("planilha grande demais")
            celulas = []
            for valor in linha:
                if isinstance(valor, datetime):
                    valor = valor.date()
                celulas.append(valor)
            linhas.append(list(celulas))
        abas.append((aba.title, linhas))
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
    "nascimento": ("data de nasc", "data de nascimento", "nascimento", "data nasc"),
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
    Nasc.' com pontos."""
    for i, linha in enumerate(linhas):
        rotulos = {_rotulo(v) for v in linha}
        if "nome" in rotulos and (
            any(p.startswith("data de nasc") for p in rotulos)
            or "ra" in rotulos or "nascimento" in rotulos):
            return i
    return None


def _valor_apos_rotulo(linha: list, alvo: str, contains: bool = False) -> str:
    """Numa linha de metadados, o valor à DIREITA do rótulo (ou o que sobra
    após ':' na própria célula, ex. 'Turno:       TARDE'). `contains`=True
    casa o rótulo em qualquer posição da célula (ex.: 'N.º da Classe (SED)')."""
    for idx, celula in enumerate(linha):
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

def analisar_matriculas(conteudo: bytes, nome_arquivo: str = "") -> ListaPilotoAnalise:
    analise = ListaPilotoAnalise()
    try:
        abas = _abrir(conteudo)
    except Exception as exc:  # noqa: BLE001 — arquivo ilegível vira aviso, não 500
        analise.avisos.append(f"Não foi possível ler a planilha: {exc}")
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
                if v.strip().isdigit():
                    analise.ano_letivo = int(v.strip())
        turma = _extrair_turma(nome_aba, topo)
        # Aba AUXILIAR (ex.: "COMPARAR COM INEP", "DESENHOS", "Etiqueta"): tem
        # uma coluna "Nome", mas NENHUM metadado de turma (turno/professor/SED)
        # do bloco de matrícula. Não é uma turma de verdade — não importar.
        if not (turma.turno or turma.professor or turma.sed):
            continue

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
        for linha in linhas[hr + 1:]:
            try:
                aluno = _extrair_aluno(linha, colunas)
            except Exception:  # noqa: BLE001 — linha corrompida não derruba a aba
                continue
            if aluno is None:
                continue
            chave = (ra_util(aluno.ficha.get("ra")) or normalizar_nome(aluno.nome))
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
            chave = ("ra", ra) if ra else ("nome", normalizar_nome(aluno.nome))
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
            if v.strip().isdigit():
                sed = v.strip()
    nome_turma, serie = _canonizar_turma(nome or nome_aba)
    return TurmaMatriculas(nome=nome_turma, ano_escolar=serie,
                           turno=turno, professor=professor, sed=sed)


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
    if numero.isdigit():
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
