"""Parser ``inep_ideb_escolas``: o Ideb POR ESCOLA dos ANOS INICIAIS do INEP
(``divulgacao_anos_iniciais_escolas_AAAA.zip``, com um .xlsx e um .ods dentro) —
etapa E6a dos indicadores oficiais.

Função PURA (linhas da planilha → leitura canônica + avisos, sem banco nem rede),
usada nos DOIS caminhos com o MESMO código:

* nesta máquina, pela linha de comando ``preparar``, sobre o xlsx inteiro (~50 MB
  comprimidos, ~65 mil escolas) lido em STREAMING (openpyxl ``read_only``) — só as
  linhas da rede ficam em memória;
* no servidor, sobre o PACOTE recortado (``pacote_ideb``): o mesmo topo da planilha
  (as linhas de cabeçalho e a técnica) + só as linhas da rede, em CSV de texto. A
  produção nunca abre o arquivo do INEP.

LAYOUT REAL (conferido no arquivo de 2023; o de 2025, ainda não baixado, deve trazer
2025 no mesmo desenho — se não trouxer, as guardas abaixo recusam com a causa):

* pré-âmbulo + cabeçalho em VÁRIAS linhas: título com a etapa ("Ensino Fundamental
  Regular - Anos Iniciais"), grupos por edição ("Taxa de Aprovação - 2005", "Nota
  SAEB - 2005", "IDEB 2005 (N x P)", "Metas do 1º ciclo do Ideb (2007-2021)"),
  componentes e séries ("1º ao 5º ano", "1º" … "5º") e, por fim, a LINHA TÉCNICA
  com o nome de cada variável (a que tem ``ID_ESCOLA``). Os rótulos trazem DÍGITOS
  DE NOTA DE RODAPÉ grudados no ano ("20211" = 2021 com a nota 1; "Ideb2,3");
* colunas lidas PELO NOME da linha técnica, nunca pela posição:
  ``SG_UF``, ``CO_MUNICIPIO``, ``NO_MUNICIPIO``, ``ID_ESCOLA``, ``NO_ESCOLA``,
  ``REDE``; por edição AAAA: ``VL_APROVACAO_AAAA_SI_4`` (1º ao 5º ano),
  ``VL_APROVACAO_AAAA_SI`` (1º ano), ``VL_APROVACAO_AAAA_1`` … ``_4`` (2º ao 5º ano),
  ``VL_INDICADOR_REND_AAAA`` (P), ``VL_NOTA_MATEMATICA_AAAA``,
  ``VL_NOTA_PORTUGUES_AAAA`` (Saeb do 5º ano), ``VL_NOTA_MEDIA_AAAA`` (N),
  ``VL_OBSERVADO_AAAA`` (Ideb); e as metas ``VL_PROJECAO_AAAA`` (2007–2021). A série
  de cada coluna de aprovação é conferida com o rótulo de cima ("1º", "5º"...);
* marcadores no lugar do número: "-" e "ND", "ND*", "ND**", "ND***" (a legenda do
  rodapé explica cada ND). Todos viram AUSÊNCIA ``nao_divulgado`` — sem inventar
  causa (plano, 4.6: sem a participação por escola não se infere
  ``participacao_baixa``); o marcador original fica contado nos avisos e, cru, no
  pacote. Número com "*" (a nota "(*)": média calculada das avaliações estaduais)
  vale como número, com aviso;
* números como número (int/float) ou TEXTO com vírgula decimal (o Saeb de 2015
  inteiro vem assim);
* rodapé no fim da aba (fonte e legenda): linhas sem código de escola.

RECORTE: só as linhas da REDE MUNICIPAL (coluna ``REDE``) do MUNICÍPIO da rede
(``CO_MUNICIPIO`` = IBGE) — nunca pelo nome. A escola casa com o cadastro depois,
pelo INEP (``recortar``); a do município sem escola no cadastro fica listada.

ONDE CADA NÚMERO VAI (sem poluir a correlação nem as opções — que só leem
``resultados_avaliacao``):

* ``resultados_avaliacao`` (as MESMAS chaves que a produção já usa): Ideb
  (``ideb``/``ideb``, etapa ``anos_iniciais``, unidade ``indice``) e Saeb do 5º ano
  (``saeb``/``proficiencia``, etapa ``5_ano``, componente ``matematica`` e
  ``portugues``, unidade ``escala_saeb``) — sem número, valor nulo + motivo;
* ``indicadores_referencia`` (abrangência ``escola``, avaliação ``ideb``): N
  (``nota_n``), P (``rendimento_p``), aprovação por série (``aprovacao``, etapa
  ``anos_iniciais`` = 1º ao 5º e ``1_ano`` … ``5_ano``) e a meta da escola
  (``meta``, edição = ano da meta), como a E4 fez com a participação e o TPS.

O Ideb do MUNICÍPIO (``inep_ideb_municipios``, o Ideb e o Saeb da REDE municipal,
``divulgacao_anos_iniciais_municipios_AAAA.zip``) e o de UF/Brasil
(``inep_ideb_uf_brasil``) estão em ``ideb_territorio`` (E6b), com o MESMO leitor de
colunas, rótulos e marcadores deste módulo (linha técnica sem ``ID_ESCOLA``), e gravam
em ``indicadores_referencia`` com abrangência ``municipio``/``uf``/``brasil`` e a rede
da coluna ``REDE``, pelo mesmo preparar → pacote → prévia. Aqui eles são reconhecidos
e mandados para lá.

O arquivo de 2025 (2005–2025) entra por este mesmo parser, sem mudança: a edição 2025
é achada PELO NOME (``VL_OBSERVADO_2025``...), e as metas continuam só até 2021.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Callable, Iterable, Iterator, Sequence

from app.services.avaliacoes import ImportacaoRecusada, normalizar_inep
from app.services.indicadores import seduc
from app.services.indicadores.ica import LinhaCanonica, normalizar_rede

PARSER = "inep_ideb_escolas"
VERSAO_PARSER = "1"
PARSER_MUNICIPIOS = "inep_ideb_municipios"      # E6b: ``ideb_territorio``
PARSER_UF_BRASIL = "inep_ideb_uf_brasil"        # E6b: ``ideb_territorio``

AVALIACAO_IDEB = "ideb"
AVALIACAO_SAEB = "saeb"
ETAPA_IDEB = "anos_iniciais"     # o Ideb cobre do 1º ao 5º ano (a etapa que a produção grava)
ETAPA_SAEB = "5_ano"             # o Saeb é do 5º ano (normalizado na 0035)
IND_IDEB = "ideb"
IND_PROFICIENCIA = "proficiencia"
IND_NOTA_N = "nota_n"            # nota média padronizada (N)
IND_RENDIMENTO_P = "rendimento_p"  # indicador de rendimento (P)
IND_APROVACAO = "aprovacao"      # taxa de aprovação (%), por série
IND_META = "meta"                # meta do 1º ciclo do Ideb (2007–2021)
UNIDADE_IDEB = "indice"
UNIDADE_SAEB = "escala_saeb"
UNIDADE_P = "proporcao"          # P vai de 0 a 1
UNIDADE_APROVACAO = "percentual"
MOTIVO = "nao_divulgado"
COMPONENTES = {"saeb_matematica": "matematica", "saeb_portugues": "portugues"}

# A etapa no topo do arquivo (os de anos finais e ensino médio usam os MESMOS nomes de
# variável — só o topo diz a etapa).
MARCADORES_AI = ("anos iniciais", "1º ao 5º ano")
_OUTRAS_ETAPAS = ("anos finais", "ensino médio", "ensino medio", "6º ao 9º")
_LINHAS_TOPO = 20           # em 2023 a técnica é a 10ª linha (8ª não vazia)
_MESCLA_MAXIMA = 8          # colunas do maior grupo mesclado do cabeçalho (as metas)
_MAX_NOTAS = 40
_MAX_NOTA = 400
_ANO_MINIMO = 2005          # o Ideb começa em 2005
_ANO_MAXIMO = 2100

_IDENTIFICACAO = ("SG_UF", "CO_MUNICIPIO", "NO_MUNICIPIO", "ID_ESCOLA", "NO_ESCOLA", "REDE")
_EXIGIDAS = ("CO_MUNICIPIO", "ID_ESCOLA", "REDE")
_NUCLEO = ("ideb", "saeb_matematica", "saeb_portugues")   # obrigatórias em cada edição
_RE_COLUNAS = (
    (re.compile(r"^VL_OBSERVADO_(\d{4})$"), "ideb"),
    (re.compile(r"^VL_NOTA_MATEMATICA_(\d{4})$"), "saeb_matematica"),
    (re.compile(r"^VL_NOTA_PORTUGUES_(\d{4})$"), "saeb_portugues"),
    (re.compile(r"^VL_NOTA_MEDIA_(\d{4})$"), "nota_n"),
    (re.compile(r"^VL_INDICADOR_REND_(\d{4})$"), "rendimento_p"),
    (re.compile(r"^VL_PROJECAO_(\d{4})$"), "meta"),
)
_RE_APROVACAO = re.compile(r"^VL_APROVACAO_(\d{4})_(SI_4|SI|[1-4])$")
# Sufixo → série (conferido com o rótulo de cima: "1º ao 5º ano", "1º" … "5º").
_ETAPA_APROVACAO = {"SI_4": "anos_iniciais", "SI": "1_ano", "1": "2_ano", "2": "3_ano",
                    "3": "4_ano", "4": "5_ano"}
_FAIXAS = {"ideb": (0.0, 10.0), "saeb_matematica": (0.0, 500.0),
           "saeb_portugues": (0.0, 500.0), "nota_n": (0.0, 10.0),
           "rendimento_p": (0.0, 1.0), "aprovacao": (0.0, 100.0), "meta": (0.0, 10.0)}
_NOME_FAMILIA = {"ideb": "Ideb", "saeb_matematica": "Saeb MT", "saeb_portugues": "Saeb LP",
                 "nota_n": "N", "rendimento_p": "P", "aprovacao": "aprovação", "meta": "meta"}

_TRACOS = {"-", "--", "–", "—"}
_RE_ND = re.compile(r"^ND\**$")
_RE_NUMERO = re.compile(r"^([+-]?\d+(?:[.,]\d+)?)(\*?)$")
_RE_ANO_ROTULO = re.compile(r"(?<!\d)((?:19|20)\d{2})\d{0,2}(?!\d)")   # "20211" = 2021 + nota 1
_RE_SERIE_ROTULO = re.compile(r"^([1-5])\s*[º°ªo]")
_RE_AI_ROTULO = re.compile(r"^1\s*[º°ªo]?\s*ao\s*5\s*[º°ªo]?\s*ano")

ARQUIVO = ('o arquivo oficial do INEP "Ideb por escola — anos iniciais" '
           "(divulgacao_anos_iniciais_escolas_AAAA.zip)")


# --- Células ------------------------------------------------------------------

def texto_celula(valor) -> str:
    """O texto de uma célula, IGUAL para a planilha (int/float do openpyxl) e para o
    CSV do pacote (texto): é ele que vai para o pacote, e o parser só lê texto."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, float):
        texto = repr(valor)
        if "e" in texto or "E" in texto:
            try:
                texto = format(Decimal(texto), "f")
            except ArithmeticError:
                pass
        return texto
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    return str(valor).replace("\r\n", "\n").replace("\r", "\n").strip()


