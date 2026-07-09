"""Catálogo pedagógico global: planetas → jornadas → missões → desafios
(docs/quest/02, grupo 2). Mantido pelo admin global; escolas ativam por
configuração (namespace quest.*)."""
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import agora


class QuestMundo(Base):
    """Disciplina — a criança vê como Planeta ("Planeta Matemática")."""

    __tablename__ = "quest_mundos"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(80))
    descricao: Mapped[str | None] = mapped_column(String(500))
    ordem: Mapped[int] = mapped_column(default=0)
    # Identidade visual/sonora: {c1, c2, sky, dark, musica, cenario, floats…}
    # — mesmo formato do protótipo constela-play-v7 (SUBJECTS/SCENES)
    tema: Mapped[dict] = mapped_column(JSON, default=dict)
    icone: Mapped[str] = mapped_column(String(16), default="🪐")
    ativo: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=agora)


class QuestJornada(Base):
    """Trilha dentro do planeta, amarrada a um ano escolar e à BNCC."""

    __tablename__ = "quest_jornadas"

    id: Mapped[int] = mapped_column(primary_key=True)
    mundo_id: Mapped[int] = mapped_column(ForeignKey("quest_mundos.id"), index=True)
    nome: Mapped[str] = mapped_column(String(120))
    descricao: Mapped[str | None] = mapped_column(String(500))
    # Mesma convenção de turmas.ano_escolar: "1º Ano" … "5º Ano"
    ano_escolar: Mapped[str] = mapped_column(String(30), index=True)
    ordem: Mapped[int] = mapped_column(default=0)
    # Códigos de habilidade BNCC cobertos (ex.: ["EF02MA05", "EF02MA06"])
    bncc: Mapped[list] = mapped_column(JSON, default=list)
    # Estrelas necessárias para liberar a missão-chefão da jornada
    estrelas_chefao: Mapped[int] = mapped_column(default=0)
    ativo: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=agora)

    mundo = relationship(QuestMundo)


class QuestMissao(Base):
    __tablename__ = "quest_missoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    jornada_id: Mapped[int] = mapped_column(ForeignKey("quest_jornadas.id"), index=True)
    ordem: Mapped[int] = mapped_column(default=0)
    nome: Mapped[str] = mapped_column(String(120))
    tipo: Mapped[str] = mapped_column(String(20), default="normal")  # normal|chefao|evento
    icone: Mapped[str | None] = mapped_column(String(16))
    descricao_crianca: Mapped[str | None] = mapped_column(String(300))
    xp_base: Mapped[int] = mapped_column(default=40)
    moedas_base: Mapped[int] = mapped_column(default=10)
    # {tempo_sugerido_min, desafios_por_tentativa, modos: ["solo","coop"…]}
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    # Editar missão publicada cria nova versão; tentativas guardam a jogada
    versao: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(20), default="rascunho",
                                        index=True)  # rascunho|publicada|arquivada
    created_at: Mapped[datetime] = mapped_column(default=agora)

    jornada = relationship(QuestJornada)


class QuestDesafio(Base):
    __tablename__ = "quest_desafios"

    id: Mapped[int] = mapped_column(primary_key=True)
    missao_id: Mapped[int] = mapped_column(ForeignKey("quest_missoes.id"), index=True)
    ordem: Mapped[int] = mapped_column(default=0)
    # Registry de mecânicas do frontend: quiz|arrastar|ligar|memoria|…
    mecanica: Mapped[str] = mapped_column(String(30))
    dificuldade: Mapped[int] = mapped_column(default=2)  # 1–5
    bncc_codigo: Mapped[str | None] = mapped_column(String(12), index=True)
    # Enunciado, áudio da instrução, mídia, opções — schema por mecânica
    corpo: Mapped[dict] = mapped_column(JSON, default=dict)
    # NUNCA entregue ao cliente: a correção é exclusiva do servidor
    gabarito: Mapped[dict] = mapped_column(JSON, default=dict)
    dica: Mapped[dict] = mapped_column(JSON, default=dict)
    explicacao: Mapped[dict] = mapped_column(JSON, default=dict)

    missao = relationship(QuestMissao)
