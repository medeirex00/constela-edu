"""Notificações acionáveis por perfil (Fase 2a).

Endpoints CENTRADOS NO USUÁRIO (não em /escolas/{id}): o feed é escolhido pelo
PERFIL de quem está logado, no servidor. Funciona para todos os papéis —
inclusive professor e Secretaria, que hoje tomavam 403 no feed antigo derivado
da auditoria (/escolas/{id}/notificacoes). A blindagem de PII é a do serviço:
Secretaria só recebe escopo 'rede'; professor só as turmas dele.
"""
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_usuario_atual
from app.models import Usuario
from app.services import notificacoes as svc

router = APIRouter(prefix="/notificacoes", tags=["Notificações"])


@router.get("")
def listar(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Feed do usuário (por perfil), do mais recente ao mais antigo, com `lida`."""
    return svc.feed(db, usuario)


@router.get("/contador")
def contador(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Quantas não-lidas — alimenta o badge do sino (busca em segundo plano)."""
    return {"nao_lidas": svc.contar_nao_lidas(db, usuario)}


@router.post("/marcar-lidas", status_code=status.HTTP_204_NO_CONTENT)
def marcar_lidas(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Marca todas como lidas (avança o marcador do usuário)."""
    svc.marcar_lidas(db, usuario)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
