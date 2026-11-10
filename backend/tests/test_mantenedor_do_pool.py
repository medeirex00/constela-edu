"""O mantenedor do pool (``app/core/mantenedor_do_pool.py``): N conexões prontas no PostgreSQL.

Antes, quem pagava a conexão NOVA (~0,8 s com o banco a 195 ms), o ping da conexão parada
(``DB_PING_OCIOSO_S``) e a reabertura da conexão velha (``DB_POOL_RECYCLE``) era a requisição
do usuário: a primeira visita da Secretaria depois de um reinício, ou depois de minutos sem
ninguém. Agora uma thread por processo, ligada no startup e parada no shutdown, retira ao
MESMO TEMPO N conexões a cada ciclo, roda ``SELECT 1`` em cada e devolve.

Sem driver (job ``test-backend``): um SQLite com ``QueuePool`` (o mantenedor não olha o
dialeto; quem olha é ``criar_para``). Com o PostgreSQL de teste (marcador ``postgres``): as
conexões prontas, o ping evitado, a reciclagem antecipada e a conexão derrubada de verdade.
"""
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool, QueuePool

from app.core import database, mantenedor_do_pool as mp
from app.core.config import Settings
from app.main import app

URL_PG = os.environ.get("TEST_DATABASE_URL_PG", "")


# --- apoio ------------------------------------------------------------------------------

class _Registro:
    """Conta as conexões ABERTAS e os pings do dialeto; lembra a última conexão de cada retirada."""

    def __init__(self, motor, monkeypatch=None):
        self._trava = threading.Lock()
        self.abertas = 0
        self.pings = 0
        event.listen(motor, "connect", self._abriu)
        if monkeypatch is not None:
            original = motor.dialect.do_ping
            monkeypatch.setattr(motor.dialect, "do_ping", lambda c: self._pingou() or original(c))

    def _abriu(self, *_a):
        with self._trava:
            self.abertas += 1

    def _pingou(self):
        with self._trava:
            self.pings += 1


def _motor(tamanho=8, *, recycle=-1, criador=None, limite_ping=None):
    opcoes = dict(poolclass=QueuePool, pool_size=tamanho, max_overflow=0, pool_use_lifo=True,
                  pool_recycle=recycle)
    if criador is None:
        opcoes["connect_args"] = {"check_same_thread": False}
    else:
        opcoes["creator"] = criador
    motor = create_engine("sqlite://", **opcoes)
    if limite_ping is not None:
        database.instalar_ping_por_ociosidade(motor, limite_s=limite_ping)
    mp.marcar_abertura(motor)
    return motor


def _rajada(motor, n):
    """N requisições ao mesmo tempo: retira N conexões, todas seguras juntas; devolve as
    conexões do DB-API que cada uma recebeu."""
    with ExitStack() as pilha:
        conexoes = [pilha.enter_context(motor.connect()) for _ in range(n)]
        for c in conexoes:
            c.execute(text("SELECT 1"))
        return [c.connection.dbapi_connection for c in conexoes]


def _config(**k):
    base = dict(DB_POOL_AQUECIDO_S=20, DB_POOL_AQUECIDO_CONEXOES=8, DB_PING_OCIOSO_S=30,
                DB_POOL_RECYCLE=1800)
    base.update(k)
    return SimpleNamespace(**base)


def _como_postgresql(motor, monkeypatch):
    monkeypatch.setattr(motor.dialect, "name", "postgresql")
    return motor


