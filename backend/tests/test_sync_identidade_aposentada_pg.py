"""Conta aposentada como descarte com motivo próprio num PostgreSQL REAL — local e
descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').
O "verificado" e o "em dia" que a tela mostra saem de filtros SQL
(``service._filtro_verificacao``/``_filtro_em_dia``); aqui eles rodam no banco
de produção. Sobrescreve a fixture ``db`` só neste módulo e reusa os testes
SQLite de ``test_sync_identidade_aposentada``."""
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


from tests.test_sync_identidade_aposentada import (  # noqa: E402,F401
    test_conta_aposentada_nao_desfaz_o_cursor_da_crianca as test_pg_cursor_da_crianca,
    test_conta_aposentada_nao_vira_pendencia_permanente as test_pg_sem_pendencia_permanente,
    test_importacao_manual_descarta_a_conta_aposentada_com_motivo_proprio
    as test_pg_importacao_manual,
    test_so_contas_aposentadas_na_coleta_nao_e_em_dia as test_pg_so_aposentadas)