# Ruído binário do float: o número que difere do arredondado em menos que isto
# (relativo) é o arredondado.
_TOLERANCIA_RUIDO = 1e-12
# O INEP publica no máximo 6 casas (N e P). Um número escrito com mais casas é o ``repr``
# do ruído do float (57.99999999999999, de 0,58 × 100), não precisão publicada.
_CASAS_MAX_PUBLICADAS = 6
_RE_DECIMAL_COM_PONTO = re.compile(r"[+-]?\d+\.(\d+)")


def texto_limpo(valor) -> str:
    """O texto da célula (como ``texto_celula``), sem o ruído binário do float que a
    planilha às vezes grava (o 0,3 de ``0.1 + 0.2``, escrito 0.30000000000000004): o
    menor número de casas que reproduz o MESMO float. Vale para a planilha e para o CSV
    do pacote (o parser do território e o da planilha do Saeb usam este)."""
    if isinstance(valor, float) and not isinstance(valor, bool) and valor == valor:
        for casas in range(0, 11):
            arredondado = round(valor, casas)
            if abs(arredondado - valor) <= _TOLERANCIA_RUIDO * max(1.0, abs(valor)):
                texto = repr(arredondado)
                if "e" in texto or "E" in texto:
                    texto = format(Decimal(texto), "f")
                return texto[:-2] if casas == 0 and texto.endswith(".0") else texto
    return texto_celula(valor)


