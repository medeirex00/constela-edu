"""Ambiente de execução das migrações Alembic do Constela Edu.

A URL do banco vem SEMPRE de ``app.core.config.settings`` (mesma fonte da
aplicação) — nunca fica escrita no alembic.ini. Assim, ``alembic upgrade head``
no container usa exatamente o ``DATABASE_URL`` de produção e, localmente, o
SQLite de desenvolvimento, sem duplicar configuração nem versionar segredos.

``target_metadata`` reúne TODOS os modelos (Constela Edu + Constela Quest) para
o autogenerate enxergar o schema inteiro.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

from app.core.config import settings
from app.core.database import Base

# Importar os pacotes de modelos REGISTRA todas as tabelas em Base.metadata.
# Sem isto o autogenerate acharia que o banco tem tabelas "a mais" e proporia
# apagá-las. Precisa acontecer antes de usar target_metadata.
import app.models        # noqa: E402,F401  Constela Edu (20 tabelas)
import app.quest.models  # noqa: E402,F401  Constela Quest (10 tabelas)

config = context.config

# Formatação das mensagens do próprio Alembic (definida no alembic.ini).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# A URL é SEMPRE a da aplicação — não a do .ini.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata


def _executar(connection: Connection) -> None:
    """Configura o contexto sobre uma conexão viva e roda as migrações."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Detecta mudança de TIPO de coluna e de DEFAULT do servidor no diff.
        compare_type=True,
        compare_server_default=True,
        # SQLite não suporta ALTER TABLE completo; o "batch mode" recria a
        # tabela de forma transparente. Inócuo no PostgreSQL, essencial no
        # SQLite (dev e testes).
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Modo offline: emite o SQL sem abrir conexão (``upgrade head --sql``)."""
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=settings.DATABASE_URL.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Modo online: aplica as migrações no banco.

    Se a aplicação injetar uma conexão (chamada programática de
    ``app.core.migracoes.aplicar_migracoes``), reutiliza-a — assim o *stamp* e
    o *upgrade* acontecem no MESMO banco, inclusive no SQLite em memória dos
    testes. No uso por linha de comando (``alembic upgrade head``,
    autogenerate) abre a própria engine a partir do ``DATABASE_URL``.
    """
    conexao_injetada = config.attributes.get("connection", None)
    if conexao_injetada is not None:
        _executar(conexao_injetada)
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _executar(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
