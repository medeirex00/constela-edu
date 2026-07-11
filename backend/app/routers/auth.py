from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_usuario_atual
from app.core.rate_limit import (
    ip_do_cliente,
    limitador_conta,
    limitador_login,
    mascarar_ip,
)
from app.core.security import (
    criar_token,
    hash_senha,
    hash_token,
    validar_forca_senha,
    verificar_senha,
    verificar_senha_dummy,
)
from app.models import TokenResetSenha, Usuario
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
    ip = ip_do_cliente(request)          # completo: chave do limitador (precisão)
    ip_log = mascarar_ip(ip)             # mascarado: log de auditoria (LGPD)

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

    # Duas camadas: por (conta, IP) — freio fino — e por CONTA (sem IP) —
    # freio contra força-bruta distribuída (vários IPs) contra a mesma conta.
    if limitador_login.bloqueado(chave) or limitador_conta.bloqueado(identidade):
        espera = max(limitador_login.segundos_restantes(chave),
                     limitador_conta.segundos_restantes(identidade))
        registrar(db, "login.bloqueado", detalhes={"email": identidade, "ip": ip_log})
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
        limitador_conta.registrar_falha(identidade)
        registrar(db, "login.falhou",
                  detalhes={"email": entrada, "ip": ip_log, "motivo": "conta_inexistente"})
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "E-mail/usuário ou senha incorretos.")

    if not verificar_senha(form.password, usuario.senha_hash):
        limitador_login.registrar_falha(chave)
        limitador_conta.registrar_falha(identidade)
        registrar(db, "login.falhou", escola_id=usuario.escola_id, usuario_id=usuario.id,
                  detalhes={"email": identidade, "ip": ip_log, "motivo": "senha_incorreta"})
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "E-mail/usuário ou senha incorretos.")

    if usuario.status != "ativo":
        registrar(db, "login.falhou", escola_id=usuario.escola_id, usuario_id=usuario.id,
                  detalhes={"email": identidade, "ip": ip_log, "motivo": "conta_desativada"})
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Usuário desativado.")

    limitador_login.limpar(chave)
    limitador_conta.limpar(identidade)
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


# --- Redefinição de senha por token (público: a pessoa não consegue entrar) ---

def _expirado(momento: datetime) -> bool:
    """Compara com o instante atual tolerando datas ingênuas do banco (o SQLite
    não guarda fuso — trata como UTC)."""
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento < datetime.now(timezone.utc)


def _token_valido(db: Session, token_bruto: str | None) -> TokenResetSenha | None:
    """Registro do token se existir, não tiver sido usado e não estiver expirado."""
    if not token_bruto:
        return None
    registro = db.execute(
        select(TokenResetSenha).where(
            TokenResetSenha.token_hash == hash_token(token_bruto))
    ).scalar_one_or_none()
    if (registro is None or registro.usado_em is not None
            or _expirado(registro.expira_em)):
        return None
    return registro


class RedefinirSenhaIn(BaseModel):
    token: str = Field(min_length=8, max_length=200)
    nova_senha: str = Field(min_length=8, max_length=100)

    @field_validator("nova_senha")
    @classmethod
    def _forca(cls, valor: str) -> str:
        erro = validar_forca_senha(valor)
        if erro:
            raise ValueError(erro)
        return valor


@router.get("/redefinir-senha/{token}", response_model=dict)
def validar_link_reset(token: str, db: Session = Depends(get_db)):
    """Diz à tela se o link ainda vale (para mostrar o formulário ou avisar que
    expirou). Não revela nada além do primeiro nome, para a saudação."""
    registro = _token_valido(db, token)
    if registro is None:
        return {"valido": False}
    alvo = db.get(Usuario, registro.usuario_id)
    if alvo is None or alvo.status == "excluido":
        return {"valido": False}
    return {"valido": True, "nome": alvo.nome}


@router.post("/redefinir-senha", response_model=dict)
def consumir_link_reset(dados: RedefinirSenhaIn, db: Session = Depends(get_db)):
    """Define a nova senha a partir do token do link. O token é de USO ÚNICO
    (some assim que a senha é trocada) e todas as sessões antigas caem — a
    senha original nunca é recuperada, apenas substituída."""
    registro = _token_valido(db, dados.token)
    if registro is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Link inválido ou expirado. Peça um novo ao "
                            "administrador da escola.")
    alvo = db.get(Usuario, registro.usuario_id)
    if alvo is None or alvo.status == "excluido":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Conta indisponível. Fale com o administrador.")

    alvo.senha_hash = hash_senha(dados.nova_senha)
    registro.usado_em = datetime.now(timezone.utc)   # uso único
    alvo.token_version = (alvo.token_version or 0) + 1  # derruba sessões antigas
    registrar(db, "usuario.senha_redefinida_por_token", escola_id=alvo.escola_id,
              usuario_id=alvo.id, entidade="usuario", entidade_id=alvo.id,
              detalhes={"email": alvo.email})
    db.commit()
    return {"mensagem": "Senha redefinida. Você já pode entrar com a nova senha."}
