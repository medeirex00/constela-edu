from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.academico import Aluno
from app.models.base import agora


class Nota(Base):
    """Resultado calculado por aluno/ano letivo — cache do motor de cálculo.

    `detalhes` guarda o passo a passo completo do cálculo, permitindo a
    auditoria exigida no PRD §45 ("Como esta nota foi calculada").
    Recalculada integralmente a cada importação ou mudança de configuração
    (PRD §43); nunca editada manualmente.
    """

    __tablename__ = "notas"
    __table_args__ = (
        UniqueConstraint("aluno_id", "ano_letivo", name="uq_nota_aluno_ano"),
        # Caminho de leitura MAIS quente do sistema: ranking, top10 do
        # dashboard, painel público, média e exportação filtram sempre por
        # (escola_id, ano_letivo) e ordenam por posicao. O índice de coluna
        # única ix_notas_escola_id não distingue ano nem evita a ordenação;
        # este composto cobre o WHERE e o ORDER BY de uma vez.
        Index("ix_notas_escola_ano_posicao", "escola_id", "ano_letivo", "posicao"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(
        ForeignKey("alunos.id", ondelete="CASCADE"), index=True)
    ano_letivo: Mapped[int] = mapped_column(index=True)
    nota_matific: Mapped[float] = mapped_column(default=0.0)
    nota_elefante: Mapped[float] = mapped_column(default=0.0)
    nota_geral: Mapped[float] = mapped_column(default=0.0)
    posicao: Mapped[int | None] = mapped_column(default=None)
    detalhes: Mapped[dict] = mapped_column(JSON, default=dict)
    calculada_em: Mapped[datetime] = mapped_column(default=agora)

    aluno: Mapped[Aluno] = relationship()


class LogAuditoria(Base):
    """Trilha de auditoria permanente (PRD §17). Logs nunca são apagados."""

    __tablename__ = "logs_auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int | None] = mapped_column(ForeignKey("escolas.id"), index=True)
    usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"))
    acao: Mapped[str] = mapped_column(String(80), index=True)
    entidade: Mapped[str | None] = mapped_column(String(80))
    entidade_id: Mapped[int | None] = mapped_column(default=None)
    detalhes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=agora, index=True)