def texto_sem_ruido(valor) -> str:
    """O texto de uma célula da linha de DADOS do Ideb por escola: ``texto_celula``, mas
    o número escrito com mais casas do que o INEP publica (o ruído do float) sai pelo
    menor número de casas que reproduz o mesmo float (``texto_limpo``). O resto — o zero
    final (6.0), a vírgula e o asterisco do INEP, os marcadores — fica como está.

    Vale para a planilha (float) e para o TEXTO do CSV do pacote: o pacote gerado antes
    desta limpeza traz o ``repr`` do ruído escrito, e a leitura do servidor o limpa do
    mesmo jeito (sem isso, as casas do ruído viravam a precisão publicada da coluna)."""
    texto = texto_celula(valor)
    casou = _RE_DECIMAL_COM_PONTO.fullmatch(texto)
    if casou is None or len(casou.group(1)) <= _CASAS_MAX_PUBLICADAS:
        return texto
    return texto_limpo(float(texto))


def _aparar(linha: list[str]) -> list[str]:
    fim = len(linha)
    while fim and not linha[fim - 1]:
        fim -= 1
    return linha[:fim]


def _cel(linha: Sequence, j: int | None):
    return linha[j] if j is not None and 0 <= j < len(linha) else None


def _codigo(bruto) -> str | None:
    """Código numérico da célula (int, '35012345', '35012345.0') ou None."""
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


@dataclass(frozen=True)
class Celula:
    """Um valor como o INEP publicou: número (com as casas escritas) ou marcador."""

    valor: float | None
    casas: int = 0
    marcador: str | None = None      # "-", "ND", "ND*"… ou "vazio" (None com número)
    asterisco: bool = False          # "(*)" do INEP: média das avaliações estaduais


def ler_celula(texto: str) -> Celula | None:
    """``Celula`` ou None (texto que não é número nem marcador conhecido)."""
    s = (texto or "").strip()
    if not s:
        return Celula(None, 0, "vazio")
    if s in _TRACOS:
        return Celula(None, 0, "-")
    if _RE_ND.match(s.upper()):
        return Celula(None, 0, s.upper())
    casou = _RE_NUMERO.match(s.replace(" ", ""))
    if not casou:
        return None
    numero = casou.group(1).replace(",", ".")
    casas = len(numero.split(".", 1)[1]) if "." in numero else 0
    return Celula(float(numero), casas, None, bool(casou.group(2)))


# --- Estruturas ---------------------------------------------------------------

@dataclass(frozen=True)
class Coluna:
    """Uma variável da linha técnica."""

    nome: str
    indice: int
    familia: str        # ideb | saeb_matematica | saeb_portugues | nota_n | rendimento_p | aprovacao | meta
    ano: int
    etapa: str = ""     # só na aprovação: anos_iniciais | 1_ano … 5_ano


