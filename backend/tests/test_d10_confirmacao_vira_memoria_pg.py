"""Memória da confirmação do D10 (``test_d10_confirmacao_vira_memoria.py``) num
PostgreSQL REAL, local e descartável (TEST_DATABASE_URL_PG; o nome do banco precisa
conter 'test'). Mesmo padrão de ``test_d10_ficha_sai_de_excluido_pg.py``."""
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


from tests.test_d10_confirmacao_vira_memoria import (  # noqa: E402,F401
    test_conta_aposentada_escolhida_como_efetiva_vale_na_coleta_daqui as test_pg_efetiva,
    test_ficha_que_sai_de_excluido_para_inativa_nao_ganha_memoria as test_pg_inativa,
    test_pendencia_aberta_antes_da_reativacao_fecha_na_coleta_seguinte as test_pg_pendencia,
    test_reativacao_da_ficha_pelo_admin_global_vale_para_a_coleta_desta_escola as
    test_pg_reativar)
