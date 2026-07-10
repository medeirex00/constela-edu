"""Observabilidade do SaaS: logs estruturados, IDs de correlação, métricas e Sentry.

Peças:
  * `FormatadorJson` — cada log vira UMA linha JSON, já enriquecida com o
    contexto da requisição (request_id, correlation_id, usuario_id, escola_id,
    rota) via `contextvars`. Assim "logs por usuário/escola/rota" saem de graça:
    é só filtrar o campo no agregador (Loki, CloudWatch, Datadog…).
  * `ObservabilidadeMiddleware` — ASGI puro (não BaseHTTPMiddleware, para o
    contexto propagar até o handler mesmo em endpoints síncronos no threadpool).
    Gera request_id, aceita/gera correlation_id, mede a latência, emite o log de
    acesso, alimenta as métricas Prometheus e é a rede de segurança de 500.
  * Métricas Prometheus (`/metrics`): contagem, latência e requisições em curso
    por método/rota/status.
  * Sentry (opcional, ligado por `SENTRY_DSN`): erros e tracing de performance,
    com o usuário e a escola anexados ao evento.

Tudo é degradável: sem `sentry-sdk`/`prometheus-client` instalados, ou sem DSN,
as funções viram no-ops — nada quebra.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# --- Dependências opcionais (degradam para no-op se ausentes) -----------------
try:  # métricas
    import prometheus_client as _prom
except ImportError:  # pragma: no cover
    _prom = None

try:  # erros + tracing
    import sentry_sdk as _sentry
except ImportError:  # pragma: no cover
    _sentry = None


# --- Contexto da requisição (propaga por toda a stack via contextvars) --------
ctx_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
ctx_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
ctx_usuario_id: ContextVar[int | None] = ContextVar("usuario_id", default=None)
ctx_escola_id: ContextVar[int | None] = ContextVar("escola_id", default=None)
ctx_rota: ContextVar[str | None] = ContextVar("rota", default=None)

_CAMPOS_CONTEXTO = (
    ("request_id", ctx_request_id),
    ("correlation_id", ctx_correlation_id),
    ("usuario_id", ctx_usuario_id),
    ("escola_id", ctx_escola_id),
    ("rota", ctx_rota),
)


# --- Log estruturado em JSON --------------------------------------------------
# Atributos padrão do LogRecord — tudo que estiver ALÉM disso veio de
# `logger.info(..., extra={...})` e entra no JSON como campo próprio.
_ATRIBUTOS_PADRAO = frozenset(logging.LogRecord(
    "", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}


class FormatadorJson(logging.Formatter):
    """Uma linha JSON por evento, com o contexto da requisição embutido."""

    def format(self, record: logging.LogRecord) -> str:
        evento: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "nivel": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for nome, var in _CAMPOS_CONTEXTO:
            valor = var.get()
            if valor is not None:
                evento[nome] = valor
        for chave, valor in record.__dict__.items():
            if chave not in _ATRIBUTOS_PADRAO and not chave.startswith("_"):
                evento[chave] = valor
        if record.exc_info:
            evento["excecao"] = self.formatException(record.exc_info)
        return json.dumps(evento, ensure_ascii=False, default=str)


def configurar_logging(settings) -> None:
    """Instala o handler único (JSON em produção, texto legível em dev)."""
    raiz = logging.getLogger()
    raiz.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    for handler in list(raiz.handlers):
        raiz.removeHandler(handler)
    handler = logging.StreamHandler()
    if settings.LOG_JSON:
        handler.setFormatter(FormatadorJson())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    raiz.addHandler(handler)
    # Uvicorn: manda o log de erro para a nossa formatação; o de acesso é
    # substituído pelo nosso (mais rico) — suba com --no-access-log em produção.
    for nome in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(nome)
        lg.handlers = []
        lg.propagate = True


# --- Métricas (Prometheus) ----------------------------------------------------
if _prom is not None:
    _M_REQS = _prom.Counter(
        "http_requisicoes_total", "Total de requisições HTTP concluídas",
        ["metodo", "rota", "status"])
    _M_DUR = _prom.Histogram(
        "http_duracao_segundos", "Duração das requisições HTTP (s)",
        ["metodo", "rota"],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
    _M_ANDAMENTO = _prom.Gauge(
        "http_em_andamento", "Requisições HTTP em andamento", ["metodo"])
else:  # pragma: no cover
    _M_REQS = _M_DUR = _M_ANDAMENTO = None


def metricas_ativas() -> bool:
    return _prom is not None


def render_metricas() -> tuple[bytes, str]:
    """Corpo e content-type para o endpoint /metrics (formato Prometheus)."""
    if _prom is None:  # pragma: no cover
        return b"# prometheus-client nao instalado\n", "text/plain"
    return _prom.generate_latest(), _prom.CONTENT_TYPE_LATEST


# --- Sentry (opcional) --------------------------------------------------------
_sentry_ativo = False


def configurar_sentry(settings) -> None:
    global _sentry_ativo
    if _sentry is None or not settings.SENTRY_DSN:
        return
    _sentry.init(
        dsn=settings.SENTRY_DSN,
        environment=(settings.SENTRY_ENVIRONMENT or settings.ENV),
        release=settings.APP_VERSION,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        # As integrações de FastAPI/Starlette/SQLAlchemy ligam sozinhas.
        send_default_pii=False,   # LGPD: sem dados pessoais por padrão
    )
    _sentry_ativo = True
    logging.getLogger("constela").info("Sentry ativado", extra={"componente": "sentry"})


def sentry_ativo() -> bool:
    return _sentry_ativo


def _marcar_sentry(request_id, correlation_id, usuario_id, escola_id) -> None:
    if not _sentry_ativo:
        return
    escopo = _sentry.get_current_scope()
    escopo.set_tag("request_id", request_id)
    escopo.set_tag("correlation_id", correlation_id)
    if escola_id is not None:
        escopo.set_tag("escola_id", escola_id)
    if usuario_id is not None:
        escopo.set_user({"id": usuario_id})


def capturar_excecao(erro: BaseException) -> None:
    if _sentry_ativo:
        _sentry.capture_exception(erro)


# --- Extração de contexto da requisição --------------------------------------
_RE_ESCOLA = re.compile(r"/escolas/(\d+)")
_RE_ID_NUM = re.compile(r"/\d+(?=/|$)")


def _escola_id_do_caminho(caminho: str) -> int | None:
    m = _RE_ESCOLA.search(caminho)
    return int(m.group(1)) if m else None


def _usuario_id_do_token(headers: dict[bytes, bytes]) -> int | None:
    """Best-effort: extrai o `sub` do JWT só para RASTREAR (sem virar autorização)."""
    bruto = headers.get(b"authorization", b"").decode("latin-1")
    if not bruto.lower().startswith("bearer "):
        return None
    from app.core.security import decodificar_token
    payload = decodificar_token(bruto[7:])
    if not payload or payload.get("papel"):
        return None
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None


def _rota_de(scope: dict) -> str:
    """Template da rota (baixa cardinalidade p/ métricas): usa a rota casada do
    Starlette; se não houver (404), colapsa ids numéricos do caminho."""
    rota = scope.get("route")
    caminho = getattr(rota, "path", None)
    if caminho:
        return caminho
    return _RE_ID_NUM.sub("/{id}", scope.get("path", "?"))


# Rotas de infra não geram log de acesso (evita ruído nos scrapes/probes).
_SEM_LOG = ("/api/health", "/metrics")

logger = logging.getLogger("constela.http")


class ObservabilidadeMiddleware:
    """ASGI puro: contexto + request/correlation id + latência + métricas +
    log de acesso + rede de segurança de 500. Como NÃO é BaseHTTPMiddleware, o
    contexto propaga até o handler (inclusive endpoints síncronos no threadpool)."""

    def __init__(self, app, settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        request_id = uuid.uuid4().hex
        correlation_id = (headers.get(b"x-correlation-id", b"").decode("latin-1")
                          or request_id)
        caminho = scope.get("path", "")
        escola_id = _escola_id_do_caminho(caminho)
        usuario_id = _usuario_id_do_token(headers)

        ctx_request_id.set(request_id)
        ctx_correlation_id.set(correlation_id)
        if escola_id is not None:
            ctx_escola_id.set(escola_id)
        if usuario_id is not None:
            ctx_usuario_id.set(usuario_id)
        _marcar_sentry(request_id, correlation_id, usuario_id, escola_id)

        metodo = scope.get("method", "?")
        inicio = time.perf_counter()
        estado = {"status": 500, "iniciou": False}
        if _M_ANDAMENTO is not None:
            _M_ANDAMENTO.labels(metodo).inc()

        async def enviar(evento):
            if evento["type"] == "http.response.start":
                estado["status"] = evento["status"]
                estado["iniciou"] = True
                cabecalhos = list(evento.get("headers") or [])
                cabecalhos.append((b"x-request-id", request_id.encode()))
                cabecalhos.append((b"x-correlation-id", correlation_id.encode()))
                evento = {**evento, "headers": cabecalhos}
            await send(evento)

        try:
            await self.app(scope, receive, enviar)
        except Exception as erro:  # noqa: BLE001 — rede de segurança de último recurso
            estado["status"] = 500
            logger.exception("erro_nao_tratado", extra={
                "metodo": metodo, "caminho": caminho})
            capturar_excecao(erro)
            if not estado["iniciou"]:
                await self._responder_500(enviar)
            else:  # resposta já começou: não dá para trocar — só registra
                raise
        finally:
            duracao = time.perf_counter() - inicio
            rota = _rota_de(scope)
            ctx_rota.set(rota)
            if _M_ANDAMENTO is not None:
                _M_ANDAMENTO.labels(metodo).dec()
            self._registrar(metodo, rota, caminho, estado["status"], duracao)

    def _registrar(self, metodo, rota, caminho, status, duracao) -> None:
        if _M_REQS is not None:
            _M_REQS.labels(metodo, rota, str(status)).inc()
            _M_DUR.labels(metodo, rota).observe(duracao)
        if any(caminho.startswith(p) for p in _SEM_LOG):
            return
        nivel = logging.ERROR if status >= 500 else (
            logging.WARNING if status >= 400 else logging.INFO)
        logger.log(nivel, "http_acesso", extra={
            "metodo": metodo, "rota": rota, "status": status,
            "dur_ms": round(duracao * 1000, 1)})

    async def _responder_500(self, enviar) -> None:
        corpo = json.dumps(
            {"detail": "Erro interno. Tente novamente em instantes."}).encode()
        await enviar({"type": "http.response.start", "status": 500,
                      "headers": [(b"content-type", b"application/json")]})
        await enviar({"type": "http.response.body", "body": corpo})
