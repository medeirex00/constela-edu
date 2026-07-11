# 14 — Infra, Deploy, Backup & DR (SRE/DevOps) / Infrastructure, Deploy, Backup & DR (SRE/DevOps)

- **Status:** 🟢 aprovado / approved
- **Padrão / Standard:** [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) (16 partes)
- **Fontes / Sources:** `INDICE.md` (bloco 14, subseções 14.1–14.45 + espelho de decisões em aberto), `_estado-atual/RELATORIO-2026-07-09.md` (as-is: Vercel+Railway, 1 instância, salas/rate-limit em memória, Redis planejado), `docs/quest/01-arquitetura.md` (escala A›B›C, gatilho de Redis, CDN Cloudflare R2), `backend/Dockerfile` + `backend/entrypoint.sh` (não-root, `$PORT`, `alembic upgrade` no boot via `scripts.migrate`), `backend/app/core/migracoes.py` + `backend/alembic/` (base `0001`, stamp-then-upgrade, revisões 0001–0005 (com 0002a de reparo)), `backend/app/core/config.py` (ENV `dev|producao` fail-closed, flag `DOCS_HABILITADOS`, pool de DB, `PUBLIC_BASE_URL`/`QUEST_BASE_URL`, envs de observabilidade), `backend/app/main.py` (`/api/health/live|ready`, `/api/health`, `/metrics`, docs gated por `DOCS_HABILITADOS`), `backend/app/core/observabilidade.py` (logs JSON, Prometheus, Sentry), `backend/app/core/security.py` (Fernet só na chave de API), `backend/app/core/rate_limit.py` (em memória), `docker-compose.yml` + `Caddyfile` + `vercel.json` + `apps/web/nginx.conf` (topologias de deploy), `.env.example` + `backend/.env.example` (catálogo de segredos), `.github/workflows/ci.yml` (CI) + `deploy.yml` (CD gated por DEPLOY_ENABLED, com aprovação manual), Seções [11](11-arquitetura.md)/[12](12-seguranca-privacidade.md), memória de produção (`producao-urls`, `constela-alembic-migrations`)
- **Depende de / Depends on:** princípios (P13 servidor é autoridade · P14 ledger auditável · P15 isolamento por escola · P17 piso de desempenho · P18 sem tracking de terceiros) → [01](01-principios-imutaveis.md); **mecanismo** (token dois-mundos, WebSocket+Redis, outbox, ledger, autoridade do gabarito, rotas, caminho de escala A›B›C, desenho do Alembic, **revogação via `token_version`**) → [11](11-arquitetura.md); **política** (retenção legal, base legal, incidentes, **cadência** de rotação, **exigência** de cifrar/reter backup) **+ delegação da operação** de backup/DR/cripto-em-repouso/segredos → [12](12-seguranca-privacidade.md); **taxonomia** de telemetria e a **definição/lógica** do expurgo (a 14 fornece o **agendador** que o executa) → [17](17-telemetria-metricas.md); **valores** de config `quest.*` → [19](19-liveops.md); **pipeline/autoria** de assets (para storage+CDN) → [15](15-arte-audio-assets.md); **formatação** pt-BR de data/tempo → [16](16-localizacao-i18n.md); **ETL** de dados de escola → [20](20-migracao-importacao.md); **comunicação** de manutenção à escola → [21](21-suporte-operacao.md); **estratégia** de teste de carga → [18](18-qa-testes.md).

> **Convenção / Convention:** "§N" = uma das 16 **partes deste capítulo** / one of the 16 **parts of this
> chapter**; "Seção NN" / "Section NN" = outro capítulo da Bible / another Bible chapter; "14.NN" = uma
> subseção do plano do `INDICE.md` / a subsection of the `INDICE.md` plan.
> **Escopo / Scope:** este capítulo decide a **operação (SRE/DevOps)** do Constela Quest — hospedagem, ambientes,
> CI/CD e deploy, execução da migração de schema no deploy, backup, Disaster Recovery, observabilidade de infra,
> cripto em repouso, cofre de segredos e escala operacional. Ele **opera, implanta e escala** o **mecanismo** da
> Seção [11](11-arquitetura.md) e **executa** o que a **política** da Seção [12](12-seguranca-privacidade.md)
> **exige** (backup/DR/cripto-em-repouso/segredos foram **explicitamente delegados** pela 12 à 14). Ele **não**
> decide o **mecanismo** (Seção 11), a **política** legal (Seção 12), a **taxonomia** de telemetria (Seção 17)
> nem os **valores** de config (Seção 19) — apenas os **opera** e **referencia**.

---

## 🇧🇷 Infra, Deploy, Backup & DR (SRE/DevOps)

### 1. Objetivo
Ser a **referência definitiva de operação** do Constela Quest: **como** o produto é **implantado, operado,
monitorado, escalado, salvo (backup) e recuperado (DR)** — para que o serviço de **milhares de escolas** fique
de pé no pico da aula, o **dado de uma criança nunca se perca**, e uma **release ruim** se reverta em minutos.
Permite operar **sem improvisar** no incidente. Decide a **operação (SRE/DevOps)**; **opera** o **mecanismo**
(Seção [11](11-arquitetura.md)) e **executa** a **política** (Seção [12](12-seguranca-privacidade.md)); **não**
decide o mecanismo, a política legal, a **taxonomia** de telemetria (Seção [17](17-telemetria-metricas.md)) nem
os **valores** de config (Seção [19](19-liveops.md)).

### 2. Contexto
No ecossistema **Hub → Edu → Quest**, o Quest **reusa a identidade do Edu** e roda como **monólito modular**
(backend FastAPI único). **Estado atual (Q0) — fundação de infra já madura:**
- **Build** — `backend/Dockerfile` (python 3.13-slim, usuário **não-root**, respeita `$PORT`, volumes `/dados`,
  `ENTRYPOINT entrypoint.sh`) e `apps/web/Dockerfile` (Node 22 → nginx).
- **Deploy (duas realidades de deploy — modelos — coexistem no repo)** — (a) **Railway** (backend, via
  `Dockerfile`) + **Vercel** (web, `vercel.json`, `constelaedu.com`/`www`) + **Postgres gerenciado** → a
  **produção real do Quest** (memória `producao-urls`); (b) **self-host** `docker-compose.yml` + `Caddyfile`
  (postgres17 + backend + web nginx; serviços `backup`/`https` **gated por profile**, backup = `pg_dump`
  retenção 14 d) → o caminho **VPS do Edu**. A 14 precisa **fixar o modelo oficial** e desambiguar (§15/ADR-14-A).
- **Migração no boot** — `entrypoint.sh` roda `python -m scripts.migrate` **uma vez** (antes dos workers, sem
  corrida de DDL) → `app/core/migracoes.py` (`alembic upgrade head`; stamp base `0001` p/ bancos pré-Alembic) →
  `alembic/versions/{0001,0002,0002a,0003,0004,0005}`. O **desenho** do Alembic é da Seção [11](11-arquitetura.md); a 14 **opera**.
- **Config/segredos** — `config.py` (pydantic-settings; `ENV` **fail-closed** em produção: `_validar_producao`
  exige `SECRET_KEY≥32` e `DATABASE_URL` não-sqlite). O `/docs`, `/redoc` e `/openapi.json` ficam **desligados
  por padrão** pela flag `DOCS_HABILITADOS=False` (aplicada em `main.py`, **independente do `ENV`**; ligados só
  explicitamente em dev). Segredos **só em env** (`.env` no `.gitignore`; `.env.example` documenta), **nenhum no
  código**.
- **Cripto em repouso** — `security.py` usa **Fernet** (derivado da `SECRET_KEY`) **apenas** para a chave de API
  externa do assistente; senhas = bcrypt; token de reset = SHA-256 uso único. **Não** há cifragem de coluna nem
  do volume do Postgres pela app.
- **Observabilidade** — `main.py` expõe `/api/health/live`, `/api/health/ready` (SELECT 1 → 503), `/api/health`,
  `/metrics` (Prometheus, gated); `observabilidade.py` (logs JSON com `request_id`/`escola_id`/rota via
  contextvars; prometheus-client; Sentry gated; tudo **degradável a no-op**). `rate_limit.py` = **em memória por
  processo** (não distribuído).
