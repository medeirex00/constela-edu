"""P15 — com "bloquear" a sync do Matific não move a matrícula — num PostgreSQL REAL,
local e descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter
'test'). A sync, a trava de importação por escola e a Lista Piloto rodam no banco
de produção. Sobrescreve a fixture ``db`` só neste módulo e reusa os testes SQLite
de ``test_sync_politica_bloquear_matricula``."""
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


from tests.test_sync_politica_bloquear_matricula import (  # noqa: E402,F401
    test_bloquear_a_divergencia_vira_aviso_e_nao_conta_como_dado_alterado
    as test_pg_bloquear_aviso_sem_aplicado,
    test_bloquear_lista_piloto_e_matific_nao_alternam_a_matricula
    as test_pg_bloquear_sem_vai_e_volta,
    test_bloquear_sync_do_matific_nao_move_a_matricula_da_lista_piloto
    as test_pg_bloquear_nao_move,
    test_permitir_a_sync_do_matific_continua_movendo as test_pg_permitir_continua_movendo)
