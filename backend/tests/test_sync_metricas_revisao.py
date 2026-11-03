"""Métricas de sincronização: achados da revisão adversarial e95 corrigidos.

Cada teste FALHA no 2a14731 (ramo antes desta correção) e passa depois:

  1. prazo TOTAL do scrape: com o pool de conexões esgotado, o coletor (e a rota
     /metrics) respondem ``sync_coletor_sucesso 0`` dentro de ``PRAZO_COLETOR_S``
     em vez de esperar o ``pool_timeout`` inteiro (30 s em produção, acima dos
     10 s do Prometheus); enquanto a leitura atrasada não termina, o scrape
     seguinte responde 0 na hora (uma leitura por processo);
  3. ``sync_recalculo_pendente`` segue a regra do serviço por ESCOLA: a marca de
     recálculo continua visível depois de removida a credencial (o DELETE fecha o
     alerta, a marca fica) e vale qualquer plataforma da escola.

O orçamento por consulta no PostgreSQL está em ``test_sync_metricas_revisao_pg.py``.
Dados fictícios, sem rede.
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app.core.database import Base
from app.main import app
from app.sync import metricas, service
from tests import test_sync_metricas as base
from tests.test_sync_metricas import metricas_abertas  # noqa: F401  (fixture)


def _engine_com_pool_de_um(tmp_path, timeout_s):
    url = f"sqlite:///{(tmp_path / 'pool1.sqlite').as_posix()}"
    eng = create_engine(url, poolclass=QueuePool, pool_size=1, max_overflow=0,
                        pool_timeout=timeout_s, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return eng


def _esperar_leitura(coletor, limite_s=15):
    leitura = getattr(coletor, "_em_curso", None)
    if leitura is not None:
        leitura.join(limite_s)


# ---------------------------------------------------------------------------
# 1. Prazo total do scrape com o pool esgotado
# ---------------------------------------------------------------------------
def test_pool_esgotado_o_coletor_responde_dentro_do_prazo_total(tmp_path, monkeypatch):
    monkeypatch.setattr(metricas, "PRAZO_COLETOR_S", 1.0, raising=False)
    eng = _engine_com_pool_de_um(tmp_path, 6)
    preso = eng.connect()            # a aplicação segurando a única conexão do pool
    coletor = metricas.ColetorSync(fabrica=sessionmaker(bind=eng), relogio=lambda: base.T)
    try:
        t0 = time.perf_counter()
        a = base._amostras(coletor)
        dt = time.perf_counter() - t0
        assert base._v(a, "sync_coletor_sucesso") == 0
        assert dt < 3, dt            # antes: esperava o pool_timeout inteiro (6 s)
        # A leitura atrasada ainda espera o pool: o scrape seguinte não empilha
        # outra thread nem outra conexão — responde 0 na hora.
        t1 = time.perf_counter()
        b = base._amostras(coletor)
        assert base._v(b, "sync_coletor_sucesso") == 0
        assert time.perf_counter() - t1 < 0.5
    finally:
        preso.close()
        _esperar_leitura(coletor)
        eng.dispose()
    # Solto o pool, a leitura seguinte volta ao normal.
    eng2 = _engine_com_pool_de_um(tmp_path, 6)
    try:
        c = base._amostras(metricas.ColetorSync(fabrica=sessionmaker(bind=eng2),
                                                relogio=lambda: base.T))
        assert base._v(c, "sync_coletor_sucesso") == 1
    finally:
        eng2.dispose()


def test_rota_metrics_responde_dentro_do_prazo_com_pool_esgotado(
        tmp_path, monkeypatch, metricas_abertas):  # noqa: F811
    monkeypatch.setattr(metricas, "PRAZO_COLETOR_S", 1.0, raising=False)
    eng = _engine_com_pool_de_um(tmp_path, 6)
    preso = eng.connect()
    try:
        monkeypatch.setattr(metricas_abertas, "fabrica", sessionmaker(bind=eng))
        t0 = time.perf_counter()
        r = TestClient(app).get("/metrics", headers={"Authorization": f"Bearer {base.TOKEN}"})
        dt = time.perf_counter() - t0
    finally:
        preso.close()
        _esperar_leitura(metricas_abertas)      # o coletor GLOBAL fica livre para os outros
        eng.dispose()
    assert r.status_code == 200
    assert "sync_coletor_sucesso 0.0" in r.text and "http_requisicoes_total" in r.text
    assert dt < 3, dt


# ---------------------------------------------------------------------------
# 3. Marca de recálculo por escola (regra de service.recalculo_pendente_aberto)
# ---------------------------------------------------------------------------
def test_recalculo_pendente_continua_na_metrica_depois_de_remover_a_credencial(
        db, escola_completa, cliente):
    e = escola_completa["escola"].id
    base._cred(db, e, "matific", "valida")
    base._exec(db, e, "matific", "parcial", fim=base.T - base.H, recalculo=True)
    base._alerta(db, e, "matific", "recalculo_pendente", "critico")
    db.commit()
    a = base._amostras(base._coletor(db))
    assert base._v(a, "sync_recalculo_pendente", escola_id=str(e)) == 1

    r = cliente.delete(f"/api/v1/escolas/{e}/sync/credenciais/matific")   # a rota real
    assert r.status_code == 204, r.text
    db.expire_all()
    assert service.recalculo_pendente_aberto(db, e) is True
    a = base._amostras(base._coletor(db))
    assert base._v(a, "sync_coletor_sucesso") == 1
    assert base._v(a, "sync_recalculo_pendente", escola_id=str(e)) == 1   # antes: sumia


def test_recalculo_pendente_de_outra_plataforma_da_escola_conta(db, escola_completa):
    """A escola continua com o Elefante cadastrado; a marca é de uma execução do
    Matific, cuja credencial já não existe. Antes: a série dizia 0."""
    e = escola_completa["escola"].id
    base._cred(db, e, "elefante", "valida")
    base._exec(db, e, "elefante", "concluida", fim=base.T - base.H)
    base._exec(db, e, "matific", "parcial", fim=base.T - 2 * base.H, recalculo=True)
    db.commit()
    assert service.recalculo_pendente_aberto(db, e) is True
    a = base._amostras(base._coletor(db))
    assert base._v(a, "sync_recalculo_pendente", escola_id=str(e)) == 1
    # Controle: a marca zerada (recálculo que deu certo) volta a 0.
    service.resolver_recalculo_pendente(db, e)
    db.commit()
    a = base._amostras(base._coletor(db))
    assert base._v(a, "sync_recalculo_pendente", escola_id=str(e)) == 0
