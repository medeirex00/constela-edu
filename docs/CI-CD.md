# Pipeline de CI/CD — Constela Edu

Visão geral do que roda automaticamente, o que **bloqueia o merge** e como
ligar a proteção de branch e os deploys.

## Workflows (`.github/workflows/`)

| Arquivo | Quando roda | Papel |
|---|---|---|
| `ci.yml` | push na `main` e todo PR | Qualidade: lint, typecheck, testes+cobertura, testes em PostgreSQL real, migrações em PostgreSQL real, testes do Quest, build, E2E, imagens Docker com fumaça do backend |
| `security.yml` | PR, push na `main` e **toda segunda** (cron) | Vulnerabilidades: pip-audit, npm audit, Trivy |
| `deploy.yml` | **só manual** ("Run workflow"), desligado até `DEPLOY_ENABLED=true` | Deploy opcional com o portão `ci-verde` (CI do push no `main` verde naquele commit), refeito depois da aprovação. **Não** é o caminho real: o Railway e a Vercel publicam pelo git (ver "Deploy") |
| `backup.yml` | diário (cron) e manual, só com `BACKUP_ENABLED=true` | Backup do banco; **recusa rodar em repositório público** (o backup real roda no repositório privado de backups) |
| `desktop-release.yml` | tags de release do desktop | Build do app Tauri (pré-existente) |

Nenhum job usa `continue-on-error` nos gates de qualidade: **qualquer erro
reprova o run** ("falha obrigatória em erro"). Com a proteção de branch (abaixo),
um run vermelho **barra o merge**.

### `ci.yml` — 11 jobs (rodam em paralelo)
1. **Lint** — `ruff check backend` (config em `backend/ruff.toml`, focada em bugs
   reais) + `typecheck` (tsc) de core, quest-core e mobile.
2. **Typecheck + testes do core** — tsc de core, quest-core e mobile e os testes do
   `@constela/core` (cliente HTTP compartilhado).
3. **Testes backend** — `pytest` com cobertura (`--cov=app`, gate `fail_under=88`),
   publica `coverage.xml` como artefato (e envia ao Codecov se `CODECOV_TOKEN` existir).
   Roda em SQLite: os testes marcados `postgres` pulam aqui.
4. **Testes backend no PostgreSQL real** — `pytest -m postgres` (travas `FOR UPDATE`,
   corridas entre transações, migrações e prontidão em processo separado) contra um
   Postgres de serviço, com o mesmo ambiente do job 3 mais `TEST_DATABASE_URL_PG`.
   Antes do pytest, confere que o banco é local, tem `test` no nome e conecta (senão
   os testes pulariam em silêncio).
5. **Migrações Alembic (PostgreSQL real)** — `alembic upgrade` num Postgres de
   serviço pelo caminho de produção, idempotência e RLS ligado (sem FORCE) em toda
   tabela; pega incompatibilidade de dialeto que o SQLite dos testes não vê.
6. **Testes web** — `vitest run --coverage`, publica a cobertura.
7. **Testes mobile** — `vitest` da lógica pura do app (cifra AES, fila offline, retry).
8. **Testes quest** — `vitest` das telas do app dos alunos (`apps/quest/src/test`).
9. **Build** — `vite build` do web e do quest (garante que compila para produção).
10. **E2E** — Playwright: sobe backend + frontend reais e testa no Chromium;
    publica o `playwright-report`.
11. **Imagens Docker** — `docker build` do backend e do web (valida os Dockerfiles) e a
    **fumaça do backend**: a imagem sobe com `ENV=producao`, chaves fictícias geradas
    na hora (diferentes entre si), `DOCS_HABILITADOS=false` e o Postgres de serviço
    **vazio**, numa rede Docker interna (sem saída para a internet). Por dentro do
    container, confere que `/api/health/ready` responde 200 com o schema em dia (o
    entrypoint migrou), que `/docs`, `/redoc`, `/openapi.json` e `/metrics` respondem
    404, que o processo não é root, que as pastas de dados aceitam escrita e que o
    Chromium do robô abre; depois derruba tudo. O 1º boot da imagem nova deixa de ser
    a produção. A forma dos três jobs novos está fixada em
    `backend/tests/test_ci_verificacoes.py`.

No `main`, cada run do CI tem o seu grupo de concorrência (nunca é cancelado por um
push seguinte); em PR, um push novo cancela o run anterior do mesmo ramo.

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
CI e segurança verdes** (cada job do `ci.yml` e do `security.yml`; o teste
`test_workflows_deploy.py` reprova se um job ficar de fora) com o ramo
**atualizado** antes do merge, histórico linear, e proíbe force-push e deleção. O
número de aprovações está em **0** (prático para mantenedor solo); suba para 1
ao ter colaboradores.

> **Estado em 21/10/2026 (leitura da API):** o ruleset **não está aplicado** — o
> `main` não tem proteção nem ruleset. Aplicá-lo é decisão do dono e só faz sentido
> depois que o `CI` e o `Segurança` do `main` estiverem verdes (antes disso, nenhum
> PR passa).

## Deploy (staging e produção)
O caminho REAL de produção não é este arquivo: o Railway e a Vercel publicam a cada
push no `main` pela integração git. O que falta para eles só publicarem com o CI
verde (Wait for CI em todos os serviços Railway, o portão
`scripts/exigir_ci_verde.py` no Pre-deploy pela variável `EXIGIR_CI_VERDE=1` com
`GH_TOKEN`, e os Deployment Checks da Vercel) está em
`docs/operacao/PRODUCAO-ENV-E-MIGRACOES.md`, passo 5. Com o portão ligado no
Railway, o `deploy.yml` não publica o backend (o `railway up` não traz o commit).

`deploy.yml` é **só manual** ("Run workflow") e fica **desligado** até você
habilitar. Nenhum job de deploy roda sem o job `ci-verde`, que recusa publicar se o
CI do push no `main` daquele commit não estiver concluído com sucesso — e cada job de
deploy refaz a mesma conferência como 1º passo, depois da aprovação do Environment
(que pode vir horas depois; um re-run reprovado nesse meio tempo barra). Para ligar:

1. **Environments** (*Settings → Environments*): crie `staging` e `producao`, cada
   um com *Deployment branches and tags: main*. No `producao`, marque **Required
   reviewers** — o deploy de produção **pausa** até alguém aprovar.
2. **Segredos** `RAILWAY_TOKEN`, `RAILWAY_SERVICE_STAGING`, `RAILWAY_SERVICE_PROD` (e,
   opcionalmente, `VERCEL_TOKEN`/`VERCEL_ORG_ID`/`VERCEL_PROJECT_ID`) **somente como
   Environment secrets** do `staging`/`producao` — nunca em *Repository* ou
   *Organization secrets*: um segredo de repositório é lido por qualquer job de
   qualquer ramo, e um ramo com o `deploy.yml` sem o portão publicaria com eles.
3. **Variável** `DEPLOY_ENABLED = true`.

> Backend (Railway) e web (Vercel) publicam em jobs separados, cada um só depois do
> `ci-verde`. Se a Vercel já publica o front pelo git, não guarde `VERCEL_TOKEN` (o
> passo do web é pulado) — evita deploy duplicado. Com o portão de CI ligado no
> Railway (`EXIGIR_CI_VERDE=1`), o job do backend é sempre recusado (o `railway up`
> não traz o commit): o backend se publica pelo *Deploy* do próprio Railway.
