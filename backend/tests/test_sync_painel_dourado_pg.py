"""O dourado e o orçamento do GET /sync/dashboard num PostgreSQL REAL — local e
descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').

Produção roda PostgreSQL: as consultas agrupadas do painel (contagens numa
instrução só, contrato das escolas vencidas e credenciais das agendas em lote,
recálculo pendente com NOT EXISTS) têm de devolver no PostgreSQL o MESMO JSON
gravado com o código de antes e caber no mesmo orçamento de instruções — que no
PostgreSQL inclui as 3 consultas do catálogo para ler as colunas da tabela."""
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


from tests.test_sync_painel_dourado import (  # noqa: E402,F401
    test_painel_devolve_o_json_gravado as test_pg_painel_devolve_o_json_gravado)
from tests.test_sync_painel_orcamento import (  # noqa: E402,F401
    test_numero_de_instrucoes_nao_cresce_com_agendas_nem_extras as test_pg_painel_volume,
    test_painel_cabe_no_orcamento_e_nao_commita as test_pg_painel_orcamento)
