"""Linhagem das fichas entre restaurações de escolas diferentes e a cópia em outra escola
(``test_backup_linhagem_entre_escolas.py``) num PostgreSQL REAL, local e descartável
(TEST_DATABASE_URL_PG; o nome do banco precisa conter 'test'). No PG um id nunca volta a
ser usado: é o que faz a ligação gravada no log de uma escola provar a mesma criança na
outra. Mesmo padrão de ``test_backup_restauracao_respeita_esquecimento_pg.py``."""
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


from tests.test_backup_linhagem_entre_escolas import (  # noqa: E402,F401
    test_arquivo_de_A_anterior_a_restauracao_de_A_restaurado_em_B as test_pg_a_antes_em_b,
    test_controle_copia_sem_exclusao_volta_com_o_backup_de_B as test_pg_copia_sem_exclusao,
    test_controle_mesmo_arquivo_restaurado_em_A_nao_traz_a_excluida as test_pg_controle_em_a,
    test_copia_em_B_da_crianca_excluida_de_vez_em_A_nao_volta_com_o_backup_de_B
    as test_pg_copia_em_b_nao_volta,
    test_ficha_de_A_nao_volta_com_o_backup_de_A_se_B_excluiu_de_vez_a_copia
    as test_pg_ficha_de_a_nao_volta)
from tests.test_backup_linhagem_entre_escolas import (  # noqa: E402,F401
    test_backup_de_A_gerado_depois_que_B_excluiu_de_vez_a_copia_traz_a_ficha_de_A
    as test_pg_backup_de_a_depois_da_exclusao_em_b,
    test_backup_de_B_gerado_depois_que_A_excluiu_de_vez_traz_a_copia_de_B
    as test_pg_backup_de_b_depois_da_exclusao_em_a,
    test_dois_downloads_do_mesmo_estado_de_A_restauram_igual
    as test_pg_dois_downloads_do_mesmo_estado)
