from datetime import date, datetime

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
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

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(100))          # ex.: "4º Ano B"
    ano_escolar: Mapped[str] = mapped_column(String(30))     # série, ex.: "4º Ano"
    ano_letivo: Mapped[int] = mapped_column(index=True)
    professor_id: Mapped[int | None] = mapped_column(ForeignKey("professores.id"))
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
    status: Mapped[str] = mapped_column(String(20), default="ativo")
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
    aluno_id: Mapped[int] = mapped_column(ForeignKey("alunos.id"), index=True)
    turma_id: Mapped[int] = mapped_column(ForeignKey("turmas.id"), index=True)
    ano_letivo: Mapped[int] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=agora)

    aluno: Mapped[Aluno] = relationship()
    turma: Mapped[Turma] = relationship()
