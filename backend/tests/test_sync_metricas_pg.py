"""Métricas de sincronização num PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').

Reusa os testes SQLite de valores, PII, custo e eventos e acrescenta o que só o
PostgreSQL mostra: o plano de cada consulta do scrape com ``enable_seqscan=off``
(sem 'Seq Scan' nas tabelas que crescem: existe caminho por índice) e a
transação do coletor em modo SÓ LEITURA, com teto de tempo por consulta."""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.sync import metricas
from tests import test_sync_metricas as base

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]


@pytest.fixture()
def db():
    engine = create_engine(URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    sessao = TestSession()

    def _get_db():
        outra = TestSession()
        try:
            yield outra
        finally:
            outra.close()

    app.dependency_overrides[get_db] = _get_db
    yield sessao
    sessao.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


from tests.test_sync_metricas import (  # noqa: E402,F401
    metricas_abertas,
    test_coletor_le_o_estado_do_banco_com_os_valores_certos as test_pg_valores,
    test_eventos_contam_cada_execucao_finalizada_uma_vez as test_pg_eventos,
    test_falha_no_meio_da_leitura_nao_deixa_serie_parcial as test_pg_falha_no_meio,
    test_metrics_nao_expoe_nome_mensagem_nem_segredo as test_pg_sem_pii,
    test_numero_de_consultas_por_scrape_nao_cresce_com_escolas_nem_historico
    as test_pg_custo,
    test_os_marcos_batem_com_as_regras_do_servico as test_pg_regras_do_servico,
    test_parcial_sem_aluno_aplicado_nao_renova_o_ultimo_dado_aplicado
    as test_pg_parcial_sem_aluno_dado_aplicado)


def test_pg_planos_sem_seq_scan_nas_tabelas_que_crescem(db):
    base._historico(db, 4, 12, 3, com_fila=True)
    cont = base._consultas_de_um_scrape(db)
    # 6 com a fila (eram 5): a marca de recálculo por escola tem consulta própria
    # desde a revisão e95 (ver test_sync_metricas.test_numero_de_consultas_…).
    assert len(cont.consultas) == 6
    with db.get_bind().connect() as conn:
        conn.exec_driver_sql("SET enable_seqscan = off")
        planos = []
        for sql, params in cont.consultas:
            plano = "\n".join(r[0] for r in conn.exec_driver_sql("EXPLAIN " + sql, params))
            planos.append(plano)
            for tabela in base.GRANDES:
                assert f"Seq Scan on {tabela}" not in plano, plano
        conn.rollback()
    usados = "\n".join(planos)
    for indice in ("ix_sync_exec_frescor", "ix_sincronizacao_alertas_resolvido",
                   "ix_sincronizacao_logs_execucao_id"):
        assert indice in usados, usados


def test_pg_sessao_do_coletor_e_so_leitura_com_teto_de_tempo(db):
    fabrica = sessionmaker(bind=db.get_bind())
    sessao = fabrica()
    try:
        metricas.preparar_sessao(sessao)
        assert sessao.execute(text("SHOW transaction_read_only")).scalar() == "on"
        assert sessao.execute(text(
            "select setting from pg_settings where name = 'statement_timeout'")
        ).scalar() == str(metricas.TETO_CONSULTA_MS)
        with pytest.raises(DBAPIError) as erro:
            sessao.execute(text("INSERT INTO escolas SELECT * FROM escolas WHERE false"))
        assert getattr(erro.value.orig, "sqlstate", None) == "25006"   # read_only_sql_transaction
    finally:
        sessao.rollback()
        sessao.close()
    # A configuração vale só para a transação do coletor (SET LOCAL / SET TRANSACTION).
    with db.get_bind().connect() as conn:
        assert conn.exec_driver_sql("SHOW transaction_read_only").scalar() == "off"


def test_pg_scrape_nao_grava_nada(db, escola_completa):
    base._cenario(db, escola_completa)
    contar = ("select (select count(*) from sincronizacao_execucoes), "
              "(select count(*) from sincronizacao_alertas), "
              "(select count(*) from sincronizacao_logs)")
    with db.get_bind().connect() as conn:
        antes = tuple(conn.exec_driver_sql(contar).one())
    coletor = metricas.ColetorSync(fabrica=sessionmaker(bind=db.get_bind()),
                                   relogio=lambda: base.T)
    a = base._amostras(coletor)
    assert base._v(a, "sync_coletor_sucesso") == 1
    assert base._v(a, "sync_execucoes_presas", plataforma="elefante", status="executando") == 1
    with db.get_bind().connect() as conn:   # o coletor não grava nada
        assert tuple(conn.exec_driver_sql(contar).one()) == antes
