"""Ponto de entrada da API.

Executar em desenvolvimento:
    uvicorn app.main:app --reload --port 8000
"""
import logging
import secrets

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import registrar_avisos_de_configuracao, settings
from app.core import observabilidade as obs
from app.core.cabecalhos import CabecalhosSegurancaMiddleware
from app.core.limite_corpo import LimiteDeCorpoMiddleware
from app.core.database import engine, garantir_dados_base, get_db
from app.core.deps import negar_secretaria
from app.core.prontidao import prontidao
from app.core.security import registrar_avisos_da_cifra
from app.quest.routers import auth as quest_auth
from app.quest.routers import conquistas as quest_conquistas
from app.quest.routers import perfil as quest_perfil
from app.quest.routers import professor as quest_professor
from app.sync import metricas as sync_metricas
from app.sync import router as sync_router
from app.sync import scheduler as sync_scheduler
from app.routers import (
    academico,
    admin,
    analise,
    auth,
    avaliacoes,
    certificados_lote,
    configuracoes,
    escolas,
    evolucao,
    gamificacao,
    ia,
    importacoes,
    indicadores,
    mobile,
    notificacoes,
    plataformas,
    presenca,
    publico,
    rankings,
    rede,
    relatorios,
    sistema,
    visao_geral,
)

# Observabilidade primeiro: logs estruturados + Sentry ANTES de qualquer log
# (inclui o startup). configurar_logging troca o handler da raiz; o Sentry só
# liga se houver SENTRY_DSN.
obs.configurar_logging(settings)
obs.configurar_sentry(settings)
logger = logging.getLogger("constela")

# Prontidão da cifra em repouso (A1, lacuna L3): DEK vazia, curta ou igual à
# SECRET_KEY caía no legado SEM aviso — agora o log do boot diz qual (sem valor).
registrar_avisos_da_cifra(logger)

# Configuração perigosa (DEK ausente ou igual à SECRET_KEY, CORS com curinga, /docs
# ligado): com ENV=producao o boot já recusou em app.core.config; em dev — como a
# produção rodou até hoje, sem ENV — o log diz o que o ENV=producao vai recusar.
registrar_avisos_de_configuracao(logger)

# Schema via Alembic. Em produção (ENV=producao) quem migra é `scripts.migrate`,
# UMA vez e ANTES do servidor (pre-deploy do Railway ou entrypoint.sh) — repetir
# por worker aqui provocaria corrida de DDL. Em desenvolvimento (uvicorn --reload,
# sem entrypoint) aplicamos as migrações no startup para manter o banco em dia
# (no PostgreSQL com advisory lock: N processos se enfileiram, não correm).
if not settings.em_producao:
    from app.core.migracoes import aplicar_migracoes  # noqa: E402

    aplicar_migracoes(engine)

# Prontidão no boot: com o schema sabidamente errado (migração pendente ou banco
# adiante do código) o processo sobe, mas o readiness responde 503 e NADA é escrito
# no banco — nem os ajustes de dados, nem a liberação de órfãs, nem o agendador de
# sync (mais abaixo). Banco fora segue o caminho de antes (os ajustes abaixo falham e
# o boot cai).
_pronto_no_boot, _motivo_boot, _ = prontidao.avaliar(engine)
_schema_errado_no_boot = _motivo_boot in ("migracao_pendente", "schema_adiante")
if _schema_errado_no_boot:
    # E o 503 vale até REINICIAR, mesmo que o schema fique em dia com o processo de pé
    # (migração aplicada por fora): o que este boot pulou não sobe sozinho depois, e
    # um processo pronto sem agendador seguiria com o /status dizendo "ativo".
    prontidao.exigir_reinicio(_motivo_boot)

if not _schema_errado_no_boot:
    # Correções de DADOS idempotentes (baratas e seguras de repetir por worker).
    garantir_dados_base(engine)

    # Um redeploy no MEIO de uma sync deixa a execução presa em 'executando' e trava
    # a escola (uq_sync_exec_ativa) até o timeout de 30 min. No boot, libera essas
    # órfãs na hora (o worker que as rodava morreu no restart). Nunca impede o boot.
    try:
        from app.sync import service as _sync_service  # noqa: E402

        _db_boot = next(get_db())
        try:
            _orfas = _sync_service.finalizar_orfas_no_boot(_db_boot)
            if _orfas:
                logger.info("Sync: %d execução(ões) órfã(s) liberada(s) no boot.", _orfas)
        finally:
            _db_boot.close()
    except Exception:  # noqa: BLE001
        logger.warning("Falha ao liberar órfãs de sync no boot", exc_info=True)

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


# Teto do corpo, ANTES da autenticação (o FastAPI lê o corpo antes das dependências).
# O MAIS INTERNO dos nossos: o 413 passa pela observabilidade, pelos cabeçalhos de
# segurança e pelo CORS. Ver app/core/limite_corpo.py.
app.add_middleware(LimiteDeCorpoMiddleware, settings=settings)

