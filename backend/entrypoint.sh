#!/bin/sh
# Entrypoint do container do backend.
#   1) aplica migrações uma única vez (antes dos workers, sem corrida de DDL);
#   2) sobe o uvicorn respeitando $PORT (Railway/Render/Fly injetam a porta)
#      e confiando nos cabeçalhos de proxy (IP real do cliente nos logs/rate).
set -e

python -m scripts.migrate

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}" \
    --proxy-headers
