"""A preparação do contexto da requisição nunca derruba a requisição.

O ``ObservabilidadeMiddleware`` extraía o id da escola do caminho (``int()`` sem teto) e o
usuário do token ANTES do ``try`` da rede de segurança de 500. O Python recusa converter
texto com mais de 4300 dígitos: ``GET /api/v1/escolas/<4301 dígitos>/...``, sem login,
escapava do middleware — 500 em texto puro, sem X-Request-ID, sem CORS nem cabeçalhos de
segurança, e um traceback "Exception in ASGI application" em ERROR a cada pedido
(auditoria, achado OBSERVABILIDADE-1). Dados fictícios.
"""
import logging

from fastapi.testclient import TestClient

from app.core import observabilidade as obs
from app.core.config import settings
from app.main import app

ORIGEM = settings.CORS_ORIGINS[0]


def test_id_de_escola_gigante_nao_vira_numero():
    assert obs._escola_id_do_caminho("/api/v1/escolas/" + "1" * 4301 + "/turmas") is None
    assert obs._escola_id_do_caminho("/api/v1/escolas/" + "1" * 19) is None
    # Ids de verdade continuam valendo, com ou sem resto no caminho.
    assert obs._escola_id_do_caminho("/api/v1/escolas/" + "9" * 18 + "/x") == int("9" * 18)
    assert obs._escola_id_do_caminho("/api/v1/escolas/9/alunos") == 9
    assert obs._escola_id_do_caminho("/api/v1/escolas/9") == 9
    assert obs._escola_id_do_caminho("/api/v1/auth/login") is None


def test_caminho_com_id_gigante_passa_pela_rede_de_seguranca(db, caplog):
    caplog.set_level(logging.INFO)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/api/v1/escolas/" + "1" * 4301 + "/turmas", headers={"Origin": ORIGEM})
    cab = {k.lower(): v for k, v in r.headers.items()}
    assert "x-request-id" in cab, "a resposta saiu sem passar pelo ObservabilidadeMiddleware"
    assert cab.get("access-control-allow-origin") == ORIGEM
    assert cab.get("x-content-type-options") == "nosniff"
    assert r.status_code < 500, f"{r.status_code} {r.text[:80]}"
    assert not [rec for rec in caplog.records if rec.levelno >= logging.ERROR]


def test_falha_inesperada_no_contexto_nao_derruba_a_requisicao(db, monkeypatch, caplog):
    """Defesa: qualquer falha ao montar o contexto (só serve ao rastreio) vira contexto
    vazio e um aviso — a requisição segue."""
    def quebra(*_args, **_kwargs):
        raise RuntimeError("falha fictícia ao ler o token")

    monkeypatch.setattr(obs, "_usuario_id_do_token", quebra)
    caplog.set_level(logging.INFO)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/api/health/live", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert "x-request-id" in {k.lower() for k in r.headers}
    avisos = [rec for rec in caplog.records if rec.getMessage() == "contexto_da_requisicao_falhou"]
    assert avisos and avisos[0].levelno == logging.WARNING
