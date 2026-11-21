"""As travas da escola recusam a sessão em AUTOCOMMIT em vez de "travar" sem travar nada.

``bloquear_escola_para_importacao`` (4711), ``bloquear_fonte_para_coleta`` (4712) e
``bloquear_escola_para_recalculo`` (4711 compartilhada, depois 4713 exclusiva) tomam
travas até o fim da TRANSAÇÃO. Numa conexão em AUTOCOMMIT — a ``SessionLeitura`` das rotas
``leitura_sem_transacao``, que usa o MESMO pool — cada comando é a sua própria transação: a
trava caía no fim do próprio SELECT, a função voltava normal e duas importações, coletas ou
recálculos da mesma escola corriam juntos sem aviso (BANCO-2). Agora a trava recusa com
``RuntimeError`` antes de executar.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.database import (
    _NS_COLETA_AVALIACAO,
    _NS_IMPORTACAO,
    _NS_RECALCULO,
    bloquear_escola_para_importacao,
    bloquear_escola_para_recalculo,
    bloquear_fonte_para_coleta,
    sessao_de_leitura,
)

URL_PG = os.environ.get("TEST_DATABASE_URL_PG", "")

EXCLUSIVA = "pg_advisory_xact_lock"
COMPARTILHADA = "pg_advisory_xact_lock_shared"
TRAVAS = [
    (bloquear_escola_para_importacao, [(_NS_IMPORTACAO, EXCLUSIVA)]),
    (bloquear_escola_para_recalculo,
     [(_NS_IMPORTACAO, COMPARTILHADA), (_NS_RECALCULO, EXCLUSIVA)]),
    (bloquear_fonte_para_coleta, [(_NS_COLETA_AVALIACAO, EXCLUSIVA)]),
]
IDS = [t.__name__ for t, _ in TRAVAS]


# --- sem banco de rede: uma sessão falsa que se diz PostgreSQL ------------------------------

class _SessaoFalsa:
    def __init__(self, *, isolamento: str | None, autocommit: bool):
        self.executados: list = []
        self._conexao = SimpleNamespace(
            get_execution_options=lambda: ({"isolation_level": isolamento} if isolamento else {}),
            connection=SimpleNamespace(dbapi_connection=SimpleNamespace(autocommit=autocommit)))

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def connection(self):
        return self._conexao

    def execute(self, *args, **kwargs):
        self.executados.append(args)


@pytest.mark.parametrize("trava,comandos", TRAVAS, ids=IDS)
@pytest.mark.parametrize("isolamento,autocommit", [("AUTOCOMMIT", True), (None, True),
                                                   ("AUTOCOMMIT", False)])
def test_trava_recusa_sessao_em_autocommit(trava, comandos, isolamento, autocommit):
    db = _SessaoFalsa(isolamento=isolamento, autocommit=autocommit)
    with pytest.raises(RuntimeError, match="AUTOCOMMIT"):
        trava(db, 4343)
    assert db.executados == []


@pytest.mark.parametrize("trava,comandos", TRAVAS, ids=IDS)
def test_trava_com_transacao_executa_os_advisory_locks_na_ordem(trava, comandos):
    db = _SessaoFalsa(isolamento=None, autocommit=False)
    trava(db, 4343)
    executados = [(str(sql).split("(")[0], tuple(parametros.values()))
                  for sql, parametros in db.executados]
    assert executados == [(f"SELECT {funcao}", (ns, 4343)) for ns, funcao in comandos]


# --- PostgreSQL de verdade -----------------------------------------------------------------

def _so_no_pg(teste):
    for marca in (pytest.mark.postgres,
                  pytest.mark.skipif(not URL_PG, reason="defina TEST_DATABASE_URL_PG"),
                  pytest.mark.skipif(bool(URL_PG) and "test" not in (make_url(URL_PG).database or ""),
                                     reason="o nome do banco PG de teste precisa conter 'test'")):
        teste = marca(teste)
    return teste


@pytest.fixture(scope="module")
def motor():
    m = create_engine(URL_PG, pool_size=4, max_overflow=0)
    yield m
    m.dispose()


def _outro_consegue(motor, ns: int, chave: int) -> bool:
    with motor.connect() as c:
        ok = c.execute(text("SELECT pg_try_advisory_xact_lock(:ns, :k)"),
                       {"ns": ns, "k": chave}).scalar()
        c.rollback()
    return bool(ok)


@_so_no_pg
@pytest.mark.parametrize("trava,comandos", TRAVAS, ids=IDS)
def test_pg_sessao_com_transacao_trava_de_verdade(motor, trava, comandos):
    with Session(motor) as db:
        trava(db, 4242)
        assert all(not _outro_consegue(motor, ns, 4242) for ns, _ in comandos)
        db.rollback()
    assert all(_outro_consegue(motor, ns, 4242) for ns, _ in comandos)


@_so_no_pg
@pytest.mark.parametrize("trava,comandos", TRAVAS, ids=IDS)
def test_pg_sessao_de_leitura_em_autocommit_e_recusada(motor, trava, comandos):
    """A sessão das rotas de leitura (mesmo pool, AUTOCOMMIT): antes a trava voltava normal e
    outro processo pegava a mesma trava em seguida."""
    db = sessao_de_leitura(motor)()
    try:
        with pytest.raises(RuntimeError, match="AUTOCOMMIT"):
            trava(db, 4343)
    finally:
        db.close()
    assert all(_outro_consegue(motor, ns, 4343) for ns, _ in comandos)
    # a conexão volta ao pool sem AUTOCOMMIT: a sessão de gravação seguinte trava normalmente
    with Session(motor) as db:
        trava(db, 4344)
        assert all(not _outro_consegue(motor, ns, 4344) for ns, _ in comandos)
        db.rollback()