@dataclass(frozen=True)
class EscolaIdeb:
    inep: str
    nome: str
    celulas: dict       # nome técnico → Celula


@dataclass
class LeituraIdeb:
    """O que o parser entendeu do arquivo (nada gravado)."""

    edicoes: list[int]
    anos_meta: list[int]
    colunas: list[Coluna]
    topo: list[list[str]]                 # linhas não vazias ACIMA da técnica (texto)
    tecnica: list[str]
    recorte: list[list[str]] = field(default_factory=list)      # linhas da rede (texto)
    notas_linhas: list[list[str]] = field(default_factory=list)  # rodapé (texto)
    escolas: list[EscolaIdeb] = field(default_factory=list)
    municipio_nome: str | None = None
    casas: dict = field(default_factory=dict)       # nome técnico → casas publicadas
    linhas_lidas: int = 0                           # linhas de escola do arquivo inteiro
    outras_redes: Counter = field(default_factory=Counter)   # do município, outra rede
    marcadores: Counter = field(default_factory=Counter)     # no recorte
    asteriscos: list[str] = field(default_factory=list)
    colunas_ignoradas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def edicao_arquivo(self) -> int:
        return max(self.edicoes)

    @property
    def notas(self) -> list[str]:
        return [ln[0] for ln in self.notas_linhas if ln]


# --- Cabeçalho ------------------------------------------------------------------

def _recusa_layout(texto: str) -> ImportacaoRecusada:
    return ImportacaoRecusada(f"{texto} Confira se é {ARQUIVO}. Nada foi gravado.")


def _achar_tecnica(it: Iterator) -> tuple[list[list[str]], list[str]]:
    """Consome o topo até a linha técnica. Devolve as linhas não vazias de cima e a
    técnica (texto). Reconhece o Ideb por município / UF e os recusa com a causa."""
    topo: list[list[str]] = []
    for i, bruta in enumerate(it):
        if i >= _LINHAS_TOPO:
            break
        linha = _aparar([texto_celula(c) for c in (bruta or ())])
        nomes = {c.upper() for c in linha}
        if "ID_ESCOLA" in nomes:
            return topo, linha
        if any(n.startswith("VL_OBSERVADO_") for n in nomes):
            alvo = (f"o Ideb por MUNICÍPIO ({PARSER_MUNICIPIOS})" if "CO_MUNICIPIO" in nomes
                    else f"o Ideb de UF/Brasil ({PARSER_UF_BRASIL})")
            raise ImportacaoRecusada(
                f"Este arquivo é {alvo}, que tem o seu próprio parser (o preparar o detecta "
                "sozinho). Aqui entra o Ideb POR ESCOLA dos anos iniciais. Nada foi gravado.")
        if linha:
            topo.append(linha)
    raise _recusa_layout(
        f"Não encontrei a linha técnica do INEP (a que tem a coluna ID_ESCOLA) nas "
        f"primeiras {_LINHAS_TOPO} linhas.")


def _mapear(tecnica: list[str]) -> tuple[list[Coluna], dict[str, int], list[str]]:
    nomes = [c.strip().upper() for c in tecnica]
    repetidas = sorted({n for n, k in Counter(n for n in nomes if n).items() if k > 1})
    if repetidas:
        raise _recusa_layout(f"A coluna {', '.join(repetidas)} aparece mais de uma vez na "
                             "linha técnica.")
    ids = {n: j for j, n in enumerate(nomes) if n in _IDENTIFICACAO}
    faltam = [c for c in _EXIGIDAS if c not in ids]
    if faltam:
        raise _recusa_layout(f"O arquivo não tem a coluna {', '.join(faltam)}.")
    colunas: list[Coluna] = []
    ignoradas: list[str] = []
    for j, n in enumerate(nomes):
        if not n or n in ids:
            continue
        casou = _RE_APROVACAO.match(n)
        if casou:
            colunas.append(Coluna(tecnica[j].strip(), j, "aprovacao", int(casou.group(1)),
                                  _ETAPA_APROVACAO[casou.group(2)]))
            continue
        for regex, familia in _RE_COLUNAS:
            casou = regex.match(n)
            if casou:
                colunas.append(Coluna(tecnica[j].strip(), j, familia, int(casou.group(1))))
                break
        else:
            ignoradas.append(tecnica[j].strip())
    return colunas, ids, ignoradas


def _edicoes(colunas: list[Coluna]) -> tuple[list[int], list[int]]:
    por_ano: dict[int, set[str]] = defaultdict(set)
    metas: list[int] = []
    for c in colunas:
        if c.familia == "meta":
            metas.append(c.ano)
        else:
            por_ano[c.ano].add(c.familia)
    if not por_ano:
        raise _recusa_layout("A linha técnica não tem nenhuma edição do Ideb "
                             "(VL_OBSERVADO_AAAA, VL_NOTA_MATEMATICA_AAAA...).")
    nomes = {"ideb": "VL_OBSERVADO", "saeb_matematica": "VL_NOTA_MATEMATICA",
             "saeb_portugues": "VL_NOTA_PORTUGUES"}
    for ano in sorted(por_ano):
        faltam = [f"{nomes[f]}_{ano}" for f in _NUCLEO if f not in por_ano[ano]]
        if faltam:
            raise _recusa_layout(
                f"A edição {ano} está incompleta na linha técnica: falta {', '.join(faltam)}.")
    for ano in [*por_ano, *metas]:
        if not _ANO_MINIMO <= ano <= _ANO_MAXIMO:
            raise _recusa_layout(f"Edição {ano} fora do esperado (de {_ANO_MINIMO} a "
                                 f"{_ANO_MAXIMO}).")
    return sorted(por_ano), sorted(metas)


