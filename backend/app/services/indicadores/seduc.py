"""Parsers dos arquivos ABERTOS da SEDUC-SP: SARESP e Índice de Excelência
Educacional (IEE) — etapa E4 dos indicadores oficiais.

Três parsers (funções PURAS: bytes → linhas canônicas + avisos, sem banco):

* ``seduc_iee`` — o IEE por escola da REDE MUNICIPAL (edições 2024-25 e 2025-26):
  proficiência do SARESP em LP e MT do 2º e do 5º ano, participação do 2º e do
  5º ano, TPS, nota do IEE, meta e cumprimento da meta (ICM). Traz o CIE
  (``CODIGO_ESCOLA``) E o INEP (``CODIGO_INEP``) — é a PONTE CIE↔INEP. O recorte
  da rede é pelo INEP das escolas do cadastro (``recortar_iee``), nunca pelo nome;
* ``seduc_saresp_municipio`` — proficiência média por município × rede (estadual
  ou municipal) × série × período × componente. Recorta pelo ``CODMUN`` da SEDUC
  (que NÃO é o IBGE; Caraguatatuba = 254), gravado na rede — nunca adivinhado;
* ``seduc_saresp_instancia`` — o mesmo por instância; aqui só a linha ESTADO
  (rede estadual e redes municipais de SP, cada uma na sua rede de ensino).

FORA desta etapa: ``seduc_saresp_escola`` (proficiência do SARESP por escola,
arquivo não autorizado para download). Quando entrar, ele vem AQUI, com o mesmo
leitor de CSV (``ler_csv``), e casa o ``CODESC`` (CIE) com o INEP pela ponte do IEE
(``ponte_do_iee``/``pipeline_seduc.ponte_cie_inep``) ou pela regra "35" + CIE com 6
dígitos (``inep_derivado``), marcada como DERIVADA e aceita só se o INEP derivado
existir no cadastro. Por ora, o arquivo é reconhecido e RECUSADO com essa explicação.

Layouts reais (conferidos nos arquivos públicos, 2022–2025) — o leitor é robusto a
TODOS eles, pelo NOME da coluna, nunca pela posição:

* encoding UTF-8 com BOM, UTF-8 sem BOM ou ISO-8859-1 (varia por ano);
* separador ``;``; decimal com VÍRGULA ou PONTO (varia por ano);
* caixa do cabeçalho variável (``MEDPROF``/``medprof``, ``DepBol``/``DEPBOL``);
  acento e "º" no nome (``PROFICIENCIA_LINGUA_PORTUGUESA_2ºEF_2025``);
* "NULL", vazio ou "-" = AUSENTE (nunca zero).

O ano do SARESP: no IEE vem no NOME das colunas (``IEE_ESCOLA_2025`` — o IEE
2025-26 é calculado com o SARESP 2025); nos arquivos por município/instância só
no nome do arquivo ("... de 2025_0.csv") — ou informado por quem importa. Faltou
ou divergiu: recusa (não se adivinha a edição).

Só os indicadores EDUCACIONAIS entram. Colunas como ``VALOR`` (o prêmio em reais),
``TOTAL_ALUNOS`` (matrícula) e ``ICM PELO IQ`` (critério de premiação) são
ignoradas e listadas no aviso. Séries fora dos anos iniciais (9º ano, EM),
Ciências (2022; decisão D14 pendente) e os turnos (só o período GERAL) também.
"""
from __future__ import annotations

import codecs
import csv
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from app.services.avaliacoes import ImportacaoRecusada, normalizar_inep
from app.services.indicadores.ica import LinhaCanonica

PARSER_IEE = "seduc_iee"
PARSER_SARESP_MUNICIPIO = "seduc_saresp_municipio"
PARSER_SARESP_INSTANCIA = "seduc_saresp_instancia"
PARSER_SARESP_ESCOLA = "seduc_saresp_escola"     # FORA da E4 (ver o topo)
PARSERS = (PARSER_IEE, PARSER_SARESP_MUNICIPIO, PARSER_SARESP_INSTANCIA)
VERSAO_PARSER = "1"

CODIGO_UF_SP = "35"
UNIDADE_SARESP = "escala_saresp"
# Faixa de sanidade da escala do SARESP (média de escola/município). Fora dela o
# arquivo não confere com o layout oficial: recusa (nunca grava número estranho).
ESCALA_SARESP_MAXIMO = 500.0

# Etapas e componentes gravados. Em `indicadores_referencia` o componente segue o
# vocabulário do plano ("lp"/"mt"); em `resultados_avaliacao`, o que a tabela já
# usa (o SAEB e as médias de 26/07 gravam "portugues"/"matematica").
ETAPAS = ("2_ano", "5_ano")
COMPONENTE_REFERENCIA = {"LP": "lp", "MT": "mt"}
COMPONENTE_ESCOLA = {"LP": "portugues", "MT": "matematica"}

# Indicadores gravados.
IND_PROFICIENCIA = "proficiencia"       # SARESP (escola em resultados_avaliacao)
IND_PARTICIPACAO = "participacao"       # SARESP, por escola e etapa (percentual)
IND_TPS = "tps"                         # SARESP: critério mínimo de participação (1/0)
IND_IEE = "iee"                         # IEE: nota da escola
IND_META = "meta"                       # IEE: meta da escola
IND_ICM = "icm"                         # IEE: cumprimento da meta (1/0)

AVALIACAO_SARESP = "saresp"
AVALIACAO_IEE = "iee"

_MAX_LINHAS = 200_000       # o maior arquivo real (por município, 2022) tem ~17 mil
_VAZIOS = {"", "NULL", "-", "--", "—", "–", "N/A", "NA", "ND", "N/D", "*", "...", "…"}
_ORDINAIS = str.maketrans({"º": "", "ª": "", "°": ""})

