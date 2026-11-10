"""O ping SÓ da conexão parada no pool (``database.instalar_ping_por_ociosidade``) e o pool LIFO.

Antes, ``pool_pre_ping=True`` mandava um ``SELECT 1`` a cada retirada do pool — em produção
(API a ~195 ms do banco) uma ida a mais em TODA requisição. Agora:

* a conexão devolvida há menos de ``DB_PING_OCIOSO_S`` (30 s) sai do pool sem ping;
* a parada há mais que isso é pingada; ping falho = a conexão (e as abertas antes dela)
  descartadas e uma NOVA entregue, sem erro para quem pediu;
* o pool é LIFO: a conexão entregue é a devolvida por último (a que dispensa o ping).

Sem driver (job ``test-backend``): um banco SQLite com ``QueuePool`` e o ping do dialeto
trocado por um contador. Com o PostgreSQL de teste (marcador ``postgres``): a conexão morta de
verdade (``pg_terminate_backend``) e a recuperação.
"""
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool, QueuePool

from app.core import database
from app.core.config import Settings

URL_PG = os.environ.get("TEST_DATABASE_URL_PG", "")


def test_engine_pg_sem_pre_ping_com_lifo_e_limite_padrao_de_30_s():
    opcoes = database.opcoes_do_engine("postgresql+psycopg://usuario@127.0.0.1:1/constela_teste")
    assert "pool_pre_ping" not in opcoes
    assert opcoes["pool_use_lifo"] is True
    assert Settings.model_fields["DB_PING_OCIOSO_S"].default == 30
    # o SQLite segue igual (sem pool de rede)
    assert database.opcoes_do_engine("sqlite://") == {
        "connect_args": {"check_same_thread": False}, "hide_parameters": True}


_SONDA_DO_ENGINE_DO_APP = """
from types import SimpleNamespace
from app.core import database as d
p = d.engine.pool
# Cada evento de conexão NOVA do pool rodado sobre uma conexão falsa (os do próprio dialeto, que
# precisam do psycopg de verdade, falham na falsa e não contam): algum desliga o prepare?
falsa = SimpleNamespace(prepare_threshold=5)
for ouvinte in list(p.dispatch.connect):
    try:
        ouvinte(falsa, SimpleNamespace(info={}))
    except Exception:
        pass
leitura = d.SessionLeitura.kw["bind"]
print(p._pre_ping, p._pool.use_lifo, len(p.dispatch.checkout) > 0, len(p.dispatch.checkin) > 0,
      falsa.prepare_threshold is None,
      leitura.get_execution_options().get("isolation_level") == "AUTOCOMMIT",
      leitura.pool is p, d.SessionLocal.kw["bind"] is d.engine)
"""


