"""O seed do E2E só apaga e semeia o SQLite de TESTE que lhe foi dado (achado G_SCRIPTS-5).

O DEFEITO. O apagamento rodava no import e olhava só ``os.environ["DATABASE_URL"]``; a
trava do ``main()`` olhava ``settings.DATABASE_URL``, que vem também do ``.env`` ou do
padrão (``database/sgpe.db``). Sem a variável exportada, nada era apagado, a trava
passava ("é SQLite e não é produção") e o script semeava por cima do banco de
desenvolvimento: marcava TODAS as crianças da escola do admin como "da Lista Piloto"
(a guarda do certificado deixava de filtrar) e criava contas de coordenação e de
professor com as senhas padrão escritas no código.

A CORREÇÃO, provada aqui: sem ``DATABASE_URL`` no ambiente, o script recusa (código ≠
0) sem tocar em nada; a trava e o apagamento usam a MESMA URL (a do engine do app); o
banco de desenvolvimento padrão nunca é apagado, nem com a variável apontando para ele.
O caminho do Playwright (``DATABASE_URL=sqlite:///./e2e.db``) continua: apaga e recria.

Tudo roda numa CÓPIA do backend numa pasta temporária: o "banco de desenvolvimento" é
o ``database/sgpe.db`` da cópia (o ``PROJECT_ROOT`` dela), nunca o desta máquina, e não
há ``.env``. Dados fictícios do próprio seed.
"""
import hashlib
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
COORD = "coord@constela.local"


@pytest.fixture(scope="module")
def copia(tmp_path_factory) -> Path:
    """``<raiz>/backend`` copiado (só o que o seed usa) e ``<raiz>/database`` vazio."""
    raiz = tmp_path_factory.mktemp("raiz_seed_e2e")
    destino = raiz / "backend"
    sem_cache = shutil.ignore_patterns("__pycache__")
    for pasta in ("app", "scripts", "alembic"):
        shutil.copytree(BACKEND / pasta, destino / pasta, ignore=sem_cache)
    shutil.copy2(BACKEND / "alembic.ini", destino / "alembic.ini")
    (raiz / "database").mkdir()
    return destino


def _ambiente(**extra: str) -> dict:
    # O subprocesso usa uma cópia de app. Remova a configuração de cobertura
    # herdada para que essa cópia não entre como uma segunda árvore no relatório.
    env = {k: v for k, v in os.environ.items()
           if k not in ("DATABASE_URL", "TEST_DATABASE_URL_PG", "ENV", "SENTRY_DSN",
                        "ADMIN_INITIAL_PASSWORD", "COORD_PASSWORD", "PROF_PASSWORD")
           and not k.startswith(("RAILWAY", "SUPABASE", "COV_CORE_", "COVERAGE_PROCESS_"))}
    env.update(SECRET_KEY=secrets.token_urlsafe(48), AUTOMACAO_VERIFICAR_NO_BOOT="false",
               SYNC_SCHEDULER_ENABLED="false", PYTHONIOENCODING="utf-8",
               PYTHONWARNINGS="ignore")
    env.update(extra)
    return env


def _rodar(copia: Path, script: str, env: dict, *argumentos: str):
    return subprocess.run([sys.executable, f"scripts/{script}", *argumentos], cwd=copia,
                          env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=600)


def _banco_de_desenvolvimento(copia: Path) -> Path:
    """O banco que o README manda criar (``seed.py --demo`` sem DATABASE_URL)."""
    banco = copia.parent / "database" / "sgpe.db"
    if not banco.exists():
        p = _rodar(copia, "seed.py", _ambiente(), "--demo")
        assert p.returncode == 0, p.stderr[-2000:]
        assert banco.exists()
    return banco


def _conectar(banco: Path):
    """Conexão que FECHA na saída (o ``with`` do sqlite3 só faz commit): no Windows, um
    arquivo aberto aqui não pode ser apagado pelo script, e a recusa pareceria trava."""
    return closing(sqlite3.connect(banco))


def _estado(banco: Path) -> dict:
    with _conectar(banco) as conn:
        return {
            "hash": hashlib.sha256(banco.read_bytes()).hexdigest(),
            "lista_piloto": conn.execute(
                "SELECT COUNT(*) FROM alunos WHERE da_lista_piloto = 1").fetchone()[0],
            "contas": sorted(e for (e,) in conn.execute("SELECT email FROM usuarios")),
        }


def test_sem_database_url_no_ambiente_recusa_e_nao_toca_o_banco_de_desenvolvimento(copia):
    banco = _banco_de_desenvolvimento(copia)
    antes = _estado(banco)
    assert antes["lista_piloto"] == 0 and COORD not in antes["contas"]

    p = _rodar(copia, "seed_e2e.py", _ambiente())

    assert p.returncode not in (0, None), p.stdout[-2000:]
    assert "DATABASE_URL" in p.stderr
    assert _estado(banco) == antes            # nem Lista Piloto, nem contas, nem bytes


@pytest.mark.parametrize("como", ["absoluto", "relativo"])
def test_database_url_no_banco_de_desenvolvimento_recusa(copia, como):
    banco = _banco_de_desenvolvimento(copia)
    antes = _estado(banco)
    url = (f"sqlite:///{banco.as_posix()}" if como == "absoluto"
           else "sqlite:///../database/sgpe.db")

    p = _rodar(copia, "seed_e2e.py", _ambiente(DATABASE_URL=url))

    assert p.returncode not in (0, None), p.stdout[-2000:]
    assert _estado(banco) == antes


def test_o_caminho_do_playwright_continua_apagando_e_recriando(copia):
    """``playwright.config.ts``: DATABASE_URL=sqlite:///./e2e.db, cwd = backend."""
    e2e = copia / "e2e.db"
    with _conectar(e2e) as conn:                       # o resto de uma rodada anterior
        conn.execute("CREATE TABLE sobra_da_rodada_anterior (x INTEGER)")
        conn.commit()
    env = _ambiente(DATABASE_URL="sqlite:///./e2e.db",
                    ADMIN_INITIAL_PASSWORD="AdminInventada@" + secrets.token_hex(4))

    p = _rodar(copia, "seed_e2e.py", env)

    assert p.returncode == 0, p.stderr[-2000:]
    with _conectar(e2e) as conn:
        tabelas = {t for (t,) in conn.execute("SELECT name FROM sqlite_master")}
    assert "sobra_da_rodada_anterior" not in tabelas      # o arquivo foi recriado
    estado = _estado(e2e)
    assert COORD in estado["contas"]
    assert estado["lista_piloto"] > 0
