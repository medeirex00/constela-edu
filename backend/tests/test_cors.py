"""CORS: o default (no código) inclui as origens de produção cross-origin.

Regressão do B1 (go-live): um deploy Vercel+Railway sem CORS_ORIGINS no
ambiente NÃO pode subir bloqueando todas as chamadas do navegador. O default
vive no código (convenção §14, como PUBLIC_BASE_URL/QUEST_BASE_URL) — setar
CORS_ORIGINS no provedor passa a ser opcional (para restringir).
"""
from fastapi.testclient import TestClient

from app.main import app

_cliente = TestClient(app)


def _preflight(origem: str):
    return _cliente.options(
        "/api/v1/quest/auth/entrar",
        headers={"Origin": origem, "Access-Control-Request-Method": "POST"},
    )


def test_cors_default_inclui_producao_e_preserva_dev_e_desktop():
    # Settings() é reavaliado do zero: prova o DEFAULT, independente de env.
    from app.core.config import Settings

    origens = Settings().CORS_ORIGINS
    assert "https://www.constelaedu.com" in origens
    assert "https://quest.constelaedu.com" in origens
    # Regressão: dev web e desktop (Tauri) continuam permitidos.
    assert "http://localhost:5173" in origens
    assert "http://127.0.0.1:5173" in origens
    assert "tauri://localhost" in origens


def test_cors_preflight_permite_front_de_producao():
    r = _preflight("https://www.constelaedu.com")
    assert r.headers.get("access-control-allow-origin") == "https://www.constelaedu.com"
    assert r.headers.get("access-control-allow-credentials") == "true"


def test_cors_preflight_permite_quest_de_producao():
    r = _preflight("https://quest.constelaedu.com")
    assert r.headers.get("access-control-allow-origin") == "https://quest.constelaedu.com"


def test_cors_preflight_nega_origem_desconhecida():
    r = _preflight("https://evil.example.com")
    # Origem fora da allowlist não recebe o cabeçalho — o navegador bloqueia.
    assert r.headers.get("access-control-allow-origin") is None
