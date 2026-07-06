"""Sessão e engine do banco de dados.

SQLAlchemy 2.0 com ORM declarativo. O mesmo código funciona em SQLite
(desenvolvimento) e PostgreSQL (produção) — basta trocar DATABASE_URL.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if is_sqlite else {},
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
