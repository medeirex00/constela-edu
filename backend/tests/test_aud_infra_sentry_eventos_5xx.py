"""Quantos eventos o Sentry recebe por resposta 5xx.

O log de ACESSO de toda resposta >= 500 sai em ERROR (``ObservabilidadeMiddleware.
_registrar``; o JSON do Railway marca a severidade) e a LoggingIntegration do sentry-sdk
transforma todo registro ERROR em evento: cada 5xx virava MAIS um evento "http_acesso",
sem exceção e com todos agrupados na mesma issue. E a integração do Starlette/FastAPI
capturava toda HTTPException de 500 a 599, inclusive os 502/503/504 que o sync devolve DE
PROPÓSITO (plataforma ou navegador indisponível): dois eventos por clique (auditoria,
achado OBSERVABILIDADE-8). SDK de verdade, com o envio trocado por um transporte em
memória; nada vai para a rede.
"""
import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core import observabilidade as obs


@pytest.fixture
def sentry_real(monkeypatch):
    sentry_sdk = pytest.importorskip("sentry_sdk")
    import sentry_sdk.utils as utilitarios
    from sentry_sdk.transport import Transport

    from app.core.config import settings
    dsn = "https://chaveficticia@sentry.exemplo.test/1"

    class _Transporte(Transport):
        def __init__(self):
            super().__init__({"dsn": dsn})
            self.envelopes = []

        def capture_envelope(self, envelope):
            self.envelopes.append(envelope)

    transporte = _Transporte()
    init_real = sentry_sdk.init

    class _SentryComTransporte:
        def __getattr__(self, nome):
            return getattr(sentry_sdk, nome)

        def init(self, **opcoes):
            return init_real(transport=transporte, **opcoes)

    monkeypatch.setattr(utilitarios, "get_error_message", utilitarios.get_error_message)
    monkeypatch.setattr(obs, "_sentry", _SentryComTransporte())
    monkeypatch.setattr(obs, "_sentry_ativo", False)
    monkeypatch.setattr(settings, "SENTRY_DSN", dsn)
    obs.configurar_sentry(settings)
    logging.getLogger("constela.http").setLevel(logging.INFO)
    try:
        yield transporte
    finally:
        sentry_sdk.get_client().close()
        sentry_sdk.get_global_scope().set_client(None)


def _eventos(transporte):
    import sentry_sdk
    sentry_sdk.flush()
    return [e for e in (env.get_event() for env in transporte.envelopes) if e]


def _resumo(eventos):
    return [(e.get("logger"), (e.get("logentry") or {}).get("message"),
             [v.get("type") for v in (e.get("exception") or {}).get("values", [])])
            for e in eventos]


def _app():
    from app.core.config import settings
    mini = FastAPI()
    mini.add_middleware(obs.ObservabilidadeMiddleware, settings=settings)

    @mini.get("/boom")
    def boom():
        raise RuntimeError("explodiu de propósito")

    @mini.get("/falha-declarada")
    def falha_declarada():
        raise HTTPException(500, "Falha declarada pelo código.")

    @mini.get("/upstream/{codigo}")
    def upstream(codigo: int):
        # Como o sync/router faz com a plataforma ou o navegador fora (502/503/504).
        raise HTTPException(codigo, "A plataforma não respondeu. Tente mais tarde.")

    return mini


def test_erro_nao_tratado_gera_um_evento_so(sentry_real):
    c = TestClient(_app(), raise_server_exceptions=False)
    assert c.get("/boom").status_code == 500
    eventos = _eventos(sentry_real)
    assert _resumo(eventos) == [("constela.http", "erro_nao_tratado", ["RuntimeError"])]


def test_502_503_504_esperados_nao_viram_evento(sentry_real, caplog):
    caplog.set_level(logging.INFO, logger="constela.http")
    c = TestClient(_app(), raise_server_exceptions=False)
    for codigo in (502, 503, 504):
        assert c.get(f"/upstream/{codigo}").status_code == codigo
    assert _resumo(_eventos(sentry_real)) == []
    # O log JSON continua marcando a severidade do acesso.
    acessos = [r for r in caplog.records if r.getMessage() == "http_acesso"]
    assert [r.levelno for r in acessos] == [logging.ERROR] * 3


def test_http_500_declarado_continua_virando_evento(sentry_real):
    c = TestClient(_app(), raise_server_exceptions=False)
    assert c.get("/falha-declarada").status_code == 500
    assert _resumo(_eventos(sentry_real)) == [(None, None, ["HTTPException"])]


def test_log_de_acesso_nao_vira_evento_e_os_outros_logs_sim(sentry_real):
    """O filtro é só do registro de acesso: um ERROR qualquer do mesmo logger segue."""
    lg = logging.getLogger("constela.http")
    lg.error("http_acesso", extra={"metodo": "GET", "rota": "/x", "status": 500})
    lg.error("outro_erro_do_middleware")
    assert _resumo(_eventos(sentry_real)) == [
        ("constela.http", "outro_erro_do_middleware", [])]
