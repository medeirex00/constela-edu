"""Observabilidade: health checks, métricas, IDs de correlação, logs JSON."""
import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import observabilidade as obs
from app.core.config import settings
from app.core.security import criar_token
from app.main import app

cliente = TestClient(app)


# --- Health checks -----------------------------------------------------------

def test_health_live_nao_toca_no_banco():
    r = cliente.get("/api/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["versao"]


def test_health_ready_confere_o_banco():
    r = cliente.get("/api/health/ready")
    assert r.status_code == 200 and r.json()["banco"] == "ok"


def test_health_geral_traz_versao_uptime_e_banco():
    corpo = cliente.get("/api/health").json()
    assert corpo["status"] == "ok"
    assert corpo["banco"] == "ok" and corpo["versao"] and "uptime_s" in corpo


# --- Métricas Prometheus -----------------------------------------------------

def test_metrics_no_formato_prometheus():
    r = cliente.get("/metrics")
    assert r.status_code == 200
    assert "http_requisicoes_total" in r.text
    assert "http_duracao_segundos" in r.text
    assert r.headers["content-type"].startswith("text/plain")


# --- Cardinalidade de métricas (rota não casada / 404) -----------------------

def test_rota_nao_casada_vira_no_match():
    """404 / caminho inexistente NUNCA vira label bruto (explosão de
    cardinalidade no Prometheus): sempre o rótulo fixo "<no_match>"."""
    assert obs._rota_de({"path": "/aaa"}) == "<no_match>"
    assert obs._rota_de({"path": "/bbb/123/xyz"}) == "<no_match>"
    assert obs._rota_de({}) == "<no_match>"

    class _Rota:
        path = "/escolas/{escola_id}/dashboard"

    assert obs._rota_de({"route": _Rota()}) == "/escolas/{escola_id}/dashboard"


def test_metricas_de_404_nao_usam_o_caminho_bruto():
    """Dois caminhos inexistentes DISTINTOS geram a MESMA série "<no_match>" —
    não uma por caminho. Limita a cardinalidade (defesa contra DoS de memória)."""
    cliente.get("/rota-que-nao-existe-aaa")
    cliente.get("/rota-que-nao-existe-bbb")
    corpo = obs.render_metricas()[0].decode()
    assert 'rota="<no_match>"' in corpo
    assert "rota-que-nao-existe-aaa" not in corpo
    assert "rota-que-nao-existe-bbb" not in corpo


# --- Request id / Correlation id ---------------------------------------------

def test_request_id_no_header_e_unico_por_requisicao():
    a = cliente.get("/api/health/live").headers["x-request-id"]
    b = cliente.get("/api/health/live").headers["x-request-id"]
    assert len(a) == 32 and a != b


def test_correlation_id_ecoa_quando_enviado_senao_vira_o_request_id():
    r = cliente.get("/api/health/live", headers={"X-Correlation-ID": "corr-xyz"})
    assert r.headers["x-correlation-id"] == "corr-xyz"
    r2 = cliente.get("/api/health/live")
    assert r2.headers["x-correlation-id"] == r2.headers["x-request-id"]


# --- Formatador JSON ---------------------------------------------------------

def _registro(msg="oi", **extra) -> logging.LogRecord:
    rec = logging.LogRecord("teste", logging.INFO, __file__, 1, msg, (), None)
    for chave, valor in extra.items():
        setattr(rec, chave, valor)
    return rec


def test_log_vira_json_valido_com_campos_extra():
    linha = obs.FormatadorJson().format(_registro("http_acesso", metodo="GET", status=200))
    d = json.loads(linha)
    assert d["nivel"] == "INFO" and d["msg"] == "http_acesso"
    assert d["metodo"] == "GET" and d["status"] == 200 and "ts" in d


def test_log_json_embute_o_contexto_da_requisicao():
    t1 = obs.ctx_request_id.set("req-1")
    t2 = obs.ctx_escola_id.set(7)
    t3 = obs.ctx_usuario_id.set(42)
    t4 = obs.ctx_rota.set("/api/v1/escolas/{escola_id}/alunos")
    try:
        d = json.loads(obs.FormatadorJson().format(_registro("x")))
    finally:
        obs.ctx_request_id.reset(t1)
        obs.ctx_escola_id.reset(t2)
        obs.ctx_usuario_id.reset(t3)
        obs.ctx_rota.reset(t4)
    assert d["request_id"] == "req-1" and d["escola_id"] == 7
    assert d["usuario_id"] == 42 and d["rota"].endswith("/alunos")


def test_log_json_captura_a_excecao():
    try:
        raise ValueError("estourou")
    except ValueError:
        import sys
        rec = logging.LogRecord("t", logging.ERROR, __file__, 1, "erro", (), sys.exc_info())
    d = json.loads(obs.FormatadorJson().format(rec))
    assert "excecao" in d and "ValueError" in d["excecao"]


# --- Extração de contexto ----------------------------------------------------

def test_escola_id_extraido_do_caminho():
    assert obs._escola_id_do_caminho("/api/v1/escolas/9/alunos") == 9
    assert obs._escola_id_do_caminho("/api/v1/auth/login") is None


def test_usuario_id_extraido_do_token():
    headers = {b"authorization": f"Bearer {criar_token(123, 0)}".encode()}
    assert obs._usuario_id_do_token(headers) == 123
    assert obs._usuario_id_do_token({}) is None
    assert obs._usuario_id_do_token({b"authorization": b"Bearer invalido"}) is None


# --- Rede de segurança de 500 ------------------------------------------------

def test_log_de_acesso_carrega_usuario_escola_rota_e_duracao(cliente, escola_completa):
    """O log de acesso de uma requisição autenticada traz usuario_id, escola_id
    e rota — é o que dá "logs por usuário / escola / rota"."""
    import io

    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(obs.FormatadorJson())
    # Handler direto no logger do middleware (não no root) para não depender da
    # captura de log do pytest; nível INFO porque o acesso de um 200 é INFO.
    log_http = logging.getLogger("constela.http")
    nivel_original = log_http.level
    log_http.setLevel(logging.INFO)
    log_http.addHandler(handler)
    try:
        escola_id = escola_completa["escola"].id
        assert cliente.get(f"/api/v1/escolas/{escola_id}/dashboard").status_code == 200
    finally:
        log_http.removeHandler(handler)
        log_http.setLevel(nivel_original)

    linhas = [json.loads(l) for l in buffer.getvalue().splitlines()
              if l.strip().startswith("{")]
    acessos = [l for l in linhas if l.get("msg") == "http_acesso"]
    assert acessos, "nenhum log de acesso foi emitido"
    ev = acessos[-1]
    assert ev["escola_id"] == escola_id
    assert ev["usuario_id"] == escola_completa["admin"].id
    assert ev["rota"].endswith("/dashboard") and ev["status"] == 200
    assert "request_id" in ev and "dur_ms" in ev


def test_excecao_nao_tratada_vira_500_generico_com_request_id():
    mini = FastAPI()
    mini.add_middleware(obs.ObservabilidadeMiddleware, settings=settings)

    @mini.get("/boom")
    def boom():
        raise RuntimeError("explodiu de propósito")

    c = TestClient(mini, raise_server_exceptions=False)
    r = c.get("/boom")
    assert r.status_code == 500
    assert r.json() == {"detail": "Erro interno. Tente novamente em instantes."}
    assert "x-request-id" in {k.lower() for k in r.headers}


# --- Sentry: minimização de PII (R2) -----------------------------------------

def test_sentry_desliga_variaveis_locais_e_pii(monkeypatch):
    """Frame-locals podem carregar PII de menor (bytes do arquivo, filename,
    linhas parseadas com nomes). O init do Sentry deve desligá-los; e
    send_default_pii permanece False. send_default_pii=False NÃO cobre locais."""
    capturado: dict = {}

    class _FakeSentry:
        def init(self, **kwargs):
            capturado.update(kwargs)

    monkeypatch.setattr(obs, "_sentry", _FakeSentry())
    monkeypatch.setattr(obs, "_sentry_ativo", False)

    class _Cfg:
        SENTRY_DSN = "https://exemplo@sentry.local/1"
        SENTRY_ENVIRONMENT = ""
        ENV = "producao"
        APP_VERSION = "test"
        SENTRY_TRACES_SAMPLE_RATE = 0.0

    obs.configurar_sentry(_Cfg())

    assert capturado.get("include_local_variables") is False
    assert capturado.get("send_default_pii") is False
    # O corpo da requisição NUNCA vai ao Sentry (token de reset + senha nova).
    assert capturado.get("max_request_body_size") == "never"
    # O init registra o higienizador de URL/query nos dois canais de envio.
    assert capturado.get("before_send") is obs.higienizar_evento_sentry
    assert capturado.get("before_send_transaction") is obs.higienizar_evento_sentry


# --- Redação de token em log e Sentry (LGPD) ---------------------------------

def test_redigir_caminho_cobre_painel_e_reset_de_senha():
    """Os dois tokens de rota somem do log de erro (nomes/notas de criança e
    tomada de conta são o que estaria em jogo)."""
    assert obs.redigir_caminho("/api/v1/publico/abc123/ranking") == \
        "/api/v1/publico/<token>/ranking"
    assert obs.redigir_caminho("/api/v1/auth/redefinir-senha/SEGREDO") == \
        "/api/v1/auth/redefinir-senha/<token>"
    # Caminho sem token não é alterado.
    assert obs.redigir_caminho("/api/v1/escolas/1/alunos") == \
        "/api/v1/escolas/1/alunos"


def test_higienizar_evento_sentry_redige_url_e_query():
    """Antes de sair para o Sentry, a URL crua perde o token de rota e a query
    string inteira (onde ?busca=/?qr= poderiam levar nome/código de criança)."""
    evento = {
        "request": {
            "url": "https://api.local/api/v1/auth/redefinir-senha/SEGREDO",
            "query_string": "busca=AGATHA",
            "method": "GET",
        },
    }
    saida = obs.higienizar_evento_sentry(evento, None)
    assert saida["request"]["url"].endswith("/redefinir-senha/<token>")
    assert "SEGREDO" not in saida["request"]["url"]
    assert saida["request"]["query_string"] == "<redigido>"


def test_higienizar_evento_sentry_tolera_evento_sem_request():
    """Evento sem contexto de requisição (ex.: erro de tarefa de fundo) passa
    intacto — o higienizador nunca pode quebrar o envio."""
    assert obs.higienizar_evento_sentry({}, None) == {}
    assert obs.higienizar_evento_sentry({"request": None}, None) == {"request": None}
