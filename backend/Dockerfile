# Constela Edu — API (FastAPI)
FROM python:3.13-slim

# psycopg (PostgreSQL) roda em modo binário — sem toolchain de compilação
WORKDIR /app

# Navegador do robô de sincronização (Playwright/Chromium). Instalado como ROOT,
# num caminho COMPARTILHADO (/ms-playwright) legível pelo usuário não-root `app`
# em runtime. NÃO usamos `playwright install --with-deps`: o `install-deps` do
# Playwright pede pacotes de fonte com NOMES DO UBUNTU (ttf-unifont,
# ttf-ubuntu-font-family) que não existem no Debian slim (falha com exit 100).
# Em vez disso, instalamos as libs de SO do Chromium com os nomes CORRETOS do
# Debian (t64 resolvido via Provides) e só baixamos o browser. Sem isto, o robô
# Matific/Elefante retorna "navegador_indisponivel" (degradação graciosa).
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]==3.2.3" \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 \
        libcups2 libdrm2 libgbm1 libasound2 libpango-1.0-0 libcairo2 \
        libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
        libxkbcommon0 libxrandr2 libglib2.0-0 fonts-liberation fonts-unifont \
    && python -m playwright install chromium \
    && chmod -R a+rx /ms-playwright \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY scripts ./scripts
# Infraestrutura de migrações: o entrypoint roda `alembic upgrade` no boot.
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY entrypoint.sh ./entrypoint.sh

# Usuário sem privilégios (nunca rodar como root em produção). Os volumes de
# dados são criados e cedidos ao usuário app; HOME evita falhas de cache.
RUN adduser --system --group --uid 1001 --home /home/app app \
    && mkdir -p /dados/uploads /dados/exports /dados/database \
    && chown -R app:app /dados /app \
    && chmod +x /app/entrypoint.sh
# Padrões da imagem: uploads/exports nos volumes graváveis pelo usuário app.
# Sem isto, o default do config resolveria para /uploads (raiz, dona root) e
# qualquer importação de PDF falharia com PermissionError em deploys que não
# definem os envs (ex.: Railway). O docker-compose sobrepõe com os mesmos valores.
ENV PYTHONUNBUFFERED=1 HOME=/home/app \
    UPLOADS_DIR=/dados/uploads EXPORTS_DIR=/dados/exports
USER app

# $PORT permite deploy direto em Railway/Render/Fly; no compose usa 8000.
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
