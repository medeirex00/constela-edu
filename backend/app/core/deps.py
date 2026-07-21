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
from app.models import Escola, Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")

# Papéis com permissão de escrita em métricas/configurações (PRD §13)
PODE_EDITAR_METRICAS = {"admin", "coordenador"}
PODE_ADMINISTRAR = {"admin"}


def get_usuario_atual(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    payload = decodificar_token(token)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida ou expirada.")
    # Tokens com papel (ex.: "aluno" do Quest) NUNCA valem aqui: o `sub` deles
    # aponta para outra tabela — aceitá-los permitiria colisão de ids.
    if payload.get("papel"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida ou expirada.")
    usuario = db.get(Usuario, int(payload["sub"]))
    if usuario is None or usuario.status != "ativo":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuário inativo ou inexistente.")
    # Sessão emitida antes da última troca de senha é rejeitada (logout global).
    if int(payload.get("ver", 0)) != int(usuario.token_version or 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Sessão expirada. Entre novamente.")
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


def exigir_admin_global(usuario: Usuario = Depends(get_usuario_atual)) -> Usuario:
    """Ações que abrangem todas as escolas (criar escola, exclusão permanente)."""
    if not usuario.is_global:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Esta ação é exclusiva de administradores globais.",
        )
    return usuario


def escola_autorizada(
    escola_id: int = Path(...),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
) -> int:
    """Isolamento multi-escolas: o usuário só acessa escolas DENTRO do seu escopo.

    O escopo vem de `permissoes.escopo_escolas` (fonte única): `None` = todas
    (admin global); um conjunto = a própria escola OU todas as escolas da rede
    (secretaria). Para o caso comum (escola única) o comportamento é IDÊNTICO ao
    anterior — é extensão pura, não mudança.

    Também confirma que a escola existe — evita 500 (AttributeError) quando um
    admin global aponta para um id inexistente e impede escritas órfãs.
    """
    # Import local evita qualquer ciclo de importação (core ↔ services).
    from app.services.permissoes import escopo_escolas

    if db.get(Escola, escola_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    escopo = escopo_escolas(db, usuario)
    if escopo is None or escola_id in escopo:
        return escola_id
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Acesso negado aos dados desta escola.",
    )


def exigir_rede(
    rede_id: int = Path(...),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
) -> int:
    """Escopo de REDE/Secretaria: acessa a rede quem é admin global OU o usuário
    daquela rede (`usuario.rede_id == rede_id`). Um usuário de rede NÃO enxerga
    outra rede (isolamento entre redes — IDOR). Coordenador/professor de escola
    única (sem `rede_id`) não têm acesso a nenhuma rota `/redes/*`.
    """
    from app.models import Rede

    if db.get(Rede, rede_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rede não encontrada.")
    if usuario.is_global or usuario.rede_id == rede_id:
        return rede_id
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Acesso negado aos dados desta rede.",
    )
