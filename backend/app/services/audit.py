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
    # Notificação acionável por perfil (Fase 2): para os eventos conhecidos,
    # materializa 1 aviso com a rota da tela de ação. Import local evita ciclo
    # (notificacoes importa models/permissoes, não audit). No-op para as demais
    # ações. Fica na MESMA sessão → commit atômico com a operação principal.
    from app.services import notificacoes as _notif
    _notif.emitir_da_auditoria(db, acao, escola_id, autor_id=usuario_id,
                               entidade=entidade, entidade_id=entidade_id)
    # commit fica a cargo da operação principal, mantendo atomicidade