def _conferir_etapa(topo: list[list[str]]) -> None:
    texto = " ".join(c for linha in topo for c in linha).casefold()
    outra = next((m for m in _OUTRAS_ETAPAS if m in texto), None)
    if outra:
        raise _recusa_layout(f"O cabeçalho do arquivo é de outra etapa (“{outra}”); aqui "
                             "entram só os anos iniciais (o Saeb do 5º ano).")
    if not any(m in texto for m in MARCADORES_AI):
        marcas = " nem ".join(f'"{m}"' for m in MARCADORES_AI)
        raise _recusa_layout(f"O cabeçalho do arquivo não indica a etapa (não traz {marcas}).")


def anos_do_rotulo(texto: str) -> set[int]:
    """Anos citados num rótulo, ignorando o dígito de nota de rodapé grudado no ano
    ("20211" → 2021; "(2007-2021)" → 2007 e 2021; "Ideb2,3" → nenhum)."""
    return {int(a) for a in _RE_ANO_ROTULO.findall(texto or "")}


def etapa_do_rotulo(texto: str) -> str | None:
    """"1º ao 5º ano" → "anos_iniciais"; "1º" … "5º" (com ou sem nota) → "1_ano" …"""
    t = (texto or "").strip().casefold()
    if _RE_AI_ROTULO.match(t):
        return "anos_iniciais"
    casou = _RE_SERIE_ROTULO.match(t)
    return f"{casou.group(1)}_ano" if casou else None


def _rotulo_acima(linha: list[str], j: int, inicio: int) -> str:
    """O rótulo que cobre a coluna ``j`` numa linha do cabeçalho: o da própria coluna
    ou, numa célula mesclada, o mais próximo à esquerda — sem sair da área de valores
    nem passar da largura do maior grupo (as 8 metas; a aprovação tem 7 colunas)."""
    for k in range(min(j, len(linha) - 1), max(inicio, j - _MESCLA_MAXIMA + 1) - 1, -1):
        if linha[k]:
            return linha[k]
    return ""


def _conferir_rotulos(topo: list[list[str]], colunas: list[Coluna]) -> None:
    """O cabeçalho legível tem de concordar com a linha técnica: o ano dos grupos de
    cada coluna (com o dígito de rodapé ignorado) e a série das colunas de aprovação.
    Rótulo ausente não é conferido (a técnica manda); rótulo que DIVERGE = recusa."""
    if not colunas:          # o ``_edicoes`` (chamado antes) já recusa a técnica sem valores
        return
    inicio = min(c.indice for c in colunas)
    for col in colunas:
        anos: set[int] = set()
        for linha in topo:
            anos |= anos_do_rotulo(_rotulo_acima(linha, col.indice, inicio))
        if anos and col.ano not in anos:
            raise _recusa_layout(
                f"O cabeçalho acima de {col.nome} fala de {', '.join(map(str, sorted(anos)))}, "
                f"não de {col.ano}: o cabeçalho não confere com a linha técnica.")
        if col.familia == "aprovacao":
            for linha in topo:
                etapa = etapa_do_rotulo(_cel(linha, col.indice) or "")
                if etapa and etapa != col.etapa:
                    raise _recusa_layout(
                        f"O rótulo acima de {col.nome} é “{_cel(linha, col.indice)}”, mas o "
                        f"sufixo da variável é de {col.etapa.replace('_', ' ')}.")


# --- Leitura --------------------------------------------------------------------

def _nota(bruta: Sequence) -> str | None:
    for c in bruta:
        t = texto_celula(c)
        if t:
            return t[:_MAX_NOTA]
    return None


def _escola(linha: list[str], inep: str, colunas: list[Coluna], ids: dict[str, int],
            leitura: LeituraIdeb) -> EscolaIdeb:
    celulas = {}
    for col in colunas:
        bruto = _cel(linha, col.indice) or ""
        celula = ler_celula(bruto)
        if celula is None:
            raise _recusa_layout(
                f"Escola INEP {inep}: “{bruto}” em {col.nome} não é número nem marcador do "
                "INEP (“-”, “ND”).")
        if celula.valor is not None:
            minimo, maximo = _FAIXAS[col.familia]
            if not minimo <= celula.valor <= maximo:
                raise _recusa_layout(
                    f"Escola INEP {inep}: {col.nome} = {bruto} fora da faixa do "
                    f"{_NOME_FAMILIA[col.familia]} ({minimo:g} a {maximo:g}).")
            if celula.asterisco:
                leitura.asteriscos.append(f"INEP {inep} {col.nome}")
        else:
            leitura.marcadores[celula.marcador] += 1
        celulas[col.nome] = celula
    return EscolaIdeb(inep=inep, nome=_cel(linha, ids.get("NO_ESCOLA")) or "", celulas=celulas)


