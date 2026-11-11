"""A prévia da Lista Piloto num PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). A prévia roda a
confirmação dentro de um SAVEPOINT e a desfaz (``_simular_lista_piloto``): aqui, no
banco de produção, os mesmos testes provam que os números são os da confirmação e
que nada fica gravado — nem a turma nova criada na simulação. Sobrescreve a fixture
``db`` só neste módulo."""
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


from tests.test_aud_imp_lista_piloto_previa import (  # noqa: E402,F401
    test_previa_conta_como_a_confirmacao as test_pg_previa_conta_como_a_confirmacao,
    test_reenvio_da_mesma_lista_so_atualiza as test_pg_reenvio_da_mesma_lista_so_atualiza,
)
from tests.test_lista_piloto_tamanho_colunas import (  # noqa: E402,F401
    test_serie_que_mudaria_a_leitura_deixa_a_aba_de_fora as test_pg_previa_nao_cria_a_turma,
)
