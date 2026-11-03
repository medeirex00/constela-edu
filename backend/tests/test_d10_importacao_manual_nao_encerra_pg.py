"""A importação manual da gestão não encerra a pendência da conta de outra escola
(``test_d10_importacao_manual_nao_encerra.py``) num PostgreSQL REAL, local e
descartável (TEST_DATABASE_URL_PG; o nome do banco precisa conter 'test').
Mesmo padrão de ``test_d10_ficha_sai_de_excluido_pg.py``."""
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


from tests.test_d10_importacao_manual_nao_encerra import (  # noqa: E402,F401
    test_admin_global_na_importacao_manual_segue_a_regra_geral as test_pg_admin_global,
    test_gestao_aplica_o_dado_pela_importacao_manual_mas_a_pendencia_fica as
    test_pg_pendencia_fica,
    test_gestao_com_nome_abreviado_nao_grava_memoria_e_a_coleta_seguinte_revisa as
    test_pg_sem_memoria,
    test_gestao_encerra_pela_importacao_quando_a_conta_ja_nao_e_de_outra_escola as
    test_pg_gestao_regra_geral,
    test_sincronizacao_encerra_sozinha_quando_a_conta_deixa_de_ser_de_outra_escola as
    test_pg_sync_encerra)
