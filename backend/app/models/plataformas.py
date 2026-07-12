from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import agora


class Importacao(Base):
    """Registro de auditoria de toda importação realizada (PRD §15)."""

    __tablename__ = "importacoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"))
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
    __table_args__ = (
        Index("ix_snap_matific_escola_aluno_id", "escola_id", "aluno_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("alunos.id", ondelete="CASCADE"), index=True)
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
    __table_args__ = (
        Index("ix_snap_elefante_escola_aluno_id", "escola_id", "aluno_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("alunos.id", ondelete="CASCADE"), index=True)
    importacao_id: Mapped[int] = mapped_column(ForeignKey("importacoes.id"), index=True)
    data_referencia: Mapped[datetime] = mapped_column(default=agora, index=True)
    livros_unicos: Mapped[int] = mapped_column(default=0)
    tempo_leitura_min: Mapped[int] = mapped_column(default=0)
    questoes_tentativas: Mapped[int] = mapped_column(default=0)
    questoes_acertos: Mapped[int] = mapped_column(default=0)
    # Distribuição de livros únicos por código de nível, ex.: {"AA": 2, "D": 1}
    livros_por_nivel: Mapped[dict] = mapped_column(JSON, default=dict)


class EventoAluno(Base):
    """Evento GRANULAR de um aluno numa plataforma (uma leitura, uma atividade)
    — o 'espelho' evento a evento e a base da LINHA DO TEMPO cronológica.

    ADITIVO: os snapshots agregados (SnapshotElefante/SnapshotMatific) seguem
    sendo a base de scoring/evolução/ranking — nada muda lá. Esta é a camada de
    histórico fino. Genérica de propósito (serve às DUAS plataformas): campos
    comuns + ``dados`` JSON para o que é específico (ex.: gênero textual). NÃO
    guarda voz/áudio de criança (dado sensível fica fora por decisão de projeto).

    IDEMPOTÊNCIA: ``UniqueConstraint(aluno_id, plataforma, chave_natural)``. Como
    Matific/Elefante não expõem id de evento estável, a chave é sintética e
    DETERMINÍSTICA (hash do que identifica o evento: plataforma, tipo, título,
    data/hora). Reimportar o mesmo relatório é no-op — nunca duplica, nunca perde
    histórico. Backfill fora de ordem entra na sua data real (append-only).
    """

    __tablename__ = "eventos_aluno"
    __table_args__ = (
        UniqueConstraint("aluno_id", "plataforma", "chave_natural",
                         name="uq_evento_natural"),
        # Feed cronológico e filtro por período (linha do tempo por aluno).
        Index("ix_eventos_aluno_ocorrido", "escola_id", "aluno_id", "ocorrido_em"),
        Index("ix_eventos_tipo", "escola_id", "aluno_id", "tipo_evento"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(
        ForeignKey("alunos.id", ondelete="CASCADE"), index=True)
    importacao_id: Mapped[int | None] = mapped_column(
        ForeignKey("importacoes.id"), index=True, default=None)
    plataforma: Mapped[str] = mapped_column(String(30))    # matific | elefante
    tipo_evento: Mapped[str] = mapped_column(String(40))   # leitura | atividade | ...
    # Data + HORA reais do evento — eixo da linha do tempo cronológica.
    ocorrido_em: Mapped[datetime] = mapped_column(index=True)
    # Chave de dedup determinística (hash). Ver docstring.
    chave_natural: Mapped[str] = mapped_column(String(64), index=True)
    conteudo_titulo: Mapped[str | None] = mapped_column(String(300), default=None)
    habilidade: Mapped[str | None] = mapped_column(String(200), default=None)
    nivel_codigo: Mapped[str | None] = mapped_column(String(10), default=None)
    acertos: Mapped[int | None] = mapped_column(default=None)
    erros: Mapped[int | None] = mapped_column(default=None)
    tentativas: Mapped[int | None] = mapped_column(default=None)
    pontuacao: Mapped[float | None] = mapped_column(default=None)
    tempo_segundos: Mapped[int | None] = mapped_column(default=None)
    livro_id: Mapped[int | None] = mapped_column(
        ForeignKey("livros.id"), index=True, default=None)
    # Payload bruto específico da plataforma sem coluna própria (ex.: gênero).
    dados: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=agora)


class SyncMarcador(Base):
    """Marca-d'água do incremental por (escola, plataforma, tipo_evento): até
    onde já capturamos eventos. Na 1ª sync (``historico_completo`` False) busca-se
    o histórico TOTAL; nas seguintes, só a partir de ``ultimo_evento_em`` (com
    uma janela de segurança), e a UNIQUE de EventoAluno descarta o que repetir.
    """

    __tablename__ = "sync_marcadores"
    __table_args__ = (
        UniqueConstraint("escola_id", "plataforma", "tipo_evento",
                         name="uq_sync_marcador"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    plataforma: Mapped[str] = mapped_column(String(30))
    tipo_evento: Mapped[str] = mapped_column(String(40))
    primeira_sync_em: Mapped[datetime | None] = mapped_column(default=None)
    historico_completo: Mapped[bool] = mapped_column(default=False)
    # Maior ocorrido_em já ingerido (cursor do incremental).
    ultimo_evento_em: Mapped[datetime | None] = mapped_column(default=None)
    ultima_chave_natural: Mapped[str | None] = mapped_column(String(64), default=None)
    updated_at: Mapped[datetime] = mapped_column(default=agora, onupdate=agora)


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
        # Filtros por período no histórico/rankings de leitura (aluno e escola).
        Index("ix_leituras_aluno_data", "aluno_id", "data"),
        Index("ix_leituras_escola_data", "escola_id", "data"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("alunos.id", ondelete="CASCADE"), index=True)
    livro_id: Mapped[int] = mapped_column(ForeignKey("livros.id"), index=True)
    # Data + HORÁRIO reais da conclusão (relatório individual do Elefante traz
    # ambos). Índice para os filtros por período (rankings/histórico/evolução).
    data: Mapped[datetime] = mapped_column(default=agora, index=True)
    # Tempo gasto naquela leitura, em minutos (quando o relatório informa).
    tempo_leitura_min: Mapped[int | None] = mapped_column(default=None)

    livro: Mapped[Livro] = relationship()
