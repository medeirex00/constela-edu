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
    # Aceita e-mail OU nome de usuário (com ou sem o "@" na frente).
    entrada = form.username.lower().strip().lstrip("@")
    ip = ip_do_cliente(request)

    usuario = db.execute(
        select(Usuario).where(Usuario.email == entrada)
    ).scalar_one_or_none()
    if usuario is None:
        usuario = db.execute(
            select(Usuario).where(Usuario.username == entrada)
        ).scalar_one_or_none()

    # O limitador conta pela CONTA (e-mail canônico): tentar pelo e-mail e
    # pelo @username soma no MESMO contador — dois identificadores não podem
    # dobrar o orçamento de força bruta contra a mesma vítima.
    identidade = usuario.email if usuario is not None else entrada
    chave = f"{identidade}|{ip}"

    if limitador_login.bloqueado(chave):
        espera = limitador_login.segundos_restantes(chave)
        registrar(db, "login.bloqueado", detalhes={"email": identidade, "ip": ip})
        db.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Muitas tentativas. Aguarde {max(1, espera // 60) } minuto(s) e "
            "tente novamente.",
        )

    if usuario is None:
        # Equaliza o tempo de resposta para não revelar se a conta existe.
        verificar_senha_dummy()
        limitador_login.registrar_falha(chave)
        registrar(db, "login.falhou",
                  detalhes={"email": entrada, "ip": ip, "motivo": "conta_inexistente"})
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "E-mail/usuário ou senha incorretos.")

    if not verificar_senha(form.password, usuario.senha_hash):
        limitador_login.registrar_falha(chave)
        registrar(db, "login.falhou", escola_id=usuario.escola_id, usuario_id=usuario.id,
                  detalhes={"email": identidade, "ip": ip, "motivo": "senha_incorreta"})
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "E-mail/usuário ou senha incorretos.")

    if usuario.status != "ativo":
        registrar(db, "login.falhou", escola_id=usuario.escola_id, usuario_id=usuario.id,
                  detalhes={"email": identidade, "ip": ip, "motivo": "conta_desativada"})
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