def ler_grade(linhas: Iterable[Sequence], *, codigo_ibge: str, nome: str = "",
              progresso: Callable[[int], None] | None = None) -> LeituraIdeb:
    """Lê as linhas da aba (valores do openpyxl OU texto do CSV do pacote) e recorta a
    rede municipal do município ``codigo_ibge``. Só as linhas recortadas ficam em
    memória. LEVANTA ``ImportacaoRecusada`` (layout, etapa, edição incompleta, valor
    que não é número nem marcador, fora da faixa, INEP repetido)."""
    it = iter(linhas)
    topo, tecnica = _achar_tecnica(it)
    colunas, ids, ignoradas = _mapear(tecnica)
    _conferir_etapa(topo)
    # As edições ANTES dos rótulos: a linha técnica sem nenhuma coluna de valor (só a
    # identificação) recusa com a causa, em vez de cair num ``min`` de lista vazia.
    edicoes, anos_meta = _edicoes(colunas)
    _conferir_rotulos(topo, colunas)
    leitura = LeituraIdeb(edicoes=edicoes, anos_meta=anos_meta, colunas=colunas, topo=topo,
                          tecnica=tecnica, colunas_ignoradas=ignoradas)
    j_id, j_mun, j_rede = ids["ID_ESCOLA"], ids["CO_MUNICIPIO"], ids["REDE"]
    vistos: set[str] = set()
    nomes_mun: set[str] = set()
    for bruta in it:
        if not bruta:
            continue
        codigo_escola = _codigo(_cel(bruta, j_id))
        if codigo_escola is None or len(codigo_escola) > 8:
            if _codigo(_cel(bruta, j_mun)) == codigo_ibge:
                raise _recusa_layout(
                    f"Uma linha do município {codigo_ibge} não tem código de escola válido "
                    f"(“{texto_celula(_cel(bruta, j_id))}” em ID_ESCOLA).")
            nota = _nota(bruta)                   # rodapé (fonte, legenda) ou linha vazia
            if nota and len(leitura.notas_linhas) < _MAX_NOTAS:
                leitura.notas_linhas.append([nota])
            continue
        leitura.linhas_lidas += 1
        if progresso and leitura.linhas_lidas % 10_000 == 0:
            progresso(leitura.linhas_lidas)
        if _codigo(_cel(bruta, j_mun)) != codigo_ibge:
            continue
        rede = normalizar_rede(texto_celula(_cel(bruta, j_rede)))
        if rede != "municipal":
            leitura.outras_redes[rede or "sem rede"] += 1
            continue
        # Sem o ruído do float: é este texto que vai para o pacote e para as casas.
        linha = _aparar([texto_sem_ruido(c) for c in bruta])
        inep = normalizar_inep(codigo_escola)
        if inep in vistos:
            raise _recusa_layout(f"O código INEP {inep} aparece em mais de uma linha da rede.")
        vistos.add(inep)
        leitura.recorte.append(linha)
        leitura.escolas.append(_escola(linha, inep, colunas, ids, leitura))
        if "NO_MUNICIPIO" in ids and _cel(linha, ids["NO_MUNICIPIO"]):
            nomes_mun.add(_cel(linha, ids["NO_MUNICIPIO"]))
    if leitura.recorte:
        for col in colunas:
            leitura.casas[col.nome] = max(
                (e.celulas[col.nome].casas for e in leitura.escolas
                 if e.celulas[col.nome].valor is not None), default=0)
    leitura.municipio_nome = next(iter(nomes_mun)) if len(nomes_mun) == 1 else None
    leitura.avisos = _avisos(leitura, codigo_ibge, nome, nomes_mun)
    return leitura


def _avisos(leitura: LeituraIdeb, codigo_ibge: str, nome: str, nomes_mun: set[str]) -> list[str]:
    avisos = []
    eds = leitura.edicoes
    avisos.append(f"Edições no arquivo: {', '.join(map(str, eds))}"
                  + (f"; metas do 1º ciclo: {', '.join(map(str, leitura.anos_meta))}."
                     if leitura.anos_meta else "; sem metas."))
    anos_nome = {int(a) for a in re.findall(r"(?<!\d)(20\d{2})(?!\d)", nome or "")}
    if len(anos_nome) == 1 and leitura.edicao_arquivo not in anos_nome:
        avisos.append(f"O nome do arquivo fala de {next(iter(anos_nome))}, mas a edição mais "
                      f"nova nas colunas é {leitura.edicao_arquivo} (vale a das colunas).")
    if not leitura.recorte:
        avisos.append(f"Nenhuma escola da rede MUNICIPAL do município {codigo_ibge} no "
                      "arquivo: nada a importar.")
        return avisos
    if len(nomes_mun) > 1:
        avisos.append(f"O município {codigo_ibge} aparece com mais de um nome no arquivo "
                      f"({', '.join(sorted(nomes_mun))}).")
    if leitura.outras_redes:
        avisos.append(f"{sum(leitura.outras_redes.values())} escola(s) do município em outra "
                      f"rede ({', '.join(sorted(leitura.outras_redes))}) ignorada(s): só entra "
                      "a rede municipal.")
    if leitura.marcadores:
        avisos.append("Sem número no recorte (viram ausência “não divulgado”, sem inventar "
                      "causa): " + ", ".join(f"“{m}” {n}×" for m, n in
                                             sorted(leitura.marcadores.items())) + ".")
    if leitura.asteriscos:
        avisos.append(f"{len(leitura.asteriscos)} número(s) com “*” (nota do INEP: média "
                      "calculada a partir das avaliações estaduais): "
                      + "; ".join(leitura.asteriscos[:10]) + ".")
    if leitura.colunas_ignoradas:
        avisos.append("Colunas não lidas: " + ", ".join(leitura.colunas_ignoradas) + ".")
    sem_meta = [a for a in eds if not leitura.anos_meta or a > max(leitura.anos_meta)]
    if sem_meta:
        avisos.append(f"O INEP não definiu meta do Ideb para {', '.join(map(str, sem_meta))} "
                      "(as metas do 1º ciclo vão até 2021): nada é gravado como meta dessas "
                      "edições.")
    avisos.append("A série do 5º ano não é comparável em todo o período (o universo do Saeb "
                  "mudou ao longo das edições — ver as notas do INEP)"
                  + ("; 2021 tem a nota própria da pandemia." if 2021 in eds else "."))
    return avisos


