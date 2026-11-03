"""Logs no Railway: severidade certa e handler que não é trocado pela migração.

Sintoma (auditoria de 20/10): linhas INFO chegavam como "error" no Railway. Duas
causas, as duas cobertas aqui:

1. ``logging.StreamHandler()`` escreve no STDERR, que o Railway converte em erro;
   e o JSON não tinha o campo ``level`` que ele lê para a severidade.
2. Em modo dev (o de produção hoje) o ``app.main`` migra no import, DEPOIS do
   ``configurar_logging``. O ``env.py`` do Alembic rodava ``fileConfig(alembic.ini)``,
   que troca o handler da raiz por um ``StreamHandler(sys.stderr)`` em texto e baixa a
   raiz para WARNING: o log de acesso INFO sumia e o resto ia para o stderr.
"""
import io
import json
import logging
import sys

import pytest
from sqlalchemy import create_engine

from app.core import observabilidade as obs
from app.core.config import settings


@pytest.fixture
def logging_preservado():
    """Devolve o logging do processo como estava (outros testes dependem dele)."""
    raiz = logging.getLogger()
    nomes = ("sqlalchemy.engine", "alembic", "httpx", "uvicorn", "uvicorn.error")
    salvo = (list(raiz.handlers), raiz.level,
             {n: (logging.getLogger(n).level, list(logging.getLogger(n).handlers),
                  logging.getLogger(n).propagate) for n in nomes})
    yield
    handlers, nivel, outros = salvo
    raiz.handlers[:] = handlers
    raiz.setLevel(nivel)
    for nome, (lvl, hs, prop) in outros.items():
        lg = logging.getLogger(nome)
        lg.setLevel(lvl)
        lg.handlers[:] = hs
        lg.propagate = prop


def _registro(nivel, msg="oi"):
    return logging.LogRecord("teste", nivel, __file__, 1, msg, (), None)


@pytest.mark.parametrize("nivel, esperado", [
    (logging.DEBUG, "debug"), (logging.INFO, "info"), (logging.WARNING, "warn"),
    (logging.ERROR, "error"), (logging.CRITICAL, "error"),
])
def test_json_traz_level_no_vocabulario_do_railway(nivel, esperado):
    d = json.loads(obs.FormatadorJson().format(_registro(nivel, "evento")))
    assert d["level"] == esperado
    assert d["message"] == "evento"
    # Compatibilidade: os campos antigos continuam (filtros e buscas existentes).
    assert d["nivel"] == logging.getLevelName(nivel) and d["msg"] == "evento"


def test_configurar_logging_escreve_no_stdout(logging_preservado):
    obs.configurar_logging(settings)
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert handlers[0].stream is sys.stdout          # nunca stderr (= "error" no Railway)
    assert isinstance(handlers[0].formatter, obs.FormatadorJson)


def test_configurar_logging_nao_libera_sql_com_parametros(logging_preservado):
    """Com a raiz em INFO, o SQLAlchemy logaria cada consulta COM os parâmetros
    (nomes de criança) se o logger dele herdasse o INFO."""
    obs.configurar_logging(settings)
    assert not logging.getLogger("sqlalchemy.engine.Engine").isEnabledFor(logging.INFO)
    assert logging.getLogger("alembic").isEnabledFor(logging.INFO)


def test_migracao_nao_troca_o_logging_e_sai_em_json_no_stdout(
        logging_preservado, monkeypatch, tmp_path):
    """A migração no processo da API mantém o handler/nível da raiz e as linhas do
    Alembic saem pelo NOSSO handler (JSON, level=info), não pelo do alembic.ini."""
    from app.core.migracoes import aplicar_migracoes

    saida = io.StringIO()
    monkeypatch.setattr(sys, "stdout", saida)
    obs.configurar_logging(settings)
    raiz = logging.getLogger()
    handlers_antes, nivel_antes = list(raiz.handlers), raiz.level

    engine = create_engine(f"sqlite:///{(tmp_path / 'logs.db').as_posix()}")
    try:
        aplicar_migracoes(engine)
    finally:
        engine.dispose()

    assert raiz.handlers == handlers_antes and raiz.level == nivel_antes
    linhas = [json.loads(x) for x in saida.getvalue().splitlines() if x.startswith("{")]
    upgrades = [x for x in linhas if "Running upgrade" in x["message"]]
    assert upgrades, "o log da migração não passou pelo handler da aplicação"
    assert {x["level"] for x in upgrades} == {"info"}
