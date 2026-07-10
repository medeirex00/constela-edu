from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import agora


class DispositivoMovel(Base):
    """Aparelho registrado para notificações push (app mobile).

    O token do Expo Push identifica o aparelho; um mesmo usuário pode ter
    vários aparelhos e o mesmo aparelho troca de dono ao fazer login com
    outra conta (upsert pelo token).
    """

    __tablename__ = "dispositivos_moveis"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    token_push: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    plataforma: Mapped[str] = mapped_column(String(20))  # android | ios
    created_at: Mapped[datetime] = mapped_column(default=agora)
    updated_at: Mapped[datetime] = mapped_column(default=agora, onupdate=agora)