# Observabilidade + rede de segurança de 500 (request/correlation id, latência,
# métricas, log de acesso estruturado). ASGI puro para o contexto propagar até
# o handler. Adicionado ANTES do CORS => o CORS fica POR FORA e a resposta 500
# volta com os cabeçalhos CORS (o app desktop é cross-origin).
app.add_middleware(obs.ObservabilidadeMiddleware, settings=settings)

# Cabeçalhos de segurança (nosniff, frame DENY, referrer, HSTS, CSP no JSON). Entre
# a observabilidade e o CORS: a resposta 500 da rede de segurança também os recebe,
# e o CORS continua sendo o mais externo. Ver app/core/cabecalhos.py.
app.add_middleware(CabecalhosSegurancaMiddleware, settings=settings)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Deixa o navegador LER o id da requisição (útil no relato de suporte) e o nome
    # do arquivo baixado: com a web e a API em origens diferentes, sem isto o
    # `apiDownload`/`apiDownloadPost` não enxerga o Content-Disposition e cai no
    # nome padrão (no lote de certificados, o nome traz quantos foram emitidos).
    expose_headers=["X-Request-ID", "X-Correlation-ID", "Content-Disposition"],
    # A web (Vercel) e a API (Railway) estão em origens diferentes: cada URL nova paga um
    # preflight (OPTIONS), uma ida e volta do navegador à API antes da chamada de
    # verdade. O navegador guarda a resposta por ``max_age`` segundos (o padrão do
    # Starlette é 600); 7200 é o teto que o Chrome respeita. Só vale para a MESMA URL de
    # novo (visitas repetidas), não para a primeira.
    max_age=7200,
)


# O 422 padrão devolve o "input" de cada erro: num corpo que não é JSON, é o corpo
# INTEIRO (até o teto do limite_corpo) — eco do que o cliente mandou, que dobra o
# tráfego e pode repetir dado pessoal em log de proxy. Entrada crua (bytes) ou longa
# sai do erro; o resto da resposta é a do FastAPI.
_INPUT_MAXIMO_NO_422 = 256


@app.exception_handler(RequestValidationError)
async def _erro_de_validacao(request: Request, exc: RequestValidationError) -> JSONResponse:
    erros = []
    for erro in exc.errors():
        erro = dict(erro)
        bruto = erro.get("input")
        if isinstance(bruto, (bytes, bytearray)) or (
                isinstance(bruto, str) and len(bruto) > _INPUT_MAXIMO_NO_422):
            erro.pop("input")
        erros.append(erro)
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        content={"detail": jsonable_encoder(erros)})


for router in (
    auth.router,
    escolas.router,
    academico.router,
    configuracoes.router,
    rankings.router,
    rede.router,
    indicadores.router,
    indicadores.router_escola,
    analise.router,
    analise.router_escola,
    avaliacoes.router,
    plataformas.router,
    evolucao.router,
    gamificacao.router,
    admin.router,
    sistema.router,
    publico.router,
    ia.router,
    mobile.router,
    presenca.router,
    notificacoes.router,
    quest_auth.router,
    quest_perfil.router,
    quest_professor.router,
    quest_conquistas.router,
):
    app.include_router(router, prefix=settings.API_V1_PREFIX)

# Áreas OPERACIONAIS de escola — importação, sincronização e diagnóstico Elefante.
# A Secretaria acompanha os resultados da REDE, mas não opera as escolas: fica
# bloqueada na raiz destes routers (leitura e escrita). Coordenador de escola
# (sem rede) e admin global passam normalmente.
#
# `relatorios` entra aqui pelo mesmo motivo de PII/LGPD: são PDFs de ESCOLA
# (certificados, lista de alunos, cartaz do ranking) com NOME de criança — a
# Secretaria vê só o agregado da rede (o boletim consolidado é `/redes/.../boletim`).
#
# `certificados_lote` (os mesmos certificados, em lote) e `visao_geral` (a tela da
# escola na identidade v2) seguem a mesma regra; as duas também declaram a guarda na
# própria rota.
for router in (
    importacoes.router,
    sync_router.router,
    sync_router.router_global,
    relatorios.router,
    certificados_lote.router,
    visao_geral.router,
):
    app.include_router(router, prefix=settings.API_V1_PREFIX,
                       dependencies=[Depends(negar_secretaria)])

# Scheduler de sincronização automática: sobe como thread de fundo SE
# SYNC_SCHEDULER_ENABLED (fail-safe: desligado por padrão). Cada worker uvicorn
# tem o seu; o claim atômico da fila evita processamento duplicado. Encerra
# junto com o processo (thread daemon) + no shutdown do app.
# Com o schema sabidamente errado no boot, NÃO sobe: a rodada grava (agenda diária,
# fila, sync completa) e rodaria com código que não casa com o schema durante a
# janela do healthcheck. O processo segue de pé, com o readiness em 503.
if _schema_errado_no_boot:
    if settings.SYNC_SCHEDULER_ENABLED:
        logger.warning("Agendador de sincronização NÃO iniciado: schema errado no boot "
                       "(%s). Sobe no próximo boot com o schema em dia.", _motivo_boot)
