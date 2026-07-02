from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import agora


class Escola(Base):
    """Raiz do modelo multi-tenant: toda informação pertence a uma escola."""

    __tablename__ = "escolas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(200), index=True)
    cidade: Mapped[str | None] = mapped_column(String(120))
    estado: Mapped[str | None] = mapped_column(String(2))
    logotipo_url: Mapped[str | None] = mapped_column(String(500))
    ano_letivo_ativo: Mapped[int] = mapped_column(default=2026)
    status: Mapped[str] = mapped_column(String(20), default="ativa")  # ativa | inativa
    created_at: Mapped[datetime] = mapped_column(default=agora)
