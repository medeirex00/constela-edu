from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import agora


class Rede(Base):
    """Rede de ensino / Secretaria de Educação — o agrupador ACIMA da escola.

    Uma rede reúne várias escolas (ex.: a rede municipal de Caraguatatuba). É o
    que dá escopo ao perfil "Secretaria": um usuário com ``rede_id`` enxerga
    TODAS as escolas dessa rede (mas não as de outras redes), sem precisar ser
    ``is_global``. O isolamento continua sendo por escola — a rede só define
    QUAIS escolas entram no escopo do usuário. A secretaria só AGREGA: nunca
    reimplementa scoring nem vê a PII de criança de escola nenhuma.
    """

    __tablename__ = "redes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(200), index=True)
    uf: Mapped[str | None] = mapped_column(String(2))
    # Código IBGE do município (7 dígitos) — chave normalizada para agregação
    # municipal, independente de variações de grafia do nome da cidade.
    codigo_ibge: Mapped[str | None] = mapped_column(String(7), index=True)
    status: Mapped[str] = mapped_column(String(20), default="ativa")  # ativa | inativa
    created_at: Mapped[datetime] = mapped_column(default=agora)
