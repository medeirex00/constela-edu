"""Peças comuns dos testes de infraestrutura (boot, migração, prontidão, logs).

Os cenários de PRODUÇÃO rodam em PROCESSOS SEPARADOS: ``app.main`` decide no IMPORT
se migra (modo dev) ou não (ENV=producao), então não dá para alternar o modo dentro
do processo de teste. E ``ENV=producao`` recusa SQLite (config.py), por isso esses
cenários exigem PostgreSQL real (``TEST_DATABASE_URL_PG``, LOCAL e com "test" no nome).
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import sys

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import BASE_DIR
from app.core.migracoes import _config

REV_FUTURA = "9999_revisao_do_futuro"           # revisão que NENHUM código conhece

# Bootstrap dos subprocessos: desliga o diagnóstico de rede do boot (abre Chromium e
# consulta serviços externos) e, se pedido, carrega um módulo de bloqueio de rede
# (TESTE_SUBPROCESSO_PRELOAD — nos ensaios locais, o mesmo plugin do pytest).
BOOT = (
    "import importlib, os, sys\n"
    "m = os.environ.get('TESTE_SUBPROCESSO_PRELOAD')\n"
    "if m: importlib.import_module(m)\n"
    "import app.core.automacao as _a\n"
    "_a.iniciar_verificacao = lambda: None\n"
)
IMPORTAR_E_SONDAR = BOOT + (
    "import json\n"
    "from fastapi.testclient import TestClient\n"
    "from app.main import app\n"
    "c = TestClient(app, raise_server_exceptions=False)\n"
    "r = c.get('/api/health/ready')\n"
    "out = {'ready': r.status_code, 'ready_corpo': r.json(),\n"
    "       'live': c.get('/api/health/live').status_code,\n"
    "       'health': c.get('/api/health').json()}\n"
    "print('RESULTADO=' + json.dumps(out))\n"
)
MIGRAR = BOOT + (
    "import runpy\n"
    "sys.argv = ['scripts.migrate']\n"
    "runpy.run_module('scripts.migrate', run_name='__main__')\n"
)


@pytest.fixture
def logging_preservado():
    """Devolve o logging do processo como estava (outros testes dependem dele)."""
    raiz = logging.getLogger()
    nomes = ("sqlalchemy.engine", "alembic", "uvicorn", "uvicorn.error")
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


@pytest.fixture
def sqlite_url(tmp_path) -> str:
    return f"sqlite:///{(tmp_path / 'infra.db').as_posix()}"


@pytest.fixture
def pg_url():
    """PostgreSQL LOCAL de teste com o schema ``public`` zerado antes e depois
    (mesma regra de tests/test_migracoes_postgres.py)."""
    url = os.environ.get("TEST_DATABASE_URL_PG")
    if not url:
        pytest.skip("defina TEST_DATABASE_URL_PG para rodar contra PostgreSQL real")
    u = make_url(url)
    if "test" not in (u.database or "").lower():
        pytest.skip("o nome do banco de teste precisa conter 'test'")
    if u.host not in ("127.0.0.1", "localhost", "::1"):
        pytest.skip("estes testes apagam o schema: só PostgreSQL LOCAL")
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    yield url
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def levar_a(url: str, alvo: str) -> None:
    """Leva o banco a uma revisão ESPECÍFICA pelo Alembic (montagem do cenário)."""
    engine = create_engine(url)
    try:
        cfg = _config()
        with engine.begin() as conexao:
            if conexao.dialect.name == "sqlite":
                conexao.exec_driver_sql("PRAGMA foreign_keys=OFF")
            cfg.attributes["connection"] = conexao
            command.upgrade(cfg, alvo)
    finally:
        engine.dispose()


def revisao_anterior_a_head() -> str:
    """Uma revisão CONHECIDA e atrás das heads (o "banco sem a última migração")."""
    from app.core.migracoes import _revisoes_do_codigo
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_config())
    head = sorted(_revisoes_do_codigo()[0])[0]
    anterior = script.get_revision(head).down_revision
    assert isinstance(anterior, str), "a head escolhida é merge/raiz: ajuste o teste"
    return anterior


def heads_do_codigo() -> list[str]:
    from app.core.migracoes import _revisoes_do_codigo
    return sorted(_revisoes_do_codigo()[0])


def marcar_versao(url: str, revisao: str) -> None:
    """Força ``alembic_version`` para ``revisao`` (simula código mais velho que o banco)."""
    engine = create_engine(url)
    try:
        with engine.begin() as c:
            c.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": revisao})
    finally:
        engine.dispose()


def assinatura(url: str) -> dict:
    """Schema (tabelas, colunas, índices) + versão + contagem de linhas."""
    engine = create_engine(url)
    try:
        with engine.connect() as c:
            insp = inspect(c)
            tabelas = sorted(insp.get_table_names())
            schema = {t: ([(col["name"], str(col["type"]), col["nullable"])
                           for col in insp.get_columns(t)],
                          sorted(i["name"] or "" for i in insp.get_indexes(t)))
                      for t in tabelas}
            versao = (sorted(c.execute(text("SELECT version_num FROM alembic_version")).scalars())
                      if "alembic_version" in tabelas else [])
            linhas = {t: c.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() for t in tabelas}
        return {"versao": versao, "schema": schema, "linhas": linhas}
    finally:
        engine.dispose()


def ambiente(url: str, producao: bool, **extra) -> dict:
    env = dict(os.environ)
    for k in list(env):
        if k.startswith(("RAILWAY", "SUPABASE")) or k in ("SENTRY_DSN", "ENV"):
            env.pop(k)
    env.update(DATABASE_URL=url, SECRET_KEY=secrets.token_urlsafe(48),
               SYNC_SCHEDULER_ENABLED="false", LOG_JSON="true", PYTHONIOENCODING="utf-8")
    if producao:
        # Produção recusa subir sem uma DEK própria e com /docs ligado
        # (config.riscos_de_producao). O processo roda com cwd=backend: sem o false
        # explícito, um backend/.env de desenvolvimento com DOCS_HABILITADOS=true
        # derrubaria todo teste de processo com ENV=producao (a variável de ambiente
        # vence o .env). Quem quer testar o /docs passa DOCS_HABILITADOS em ``extra``.
        env.update(ENV="producao", DATA_ENCRYPTION_KEY=secrets.token_urlsafe(48),
                   DOCS_HABILITADOS="false")
    env.update({k: str(v) for k, v in extra.items()})
    return env


def rodar(codigo: str, env: dict, timeout: int = 240) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", codigo], cwd=str(BASE_DIR), env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=timeout)


def sondar(url: str, producao: bool, **extra) -> dict:
    """Importa ``app.main`` num processo novo (como o uvicorn faria) e sonda a saúde."""
    p = rodar(IMPORTAR_E_SONDAR, ambiente(url, producao, **extra))
    linhas = [x for x in p.stdout.splitlines() if x.startswith("RESULTADO=")]
    assert p.returncode == 0 and linhas, (
        f"saída {p.returncode}\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
    resultado = json.loads(linhas[-1][len("RESULTADO="):])
    resultado["_log"] = p.stdout + p.stderr
    return resultado


def migrar_processo(url: str, producao: bool = True, **extra) -> subprocess.CompletedProcess:
    return rodar(MIGRAR, ambiente(url, producao, **extra))
