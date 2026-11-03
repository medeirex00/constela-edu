"""Achados da revisão e95 da forma C (``test_sync_em_dia_forma_c_revisao.py``) num
PostgreSQL REAL, local e descartável (TEST_DATABASE_URL_PG; o nome do banco precisa
conter 'test'). Mesmo padrão de ``test_sync_em_dia_forma_c_pg.py``."""
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


from tests.test_sync_em_dia_forma_c_revisao import (  # noqa: E402,F401
    test_periodo_so_com_pendente_nao_acusa_credencial_de_outra_escola as test_pg_periodo,
    test_queda_de_conta_de_ficha_transferida_nao_conta_como_conferida as test_pg_queda_inativa,
    test_so_linhas_sem_vinculo_nao_diz_zero_contas_na_fila as test_pg_fila_vazia,
    test_vinculados_todos_de_fichas_inativas_tem_texto_proprio as test_pg_inativas)
