"""Interruptor do diagnóstico do robô no boot (``AUTOMACAO_VERIFICAR_NO_BOOT``).

O ``app.main`` dispara no import uma thread ``verificar-automacao`` que faz GET a
ipinfo.io/ipapi.co (IP de saída) e abre o Chromium nas páginas de login. O pytest importa
o ``app.main`` pelo conftest e o E2E sobe ``uvicorn app.main:app``: os dois saíam para a
internet a partir do runner do CI. Agora o padrão continua LIGADO (a produção não muda) e
``false`` desliga — o conftest desliga antes de importar o app e o E2E no BACKEND_ENV.

Nada aqui usa rede: o alvo da thread é trocado por um espião e o ``urlopen`` por uma
armadilha que conta as chamadas.
"""
import importlib.util
import json
import re
import threading
import types
import urllib.request

import pytest

from app.core import automacao
from app.core.config import PROJECT_ROOT, Settings, settings
from tests._infra_comum import ambiente, rodar, sqlite_url  # noqa: F401 — fixture

VARIAVEL = "AUTOMACAO_VERIFICAR_NO_BOOT"
NOME_DA_THREAD = "verificar-automacao"


def _cfg(valor):
    return types.SimpleNamespace(**{VARIAVEL: valor})


# --- 1. Padrão e interpretação --------------------------------------------------------

def test_a_sessao_de_testes_nasce_com_o_diagnostico_desligado():
    """O conftest desligou ANTES de importar o app (o Settings lê o ambiente no import)."""
    assert settings.AUTOMACAO_VERIFICAR_NO_BOOT == "false"
    assert automacao.verificacao_no_boot_ligada() is False


def test_o_padrao_e_ligado_como_em_producao(monkeypatch):
    assert Settings.model_fields[VARIAVEL].default == "true"
    monkeypatch.delenv(VARIAVEL, raising=False)
    sem_variavel = Settings(_env_file=None)
    assert automacao.verificacao_no_boot_ligada(sem_variavel) is True


@pytest.mark.parametrize("valor", ["false", "FALSE", " 0 ", "off", "no", "nao", "não"])
def test_valores_de_desligado_desligam(valor):
    assert automacao.verificacao_no_boot_ligada(_cfg(valor)) is False


@pytest.mark.parametrize("valor", ["true", "1", "on", "sim", "yes", "", None])
def test_valores_de_ligado_e_vazio_mantem_ligado(valor, caplog):
    assert automacao.verificacao_no_boot_ligada(_cfg(valor)) is True
    assert VARIAVEL not in caplog.text


def test_valor_nao_reconhecido_mantem_ligado_e_avisa(caplog):
    """Um erro de digitação no painel do deploy não derruba o boot nem desliga em
    silêncio o diagnóstico da produção."""
    assert automacao.verificacao_no_boot_ligada(_cfg("talvez")) is True
    assert "AUTOMACAO_VERIFICAR_NO_BOOT com valor não reconhecido" in caplog.text


# --- 2. O que o boot chama: thread ou nada ---------------------------------------------

@pytest.fixture
def automacao_isolada(monkeypatch):
    """Cópia NOVA do módulo, com as funções originais (o plugin de rede dos ensaios
    locais troca ``automacao.iniciar_verificacao`` no módulo carregado), o alvo da thread
    trocado por um espião e o ``urlopen`` por uma armadilha."""
    spec = importlib.util.spec_from_file_location("automacao_isolada", automacao.__file__)
    copia = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copia)
    rodou, liberar, nomes, urlopen = threading.Event(), threading.Event(), [], []

    def espiao():
        nomes.append(threading.current_thread().name)
        rodou.set()
        liberar.wait(10)

    def armadilha(*args, **kwargs):
        urlopen.append(args)
        raise OSError("sem rede no teste")

    copia._verificar = espiao
    monkeypatch.setattr(urllib.request, "urlopen", armadilha)
    yield types.SimpleNamespace(modulo=copia, rodou=rodou, nomes=nomes, urlopen=urlopen)
    liberar.set()


def _threads_do_diagnostico():
    return [t for t in threading.enumerate() if t.name == NOME_DA_THREAD]


