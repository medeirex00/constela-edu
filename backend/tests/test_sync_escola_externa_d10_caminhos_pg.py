"""D10 pelos outros caminhos (``test_sync_escola_externa_d10_caminhos.py``) num
PostgreSQL REAL, local e descartável (TEST_DATABASE_URL_PG; o nome do banco
precisa conter 'test'). Mesmo padrão de ``test_sync_escola_externa_decisoes_pg.py``:
a consulta em lote da regra única, a revisão, o vínculo e a auditoria rodam aqui no
banco de produção."""
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


from tests.test_sync_escola_externa_d10_caminhos import (  # noqa: E402,F401
    test_admin_global_reativa_com_aviso_e_auditoria as test_pg_reativar_global,
    test_escolher_aposentada_efetiva_em_outra_escola_e_so_do_admin_global as test_pg_efetiva,
    test_reativar_conta_efetiva_em_outra_escola_e_so_do_admin_global as test_pg_reativar_gestao,
    test_s3_admin_global_vincula_pela_importacao_com_aviso_e_auditoria as test_pg_s3_global,
    test_s3_gestao_da_escola_nao_vincula_conta_efetiva_em_outra_pela_importacao as test_pg_s3_gestao)
