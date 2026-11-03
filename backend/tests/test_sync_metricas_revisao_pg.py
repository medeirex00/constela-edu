"""Métricas de sincronização num PostgreSQL REAL, local e descartável
(TEST_DATABASE_URL_PG; o nome do banco precisa conter 'test'): achado 1 da revisão
e95 — o teto por consulta passa a ser um ORÇAMENTO do prazo total do scrape.

Falha no 2a14731 (cada consulta esperava até quase 3 s por lock sem estourar o
teto: o scrape passava de 10 s e ainda saía com ``sync_coletor_sucesso 1``) e
passa depois. Reusa os achados 3 (marca de recálculo) e o controle do teto."""
from __future__ import annotations

import os
import threading
import time

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.sync import metricas
from tests import test_sync_metricas as base
from tests.test_sync_metricas_pg import db  # noqa: F401  (fixture PG)
from tests.test_sync_metricas_revisao import (  # noqa: F401
    test_recalculo_pendente_de_outra_plataforma_da_escola_conta as test_pg_recalculo_outra_plat)

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]

TABELAS = ("plataforma_credenciais", "sincronizacao_execucoes", "sincronizacao_logs",
           "sincronizacao_alertas")


def test_pg_varias_tabelas_travadas_o_scrape_respeita_o_prazo_total(
        db, escola_completa):  # noqa: F811
    base._cenario(db, escola_completa)          # tem execução na fila: todas as consultas
    eng = db.get_bind()
    travas = []
    for tabela in TABELAS:
        c = eng.connect()
        c.exec_driver_sql(f"LOCK TABLE {tabela} IN ACCESS EXCLUSIVE MODE")
        travas.append(c)

    def _soltar():                              # cada lock dura 2,7 s, um depois do outro
        for c in travas:
            time.sleep(2.7)
            c.rollback()

    soltador = threading.Thread(target=_soltar)
    coletor = metricas.ColetorSync(fabrica=sessionmaker(bind=eng), relogio=lambda: base.T)
    soltador.start()
    t0 = time.perf_counter()
    try:
        a = base._amostras(coletor)
        dt = time.perf_counter() - t0
    finally:
        soltador.join()
        leitura = getattr(coletor, "_em_curso", None)
        if leitura is not None:
            leitura.join(15)
        for c in travas:
            c.close()
    assert base._v(a, "sync_coletor_sucesso") == 0
    assert dt < metricas.PRAZO_COLETOR_S + 1.5, dt      # antes: mais de 10 s, sucesso 1


def test_pg_uma_consulta_travada_continua_caindo_no_teto_por_consulta(
        db, escola_completa):  # noqa: F811
    """Controle: com o orçamento cheio, o teto de uma consulta continua o
    ``TETO_CONSULTA_MS`` (3 s), não o prazo total."""
    base._cenario(db, escola_completa)
    eng = db.get_bind()
    trava = eng.connect()
    trava.exec_driver_sql("LOCK TABLE sincronizacao_alertas IN ACCESS EXCLUSIVE MODE")
    try:
        coletor = metricas.ColetorSync(fabrica=sessionmaker(bind=eng), relogio=lambda: base.T)
        t0 = time.perf_counter()
        a = base._amostras(coletor)
        dt = time.perf_counter() - t0
    finally:
        trava.rollback()
        trava.close()
    assert base._v(a, "sync_coletor_sucesso") == 0
    prazo = getattr(metricas, "PRAZO_COLETOR_S", 5.0)
    assert metricas.TETO_CONSULTA_MS / 1000 - 0.3 <= dt < prazo, dt
