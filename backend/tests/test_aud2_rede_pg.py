"""Os testes da frente REDE (2ª onda da auditoria) num PostgreSQL REAL — local e
descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').

Os cartões das escolas da rede saem de ``UNION ALL`` com colunas nulas TIPADAS
(``rede._leituras_da_rede``): o PostgreSQL exige o mesmo tipo em cada posição de todos
os ramos, coisa que o SQLite não confere. Sobrescreve a fixture ``db`` só neste módulo."""
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


from tests.test_aud2_rede_indice_peso import (  # noqa: E402,F401
    test_indice_e_media_geral_da_rede_nao_pesam_as_criancas_da_fase as test_pg_indice_peso,
    test_panorama_global_pesa_redes_e_escolas_por_quem_concorre as test_pg_indice_global,
)
