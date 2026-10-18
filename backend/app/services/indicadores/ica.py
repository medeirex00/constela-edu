"""Parsers das planilhas oficiais do Indicador Criança Alfabetizada (INEP).

São dois arquivos públicos por edição, os dois em XLSX:

* ``inep_ica_municipios`` — "resultados e metas" por MUNICÍPIO (só a rede
  municipal). Grava SÓ a linha do município da rede (``redes.codigo_ibge``);
* ``inep_ica_ufs`` — "resultados e metas" por UF e Brasil (rede pública). Grava
  a UF da rede (os 2 primeiros dígitos do IBGE: 35 = SP) e o Brasil.

Layout real (2023; 2024; 2025 v3 e v2), conferido nos arquivos do INEP:

* linha 1 = rótulos para gente ("PERCENTUAL DE ALUNOS ALFABETIZADOS - 2023 (1)");
* linha 2 = CÓDIGOS das variáveis — ``ANO``, ``CO_MUNICIPIO``/``CD_UF``,
  ``NO_TP_REDE``/``REDE``, ``PC_ALUNO_ALFABETIZADO_2023``, ``META_FINAL_2024`` …
  ``META_FINAL_2030``, ``CO_NIVEL_ALFABETIZACAO`` (2023: ``NIVEIS_ALFABETIZACAO_2023``)
  e ``PC_AVALIADOS_LP``;
* depois os dados; no fim, linhas de OBSERVAÇÃO (texto na 1ª coluna).

As colunas são localizadas PELO CÓDIGO da linha técnica, nunca pela posição — o
arquivo de 2025 acrescenta colunas no meio. Faltou o que é exigido (ou veio
repetido) → recusa com mensagem clara, sem gravar nada. O arquivo de 2023 não
traz o ano no código do resultado (``PC_ALUNO_ALFABETIZADO``): a edição vem da
coluna ``ANO``. Nível e participação são sempre da edição do arquivo (``ANO``).

PRECISÃO: o valor entra como o arquivo traz, arredondado a 2 casas (a precisão
que o INEP divulga — o arquivo de 2023 traz as metas com os 15 dígitos do
cálculo). ``casas_decimais`` é a precisão PUBLICADA da COLUNA no arquivo, não a
do valor: o máximo de casas entre os valores numéricos da coluna (até 2), ou o
que o formato da célula mostra, quando mostra mais. O float perde o zero final
(27,90 vira 27.9), a precisão não: numa coluna de 2 casas, 27,90 tem 2 casas;
numa coluna de inteiros, 28 tem 0. É ela que decide a precedência entre arquivos
(``pipeline``) e a precisão da comparação resultado × meta (``consulta``).

DATA DO ARQUIVO: ``arquivo_data`` é o ``dcterms:modified`` gravado DENTRO do XLSX
(docProps/core.xml), lido direto do pacote. Sem essa data, fica nula (com aviso
na prévia) — nunca a hora da leitura, que o openpyxl põe no lugar quando ela falta.

AUSÊNCIA ≠ ZERO: célula vazia ou "-" vira ausência com motivo — ``participacao_baixa``
quando o próprio arquivo mostra participação abaixo de 70% (a regra da
Observação 1 do INEP), senão ``nao_divulgado``. A META 0 (no arquivo de 2025, em
municípios sem resultado de base em 2023 — às vezes só a de 2030) vira
``sem_meta``: 0% não é meta, e mostrar "meta 0%" seria inventar um número.

Funções PURAS: bytes → ``LeituraICA`` (linhas canônicas + avisos). Sem banco.
"""
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

from app.services.avaliacoes import ImportacaoRecusada

PARSER_MUNICIPIOS = "inep_ica_municipios"
PARSER_UFS = "inep_ica_ufs"
VERSAO_PARSER = "1"

# Indicadores gravados (coluna `indicador` de indicadores_referencia).
IND_RESULTADO = "percentual_alfabetizado"
IND_META = "meta"
IND_NIVEL = "nivel_municipio"
IND_PARTICIPACAO = "participacao"

CODIGO_BRASIL = "BR"
ETAPA = "2_ano"           # o ICA mede o 2º ano...
COMPONENTE = "lp"         # ...em Língua Portuguesa
PARTICIPACAO_MINIMA = 70  # abaixo disso o INEP não divulga o município (Observação 1)

