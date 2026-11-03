"""A sonda do readiness não escreve no log; o LOG_LEVEL do ambiente vale.

Achado da auditoria de 20/10: cada ``GET /api/health/ready`` montava um
``MigrationContext`` do Alembic só para ler a ``alembic_version``, e o construtor
dele loga em INFO duas linhas ("Context impl ...", "Will assume ... DDL"). Com o
logger ``alembic`` fixo em INFO, eram 2 linhas por sonda MESMO com
``LOG_LEVEL=WARNING`` — com um monitor de 1 sonda/min, ~2.880 linhas/dia sem
informação. ``/api/health`` fica fora do log de acesso justamente por isso, e a
prontidão só loga quando o motivo MUDA.

Mesma rodada: o ``httpx`` herdava o INFO da raiz e logava cada chamada de saída com a
URL inteira; agora fica em WARNING, junto com o ``sqlalchemy.engine``.
"""
from __future__ import annotations

import io
import json
import logging
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

import app.main as main_mod
from app.core import observabilidade as obs
from app.core.config import settings
from app.core.migracoes import revisoes_do_banco
from app.core.prontidao import Prontidao
from tests._infra_comum import (  # noqa: F401 — fixtures
    levar_a,
    pg_url,
    sondar,
)

cliente = TestClient(main_mod.app)

_LOGGERS = ("sqlalchemy.engine", "alembic", "httpx", "uvicorn", "uvicorn.error")


@pytest.fixture
def log_do_processo(monkeypatch):
    """O logging de PRODUÇÃO (``configurar_logging``) gravando num buffer. Chame a
    função devolvida com o LOG_LEVEL desejado; ela devolve o leitor das linhas JSON.
    Restaura o logging do processo no fim."""
    raiz = logging.getLogger()
    salvo = (list(raiz.handlers), raiz.level,
             {n: (logging.getLogger(n).level, list(logging.getLogger(n).handlers),
                  logging.getLogger(n).propagate) for n in _LOGGERS})
    saida = io.StringIO()

    def configurar(nivel: str = "INFO"):
        monkeypatch.setattr(settings, "LOG_LEVEL", nivel)
        monkeypatch.setattr(sys, "stdout", saida)
        obs.configurar_logging(settings)
        return lambda: [json.loads(x) for x in saida.getvalue().splitlines()
                        if x.startswith("{")]

    yield configurar
    handlers, nivel, outros = salvo
    raiz.handlers[:] = handlers
    raiz.setLevel(nivel)
    for nome, (lvl, hs, prop) in outros.items():
        lg = logging.getLogger(nome)
        lg.setLevel(lvl)
        lg.handlers[:] = hs
        lg.propagate = prop


@pytest.fixture
def processo_novo(monkeypatch):
    """Prontidão de um processo que acabou de subir (ainda não logou o motivo)."""
    monkeypatch.setattr(main_mod, "prontidao", Prontidao())


def test_sondas_do_readiness_so_logam_a_mudanca_de_motivo(log_do_processo, processo_novo):
    linhas = log_do_processo("INFO")
    for _ in range(3):
        assert cliente.get("/api/health/ready").status_code == 200
    mensagens = [(x["logger"], x["message"]) for x in linhas()]
    # Uma linha só: "Schema em dia" na 1ª sonda (o motivo mudou de nada para em_dia).
    assert len(mensagens) == 1, mensagens
    assert mensagens[0][0] == "constela" and mensagens[0][1].startswith("Schema em dia")


def test_log_level_warning_silencia_as_sondas(log_do_processo, processo_novo):
    linhas = log_do_processo("WARNING")
    for _ in range(5):
        assert cliente.get("/api/health/ready").status_code == 200
    assert linhas() == []


def test_configurar_logging_baixa_httpx_e_alembic_respeita_o_log_level(log_do_processo):
    log_do_processo("INFO")
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
    assert logging.getLogger("httpx").isEnabledFor(logging.WARNING)
    assert logging.getLogger("alembic").isEnabledFor(logging.INFO)   # "Running upgrade"
    log_do_processo("WARNING")
    assert not logging.getLogger("alembic").isEnabledFor(logging.INFO)
    assert logging.getLogger("alembic").isEnabledFor(logging.WARNING)


def test_revisoes_do_banco_le_a_tabela_sem_contexto_do_alembic(tmp_path):
    """A leitura direta devolve o mesmo que o Alembic: vazio sem tabela, e TODAS as
    linhas quando há mais de uma head (ramos)."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'versao.db').as_posix()}")
    try:
        with engine.connect() as c:
            assert revisoes_do_banco(c) == frozenset()
        with engine.begin() as c:
            c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            c.execute(text("INSERT INTO alembic_version VALUES ('0001'), ('0002_ramo')"))
        with engine.connect() as c:
            assert revisoes_do_banco(c) == frozenset({"0001", "0002_ramo"})
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_postgres_boot_e_sonda_nao_logam_contexto_do_alembic(pg_url):
    """Processo separado com ENV=producao sobre banco em dia (sem migrar no import):
    o boot e a sonda leem a versão sem nenhuma linha do Alembic no log."""
    levar_a(pg_url, "heads")
    r = sondar(pg_url, producao=True, LOG_LEVEL="INFO")
    assert r["ready"] == 200 and r["ready_corpo"]["schema"] == "em_dia"
    linhas = []
    for linha in r["_log"].splitlines():
        if linha.startswith("{"):
            try:
                linhas.append(json.loads(linha))
            except ValueError:
                pass
    assert any(x.get("message", "").startswith("Schema em dia") for x in linhas)
    assert [x["message"] for x in linhas if x.get("logger", "").startswith("alembic")] == []
    assert "Context impl" not in r["_log"]
