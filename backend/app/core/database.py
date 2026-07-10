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
# Correções de DADOS no início da aplicação.
#
# O SCHEMA é responsabilidade do Alembic (app/core/migracoes.py + alembic/).
# Aqui ficam apenas ajustes de DADOS idempotentes: o banco de produção não tem
# acesso administrativo direto, então estas correções rodam a cada boot (são
# baratas e seguras de repetir).
# --------------------------------------------------------------------------

# Conta do DONO do sistema: acesso global (todas as escolas). Idempotente —
# só escreve quando ainda não é global.
_EMAIL_ADMIN_GLOBAL = "edumedeiros1405@gmail.com"


def _promover_admin_global(motor=None) -> None:
    """Garante o acesso global do dono do sistema (idempotente)."""
    from sqlalchemy import inspect, text

    motor = motor or engine
    if "usuarios" not in inspect(motor).get_table_names():
        return
    with motor.begin() as conexao:
        conexao.execute(
            text("UPDATE usuarios SET is_global = :sim "
                 "WHERE lower(email) = :email AND is_global = :nao"),
            {"sim": True, "nao": False, "email": _EMAIL_ADMIN_GLOBAL})


def _backfill_codigo_niveis(motor=None) -> None:
    """Preenche o código estável das faixas antigas (deriva do nome)."""
    from sqlalchemy import inspect, text

    motor = motor or engine
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


def garantir_dados_base(motor=None) -> None:
    """Ajustes de dados idempotentes aplicados após as migrações de schema."""
    motor = motor or engine
    _backfill_codigo_niveis(motor)
    _promover_admin_global(motor)