# Colunas do IEE que NÃO são indicador educacional (ignoradas, com aviso).
_IEE_NAO_EDUCACIONAIS = {"VALOR", "TOTAL_ALUNOS", "ICM_PELO_IQ"}
_IEE_IDENTIFICACAO = {"REDE_DE_ENSINO", "DIRETORIA", "MUNICIPIO", "CODIGO_ESCOLA",
                      "CODIGO_INEP", "NOME_ESCOLA"}

_ARQUIVO_IEE = ('o arquivo oficial da SEDUC "Índice de Excelência Educacional" '
                "(Indice de Excelencia Educacional AAAA-AAAA.csv)")
_ARQUIVO_MUNICIPIO = ('o arquivo oficial da SEDUC "Proficiência do SARESP por município" '
                      "(... por Municipio de AAAA.csv)")
_ARQUIVO_INSTANCIA = ('o arquivo oficial da SEDUC "Proficiência do SARESP por instância" '
                      "(... por instância de AAAA.csv)")


# --- Leitura do CSV -----------------------------------------------------------

def sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def normalizar_coluna(bruto: str) -> str:
    """Nome de coluna comparável: sem "º"/"ª", sem acento, MAIÚSCULO, e tudo que não
    é letra/dígito vira "_" (" VALOR " → "VALOR"; "ICM Pelo IQ" → "ICM_PELO_IQ";
    "INDICE_CUMPRIMENTO_META_IEE_2025(ICM)" → "INDICE_CUMPRIMENTO_META_IEE_2025_ICM")."""
    texto = sem_acento(str(bruto or "").translate(_ORDINAIS)).upper()
    return re.sub(r"[^A-Z0-9]+", "_", texto).strip("_")


def normalizar_texto(bruto) -> str:
    """Valor categórico comparável ('MANHÃ' → 'MANHA'; 'Rede Municipal' → 'REDE MUNICIPAL')."""
    return " ".join(sem_acento(str(bruto or "").translate(_ORDINAIS)).upper().split())


def decodificar(conteudo: bytes) -> tuple[str, str]:
    """``(texto, encoding)``: UTF-8 com BOM, UTF-8 sem BOM ou ISO-8859-1 (nessa
    ordem — o ISO-8859-1 aceita qualquer byte, então só entra se o UTF-8 falhar)."""
    if conteudo.startswith(codecs.BOM_UTF8):
        try:
            return conteudo[len(codecs.BOM_UTF8):].decode("utf-8"), "utf-8-sig"
        except UnicodeDecodeError as exc:
            raise ImportacaoRecusada(
                "O arquivo começa com a marca de UTF-8, mas tem bytes que não são UTF-8 "
                "(arquivo corrompido). Nada foi gravado.") from exc
    try:
        return conteudo.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return conteudo.decode("iso-8859-1"), "iso-8859-1"


@dataclass
class TabelaCSV:
    """O CSV lido: cabeçalho normalizado (nome → índice), linhas e o que foi detectado."""

    colunas: dict[str, int]
    originais: list[str]
    linhas: list[list[str]]
    encoding: str
    separador: str


def ler_csv(conteudo: bytes, nome: str) -> TabelaCSV:
    """Lê o CSV inteiro (são poucos MB): detecta encoding e separador, normaliza o
    cabeçalho e recusa coluna repetida. LEVANTA ``ImportacaoRecusada``."""
    if conteudo.startswith(b"PK"):
        raise ImportacaoRecusada(
            f"O arquivo “{nome or 'sem nome'}” é um ZIP/XLSX; os arquivos da SEDUC são CSV "
            "(separados por ponto e vírgula). Suba o .csv como baixado. Nada foi gravado.")
    if b"\x00" in conteudo[:4096]:
        raise ImportacaoRecusada("O arquivo não é texto (CSV). Nada foi gravado.")
    texto, encoding = decodificar(conteudo)
    primeira = next((ln for ln in texto.splitlines() if ln.strip()), "")
    separador = max((";", "\t", ","), key=primeira.count)
    if not primeira.count(separador):
        raise ImportacaoRecusada(
            "Não reconheci o cabeçalho do CSV (sem separador). Confira se é um arquivo "
            "da SEDUC como baixado. Nada foi gravado.")
    leitor = csv.reader(io.StringIO(texto, newline=""), delimiter=separador)
    cabecalho: list[str] | None = None
    linhas: list[list[str]] = []
    for linha in leitor:
        if not any(c.strip() for c in linha):
            continue
        if cabecalho is None:
            cabecalho = linha
            continue
        if len(linhas) >= _MAX_LINHAS:
            raise ImportacaoRecusada(
                f"O arquivo tem mais de {_MAX_LINHAS} linhas — muito maior que os "
                "arquivos oficiais da SEDUC. Nada foi gravado.")
        linhas.append(linha)
    if cabecalho is None:
        raise ImportacaoRecusada("O arquivo está vazio. Nada foi gravado.")
    colunas: dict[str, int] = {}
    repetidas = []
    for j, bruto in enumerate(cabecalho):
        nome_col = normalizar_coluna(bruto)
        if not nome_col:
            continue
        if nome_col in colunas:
            repetidas.append(bruto.strip())
        colunas[nome_col] = j
    if repetidas:
        raise ImportacaoRecusada(
            f"A coluna {', '.join(sorted(set(repetidas)))} aparece mais de uma vez no "
            "arquivo. Nada foi gravado.")
    return TabelaCSV(colunas=colunas, originais=[c.strip() for c in cabecalho],
                     linhas=linhas, encoding=encoding, separador=separador)


def _cel(linha: list[str], j: int | None) -> str:
    if j is None or j >= len(linha):
        return ""
    return linha[j].strip()


