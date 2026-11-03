"""Achados da revisão e95 da escola externa (``test_sync_escola_cruzada_revisao.py``)
num PostgreSQL REAL, local e descartável (TEST_DATABASE_URL_PG; o nome do banco
precisa conter 'test'). Mesmo padrão de ``test_sync_escola_cruzada_pg.py``."""
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


from tests.test_sync_escola_cruzada_revisao import (  # noqa: E402,F401
    test_a1_controle_primeira_coleta_da_propria_escola_aprende_o_vinculo as test_pg_a1_controle,
    test_a1_coleta_mista_aprende_e_desfaz_o_vinculo as test_pg_a1_misto,
    test_a1_elefante_conta_de_outra_escola_na_1a_coleta_nao_fixa_o_vinculo as test_pg_a1,
    test_a1m_matific_conta_de_outra_escola_na_1a_coleta_nao_fixa_o_vinculo as test_pg_a1m,
    test_j_controle_corpo_com_a_escola_pedida_aplica as test_pg_j_controle,
    test_j_matific_corpo_do_placar_de_outra_escola_nao_e_aplicado as test_pg_j,
    test_k_servico_recusa_escola_detectada_diferente_do_vinculo as test_pg_k)
