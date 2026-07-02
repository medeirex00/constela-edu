"""Registro de auditoria — nada relevante acontece sem ficar no log (PRD §17)."""
from sqlalchemy.orm import Session

from app.models import LogAuditoria


def registrar(
    db: Session,
    acao: str,
    escola_id: int | None = None,
    usuario_id: int | None = None,
    entidade: str | None = None,
    entidade_id: int | None = None,
    detalhes: dict | None = None,
) -> None:
    db.add(
        LogAuditoria(
            escola_id=escola_id,
            usuario_id=usuario_id,
            acao=acao,
            entidade=entidade,
            entidade_id=entidade_id,
            detalhes=detalhes or {},
        )
    )
    # commit fica a cargo da operação principal, mantendo atomicidade