def ler_numero(bruto: str) -> tuple[float | None, int, bool]:
    """``(valor, casas escritas, reconhecido)``. "NULL"/vazio/"-" → (None, 0, True).
    Decimal com VÍRGULA ("87,3") ou PONTO ("176.4"); com os dois, o ponto é milhar
    ("1.234,5"). Texto que não é número → (None, 0, False)."""
    s = (bruto or "").strip().replace(" ", "")
    if s.upper() in _VAZIOS:
        return None, 0, True
    s = s.replace("%", "").strip()
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", s):
        return None, 0, False
    casas = len(s.split(".", 1)[1]) if "." in s else 0
    return float(s), casas, True


# --- Estruturas de saída ------------------------------------------------------

@dataclass(frozen=True)
class NumeroReferencia:
    """Um número (ou ausência) para `indicadores_referencia`, com a avaliação."""

    avaliacao: str              # saresp | iee
    linha: LinhaCanonica


@dataclass(frozen=True)
class LinhaEscola:
    """Um resultado oficial por ESCOLA para `resultados_avaliacao`."""

    avaliacao: str              # saresp
    edicao: int
    indicador: str
    escola_id: int
    rede_id: int | None
    codigo_inep: str
    etapa: str
    componente: str | None      # None no Ideb (sem componente)
    unidade: str
    valor: float | None
    motivo_ausencia: str | None = None

    @property
    def chave(self) -> tuple:
        """Chave natural (a do ``uq_resultado_natural``: dimensão nula = '' — o Ideb
        não tem componente; nenhuma linha tem turma)."""
        return (self.edicao, self.indicador, self.escola_id, self.etapa or "",
                self.componente or "", "")


@dataclass(frozen=True)
class EscolaIEE:
    """Uma linha do IEE (uma escola), já lida e validada — antes do recorte."""

    rede: str
    municipio: str
    cie: str
    inep: str
    inep_derivado: bool          # INEP vazio no arquivo → "35" + CIE (marcado)
    nome: str
    valores: dict                # chave interna → (valor | None, casas)


@dataclass
class LeituraSeduc:
    """O que o parser entendeu do arquivo (nada gravado)."""

    parser: str
    edicao_arquivo: int
    encoding: str
    referencia: list[NumeroReferencia] = field(default_factory=list)
    escolares: list[LinhaEscola] = field(default_factory=list)
    escolas_iee: list[EscolaIEE] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    territorios: dict[str, str] = field(default_factory=dict)
    colunas_ignoradas: list[str] = field(default_factory=list)
    linhas_lidas: int = 0
    # Do recorte do IEE (preenchidos por ``recortar_iee``).
    escolas_casadas: list[dict] = field(default_factory=list)
    fora_do_cadastro: list[dict] = field(default_factory=list)
    ponte: dict[str, str] = field(default_factory=dict)


# --- Identificação do arquivo -----------------------------------------------

def identificar(colunas: dict[str, int]) -> str:
    """O parser pela ASSINATURA do cabeçalho (nunca pelo nome do arquivo)."""
    nomes = set(colunas)
    if "CODIGO_INEP" in nomes and any(n.startswith("IEE_ESCOLA") for n in nomes):
        return PARSER_IEE
    if "MEDPROF" in nomes and "CODMUN" in nomes:
        return PARSER_SARESP_MUNICIPIO
    if "MEDPROF" in nomes and "REGIAOMETROPOLITANA" in nomes:
        return PARSER_SARESP_INSTANCIA
    if "MEDPROF" in nomes and nomes & {"CODESC", "CODIGO_ESCOLA", "NOMESC", "NOME_ESCOLA"}:
        raise ImportacaoRecusada(
            "Este é o arquivo da proficiência do SARESP POR ESCOLA. Ele ainda não entra "
            "no Constela (parser seduc_saresp_escola fora desta etapa): a proficiência "
            "oficial por escola das edições 2024-25 e 2025-26 vem do arquivo do Índice de "
            "Excelência Educacional (IEE), que também traz o código INEP. Nada foi gravado.")
    raise ImportacaoRecusada(
        "Não reconheci o arquivo. São aceitos, como baixados de dados.educacao.sp.gov.br: "
        f"{_ARQUIVO_IEE}, {_ARQUIVO_MUNICIPIO} e {_ARQUIVO_INSTANCIA}. Nada foi gravado.")


def _anos_no_nome(nome: str) -> list[int]:
    return sorted({int(a) for a in re.findall(r"(?<!\d)(20\d{2})(?!\d)", nome or "")})


def _edicao(*, da_coluna: int | None, nome: str, informada: int | None, arquivo: str,
            par_no_nome: bool = False) -> int:
    """A edição do SARESP: a da coluna, senão a do nome do arquivo (o 1º ano de
    "2024-2025" no IEE; o único ano no SARESP), senão a informada. A informada que
    DIVERGE da coluna/do nome é recusada — nunca se escolhe uma em silêncio. A faixa
    de sanidade (2007 a 2100) vale para a edição FINAL, informada ou lida (uma edição
    digitada errada — "205" — não é gravada)."""
    anos = _anos_no_nome(nome)
    do_nome = None
    if par_no_nome and len(anos) == 2 and anos[1] == anos[0] + 1:
        do_nome = anos[0]
    elif len(anos) == 1:
        do_nome = anos[0]
    candidata = da_coluna if da_coluna is not None else do_nome
    if informada is not None and candidata is not None and candidata != informada:
        raise ImportacaoRecusada(
            f"A edição informada ({informada}) não confere com a do arquivo "
            f"({candidata}). Nada foi gravado.")
    edicao = informada if informada is not None else candidata
    if edicao is None:
        raise ImportacaoRecusada(
            f"Não consegui saber o ano do SARESP deste arquivo (nem no cabeçalho nem no "
            f"nome “{nome or 'sem nome'}”). Informe a edição na importação ou suba "
            f"{arquivo} com o nome como baixado. Nada foi gravado.")
    if not 2007 <= edicao <= 2100:
        raise ImportacaoRecusada(f"Edição {edicao} fora do esperado (de 2007 a 2100). Nada "
                                 "foi gravado.")
    return edicao


