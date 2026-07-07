# Constela Edu — API (FastAPI)
FROM python:3.13-slim

# psycopg (PostgreSQL) roda em modo binário — sem toolchain de compilação
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]==3.2.3"

COPY app ./app
COPY scripts ./scripts
COPY entrypoint.sh ./entrypoint.sh

# Usuário sem privilégios (nunca rodar como root em produção). Os volumes de
# dados são criados e cedidos ao usuário app; HOME evita falhas de cache.
RUN adduser --system --group --uid 1001 --home /home/app app \
    && mkdir -p /dados/uploads /dados/exports /dados/database \
    && chown -R app:app /dados /app \
    && chmod +x /app/entrypoint.sh
ENV PYTHONUNBUFFERED=1 HOME=/home/app
USER app

# $PORT permite deploy direto em Railway/Render/Fly; no compose usa 8000.
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
