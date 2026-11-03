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
   - `DATA_ENCRYPTION_KEY` = 32+ caracteres aleatórios gerados **para o staging**,
     diferente da DEK de produção **e** da `SECRET_KEY` do staging. Obrigatória com
     `ENV=producao`: ausente, de exemplo ou igual à `SECRET_KEY`, o boot recusa e o
     deploy reprova. Regras e como gerar: §2.1 de
     [`docs/operacao/PRODUCAO-ENV-E-MIGRACOES.md`](operacao/PRODUCAO-ENV-E-MIGRACOES.md)
   - `SYNC_SCHEDULER_ENABLED=false` (staging não deve coletar dados reais)
   - `PUBLIC_BASE_URL`/`QUEST_BASE_URL` = os domínios de staging
   - `CORS_ORIGINS` = array JSON só com a origem **exata** do front de staging
     (§2c), a mesma de `PUBLIC_BASE_URL`: esquema + domínio (+ porta, se houver),
     sem barra no fim e sem caminho — ex.: `["https://staging.SEU-DOMINIO"]`. Se o
     Quest de staging for usado, acrescente a origem de `QUEST_BASE_URL` no mesmo
     array. **Obrigatória no staging** (em produção é opcional): com
     `ENV=producao` e sem ela vale o padrão do código, que só aceita os domínios
     de **produção** (`www`, `quest`) e o app desktop. O healthcheck passa, mas o
     navegador barra toda chamada do front de staging, inclusive o login (o site
     "abre mas não funciona"). O valor **substitui** o padrão (não soma). Nunca
     `*`: o boot recusa.
   - Não configure credenciais reais de Matific/Elefante em staging.

### 2c. Frontend de staging (Vercel)  ⏳ você
1. A Vercel já cria **Preview Deployments** para cada branch/PR automaticamente —
   servem para revisar telas e textos, mas **não falam com o backend de
   staging** (item 3).
2. Para um staging fixo: em *Settings → Git*, associe a branch `staging` a um
   *Environment* "Preview" com `VITE_API_URL` apontando para o **backend de
   staging** (2b). O domínio desse staging fixo é a origem que vai, igual letra
   por letra, no `CORS_ORIGINS` do backend de staging (2b); se o domínio mudar,
   atualize o `CORS_ORIGINS` e reimplante o backend.
3. **Previews por PR não falam com o backend de staging.** Cada Preview tem um
   endereço próprio (`*.vercel.app`) que muda a cada deploy e não está no
   `CORS_ORIGINS` do staging; o curinga `*`, que os liberaria, o boot recusa com
   `ENV=producao`. O navegador barra as chamadas à API (login inclusive). Para
   validar com dados (login, importação, relatórios), faça o merge em `staging` e
   use o domínio fixo do item 2. Não acrescente endereços de Preview ao
   `CORS_ORIGINS` como rotina: mudam a cada deploy e cada troca exige reimplantar
   o backend.

## 3. Garantia de que staging não toca produção

- Banco **fisicamente separado** (2a) — a `DATABASE_URL` de staging nunca aponta
  para o banco de produção.
- `SYNC_SCHEDULER_ENABLED=false` em staging — o robô não coleta nada real.
- `SECRET_KEY` diferente — sessões/segredos não são intercambiáveis.
- `DATA_ENCRYPTION_KEY` própria — uma credencial cifrada em produção não se abre
  no staging (e vice-versa).
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
| Frontend de staging (Preview) | ⏳ associar a branch `staging` na Vercel (§2c; o Preview por PR existe, mas não fala com o backend de staging) |
| `CORS_ORIGINS` do staging = array JSON com a origem exata do front de staging, sem `*` | ⏳ setar (§2b) — sem ela o site abre mas toda chamada é barrada |
| Chaves próprias do staging (`SECRET_KEY` e `DATA_ENCRYPTION_KEY`) | ⏳ gerar (§2b) |
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
