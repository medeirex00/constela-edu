"""Sondas de saúde com o banco FORA: o traceback sai na queda, e a volta fica no log.

``Prontidao.avaliar`` (``/api/health/ready``) e ``_banco_ok`` (``/api/health``) faziam
``logger.exception`` a cada sonda com o banco inacessível — um traceback em ERROR (e um
evento no Sentry) a cada poucos segundos — e, como o motivo "banco_inacessivel" nunca era
registrado, a volta do banco não deixava linha nenhuma (auditoria, achado
OBSERVABILIDADE-7). Dados fictícios; os bancos são SQLite em diretório temporário.
"""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.main as main_mod
from app.core import migracoes
from app.core import prontidao as modulo
from app.core.prontidao import Prontidao

cliente = TestClient(main_mod.app)


@pytest.fixture
def bancos(tmp_path):
    fora = create_engine(f"sqlite:///{(tmp_path / 'nao' / 'existe' / 'banco.db').as_posix()}")
    bom = create_engine(f"sqlite:///{(tmp_path / 'bom.db').as_posix()}")
    heads, _ = migracoes._revisoes_do_codigo()
    with bom.begin() as c:   # banco "em dia": alembic_version com as heads do código
        c.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        for h in heads:
            c.exec_driver_sql(f"INSERT INTO alembic_version VALUES ('{h}')")
    yield fora, bom
    fora.dispose()
    bom.dispose()


@pytest.fixture
def processo_novo(monkeypatch):
    nova = Prontidao()
    monkeypatch.setattr(main_mod, "prontidao", nova)
    return nova


def _sessao_em(engine):
    def get_db():
        db = Session(bind=engine)
        try:
            yield db
        finally:
            db.close()
    return get_db


def _com_traceback(registros):
    return [r for r in registros if r.levelno >= logging.ERROR and r.exc_info]


def test_banco_fora_loga_o_traceback_uma_vez_e_a_volta_aparece(bancos, caplog):
    fora, bom = bancos
    p = Prontidao()
    caplog.set_level(logging.INFO, logger="constela")
    assert p.avaliar(bom)[1] == "em_dia"
    caplog.clear()
    for _ in range(10):                      # 10 sondas com o banco fora
        assert p.avaliar(fora)[1] == "banco_inacessivel"
    assert len(_com_traceback(caplog.records)) == 1, \
        "cada sonda com o banco fora escreveu um traceback ERROR"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR and not r.exc_info]
    caplog.clear()
    assert p.avaliar(bom)[1] == "em_dia"     # o banco voltou
    mensagens = [r.getMessage() for r in caplog.records]
    assert any("voltou a responder" in m for m in mensagens), mensagens
    assert any(m.startswith("Schema em dia") for m in mensagens), mensagens
    assert all(r.levelno == logging.INFO for r in caplog.records)
    caplog.clear()
    assert p.avaliar(bom)[1] == "em_dia"     # em dia de novo: nada a dizer
    assert not caplog.records


def test_queda_seguinte_volta_a_gerar_o_traceback(bancos, caplog):
    fora, bom = bancos
    p = Prontidao()
    caplog.set_level(logging.INFO, logger="constela")
    for _ in range(2):                       # duas quedas, cada uma com a sua volta
        for _ in range(3):
            p.avaliar(fora)
        p.avaliar(bom)
    assert len(_com_traceback(caplog.records)) == 2
    assert sum("voltou a responder" in r.getMessage() for r in caplog.records) == 2


def test_banco_fora_por_muito_tempo_ganha_lembrete_curto(bancos, caplog, monkeypatch):
    fora, _ = bancos
    agora = [1000.0]
    monkeypatch.setattr(modulo.time, "monotonic", lambda: agora[0])
    p = Prontidao()
    caplog.set_level(logging.INFO, logger="constela")
    p.avaliar(fora)
    for _ in range(5):                       # dentro da janela: silêncio
        agora[0] += 10
        p.avaliar(fora)
    assert len(caplog.records) == 1
    agora[0] = 1000.0 + modulo.AVISO_BANCO_FORA_S
    p.avaliar(fora)
    p.avaliar(fora)
    lembretes = caplog.records[1:]
    assert len(lembretes) == 1
    assert lembretes[0].levelno == logging.WARNING and not lembretes[0].exc_info
    assert "continua inacessível" in lembretes[0].getMessage()


def test_health_publico_tambem_loga_so_a_queda_e_a_volta(bancos, processo_novo,
                                                          monkeypatch, caplog):
    fora, bom = bancos
    caplog.set_level(logging.INFO, logger="constela")
    monkeypatch.setattr(main_mod, "get_db", _sessao_em(fora))
    for _ in range(5):
        r = cliente.get("/api/health")
        assert r.status_code == 503 and r.json()["banco"] == "inacessivel"
    assert len(_com_traceback(caplog.records)) == 1
    caplog.clear()
    monkeypatch.setattr(main_mod, "get_db", _sessao_em(bom))
    assert cliente.get("/api/health").status_code == 200
    assert any("voltou a responder" in r.getMessage() for r in caplog.records)


def test_as_duas_sondas_dividem_a_mesma_queda(bancos, processo_novo, monkeypatch, caplog):
    """O /api/health e o /api/health/ready veem o mesmo banco: uma queda, um traceback."""
    fora, _ = bancos
    caplog.set_level(logging.INFO, logger="constela")
    monkeypatch.setattr(main_mod, "get_db", _sessao_em(fora))
    monkeypatch.setattr(main_mod, "engine", fora)
    for _ in range(3):
        assert cliente.get("/api/health").status_code == 503
        assert cliente.get("/api/health/ready").status_code == 503
    assert len(_com_traceback(caplog.records)) == 1
