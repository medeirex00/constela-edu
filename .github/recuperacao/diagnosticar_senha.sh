#!/usr/bin/env bash
# =============================================================================
# DIAGNÓSTICO: o secret BACKUP_PASSPHRASE deste repositório abre o backup <id>?
# Imprime UMA linha — "RESULTADO: OK", "RESULTADO: FALHOU" ou
# "RESULTADO: ERRO TÉCNICO (<etapa>)" — e grava a mesma coisa no resumo do job.
# Não imprime senha nem conteúdo; não sobe artefato; não altera nada.
# Mesma cifra do backup público: openssl enc -aes-256-cbc -pbkdf2 -pass env:…
# Saída: 0 = OK · 1 = FALHOU · 2 = ERRO TÉCNICO.
# =============================================================================
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=comum.sh
source "$DIR/comum.sh"
ID="${1:?Informe o id do artefato.}"
# Só os 6 aprovados + o reserva do de 20/09.
PERMITIDOS=" 10604370780 10690878242 10746600820 11032708030 11415732920 11820675729 10638197659 "
W="$(mktemp -d)"
trap 'rm -rf "$W"; unset BACKUP_PASSPHRASE' EXIT

fim() {
  echo "RESULTADO: $1"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '### Diagnóstico da senha dos backups (artefato %s): **%s**\n' "$ID" "$1" >> "$GITHUB_STEP_SUMMARY"
  fi
  exit "$2"
}

[[ "$ID" =~ ^[0-9]+$ && "$PERMITIDOS" == *" $ID "* ]] || fim "ERRO TÉCNICO (id fora da lista aprovada)" 2
[ -n "${BACKUP_PASSPHRASE:-}" ] || fim "ERRO TÉCNICO (secret BACKUP_PASSPHRASE ausente ou vazio)" 2

enc="$(baixar_artefato "$ID" "$W")"; rc=$?
case "$rc" in
  0) ;;
  10) fim "ERRO TÉCNICO (metadados do artefato)" 2 ;;
  11) fim "ERRO TÉCNICO (artefato inelegível, expirando ou sem digest)" 2 ;;
  12) fim "ERRO TÉCNICO (download)" 2 ;;
  13) fim "ERRO TÉCNICO (integridade: sha256 do zip difere do registrado pelo GitHub)" 2 ;;
  *) fim "ERRO TÉCNICO (conteúdo do artefato, etapa $rc)" 2 ;;
esac

# 1) Senha: decifra o arquivo INTEIRO (o padding do último bloco só confere com a
#    senha certa). Nada vai para a tela nem para o disco.
openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$enc" -out /dev/null 2>/dev/null \
  || fim "FALHOU" 1
# 2) Conteúdo: gzip íntegro (CRC). Decifrou sem erro mas não é gzip = senha errada que
#    passou no padding por acaso (~1/256) ou arquivo corrompido: repetir noutro artefato.
if ! openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$enc" 2>/dev/null | gunzip -t 2>/dev/null; then
  fim "FALHOU (decifrou sem erro de bloco, mas não é gzip: repetir o diagnóstico noutro artefato)" 1
fi
# Dump completo: o pg_dump só escreve o rodapé no fim (só se conta a ocorrência).
rodape="$(openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$enc" 2>/dev/null \
          | gunzip -c 2>/dev/null | tail -c 4096 | grep -c -- '-- PostgreSQL database dump complete' || true)"
[ "${rodape:-0}" -ge 1 ] 2>/dev/null || fim "ERRO TÉCNICO (a senha abre, mas o dump está incompleto)" 2
fim "OK" 0