- **CI** — `.github/workflows/ci.yml` (pytest + typecheck/build + validação de `docker build`). O **CD** vive em
  `deploy.yml` (staging/produção, gated por `DEPLOY_ENABLED`, **dormante** até ativação). `desktop-release.yml`
  (instaladores Tauri em tags `v*`).

**Não existe ainda:** IaC versionada do host de produção; **CD/staging ATIVADOS** (o `deploy.yml` já existe, mas
está gated por `DEPLOY_ENABLED` e dormante); **backup
automatizado da prod Railway** (o serviço do compose é gated e mira o Postgres local); **runbook de DR**, RTO/RPO,
failover, teste de restauração; **Redis** provisionado (alvo do estágio B da Seção 11); **CDN** próprio;
**cofre/rotação** de segredos; **agendador** dos jobs de retenção/expurgo. Este capítulo especifica a operação-alvo.

### 3. Filosofia da funcionalidade
**Boa operação é invisível quando funciona e óbvia quando falha.** Os princípios de SRE guiam esta seção:
**automatize o repetível**, **torne o estado reproduzível** (IaC — recriar um ambiente do zero sem adivinhação),
**um backup só conta se já foi restaurado** (game day), e o **erro de operação nunca chega à criança como
punição** — sob incidente, o produto **degrada com dignidade** (shell offline + fila local — mecanismo da
Seção [11](11-arquitetura.md)), coerente com P6 e a Seção [13](13-acessibilidade.md).

Conexão com os **Princípios Imutáveis** ([01](01-principios-imutaveis.md)): **P13** (o servidor é a autoridade
do gabarito) exige que ele **esteja de pé** e íntegro; **P14** (ledger auditável) exige um backup com
**integridade verificável** (*tamper-evident* — à prova de alteração silenciosa/ransomware **durante a janela de
retenção**), **não** retenção perpétua: o backup **honra a retenção e o direito de exclusão** da
Seção [12](12-seguranca-privacidade.md); **P15** (isolamento por `escola_id`) se estende ao **backup/restore por
escola**; **P17** (piso de desempenho) vira **capacidade** operacional; **P18** (sem SDK de rastreamento de
terceiros no cliente) exige **não vender telemetria de criança** — e, como agregadores/Sentry são
**processadores** externos, a **minimização** da Seção [12](12-seguranca-privacidade.md) (mascarar código/IP de
criança) é aplicada **antes** de qualquer egresso, sob a base legal dela. A **confiança da escola** é, no fim,
**uptime + dado seguro + recuperável**.

### 4. Experiência que o jogador deve sentir
**A criança e o adulto nunca veem a infra** — sentem apenas que o jogo **"está sempre lá e é rápido"**, mesmo às
7h30 quando a rede toda entra ao mesmo tempo. Sob incidente, em vez de tela branca, a criança encontra
**degradação graciosa** (o app abre offline, guarda o que fez e sincroniza depois — mecanismo da
Seção [11](11-arquitetura.md)); a manutenção aparece com **gentileza** (Seção [13](13-acessibilidade.md)).

**O adulto** (escola/família) sente **confiança**: o dado do aluno está **salvo, cifrado e restaurável**, e a
LGPD é respeitada. **A equipe** (hoje **um desenvolvedor**) sente que **o runbook a guia** — um incidente às 3h
da manhã tem um passo-a-passo, não um pânico.

### 5. Fluxo completo
O **ciclo de vida operacional**, do commit ao incidente:

1. **Build** — imagem Docker do backend e do web (reprodutível, não-root).
2. **CI** — `ci.yml`: testes + typecheck + build das imagens (portão de qualidade antes do merge).
3. **Deploy** — backend na **Railway** (via `Dockerfile`+`$PORT`), web na **Vercel** (via `vercel.json`).
4. **Migração no boot** — `entrypoint.sh` roda `alembic upgrade` **uma única vez** antes dos workers (evita
   corrida de DDL); política **expand/contract** para mudanças sem downtime no pico (§9).
5. **Health gate** — o roteador só manda tráfego após `/api/health/ready` responder OK (readiness com SELECT 1).
6. **Smoke pós-deploy** — verificação automática dos caminhos críticos (login do aluno; e um caminho de
   **submissão read-only/validação** ou em **perfil/escola sintética descartável** — **nunca** escrevendo no
   ledger de produção, P14).
7. **Rollback** — se o smoke/erro falhar, **reverte a release** (código); com expand/contract o padrão é
   **fix-forward** (a fase aditiva é segura de reverter). **Downgrade de DDL não roda no boot** — se necessário,
   é procedimento **manual de runbook** (§9/§12).
8. **Operação contínua** — observabilidade (logs JSON, `/metrics`, Sentry), **alertas** de recurso e **on-call**.
9. **Backup contínuo** — snapshot + retenção de WAL / PITR do Postgres de produção (cifrado, off-site).
10. **Teste de restauração** — **game day** periódico que prova o RTO/RPO ("backup não testado não conta").
11. **DR** — em desastre (perda do banco, região fora, corrupção), segue o **runbook** técnico passo-a-passo.
12. **Escala** — quando o gatilho dispara (estágio B da Seção [11](11-arquitetura.md)), **provisiona o Redis**
    (rate-limit e salas WS distribuídos) e réplicas stateless do backend.

Ambientes: **dev** (SQLite/local) → **staging** (paridade com prod, dado sintético — ⚠️ §15) → **prod**.

### 6. Interface (quando existir)
**N/A para UI de criança** — este capítulo não tem tela no jogo. Superfícies **operacionais**:
- **Página de status pública** (14.35) — comunica incidente/manutenção; **existência** é da 14, o **texto/canal**
  de aviso à escola é da Seção [21](21-suporte-operacao.md).
- **Dashboards de observabilidade** (internos) — RED/USE, uptime, recurso; consomem `/metrics` e os logs JSON.
- **Endpoints de saúde** (`/api/health/*`) e **`/metrics`** — já existem (Q0); a 14 define a **operação** (scrape
  seguro, restringir `/metrics` na rede).

### 7. UX
A "UX de operação" tem dois públicos:
- **Para a equipe** — **runbooks** claros e testados; **alertas acionáveis** (sinal, não ruído); **logs
  estruturados** pesquisáveis por `request_id`/`escola_id`/rota; **painel de status** legível. O objetivo é que
  quem estiver de plantão **resolva sem adivinhar**.
- **Para o usuário final** — sob incidente/manutenção, **degradação graciosa** e **mensagens gentis** (a
  superfície e o tom são da Seção [13](13-acessibilidade.md)); nunca uma tela de erro crua para a criança.

### 8. Game Design
**N/A** — capítulo de infraestrutura, sem dimensão de jogo. Nota de fronteira: a operação **sustenta** as regras
de jogo. Ex.: o **corte de dia/semana** (para teto/Chama/diárias) é definição da Seção [05](05-sistemas-de-jogo.md);
a 14 só garante o **UTC no banco** e o cálculo consistente do `data_ref` (a data-referência operacional derivada
do UTC — §9/O17). A **capacidade** no pico usa a métrica da Seção [17](17-telemetria-metricas.md)/[18](18-qa-testes.md);
o **dimensionamento** é da 14.

### 9. Regras de negócio
As **normas determinísticas de operação** (a fonte única; o **mecanismo** é da Seção [11](11-arquitetura.md), a
**política** da Seção [12](12-seguranca-privacidade.md)):

