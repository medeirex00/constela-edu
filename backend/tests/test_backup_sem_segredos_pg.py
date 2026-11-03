"""A restauração sem segredos (lacuna L1 do e97) com a sessão num PostgreSQL LOCAL
DESCARTÁVEL (``TEST_DATABASE_URL_PG``). O ``DELETE ... namespace NOT IN (...)`` que
preserva as configurações de segredo/acesso só tinha rodado em SQLite.

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


from tests.test_backup_sem_segredos import (  # noqa: E402,F401
    escola_com_segredos,
    test_restaurar_backup_antigo_nao_reativa_link_nem_devolve_cifra_morta as test_pg_antigo,
    test_restaurar_nao_cria_painel_que_a_escola_nao_tem as test_pg_nao_cria_painel,
    test_restaurar_nao_reabre_painel_desativado_depois_do_backup as test_pg_desativado,
    test_rota_restaurar_backup_antigo_mantem_o_link_atual as test_pg_rota_restaurar)