def cobertura_do_recorte(leitura: LeituraIdeb) -> dict[int, tuple[int, int]]:
    """``{edição: (escolas com Ideb, escolas com Saeb)}`` no recorte (sem cadastro)."""
    col = {(c.familia, c.ano): c.nome for c in leitura.colunas}
    saida = {}
    for ano in leitura.edicoes:
        com_ideb = sum(1 for e in leitura.escolas
                       if e.celulas[col[("ideb", ano)]].valor is not None)
        com_saeb = sum(1 for e in leitura.escolas if any(
            e.celulas[col[(f, ano)]].valor is not None for f in COMPONENTES))
        saida[ano] = (com_ideb, com_saeb)
    return saida


# --- Planilha (linha de comando) -------------------------------------------------

def linhas_da_planilha(wb) -> tuple[str, Iterator]:
    """``(nome da aba, linhas)`` da ÚNICA aba que tem a linha técnica do Ideb no topo
    (``ID_ESCOLA`` ou ``VL_OBSERVADO_AAAA`` — o Ideb de município/UF é reconhecido e
    recusado com a causa pelo ``ler_grade``) — pela assinatura, não pela posição nem
    pelo nome da aba."""
    achadas = []
    for aba in wb.worksheets:
        for linha in aba.iter_rows(max_row=_LINHAS_TOPO, values_only=True):
            nomes = [texto_celula(c).upper() for c in linha]
            if "ID_ESCOLA" in nomes or any(n.startswith("VL_OBSERVADO_") for n in nomes):
                achadas.append(aba)
                break
    if len(achadas) != 1:
        raise _recusa_layout(
            "Nenhuma aba tem a linha técnica do INEP (com ID_ESCOLA)." if not achadas else
            f"Mais de uma aba tem a linha técnica ({', '.join(a.title for a in achadas)}); não "
            "dá para saber qual vale.")
    return achadas[0].title, achadas[0].iter_rows(values_only=True)


# --- Recorte pelo cadastro (servidor) --------------------------------------------

