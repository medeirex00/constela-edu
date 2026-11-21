"""G_LGPD-2 (``test_aud2_backup_restauracao_fusao.py``) num PostgreSQL REAL, local e
descartável (TEST_DATABASE_URL_PG; o nome do banco precisa conter 'test'). O
PostgreSQL nunca reaproveita o id de uma linha apagada: a duplicata absorvida voltava
com id novo e a conta da plataforma. Mesmo padrão de
``test_backup_restauracao_d10_pg.py``."""
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


from tests.test_aud2_backup_restauracao_fusao import (  # noqa: E402,F401
    test_entre_escolas_a_copia_da_duplicata_nao_volta as test_pg_entre_escolas,
    test_excluir_a_duplicata_que_voltou_tambem_segura_a_oficial as test_pg_outro_sentido,
    test_fusao_antes_do_backup_a_crianca_nao_volta as test_pg_fusao_antes,
    test_fusao_depois_do_backup_a_duplicata_nao_volta as test_pg_fusao_depois,
)
