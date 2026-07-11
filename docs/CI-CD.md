# Pipeline de CI/CD — Constela Edu

Visão geral do que roda automaticamente, o que **bloqueia o merge** e como
ligar a proteção de branch e os deploys.

## Workflows (`.github/workflows/`)

| Arquivo | Quando roda | Papel |
|---|---|---|
| `ci.yml` | push na `main` e todo PR | Qualidade: lint, testes+cobertura, build, E2E, imagens Docker |
| `security.yml` | PR, push na `main` e **toda segunda** (cron) | Vulnerabilidades: pip-audit, npm audit, Trivy |
| `deploy.yml` | push na `main` (staging) / release (produção) / manual | Entrega contínua com aprovação em produção |
| `desktop-release.yml` | tags de release do desktop | Build do app Tauri (pré-existente) |

Nenhum job usa `continue-on-error` nos gates de qualidade: **qualquer erro
reprova o run** ("falha obrigatória em erro"). Com a proteção de branch (abaixo),
um run vermelho **barra o merge**.

### `ci.yml` — 8 jobs (rodam em paralelo)
1. **Lint** — `ruff check backend` (config em `backend/ruff.toml`, focada em bugs
   reais) + `typecheck` (tsc) de core, quest-core e mobile.
2. **Testes backend** — `pytest` com cobertura (`--cov=app`, gate `fail_under=88`),
   publica `coverage.xml` como artefato (e envia ao Codecov se `CODECOV_TOKEN` existir).
3. **Migrações Alembic (PostgreSQL real)** — `alembic upgrade` num Postgres de
   serviço; pega incompatibilidade de dialeto que o SQLite dos testes não vê.
4. **Testes web** — `vitest run --coverage`, publica a cobertura.
5. **Testes mobile** — `vitest` da lógica pura do app (cifra AES, fila offline, retry).
6. **Build** — `vite build` do web e do quest (garante que compila para produção).
7. **E2E** — Playwright: sobe backend + frontend reais e testa no Chromium;
   publica o `playwright-report`.
8. **Imagens Docker** — `docker build` do backend e do web (valida os Dockerfiles).

### `security.yml` — 3 jobs
- **pip-audit** — audita `backend/requirements.txt`. Reprova em qualquer CVE,
  exceto uma *allowlist* explícita e comentada (frameworks que fixam a versão —
  ex.: starlette pelo FastAPI — ou CVEs sem correção). O Dependabot abre PR
  quando surge correção.
- **npm audit** — reprova em **CRITICAL** (produção) e **reporta** high/moderate
  (hoje só na árvore do Expo/mobile; a correção é um upgrade de SDK conduzido
  pelo Dependabot).
- **Trivy** — escaneia o código e as **imagens Docker**; reprova em CRITICAL com
  correção disponível (`--ignore-unfixed`) e envia o relatório HIGH+ (SARIF) para
  a aba **Security** do GitHub.

> Por que não bloquear em todo HIGH? Porque as pendências de hoje são
> framework-pinned (FastAPI/starlette, Expo SDK): bloquear tudo deixaria o
> pipeline **permanentemente vermelho**, travando qualquer merge. A política
> bloqueia o que é acionável agora (crítico/corrigível) e usa o **Dependabot**
> para conduzir o resto — que é exatamente o papel dele.

## Dependabot (`.github/dependabot.yml`)
Abre PRs semanais de atualização para **pip** (backend), **npm** (todos os
workspaces) e **github-actions**. Patches/minors são agrupados num PR só; majors
vêm separados. Cada PR passa por CI + segurança antes de poder entrar.

## Proteção de branch (obrigatória)
O arquivo `.github/rulesets/protecao-main.json` é um **ruleset importável**.
Para aplicar (uma vez), via UI: *Settings → Rules → Rulesets → New ruleset →
Import*, selecione o arquivo. Ou via CLI:

```bash
gh api repos/{owner}/{repo}/rulesets --method POST \
  --input .github/rulesets/protecao-main.json
```

O ruleset exige, na `main`: mudança **via Pull Request**, **todos os checks de
CI e segurança verdes**, histórico linear, e proíbe force-push e deleção. O
número de aprovações está em **0** (prático para mantenedor solo); suba para 1
ao ter colaboradores.

## Deploy (staging e produção)
`deploy.yml` fica **desligado** até você habilitar (não falha sem os segredos):

1. **Segredos** (*Settings → Secrets and variables → Actions*): `RAILWAY_TOKEN`,
   `RAILWAY_SERVICE_STAGING`, `RAILWAY_SERVICE_PROD` (e, opcionalmente,
   `VERCEL_TOKEN`/`VERCEL_ORG_ID`/`VERCEL_PROJECT_ID` se for deployar o front por
   aqui em vez da integração git da Vercel).
2. **Environments** (*Settings → Environments*): crie `staging` e `producao`.
   No `producao`, marque **Required reviewers** — isso cria o **portão de
   aprovação manual**: o deploy de produção **pausa** até alguém aprovar.
3. **Variável** `DEPLOY_ENABLED = true`.

Fluxo: `push na main` → **staging** automático; `release publicada` → **produção**
(após aprovação); "Run workflow" → deploy manual escolhendo o ambiente.

> A Vercel pode já fazer deploy do front automaticamente pelo git. Se for o
> caso, remova os passos da Vercel do `deploy.yml` e deixe só o backend
> (Railway) — evita deploy duplicado.
