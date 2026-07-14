from datetime import date, datetime

from sqlalchemy import JSON, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import agora


class Professor(Base):
    __tablename__ = "professores"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(200), index=True)
    email: Mapped[str | None] = mapped_column(String(200))
    observacoes: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(default=agora)


class Turma(Base):
    __tablename__ = "turmas"
    # Uma turma É identificada por (escola, ano letivo, nome): duas com a mesma
    # tripla são a MESMA sala. O índice único barra a duplicação sob importações
    # concorrentes (defesa cross-DB, além do advisory lock por escola no
    # Postgres). O import trata a colisão re-resolvendo para a existente.
    __table_args__ = (
        Index("uq_turma_escola_ano_nome", "escola_id", "ano_letivo", "nome",
              unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(100))          # ex.: "4º Ano B"
    ano_escolar: Mapped[str] = mapped_column(String(30))     # série, ex.: "4º Ano"
    ano_letivo: Mapped[int] = mapped_column(index=True)
    professor_id: Mapped[int | None] = mapped_column(
        ForeignKey("professores.id", ondelete="SET NULL"))
    turno: Mapped[str | None] = mapped_column(String(20))    # manha|tarde|noite|integral
    capacidade_maxima: Mapped[int | None] = mapped_column(default=None)
    observacoes: Mapped[str | None] = mapped_column(String(2000))
    # "ativa" | "arquivada" — arquivar preserva o histórico sem poluir os filtros
    status: Mapped[str] = mapped_column(String(20), default="ativa", index=True)
    created_at: Mapped[datetime] = mapped_column(default=agora)

    professor: Mapped[Professor | None] = relationship()


class Aluno(Base):
    __tablename__ = "alunos"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(200), index=True)
    foto_url: Mapped[str | None] = mapped_column(String(500))
    data_nascimento: Mapped[date | None] = mapped_column(default=None)
    numero_chamada: Mapped[int | None] = mapped_column(default=None)
    # ativo | arquivado | excluido | fora_lista_piloto. Todas as consultas de
    # visão (rankings/relatórios/dashboards) filtram por "ativo", então qualquer
    # outro valor esconde o aluno SEM apagá-lo (reversível).
    status: Mapped[str] = mapped_column(String(20), default="ativo")
    # True quando o aluno veio (ou foi casado) por uma importação da Lista
    # Piloto. Só estes entram na reconciliação incremental: quem some de uma
    # nova lista vira "fora_lista_piloto"; alunos criados à mão ou por upload
    # (Matific/Elefante) NUNCA são afetados.
    da_lista_piloto: Mapped[bool] = mapped_column(default=False)
    observacoes: Mapped[str | None] = mapped_column(String(1000))
    # Ficha cadastral livre (JSON): dados da planilha de matrículas da escola
    # que não têm coluna própria — RA, RM, responsável, endereço, telefone,
    # RG, CPF, SUS, sexo, raça/cor, bolsa família, etc.
    ficha: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=agora)


class Matricula(Base):
    """Vínculo aluno ↔ turma por ano letivo.

    Preserva o histórico quando o aluno muda de série (PRD §14):
    nada é sobrescrito, cada ano letivo gera um novo registro.
    """

    __tablename__ = "matriculas"
    __table_args__ = (
        UniqueConstraint("aluno_id", "ano_letivo", name="uq_matricula_aluno_ano"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(
        ForeignKey("alunos.id", ondelete="CASCADE"), index=True)
    turma_id: Mapped[int] = mapped_column(ForeignKey("turmas.id"), index=True)
    ano_letivo: Mapped[int] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=agora)

    aluno: Mapped[Aluno] = relationship()
    turma: Mapped[Turma] = relationship()


class IdentidadeExterna(Base):
    """Vínculo estável aluno ↔ id do aluno numa plataforma externa (UUID do
    Matific, id do Elefante). É a identificação CONFIÁVEL entre sincronizações:
    permite recasar o aluno mesmo se o nome mudar e, principalmente, detectar
    MUDANÇA DE TURMA com segurança (o UUID não muda quando o aluno troca de sala).
    Genérico por ``plataforma`` para o Elefante reusar a mesma arquitetura."""

    __tablename__ = "identidades_externas"
    __table_args__ = (
        # Um id externo aponta para UM aluno por escola/plataforma.
        UniqueConstraint("escola_id", "plataforma", "id_externo",
                         name="uq_identidade_externa"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(
        ForeignKey("alunos.id", ondelete="CASCADE"), index=True)
    plataforma: Mapped[str] = mapped_column(String(30))      # matific | elefante
    id_externo: Mapped[str] = mapped_column(String(80))       # UUID/id do aluno lá
    created_at: Mapped[datetime] = mapped_column(default=agora)
