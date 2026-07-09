"""Identidade do aluno no Quest: perfil (o astronauta), credencial de login
infantil e vínculo de responsáveis (docs/quest/02, grupo 1)."""
from datetime import date, datetime

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import agora


class QuestPerfil(Base):
    """O astronauta — estado de jogo do aluno.

    `nivel`, `moedas` e `estrelas_total` são caches recalculáveis (a verdade
    vive no ledger e nas tentativas), mantidos por serem lidos em toda tela.
    """

    __tablename__ = "quest_perfis"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("alunos.id"), unique=True)
    # Nome de exibição fora da própria turma (LGPD: nome real só entre colegas)
    apelido: Mapped[str] = mapped_column(String(60))
    codigo_amigo: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    nivel: Mapped[int] = mapped_column(default=1)
    xp_total: Mapped[int] = mapped_column(default=0)
    moedas: Mapped[int] = mapped_column(default=0)
    estrelas_total: Mapped[int] = mapped_column(default=0)
    # "Chama do Cosmo": dias seguidos com atividade; o escudo perdoa 1 falta
    # por semana (renovado às segundas) — criança não controla a própria agenda
    sequencia_dias: Mapped[int] = mapped_column(default=0)
    escudo_sequencia: Mapped[bool] = mapped_column(default=True)
    ultimo_dia_ativo: Mapped[date | None] = mapped_column(default=None)
    # Itens equipados: {cor, roupa, chapeu, acessorio, pet, efeito, moldura}
    avatar: Mapped[dict] = mapped_column(JSON, default=dict)
    # {som, musica, narracao, reduzir_animacoes, ...}
    preferencias: Mapped[dict] = mapped_column(JSON, default=dict)
    # Nível adaptativo por mundo (1–5), invisível para a criança
    dificuldade: Mapped[dict] = mapped_column(JSON, default=dict)
    # Recursos sociais: desligado por padrão; escola/responsável habilita
    social_ativo: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="ativo")
    created_at: Mapped[datetime] = mapped_column(default=agora)


class QuestCredencialAluno(Base):
    """Login infantil — separado do estado de jogo.

    O cartão de acesso impresso carrega o QR, o código falável e as 4 figuras
    do PIN. As figuras ficam em claro (como o token do Painel Público e a
    senha visível do Edu — decisão do produto): elas JÁ estão impressas no
    cartão e precisam ser reimprimíveis pelo professor; a comparação usa
    tempo constante. A segurança real contra força bruta é o limitador de
    tentativas + o QR token de alta entropia.
    """

    __tablename__ = "quest_credenciais_aluno"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("alunos.id"), unique=True)
    # Curto e falável ("SOL-1234") — único na rede toda
    codigo_login: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    # 4 figuras em ordem (slugs do catálogo FIGURAS_PIN)
    pin_figuras: Mapped[list] = mapped_column(JSON, default=list)
    # Login por QR nos tablets; trocável (regenerar cartão mata o antigo)
    qr_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Incrementado ao regenerar o cartão: derruba sessões antigas (como no Edu)
    token_version: Mapped[int] = mapped_column(default=0)
    ultimo_acesso: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=agora)

    aluno = relationship("Aluno")


class ResponsavelAluno(Base):
    """Vínculo responsável (usuarios, cargo=responsavel) ↔ aluno.

    O vínculo só nasce autorizado por alguém da escola — responsável nunca
    se auto-vincula a uma criança.
    """

    __tablename__ = "responsaveis_alunos"
    __table_args__ = (
        UniqueConstraint("usuario_id", "aluno_id", name="uq_responsavel_aluno"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("alunos.id"), index=True)
    parentesco: Mapped[str | None] = mapped_column(String(40))
    autorizado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    created_at: Mapped[datetime] = mapped_column(default=agora)
