from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import agora


class Importacao(Base):
    """Registro de auditoria de toda importação realizada (PRD §15)."""

    __tablename__ = "importacoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    plataforma: Mapped[str] = mapped_column(String(30))   # matific | elefante
    tipo: Mapped[str] = mapped_column(String(20))          # pdf | texto | seed
    arquivo_original: Mapped[str | None] = mapped_column(String(500))
    qtd_alunos: Mapped[int] = mapped_column(default=0)
    qtd_erros: Mapped[int] = mapped_column(default=0)
    tempo_ms: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="concluida")
    created_at: Mapped[datetime] = mapped_column(default=agora)


class SnapshotMatific(Base):
    """Fotografia imutável dos dados Matific de um aluno em uma importação.

    Nunca é sobrescrita (PRD §68) — a evolução é calculada comparando
    snapshots ao longo do tempo. O estado atual é o snapshot mais recente.
    """

    __tablename__ = "snapshots_matific"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("alunos.id"), index=True)
    importacao_id: Mapped[int] = mapped_column(ForeignKey("importacoes.id"), index=True)
    data_referencia: Mapped[datetime] = mapped_column(default=agora, index=True)
    atividades: Mapped[int] = mapped_column(default=0)
    estrelas: Mapped[int] = mapped_column(default=0)
    # Escala do relatório de origem (Matific atual: 0–5). A nota do aluno é
    # normalizada pelo maior valor da escola, então a escala não importa.
    pontuacao_media: Mapped[float] = mapped_column(default=0.0)


class SnapshotElefante(Base):
    """Fotografia imutável dos dados do Elefante Letrado (PRD §68)."""

    __tablename__ = "snapshots_elefante"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("alunos.id"), index=True)
    importacao_id: Mapped[int] = mapped_column(ForeignKey("importacoes.id"), index=True)
    data_referencia: Mapped[datetime] = mapped_column(default=agora, index=True)
    livros_unicos: Mapped[int] = mapped_column(default=0)
    tempo_leitura_min: Mapped[int] = mapped_column(default=0)
    questoes_tentativas: Mapped[int] = mapped_column(default=0)
    questoes_acertos: Mapped[int] = mapped_column(default=0)
    # Distribuição de livros únicos por código de nível, ex.: {"AA": 2, "D": 1}
    livros_por_nivel: Mapped[dict] = mapped_column(JSON, default=dict)


class Livro(Base):
    __tablename__ = "livros"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    titulo: Mapped[str] = mapped_column(String(300), index=True)
    autor: Mapped[str | None] = mapped_column(String(200))
    nivel_codigo: Mapped[str] = mapped_column(String(5), index=True)  # AA..Z
    categoria: Mapped[str | None] = mapped_column(String(100))
    paginas: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=agora)


class Leitura(Base):
    """Livro concluído por um aluno.

    A restrição de unicidade garante que releituras jamais pontuem
    novamente (PRD §35).
    """

    __tablename__ = "leituras"
    __table_args__ = (
        UniqueConstraint("aluno_id", "livro_id", name="uq_leitura_unica"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("alunos.id"), index=True)
    livro_id: Mapped[int] = mapped_column(ForeignKey("livros.id"), index=True)
    data: Mapped[datetime] = mapped_column(default=agora)

    livro: Mapped[Livro] = relationship()
