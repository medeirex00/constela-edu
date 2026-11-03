"""Fusão × memória do D10 (``test_fusao_preserva_decisao_d10.py``) num PostgreSQL
REAL, local e descartável (TEST_DATABASE_URL_PG; o nome do banco precisa conter
'test'): aqui a FK ``ondelete=SET NULL`` de ``aluno_escolhido_id`` roda de verdade.
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


from tests.test_fusao_preserva_decisao_d10 import (  # noqa: E402,F401
    test_fusao_de_um_par_preserva_a_confirmacao_do_d10 as test_pg_par,
    test_fusao_em_lote_preserva_a_confirmacao_do_d10 as test_pg_lote)
