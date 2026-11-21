"""Parsers ``inep_ideb_municipios`` e ``inep_ideb_uf_brasil``: o Ideb dos ANOS
INICIAIS da REDE municipal (arquivo por município), de SP e do Brasil (arquivos de
UF/regiões e de Brasil) — etapa E6b dos indicadores oficiais.

Funções PURAS (linhas da planilha → leitura + avisos, sem banco nem rede), usadas nos
DOIS caminhos com o MESMO código, como o Ideb por escola (``ideb``): nesta máquina,
pela linha de comando ``preparar``, sobre o xlsx inteiro do zip do INEP (o de
municípios tem ~12 MB comprimidos e ~14,5 mil linhas, lido em STREAMING); no
servidor, sobre o PACOTE recortado (``pacote_ideb``): o topo da planilha + só as
linhas do território, em CSV de texto.

LAYOUT REAL (conferido nos arquivos de 2025 de municípios, de UF/regiões e de
Brasil):

* o MESMO topo do arquivo por escola — título com a etapa, grupos por edição com o
  dígito de nota de rodapé grudado no ano ("20212"), séries ("1º ao 5º ano", "1º"…),
  a meta do 1º ciclo e a LINHA TÉCNICA (``VL_OBSERVADO_AAAA``, ``VL_NOTA_*``,
  ``VL_INDICADOR_REND_AAAA``, ``VL_APROVACAO_AAAA_SI_4``… ``VL_PROJECAO_AAAA``);
  edições 2005–2025 e metas 2007–2021, lidas PELO NOME (o leitor de colunas, de
  rótulos e de marcadores é o do ``ideb``);
* MUNICÍPIOS: uma aba; identificação ``SG_UF``, ``CO_MUNICIPIO``, ``NO_MUNICIPIO`` e
  ``REDE`` na linha técnica; uma linha por município × rede ("Municipal",
  "Pública", "Estadual"…);
* UF/REGIÕES e BRASIL: TRÊS abas (anos iniciais, anos finais e ensino médio) — vale
  a dos ANOS INICIAIS, escolhida PELO TOPO (nunca pela posição nem pelo nome da
  aba). No de Brasil a linha técnica traz ``BRASIL`` e ``rede``; no de UF as duas
  colunas de identificação NÃO têm nome técnico, só o rótulo legível
  ("Região/Unidade da Federação" e "Rede"), e a UF vem pelo NOME — o arquivo não traz
  código. O nome casa EXATAMENTE (sem acento e sem caixa) com a tabela fixa das 27
  UFs do IBGE, inclusive as abreviações do INEP ("R. G. do Sul", "M. G. do Sul"),
  e vira o código da UF; as regiões ficam de fora; nome fora da tabela não casa
  (aviso). Se uma versão futura trouxer ``CO_UF``/``SG_UF``, vale o código;
* a REDE com dígito de nota de rodapé ("Total (3)(4)", "Pública (4)", "Privada (1)"):
  o rótulo é normalizado e o TEXTO da nota (do rodapé) vai para os avisos;
* nome técnico REPETIDO (no arquivo de UF de 2025, ``VL_INDICADOR_REND_2023`` aparece
  também no lugar do P de 2025, sob o grupo "Taxa de Aprovação - 2025"): vale a
  ocorrência cujo cabeçalho legível confere com o ano do nome; a outra NÃO é lida e
  fica no aviso — nunca se adivinha a variável. Sem uma única ocorrência que confira:
  recusa;
* marcadores "-", "ND", "ND*"… = AUSÊNCIA ``nao_divulgado``; número com "*" ou "**"
  (médias com uma ressalva da legenda do INEP: calculadas das avaliações estaduais ou
  com participação baixa) vale como número, com aviso.

RECORTE — pelo CÓDIGO, nunca pelo nome do município: ``CO_MUNICIPIO`` = IBGE da rede.
A linha da rede MUNICIPAL é gravada como a do município; as outras redes do município
no arquivo (Pública, Estadual...) ficam REGISTRADAS no resumo e nos avisos, nunca
gravadas como a municipal. UF = a UF do IBGE da rede (os 2 primeiros dígitos) e
Brasil: as redes total, pública, estadual e municipal que o arquivo trouxer (a
privada fica de fora: a comparação é com a rede pública).

ONDE VAI (sem poluir a correlação nem as opções, que só leem ``resultados_avaliacao``):
``indicadores_referencia``, avaliação ``ideb``, abrangência
``municipio``/``uf``/``brasil`` (território = IBGE, "35" ou "BR") e ``rede_ensino`` da
coluna REDE — a comparação é SEMPRE na mesma rede (plano, 4.8). Indicadores:
``ideb`` (índice), ``nota_saeb`` (LP/MT do 5º ano: a nota do Saeb que entra no Ideb;
a média da planilha do Saeb é outra chave — ``saeb``/``proficiencia``), ``nota_n``,
``rendimento_p``, ``aprovacao`` (1º–5º e por série) e ``meta`` (edição = ano da meta).
Sem número: valor nulo + ``nao_divulgado``. A precisão gravada é a da FAMÍLIA no
recorte (o Ideb de 1 casa continua com 1 casa quando um ano sai inteiro).

UNIVERSO DA NOTA DO SAEB (plano, 4.2: "o Ideb municipal usa só as escolas urbanas; isso
vai no rótulo"). O arquivo do Ideb não diz de que escolas é a nota do Saeb que entra
nele (nem no rodapé); conferida contra a planilha do Saeb do INEP nas edições que ela
cobre (2019, 2021 e 2025), ela é a média das escolas URBANAS no município e na UF (todas
as redes) e, no Brasil, nas redes municipal e estadual; só no Brasil das redes pública e
total ela é a de TODAS as escolas (a "Total" da planilha, urbanas e rurais). O N e o
Ideb saem dessa nota. A chave gravada continua ``localizacao='total'`` — é o Ideb
OFICIAL do território, que o arquivo não divide por localização —, e o universo vai no
RÓTULO (``universo_saeb``/``rotulo_universo``), nos avisos e no resumo da importação.
Por isso a média do Saeb do 5º ano do território (``saeb``/``proficiencia``, Total ×
Urbana × Rural) vem só da planilha, com a localização explícita: a ``nota_saeb`` daqui
nunca é emendada na série da planilha nem cruzada com ela.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator, Sequence

from app.services.avaliacoes import ImportacaoRecusada
from app.services.indicadores import ideb, seduc
from app.services.indicadores.ica import CODIGO_BRASIL, LinhaCanonica, normalizar_rede

PARSER_MUNICIPIOS = ideb.PARSER_MUNICIPIOS
PARSER_UF_BRASIL = ideb.PARSER_UF_BRASIL
PARSERS = (PARSER_MUNICIPIOS, PARSER_UF_BRASIL)
VERSAO_PARSER = "1"

ABR_MUNICIPIO, ABR_UF, ABR_BRASIL = "municipio", "uf", "brasil"
IND_NOTA_SAEB = "nota_saeb"           # a nota do Saeb (LP/MT) que entra no Ideb
COMPONENTES = {"saeb_matematica": "mt", "saeb_portugues": "lp"}
REDES_GRAVADAS = ("total", "publica", "estadual", "municipal")
UNIDADE = {"ideb": ideb.UNIDADE_IDEB, "nota_n": ideb.UNIDADE_IDEB, "meta": ideb.UNIDADE_IDEB,
           "rendimento_p": ideb.UNIDADE_P, "aprovacao": ideb.UNIDADE_APROVACAO,
           "saeb_matematica": ideb.UNIDADE_SAEB, "saeb_portugues": ideb.UNIDADE_SAEB}
INDICADOR = {"ideb": ideb.IND_IDEB, "nota_n": ideb.IND_NOTA_N,
             "rendimento_p": ideb.IND_RENDIMENTO_P, "aprovacao": ideb.IND_APROVACAO,
             "meta": ideb.IND_META, "saeb_matematica": IND_NOTA_SAEB,
             "saeb_portugues": IND_NOTA_SAEB}

# Universo da nota do Saeb que entra no Ideb do território (ver a docstring do módulo).
UNIVERSO_URBANAS = "urbanas"          # só as escolas urbanas (≠ a "Total" da planilha)
UNIVERSO_TODAS = "todas"              # urbanas e rurais (= a "Total" da planilha)
_REDES_BRASIL_TODAS = ("publica", "total")
_NOME_REDE = {"total": "total", "publica": "pública", "estadual": "estadual",
              "municipal": "municipal"}
# O que sai da nota do Saeb (o universo vale para eles; P, aprovação e meta, não).
INDICADORES_DO_UNIVERSO = (ideb.IND_IDEB, IND_NOTA_SAEB, ideb.IND_NOTA_N)
ROTULO_UNIVERSO = {
    UNIVERSO_URBANAS: ("Só escolas urbanas (universo do INEP no Ideb): não é a média “Total” "
                       "da planilha do Saeb, que inclui as rurais."),
    UNIVERSO_TODAS: ("Escolas urbanas e rurais (universo do INEP no Ideb): a mesma base da "
                     "média “Total” da planilha do Saeb."),
}

_LINHAS_TOPO = 20
_MAX_NOTAS = 40

ARQUIVO = ('o arquivo oficial do INEP "Ideb por município" '
           "(divulgacao_anos_iniciais_municipios_AAAA.zip) ou o de UF/regiões ou de "
           "Brasil (divulgacao_regioes_ufs_ideb_AAAA.zip, divulgacao_brasil_ideb_AAAA.zip)")

# As 27 UFs (código e nome do IBGE) e as abreviações que o INEP usa no arquivo de UF.
# Tabela FIXA: a UF casa só por igualdade exata do nome normalizado — nunca aproximado.
UFS = {
    "11": ("Rondônia", "RO"), "12": ("Acre", "AC"), "13": ("Amazonas", "AM"),
    "14": ("Roraima", "RR"), "15": ("Pará", "PA"), "16": ("Amapá", "AP"),
    "17": ("Tocantins", "TO"), "21": ("Maranhão", "MA"), "22": ("Piauí", "PI"),
    "23": ("Ceará", "CE"), "24": ("Rio Grande do Norte", "RN"), "25": ("Paraíba", "PB"),
    "26": ("Pernambuco", "PE"), "27": ("Alagoas", "AL"), "28": ("Sergipe", "SE"),
    "29": ("Bahia", "BA"), "31": ("Minas Gerais", "MG"), "32": ("Espírito Santo", "ES"),
    "33": ("Rio de Janeiro", "RJ"), "35": ("São Paulo", "SP"), "41": ("Paraná", "PR"),
    "42": ("Santa Catarina", "SC"), "43": ("Rio Grande do Sul", "RS"),
    "50": ("Mato Grosso do Sul", "MS"), "51": ("Mato Grosso", "MT"), "52": ("Goiás", "GO"),
    "53": ("Distrito Federal", "DF"),
}
_ABREVIACOES_INEP = {"R. G. do Norte": "24", "R. G. do Sul": "43", "M. G. do Sul": "50"}
REGIOES = ("Norte", "Nordeste", "Sudeste", "Sul", "Centro-Oeste")

_RE_NOTA_REDE = re.compile(r"\(\s*(\d{1,2})\s*\)")
_RE_NOTA_RODAPE = re.compile(r"^\s*(?:Notas?\s*:\s*)?\(\s*(\d{1,2})\s*\)\s*[-–—:]?\s*(.+)$")


def chave_nome(texto: str) -> str:
    """Nome comparável: sem acento, sem caixa, pontuação e espaços colapsados
    ("São Paulo" → "sao paulo"; "R. G. do Sul" → "r g do sul")."""
    return re.sub(r"[^a-z0-9]+", " ", seduc.sem_acento(texto or "").casefold()).strip()


_UF_POR_NOME = {chave_nome(nome): codigo for codigo, (nome, _) in UFS.items()}
_UF_POR_NOME.update({chave_nome(nome): codigo for nome, codigo in _ABREVIACOES_INEP.items()})
_UF_POR_SIGLA = {sigla: codigo for codigo, (_, sigla) in UFS.items()}
_REGIOES = {chave_nome(r) for r in REGIOES}


def uf_do_nome(texto: str) -> str | None:
    """Código da UF pelo nome EXATO (normalizado) ou None."""
    return _UF_POR_NOME.get(chave_nome(texto))


def universo_saeb(abrangencia: str, rede: str) -> str:
    """De que escolas é a nota do Saeb (e o N e o Ideb) do arquivo do Ideb nesta
    abrangência e rede: ``urbanas`` (município, UF e Brasil municipal/estadual) ou
    ``todas`` (só Brasil pública e total)."""
    if abrangencia == ABR_BRASIL and rede in _REDES_BRASIL_TODAS:
        return UNIVERSO_TODAS
    return UNIVERSO_URBANAS


def rotulo_universo(abrangencia: str, rede: str) -> str:
    """O rótulo da tela para o Ideb, o N e a nota do Saeb do território nesta rede."""
    return ROTULO_UNIVERSO[universo_saeb(abrangencia, rede)]


# --- Células ------------------------------------------------------------------

# A limpeza do ruído binário do float é a MESMA do Ideb por escola (``ideb.texto_limpo``).
texto_limpo = ideb.texto_limpo


def ler_celula(texto: str) -> ideb.Celula | None:
    """Como ``ideb.ler_celula``, aceitando "*", "**" e "***" depois do número (as
    médias com nota da legenda do INEP: valem como número, com aviso)."""
    s = (texto or "").strip()
    if s.endswith("*") and not ideb._RE_ND.match(s.upper()):
        base = s.rstrip("*").strip()
        celula = ideb.ler_celula(base)
        if celula is None or celula.valor is None:
            return None
        return ideb.Celula(celula.valor, celula.casas, None, True)
    return ideb.ler_celula(s)


def _aparar(linha: list[str]) -> list[str]:
    fim = len(linha)
    while fim and not linha[fim - 1]:
        fim -= 1
    return linha[:fim]


def _cel(linha: Sequence, j: int | None):
    return linha[j] if j is not None and 0 <= j < len(linha) else None


def _recusa_layout(texto: str) -> ImportacaoRecusada:
    return ImportacaoRecusada(f"{texto} Confira se é {ARQUIVO}. Nada foi gravado.")


# --- Estruturas ---------------------------------------------------------------

@dataclass(frozen=True)
class LinhaTerritorio:
    """Uma linha do território (uma rede) — já lida e validada."""

    codigo: str             # IBGE (7) | UF (2) | "BR"
    nome: str               # como no arquivo
    rede: str               # normalizada: total | publica | estadual | municipal | privada…
    rotulo_rede: str        # como no arquivo ("Total (4)")
    notas: tuple[str, ...]  # números das notas de rodapé grudadas no rótulo da rede
    celulas: dict           # nome técnico → ideb.Celula


@dataclass
class LeituraTerritorio:
    """O que o parser entendeu do arquivo (nada gravado)."""

    parser: str
    abrangencia: str                     # municipio | uf | brasil
    edicoes: list[int]
    anos_meta: list[int]
    colunas: list[ideb.Coluna]
    topo: list[list[str]]
    tecnica: list[str]
    alvo: str                            # código do território recortado
    recorte: list[list[str]] = field(default_factory=list)       # linhas do território
    notas_linhas: list[list[str]] = field(default_factory=list)
    linhas: list[LinhaTerritorio] = field(default_factory=list)
    linhas_lidas: int = 0
    casas: dict = field(default_factory=dict)                     # família → casas
    marcadores: Counter = field(default_factory=Counter)
    asteriscos: list[str] = field(default_factory=list)
    colunas_ignoradas: list[str] = field(default_factory=list)
    colunas_repetidas: list[str] = field(default_factory=list)
    nao_reconhecidos: list[str] = field(default_factory=list)     # nomes fora da tabela
    avisos: list[str] = field(default_factory=list)

    @property
    def edicao_arquivo(self) -> int:
        return max(self.edicoes)

    @property
    def notas(self) -> list[str]:
        return [ln[0] for ln in self.notas_linhas if ln]

    @property
    def nome_territorio(self) -> str | None:
        nomes = {ln.nome for ln in self.linhas if ln.nome}
        return next(iter(nomes)) if len(nomes) == 1 else None


# --- Cabeçalho ------------------------------------------------------------------

def _achar_tecnica(it: Iterator) -> tuple[list[list[str]], list[str]]:
    topo: list[list[str]] = []
    for i, bruta in enumerate(it):
        if i >= _LINHAS_TOPO:
            break
        linha = _aparar([texto_limpo(c) for c in (bruta or ())])
        nomes = {c.upper() for c in linha}
        if "ID_ESCOLA" in nomes:
            raise ImportacaoRecusada(
                f"Este arquivo é o Ideb POR ESCOLA ({ideb.PARSER}), que tem o seu parser; "
                "aqui entra o Ideb do município, da UF ou do Brasil. Nada foi gravado.")
        if any(n.startswith("VL_OBSERVADO_") for n in nomes):
            return topo, linha
        if linha:
            topo.append(linha)
    raise _recusa_layout(
        f"Não encontrei a linha técnica do INEP (com VL_OBSERVADO_AAAA) nas primeiras "
        f"{_LINHAS_TOPO} linhas.")


def _e_coluna_de_valor(nome: str) -> bool:
    return bool(ideb._RE_APROVACAO.match(nome)) or any(r.match(nome) for r, _ in ideb._RE_COLUNAS)


def _rotulo_legivel(topo: list[list[str]], j: int) -> str:
    """O rótulo legível da coluna de identificação ``j`` (o mais baixo do topo)."""
    for linha in reversed(topo):
        valor = _cel(linha, j)
        if valor:
            return valor
    return ""


@dataclass(frozen=True)
class _Layout:
    parser: str
    abrangencia: str
    j_territorio: int
    tipo_territorio: str          # codigo_ibge | codigo_uf | sigla_uf | nome_uf | brasil
    j_rede: int
    j_nome: int | None = None


def _layout(topo: list[list[str]], tecnica: list[str]) -> _Layout:
    nomes = [c.strip().upper() for c in tecnica]
    valores = [j for j, n in enumerate(nomes) if n and _e_coluna_de_valor(n)]
    if not valores:
        raise _recusa_layout("A linha técnica não tem nenhuma edição do Ideb "
                             "(VL_OBSERVADO_AAAA, VL_NOTA_MATEMATICA_AAAA...).")
    primeira = min(valores)
    if "CO_MUNICIPIO" in nomes:
        if "REDE" not in nomes:
            raise _recusa_layout("O arquivo não tem a coluna REDE.")
        return _Layout(PARSER_MUNICIPIOS, ABR_MUNICIPIO, nomes.index("CO_MUNICIPIO"),
                       "codigo_ibge", nomes.index("REDE"),
                       nomes.index("NO_MUNICIPIO") if "NO_MUNICIPIO" in nomes else None)
    j_rede = j_terr = None
    tipo = None
    for j in range(primeira):
        tecnico = nomes[j] if j < len(nomes) else ""
        legivel = chave_nome(_rotulo_legivel(topo, j))
        if tecnico == "REDE" or (not tecnico and legivel == "rede"):
            j_rede = j
        elif tecnico == "BRASIL" or (not tecnico and legivel == "brasil"):
            j_terr, tipo = j, "brasil"
        elif tecnico == "CO_UF":
            j_terr, tipo = j, "codigo_uf"
        elif tecnico == "SG_UF" and tipo != "codigo_uf":
            j_terr, tipo = j, "sigla_uf"
        elif (tecnico == "NO_UF" or (not tecnico and "unidade da federacao" in legivel)) \
                and tipo not in ("codigo_uf", "sigla_uf"):
            j_terr, tipo = j, "nome_uf"
    if j_rede is None or j_terr is None:
        raise _recusa_layout("Não reconheci as colunas de identificação (a rede e o "
                             "município, a UF ou o Brasil) antes das colunas de valor.")
    return _Layout(PARSER_UF_BRASIL, ABR_BRASIL if tipo == "brasil" else ABR_UF, j_terr,
                   tipo, j_rede)


def _colunas(topo: list[list[str]], tecnica: list[str], layout: _Layout
             ) -> tuple[list[ideb.Coluna], list[str], list[str]]:
    """As colunas de valor PELO NOME; o nome repetido é resolvido pelo cabeçalho
    legível (vale a ocorrência que confere com o ano do nome) — ``(colunas,
    ignoradas, repetidas)``."""
    identificacao = {layout.j_territorio, layout.j_rede, layout.j_nome}
    candidatas: list[ideb.Coluna] = []
    ignoradas: list[str] = []
    for j, bruto in enumerate(tecnica):
        nome = bruto.strip().upper()
        if not nome or j in identificacao or nome in ("SG_UF", "NO_MUNICIPIO", "CO_UF",
                                                      "NO_UF"):
            continue
        casou = ideb._RE_APROVACAO.match(nome)
        if casou:
            candidatas.append(ideb.Coluna(bruto.strip(), j, "aprovacao", int(casou.group(1)),
                                          ideb._ETAPA_APROVACAO[casou.group(2)]))
            continue
        for regex, familia in ideb._RE_COLUNAS:
            casou = regex.match(nome)
            if casou:
                candidatas.append(ideb.Coluna(bruto.strip(), j, familia, int(casou.group(1))))
                break
        else:
            ignoradas.append(bruto.strip())
    if not candidatas:
        raise _recusa_layout("A linha técnica não tem nenhuma edição do Ideb.")
    inicio = min(c.indice for c in candidatas)
    por_nome: dict[str, list[ideb.Coluna]] = {}
    for c in candidatas:
        por_nome.setdefault(c.nome.upper(), []).append(c)
    colunas: list[ideb.Coluna] = []
    repetidas: list[str] = []
    for nome, ocorrencias in por_nome.items():
        if len(ocorrencias) == 1:
            colunas.append(ocorrencias[0])
            continue
        conferem = []
        for c in ocorrencias:
            anos: set[int] = set()
            for linha in topo:
                anos |= ideb.anos_do_rotulo(ideb._rotulo_acima(linha, c.indice, inicio))
            if c.ano in anos:
                conferem.append(c)
        if len(conferem) != 1:
            raise _recusa_layout(f"A coluna {nome} aparece {len(ocorrencias)} vezes na linha "
                                 "técnica e o cabeçalho legível não diz qual delas vale.")
        colunas.append(conferem[0])
        for c in ocorrencias:
            if c is not conferem[0]:
                grupo = next((ideb._rotulo_acima(linha, c.indice, inicio) for linha in topo
                              if ideb.anos_do_rotulo(ideb._rotulo_acima(linha, c.indice,
                                                                        inicio))), "")
                repetidas.append(f"{nome} (coluna {c.indice + 1}"
                                 + (f", sob “{grupo.replace(chr(10), ' ')}”" if grupo else "")
                                 + ")")
    colunas.sort(key=lambda c: c.indice)
    return colunas, ignoradas, repetidas


# --- Leitura --------------------------------------------------------------------

def _rede(rotulo: str) -> tuple[str, tuple[str, ...]]:
    """"Total (3)(4)" → ("total", ("3", "4")); "Pública" → ("publica", ())."""
    notas = tuple(_RE_NOTA_REDE.findall(rotulo or ""))
    return normalizar_rede(_RE_NOTA_REDE.sub(" ", rotulo or "")), notas


def _nota(bruta: Sequence) -> str | None:
    for c in bruta:
        t = texto_limpo(c)
        if t:
            return t[:400]
    return None


def _codigo_do_territorio(layout: _Layout, valor: str, leitura: LeituraTerritorio) -> str | None:
    """O código do território da linha (ou None: região, Brasil no arquivo de UF, nome
    fora da tabela — este último fica listado)."""
    if layout.tipo_territorio == "brasil":
        if chave_nome(valor) == "brasil":
            return CODIGO_BRASIL
        leitura.nao_reconhecidos.append(valor)
        return None
    if layout.tipo_territorio == "codigo_uf":
        codigo = ideb._codigo(valor)
        return codigo if codigo in UFS else None
    if layout.tipo_territorio == "sigla_uf":
        return _UF_POR_SIGLA.get(valor.strip().upper())
    chave = chave_nome(valor)
    if chave in _REGIOES or chave == "brasil":
        return None
    codigo = _UF_POR_NOME.get(chave)
    if codigo is None and valor not in leitura.nao_reconhecidos:
        leitura.nao_reconhecidos.append(valor)
    return codigo


def _alvo(layout: _Layout, codigo_ibge: str) -> str:
    if layout.abrangencia == ABR_MUNICIPIO:
        return codigo_ibge
    return CODIGO_BRASIL if layout.abrangencia == ABR_BRASIL else codigo_ibge[:2]


def ler_grade(linhas: Iterable[Sequence], *, codigo_ibge: str, nome: str = "",
              progresso: Callable[[int], None] | None = None) -> LeituraTerritorio:
    """Lê as linhas da aba (valores do openpyxl OU texto do CSV do pacote) e recorta o
    território: o município ``codigo_ibge``, a UF dele ou o Brasil (pelo layout do
    arquivo). Só as linhas do território ficam em memória. LEVANTA
    ``ImportacaoRecusada`` (layout, etapa, edição incompleta, nome repetido sem
    resolução, valor que não é número nem marcador, fora da faixa, rede repetida)."""
    it = iter(linhas)
    topo, tecnica = _achar_tecnica(it)
    layout = _layout(topo, tecnica)
    try:
        # As guardas do Ideb por escola (etapa, edição completa, rótulo × técnica), com
        # a recusa dizendo QUAL arquivo era esperado aqui.
        ideb._conferir_etapa(topo)
        colunas, ignoradas, repetidas = _colunas(topo, tecnica, layout)
        edicoes, anos_meta = ideb._edicoes(colunas)
        ideb._conferir_rotulos(topo, colunas)
    except ImportacaoRecusada as exc:
        raise ImportacaoRecusada(str(exc).replace(ideb.ARQUIVO, ARQUIVO)) from exc
    leitura = LeituraTerritorio(parser=layout.parser, abrangencia=layout.abrangencia,
                                edicoes=edicoes, anos_meta=anos_meta, colunas=colunas,
                                topo=topo, tecnica=tecnica, alvo=_alvo(layout, codigo_ibge),
                                colunas_ignoradas=ignoradas, colunas_repetidas=repetidas)
    vistas: set[str] = set()
    for bruta in it:
        if not bruta:
            continue
        if layout.abrangencia == ABR_MUNICIPIO:
            codigo = ideb._codigo(_cel(bruta, layout.j_territorio))
            if codigo is None:
                nota = _nota(bruta)              # rodapé (fonte, legenda) ou linha vazia
                if nota and len(leitura.notas_linhas) < _MAX_NOTAS:
                    leitura.notas_linhas.append([nota])
                continue
            if len(codigo) != 7:
                raise _recusa_layout(f"“{codigo}” em CO_MUNICIPIO não é um código IBGE de "
                                     "município (7 dígitos).")
            nome_territorio = texto_limpo(_cel(bruta, layout.j_nome))
        else:
            rotulo = texto_limpo(_cel(bruta, layout.j_rede))
            valor = texto_limpo(_cel(bruta, layout.j_territorio))
            if not rotulo:
                nota = _nota(bruta)              # rodapé (fonte, notas) ou linha vazia
                if nota and len(leitura.notas_linhas) < _MAX_NOTAS:
                    leitura.notas_linhas.append([nota])
                continue
            if not valor:
                raise _recusa_layout(f"Uma linha da rede “{rotulo}” não diz o território "
                                     "(célula vazia na coluna da UF/Brasil).")
            codigo = _codigo_do_territorio(layout, valor, leitura)
            nome_territorio = valor
        leitura.linhas_lidas += 1
        if progresso and leitura.linhas_lidas % 5_000 == 0:
            progresso(leitura.linhas_lidas)
        if codigo != leitura.alvo:
            continue
        linha = _aparar([texto_limpo(c) for c in bruta])
        rotulo = _cel(linha, layout.j_rede) or ""
        rede, notas = _rede(rotulo)
        if not rede:
            raise _recusa_layout(f"Uma linha do território {leitura.alvo} não tem a rede.")
        if rede in vistas:
            raise _recusa_layout(f"A rede “{rotulo}” aparece em mais de uma linha do "
                                 f"território {leitura.alvo}.")
        vistas.add(rede)
        celulas = {}
        for col in colunas:
            bruto = _cel(linha, col.indice) or ""
            celula = ler_celula(bruto)
            if celula is None:
                raise _recusa_layout(
                    f"{nome_territorio} ({rotulo}): “{bruto}” em {col.nome} não é número nem "
                    "marcador do INEP (“-”, “ND”).")
            if celula.valor is not None:
                minimo, maximo = ideb._FAIXAS[col.familia]
                if not minimo <= celula.valor <= maximo:
                    raise _recusa_layout(
                        f"{nome_territorio} ({rotulo}): {col.nome} = {bruto} fora da faixa do "
                        f"{ideb._NOME_FAMILIA[col.familia]} ({minimo:g} a {maximo:g}).")
                if celula.asterisco:
                    leitura.asteriscos.append(f"{rotulo} {col.nome}")
            else:
                leitura.marcadores[celula.marcador] += 1
            celulas[col.nome] = celula
        leitura.recorte.append(linha)
        leitura.linhas.append(LinhaTerritorio(codigo=leitura.alvo, nome=nome_territorio,
                                              rede=rede, rotulo_rede=rotulo, notas=notas,
                                              celulas=celulas))
    for col in colunas:
        casas = max((ln.celulas[col.nome].casas for ln in leitura.linhas
                     if ln.celulas[col.nome].valor is not None), default=0)
        leitura.casas[col.familia] = max(leitura.casas.get(col.familia, 0), casas)
    leitura.avisos = _avisos(leitura, nome)
    return leitura


def notas_de_rodape(notas: list[str]) -> dict[str, str]:
    """``{"4": "Médias do SAEB 2011..."}`` a partir das linhas do rodapé ("(4) ...",
    "Notas: (1) ...")."""
    saida: dict[str, str] = {}
    for texto in notas:
        casou = _RE_NOTA_RODAPE.match(texto or "")
        if casou and casou.group(1) not in saida:
            saida[casou.group(1)] = casou.group(2).strip()
    return saida


def _do_territorio(leitura: LeituraTerritorio) -> str:
    """"do Brasil", "da UF 35 (São Paulo)", "do município 3599999"."""
    if leitura.abrangencia == ABR_BRASIL:
        return "do Brasil"
    if leitura.abrangencia == ABR_UF:
        return f"da UF {leitura.alvo} ({UFS.get(leitura.alvo, ('?',))[0]})"
    return f"do município {leitura.alvo}"


def _redes_gravadas(leitura: LeituraTerritorio) -> list[str]:
    """As redes do recorte que viram número, na ordem do arquivo."""
    gravadas = ("municipal",) if leitura.abrangencia == ABR_MUNICIPIO else REDES_GRAVADAS
    return [ln.rede for ln in leitura.linhas if ln.rede in gravadas]


def _aviso_universo(leitura: LeituraTerritorio) -> str | None:
    """O universo da nota do Saeb (e do N e do Ideb) das redes gravadas — o rótulo que
    o arquivo não traz."""
    redes = _redes_gravadas(leitura)
    if not redes:
        return None
    por_universo: dict[str, list[str]] = {}
    for rede in redes:
        por_universo.setdefault(universo_saeb(leitura.abrangencia, rede), []).append(rede)
    partes = []
    for universo, nomes in por_universo.items():
        quem = ("das escolas URBANAS" if universo == UNIVERSO_URBANAS
                else "de TODAS as escolas (urbanas e rurais, a base da “Total” da planilha)")
        if leitura.abrangencia != ABR_MUNICIPIO:
            nomes = [_NOME_REDE.get(r, r) for r in nomes]
            quem += (f" na rede {nomes[0]}" if len(nomes) == 1 else
                     f" nas redes {', '.join(nomes[:-1])} e {nomes[-1]}")
        partes.append(quem)
    return (f"Universo do INEP no Ideb {_do_territorio(leitura)}: a nota do Saeb (e, com ela, "
            f"o N e o Ideb) é a {'; a '.join(partes)} — o arquivo não diz; conferido contra a "
            "planilha do Saeb nas edições que ela cobre (2019, 2021 e 2025). Gravados como o "
            "Ideb oficial do território (localização “total” na chave), com este rótulo. A "
            "nota “só urbanas” NÃO é a média “Total” da planilha: a média do Saeb do 5º ano "
            "do território vem só da planilha, com a localização explícita, e nunca é "
            "emendada nem cruzada com esta nota.")


def _avisos(leitura: LeituraTerritorio, nome: str) -> list[str]:
    avisos = [f"Edições no arquivo: {', '.join(map(str, leitura.edicoes))}"
              + (f"; metas do 1º ciclo: {', '.join(map(str, leitura.anos_meta))}."
                 if leitura.anos_meta else "; sem metas.")]
    anos_nome = {int(a) for a in re.findall(r"(?<!\d)(20\d{2})(?!\d)", nome or "")}
    if len(anos_nome) == 1 and leitura.edicao_arquivo not in anos_nome:
        avisos.append(f"O nome do arquivo fala de {next(iter(anos_nome))}, mas a edição mais "
                      f"nova nas colunas é {leitura.edicao_arquivo} (vale a das colunas).")
    for repetida in leitura.colunas_repetidas:
        avisos.append(f"Nome técnico repetido na linha técnica: {repetida} não confere com o "
                      "cabeçalho legível e NÃO foi lida (o número dessa coluna fica fora "
                      "desta importação; nada é adivinhado).")
    if not leitura.linhas:
        avisos.append(f"Nenhuma linha {_do_territorio(leitura)} no arquivo: nada a "
                      "importar.")
        return avisos
    redes = [ln.rede for ln in leitura.linhas]
    if leitura.abrangencia == ABR_MUNICIPIO:
        outras = [ln.rotulo_rede for ln in leitura.linhas if ln.rede != "municipal"]
        if "municipal" not in redes:
            avisos.append(f"O município {leitura.alvo} não tem linha da rede MUNICIPAL no "
                          "arquivo: nada é gravado (outra rede NUNCA vira a municipal).")
        if outras:
            avisos.append(f"Outras redes do município no arquivo, registradas e NÃO gravadas "
                          f"(a do município é a rede MUNICIPAL): {', '.join(outras)}.")
    else:
        fora = [ln.rotulo_rede for ln in leitura.linhas if ln.rede not in REDES_GRAVADAS]
        if fora:
            avisos.append(f"Redes {_do_territorio(leitura)} não gravadas (a comparação é "
                          f"com a rede pública): {', '.join(fora)}.")
        if "municipal" not in redes:
            avisos.append(f"O arquivo não traz a rede MUNICIPAL {_do_territorio(leitura)}: "
                          "a comparação da rede municipal na MESMA rede fica sem este "
                          "território (nada é estimado no lugar).")
    if leitura.nao_reconhecidos:
        avisos.append("Territórios fora da tabela das UFs do IBGE (não casam): "
                      + ", ".join(leitura.nao_reconhecidos[:10]) + ".")
    universo = _aviso_universo(leitura)
    if universo:
        avisos.append(universo)
    textos = notas_de_rodape(leitura.notas)
    for ln in leitura.linhas:
        for n in ln.notas:
            avisos.append(f"{ln.nome} — {ln.rotulo_rede}: nota ({n}) do INEP"
                          + (f": {textos[n]}" if n in textos else " (texto não encontrado no "
                             "rodapé)."))
    if leitura.marcadores:
        avisos.append("Sem número no recorte (viram ausência “não divulgado”, sem inventar "
                      "causa): " + ", ".join(f"“{m}” {n}×" for m, n in
                                             sorted(leitura.marcadores.items())) + ".")
    if leitura.asteriscos:
        avisos.append(f"{len(leitura.asteriscos)} número(s) com “*” (nota da legenda do INEP): "
                      + "; ".join(leitura.asteriscos[:10]) + ".")
    if leitura.colunas_ignoradas:
        avisos.append("Colunas não lidas: " + ", ".join(leitura.colunas_ignoradas) + ".")
    sem_meta = [a for a in leitura.edicoes
                if not leitura.anos_meta or a > max(leitura.anos_meta)]
    if sem_meta:
        avisos.append(f"O INEP não definiu meta do Ideb para {', '.join(map(str, sem_meta))} "
                      "(as metas do 1º ciclo vão até 2021): nada é gravado como meta dessas "
                      "edições.")
    avisos.append("A série do 5º ano não é comparável em todo o período (o universo do Saeb "
                  "mudou ao longo das edições — ver as notas do INEP)"
                  + ("; 2021 tem a nota própria da pandemia." if 2021 in leitura.edicoes
                     else "."))
    return avisos


# --- Planilha (linha de comando) -------------------------------------------------

def _topo_da_aba(aba) -> str | None:
    """O texto do topo da aba ATÉ a linha técnica, ou None se a aba não a tem."""
    textos = []
    for linha in aba.iter_rows(max_row=_LINHAS_TOPO, values_only=True):
        nomes = [texto_limpo(c) for c in linha]
        if any(n.upper().startswith("VL_OBSERVADO_") for n in nomes):
            return " ".join(textos).casefold()
        textos.extend(n for n in nomes if n)
    return None


def linhas_da_planilha(wb) -> tuple[str, Iterator]:
    """``(nome da aba, linhas)`` da ÚNICA aba dos ANOS INICIAIS com a linha técnica do
    Ideb — pelo TOPO (título "Anos Iniciais", série "1º ao 5º ano"), nunca pela posição
    nem pelo nome da aba (o arquivo de UF/Brasil traz também anos finais e EM)."""
    candidatas = []
    for aba in wb.worksheets:
        topo = _topo_da_aba(aba)
        if topo is None:
            continue
        if (any(m in topo for m in ideb.MARCADORES_AI)
                and not any(m in topo for m in ideb._OUTRAS_ETAPAS)):
            candidatas.append(aba)
    if len(candidatas) != 1:
        raise _recusa_layout(
            "Nenhuma aba dos ANOS INICIAIS tem a linha técnica do Ideb." if not candidatas else
            f"Mais de uma aba dos anos iniciais tem a linha técnica "
            f"({', '.join(a.title for a in candidatas)}); não dá para saber qual vale.")
    return candidatas[0].title, candidatas[0].iter_rows(values_only=True)


# --- Para indicadores_referencia (servidor) --------------------------------------

def recortar(lido: LeituraTerritorio) -> tuple[seduc.LeituraSeduc, dict]:
    """As linhas de ``indicadores_referencia`` (avaliação ``ideb``) das redes gravadas
    do território, no formato do fluxo de famílias (``pipeline_seduc``), e o que é só
    deste arquivo (redes do arquivo, notas, marcadores)."""
    leitura = seduc.LeituraSeduc(parser=lido.parser, edicao_arquivo=lido.edicao_arquivo,
                                 encoding="utf-8", linhas_lidas=lido.linhas_lidas,
                                 avisos=list(lido.avisos),
                                 colunas_ignoradas=[*lido.colunas_ignoradas,
                                                    *lido.colunas_repetidas])
    gravadas = (("municipal",) if lido.abrangencia == ABR_MUNICIPIO else REDES_GRAVADAS)
    nome = lido.nome_territorio or lido.alvo
    leitura.territorios[lido.alvo] = nome
    por_familia: dict[tuple[str, int], ideb.Coluna] = {}
    aprovacao: dict[int, list[ideb.Coluna]] = {}
    for col in lido.colunas:
        if col.familia == "aprovacao":
            aprovacao.setdefault(col.ano, []).append(col)
        else:
            por_familia[(col.familia, col.ano)] = col
    redes_no_arquivo = []
    universo: dict[str, dict] = {}
    for ln in lido.linhas:
        gravada = ln.rede in gravadas
        redes_no_arquivo.append({"rede": ln.rede, "rotulo": ln.rotulo_rede,
                                 "gravada": gravada, "notas": list(ln.notas),
                                 "universo_saeb": (universo_saeb(lido.abrangencia, ln.rede)
                                                   if gravada else None)})
        if not gravada:
            continue
        universo[ln.rede] = {"universo": universo_saeb(lido.abrangencia, ln.rede),
                             "rotulo": rotulo_universo(lido.abrangencia, ln.rede)}
        for ano in lido.edicoes:
            for familia in ("ideb", "saeb_matematica", "saeb_portugues", "nota_n",
                            "rendimento_p"):
                col = por_familia.get((familia, ano))
                if col is not None:
                    leitura.referencia.append(_numero(lido, ln, col, ano))
            for col in sorted(aprovacao.get(ano, []), key=lambda c: c.indice):
                leitura.referencia.append(_numero(lido, ln, col, ano))
        for ano in lido.anos_meta:
            leitura.referencia.append(_numero(lido, ln, por_familia[("meta", ano)], ano))
    extra = {"edicoes": list(lido.edicoes), "anos_meta": list(lido.anos_meta),
             "abrangencia": lido.abrangencia, "redes_no_arquivo": redes_no_arquivo,
             "notas_arquivo": lido.notas, "marcadores": dict(sorted(lido.marcadores.items())),
             "asteriscos": list(lido.asteriscos),
             "colunas_repetidas": list(lido.colunas_repetidas),
             # O rótulo que a tela lê (o arquivo não traz): de que escolas é a nota do
             # Saeb — e o N e o Ideb — de cada rede gravada.
             "universo_saeb": {"indicadores": list(INDICADORES_DO_UNIVERSO),
                               "por_rede": universo}}
    return leitura, extra


def _numero(lido: LeituraTerritorio, ln: LinhaTerritorio, col: ideb.Coluna,
            ano: int) -> seduc.NumeroReferencia:
    celula = ln.celulas[col.nome]
    familia = col.familia
    if familia == "aprovacao":
        etapa = col.etapa
    elif familia in COMPONENTES:
        etapa = ideb.ETAPA_SAEB
    else:
        etapa = ideb.ETAPA_IDEB
    # Meta e rede TOTAL (com a privada, amostral no Saeb): sem marca de desenho.
    desenho = None if familia == "meta" or ln.rede == "total" else "censitario"
    # ``localizacao`` fica a padrão ("total"): o Ideb OFICIAL do território, sem divisão
    # por localização no arquivo. A nota do Saeb (e o N e o Ideb) é das escolas urbanas
    # na maior parte das redes — isso vai no rótulo (``universo_saeb``), nunca na chave.
    base = dict(indicador=INDICADOR[familia], edicao=ano, abrangencia=lido.abrangencia,
                codigo_territorio=lido.alvo, rede_ensino=ln.rede, unidade=UNIDADE[familia],
                etapa=etapa, componente=COMPONENTES.get(familia, ""), desenho=desenho)
    if celula.valor is None:
        linha = LinhaCanonica(valor=None, motivo_ausencia=ideb.MOTIVO, **base)
    else:
        linha = LinhaCanonica(valor=celula.valor, casas_decimais=lido.casas.get(familia),
                              **base)
    return seduc.NumeroReferencia(ideb.AVALIACAO_IDEB, linha)
