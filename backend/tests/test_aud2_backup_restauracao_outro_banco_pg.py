"""REV2-BACKUP-1 (``test_aud2_backup_restauracao_outro_banco.py``) num PostgreSQL REAL,
local e descartável (TEST_DATABASE_URL_PG; o nome do banco precisa conter 'test'): o
arquivo vem de uma escola exportada em OUTRO banco e é restaurado numa escola do
PostgreSQL que tem as SUAS crianças com os mesmos ids. Mesmo padrão de
``test_aud2_backup_restauracao_revisoes_pg.py``."""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base

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
    sessao = sessionmaker(bind=engine)()
    yield sessao
    sessao.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


from tests.test_aud2_backup_restauracao_outro_banco import (  # noqa: E402,F401
    test_arquivo_de_outro_banco_nao_religa_a_fila_a_outras_criancas as test_pg_outro_banco,
    test_linhagem_com_numeros_de_outro_banco_nao_religa_a_outra_crianca as test_pg_linhagem,
)
