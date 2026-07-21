from datetime import datetime

from sqlalchemy import Float, ForeignKey, String
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
    # Rede/Secretaria à qual a escola pertence (None = escola avulsa). Define
    # quais escolas entram no escopo de um usuário de rede (ver models/rede.py).
    rede_id: Mapped[int | None] = mapped_column(
        ForeignKey("redes.id", ondelete="SET NULL"), index=True)
    # Geolocalização e endereço — habilitam o MAPA da rede e a agregação por
    # município. Todos nullable: preenchidos por geocodificação (batch) ou à mão.
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    endereco: Mapped[str | None] = mapped_column(String(300))
    bairro: Mapped[str | None] = mapped_column(String(120))
    cep: Mapped[str | None] = mapped_column(String(9))
    # Código IBGE do município (7 dígitos) — chave normalizada de agregação.
    codigo_ibge: Mapped[str | None] = mapped_column(String(7), index=True)
    created_at: Mapped[datetime] = mapped_column(default=agora)
