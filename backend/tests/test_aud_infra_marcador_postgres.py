"""Teste que pula sem o driver psycopg leva o marcador ``postgres`` — senão nunca roda no CI.

O psycopg NÃO está no ``requirements.txt``: o job ``test-backend`` roda a suíte sem ele, e o
job ``test-backend-postgres`` (que o instala) roda só ``-m postgres``. Um teste com
``pytest.importorskip("psycopg")`` e sem o marcador PULA no primeiro e NÃO é selecionado no
segundo: não roda em lugar nenhum. Foi o caso do teste da montagem do engine do app em
PostgreSQL (``test_database_ping_ocioso.py``: pool LIFO, ping por ociosidade, prepared
statements desligados, leitura em AUTOCOMMIT no mesmo pool) — TESTES-5. A convenção já estava
escrita em ``test_database_connect_timeout.py``; esta catraca a cobra de todos os arquivos.

Acha (pela árvore do código) o teste que chama ``importorskip("psycopg")`` direto ou por um
ajudante do próprio arquivo e confere (pelo módulo importado) as marcas do teste, da classe e
do módulo — vale também o decorador próprio que aplica ``pytest.mark.postgres``.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

TESTES = Path(__file__).resolve().parent
_DRIVERS = ("psycopg", "psycopg2")
_FUNCOES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _pede_o_driver(no: ast.AST) -> bool:
    for n in ast.walk(no):
        if (isinstance(n, ast.Call)
                and getattr(n.func, "attr", getattr(n.func, "id", None)) == "importorskip"
                and n.args and isinstance(n.args[0], ast.Constant)
                and isinstance(n.args[0].value, str)
                and n.args[0].value.split(".")[0] in _DRIVERS):
            return True
    return False


def _chama_algum(no: ast.AST, nomes: set[str]) -> bool:
    return bool(nomes) and any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in nomes
        for n in ast.walk(no))


def _nomes_das_marcas(alvo) -> set[str]:
    marcas = getattr(alvo, "pytestmark", [])
    if not isinstance(marcas, (list, tuple)):
        marcas = [marcas]
    return {getattr(m, "name", None) or getattr(getattr(m, "mark", None), "name", None)
            for m in marcas}


def _sem_marcador() -> list[str]:
    faltando: list[str] = []
    for arquivo in sorted(TESTES.glob("test_*.py")):
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        ajudantes = {n.name for n in arvore.body
                     if isinstance(n, _FUNCOES) and not n.name.startswith("test_")
                     and _pede_o_driver(n)}
        no_modulo = any(_pede_o_driver(n) for n in arvore.body
                        if not isinstance(n, (*_FUNCOES, ast.ClassDef)))
        alvos: list[tuple[str | None, str]] = []      # (classe, teste)
        for n in arvore.body:
            if isinstance(n, _FUNCOES) and n.name.startswith("test_"):
                if _pede_o_driver(n) or _chama_algum(n, ajudantes):
                    alvos.append((None, n.name))
            elif isinstance(n, ast.ClassDef):
                for m in n.body:
                    if (isinstance(m, _FUNCOES) and m.name.startswith("test_")
                            and (_pede_o_driver(m) or _chama_algum(m, ajudantes))):
                        alvos.append((n.name, m.name))
        if not alvos and not no_modulo:
            continue
        modulo = importlib.import_module(f"tests.{arquivo.stem}")
        do_modulo = _nomes_das_marcas(modulo)
        if no_modulo and "postgres" not in do_modulo:
            faltando.append(f"{arquivo.name} (importorskip no nível do módulo)")
        for classe, nome in alvos:
            dono = getattr(modulo, classe) if classe else modulo
            marcas = do_modulo | _nomes_das_marcas(getattr(dono, nome))
            if classe:
                marcas |= _nomes_das_marcas(dono)
            if "postgres" not in marcas:
                faltando.append(f"{arquivo.name}::{classe + '::' if classe else ''}{nome}")
    return faltando


def test_teste_que_pula_sem_o_psycopg_leva_o_marcador_postgres():
    faltando = _sem_marcador()
    assert not faltando, (
        "pulam sem o psycopg (job test-backend) e não são selecionados pelo -m postgres "
        f"(job do PostgreSQL) — nunca rodam no CI; marque com @pytest.mark.postgres: {faltando}")


def test_a_catraca_enxerga_o_teste_do_engine_do_app_em_postgresql():
    """A catraca não é inócua: o caso que motivou a regra está entre os que ela confere."""
    arvore = ast.parse((TESTES / "test_database_ping_ocioso.py").read_text(encoding="utf-8"))
    alvo = next(n for n in arvore.body if isinstance(n, _FUNCOES)
                and n.name == "test_o_engine_do_app_em_postgresql_ganha_o_ping_por_ociosidade_e_o_lifo")
    assert _pede_o_driver(alvo)
    arvore = ast.parse((TESTES / "test_database_connect_timeout.py").read_text(encoding="utf-8"))
    ajudantes = {n.name for n in arvore.body if isinstance(n, _FUNCOES)
                 and not n.name.startswith("test_") and _pede_o_driver(n)}
    assert "_exigir_driver" in ajudantes
