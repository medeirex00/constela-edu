"""Catálogo de INDICADORES — o que é possível medir, declarado em código.

Cada indicador é um DADO (não código espalhado): o motor percorre o catálogo e,
para cada indicador ativo da escola, pede o valor bruto do aluno (via ``extrator``)
e aplica a régua. Adicionar um indicador (de qualquer plataforma) = acrescentar
uma entrada aqui + o coletor que popula o contexto do aluno. O motor NÃO muda.

Os campos são ricos de propósito: além de dirigir o cálculo, descrevem cada
indicador (nome, descrição, categoria, unidade, sentido) de forma que a IA os
consuma sem adivinhar nada — "o aluno tem elefante.tempo_leitura = 640 min
(Leitura, volume)".

O ``extrator`` recebe o CONTEXTO do aluno (um dict com os valores brutos já
carregados dos snapshots/derivações) e devolve o valor bruto do indicador. É PURO
e testável — não toca no banco; quem monta o contexto é o motor.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# Tipos permitidos (semântica p/ a IA e p/ escolher a régua padrão).
TIPOS = ("volume", "qualidade", "derivado")
UNIDADES = ("minutos", "pontos", "questoes", "estrelas", "atividades",
            "xp", "medalhas", "dias", "contagem", "taxa")
SENTIDOS = ("maior_melhor", "menor_melhor")


@dataclass(frozen=True)
class Indicador:
    """Um indicador do catálogo. ``id`` é ESTÁVEL e nunca reusado (é a chave que
    liga catálogo ↔ configuração da escola ↔ auditoria da nota)."""

    id: str                              # "elefante.tempo_leitura"
    nome: str                            # "Tempo de leitura"
    descricao: str                       # legível p/ gestor E p/ IA
    categoria: str                       # "Elefante Letrado" — agrupa na tela/IA
    plataforma: str                      # "elefante" | "matific" | "quest" | "sistema"
    tipo: str                            # volume | qualidade | derivado
    unidade: str                         # minutos | pontos | questoes | taxa | …
    chave_contexto: str                  # de onde o extrator lê no contexto do aluno
    sentido: str = "maior_melhor"
    peso_padrao: float = 0.0             # % padrão (configurável por escola)
    metodo_padrao: str = "percentil"     # régua padrão (id do registro de métodos)
    ao_vivo: bool = False                # true = consulta em tempo real; false = snapshot
    cache_s: int = 0                     # TTL do cache p/ ao_vivo (0 = não se aplica)
    extrator: Callable[[dict], float] | None = None  # (contexto_aluno) -> valor bruto
    metodos_permitidos: tuple[str, ...] = ()          # vazio = todos os do registro

    def valor(self, contexto: dict) -> float:
        """Valor bruto do indicador para um aluno, do contexto já carregado."""
        if self.extrator is not None:
            return float(self.extrator(contexto) or 0.0)
        return float((contexto or {}).get(self.chave_contexto) or 0.0)


def _num(ctx: dict, chave: str) -> float:
    try:
        return float((ctx or {}).get(chave) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _taxa_acerto(ctx: dict) -> float:
    """Aprovadas ÷ respondidas (0–1). Zero quando não respondeu nada — evita
    divisão por zero e o 'campeão' que acertou 1 de 1."""
    tent = _num(ctx, "questoes_tentativas")
    if tent <= 0:
        return 0.0
    return max(0.0, min(1.0, _num(ctx, "questoes_acertos") / tent))


# --- Catálogo inicial: Elefante Letrado --------------------------------------
# (Matific/Quest/Frequência entram no futuro SÓ acrescentando entradas aqui.)

CATALOGO: list[Indicador] = [
    Indicador(
        id="elefante.tempo_leitura",
        nome="Tempo de leitura",
        descricao="Minutos totais de leitura no período.",
        categoria="Elefante Letrado", plataforma="elefante",
        tipo="volume", unidade="minutos", chave_contexto="tempo_leitura_min",
        peso_padrao=35.0, metodo_padrao="percentil"),
    Indicador(
        id="elefante.pontos_leitura",
        nome="Pontos de leitura",
        descricao=("Pontos pela DIFICULDADE dos livros lidos (AA=1, B=2, … L=8), "
                   "usando a tabela de níveis configurável da escola — não é "
                   "'livros lidos' nem tempo."),
        categoria="Elefante Letrado", plataforma="elefante",
        tipo="derivado", unidade="pontos", chave_contexto="pontos_dificuldade",
        peso_padrao=35.0, metodo_padrao="percentil"),
    Indicador(
        id="elefante.questoes_respondidas",
        nome="Questões respondidas",
        descricao="Volume de questões respondidas no período (não 'aprovadas').",
        categoria="Elefante Letrado", plataforma="elefante",
        tipo="volume", unidade="questoes", chave_contexto="questoes_tentativas",
        peso_padrao=20.0, metodo_padrao="percentil",
        ao_vivo=True, cache_s=1800),   # consulta ao vivo + cache 30 min
    Indicador(
        id="elefante.taxa_acerto",
        nome="Taxa de acerto",
        descricao=("Proporção de acertos (aprovadas ÷ respondidas). Indicador de "
                   "QUALIDADE — peso baixo, nunca pontuação absoluta."),
        categoria="Elefante Letrado", plataforma="elefante",
        tipo="qualidade", unidade="taxa", chave_contexto="",
        peso_padrao=10.0, metodo_padrao="fixa",
        extrator=_taxa_acerto, metodos_permitidos=("fixa",)),
]

_POR_ID = {ind.id: ind for ind in CATALOGO}


def obter(indicador_id: str) -> Indicador | None:
    return _POR_ID.get(indicador_id)


def por_plataforma(plataforma: str) -> list[Indicador]:
    return [i for i in CATALOGO if i.plataforma == plataforma]


def criterios_padrao(plataforma: str | None = None) -> list[dict]:
    """Config PADRÃO (semente) dos critérios — o que a migração de dados grava por
    escola. Cada critério referencia um indicador do catálogo pelo id."""
    inds = CATALOGO if plataforma is None else por_plataforma(plataforma)
    return [
        {"id": ind.id, "peso": ind.peso_padrao, "ativo": True, "ordem": i + 1,
         "referencia": {"metodo": ind.metodo_padrao, "coorte": "escola",
                        "parametros": {}}}
        for i, ind in enumerate(inds)
    ]
