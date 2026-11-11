"""Congelamento do nível × livro corrigido no meio, num PostgreSQL REAL (G_SCRIPTS-7)
— local e descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter
'test'). Confere no banco de produção o ``UPDATE`` condicional (EXISTS correlato com
``upper(trim(...))``) e a trava da escola tomada pelo script. Sobrescreve a fixture
``db`` só neste módulo e reusa os testes de ``test_aud2_plat_congelar_niveis_corrida``.

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud2_plat_congelar_niveis_corrida_pg.py -m postgres

Dados fictícios.
"""
import importlib
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
    importlib.import_module("app.quest.models")   # registra o schema completo
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


from tests.test_aud2_plat_congelar_niveis_corrida import (  # noqa: E402,F401
    test_livro_corrigido_entre_a_analise_e_o_update_nao_congela_o_nivel_velho as test_pg_corrida,
    test_rodar_de_novo_congela_o_nivel_atual as test_pg_rodar_de_novo,
    test_sem_corrida_o_congelamento_e_o_de_sempre as test_pg_sem_corrida)
