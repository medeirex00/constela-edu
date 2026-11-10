"""Nº de chamada fora do INTEGER no PostgreSQL: 422, não 500 (cadastro e edição).

No SQLite a coluna não tem limite; no PostgreSQL o valor acima de 2³¹−1 estourava
no commit (``NumericValueOutOfRange``) e a resposta era 500 "Erro interno". O
limite exato (2³¹−1) continua gravando.

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud_alunos_numero_chamada_limite_pg.py -m postgres

Achado ALUNOS-9 da auditoria. Dados fictícios.
"""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.services.lista_piloto import MAX_NUMERO_CHAMADA

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]


@pytest.fixture()
def db():
    """O mesmo ``db`` do conftest, mas num PostgreSQL de teste descartável."""
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


def test_numero_de_chamada_fora_do_inteiro_nao_da_500(db, cliente, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    ana = escola_completa["alunos"][0]
    http = TestClient(app, raise_server_exceptions=False)
    http.headers.update(cliente.headers)
    base = f"/api/v1/escolas/{escola.id}"
    r1 = http.post(f"{base}/alunos", json={"nome": "Crianca Ficticia Nova",
                                           "turma_id": turma.id,
                                           "numero_chamada": 3_000_000_000})
    r2 = http.patch(f"{base}/alunos/{ana.id}", json={"numero_chamada": 3_000_000_000})
    assert (r1.status_code, r2.status_code) == (422, 422), \
        f"cadastro {r1.status_code} {r1.text[:120]} | edição {r2.status_code} {r2.text[:120]}"

    # O limite exato da coluna grava normalmente.
    r3 = http.patch(f"{base}/alunos/{ana.id}", json={"numero_chamada": MAX_NUMERO_CHAMADA})
    assert r3.status_code == 200, r3.text
    assert r3.json()["numero_chamada"] == MAX_NUMERO_CHAMADA