def _exigir(colunas: dict[str, int], exigidas: tuple[str, ...], arquivo: str) -> None:
    faltam = [c for c in exigidas if c not in colunas]
    if faltam:
        raise ImportacaoRecusada(
            f"O arquivo não tem a coluna {', '.join(faltam)}; confira se é {arquivo}. "
            "Nada foi gravado.")


def _casas_publicadas(linhas: list[list[str]], j: int) -> int:
    """Precisão PUBLICADA da coluna: o máximo de casas escritas entre os valores
    (o float perde o zero final; a precisão da coluna não)."""
    maximo = 0
    for linha in linhas:
        _, casas, _ = ler_numero(_cel(linha, j))
        maximo = max(maximo, casas)
        if maximo >= 4:
            break
    return min(maximo, 4)


# --- SARESP por município e por instância ------------------------------------

_RE_SERIE = re.compile(r"^(\d{1,2})\s*ANO\s*EF$")


def _etapa(bruto: str) -> str | None:
    """'2º Ano EF' → '2_ano'; 'EM-3ª série'/'9º Ano EF' → None (fora dos anos iniciais
    gravados)."""
    casou = _RE_SERIE.match(normalizar_texto(bruto))
    etapa = f"{int(casou.group(1))}_ano" if casou else None
    return etapa if etapa in ETAPAS else None


def _componente(co_comp: str, ds_comp: str, rotulo: str) -> str | None:
    """'LP' | 'MT' | None (Ciências e outros). Código e descrição têm de concordar."""
    por_codigo = {"1": "LP", "2": "MT", "3": "CIE"}.get(co_comp.strip())
    texto = normalizar_texto(ds_comp)
    por_texto = ("LP" if "PORTUGUESA" in texto else "MT" if "MATEMATICA" in texto
                 else "CIE" if "CIENCIAS" in texto else None)
    if por_codigo and por_texto and por_codigo != por_texto:
        raise ImportacaoRecusada(
            f"{rotulo}: o código do componente ({co_comp}) não confere com a descrição "
            f"(“{ds_comp}”). O arquivo não confere com o layout oficial; nada foi gravado.")
    comp = por_codigo or por_texto
    return comp if comp in ("LP", "MT") else None


def _rede_ensino(depadm: str, nome_rede: str, rotulo: str) -> str | None:
    """DEPADM 1 = estadual, 2 = municipal (conferido com NOMEDEPBOL quando houver)."""
    por_codigo = {"1": "estadual", "2": "municipal"}.get(depadm.strip())
    texto = normalizar_texto(nome_rede)
    por_texto = ("estadual" if "ESTADUAL" in texto else "municipal" if "MUNICIPAL" in texto
                 else None)
    if por_codigo and por_texto and por_codigo != por_texto:
        raise ImportacaoRecusada(
            f"{rotulo}: DEPADM {depadm} não confere com “{nome_rede}”. O arquivo não "
            "confere com o layout oficial; nada foi gravado.")
    return por_codigo or (por_texto if not depadm.strip() else None)


def _periodo_geral(periodo: str, cod_per: str, rotulo: str) -> bool:
    """Só o período GERAL (todos os turnos). O código 9 e o texto têm de concordar."""
    geral_texto = normalizar_texto(periodo) == "GERAL"
    if cod_per.strip():
        geral_codigo = cod_per.strip() == "9"
        if geral_codigo != geral_texto:
            raise ImportacaoRecusada(
                f"{rotulo}: período “{periodo}” com código {cod_per}. O arquivo não "
                "confere com o layout oficial; nada foi gravado.")
    return geral_texto


@dataclass
class _Contagem:
    turnos: int = 0
    series_fora: int = 0
    componentes_fora: int = 0
    redes_fora: int = 0


def _avisos_de_contagem(contagem: _Contagem) -> list[str]:
    avisos = []
    if contagem.turnos:
        avisos.append(f"{contagem.turnos} linha(s) de turno (manhã/tarde/noite) ignoradas: "
                      "só entra o período GERAL.")
    if contagem.series_fora:
        avisos.append(f"{contagem.series_fora} linha(s) de outras séries (9º ano, Ensino "
                      "Médio) ignoradas: só entram o 2º e o 5º ano.")
    if contagem.componentes_fora:
        avisos.append(f"{contagem.componentes_fora} linha(s) de Ciências ignoradas: só LP e "
                      "Matemática (decisão D14 pendente).")
    if contagem.redes_fora:
        avisos.append(f"{contagem.redes_fora} linha(s) de outra dependência administrativa "
                      "ignoradas: só rede estadual e municipal.")
    return avisos