# Teto de linhas lidas (barra decompression-bomb de XLSX). O arquivo municipal
# real tem ~5,5 mil linhas.
_MAX_LINHAS = 100_000
_LINHAS_TOPO = 6          # a linha técnica (códigos) é a 2ª; folga para pré-âmbulo

_RE_RESULTADO = re.compile(r"^PC_ALUNO_ALFABETIZADO(?:_(\d{4}))?$")
_RE_META = re.compile(r"^META_FINAL_(\d{4})$")
_RE_NIVEL = re.compile(r"^(?:CO_NIVEL_ALFABETIZACAO|NIVEIS_ALFABETIZACAO_(\d{4}))$")
_PARTICIPACAO = "PC_AVALIADOS_LP"
_RE_SAEB_ANTIGO = re.compile(r"^SAEB_(\d{4})$")
_RE_OPERADOR = re.compile(r"^(>=|≥|>|<=|≤|<)\s*(\d+(?:[.,]\d+)?)\s*%?$")
_VAZIOS = {"", "-", "--", "—", "–", "nd", "n/d", "*", "...", "…"}

_ARQUIVO_MUNICIPIOS = ('a planilha oficial do INEP "resultados e metas" por município '
                       "(resultados_e_metas_municipios_*.xlsx)")
_ARQUIVO_UFS = ('a planilha oficial do INEP "resultados e metas" por UF e Brasil '
                "(resultados_e_metas_ufs_*.xlsx)")

# Onde o XLSX guarda a data de modificação (o mesmo caminho que o openpyxl lê).
_CORE_XML = "docProps/core.xml"
_DCTERMS_MODIFIED = "{http://purl.org/dc/terms/}modified"
_MAX_CORE_XML = 1_000_000   # são poucos KB; maior que isso não é um core.xml de verdade
AVISO_SEM_DATA = (
    "O arquivo não traz a data interna de modificação (dcterms:modified, em "
    "docProps/core.xml): a importação fica sem “arquivo de <data>” e, na mesma edição, "
    "não passa à frente de uma versão datada. Se puder, suba a planilha como baixada "
    "do INEP (abrir e salvar de novo no Excel também troca essa data).")


@dataclass(frozen=True)
class LinhaCanonica:
    """Um número (ou a ausência dele) pronto para `indicadores_referencia`."""

    indicador: str
    edicao: int
    abrangencia: str            # municipio | uf | brasil
    codigo_territorio: str      # IBGE (7) | UF (2) | "BR"
    rede_ensino: str            # municipal | publica
    unidade: str                # percentual | nivel
    valor: float | None
    casas_decimais: int | None = None
    operador: str | None = None
    motivo_ausencia: str | None = None
    etapa: str = ETAPA
    componente: str = COMPONENTE
    codigo_inep: str = ""
    localizacao: str = "total"
    nivel: str = ""
    desenho: str | None = "censitario"

    @property
    def chave(self) -> tuple:
        """Chave natural (sem a avaliação) — a da restrição única da tabela."""
        return (self.edicao, self.indicador, self.abrangencia, self.codigo_territorio,
                self.codigo_inep, self.rede_ensino, self.localizacao, self.etapa,
                self.componente, self.nivel)


@dataclass
class LeituraICA:
    """O que o parser entendeu do arquivo (nada gravado)."""

    parser: str
    edicao_arquivo: int
    arquivo_data: datetime | None
    aba: str
    linhas: list[LinhaCanonica] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    notas_arquivo: list[str] = field(default_factory=list)
    territorios: dict[str, str] = field(default_factory=dict)  # código → nome no arquivo
    linhas_lidas: int = 0


# --- Normalização de célula ---------------------------------------------------

def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def normalizar_rede(bruto) -> str:
    """'MUNICIPAL' → 'municipal'; 'PÚBLICA' → 'publica' (sem acento, minúsculo)."""
    return _sem_acento(str(bruto or "")).strip().strip("*").strip().casefold()


def _codigo(bruto) -> str | None:
    """Código numérico da célula (int do openpyxl, '3599999', '3599999.0'), ou None
    se a célula não é um código (vazia, texto de observação)."""
    if bruto is None or isinstance(bruto, bool):
        return None
    if isinstance(bruto, float):
        if not bruto.is_integer():
            return None
        bruto = int(bruto)
    s = str(bruto).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s if s.isdigit() else None


