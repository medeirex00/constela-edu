"""A 0039 acrescenta à execução de sincronização a contabilidade que decide o status
(qtd_linhas, qtd_em_revisao, qtd_falhas, recalculo_pendente, motivo). ADITIVA:
contagens anuláveis (execução antiga = "não medido"), recalculo_pendente nasce
false; o downgrade só remove as colunas, sem tocar nas linhas. Sobe e desce em
SQLite e — com ``TEST_DATABASE_URL_PG`` (nome com 'test') — em PostgreSQL real."""
import importlib.util
import os
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.migracoes import _config

VERSAO = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0039_execucao_contabilidade.py"
NOVAS = {"qtd_linhas", "qtd_em_revisao", "qtd_falhas", "recalculo_pendente", "motivo"}


def _modulo():
    spec = importlib.util.spec_from_file_location("m0039", VERSAO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _migrar(engine, alvo, *, descer=False):
    cfg = _config()
    with engine.begin() as conexao:
        if engine.dialect.name == "sqlite":
            conexao.exec_driver_sql("PRAGMA foreign_keys=OFF")
        cfg.attributes["connection"] = conexao
        (command.downgrade if descer else command.upgrade)(cfg, alvo)


def _colunas(engine):
    return {c["name"]: c for c in inspect(engine).get_columns("sincronizacao_execucoes")}


def _sobe_com_linha_antiga_e_desce(engine):
    _migrar(engine, "0038_revogar_papeis_da_api")
    with engine.begin() as c:
        c.execute(text("INSERT INTO escolas (nome, ano_letivo_ativo, status, created_at) "
                       "VALUES ('ESCOLA FICTICIA', 2026, 'ativa', CURRENT_TIMESTAMP)"))
        eid = c.execute(text("SELECT id FROM escolas")).scalar()
        c.execute(text(
            "INSERT INTO sincronizacao_execucoes (escola_id, plataforma, origem, status, "
            "duracao_ms, qtd_alunos, qtd_turmas, qtd_alteracoes, qtd_arquivos, qtd_erros, "
            "tentativa, parametros, created_at) VALUES (:e, 'matific', 'manual', 'concluida', "
            "0, 7, 1, 7, 1, 0, 1, '{}', CURRENT_TIMESTAMP)"), {"e": eid})
    assert not (NOVAS & set(_colunas(engine)))

    _migrar(engine, "0039_execucao_contabilidade")
    cols = _colunas(engine)
    assert NOVAS <= set(cols)
    assert all(cols[n]["nullable"] for n in ("qtd_linhas", "qtd_em_revisao", "qtd_falhas", "motivo"))
    assert cols["recalculo_pendente"]["nullable"] is False
    with engine.connect() as c:
        linha = c.execute(text(
            "SELECT qtd_alunos, qtd_linhas, qtd_em_revisao, qtd_falhas, recalculo_pendente, "
            "motivo FROM sincronizacao_execucoes")).one()
    # A linha antiga fica como estava: contagens "não medidas" e sem pendência.
    assert linha[0] == 7 and linha[1:4] == (None, None, None)
    assert bool(linha[4]) is False and linha[5] is None
    with engine.begin() as c:
        c.execute(text("UPDATE sincronizacao_execucoes SET qtd_linhas = 3, motivo = 'nada_mudou', "
                       "recalculo_pendente = :v"), {"v": True})

    _migrar(engine, "0038_revogar_papeis_da_api", descer=True)
    assert not (NOVAS & set(_colunas(engine)))
    with engine.connect() as c:
        assert c.execute(text("SELECT qtd_alunos, status FROM sincronizacao_execucoes")).one() \
            == (7, "concluida")                         # nenhuma linha perdida na descida
    _migrar(engine, "0039_execucao_contabilidade")      # e sobe de novo
    assert NOVAS <= set(_colunas(engine))


def test_0039_vem_depois_da_0038_e_e_aditiva():
    m = _modulo()
    assert m.down_revision == "0038_revogar_papeis_da_api"
    assert set(m.COLUNAS) == NOVAS
    fonte = VERSAO.read_text(encoding="utf-8")
    assert "UPDATE" not in fonte.split("def upgrade", 1)[1]     # sem backfill: só colunas
    assert "DELETE" not in fonte


def test_0039_sobe_e_desce_no_sqlite(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm0039.db'}")
    try:
        _sobe_com_linha_antiga_e_desce(engine)
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_0039_sobe_e_desce_no_postgres():
    url = os.environ.get("TEST_DATABASE_URL_PG")
    if not url:
        pytest.skip("defina TEST_DATABASE_URL_PG para rodar contra PostgreSQL real")
    if "test" not in (make_url(url).database or "").lower():
        pytest.skip("o nome do banco PG de teste precisa conter 'test'")
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    try:
        _sobe_com_linha_antiga_e_desce(engine)
    finally:
        with engine.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE"))
            c.execute(text("CREATE SCHEMA public"))
        engine.dispose()
