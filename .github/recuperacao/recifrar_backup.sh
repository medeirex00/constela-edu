#!/usr/bin/env bash
# =============================================================================
# Recifra UM backup (constela_*.sql.gz.enc) da senha ANTIGA para a senha NOVA,
# sem nunca gravar o conteúdo em texto puro no disco (só pipes).
#
# Uso:
#   BACKUP_PASSPHRASE_ANTIGA=... BACKUP_PASSPHRASE=... \
#     bash scripts/recifrar_backup.sh <entrada.enc> <saida.enc>
#
# Conferências (qualquer falha = código != 0 e NENHUM arquivo de saída):
#   1. a entrada decifra com a senha antiga E o gzip dentro dela está íntegro
#      (gunzip -t confere o CRC do arquivo inteiro);
#   2. a saída decifra com a senha NOVA, o gzip está íntegro, e o conteúdo
#      comprimido é BIT A BIT o mesmo da entrada (sha256 dos dois lados).
# Mesmos parâmetros de cifra do backup_postgres.sh (AES-256-CBC, PBKDF2, sal),
# então a saída restaura com o verificar_restauracao.sh de sempre.
# As senhas vão pelo ambiente (env:), nunca pela linha de comando.
# =============================================================================
set -euo pipefail

ENTRADA="${1:?Informe o arquivo de entrada (.enc).}"
SAIDA="${2:?Informe o arquivo de saída (.enc).}"
: "${BACKUP_PASSPHRASE_ANTIGA:?Defina BACKUP_PASSPHRASE_ANTIGA (a senha que cifrou a entrada).}"
: "${BACKUP_PASSPHRASE:?Defina BACKUP_PASSPHRASE (a senha nova).}"
[ -f "$ENTRADA" ] || { echo "[recifrar] entrada não encontrada: $ENTRADA" >&2; exit 2; }
[ ! -e "$SAIDA" ] || { echo "[recifrar] RECUSADO: a saída já existe: $SAIDA" >&2; exit 2; }
# A migração existe para TROCAR a senha: igual à antiga (ou curta) não é troca.
[ "$BACKUP_PASSPHRASE" != "$BACKUP_PASSPHRASE_ANTIGA" ] \
  || { echo "[recifrar] RECUSADO: a senha nova é igual à antiga." >&2; exit 2; }
[ "${#BACKUP_PASSPHRASE}" -ge 32 ] \
  || { echo "[recifrar] RECUSADO: a senha nova tem menos de 32 caracteres." >&2; exit 2; }

decifrar() {  # $1 = arquivo, $2 = NOME da variável com a senha
  openssl enc -d -aes-256-cbc -pbkdf2 -pass "env:$2" -in "$1"
}

# 1. Entrada íntegra com a senha antiga: gzip sem erro (CRC do arquivo inteiro)
#    e dump COMPLETO — o pg_dump só escreve o rodapé no fim; um dump cortado com
#    gzip íntegro (sem índices, chaves, restrições) não passa.
decifrar "$ENTRADA" BACKUP_PASSPHRASE_ANTIGA | gunzip -t
fim="$(decifrar "$ENTRADA" BACKUP_PASSPHRASE_ANTIGA | gunzip -c | tail -c 4096)"
[[ "$fim" == *"-- PostgreSQL database dump complete"* ]] \
  || { echo "[recifrar] FALHOU: o dump de ${ENTRADA##*/} não termina com o rodapé do pg_dump (incompleto)." >&2; exit 1; }
hash_entrada="$(decifrar "$ENTRADA" BACKUP_PASSPHRASE_ANTIGA | sha256sum | cut -d' ' -f1)"

# 2. Recifra o gzip (sem descomprimir) num arquivo TEMPORÁRIO ao lado da saída.
tmp="${SAIDA}.parcial"
trap 'rm -f "$tmp"' EXIT
decifrar "$ENTRADA" BACKUP_PASSPHRASE_ANTIGA \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE -out "$tmp"

# 3. A saída decifra com a senha NOVA, é gzip íntegro e é o MESMO conteúdo.
decifrar "$tmp" BACKUP_PASSPHRASE | gunzip -t
hash_saida="$(decifrar "$tmp" BACKUP_PASSPHRASE | sha256sum | cut -d' ' -f1)"
if [ "$hash_entrada" != "$hash_saida" ]; then
  echo "[recifrar] FALHOU: o conteúdo recifrado difere da entrada." >&2
  exit 1
fi

mv "$tmp" "$SAIDA"
trap - EXIT
echo "[recifrar] OK: ${ENTRADA##*/} → ${SAIDA##*/} (conteúdo idêntico)"
