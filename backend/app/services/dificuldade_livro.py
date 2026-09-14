"""Dificuldade por LIVRO do Elefante Letrado — FONTE ÚNICA da regra (v1).

    DificuldadeLivro(livro, série) = BaseDoNível × AjusteIntrínseco × FatorSérie

* **BaseDoNível** — a régua institucional A3 que já existe (``scoring.peso_a3``:
  ``exp(0,103·pos)``, AA=0 … Z=29), INTOCADA. A v1 apenas estende posições para
  o tier avançado revelado pelo catálogo (``Z+``=30) e para ``A+`` (n=1, provisório),
  e dá posição às FAIXAS (``pre_leitor``…``nivel_5``) que hoje valiam 0 na A3.
* **AjusteIntrínseco** — quanto o livro é maior/menor que o TÍPICO do próprio
  nível: ``clamp(1 + α·log₃(wordCount / medianaDoNível), piso, teto)``. Um livro
  3× a mediana vale +35 %; 2× vale +22 %; nunca passa de +35 % nem cai abaixo de
  −20 %. Assim o nível continua mandando (+35 % ≈ 3 letras acima), livros
  excepcionais se aproximam da faixa seguinte e um outlier de 9× não explode.
  ``wordCount`` é a ÚNICA variável intrínseca: ``minimumReadTime`` é função dele
  (r = 1,000) e ``pageCount`` não discrimina dentro do nível (r intra-nível ≈ 0).
* **FatorSérie** — o mesmo livro vale mais para quem está no começo: +10 pontos
  percentuais por série abaixo do 5º (1º=1,40 … 5º=1,00). Série desconhecida → 1,0.

Tudo é calculável só com metadados do livro + série do aluno; nada de tempo real
do aluno. DETERMINÍSTICO: os parâmetros (inclusive as medianas por nível) são
CONGELADOS por versão, calibrados no catálogo de 752 livros de 2026-09-14 — um
livro novo recebe valor pela versão vigente com as mesmas medianas; recalibrar é
uma NOVA versão (``elefante_dificuldade_v2``), nunca uma edição silenciosa.

GOVERNANÇA: a regra é GLOBAL (rede inteira). Nenhum endpoint de escola altera
estes parâmetros; a única saída da regra global é o perfil ``personalizado``
(override autorizado, exclusivo do Admin Global), que mantém a régua legada por
faixa da escola — ver ``regra_da_escola``.

CONSUMIDORES (todos passam por aqui — nota anual, ranking por período, premiações,
evolução, perfil/histórico do aluno, catálogo de livros, simulador, mural/insights):
``regra_da_escola(db, escola_id)`` → objeto com ``valor_livro``/``valor_tipico``/
``pontos_por_chave``/``pontos_aluno``. Ver ``docs/elefante-dificuldade-v1.md``.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Leitura, Livro
from app.services import scoring
from app.services.provisionamento import NIVEIS_PADRAO

VERSAO_VIGENTE = "elefante_dificuldade_v1"
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
    if bruto.lower() in (params or PARAMS_V1)["posicoes_faixa"]:
        return bruto.lower()
    return FAIXA_OUTROS


class LeituraItem(NamedTuple):
    """Uma leitura ITEMIZADA (linha de ``Leitura`` com o ``Livro``)."""
    titulo: str
    nivel: str
    tempo_min: int = 0


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
# Parâmetros da v1 — CALIBRAÇÃO CONGELADA (não ler de config; mudar = nova versão)
# ---------------------------------------------------------------------------
PARAMS_V1: dict = {
    "versao": VERSAO_VIGENTE,
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

# Série a partir de `Turma.ano_escolar`: "1º Ano", "4º ANO B", "3ª série", "2° ano",
# "5º", "5", "5B", "Ano 3" — mas NUNCA o primeiro número de um rótulo qualquer
# ("Turma 12345", "Turma 3", "EJA 2" → None): a série tem de estar marcada como
# tal (ordinal / "ano" / "série") ou ser o rótulo inteiro.
_RE_SERIE = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:[ºª°]|o\b|a\b)?\s*(?:ano|s[ée]rie)\b"   # 3º Ano / 3a série
    r"|\b(?:ano|s[ée]rie)\s*(\d{1,2})(?!\d)"                        # Ano 3
    r"|^\s*(\d{1,2})\s*[ºª°]"                                        # 5º / 5º B
    r"|^\s*(\d{1,2})\s*(?:[A-Za-z]\b)?\s*$",                        # 5 / 5B / 5 B
    re.IGNORECASE)


# ---------------------------------------------------------------------------
# Funções PURAS (sem banco) — a fórmula em si
# ---------------------------------------------------------------------------

def normalizar_titulo(texto: str | None) -> str:
    """Chave de casamento título↔catálogo: sem acento, sem caixa, espaços únicos."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", str(texto or ""))
        if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sem_acento).strip().casefold()