def _linhas_saresp(tabela: TabelaCSV, filtro, *, edicao: int, abrangencia: str,
                   codigo_territorio: str, rotulo_base: str) -> tuple[list, _Contagem]:
    """Linhas canônicas de proficiência (rede × série × componente, período GERAL)
    das linhas do arquivo que passam no ``filtro``."""
    c = tabela.colunas
    j_med = c["MEDPROF"]
    casas_col = _casas_publicadas(tabela.linhas, j_med)
    contagem = _Contagem()
    saida: dict[tuple, NumeroReferencia] = {}
    for linha in tabela.linhas:
        if not filtro(linha):
            continue
        rotulo = f"{rotulo_base} · {_cel(linha, c['SERIE_ANO'])} · {_cel(linha, c['DS_COMP'])}"
        if not _periodo_geral(_cel(linha, c["PERIODO"]), _cel(linha, c.get("COD_PER")), rotulo):
            contagem.turnos += 1
            continue
        rede = _rede_ensino(_cel(linha, c["DEPADM"]), _cel(linha, c.get("NOMEDEPBOL")), rotulo)
        if rede is None:
            contagem.redes_fora += 1
            continue
        etapa = _etapa(_cel(linha, c["SERIE_ANO"]))
        if etapa is None:
            contagem.series_fora += 1
            continue
        comp = _componente(_cel(linha, c["CO_COMP"]), _cel(linha, c["DS_COMP"]), rotulo)
        if comp is None:
            contagem.componentes_fora += 1
            continue
        bruto = _cel(linha, j_med)
        valor, casas, ok = ler_numero(bruto)
        if not ok:
            raise ImportacaoRecusada(
                f"{rotulo}: MEDPROF “{bruto}” não é número. O arquivo não confere com o "
                "layout oficial; nada foi gravado.")
        if valor is not None and not 0 < valor <= ESCALA_SARESP_MAXIMO:
            raise ImportacaoRecusada(
                f"{rotulo}: MEDPROF = {valor} fora da escala do SARESP. Nada foi gravado.")
        base = dict(indicador=IND_PROFICIENCIA, edicao=edicao, abrangencia=abrangencia,
                    codigo_territorio=codigo_territorio, rede_ensino=rede,
                    unidade=UNIDADE_SARESP, etapa=etapa,
                    componente=COMPONENTE_REFERENCIA[comp], desenho="censitario")
        if valor is None:
            ln = LinhaCanonica(valor=None, motivo_ausencia="nao_divulgado", **base)
        else:
            ln = LinhaCanonica(valor=round(valor, 4), casas_decimais=max(casas, casas_col),
                               **base)
        if ln.chave in saida:
            raise ImportacaoRecusada(
                f"{rotulo}: a mesma rede, série e componente aparece duas vezes no período "
                "GERAL; não dá para saber qual linha vale. Nada foi gravado.")
        saida[ln.chave] = NumeroReferencia(AVALIACAO_SARESP, ln)
    return list(saida.values()), contagem


def ler_saresp_municipio(tabela: TabelaCSV, nome: str, *, codmun: str, codigo_ibge: str,
                         edicao_informada: int | None = None) -> LeituraSeduc:
    """Recorta o município pelo ``CODMUN`` da SEDUC (gravado na rede) e grava as
    linhas sob o IBGE da rede (``codigo_territorio``). Rede municipal E rede estadual
    no município, cada uma com a sua rede de ensino."""
    exigidas = ("DEPADM", "CODMUN", "MUN", "SERIE_ANO", "PERIODO", "CO_COMP", "DS_COMP",
                "MEDPROF")
    _exigir(tabela.colunas, exigidas, _ARQUIVO_MUNICIPIO)
    edicao = _edicao(da_coluna=None, nome=nome, informada=edicao_informada,
                     arquivo=_ARQUIVO_MUNICIPIO)
    codmun = (codmun or "").strip().lstrip("0") or "0"
    c = tabela.colunas
    leitura = LeituraSeduc(parser=PARSER_SARESP_MUNICIPIO, edicao_arquivo=edicao,
                           encoding=tabela.encoding, linhas_lidas=len(tabela.linhas))

    def _do_municipio(linha) -> bool:
        return (_cel(linha, c["CODMUN"]).lstrip("0") or "0") == codmun

    nomes = {_cel(ln, c["MUN"]) for ln in tabela.linhas if _do_municipio(ln)}
    if not nomes:
        leitura.avisos.append(
            f"O CODMUN {codmun} não está no arquivo: nada a importar. Confira o código do "
            "município na SEDUC cadastrado na rede (não é o IBGE).")
        return leitura
    if len(nomes) > 1:
        raise ImportacaoRecusada(
            f"O CODMUN {codmun} aparece com mais de um nome no arquivo "
            f"({', '.join(sorted(nomes))}). Nada foi gravado.")
    nome_mun = next(iter(nomes))
    leitura.territorios[codigo_ibge] = nome_mun
    leitura.referencia, contagem = _linhas_saresp(
        tabela, _do_municipio, edicao=edicao, abrangencia="municipio",
        codigo_territorio=codigo_ibge, rotulo_base=f"{nome_mun} (CODMUN {codmun})")
    leitura.avisos.append(
        f"No arquivo, o CODMUN {codmun} é “{nome_mun}”: confira se é o município da rede "
        f"(IBGE {codigo_ibge}).")
    leitura.avisos.extend(_avisos_de_contagem(contagem))
    return leitura


def ler_saresp_instancia(tabela: TabelaCSV, nome: str, *, codigo_uf: str = CODIGO_UF_SP,
                         edicao_informada: int | None = None) -> LeituraSeduc:
    """Só a instância ESTADO (as regiões metropolitanas e o "Interior" ficam de
    fora), nas duas redes de ensino que o arquivo traz."""
    exigidas = ("DEPADM", "REGIAOMETROPOLITANA", "SERIE_ANO", "PERIODO", "CO_COMP",
                "DS_COMP", "MEDPROF")
    _exigir(tabela.colunas, exigidas, _ARQUIVO_INSTANCIA)
    if codigo_uf != CODIGO_UF_SP:
        raise ImportacaoRecusada("O SARESP é de São Paulo: a rede não é de SP (UF 35). "
                                 "Nada foi gravado.")
    edicao = _edicao(da_coluna=None, nome=nome, informada=edicao_informada,
                     arquivo=_ARQUIVO_INSTANCIA)
    c = tabela.colunas
    leitura = LeituraSeduc(parser=PARSER_SARESP_INSTANCIA, edicao_arquivo=edicao,
                           encoding=tabela.encoding, linhas_lidas=len(tabela.linhas))

    def _estado(linha) -> bool:
        return normalizar_texto(_cel(linha, c["REGIAOMETROPOLITANA"])) == "ESTADO"

    if not any(_estado(ln) for ln in tabela.linhas):
        leitura.avisos.append("O arquivo não tem a instância ESTADO: nada a importar.")
        return leitura
    leitura.territorios[codigo_uf] = "Estado de São Paulo"
    leitura.referencia, contagem = _linhas_saresp(
        tabela, _estado, edicao=edicao, abrangencia="uf", codigo_territorio=codigo_uf,
        rotulo_base="Estado de São Paulo")
    leitura.avisos.append("Só a instância ESTADO entra (regiões metropolitanas e Interior "
                          "ficam de fora).")
    leitura.avisos.extend(_avisos_de_contagem(contagem))
    return leitura


