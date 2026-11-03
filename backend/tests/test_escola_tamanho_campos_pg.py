"""``cidade``/``logotipo_url`` da escola num PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). É no PG que o
valor acima da coluna virava 500 (DataError no commit); o SQLite aceita qualquer
tamanho. Sobrescreve a fixture ``db`` só neste módulo e reusa os testes SQLite de
``test_escola_tamanho_campos``."""
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


from tests.test_escola_tamanho_campos import (  # noqa: E402,F401
    test_patch_campo_acima_da_coluna_responde_422_sem_gravar as test_pg_patch_acima_422,
    test_patch_no_limite_da_coluna_grava as test_pg_patch_no_limite,
    test_post_cidade_acima_da_coluna_responde_422_sem_criar as test_pg_post_acima_422,
    test_post_cidade_no_limite_da_coluna_cria as test_pg_post_no_limite)
