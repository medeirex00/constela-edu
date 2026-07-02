"""Gamificação (PRD §64, §79–§84): mural, destaques, XP e conquistas."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, get_usuario_atual
from app.models import Aluno, Usuario
from app.services import gamificacao as svc

router = APIRouter(prefix="/escolas/{escola_id}/gamificacao", tags=["Gamificação"])


@router.get("/mural")
def mural(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Mural da escola: Aluno do Dia/Semana/Mês + eventos recentes (§83)."""
    return svc.mural(db, escola_id)


@router.get("/ranking-xp")
def ranking_xp(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Ranking por XP/nível — motivacional, separado das notas (§81)."""
    return svc.ranking_xp(db, escola_id)


@router.get("/alunos/{aluno_id}")
def gamificacao_do_aluno(
    aluno_id: int,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """XP, nível, sequência e todas as conquistas (com progresso) do aluno."""
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    resultado = svc.gamificacao_do_aluno(db, escola_id, aluno_id)
    resultado["nome"] = aluno.nome
    return resultado
