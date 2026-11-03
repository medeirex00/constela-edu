"""Regenerar a turma × quem saiu dela, num PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). A lista de quem
esteve na folha é lida dos detalhes JSON de ``logs_auditoria``; aqui se confere que o
PG devolve o mesmo que o SQLite. Sobrescreve a fixture ``db`` só neste módulo e reusa
os testes de ``test_quest_regenerar_turma_quem_saiu``. Dados fictícios."""
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


from tests.test_quest_regenerar_turma_quem_saiu import (  # noqa: E402
    test_folha_perdida_da_turma_a_cai_para_quem_trocou_de_turma as test_pg_folha_perdida,
    test_folha_registrada_antes_dos_aluno_ids_nao_quebra_o_regenerar as test_pg_folha_antiga,
    test_so_as_folhas_desde_a_ultima_revogacao_contam as test_pg_janela,
)

__all__ = ["test_pg_folha_perdida", "test_pg_folha_antiga", "test_pg_janela"]
