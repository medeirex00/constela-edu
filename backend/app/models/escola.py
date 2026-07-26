from datetime import datetime

from sqlalchemy import ForeignKey, String
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
    # Rede/Secretaria à qual a escola pertence (nulo = escola avulsa, sem rede).
    # É o que o tier Secretaria agrega — sem tocar no isolamento por escola.
    rede_id: Mapped[int | None] = mapped_column(
        ForeignKey("redes.id", ondelete="SET NULL"), index=True)
    # Coordenadas para o mapa da rede (opcional; preenchidas por geocodificação).
    latitude: Mapped[float | None] = mapped_column(default=None)
    longitude: Mapped[float | None] = mapped_column(default=None)
    # Código INEP da escola (8 dígitos) — identificador OFICIAL para casar com as
    # bases de avaliações externas (SAEB/IDEB/...) sem depender do nome.
    codigo_inep: Mapped[str | None] = mapped_column(String(8), index=True, default=None)
    created_at: Mapped[datetime] = mapped_column(default=agora)
