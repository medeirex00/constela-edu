"""D10 na restauração (``test_backup_restauracao_d10.py``) num PostgreSQL REAL,
local e descartável (TEST_DATABASE_URL_PG; o nome do banco precisa conter 'test').
Mesmo padrão de ``test_d10_ficha_sai_de_excluido_pg.py``."""
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


from tests.test_backup_restauracao_d10 import (  # noqa: E402,F401
    test_restaurar_avisa_e_audita_a_conta_que_passa_a_valer_nas_duas as test_pg_aviso,
    test_restaurar_nao_grava_memoria_e_a_coleta_daqui_tambem_revisa as test_pg_sem_memoria,
    test_restaurar_sem_conta_de_outra_escola_devolve_avisos_vazio as test_pg_vazio)
