#!/usr/bin/env bash
# =============================================================================
# TRANSFERÊNCIA (só depois de um diagnóstico OK): recifra os backups aprovados
# do secret BACKUP_PASSPHRASE (o que cifrou os públicos) para o secret
# TEMPORÁRIO BACKUP_PASSPHRASE_TRANSFERENCIA, para o repositório PRIVADO importar.
# Saída em <destino>: os .enc recifrados + SHA256SUMS + MANIFESTO.txt (id e nome).
# Os artefatos originais NÃO são tocados (só GET). Nada de senha/conteúdo no log.
# Uso: bash transferir_backups.sh "<id>,<id>,…" <destino>
# =============================================================================
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=comum.sh
source "$DIR/comum.sh"
IDS="$(printf '%s' "${1:?Informe os ids.}" | tr -d ' ')"
DEST="${2:?Informe a pasta de destino.}"
# Só os 6 aprovados pelo dono + o reserva do de 20/09.
PERMITIDOS=" 10604370780 10690878242 10746600820 11032708030 11415732920 11820675729 10638197659 "

[[ "$IDS" =~ ^[0-9]+(,[0-9]+){0,5}$ ]] || { echo "::error::ids: de 1 a 6 números separados por vírgula."; exit 1; }
for id in ${IDS//,/ }; do
  [[ "$PERMITIDOS" == *" $id "* ]] || { echo "::error::id $id fora da lista aprovada."; exit 1; }
done
[ "$(tr ',' '\n' <<< "$IDS" | sort | uniq -d | wc -l)" -eq 0 ] || { echo "::error::id repetido."; exit 1; }
: "${BACKUP_PASSPHRASE:?secret BACKUP_PASSPHRASE ausente}"
: "${BACKUP_PASSPHRASE_TRANSFERENCIA:?secret BACKUP_PASSPHRASE_TRANSFERENCIA ausente}"

mkdir -p "$DEST"
W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
: > "$DEST/MANIFESTO.txt"
for id in ${IDS//,/ }; do
  enc="$(baixar_artefato "$id" "$W")" || { echo "::error::artefato $id: falha ao baixar/conferir (etapa $?)."; exit 1; }
  nome="${enc##*/}"
  # recifrar_backup.sh confere: decifra com a antiga + gzip íntegro + rodapé do
  # pg_dump; recifra; decifra com a nova; conteúdo idêntico (sha256 dos dois lados).
  BACKUP_PASSPHRASE_ANTIGA="$BACKUP_PASSPHRASE" BACKUP_PASSPHRASE="$BACKUP_PASSPHRASE_TRANSFERENCIA" \
    bash "$DIR/recifrar_backup.sh" "$enc" "$DEST/$nome"
  rm -f "$enc"
  printf '%s %s\n' "$id" "$nome" >> "$DEST/MANIFESTO.txt"
done
(cd "$DEST" && sha256sum constela_*.sql.gz.enc > SHA256SUMS)
n="$(grep -c . "$DEST/MANIFESTO.txt")"
esperado="$(tr ',' '\n' <<< "$IDS" | grep -c .)"
[ "$n" -eq "$esperado" ] && [ "$(grep -c 'constela_' "$DEST/SHA256SUMS")" -eq "$esperado" ] \
  || { echo "::error::transferidos=$n, esperados=$esperado: não batem."; exit 1; }
echo "[transferir] ${n} de ${esperado} backup(s) recifrado(s) para a senha de transferência."
