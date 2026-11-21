"""A leitura em lote das plataformas (DESEMPENHO-6) num PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). Os retratos ordenados uma
vez (``lag``/``lead``) e a faixa de cada período comparada com a das vizinhas: as linhas
escolhidas têm de ser as da regra também no banco de produção. Sobrescreve a fixture ``db``
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


from tests.test_aud2_analise_leitura_em_lote import (  # noqa: E402,F401
    test_funcoes_de_janela_nao_crescem_com_o_numero_de_periodos as test_pg_janelas,
    test_linhas_escolhidas_sao_as_da_regra as test_pg_linhas_escolhidas,
)