class _Linhas(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.linhas = []

    def emit(self, registro):
        self.linhas.append((registro.levelno, registro.getMessage()))


@pytest.fixture
def log_constela():
    lg = logging.getLogger("constela")
    h = _Linhas()
    nivel = lg.level
    lg.addHandler(h)
    lg.setLevel(logging.DEBUG)
    yield h
    lg.removeHandler(h)
    lg.setLevel(nivel)


@pytest.fixture(autouse=True)
def _sem_mantenedor_sobrando():
    yield
    mp.parar()


# --- configuração e decisão de ligar ------------------------------------------------------

def test_padroes_seguros_intervalo_abaixo_do_ping_e_n_dentro_do_pool():
    campos = Settings.model_fields
    assert campos["DB_POOL_AQUECIDO_S"].default == 20
    assert campos["DB_POOL_AQUECIDO_CONEXOES"].default == 8
    assert campos["DB_POOL_AQUECIDO_S"].default < campos["DB_PING_OCIOSO_S"].default
    assert campos["DB_POOL_AQUECIDO_CONEXOES"].default <= campos["DB_POOL_SIZE"].default


def test_variaveis_lidas_do_ambiente(monkeypatch):
    monkeypatch.setenv("DB_POOL_AQUECIDO_S", "0")
    monkeypatch.setenv("DB_POOL_AQUECIDO_CONEXOES", "3")
    s = Settings()
    assert s.DB_POOL_AQUECIDO_S == 0 and s.DB_POOL_AQUECIDO_CONEXOES == 3


def test_liga_so_no_postgresql_e_desliga_com_zero(monkeypatch):
    motor = _motor(10)
    assert mp.criar_para(motor, _config()) is None              # SQLite de verdade: não liga
    _como_postgresql(motor, monkeypatch)
    m = mp.criar_para(motor, _config())
    assert isinstance(m, mp.MantenedorDoPool)
    assert (m.conexoes, m.intervalo_s, m.limite_da_reciclagem_s) == (8, 20.0, 1760.0)
    assert (m.calmaria_s, m.espera_maxima_s) == (2.0, 5.0)     # 20 + 5 = 25 s < 30 s do ping
    assert mp.criar_para(motor, _config(DB_PING_OCIOSO_S=22)).espera_maxima_s == 0
    for desliga in (dict(DB_POOL_AQUECIDO_S=0), dict(DB_POOL_AQUECIDO_CONEXOES=0),
                    dict(DB_POOL_AQUECIDO_S=-1), dict(DB_POOL_AQUECIDO_CONEXOES=-2)):
        assert mp.criar_para(motor, _config(**desliga)) is None, desliga
    sem_fila = create_engine("sqlite://", poolclass=NullPool)
    _como_postgresql(sem_fila, monkeypatch)
    assert mp.criar_para(sem_fila, _config()) is None           # sem QueuePool: nada a manter
    motor.dispose()


def test_n_limitado_ao_pool_size_e_reciclagem_desligada(monkeypatch, log_constela):
    motor = _como_postgresql(_motor(4), monkeypatch)
    m = mp.criar_para(motor, _config(DB_POOL_AQUECIDO_CONEXOES=50, DB_POOL_RECYCLE=-1))
    assert m.conexoes == 4 and m.limite_da_reciclagem_s is None
    assert any("DB_POOL_SIZE=4" in t for _, t in log_constela.linhas)
    curta = mp.criar_para(motor, _config(DB_POOL_RECYCLE=30))
    assert curta.limite_da_reciclagem_s == 15                   # nunca antes da metade
    motor.dispose()


def test_o_engine_do_app_no_sqlite_nao_liga():
    """Os testes comuns (e o desenvolvimento) usam SQLite: o startup não sobe thread nenhuma."""
    assert database.is_sqlite
    assert mp.iniciar(database.engine) is False
    assert mp.ativo() is False


def test_startup_liga_e_shutdown_para(monkeypatch):
    chamadas = []
    monkeypatch.setattr(mp, "iniciar", lambda motor: chamadas.append(("iniciar", motor)))
    monkeypatch.setattr(mp, "parar", lambda: chamadas.append(("parar", None)))
    with TestClient(app):
        assert chamadas == [("iniciar", database.engine)]
    assert chamadas == [("iniciar", database.engine), ("parar", None)]


def test_iniciar_e_parar_do_processo_idempotentes_e_sem_levantar(monkeypatch, log_constela):
    motor = _como_postgresql(_motor(4), monkeypatch)
    assert mp.iniciar(motor, _config(DB_POOL_AQUECIDO_S=60, DB_POOL_AQUECIDO_CONEXOES=2))
    primeiro = mp._atual
    assert mp.ativo() and primeiro._thread.daemon
    assert mp.iniciar(motor, _config()) is True and mp._atual is primeiro    # já ligado
    mp.parar()
    assert not mp.ativo() and not primeiro.vivo()
    mp.parar()                                                   # sem mantenedor: nada

    def quebra(*_a, **_k):
        raise RuntimeError("falso")
    monkeypatch.setattr(mp, "criar_para", quebra)
    assert mp.iniciar(motor, _config()) is False                # o boot segue sem ele
    assert any("não iniciou (RuntimeError)" in t for _, t in log_constela.linhas)
    assert motor.pool.checkedout() == 0
    motor.dispose()


# --- o ciclo ------------------------------------------------------------------------------

def test_ciclo_retira_n_conexoes_distintas_ao_mesmo_tempo_e_devolve_todas():
    motor = _motor(8)
    reg = _Registro(motor)
    m = mp.MantenedorDoPool(motor, intervalo_s=60, conexoes=5)
    r = m.ciclo()
    assert (r.pedidas, r.prontas, r.falhas) == (5, 5, [])
    assert reg.abertas == 5                  # 5 DISTINTAS (uma de cada vez seria sempre a mesma)
    assert motor.pool.checkedout() == 0 and motor.pool.checkedin() == 5
    r = m.ciclo()                            # o ciclo seguinte reusa as mesmas 5
    assert (r.prontas, reg.abertas) == (5, 5)
    assert motor.pool.checkedout() == 0
    motor.dispose()


def test_ciclo_desconta_as_conexoes_que_ja_estao_com_requisicoes():
    motor = _motor(8)
    reg = _Registro(motor)
    m = mp.MantenedorDoPool(motor, intervalo_s=60, conexoes=5)
    with ExitStack() as pilha:
        for _ in range(3):
            pilha.enter_context(motor.connect())
        r = m.ciclo()
        assert (r.pedidas, r.prontas) == (2, 2)
        assert reg.abertas == 5 and motor.pool.checkedout() == 3     # não abre além de N
        for _ in range(2):
            pilha.enter_context(motor.connect())
        assert m.ciclo().pedidas == 0                                # N em uso: nada a fazer
    assert motor.pool.checkedout() == 0
    motor.dispose()


def test_depois_do_ciclo_a_rajada_de_n_requisicoes_nao_abre_conexao_nem_pinga(monkeypatch):
    motor = _motor(8, limite_ping=1.0)
    reg = _Registro(motor, monkeypatch)
    m = mp.MantenedorDoPool(motor, intervalo_s=0.6, conexoes=5)
    m.ciclo()                                # pré-aquece: as 5 abertas pelo mantenedor
    time.sleep(0.6)
    m.ciclo()
    time.sleep(0.6)                          # 1,2 s desde o 1º ciclo, 0,6 s desde o 2º
    abertas, reg.pings = reg.abertas, 0
    assert len(set(map(id, _rajada(motor, 5)))) == 5
    assert (reg.abertas - abertas, reg.pings) == (0, 0)
    time.sleep(1.1)                          # controle: sem ciclo, a rajada paga os pings
    _rajada(motor, 5)
    assert reg.pings == 5
    motor.dispose()


def test_reciclagem_antecipada_acontece_no_mantenedor_e_nao_na_requisicao():
    motor = _motor(8, recycle=2)
    reg = _Registro(motor)
    m = mp.MantenedorDoPool(motor, intervalo_s=0.25, conexoes=3, reciclagem_s=2)
    assert m.limite_da_reciclagem_s == 1.5
    m.ciclo()
    velhas = _rajada(motor, 3)               # a lista as mantém vivas: o id() não se repete
    time.sleep(1.6)                          # perto dos 2 s do pool_recycle
    r = m.ciclo()
    assert (r.renovadas, r.prontas, reg.abertas) == (3, 3, 6)
    time.sleep(0.5)                          # as velhas teriam 2,1 s: o pool as reabriria
    abertas = reg.abertas
    novas = _rajada(motor, 3)
    assert reg.abertas == abertas            # a requisição não reabriu nada
    assert not set(map(id, novas)) & set(map(id, velhas))
    assert motor.pool.checkedout() == 0
    motor.dispose()


class _ConexaoQueMorre:
    """Conexão SQLite que "morre do lado do servidor": o cliente só descobre na consulta
    seguinte (como o PostgreSQL reiniciado), com o erro que o dialeto lê como desconexão."""

    def __init__(self):
        object.__setattr__(self, "_real", sqlite3.connect(":memory:", check_same_thread=False))
        object.__setattr__(self, "morta", False)

    def __getattr__(self, nome):
        return getattr(self._real, nome)

    def __setattr__(self, nome, valor):
        if nome == "morta":
            object.__setattr__(self, nome, valor)
        else:
            setattr(self._real, nome, valor)

    def cursor(self, *a):
        if self.morta:
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")
        return self._real.cursor(*a)


def test_conexao_morta_e_trocada_no_proprio_ciclo():
    criadas = []

    def criador():
        criadas.append(_ConexaoQueMorre())
        return criadas[-1]

    motor = _motor(8, criador=criador)
    reg = _Registro(motor)
    m = mp.MantenedorDoPool(motor, intervalo_s=60, conexoes=3)
    m.ciclo()
    assert len(criadas) == 3
    for conexao in criadas:
        conexao.morta = True                 # o banco "reiniciou": as 3 do pool morreram
    r = m.ciclo()
    # A 1ª desconexão vista invalida o pool inteiro: quem a viu reconecta no SELECT 1, e as
    # outras retiradas do ciclo já saem reabertas do pool. As 3 são trocadas pelo mantenedor.
    assert (r.prontas, r.falhas) == (3, []) and r.reconectadas >= 1
    assert reg.abertas == 6
    _rajada(motor, 3)                        # a requisição pega conexões vivas, sem erro
    assert reg.abertas == 6                  # e não abre nenhuma
    motor.dispose()


def test_erro_do_banco_nao_propaga_nao_vaza_conexao_e_o_ciclo_seguinte_tenta_de_novo():
    fora = {"sim": True}

    def criador():
        if fora["sim"]:
            raise sqlite3.OperationalError("banco fora (falso)")
        return sqlite3.connect(":memory:", check_same_thread=False)

    motor = _motor(4, criador=criador)
    m = mp.MantenedorDoPool(motor, intervalo_s=60, conexoes=3)
    r = m.ciclo()                            # não levanta
    assert (r.pedidas, r.prontas) == (3, 0)
    assert r.falhas == ["OperationalError"] * 3
    assert motor.pool.checkedout() == 0
    fora["sim"] = False
    r = m.ciclo()
    assert (r.prontas, r.falhas) == (3, [])
    assert motor.pool.checkedout() == 0 and motor.pool.checkedin() == 3
    motor.dispose()


def test_thread_com_banco_fora_segue_viva_e_avisa_uma_vez_por_janela(log_constela):
    def criador():
        raise sqlite3.OperationalError("banco fora (falso)")

    motor = _motor(4, criador=criador)
    m = mp.MantenedorDoPool(motor, intervalo_s=0.05, conexoes=2)
    m.iniciar()
    time.sleep(0.6)                          # ~10 ciclos falhando
    assert m.vivo()
    avisos = [t for nivel, t in log_constela.linhas if nivel == logging.WARNING]
    assert len(avisos) == 1, avisos
    assert "2 de 2 conexão(ões) sem resposta (OperationalError)" in avisos[0]
    assert "banco fora" not in avisos[0]     # só o tipo: a mensagem do driver fica fora do log
    m.parar()
    assert not m.vivo() and motor.pool.checkedout() == 0
    motor.dispose()


def test_aviso_com_limite_de_frequencia_e_aviso_da_volta(log_constela):
    agora = [0.0]
    aviso = mp._AvisoComPausa(janela_s=300, relogio=lambda: agora[0])
    assert aviso.falhou("x") is True
    for t in (10, 100, 299):
        agora[0] = t
        assert aviso.falhou("x") is False
    agora[0] = 301
    assert aviso.falhou("x") is True
    aviso.voltou()
    aviso.voltou()                           # só avisa a volta uma vez
    linhas = [(n, t) for n, t in log_constela.linhas if "Mantenedor do pool" in t]
    assert [n for n, _ in linhas] == [logging.WARNING, logging.WARNING, logging.INFO]
    assert "3 falha(s) a mais" in linhas[1][1]


def test_primeiro_ciclo_e_imediato_e_parar_e_prompto():
    motor = _motor(8)
    m = mp.MantenedorDoPool(motor, intervalo_s=60, conexoes=4)
    m.iniciar()
    limite = time.monotonic() + 5
    while motor.pool.checkedin() < 4 and time.monotonic() < limite:
        time.sleep(0.02)
    assert motor.pool.checkedin() == 4       # o intervalo é 60 s: só o ciclo do boot explica
    assert m._thread.daemon
    t0 = time.monotonic()
    m.parar()
    assert not m.vivo() and time.monotonic() - t0 < 2
    assert motor.pool.checkedout() == 0
    motor.dispose()


def test_ciclo_espera_a_calmaria_sem_competir_com_a_pagina_e_tem_teto():
    """Com uma requisição em andamento o ciclo espera (não segura as conexões paradas bem
    quando a camada seguinte da página chega); passado o teto, roda assim mesmo."""
    motor = _motor(8)
    do_mantenedor = []
    event.listen(motor, "checkout", lambda *_a: do_mantenedor.append(time.monotonic())
                 if threading.current_thread().name.startswith("pool-aquecido") else None)
    m = mp.MantenedorDoPool(motor, intervalo_s=0.2, conexoes=3, calmaria_s=0.3,
                            espera_maxima_s=1.5)
    m.iniciar()
    limite = time.monotonic() + 5
    while motor.pool.checkedin() < 3 and time.monotonic() < limite:
        time.sleep(0.02)
    assert motor.pool.checkedin() == 3       # o ciclo do boot não espera calmaria
    with motor.connect():                    # uma requisição em andamento
        do_mantenedor.clear()
        t0 = time.monotonic()
        time.sleep(1.2)
        assert do_mantenedor == []           # intervalo de 0,2 s, mas o ciclo esperou
        while not do_mantenedor and time.monotonic() - t0 < 5:
            time.sleep(0.02)
        assert do_mantenedor                 # teto de 0,2 + 1,5 s: rodou com a requisição
        assert do_mantenedor[0] - t0 < 3
    m.parar()
    assert motor.pool.checkedout() == 0
    motor.dispose()


def test_devolucao_recente_de_requisicao_adia_o_ciclo_e_a_do_mantenedor_nao():
    motor = _motor(8)
    m = mp.MantenedorDoPool(motor, intervalo_s=60, conexoes=2, calmaria_s=0.5,
                            espera_maxima_s=3)
    m.iniciar()                              # o ciclo do boot devolve 2 conexões...
    limite = time.monotonic() + 5
    while motor.pool.checkedin() < 2 and time.monotonic() < limite:
        time.sleep(0.02)
    m.parar()
    m._parar.clear()                         # a espera roda aqui, sem a thread
    t0 = time.monotonic()
    m._esperar_calmaria()                    # ...que não contam como uso: sem espera
    assert time.monotonic() - t0 < 0.2
    with motor.connect():
        pass                                 # devolução de uma requisição agora
    t0 = time.monotonic()
    m._esperar_calmaria()
    assert 0.4 < time.monotonic() - t0 < 2
    motor.dispose()


# --- o engine do app com PostgreSQL (processo à parte, sem conectar) ----------------------

_SONDA_DO_ENGINE_DO_APP = """
from types import SimpleNamespace
from app.core import database as d, mantenedor_do_pool as m
registro = SimpleNamespace(info={})
for ouvinte in list(d.engine.pool.dispatch.connect):
    try:
        ouvinte(SimpleNamespace(prepare_threshold=5), registro)
    except Exception:
        pass
mant = m.criar_para(d.engine)
print(m._ABERTA_EM in registro.info, type(mant).__name__, mant.conexoes, mant.intervalo_s,
      mant.limite_da_reciclagem_s)
"""


@pytest.mark.postgres
def test_o_engine_do_app_em_postgresql_marca_a_abertura_e_ganha_o_mantenedor():
    pytest.importorskip("psycopg", reason="sem o driver psycopg (instalado só no job postgres do CI)")
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg://usuario@127.0.0.1:1/constela_teste",
           "AUTOMACAO_VERIFICAR_NO_BOOT": "false"}
    for nome in ("DB_POOL_AQUECIDO_S", "DB_POOL_AQUECIDO_CONEXOES", "DB_POOL_RECYCLE",
                 "DB_POOL_SIZE", "DB_PING_OCIOSO_S"):
        env.pop(nome, None)
    r = subprocess.run([sys.executable, "-c", _SONDA_DO_ENGINE_DO_APP],
                       cwd=str(Path(database.__file__).parents[2]),
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.split() == ["True", "MantenedorDoPool", "8", "20.0", "1760.0"]


# --- PostgreSQL de verdade -----------------------------------------------------------------

def _so_no_pg(teste):
    for marca in (pytest.mark.postgres,
                  pytest.mark.skipif(not URL_PG, reason="defina TEST_DATABASE_URL_PG"),
                  pytest.mark.skipif(bool(URL_PG) and "test" not in (make_url(URL_PG).database or ""),
                                     reason="o nome do banco PG de teste precisa conter 'test'")):
        teste = marca(teste)
    return teste


def _motor_pg(tamanho, *, recycle=1800, limite_ping=30.0):
    opcoes = {**database.opcoes_do_engine(URL_PG), "pool_size": tamanho, "max_overflow": 0,
              "pool_recycle": recycle}
    motor = create_engine(URL_PG, **opcoes)
    database.instalar_ping_por_ociosidade(motor, limite_s=limite_ping)
    database.desligar_prepared_statements(motor)
    mp.marcar_abertura(motor)
    return motor


def _pids_da_rajada(motor, n):
    with ExitStack() as pilha:
        conexoes = [pilha.enter_context(motor.connect()) for _ in range(n)]
        return {c.execute(text("SELECT pg_backend_pid()")).scalar() for c in conexoes}


@_so_no_pg
def test_pg_depois_do_ciclo_o_pool_tem_n_conexoes_prontas(monkeypatch):
    motor = _motor_pg(6)
    reg = _Registro(motor, monkeypatch)
    m = mp.MantenedorDoPool(motor, intervalo_s=20, conexoes=4)
    r = m.ciclo()
    assert (r.pedidas, r.prontas, r.falhas) == (4, 4, [])
    assert motor.pool.checkedout() == 0 and motor.pool.checkedin() == 4
    abertas = reg.abertas
    assert abertas == 4
    pids = _pids_da_rajada(motor, 4)         # 4 requisições ao mesmo tempo
    assert len(pids) == 4
    assert (reg.abertas, reg.pings) == (abertas, 0)
    motor.dispose()


@_so_no_pg
def test_pg_conexao_que_ficaria_ociosa_e_renovada_e_o_checkout_seguinte_nao_pinga(monkeypatch):
    motor = _motor_pg(4, limite_ping=1.5)
    reg = _Registro(motor, monkeypatch)
    m = mp.MantenedorDoPool(motor, intervalo_s=1.0, conexoes=2)
    m.ciclo()
    time.sleep(1.0)
    m.ciclo()                                # renova antes do limite de 1,5 s
    time.sleep(1.0)                          # 2,0 s desde o 1º ciclo, 1,0 s desde o 2º
    abertas, reg.pings = reg.abertas, 0
    assert len(_pids_da_rajada(motor, 2)) == 2
    assert (reg.abertas, reg.pings) == (abertas, 0)
    time.sleep(1.6)                          # controle: parada além do limite, sem ciclo
    _pids_da_rajada(motor, 2)
    assert reg.pings == 2
    motor.dispose()


@_so_no_pg
def test_pg_reciclagem_antecipada_acontece_no_mantenedor(monkeypatch):
    motor = _motor_pg(4, recycle=3)
    reg = _Registro(motor, monkeypatch)
    m = mp.MantenedorDoPool(motor, intervalo_s=0.5, conexoes=2, reciclagem_s=3)
    assert m.limite_da_reciclagem_s == 2
    m.ciclo()
    velhos = _pids_da_rajada(motor, 2)
    time.sleep(2.1)
    r = m.ciclo()                            # o mantenedor reabre as duas
    assert (r.renovadas, r.prontas, r.falhas) == (2, 2, [])
    time.sleep(1.0)                          # as velhas teriam 3,1 s: o pool as reabriria
    abertas = reg.abertas
    novos = _pids_da_rajada(motor, 2)
    assert reg.abertas == abertas            # a requisição não abriu conexão
    assert not novos & velhos
    motor.dispose()


@_so_no_pg
def test_pg_conexoes_derrubadas_sao_trocadas_no_ciclo_e_a_requisicao_nao_erra(monkeypatch):
    motor = _motor_pg(4, limite_ping=60)    # dentro da janela: sem ping, a requisição erraria
    reg = _Registro(motor, monkeypatch)
    m = mp.MantenedorDoPool(motor, intervalo_s=20, conexoes=3)
    m.ciclo()
    velhos = _pids_da_rajada(motor, 3)
    admin = create_engine(URL_PG, poolclass=NullPool)
    with admin.connect() as c:
        for pid in velhos:
            assert c.execute(text("SELECT pg_terminate_backend(:p)"), {"p": pid}).scalar()
    admin.dispose()
    time.sleep(0.3)                          # o servidor fecha os sockets
    abertas = reg.abertas
    r = m.ciclo()
    assert (r.prontas, r.falhas) == (3, []) and r.reconectadas >= 1
    assert reg.abertas == abertas + 3        # as 3 reabertas pelo mantenedor
    novos = _pids_da_rajada(motor, 3)        # sem DBAPIError na requisição
    assert reg.abertas == abertas + 3 and not novos & velhos
    motor.dispose()