| # | Norma de operação | Regra | Fronteira |
|---|-------------------|-------|-----------|
| O1 | **Ambientes** | **dev / staging / prod** isolados (dado/segredo por ambiente); produção **fail-closed** (`config.py`) | 14 ⚠️ (staging — §15) |
| O2 | **Infra como código** | topologia reproduzível e versionada (recriar do zero sem painel) | 14 ⚠️ (ferramenta — §15) |
| O3 | **Migração de schema** | `alembic upgrade` **uma vez** no boot (`entrypoint.sh`), **antes** dos workers; **expand/contract** para zero-downtime; **fase destrutiva só na janela de manutenção** (14.34/§15) | 14 opera; desenho = [11](11-arquitetura.md) |
| O4 | **Health gate** | tráfego só após `/api/health/ready` OK; **smoke** dos caminhos críticos pós-deploy (sem escrever no ledger de prod) | 14 |
| O5 | **Rollback** | reverter **código**; com expand/contract o padrão é **fix-forward**; **downgrade de DDL não roda no boot** (manual, via runbook) | 14 |
| O6 | **Backup** | snapshot + WAL/PITR do Postgres de **produção**; **cifrado** e **off-site**; integridade verificável (*tamper-evident*) | 14 ⚠️ (cadência/local — §15); exigência = [12](12-seguranca-privacidade.md) |
| O7 | **Restore testado** | **game day** periódico prova RTO/RPO — *"backup não testado não conta"* | 14 |
| O8 | **RPO/RTO** | alvo por **classe de dado** (ledger append-only × telemetria durável-mas-expurgável × estado cosmético) | 14 ⚠️ (números — §15) |
| O9 | **Isolamento no backup** | restaurar/exportar **por `escola_id`** — direto onde a coluna existe; via `perfil_id`→`quest_perfis` na **tenancy transitiva** (Seção [11](11-arquitetura.md)); catálogo global de referência fica fora do escopo por-escola (P15) | 14 + [01](01-principios-imutaveis.md)/[11](11-arquitetura.md) |
| O10 | **Cripto em repouso** | volume do Postgres + backups cifrados; Fernet-at-rest da chave de API (Q0) | 14 (operação delegada por [12](12-seguranca-privacidade.md)) |
| O11 | **Segredos** | **nunca no código** (`.env`/cofre); **procedimento** operacional de rotação de `SECRET_KEY`/JWT/Fernet/senha do DB (janela/passos). A rotação da chave de assinatura **invalida os tokens**; `token_version` é o mecanismo de **revogação** da Seção [11](11-arquitetura.md) | 14 (operação); mecanismo = [11](11-arquitetura.md); política/cadência = [12](12-seguranca-privacidade.md) |
| O12 | **Observabilidade** | logs JSON + `/metrics` + Sentry (Q0); **alertas** de recurso (CPU/RAM/disco/pool/uptime) | 14 ⚠️ (stack/SLO — §15) |
| O13 | **SLI/SLO** | metas de disponibilidade/latência + error budget (login do aluno, submissão) | 14 ⚠️ (números — §15) |
| O14 | **Segurança de infra** | **TLS obrigatório**, hardening, `dependabot`, varredura de segredos | 14 (complementa [12](12-seguranca-privacidade.md)) |
| O15 | **Escala** | dimensionar workers/pool; **provisionar Redis** no gatilho do estágio B; réplicas stateless | 14 opera; caminho A›B›C = [11](11-arquitetura.md) |
| O16 | **Agendamento** | cron/worker que **executa** os jobs de retenção/expurgo/anonimização | 14 (mecanismo); prazo = [12](12-seguranca-privacidade.md); taxonomia/lógica = [17](17-telemetria-metricas.md) |
| O17 | **Tempo na operação** | **UTC no banco**; `data_ref` operacional (derivado do UTC); corte de dia/semana = [05](05-sistemas-de-jogo.md); formatação pt-BR = [16](16-localizacao-i18n.md) | 14 |
| O18 | **Dado fora de produção** | staging/testes usam dado **sintético/anonimizado** — **proibido** copiar dado real de criança | 14 (corolário de P15/P18 + minimização = [12](12-seguranca-privacidade.md)) |
| O19 | **Exclusão → backup** | a exclusão/anonimização decidida pela Seção [12](12-seguranca-privacidade.md) **propaga-se aos backups** dentro da janela de retenção (retenção limitada + **crypto-shredding** da chave quando aplicável); backup **não é** retenção perpétua | 14 opera; decisão de erasure (cascade × anonimização) = [12](12-seguranca-privacidade.md) §15 ⚠️ |

**Config × valores:** a 14 é dona do **mecanismo de entrega** de config/env/segredos e das **feature flags**; os
**valores** `quest.*` (limites, janelas, economia) são da Seção [19](19-liveops.md) — a 14 **entrega**, não fixa.
**Logs, três donos:** o **log de observabilidade** (efêmero, request-scoped, retenção curta) é operado pela 14
(O12); o **log de auditoria / ledger** (imutável, retenção legal) é da Seção [12](12-seguranca-privacidade.md)
(a 14 só o **respalda** no backup — O6/O19 —, sem redefinir sua retenção); a **telemetria de produto** é da
Seção [17](17-telemetria-metricas.md).

### 10. Arquitetura técnica
A topologia real e o mapeamento ao código (contratos → Apêndice B):
- **Produção (modelo canônico proposto — ⚠️ §15/ADR-14-A):** **backend na Railway** (imagem `backend/Dockerfile`,
  `$PORT`, `entrypoint.sh` com migração única) + **web na Vercel** (`vercel.json`, `www.constelaedu.com`) +
  **Postgres gerenciado**. O **self-host** `docker-compose.yml`+`Caddyfile` (backup `pg_dump` 14 d, HTTPS Caddy)
  é a **alternativa de soberania/Edu**, **não** a prod do Quest — a 14 documenta ambos e marca o oficial.
- **Config fail-closed** — `config.py` recusa subir em produção sem `SECRET_KEY≥32`/`DATABASE_URL` não-sqlite; o
  `/docs` fica off por `DOCS_HABILITADOS` (independente do ENV). A convenção é **default=produção no código, dev
  sobrescreve no `.env`** (lição do `PUBLIC_BASE_URL`).
- **Migração** — `migracoes.py`/`alembic` (stamp-then-upgrade); a 14 opera o **quando/como** no deploy.
- **Observabilidade** — `observabilidade.py` (logs JSON, Prometheus, Sentry) + `main.py` (health/`/metrics`); a
  14 define a **operação** (agregador, alertas, scrape seguro).
- **Cripto/segredos** — `security.py` (Fernet at-rest hoje só p/ a chave de IA); a 14 estende p/ **volume/backup
  cifrados** e **cofre** (operação delegada pela Seção [12](12-seguranca-privacidade.md)).
- **Escala A›B›C** (mecanismo = Seção [11](11-arquitetura.md)): **A** = 1 instância Railway + rate-limit/salas em
  memória (hoje); **B** = **Redis** (rate-limit e estado ao vivo distribuídos; réplicas stateless); **C** =
  extração de serviços. A 14 define o **gatilho** e a **operação**, não o desenho.
- **CDN** — **Cloudflare R2** (ou equivalente — ⚠️ §15) para GLB/áudio; o **pipeline/autoria** dos assets é da
  Seção [15](15-arte-audio-assets.md); a **regra** "asset público sem token, nunca gabarito" é da
  Seção [12](12-seguranca-privacidade.md); a 14 só **opera** a entrega.

### 11. Dependências com outros módulos
**Consome / opera / executa:**
- **Seção [11](11-arquitetura.md)** — o **mecanismo** (token, WebSocket+Redis, outbox, ledger, autoridade do
  gabarito, rotas, caminho A›B›C, desenho do Alembic, `token_version` = revogação). A 14 **opera/implanta/escala**,
  não redesenha.
- **Seção [12](12-seguranca-privacidade.md)** — a **política** (retenção legal, incidentes, base legal, **cadência**
  de rotação) e a **exigência** de cifrar/reter backup. A 12 **delega à 14** a **operação** de
  backup/DR/cripto-em-repouso/segredos — a 14 **executa**.
- **Seção [17](17-telemetria-metricas.md)** — fronteira: a 17 é dona da **taxonomia** e da **lógica** do expurgo;
  a 14 cuida de **observabilidade de infra** (health/uptime/RED/USE) e **fornece o agendador** que dispara o expurgo.
- **Seção [19](19-liveops.md)** — os **valores** `quest.*`; a 14 entrega o **mecanismo** de config/flags.
- **Seção [15](15-arte-audio-assets.md)** — o **acervo** de assets; a 14 opera o **storage+CDN**.
- **Seção [16](16-localizacao-i18n.md)** — a **formatação** pt-BR de data (a 14 guarda **UTC** no banco).

**Fronteira dos "logs" (três donos):** **observabilidade** (efêmera, operacional) = 14 (O12); **auditoria/ledger**
(imutável, retenção legal) = Seção [12](12-seguranca-privacidade.md) (a 14 só respalda no backup, O6/O19);
**telemetria de produto** = Seção [17](17-telemetria-metricas.md).

**Ponte (bridge), não redefinição:**
- **Seção [21](21-suporte-operacao.md)** — a 14 **agenda** a janela de manutenção; a **comunicação** à escola é da 21.
- **Seção [20](20-migracao-importacao.md)** — a 14 executa a **migração de schema** no deploy; o **ETL** de dados
  de escola é da 20.
