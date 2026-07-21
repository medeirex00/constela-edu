"""Rede / Secretaria de Educação — o tier municipal (acima da escola).

Isolamento REAL: toda rota de dados passa por `exigir_rede`, que só libera a
rede do próprio usuário (`usuario.rede_id`) ou o admin global. Uma secretaria
NUNCA lê os dados de outra rede (IDOR entre redes barrado). Só AGREGA — não
reimplementa scoring nem toca em pesos/fórmulas.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import exigir_rede, get_usuario_atual
from app.models import Rede, Usuario
from app.services import rede as svc_rede

router = APIRouter(prefix="/redes", tags=["Rede / Secretaria"])


@router.get("")
def listar_redes(
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Redes visíveis ao usuário: o admin global vê todas; um usuário de rede vê
    só a sua; um usuário de escola única não vê nenhuma (lista vazia)."""
    consulta = select(Rede).where(Rede.status == "ativa").order_by(Rede.nome)
    if not usuario.is_global:
        if usuario.rede_id is None:
            return []
        consulta = consulta.where(Rede.id == usuario.rede_id)
    return [
        {"id": r.id, "nome": r.nome, "uf": r.uf, "codigo_ibge": r.codigo_ibge}
        for r in db.execute(consulta).scalars().all()
    ]


@router.get("/{rede_id}/dashboard")
def dashboard(
    rede_id: int = Depends(exigir_rede),
    db: Session = Depends(get_db),
):
    """Painel municipal: totais da rede + cartão de cada escola (com lat/lng para
    o mapa). Só dados agregados por escola — nada de PII de criança."""
    return svc_rede.dashboard_rede(db, rede_id)


@router.get("/{rede_id}/ranking")
def ranking(
    rede_id: int = Depends(exigir_rede),
    limite: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Ranking municipal POR ESCOLA (privacidade: não expõe ranking individual
    de crianças entre escolas). Ordena por média geral e participação."""
    return svc_rede.ranking_escolas(db, rede_id, limite=limite)
