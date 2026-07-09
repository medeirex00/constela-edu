"""Ponto de entrada da API.

Executar em desenvolvimento:
    uvicorn app.main:app --reload --port 8000
"""
import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.database import Base, engine, get_db, migrar_colunas_novas
from app.quest.routers import auth as quest_auth
from app.quest.routers import perfil as quest_perfil
from app.quest.routers import professor as quest_professor
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("constela")

# Fase 1: criação direta do schema. Ao migrar para PostgreSQL/produção,
# substituir por migrações Alembic (estrutura já compatível).
migrar_colunas_novas(engine)   # bancos existentes ganham as colunas/índices novos
Base.metadata.create_all(bind=engine)
# Em banco NOVO a tabela usuarios só existe após o create_all — repete a
# correção de dados para valer já no primeiro início.
from app.core.database import _promover_admin_global  # noqa: E402

_promover_admin_global(engine)

# /docs, /redoc e /openapi.json só quando explicitamente habilitados (dev).
_docs = "/docs" if settings.DOCS_HABILITADOS else None
_redoc = "/redoc" if settings.DOCS_HABILITADOS else None
_openapi = "/openapi.json" if settings.DOCS_HABILITADOS else None

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description=(
        "API do Constela Edu — gestão e premiação escolar. "
        "Multi-escolas, com motor de cálculo configurável e auditável."
    ),
    docs_url=_docs,
    redoc_url=_redoc,
    openapi_url=_openapi,
)


# Rede de segurança: qualquer exceção não tratada vira um 500 genérico (sem
# vazar stack/SQL ao cliente) e é registrada no log. Este middleware é
# adicionado ANTES do CORS para que a resposta 500 volte com os cabeçalhos
# CORS corretos (relevante ao app desktop, que é cross-origin).
@app.middleware("http")
async def capturar_erros(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:  # noqa: BLE001 — handler de último recurso
        logger.exception("Erro não tratado em %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Erro interno. Tente novamente em instantes."},
        )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
):
    app.include_router(router, prefix=settings.API_V1_PREFIX)


@app.get("/api/health", tags=["Sistema"])
def health():
    """Liveness + readiness: confirma que o processo responde E que o banco
    está acessível (usado pelo healthcheck do container)."""
    db = next(get_db())
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        logger.exception("Healthcheck: banco de dados inacessível")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degradado", "banco": "inacessivel"},
        )
    finally:
        db.close()
    return {"status": "ok", "app": settings.APP_NAME}
