# Plano de Continuidade e Transferência — Constela Edu

Objetivo: reduzir o risco de "um único desenvolvedor" desde já. Este documento
permite que **outra pessoa técnica assuma o projeto** sem depender do conhecimento
na cabeça de uma só pessoa, e lista **tudo que hoje depende exclusivamente do
dono** e precisa ser compartilhado/transferido quando houver equipe.

> Status atual: 1 desenvolvedor (fase inicial). Ao adotar a Secretaria, formar
> equipe. Este plano é o "manual de sucessão".

---

## 1. Visão geral da arquitetura (mapa mental de 2 minutos)

| Camada | Tecnologia | Onde roda | Código |
|--------|-----------|-----------|--------|
| Backend / API | FastAPI + SQLAlchemy + Alembic | **Railway** | `backend/` |
| Frontend web | React + TypeScript + Vite + Tailwind | **Vercel** | `apps/web/` |
| App das crianças (Quest) | React + TS | Vercel (mesmo build) | `apps/web` (rotas /quest) + backend `app/quest/` |
| App mobile | Expo / React Native | — (build sob demanda) | `apps/mobile/` |
| Banco de dados | PostgreSQL gerenciado | **Supabase** | migrações em `backend/alembic/` |
| Robô de coleta | Playwright/Chromium (login) + httpx | dentro do backend (Railway) | `backend/app/sync/` |

**Fluxo de deploy hoje:** `git push` na `main` → Railway rebuilda o backend e
Vercel rebuilda o frontend automaticamente (git-integration). A pipeline com
gate de aprovação (`deploy.yml`) existe mas está dormante — ver [CI-CD.md](CI-CD.md).

## 2. Inventário de acessos e credenciais (o que depende do dono)

Cada linha é algo que **hoje só o dono controla** e que precisará ser
compartilhado com a equipe (idealmente via um **cofre de segredos** — 1Password,
Bitwarden, Infisical — nunca por mensagem/e-mail).

| # | Acesso / Serviço | Para quê | Onde está | Ação para a equipe |
|---|------------------|----------|-----------|--------------------|
| 1 | **GitHub** (repo `medeirex00/constela-edu`) | código, CI, secrets de Actions | github.com | Adicionar membros ao repo/org; definir *owners*; ativar branch protection (ver §5) |
| 2 | **Railway** (backend) | deploy da API, variáveis de ambiente, logs | railway.app | Convidar a equipe ao projeto; documentar as env vars (§3) |
| 3 | **Vercel** (frontend) | deploy do web, domínios | vercel.com | Convidar a equipe ao projeto |
| 4 | **Supabase** (Postgres) | banco de produção, RLS, backups do provedor | supabase.com | Convidar a equipe; guardar a connection string no cofre |
| 5 | **Registrador do domínio** `constelaedu.com` | DNS, e-mail | (registrador) | Transferir/compartilhar acesso; anotar onde está o DNS |
| 6 | **SECRET_KEY** de produção | assina sessões JWT | env do Railway | Cofre; rotacionar ao trocar de equipe (derruba sessões) |
| 7 | **Credenciais Matific/Elefante das escolas** | coleta automática | **cifradas no banco** (Fernet), a chave vem da SECRET_KEY | Não precisam ser "transferidas" (ficam no banco); mas a SECRET_KEY sim |
| 8 | **AI_API_KEY** (provedor de IA) | assistente | env do Railway (cifrada por escola no banco quando por escola) | Cofre |
| 9 | **BACKUP_PASSPHRASE** | decifra os backups | (a definir — ver DR-RUNBOOK) | Cofre, **guardada separada dos backups** |
| 10 | **Conta Sentry** (quando ativada) | erros | sentry.io | Convidar a equipe |
| 11 | **Monitor de uptime** (quando ativado) | alertas de queda | (provedor externo) | Convidar a equipe |
| 12 | **Contas Matific/Elefante do gestor** (para testes reais) | validar conectores | com o dono | Documentar credenciais de teste no cofre |

**Recomendação forte:** criar uma **conta de organização** (GitHub Org, Railway
Team, Vercel Team) em vez de contas pessoais, para que a saída de qualquer pessoa
não derrube o acesso. Migrar os projetos para essas orgs é o passo nº 1 quando a
equipe se formar.

## 3. Variáveis de ambiente (todas, com classificação)

