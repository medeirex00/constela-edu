from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_usuario_atual
from app.core.security import criar_token, verificar_senha
from app.models import Usuario
from app.schemas import LoginOut, UsuarioOut
from app.services.audit import registrar

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post("/login", response_model=LoginOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    usuario = db.execute(
        select(Usuario).where(Usuario.email == form.username.lower().strip())
    ).scalar_one_or_none()
    if usuario is None or not verificar_senha(form.password, usuario.senha_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail ou senha incorretos.")
    if usuario.status != "ativo":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Usuário desativado.")

    usuario.ultimo_acesso = datetime.now(timezone.utc)
    registrar(db, "login", escola_id=usuario.escola_id, usuario_id=usuario.id)
    db.commit()

    return LoginOut(
        access_token=criar_token(usuario.id),
        usuario=UsuarioOut.model_validate(usuario),
    )


@router.get("/me", response_model=UsuarioOut)
def me(usuario: Usuario = Depends(get_usuario_atual)):
    return usuario