- **Seção [18](18-qa-testes.md)** — o **teste de carga** do cenário de pico é **compartilhado** (14 = capacidade
  operacional, 18 = estratégia de teste).

**O que quebra se mudar:** se a 11 mudar o **caminho de escala** ou o desenho do Alembic, a 14 **reajusta a
operação**; se a 12 mudar a **exigência de cripto/retenção** ou a decisão de erasure, a 14 **reexecuta** — a 14
nunca fixa o número legal.

### 12. Casos extremos (Edge Cases)
- **Perda do banco de produção** → restauração via **PITR**/snapshot mais recente (RPO — ⚠️ §15); runbook 14.24.
- **Região/host fora do ar** → **DR**: failover/recriação a partir da IaC + backup off-site (⚠️ §15).
- **Corrupção/erro de dados de uma escola** → restaurar/exportar **por `escola_id`** (direto onde a coluna existe;
  via `perfil_id`→`quest_perfis` na tenancy transitiva — Seção [11](11-arquitetura.md)) sem tocar as demais (P15).
- **Exclusão do titular (LGPD)** → a exclusão/anonimização (decisão da Seção [12](12-seguranca-privacidade.md) §15
  — hoje `ON DELETE CASCADE`) **propaga-se aos backups**: retenção limitada + **crypto-shredding** da chave quando
  aplicável; o dado da criança **não** fica eterno no snapshot (O19).
- **Deploy falho** → **rollback** de release (fix-forward por padrão); a fase destrutiva nunca vai junto da
  release que a introduz.
- **Migração no pico de aula** → **expand/contract** em duas fases; a fase destrutiva só na **janela de
  manutenção** (⚠️ §15/14.34).
- **Pico 7h30 (rede toda ao mesmo tempo)** → capacidade dimensionada + gatilho de Redis/réplicas (⚠️ §15).
- **Queda de dependência** (DB/Redis) → **degradação graciosa**: shell offline + fila local (mecanismo da
  Seção [11](11-arquitetura.md)); a criança não vê tela branca.
- **Segredo vazado** → **rotação** (procedimento = 14; política/cadência = Seção [12](12-seguranca-privacidade.md));
  o `token_version` **revoga** as sessões comprometidas (mecanismo da Seção [11](11-arquitetura.md)).
- **Backup nunca restaurado** → **game day** obrigatório; um backup não testado é tratado como **inexistente**.
- **Service worker com cache preso** (lição do favicon) → **cache-busting** do SW (Workbox) no deploy do PWA.
- **Divergência SQLite (dev) × Postgres (prod)** → política de **paridade** dev↔prod (tipos JSON, índices,
  transações); staging com Postgres reduz o risco.
- **Um único dev no on-call** → **severidades** + automação + alertas acionáveis reduzem o que exige humano de
  madrugada (⚠️ §15 — plantão/SLA).

### 13. Escalabilidade futura
- **Caminho A›B›C** (Seção [11](11-arquitetura.md)) — **Redis** no gatilho (estágio B: rate-limit e salas WS
  distribuídos, réplicas stateless); **extração** de serviços (C) quando a carga justificar.
- **Multi-região** para DR (failover geográfico) quando o RTO exigir.
- **IaC completa** — recriar qualquer ambiente do zero; **staging** permanente.
- **CDN + storage** dedicados (Cloudflare R2 ou equivalente) para o acervo crescente de GLB/áudio.
- **Cofre de segredos** e **rotação automatizada**; **FinOps** com teto e alerta de custo por serviço.
- **Auditoria/segurança contínua** — `dependabot`, varredura de segredos, e o gate de contraste/perf no CI
  (Seção [18](18-qa-testes.md)).

### 14. Checklist de implementação
**A — Verificável agora (gate de go-live / DoD operacional; liga ao Apêndice F):**
- [ ] **Produção fail-closed** (`config.py`: `SECRET_KEY≥32`, `DATABASE_URL` não-sqlite).
- [ ] **`DOCS_HABILITADOS=false`** em produção (`/docs`, `/redoc`, `/openapi.json` fora do ar).
- [ ] **Migração** aplicada **uma vez** no boot, testada, com plano de fix-forward / rollback de código.
- [ ] **Health gate** ativo (tráfego só após `/api/health/ready`) + **smoke** pós-deploy (sem escrever no ledger de prod).
- [ ] **Cripto em repouso** (volume + backups) e **segredos** fora do código (cofre/env).
- [ ] **TLS obrigatório** + hardening + `dependabot` + varredura de segredos.
- [ ] **Isolamento por `escola_id`** verificado no backup/restore, honrando a tenancy transitiva (P15).
- [ ] **Dado fora de produção** é sintético/anonimizado (nunca dado real de criança).
- [ ] **Provisionamento por escola nova** cumprido (criar `escola_id`, verificar isolamento P15, seed mínimo).
- [ ] **UTC no banco** e `data_ref` operacional consistentes (O17).

**B — Bloqueado por decisão do dono (§15) — não pode ir a go-live sem ratificar:**
- [ ] **Topologia oficial ratificada** (ADR-14-A) — pré-condição de go-live.
- [ ] **Backup automatizado** da prod (snapshot + WAL/PITR), **cifrado** e **off-site** — requer cadência/local (O6/§15).
- [ ] **Restore testado** (game day) provando o **RTO/RPO** alvo — requer O8/§15 ratificada.
- [ ] **Rotação** de segredos documentada (procedimento/janela; cadência = Seção [12](12-seguranca-privacidade.md)).
- [ ] **Observabilidade** + **alertas** de recurso operando; **SLI/SLO** definidos (O12/O13/§15).
- [ ] **Runbook de DR** escrito e validado; severidades e on-call definidos (§15).
- [ ] **IaC versionada** do ambiente (O2/§15).
- [ ] **Propagação de exclusão ao backup** definida (O19), acoplada à decisão de erasure da Seção [12](12-seguranca-privacidade.md) §15.
- [ ] **Agendador de retenção/expurgo/anonimização** provisionado (O16; prazo = Seção [12](12-seguranca-privacidade.md);
  taxonomia = Seção [17](17-telemetria-metricas.md)) — **exigido quando a 1ª janela de retenção se aproximar**.
- [ ] **Dimensionamento** de workers/pool definido; **Redis** provisionado no gatilho do estágio B (O15/§15).

### 15. Questões em aberto
Cada item é **decisão do dono** (⚠️); os defaults são **propostas** da 14, não decisões autônomas:

- ⚠️ **Modelo oficial de produção (14.3/14.6/ADR-14-A).** Proposta: **Railway (backend) + Vercel (web) +
  Postgres gerenciado** como oficial do Quest; **self-host compose/Caddy** = alternativa de soberania/Edu (as
  **duas realidades** hoje no repo). Confirmar + decidir a **IaC** (ferramenta para versionar Railway/Vercel).
- ⚠️ **Ambiente de staging (14.4).** Criar staging/homologação separado (hoje só `dev|producao`)? Limites de
  acesso e que dado pode conter.
- ✅/⚠️ **CD automatizado (14.10).** JÁ EXISTE `deploy.yml` (staging/produção, gated por `DEPLOY_ENABLED`, com
  aprovação manual no Environment). Resta ao dono ATIVAR (segredos Railway/Vercel + Required reviewers) ou
  mantê-lo desligado — o mecanismo está no repo, não é mais questão em aberto de arquitetura.
- ⚠️ **Rotação de segredos (14.9/O11).** **Procedimento e ferramenta** (cofre/secret manager vs. env vars da
  plataforma; janela/comunicação, dado que a rotação da chave de assinatura **invalida os tokens** — `token_version`
  = revogação, Seção [11](11-arquitetura.md)). *A **cadência** é política da Seção [12](12-seguranca-privacidade.md).*
- ⚠️ **RPO/RTO (14.20/O8).** Alvos por classe de dado (**ledger append-only** × **telemetria durável mas
  expurgável** — Seção [17](17-telemetria-metricas.md) — × estado cosmético) — quanto de perda e de
  indisponibilidade o negócio aceita.
- ⚠️ **Backup: cadência/retenção/local/cripto (14.19/14.22/O6).** Snapshots gerenciados do Railway **ou**
  `pg_dump` agendado próprio; retenção; **destino off-site**; **cifragem** (exigida pela Seção [12](12-seguranca-privacidade.md)
  por ser dado de criança); periodicidade do **game day**.
