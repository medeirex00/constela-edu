# Funções comuns da recuperação dos backups (incluído com "source").
# SÓ LEITURA no GitHub: GET de metadados e download de artefatos DESTE repositório.

api() {  # GET na API com o token do job; qualquer erro HTTP = código != 0
  curl -fsS --proto '=https' --retry 3 --retry-delay 2 \
    -H "Authorization: Bearer ${GH_TOKEN:?}" -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" "$@"
}

# baixar_artefato <id> <pasta_de_trabalho>
# Baixa um artefato "backup-postgres-*" DESTE repositório e confere:
#   gerado pelo main do próprio repositório, não expirado (folga de 30 min),
#   zip com o MESMO sha256 registrado pelo GitHub (digest), exatamente um
#   constela_*.sql.gz.enc com cabeçalho do openssl ("Salted__").
# Imprime o caminho do .enc. Código != 0 indica a etapa que falhou:
#   10 metadados · 11 inelegível · 12 download · 13 digest · 14 unzip · 15 conteúdo · 16 formato
baixar_artefato() {
  local id="$1" w="$2/$1" digest
  mkdir -p "$w"
  api "https://api.github.com/repos/${GITHUB_REPOSITORY:?}/actions/artifacts/${id}" > "$w/meta.json" 2>/dev/null || return 10
  digest="$(python3 - "$w/meta.json" 2>/dev/null <<'PY'
import json, sys
from datetime import datetime, timedelta, timezone
a = json.load(open(sys.argv[1])); w = a.get("workflow_run") or {}
expira = datetime.fromisoformat(a["expires_at"].replace("Z", "+00:00"))
ok = (a["name"].startswith("backup-postgres-") and not a["expired"]
      and expira > datetime.now(timezone.utc) + timedelta(minutes=30)
      and w.get("head_branch") == "main" and w.get("head_repository_id") == w.get("repository_id")
      and (a.get("digest") or "").startswith("sha256:"))
print(a["digest"][7:] if ok else "")
PY
)" 2>/dev/null || return 11
  [ -n "$digest" ] || return 11
  api -L -o "$w/a.zip" "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/artifacts/${id}/zip" 2>/dev/null || return 12
  [ "$(sha256sum "$w/a.zip" | cut -d' ' -f1)" = "$digest" ] || return 13
  unzip -q -o "$w/a.zip" -d "$w/x" 2>/dev/null || return 14
  rm -f "$w/a.zip"
  local encs=("$w"/x/constela_*.sql.gz.enc)
  { [ "${#encs[@]}" -eq 1 ] && [ -f "${encs[0]}" ]; } || return 15
  [ "$(head -c 8 "${encs[0]}")" = "Salted__" ] || return 16
  printf '%s\n' "${encs[0]}"
}
