"""Vitrine pública da rede com o k mínimo (``test_vitrine_rede_k_minimo.py``) num
PostgreSQL REAL, local e descartável (TEST_DATABASE_URL_PG; o nome do banco precisa
conter 'test'). A contagem de quem CONTRIBUI (``sum(case(campo > 0, 1, 0))`` sobre o
retrato atual, em ``rede._totais_plataforma_por_escola``) roda aqui no dialeto de
produção. Mesmo padrão de ``test_backup_restauracao_respeita_esquecimento_pg.py``."""
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


from tests.test_vitrine_rede_k_minimo import (  # noqa: E402,F401
    test_vitrine_aplica_o_k_de_quem_contribui_por_materia as test_pg_k_por_materia,
    test_vitrine_com_cinco_que_contribuem_publica_o_mesmo_per_capita as test_pg_cinco,
    test_vitrine_omite_escola_com_menos_de_k_criancas_que_concorrem as test_pg_k_concorrem,
    test_vitrine_omite_escola_com_uma_so_crianca_com_dado_entre_cinco as test_pg_uma_so)
