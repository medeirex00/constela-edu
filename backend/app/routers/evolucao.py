"""Evolução, páginas de turma/escola e comparadores (PRD §67–§78).

Endpoints somente-leitura: toda a informação vem dos snapshots imutáveis.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, get_usuario_atual
from app.models import Aluno, Usuario
from app.services import evolucao as svc

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Evolução"])


@router.get("/alunos/{aluno_id}/evolucao")
def evolucao_do_aluno(
    aluno_id: int,
    dias: int = Query(default=30, ge=1, le=366),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Linha do tempo completa + variação no período (PRD §67–§71)."""
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    return {
        "aluno_id": aluno_id,
        "nome": aluno.nome,
        "linha_do_tempo": svc.linha_do_tempo(db, escola_id, aluno_id),
        "resumo": svc.resumo_evolucao(db, escola_id, aluno_id, dias),
    }


@router.get("/ranking-evolucao")
def ranking_evolucao(
    dias: int = Query(default=30, ge=1, le=366),
    turma_id: int | None = Query(default=None),
    ano_escolar: str | None = Query(default=None),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Ranking independente do geral: quem mais cresceu no período (PRD §72)."""
    return [
        {
            "posicao": item.posicao,
            "aluno_id": item.aluno_id,
            "nome": item.nome,
            "turma": item.turma,
            "ano_escolar": item.ano_escolar,
            "nota_evolucao": item.nota_evolucao,
            "ganhos": item.ganhos,
        }
        for item in svc.ranking_evolucao(db, escola_id, dias, turma_id, ano_escolar)
    ]


@router.get("/turmas/{turma_id}/resumo")
def resumo_turma(
    turma_id: int,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Página da turma: médias, totais e indicadores (PRD §76–§77)."""
    resumo = svc.resumo_turma(db, escola_id, turma_id)
    if resumo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Turma não encontrada.")
    return resumo


@router.get("/resumo-escola")
def resumo_escola(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Página da escola: comparação entre turmas (PRD §78)."""
    return svc.resumo_escola(db, escola_id)


@router.get("/comparar")
def comparar(
    tipo_a: str = Query(pattern="^(aluno|turma)$"),
    id_a: int = Query(),
    tipo_b: str = Query(pattern="^(aluno|turma)$"),
    id_b: int = Query(),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Comparador aluno×aluno, aluno×turma e turma×turma (PRD §73–§75)."""
    resultado = svc.comparar(db, escola_id, tipo_a, id_a, tipo_b, id_b)
    if resultado is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Aluno ou turma não encontrado nesta escola.")
    return resultado
