from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import agora


class TokenResetSenha(Base):
    """Token de USO ÚNICO para redefinição de senha ("esqueci a senha").

    Guardamos apenas o HASH do token (SHA-256) — o token em texto só existe no
    link entregue ao usuário. Cada token tem validade (`expira_em`) e é
    invalidado ao ser usado (`usado_em`). A senha original nunca é recuperável;
    o fluxo apenas permite ESCOLHER uma nova senha.
    """

    __tablename__ = "tokens_reset_senha"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    # SHA-256 hex do token (64 chars). Único: dois tokens jamais colidem.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expira_em: Mapped[datetime] = mapped_column()
    # Preenchido no momento em que o token é consumido — bloqueia reuso.
    usado_em: Mapped[datetime | None] = mapped_column(default=None)
    # Quem gerou o link (admin/coordenador). Nulo em autoatendimento futuro.
    criado_por: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=agora)
