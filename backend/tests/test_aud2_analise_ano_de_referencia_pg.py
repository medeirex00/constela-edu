"""O ano letivo de referência da rede (G_ANALISE-3) num PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). A escolha das escolas em uso
lê a coorte com um ``EXISTS`` correlacionado (``indicadores.escolas_com_aluno``) quando as
escolas estão em anos letivos diferentes: aqui os mesmos testes do SQLite rodam no banco de
produção. Sobrescreve a fixture ``db`` só neste módulo."""
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


from tests.test_aud2_analise_ano_de_referencia import (  # noqa: E402,F401
    test_alerta_do_catalogo_fala_do_ano_das_escolas_em_uso as test_pg_alerta_do_catalogo,
    test_escola_inativa_com_aluno_noutro_ano_continua_avisada as test_pg_inativa_com_aluno,
    test_escolas_fechadas_sem_aluno_nao_decidem_o_ano_da_rede as test_pg_escolas_fechadas,
    test_ficha_da_escola_usa_o_ano_da_propria_escola as test_pg_ficha,
    test_virada_escolas_so_cadastradas_nao_prendem_a_rede_no_ano_velho as test_pg_virada,
)
