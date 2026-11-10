"""Engine do PostgreSQL com PRAZO para abrir conexão (``connect_timeout``) — lacuna L11
da matriz de prontidão v2.

Antes: ``opcoes_do_engine`` dava pool, ``pool_pre_ping`` e ``hide_parameters`` ao
PostgreSQL, mas nenhum ``connect_timeout``. Uma conexão nova com um banco que aceita o
TCP e não responde (ou com host fora do ar) ficava presa no handshake pelo padrão do
driver (130 s no psycopg 3.2 da imagem), com o worker junto; só o coletor de métricas
tinha prazo próprio. Agora o driver (psycopg) recebe ``connect_timeout`` de
``DB_CONNECT_TIMEOUT`` (padrão 10 s), sem tocar o SQLite.

Sem rede: o banco "que não responde" é um socket em 127.0.0.1 que escuta e nunca fala; o
PostgreSQL de verdade é o LOCAL de teste (``TEST_DATABASE_URL_PG``, marcador
``postgres``).

O driver (psycopg) NÃO está no ``requirements.txt``: entra só no Dockerfile e nos jobs
``test-backend-postgres``/``migracoes-postgres`` do CI. O job ``test-backend`` roda a suíte
inteira sem ele, e o ``create_engine("postgresql+psycopg://...")`` faz ``import psycopg``.
Por isso os testes que criam um engine psycopg (``PRECISAM_DO_DRIVER``) PULAM sem o driver
(``_exigir_driver``) e levam o marcador ``postgres``, para rodar no job que o instala; o que
não precisa do driver (as opções do engine, o SQLite) roda sem marcador nos dois.

``PGCONNECT_TIMEOUT`` (revisão pós-snapshot do d4caac4): o psycopg só lê essa variável de
ambiente da libpq quando o ``connect_timeout`` NÃO vem nos parâmetros; o ``connect_args`` do
app a escondia (o operador pedia 2 s e o worker esperava 10). Agora, definida e não vazia, ela
prevalece, como o ``?connect_timeout=`` da URL. A fixture automática abaixo tira a variável
do ambiente de cada teste, para os que conferem o padrão do app não dependerem da máquina.
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.core import database
from app.core.config import PROJECT_ROOT, Settings, settings

URL_PG ="postgresql+psycopg://usuario@127.0.0.1:1/constela_teste"

# Os testes que criam um engine psycopg: pulam sem o driver e levam o marcador ``postgres``.
PRECISAM_DO_DRIVER = frozenset({
    "test_o_driver_recebe_o_connect_timeout",
    "test_prazo_configuravel_e_zero_desliga",
    "test_connect_timeout_da_url_prevalece",
    "test_banco_mudo_falha_no_prazo_em_vez_de_pendurar",
    "test_controle_sem_prazo_o_mesmo_banco_mudo_pendura",
    "test_banco_mudo_respeita_o_pgconnect_timeout_do_ambiente",
})


@pytest.fixture(autouse=True)
def _sem_pgconnect_timeout_do_ambiente(monkeypatch):
    """Cada teste começa sem ``PGCONNECT_TIMEOUT`` (quem a quer, define)."""
    monkeypatch.delenv("PGCONNECT_TIMEOUT", raising=False)


def _exigir_driver():
    """Pula o teste quando o psycopg não está instalado (job ``test-backend`` do CI)."""
    return pytest.importorskip(
        "psycopg", reason="sem o driver psycopg (instalado só no job postgres do CI)")


def _cparams_entregues_ao_driver(url: str) -> dict:
    """Os parâmetros que o SQLAlchemy entrega ao ``psycopg.connect`` (URL + connect_args),
    capturados no evento ``do_connect`` e interrompidos ANTES de abrir qualquer socket."""
    _exigir_driver()
    motor = create_engine(url, **database.opcoes_do_engine(url))
    capturado: dict = {}

    @event.listens_for(motor, "do_connect")
    def _capturar(_dialeto, _registro, _cargs, cparams):
        capturado.update(cparams)
        raise RuntimeError("parado antes de conectar")

    with pytest.raises(RuntimeError, match="parado antes de conectar"):
        motor.connect()
    motor.dispose()
    return capturado


def test_padrao_e_10_segundos_e_o_engine_pg_o_recebe():
    assert Settings.model_fields["DB_CONNECT_TIMEOUT"].default == 10
    opcoes = database.opcoes_do_engine(URL_PG)
    assert opcoes["connect_args"] == {"connect_timeout": settings.DB_CONNECT_TIMEOUT}
    # o resto do ramo PostgreSQL (o ping da conexão parada e o pool LIFO estão em
    # test_database_ping_ocioso)
    assert opcoes["hide_parameters"] is True
    assert opcoes["pool_size"] == settings.DB_POOL_SIZE
    assert opcoes["max_overflow"] == settings.DB_MAX_OVERFLOW
    assert opcoes["pool_recycle"] == settings.DB_POOL_RECYCLE


def test_opcoes_sem_driver_prazo_configuravel_zero_desliga_e_url_prevalece(monkeypatch):
    """A decisão do ``connect_args`` não depende do driver: roda também no job sem
    psycopg (os testes abaixo conferem o que de fato chega ao ``psycopg.connect``)."""
    for prazo in (7, 3):
        monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", prazo)
        for url in (URL_PG, "postgresql://usuario@127.0.0.1:1/constela_teste"):
            assert database.opcoes_do_engine(url)["connect_args"] == {"connect_timeout": prazo}
        assert database.opcoes_do_engine(URL_PG + "?connect_timeout=4").get(
            "connect_args") is None
    for sem_prazo in (0, -5):
        monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", sem_prazo)
        assert "connect_args" not in database.opcoes_do_engine(URL_PG)
        assert database.argumentos_de_conexao_pg(URL_PG) == {}


@pytest.mark.postgres
def test_o_driver_recebe_o_connect_timeout(monkeypatch):
    monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", 7)
    assert _cparams_entregues_ao_driver(URL_PG)["connect_timeout"] == 7
    # A URL sem o driver explícito também é PostgreSQL (a opção vale pelo dialeto, não
    # pelo texto "+psycopg"); aqui só a opção, porque o driver padrão dela não está
    # instalado.
    url = "postgresql://usuario@127.0.0.1:1/constela_teste"
    assert database.opcoes_do_engine(url)["connect_args"] == {"connect_timeout": 7}


@pytest.mark.postgres
def test_prazo_configuravel_e_zero_desliga(monkeypatch):
    monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", 3)
    assert database.opcoes_do_engine(URL_PG)["connect_args"] == {"connect_timeout": 3}
    for sem_prazo in (0, -5):
        monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", sem_prazo)
        assert "connect_args" not in database.opcoes_do_engine(URL_PG)
        assert "connect_timeout" not in _cparams_entregues_ao_driver(URL_PG)


def test_variavel_de_ambiente_e_lida(monkeypatch):
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "4")
    assert Settings().DB_CONNECT_TIMEOUT == 4


def test_pgconnect_timeout_do_ambiente_prevalece_sobre_o_padrao_do_app(monkeypatch):
    """Sem o driver (roda no job ``test-backend``): com ``PGCONNECT_TIMEOUT`` definida, o
    engine não manda ``connect_args`` — senão o parâmetro explícito esconderia a variável
    (o psycopg só a lê quando o ``connect_timeout`` não vem). Vazia ou só espaços não é
    escolha do operador (o psycopg recusaria ``""`` como prazo): o padrão do app vale."""
    monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", 10)
    for valor in ("30", "2", "0"):
        monkeypatch.setenv("PGCONNECT_TIMEOUT", valor)
        assert database.argumentos_de_conexao_pg(URL_PG) == {}, valor
        assert "connect_args" not in database.opcoes_do_engine(URL_PG), valor
    for vazio in ("", "   "):
        monkeypatch.setenv("PGCONNECT_TIMEOUT", vazio)
        assert database.argumentos_de_conexao_pg(URL_PG) == {"connect_timeout": 10}, vazio
    monkeypatch.delenv("PGCONNECT_TIMEOUT")
    assert database.argumentos_de_conexao_pg(URL_PG) == {"connect_timeout": 10}
    assert database.opcoes_do_engine(URL_PG)["connect_args"] == {"connect_timeout": 10}
    # o SQLite não muda com a variável
    monkeypatch.setenv("PGCONNECT_TIMEOUT", "30")
    assert database.opcoes_do_engine("sqlite://") == {
        "connect_args": {"check_same_thread": False}, "hide_parameters": True}


def test_metricas_sync_md_nao_diz_que_a_conexao_nova_e_sem_prazo(monkeypatch):
    """docs/sync/METRICAS-SYNC.md (seção do prazo total do coletor) seguia dizendo "uma
    conexão nova sem ``connect_timeout``" depois que o engine PostgreSQL passou a ter o
    prazo (486c571); a docstring de ``app/sync/metricas.py`` já fora corrigida. O
    documento tem de citar o ``DB_CONNECT_TIMEOUT`` e não negar o prazo que o engine dá."""
    monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", 10)
    assert database.opcoes_do_engine(URL_PG)["connect_args"] == {"connect_timeout": 10}
    doc = PROJECT_ROOT / "docs" / "sync" / "METRICAS-SYNC.md"
    texto = " ".join(doc.read_text(encoding="utf-8").split())
    velho = re.search(r"conex(?:ão|ao) nova sem `*connect_timeout", texto, re.IGNORECASE)
    assert velho is None, velho.group(0)
    assert "DB_CONNECT_TIMEOUT" in texto


@pytest.mark.postgres
def test_connect_timeout_da_url_prevalece(monkeypatch):
    """O ``connect_args`` sobrescreveria o ``?connect_timeout=`` da URL: a escolha
    explícita do operador vale mais que o padrão do app."""
    monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", 10)
    url = URL_PG + "?connect_timeout=4"
    assert "connect_args" not in database.opcoes_do_engine(url)
    assert str(_cparams_entregues_ao_driver(url)["connect_timeout"]) == "4"


@pytest.mark.parametrize("url", ["sqlite:///constela.db", "sqlite://"])
def test_sqlite_intacto(url):
    """O SQLite segue com as MESMAS opções de antes — ``sqlite3.connect`` não conhece
    ``connect_timeout`` e recusaria o argumento."""
    assert database.argumentos_de_conexao_pg(url) == {}
    assert database.opcoes_do_engine(url) == {
        "connect_args": {"check_same_thread": False}, "hide_parameters": True}


def test_sqlite_continua_conectando():
    motor = create_engine("sqlite://", **database.opcoes_do_engine("sqlite://"))
    with motor.connect() as conexao:
        assert conexao.execute(text("SELECT 1")).scalar() == 1
    motor.dispose()
    # e o engine vivo deste processo (SQLite nos testes) também
    if database.is_sqlite:
        with database.engine.connect() as conexao:
            assert conexao.execute(text("SELECT 1")).scalar() == 1


@pytest.fixture()
def banco_mudo():
    """Um "PostgreSQL" que aceita o TCP (o kernel completa o handshake na fila do
    ``listen``) e nunca responde à mensagem de abertura — o caso que o prazo cobre."""
    _exigir_driver()
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.bind(("127.0.0.1", 0))
    servidor.listen(8)
    porta = servidor.getsockname()[1]
    try:
        yield f"postgresql+psycopg://usuario@127.0.0.1:{porta}/constela_teste"
    finally:
        servidor.close()


@pytest.mark.postgres
def test_banco_mudo_falha_no_prazo_em_vez_de_pendurar(monkeypatch, banco_mudo):
    monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", 2)
    motor = create_engine(banco_mudo, **database.opcoes_do_engine(banco_mudo))
    inicio = time.monotonic()
    with pytest.raises(OperationalError):
        motor.connect()
    decorrido = time.monotonic() - inicio
    motor.dispose()
    assert 1.0 <= decorrido < 15, decorrido


@pytest.mark.postgres
def test_banco_mudo_respeita_o_pgconnect_timeout_do_ambiente(monkeypatch, banco_mudo):
    """Ponta a ponta, pelo ``psycopg.connect`` de verdade: o operador põe
    ``PGCONNECT_TIMEOUT=2`` e o engine desiste em ~2 s, não nos 10 s do padrão do app
    (antes da correção, o ``connect_args`` escondia a variável e levava 10 s)."""
    monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", 10)
    monkeypatch.setenv("PGCONNECT_TIMEOUT", "2")
    motor = create_engine(banco_mudo, **database.opcoes_do_engine(banco_mudo))
    inicio = time.monotonic()
    with pytest.raises(OperationalError):
        motor.connect()
    decorrido = time.monotonic() - inicio
    motor.dispose()
    assert 1.0 <= decorrido < 6, decorrido


@pytest.mark.postgres
def test_controle_sem_prazo_o_mesmo_banco_mudo_pendura(monkeypatch, banco_mudo):
    """Controle: com ``DB_CONNECT_TIMEOUT=0`` (sem prazo do app, padrão de 130 s do
    psycopg 3.2) a MESMA conexão segue presa depois de 4 s. A thread é daemon e se solta
    quando o servidor fecha (fim do teste) ou no prazo do driver."""
    monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", 0)
    motor = create_engine(banco_mudo, **database.opcoes_do_engine(banco_mudo))
    resultado: dict = {}

    def tentar():
        try:
            motor.connect()
            resultado["fim"] = "conectou"
        except Exception as exc:  # noqa: BLE001 — só registra como terminou
            resultado["fim"] = type(exc).__name__

    tarefa = threading.Thread(target=tentar, daemon=True)
    tarefa.start()
    tarefa.join(4)
    assert tarefa.is_alive(), f"sem prazo deveria seguir preso; terminou: {resultado}"
    motor.dispose()


@pytest.mark.postgres
def test_pg_local_continua_conectando_e_o_driver_tem_o_prazo(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL_PG")
    if not url:
        pytest.skip("defina TEST_DATABASE_URL_PG para rodar contra PostgreSQL real")
    if make_url(url).host not in ("127.0.0.1", "localhost", "::1"):
        pytest.skip("só PostgreSQL LOCAL")
    for prazo in (settings.DB_CONNECT_TIMEOUT, 3):
        monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", prazo)
        motor = create_engine(url, **database.opcoes_do_engine(url))
        try:
            with motor.connect() as conexao:
                assert conexao.execute(text("SELECT 1")).scalar() == 1
                parametros = conexao.connection.driver_connection.info.get_parameters()
                assert parametros.get("connect_timeout") == str(prazo), parametros
        finally:
            motor.dispose()
    # Com PGCONNECT_TIMEOUT no ambiente, a PRÓPRIA libpq registra o prazo do operador
    # (antes da correção registrava os 10 s do app).
    monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", 10)
    monkeypatch.setenv("PGCONNECT_TIMEOUT", "30")
    motor = create_engine(url, **database.opcoes_do_engine(url))
    try:
        with motor.connect() as conexao:
            parametros = conexao.connection.driver_connection.info.get_parameters()
            assert parametros.get("connect_timeout") == "30", parametros
    finally:
        motor.dispose()


# ---------------------------------------------------------------------------
# Regressão (revisão do grupo rp-conexao): 5 testes deste arquivo chamavam
# create_engine("postgresql+psycopg://...") sem guarda e quebravam o job test-backend do CI,
# que roda a suíte inteira SEM o psycopg (ModuleNotFoundError no import_dbapi do SQLAlchemy).
# ---------------------------------------------------------------------------

def test_os_que_precisam_do_driver_tem_o_marcador_postgres():
    """Pular sem o driver não basta: sem o marcador ``postgres`` eles não rodariam em job
    nenhum do CI (o ``test-backend-postgres``, que instala o psycopg, roda ``-m postgres``)."""
    for nome in sorted(PRECISAM_DO_DRIVER):
        marcadores = {m.name for m in getattr(globals()[nome], "pytestmark", [])}
        assert "postgres" in marcadores, nome


# O job test-backend sem o psycopg: o import do driver falha como num ambiente sem ele, e o
# desfecho de cada teste volta ao processo pai numa linha JSON.
_SIMULA_JOB_SEM_DRIVER = r'''
import importlib.abc
import json
import sys

import pytest


class _SemPsycopg(importlib.abc.MetaPathFinder):
    def find_spec(self, nome, caminho, alvo=None):
        if nome == "psycopg" or nome.startswith(("psycopg.", "psycopg_")):
            raise ModuleNotFoundError(f"No module named {nome!r}", name=nome)
        return None


sys.meta_path.insert(0, _SemPsycopg())


class _Desfechos:
    def __init__(self):
        self.por_teste = {}

    def pytest_runtest_logreport(self, report):
        nome = report.nodeid.split("::")[-1]
        if report.failed:
            self.por_teste[nome] = "failed"
        elif report.skipped:
            self.por_teste.setdefault(nome, "skipped")
        elif report.when == "call":
            self.por_teste.setdefault(nome, "passed")


desfechos = _Desfechos()
rc = pytest.main(sys.argv[1:], plugins=[desfechos])
print("DESFECHOS=" + json.dumps({"rc": int(rc), "testes": desfechos.por_teste}))
'''


def test_sem_o_driver_o_arquivo_pula_em_vez_de_falhar():
    """Este arquivo inteiro num processo SEM o psycopg (como no job ``test-backend``):
    nenhuma falha; os de ``PRECISAM_DO_DRIVER`` pulam, o resto passa. O PostgreSQL local
    (``TEST_DATABASE_URL_PG``) sai do ambiente, como no job, e o app usa SQLite em memória."""
    eu = Path(__file__).resolve()
    env = {k: v for k, v in os.environ.items()
           if k != "TEST_DATABASE_URL_PG" and k != "SENTRY_DSN"
           and not k.startswith(("RAILWAY", "SUPABASE"))}
    env.update(DATABASE_URL="sqlite://", SYNC_SCHEDULER_ENABLED="false",
               PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, "-c", _SIMULA_JOB_SEM_DRIVER, "-q", "-p", "no:cacheprovider",
         "-k", "not test_sem_o_driver_o_arquivo_pula_em_vez_de_falhar", str(eu)],
        cwd=str(eu.parents[1]), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300)
    saida = proc.stdout[-6000:] + proc.stderr[-3000:]
    linhas = [linha for linha in proc.stdout.splitlines() if linha.startswith("DESFECHOS=")]
    assert linhas, saida
    desfechos = json.loads(linhas[-1].removeprefix("DESFECHOS="))
    testes = desfechos["testes"]
    assert not [n for n, d in testes.items() if d == "failed"], saida
    assert desfechos["rc"] == 0, saida
    pularam = {n for n, d in testes.items() if d == "skipped"}
    assert pularam == PRECISAM_DO_DRIVER | {
        "test_pg_local_continua_conectando_e_o_driver_tem_o_prazo"}, saida
    passaram = {n for n, d in testes.items() if d == "passed"}
    assert {"test_padrao_e_10_segundos_e_o_engine_pg_o_recebe",
            "test_opcoes_sem_driver_prazo_configuravel_zero_desliga_e_url_prevalece",
            "test_variavel_de_ambiente_e_lida",
            "test_pgconnect_timeout_do_ambiente_prevalece_sobre_o_padrao_do_app",
            "test_metricas_sync_md_nao_diz_que_a_conexao_nova_e_sem_prazo",
            "test_sqlite_continua_conectando",
            "test_os_que_precisam_do_driver_tem_o_marcador_postgres"} <= passaram, saida
