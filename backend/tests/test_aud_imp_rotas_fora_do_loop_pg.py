"""A Lista Piloto espera a trava da escola SEM parar o worker — num PostgreSQL REAL,
local e descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').

Outra operação da mesma escola (uma importação, a sincronização, uma fusão, o 2º
clique em "Confirmar" atendido por outro worker) segura o ``pg_advisory_xact_lock`` da
escola. Com a rota ``async def``, a espera acontecia na thread do event loop: até a
outra transação terminar, o worker não respondia a ninguém — nem a /api/health/live.
Aqui uma conexão à parte segura a trava por 3 s. Sobrescreve a fixture ``db`` só neste
módulo. Dados fictícios."""
import asyncio
import os
import threading

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from tests.test_aud_imp_rotas_fora_do_loop import (
    API,
    CT_XLSX,
    _login,
    conferir,
    lista_piloto,
    medir,
)

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]

SEGURA_S = 3.0


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


def test_lista_piloto_espera_a_trava_da_escola_sem_parar_o_worker(db, escola_completa):
    escola_id = escola_completa["escola"].id
    token = _login(db, escola_id, "coord.pg.loop@teste.local")
    conteudo = lista_piloto(2, 5)

    # Outra transação (outra operação da mesma escola) segura a trava de importação.
    outra = create_engine(URL)
    conexao = outra.connect()
    transacao = conexao.begin()
    conexao.execute(text("SELECT pg_advisory_xact_lock(4711, :e)"), {"e": escola_id})
    soltar = threading.Timer(SEGURA_S, transacao.rollback)
    from app.routers import importacoes as rota

    async def enviar(c):
        return await c.post(f"{API}/escolas/{escola_id}/importacoes/matriculas/confirmar",
                            headers={"Authorization": f"Bearer {token}"},
                            files={"arquivo": ("Lista Piloto 2026.xlsx", conteudo, CT_XLSX)})

    try:
        res = asyncio.run(medir(enviar, rota, "bloquear_escola_para_importacao",
                                ao_comecar=soltar.start))
    finally:
        soltar.cancel()
        conexao.close()
        outra.dispose()
    # A importação esperou a outra operação terminar (a trava continua valendo)...
    assert res["upload"][1] >= SEGURA_S - 0.5, res
    # ...mas o worker seguiu atendendo enquanto isso.
    conferir(res, "importacoes/matriculas/confirmar (trava segura por outra transação)")
