"""Os casos de ``test_aud_imp_valores_fora_da_coluna`` num PostgreSQL REAL — local e
descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). É aqui
que o defeito aparecia: o ``integer`` e os ``varchar(N)`` do PostgreSQL recusavam no
commit (500) o que o SQLite dos testes aceitava. Sobrescreve a fixture ``db`` só
neste módulo."""
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


from tests.test_aud_imp_valores_fora_da_coluna import (  # noqa: E402,F401
    test_confirmar_ignora_a_linha_com_texto_longo_demais as test_pg_confirmar_ignora_texto_longo,
    test_confirmar_recusa_contagem_absurda_com_400 as test_pg_confirmar_recusa_contagem_absurda,
    test_previa_marca_a_linha_com_texto_longo_demais as test_pg_previa_marca_texto_longo,
    test_previa_mostra_numero_gigante_como_ilegivel as test_pg_previa_numero_gigante,
)
