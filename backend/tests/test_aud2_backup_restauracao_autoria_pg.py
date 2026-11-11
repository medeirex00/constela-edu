"""G_LGPD-7 (``test_aud2_backup_restauracao_autoria.py``) num PostgreSQL REAL, local e
descartável (TEST_DATABASE_URL_PG; o nome do banco precisa conter 'test'). O
PostgreSQL confere a FK de ``importacoes.usuario_id`` como em produção: o autor que
não existe mais tem de virar NULL. Mesmo padrão de
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


from tests.test_aud2_backup_restauracao_autoria import (  # noqa: E402,F401
    test_autor_que_nao_existe_mais_vira_vazio_e_a_restauracao_segue as test_pg_autor_removido,
    test_restauracao_mantem_quem_fez_cada_importacao as test_pg_autoria,
)
