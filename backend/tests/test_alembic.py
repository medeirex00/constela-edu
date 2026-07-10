"""Infraestrutura de migrações Alembic.

Independe do conftest (que monta o schema via create_all): aqui exercitamos o
caminho REAL de produção — ``aplicar_migracoes`` sobre bancos SQLite
temporários (arquivo, não memória, para sobreviver entre conexões).
"""
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

# Importar os pacotes de modelos registra TODAS as tabelas em Base.metadata.
import app.models        # noqa: F401
import app.quest.models  # noqa: F401
from app.core.database import Base
from app.core.migracoes import _REVISAO_BASE, _config, aplicar_migracoes


@pytest.fixture
def fazer_engine(tmp_path):
    """Cria engines SQLite em arquivo temporário e as descarta ao final —
    liberar o arquivo evita travas de exclusão no Windows."""
    criadas = []

    def _criar(nome: str = "db.sqlite"):
        engine = create_engine(f"sqlite:///{tmp_path / nome}")
        criadas.append(engine)
        return engine

    yield _criar
    for engine in criadas:
        engine.dispose()


def _head() -> str:
    """Última revisão do diretório de migrações (para onde o upgrade leva)."""
    return ScriptDirectory.from_config(_config()).get_current_head()


def _versao(engine):
    if "alembic_version" not in inspect(engine).get_table_names():
        return None
    with engine.connect() as c:
        return c.execute(text("SELECT version_num FROM alembic_version")).scalar()


def test_banco_novo_recebe_schema_completo(fazer_engine):
    """Banco vazio: o upgrade cria TODAS as tabelas dos modelos e versiona."""
    engine = fazer_engine("novo.db")
    aplicar_migracoes(engine)

    tabelas = set(inspect(engine).get_table_names())
    esperadas = set(Base.metadata.tables) | {"alembic_version"}
    assert esperadas <= tabelas
    assert _versao(engine) == _head()


def test_colunas_e_indices_criticos_presentes(fazer_engine):
    """As colunas/índices críticos existem — e a senha reversível NÃO existe."""
    engine = fazer_engine("schema.db")
    aplicar_migracoes(engine)
    insp = inspect(engine)

    cols_turmas = {c["name"] for c in insp.get_columns("turmas")}
    assert {"turno", "capacidade_maxima", "observacoes", "status"} <= cols_turmas

    cols_usuarios = {c["name"] for c in insp.get_columns("usuarios")}
    assert {"username", "token_version"} <= cols_usuarios
    # A cópia reversível da senha foi REMOVIDA (0002); o reset é por token.
    assert "senha_visivel" not in cols_usuarios
    assert "tokens_reset_senha" in insp.get_table_names()

    idx_leituras = {i["name"] for i in insp.get_indexes("leituras")}
    assert {"ix_leituras_aluno_data", "ix_leituras_escola_data"} <= idx_leituras

    idx_usuarios = {i["name"]: i for i in insp.get_indexes("usuarios")}
    assert idx_usuarios["ix_usuarios_username"]["unique"]


def test_idempotente(fazer_engine):
    """Rodar duas vezes não quebra nem altera a versão."""
    engine = fazer_engine("idem.db")
    aplicar_migracoes(engine)
    aplicar_migracoes(engine)  # segunda vez: nada a fazer
    assert _versao(engine) == _head()


def test_banco_pre_alembic_e_carimbado_sem_perder_dados(fazer_engine):
    """Instalação anterior ao Alembic: adotada sem perder dados; as migrações
    seguintes (ex.: remover senha_visivel) aplicam por cima."""
    engine = fazer_engine("antigo.db")

    # Monta o schema EXATAMENTE na revisão base (0001, ainda com senha_visivel)
    # e apaga a marca de versão — assim o banco parece anterior ao Alembic.
    cfg = _config()
    with engine.begin() as conexao:
        cfg.attributes["connection"] = conexao
        command.upgrade(cfg, _REVISAO_BASE)
    with engine.begin() as c:
        c.execute(text("DROP TABLE alembic_version"))
        c.execute(text(
            "INSERT INTO escolas (nome, ano_letivo_ativo, status, created_at) "
            "VALUES ('Escola Piloto', 2026, 'ativa', '2026-01-01 00:00:00')"))
    assert _versao(engine) is None  # ainda não versionado
    cols = {c["name"] for c in inspect(engine).get_columns("usuarios")}
    assert "senha_visivel" in cols  # o legado tinha a coluna

    aplicar_migracoes(engine)

    # Adotado e migrado até o head: dado preservado, senha_visivel removida.
    assert _versao(engine) == _head()
    cols_apos = {c["name"] for c in inspect(engine).get_columns("usuarios")}
    assert "senha_visivel" not in cols_apos
    with engine.connect() as c:
        assert c.execute(text("SELECT nome FROM escolas")).scalar_one() == "Escola Piloto"
