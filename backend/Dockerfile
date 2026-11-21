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
# Só as dependências de RUNTIME: pytest/pytest-cov ficam em requirements-dev.txt,
# que a imagem não copia (o CI instala os dois para rodar os testes).
COPY requirements.txt .
# O pip é ferramenta de BUILD e sai da imagem de runtime ao fim desta camada: o
# pip/_vendor dele traz cópias próprias de urllib3, msgpack e (no SBOM)
# setuptools, que o Trivy acusa e que o app não usa. Para depurar no container:
# python -m ensurepip.
# Na lista do apt, zlib1g atualiza também a cópia já presente na base.
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]==3.2.3" \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 \
        libcups2 libdrm2 libgbm1 libasound2 libpango-1.0-0 libcairo2 zlib1g \
        libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
        libxkbcommon0 libxrandr2 libglib2.0-0 fonts-liberation fonts-unifont \
    && python -m playwright install chromium \
    && chmod -R a+rx /ms-playwright \
    && python -m pip uninstall -y pip \
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
# Padrão da imagem: a base dos arquivos é /dados (uploads/exports graváveis pelo
# usuário app — os MESMOS caminhos de antes, /dados/uploads e /dados/exports).
# Sem isto, o default do config resolveria para /uploads (raiz, dona root) e
# qualquer importação de PDF falharia com PermissionError em deploys que não
# definem os envs (ex.: Railway). O docker-compose fixa UPLOADS_DIR/EXPORTS_DIR
# com os mesmos valores. No Railway, /dados só é persistente com um VOLUME
# anexado nesse caminho (docs/operacao/ARMAZENAMENTO.md).
ENV PYTHONUNBUFFERED=1 HOME=/home/app DADOS_DIR=/dados
USER app

# $PORT permite deploy direto em Railway/Render/Fly; no compose usa 8000.
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