# --- IEE ----------------------------------------------------------------------

_RE_PROF = re.compile(r"^PROFICIENCIA_(LINGUA_PORTUGUESA|MATEMATICA)_([25])_?EF(?:_(\d{4}))?$")
_RE_PART = re.compile(r"^TAXA_PAR(?:TI)?CIPACAO_([25])_ANO$")     # o arquivo grafa "PARCIPACAO"
_RE_IEE = re.compile(r"^IEE_ESCOLA(?:_(\d{4}))?$")
_RE_META = re.compile(r"^META_IEE(?:_(\d{4}))?$")
_RE_ICM = re.compile(r"^INDICE_CUMPRIMENTO_META_IEE(?:_(\d{4}))?(?:_ICM)?$")


def inep_derivado(cie: str) -> str | None:
    """Regra "35" + CIE com 6 dígitos (escolas de SP). É DERIVADA: só vale marcada
    e quando o INEP existe no cadastro (nunca cria vínculo sozinha)."""
    digitos = "".join(ch for ch in (cie or "") if ch.isdigit()).lstrip("0")
    if not digitos or len(digitos) > 6:
        return None
    return CODIGO_UF_SP + digitos.zfill(6)


def _mapear_iee(colunas: dict[str, int]) -> tuple[dict[str, int], int | None, list[str]]:
    """Índices das colunas do IEE (chave interna → índice), o ano que elas trazem e
    as colunas ignoradas. Recusa se faltar uma exigida ou se os anos divergirem."""
    mapa: dict[str, int] = {}
    anos: set[int] = set()
    for nome_col, j in colunas.items():
        if (m := _RE_PROF.match(nome_col)):
            comp = "LP" if m.group(1) == "LINGUA_PORTUGUESA" else "MT"
            mapa[f"prof_{comp}_{m.group(2)}"] = j
            if m.group(3):
                anos.add(int(m.group(3)))
        elif (m := _RE_PART.match(nome_col)):
            mapa[f"part_{m.group(1)}"] = j
        elif nome_col == "TPS":
            mapa["tps"] = j
        elif (m := _RE_IEE.match(nome_col)):
            mapa["iee"] = j
            if m.group(1):
                anos.add(int(m.group(1)))
        elif (m := _RE_META.match(nome_col)):
            mapa["meta"] = j
            if m.group(1):
                anos.add(int(m.group(1)))
        elif (m := _RE_ICM.match(nome_col)):
            mapa["icm"] = j
            if m.group(1):
                anos.add(int(m.group(1)))
    exigidas = {
        "prof_LP_2": "PROFICIENCIA_LINGUA_PORTUGUESA_2ºEF", "prof_MT_2": "PROFICIENCIA_MATEMATICA_2ºEF",
        "prof_LP_5": "PROFICIENCIA_LINGUA_PORTUGUESA_5ºEF", "prof_MT_5": "PROFICIENCIA_MATEMATICA_5ºEF",
        "part_2": "TAXA_PARCIPACAO_2_ANO", "part_5": "TAXA_PARCIPACAO_5_ANO", "tps": "TPS",
        "iee": "IEE_ESCOLA", "meta": "META_IEE", "icm": "INDICE_CUMPRIMENTO_META_IEE (ICM)",
    }
    faltam = [rotulo for chave, rotulo in exigidas.items() if chave not in mapa]
    faltam += [c for c in ("REDE_DE_ENSINO", "MUNICIPIO", "CODIGO_ESCOLA", "CODIGO_INEP")
               if c not in colunas]
    if faltam:
        raise ImportacaoRecusada(
            f"O arquivo não tem a coluna {', '.join(faltam)}; confira se é {_ARQUIVO_IEE}. "
            "Nada foi gravado.")
    if len(anos) > 1:
        raise ImportacaoRecusada(
            f"As colunas do IEE trazem anos diferentes ({', '.join(map(str, sorted(anos)))}); "
            f"confira se é {_ARQUIVO_IEE}. Nada foi gravado.")
    usados = set(mapa.values()) | {colunas[c] for c in _IEE_IDENTIFICACAO if c in colunas}
    ignoradas = [n for n, j in colunas.items() if j not in usados]
    return mapa, (next(iter(anos)) if anos else None), ignoradas


def _validar_iee(chave: str, valor: float, rotulo: str) -> None:
    if chave.startswith("prof_"):
        ok, faixa = 0 < valor <= ESCALA_SARESP_MAXIMO, "da escala do SARESP"
    elif chave.startswith("part_"):
        ok, faixa = 0 <= valor <= 100, "de 0 a 100%"
    elif chave in ("tps", "icm"):
        ok, faixa = valor in (0.0, 1.0), "(só 0 ou 1)"
    else:                                   # iee, meta
        ok, faixa = 0 <= valor <= 10, "de 0 a 10"
    if not ok:
        raise ImportacaoRecusada(
            f"{rotulo}: {chave} = {valor} fora da faixa {faixa}. O arquivo não confere com "
            "o layout oficial; nada foi gravado.")