- ⚠️ **Propagação da exclusão ao backup (O19).** Como a exclusão/anonimização sai dos snapshots/WAL/PITR/off-site
  (retenção limitada × crypto-shredding) — **depende da decisão de erasure** ainda aberta na
  Seção [12](12-seguranca-privacidade.md) §15 (cascade × anonimização).
- ⚠️ **Cenários de DR e validação dos runbooks (14.24).** Quais desastres priorizar e quem valida.
- ⚠️ **Stack de observabilidade e SLO (14.28/14.31/O12/O13).** Nativo Railway × Grafana/Prometheus × Sentry pago;
  **SLI/SLO** e error budget (disponibilidade da API, sucesso de login do aluno, latência de submissão); orçamento.
  *(Sentry é processador externo — exige a minimização da Seção [12](12-seguranca-privacidade.md) antes do egresso.)*
- ⚠️ **Plantão on-call (14.32).** Quem responde fora do horário (realidade de **1 dev**), por qual canal, e o
  **SLA** prometido às escolas.
- ⚠️ **Janela de manutenção (14.34).** Horário aceitável dado o calendário letivo (madrugada BR? fim de semana?)
  e o canal de aviso (**ponte com a Seção [21](21-suporte-operacao.md)**). *(É a "janela segura" da fase
  destrutiva — O3.)*
- ⚠️ **CDN de assets (14.36).** Confirmar **Cloudflare R2** (ou equivalente) e o orçamento de storage/banda para
  áudio e GLB.
- ⚠️ **Gatilho do Redis (14.37).** Quando provisionar o estágio B (proposta: ~10 escolas simultâneas / quando o
  rate-limit/salas em memória deixarem de servir) — coordenado com a Seção [11](11-arquitetura.md).
- ⚠️ **Capacidade e teste de carga (14.40).** Cenário-alvo (pico **7h30**), número de dispositivos simultâneos, e
  quando validar antes de cada temporada (**compartilhado com a Seção [18](18-qa-testes.md)**).
- ⚠️ **FinOps (14.41).** Teto orçamentário de infra por serviço (banco/CDN/IA) e o gatilho de alerta de custo.

### 16. ADR (Architecture Decision Record)
- **ADR-14-A — Modelo canônico de produção.** Proposta: **Railway (backend) + Vercel (web) + Postgres
  gerenciado** como a produção oficial do Quest; o **self-host** `docker-compose`+`Caddy` é alternativa de
  soberania (Edu), não a prod do Quest. A infra passa a ser **versionada** (IaC). *Pendente de ratificação (§15).*
- **ADR-14-B — Migração de schema executada uma vez no boot.** O `entrypoint.sh` roda `alembic upgrade` **uma
  única vez** antes dos workers (evita corrida de DDL — desenho da Seção [11](11-arquitetura.md)); mudanças
  seguem **expand/contract** (padrão **fix-forward**), com a fase destrutiva isolada na **janela de manutenção**.
- **ADR-14-C — Backup só conta se restaurado, e honra a exclusão.** O backup do Postgres de produção é
  **cifrado**, **off-site**, **por `escola_id`** (P15, honrando a tenancy transitiva) e validado por **game day**
  periódico. Ele tem **integridade verificável** (*tamper-evident*), **não** imutabilidade perpétua: **honra a
  retenção e o direito de exclusão** da Seção [12](12-seguranca-privacidade.md) (O19). *Cadência/retenção/RTO/RPO/destino
  pendentes (§15); exigência de cifrar = Seção 12.*
- **ADR-14-D — Cripto em repouso e cofre de segredos (operação delegada pela 12).** Volume e backups cifrados;
  segredos fora do código; **procedimento** de rotação de chaves. A rotação da chave de assinatura **invalida os
  tokens** (`token_version` = **revogação**, mecanismo da Seção [11](11-arquitetura.md)); a 14 fixa a **operação**
  (janela/passos), a **política/cadência** = Seção [12](12-seguranca-privacidade.md).

*Decisões cross-módulo não são improvisadas aqui: as pendências acima viram ADR ou item de §15.*

---

## 🇬🇧 Infrastructure, Deploy, Backup & DR (SRE/DevOps)

### 1. Objective
To be the **definitive operations reference** for Constela Quest: **how** the product is **deployed, operated,
monitored, scaled, backed up and recovered (DR)** — so the service for **thousands of schools** stays up during
the class-time peak, a **child's data is never lost**, and a **bad release** reverts in minutes. It lets us
operate **without improvising** during an incident. It decides **operations (SRE/DevOps)**; it **operates** the
**mechanism** (Section [11](11-arquitetura.md)) and **executes** the **policy** (Section [12](12-seguranca-privacidade.md));
it does **not** decide the mechanism, the legal policy, the telemetry **taxonomy** (Section [17](17-telemetria-metricas.md)),
nor the config **values** (Section [19](19-liveops.md)).

### 2. Context
In the **Hub → Edu → Quest** ecosystem, Quest **reuses Edu's identity** and runs as a **modular monolith** (a
single FastAPI backend). **Current state (Q0) — already-mature infra foundation:**
- **Build** — `backend/Dockerfile` (python 3.13-slim, **non-root**, respects `$PORT`, `/dados` volumes,
  `ENTRYPOINT entrypoint.sh`) and `apps/web/Dockerfile` (Node 22 → nginx).
- **Deploy (two deploy realities — models — coexist in the repo)** — (a) **Railway** (backend, via `Dockerfile`)
  + **Vercel** (web, `vercel.json`, `constelaedu.com`/`www`) + **managed Postgres** → the **real Quest
  production** (memory `producao-urls`); (b) **self-host** `docker-compose.yml` + `Caddyfile` (postgres17 +
  backend + web nginx; `backup`/`https` services **profile-gated**, backup = `pg_dump` 14-day retention) → the
  **Edu VPS** path. Section 14 must **fix the official model** and disambiguate (§15/ADR-14-A).
- **Migration on boot** — `entrypoint.sh` runs `python -m scripts.migrate` **once** (before the workers, no DDL
  race) → `app/core/migracoes.py` (`alembic upgrade head`; stamp base `0001` for pre-Alembic DBs) →
  `alembic/versions/{0001,0002,0002a,0003,0004,0005}`. The Alembic **design** is Section [11](11-arquitetura.md)'s; 14 **operates**.
- **Config/secrets** — `config.py` (pydantic-settings; `ENV` **fail-closed** in production: `_validar_producao`
  requires `SECRET_KEY≥32` and non-sqlite `DATABASE_URL`). `/docs`, `/redoc` and `/openapi.json` are **off by
  default** via the `DOCS_HABILITADOS=False` flag (applied in `main.py`, **independent of `ENV`**; enabled only
  explicitly in dev). Secrets **only in env** (`.env` gitignored; `.env.example` documents), **none in code**.
- **Encryption at rest** — `security.py` uses **Fernet** (derived from `SECRET_KEY`) **only** for the external
  assistant API key; passwords = bcrypt; reset token = single-use SHA-256. **No** column encryption nor Postgres
  volume encryption by the app.
- **Observability** — `main.py` exposes `/api/health/live`, `/api/health/ready` (SELECT 1 → 503), `/api/health`,
  `/metrics` (Prometheus, gated); `observabilidade.py` (JSON logs with `request_id`/`escola_id`/route via
  contextvars; prometheus-client; gated Sentry; all **degradable to no-op**). `rate_limit.py` = **in-memory
  per-process** (not distributed).
- **CI** — `.github/workflows/ci.yml` (pytest + typecheck/build + `docker build` validation); **no deploy job**.
  `desktop-release.yml` (Tauri installers on `v*` tags).

**Not yet present:** versioned IaC of the production host; a **CD** step; a **staging** environment; **automated
backup of Railway prod** (the compose service is gated and targets the local Postgres); a **DR runbook**,
RTO/RPO, failover, restore test; provisioned **Redis** (Section 11 stage B target); an own **CDN**;
**vault/rotation** of secrets; a **scheduler** for retention/purge jobs. This chapter specifies the target operation.

