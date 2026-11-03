"""D17 num PostgreSQL REAL — local e descartável (``TEST_DATABASE_URL_PG``; o
nome do banco precisa conter 'test'). No PG o arquivamento toma a trava de
importação da escola (``pg_advisory_xact_lock``) antes de contar as matrículas;
o SQLite não exercita esse caminho. Sobrescreve a fixture ``db`` só neste
módulo e reusa os testes SQLite de ``test_turma_arquivar_com_alunos_ativos``."""
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


from tests.test_turma_arquivar_com_alunos_ativos import (  # noqa: E402,F401
    test_arquivar_liberado_depois_de_transferir_os_alunos as test_pg_transferir_e_arquivar,
    test_arquivar_turma_com_alunos_ativos_e_recusado as test_pg_recusa_com_ativos,
    test_turma_do_ano_anterior_arquiva_mesmo_com_os_alunos_ativos_hoje as test_pg_ano_anterior,
    test_turma_ja_arquivada_mantem_o_significado as test_pg_ja_arquivada)
