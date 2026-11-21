"""O assistente com provedor externo sem a transação aberta (API_SEGURANCA-3) num
PostgreSQL LOCAL DESCARTÁVEL (``TEST_DATABASE_URL_PG``): durante a chamada de rede,
nenhuma conexão do banco fica "idle in transaction" no ``pg_stat_activity``. Roda
também, no PostgreSQL, os testes de rota do par SQLite.

Sobrescreve a fixture ``db`` só neste módulo; sem a variável, pula. Dados fictícios."""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from tests.test_aud_misc_assistente_prazo_transacao import (  # noqa: F401
    _espiar,
    test_contingencia_tambem_sem_transacao_aberta as test_pg_contingencia,
    test_conversa_apagada_durante_a_chamada_externa_responde_404 as test_pg_conversa_apagada,
    test_conversa_continuada_sem_transacao_aberta_e_com_o_historico as test_pg_continuada,
    test_conversa_nova_sem_transacao_aberta_durante_a_chamada_externa as test_pg_nova,
    test_modo_local_continua_gravando_a_conversa as test_pg_modo_local,
    test_testar_configuracao_sem_transacao_aberta_durante_a_chamada as test_pg_testar,
)

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG")]
API = "/api/v1"


@pytest.fixture()
def db():
    if make_url(URL).host not in ("127.0.0.1", "localhost", "::1"):
        pytest.skip("estes testes recriam as tabelas: só PostgreSQL LOCAL")
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


def _presas(motor) -> list[tuple]:
    """Conexões deste banco (fora a da consulta) paradas dentro de uma transação."""
    with motor.connect() as conexao:
        return [tuple(linha) for linha in conexao.execute(text(
            "SELECT state, left(query, 80) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid() "
            "AND state LIKE 'idle in transaction%'"))]


@pytest.mark.parametrize("rota,corpo,cliente_fixture", [
    ("assistente", {"pergunta": "resumo"}, "cliente"),
    ("assistente/config/testar", None, "cliente_global"),
], ids=["pergunta", "testar-configuracao"])
def test_pg_nenhuma_conexao_presa_durante_a_chamada_externa(request, db, escola_completa,
                                                            monkeypatch, rota, corpo,
                                                            cliente_fixture):
    cliente = request.getfixturevalue(cliente_fixture)
    escola_id = escola_completa["escola"].id
    db.commit()  # a sessão do próprio teste fora de transação
    motor = db.get_bind()
    vistos: list = []
    presas: list = []
    _espiar(monkeypatch, vistos, acao=lambda: presas.append(_presas(motor)))

    r = cliente.post(f"{API}/escolas/{escola_id}/{rota}", json=corpo)

    assert r.status_code == 200, r.text
    assert presas == [[]], f"conexões presas durante a chamada externa: {presas}"
    assert vistos[0]["em_transacao"] is False