def serie_numero(ano_escolar: str | None) -> int | None:
    """``"4º Ano B"`` → 4; sem dígito → None."""
    m = _RE_SERIE.search(str(ano_escolar or ""))
    if not m:
        return None
    return int(next(g for g in m.groups() if g is not None))


def fator_serie(ano_escolar: str | None, params: dict = PARAMS_V1) -> float:
    n = serie_numero(ano_escolar)
    return float(params["fator_serie"].get(n, params["fator_serie_padrao"]))


def posicao_nivel(codigo: str | None, params: dict = PARAMS_V1) -> float | None:
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


def base_nivel(codigo: str | None, params: dict = PARAMS_V1) -> float:
    """BaseDoNível = A3 = exp(coeficiente·pos). Código desconhecido → 0 (como a A3)."""
    pos = posicao_nivel(codigo, params)
    return round(math.exp(scoring.A3_COEFICIENTE * pos), 6) if pos is not None else 0.0


def mediana_nivel(codigo: str | None, params: dict = PARAMS_V1) -> float | None:
    return params["medianas_wordcount"].get(str(codigo or "").strip().upper())


def ajuste_intrinseco(codigo: str | None, word_count: int | float | None,
                      params: dict = PARAMS_V1) -> float:
    """clamp(1 + α·log_r(wc/mediana), piso, teto). Sem wordCount ou sem mediana
    do nível → 1,0 (o livro vale o TÍPICO do nível: fallback determinístico)."""
    med = mediana_nivel(codigo, params)
    try:
        wc = float(word_count or 0)
    except (TypeError, ValueError):
        wc = 0.0
    if wc <= 0 or not med or med <= 0:
        return 1.0
    z = math.log(wc / med) / math.log(params["razao_log"])
    return round(max(params["piso"], min(params["teto"], 1.0 + params["alpha"] * z)), 6)


def calcular_dificuldade_livro(nivel_codigo: str | None, word_count: int | float | None,
                               ano_escolar: str | None, versao: str = VERSAO_VIGENTE) -> float:
    """Valor de UMA leitura para um aluno da série dada. ``versao`` é explícita
    para o chamador declarar que sabe qual regra está usando."""
    if versao != VERSAO_VIGENTE:
        raise ValueError(f"versão de dificuldade desconhecida: {versao!r}")
    return round(base_nivel(nivel_codigo) * ajuste_intrinseco(nivel_codigo, word_count)
                 * fator_serie(ano_escolar), 4)


def explicar_dificuldade(nivel_codigo: str | None, word_count: int | float | None,
                         ano_escolar: str | None, titulo: str | None = None,
                         encontrado: bool | None = None) -> dict:
    """Decomposição auditável (o que a tela/coordenação vê)."""
    base = base_nivel(nivel_codigo)
    ajuste = ajuste_intrinseco(nivel_codigo, word_count)
    fator = fator_serie(ano_escolar)
    return {
        "versao": VERSAO_VIGENTE, "titulo": titulo, "nivel": str(nivel_codigo or "").upper(),
        "posicao": posicao_nivel(nivel_codigo), "base_nivel": base,
        "word_count": word_count, "mediana_nivel": mediana_nivel(nivel_codigo),
        "ajuste_intrinseco": ajuste, "serie": serie_numero(ano_escolar), "fator_serie": fator,
        "valor": round(base * ajuste * fator, 4), "encontrado_no_catalogo": encontrado,
    }