### 3. Feature philosophy
**Good operations are invisible when they work and obvious when they fail.** SRE principles guide this section:
**automate the repeatable**, **make state reproducible** (IaC — recreate an environment from scratch without
guessing), **a backup only counts once it has been restored** (game day), and the **operational error never
reaches the child as punishment** — under incident, the product **degrades with dignity** (offline shell + local
queue — Section [11](11-arquitetura.md)'s mechanism), consistent with P6 and Section [13](13-acessibilidade.md).

Link to the **Immutable Principles** ([01](01-principios-imutaveis.md)): **P13** (the server is the answer-key
authority) requires it to **stay up** and intact; **P14** (auditable ledger) requires a backup with **verifiable
integrity** (*tamper-evident* — resistant to silent alteration/ransomware **during the retention window**),
**not** perpetual retention: the backup **honors the retention and the right to erasure** of
Section [12](12-seguranca-privacidade.md); **P15** (isolation by `escola_id`) extends to **backup/restore per
school**; **P17** (performance floor) becomes operational **capacity**; **P18** (no third-party tracking SDK on
the client) requires **not selling a child's telemetry** — and, since aggregators/Sentry are external
**processors**, Section [12](12-seguranca-privacidade.md)'s **minimization** (masking a child's code/IP) is
applied **before** any egress, under its legal basis. The **school's trust** is, in the end, **uptime + safe,
recoverable data**.