def normalizar_codigo_ibge(bruto) -> str | None:
    """IBGE do município com 7 dígitos, ou None (nunca completa nem adivinha)."""
    s = _codigo(bruto)
    return s if s is not None and len(s) == 7 else None


def _ano(bruto) -> int | None:
    s = _codigo(bruto)
    return int(s) if s is not None and len(s) == 4 else None


def ler_numero(bruto) -> tuple[float | None, str | None, bool]:
    """``(valor, operador, reconhecido)``. Vazio/"-" → (None, None, True); "> 80" →
    (80.0, ">", True); texto que não é número → (None, None, False)."""
    if bruto is None:
        return None, None, True
    if isinstance(bruto, bool):
        return None, None, False
    if isinstance(bruto, (int, float)):
        return float(bruto), None, True
    s = str(bruto).strip()
    if s.casefold() in _VAZIOS:
        return None, None, True
    casou = _RE_OPERADOR.match(s)
    if casou:
        operador = {"≥": ">=", "≤": "<="}.get(casou.group(1), casou.group(1))
        return float(casou.group(2).replace(",", ".")), operador, True
    try:
        return float(s.replace("%", "").replace(",", ".").strip()), None, True
    except ValueError:
        return None, None, False


def arredondar(valor: float, casas: int = 2) -> float:
    """Arredonda "meio para cima" (como a divulgação), não o arredondamento do banqueiro."""
    quantum = Decimal(1).scaleb(-casas)
    return float(Decimal(repr(float(valor))).quantize(quantum, rounding=ROUND_HALF_UP))


