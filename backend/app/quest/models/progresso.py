"""Progresso e telemetria (docs/quest/02, grupo 3).

`quest_tentativas` segue a filosofia dos snapshots do Edu: imutável, nunca
sobrescrita — é a fonte do painel do professor, do portal da família e dos
agregados de habilidade (que são caches recalculáveis).
"""
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import agora


class QuestProgresso(Base):
    """Melhor resultado por aluno × missão (estrelas nunca são perdidas)."""

    __tablename__ = "quest_progresso"
    __table_args__ = (
        UniqueConstraint("perfil_id", "missao_id", name="uq_progresso_perfil_missao"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    perfil_id: Mapped[int] = mapped_column(ForeignKey("quest_perfis.id"), index=True)
    missao_id: Mapped[int] = mapped_column(ForeignKey("quest_missoes.id"), index=True)
    estrelas: Mapped[int] = mapped_column(default=0)      # 0–3, vale a melhor
    melhor_pct: Mapped[float] = mapped_column(default=0.0)
    tentativas: Mapped[int] = mapped_column(default=0)
    primeira_conclusao_em: Mapped[datetime | None] = mapped_column(default=None)
    ultima_tentativa_em: Mapped[datetime | None] = mapped_column(default=None)


class QuestTentativa(Base):
    """Registro imutável de cada jogada — nunca editado, nunca apagado."""

    __tablename__ = "quest_tentativas"
    __table_args__ = (
        Index("ix_quest_tent_perfil_fim", "perfil_id", "finalizada_em"),
        Index("ix_quest_tent_escola_fim", "escola_id", "finalizada_em"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    perfil_id: Mapped[int] = mapped_column(ForeignKey("quest_perfis.id"), index=True)
    missao_id: Mapped[int] = mapped_column(ForeignKey("quest_missoes.id"), index=True)
    missao_versao: Mapped[int] = mapped_column(default=1)
    modo: Mapped[str] = mapped_column(String(20), default="solo")  # solo|coop|corrida|x1
    # Partidas sociais (fase Q4). Sem FK: a tabela quest_salas ainda não existe
    sala_id: Mapped[int | None] = mapped_column(default=None)
    iniciada_em: Mapped[datetime] = mapped_column(default=agora)
    finalizada_em: Mapped[datetime | None] = mapped_column(default=None)
    total_desafios: Mapped[int] = mapped_column(default=0)
    acertos: Mapped[int] = mapped_column(default=0)
    tempo_seg: Mapped[int] = mapped_column(default=0)
    xp_ganho: Mapped[int] = mapped_column(default=0)
    moedas_ganhas: Mapped[int] = mapped_column(default=0)
    estrelas: Mapped[int] = mapped_column(default=0)
    # Por desafio: {desafio_id, correta, resposta, tempo_ms, dicas, tentativas}
    respostas: Mapped[list] = mapped_column(JSON, default=list)
    origem: Mapped[str] = mapped_column(String(12), default="web")  # web|pwa-offline


class QuestHabilidade(Base):
    """Agregado por habilidade BNCC — cache recalculável de quest_tentativas."""

    __tablename__ = "quest_habilidades"
    __table_args__ = (
        UniqueConstraint("perfil_id", "bncc_codigo", name="uq_habilidade_perfil_bncc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    perfil_id: Mapped[int] = mapped_column(ForeignKey("quest_perfis.id"), index=True)
    bncc_codigo: Mapped[str] = mapped_column(String(12), index=True)
    tentativas: Mapped[int] = mapped_column(default=0)
    acertos: Mapped[int] = mapped_column(default=0)
    dominio: Mapped[float] = mapped_column(default=0.0)   # 0–100, média móvel
    ultima_atividade_em: Mapped[datetime | None] = mapped_column(default=None)
