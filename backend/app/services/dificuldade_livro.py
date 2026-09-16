"""Dificuldade por LIVRO do Elefante Letrado — FONTE ÚNICA da regra (v2 vigente).

    DificuldadeLivro(livro, série) = BaseDoNível × AjusteIntrínseco × FatorSérie

VERSÕES: ``elefante_dificuldade_v2`` (vigente) usa EXATAMENTE a mesma conta e os
mesmos parâmetros congelados da ``elefante_dificuldade_v1``. O que a v2 muda é a
RESOLUÇÃO e as GUARDAS (lista em ``PARAMS_V2["mudancas_desde_v1"]``): o livro é
identificado pelo id oficial do Elefante (``elefante_id``) antes do título; o
wordCount passa por um fallback AUDITÁVEL (``resolver_word_count`` → status
``catalogo``/``ausente``/``invalido``/``sem_mediana``); nenhuma etapa produz NaN,
infinito ou valor negativo; contagem negativa ou não finita vale 0; e a série é
reconhecida também por extenso ("Terceiro Ano") e em rótulos como "EF1 - 3º".
Notas carimbadas com a v1 NÃO são recalculadas sozinhas: o recálculo é explícito
(``scripts/recalcular_institucional.py --pendentes``).

* **BaseDoNível** — a régua institucional A3 que já existe (``scoring.peso_a3``:
  ``exp(0,103·pos)``, AA=0 … Z=29), INTOCADA. A régua apenas estende posições para
  o tier avançado revelado pelo catálogo (``Z+``=30) e para ``A+`` (n=1, provisório),
  e dá posição às FAIXAS (``pre_leitor``…``nivel_5``) que hoje valiam 0 na A3.
  Nível desconhecido vale 0 (nunca negativo).
* **AjusteIntrínseco** — quanto o livro é maior/menor que o TÍPICO do próprio
  nível: ``clamp(1 + α·ln(wordCount / medianaDoNível) / ln 3, piso, teto)``. Um
  livro 3× a mediana vale +35 %; 2× vale +22 %; nunca passa de +35 % nem cai
  abaixo de −20 %. Assim o nível continua mandando (+35 % ≈ 3 letras acima),
  livros excepcionais se aproximam da faixa seguinte e um outlier de 9× não
  explode. ``wordCount`` é a ÚNICA variável intrínseca: ``minimumReadTime`` é
  função dele (r = 1,000) e ``pageCount`` não discrimina dentro do nível (r
  intra-nível ≈ 0). wordCount ausente/inválido ou nível sem mediana → 1,0 (o
  livro vale o TÍPICO do nível).
* **FatorSérie** — o mesmo livro vale mais para quem está no começo: +10 pontos
  percentuais por série abaixo do 5º (1º=1,40 … 5º=1,00). Série desconhecida → 1,0.

Tudo é calculável só com metadados do livro + série do aluno; nada de tempo real
do aluno. DETERMINÍSTICO: os parâmetros (inclusive as medianas por nível) são
CONGELADOS por versão, calibrados no catálogo de 752 livros de 2026-09-14 — um
livro novo recebe valor pela versão vigente com as mesmas medianas; recalibrar é
uma NOVA versão (``elefante_dificuldade_v3``), nunca uma edição silenciosa.

GUARDAS NUMÉRICAS: toda etapa passa por ``math.isfinite``; o valor final é
sempre finito e ≥ 0. Contagem negativa ou não finita em ``livros_por_nivel``
vale 0 — um snapshot manual não subtrai pontos, e a evolução só passa ganhos
positivos (``evolucao._delta_niveis``), então nenhum consumidor depende de
contagem negativa.

GOVERNANÇA: a regra é GLOBAL (rede inteira). Nenhum endpoint de escola altera
estes parâmetros; a única saída da regra global é o perfil ``personalizado``
(override autorizado, exclusivo do Admin Global), que mantém a régua legada por
faixa da escola — ver ``regra_da_escola``.

CONSUMIDORES (todos passam por aqui — nota anual, ranking por período, premiações,
evolução, perfil/histórico do aluno, catálogo de livros, simulador, mural/insights):
``regra_da_escola(db, escola_id)`` → objeto com ``valor_livro``/``valor_tipico``/
``pontos_por_chave``/``pontos_aluno``. Ver ``docs/elefante-dificuldade-v2.md``
(e o histórico da calibração em ``docs/elefante-dificuldade-v1.md``).
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Leitura, Livro
from app.services import scoring
from app.services.provisionamento import NIVEIS_PADRAO

VERSAO_V1 = "elefante_dificuldade_v1"
VERSAO_V2 = "elefante_dificuldade_v2"
VERSAO_VIGENTE = VERSAO_V2
VERSAO_LEGADA = "escola_legada_v0"   # régua por faixa da escola (perfil personalizado)

# FAIXAS da régua (as mesmas de provisionamento.NIVEIS_PADRAO): letra → slug.
# Usadas SÓ para CONCILIAR o snapshot agregado (que pode vir por faixa, ex.:
# {"nivel_5": 2}) com as leituras itemizadas (que vêm por letra, ex.: "Z") — nunca
# para valorar. Z+ e A+ ficam na faixa vizinha.
LETRA_PARA_FAIXA: dict[str, str] = {
    letra.upper(): slug for _nome, slug, letras, _pts in NIVEIS_PADRAO for letra in letras}
LETRA_PARA_FAIXA.update({"Z+": "nivel_5", "A+": "nivel_1"})
FAIXA_OUTROS = "__outros__"


def faixa_da_chave(chave: str | None, params: dict | None = None) -> str:
    """Faixa (bucket de conciliação) de uma chave de ``livros_por_nivel``: letra
    (AA..Z, Z+, A+) → slug da faixa; slug de faixa → ele mesmo; sujo → outros."""
    bruto = str(chave or "").strip()
    if not bruto:
        return FAIXA_OUTROS
    slug = LETRA_PARA_FAIXA.get(bruto.upper())
    if slug:
        return slug
    if bruto.lower() in (params or PARAMS_VIGENTES)["posicoes_faixa"]:
        return bruto.lower()
    return FAIXA_OUTROS


class LeituraItem(NamedTuple):
    """Uma leitura ITEMIZADA (linha de ``Leitura`` com o ``Livro``). O 4º campo,
    opcional, é o id OFICIAL do livro no catálogo do Elefante: quando presente e
    conhecido, identifica o livro antes do título (usos posicionais de 2 ou 3
    campos continuam válidos)."""
    titulo: str
    nivel: str
    tempo_min: int = 0
    elefante_id: int | None = None


@dataclass
class InsumoElefante:
    """INSUMO reconciliado do aluno para o motor: o que ``calcular_elefante`` e as
    referências leem. Snapshot = agregado autoritativo; itemização = evidência
    detalhada. Quando ambos existem, ``livros`` e ``tempo`` são o MAIOR dos dois
    (nunca a soma — a mesma leitura não conta duas vezes); só itemização → ela
    basta para alimentar a nota; só snapshot → snapshot. Nunca é um objeto ORM
    (mutar um snapshot na sessão do recálculo o gravaria no commit)."""
    aluno_id: int
    livros_unicos: int = 0
    tempo_leitura_min: int = 0
    questoes_tentativas: int = 0
    questoes_acertos: int = 0
    livros_por_nivel: dict | None = None
    data_referencia: object = None
    id: int | None = None                 # id do snapshot (quando há)
    importacao_id: int | None = None
    itemizadas: int = 0
    fonte: str = "snapshot"               # snapshot | leituras | snapshot+leituras


def reconciliar_insumo(aluno_id: int, snapshot, itens: list | None) -> InsumoElefante | None:
    """Combina o snapshot atual (ou None) com as leituras itemizadas (ou vazio).
    Sem nenhum dos dois → None (ausência de dado, não zero)."""
    itens = list(itens or [])
    if snapshot is None and not itens:
        return None
    n_itens = len(itens)
    tempo_itens = sum(int(getattr(i, "tempo_min", 0) or (i[2] if len(i) > 2 else 0) or 0)
                      for i in itens)
    if snapshot is None:
        return InsumoElefante(aluno_id=aluno_id, livros_unicos=n_itens,
                              tempo_leitura_min=tempo_itens, livros_por_nivel={},
                              itemizadas=n_itens, fonte="leituras")
    return InsumoElefante(
        aluno_id=aluno_id,
        livros_unicos=max(int(snapshot.livros_unicos or 0), n_itens),
        tempo_leitura_min=max(int(snapshot.tempo_leitura_min or 0), tempo_itens),
        questoes_tentativas=int(snapshot.questoes_tentativas or 0),
        questoes_acertos=int(snapshot.questoes_acertos or 0),
        livros_por_nivel=dict(snapshot.livros_por_nivel or {}),
        data_referencia=snapshot.data_referencia, id=snapshot.id,
        importacao_id=snapshot.importacao_id, itemizadas=n_itens,
        fonte="snapshot+leituras" if n_itens else "snapshot")

# Arquivo de referência (metadados objetivos do catálogo). Versionado em git.
CAMINHO_CATALOGO = Path(__file__).resolve().parent.parent / "dados" / "catalogo_elefante.json"

# ---------------------------------------------------------------------------
# Parâmetros — CALIBRAÇÃO CONGELADA (não ler de config; mudar = nova versão)
# ---------------------------------------------------------------------------
PARAMS_V1: dict = {
    "versao": VERSAO_V1,
    "calibracao": {"n_livros": 752, "catalogo_de": "2026-09-14",
                   "fonte": "admin.elefanteletrado.com.br /library (EF + tier Z+/A+)"},
    # Posições fora da A3 (AA..Z = scoring.POS_DO_NIVEL). Z+ é o tier acima de Z
    # (mediana 23.549 palavras vs 7.380 do Z). A+ tem UM livro no catálogo: fica
    # meio degrau acima de A, provisório até haver amostra.
    "posicoes_extra": {"Z+": 30.0, "A+": 4.5},
    # Faixas (chaves de `livros_por_nivel` quando o import é por faixa, não por
    # letra): posição = centro das letras da faixa (provisionamento.NIVEIS_PADRAO).
    "posicoes_faixa": {"pre_leitor": 1.5, "nivel_1": 5.0, "nivel_2": 10.0,
                       "nivel_3": 17.5, "nivel_4": 24.5, "nivel_5": 28.5},
    # Mediana de wordCount por nível no catálogo de calibração (752 livros).
    "medianas_wordcount": {
        "AA": 12.0, "A": 34.5, "B": 74.0, "C": 107.0, "BB": 70.5, "CC": 77.0,
        "DD": 100.0, "D": 139.0, "E": 190.5, "F": 248.5, "G": 309.5, "H": 477.0,
        "I": 573.5, "J": 710.0, "K": 822.0, "L": 1043.0, "M": 1232.0, "N": 1460.0,
        "O": 1822.0, "P": 2181.0, "Q": 2601.0, "R": 3420.0, "S": 4197.0,
        "T": 5274.0, "U": 6803.0, "V": 7569.0, "W": 8787.5, "X": 5749.0,
        "Y": 5156.5, "Z": 7380.0, "A+": 965.0, "Z+": 23549.0,
    },
    "alpha": 0.35,        # inclinação do ajuste por log₃(wc/mediana)
    "razao_log": 3.0,     # base do log: 3× a mediana ⇒ +alpha
    "piso": 0.80,         # ajuste mínimo (livro muito curto NÃO zera)
    "teto": 1.35,         # ajuste máximo (outlier gigante NÃO explode)
    "fator_serie": {1: 1.40, 2: 1.30, 3: 1.20, 4: 1.10, 5: 1.00},
    "fator_serie_padrao": 1.0,   # série fora de 1º–5º (ou desconhecida)
}

# v2 = MESMOS números da v1 (a fórmula definida pelo dono coincide com a da v1);
# a versão nova existe para identificar, nas notas, a mudança de RESOLUÇÃO do
# livro e das GUARDAS — nunca para mover o valor de uma leitura válida.
PARAMS_V2: dict = {
    **copy.deepcopy(PARAMS_V1),
    "versao": VERSAO_V2,
    "mudancas_desde_v1": [
        "Fórmula e parâmetros idênticos aos da v1 (mesmas medianas congeladas "
        "da calibração de 752 livros).",
        "Identidade oficial: com elefante_id presente no catálogo, o wordCount vem "
        "do livro por id; sem id (ou id fora do catálogo), título+nível como na v1.",
        "Fallback auditável de wordCount: status catalogo/ausente/invalido/"
        "sem_mediana; qualquer status diferente de catalogo usa o fator 1,0 "
        "(livro típico do nível).",
        "Guardas numéricas: nenhuma etapa produz NaN, infinito ou valor negativo; "
        "nível desconhecido vale 0.",
        "Contagem negativa ou não finita em livros_por_nivel vale 0 (na v1 um "
        "delta negativo passava como estava).",
        "Série reconhecida também por extenso (Primeiro…Quinto Ano), em '3.º ano', "
        "'EF1 - 3º' e '3º B'; 'Turma 12345', 'Turma 3', 'EJA 2' e etapas/períodos "
        "('EJA 1ª Etapa', 'Turma A - 3º Período') continuam sem série.",
        "Nota.detalhes.elefante.dificuldade.catalogo registra a versão (sha256) e o "
        "tamanho do catálogo usado.",
    ],
}
PARAMS_VIGENTES: dict = PARAMS_V2
PARAMS_POR_VERSAO: dict[str, dict] = {VERSAO_V1: PARAMS_V1, VERSAO_V2: PARAMS_V2}

# Status do fallback de wordCount (``resolver_word_count``).
WC_CATALOGO = "catalogo"        # número finito > 0 e nível com mediana: entra no ajuste
WC_AUSENTE = "ausente"          # sem wordCount (livro fora do catálogo, campo vazio)
WC_INVALIDO = "invalido"        # não numérico, ≤ 0, NaN ou infinito
WC_SEM_MEDIANA = "sem_mediana"  # wordCount válido, mas o nível não tem mediana (faixa/sujo)

# Série a partir de `Turma.ano_escolar` (comparada SEM acento e sem caixa):
# "1º Ano", "4º ANO B", "3ª série", "2° ano", "3.º ano", "5º", "5", "5B", "Ano 3",
# "EF1 - 3º", "3º B", "Terceiro Ano", "Quarta série" — mas NUNCA o primeiro número
# de um rótulo qualquer ("Turma 12345", "Turma 3", "EJA 2" → None): a série tem de
# estar marcada como tal (ordinal / "ano" / "série" / por extenso) ou ser o
# rótulo inteiro. O ordinal SOLTO no meio do rótulo ("EF1 - 3º") é o ÚLTIMO
# recurso (ver `serie_numero`: duas passadas): ele nunca vence um padrão MARCADO
# no mesmo rótulo — senão "Multisseriada 1º ao 5º Ano" viraria 1º ano — e não vale
# quando indica etapa/período ("EJA 1ª Etapa", "Turma A - 3º Período"), em rótulo
# da EJA (etapa da EJA não é série do 1º–5º) nem quando há MAIS DE UM no rótulo
# (intervalo/multisseriada: não há série única).
_SERIE_POR_EXTENSO = {"primeir": 1, "segund": 2, "terceir": 3, "quart": 4, "quint": 5}
_RE_SERIE = re.compile(
    r"(?<!\d)(\d{1,2})\s*\.?\s*(?:[ºª°]|o\b|a\b)?\s*(?:ano|serie)\b"   # 3º Ano / 3.º ano / 3a série
    r"|\b(?:ano|serie)\s*(\d{1,2})(?!\d)"                              # Ano 3
    r"|^\s*(\d{1,2})\s*\.?\s*[ºª°]"                                     # 5º / 3º B (início, como na v1)
    r"|(?<![\w.])(\d{1,2})\s*\.?\s*[ºª°]"                               # EF1 - 3º (ordinal solto)
    r"(?!\s*(?:etapa|segmento|semestre|bimestre|trimestre|periodo|modulo|fase|ciclo)\b)"
    r"|^\s*(\d{1,2})\s*(?:[a-z]\b)?\s*$"                               # 5 / 5B / 5 B
    r"|\b(primeir|segund|terceir|quart|quint)[oa]\s+(?:ano|serie)\b",  # Terceiro Ano / Quarta série
    re.IGNORECASE)
_GRUPO_ORDINAL_SOLTO = 4
_RE_EJA = re.compile(r"\beja\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Guardas numéricas (puras)
# ---------------------------------------------------------------------------

def _numero_finito(valor) -> float | None:
    """``float`` finito ou None (None, bool, texto não numérico, NaN, ±infinito)."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError, OverflowError):
        return None
    return numero if math.isfinite(numero) else None


