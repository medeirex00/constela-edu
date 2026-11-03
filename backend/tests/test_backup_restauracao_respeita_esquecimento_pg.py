"""Restauração que respeita a exclusão permanente
(``test_backup_restauracao_respeita_esquecimento.py``) num PostgreSQL REAL, local e
descartável (TEST_DATABASE_URL_PG; o nome do banco precisa conter 'test'). No PG um id
nunca volta a ser usado — é o que faz o ``entidade_id`` do log provar a mesma criança.
Mesmo padrão de ``test_backup_restauracao_d10_pg.py``."""
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


from tests.test_backup_restauracao_respeita_esquecimento import (  # noqa: E402,F401
    test_arquivo_antigo_sem_a_marca_do_log_tambem_respeita_a_exclusao as test_pg_sem_marca,
    test_arquivo_de_outra_escola_nao_ressuscita_a_crianca_excluida_na_origem as test_pg_a_em_b,
    test_arquivo_de_outra_escola_sem_exclusao_restaura_todas as test_pg_a_em_b_sem_exclusao,
    test_backup_antigo_nao_ressuscita_a_crianca_excluida_e_avisa as test_pg_antigo,
    test_backup_feito_depois_da_exclusao_restaura_tudo_sem_aviso as test_pg_depois,
    test_backup_sem_exclusao_restaura_todas_as_criancas as test_pg_sem_exclusao)
