"""Upload manual seguindo a política 'bloquear' num PostgreSQL REAL — local e
descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').
A trava de importação por escola e a fila de revisão rodam no banco de
produção. Sobrescreve a fixture ``db`` só neste módulo e reusa os testes SQLite
de ``test_importacao_manual_politica``."""
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


from tests.test_importacao_manual_politica import (  # noqa: E402,F401
    test_bloquear_nao_cria_turma_vazia_pelo_nome_do_relatorio as test_pg_sem_turma_vazia,
    test_confirmar_pela_tela_com_bloquear_nao_cria_e_diz_o_motivo as test_pg_bloquear,
    test_lista_piloto_continua_criando_com_bloquear as test_pg_lista_piloto,
    test_revisao_continua_criando_a_ficha_deliberada as test_pg_revisao_cria)
