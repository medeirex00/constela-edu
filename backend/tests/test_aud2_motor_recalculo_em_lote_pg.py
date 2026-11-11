"""Os casos de ``test_aud2_motor_recalculo_em_lote`` num PostgreSQL REAL — local e
descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). É no
PostgreSQL (psycopg) que o UPDATE em lote por chave primária vira um executemany em
pipeline, e é lá que a ida ao banco custa caro em produção. Sobrescreve a fixture ``db``
só neste módulo."""
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


from tests.test_aud2_motor_recalculo_em_lote import (  # noqa: E402,F401
    escola_grande,
    test_quem_saiu_perde_a_posicao_no_mesmo_lote as test_pg_quem_saiu_no_mesmo_lote,
    test_recalculo_grava_as_notas_existentes_num_update_so as test_pg_um_update_so,
    test_recalculo_sem_commit_deixa_a_sessao_com_as_notas_novas as test_pg_sem_commit,
    test_resultado_do_lote_e_o_mesmo_do_calculo_linha_a_linha as test_pg_mesmo_resultado,
)
