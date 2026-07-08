"""Sessão e engine do banco de dados.

SQLAlchemy 2.0 com ORM declarativo. O mesmo código funciona em SQLite
(desenvolvimento) e PostgreSQL (produção) — basta trocar DATABASE_URL.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

is_sqlite = settings.DATABASE_URL.startswith("sqlite")

if is_sqlite:
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    # Banco de rede (PostgreSQL em produção): pool dimensionado e verificação
    # de conexões mortas antes de reusar (pool_pre_ping) evitam erros
    # intermitentes após timeouts do banco. Total por worker uvicorn =
    # DB_POOL_SIZE + DB_MAX_OVERFLOW.
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE,
    )

if is_sqlite:
    # Garante integridade referencial no SQLite (desligada por padrão).
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------------------------------
# Migração leve: colunas adicionadas a tabelas que já existem no banco.
# `create_all` só cria tabelas NOVAS — bancos de instalações anteriores
# precisam do ALTER TABLE. Ao adotar Alembic, mover estas entradas para lá.
# --------------------------------------------------------------------------

_COLUNAS_NOVAS: dict[str, dict[str, str]] = {
    "turmas": {
        "turno": "VARCHAR(20)",
        "capacidade_maxima": "INTEGER",
        "observacoes": "VARCHAR(2000)",
        "status": "VARCHAR(20) DEFAULT 'ativa' NOT NULL",
    },
    "usuarios": {
        "token_version": "INTEGER DEFAULT 0 NOT NULL",
        # Nome de usuário do login (estilo @): único, minúsculo, opcional.
        "username": "VARCHAR(30)",
    },
    "niveis_dificuldade": {
        "codigo": "VARCHAR(40)",
    },
    "leituras": {
        "tempo_leitura_min": "INTEGER",
    },
}


def migrar_colunas_novas(motor=None) -> None:
    """Adiciona colunas que faltam (idempotente; SQLite e PostgreSQL)."""
    from sqlalchemy import inspect, text

    motor = motor or engine
    inspetor = inspect(motor)
    tabelas = set(inspetor.get_table_names())
    with motor.begin() as conexao:
        for tabela, colunas in _COLUNAS_NOVAS.items():
            if tabela not in tabelas:
                continue  # create_all vai criá-la já completa
            existentes = {c["name"] for c in inspetor.get_columns(tabela)}
            for coluna, ddl in colunas.items():
                if coluna not in existentes:
                    conexao.execute(
                        text(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {ddl}"))
        # Índices compostos para "último snapshot por aluno" — CREATE INDEX
        # IF NOT EXISTS é idempotente em SQLite e PostgreSQL. create_all cobre
        # bancos novos; isto cobre os já existentes.
        for indice, tabela, colunas_idx in _INDICES_NOVOS:
            if tabela in tabelas:
                conexao.execute(text(
                    f"CREATE INDEX IF NOT EXISTS {indice} ON {tabela} ({colunas_idx})"))
        # Unicidade do nome de usuário do login (NULLs não conflitam em
        # SQLite nem PostgreSQL). create_all cobre bancos novos.
        if "usuarios" in tabelas:
            conexao.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_usuarios_username "
                "ON usuarios (username)"))

    _backfill_codigo_niveis(motor)


def _backfill_codigo_niveis(motor) -> None:
    """Preenche o código estável das faixas antigas (deriva do nome)."""
    from sqlalchemy import inspect, text

    inspetor = inspect(motor)
    if "niveis_dificuldade" not in inspetor.get_table_names():
        return
    from app.models.configuracao import slug_nivel

    with motor.begin() as conexao:
        linhas = conexao.execute(text(
            "SELECT id, nome FROM niveis_dificuldade "
            "WHERE codigo IS NULL OR codigo = ''"
        )).all()
        for id_, nome in linhas:
            conexao.execute(
                text("UPDATE niveis_dificuldade SET codigo = :c WHERE id = :i"),
                {"c": slug_nivel(nome or "nivel"), "i": id_})


# Índices adicionados a bancos existentes (bancos novos os ganham via create_all).
_INDICES_NOVOS = [
    ("ix_snap_matific_escola_aluno_id", "snapshots_matific", "escola_id, aluno_id, id"),
    ("ix_snap_elefante_escola_aluno_id", "snapshots_elefante", "escola_id, aluno_id, id"),
    # Filtros por período no histórico/rankings de leitura.
    ("ix_leituras_aluno_data", "leituras", "aluno_id, data"),
    ("ix_leituras_escola_data", "leituras", "escola_id, data"),
]
