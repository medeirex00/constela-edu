"""Tamanho dos campos de texto de entrada num PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). É no PG que o
valor acima da coluna virava 500 (DataError no commit); o SQLite aceita qualquer
tamanho. Sobrescreve a fixture ``db`` só neste módulo e reusa os testes de API de
``test_schemas_tamanho_colunas``."""
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


from tests.test_schemas_tamanho_colunas import (  # noqa: E402,F401
    apoio,
    test_cadastro_completo_de_professor_email as test_pg_professor_completo_email,
    test_cadastro_de_aluno_observacoes as test_pg_aluno_observacoes,
    test_cadastro_de_conta_email as test_pg_conta_email,
    test_cadastro_de_professor_acima_da_coluna as test_pg_professor_acima,
    test_cadastro_de_professor_no_limite as test_pg_professor_no_limite,
    test_edicao_do_email_do_professor as test_pg_professor_email,
    test_edicao_do_nome_da_conta as test_pg_conta_nome)
