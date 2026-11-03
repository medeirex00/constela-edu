"""Travas da sync na restauração (``test_backup_preserva_travas_da_sync.py``) num
PostgreSQL REAL, local e descartável (TEST_DATABASE_URL_PG; o nome do banco precisa
conter 'test'). Mesmo padrão de ``test_backup_sem_segredos_pg.py``."""
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


from tests.test_backup_preserva_travas_da_sync import (  # noqa: E402,F401
    test_restauracao_mantem_bloquear_e_vinculo_explicito as test_pg_bloquear,
    test_restauracao_nao_planta_vinculo_que_a_api_recusa_com_409 as test_pg_409,
    test_restauracao_nao_repoe_permitir_do_arquivo as test_pg_permitir)
