"""Aplicação das migrações Alembic dentro da própria aplicação.

Substitui o antigo `Base.metadata.create_all` + micro-migrações manuais. É
chamado pelo entrypoint do container (``scripts.migrate``, UMA vez antes dos
workers) e pelo startup de desenvolvimento (``app.main``). Idempotente e
seguro para bancos já existentes.

Estratégia de adoção (preserva 100% dos dados):

* Banco NOVO (sem tabelas) → ``upgrade head`` cria todo o schema.
* Banco JÁ versionado pelo Alembic → ``upgrade head`` aplica o que faltar.
* Banco EXISTENTE anterior ao Alembic (tem tabelas, mas sem
  ``alembic_version``) → ``stamp`` da revisão base (assume que o schema já é
  o da base — as micro-migrações antigas o mantinham em dia — SEM recriar
  nada) e, em seguida, ``upgrade head`` para migrações futuras.
"""
from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.core.config import BASE_DIR

# Revisão que representa o schema completo no momento em que o Alembic foi
# adotado. Bancos pré-Alembic são "carimbados" com ela.
_REVISAO_BASE = "0001"
# Tabela âncora do sistema: se existe mas não há `alembic_version`, o banco é
# de uma instalação anterior à adoção do Alembic.
_TABELA_ANCORA = "usuarios"


def _config() -> Config:
    """Config do Alembic com caminhos ABSOLUTOS (independe do diretório atual)."""
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    return cfg


def aplicar_migracoes(engine: Engine) -> None:
    """Leva o banco até a última revisão, preservando dados existentes."""
    tabelas = set(inspect(engine).get_table_names())
    pre_alembic = _TABELA_ANCORA in tabelas and "alembic_version" not in tabelas
    sqlite = engine.dialect.name == "sqlite"

    cfg = _config()
    # Conexão única compartilhada entre os comandos (padrão recomendado pelo
    # Alembic para uso programático): stamp e upgrade veem o MESMO banco.
    with engine.connect() as conexao:
        if sqlite:
            # PRAGMA foreign_keys só muda FORA de transação; desligamos ANTES
            # de qualquer BEGIN. Migrações que recriam tabelas em lote (SQLite
            # não altera constraint no lugar) fariam DROP TABLE de tabelas
            # referenciadas — com a checagem ligada, isso falharia.
            conexao.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            cfg.attributes["connection"] = conexao
            if pre_alembic:
                command.stamp(cfg, _REVISAO_BASE)
            command.upgrade(cfg, "head")
            conexao.commit()
        except Exception:
            # Nunca devolver ao pool uma conexão com a checagem desligada:
            # descarta a conexão física (o próximo checkout religa via evento).
            if sqlite:
                conexao.invalidate()
            raise
        else:
            if sqlite:
                conexao.exec_driver_sql("PRAGMA foreign_keys=ON")
