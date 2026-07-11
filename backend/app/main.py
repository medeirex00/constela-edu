"""Ponto de entrada da API.

Executar em desenvolvimento:
    uvicorn app.main:app --reload --port 8000
"""
import logging
import secrets
import time

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core import observabilidade as obs
from app.core.database import engine, garantir_dados_base, get_db
from app.quest.routers import auth as quest_auth
from app.quest.routers import perfil as quest_perfil
from app.quest.routers import professor as quest_professor
from app.sync import router as sync_router
from app.sync import scheduler as sync_scheduler
from app.routers import (
    academico,
    admin,
    auth,
    configuracoes,
    escolas,
    evolucao,
    gamificacao,
    ia,
    importacoes,
    mobile,
    plataformas,
    publico,
    rankings,
    relatorios,
    sistema,
)

# Observabilidade primeiro: logs estruturados + Sentry ANTES de qualquer log
# (inclui o startup). configurar_logging troca o handler da raiz; o Sentry só
# liga se houver SENTRY_DSN.
obs.configurar_logging(settings)
obs.configurar_sentry(settings)
logger = logging.getLogger("constela")
_INICIO = time.time()

# Schema via Alembic. Em produção, o entrypoint do container roda
# `scripts.migrate` UMA vez antes dos workers — repetir por worker aqui
# provocaria corrida de DDL. Em desenvolvimento (uvicorn --reload, sem
# entrypoint) aplicamos as migrações no startup para manter o banco em dia.
if not settings.em_producao:
    from app.core.migracoes import aplicar_migracoes  # noqa: E402

    aplicar_migracoes(engine)

# Correções de DADOS idempotentes (baratas e seguras de repetir por worker).
garantir_dados_base(engine)

# /docs, /redoc e /openapi.json só quando explicitamente habilitados (dev).
_docs = "/docs" if settings.DOCS_HABILITADOS else None
_redoc = "/redoc" if settings.DOCS_HABILITADOS else None
_openapi = "/openapi.json" if settings.DOCS_HABILITADOS else None

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "API do Constela Edu — gestão e premiação escolar. "
        "Multi-escolas, com motor de cálculo configurável e auditável."
    ),
    docs_url=_docs,
    redoc_url=_redoc,
    openapi_url=_openapi,
)


# Observabilidade + rede de segurança de 500 (request/correlation id, latência,
# métricas, log de acesso estruturado). ASGI puro para o contexto propagar até
# o handler. Adicionado ANTES do CORS => o CORS fica POR FORA e a resposta 500
# volta com os cabeçalhos CORS (o app desktop é cross-origin).
app.add_middleware(obs.ObservabilidadeMiddleware, settings=settings)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Deixa o navegador LER o id da requisição (útil no relato de suporte).
    expose_headers=["X-Request-ID", "X-Correlation-ID"],
)

for router in (
    auth.router,
    escolas.router,
    academico.router,
    configuracoes.router,
    rankings.router,
    importacoes.router,
    plataformas.router,
    evolucao.router,
    gamificacao.router,
    relatorios.router,
    admin.router,
    sistema.router,
    publico.router,
    ia.router,
    mobile.router,
    quest_auth.router,
    quest_perfil.router,
    quest_professor.router,
    sync_router.router,
    sync_router.router_global,
):
    app.include_router(router, prefix=settings.API_V1_PREFIX)

# Scheduler de sincronização automática: sobe como thread de fundo SE
# SYNC_SCHEDULER_ENABLED (fail-safe: desligado por padrão). Cada worker uvicorn
# tem o seu; o claim atômico da fila evita processamento duplicado. Encerra
# junto com o processo (thread daemon) + no shutdown do app.
sync_scheduler.iniciar()

# Diagnóstico do robô: verifica UMA vez, em background, se o Playwright abre o
# Chromium (reportado em /api/health como `automacao_navegador`). Não liga o
# scheduler nem coleta nada — só valida a infra do navegador.
from app.core import automacao  # noqa: E402

automacao.iniciar_verificacao()


@app.on_event("shutdown")
def _parar_scheduler_sync() -> None:
    sync_scheduler.parar()


# --- Health checks e métricas (SaaS) -----------------------------------------

def _banco_ok() -> bool:
    db = next(get_db())
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        logger.exception("Healthcheck: banco de dados inacessível")
        return False
    finally:
        db.close()


@app.get("/api/health/live", tags=["Sistema"])
def health_live():
    """Liveness: o processo responde? (o orquestrador REINICIA se falhar)."""
    return {"status": "ok", "versao": settings.APP_VERSION}


@app.get("/api/health/ready", tags=["Sistema"])
def health_ready():
    """Readiness: processo + banco prontos? (o balanceador TIRA de rota sem
    reiniciar enquanto o banco não volta)."""
    if not _banco_ok():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degradado", "banco": "inacessivel"})
    return {"status": "ok", "banco": "ok"}


@app.get("/api/health", tags=["Sistema"])
def health():
    """Saúde geral (compatível com o healthcheck do container): processo, banco,
    versão e tempo no ar."""
    banco = _banco_ok()
    corpo = {"status": "ok" if banco else "degradado", "app": settings.APP_NAME,
             "versao": settings.APP_VERSION,
             "banco": "ok" if banco else "inacessivel",
             "sentry": obs.sentry_ativo(),
             # true/false = robô abre o Chromium; null = ainda verificando no boot.
             "automacao_navegador": automacao.status()["navegador"],
             "uptime_s": round(time.time() - _INICIO, 1)}
    if not banco:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=corpo)
    return corpo


@app.get("/metrics", tags=["Sistema"], include_in_schema=False)
def metricas(request: Request):
    """Métricas Prometheus. Protegido: com METRICS_TOKEN definido, exige
    Authorization: Bearer <token>. Em produção sem token, recusa (fail-closed) —
    telemetria operacional nunca fica pública. Em dev sem token, fica aberto."""
    if not settings.METRICS_ENABLED or not obs.metricas_ativas():
        return Response("metrics desativado\n", media_type="text/plain")
    token = settings.METRICS_TOKEN.strip()
    if token:
        cabecalho = request.headers.get("authorization") or ""
        enviado = cabecalho[7:].strip() if cabecalho[:7].lower() == "bearer " else ""
        if not (enviado and secrets.compare_digest(enviado, token)):
            return Response("nao autorizado\n", status_code=status.HTTP_401_UNAUTHORIZED,
                            media_type="text/plain")
    elif settings.em_producao:
        # Sem token configurado em produção: não expõe (esconde o endpoint).
        return Response("nao encontrado\n", status_code=status.HTTP_404_NOT_FOUND,
                        media_type="text/plain")
    corpo, tipo = obs.render_metricas()
    return Response(corpo, media_type=tipo)