def ler_iee(tabela: TabelaCSV, nome: str, *, edicao_informada: int | None = None) -> LeituraSeduc:
    """Lê TODAS as escolas MUNICIPAIS do arquivo (o recorte da rede é depois, pelo
    INEP do cadastro — ``recortar_iee``). Nenhum número é gravado aqui."""
    mapa, ano_colunas, ignoradas = _mapear_iee(tabela.colunas)
    edicao = _edicao(da_coluna=ano_colunas, nome=nome, informada=edicao_informada,
                     arquivo=_ARQUIVO_IEE, par_no_nome=True)
    c = tabela.colunas
    leitura = LeituraSeduc(parser=PARSER_IEE, edicao_arquivo=edicao, encoding=tabela.encoding,
                           linhas_lidas=len(tabela.linhas))
    leitura.colunas_ignoradas = sorted(tabela.originais[j] for j in
                                       (tabela.colunas[n] for n in ignoradas))
    if leitura.colunas_ignoradas:
        leitura.avisos.append(
            "Colunas ignoradas (não são indicador educacional): "
            f"{', '.join(leitura.colunas_ignoradas)}.")
    casas_col = {chave: _casas_publicadas(tabela.linhas, j) for chave, j in mapa.items()}
    outras_redes = 0
    divergentes = []
    for linha in tabela.linhas:
        rede = normalizar_texto(_cel(linha, c["REDE_DE_ENSINO"]))
        if rede != "MUNICIPAL":
            outras_redes += 1
            continue
        cie = "".join(ch for ch in _cel(linha, c["CODIGO_ESCOLA"]) if ch.isdigit())
        bruto_inep = _cel(linha, c["CODIGO_INEP"])
        inep = normalizar_inep(bruto_inep) if bruto_inep.upper() not in _VAZIOS else None
        derivado = False
        if inep is None:
            inep, derivado = inep_derivado(cie), True
        if inep is None:
            leitura.avisos.append(f"Linha sem código INEP nem CIE válido ignorada "
                                  f"(“{_cel(linha, c.get('NOME_ESCOLA'))}”).")
            continue
        if not derivado and cie and inep_derivado(cie) != inep:
            divergentes.append(f"CIE {cie} → INEP {inep}")
        rotulo = f"Escola INEP {inep}"
        valores = {}
        for chave, j in mapa.items():
            bruto = _cel(linha, j)
            valor, casas, ok = ler_numero(bruto)
            if not ok:
                raise ImportacaoRecusada(
                    f"{rotulo}: “{bruto}” não é número ({tabela.originais[j]}). O arquivo não "
                    "confere com o layout oficial; nada foi gravado.")
            if valor is not None:
                _validar_iee(chave, valor, rotulo)
            valores[chave] = (valor, max(casas, casas_col[chave]))
        leitura.escolas_iee.append(EscolaIEE(
            rede="municipal", municipio=normalizar_texto(_cel(linha, c["MUNICIPIO"])),
            cie=cie, inep=inep, inep_derivado=derivado,
            nome=_cel(linha, c.get("NOME_ESCOLA")), valores=valores))
    contagem = Counter(e.inep for e in leitura.escolas_iee)
    repetidos = sorted(inep for inep, n in contagem.items() if n > 1)
    if repetidos:
        raise ImportacaoRecusada(
            f"O código INEP {', '.join(repetidos[:10])} aparece em mais de uma linha do "
            "arquivo; não dá para saber qual vale. Nada foi gravado.")
    if outras_redes:
        leitura.avisos.append(f"{outras_redes} linha(s) de rede não municipal ignoradas "
                              "(o IEE é da rede municipal).")
    if divergentes:
        leitura.avisos.append(
            "INEP do arquivo diferente da regra “35” + CIE (vale o INEP do arquivo): "
            + "; ".join(divergentes[:10]) + ".")
    return leitura


def ponte_do_iee(leitura: LeituraSeduc) -> dict[str, str]:
    """CIE → INEP de TODAS as escolas do arquivo com os dois códigos (não derivados)
    — a ponte que o ``seduc_saresp_escola`` (CIE só) vai usar."""
    return {e.cie: e.inep for e in leitura.escolas_iee if e.cie and not e.inep_derivado}


