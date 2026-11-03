"""As três frentes da Etapa 3 juntas num PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). O filtro do
"em dia" (``coalesce`` + ``NOT IN``), o vínculo da escola externa (JSON em
``configuracoes``) e o coletor das métricas (transação READ ONLY com teto por
consulta) rodam aqui no banco de produção. Sobrescreve a fixture ``db`` só neste
módulo e reusa os testes SQLite de ``test_sync_etapa3_integracao.py``."""
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


from tests.test_sync_etapa3_integracao import (  # noqa: E402,F401
    test_conta_multiescola_nunca_e_em_dia_e_aparece_nas_metricas as test_pg_conta_multiescola,
    test_contas_de_outra_escola_do_constela_sao_tudo_em_revisao_ate_o_gestor_confirmar
    as test_pg_contas_de_outra_escola,
    test_credencial_trocada_e_recusada_nao_anda_o_em_dia_e_aparece_nas_metricas
    as test_pg_credencial_trocada)
