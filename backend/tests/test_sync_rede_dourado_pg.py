"""O dourado e o orçamento do /sync/status e do /sync/agora de escola DE REDE num
PostgreSQL REAL — local e descartável (``TEST_DATABASE_URL_PG``; o nome do banco
precisa conter 'test').

Produção roda PostgreSQL: o contrato da rede lido junto com a escola (EXISTS
correlacionado no /status, junção escola × modulos_rede no /agora) tem de devolver
no PostgreSQL o MESMO JSON gravado com o código de antes, com o mesmo número de
instruções da escola avulsa."""
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


from tests.test_sync_rede_dourado import (  # noqa: E402,F401
    test_agora_de_escola_de_rede_devolve_o_json_gravado as test_pg_agora_de_rede_dourado,
    test_status_de_escola_de_rede_devolve_o_json_gravado as test_pg_status_de_rede_dourado)
from tests.test_sync_rede_orcamento import (  # noqa: E402,F401
    test_agora_de_rede_custa_o_mesmo_que_o_da_avulsa as test_pg_agora_de_rede_orcamento,
    test_status_de_rede_custa_o_mesmo_que_o_da_avulsa as test_pg_status_de_rede_orcamento,
    test_status_de_rede_sem_um_modulo_nao_paga_ida_a_mais as test_pg_status_sem_modulo)
