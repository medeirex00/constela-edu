"""G_LGPD-4 (``test_aud2_backup_restauracao_revisoes.py``) num PostgreSQL REAL, local e
descartável (TEST_DATABASE_URL_PG; o nome do banco precisa conter 'test'). O
PostgreSQL nunca reaproveita o id de uma linha apagada: é onde os candidatos antigos
apontavam para fichas que não existem. Mesmo padrão de
``test_backup_restauracao_d10_pg.py``."""
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
    from app.quest import models as _quest  # noqa: F401
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


from tests.test_aud2_backup_restauracao_revisoes import (  # noqa: E402,F401
    test_arquivo_anterior_a_outra_restauracao_reaponta_pela_linhagem as test_pg_linhagem,
    test_o_que_o_arquivo_nao_traz_sai_da_fila_e_fica_contado_no_log as test_pg_sem_equivalente,
    test_restauracao_mantem_a_importacao_da_execucao_da_sincronizacao as test_pg_execucao,
    test_restauracao_mantem_a_memoria_da_decisao_humana as test_pg_memoria_d10,
    test_restauracao_reaponta_candidatos_turma_e_importacao_da_pendencia as test_pg_candidatos,
)