def test_o_engine_do_app_em_postgresql_ganha_o_ping_por_ociosidade_e_o_lifo():
    """O ``engine`` do próprio app, montado com uma URL PostgreSQL (num processo à parte, sem
    conectar): sem ``pool_pre_ping``, com LIFO e com o evento de retirada instalado; toda
    conexão nova sem prepared statements (``desligar_prepared_statements``) e a
    ``SessionLeitura`` das rotas de leitura em AUTOCOMMIT no MESMO pool (``sessao_de_leitura``),
    com a ``SessionLocal`` das gravações ainda no engine com transação."""
    pytest.importorskip("psycopg", reason="sem o driver psycopg (instalado só no job postgres do CI)")
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg://usuario@127.0.0.1:1/constela_teste",
           "AUTOMACAO_VERIFICAR_NO_BOOT": "false"}
    r = subprocess.run([sys.executable, "-c", _SONDA_DO_ENGINE_DO_APP],
                       cwd=str(Path(database.__file__).parents[2]),
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.split() == ["False", "True", "True", "True", "True", "True", "True", "True"]


class _Pings:
    """Troca o ``do_ping`` do dialeto por um contador (que pode falhar)."""

    def __init__(self, motor, monkeypatch):
        self.n, self.falhar = 0, False
        monkeypatch.setattr(motor.dialect, "do_ping", self._ping)

    def _ping(self, dbapi_connection):
        self.n += 1
        if self.falhar:
            raise sqlite3.OperationalError("conexão encerrada (falsa)")
        return True


def _motor(limite_s: float, monkeypatch, *, tamanho: int = 1):
    motor = create_engine("sqlite://", poolclass=QueuePool, pool_size=tamanho, max_overflow=0,
                          pool_use_lifo=True)
    database.instalar_ping_por_ociosidade(motor, limite_s=limite_s)
    return motor, _Pings(motor, monkeypatch)


def _dbapi(conexao):
    return conexao.connection.dbapi_connection


def test_conexao_devolvida_ha_pouco_sai_sem_ping(monkeypatch):
    motor, pings = _motor(60, monkeypatch)
    for _ in range(5):
        with motor.connect() as c:
            assert c.execute(text("SELECT 1")).scalar() == 1
    assert pings.n == 0                          # a nova e as quentes: nenhuma ida a mais
    motor.dispose()


def test_conexao_parada_alem_do_limite_e_pingada_uma_vez(monkeypatch):
    motor, pings = _motor(0.05, monkeypatch)
    with motor.connect() as c:
        c.execute(text("SELECT 1"))
    time.sleep(0.1)
    with motor.connect() as c:                   # parada 0,1 s > 0,05 s: ping
        c.execute(text("SELECT 1"))
    assert pings.n == 1
    with motor.connect() as c:                   # acabou de voltar: sem ping
        c.execute(text("SELECT 1"))
    assert pings.n == 1
    motor.dispose()


def test_limite_zero_pinga_toda_retirada_como_o_pre_ping(monkeypatch):
    motor, pings = _motor(0, monkeypatch)
    with motor.connect():
        pass                                     # a NOVA também (como o pre_ping, menos a 1ª)
    for _ in range(3):
        with motor.connect():
            pass
    assert pings.n >= 3
    motor.dispose()


def test_ping_falho_entrega_uma_conexao_nova_sem_erro(monkeypatch):
    motor, pings = _motor(0.05, monkeypatch)
    with motor.connect() as c:
        velha = _dbapi(c)
    time.sleep(0.1)
    pings.falhar = True
    with motor.connect() as c:                   # ping falho: descartada; a nova não é pingada
        nova = _dbapi(c)
        assert c.execute(text("SELECT 1")).scalar() == 1
    assert pings.n == 1
    assert nova is not velha
    motor.dispose()


def test_pool_lifo_entrega_a_devolvida_por_ultimo(monkeypatch):
    motor, pings = _motor(60, monkeypatch, tamanho=2)
    a, b = motor.connect(), motor.connect()
    dbapi_a, dbapi_b = _dbapi(a), _dbapi(b)
    a.close()
    b.close()                                    # b é a devolvida por último
    with motor.connect() as c:
        assert _dbapi(c) is dbapi_b
    with motor.connect() as c:                   # e de novo a mesma (a quente), não a "a"
        assert _dbapi(c) is dbapi_b and _dbapi(c) is not dbapi_a
    assert pings.n == 0
    motor.dispose()


# --- PostgreSQL de verdade -----------------------------------------------------------------

def _so_no_pg(teste):
    for marca in (pytest.mark.postgres,
                  pytest.mark.skipif(not URL_PG, reason="defina TEST_DATABASE_URL_PG"),
                  pytest.mark.skipif(bool(URL_PG) and "test" not in (make_url(URL_PG).database or ""),
                                     reason="o nome do banco PG de teste precisa conter 'test'")):
        teste = marca(teste)
    return teste


def _motor_pg(limite_s: float):
    opcoes = {**database.opcoes_do_engine(URL_PG), "pool_size": 1, "max_overflow": 0}
    motor = create_engine(URL_PG, **opcoes)
    database.instalar_ping_por_ociosidade(motor, limite_s=limite_s)
    return motor


def _pid(motor) -> int:
    with motor.connect() as c:
        return c.execute(text("SELECT pg_backend_pid()")).scalar()


def _derrubar(pid: int) -> None:
    admin = create_engine(URL_PG, poolclass=NullPool)
    with admin.connect() as c:
        assert c.execute(text("SELECT pg_terminate_backend(:p)"), {"p": pid}).scalar() is True
    admin.dispose()
    time.sleep(0.3)                              # o servidor fecha o socket


@_so_no_pg
def test_pg_conexao_derrubada_e_parada_reconecta_sem_erro():
    motor = _motor_pg(limite_s=0.1)
    velho = _pid(motor)
    _derrubar(velho)                             # o banco encerra a conexão parada no pool
    novo = _pid(motor)                           # parada > 0,1 s: ping falha, conexão nova
    assert novo != velho
    assert _pid(motor) == novo                   # e a nova fica no pool
    motor.dispose()


@_so_no_pg
def test_pg_conexao_derrubada_dentro_da_janela_falha_uma_vez_e_a_seguinte_reconecta():
    """O risco aceito: a conexão morta usada há menos que o limite dá erro em UMA
    requisição; a seguinte já sai com conexão nova."""
    motor = _motor_pg(limite_s=60)
    velho = _pid(motor)
    _derrubar(velho)
    with pytest.raises(DBAPIError) as erro:
        _pid(motor)
    assert erro.value.connection_invalidated is True
    novo = _pid(motor)
    assert novo != velho
    motor.dispose()


@_so_no_pg
def test_pg_conexao_quente_sem_ida_a_mais():
    """Com o PostgreSQL de verdade: a conexão quente não é pingada (o ping do dialeto é
    contado); a parada, uma vez."""
    motor = _motor_pg(limite_s=0.2)
    chamadas = []
    original = motor.dialect.do_ping
    motor.dialect.do_ping = lambda conexao: chamadas.append(1) or original(conexao)
    for _ in range(4):
        _pid(motor)
    assert chamadas == []
    time.sleep(0.3)
    _pid(motor)
    assert chamadas == [1]
    motor.dispose()
