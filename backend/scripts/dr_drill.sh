#!/usr/bin/env bash
# =============================================================================
# DR DRILL — teste REAL de recuperação de desastre, fim a fim e automatizado.
#
# Faz: backup do banco de ORIGEM → cifra → decifra → restaura num banco
# ISOLADO (scratch) → compara contagens de tabelas-chave origem×restaurado →
# confere a versão do Alembic → veredito PASSOU/FALHOU. É o "game day" do
# docs/DR-RUNBOOK.md numa linha de comando.
#
# NUNCA restaura sobre a origem: exige um banco scratch DIFERENTE e vazio.
#
# Uso (aponte a ORIGEM para o STAGING; o scratch é um banco descartável vazio):
#   SRC_DATABASE_URL="postgresql://.../staging" \
#   DR_SCRATCH_URL="postgresql://.../dr_scratch" \
#   BACKUP_PASSPHRASE="..." \
#     bash backend/scripts/dr_drill.sh
#
# Requisitos: pg_dump, psql, gzip, openssl.
# =============================================================================
set -euo pipefail

: "${SRC_DATABASE_URL:?Defina SRC_DATABASE_URL (banco de ORIGEM — use o STAGING).}"
: "${DR_SCRATCH_URL:?Defina DR_SCRATCH_URL (banco scratch VAZIO e isolado).}"
: "${BACKUP_PASSPHRASE:?Defina BACKUP_PASSPHRASE (senha de cifra do backup).}"

norm() { echo "${1/postgresql+psycopg:\/\//postgresql://}" | sed 's#postgres+psycopg://#postgres://#'; }
SRC="$(norm "$SRC_DATABASE_URL")"
DST="$(norm "$DR_SCRATCH_URL")"

if [ "$SRC" = "$DST" ]; then
  echo "[dr] ABORTADO: origem e scratch são o MESMO banco. O scratch deve ser separado."
  exit 2
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ENC="$TMP/backup.sql.gz.enc"
SQL="$TMP/backup.sql"

echo "[dr] 1/5 Backup cifrado da origem..."
pg_dump "$SRC" --no-owner --no-privileges --format=plain \
  | gzip -9 | openssl enc -aes-256-cbc -pbkdf2 -salt -pass "env:BACKUP_PASSPHRASE" -out "$ENC"
echo "[dr]     -> $(du -h "$ENC" | cut -f1) cifrado"

echo "[dr] 2/5 Decifrar + descomprimir..."
openssl enc -d -aes-256-cbc -pbkdf2 -pass "env:BACKUP_PASSPHRASE" -in "$ENC" | gunzip > "$SQL"

echo "[dr] 3/5 Restaurar no banco scratch (isolado)..."
psql "$DST" -v ON_ERROR_STOP=1 -q < "$SQL"

echo "[dr] 4/5 Conferir integridade (contagens origem × restaurado)..."
TABELAS="escolas turmas alunos matriculas notas usuarios sincronizacao_execucoes logs_auditoria"
FALHAS=0
printf "%-28s %12s %12s  %s\n" "tabela" "origem" "restaurado" "ok"
for t in $TABELAS; do
  c_src=$(psql "$SRC" -tAc "SELECT count(*) FROM $t" 2>/dev/null || echo "ERR")
  c_dst=$(psql "$DST" -tAc "SELECT count(*) FROM $t" 2>/dev/null || echo "ERR")
  if [ "$c_src" = "$c_dst" ] && [ "$c_src" != "ERR" ]; then ok="✓"; else ok="✗"; FALHAS=$((FALHAS+1)); fi
  printf "%-28s %12s %12s  %s\n" "$t" "$c_src" "$c_dst" "$ok"
done

echo "[dr] 5/5 Conferir versão do schema (Alembic)..."
v_src=$(psql "$SRC" -tAc "SELECT version_num FROM alembic_version" 2>/dev/null || echo "ERR")
v_dst=$(psql "$DST" -tAc "SELECT version_num FROM alembic_version" 2>/dev/null || echo "ERR")
echo "[dr]     origem=$v_src  restaurado=$v_dst"
[ "$v_src" = "$v_dst" ] && [ "$v_src" != "ERR" ] || FALHAS=$((FALHAS+1))

echo
if [ "$FALHAS" -eq 0 ]; then
  echo "[dr] VEREDITO: PASSOU — backup restaura íntegro e completo."
  echo "[dr] Anote a data deste drill no docs/DR-RUNBOOK.md (§6)."
  exit 0
else
  echo "[dr] VEREDITO: FALHOU ($FALHAS divergência(s)). NÃO confie no backup até resolver."
  exit 1
fi