### 4. The experience the player should feel
**The child and the adult never see the infra** — they only feel that the game **"is always there and fast"**,
even at 7:30 a.m. when the whole network logs in at once. Under incident, instead of a blank screen, the child
finds **graceful degradation** (the app opens offline, keeps what they did, and syncs later — Section
[11](11-arquitetura.md)'s mechanism); maintenance appears with **kindness** (Section [13](13-acessibilidade.md)).

**The adult** (school/family) feels **confidence**: the student's data is **saved, encrypted and recoverable**,
and LGPD is respected. **The team** (today **one developer**) feels that **the runbook guides them** — an
incident at 3 a.m. has a step-by-step, not a panic.

### 5. Complete flow
The **operational lifecycle**, from commit to incident:

1. **Build** — Docker image of backend and web (reproducible, non-root).
2. **CI** — `ci.yml`: tests + typecheck + image build (quality gate before merge).
3. **Deploy** — backend on **Railway** (via `Dockerfile`+`$PORT`), web on **Vercel** (via `vercel.json`).
4. **Migration on boot** — `entrypoint.sh` runs `alembic upgrade` **once** before the workers (avoids DDL race);
   **expand/contract** policy for changes without peak-time downtime (§9).
5. **Health gate** — the router only sends traffic after `/api/health/ready` returns OK (readiness with SELECT 1).
6. **Post-deploy smoke** — automatic check of the critical paths (student login; and a **read-only/validation**
   submission path or one on a **disposable synthetic school/profile** — **never** writing to the production
   ledger, P14).
7. **Rollback** — if smoke/error fails, **revert the release** (code); with expand/contract the default is
   **fix-forward** (the additive phase is safe to revert). **DDL downgrade does not run on boot** — if needed, it
   is a **manual runbook** procedure (§9/§12).
8. **Continuous operation** — observability (JSON logs, `/metrics`, Sentry), resource **alerts** and **on-call**.
9. **Continuous backup** — snapshot + WAL retention / PITR of the production Postgres (encrypted, off-site).
10. **Restore test** — periodic **game day** proving RTO/RPO ("an untested backup does not count").
11. **DR** — in a disaster (DB loss, region down, corruption), follow the step-by-step technical **runbook**.
12. **Scale** — when the trigger fires (Section [11](11-arquitetura.md) stage B), **provision Redis** (distributed
    rate-limit and WS rooms) and stateless backend replicas.

Environments: **dev** (SQLite/local) → **staging** (prod parity, synthetic data — ⚠️ §15) → **prod**.

### 6. Interface (when it exists)
**N/A for child UI** — this chapter has no in-game screen. **Operational** surfaces:
- **Public status page** (14.35) — communicates incident/maintenance; **existence** is 14's, the school-facing
  **text/channel** is Section [21](21-suporte-operacao.md)'s.
- **Observability dashboards** (internal) — RED/USE, uptime, resources; consume `/metrics` and the JSON logs.
- **Health endpoints** (`/api/health/*`) and **`/metrics`** — already exist (Q0); 14 defines the **operation**
  (secure scrape, restrict `/metrics` on the network).

### 7. UX
The "operations UX" has two audiences:
- **For the team** — clear, tested **runbooks**; **actionable alerts** (signal, not noise); **structured logs**
  searchable by `request_id`/`escola_id`/route; a readable **status panel**. The goal is that whoever is on-call
  **resolves without guessing**.
- **For the end user** — under incident/maintenance, **graceful degradation** and **gentle messages** (the
  surface and tone are Section [13](13-acessibilidade.md)'s); never a raw error screen for the child.

### 8. Game Design
**N/A** — an infrastructure chapter, no game dimension. Boundary note: operation **sustains** the game rules.
E.g. the **day/week cutoff** (for cap/Flame/dailies) is Section [05](05-sistemas-de-jogo.md)'s definition; 14
only guarantees **UTC in the DB** and the consistent computation of `data_ref` (the operational reference date
derived from UTC — §9/O17). **Capacity** at peak uses the metric of Section [17](17-telemetria-metricas.md)/[18](18-qa-testes.md);
the **sizing** is 14's.

### 9. Business rules
The **deterministic operation norms** (the single source; the **mechanism** is Section [11](11-arquitetura.md)'s,
the **policy** Section [12](12-seguranca-privacidade.md)'s):

| # | Operation norm | Rule | Boundary |
|---|----------------|------|----------|
| O1 | **Environments** | **dev / staging / prod** isolated (data/secret per env); production **fail-closed** (`config.py`) | 14 ⚠️ (staging — §15) |
| O2 | **Infra as code** | reproducible, versioned topology (recreate from scratch without a panel) | 14 ⚠️ (tool — §15) |
| O3 | **Schema migration** | `alembic upgrade` **once** on boot (`entrypoint.sh`), **before** the workers; **expand/contract** for zero-downtime; **destructive phase only in the maintenance window** (14.34/§15) | 14 operates; design = [11](11-arquitetura.md) |
| O4 | **Health gate** | traffic only after `/api/health/ready` OK; **smoke** of critical paths post-deploy (without writing to the prod ledger) | 14 |
| O5 | **Rollback** | revert **code**; with expand/contract the default is **fix-forward**; **DDL downgrade does not run on boot** (manual, via runbook) | 14 |
| O6 | **Backup** | snapshot + WAL/PITR of the **production** Postgres; **encrypted** and **off-site**; verifiable integrity (*tamper-evident*) | 14 ⚠️ (cadence/location — §15); requirement = [12](12-seguranca-privacidade.md) |
| O7 | **Tested restore** | periodic **game day** proves RTO/RPO — *"an untested backup does not count"* | 14 |
| O8 | **RPO/RTO** | target per **data class** (append-only ledger × durable-but-purgeable telemetry × cosmetic state) | 14 ⚠️ (numbers — §15) |
| O9 | **Backup isolation** | restore/export **per `escola_id`** — directly where the column exists; via `perfil_id`→`quest_perfis` for **transitive tenancy** (Section [11](11-arquitetura.md)); the global reference catalog stays outside the per-school scope (P15) | 14 + [01](01-principios-imutaveis.md)/[11](11-arquitetura.md) |
| O10 | **Encryption at rest** | Postgres volume + encrypted backups; Fernet-at-rest of the API key (Q0) | 14 (operation delegated by [12](12-seguranca-privacidade.md)) |
| O11 | **Secrets** | **never in code** (`.env`/vault); operational **procedure** to rotate `SECRET_KEY`/JWT/Fernet/DB password (window/steps). Rotating the signing key **invalidates the tokens**; `token_version` is Section [11](11-arquitetura.md)'s **revocation** mechanism | 14 (operation); mechanism = [11](11-arquitetura.md); policy/cadence = [12](12-seguranca-privacidade.md) |
| O12 | **Observability** | JSON logs + `/metrics` + Sentry (Q0); resource **alerts** (CPU/RAM/disk/pool/uptime) | 14 ⚠️ (stack/SLO — §15) |
| O13 | **SLI/SLO** | availability/latency targets + error budget (student login, submission) | 14 ⚠️ (numbers — §15) |
| O14 | **Infra security** | **mandatory TLS**, hardening, `dependabot`, secret scanning | 14 (complements [12](12-seguranca-privacidade.md)) |
| O15 | **Scale** | size workers/pool; **provision Redis** at the stage-B trigger; stateless replicas | 14 operates; A›B›C path = [11](11-arquitetura.md) |
| O16 | **Scheduling** | cron/worker that **executes** the retention/purge/anonymization jobs | 14 (mechanism); deadline = [12](12-seguranca-privacidade.md); taxonomy/logic = [17](17-telemetria-metricas.md) |
| O17 | **Time in operation** | **UTC in the DB**; operational `data_ref` (derived from UTC); day/week cutoff = [05](05-sistemas-de-jogo.md); pt-BR formatting = [16](16-localizacao-i18n.md) | 14 |
| O18 | **Data outside prod** | staging/tests use **synthetic/anonymized** data — **forbidden** to copy real child data | 14 (corollary of P15/P18 + minimization = [12](12-seguranca-privacidade.md)) |
| O19 | **Erasure → backup** | the erasure/anonymization decided by Section [12](12-seguranca-privacidade.md) **propagates into the backups** within the retention window (limited retention + **crypto-shredding** of the key where applicable); a backup is **not** perpetual retention | 14 operates; erasure decision (cascade × anonymization) = [12](12-seguranca-privacidade.md) §15 ⚠️ |

**Config × values:** 14 owns the **delivery mechanism** for config/env/secrets and the **feature flags**; the
`quest.*` **values** (limits, windows, economy) are Section [19](19-liveops.md)'s — 14 **delivers**, does not set them.
**Logs, three owners:** the **observability log** (ephemeral, request-scoped, short retention) is operated by 14
(O12); the **audit log / ledger** (immutable, legal retention) is Section [12](12-seguranca-privacidade.md)'s
(14 only **backs it up** — O6/O19 —, without redefining its retention); the **product telemetry** is Section
[17](17-telemetria-metricas.md)'s.

### 10. Technical architecture
The real topology and its mapping to code (contracts → Appendix B):
- **Production (proposed canonical model — ⚠️ §15/ADR-14-A):** **backend on Railway** (`backend/Dockerfile`
  image, `$PORT`, `entrypoint.sh` with single migration) + **web on Vercel** (`vercel.json`,
  `www.constelaedu.com`) + **managed Postgres**. The **self-host** `docker-compose.yml`+`Caddyfile` (backup
  `pg_dump` 14 d, HTTPS Caddy) is the **sovereignty/Edu alternative**, **not** Quest prod — 14 documents both and
  marks the official one.
- **Fail-closed config** — `config.py` refuses to boot in production without `SECRET_KEY≥32`/non-sqlite
  `DATABASE_URL`; `/docs` is off via `DOCS_HABILITADOS` (independent of ENV). The convention is **default=production
  in code, dev overrides in `.env`** (the `PUBLIC_BASE_URL` lesson).
- **Migration** — `migracoes.py`/`alembic` (stamp-then-upgrade); 14 operates the **when/how** at deploy.
- **Observability** — `observabilidade.py` (JSON logs, Prometheus, Sentry) + `main.py` (health/`/metrics`); 14
  defines the **operation** (aggregator, alerts, secure scrape).
- **Crypto/secrets** — `security.py` (Fernet at-rest today only for the AI key); 14 extends to **encrypted
  volume/backups** and a **vault** (operation delegated by Section [12](12-seguranca-privacidade.md)).
- **Scale A›B›C** (mechanism = Section [11](11-arquitetura.md)): **A** = 1 Railway instance + in-memory
  rate-limit/rooms (today); **B** = **Redis** (distributed rate-limit and live state; stateless replicas); **C** =
  service extraction. 14 defines the **trigger** and the **operation**, not the design.
- **CDN** — **Cloudflare R2** (or equivalent — ⚠️ §15) for GLB/audio; the asset **pipeline/authoring** is Section
  [15](15-arte-audio-assets.md)'s; the rule "public asset without token, never the answer key" is Section
  [12](12-seguranca-privacidade.md)'s; 14 only **operates** delivery.

### 11. Dependencies on other modules
**Consumes / operates / executes:**
- **Section [11](11-arquitetura.md)** — the **mechanism** (token, WebSocket+Redis, outbox, ledger, answer-key
  authority, routes, A›B›C path, Alembic design, `token_version` = revocation). 14 **operates/deploys/scales**,
  does not redesign.
- **Section [12](12-seguranca-privacidade.md)** — the **policy** (legal retention, incidents, legal basis,
  rotation **cadence**) and the **requirement** to encrypt/retain the backup. The 12 **delegates to 14** the
  **operation** of backup/DR/encryption-at-rest/secrets — 14 **executes**.
- **Section [17](17-telemetria-metricas.md)** — boundary: 17 owns the **taxonomy** and the **logic** of the
  purge; 14 handles **infra observability** (health/uptime/RED/USE) and **provides the scheduler** that fires the purge.
- **Section [19](19-liveops.md)** — the `quest.*` **values**; 14 delivers the config/flags **mechanism**.
- **Section [15](15-arte-audio-assets.md)** — the asset **catalog**; 14 operates the **storage+CDN**.
- **Section [16](16-localizacao-i18n.md)** — the pt-BR date **formatting** (14 keeps **UTC** in the DB).

**"Logs" boundary (three owners):** **observability** (ephemeral, operational) = 14 (O12); **audit/ledger**
(immutable, legal retention) = Section [12](12-seguranca-privacidade.md) (14 only backs it up, O6/O19);
**product telemetry** = Section [17](17-telemetria-metricas.md).

**Bridge, not redefinition:**
- **Section [21](21-suporte-operacao.md)** — 14 **schedules** the maintenance window; the school-facing
  **communication** is 21's.
- **Section [20](20-migracao-importacao.md)** — 14 executes the **schema migration** at deploy; the school data
  **ETL** is 20's.
- **Section [18](18-qa-testes.md)** — the peak-scenario **load test** is **shared** (14 = operational capacity,
  18 = test strategy).

**What breaks if it changes:** if 11 changes the **scale path** or the Alembic design, 14 **re-tunes the
operation**; if 12 changes the **encryption/retention requirement** or the erasure decision, 14 **re-executes**
— 14 never sets the legal number.

### 12. Edge cases
- **Production DB loss** → restore via **PITR**/latest snapshot (RPO — ⚠️ §15); runbook 14.24.
- **Region/host down** → **DR**: failover/recreation from IaC + off-site backup (⚠️ §15).
- **Data corruption/error for one school** → restore/export **per `escola_id`** (directly where the column
  exists; via `perfil_id`→`quest_perfis` for transitive tenancy — Section [11](11-arquitetura.md)) without
  touching the others (P15).
- **Data-subject erasure (LGPD)** → the erasure/anonymization (Section [12](12-seguranca-privacidade.md) §15's
  decision — today `ON DELETE CASCADE`) **propagates into the backups**: limited retention + **crypto-shredding**
  of the key where applicable; the child's data does **not** stay forever in the snapshot (O19).
- **Failed deploy** → **rollback** of the release (fix-forward by default); the destructive phase never ships
  with the release that introduces it.
- **Migration during class peak** → **expand/contract** in two phases; the destructive phase only in the
  **maintenance window** (⚠️ §15/14.34).
- **7:30 a.m. peak (whole network at once)** → sized capacity + Redis/replica trigger (⚠️ §15).
- **Dependency down** (DB/Redis) → **graceful degradation**: offline shell + local queue (Section
  [11](11-arquitetura.md)'s mechanism); the child sees no blank screen.
- **Leaked secret** → **rotation** (procedure = 14; policy/cadence = Section [12](12-seguranca-privacidade.md));
  `token_version` **revokes** the compromised sessions (Section [11](11-arquitetura.md)'s mechanism).
- **Backup never restored** → mandatory **game day**; an untested backup is treated as **nonexistent**.
- **Stuck service-worker cache** (the favicon lesson) → **cache-busting** of the SW (Workbox) on the PWA deploy.
- **SQLite (dev) × Postgres (prod) divergence** → dev↔prod **parity** policy (JSON types, indexes, transactions);
  a Postgres staging reduces the risk.
- **A single dev on-call** → **severities** + automation + actionable alerts reduce what needs a human at 3 a.m.
  (⚠️ §15 — on-call/SLA).

### 13. Future scalability
- **A›B›C path** (Section [11](11-arquitetura.md)) — **Redis** at the trigger (stage B: distributed rate-limit
  and WS rooms, stateless replicas); **service extraction** (C) when load justifies it.
- **Multi-region** for DR (geographic failover) when the RTO requires it.
- **Full IaC** — recreate any environment from scratch; a permanent **staging**.
- **Dedicated CDN + storage** (Cloudflare R2 or equivalent) for the growing GLB/audio catalog.
- **Secret vault** and **automated rotation**; **FinOps** with a per-service cost ceiling and alert.
- **Continuous security/audit** — `dependabot`, secret scanning, and the contrast/perf gate in CI
  (Section [18](18-qa-testes.md)).

### 14. Implementation checklist
**A — Verifiable now (go-live gate / operational DoD; links to Appendix F):**
- [ ] **Production fail-closed** (`config.py`: `SECRET_KEY≥32`, non-sqlite `DATABASE_URL`).
- [ ] **`DOCS_HABILITADOS=false`** in production (`/docs`, `/redoc`, `/openapi.json` down).
- [ ] **Migration** applied **once** on boot, tested, with a fix-forward / code-rollback plan.
- [ ] **Health gate** active (traffic only after `/api/health/ready`) + **smoke** post-deploy (without writing to the prod ledger).
- [ ] **Encryption at rest** (volume + backups) and **secrets** outside code (vault/env).
- [ ] **Mandatory TLS** + hardening + `dependabot` + secret scanning.
- [ ] **Isolation by `escola_id`** verified in backup/restore, honoring transitive tenancy (P15).
- [ ] **Data outside production** is synthetic/anonymized (never real child data).
- [ ] **Per-new-school provisioning** completed (create `escola_id`, verify P15 isolation, minimal seed).
- [ ] **UTC in the DB** and operational `data_ref` consistent (O17).

**B — Blocked by owner decision (§15) — cannot go live without ratification:**
- [ ] **Official topology ratified** (ADR-14-A) — go-live precondition.
- [ ] **Automated backup** of prod (snapshot + WAL/PITR), **encrypted** and **off-site** — requires cadence/location (O6/§15).
- [ ] **Tested restore** (game day) proving the target **RTO/RPO** — requires O8/§15 ratified.
- [ ] **Secret rotation** documented (procedure/window; cadence = Section [12](12-seguranca-privacidade.md)).
- [ ] **Observability** + resource **alerts** operating; **SLI/SLO** defined (O12/O13/§15).
- [ ] **DR runbook** written and validated; severities and on-call defined (§15).
- [ ] **Versioned IaC** of the environment (O2/§15).
- [ ] **Erasure propagation to backup** defined (O19), coupled to Section [12](12-seguranca-privacidade.md) §15's erasure decision.
- [ ] **Retention/purge/anonymization scheduler** provisioned (O16; deadline = Section [12](12-seguranca-privacidade.md);
  taxonomy = Section [17](17-telemetria-metricas.md)) — **required as the first retention window approaches**.
- [ ] **Workers/pool sizing** defined; **Redis** provisioned at the stage-B trigger (O15/§15).

### 15. Open questions
Each item is a **owner decision** (⚠️); the defaults are 14's **proposals**, not autonomous decisions:

- ⚠️ **Official production model (14.3/14.6/ADR-14-A).** Proposal: **Railway (backend) + Vercel (web) + managed
  Postgres** as the official Quest prod; **self-host compose/Caddy** = sovereignty/Edu alternative (the **two
  realities** in the repo today). Confirm + decide the **IaC** (tool to version Railway/Vercel).
- ⚠️ **Staging environment (14.4).** Create a staging environment separate from prod (today only `dev|producao`)?
  Access limits and what data it may contain.
- ⚠️ **Automated CD (14.10).** Add deploy to the pipeline (with an approval gate) or keep manual/auto-Railway deploy?
- ⚠️ **Secret rotation (14.9/O11).** **Procedure and tool** (vault/secret manager vs. platform env vars;
  window/communication, given that rotating the signing key **invalidates the tokens** — `token_version` =
  revocation, Section [11](11-arquitetura.md)). *The **cadence** is Section [12](12-seguranca-privacidade.md)'s policy.*
- ⚠️ **RPO/RTO (14.20/O8).** Targets per data class (**append-only ledger** × **durable-but-purgeable telemetry**
  — Section [17](17-telemetria-metricas.md) — × cosmetic state) — how much loss and downtime the business accepts.
- ⚠️ **Backup: cadence/retention/location/crypto (14.19/14.22/O6).** Railway managed snapshots **or** own
  scheduled `pg_dump`; retention; **off-site destination**; **encryption** (required by Section
  [12](12-seguranca-privacidade.md) as child data); **game day** frequency.
- ⚠️ **Erasure propagation to backup (O19).** How erasure/anonymization leaves the snapshots/WAL/PITR/off-site
  (limited retention × crypto-shredding) — **depends on the erasure decision** still open in Section
  [12](12-seguranca-privacidade.md) §15 (cascade × anonymization).
- ⚠️ **DR scenarios and runbook validation (14.24).** Which disasters to prioritize and who validates.
- ⚠️ **Observability stack and SLO (14.28/14.31/O12/O13).** Railway native × Grafana/Prometheus × paid Sentry;
  **SLI/SLO** and error budget (API availability, student login success, submission latency); budget. *(Sentry is
  an external processor — requires Section [12](12-seguranca-privacidade.md)'s minimization before egress.)*
- ⚠️ **On-call (14.32).** Who responds off-hours (the **1-dev** reality), through which channel, and the **SLA**
  promised to schools.
- ⚠️ **Maintenance window (14.34).** Acceptable timing given the school calendar (BR early morning? weekend?) and
  the notice channel (**bridge with Section [21](21-suporte-operacao.md)**). *(It is the destructive phase's
  "safe window" — O3.)*
- ⚠️ **Asset CDN (14.36).** Confirm **Cloudflare R2** (or equivalent) and the storage/bandwidth budget for audio
  and GLB.
- ⚠️ **Redis trigger (14.37).** When to provision stage B (proposal: ~10 concurrent schools / when in-memory
  rate-limit/rooms no longer serve) — coordinated with Section [11](11-arquitetura.md).
- ⚠️ **Capacity and load test (14.40).** Target scenario (**7:30 a.m.** peak), concurrent device count, and when
  to validate before each season (**shared with Section [18](18-qa-testes.md)**).
- ⚠️ **FinOps (14.41).** Per-service infra budget ceiling (DB/CDN/AI) and the cost-alert trigger.

### 16. ADR (Architecture Decision Record)
- **ADR-14-A — Canonical production model.** Proposal: **Railway (backend) + Vercel (web) + managed Postgres**
  as the official Quest production; the **self-host** `docker-compose`+`Caddy` is a sovereignty alternative (Edu),
  not Quest prod. Infra becomes **versioned** (IaC). *Pending ratification (§15).*
- **ADR-14-B — Schema migration executed once on boot.** `entrypoint.sh` runs `alembic upgrade` **once** before
  the workers (avoids a DDL race — Section [11](11-arquitetura.md)'s design); changes follow **expand/contract**
  (default **fix-forward**), with the destructive phase isolated in the **maintenance window**.
- **ADR-14-C — A backup only counts if restored, and honors erasure.** The production Postgres backup is
  **encrypted**, **off-site**, **per `escola_id`** (P15, honoring transitive tenancy) and validated by a periodic
  **game day**. It has **verifiable integrity** (*tamper-evident*), **not** perpetual immutability: it **honors
  the retention and the right to erasure** of Section [12](12-seguranca-privacidade.md) (O19).
  *Cadence/retention/RTO/RPO/destination pending (§15); the encryption requirement = Section 12.*
- **ADR-14-D — Encryption at rest and secret vault (operation delegated by 12).** Encrypted volume and backups;
  secrets outside code; key rotation **procedure**. Rotating the signing key **invalidates the tokens**
  (`token_version` = **revocation**, Section [11](11-arquitetura.md)'s mechanism); 14 fixes the **operation**
  (window/steps), the **policy/cadence** = Section [12](12-seguranca-privacidade.md).

*Cross-module decisions are not improvised here: the pending items above become an ADR or a §15 entry.*
