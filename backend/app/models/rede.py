from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, String
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
    # Painel público da Secretaria (vitrine SEM login): quando definido, habilita
    # /publico/rede/{token} com as MELHORES ESCOLAS (top 5 em leitura e matemática)
    # — NUNCA nome de criança. Nulo = desligado. Trocar o token invalida o link.
    token_publico: Mapped[str | None] = mapped_column(String(64), unique=True,
                                                      index=True, default=None)
    created_at: Mapped[datetime] = mapped_column(default=agora)


class MetaRede(Base):
    """Meta (objetivo) da rede para um INDICADOR consolidado — o que a Secretaria
    quer que a rede alcance. O progresso é calculado sobre os dados REAIS (totais
    da rede / cartões por escola); a meta em si é o único dado 'cadastrado'. Uma
    meta por (rede, métrica) — redefinir sobrescreve o alvo anterior.
    """

    __tablename__ = "metas_rede"
    __table_args__ = (
        Index("uq_meta_rede_metrica", "rede_id", "metrica", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rede_id: Mapped[int] = mapped_column(
        ForeignKey("redes.id", ondelete="CASCADE"), index=True)
    # media_geral | media_elefante | media_matific | adocao | livros | atividades
    metrica: Mapped[str] = mapped_column(String(30))
    alvo: Mapped[float] = mapped_column(Float)   # valor-alvo do indicador
    descricao: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=agora)