def _nao_negativo_finito(valor) -> float:
    """Guarda de SAÍDA: o próprio valor se for finito e > 0; qualquer outra coisa
    (negativo, NaN, infinito, não numérico) vira 0,0."""
    numero = _numero_finito(valor)
    return numero if numero is not None and numero > 0 else 0.0


def _numero_finito_ou_saturado(valor) -> float | None:
    """Como ``_numero_finito``, mas um INTEIRO fora do alcance do float
    (``10**400``, que o JSON aceita) satura no maior float finito em vez de virar
    None. Um número absurdo GRANDE é um outlier gigante — a mesma leitura que
    ``1e308`` já recebia —, não um dado ilegível: sem isto havia um degrau
    (``1e308`` valia o ajuste no teto e ``10**400`` caía em ``invalido``, ou seja,
    o livro TÍPICO) para o mesmo tipo de sujeira."""
    numero = _numero_finito(valor)
    if numero is not None:
        return numero
    if isinstance(valor, int) and not isinstance(valor, bool):
        return sys.float_info.max if valor > 0 else -sys.float_info.max
    return None


# Teto de SATURAÇÃO da contagem de livros de uma chave do snapshot. Um inteiro
# acima disto não é dado de aluno (o catálogo oficial tem ~750 títulos): é JSON
# corrompido ou edição manual. Sem o teto, um inteiro fora do alcance do float
# (`10**400`, que o JSON aceita) levantava OverflowError na multiplicação pelo
# típico, e `1e308` estourava para infinito — que a guarda de saída zerava, ou
# seja, MAIS livros valendo MENOS. Saturar mantém a monotonicidade e a finitude.
TETO_CONTAGEM = 10**12


