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

# O nome vem citado PELO SERVIDOR (format('%I')): um nome de tabela com aspas,
# ponto e vírgula ou espaço nunca vira SQL solto — sem isso, uma tabela chamada
# 'x";COMMIT;DROP TABLE y;--' encerrava a transação somente leitura e o DROP
# rodava (reproduzido em banco descartável). Nome e forma citada vão separados
# pelo caractere de controle 0x1F, que não aparece em nome de tabela.
# A lista vem do pg_catalog, não do information_schema: este só mostra as
# tabelas em que o usuário tem algum privilégio, e uma tabela sem permissão
# sumiria da contagem EM SILÊNCIO. Pelo catálogo ela aparece e a contagem
# dela falha — explícito.
SEP=$'\x1f'
tabelas="$(ler "SELECT c.relname || chr(31) || format('%I', c.relname)
                 FROM pg_catalog.pg_class c
                 JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
                 ORDER BY c.relname")"

while IFS="$SEP" read -r nome citado; do
  [ -n "$nome" ] || continue
  # Atribuição SEPARADA de propósito: dentro de `echo "...$(ler ...)"` uma
  # contagem que falha não para o script (vale o status do echo) e sairia
  # "tabela=" — um zero silencioso na comparação. Aqui o set -e interrompe.
  n="$(ler "SELECT count(*) FROM public.${citado}")"
  [[ "$n" =~ ^[0-9]+$ ]] || { echo "contagem inválida para a tabela ${nome}" >&2; exit 1; }
  echo "${nome}=${n}"
done <<< "$tabelas"