def recortar_iee(leitura: LeituraSeduc, escolas_por_inep: dict[str, dict], *,
                 codigo_ibge: str) -> LeituraSeduc:
    """Recorta a REDE pelo INEP das escolas do cadastro (``{inep: {"id", "rede_id",
    "nome"}}``) — nunca pelo nome da escola nem do município — e produz as linhas:

    * ``resultados_avaliacao`` (SARESP, por escola): proficiência de LP e MT do 2º e
      do 5º ano, cada série na SUA etapa (``2_ano``/``5_ano``); vazio = ausência
      ``nao_divulgado`` (nunca zero, nunca imputado);
    * ``indicadores_referencia`` (abrangência escola, IBGE da rede): participação
      do 2º e do 5º ano e TPS (SARESP); nota, meta e ICM (IEE).

    INEP DERIVADO (o arquivo sem INEP) só casa se existir no cadastro, e vai
    marcado no aviso. O nome do município das escolas casadas só AGRUPA a lista
    informativa "do município, fora do cadastro" (nunca casa nada)."""
    casadas: list[tuple[EscolaIEE, dict]] = []
    for e in leitura.escolas_iee:
        alvo = escolas_por_inep.get(e.inep)
        if alvo is not None:
            casadas.append((e, alvo))
    municipios = {e.municipio for e, _ in casadas}
    # A ponte guardada é a do MUNICÍPIO da rede (casadas + fora do cadastro), não a
    # do estado inteiro: é ela que o `seduc_saresp_escola` vai usar para esta rede.
    cies_do_municipio = {e.cie for e in leitura.escolas_iee if e.municipio in municipios}
    leitura.ponte = {cie: inep for cie, inep in ponte_do_iee(leitura).items()
                     if cie in cies_do_municipio}
    if len(municipios) > 1:
        leitura.avisos.append(
            "As escolas da rede casadas pelo INEP estão em municípios diferentes no arquivo "
            f"({', '.join(sorted(municipios))}): confira o código INEP no cadastro.")
    casados = {e.inep for e, _ in casadas}
    leitura.fora_do_cadastro = sorted(
        ({"cie": e.cie, "codigo_inep": e.inep, "nome_no_arquivo": e.nome,
          "municipio": e.municipio}
         for e in leitura.escolas_iee if e.municipio in municipios and e.inep not in casados),
        key=lambda d: d["codigo_inep"])
    derivados = [e.inep for e, _ in casadas if e.inep_derivado]
    if derivados:
        leitura.avisos.append(
            "Casadas pelo INEP DERIVADO (“35” + CIE; o arquivo não trazia o INEP): "
            f"{', '.join(derivados)}.")
    if not casadas:
        leitura.avisos.append(
            "Nenhuma escola da rede casou pelo código INEP: confira o INEP no cadastro "
            "das escolas. Nada a importar.")
    if leitura.fora_do_cadastro:
        leitura.avisos.append(
            f"{len(leitura.fora_do_cadastro)} escola(s) do mesmo município no arquivo sem "
            "escola no cadastro do Constela com esse INEP (não importadas): "
            + ", ".join(f"INEP {d['codigo_inep']} (CIE {d['cie']})"
                        for d in leitura.fora_do_cadastro[:10]) + ".")
    edicao = leitura.edicao_arquivo
    escolares: list[LinhaEscola] = []
    referencia: list[NumeroReferencia] = []
    for e, alvo in sorted(casadas, key=lambda par: par[0].inep):
        for serie in ("2", "5"):
            etapa = f"{serie}_ano"
            for comp in ("LP", "MT"):
                valor, _ = e.valores[f"prof_{comp}_{serie}"]
                escolares.append(LinhaEscola(
                    avaliacao=AVALIACAO_SARESP, edicao=edicao, indicador=IND_PROFICIENCIA,
                    escola_id=alvo["id"], rede_id=alvo.get("rede_id"), codigo_inep=e.inep,
                    etapa=etapa, componente=COMPONENTE_ESCOLA[comp], unidade=UNIDADE_SARESP,
                    valor=None if valor is None else round(valor, 4),
                    motivo_ausencia="nao_divulgado" if valor is None else None))
            referencia.append(_ref_escola(AVALIACAO_SARESP, IND_PARTICIPACAO, e,
                                          f"part_{serie}", edicao, codigo_ibge,
                                          unidade="percentual", etapa=etapa))
        referencia.append(_ref_escola(AVALIACAO_SARESP, IND_TPS, e, "tps", edicao, codigo_ibge,
                                      unidade="binario"))
        referencia.append(_ref_escola(AVALIACAO_IEE, IND_IEE, e, "iee", edicao, codigo_ibge,
                                      unidade="indice"))
        referencia.append(_ref_escola(AVALIACAO_IEE, IND_META, e, "meta", edicao, codigo_ibge,
                                      unidade="indice"))
        referencia.append(_ref_escola(AVALIACAO_IEE, IND_ICM, e, "icm", edicao, codigo_ibge,
                                      unidade="binario"))
    leitura.escolares = escolares
    leitura.referencia = referencia
    leitura.escolas_casadas = [
        {"escola_id": alvo["id"], "escola": alvo.get("nome"), "codigo_inep": e.inep,
         "cie": e.cie, "nome_no_arquivo": e.nome, "inep_derivado": e.inep_derivado}
        for e, alvo in sorted(casadas, key=lambda par: (par[1].get("nome") or "", par[0].inep))]
    leitura.territorios[codigo_ibge] = next(iter(municipios)) if len(municipios) == 1 else codigo_ibge
    tps_zero = [e.inep for e, _ in casadas if e.valores["tps"][0] == 0]
    if tps_zero:
        leitura.avisos.append(
            f"{len(tps_zero)} escola(s) com TPS = 0 (não atendeu ao critério mínimo de "
            "participação): a média dessas escolas é instável — "
            + ", ".join(f"INEP {i}" for i in tps_zero[:10]) + ".")
    return leitura


def _ref_escola(avaliacao: str, indicador: str, e: EscolaIEE, chave: str, edicao: int,
                codigo_ibge: str, *, unidade: str, etapa: str = "") -> NumeroReferencia:
    valor, casas = e.valores[chave]
    base = dict(indicador=indicador, edicao=edicao, abrangencia="escola",
                codigo_territorio=codigo_ibge, codigo_inep=e.inep, rede_ensino="municipal",
                unidade=unidade, etapa=etapa, componente="", desenho="censitario")
    if valor is None:
        return NumeroReferencia(avaliacao, LinhaCanonica(valor=None,
                                                         motivo_ausencia="nao_divulgado",
                                                         **base))
    return NumeroReferencia(avaliacao, LinhaCanonica(valor=round(valor, 4),
                                                     casas_decimais=casas, **base))


# --- Entrada única ------------------------------------------------------------

def ler_arquivo(conteudo: bytes, nome: str, *, codigo_ibge: str,
                codmun: str | None = None, edicao_informada: int | None = None) -> LeituraSeduc:
    """Identifica o arquivo pelo cabeçalho e o lê. No SARESP por município exige o
    CODMUN da rede; no IEE devolve as escolas SEM recorte (``recortar_iee`` depois)."""
    tabela = ler_csv(conteudo, nome)
    parser = identificar(tabela.colunas)
    if parser == PARSER_IEE:
        return ler_iee(tabela, nome, edicao_informada=edicao_informada)
    if parser == PARSER_SARESP_MUNICIPIO:
        if not (codmun or "").strip():
            raise ImportacaoRecusada(
                "A rede não tem o código do município na SEDUC (CODMUN dos arquivos do "
                "SARESP — não é o IBGE; Caraguatatuba = 254). O SARESP por município é "
                "recortado por esse código e o Constela não o adivinha pelo nome: cadastre "
                "o código na rede e envie a prévia de novo. Nada foi gravado.")
        return ler_saresp_municipio(tabela, nome, codmun=codmun, codigo_ibge=codigo_ibge,
                                    edicao_informada=edicao_informada)
    return ler_saresp_instancia(tabela, nome, codigo_uf=codigo_ibge[:2],
                                edicao_informada=edicao_informada)
