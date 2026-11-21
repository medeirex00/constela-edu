"""A guarda das medidas dos blocos (REV2-ANALISE-1) num PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). O carimbo dos dados vai na
consulta da coorte (contagens e somas em ``BIGINT`` numa ``UNION ALL`` com colunas nulas
tipadas): tem de valer também no banco de produção. Sobrescreve a fixture ``db`` só neste
módulo."""
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


from tests.test_aud2_analise_guarda_dos_blocos import (  # noqa: E402,F401
    _guarda_limpa,
    medidas,
    test_ano_letivo_pedido_de_novo_mede_so_o_periodo as test_pg_ano_letivo_de_novo,
    test_cada_mudanca_mede_de_novo_so_a_escola_dela as test_pg_cada_mudanca,
    test_coleta_de_janeiro_chegada_depois_esconde_o_ano as test_pg_coleta_de_janeiro,
    test_crianca_inativada_muda_a_coorte_e_o_bloco as test_pg_crianca_inativada,
    test_crianca_que_muda_de_serie_entre_duas_series_visiveis as test_pg_muda_de_serie,
    test_fusao_de_fichas_sem_linha_nova_esconde_o_ano as test_pg_fusao,
    test_serie_ficha_diagnostico_e_relacao_reaproveitam_os_blocos as test_pg_rotas,
)
