"""Dependências de autenticação e autorização.

Toda permissão é validada aqui, no backend — o frontend nunca é a
única barreira (PRD §13, Permissões).
"""
from fastapi import Depends, HTTPException, Path, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decodificar_token
from app.models import Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")

# Papéis com permissão de escrita em métricas/configurações (PRD §13)
PODE_EDITAR_METRICAS = {"admin", "coordenador"}
PODE_ADMINISTRAR = {"admin"}


def get_usuario_atual(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    usuario_id = decodificar_token(token)
    if usuario_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida ou expirada.")
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or usuario.status != "ativo":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuário inativo ou inexistente.")
    return usuario


def exigir_papeis(*papeis: str):
    def dependencia(usuario: Usuario = Depends(get_usuario_atual)) -> Usuario:
        if usuario.is_global:
            return usuario
        if usuario.cargo not in papeis:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Você não possui permissão para esta ação.",
            )
        return usuario

    return dependencia


def escola_autorizada(
    escola_id: int = Path(...),
    usuario: Usuario = Depends(get_usuario_atual),
) -> int:
    """Isolamento multi-escolas: usuários comuns só acessam a própria escola."""
    if usuario.is_global:
        return escola_id
    if usuario.escola_id != escola_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Acesso negado aos dados desta escola.",
        )
    return escola_id
