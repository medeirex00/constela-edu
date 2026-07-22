# Staging / Homologação — Constela Edu

Objetivo: acabar com "mudança indo direto de desenvolvimento para produção".
Meta: **Desenvolvimento → Staging → Produção**, com staging **incapaz** de tocar
dados reais.

> O que já está pronto no repositório vs. o que **só você** pode configurar (por
> depender das suas contas Railway/Vercel/Supabase) está marcado em cada passo.

---

## 1. Modelo de branches e promoção

```
feature/*  →  PR  →  (CI verde)  →  merge em `staging`  →  deploy staging (auto)
                                          ↓ validação manual em staging
                                     PR staging → main  →  deploy produção (auto)
```

- **`main`** = produção (Railway + Vercel já ligados por git-integration).
- **`staging`** = homologação (a criar; passos abaixo).
- Nada vai para produção sem passar por `staging` e pela revisão do PR.

✅ **Pronto:** o CI (`.github/workflows/ci.yml`) já roda **em todo Pull Request**
(lint, testes com cobertura, build, E2E). Então "testes automáticos antes do
merge" já existe — falta só ativar a **proteção da branch** (§4).

## 2. Criar o ambiente de staging (depende de você — passos exatos)

### 2a. Banco separado (Supabase)  ⏳ você
1. No Supabase, crie um **novo projeto** `constela-staging` (ou um novo banco no
   mesmo projeto). Nunca compartilhe o banco com produção.
2. Copie a connection string (use o **pooler**, porta 6543).
3. Rode as migrações apontando para ele:
   `DATABASE_URL="postgresql+psycopg://.../staging" alembic upgrade head`
4. (Opcional) Popular com dados FICTÍCIOS: `python backend/scripts/seed.py`
   (nunca copie dados reais de crianças para staging).

### 2b. Backend de staging (Railway)  ⏳ você
1. No Railway, crie um **novo serviço** a partir do mesmo repo, apontando para a
   branch **`staging`**.
2. Variáveis de ambiente **próprias** (separadas da produção):
   - `ENV=producao` (mantém o fail-closed/hardening; é "produção-like")
   - `DATABASE_URL` = o banco de **staging** (2a)
   - `SECRET_KEY` = uma chave **diferente** da produção (gere nova)
   - `SYNC_SCHEDULER_ENABLED=false` (staging não deve coletar dados reais)
   - `PUBLIC_BASE_URL`/`QUEST_BASE_URL` = os domínios de staging
   - Não configure credenciais reais de Matific/Elefante em staging.

### 2c. Frontend de staging (Vercel)  ⏳ você
1. A Vercel já cria **Preview Deployments** para cada branch/PR automaticamente —
   isso já é um staging do frontend "de graça".
2. Para um staging fixo: em *Settings → Git*, associe a branch `staging` a um
   *Environment* "Preview" com `VITE_API_URL` apontando para o **backend de
   staging** (2b).

## 3. Garantia de que staging não toca produção

- Banco **fisicamente separado** (2a) — a `DATABASE_URL` de staging nunca aponta
  para o banco de produção.
- `SYNC_SCHEDULER_ENABLED=false` em staging — o robô não coleta nada real.
- `SECRET_KEY` diferente — sessões/segredos não são intercambiáveis.
- O harness de carga (`carga_sync.py`) e o DR drill (`dr_drill.sh`) **se recusam**
  a rodar contra um banco com dados reais / a origem = destino.

## 4. Proteção da `main`  ⏳ você (1 clique)

✅ **Pronto no repo:** `.github/rulesets/protecao-main.json` — exige PR +
required status checks (os 10 jobs de CI/segurança) antes de qualquer merge.

**Você precisa:** GitHub → *Settings → Rules → Import ruleset* e selecionar esse
arquivo (ou ativar manualmente as regras). Enquanto for **1 desenvolvedor**,
mantenha `required_approving_review_count = 0` (não dá para aprovar o próprio PR);
**suba para 1 assim que a 2ª pessoa entrar** (editar o JSON e reimportar).

## 5. Checklist de prontidão do staging

| Item | Estado |
|------|--------|
| CI roda testes em todo PR | ✅ pronto (`ci.yml`) |
| Ruleset de proteção da main | ✅ no repo; ⏳ **importar** no GitHub |
| Banco de staging separado | ⏳ criar no Supabase |
| Backend de staging (branch `staging`) | ⏳ criar no Railway |
| Frontend de staging (Preview) | ⏳ associar na Vercel (Preview já existe por PR) |
| Scheduler desligado em staging | ⏳ setar `SYNC_SCHEDULER_ENABLED=false` |
| Nenhuma credencial real em staging | ⏳ garantir |

## 6. Fluxo do dia a dia depois de pronto

```bash
git checkout -b feature/minha-mudanca
# ... código + testes ...
git push -u origin feature/minha-mudanca         # abre PR → CI roda
# merge do PR em `staging` → Railway/Vercel publicam staging automaticamente
# validar em staging (dados fictícios)
# PR staging → main → produção
```
