from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_usuario_atual
from app.core.rate_limit import ip_do_cliente, limitador_login
from app.core.security import criar_token, verificar_senha, verificar_senha_dummy
from app.models import Usuario
from app.schemas import LoginOut, UsuarioOut
from app.services.audit import registrar

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post("/login", response_model=LoginOut)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    email = form.username.lower().strip()
    ip = ip_do_cliente(request)
    chave = f"{email}|{ip}"

    if limitador_login.bloqueado(chave):
        espera = limitador_login.segundos_restantes(chave)
        registrar(db, "login.bloqueado", detalhes={"email": email, "ip": ip})
        db.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Muitas tentativas. Aguarde {max(1, espera // 60) } minuto(s) e "
            "tente novamente.",
        )

    usuario = db.execute(
        select(Usuario).where(Usuario.email == email)
    ).scalar_one_or_none()

    if usuario is None:
        # Equaliza o tempo de resposta para não revelar se o e-mail existe.
        verificar_senha_dummy()
        limitador_login.registrar_falha(chave)
        registrar(db, "login.falhou",
                  detalhes={"email": email, "ip": ip, "motivo": "email_inexistente"})
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail ou senha incorretos.")

    if not verificar_senha(form.password, usuario.senha_hash):
        limitador_login.registrar_falha(chave)
        registrar(db, "login.falhou", escola_id=usuario.escola_id, usuario_id=usuario.id,
                  detalhes={"email": email, "ip": ip, "motivo": "senha_incorreta"})
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail ou senha incorretos.")

    if usuario.status != "ativo":
        registrar(db, "login.falhou", escola_id=usuario.escola_id, usuario_id=usuario.id,
                  detalhes={"email": email, "ip": ip, "motivo": "conta_desativada"})
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Usuário desativado.")

    limitador_login.limpar(chave)
    usuario.ultimo_acesso = datetime.now(timezone.utc)
    registrar(db, "login", escola_id=usuario.escola_id, usuario_id=usuario.id)
    db.commit()

    return LoginOut(
        access_token=criar_token(usuario.id, usuario.token_version),
        usuario=UsuarioOut.model_validate(usuario),
    )


@router.get("/me", response_model=UsuarioOut)
def me(usuario: Usuario = Depends(get_usuario_atual)):
    return usuario
