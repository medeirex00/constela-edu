"""Evolução e histórico (PRD §67–§78).

Toda a base vem dos snapshots imutáveis da Fase 1: a evolução é sempre a
comparação entre o último snapshot anterior ao período (linha de base) e o
snapshot mais recente. Nenhum dado novo é gravado aqui — apenas leitura.

O Ranking de Evolução reaproveita o próprio motor de cálculo aplicado aos
GANHOS do período: os mesmos pesos configuráveis, a mesma normalização
0–100 (referência = maior ganho da escola). Indicadores não cumulativos
(pontuação média) entram pela variação positiva — quem manteve não perde,
quem cresceu pontua.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Aluno,
    Escola,
    Matricula,
    Nota,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import scoring

CAMPOS_MATIFIC = ("atividades", "estrelas", "pontuacao_media")
CAMPOS_ELEFANTE = ("livros_unicos", "tempo_leitura_min", "questoes_tentativas", "questoes_acertos")


def _sem_fuso(momento: datetime) -> datetime:
    """SQLite devolve datetimes ingênuos; normaliza para comparar com segurança."""
    return momento.replace(tzinfo=None) if momento.tzinfo else momento


def _series_por_aluno(db: Session, escola_id: int, modelo) -> dict[int, list]:
    """Todos os snapshots da escola agrupados por aluno, em ordem cronológica."""
    series: dict[int, list] = {}
    for snap in db.execute(
        select(modelo).where(modelo.escola_id == escola_id).order_by(modelo.id)
    ).scalars():
        series.setdefault(snap.aluno_id, []).append(snap)
    return series


def _baseline(serie: list, inicio: datetime):
    """Último snapshot ANTERIOR ao início do período (None = começou do zero)."""
    inicio = _sem_fuso(inicio)
    anterior = None
    for snap in serie:
        if _sem_fuso(snap.data_referencia) < inicio:
            anterior = snap
    return anterior


def _delta(atual, anterior, campo: str) -> float:
    """Ganho no período, nunca negativo (dados cumulativos não regridem;
    correções manuais para baixo não podem gerar evolução negativa)."""
    valor_atual = float(getattr(atual, campo, 0) or 0) if atual else 0.0
    valor_anterior = float(getattr(anterior, campo, 0) or 0) if anterior else 0.0
    return max(0.0, round(valor_atual - valor_anterior, 2))


def _delta_niveis(atual, anterior) -> dict[str, int]:
    atuais: dict = (atual.livros_por_nivel or {}) if atual else {}
    anteriores: dict = (anterior.livros_por_nivel or {}) if anterior else {}
    ganhos = {}
    for codigo, quantidade in atuais.items():
        ganho = int(quantidade) - int(anteriores.get(codigo, 0))
        if ganho > 0:
            ganhos[codigo] = ganho
    return ganhos


# ---------------------------------------------------------------------------
# Linha do tempo e resumo de evolução por aluno (PRD §67–§71)
# ---------------------------------------------------------------------------

def linha_do_tempo(db: Session, escola_id: int, aluno_id: int) -> dict:
    matific = db.execute(
        select(SnapshotMatific)
        .where(SnapshotMatific.escola_id == escola_id, SnapshotMatific.aluno_id == aluno_id)
        .order_by(SnapshotMatific.id)
    ).scalars().all()
    elefante = db.execute(
        select(SnapshotElefante)
        .where(SnapshotElefante.escola_id == escola_id, SnapshotElefante.aluno_id == aluno_id)
        .order_by(SnapshotElefante.id)
    ).scalars().all()
    return {
        "matific": [
            {
                "data": snap.data_referencia,
                "atividades": snap.atividades,
                "estrelas": snap.estrelas,
                "pontuacao_media": snap.pontuacao_media,
            }
            for snap in matific
        ],
        "elefante": [
            {
                "data": snap.data_referencia,
                "livros_unicos": snap.livros_unicos,
                "tempo_leitura_min": snap.tempo_leitura_min,
                "questoes_tentativas": snap.questoes_tentativas,
                "questoes_acertos": snap.questoes_acertos,
            }
            for snap in elefante
        ],
    }


def resumo_evolucao(db: Session, escola_id: int, aluno_id: int, dias: int) -> dict:
    """Variação de cada indicador no período, com percentual quando possível."""
    inicio = datetime.now(timezone.utc) - timedelta(days=dias)
    indicadores = []
    for modelo, campos in ((SnapshotMatific, CAMPOS_MATIFIC), (SnapshotElefante, CAMPOS_ELEFANTE)):
        serie = [
            snap for snap in db.execute(
                select(modelo)
                .where(modelo.escola_id == escola_id, modelo.aluno_id == aluno_id)
                .order_by(modelo.id)
            ).scalars()
        ]
        atual = serie[-1] if serie else None
        anterior = _baseline(serie, inicio)
        for campo in campos:
            valor_inicial = float(getattr(anterior, campo, 0) or 0) if anterior else 0.0
            valor_atual = float(getattr(atual, campo, 0) or 0) if atual else 0.0
            variacao = round(valor_atual - valor_inicial, 2)
            indicadores.append({
                "indicador": campo,
                "inicial": valor_inicial,
                "atual": valor_atual,
                "variacao": variacao,
                "percentual": round(variacao / valor_inicial * 100, 1) if valor_inicial else None,
            })
    return {"dias": dias, "indicadores": indicadores}


# ---------------------------------------------------------------------------
# Ranking de Evolução (PRD §72 — independente do Ranking Geral)
# ---------------------------------------------------------------------------

@dataclass
class ItemEvolucao:
    aluno_id: int
    nome: str
    turma: str
    ano_escolar: str
    nota_evolucao: float
    ganhos: dict
    posicao: int = 0


def ranking_evolucao(db: Session, escola_id: int, dias: int = 30,
                     turma_id: int | None = None,
                     ano_escolar: str | None = None) -> list[ItemEvolucao]:
    escola = db.get(Escola, escola_id)
    if escola is None:
        return []
    inicio = datetime.now(timezone.utc) - timedelta(days=dias)

    consulta = (
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .where(
            Matricula.escola_id == escola_id,
            Matricula.ano_letivo == escola.ano_letivo_ativo,
            Aluno.status == "ativo",
        )
    )
    if turma_id:
        consulta = consulta.where(Turma.id == turma_id)
    if ano_escolar:
        consulta = consulta.where(Turma.ano_escolar == ano_escolar)
    consulta = consulta.options(selectinload(Matricula.aluno))  # evita N+1
    matriculas = db.execute(consulta).all()

    serie_m = _series_por_aluno(db, escola_id, SnapshotMatific)
    serie_e = _series_por_aluno(db, escola_id, SnapshotElefante)
    mapa_dif = scoring._mapa_dificuldade(db, escola_id)

    # Ganhos por aluno no período (snapshots sintéticos alimentam o motor)
    ganhos_m: dict[int, SimpleNamespace] = {}
    ganhos_e: dict[int, SimpleNamespace] = {}
    pontos_dif: dict[int, float] = {}
    for matricula, turma in matriculas:
        aluno_id = matricula.aluno_id
        serie = serie_m.get(aluno_id, [])
        atual, anterior = (serie[-1] if serie else None), _baseline(serie_m.get(aluno_id, []), inicio)
        ganhos_m[aluno_id] = SimpleNamespace(
            atividades=_delta(atual, anterior, "atividades"),
            estrelas=_delta(atual, anterior, "estrelas"),
            pontuacao_media=_delta(atual, anterior, "pontuacao_media"),
        )
        serie = serie_e.get(aluno_id, [])
        atual, anterior = (serie[-1] if serie else None), _baseline(serie_e.get(aluno_id, []), inicio)
        ganhos_e[aluno_id] = SimpleNamespace(
            livros_unicos=_delta(atual, anterior, "livros_unicos"),
            tempo_leitura_min=_delta(atual, anterior, "tempo_leitura_min"),
            questoes_tentativas=_delta(atual, anterior, "questoes_tentativas"),
            questoes_acertos=_delta(atual, anterior, "questoes_acertos"),
        )
        pontos_dif[aluno_id] = scoring._pontos_dificuldade(
            _delta_niveis(atual, anterior), turma.ano_escolar, mapa_dif
        )

    # Referências = maiores ganhos da escola no período (sempre automático)
    refs = {
        "max_atividades": max((g.atividades for g in ganhos_m.values()), default=0),
        "max_media": max((g.pontuacao_media for g in ganhos_m.values()), default=0),
        "max_estrelas": max((g.estrelas for g in ganhos_m.values()), default=0),
        "max_livros": max((g.livros_unicos for g in ganhos_e.values()), default=0),
        "max_pontos_dificuldade": max(pontos_dif.values(), default=0),
        "max_tentativas": max((g.questoes_tentativas for g in ganhos_e.values()), default=0),
        "max_acertos": max((g.questoes_acertos for g in ganhos_e.values()), default=0),
        "max_tempo": max((g.tempo_leitura_min for g in ganhos_e.values()), default=0),
    }

    p_matific = scoring.obter_pesos(db, escola_id, "pesos.matific")
    p_elefante = scoring.obter_pesos(db, escola_id, "pesos.elefante")
    p_questoes = scoring.obter_pesos(db, escola_id, "pesos.questoes")
    p_geral = scoring.obter_pesos(db, escola_id, "pesos.geral")
    pct_matific = scoring.obter_pesos_brutos(db, escola_id, "pesos.matific")
    pct_elefante = scoring.obter_pesos_brutos(db, escola_id, "pesos.elefante")
    pct_questoes = scoring.obter_pesos_brutos(db, escola_id, "pesos.questoes")

    itens: list[ItemEvolucao] = []
    for matricula, turma in matriculas:
        aluno_id = matricula.aluno_id
        nota_m, _ = scoring.calcular_matific(ganhos_m[aluno_id], refs, p_matific, pct_matific)
        nota_e, _, _ = scoring.calcular_elefante(
            ganhos_e[aluno_id], pontos_dif[aluno_id], refs,
            p_elefante, pct_elefante, p_questoes, pct_questoes,
        )
        nota = round(nota_m * p_geral.get("matific", 0) + nota_e * p_geral.get("elefante", 0), 2)
        ganhos = {
            "atividades": ganhos_m[aluno_id].atividades,
            "estrelas": ganhos_m[aluno_id].estrelas,
            "livros": ganhos_e[aluno_id].livros_unicos,
            "tempo_leitura_min": ganhos_e[aluno_id].tempo_leitura_min,
            "acertos": ganhos_e[aluno_id].questoes_acertos,
        }
        itens.append(ItemEvolucao(
            aluno_id=aluno_id, nome=matricula.aluno.nome, turma=turma.nome,
            ano_escolar=turma.ano_escolar, nota_evolucao=nota, ganhos=ganhos,
        ))

    itens.sort(key=lambda item: (-item.nota_evolucao, item.nome.casefold()))
    for posicao, item in enumerate(itens, start=1):
        item.posicao = posicao
    return itens


# ---------------------------------------------------------------------------
# Agregados de turma e escola (PRD §76–§78)
# ---------------------------------------------------------------------------

def _indicadores_atuais(db: Session, escola_id: int, aluno_ids: list[int],
                        matific=None, elefante=None) -> dict:
    """Soma/média dos snapshots mais recentes dos alunos indicados.

    `matific`/`elefante` pré-carregados evitam varrer a escola inteira a
    cada turma (resumo_escola já carrega uma vez e repassa)."""
    if matific is None:
        matific = scoring._snapshots_atuais(db, escola_id, SnapshotMatific)
    if elefante is None:
        elefante = scoring._snapshots_atuais(db, escola_id, SnapshotElefante)
    total = {
        "atividades": 0, "estrelas": 0, "pontuacao_media": 0.0,
        "livros_unicos": 0, "tempo_leitura_min": 0,
        "questoes_tentativas": 0, "questoes_acertos": 0,
    }
    com_media = 0
    for aluno_id in aluno_ids:
        snap_m = matific.get(aluno_id)
        if snap_m:
            total["atividades"] += snap_m.atividades
            total["estrelas"] += snap_m.estrelas
            total["pontuacao_media"] += snap_m.pontuacao_media
            com_media += 1
        snap_e = elefante.get(aluno_id)
        if snap_e:
            total["livros_unicos"] += snap_e.livros_unicos
            total["tempo_leitura_min"] += snap_e.tempo_leitura_min
            total["questoes_tentativas"] += snap_e.questoes_tentativas
            total["questoes_acertos"] += snap_e.questoes_acertos
    total["pontuacao_media"] = round(total["pontuacao_media"] / com_media, 2) if com_media else 0.0
    return total


def resumo_turma(db: Session, escola_id: int, turma_id: int,
                 matific=None, elefante=None) -> dict | None:
    turma = db.get(Turma, turma_id)
    if turma is None or turma.escola_id != escola_id:
        return None
    escola = db.get(Escola, escola_id)
    matriculas = db.execute(
        select(Matricula)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .where(Matricula.turma_id == turma_id,
               Matricula.ano_letivo == escola.ano_letivo_ativo,
               Aluno.status == "ativo")
    ).scalars().all()
    aluno_ids = [m.aluno_id for m in matriculas]

    notas = db.execute(
        select(Nota).where(Nota.escola_id == escola_id,
                           Nota.ano_letivo == escola.ano_letivo_ativo,
                           Nota.aluno_id.in_(aluno_ids or [0]))
    ).scalars().all()
    media_geral = round(sum(n.nota_geral for n in notas) / len(notas), 2) if notas else 0.0
    media_matific = round(sum(n.nota_matific for n in notas) / len(notas), 2) if notas else 0.0
    media_elefante = round(sum(n.nota_elefante for n in notas) / len(notas), 2) if notas else 0.0

    return {
        "turma": {"id": turma.id, "nome": turma.nome, "ano_escolar": turma.ano_escolar},
        "total_alunos": len(aluno_ids),
        "media_geral": media_geral,
        "media_matific": media_matific,
        "media_elefante": media_elefante,
        "indicadores": _indicadores_atuais(db, escola_id, aluno_ids, matific, elefante),
    }


def resumo_escola(db: Session, escola_id: int) -> dict:
    """Visão da escola inteira: totais e comparação entre turmas (PRD §78)."""
    escola = db.get(Escola, escola_id)
    turmas = db.execute(
        select(Turma).where(Turma.escola_id == escola_id,
                            Turma.ano_letivo == escola.ano_letivo_ativo)
        .order_by(Turma.ano_escolar, Turma.nome)
    ).scalars().all()
    # Carrega os snapshots da escola UMA vez e repassa a cada turma (antes,
    # cada turma varria a escola inteira duas vezes).
    matific = scoring._snapshots_atuais(db, escola_id, SnapshotMatific)
    elefante = scoring._snapshots_atuais(db, escola_id, SnapshotElefante)
    return {
        "escola": {"id": escola.id, "nome": escola.nome},
        "turmas": [resumo_turma(db, escola_id, turma.id, matific, elefante)
                   for turma in turmas],
    }


# ---------------------------------------------------------------------------
# Comparadores (PRD §73–§75)
# ---------------------------------------------------------------------------

def _lado_aluno(db: Session, escola_id: int, aluno_id: int) -> dict | None:
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        return None
    escola = db.get(Escola, escola_id)
    nota = db.execute(
        select(Nota).where(Nota.aluno_id == aluno_id,
                           Nota.ano_letivo == escola.ano_letivo_ativo)
    ).scalar_one_or_none()
    return {
        "tipo": "aluno",
        "id": aluno.id,
        "nome": aluno.nome,
        "indicadores": _indicadores_atuais(db, escola_id, [aluno_id]),
        "notas": {
            "matific": nota.nota_matific if nota else 0.0,
            "elefante": nota.nota_elefante if nota else 0.0,
            "geral": nota.nota_geral if nota else 0.0,
            "posicao": nota.posicao if nota else None,
        },
    }


def _lado_turma(db: Session, escola_id: int, turma_id: int) -> dict | None:
    resumo = resumo_turma(db, escola_id, turma_id)
    if resumo is None:
        return None
    return {
        "tipo": "turma",
        "id": resumo["turma"]["id"],
        "nome": resumo["turma"]["nome"],
        "total_alunos": resumo["total_alunos"],
        "indicadores": resumo["indicadores"],
        "notas": {
            "matific": resumo["media_matific"],
            "elefante": resumo["media_elefante"],
            "geral": resumo["media_geral"],
            "posicao": None,
        },
    }


def comparar(db: Session, escola_id: int, tipo_a: str, id_a: int,
             tipo_b: str, id_b: int) -> dict | None:
    lados = []
    for tipo, identificador in ((tipo_a, id_a), (tipo_b, id_b)):
        lado = (_lado_aluno if tipo == "aluno" else _lado_turma)(db, escola_id, identificador)
        if lado is None:
            return None
        lados.append(lado)
    return {"a": lados[0], "b": lados[1]}
