"""Inteligência Pedagógica (PRD §129–§153): índices e alertas automáticos.

Tudo é derivado dos dados existentes por regras transparentes — nenhum
modelo de IA participa destes cálculos, então os números são reproduzíveis
e auditáveis. O Assistente de IA (services/ia) usa estes mesmos índices
como contexto, nunca o contrário.

Índices (0–100):
  * Engajamento  — volume de atividade recente (nota de evolução em 30 dias)
  * Evolução     — crescimento sustentado (nota de evolução em 90 dias)
  * Persistência — constância: sequência de semanas ativas + volume de
                   tentativas de questões (continua tentando mesmo errando)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
from app.services import evolucao, gamificacao, scoring

DIAS_SEM_ATIVIDADE = 30
QUEDA_ACERTOS_PONTOS = 15.0
FRACAO_ABAIXO_TURMA = 0.5


def _pct_acertos(snap) -> float | None:
    if snap is None or not snap.questoes_tentativas:
        return None
    return round(snap.questoes_acertos / snap.questoes_tentativas * 100, 1)


def indices_da_escola(db: Session, escola_id: int) -> list[dict]:
    """Engajamento, evolução e persistência de cada aluno ativo."""
    engajamento = {
        item.aluno_id: item.nota_evolucao
        for item in evolucao.ranking_evolucao(db, escola_id, dias=30)
    }
    crescimento = {
        item.aluno_id: item.nota_evolucao
        for item in evolucao.ranking_evolucao(db, escola_id, dias=90)
    }

    escola = db.get(Escola, escola_id)
    # selectinload(Matricula.aluno): o laço lê matricula.aluno.nome; sem isto,
    # cada aluno dispararia um SELECT lazy (N+1). Carrega todos em 1 consulta.
    matriculas = db.execute(
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .options(selectinload(Matricula.aluno))
        .where(Matricula.escola_id == escola_id,
               Matricula.ano_letivo == escola.ano_letivo_ativo,
               Aluno.status == "ativo")
    ).all()

    serie_m = evolucao._series_por_aluno(db, escola_id, SnapshotMatific)
    serie_e = evolucao._series_por_aluno(db, escola_id, SnapshotElefante)
    max_tentativas = max(
        (s[-1].questoes_tentativas for s in serie_e.values() if s), default=0
    )

    itens = []
    for matricula, turma in matriculas:
        aluno_id = matricula.aluno_id
        sequencia = gamificacao.sequencia_semanas(
            serie_m.get(aluno_id, []), serie_e.get(aluno_id, [])
        )
        snap_e = serie_e.get(aluno_id, [])
        tentativas = snap_e[-1].questoes_tentativas if snap_e else 0
        # Persistência: constância semanal (até 60 pts) + volume de tentativas
        # relativo à escola (até 40 pts) — quem insiste pontua, mesmo errando.
        persistencia = min(60.0, sequencia * 15.0) + (
            scoring.normalizar(tentativas, max_tentativas) * 0.4
        )
        itens.append({
            "aluno_id": aluno_id,
            "nome": matricula.aluno.nome,
            "turma": turma.nome,
            "engajamento": round(engajamento.get(aluno_id, 0.0), 1),
            "evolucao": round(crescimento.get(aluno_id, 0.0), 1),
            "persistencia": round(min(100.0, persistencia), 1),
        })
    itens.sort(key=lambda item: -item["engajamento"])
    return itens


def alertas_da_escola(db: Session, escola_id: int) -> list[dict]:
    """Alertas automáticos (PRD §139): situações que pedem atenção do professor."""
    escola = db.get(Escola, escola_id)
    if escola is None:
        return []
    ano = escola.ano_letivo_ativo
    agora = datetime.now(timezone.utc)
    corte_atividade = agora - timedelta(days=DIAS_SEM_ATIVIDADE)

    # selectinload(Matricula.aluno): idem indices_da_escola — o laço lê
    # matricula.aluno.nome; evita N+1. Rota também usada pela sincronização
    # mobile e pelo contexto do Assistente.
    matriculas = db.execute(
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .options(selectinload(Matricula.aluno))
        .where(Matricula.escola_id == escola_id,
               Matricula.ano_letivo == ano,
               Aluno.status == "ativo")
    ).all()

    serie_m = evolucao._series_por_aluno(db, escola_id, SnapshotMatific)
    serie_e = evolucao._series_por_aluno(db, escola_id, SnapshotElefante)
    notas = {
        nota.aluno_id: nota
        for nota in db.execute(
            select(Nota).where(Nota.escola_id == escola_id, Nota.ano_letivo == ano)
        ).scalars()
    }

    # Média da turma para o alerta "muito abaixo da turma"
    media_turma: dict[int, float] = {}
    alunos_por_turma: dict[int, list[int]] = {}
    for matricula, turma in matriculas:
        alunos_por_turma.setdefault(turma.id, []).append(matricula.aluno_id)
    for turma_id, ids in alunos_por_turma.items():
        com_nota = [notas[i].nota_geral for i in ids if i in notas]
        media_turma[turma_id] = sum(com_nota) / len(com_nota) if com_nota else 0.0

    alertas: list[dict] = []
    for matricula, turma in matriculas:
        aluno_id = matricula.aluno_id
        nome = matricula.aluno.nome
        m = serie_m.get(aluno_id, [])
        e = serie_e.get(aluno_id, [])

        if not m and not e:
            alertas.append({
                "tipo": "sem_dados", "gravidade": "alta",
                "aluno_id": aluno_id, "nome": nome, "turma": turma.nome,
                "texto": f"{nome} ainda não tem nenhum dado importado.",
            })
            continue

        ultima = max(
            (s[-1].data_referencia for s in (m, e) if s),
        )
        ultima_cmp = ultima.replace(tzinfo=timezone.utc) if ultima.tzinfo is None else ultima
        if ultima_cmp < corte_atividade:
            dias = (agora - ultima_cmp).days
            alertas.append({
                "tipo": "sem_atividade", "gravidade": "alta",
                "aluno_id": aluno_id, "nome": nome, "turma": turma.nome,
                "texto": f"{nome} está sem novos dados há {dias} dias.",
            })

        # Queda no percentual de acertos entre os dois últimos snapshots
        if len(e) >= 2:
            atual, anterior = _pct_acertos(e[-1]), _pct_acertos(e[-2])
            if atual is not None and anterior is not None \
                    and anterior - atual >= QUEDA_ACERTOS_PONTOS:
                alertas.append({
                    "tipo": "queda_acertos", "gravidade": "media",
                    "aluno_id": aluno_id, "nome": nome, "turma": turma.nome,
                    "texto": f"{nome} caiu de {anterior}% para {atual}% de acertos nas questões.",
                })

        nota = notas.get(aluno_id)
        media = media_turma.get(turma.id, 0.0)
        if nota and media > 0 and nota.nota_geral < media * FRACAO_ABAIXO_TURMA:
            alertas.append({
                "tipo": "abaixo_da_turma", "gravidade": "media",
                "aluno_id": aluno_id, "nome": nome, "turma": turma.nome,
                "texto": (f"{nome} está com nota {nota.nota_geral:.1f}, "
                          f"menos da metade da média da turma ({media:.1f})."),
            })

    ordem = {"alta": 0, "media": 1, "baixa": 2}
    alertas.sort(key=lambda alerta: (ordem.get(alerta["gravidade"], 9), alerta["nome"]))
    return alertas