def precisao(valor: float) -> tuple[float, int]:
    """``(valor com no máximo 2 casas, casas efetivas 0–2)``. As casas são as do
    VALOR (o float perdeu os zeros finais): a precisão publicada é a da coluna
    (``_CasasPorColuna``)."""
    v = Decimal(repr(float(valor))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if v == v.to_integral_value():
        return float(v), 0
    if v == v.quantize(Decimal("0.1")):
        return float(v), 1
    return float(v), 2


@lru_cache(maxsize=128)
def casas_do_formato(formato) -> int:
    """Casas que o formato da célula MOSTRA: '0.00' → 2; '0.0' → 1; '0', 'General' → 0."""
    secao = re.sub(r'"[^"]*"|\[[^\]]*\]', "", str(formato or "")).split(";", 1)[0]
    casou = re.search(r"\.(0+)", secao)
    return len(casou.group(1)) if casou else 0


def _casas_da_celula(celula) -> int | None:
    """Casas (até 2) que UMA célula publica, ou None se ela não traz número."""
    valor = getattr(celula, "value", None)
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        do_valor = 0 if float(valor).is_integer() else precisao(valor)[1]
        casas = max(do_valor, casas_do_formato(getattr(celula, "number_format", None)))
    elif isinstance(valor, str):
        numero, _, _ = ler_numero(valor)
        if numero is None:
            return None
        escritas = re.search(r"[.,](\d+)\s*%?\s*$", valor.strip())   # "33,50" → 2
        casas = max(precisao(numero)[1], len(escritas.group(1)) if escritas else 0)
    else:
        return None
    return min(casas, 2)


class _CasasPorColuna:
    """Precisão PUBLICADA de cada coluna numérica, vista em TODAS as linhas de dados
    do arquivo: o máximo de casas (até 2) entre os valores da coluna, ou o que o
    formato da célula mostra, quando mostra mais. É da coluna, não do valor: numa
    coluna publicada com 2 casas, 27,90 continua com 2 casas (o float 27.9 perdeu
    o zero final, a precisão não)."""

    def __init__(self, colunas):
        self.casas: dict[int, int] = dict.fromkeys(colunas, 0)

    def ver(self, celulas) -> None:
        for j, atual in list(self.casas.items()):
            if atual >= 2 or j >= len(celulas):
                continue
            casas = _casas_da_celula(celulas[j])
            if casas is not None and casas > atual:
                self.casas[j] = casas


def _colunas_numericas(mapa: dict) -> list[int]:
    participacao = [] if mapa["participacao"] is None else [mapa["participacao"]]
    return [*mapa["resultados"], *mapa["metas"], *participacao]


def ler_do_zip(z: zipfile.ZipFile, info: zipfile.ZipInfo, maximo: int) -> bytes:
    """O conteúdo da entrada, descomprimindo NO MÁXIMO ``maximo + 1`` bytes.

    Conferir ``info.file_size`` não basta: o tamanho é o que o PRÓPRIO zip declara, e
    ``z.read(info)`` infla o fluxo inteiro antes de cortá-lo nesse tamanho — uma
    entrada que declara 100 bytes e infla centenas de MB ocuparia a memória toda (zip
    bomb). ``ZipExtFile.read(n)`` descomprime aos poucos, para no tamanho declarado e
    confere o CRC32 no fim (``BadZipFile`` se o fluxo não é o declarado). LEVANTA
    ``ValueError`` se passar de ``maximo``."""
    with z.open(info) as entrada:
        dados = entrada.read(maximo + 1)
    if len(dados) > maximo:
        raise ValueError(f"a entrada {info.filename} passa de {maximo} bytes")
    return dados


def data_interna(conteudo) -> datetime | None:
    """``dcterms:modified`` gravado DENTRO do XLSX (docProps/core.xml), em UTC sem
    fuso, ou None quando o arquivo não traz a data (ou ela não é legível).

    ``conteudo``: os bytes do XLSX ou o CAMINHO dele (a planilha do Saeb tem dezenas
    de MB: pelo caminho, só o core.xml é lido).

    Lido direto do pacote, e não de ``wb.properties.modified``: quando a data
    falta, o openpyxl põe ali a hora da LEITURA — e uma data inventada decidiria a
    precedência entre versões da mesma edição e apareceria no selo como se fosse a
    data do arquivo do INEP."""
    from openpyxl.xml.functions import fromstring   # o mesmo XML seguro do openpyxl
    fonte = io.BytesIO(conteudo) if isinstance(conteudo, (bytes, bytearray)) else conteudo
    try:
        with zipfile.ZipFile(fonte) as pacote:
            info = pacote.getinfo(_CORE_XML)
            if info.file_size > _MAX_CORE_XML:
                return None
            no = fromstring(ler_do_zip(pacote, info, _MAX_CORE_XML)).find(_DCTERMS_MODIFIED)
        texto = (no.text or "").strip() if no is not None else ""
        if not texto:
            return None
        quando = datetime.fromisoformat(texto)
    except Exception:  # noqa: BLE001 — sem core.xml, XML quebrado ou data ilegível = sem data
        return None
    if quando.tzinfo is not None:
        quando = quando.astimezone(timezone.utc).replace(tzinfo=None)
    return quando


# --- Abertura e localização da linha técnica ---------------------------------

def _abrir(conteudo: bytes, nome: str):
    if not (nome or "").lower().endswith((".xlsx", ".xlsm")):
        raise ImportacaoRecusada(
            f"O arquivo “{nome or 'sem nome'}” não é uma planilha XLSX. Suba a planilha "
            "oficial do INEP como baixada (resultados_e_metas_*.xlsx). Nada foi gravado.")
    from openpyxl import load_workbook
    try:
        return load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 — qualquer falha de leitura = recusa clara
        raise ImportacaoRecusada(
            "Não consegui abrir o arquivo como planilha XLSX (arquivo corrompido ou de "
            "outro formato). Nada foi gravado.") from exc


def _codigos(linha) -> list[str]:
    return ["" if c is None else str(c).strip().upper() for c in linha]


def _localizar(wb) -> tuple[str, object, int, list[str]]:
    """Acha a aba e a linha técnica pela ASSINATURA (não pela posição nem só pelo
    nome da aba): a linha que tem a coluna de resultado do ICA e o código do
    território. Devolve ``(parser, aba, índice da linha técnica, códigos)``."""
    for aba in wb.worksheets:
        for i, linha in enumerate(aba.iter_rows(max_row=_LINHAS_TOPO, values_only=True)):
            cods = _codigos(linha)
            if not any(_RE_RESULTADO.match(c) for c in cods):
                continue
            if "CO_MUNICIPIO" in cods:
                return PARSER_MUNICIPIOS, aba, i, cods
            if "CD_UF" in cods and "NOME_UF" in cods:
                return PARSER_UFS, aba, i, cods
    raise ImportacaoRecusada(
        "O arquivo não parece a planilha oficial de resultados e metas do Indicador "
        "Criança Alfabetizada: não encontrei a linha de códigos das variáveis (com "
        "PC_ALUNO_ALFABETIZADO e CO_MUNICIPIO, ou CD_UF e NOME_UF). Confira se é "
        f"{_ARQUIVO_MUNICIPIOS} ou {_ARQUIVO_UFS}. Nada foi gravado.")


def _mapear(cods: list[str], fixas: tuple[str, ...], arquivo: str) -> dict:
    """Índices PELO CÓDIGO: as fixas exigidas, os resultados e as metas por ano, o
    nível e a participação. Recusa se faltar exigida ou se algo vier repetido."""
    vistos: dict[str, int] = {}
    repetidas = []
    for j, c in enumerate(cods):
        if not c:
            continue
        if c in vistos:
            repetidas.append(c)
        vistos[c] = j
    if repetidas:
        raise ImportacaoRecusada(
            f"A coluna {', '.join(sorted(set(repetidas)))} aparece mais de uma vez no "
            f"arquivo; confira se é {arquivo}. Nada foi gravado.")
    faltam = [c for c in fixas if c not in vistos]
    resultados = {c: (int(m.group(1)) if m.group(1) else None)
                  for c in vistos if (m := _RE_RESULTADO.match(c))}
    metas = {c: int(m.group(1)) for c in vistos if (m := _RE_META.match(c))}
    if not metas:
        faltam.append("META_FINAL_<ano>")
    if faltam:
        raise ImportacaoRecusada(
            f"O arquivo não tem a coluna {', '.join(faltam)}; confira se é {arquivo}. "
            "Nada foi gravado.")
    if sum(1 for ano in resultados.values() if ano is None) > 1:
        raise ImportacaoRecusada(
            "O arquivo tem mais de uma coluna de resultado sem ano; confira se é "
            f"{arquivo}. Nada foi gravado.")
    niveis = {c: (int(m.group(1)) if m.group(1) else None)
              for c in vistos if (m := _RE_NIVEL.match(c))}
    if len(niveis) > 1:
        raise ImportacaoRecusada(
            f"O arquivo tem mais de uma coluna de nível ({', '.join(sorted(niveis))}); "
            f"confira se é {arquivo}. Nada foi gravado.")
    return {
        "fixas": {c: vistos[c] for c in fixas},
        "resultados": {vistos[c]: ano for c, ano in resultados.items()},
        "metas": {vistos[c]: ano for c, ano in metas.items()},
        "nivel": next(((vistos[c], ano) for c, ano in niveis.items()), None),
        "participacao": vistos.get(_PARTICIPACAO),
        "saeb_antigo": sorted(c for c in vistos if _RE_SAEB_ANTIGO.match(c)),
    }


def _cel(linha, j):
    return linha[j] if j is not None and 0 <= j < len(linha) else None


def _nota(linha) -> str | None:
    """Texto de observação no rodapé (1ª célula com texto, sem código na linha)."""
    for c in linha:
        if isinstance(c, str) and c.strip():
            return c.strip()
    return None


# --- Linhas canônicas de UMA linha do arquivo ----------------------------------

def _linhas_do_territorio(linha, mapa: dict, *, edicao_arquivo: int, abrangencia: str,
                          codigo: str, rede_ensino: str, rotulo: str, casas: dict[int, int],
                          avisos: list[str]) -> list[LinhaCanonica]:
    base = {"abrangencia": abrangencia, "codigo_territorio": codigo,
            "rede_ensino": rede_ensino}

    def _publicado(valor: float, j) -> tuple[float, int]:
        """Valor com até 2 casas e a precisão PUBLICADA da coluna (``casas``)."""
        v, do_valor = precisao(valor)
        return v, max(do_valor, casas.get(j, 0))

    def _numero(j, coluna: str) -> tuple[float | None, str | None]:
        valor, operador, ok = ler_numero(_cel(linha, j))
        if not ok:
            avisos.append(f"{rotulo}: valor não numérico “{_cel(linha, j)}” em {coluna} "
                          "— tratado como ausente (não como zero).")
        return valor, operador

    def _percentual(valor: float | None, coluna: str) -> float | None:
        if valor is not None and not 0 <= valor <= 100:
            raise ImportacaoRecusada(
                f"{rotulo}: {coluna} = {valor} fora da faixa de 0 a 100%. O arquivo não "
                "confere com o layout oficial; nada foi gravado.")
        return valor

    saida: list[LinhaCanonica] = []

    participacao = None
    if mapa["participacao"] is not None:
        bruto, _ = _numero(mapa["participacao"], _PARTICIPACAO)
        participacao = _percentual(bruto, _PARTICIPACAO)
        if participacao is None:
            saida.append(LinhaCanonica(indicador=IND_PARTICIPACAO, edicao=edicao_arquivo,
                                       unidade="percentual", valor=None,
                                       motivo_ausencia="nao_divulgado", **base))
        else:
            v, c = _publicado(participacao, mapa["participacao"])
            saida.append(LinhaCanonica(indicador=IND_PARTICIPACAO, edicao=edicao_arquivo,
                                       unidade="percentual", valor=v, casas_decimais=c,
                                       **base))

    for j, ano in sorted(mapa["resultados"].items(), key=lambda par: par[1] or edicao_arquivo):
        edicao = ano or edicao_arquivo
        coluna = f"PC_ALUNO_ALFABETIZADO{'_' + str(ano) if ano else ''}"
        bruto, _ = _numero(j, coluna)
        valor = _percentual(bruto, coluna)
        if valor is None:
            # Sem resultado: a participação do PRÓPRIO arquivo (da mesma edição)
            # abaixo de 70% é a evidência da Observação 1; sem ela, não divulgado.
            baixa = (edicao == edicao_arquivo and participacao is not None
                     and participacao < PARTICIPACAO_MINIMA)
            saida.append(LinhaCanonica(
                indicador=IND_RESULTADO, edicao=edicao, unidade="percentual", valor=None,
                motivo_ausencia="participacao_baixa" if baixa else "nao_divulgado", **base))
            continue
        v, c = _publicado(valor, j)
        saida.append(LinhaCanonica(indicador=IND_RESULTADO, edicao=edicao,
                                   unidade="percentual", valor=v, casas_decimais=c,
                                   **base))

    for j, ano in sorted(mapa["metas"].items(), key=lambda par: par[1]):
        coluna = f"META_FINAL_{ano}"
        bruto, operador = _numero(j, coluna)
        valor = _percentual(bruto, coluna)
        if valor is None:
            saida.append(LinhaCanonica(indicador=IND_META, edicao=ano, unidade="percentual",
                                       valor=None, motivo_ausencia="nao_divulgado", **base))
            continue
        if valor == 0 and operador is None:
            avisos.append(f"{rotulo}: o arquivo traz META {ano} = 0 — tratada como “sem "
                          "meta definida” (0% não é meta), não como meta de 0%.")
            saida.append(LinhaCanonica(indicador=IND_META, edicao=ano, unidade="percentual",
                                       valor=None, motivo_ausencia="sem_meta", **base))
            continue
        v, c = _publicado(valor, j)
        saida.append(LinhaCanonica(indicador=IND_META, edicao=ano, unidade="percentual",
                                   valor=v, casas_decimais=c, operador=operador,
                                   **base))

    if mapa["nivel"] is not None:
        j, ano = mapa["nivel"]
        edicao = ano or edicao_arquivo
        bruto, _ = _numero(j, "nível de alfabetização")
        if bruto is None:
            saida.append(LinhaCanonica(indicador=IND_NIVEL, edicao=edicao, unidade="nivel",
                                       valor=None, motivo_ausencia="nao_divulgado", **base))
        else:
            if not (float(bruto).is_integer() and 0 <= bruto <= 5):
                raise ImportacaoRecusada(
                    f"{rotulo}: nível de alfabetização = {bruto}, fora da escala oficial "
                    "(0 a 5). Nada foi gravado.")
            saida.append(LinhaCanonica(indicador=IND_NIVEL, edicao=edicao, unidade="nivel",
                                       valor=float(bruto), casas_decimais=0, **base))
    return saida


# --- Leitura do arquivo -------------------------------------------------------

def ler_planilha_ica(conteudo: bytes, nome: str, *, codigo_ibge: str) -> LeituraICA:
    """Identifica o arquivo pela assinatura (municípios ou UFs) e recorta SÓ o que a
    rede usa: a linha MUNICIPAL do município ``codigo_ibge``, ou a UF dele e o
    Brasil (rede pública). LEVANTA ``ImportacaoRecusada`` se o arquivo não confere."""
    codigo_ibge = normalizar_codigo_ibge(codigo_ibge)
    if codigo_ibge is None:
        raise ImportacaoRecusada("Código IBGE do município inválido (são 7 dígitos).")
    wb = _abrir(conteudo, nome)
    try:
        parser, aba, i_tecnica, cods = _localizar(wb)
        # Nunca wb.properties.modified: sem a data no arquivo, ali vem a hora da leitura.
        arquivo_data = data_interna(conteudo)
        if parser == PARSER_MUNICIPIOS:
            leitura = _ler_municipios(aba, i_tecnica, cods, codigo_ibge, arquivo_data)
        else:
            leitura = _ler_ufs(aba, i_tecnica, cods, codigo_ibge[:2], arquivo_data)
        if arquivo_data is None:
            leitura.avisos.append(AVISO_SEM_DATA)
        return leitura
    except ImportacaoRecusada:
        raise
    except Exception as exc:  # noqa: BLE001 — XML da aba quebrado no meio da leitura
        raise ImportacaoRecusada(
            "A planilha abriu, mas não consegui ler as linhas dela (arquivo corrompido). "
            "Nada foi gravado.") from exc
    finally:
        wb.close()


def _linhas_de_dados(aba, i_tecnica: int):
    """``(valores, células)`` de cada linha não vazia depois da linha técnica — as
    células trazem o formato, que entra na precisão da coluna."""
    for k, celulas in enumerate(aba.iter_rows(min_row=i_tecnica + 2)):
        if k >= _MAX_LINHAS:
            raise ImportacaoRecusada(
                f"O arquivo tem mais de {_MAX_LINHAS} linhas — muito maior que a planilha "
                "oficial do ICA. Nada foi gravado.")
        linha = tuple(getattr(c, "value", None) for c in celulas)
        if any(c is not None and str(c).strip() for c in linha):
            yield linha, celulas


def _edicao_unica(anos: set[int], arquivo: str) -> int:
    if not anos:
        raise ImportacaoRecusada(
            f"O arquivo não tem linhas de dados com o ANO da avaliação; confira se é "
            f"{arquivo}. Nada foi gravado.")
    if len(anos) > 1:
        raise ImportacaoRecusada(
            f"O arquivo mistura anos de avaliação ({', '.join(map(str, sorted(anos)))}) na "
            f"coluna ANO; confira se é {arquivo}. Nada foi gravado.")
    return next(iter(anos))


def _ler_municipios(aba, i_tecnica, cods, codigo_ibge, arquivo_data) -> LeituraICA:
    mapa = _mapear(cods, ("ANO", "CO_MUNICIPIO", "NO_TP_REDE"), _ARQUIVO_MUNICIPIOS)
    j_ano, j_mun, j_rede = (mapa["fixas"][c] for c in ("ANO", "CO_MUNICIPIO", "NO_TP_REDE"))
    j_nome = cods.index("NO_MUNICIPIO") if "NO_MUNICIPIO" in cods else None
    anos: set[int] = set()
    alvo: list[tuple] = []
    notas: list[str] = []
    casas = _CasasPorColuna(_colunas_numericas(mapa))
    lidas = 0
    for linha, celulas in _linhas_de_dados(aba, i_tecnica):
        codigo = normalizar_codigo_ibge(_cel(linha, j_mun))
        if codigo is None:
            nota = _nota(linha)
            if nota:
                notas.append(nota)
            continue
        lidas += 1
        casas.ver(celulas)
        ano = _ano(_cel(linha, j_ano))
        if ano is not None:
            anos.add(ano)
        if codigo == codigo_ibge:
            alvo.append(linha)
    edicao = _edicao_unica(anos, _ARQUIVO_MUNICIPIOS)
    leitura = LeituraICA(parser=PARSER_MUNICIPIOS, edicao_arquivo=edicao,
                         arquivo_data=arquivo_data, aba=aba.title, notas_arquivo=notas,
                         linhas_lidas=lidas)
    municipais = [ln for ln in alvo if normalizar_rede(_cel(ln, j_rede)) == "municipal"]
    if alvo and not municipais:
        leitura.avisos.append(
            f"O município {codigo_ibge} está no arquivo, mas não na rede MUNICIPAL — "
            "nada a importar (o ICA municipal é só da rede municipal).")
    if len(municipais) > 1:
        raise ImportacaoRecusada(
            f"O município {codigo_ibge} aparece {len(municipais)} vezes na rede municipal "
            "do arquivo; não dá para saber qual linha vale. Nada foi gravado.")
    if not alvo:
        leitura.avisos.append(
            f"O município {codigo_ibge} não está no arquivo. Pela Observação 1 do INEP, "
            "ficam sem resultado os municípios que não participaram ou tiveram "
            "participação abaixo de 70%. Nada a importar deste arquivo.")
    if municipais:
        linha = municipais[0]
        nome = str(_cel(linha, j_nome) or "").strip() or codigo_ibge
        leitura.territorios[codigo_ibge] = nome
        leitura.linhas = _linhas_do_territorio(
            linha, mapa, edicao_arquivo=edicao, abrangencia="municipio", codigo=codigo_ibge,
            rede_ensino="municipal", rotulo=nome, casas=casas.casas, avisos=leitura.avisos)
    return leitura


def _ler_ufs(aba, i_tecnica, cods, codigo_uf, arquivo_data) -> LeituraICA:
    mapa = _mapear(cods, ("ANO", "CD_UF", "NOME_UF", "REDE"), _ARQUIVO_UFS)
    j_ano, j_uf, j_nome, j_rede = (mapa["fixas"][c] for c in ("ANO", "CD_UF", "NOME_UF", "REDE"))
    anos: set[int] = set()
    alvos: dict[str, list[tuple]] = {codigo_uf: [], CODIGO_BRASIL: []}
    notas: list[str] = []
    casas = _CasasPorColuna(_colunas_numericas(mapa))
    lidas = 0
    for linha, celulas in _linhas_de_dados(aba, i_tecnica):
        uf = _codigo(_cel(linha, j_uf))
        nome = _sem_acento(str(_cel(linha, j_nome) or "")).strip().strip("*").strip().casefold()
        if uf is None and nome != "brasil":
            nota = _nota(linha)
            if nota:
                notas.append(nota)
            continue
        lidas += 1
        casas.ver(celulas)
        ano = _ano(_cel(linha, j_ano))
        if ano is not None:
            anos.add(ano)
        if nome == "brasil" and uf is None:
            alvos[CODIGO_BRASIL].append(linha)
        elif uf == codigo_uf:
            alvos[codigo_uf].append(linha)
    edicao = _edicao_unica(anos, _ARQUIVO_UFS)
    leitura = LeituraICA(parser=PARSER_UFS, edicao_arquivo=edicao, arquivo_data=arquivo_data,
                         aba=aba.title, notas_arquivo=notas, linhas_lidas=lidas)
    if mapa["saeb_antigo"]:
        leitura.avisos.append(
            f"O arquivo traz também {', '.join(mapa['saeb_antigo'])} (percentual de "
            "alfabetizados no Saeb, outra metodologia, amostral): não importado.")
    for codigo, abrangencia in ((codigo_uf, "uf"), (CODIGO_BRASIL, "brasil")):
        publicas = [ln for ln in alvos[codigo] if normalizar_rede(_cel(ln, j_rede)) == "publica"]
        rotulo = "Brasil" if codigo == CODIGO_BRASIL else f"UF {codigo}"
        if len(publicas) > 1:
            raise ImportacaoRecusada(
                f"{rotulo} aparece {len(publicas)} vezes na rede pública do arquivo; não dá "
                "para saber qual linha vale. Nada foi gravado.")
        if not publicas:
            leitura.avisos.append(f"{rotulo} (rede pública) não está no arquivo — nada a "
                                  "importar para esse território.")
            continue
        linha = publicas[0]
        nome = str(_cel(linha, j_nome) or "").strip().strip("*").strip() or rotulo
        leitura.territorios[codigo] = nome
        leitura.linhas.extend(_linhas_do_territorio(
            linha, mapa, edicao_arquivo=edicao, abrangencia=abrangencia, codigo=codigo,
            rede_ensino="publica", rotulo=nome, casas=casas.casas, avisos=leitura.avisos))
    return leitura
