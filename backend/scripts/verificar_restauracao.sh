#!/usr/bin/env bash
# =============================================================================
# ENSAIO DE RESTAURAÇÃO de um backup cifrado (backup_postgres.sh) num
# PostgreSQL DESCARTÁVEL — a prova de que o backup volta, não só de que existe.
#
# Uso:
#   BACKUP_PASSPHRASE=...  RESTORE_DATABASE_URL=postgresql://u:s@localhost:5432/restauracao_teste \
#   [CONTAGENS_ORIGEM=contagens_origem.txt] \
#   bash backend/scripts/verificar_restauracao.sh <constela_AAAAMMDD_HHMMSSZ.sql.gz.enc>
#
# Travas (um engano de variável nunca restaura por cima de nada real):
#   * o destino tem de ser LOCAL (localhost / 127.0.0.1 / ::1) e o NOME do banco
#     tem de conter "restaura" ou "test";
#   * o destino tem de estar VAZIO (nenhuma tabela em public);
#   * psql com ON_ERROR_STOP: qualquer erro ao aplicar o dump reprova o ensaio.
#
# O que é conferido:
#   * o dump decifra com a senha e aplica sem erro;
#   * existe alembic_version (o schema veio inteiro, com a versão de migração);
#   * com CONTAGENS_ORIGEM (saída de contar_tabelas.sh na ORIGEM, tirada antes do
#     pg_dump): toda tabela da origem existe no restaurado e tem pelo menos 98%
#     das linhas contadas lá. A folga cobre o que foi apagado entre a contagem e
#     o dump (ex.: uma fusão de cadastro) — o dump não é tirado no mesmo instante.
#
# Só imprime NÚMEROS (versão do Alembic e linhas por tabela). A senha nunca é
# impressa: o openssl a lê da variável de ambiente.
# =============================================================================
set -euo pipefail

ARQUIVO="${1:?Informe o arquivo .sql.gz.enc a restaurar.}"
: "${BACKUP_PASSPHRASE:?Defina BACKUP_PASSPHRASE (a senha que cifrou o backup).}"
: "${RESTORE_DATABASE_URL:?Defina RESTORE_DATABASE_URL (banco DESCARTÁVEL, local).}"
[ -f "$ARQUIVO" ] || { echo "[restauração] arquivo não encontrado: $ARQUIVO" >&2; exit 2; }

URL="${RESTORE_DATABASE_URL/postgresql+psycopg:\/\//postgresql://}"
URL="${URL/postgres+psycopg:\/\//postgres://}"

resto="${URL#*://}"
resto="${resto#*@}"
case "$resto" in
  \[*) host="${resto%%]*}"; host="${host#[}" ;;
  *)   host="${resto%%[:/]*}" ;;
esac
banco="${URL##*/}"
banco="${banco%%\?*}"

case "$host" in
  localhost|127.0.0.1|::1) ;;
  *) echo "[restauração] RECUSADO: o destino tem de ser local (recebido host '$host')." >&2; exit 2 ;;
esac
case "$banco" in
  *restaura*|*test*) ;;
  *) echo "[restauração] RECUSADO: o nome do banco de destino tem de conter 'restaura' ou 'test' (recebido '$banco')." >&2; exit 2 ;;
esac

psql_q() { psql "$URL" -X -Atq -v ON_ERROR_STOP=1 "$@" | tr -d '\r'; }  # CRLF do psql no Windows

ja_tem="$(psql_q -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
if [ "$ja_tem" != "0" ]; then
  echo "[restauração] RECUSADO: o banco de destino não está vazio ($ja_tem tabelas em public)." >&2
  exit 2
fi

# Papéis que as políticas de RLS do Supabase citam (o dump sai com
# --no-owner --no-privileges, mas CREATE POLICY ... TO <papel> continua lá).
for papel in anon authenticated service_role; do
  psql_q -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${papel}')
             THEN CREATE ROLE ${papel} NOLOGIN; END IF; END \$\$;" > /dev/null
done

echo "[restauração] decifrando e aplicando ${ARQUIVO##*/} no banco descartável '${banco}'"
# O pg_dump (--schema=public) emite "CREATE SCHEMA public;", e todo banco novo
# já nasce com o schema public — só essa linha exata sai do fluxo.
openssl enc -d -aes-256-cbc -pbkdf2 -pass "env:BACKUP_PASSPHRASE" -in "$ARQUIVO" \
  | gunzip \
  | sed '/^CREATE SCHEMA public;$/d' \
  | psql "$URL" -X -q -v ON_ERROR_STOP=1 -o /dev/null

versao="$(psql_q -c "SELECT string_agg(version_num, ',') FROM alembic_version" 2>/dev/null || true)"
if [ -z "$versao" ]; then
  echo "[restauração] FALHOU: alembic_version ausente ou vazia no banco restaurado." >&2
  exit 1
fi
echo "[restauração] alembic_version = ${versao}"

DIR_SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESTAURADO="$(mktemp)"
trap 'rm -f "$RESTAURADO"' EXIT
bash "$DIR_SCRIPTS/contar_tabelas.sh" "$URL" > "$RESTAURADO"
total_tabelas="$(wc -l < "$RESTAURADO" | tr -d ' ')"
total_linhas="$(awk -F= '{s += $2} END {print s + 0}' "$RESTAURADO")"
echo "[restauração] ${total_tabelas} tabelas, ${total_linhas} linhas restauradas"

if [ -n "${CONTAGENS_ORIGEM:-}" ]; then
  [ -f "$CONTAGENS_ORIGEM" ] || { echo "[restauração] CONTAGENS_ORIGEM não encontrado." >&2; exit 2; }
  # A contagem da origem tem de estar INTEIRA e VÁLIDA, senão a comparação
  # abaixo aprovaria só uma parte: linha sem número ("tabela=") contaria como
  # zero, e um arquivo que parou no meio conferiria só as tabelas que listou.
  invalidas="$(grep -cvE '^[^=]+=[0-9]+$' "$CONTAGENS_ORIGEM" || true)"
  if [ "$invalidas" != "0" ]; then
    echo "[restauração] FALHOU: contagem da origem com ${invalidas} linha(s) sem número." >&2
    exit 1
  fi
  tabelas_origem="$(grep -c '=' "$CONTAGENS_ORIGEM" || true)"
  if [ "$tabelas_origem" -lt "$total_tabelas" ]; then
    echo "[restauração] FALHOU: contagem da origem incompleta (${tabelas_origem} tabelas; restauradas ${total_tabelas})." >&2
    exit 1
  fi
  awk -F= '
    NR == FNR { restaurado[$1] = $2; next }
    {
      origem = $2 + 0
      if (!($1 in restaurado)) { printf "[restauração] FALTA a tabela %s (origem %d)\n", $1, origem; falhas++; next }
      r = restaurado[$1] + 0
      minimo = int(origem * 0.98)
      if (r < minimo) { printf "[restauração] POUCAS linhas em %s: %d restauradas, %d na origem\n", $1, r, origem; falhas++ }
      else if (r != origem) { printf "[restauração] aviso: %s %d restauradas × %d na origem (dentro da folga)\n", $1, r, origem }
    }
    END { if (falhas) { printf "[restauração] FALHOU: %d tabela(s) divergente(s)\n", falhas; exit 1 } }
  ' "$RESTAURADO" "$CONTAGENS_ORIGEM"
  echo "[restauração] contagens conferidas com a origem: OK"
fi

echo "[restauração] OK: o backup decifra, aplica sem erro e traz o schema com a versão de migração."
