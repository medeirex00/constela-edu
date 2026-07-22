#!/usr/bin/env bash
# =============================================================================
# Backup versionado e CIFRADO do Postgres de produção (Supabase/Railway).
#
# Resolve a lacuna de DR apontada na auditoria: a rotina do docker-compose só
# faz backup do Postgres LOCAL. Este script faz pg_dump do banco de PRODUÇÃO,
# comprime, CIFRA em repouso (openssl AES-256) e deixa o arquivo pronto para
# guardar off-site. Pensado para rodar tanto no CI (.github/workflows/backup.yml)
# quanto à mão numa máquina do operador.
#
# Uso:
#   DATABASE_URL="postgresql://..." BACKUP_PASSPHRASE="..." \
#     bash backend/scripts/backup_postgres.sh [pasta_destino]
#
# Requisitos: pg_dump (postgresql-client), gzip, openssl.
# Restauração: ver docs/DR-RUNBOOK.md.
# =============================================================================
set -euo pipefail

DESTINO="${1:-./backups}"
: "${DATABASE_URL:?Defina DATABASE_URL com a string de conexão de produção (read-only de preferência).}"
: "${BACKUP_PASSPHRASE:?Defina BACKUP_PASSPHRASE — a senha que cifra o backup (guarde-a separada do backup!).}"

# pg_dump aceita URLs postgresql:// e postgres://, mas NÃO o dialeto do
# SQLAlchemy (postgresql+psycopg://). Normaliza para o driver nativo.
URL_PG="${DATABASE_URL/postgresql+psycopg:\/\//postgresql://}"
URL_PG="${URL_PG/postgres+psycopg:\/\//postgres://}"

CARIMBO="$(date -u +%Y%m%d_%H%M%SZ)"
ARQUIVO="${DESTINO}/constela_${CARIMBO}.sql.gz.enc"

mkdir -p "$DESTINO"

echo "[backup] pg_dump → gzip → openssl(AES-256) → ${ARQUIVO}"
# -Fp (texto) + gzip para compatibilidade ampla de restauração; --no-owner e
# --no-privileges para o dump restaurar limpo em qualquer instância/role.
pg_dump "$URL_PG" --no-owner --no-privileges --format=plain \
  | gzip -9 \
  | openssl enc -aes-256-cbc -pbkdf2 -salt \
      -pass "env:BACKUP_PASSPHRASE" -out "$ARQUIVO"

TAM="$(du -h "$ARQUIVO" | cut -f1)"
echo "[backup] OK: ${ARQUIVO} (${TAM})"

# Retenção local: mantém os últimos N dias (o off-site é a cópia durável).
RETENCAO_DIAS="${BACKUP_RETENCAO_DIAS:-14}"
find "$DESTINO" -name 'constela_*.sql.gz.enc' -type f \
  -mtime "+${RETENCAO_DIAS}" -delete 2>/dev/null || true

echo "[backup] Concluído. Guarde este arquivo OFF-SITE (fora do Railway/Supabase)."
echo "[backup] Restauração: docs/DR-RUNBOOK.md"
