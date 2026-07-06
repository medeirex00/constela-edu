"""Ponto de entrada da API.

Executar em desenvolvimento:
    uvicorn app.main:app --reload --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import Base, engine
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

# Fase 1: criação direta do schema. Ao migrar para PostgreSQL/produção,
# substituir por migrações Alembic (estrutura já compatível).
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description=(
        "API do Constela Edu — gestão e premiação escolar. "
        "Multi-escolas, com motor de cálculo configurável e auditável."
    ),
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
):
    app.include_router(router, prefix=settings.API_V1_PREFIX)


@app.get("/api/health", tags=["Sistema"])
def health():
    return {"status": "ok", "app": settings.APP_NAME}
