"""Decisões da escola externa (``test_sync_escola_externa_decisoes.py``) num
PostgreSQL REAL, local e descartável (TEST_DATABASE_URL_PG; o nome do banco
precisa conter 'test'). Mesmo padrão de ``test_sync_escola_cruzada_revisao_pg.py``:
as consultas em lote (``IN``), o JSON do vínculo e a auditoria rodam aqui no banco
de produção."""
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


from tests.test_sync_escola_externa_decisoes import (  # noqa: E402,F401
    test_d8_coleta_mista_com_conta_desta_escola_aplica_so_as_da_escola as test_pg_d8_mista,
    test_d8_elefante_credencial_de_outra_escola_sem_vinculo_nao_grava_nada as test_pg_d8_el,
    test_d8_ficha_inativa_aqui_com_conta_de_crianca_ativa_daqui_segue_mista as
    test_pg_d8_inativa_mista,
    test_d8_matific_credencial_de_outra_escola_sem_vinculo_nao_grava_nada as test_pg_d8_mt,
    test_d8_identidade_nao_efetiva_aqui_nao_livra_da_recusa as test_pg_d8_nao_efetiva,
    test_d8_regra_de_efetiva_aqui_e_a_mesma_de_outra_escola as test_pg_d8_regra,
    test_d9_nome_divergente_coleta_sem_aprender_e_a_dona_aprende as test_pg_d9,
    test_d10_admin_global_confirma_com_aviso_e_auditoria as test_pg_d10_global,
    test_d10_gestao_da_escola_nao_confirma_conta_efetiva_em_outra_escola as test_pg_d10_gestao)
