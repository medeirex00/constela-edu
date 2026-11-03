"""Cabeçalhos de segurança da API, /docs fechado por padrão e CORS intacto.

A API não mandava nenhum cabeçalho de segurança. Agora: nosniff, X-Frame-Options
DENY, Referrer-Policy no-referrer, HSTS quando chega por HTTPS (ou em produção) e
CSP restritiva só no JSON — sem quebrar CORS (fica por fora), os downloads de
PDF/XLSX nem o app desktop (Tauri, cross-origin).
"""
import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient

from app.core import observabilidade as obs
from app.core.cabecalhos import CSP_JSON, HSTS, CabecalhosSegurancaMiddleware
from app.core.config import Settings, settings
from app.main import app

cliente = TestClient(app)


def test_json_traz_todos_os_cabecalhos_e_csp():
    r = cliente.get("/api/health/live")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["content-security-policy"] == CSP_JSON


def test_erro_json_tambem_recebe_os_cabecalhos():
    r = cliente.get("/api/v1/sistema/diagnostico")          # 401 em JSON
    assert r.status_code == 401
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["content-security-policy"] == CSP_JSON


def test_hsts_so_quando_chega_por_https(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "dev")
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
    assert "strict-transport-security" not in cliente.get("/api/health/live").headers
    via_proxy = cliente.get("/api/health/live", headers={"X-Forwarded-Proto": "https"})
    assert via_proxy.headers["strict-transport-security"] == HSTS
    # Cada proxy confiável acrescenta à direita: vale a entrada do último salto.
    assert "strict-transport-security" not in cliente.get(
        "/api/health/live", headers={"X-Forwarded-Proto": "https, http"}).headers
    direto = TestClient(app, base_url="https://testserver").get("/api/health/live")
    assert direto.headers["strict-transport-security"] == HSTS


def test_hsts_ignora_x_forwarded_proto_sem_proxy_confiavel(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "dev")
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 0)
    r = cliente.get("/api/health/live", headers={"X-Forwarded-Proto": "https"})
    assert "strict-transport-security" not in r.headers


def test_hsts_sempre_em_producao(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "producao")
    assert cliente.get("/api/health/live").headers["strict-transport-security"] == HSTS


def test_download_de_pdf_sem_csp_e_com_anexo_intacto(cliente, escola_completa,
                                                     monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "EXPORTS_DIR", tmp_path)
    escola_id = escola_completa["escola"].id
    r = cliente.get(f"/api/v1/escolas/{escola_id}/relatorios/alunos?formato=pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert r.headers["content-type"].startswith("application/pdf")
    assert "attachment" in r.headers.get("content-disposition", "")
    assert "content-security-policy" not in r.headers      # CSP só no JSON
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def _mini():
    mini = FastAPI()

    @mini.get("/pdf")
    def pdf():
        return Response(b"%PDF-1.4", media_type="application/pdf")

    @mini.get("/proprio")
    def proprio():
        return Response("{}", media_type="application/json",
                        headers={"X-Frame-Options": "SAMEORIGIN"})

    @mini.get("/boom")
    def boom():
        raise RuntimeError("explodiu de propósito")

    mini.add_middleware(obs.ObservabilidadeMiddleware, settings=settings)
    mini.add_middleware(CabecalhosSegurancaMiddleware, settings=settings)
    return TestClient(mini, raise_server_exceptions=False)


def test_cabecalho_definido_pela_rota_e_respeitado():
    r = _mini().get("/proprio")
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert r.headers["content-security-policy"] == CSP_JSON


def test_500_da_rede_de_seguranca_recebe_os_cabecalhos():
    r = _mini().get("/boom")
    assert r.status_code == 500
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["content-security-policy"] == CSP_JSON


# --- CORS continua por fora ------------------------------------------------------

@pytest.mark.parametrize("origem", ["https://www.constelaedu.com", "tauri://localhost",
                                    "http://tauri.localhost"])
def test_cors_permitido_segue_igual_e_convive_com_os_cabecalhos(origem):
    pre = cliente.options("/api/v1/auth/login", headers={
        "Origin": origem, "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 200
    assert pre.headers["access-control-allow-origin"] == origem
    r = cliente.get("/api/health/live", headers={"Origin": origem})
    assert r.headers["access-control-allow-origin"] == origem
    assert "x-request-id" in r.headers["access-control-expose-headers"].lower()
    assert r.headers["x-frame-options"] == "DENY"


def test_cors_origem_estranha_recebe_400_sem_allow_origin():
    pre = cliente.options("/api/v1/auth/login", headers={
        "Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 400
    assert "access-control-allow-origin" not in pre.headers


# --- /docs, /redoc e /openapi.json fechados por padrão -----------------------------

def test_docs_desligados_por_padrao():
    assert Settings().DOCS_HABILITADOS is False
    for rota in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        assert cliente.get(rota).status_code == 404, rota