def recortar(lido: LeituraIdeb, escolas_por_inep: dict[str, dict], *,
             codigo_ibge: str) -> tuple[seduc.LeituraSeduc, dict]:
    """Casa as escolas do recorte com o cadastro PELO INEP (``{inep: {"id",
    "rede_id", "nome"}}``) e produz as linhas no formato do fluxo de escolas
    (``pipeline_seduc``): ``escolares`` (Ideb e Saeb → ``resultados_avaliacao``) e
    ``referencia`` (N, P, aprovação e metas → ``indicadores_referencia``). Devolve
    também o que é só do Ideb (cobertura por edição, marcadores, notas, escolas do
    cadastro sem linha no arquivo)."""
    leitura = seduc.LeituraSeduc(parser=PARSER, edicao_arquivo=lido.edicao_arquivo,
                                 encoding="utf-8", linhas_lidas=lido.linhas_lidas,
                                 avisos=list(lido.avisos),
                                 colunas_ignoradas=list(lido.colunas_ignoradas))
    leitura.territorios[codigo_ibge] = lido.municipio_nome or codigo_ibge
    casadas = sorted(((e, escolas_por_inep[e.inep]) for e in lido.escolas
                      if e.inep in escolas_por_inep), key=lambda par: par[0].inep)
    leitura.fora_do_cadastro = sorted(
        ({"codigo_inep": e.inep, "nome_no_arquivo": e.nome} for e in lido.escolas
         if e.inep not in escolas_por_inep), key=lambda d: d["codigo_inep"])
    no_arquivo = {e.inep for e in lido.escolas}
    sem_linha = sorted(({"escola_id": alvo["id"], "escola": alvo.get("nome"),
                         "codigo_inep": inep}
                        for inep, alvo in escolas_por_inep.items() if inep not in no_arquivo),
                       key=lambda d: (d["escola"] or "", d["codigo_inep"]))
    por_familia: dict[tuple[str, int], Coluna] = {}
    aprovacao: dict[int, list[Coluna]] = defaultdict(list)
    for col in lido.colunas:
        if col.familia == "aprovacao":
            aprovacao[col.ano].append(col)
        else:
            por_familia[(col.familia, col.ano)] = col
    cobertura = {ano: {"ideb": 0, "saeb": 0} for ano in lido.edicoes}
    for e, alvo in casadas:
        for ano in lido.edicoes:
            ideb = e.celulas[por_familia[("ideb", ano)].nome]
            leitura.escolares.append(_linha_escola(
                AVALIACAO_IDEB, ano, IND_IDEB, e, alvo, ETAPA_IDEB, None, UNIDADE_IDEB, ideb))
            cobertura[ano]["ideb"] += ideb.valor is not None
            com_saeb = False
            for familia in ("saeb_matematica", "saeb_portugues"):
                celula = e.celulas[por_familia[(familia, ano)].nome]
                com_saeb |= celula.valor is not None
                leitura.escolares.append(_linha_escola(
                    AVALIACAO_SAEB, ano, IND_PROFICIENCIA, e, alvo, ETAPA_SAEB,
                    COMPONENTES[familia], UNIDADE_SAEB, celula))
            cobertura[ano]["saeb"] += com_saeb
            for familia, indicador, unidade in (("nota_n", IND_NOTA_N, UNIDADE_IDEB),
                                                ("rendimento_p", IND_RENDIMENTO_P, UNIDADE_P)):
                col = por_familia.get((familia, ano))
                if col is not None:
                    leitura.referencia.append(_ref(indicador, ano, e, col, lido, codigo_ibge,
                                                   unidade=unidade, etapa=ETAPA_IDEB))
            for col in sorted(aprovacao.get(ano, []), key=lambda c: c.indice):
                leitura.referencia.append(_ref(IND_APROVACAO, ano, e, col, lido, codigo_ibge,
                                               unidade=UNIDADE_APROVACAO, etapa=col.etapa))
        for ano in lido.anos_meta:
            leitura.referencia.append(_ref(IND_META, ano, e, por_familia[("meta", ano)], lido,
                                           codigo_ibge, unidade=UNIDADE_IDEB, etapa=ETAPA_IDEB,
                                           desenho=None))
    leitura.escolas_casadas = [
        {"escola_id": alvo["id"], "escola": alvo.get("nome"), "codigo_inep": e.inep,
         "nome_no_arquivo": e.nome}
        for e, alvo in sorted(casadas, key=lambda par: (par[1].get("nome") or "", par[0].inep))]
    if not casadas:
        leitura.avisos.append("Nenhuma escola da rede casou pelo código INEP: confira o INEP "
                              "no cadastro das escolas. Nada a importar.")
    if leitura.fora_do_cadastro:
        leitura.avisos.append(
            f"{len(leitura.fora_do_cadastro)} escola(s) da rede municipal no arquivo sem escola "
            "no cadastro do Constela com esse INEP (não importadas): "
            + ", ".join(d["codigo_inep"] for d in leitura.fora_do_cadastro[:15]) + ".")
    if sem_linha:
        leitura.avisos.append(
            f"{len(sem_linha)} escola(s) do cadastro com INEP sem linha neste arquivo (nada a "
            "importar para elas): " + ", ".join(d["codigo_inep"] for d in sem_linha[:15]) + ".")
    extra = {"edicoes": list(lido.edicoes), "anos_meta": list(lido.anos_meta),
             "cobertura": {str(a): c for a, c in cobertura.items()},
             "marcadores": dict(sorted(lido.marcadores.items())),
             "asteriscos": list(lido.asteriscos), "notas_arquivo": lido.notas,
             "sem_linha_no_arquivo": sem_linha}
    return leitura, extra


def _linha_escola(avaliacao: str, ano: int, indicador: str, e: EscolaIdeb, alvo: dict,
                  etapa: str, componente: str | None, unidade: str,
                  celula: Celula) -> seduc.LinhaEscola:
    return seduc.LinhaEscola(
        avaliacao=avaliacao, edicao=ano, indicador=indicador, escola_id=alvo["id"],
        rede_id=alvo.get("rede_id"), codigo_inep=e.inep, etapa=etapa, componente=componente,
        unidade=unidade, valor=celula.valor,
        motivo_ausencia=MOTIVO if celula.valor is None else None)


def _ref(indicador: str, ano: int, e: EscolaIdeb, col: Coluna, lido: LeituraIdeb,
         codigo_ibge: str, *, unidade: str, etapa: str,
         desenho: str | None = "censitario") -> seduc.NumeroReferencia:
    celula = e.celulas[col.nome]
    base = dict(indicador=indicador, edicao=ano, abrangencia="escola",
                codigo_territorio=codigo_ibge, codigo_inep=e.inep, rede_ensino="municipal",
                unidade=unidade, etapa=etapa, componente="", desenho=desenho)
    if celula.valor is None:
        linha = LinhaCanonica(valor=None, motivo_ausencia=MOTIVO, **base)
    else:
        linha = LinhaCanonica(valor=celula.valor, casas_decimais=lido.casas.get(col.nome),
                              **base)
    return seduc.NumeroReferencia(AVALIACAO_IDEB, linha)
