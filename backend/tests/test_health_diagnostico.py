"""/api/health público e mínimo; o diagnóstico operacional só para admin global.

Auditoria de 20/10: o /api/health público devolvia o IP/ASN/cidade de SAÍDA do robô
(egress), o diagnóstico das páginas de login das plataformas, o estado do navegador e
do agendador. Agora o público diz só status, banco e versão; o resto está em
GET /api/v1/sistema/diagnostico, com a dependência ``exigir_admin_global``.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as main_mod
from app.core import automacao
from app.core.config import settings
from app.main import app
from tests._infra_comum import levar_a, pg_url, sondar  # noqa: F401 — fixture pg_url

_ROTA = "/api/v1/sistema/diagnostico"
_EGRESS_FICTICIO = {"ip": "203.0.113.7", "org": "AS64500 Provedor Ficticio",
                    "cidade": "Cidade Teste", "regiao": "XX", "pais": "ZZ"}
# O que NUNCA aparece na saúde pública, em ambiente nenhum (valores fictícios do robô
# e os nomes das chaves do diagnóstico).
_VAZAMENTOS = ("203.0.113.7", "AS64500", "Cidade Teste", "egress", "login", "automacao",
               "scheduler", "uptime", "revisoes", "armazenamento", "sentry", "cifra")


@pytest.fixture
def robo_com_diagnostico(monkeypatch):
    """Estado do robô como ficaria em produção depois do boot (valores fictícios)."""
    monkeypatch.setitem(automacao._estado, "navegador", True)
    monkeypatch.setitem(automacao._estado, "egress", dict(_EGRESS_FICTICIO))
    monkeypatch.setitem(automacao._estado, "login", {"matific": {"formulario": True}})


def test_health_publico_nao_expoe_o_diagnostico(robo_com_diagnostico):
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "banco": "ok", "versao": settings.APP_VERSION}
    for vazamento in ("203.0.113.7", "AS64500", "Cidade Teste", "egress", "login",
                      "automacao", "scheduler", "uptime"):
        assert vazamento not in r.text


@pytest.mark.parametrize("rota", ["/api/health/live", "/api/health/ready"])
def test_live_e_ready_continuam_publicos(rota):
    assert TestClient(app).get(rota).status_code == 200


# A produção roda SEM ENV (= "dev") e a A3 viu nela o /api/health com IP, cidade e org
# de saída e o /metrics aberto. A saúde pública não pode depender do ENV: o mesmo
# mínimo com ENV ausente, "dev" e "producao" — e /metrics e /docs fechados nos três.
@pytest.mark.parametrize("env", ["", "dev", "producao"])
def test_saude_publica_e_minima_em_qualquer_env(robo_com_diagnostico, monkeypatch, env):
    monkeypatch.setattr(settings, "ENV", env)
    monkeypatch.setattr(settings, "METRICS_TOKEN", "")
    monkeypatch.setattr(settings, "METRICS_PUBLICO", False)
    c = TestClient(app)
    saude = c.get("/api/health")
    assert saude.status_code == 200
    assert saude.json() == {"status": "ok", "banco": "ok", "versao": settings.APP_VERSION}
    live = c.get("/api/health/live")
    assert live.json() == {"status": "ok", "versao": settings.APP_VERSION}
    ready = c.get("/api/health/ready")
    assert ready.json() == {"status": "ok", "banco": "ok", "schema": "em_dia"}
    for r in (saude, live, ready):
        for vazamento in _VAZAMENTOS:
            assert vazamento not in r.text, (r.url, vazamento)
    assert c.get("/metrics").status_code == 404
    for rota in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(rota).status_code == 404, rota


def test_saude_publica_degradada_nao_expoe_detalhe(robo_com_diagnostico, monkeypatch):
    """Banco fora: 503 com o mesmo mínimo — o motivo do erro fica só no log."""
    monkeypatch.setattr(main_mod, "_banco_ok", lambda: False)
    r = TestClient(app).get("/api/health")
    assert r.status_code == 503
    assert r.json() == {"status": "degradado", "banco": "inacessivel",
                        "versao": settings.APP_VERSION}
    for vazamento in _VAZAMENTOS:
        assert vazamento not in r.text


@pytest.mark.postgres
def test_processo_de_producao_serve_a_saude_minima(pg_url):
    """Processo novo com ENV=producao (como o uvicorn no Railway) sobre o schema em dia:
    a saúde pública traz só status, banco e versão."""
    levar_a(pg_url, "heads")
    r = sondar(pg_url, producao=True)
    assert r["ready"] == 200 and r["ready_corpo"] == {"status": "ok", "banco": "ok",
                                                      "schema": "em_dia"}
    assert set(r["health"]) == {"status", "banco", "versao"}
    assert r["health"]["status"] == "ok" and r["health"]["banco"] == "ok"


def test_diagnostico_exige_login():
    assert TestClient(app).get(_ROTA).status_code == 401


def test_diagnostico_recusa_admin_de_escola(cliente):
    assert cliente.get(_ROTA).status_code == 403


def test_diagnostico_para_admin_global(cliente_global, robo_com_diagnostico, monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "token-de-teste-diagnostico")
    r = cliente_global.get(_ROTA)
    assert r.status_code == 200
    d = r.json()
    assert d["egress"] == _EGRESS_FICTICIO
    assert d["automacao_navegador"] is True and d["login_paginas"]
    assert d["scheduler_sync"] == {"habilitado": settings.SYNC_SCHEDULER_ENABLED,
                                   "ativo": False}
    assert d["schema"]["pronto"] is True and d["schema"]["motivo"] == "em_dia"
    assert d["versao"] == settings.APP_VERSION and d["uptime_s"] >= 0
    assert set(d["armazenamento"]) >= {"persistente", "volume", "pastas", "avisos"}
    assert d["metricas"]["token_configurado"] is True
    # Nenhum segredo: do token só se diz que existe; nada de URL do banco nem chave.
    assert "token-de-teste-diagnostico" not in r.text
    assert settings.SECRET_KEY not in r.text
    assert settings.DATABASE_URL not in r.text
