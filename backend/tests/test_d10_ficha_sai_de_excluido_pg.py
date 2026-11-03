"""D10 pela ficha (``test_d10_ficha_sai_de_excluido.py``) num PostgreSQL REAL,
local e descartável (TEST_DATABASE_URL_PG; o nome do banco precisa conter
'test'). Mesmo padrão de ``test_sync_escola_externa_d10_caminhos_pg.py``: a
consulta em lote das identidades da ficha, a regra única, a recusa sem mudar nada
(rollback), a auditoria e a Lista Piloto rodam aqui no banco de produção."""
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


from tests.test_d10_ficha_sai_de_excluido import (  # noqa: E402,F401
    test_acao_em_massa_com_uma_ficha_travada_e_recusada_inteira as test_pg_massa,
    test_admin_global_tira_de_excluido_com_aviso_e_auditoria as test_pg_global,
    test_gestao_nao_tira_de_excluido_ficha_com_conta_efetiva_em_outra_escola as test_pg_gestao,
    test_lista_piloto_nao_reativa_ficha_excluida_com_conta_efetiva_em_outra_escola as
    test_pg_lista_piloto,
    test_lista_piloto_reativa_quando_a_conta_deixa_de_valer_na_outra_escola as
    test_pg_lista_piloto_depois)
