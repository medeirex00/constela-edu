#!/usr/bin/env bash
# Conta as linhas de cada tabela do schema public — SÓ NÚMEROS ("tabela=N"),
# nenhum dado de aluno. Usado pelo ensaio de restauração: as contagens da
# ORIGEM (antes do pg_dump) são comparadas com as do banco RESTAURADO
# (verificar_restauracao.sh).
#
# Uso: bash backend/scripts/contar_tabelas.sh <url-postgres>
# Somente leitura: a sessão abre em READ ONLY.
set -euo pipefail

URL="${1:?Informe a string de conexão do PostgreSQL.}"
URL="${URL/postgresql+psycopg:\/\//postgresql://}"
URL="${URL/postgres+psycopg:\/\//postgres://}"

export PGOPTIONS="-c default_transaction_read_only=on"
# `tr -d '\r'`: o psql do Windows encerra as linhas com CRLF.
tabelas="$(psql "$URL" -X -Atq -v ON_ERROR_STOP=1 -c \
  "SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    ORDER BY table_name" | tr -d '\r')"

for t in $tabelas; do
  n="$(psql "$URL" -X -Atq -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM public.\"${t}\"" | tr -d '\r')"
  echo "${t}=${n}"
done
