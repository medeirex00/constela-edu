"""Trava da escola para a revogação dos cartões do Quest por turma (S_G_QUEST-2).

``bloquear_escola_para_cartoes_quest`` (4715) serializa as revogações de turma da
mesma escola: sem ela, duas turmas regeneradas juntas com troca cruzada de crianças
travavam as credenciais em ordens opostas e o PostgreSQL abortava uma (o teste com
PostgreSQL real é ``test_aud3_quest_regenerar_concorrente_pg.py``). Aqui:

- a trava recusa a sessão em AUTOCOMMIT e, com transação, executa o advisory lock
  no namespace dela (como as de importação, coleta e recálculo);
- a rota toma a trava ANTES de revogar qualquer credencial, no ``regenerar`` e no
  ``rotacionar_codigo``; a reimpressão não a toma.

Dados 100% fictícios.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.database import (
    _NS_CARTOES_QUEST,
    _NS_COLETA_AVALIACAO,
    _NS_IMPORTACAO,
    _NS_RECALCULO,
    bloquear_escola_para_cartoes_quest,
    sessao_de_leitura,
)
from app.core.migracoes import _NS_MIGRACAO
from app.quest.routers import professor
from app.quest.services import credenciais as svc_cred

URL_PG = os.environ.get("TEST_DATABASE_URL_PG", "")


class _SessaoFalsa:
    """Sessão que se diz PostgreSQL, sem banco de rede."""

    def __init__(self, *, isolamento: str | None, autocommit: bool):
        self.executados: list = []
        self._conexao = SimpleNamespace(
            get_execution_options=lambda: ({"isolation_level": isolamento} if isolamento else {}),
            connection=SimpleNamespace(dbapi_connection=SimpleNamespace(autocommit=autocommit)))

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def connection(self):
        return self._conexao

    def execute(self, *args, **kwargs):
        self.executados.append(args)


def test_namespace_proprio_sem_colidir_com_as_outras_travas():
    assert _NS_CARTOES_QUEST not in {_NS_IMPORTACAO, _NS_COLETA_AVALIACAO, _NS_RECALCULO,
                                     _NS_MIGRACAO}


@pytest.mark.parametrize("isolamento,autocommit", [("AUTOCOMMIT", True), (None, True),
                                                   ("AUTOCOMMIT", False)])
def test_trava_recusa_sessao_em_autocommit(isolamento, autocommit):
    db = _SessaoFalsa(isolamento=isolamento, autocommit=autocommit)
    with pytest.raises(RuntimeError, match="AUTOCOMMIT"):
        bloquear_escola_para_cartoes_quest(db, 4343)
    assert db.executados == []


def test_trava_com_transacao_executa_o_advisory_lock():
    db = _SessaoFalsa(isolamento=None, autocommit=False)
    bloquear_escola_para_cartoes_quest(db, 4343)
    assert len(db.executados) == 1
    sql, parametros = db.executados[0]
    assert "pg_advisory_xact_lock" in str(sql)
    assert list(parametros.values()) == [_NS_CARTOES_QUEST, 4343]


def _espiar(monkeypatch) -> list[str]:
    """Ordem em que a rota trava a escola e revoga cada grupo de credenciais."""
    passos: list[str] = []

    def _embrulhar(modulo, nome, rotulo):
        original = getattr(modulo, nome)

        def _espia(*args, **kwargs):
            passos.append(rotulo)
            return original(*args, **kwargs)

        monkeypatch.setattr(modulo, nome, _espia)

    _embrulhar(professor, "bloquear_escola_para_cartoes_quest", "trava")
    _embrulhar(svc_cred, "revogar_cartoes_inativos_da_turma", "inativos")
    _embrulhar(svc_cred, "revogar_cartoes_que_sairam_da_turma", "quem_saiu")
    _embrulhar(svc_cred, "garantir_credenciais_turma", "matriculados")
    return passos


@pytest.mark.parametrize("consulta", ["?regenerar=true", "?rotacionar_codigo=true"])
def test_revogacao_da_turma_trava_a_escola_antes_de_revogar(cliente, escola_completa,
                                                            monkeypatch, consulta):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    rota = f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/cartoes"
    assert cliente.post(rota).status_code == 200
    passos = _espiar(monkeypatch)

    r = cliente.post(rota + consulta)

    assert r.status_code == 200, r.text
    assert passos == ["trava", "inativos", "quem_saiu", "matriculados"]


def test_reimpressao_nao_trava_a_escola(cliente, escola_completa, monkeypatch):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    passos = _espiar(monkeypatch)

    r = cliente.post(f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/cartoes")

    assert r.status_code == 200, r.text
    assert passos == ["matriculados"]


# --- PostgreSQL de verdade -----------------------------------------------------------------

def _so_no_pg(teste):
    for marca in (pytest.mark.postgres,
                  pytest.mark.skipif(not URL_PG, reason="defina TEST_DATABASE_URL_PG"),
                  pytest.mark.skipif(bool(URL_PG) and "test" not in (make_url(URL_PG).database or ""),
                                     reason="o nome do banco PG de teste precisa conter 'test'")):
        teste = marca(teste)
    return teste


@pytest.fixture(scope="module")
def motor():
    m = create_engine(URL_PG, pool_size=4, max_overflow=0)
    yield m
    m.dispose()


def _outro_consegue(motor, chave: int) -> bool:
    with motor.connect() as c:
        ok = c.execute(text("SELECT pg_try_advisory_xact_lock(:ns, :k)"),
                       {"ns": _NS_CARTOES_QUEST, "k": chave}).scalar()
        c.rollback()
    return bool(ok)


@_so_no_pg
def test_pg_trava_vale_ate_o_fim_da_transacao(motor):
    with Session(motor) as db:
        bloquear_escola_para_cartoes_quest(db, 4242)
        assert _outro_consegue(motor, 4242) is False
        assert _outro_consegue(motor, 4243) is True      # outra escola segue livre
        db.rollback()
    assert _outro_consegue(motor, 4242) is True


@_so_no_pg
def test_pg_sessao_de_leitura_em_autocommit_e_recusada(motor):
    db = sessao_de_leitura(motor)()
    try:
        with pytest.raises(RuntimeError, match="AUTOCOMMIT"):
            bloquear_escola_para_cartoes_quest(db, 4343)
    finally:
        db.close()
    assert _outro_consegue(motor, 4343) is True
