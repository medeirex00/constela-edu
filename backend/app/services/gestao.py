"""Consolidações de GESTÃO da escola (coordenador/gestor).

Agrega os dados por escola que já existem numa visão POR PROFESSOR — a lacuna
que faltava para o coordenador acompanhar a equipe docente. Não reimplementa
scoring: usa as notas/matrículas já calculadas.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Aluno, Escola, Matricula, Nota, Professor, Turma


def consolidado_por_professor(db: Session, escola_id: int) -> list[dict]:
    """Uma linha por professor (regente das turmas): nº de turmas/alunos, média
    geral e participação, com o detalhe por turma. Turmas sem professor caem em
    'Sem professor'. Ordena por média geral (desc)."""
    escola = db.get(Escola, escola_id)
    if escola is None:
        return []
    ano = escola.ano_letivo_ativo

    turmas = db.execute(
        select(Turma, Professor.nome)
        .outerjoin(Professor, Turma.professor_id == Professor.id)
        .where(Turma.escola_id == escola_id, Turma.ano_letivo == ano, Turma.status == "ativa")
    ).all()

    alunos_por_turma = dict(db.execute(
        select(Matricula.turma_id, func.count(func.distinct(Matricula.aluno_id)))
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .where(Matricula.escola_id == escola_id, Matricula.ano_letivo == ano,
               Aluno.status == "ativo")
        .group_by(Matricula.turma_id)
    ).all())

    notas_por_turma: dict[int, list[float]] = {}
    for turma_id, nota_geral in db.execute(
        select(Matricula.turma_id, Nota.nota_geral)
        .join(Nota, (Nota.aluno_id == Matricula.aluno_id)
              & (Nota.ano_letivo == ano) & (Nota.escola_id == escola_id))
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .where(Matricula.escola_id == escola_id, Matricula.ano_letivo == ano,
               Aluno.status == "ativo")
    ).all():
        notas_por_turma.setdefault(turma_id, []).append(nota_geral)

    grupos: dict[int | None, dict] = {}
    for turma, professor_nome in turmas:
        g = grupos.setdefault(turma.professor_id, {
            "professor_id": turma.professor_id,
            "professor_nome": professor_nome or "Sem professor",
            "total_turmas": 0, "total_alunos": 0, "turmas": [], "_notas": [],
        })
        alunos = int(alunos_por_turma.get(turma.id, 0))
        notas = notas_por_turma.get(turma.id, [])
        g["total_turmas"] += 1
        g["total_alunos"] += alunos
        g["_notas"].extend(notas)
        g["turmas"].append({
            "turma_id": turma.id, "nome": turma.nome, "total_alunos": alunos,
            "alunos_com_dados": len(notas),
            "media_geral": round(sum(notas) / len(notas), 1) if notas else 0.0,
        })

    saida = []
    for g in grupos.values():
        notas = g.pop("_notas")
        g["alunos_com_dados"] = len(notas)
        g["media_geral"] = round(sum(notas) / len(notas), 1) if notas else 0.0
        g["participacao"] = round(len(notas) / g["total_alunos"] * 100, 1) if g["total_alunos"] else 0.0
        saida.append(g)
    saida.sort(key=lambda x: (-x["media_geral"], x["professor_nome"].casefold()))
    return saida
