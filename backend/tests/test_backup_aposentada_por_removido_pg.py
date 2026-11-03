"""Restauração do backup com o autor da aposentadoria removido
(``test_backup_aposentada_por_removido.py``) num PostgreSQL REAL, local e
descartável (TEST_DATABASE_URL_PG; o nome do banco precisa conter 'test').
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


from tests.test_backup_aposentada_por_removido import (  # noqa: E402,F401
    test_backup_anterior_a_remocao_de_quem_aposentou_restaura_sem_o_autor as
    test_pg_sem_o_autor,
    test_backup_restaura_com_o_autor_da_aposentadoria_vivo_e_mantem_o_autor as
    test_pg_autor_vivo,
    test_restaurar_servico_anula_so_a_referencia_a_usuario_inexistente as
    test_pg_servico)
