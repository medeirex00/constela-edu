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
    por método/rota/status — e o Sensor 4 do plano de retirada do legado
    (`legado_nota_geral_servido_total`, ver `registrar_legado_nota_geral`).
  * Sentry (opcional, ligado por `SENTRY_DSN`): erros e tracing de performance,
    com o usuário e a escola anexados ao evento.

Tudo é degradável: sem `sentry-sdk`/`prometheus-client` instalados, ou sem DSN,
as funções viram no-ops — nada quebra.
"""
from __future__ import annotations

import json
import logging
import re
import threading
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
# O `scope` ASGI da requisição em curso. Não entra no log: existe para que um
# sensor chamado de DENTRO do handler (ver `registrar_legado_nota_geral`) leia o
# template da rota casada e o cliente sem que cada rota precise declarar um
# parâmetro `Request` só para a telemetria. Fora de uma requisição HTTP
# (chamada direta da função em Python, script) fica `None` e o sensor não conta.
ctx_escopo_http: ContextVar[dict | None] = ContextVar("escopo_http", default=None)

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
    # Sensor 4 do plano de retirada (docs/plano-retirada-nota-geral.md §1).
    _M_LEGADO = _prom.Counter(
        "legado_nota_geral_servido_total",
        "Respostas servidas com o contrato legado nota_geral/Nota.posicao",
        ["rota", "cliente"])
else:  # pragma: no cover
    _M_REQS = _M_DUR = _M_ANDAMENTO = _M_LEGADO = None


def metricas_ativas() -> bool:
    return _prom is not None


def render_metricas() -> tuple[bytes, str]:
    """Corpo e content-type para o endpoint /metrics (formato Prometheus)."""
    if _prom is None:  # pragma: no cover
        return b"# prometheus-client nao instalado\n", "text/plain"
    return _prom.generate_latest(), _prom.CONTENT_TYPE_LATEST


# --- Sentry (opcional) --------------------------------------------------------
_sentry_ativo = False


def higienizar_evento_sentry(event, _hint=None):
    """Redige segredos da URL/query ANTES do evento sair para o Sentry
    (processador externo). A integração Starlette anexa a URL crua da
    requisição ao evento — e ``send_default_pii=False`` não cobre isso —, então
    um 500 em /publico/{token} ou /auth/redefinir-senha/{token} vazaria o token.
    Espelha a redação dos logs internos (redigir_caminho) e zera a query string,
    onde nomes/códigos de criança poderiam aparecer (?busca=, ?qr=)."""
    req = event.get("request") if isinstance(event, dict) else None
    if isinstance(req, dict):
        if isinstance(req.get("url"), str):
            req["url"] = redigir_caminho(req["url"])
        if req.get("query_string"):
            req["query_string"] = "<redigido>"
    return event


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
        # NÃO anexar variáveis locais dos frames às exceções: elas podem conter
        # PII de menor (bytes do arquivo, filename, linhas já parseadas com
        # nomes de alunos). send_default_pii=False não cobre frame-locals.
        include_local_variables=False,
        # NUNCA anexar o CORPO da requisição: POST /auth/redefinir-senha carrega o
        # token de reset E a nova senha em texto puro no corpo; imports carregam
        # nomes de alunos. send_default_pii=False não cobre o corpo (o SDK captura
        # corpos "medium" por padrão).
        max_request_body_size="never",
        # Redige o token de rota e a query string da URL crua em erros E em
        # transações de performance antes do envio externo.
        before_send=higienizar_evento_sentry,
        before_send_transaction=higienizar_evento_sentry,
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


def _escola_id_do_caminho(caminho: str) -> int | None:
    m = _RE_ESCOLA.search(caminho)
    return int(m.group(1)) if m else None


def redigir_caminho(caminho: str) -> str:
    """Remove segredos de URL antes de logar/telemetrar. Dois tokens de rota
    NÃO podem aparecer no log de erro nem no Sentry:
      * painel público (/publico/{token}/...) — quem lê o log abriria o painel
        (nomes e notas das crianças);
      * redefinição de senha (/redefinir-senha/{token}) — quem lê poderia
        trocar a senha da conta antes de a pessoa usar o link."""
    caminho = re.sub(r"(/publico/)[^/?#]+", r"\1<token>", caminho)
    caminho = re.sub(r"(/redefinir-senha/)[^/?#]+", r"\1<token>", caminho)
    return caminho


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
    """Template da rota para as MÉTRICAS (baixa cardinalidade): usa a rota
    casada do Starlette. SEM rota casada (404/caminho inexistente), devolve um
    rótulo FIXO "<no_match>" — nunca o caminho bruto. Usar o path cru como label
    permitiria a um anônimo criar séries temporais infinitas (GET /aaa, /bbb…),
    estourando a memória do prometheus_client (DoS por cardinalidade)."""
    rota = scope.get("route")
    caminho = getattr(rota, "path", None)
    return caminho if caminho else "<no_match>"


# --- Sensor 4: quem ainda RECEBE o contrato legado `nota_geral` ---------------
# O inventário estático (tests/test_legado_nota_geral.py) cobre o código DESTE
# repositório. Ele não enxerga o binário do app já instalado nos celulares nem
# uma aba de navegador presa num bundle antigo — e são exatamente esses que
# decidem quando o motor pode parar de gravar `nota_geral` (Gatilho 1 do plano).
# Para eles, "ninguém mais lê" só pode ser MEDIDO no servidor: é este contador.

# Tipos de cliente deduzidos do User-Agent — conjunto FECHADO. O rótulo nunca
# carrega texto livre do cabeçalho: um User-Agent por série temporal deixaria
# qualquer um estourar a memória do prometheus_client (o mesmo DoS por
# cardinalidade que `_rota_de` fecha para o caminho).
CLIENTES_POR_USER_AGENT = ("web", "mobile-android", "mobile-ios", "outro")

# Cabeçalho OPCIONAL com que um cliente se declara COM versão ("mobile/1.4.0").
# Nenhum cliente o envia hoje: ele existe para o próximo build do app poder dizer
# a versão — a única forma de saber QUAL versão em campo ainda lê o `ranking`
# legado do pacote de sincronização (plano, §4 item 11).
CABECALHO_CLIENTE = b"x-constela-cliente"
_RE_CLIENTE_DECLARADO = re.compile(r"(web|mobile)/(\d{1,3}(?:\.\d{1,3}){0,2})")
# A versão vem do cliente, então também é limitada: no máximo este número de
# pares tipo/versão distintos por processo. Passou disso, o rótulo vira
# "<tipo>/outra" — a métrica perde detalhe, a memória não cresce.
MAX_VERSOES_DECLARADAS = 16
_versoes_admitidas: set[str] = set()
_trava_versoes = threading.Lock()

# Variantes de rota admitidas no rótulo — texto FIXO do código, nunca da query.
# Separam, dentro da mesma rota, o pedido que além de receber o campo ainda
# ORDENA pelo legado (a lista da turma com `?ordenar=desempenho`, plano §4 item 2).
VARIANTES_ROTA = frozenset({"ordenar=desempenho"})


def cliente_da_requisicao(escopo: dict) -> str:
    """Rótulo de cliente, de BAIXA cardinalidade, para o Sensor 4.

    1. ``X-Constela-Cliente: <web|mobile>/<versão>`` bem formado →
       ``"mobile/1.4.0"`` (no máximo ``MAX_VERSOES_DECLARADAS`` pares por
       processo; o excedente vira ``"mobile/outra"``);
    2. senão, o ``User-Agent`` reduzido a ``CLIENTES_POR_USER_AGENT``:
       ``okhttp/`` (o fetch do React Native no Android) → ``mobile-android``;
       ``CFNetwork/`` (o fetch nativo do iOS) → ``mobile-ios``; navegador
       (``Mozilla/``) → ``web``; qualquer outra coisa → ``outro``.

    A heurística do User-Agent é deliberadamente grosseira: o que importa é
    separar o app instalado (que não atualizamos à força) do web (que muda a
    cada deploy)."""
    cabecalhos = dict(escopo.get("headers") or [])
    declarado = cabecalhos.get(CABECALHO_CLIENTE, b"").decode("latin-1").strip().lower()
    achado = _RE_CLIENTE_DECLARADO.fullmatch(declarado)
    if achado:
        tipo, versao = achado.groups()
        rotulo = f"{tipo}/{versao}"
        with _trava_versoes:
            if (rotulo in _versoes_admitidas
                    or len(_versoes_admitidas) < MAX_VERSOES_DECLARADAS):
                _versoes_admitidas.add(rotulo)
                return rotulo
        return f"{tipo}/outra"
    agente = cabecalhos.get(b"user-agent", b"").decode("latin-1")
    if "okhttp/" in agente:
        return "mobile-android"
    if "CFNetwork/" in agente:
        return "mobile-ios"
    if agente.startswith("Mozilla/"):
        return "web"
    return "outro"


def registrar_legado_nota_geral(variante: str | None = None) -> None:
    """SENSOR 4 (docs/plano-retirada-nota-geral.md §1): conta UMA resposta
    servida com o contrato legado — `nota_geral` e/ou a ordem única
    `Nota.posicao`.

    Quem chama: as rotas da §4 do plano, logo antes de devolver o payload, e só
    quando o payload é o LEGADO (ex.: `/ranking` SEM `?dimensao=`). A rota por
    dimensão não conta: o item dela ainda traz o campo (é o mesmo schema), mas
    quem pede `?dimensao=` lê `nota`/`posicao` da dimensão — é cliente migrado.

    Rótulos: ``rota`` = TEMPLATE da rota casada
    (``/api/v1/escolas/{escola_id}/ranking`` — nunca a URL com ids, nunca o
    token do telão), mais a ``variante`` quando ela é uma de ``VARIANTES_ROTA``;
    ``cliente`` = `cliente_da_requisicao`.

    Puramente aditivo: não lê nem altera a resposta e NUNCA derruba a
    requisição — telemetria que quebra o produto é pior do que nenhuma. Fora de
    uma requisição HTTP (a função da rota chamada direto em Python) não conta."""
    if _M_LEGADO is None:  # pragma: no cover — prometheus-client ausente
        return
    escopo = ctx_escopo_http.get()
    if escopo is None:
        return
    try:
        rota = _rota_de(escopo)
        if variante is not None:
            if variante in VARIANTES_ROTA:
                rota = f"{rota}?{variante}"
            else:  # erro de programação: conta na rota simples, mas avisa
                logger.warning("sensor_legado_variante_desconhecida",
                               extra={"variante": variante})
        _M_LEGADO.labels(rota, cliente_da_requisicao(escopo)).inc()
    except Exception:  # noqa: BLE001 — telemetria nunca derruba a resposta
        logger.warning("sensor_legado_falhou", exc_info=True)


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
        # O MESMO dict que o roteador completa com a rota casada (`scope.update`)
        # — por isso o sensor, chamado já dentro do handler, enxerga o template.
        token_escopo = ctx_escopo_http.set(scope)
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
                "metodo": metodo, "caminho": redigir_caminho(caminho)})
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
            ctx_escopo_http.reset(token_escopo)

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