Fonte da verdade: [`backend/app/core/config.py`](../backend/app/core/config.py).
Segredos (🔑) vão no cofre; configs (⚙️) podem ficar no repositório/dashboard.

| Variável | Tipo | Observação |
|----------|------|-----------|
| `SECRET_KEY` | 🔑 | Assina JWT **e** deriva a cifra Fernet (ver `DATA_ENCRYPTION_KEY`) |
| `DATA_ENCRYPTION_KEY` | 🔑 | (após deploy de A1/M3) cifra dedicada; opcional |
| `DATABASE_URL` | 🔑 | String do Supabase; usar o **pooler** (porta 6543) ao escalar |
| `AI_API_KEY` | 🔑 | Chave do provedor de IA (se `AI_PROVIDER` externo) |
| `BACKUP_PASSPHRASE` | 🔑 | Só nos secrets do backup/DR |
| `SENTRY_DSN` | 🔑 | Vazio = Sentry desligado |
| `METRICS_TOKEN` | 🔑 | Protege `/metrics` |
| `SYNC_PROXY_URL` | 🔑 | Se usar proxy para a coleta |
| `ENV` | ⚙️ | `producao` liga o fail-closed; `dev` libera |
| `PUBLIC_BASE_URL`, `QUEST_BASE_URL` | ⚙️ | URLs públicas (link/QR) |
| `CORS_ORIGINS` | ⚙️ | Origens permitidas |
| `SYNC_SCHEDULER_ENABLED` | ⚙️ | Liga o robô |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `EXPORTS_RETENCAO_DIAS`, `SYNC_*`, `LOG_*`, `METRICS_ENABLED`, `SENTRY_*` | ⚙️ | Ajustes; têm padrões seguros |

O template comentado está em [`backend/.env.example`](../backend/.env.example).

## 4. Onboarding de um novo desenvolvedor (30 minutos)

```bash
# 1. Clonar e entrar
git clone https://github.com/medeirex00/constela-edu && cd constela-edu

# 2. Backend (Python 3.13)
cd backend && python -m venv .venv && .venv/Scripts/activate  # (Windows) ou source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # ajustar SECRET_KEY etc.

# 3. Rodar a suíte (banco isolado — conftest roda Alembic no boot)
DATABASE_URL="sqlite:///./_dev.db" python -m pytest -q     # deve dar "N passed"

# 4. Frontend
cd ../ && npm install --legacy-peer-deps
npm run dev --workspace apps/web    # http://localhost:5173

# 5. Backend local
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

## 5. Proteções e processo (para não depender de "confiança")

- **Branch protection na `main`** (obrigatório com equipe): exigir PR + review +
  os checks de CI verdes. O ruleset está em `.github/rulesets/protecao-main.json`
  (importar no GitHub → Settings → Rules). Hoje exige 0 revisores — subir para 1.
- **Staging** antes de produção: ver [STAGING.md](STAGING.md).
- **Segredos no cofre**, nunca no código nem em mensagens.
- **2 pessoas no on-call** quando houver equipe (hoje é 1 — risco aceito na fase
  inicial, mitigado por este plano).

## 6. Índice de runbooks (o "cérebro" fora da cabeça de uma pessoa)

| Preciso... | Documento |
|-----------|-----------|
| Fazer deploy / entender a pipeline | [CI-CD.md](CI-CD.md), [DEPLOY.md](DEPLOY.md) |
| Restaurar o banco / DR | [DR-RUNBOOK.md](DR-RUNBOOK.md) |
| Entender a sincronização e escala | [SINCRONIZACAO.md](SINCRONIZACAO.md), [ESCALA-SINCRONIZACAO.md](ESCALA-SINCRONIZACAO.md) |
| Ligar monitoramento | [MONITORAMENTO-ATIVACAO.md](MONITORAMENTO-ATIVACAO.md) |
| Configurar staging | [STAGING.md](STAGING.md) |
| Arquitetura geral | [ARQUITETURA.md](ARQUITETURA.md), `docs/bible/` |

## 7. O que NÃO pode ser resolvido só com código (precisa de pessoas/decisão)

- Criar contas de **organização** e migrar Railway/Vercel/GitHub/Supabase para
  elas (decisão + acesso do dono).
- Contratar/definir a **2ª pessoa de on-call** e um SLA por escrito.
- Guardar segredos num **cofre** compartilhado.
- Transferir/compartilhar o **domínio** e o DNS.
