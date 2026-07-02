from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import agora


class ConversaIA(Base):
    """Conversa com o Assistente Pedagógico (PRD §160).

    Toda conversa fica registrada com autor e escola — o log completo
    exigido pelo §169 vive em `mensagens_ia`.
    """

    __tablename__ = "conversas_ia"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    titulo: Mapped[str] = mapped_column(String(200), default="Nova conversa")
    provedor: Mapped[str] = mapped_column(String(30), default="local")
    created_at: Mapped[datetime] = mapped_column(default=agora)


class MensagemIA(Base):
    __tablename__ = "mensagens_ia"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversa_id: Mapped[int] = mapped_column(ForeignKey("conversas_ia.id"), index=True)
    papel: Mapped[str] = mapped_column(String(20))  # usuario | assistente
    conteudo: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=agora)
