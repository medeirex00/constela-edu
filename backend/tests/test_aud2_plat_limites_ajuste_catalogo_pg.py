"""Limites do ajuste manual e do catálogo num PostgreSQL REAL (G_AJUSTE-7) — local e
descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). É no
PG que o valor acima da coluna virava 500 (DataError no commit); o SQLite aceita
qualquer inteiro e texto. Sobrescreve a fixture ``db`` só neste módulo e reusa os
testes de API de ``test_aud2_plat_limites_ajuste_catalogo``.

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud2_plat_limites_ajuste_catalogo_pg.py -m postgres

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


from tests.test_aud2_plat_limites_ajuste_catalogo import (  # noqa: E402,F401
    ids,
    test_elefante_acima_da_coluna_e_422 as test_pg_elefante_acima,
    test_livro_acima_do_limite_e_422_no_cadastro_e_na_correcao as test_pg_livro_acima,
    test_livro_no_limite_e_aceito as test_pg_livro_no_limite,
    test_matific_acima_da_coluna_e_422 as test_pg_matific_acima,
    test_matific_e_elefante_no_teto_da_coluna_sao_aceitos as test_pg_no_teto)
