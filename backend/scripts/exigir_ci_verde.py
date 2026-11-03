"""Portão de deploy: recusa publicar um commit cujo CI do push no `main` não passou.

Quem chama:
* o job `ci-verde` do `.github/workflows/deploy.yml` (deploy manual), com
  REPO=github.repository, SHA=github.sha e GH_TOKEN=github.token;
* OPCIONAL — o Pre-deploy do Railway (configuração do dono): com EXIGIR_CI_VERDE=1 no
  serviço, o próprio `python -m scripts.migrate` chama este portão ANTES de tocar no
  banco (o comando continua um só: o Railway roda o Pre-deploy de um serviço com
  Dockerfile sem shell, e `a && b` não funcionaria). O Railway expõe o commit do deploy
  em RAILWAY_GIT_COMMIT_SHA e o repositório em RAILWAY_GIT_REPO_OWNER/NAME — só num
  deploy disparado pelo GitHub; um `railway up` não as traz e é recusado. Com saída
  diferente de 0, o deploy não segue e o anterior continua no ar. É o que fecha o
  buraco do "Wait for CI": ele IGNORA um CI cancelado quando outro workflow do mesmo
  commit (o Segurança) passou. No Railway, o GH_TOKEN é OBRIGATÓRIO mesmo com o
  repositório público: sem token, o limite de 60 consultas/h é por IP de saída, e o
  do Railway é compartilhado — um 403/429 de outro cliente recusaria o deploy.

Regra: vale a execução MAIS RECENTE (pela data, não pela ordem da API) do ci.yml
disparada por PUSH no `main` para EXATAMENTE este commit, e ela tem de estar
`completed/success`. Em andamento, reprovada, cancelada, ausente, só de pull_request
(que testou o merge commit, não este), de outro ramo, sem commit/repositório válidos,
ou a API fora do ar / sem permissão = recusa (sai com 1). Só biblioteca padrão: roda
no runner do GitHub e no container do Railway sem instalar nada. O token (GH_TOKEN ou
GITHUB_TOKEN; num repositório privado, um token só de leitura de Actions) nunca é
impresso.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

try:
    from scripts._saida import forcar_saida_utf8
except ImportError:  # rodado como arquivo: o sys.path[0] é a própria scripts/
    from _saida import forcar_saida_utf8

API = "https://api.github.com"
WORKFLOW = "ci.yml"
_SHA = re.compile(r"[0-9a-f]{40}")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def consultar(repo: str, sha: str, token: str | None, abrir=urllib.request.urlopen) -> list[dict]:
    url = (f"{API}/repos/{repo}/actions/workflows/{WORKFLOW}/runs"
           f"?head_sha={sha}&event=push&branch=main&per_page=100")
    cabecalhos = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                  "User-Agent": "constela-exigir-ci-verde"}
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"
    with abrir(urllib.request.Request(url, headers=cabecalhos), timeout=30) as resposta:
        return json.load(resposta).get("workflow_runs") or []


def situacao(execucoes: list[dict], sha: str) -> str:
    """`status/conclusion` da execução mais recente do push no main para este commit."""
    do_main = [r for r in execucoes
               if r.get("event") == "push" and r.get("head_branch") == "main"
               and r.get("head_sha") == sha]
    do_main.sort(key=lambda r: (r.get("created_at") or "", r.get("run_attempt") or 0))
    if not do_main:
        return "ausente"
    ultima = do_main[-1]
    return f"{ultima.get('status')}/{ultima.get('conclusion')}"


def alvo(env) -> tuple[str, str]:
    sha = (env.get("SHA") or env.get("RAILWAY_GIT_COMMIT_SHA") or "").strip().lower()
    repo = (env.get("REPO") or env.get("GITHUB_REPOSITORY") or "").strip()
    if not repo and env.get("RAILWAY_GIT_REPO_OWNER") and env.get("RAILWAY_GIT_REPO_NAME"):
        repo = f"{env['RAILWAY_GIT_REPO_OWNER']}/{env['RAILWAY_GIT_REPO_NAME']}"
    return repo, sha


def main(env=None, abrir=urllib.request.urlopen) -> int:
    env = os.environ if env is None else env
    repo, sha = alvo(env)
    if not _SHA.fullmatch(sha) or not _REPO.fullmatch(repo):
        print("::error::Sem o commit (40 hexadecimais) ou o repositório do deploy: deploy "
              "recusado. Um `railway up` manual não traz RAILWAY_GIT_COMMIT_SHA.")
        return 1
    try:
        execucoes = consultar(repo, sha, env.get("GH_TOKEN") or env.get("GITHUB_TOKEN"), abrir)
        estado = situacao(execucoes, sha)
    except Exception as erro:  # noqa: BLE001 — qualquer falha aqui RECUSA (falha fechada)
        codigo = f" HTTP {erro.code}" if isinstance(erro, urllib.error.HTTPError) else ""
        print(f"::error::Não foi possível consultar o CI no GitHub ({type(erro).__name__}"
              f"{codigo}): deploy recusado.")
        return 1
    print(f"CI do push no main para o commit {sha}: {estado}")
    if estado != "completed/success":
        print(f"::error::O CI deste commit no main não está verde ({estado}): deploy recusado.")
        return 1
    return 0


def principal(argv: list[str]) -> int:
    """Pela linha de comando: argumento nenhum. Um `portão && migrate` passado sem
    shell chegaria aqui como argumentos — recusar evita o deploy "verde" sem migrate."""
    forcar_saida_utf8()
    if argv:
        print(f"::error::Argumentos inesperados ({' '.join(argv)!r}): deploy recusado. "
              "Sem shell, `&&` não encadeia comandos — use EXIGIR_CI_VERDE=1 com o migrate.")
        return 1
    return main()


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1:]))
