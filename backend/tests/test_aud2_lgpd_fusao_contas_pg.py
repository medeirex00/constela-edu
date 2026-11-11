"""ALUNOS-4 (fusão × contas diferentes da mesma plataforma) num PostgreSQL REAL —
local e descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').

Reusa os testes SQLite de ``test_aud2_lgpd_fusao_contas``: no PostgreSQL a recusa
acontece com a trava da escola tomada (``bloquear_escola_para_importacao``) e o
rollback da fusão manual e o savepoint do lote têm de deixar tudo no lugar.

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud2_lgpd_fusao_contas_pg.py -m postgres

Dados fictícios.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]


@pytest.fixture()
def db():
    from app.quest import models as _quest  # noqa: F401
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


from tests.test_aud2_lgpd_fusao_contas import (  # noqa: E402,F401
    test_contas_de_plataformas_diferentes_continuam_fundindo as test_pg_plataformas_diferentes,
    test_duas_contas_no_elefante_tambem_recusa as test_pg_elefante,
    test_fusao_em_lote_recusa_o_par_e_segue as test_pg_lote,
    test_fusao_manual_de_fichas_com_contas_diferentes_no_matific_e_recusada as test_pg_manual,
    test_premiacao_do_periodo_nao_vira_diferenca_entre_contas as test_pg_premiacao)