else:
    sync_scheduler.iniciar()

# Diagnóstico do robô: verifica UMA vez, em background, se o Playwright abre o
# Chromium (reportado no diagnóstico protegido, GET /api/v1/sistema/diagnostico).
# Não liga o scheduler nem coleta nada — só valida a infra do navegador. Ligado por
# padrão (produção); AUTOMACAO_VERIFICAR_NO_BOOT=false desliga (testes e E2E: sem
# saída para a internet a partir do runner).
from app.core import automacao  # noqa: E402

automacao.iniciar_no_boot(settings)


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


# HEAD nas duas sondas: o @app.get do FastAPI não registra HEAD, e o monitor de
# disponibilidade que sonda com HEAD recebia 405 (nunca media a prontidão). Mesma
# função e mesmo status do GET (a resposta a HEAD vai sem corpo); fora do OpenAPI.
@app.head("/api/health/live", include_in_schema=False)
@app.get("/api/health/live", tags=["Sistema"])
def health_live():
    """Liveness: o processo responde? (o orquestrador REINICIA se falhar)."""
    return {"status": "ok", "versao": settings.APP_VERSION}


@app.head("/api/health/ready", include_in_schema=False)
@app.get("/api/health/ready", tags=["Sistema"])
def health_ready():
    """Readiness: banco acessível E schema na revisão do código (heads do Alembic).

    É o healthcheck do deploy no Railway: com migração pendente responde 503
    ``migracao_pendente`` e o tráfego NÃO vai para este deploy (o anterior segue no
    ar). Se este processo bootou com o schema errado, responde 503
    ``reinicio_pendente`` mesmo depois de o schema ficar em dia (só um boot novo sobe
    o agendador e os ajustes). O corpo leva só o motivo; as revisões ficam no log.
    Ver app/core/prontidao.py."""
    pronto, motivo, _ = prontidao.avaliar(engine)
    if motivo == "banco_inacessivel":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degradado", "banco": "inacessivel", "motivo": motivo})
    if not pronto:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degradado", "banco": "ok", "motivo": motivo})
    return {"status": "ok", "banco": "ok", "schema": motivo}


@app.get("/api/health", tags=["Sistema"])
def health():
    """Saúde PÚBLICA mínima (healthcheck do docker-compose): status, banco e versão.

    O diagnóstico operacional (IP/ASN/cidade de saída do robô, páginas de login das
    plataformas, navegador, agendador, schema, armazenamento) saiu daqui: era
    público. Fica em GET /api/v1/sistema/diagnostico, só para admin global."""
    banco = _banco_ok()
    corpo = {"status": "ok" if banco else "degradado",
             "banco": "ok" if banco else "inacessivel",
             "versao": settings.APP_VERSION}
    if not banco:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=corpo)
    return corpo


# Diagnóstico protegido (admin global) — o que /api/health expunha em público.
# Router próprio, fora da lista de routers de negócio acima.
app.include_router(sistema.router_diagnostico, prefix=settings.API_V1_PREFIX)

# Métricas de sincronização lidas do BANCO na hora do scrape (valem para qualquer
# worker que atender): o coletor só roda depois da proteção da rota abaixo.
sync_metricas.registrar_coletor()


@app.get("/metrics", tags=["Sistema"], include_in_schema=False)
def metricas(request: Request):
    """Métricas Prometheus. Protegido: com METRICS_TOKEN definido, exige
    Authorization: Bearer <token> (comparação em tempo constante). Sem token,
    responde 404 em QUALQUER ENV (fail-closed): a produção já rodou sem ENV e a
    regra antiga "aberto em dev" deixava a telemetria pública. Só METRICS_PUBLICO
    (opção de desenvolvimento, ignorada com ENV=producao) abre sem token."""
    if not settings.METRICS_ENABLED or not obs.metricas_ativas():
        return Response("metrics desativado\n", media_type="text/plain")
    token = settings.METRICS_TOKEN.strip()
    if token:
        cabecalho = request.headers.get("authorization") or ""
        enviado = cabecalho[7:].strip() if cabecalho[:7].lower() == "bearer " else ""
        # Em bytes: compare_digest recusa (TypeError → 500) str com não-ASCII.
        if not (enviado and secrets.compare_digest(enviado.encode(), token.encode())):
            return Response("nao autorizado\n", status_code=status.HTTP_401_UNAUTHORIZED,
                            media_type="text/plain")
    elif not settings.METRICS_PUBLICO or settings.em_producao:
        # Sem token: não expõe (esconde o endpoint).
        return Response("nao encontrado\n", status_code=status.HTTP_404_NOT_FOUND,
                        media_type="text/plain")
    corpo, tipo = obs.render_metricas()
    return Response(corpo, media_type=tipo)
