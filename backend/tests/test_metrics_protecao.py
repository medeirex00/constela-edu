"""/metrics fechado por padrão, sem depender do ENV.

A produção roda sem ENV (= "dev"): com a regra antiga ("sem token: aberto em dev,
404 em produção"), a telemetria Prometheus ficava pública na internet. Agora:
sem METRICS_TOKEN → 404 em qualquer ENV; só a opção explícita de desenvolvimento
METRICS_PUBLICO abre, e ela é ignorada com ENV=producao.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

cliente = TestClient(app)


@pytest.fixture
def sem_token(monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "")
    monkeypatch.setattr(settings, "METRICS_PUBLICO", False)


@pytest.mark.parametrize("env", ["dev", "", "producao"])
def test_sem_token_responde_404_em_qualquer_env(sem_token, monkeypatch, env):
    monkeypatch.setattr(settings, "ENV", env)
    r = cliente.get("/metrics")
    assert r.status_code == 404
    assert "http_requisicoes_total" not in r.text


def test_metrics_publico_abre_so_em_desenvolvimento(sem_token, monkeypatch):
    monkeypatch.setattr(settings, "METRICS_PUBLICO", True)
    monkeypatch.setattr(settings, "ENV", "dev")
    assert cliente.get("/metrics").status_code == 200
    # Em produção a opção de desenvolvimento não vale: continua fechado.
    monkeypatch.setattr(settings, "ENV", "producao")
    assert cliente.get("/metrics").status_code == 404


def test_com_token_exige_bearer_correto_mesmo_com_metrics_publico(monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "token-de-teste-metrics")
    monkeypatch.setattr(settings, "METRICS_PUBLICO", True)   # não afrouxa o token
    assert cliente.get("/metrics").status_code == 401
    assert cliente.get("/metrics", headers={"Authorization": "Basic x"}).status_code == 401
    assert cliente.get("/metrics", headers={
        "Authorization": "Bearer token-de-teste-metric"}).status_code == 401
    ok = cliente.get("/metrics", headers={"Authorization": "Bearer token-de-teste-metrics"})
    assert ok.status_code == 200 and "http_requisicoes_total" in ok.text


def test_token_com_caractere_nao_ascii_nao_vira_500(monkeypatch):
    """compare_digest com str não-ASCII levanta TypeError; a comparação é em bytes."""
    monkeypatch.setattr(settings, "METRICS_TOKEN", "token-de-teste-metrics")
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/metrics", headers={"Authorization": "Bearer ção".encode("utf-8")})
    assert r.status_code == 401
