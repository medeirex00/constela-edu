#!/bin/sh
# Entrypoint do container do backend.
#   1) aplica migrações uma única vez (antes dos workers, sem corrida de DDL);
#   2) sobe o uvicorn respeitando $PORT (Railway/Render/Fly injetam a porta)
#      e confiando nos cabeçalhos de proxy (IP real do cliente nos logs/rate).
#
# Com ARGUMENTOS, roda só o comando pedido e devolve o código de saída dele, sem
# migrar nem subir o uvicorn. É a defesa para o pre-deploy do Railway: se ele for
# passado como argumento ao ENTRYPOINT da imagem (a documentação não diz se
# substitui ou se passa), `entrypoint.sh python -m scripts.migrate` migra e TERMINA
# — em vez de migrar e ficar preso num uvicorn que nunca sai.
set -e

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

python -m scripts.migrate

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}" \
    --proxy-headers \
    --no-access-log
# --no-access-log: o log de acesso (estruturado, com request_id/escola/rota e o
# token das rotas públicas MASCARADO) é emitido pelo ObservabilidadeMiddleware. O do
# uvicorn grava a URL CRUA — inclusive o token do painel público e o de
# redefinição de senha — por isso fica desligado (docs/operacao/PRODUCAO-ENV-E-MIGRACOES.md).