def _contagem_segura(quantidade) -> int:
    """Contagem de livros de uma chave de ``livros_por_nivel``: inteiro ≥ 0.
    Negativa, NaN, infinita ou não numérica → 0 (um snapshot manual não subtrai
    pontos; a evolução só passa ganhos positivos); acima de ``TETO_CONTAGEM``
    satura no teto (nunca estoura para infinito nem levanta OverflowError)."""
    try:
        n = int(quantidade or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    if n <= 0:
        return 0
    return n if n < TETO_CONTAGEM else TETO_CONTAGEM


def _json_seguro(valor):
    """Float não finito não é JSON válido: vira None na explicação."""
    if isinstance(valor, float) and not math.isfinite(valor):
        return None
    return valor


def _id_oficial(valor) -> int | None:
    """Id do catálogo oficial do Elefante (inteiro) ou None. Aceita int, texto com
    dígitos e float INTEIRO (``1234.0`` vindo de JSON); fração, NaN, infinito e
    bool → None."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, float):
        return int(valor) if math.isfinite(valor) and valor.is_integer() else None
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Funções PURAS (sem banco) — a fórmula em si
# ---------------------------------------------------------------------------

def _sem_acento(texto: str | None) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(texto or ""))
        if unicodedata.category(c) != "Mn")


def normalizar_titulo(texto: str | None) -> str:
    """Chave de casamento título↔catálogo: sem acento, sem caixa, espaços únicos."""
    return re.sub(r"\s+", " ", _sem_acento(texto)).strip().casefold()


def _serie_do_match(m: re.Match) -> int:
    grupo = next(g for g in m.groups() if g is not None)
    return int(grupo) if grupo.isdigit() else _SERIE_POR_EXTENSO[grupo.lower()]


def serie_numero(ano_escolar: str | None) -> int | None:
    """``"4º Ano B"`` → 4; ``"Terceiro Ano"`` → 3; série não marcada → None.

    DUAS PASSADAS sobre o rótulo, para o ordinal SOLTO nunca atropelar a série
    MARCADA (sem isso "Multisseriada 1º ao 5º Ano" valia 1 — o ordinal mais à
    esquerda — em vez dos 5 da v1, inflando o fator de série da turma inteira):

    1. padrões MARCADOS ("5º Ano", "Ano 5", rótulo inteiro, por extenso): vale o
       primeiro da esquerda para a direita, exatamente como na v1;
    2. só quando NENHUM marcado casa, o ordinal solto ("EF1 - 3º"). Havendo mais
       de um ordinal solto o rótulo é um INTERVALO ("EF1 - 1º ao 5º") e não há
       série única → None; em rótulo da EJA ("EJA 3º") ele também não vale."""
    rotulo = _sem_acento(ano_escolar)
    soltos: list[re.Match] = []
    for m in _RE_SERIE.finditer(rotulo):
        if m.group(_GRUPO_ORDINAL_SOLTO) is not None:
            soltos.append(m)
            continue
        return _serie_do_match(m)
    if len(soltos) != 1 or _RE_EJA.search(rotulo):
        return None
    return _serie_do_match(soltos[0])


def fator_serie(ano_escolar: str | None, params: dict = PARAMS_VIGENTES) -> float:
    n = serie_numero(ano_escolar)
    fator = _numero_finito(params["fator_serie"].get(n, params["fator_serie_padrao"]))
    if fator is None or fator < 0:
        return float(params["fator_serie_padrao"])
    return fator


def posicao_nivel(codigo: str | None, params: dict = PARAMS_VIGENTES) -> float | None:
    """Posição na escada (AA=0 … Z=29, Z+=30; faixas no centro); None se sujo."""
    bruto = str(codigo or "").strip()
    if not bruto:
        return None
    pos = scoring.POS_DO_NIVEL.get(bruto.upper())
    if pos is not None:
        return float(pos)
    extra = params["posicoes_extra"].get(bruto.upper())
    if extra is not None:
        return float(extra)
    faixa = params["posicoes_faixa"].get(bruto.lower())
    return float(faixa) if faixa is not None else None


def base_nivel(codigo: str | None, params: dict = PARAMS_VIGENTES) -> float:
    """BaseDoNível = A3 = exp(coeficiente·pos). Código desconhecido → 0 (como a A3)."""
    pos = posicao_nivel(codigo, params)
    if pos is None or not math.isfinite(pos):
        return 0.0
    return round(_nao_negativo_finito(math.exp(scoring.A3_COEFICIENTE * pos)), 6)


def mediana_nivel(codigo: str | None, params: dict = PARAMS_VIGENTES) -> float | None:
    return params["medianas_wordcount"].get(str(codigo or "").strip().upper())


def resolver_word_count(codigo: str | None, word_count,
                        params: dict = PARAMS_VIGENTES) -> tuple[float | None, str]:
    """Fallback DETERMINÍSTICO e AUDITÁVEL do wordCount: ``(wordCount, status)``.

    * ``ausente``     — None/vazio (livro fora do catálogo)        → ``(None, ...)``
    * ``invalido``    — não numérico, ≤ 0, NaN ou infinito          → ``(None, ...)``
    * ``sem_mediana`` — número válido, mas o nível não tem mediana  → ``(wc, ...)``
    * ``catalogo``    — número finito > 0 e nível com mediana       → ``(wc, ...)``

    Só ``catalogo`` entra no ajuste intrínseco; qualquer outro status vale o
    fator 1,0 (o livro TÍPICO do nível). Nunca usa tempo do aluno nem pageCount."""
    if word_count is None or (isinstance(word_count, str) and not word_count.strip()):
        return None, WC_AUSENTE
    # `_numero_finito_ou_saturado` (e não `_numero_finito`): um inteiro fora do
    # alcance do float é outlier gigante (ajuste no TETO), não dado ilegível.
    wc = _numero_finito_ou_saturado(word_count)
    if wc is None or wc <= 0:
        return None, WC_INVALIDO
    med = _numero_finito(mediana_nivel(codigo, params))
    if med is None or med <= 0:
        return wc, WC_SEM_MEDIANA
    return wc, WC_CATALOGO


def ajuste_intrinseco(codigo: str | None, word_count: int | float | None,
                      params: dict = PARAMS_VIGENTES) -> float:
    """clamp(1 + α·log_r(wc/mediana), piso, teto). Status do wordCount diferente
    de ``catalogo`` → 1,0 (o livro vale o TÍPICO do nível: fallback determinístico)."""
    wc, status = resolver_word_count(codigo, word_count, params)
    if status != WC_CATALOGO:
        return 1.0
    med = float(mediana_nivel(codigo, params))
    razao = wc / med
    # log da razão (idêntico à v1); só um wordCount subnormal, cuja razão estoura
    # para 0, usa a diferença dos logs — mesmo número, sem erro de domínio.
    log_razao = (math.log(razao) if razao > 0 and math.isfinite(razao)
                 else math.log(wc) - math.log(med))
    ajuste = 1.0 + params["alpha"] * (log_razao / math.log(params["razao_log"]))
    if not math.isfinite(ajuste):
        return 1.0
    return round(max(params["piso"], min(params["teto"], ajuste)), 6)


def calcular_dificuldade_livro(nivel_codigo: str | None, word_count: int | float | None,
                               ano_escolar: str | None, versao: str = VERSAO_VIGENTE) -> float:
    """Valor de UMA leitura para um aluno da série dada. ``versao`` é explícita
    para o chamador declarar que sabe qual regra está usando: v1 e v2 fazem a
    MESMA conta (parâmetros idênticos); versão desconhecida é recusada. Sempre
    finito e ≥ 0."""
    if not isinstance(versao, str) or versao not in PARAMS_POR_VERSAO:
        raise ValueError(f"versão de dificuldade desconhecida: {versao!r}")
    params = PARAMS_POR_VERSAO[versao]
    valor = (base_nivel(nivel_codigo, params) * ajuste_intrinseco(nivel_codigo, word_count, params)
             * fator_serie(ano_escolar, params))
    return round(_nao_negativo_finito(valor), 4)


def explicar_dificuldade(nivel_codigo: str | None, word_count: int | float | None,
                         ano_escolar: str | None, titulo: str | None = None,
                         encontrado: bool | None = None, *,
                         elefante_id: int | None = None,
                         resolvido_por: str | None = None) -> dict:
    """Decomposição auditável (o que a tela/coordenação vê). ``word_count_status``
    diz de onde veio o ajuste (``catalogo``) ou por que o livro vale o típico;
    ``resolvido_por`` diz como o livro foi achado (``elefante_id`` / ``titulo_nivel``)."""
    base = base_nivel(nivel_codigo)
    ajuste = ajuste_intrinseco(nivel_codigo, word_count)
    _wc, status = resolver_word_count(nivel_codigo, word_count)
    fator = fator_serie(ano_escolar)
    return {
        "versao": VERSAO_VIGENTE, "titulo": titulo, "nivel": str(nivel_codigo or "").upper(),
        "posicao": posicao_nivel(nivel_codigo), "base_nivel": base,
        "word_count": _json_seguro(word_count), "word_count_status": status,
        "mediana_nivel": mediana_nivel(nivel_codigo),
        "ajuste_intrinseco": ajuste, "serie": serie_numero(ano_escolar), "fator_serie": fator,
        "valor": round(_nao_negativo_finito(base * ajuste * fator), 4),
        "encontrado_no_catalogo": encontrado,
        "elefante_id": elefante_id, "resolvido_por": resolvido_por,
    }


def parametros_publicos() -> dict:
    """Cópia dos parâmetros vigentes (leitura; nada aqui é editável em runtime)."""
    return json.loads(json.dumps(PARAMS_VIGENTES))


# ---------------------------------------------------------------------------
# Catálogo de referência (arquivo versionado) — só metadados objetivos
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LivroCatalogo:
    id: int
    titulo: str
    nivel: str
    word_count: int
    page_count: int
    level_id: int | None


def _inteiro_ou_zero(valor) -> int:
    numero = _numero_finito(valor)
    return int(numero) if numero is not None else 0


class Catalogo:
    def __init__(self, pacote: dict):
        self.meta = {k: v for k, v in pacote.items() if k != "livros"}
        self.por_titulo_nivel: dict[tuple[str, str], LivroCatalogo] = {}
        self.por_titulo: dict[str, list[LivroCatalogo]] = {}
        self.por_id: dict[int, LivroCatalogo] = {}
        for b in pacote.get("livros", []):
            livro = LivroCatalogo(
                id=int(b["id"]), titulo=str(b.get("title") or ""),
                nivel=str(b.get("levelName") or "").strip().upper(),
                # wordCount sujo no arquivo (NaN/texto) vira 0 → status "invalido"
                # na regra (vale o típico), em vez de derrubar a carga do catálogo.
                word_count=_inteiro_ou_zero(b.get("wordCount")),
                page_count=_inteiro_ou_zero(b.get("pageCount")), level_id=b.get("levelId"))
            chave = normalizar_titulo(livro.titulo)
            self.por_titulo_nivel[(chave, livro.nivel)] = livro
            self.por_titulo.setdefault(chave, []).append(livro)
            self.por_id[livro.id] = livro

    def __len__(self) -> int:
        return len(self.por_id)

    def buscar(self, titulo: str | None, nivel: str | None) -> LivroCatalogo | None:
        """Casa (título normalizado, NÍVEL); sem par exato, aceita o título se ele
        for único no catálogo (2 títulos existem em 2 níveis — aí o nível decide)."""
        if not titulo:
            return None
        chave = normalizar_titulo(titulo)
        exato = self.por_titulo_nivel.get((chave, str(nivel or "").strip().upper()))
        if exato is not None:
            return exato
        candidatos = self.por_titulo.get(chave) or []
        return candidatos[0] if len(candidatos) == 1 else None

    def buscar_por_id(self, elefante_id) -> LivroCatalogo | None:
        """Livro pelo id OFICIAL do Elefante; None se o id não existe no catálogo."""
        eid = _id_oficial(elefante_id)
        return self.por_id.get(eid) if eid is not None else None


@lru_cache(maxsize=1)
def catalogo() -> Catalogo:
    """Catálogo carregado UMA vez por processo (arquivo pequeno, ~100 KB)."""
    if not CAMINHO_CATALOGO.exists():
        return Catalogo({"n": 0, "livros": []})
    return Catalogo(json.loads(CAMINHO_CATALOGO.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def _versao_catalogo_cache() -> tuple[str | None, int]:
    if not CAMINHO_CATALOGO.exists():
        return None, 0
    digest = hashlib.sha256(CAMINHO_CATALOGO.read_bytes()).hexdigest()[:12]
    return digest, len(catalogo())


def versao_catalogo() -> dict:
    """``{"versao": 12 primeiros hex do sha256 do arquivo, "n_livros": N}`` —
    calculado UMA vez por processo (cópia nova a cada chamada). Carimbado em
    ``Nota.detalhes.elefante.dificuldade.catalogo``: a fórmula muda só por versão,
    mas o arquivo do catálogo muda por commit — o carimbo diz QUAL extrato deu o
    wordCount. Sem arquivo → ``versao`` None e 0 livros."""
    versao, n_livros = _versao_catalogo_cache()
    return {"versao": versao, "n_livros": n_livros}


def recarregar_catalogo() -> None:
    catalogo.cache_clear()
    _versao_catalogo_cache.cache_clear()


# ---------------------------------------------------------------------------
# REGRAS — o contrato único que TODOS os consumidores usam
# ---------------------------------------------------------------------------

RESOLVIDO_POR_ID = "elefante_id"
RESOLVIDO_POR_TITULO = "titulo_nivel"


class RegraGlobal:
    """Regra GLOBAL vigente (rede inteira): A3 × ajuste intrínseco × série.

    IDENTIDADE: com ``elefante_id`` presente no catálogo oficial o livro é o do
    id (o wordCount vem dele); sem id — ou com id fora do catálogo — busca por
    título + nível, como na v1. O NÍVEL que vale é sempre o registrado na leitura
    (o nível efetivo), nunca o do catálogo."""

    versao = VERSAO_VIGENTE

    def __init__(self, cat: Catalogo | None = None):
        self._cat = cat if cat is not None else catalogo()

    def _resolver(self, titulo: str | None, nivel: str | None,
                  elefante_id: int | None) -> tuple[LivroCatalogo | None, str | None]:
        por_id = self._cat.buscar_por_id(elefante_id)
        if por_id is not None:
            return por_id, RESOLVIDO_POR_ID
        por_titulo = self._cat.buscar(titulo, nivel)
        return (por_titulo, RESOLVIDO_POR_TITULO) if por_titulo is not None else (None, None)

    def metadados(self, titulo: str | None, nivel: str | None, *,
                  elefante_id: int | None = None) -> LivroCatalogo | None:
        return self._resolver(titulo, nivel, elefante_id)[0]

    def valor_tipico(self, nivel_codigo: str | None, ano_escolar: str | None = None,
                     turma_id: int | None = None) -> float:
        """Valor do livro TÍPICO do nível (ajuste 1,0) para a série."""
        return round(_nao_negativo_finito(base_nivel(nivel_codigo) * fator_serie(ano_escolar)), 4)

    def valor_livro(self, nivel_codigo: str | None, titulo: str | None = None,
                    ano_escolar: str | None = None, turma_id: int | None = None, *,
                    elefante_id: int | None = None) -> float:
        """Valor de UMA leitura: usa o wordCount do catálogo quando o livro é
        identificado (id oficial, senão título+nível); senão o típico do nível
        (fallback determinístico). O nível que vale é o registrado na leitura (o
        que o aluno de fato leu)."""
        meta = self.metadados(titulo, nivel_codigo, elefante_id=elefante_id)
        wc = meta.word_count if meta is not None else None
        return calcular_dificuldade_livro(nivel_codigo, wc, ano_escolar, self.versao)

    def explicar(self, nivel_codigo: str | None, titulo: str | None = None,
                 ano_escolar: str | None = None, *, elefante_id: int | None = None) -> dict:
        meta, via = self._resolver(titulo, nivel_codigo, elefante_id)
        return explicar_dificuldade(
            nivel_codigo, meta.word_count if meta else None, ano_escolar, titulo,
            encontrado=meta is not None,
            elefante_id=meta.id if meta is not None else _id_oficial(elefante_id),
            resolvido_por=via)

    def pontos_por_chave(self, livros_por_nivel: dict | None, ano_escolar: str | None = None,
                         turma_id: int | None = None,
                         leituras: list | None = None) -> dict[str, float]:
        """HÍBRIDO reconciliado: cada livro ITEMIZADO (Leitura com título) vale o
        seu próprio valor; o RESTANTE da contagem do snapshot vale o típico da
        chave. Cada livro conta UMA vez — a conciliação não depende de as chaves
        coincidirem (o snapshot pode vir por FAIXA, ``{"nivel_5": 2}``, e as
        leituras por LETRA, ``Z``), nem da ordem em que os imports ocorreram:

        1. cada item cobre primeiro a contagem da SUA letra;
        2. depois a contagem de outra chave da MESMA faixa (letra ≠, faixa igual;
           chave por faixa);
        3. o excedente cobre contagens de OUTRAS faixas (renivelamento, faixa
           divergente) — das mais valiosas para as mais baratas, para nunca
           inflar: o total contado nunca passa de ``max(Σ snapshot, Σ itens)``.

        ``leituras`` = ``[(titulo, nivel[, tempo[, elefante_id]]), ...]`` do aluno
        (``LeituraItem``). Contagem negativa ou não finita vale 0 (guarda v2: um
        snapshot manual não subtrai pontos; a evolução só passa ganhos positivos).
        Todo valor de saída é finito e ≥ 0."""
        # 1) valor de cada item, por letra; e o "pool" de itens por faixa
        itens_por_letra: dict[str, list[float]] = defaultdict(list)
        pool_letra: dict[str, int] = defaultdict(int)
        pool_faixa: dict[str, int] = defaultdict(int)
        for item in (leituras or []):
            titulo, nivel = item[0], item[1]
            elefante_id = item[3] if len(item) > 3 else None
            letra = str(nivel or "").strip().upper()
            if not letra:
                continue
            itens_por_letra[letra].append(
                self.valor_livro(letra, titulo, ano_escolar, elefante_id=elefante_id))
            pool_letra[letra] += 1
            pool_faixa[faixa_da_chave(letra)] += 1

        # chaves do snapshot, das mais valiosas às mais baratas (cobrir primeiro as
        # caras deixa o restante valorado no típico mais barato — conservador)
        contagens: dict[str, int] = {
            chave: _contagem_segura(quantidade)
            for chave, quantidade in (livros_por_nivel or {}).items()}
        ordem = sorted(contagens, key=lambda k: -(posicao_nivel(k) if posicao_nivel(k) is not None else -1))
        restante: dict[str, int] = {}
        # passo 1 — mesma letra
        for chave in ordem:
            n = contagens[chave]
            if n <= 0:
                restante[chave] = 0
                continue
            letra = str(chave).strip().upper()
            cobre = min(n, pool_letra.get(letra, 0))
            if cobre:
                pool_letra[letra] -= cobre
                pool_faixa[faixa_da_chave(letra)] -= cobre
            restante[chave] = n - cobre
        # passo 2 — mesma faixa (letra diferente da mesma faixa, ou chave por faixa)
        for chave in ordem:
            if restante[chave] <= 0:
                continue
            faixa = faixa_da_chave(chave)
            cobre = min(restante[chave], pool_faixa.get(faixa, 0))
            if cobre:
                pool_faixa[faixa] -= cobre
                restante[chave] -= cobre
                # consome os itens desta faixa (qualquer letra) no pool por letra
                for letra in list(pool_letra):
                    if cobre <= 0:
                        break
                    if faixa_da_chave(letra) == faixa and pool_letra[letra] > 0:
                        c = min(cobre, pool_letra[letra])
                        pool_letra[letra] -= c
                        cobre -= c
        # passo 3 — excedente de itens (faixa sem chave no snapshot / renivelamento)
        sobra = sum(v for v in pool_faixa.values() if v > 0)
        for chave in ordem:
            if sobra <= 0:
                break
            if restante[chave] > 0:
                c = min(restante[chave], sobra)
                restante[chave] -= c
                sobra -= c

        # 3) saída: restante do snapshot × típico da chave + itens pela própria letra
        saida: dict[str, float] = {}
        for chave in contagens:
            saida[chave] = round(_nao_negativo_finito(
                restante[chave] * self.valor_tipico(chave, ano_escolar)), 4)
        for letra, valores in itens_por_letra.items():
            saida[letra] = round(_nao_negativo_finito(saida.get(letra, 0.0) + sum(valores)), 4)
        return saida

    def pontos_aluno(self, livros_por_nivel: dict | None, ano_escolar: str | None = None,
                     turma_id: int | None = None,
                     leituras: list[tuple[str, str]] | None = None) -> float:
        return round(_nao_negativo_finito(sum(self.pontos_por_chave(
            livros_por_nivel, ano_escolar, turma_id, leituras).values())), 2)


# Nome histórico: todo consumidor (e ``isinstance``) que usa ``RegraV1`` recebe a
# regra global VIGENTE — hoje a v2 (``RegraGlobal.versao``).
RegraV1 = RegraGlobal


class RegraEscolaLegada:
    """OVERRIDE AUTORIZADO (perfil ``personalizado``): a régua por FAIXA da escola
    (NivelDificuldade / DificuldadeTurma / PontuacaoNivelTurma, TURMA > SÉRIE >
    padrão). Sem dificuldade por livro: todo livro do nível vale o mesmo. Mantida
    intacta para não mover uma nota sequer dessas escolas — só as guardas de
    entrada/saída (contagem negativa ou não finita = 0; valor final finito ≥ 0)."""

    versao = VERSAO_LEGADA

    def __init__(self, db: Session, escola_id: int):
        self._mapa = scoring._mapa_dificuldade(db, escola_id)
        self._mapa_turmas = scoring.mapa_pontos_turmas(db, escola_id)

    def valor_tipico(self, nivel_codigo: str | None, ano_escolar: str | None = None,
                     turma_id: int | None = None) -> float:
        por_turma = self._mapa_turmas.get(turma_id, self._mapa_turmas[None])
        return _nao_negativo_finito(por_turma.get(str(nivel_codigo or "").strip().upper(), 0.0))

    def valor_livro(self, nivel_codigo: str | None, titulo: str | None = None,
                    ano_escolar: str | None = None, turma_id: int | None = None, *,
                    elefante_id: int | None = None) -> float:
        """``elefante_id`` é aceito (contrato único das regras) e IGNORADO: na régua
        por faixa todo livro do nível vale o mesmo."""
        return self.valor_tipico(nivel_codigo, ano_escolar, turma_id)

    def explicar(self, nivel_codigo, titulo=None, ano_escolar=None, *, elefante_id=None) -> dict:
        return {"versao": self.versao, "nivel": str(nivel_codigo or "").upper(),
                "valor": self.valor_livro(nivel_codigo, titulo, ano_escolar)}

    def pontos_por_chave(self, livros_por_nivel: dict | None, ano_escolar: str | None = None,
                         turma_id: int | None = None, leituras=None) -> dict[str, float]:
        return {chave: round(_nao_negativo_finito(scoring._pontos_dificuldade(
                    {chave: _contagem_segura(qtd)}, ano_escolar or "", self._mapa, turma_id)), 2)
                for chave, qtd in (livros_por_nivel or {}).items()}

    def pontos_aluno(self, livros_por_nivel: dict | None, ano_escolar: str | None = None,
                     turma_id: int | None = None, leituras=None) -> float:
        contagens = {chave: _contagem_segura(qtd)
                     for chave, qtd in (livros_por_nivel or {}).items()}
        return round(_nao_negativo_finito(scoring._pontos_dificuldade(
            contagens, ano_escolar or "", self._mapa, turma_id)), 2)


def regra_institucional() -> RegraGlobal:
    """A régua da REDE: sempre a regra global vigente (é o que as colunas
    ``*_institucional`` e o ranking da rede usam)."""
    return RegraGlobal()


def regra_da_escola(db: Session, escola_id: int):
    """Régua do contexto INTERNO da escola: regra global vigente por padrão; a régua
    legada por faixa SÓ se a escola está no perfil ``personalizado`` (override
    autorizado)."""
    if scoring._scoring_personalizado(db, escola_id):
        return RegraEscolaLegada(db, escola_id)
    return RegraGlobal()


def leituras_por_aluno(db: Session, escola_id: int,
                       aluno_ids: set[int] | None = None) -> dict[int, list[LeituraItem]]:
    """``{aluno_id: [LeituraItem(titulo, nivel, tempo_min, elefante_id), ...]}`` das
    leituras ITEMIZADAS da escola, em UMA query (nunca por aluno). ``aluno_ids``
    restringe. ``elefante_id`` (id oficial do livro) viaja junto para a regra
    identificar o livro antes do título.

    NÍVEL CONGELADO: o nível que vale é o carimbado NA LEITURA
    (``Leitura.nivel_codigo``) e só quando ele é nulo — leitura anterior a esta
    versão — cai no nível ATUAL do livro (``coalesce``). É o que impede que
    corrigir o catálogo hoje reescreva a nota gravada de ontem: esta função é a
    que alimenta o MOTOR (``scoring``), e as demais telas usam o mesmo
    ``coalesce``."""
    nivel_efetivo = func.coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)
    saida: dict[int, list[LeituraItem]] = {}
    consulta = (select(Leitura.aluno_id, Livro.titulo, nivel_efetivo,
                       Leitura.tempo_leitura_min, Livro.elefante_id)
                .join(Livro, Leitura.livro_id == Livro.id)
                .where(Leitura.escola_id == escola_id))
    ids = set(aluno_ids) if aluno_ids is not None else None
    if ids is not None and 0 < len(ids) <= 50:     # poucos alunos: filtra no SQL
        consulta = consulta.where(Leitura.aluno_id.in_(ids))
    for aluno_id, titulo, nivel, tempo, elefante_id in db.execute(consulta).all():
        if ids is not None and aluno_id not in ids:
            continue
        saida.setdefault(aluno_id, []).append(
            LeituraItem(titulo or "", nivel or "", int(tempo or 0), elefante_id))
    return saida


def insumos_elefante(snapshots: dict, leituras: dict[int, list], aluno_ids) -> dict[int, InsumoElefante]:
    """``{aluno_id: InsumoElefante}`` reconciliado para o conjunto pontuado: quem
    tem snapshot e/ou leituras itemizadas. Quem não tem nada fica FORA (ausência)."""
    saida: dict[int, InsumoElefante] = {}
    for aid in aluno_ids:
        insumo = reconciliar_insumo(aid, snapshots.get(aid), leituras.get(aid))
        if insumo is not None:
            saida[aid] = insumo
    return saida