def parametros_publicos() -> dict:
    """Cópia dos parâmetros vigentes (leitura; nada aqui é editável em runtime)."""
    return json.loads(json.dumps(PARAMS_V1))


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
                word_count=int(b.get("wordCount") or 0),
                page_count=int(b.get("pageCount") or 0), level_id=b.get("levelId"))
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


@lru_cache(maxsize=1)
def catalogo() -> Catalogo:
    """Catálogo carregado UMA vez por processo (arquivo pequeno, ~100 KB)."""
    if not CAMINHO_CATALOGO.exists():
        return Catalogo({"n": 0, "livros": []})
    return Catalogo(json.loads(CAMINHO_CATALOGO.read_text(encoding="utf-8")))


def recarregar_catalogo() -> None:
    catalogo.cache_clear()


# ---------------------------------------------------------------------------
# REGRAS — o contrato único que TODOS os consumidores usam
# ---------------------------------------------------------------------------

class RegraV1:
    """Regra GLOBAL vigente (rede inteira): A3 × ajuste intrínseco × série."""

    versao = VERSAO_VIGENTE

    def __init__(self, cat: Catalogo | None = None):
        self._cat = cat if cat is not None else catalogo()

    def metadados(self, titulo: str | None, nivel: str | None) -> LivroCatalogo | None:
        return self._cat.buscar(titulo, nivel)

    def valor_tipico(self, nivel_codigo: str | None, ano_escolar: str | None = None,
                     turma_id: int | None = None) -> float:
        """Valor do livro TÍPICO do nível (ajuste 1,0) para a série."""
        return round(base_nivel(nivel_codigo) * fator_serie(ano_escolar), 4)

    def valor_livro(self, nivel_codigo: str | None, titulo: str | None = None,
                    ano_escolar: str | None = None, turma_id: int | None = None) -> float:
        """Valor de UMA leitura: usa o wordCount do catálogo quando o título casa;
        senão o típico do nível (fallback determinístico). O nível que vale é o
        registrado na leitura (o que o aluno de fato leu)."""
        meta = self.metadados(titulo, nivel_codigo)
        wc = meta.word_count if meta is not None else None
        return calcular_dificuldade_livro(nivel_codigo, wc, ano_escolar)

    def explicar(self, nivel_codigo: str | None, titulo: str | None = None,
                 ano_escolar: str | None = None) -> dict:
        meta = self.metadados(titulo, nivel_codigo)
        return explicar_dificuldade(nivel_codigo, meta.word_count if meta else None,
                                    ano_escolar, titulo, encontrado=meta is not None)

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

        ``leituras`` = ``[(titulo, nivel[, tempo]), ...]`` do aluno. Contagem
        negativa (delta de evolução) passa como está."""
        # 1) valor de cada item, por letra; e o "pool" de itens por faixa
        itens_por_letra: dict[str, list[float]] = defaultdict(list)
        pool_letra: dict[str, int] = defaultdict(int)
        pool_faixa: dict[str, int] = defaultdict(int)
        for item in (leituras or []):
            titulo, nivel = item[0], item[1]
            letra = str(nivel or "").strip().upper()
            if not letra:
                continue
            itens_por_letra[letra].append(self.valor_livro(letra, titulo, ano_escolar))
            pool_letra[letra] += 1
            pool_faixa[faixa_da_chave(letra)] += 1

        # chaves do snapshot, das mais valiosas às mais baratas (cobrir primeiro as
        # caras deixa o restante valorado no típico mais barato — conservador)
        contagens: dict[str, int] = {}
        for chave, quantidade in (livros_por_nivel or {}).items():
            try:
                contagens[chave] = int(quantidade or 0)
            except (TypeError, ValueError):
                contagens[chave] = 0
        ordem = sorted(contagens, key=lambda k: -(posicao_nivel(k) if posicao_nivel(k) is not None else -1))
        restante: dict[str, int] = {}
        # passo 1 — mesma letra
        for chave in ordem:
            n = contagens[chave]
            if n <= 0:
                restante[chave] = n
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
            saida[chave] = round(restante[chave] * self.valor_tipico(chave, ano_escolar), 4)
        for letra, valores in itens_por_letra.items():
            saida[letra] = round(saida.get(letra, 0.0) + sum(valores), 4)
        return saida

    def pontos_aluno(self, livros_por_nivel: dict | None, ano_escolar: str | None = None,
                     turma_id: int | None = None,
                     leituras: list[tuple[str, str]] | None = None) -> float:
        return round(sum(self.pontos_por_chave(livros_por_nivel, ano_escolar, turma_id,
                                               leituras).values()), 2)


class RegraEscolaLegada:
    """OVERRIDE AUTORIZADO (perfil ``personalizado``): a régua por FAIXA da escola
    (NivelDificuldade / DificuldadeTurma / PontuacaoNivelTurma, TURMA > SÉRIE >
    padrão). Sem dificuldade por livro: todo livro do nível vale o mesmo. Mantida
    intacta para não mover uma nota sequer dessas escolas."""

    versao = VERSAO_LEGADA

    def __init__(self, db: Session, escola_id: int):
        self._mapa = scoring._mapa_dificuldade(db, escola_id)
        self._mapa_turmas = scoring.mapa_pontos_turmas(db, escola_id)

    def valor_tipico(self, nivel_codigo: str | None, ano_escolar: str | None = None,
                     turma_id: int | None = None) -> float:
        por_turma = self._mapa_turmas.get(turma_id, self._mapa_turmas[None])
        return float(por_turma.get(str(nivel_codigo or "").strip().upper(), 0.0))

    def valor_livro(self, nivel_codigo: str | None, titulo: str | None = None,
                    ano_escolar: str | None = None, turma_id: int | None = None) -> float:
        return self.valor_tipico(nivel_codigo, ano_escolar, turma_id)

    def explicar(self, nivel_codigo, titulo=None, ano_escolar=None) -> dict:
        return {"versao": self.versao, "nivel": str(nivel_codigo or "").upper(),
                "valor": self.valor_livro(nivel_codigo, titulo, ano_escolar)}

    def pontos_por_chave(self, livros_por_nivel: dict | None, ano_escolar: str | None = None,
                         turma_id: int | None = None, leituras=None) -> dict[str, float]:
        return {chave: scoring._pontos_dificuldade({chave: qtd}, ano_escolar or "",
                                                   self._mapa, turma_id)
                for chave, qtd in (livros_por_nivel or {}).items()}

    def pontos_aluno(self, livros_por_nivel: dict | None, ano_escolar: str | None = None,
                     turma_id: int | None = None, leituras=None) -> float:
        return scoring._pontos_dificuldade(livros_por_nivel or {}, ano_escolar or "",
                                           self._mapa, turma_id)


def regra_institucional() -> RegraV1:
    """A régua da REDE: sempre a v1 global (é o que as colunas ``*_institucional``
    e o ranking da rede usam)."""
    return RegraV1()


def regra_da_escola(db: Session, escola_id: int):
    """Régua do contexto INTERNO da escola: v1 global por padrão; a régua legada por
    faixa SÓ se a escola está no perfil ``personalizado`` (override autorizado)."""
    if scoring._scoring_personalizado(db, escola_id):
        return RegraEscolaLegada(db, escola_id)
    return RegraV1()


def leituras_por_aluno(db: Session, escola_id: int,
                       aluno_ids: set[int] | None = None) -> dict[int, list[LeituraItem]]:
    """``{aluno_id: [LeituraItem(titulo, nivel, tempo_min), ...]}`` das leituras
    ITEMIZADAS da escola, em UMA query (nunca por aluno). ``aluno_ids`` restringe."""
    saida: dict[int, list[LeituraItem]] = {}
    consulta = (select(Leitura.aluno_id, Livro.titulo, Livro.nivel_codigo,
                       Leitura.tempo_leitura_min)
                .join(Livro, Leitura.livro_id == Livro.id)
                .where(Leitura.escola_id == escola_id))
    ids = set(aluno_ids) if aluno_ids is not None else None
    if ids is not None and 0 < len(ids) <= 50:     # poucos alunos: filtra no SQL
        consulta = consulta.where(Leitura.aluno_id.in_(ids))
    for aluno_id, titulo, nivel, tempo in db.execute(consulta).all():
        if ids is not None and aluno_id not in ids:
            continue
        saida.setdefault(aluno_id, []).append(
            LeituraItem(titulo or "", nivel or "", int(tempo or 0)))
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
