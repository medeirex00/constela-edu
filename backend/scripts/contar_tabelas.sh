#!/usr/bin/env bash
# Conta as linhas de cada tabela do schema public — SÓ NÚMEROS ("tabela=N"),
# nenhum dado de aluno. Usado pelo ensaio de restauração: as contagens da
# ORIGEM (antes do pg_dump) são comparadas com as do banco RESTAURADO
# (verificar_restauracao.sh).
#
# Uso: bash backend/scripts/contar_tabelas.sh <url-postgres>
# Somente leitura: cada consulta roda dentro de BEGIN TRANSACTION READ ONLY …
# COMMIT, na MESMA chamada. Não usa PGOPTIONS de propósito: um pooler de
# conexões (ex.: o do Supabase) pode recusar parâmetros de inicialização, e a
# transação explícita vale com ou sem pooler.
set -euo pipefail

URL="${1:?Informe a string de conexão do PostgreSQL.}"
URL="${URL/postgresql+psycopg:\/\//postgresql://}"
URL="${URL/postgres+psycopg:\/\//postgres://}"

# Só o resultado do SELECT sai (-q cala BEGIN/COMMIT); `tr -d '\r'`: o psql do
# Windows encerra as linhas com CRLF.
ler() {
  psql "$URL" -X -Atq -v ON_ERROR_STOP=1 \
    -c "BEGIN TRANSACTION READ ONLY; $1; COMMIT;" | tr -d '\r'
}

tabelas="$(ler "SELECT table_name FROM information_schema.tables
                 WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                 ORDER BY table_name")"

for t in $tabelas; do
  echo "${t}=$(ler "SELECT count(*) FROM public.\"${t}\"")"
done