def test_desligado_nao_nasce_thread_nem_sai_para_a_rede(automacao_isolada):
    a = automacao_isolada
    antes = _threads_do_diagnostico()
    assert a.modulo.iniciar_no_boot(_cfg("false")) is False
    assert not a.rodou.wait(0.5)
    # Nenhuma thread NOVA. Não é igualdade com ``antes``: a thread de outro teste (presa
    # no espião até o teardown dele) pode terminar durante a espera e sair da lista.
    novas = [t for t in _threads_do_diagnostico() if t not in antes]
    assert novas == [] and a.nomes == [] and a.urlopen == []
    assert "desligada" in a.modulo.status()["detalhe"]


def test_ligado_nasce_a_thread_do_diagnostico(automacao_isolada):
    a = automacao_isolada
    assert a.modulo.iniciar_no_boot(_cfg("true")) is True
    assert a.rodou.wait(10)
    assert a.nomes == [NOME_DA_THREAD] and a.urlopen == []


def test_o_padrao_do_settings_dispara(automacao_isolada, monkeypatch):
    monkeypatch.delenv(VARIAVEL, raising=False)
    assert automacao_isolada.modulo.iniciar_no_boot(Settings(_env_file=None)) is True
    assert automacao_isolada.rodou.wait(10)


# --- 3. Ponta a ponta: importar o app.main num processo novo, como o uvicorn faz -------

IMPORTAR_COM_ESPIAO = (
    "import json, threading, urllib.request\n"
    "import app.core.automacao as a\n"
    "rodou, liberar, alvo, chamadas = threading.Event(), threading.Event(), [], []\n"
    "def _espiao():\n"
    "    alvo.append(threading.current_thread().name)\n"
    "    rodou.set()\n"
    "    liberar.wait(10)\n"
    "a._verificar = _espiao\n"
    "def _armadilha(*args, **kwargs):\n"
    "    chamadas.append(1)\n"
    "    raise OSError('sem rede no teste')\n"
    "urllib.request.urlopen = _armadilha\n"
    "import app.main\n"
    "vivas = sorted(t.name for t in threading.enumerate())\n"
    f"if {NOME_DA_THREAD!r} in vivas:\n"
    "    rodou.wait(10)\n"
    "liberar.set()\n"
    "print('RESULTADO=' + json.dumps({'vivas': vivas, 'alvo': alvo, 'urlopen': len(chamadas)}))\n"
)


def _boot(sqlite_url, **extra):
    env = ambiente(sqlite_url, producao=False)
    env.pop(VARIAVEL, None)                         # o conftest pôs "false" no ambiente
    env.update(extra)
    p = rodar(IMPORTAR_COM_ESPIAO, env)
    linhas = [x for x in p.stdout.splitlines() if x.startswith("RESULTADO=")]
    assert p.returncode == 0 and linhas, f"{p.returncode}\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}"
    return json.loads(linhas[-1][len("RESULTADO="):])


def test_boot_com_a_variavel_desligada_nao_dispara(sqlite_url):
    r = _boot(sqlite_url, **{VARIAVEL: "false"})
    assert NOME_DA_THREAD not in r["vivas"] and r["alvo"] == [] and r["urlopen"] == 0


def test_boot_sem_a_variavel_dispara_como_em_producao(sqlite_url):
    r = _boot(sqlite_url)
    assert NOME_DA_THREAD in r["vivas"] and r["alvo"] == [NOME_DA_THREAD]
    assert r["urlopen"] == 0                        # o espião não consulta nada


# --- 4. O E2E sobe o backend com o diagnóstico desligado --------------------------------

def test_todo_e2e_que_sobe_o_backend_desliga_o_diagnostico():
    configs = sorted((PROJECT_ROOT / "apps" / "web").glob("playwright*.config.ts"))
    assert configs, "nenhum playwright*.config.ts em apps/web"
    sobem_backend = [c for c in configs
                     if re.search(r"uvicorn|app\.main|--servir", c.read_text(encoding="utf-8"))]
    assert {c.name for c in sobem_backend} >= {"playwright.config.ts"}
    for c in sobem_backend:
        texto = c.read_text(encoding="utf-8")
        assert re.search(rf'\b{VARIAVEL}:\s*"false"', texto), f"{c.name} sem {VARIAVEL}: \"false\""
        assert "env: BACKEND_ENV" in texto, (
            f"{c.name}: o webServer do backend não usa o BACKEND_ENV")
