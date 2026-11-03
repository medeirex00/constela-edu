"""Exceção no FIM da sessão do pytest chega ao stderr com a causa (conftest.pytest_unconfigure).

O handler do app (``SaidaDoLog``) nasce no import do ``app.main`` pelo conftest, com a
captura global do pytest já ligada: o stream dele é o ``sys.stdout`` DA CAPTURA, que o
pytest só fecha no último cleanup da sessão (``stop_global_capturing``). Uma exceção que
sobe depois disso — de um ``config.add_cleanup`` ou do ``pytest_sessionfinish``, como em
28/10 (``cleanup_dead_symlinks`` com PermissionError nos links ``*current`` do basetemp)
— chega ao ``sys.excepthook`` do app, que loga ``excecao_nao_tratada`` nesse stream
FECHADO. Saía só "<falha ao escrever o log de constela: ValueError>" (ou, com o handler do
alembic.ini vazado para a raiz, "--- Logging error ---"), e a causa sumia. O
``pytest_runtest_protocol`` do conftest não resolve isso sozinho: ele devolve à raiz o
mesmo ``SaidaDoLog``, preso à captura.

Aqui roda um pytest NOVO num subprocesso, com o conftest dos testes carregado sob a
captura, como na suíte (``pytest_plugins`` de um conftest inicial), e dois testes
fictícios: o 1º migra pelo alembic.ini (o caso que trocava o handler da raiz); o 2º
registra um cleanup que levanta e um ``atexit`` que loga um erro (o log que chega depois
de tudo, já na finalização do interpretador). Sem rede: o diagnóstico do boot fica
neutralizado, como nos outros subprocessos (``_infra_comum.BOOT``).
"""
from __future__ import annotations

import subprocess
import sys

from app.core.config import BASE_DIR
from tests._infra_comum import ambiente, sqlite_url  # noqa: F401 — fixture

CAUSA = "CAUSA_FICTICIA_DO_CLEANUP"
CAUSA_NO_ATEXIT = "CAUSA_FICTICIA_DO_ATEXIT"

# O conftest da sessão de dentro: o bootstrap dos subprocessos de _infra_comum (bloqueio
# de rede opcional + diagnóstico do boot neutralizado) e o conftest dos testes carregado
# como plugin DURANTE a carga dos conftests iniciais, isto é, sob a captura global.
CONFTEST_DE_DENTRO = (
    "import importlib, os\n"
    "m = os.environ.get('TESTE_SUBPROCESSO_PRELOAD')\n"
    "if m: importlib.import_module(m)\n"
    "import app.core.automacao as _a\n"
    "_a.iniciar_verificacao = lambda: None\n"
    "pytest_plugins = ['tests.conftest']\n"
)

TESTES_DE_DENTRO = '''
import atexit
import logging

from alembic import command
from sqlalchemy import create_engine

from app.core.migracoes import _REVISAO_BASE, _config


def test_a_migra():
    # Banco em memória: sem tmp_path, a sessão de dentro não cria diretório numerado nem
    # o link "*current" (no Windows, caminho longo neles é o que quebrava o cleanup).
    engine = create_engine("sqlite://")
    try:
        cfg = _config()
        with engine.begin() as conexao:
            cfg.attributes["connection"] = conexao
            command.upgrade(cfg, _REVISAO_BASE)
    finally:
        engine.dispose()


def _levanta():
    raise PermissionError("@CAUSA@")


def _loga_no_fim():
    try:
        raise RuntimeError("@CAUSA_NO_ATEXIT@")
    except RuntimeError:
        logging.getLogger("constela.prova").error("erro_no_atexit", exc_info=True)


def test_b_cleanup_que_levanta(request):
    request.config.add_cleanup(_levanta)
    atexit.register(_loga_no_fim)
'''.replace("@CAUSA@", CAUSA).replace("@CAUSA_NO_ATEXIT@", CAUSA_NO_ATEXIT)


def test_excecao_depois_que_a_captura_fecha_chega_ao_stderr_com_a_causa(tmp_path, sqlite_url):
    pasta = tmp_path / "s"                      # caminhos curtos: o Windows tem MAX_PATH
    pasta.mkdir()
    (pasta / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (pasta / "conftest.py").write_text(CONFTEST_DE_DENTRO, encoding="utf-8")
    (pasta / "test_fim.py").write_text(TESTES_DE_DENTRO, encoding="utf-8")
    env = ambiente(sqlite_url, producao=False, AUTOMACAO_VERIFICAR_NO_BOOT="false")
    for var in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS"):   # a sessão de dentro é só esta
        env.pop(var, None)
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-c", str(pasta / "pytest.ini"), "--rootdir", str(pasta),
         "--basetemp", str(tmp_path / "bt"), str(pasta)],
        cwd=str(BASE_DIR), env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=240)
    saida = (f"rc={p.returncode}\n--- stdout\n{p.stdout[-4000:]}\n"
             f"--- stderr\n{p.stderr[-4000:]}")
    assert "2 passed" in p.stdout, saida               # os dois testes fictícios rodaram
    # A exceção continua derrubando o processo (não é engolida)...
    assert p.returncode == 1, saida
    # ...e o diagnóstico chega inteiro ao stderr real: o registro do excepthook do app,
    # com o traceback da causa.
    assert "excecao_nao_tratada" in p.stderr, saida
    assert f"PermissionError: {CAUSA}" in p.stderr, saida
    # O log emitido no atexit, depois de tudo, também chega com o traceback.
    assert "erro_no_atexit" in p.stderr, saida
    assert f"RuntimeError: {CAUSA_NO_ATEXIT}" in p.stderr, saida
    assert "<falha ao escrever o log" not in p.stdout + p.stderr, saida
    assert "--- Logging error ---" not in p.stdout + p.stderr, saida
