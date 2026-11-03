"""A trava do provedor externo do assistente (A1 / P9) com a sessão num PostgreSQL
LOCAL DESCARTÁVEL (``TEST_DATABASE_URL_PG``): o 403 antes de gravar e o "desligar
descarta a chave" (JSON da ``Configuracao`` regravado) também no banco de produção.

Sobrescreve a fixture ``db`` só neste módulo; sem a variável, pula. Dados fictícios."""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG")]


@pytest.fixture()
def db():
    if make_url(URL).host not in ("127.0.0.1", "localhost", "::1"):
        pytest.skip("estes testes recriam as tabelas: só PostgreSQL LOCAL")
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


from tests.test_ia_provedor_externo_admin_global import (  # noqa: E402,F401
    test_admin_da_escola_nao_liga_provedor_externo_nem_grava_chave as test_pg_escola_nao_liga,
    test_global_liga_e_a_escola_ve_o_estado_e_desliga as test_pg_global_liga_escola_desliga,
)
