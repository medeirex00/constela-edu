"""C-06 (``test_backup_restauracao_sem_perda.py``) num PostgreSQL REAL, local e
descartável (TEST_DATABASE_URL_PG; o nome do banco precisa conter 'test'). Mesmo
padrão de ``test_backup_restauracao_d10_pg.py``.

Por que existe (S_G_LGPD-3): a suíte é a rede de proteção da restauração, mas não tinha
o marcador ``postgres`` e o job de PostgreSQL do CI roda só ``pytest -m postgres`` — ela
nunca rodava no banco de produção. No SQLite o banco devolve à ficha recriada o id
antigo, e um teste chegou a passar por isso (lia a ficha APAGADA pelo id, que no
PostgreSQL levanta ``ObjectDeletedError``). Aqui entram TODOS os testes da suíte que
usam o banco (``db``), inclusive os que ela ganhar depois; os estruturais, que não
tocam no banco, ficam só lá.
"""
import inspect
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from tests import test_backup_restauracao_sem_perda as _suite

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.usefixtures("cliente"),
              pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]


@pytest.fixture()
def db():
    from app.quest import models as _quest  # noqa: F401 — o schema inteiro (Quest)
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


_DA_SUITE = {nome: teste for nome, teste in vars(_suite).items()
             if nome.startswith("test_") and callable(teste)
             and "db" in inspect.signature(teste).parameters}
globals().update(_DA_SUITE)


def test_a_suite_entra_inteira_no_postgres():
    """Os testes da suíte que usam o banco estão todos aqui (os que não usam são os
    estruturais, que valem para qualquer banco)."""
    assert len(_DA_SUITE) >= 15
    assert "test_roundtrip_preserva_identidade_externa_evento_e_marcador" in _DA_SUITE
