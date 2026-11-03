"""D19 num PostgreSQL REAL — local e descartável (``TEST_DATABASE_URL_PG``; o
nome do banco precisa conter 'test'). É no PG que valem a integridade
referencial de produção, o ``rowcount`` das contagens da auditoria, a trava de
importação da escola (``pg_advisory_xact_lock``) e o ROLLBACK da transação
única quando algo falha no meio. Sobrescreve a fixture ``db`` só neste módulo e
reusa os testes SQLite de ``test_turma_excluir_com_alunos_admin_global``."""
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


from tests.test_turma_excluir_com_alunos_admin_global import (  # noqa: E402,F401
    pastas,
    test_admin_da_escola_nao_exclui_turma_com_alunos as test_pg_admin_escola_403,
    test_admin_global_desvincula_e_audita_as_matriculas as test_pg_desvincula,
    test_admin_global_exclui_com_contagens_na_resposta_e_na_auditoria as test_pg_contagens,
    test_exclusao_em_massa_com_alunos_recusada_inteira as test_pg_massa_403,
    test_falha_no_meio_da_exclusao_desfaz_tudo as test_pg_rollback)
