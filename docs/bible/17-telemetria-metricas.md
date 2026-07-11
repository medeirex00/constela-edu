# 17 — Telemetria, Métricas & Analytics / Telemetry, Metrics & Analytics

- **Status:** 🟢 aprovado / approved
- **Padrão / Standard:** [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) (16 partes)
- **Fontes / Sources:** `INDICE.md` (bloco 17, subseções 17.1–17.30 + espelho de decisões em aberto; ⚠️ 17.2/17.3/17.4/17.6/17.21/17.28) + **Apêndice D** (Catálogo de Eventos, D.1–D.36), `_estado-atual/RELATORIO-2026-07-09.md` (Q0: sem analytics de produto), `backend/app/quest/models/progresso.py` (`quest_tentativas` = **ledger de jogadas** imutável; coluna `respostas` JSON = artefato **expurgável** dividido pela Seção 12; `perfil_id` **ON DELETE CASCADE** → toda a telemetria some na exclusão do aluno; `quest_progresso`/`quest_habilidades` = caches recalculáveis; `origem` web|pwa-offline), `backend/app/quest/models/perfil.py` (`quest_perfis`: `xp_total`; `sequencia_dias`/`escudo_sequencia`/`ultimo_dia_ativo` = sinal de uso saudável), `backend/app/models/nota.py` (`LogAuditoria`/`logs_auditoria` = **auditoria permanente**, ≠ telemetria de produto) + `backend/app/services/audit.py` (`registrar()`), `backend/app/core/observabilidade.py` (observabilidade de **infra** — Seção 14, não produto), `backend/app/quest/routers/professor.py` (Q0: só cartões/acessos; nenhum painel de telemetria), `backend/alembic/versions/0001_esquema_inicial.py` (cria o ledger; **sem** `quest_outbox`), Seções [06](06-pedagogico-bncc.md)/[08](08-onboarding-ftue.md)/[09](09-social.md)/[12](12-seguranca-privacidade.md)/[13](13-acessibilidade.md)/[14](14-infra-deploy-dr.md)
- **Depende de / Depends on:** princípios (P3 coleta mínima · P5 ranking individual nunca à criança · P13 servidor é autoridade · P14 ledger auditável · P15 isolamento por escola · P18 sem tracking de terceiros) → [01](01-principios-imutaveis.md); **política LGPD** (base legal, consentimento, **prazo** de retenção, minimização/mascaramento, gatilho de anonimização, **decisão de erasure** cascade × anonimização) → [12](12-seguranca-privacidade.md); **observabilidade de infra** + o **agendador** (cron/worker O16) que **executa** o expurgo → [14](14-infra-deploy-dr.md); **mecânica** de jogo/economia que **gera** os eventos (XP/moedas/estrelas/Chama) → [05](05-sistemas-de-jogo.md); **fórmula de domínio BNCC** e o **mapeamento** pedagógico → [06](06-pedagogico-bncc.md); **mecanismo** (ledger, autoridade do gabarito, `quest_outbox`, WebSocket/Redis, Alembic) → [11](11-arquitetura.md); **norma** de bem-estar/uso saudável → [13](13-acessibilidade.md); **ranking saudável**/P5 → [09](09-social.md); **critério qualitativo** do funil de ativação (os números são da 17) → [08](08-onboarding-ftue.md); **UI** do painel do professor/família → [10](10-professor-familia.md); **valores** de config `quest.*` → [19](19-liveops.md); **locale** como propriedade de evento → [16](16-localizacao-i18n.md); **contratos de dados** → Apêndice B; **catálogo executável de eventos** → Apêndice D.

> **Convenção / Convention:** "§N" = uma das 16 **partes deste capítulo** / one of the 16 **parts of this
> chapter**; "Seção NN" / "Section NN" = outro capítulo da Bible; "17.NN" / "D.NN" = uma subseção do plano do
> `INDICE.md` (bloco 17 / Apêndice D).
> **Escopo / Scope:** este capítulo decide a **telemetria, as métricas e o analytics de produto** do Constela
> Quest — a **taxonomia de eventos** (o que medir e o esquema de cada evento), as **métricas** de
> produto/aprendizagem/engajamento/uso-saudável, e a **lógica de expurgo/anonimização** da telemetria. Tudo é
> **analytics próprio, mínimo e finalístico** (P18/P3) sobre **dado de criança**. Ele **executa** a **política**
> da Seção [12](12-seguranca-privacidade.md) (prazo/base legal/erasure), usa o **agendador** da Seção [14](14-infra-deploy-dr.md)
> (O16) e **mede** as mecânicas das Seções [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md); **não** cria
> política LGPD, **não** constrói o cron, **não** redefine mecânica **nem fórmula** (BNCC = Seção [06](06-pedagogico-bncc.md)),
> **não** mede infra (Seção [14](14-infra-deploy-dr.md)) e **nunca** expõe **ranking individual** à criança (P5).
> É **dona da taxonomia** que alimenta o **Apêndice D**.

---

## 🇧🇷 Telemetria, Métricas & Analytics

### 1. Objetivo
Ser a **referência definitiva de telemetria e métricas** do Constela Quest: **como sabemos se o produto ensina,
encanta e é saudável** — com **analytics próprio, mínimo e finalístico** (P18/P3), nunca vendendo nem vazando
dado de criança. Define a **taxonomia de eventos** e o **arcabouço de métricas** (norte + guardrails + KPIs — a
enumeração-proposta está em §15, os alvos são ⚠️) e a **lógica de expurgo**. **Executa** a **política** LGPD da
Seção [12](12-seguranca-privacidade.md), usa o **agendador** da Seção [14](14-infra-deploy-dr.md) e **mede** as
mecânicas das Seções [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md); **não** cria política, cron,
mecânica, fórmula BNCC nem métrica de infra — e **nunca** expõe ranking individual à criança (P5).

### 2. Contexto
No ecossistema **Hub → Edu → Quest**, medir **dado de menor** é um ato de responsabilidade: o que se coleta é o
**mínimo** para melhorar o aprendizado e o bem-estar, **nunca** para anúncio ou revenda. **Estado atual (Q0) —
greenfield de analytics de produto:**
- **Nenhum analytics de produto** — **zero** SDK de terceiros (mixpanel/amplitude/GA/posthog/segment…) em código
  ou `package.json` (confirma **P18**); **nenhuma** camada de taxonomia/emissão de evento; **nenhum** KPI/norte
  computado.
- **Matéria-prima existente** — o **ledger de jogadas** imutável `quest_tentativas` (o que a Seção [12](12-seguranca-privacidade.md) chama "ledger de agregados" é este mesmo ledger de jogadas; por jogada: `escola_id`,
  `perfil_id`, `missao_id`, acertos, `tempo_seg`, `xp_ganho`, `estrelas`, `origem`, e a coluna JSON **`respostas`**
  = `{desafio_id, correta, resposta, tempo_ms, dicas, tentativas}` — o **artefato expurgável** dividido pela Seção
  [12](12-seguranca-privacidade.md); note que `resposta` guarda a **resposta bruta** da criança); os **caches
  recalculáveis** `quest_progresso` (melhor estrela/missão) e `quest_habilidades` (domínio BNCC 0–100, **fórmula
  da Seção [06](06-pedagogico-bncc.md) §8k**); `quest_perfis` (`xp_total`, `sequencia_dias`/`escudo_sequencia` = a
  **Chama do Cosmo**, sinal de uso saudável).
- **Erasure hoje = cascade-delete** — na **exclusão do aluno**, toda a telemetria (ledger + caches) é **apagada em
  cascata** (`progresso.py` docstring; `perfil_id` **ON DELETE CASCADE** → `quest_perfis` → `alunos`), por LGPD.
  **Nada** sobrevive hoje; migrar para anonimização é **decisão em aberto da Seção [12](12-seguranca-privacidade.md) §15**.
- **Auditoria ≠ telemetria** — `logs_auditoria` (`LogAuditoria`) é a **trilha de accountability permanente** (da
  Seção [12](12-seguranca-privacidade.md)/[11](11-arquitetura.md)), **não** um barramento de analytics de produto.
- **Observabilidade de infra ≠ produto** — `observabilidade.py` (Prometheus RED, Sentry `send_default_pii=False`,
  `/metrics`) mede **saúde do sistema** (Seção [14](14-infra-deploy-dr.md)), não comportamento no jogo.
- **Não existe ainda** — o **caminho de escrita** da telemetria (nada em produção escreve o ledger; só um teste),
  o **expurgo** (as `respostas` vivem inline, sem store expurgável e sem agendador), o **`quest_outbox`** (alvo Q4)
  e qualquer **painel** de métricas.

Este capítulo **especifica** a taxonomia, o arcabouço de métricas e a lógica de expurgo **do zero**, ancorada no
que já existe.

### 3. Filosofia da funcionalidade
**"Medir para servir a criança — não para explorá-la."** A telemetria do Constela é **própria** (sem terceiros —
P18), **mínima** (só o que tem finalidade pedagógica/produto — P3) e **honesta** (o **servidor** é a fonte da
verdade — P13; o ledger é **auditável** — P14). A regra moral que organiza tudo: **toda métrica de engajamento é
subordinada a um guardrail de aprendizado e de bem-estar** — nunca se otimiza "a criança volta amanhã" às custas
de ela **aprender** e **usar de forma saudável**. E o **ranking individual jamais** chega à criança (P5): métrica
interna ≠ exposição.

Conexão com os **Princípios Imutáveis** ([01](01-principios-imutaveis.md)): **P18** (analytics próprio) e **P3**
(coleta mínima) fundam esta seção; **P13** faz a telemetria **derivada no servidor** a autoridade; **P14** faz o
ledger a fonte imutável; **P15** isola cada evento por `escola_id`; **P5** proíbe expor o ranking individual. Aos
**4 pilares**: mede a **surpresa**, o **progresso visível**, o **vínculo** (sem exposição) e a **autonomia** —
para melhorá-los, nunca para manipular.

### 4. Experiência que o jogador deve sentir
**A criança não sente a telemetria** — ela não vê números frios, não é rotulada, não é ranqueada publicamente. O
que ela sente é o **efeito** de um produto que **aprende com ela**: dificuldade que se ajusta, um mundo que
melhora, um Cosmo que a acolhe. **O adulto** (professor/família) recebe um **panorama honesto** de aprendizado
(mapa BNCC, erros comuns) — **sem** moedas/loja, **sem** ranking individual da criança. **A equipe** enxerga se o
produto ensina e encanta **sem** trair a confiança de quem confiou seu filho/aluno.

### 5. Fluxo completo
O **ciclo de vida de um dado**, da jogada ao expurgo:

1. **Gera** — a criança joga; a mecânica (Seções [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md))
   produz um resultado que o **servidor** grava no **ledger de jogadas** imutável `quest_tentativas` (P13/P14).
2. **Emite** — eventos de produto (envelope padrão) são **derivados no servidor** a partir do ledger imutável
   (P13) — e, **quando o `quest_outbox` existir** (alvo Q4, Seção [11](11-arquitetura.md)), também da telemetria
   social; a instrumentação do **cliente** é **suplementar**, com **fila offline** (IndexedDB) e **sync** ao
   reconectar (dedup por `event_id`, `origem` web|pwa-offline).
3. **Valida** — o **schema registry** (fonte única cliente↔servidor) valida o evento; inválido → **dead-letter**.
4. **Agrega** — os **caches** (`quest_habilidades`) são recomputados a partir do ledger — sem agregado órfão após
   correção; a **fórmula** do domínio (média móvel exponencial, α=0,3) é da Seção [06](06-pedagogico-bncc.md) §8k
   e a **persistência/recompute** do cache é **mecanismo da Seção [11](11-arquitetura.md)**; a 17 **deriva e expõe**
   a métrica e opera seus **próprios agregados analíticos** (**cron** = Seção [14](14-infra-deploy-dr.md) O16).
5. **Mede** — KPIs (norte/guardrails/funis) sobem para **dashboards internos**; **agregados** curados vão ao
   **painel do professor** (UI = Seção [10](10-professor-familia.md)), **sem** moedas/loja/ranking individual (P5).
6. **Minimiza** — o **envelope** de evento nunca carrega **PII/foto/localização/texto livre** (P3); a identidade é
   **pseudônima** (`perfil_id`+`escola_id`); a **resposta bruta** da criança vive **só** no store expurgável (§9/T13).
7. **Expurga / anonimiza** — no **prazo** definido pela Seção [12](12-seguranca-privacidade.md), o agendador (Seção
   [14](14-infra-deploy-dr.md) O16) **expurga** as **respostas detalhadas** (store expurgável — §9), preservando as
   colunas de resultado por jogada (append-only, P14). Na **exclusão do aluno (erasure)**, o resultado segue a
   **decisão da Seção [12](12-seguranca-privacidade.md) §15**: **hoje é cascade-delete** (tudo some); **se** a 12
   migrar para anonimização, o **agregado anônimo** é derivado **antes** do expurgo, congelado e mantido **fora do
   ledger** (nunca por UPDATE nas linhas imutáveis — §9/T14).

### 6. Interface (quando existir)
A 17 **não desenha telas** de criança (N/A). Superfícies **de dados** (não infantis):
- **Dashboards internos de produto** — norte, guardrails, funis; fonte = os agregados derivados.
- **Métricas expostas ao professor** (Edu) — panorama/mapa BNCC/erros comuns; a 17 **delimita quais agregados**
  ficam disponíveis, a **UI** do painel é da Seção [10](10-professor-familia.md) (nunca moedas/loja/ranking individual).
- **Alertas de anomalia de métrica** — norte/guardrail fora da faixa (distinto dos **alertas de recurso/infra** da
  Seção [14](14-infra-deploy-dr.md)).

### 7. UX
A "UX de dados" é para **adultos e equipe** (a criança nunca vê telemetria):
- **Honestidade** — o painel do professor mostra **aprendizado**, não vaidade; nada de expor a criança.
- **Legibilidade** — agregados claros (mapa BNCC, erros comuns), no vocabulário do adulto.
- **Privacidade por padrão** — nenhum dado sensível novo no envelope; identidade pseudônima; acessos de adulto
  **auditados** (reusa `logs_auditoria`).

### 8. Game Design
**N/A como mecânica** — a 17 **mede** o jogo, não o cria. Nota de fronteira: os **sinais anti-farm/anti-abuso**
(farm de XP, abuso de login) que a 17 calcula **alimentam** o rate-limit e a **economia auditável** (mecanismo =
Seções [05](05-sistemas-de-jogo.md)/[11](11-arquitetura.md)); a 17 detecta, não pune.

### 9. Regras de negócio
As **normas de telemetria** (a fonte única da taxonomia e da lógica; a **política** é da Seção [12](12-seguranca-privacidade.md),
o **cron** da Seção [14](14-infra-deploy-dr.md), a **mecânica/fórmula** das Seções [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)):

| # | Norma | Regra | Fronteira |
|---|-------|-------|-----------|
| T1 | **Analytics próprio** | **sem SDK de terceiros** (P18); nenhum dado de criança sai para processador de ads/analytics externo | 17 + [01](01-principios-imutaveis.md) |
| T2 | **Coleta mínima** | o **envelope** de evento nunca carrega **foto/localização/texto livre/PII** direta (P3); só o que tem **finalidade**; a **resposta bruta** da criança vive **só** no store expurgável (T13) | 17; **veredito** de minimização = [12](12-seguranca-privacidade.md) |
| T3 | **Servidor é a fonte** | a telemetria de jogo é **derivada no servidor** do ledger imutável (P13/P14); o cliente é **suplementar** | 17; mecanismo = [11](11-arquitetura.md) |
| T4 | **Pseudonimização** | identidade = `perfil_id` + `escola_id` (isolamento P15); **nunca** nome/PII no evento | 17; política = [12](12-seguranca-privacidade.md) |
| T5 | **Envelope de evento** | `event_name` (`substantivo.verbo`, vocabulário **interno**), `event_version`, `event_id` (UUID, dedup), `occurred_at`/`received_at`, `perfil_id`, `escola_id`, `sessao_id` (definição de sessão ⚠️ §15), `origem`, `locale` | 17 (taxonomia → Apêndice D) |
| T6 | **Schema & versionamento** | **schema registry** como fonte única cliente↔servidor; mudança **versionada** (não quebrar análise histórica); inválido → **dead-letter** | 17 (→ Apêndice D) |
| T7 | **Offline/sync** | fila **IndexedDB** append-only; sync ao reconectar; **dedup por `event_id`**; `occurred_at` preservado em late-arrival; flag `origem` | 17; transporte = [11](11-arquitetura.md) |
| T8 | **Métrica-norte** | "a criança volta amanhã?" (retenção); **definição operacional** proposta: sessão iniciada em D+1 (dia-calendário no fuso da escola) | 17 ⚠️ (definição + alvo — §15) |
| T9 | **Guardrail precede engajamento** | nenhum ganho de retenção vale se **violar** o aprendizado (BNCC) ou o **bem-estar**; o guardrail **precede** o engajamento (núcleo moral, firme) | 17 (firme) ⚠️ (limiares — §15) |
| T10 | **Guardrail de bem-estar** | uso saudável (sessão, teto, pausa) é guardrail formal — a 17 **mede** a norma da Seção [13](13-acessibilidade.md) | 17 ⚠️ (limites/sessão — §15); norma = [13](13-acessibilidade.md) |
| T11 | **Ranking individual** | pode ser **calculado** internamente, **nunca** exposto à criança (P5) | 17 + [09](09-social.md)/[01](01-principios-imutaveis.md) |
| T12 | **Telemetria derivada** | `quest_habilidades` é **cache recalculável** — a **fórmula** do domínio (EMA α=0,3) é da Seção [06](06-pedagogico-bncc.md) §8k e a **persistência/recompute** é **mecanismo da Seção [11](11-arquitetura.md)**; a 17 **deriva/expõe** a métrica e opera seus próprios agregados analíticos | 17 (derivação); fórmula = [06](06-pedagogico-bncc.md); recompute = [11](11-arquitetura.md) |
| T13 | **Expurgo — respostas** | a coluna **`respostas`** (hoje inline em `quest_tentativas`) vai para um **store próprio expurgável**; as **colunas de resultado por jogada** permanecem no ledger (append-only, P14); o **prazo** é da Seção [12](12-seguranca-privacidade.md), o **cron** da Seção [14](14-infra-deploy-dr.md) O16 | 17 (lógica) ⚠️ (split — §15); prazo = [12](12-seguranca-privacidade.md) |
| T14 | **Erasure** | o resultado da exclusão do titular segue a Seção [12](12-seguranca-privacidade.md) §15 — **hoje cascade-delete** (nada sobrevive); **se** a 12 migrar para anonimização, o **agregado anônimo** é derivado **antes** do expurgo e mantido **fora do ledger** (nunca UPDATE nas linhas imutáveis — P14) | 17 executa; decisão = [12](12-seguranca-privacidade.md) ⚠️ |
| T15 | **Auditoria de acesso** | acesso de adulto a telemetria é **registrado** (reusa `logs_auditoria`) e restrito | 17 reusa [12](12-seguranca-privacidade.md) |
| T16 | **Alerta de métrica ≠ infra** | anomalia de **norte/guardrail** é alerta de **produto** (17), distinto do alerta de **recurso** (Seção [14](14-infra-deploy-dr.md)) | 17 / [14](14-infra-deploy-dr.md) |
| T17 | **Amostragem** | eventos de **alto volume** podem ser amostrados **sem** perder fidelidade dos KPIs-núcleo | 17 ⚠️ (política — §15) |

### 10. Arquitetura técnica
Onde a telemetria **toca** o código (o **mecanismo** é da Seção [11](11-arquitetura.md); o **catálogo executável** é
o Apêndice D):
- **Envelope & schema** — o contrato do evento (T5/T6) vive num **schema registry** versionado; o **Apêndice D** é
  o dicionário técnico (D.1–D.36: envelope comum, template de ficha, famílias de evento) derivado desta taxonomia.
- **Derivação no servidor** — eventos/agregações são computados a partir de `quest_tentativas` (imutável) e, quando
  existir, do `quest_outbox` (alvo Q4; schema = Seção [11](11-arquitetura.md)), **sem** depender do cliente (P13).
- **Store expurgável (T13)** — a coluna `respostas` se **separa** do ledger de jogadas num store **expurgável** (o
  split resolve a tensão da Seção [12](12-seguranca-privacidade.md): não dá para purgar inline sem editar a linha
  imutável — P14); as **colunas de resultado por jogada** (`acertos`, `tempo_seg`, `xp_ganho`, `estrelas`)
  permanecem no ledger; o **agendador** (Seção [14](14-infra-deploy-dr.md) O16) executa o expurgo no **prazo** da
  Seção [12](12-seguranca-privacidade.md).
- **Instrumentação cliente** — **suplementar**: fila IndexedDB, sync, dedup por `event_id` (T7); o cliente **não**
  é a fonte da verdade das métricas de jogo.
- **Reuso, não duplicação** — `logs_auditoria` continua **auditoria** (não vira bus de analytics); `observabilidade.py`
  continua **infra** (Seção [14](14-infra-deploy-dr.md)).

### 11. Dependências com outros módulos
**Consome / mede / executa:**
- **Seção [01](01-principios-imutaveis.md)** — P3/P5/P13/P14/P15/P18.
- **Seção [12](12-seguranca-privacidade.md)** — a **política** (prazo, base legal, consentimento, minimização,
  anonimização, **erasure**); a 17 **executa** a taxonomia + o expurgo **sob** ela.
- **Seção [14](14-infra-deploy-dr.md)** — o **agendador** (O16) do expurgo e a fronteira **infra × produto**.
- **Seções [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)** — as **mecânicas** e a **fórmula/mapeamento** BNCC que geram/rotulam os eventos.
- **Seção [11](11-arquitetura.md)** — o **ledger**, o `quest_outbox` e a autoridade do gabarito.
- **Seção [13](13-acessibilidade.md)** — a **norma** de bem-estar (a 17 mede as métricas de uso saudável — 13 §11).
- **Seção [09](09-social.md)** — o **ranking saudável**/P5.
- **Seção [08](08-onboarding-ftue.md)** — o **critério qualitativo** do funil (a 17 dá os **números**).
- **Seção [16](16-localizacao-i18n.md)** — `locale` como **propriedade** do envelope (nenhum texto de UI no payload).

**Alimenta:**
- **Apêndice D** — a **taxonomia** (a 17 é dona; o D é o dicionário executável).
- **Seção [10](10-professor-familia.md)** — os **agregados** que o painel do professor pode exibir.
- **Seção [05](05-sistemas-de-jogo.md)/[11](11-arquitetura.md)** — os **sinais anti-farm** que alimentam rate-limit/economia.

**O que quebra se mudar:** se a Seção [12](12-seguranca-privacidade.md) mudar o **prazo/erasure**, a 17 **reajusta**
o expurgo (T13/T14); se a Seção [06](06-pedagogico-bncc.md) mudar a **fórmula/BNCC**, a 17 **re-rotula/recomputa**;
se a Seção [11](11-arquitetura.md) criar o `quest_outbox`, a 17 **liga** a telemetria social.

### 12. Casos extremos (Edge Cases)
- **Evento inválido** (schema) → **dead-letter** (quarentena/descarte — ⚠️ §15), nunca corrompe o KPI.
- **Cliente offline** → fila IndexedDB; sync ao reconectar; **dedup** por `event_id`; `occurred_at` preservado.
- **Evento duplicado / late-arrival** → idempotente por `event_id`; ordenação por `occurred_at` (não `received_at`).
- **Exclusão do titular (LGPD)** → segue a **decisão da Seção [12](12-seguranca-privacidade.md) §15**: **hoje
  cascade-delete** (ledger + caches somem); **se** a 12 migrar para anonimização, o agregado anônimo é derivado
  antes e congelado **fora do ledger** (nunca UPDATE — T14).
- **Correção de dado** → recompute do agregado a partir do ledger (sem agregado órfão — T12).
- **Farm de XP / abuso** → sinal anti-farm alimenta rate-limit/economia (não pune na telemetria — §8).
- **Métrica pede expor ranking individual** → **proibido** à criança (P5); só interno/adulto agregado.
- **Alto volume** → amostragem sem perder os KPIs-núcleo (⚠️ §15).
- **Tentativa de reusar `logs_auditoria` como analytics** → **não**: auditoria é permanente (Seção [12](12-seguranca-privacidade.md)); telemetria é expurgável.
- **Experimento A/B com criança** → só se autorizado, com limites éticos/consentimento (⚠️ §15/17.28).

### 13. Escalabilidade futura
- **`quest_outbox`** (Q4) — liga a telemetria social (eventos de sala/corrida) ao pipeline derivado.
- **Novos eventos** — o schema registry versionado absorve novas famílias sem quebrar o histórico (T6).
- **Coortes e retenção** — D1/D7/D30 por coorte quando o volume permitir (⚠️ alvos — §15).
- **Data warehouse / BI interno** — sempre **próprio** (P18) e minimizado; carrega `escola_id` e **só agregados
  anonimizados** cruzam fronteiras de escola (P15) — **proibido** join cross-escola em nível individual.
- **Experimentação** — framework de A/B **só** sob a decisão ética do dono (⚠️ 17.28).

### 14. Checklist de implementação
**"Pronto quando" (liga ao Apêndice F):**
- [ ] **Zero SDK de terceiros** (P18); analytics 100% próprio (T1).
- [ ] **Envelope + schema registry** versionado; validação → dead-letter (T5/T6).
- [ ] **Telemetria derivada no servidor** do ledger imutável (P13); cliente **suplementar** com fila offline + dedup (T3/T7).
- [ ] **Agregados recomputáveis** do ledger (mecanismo da Seção [11](11-arquitetura.md)), **sem agregado órfão** após correção (T12); fórmula BNCC = Seção [06](06-pedagogico-bncc.md).
- [ ] **Envelope minimizado** (`perfil_id`+`escola_id`; **sem** PII/foto/localização/texto livre); **resposta bruta só** no store expurgável (T2/T4/T13).
- [ ] **Métrica-norte + guardrails** com **definição operacional** fechada (evento de retorno, janela, coorte, num/den) — hoje ⚠️ §15; alvos §15 (T8/T9/T10).
- [ ] **Store expurgável** das `respostas` separado do ledger de jogadas (T13); expurgo pelo agendador da Seção [14](14-infra-deploy-dr.md) no prazo da Seção [12](12-seguranca-privacidade.md).
- [ ] **Erasure** segue a decisão da Seção [12](12-seguranca-privacidade.md) §15 (hoje cascade-delete); anonimização, se adotada, **fora do ledger** (T14).
- [ ] **Nenhum ranking individual** exposto à criança (P5 — T11); acesso a telemetria **auditado** (T15).
- [ ] **Alertas de métrica** distintos dos alertas de infra (T16); **"conseguimos medir o norte"** (instrumentação mínima) satisfeito (17.30).
- [ ] **[quando adotada — §15]** política de **amostragem** de alto volume sem perder KPIs-núcleo (T17).

### 15. Questões em aberto
Cada item é **decisão do dono** (⚠️); os defaults são **propostas** da 17, não decisões autônomas:

- ⚠️ **17.2/17.6 — Definição do norte e alvos.** A norte é a **retenção** ("volta amanhã?"). Proposta de
  **definição operacional**: "**sessão iniciada em D+1**, dia-calendário no fuso da escola" (confirmar o evento de
  retorno, a janela, a coorte e o num/den). Confirmar os **alvos** D1/D7/D30 por coorte (base da régua de corte de
  fase — Seção [08](08-onboarding-ftue.md) delega os números à 17).
- ⚠️ **17.3 — Limiares dos guardrails de aprendizado.** Os **limiares** de domínio BNCC que, se violados,
  **invalidam** um ganho de retenção. *(A **precedência** do guardrail sobre o engajamento já é firme — §3/T9/ADR-17-C;
  aqui só os limiares.)*
- ⚠️ **17.4 / T10 — Guardrails de bem-estar + definição de sessão.** Os **limites** de uso saudável (duração
  máxima, teto diário, gatilho de pausa) tratados como guardrail formal — a **norma** é da Seção [13](13-acessibilidade.md),
  os **valores** de 05/19. E a **definição operacional de sessão** (janela de inatividade que fecha a sessão; como o
  `sessao_id` é cunhado e preservado no sync offline) — hoje indefinida.
- ⚠️ **17.21 / T13 — Retenção e anonimização.** Confirmar o **prazo** de retenção da telemetria detalhada (**valor
  de posse da Seção [12](12-seguranca-privacidade.md) §15** — a 17 não o fixa) e o **gatilho** de anonimização na
  saída do aluno. **Erasure = decisão da Seção [12](12-seguranca-privacidade.md) §15** (hoje cascade-delete).
- ⚠️ **T13 — Split do store.** Confirmar **separar** a coluna `respostas` num store próprio expurgável (proposta)
  vs. mantê-la inline e expurgar por UPDATE (que atrita com a imutabilidade do ledger — P14).
- ⚠️ **T14 — Desenho do agregado anônimo.** *Se* a Seção [12](12-seguranca-privacidade.md) migrar para
  anonimização: qual **granularidade** sobrevive, sob qual **chave de coorte anônima**, computada **antes** do
  expurgo e congelada fora do ledger.
- ⚠️ **17.28 / D.35 — Experimentos A/B com crianças.** É permitido? Sob quais **limites éticos e de consentimento**?
- ⚠️ **Dead-letter & minimização.** Destino dos eventos rejeitados (descartar × quarentenar; quem revisa). A 17
  **propõe** coletar `app_version` + **classe** de device (não o modelo exato) como propriedade de evento; o
  **veredito** de minimização/P3 é da Seção [12](12-seguranca-privacidade.md) §15. Amostragem de alto volume
  autorizada (T17)?
- ⚠️ **KPIs-núcleo & Apêndice D (Q1).** Confirmar a **lista-proposta** de KPIs-núcleo — retenção D1/D7/D30, taxa de
  conclusão de missão, cobertura de domínio BNCC, taxa de **sessão saudável** — e a **lista fechada** de eventos-núcleo
  (login, início/fim de missão, tentativa, loja/equipar, cerimônia/FTUE, sociais) + o **esquema** de cada um (hoje só propostos).

### 16. ADR (Architecture Decision Record)
- **ADR-17-A — Analytics próprio, mínimo, derivado no servidor.** Sem SDK de terceiros (P18); a telemetria de jogo
  é **derivada do ledger imutável** (P13/P14); o cliente é suplementar (fila offline + dedup). Coleta mínima no
  envelope (P3), pseudônima (`perfil_id`+`escola_id`, P15).
- **ADR-17-B — Respostas detalhadas num store expurgável; erasure segue a 12.** A coluna `respostas` (hoje inline
  em `quest_tentativas`) se **separa** num store **expurgável**, mantendo as colunas de resultado por jogada no
  ledger **append-only** (P14); o **expurgo por prazo** roda pelo agendador da Seção [14](14-infra-deploy-dr.md) O16.
  A **erasure** segue a decisão da Seção [12](12-seguranca-privacidade.md) §15 (**hoje cascade-delete**); qualquer
  anonimização é feita **fora do ledger**, nunca por UPDATE. *Split e desenho do agregado anônimo pendentes (§15).*
- **ADR-17-C — Engajamento é subordinado a guardrails.** A **métrica-norte** (retenção) **nunca** vale contra os
  **guardrails** de aprendizado (BNCC) e de **bem-estar** (norma da Seção [13](13-acessibilidade.md)); o **ranking
  individual** é interno e **nunca** exposto à criança (P5). *Limiares/alvos pendentes (§15).*
- **ADR-17-D — A 17 é dona da taxonomia; o Apêndice D a executa.** A taxonomia de eventos (nomes, esquema, envelope,
  versionamento) é decidida aqui; o **Apêndice D** é o dicionário técnico executável derivado; `logs_auditoria`
  (auditoria) e `observabilidade.py` (infra) **não** são reusados como bus de analytics; a **fórmula** do domínio
  BNCC é da Seção [06](06-pedagogico-bncc.md).

*Decisões cross-módulo não são improvisadas aqui: as pendências acima viram ADR ou item de §15.*

---

## 🇬🇧 Telemetry, Metrics & Analytics

### 1. Objective
To be the **definitive telemetry and metrics reference** for Constela Quest: **how we know whether the product
teaches, delights and is healthy** — with **first-party, minimal, purposeful analytics** (P18/P3), never selling
nor leaking a child's data. It defines the **event taxonomy** and the **metrics framework** (north star +
guardrails + KPIs — the proposed enumeration is in §15, the targets are ⚠️) and the **purge logic**. It
**executes** Section [12](12-seguranca-privacidade.md)'s LGPD **policy**, uses Section [14](14-infra-deploy-dr.md)'s
**scheduler** and **measures** the mechanics of Sections [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md);
it does **not** create policy, cron, mechanics, the BNCC formula nor infra metrics — and **never** exposes an
individual ranking to the child (P5).

### 2. Context
In the **Hub → Edu → Quest** ecosystem, measuring a **minor's data** is an act of responsibility: what is
collected is the **minimum** to improve learning and well-being, **never** for ads or resale. **Current state
(Q0) — product-analytics greenfield:**
- **No product analytics** — **zero** third-party SDK (mixpanel/amplitude/GA/posthog/segment…) in code or
  `package.json` (confirms **P18**); **no** taxonomy/event-emit layer; **no** computed KPI/north-star.
- **Existing raw material** — the immutable **play ledger** `quest_tentativas` (what Section [12](12-seguranca-privacidade.md) calls the "aggregate ledger" is this same play ledger; per play: `escola_id`, `perfil_id`,
  `missao_id`, correct answers, `tempo_seg`, `xp_ganho`, `estrelas`, `origem`, and the JSON column **`respostas`**
  = `{desafio_id, correta, resposta, tempo_ms, dicas, tentativas}` — the **purgeable artifact** split by Section
  [12](12-seguranca-privacidade.md); note `resposta` holds the child's **raw answer**); the **recalculable caches**
  `quest_progresso` (best star/mission) and `quest_habilidades` (BNCC domain 0–100, **Section [06](06-pedagogico-bncc.md) §8k's
  formula**); `quest_perfis` (`xp_total`, `sequencia_dias`/`escudo_sequencia` = the **Cosmo's Flame**, a healthy-use signal).
- **Erasure today = cascade-delete** — on the **student's deletion**, all telemetry (ledger + caches) is
  **cascade-deleted** (`progresso.py` docstring; `perfil_id` **ON DELETE CASCADE** → `quest_perfis` → `alunos`), for
  LGPD. **Nothing** survives today; migrating to anonymization is an **open decision of Section [12](12-seguranca-privacidade.md) §15**.
- **Audit ≠ telemetry** — `logs_auditoria` (`LogAuditoria`) is the **permanent accountability trail** (Section
  [12](12-seguranca-privacidade.md)'s/[11](11-arquitetura.md)'s), **not** a product-analytics bus.
- **Infra observability ≠ product** — `observabilidade.py` (Prometheus RED, Sentry `send_default_pii=False`,
  `/metrics`) measures **system health** (Section [14](14-infra-deploy-dr.md)), not in-game behavior.
- **Not yet present** — the telemetry **write path** (nothing in prod writes the ledger; only a test), the
  **purge** (`respostas` live inline, no purgeable store, no scheduler), the **`quest_outbox`** (Q4 target) and any
  metrics **dashboard**.

This chapter **specifies** the taxonomy, the metrics framework and the purge logic **from scratch**, anchored to
what already exists.

### 3. Feature philosophy
**"Measure to serve the child — not to exploit them."** Constela's telemetry is **first-party** (no third parties
— P18), **minimal** (only what has a pedagogical/product purpose — P3) and **honest** (the **server** is the source
of truth — P13; the ledger is **auditable** — P14). The moral rule that organizes everything: **every engagement
metric is subordinate to a learning and a well-being guardrail** — we never optimize "the child comes back
tomorrow" at the expense of them **learning** and **using it healthily**. And the **individual ranking never**
reaches the child (P5): an internal metric ≠ exposure.

Link to the **Immutable Principles** ([01](01-principios-imutaveis.md)): **P18** (first-party analytics) and **P3**
(minimal collection) found this section; **P13** makes **server-derived** telemetry the authority; **P14** makes
the ledger the immutable source; **P15** isolates each event by `escola_id`; **P5** forbids exposing the individual
ranking. To the **4 pillars**: it measures **surprise**, **visible progress**, **connection** (without exposure)
and **autonomy** — to improve them, never to manipulate.

### 4. The experience the player should feel
**The child does not feel the telemetry** — they see no cold numbers, are not labeled, are not publicly ranked.
What they feel is the **effect** of a product that **learns from them**: difficulty that adjusts, a world that
improves, a Cosmo that welcomes them. **The adult** (teacher/family) gets an **honest overview** of learning
(BNCC map, common errors) — **without** coins/store, **without** the child's individual ranking. **The team** sees
whether the product teaches and delights **without** betraying the trust of whoever entrusted their child/student.

### 5. Complete flow
The **lifecycle of a datum**, from play to purge:

1. **Generates** — the child plays; the mechanic (Sections [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md))
   produces a result the **server** writes to the immutable **play ledger** `quest_tentativas` (P13/P14).
2. **Emits** — product events (standard envelope) are **server-derived** from the immutable ledger (P13) — and,
   **once the `quest_outbox` exists** (Q4 target, Section [11](11-arquitetura.md)), also from social telemetry;
   **client** instrumentation is **supplementary**, with an **offline queue** (IndexedDB) and **sync** on reconnect
   (dedup by `event_id`, `origem` web|pwa-offline).
3. **Validates** — the **schema registry** (single client↔server source) validates the event; invalid → **dead-letter**.
4. **Aggregates** — the **caches** (`quest_habilidades`) are recomputed from the ledger — no orphan aggregate after
   a correction; the domain **formula** (exponential moving average, α=0.3) is Section [06](06-pedagogico-bncc.md) §8k's
   and the cache **persistence/recompute** is **Section [11](11-arquitetura.md)'s mechanism**; 17 **derives and exposes**
   the metric and operates its **own analytical aggregates** (**cron** = Section [14](14-infra-deploy-dr.md)'s O16).
5. **Measures** — KPIs (north/guardrails/funnels) feed **internal dashboards**; curated **aggregates** go to the
   **teacher panel** (UI = Section [10](10-professor-familia.md)), **without** coins/store/individual ranking (P5).
6. **Minimizes** — the event **envelope** never carries **PII/photo/location/free text** (P3); identity is
   **pseudonymous** (`perfil_id`+`escola_id`); the child's **raw answer** lives **only** in the purgeable store (§9/T13).
7. **Purges / anonymizes** — at Section [12](12-seguranca-privacidade.md)'s **deadline**, the scheduler (Section
   [14](14-infra-deploy-dr.md)'s O16) **purges** the **detailed answers** (purgeable store — §9), preserving the
   per-play result columns (append-only, P14). On the **student's deletion (erasure)**, the outcome follows
   **Section [12](12-seguranca-privacidade.md) §15's decision**: **today it is cascade-delete** (everything goes);
   **if** 12 migrates to anonymization, the **anonymous aggregate** is derived **before** the purge, frozen and kept
   **off-ledger** (never by UPDATE on the immutable rows — §9/T14).

### 6. Interface (when it exists)
Section 17 **draws no child screens** (N/A). **Data** surfaces (not children's):
- **Internal product dashboards** — north, guardrails, funnels; source = the derived aggregates.
- **Metrics exposed to the teacher** (Edu) — overview/BNCC map/common errors; 17 **delimits which aggregates** are
  available, the panel **UI** is Section [10](10-professor-familia.md)'s (never coins/store/individual ranking).
- **Metric-anomaly alerts** — north/guardrail out of band (distinct from the **resource/infra alerts** of Section [14](14-infra-deploy-dr.md)).

### 7. UX
The "data UX" is for **adults and the team** (the child never sees telemetry):
- **Honesty** — the teacher panel shows **learning**, not vanity; nothing that exposes the child.
- **Legibility** — clear aggregates (BNCC map, common errors), in the adult's vocabulary.
- **Privacy by default** — no new sensitive data in the envelope; pseudonymous identity; adult access **audited** (reuses `logs_auditoria`).

### 8. Game Design
**N/A as a mechanic** — 17 **measures** the game, does not create it. Boundary note: the **anti-farm/anti-abuse
signals** (XP farming, login abuse) 17 computes **feed** the rate-limit and the **auditable economy** (mechanism =
Sections [05](05-sistemas-de-jogo.md)/[11](11-arquitetura.md)); 17 detects, it does not punish.

### 9. Business rules
The **telemetry norms** (the single source of taxonomy and logic; the **policy** is Section [12](12-seguranca-privacidade.md)'s,
the **cron** Section [14](14-infra-deploy-dr.md)'s, the **mechanics/formula** Sections [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)'s):

| # | Norm | Rule | Boundary |
|---|------|------|----------|
| T1 | **First-party analytics** | **no third-party SDK** (P18); no child's data leaves to an external ad/analytics processor | 17 + [01](01-principios-imutaveis.md) |
| T2 | **Minimal collection** | the event **envelope** never carries **photo/location/free text/direct PII** (P3); only what has a **purpose**; the child's **raw answer** lives **only** in the purgeable store (T13) | 17; minimization **verdict** = [12](12-seguranca-privacidade.md) |
| T3 | **Server is the source** | game telemetry is **server-derived** from the immutable ledger (P13/P14); the client is **supplementary** | 17; mechanism = [11](11-arquitetura.md) |
| T4 | **Pseudonymization** | identity = `perfil_id` + `escola_id` (P15 isolation); **never** name/PII in the event | 17; policy = [12](12-seguranca-privacidade.md) |
| T5 | **Event envelope** | `event_name` (`noun.verb`, **internal** vocabulary), `event_version`, `event_id` (UUID, dedup), `occurred_at`/`received_at`, `perfil_id`, `escola_id`, `sessao_id` (session definition ⚠️ §15), `origem`, `locale` | 17 (taxonomy → Appendix D) |
| T6 | **Schema & versioning** | a **schema registry** as the single client↔server source; **versioned** change (don't break historical analysis); invalid → **dead-letter** | 17 (→ Appendix D) |
| T7 | **Offline/sync** | append-only **IndexedDB** queue; sync on reconnect; **dedup by `event_id`**; `occurred_at` preserved on late arrival; `origem` flag | 17; transport = [11](11-arquitetura.md) |
| T8 | **North-star metric** | "does the child come back tomorrow?" (retention); proposed **operational definition**: a session started on D+1 (calendar day in the school's timezone) | 17 ⚠️ (definition + target — §15) |
| T9 | **Guardrail precedes engagement** | no retention gain counts if it **violates** learning (BNCC) or **well-being**; the guardrail **precedes** engagement (moral core, firm) | 17 (firm) ⚠️ (thresholds — §15) |
| T10 | **Well-being guardrail** | healthy use (session, cap, pause) is a formal guardrail — 17 **measures** Section [13](13-acessibilidade.md)'s norm | 17 ⚠️ (limits/session — §15); norm = [13](13-acessibilidade.md) |
| T11 | **Individual ranking** | may be **computed** internally, **never** exposed to the child (P5) | 17 + [09](09-social.md)/[01](01-principios-imutaveis.md) |
| T12 | **Derived telemetry** | `quest_habilidades` is a **recalculable cache** — the domain **formula** (EMA α=0.3) is Section [06](06-pedagogico-bncc.md) §8k's and the **persistence/recompute** is **Section [11](11-arquitetura.md)'s mechanism**; 17 **derives/exposes** the metric and operates its own analytical aggregates | 17 (derivation); formula = [06](06-pedagogico-bncc.md); recompute = [11](11-arquitetura.md) |
| T13 | **Purge — answers** | the **`respostas`** column (today inline in `quest_tentativas`) goes to an **own purgeable store**; the **per-play result columns** stay in the ledger (append-only, P14); the **deadline** is Section [12](12-seguranca-privacidade.md)'s, the **cron** Section [14](14-infra-deploy-dr.md)'s O16 | 17 (logic) ⚠️ (split — §15); deadline = [12](12-seguranca-privacidade.md) |
| T14 | **Erasure** | the deletion outcome follows Section [12](12-seguranca-privacidade.md) §15 — **today cascade-delete** (nothing survives); **if** 12 migrates to anonymization, the **anonymous aggregate** is derived **before** the purge and kept **off-ledger** (never UPDATE on the immutable rows — P14) | 17 executes; decision = [12](12-seguranca-privacidade.md) ⚠️ |
| T15 | **Access audit** | adult access to telemetry is **logged** (reuses `logs_auditoria`) and restricted | 17 reuses [12](12-seguranca-privacidade.md) |
| T16 | **Metric alert ≠ infra** | a **north/guardrail** anomaly is a **product** alert (17), distinct from a **resource** alert (Section [14](14-infra-deploy-dr.md)) | 17 / [14](14-infra-deploy-dr.md) |
| T17 | **Sampling** | **high-volume** events may be sampled **without** losing core-KPI fidelity | 17 ⚠️ (policy — §15) |

### 10. Technical architecture
Where telemetry **touches** code (the **mechanism** is Section [11](11-arquitetura.md)'s; the **executable catalog**
is Appendix D):
- **Envelope & schema** — the event contract (T5/T6) lives in a versioned **schema registry**; **Appendix D** is
  the technical dictionary (D.1–D.36: common envelope, sheet template, event families) derived from this taxonomy.
- **Server derivation** — events/aggregations are computed from `quest_tentativas` (immutable) and, once it exists,
  the `quest_outbox` (Q4 target; schema = Section [11](11-arquitetura.md)), **without** depending on the client (P13).
- **Purgeable store (T13)** — the `respostas` column is **split** from the play ledger into a **purgeable** store
  (the split resolves Section [12](12-seguranca-privacidade.md)'s tension: you cannot purge inline without editing
  the immutable row — P14); the **per-play result columns** (`acertos`, `tempo_seg`, `xp_ganho`, `estrelas`) stay in
  the ledger; the **scheduler** (Section [14](14-infra-deploy-dr.md)'s O16) runs the purge at Section
  [12](12-seguranca-privacidade.md)'s **deadline**.
- **Client instrumentation** — **supplementary**: IndexedDB queue, sync, dedup by `event_id` (T7); the client is
  **not** the source of truth for game metrics.
- **Reuse, not duplication** — `logs_auditoria` stays **audit** (not an analytics bus); `observabilidade.py` stays
  **infra** (Section [14](14-infra-deploy-dr.md)).

### 11. Dependencies on other modules
**Consumes / measures / executes:**
- **Section [01](01-principios-imutaveis.md)** — P3/P5/P13/P14/P15/P18.
- **Section [12](12-seguranca-privacidade.md)** — the **policy** (deadline, legal basis, consent, minimization,
  anonymization, **erasure**); 17 **executes** the taxonomy + purge **under** it.
- **Section [14](14-infra-deploy-dr.md)** — the purge **scheduler** (O16) and the **infra × product** boundary.
- **Sections [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)** — the **mechanics** and the BNCC **formula/mapping** that generate/label the events.
- **Section [11](11-arquitetura.md)** — the **ledger**, the `quest_outbox` and the answer-key authority.
- **Section [13](13-acessibilidade.md)** — the well-being **norm** (17 measures the healthy-use metrics — 13 §11).
- **Section [09](09-social.md)** — the **healthy ranking**/P5.
- **Section [08](08-onboarding-ftue.md)** — the funnel's **qualitative criterion** (17 provides the **numbers**).
- **Section [16](16-localizacao-i18n.md)** — `locale` as an event **property** (no UI text in the payload).

**Feeds:**
- **Appendix D** — the **taxonomy** (17 owns it; D is the executable dictionary).
- **Section [10](10-professor-familia.md)** — the **aggregates** the teacher panel may display.
- **Sections [05](05-sistemas-de-jogo.md)/[11](11-arquitetura.md)** — the **anti-farm signals** feeding rate-limit/economy.

**What breaks if it changes:** if Section [12](12-seguranca-privacidade.md) changes the **deadline/erasure**, 17
**re-tunes** the purge (T13/T14); if Section [06](06-pedagogico-bncc.md) changes the **formula/BNCC**, 17
**re-labels/recomputes**; if Section [11](11-arquitetura.md) creates the `quest_outbox`, 17 **wires** the social telemetry.

### 12. Edge cases
- **Invalid event** (schema) → **dead-letter** (quarantine/discard — ⚠️ §15), never corrupts the KPI.
- **Offline client** → IndexedDB queue; sync on reconnect; **dedup** by `event_id`; `occurred_at` preserved.
- **Duplicate / late-arrival event** → idempotent by `event_id`; ordered by `occurred_at` (not `received_at`).
- **Data-subject erasure (LGPD)** → follows **Section [12](12-seguranca-privacidade.md) §15's decision**: **today
  cascade-delete** (ledger + caches go); **if** 12 migrates to anonymization, the anonymous aggregate is derived
  before and frozen **off-ledger** (never UPDATE — T14).
- **Data correction** → recompute the aggregate from the ledger (no orphan aggregate — T12).
- **XP farming / abuse** → an anti-farm signal feeds rate-limit/economy (does not punish in telemetry — §8).
- **A metric asks to expose an individual ranking** → **forbidden** to the child (P5); internal/adult aggregate only.
- **High volume** → sampling without losing core KPIs (⚠️ §15).
- **Attempt to reuse `logs_auditoria` as analytics** → **no**: audit is permanent (Section [12](12-seguranca-privacidade.md)); telemetry is purgeable.
- **A/B experiment with a child** → only if authorized, with ethical/consent limits (⚠️ §15/17.28).

### 13. Future scalability
- **`quest_outbox`** (Q4) — wires social telemetry (room/race events) to the derived pipeline.
- **New events** — the versioned schema registry absorbs new families without breaking history (T6).
- **Cohorts and retention** — D1/D7/D30 per cohort once volume allows (⚠️ targets — §15).
- **Data warehouse / internal BI** — always **first-party** (P18) and minimized; it carries `escola_id` and **only
  anonymized aggregates** cross school boundaries (P15) — **forbidden** cross-school individual join.
- **Experimentation** — an A/B framework **only** under the owner's ethical decision (⚠️ 17.28).

### 14. Implementation checklist
**"Done when" (links to Appendix F):**
- [ ] **Zero third-party SDK** (P18); 100% first-party analytics (T1).
- [ ] **Envelope + versioned schema registry**; validation → dead-letter (T5/T6).
- [ ] **Server-derived telemetry** from the immutable ledger (P13); **supplementary** client with offline queue + dedup (T3/T7).
- [ ] **Recomputable aggregates** from the ledger (Section [11](11-arquitetura.md)'s mechanism), **no orphan aggregate** after a correction (T12); BNCC formula = Section [06](06-pedagogico-bncc.md).
- [ ] **Minimized envelope** (`perfil_id`+`escola_id`; **no** PII/photo/location/free text); **raw answer only** in the purgeable store (T2/T4/T13).
- [ ] **North-star + guardrails** with a closed **operational definition** (return event, window, cohort, num/den) — today ⚠️ §15; targets §15 (T8/T9/T10).
- [ ] **Purgeable store** for `respostas` split from the play ledger (T13); purge by Section [14](14-infra-deploy-dr.md)'s scheduler at Section [12](12-seguranca-privacidade.md)'s deadline.
- [ ] **Erasure** follows Section [12](12-seguranca-privacidade.md) §15's decision (today cascade-delete); anonymization, if adopted, **off-ledger** (T14).
- [ ] **No individual ranking** exposed to the child (P5 — T11); telemetry access **audited** (T15).
- [ ] **Metric alerts** distinct from infra alerts (T16); **"we can measure the north"** (minimal instrumentation) satisfied (17.30).
- [ ] **[once adopted — §15]** high-volume **sampling** policy without losing core KPIs (T17).

### 15. Open questions
Each item is a **owner decision** (⚠️); the defaults are 17's **proposals**, not autonomous decisions:

- ⚠️ **17.2/17.6 — North-star definition and targets.** The north is **retention** ("comes back tomorrow?").
  Proposed **operational definition**: "**a session started on D+1**, calendar day in the school's timezone"
  (confirm the return event, window, cohort and num/den). Confirm the D1/D7/D30 **targets** per cohort (basis of
  the phase-cut ruler — Section [08](08-onboarding-ftue.md) delegates the numbers to 17).
- ⚠️ **17.3 — Learning-guardrail thresholds.** The BNCC-domain **thresholds** that, if violated, **invalidate** a
  retention gain. *(The guardrail's **precedence** over engagement is already firm — §3/T9/ADR-17-C; only the
  thresholds here.)*
- ⚠️ **17.4 / T10 — Well-being guardrails + session definition.** The healthy-use **limits** (max duration, daily
  cap, pause trigger) treated as a formal guardrail — the **norm** is Section [13](13-acessibilidade.md)'s, the
  **values** 05/19's. And the **operational session definition** (inactivity window that closes the session; how
  `sessao_id` is minted and preserved on offline sync) — today undefined.
- ⚠️ **17.21 / T13 — Retention and anonymization.** Confirm the detailed-telemetry **retention deadline** (**owned
  by Section [12](12-seguranca-privacidade.md) §15** — 17 does not set it) and the anonymization **trigger** on the
  student's departure. **Erasure = Section [12](12-seguranca-privacidade.md) §15's decision** (today cascade-delete).
- ⚠️ **T13 — Store split.** Confirm **splitting** the `respostas` column into an own purgeable store (proposal) vs.
  keeping it inline and purging by UPDATE (which conflicts with the ledger's immutability — P14).
- ⚠️ **T14 — Anonymous-aggregate design.** *If* Section [12](12-seguranca-privacidade.md) migrates to anonymization:
  which **granularity** survives, under which **anonymous cohort key**, computed **before** the purge and frozen off-ledger.
- ⚠️ **17.28 / D.35 — A/B experiments with children.** Is it allowed? Under what **ethical and consent limits**?
- ⚠️ **Dead-letter & minimization.** Destination of rejected events (discard × quarantine; who reviews). 17
  **proposes** collecting `app_version` + device **class** (not the exact model) as an event property; the
  minimization/P3 **verdict** is Section [12](12-seguranca-privacidade.md) §15's. Is high-volume sampling authorized (T17)?
- ⚠️ **Core KPIs & Appendix D (Q1).** Confirm the **proposed** core-KPI list — retention D1/D7/D30, mission
  completion rate, BNCC domain coverage, **healthy-session** rate — and the **closed list** of core events (login,
  mission start/end, attempt, store/equip, ceremony/FTUE, social) + each one's **schema** (today only proposed).

### 16. ADR (Architecture Decision Record)
- **ADR-17-A — First-party, minimal, server-derived analytics.** No third-party SDK (P18); game telemetry is
  **derived from the immutable ledger** (P13/P14); the client is supplementary (offline queue + dedup). Minimal
  envelope collection (P3), pseudonymous (`perfil_id`+`escola_id`, P15).
- **ADR-17-B — Detailed answers in a purgeable store; erasure follows 12.** The `respostas` column (today inline in
  `quest_tentativas`) is **split** into a **purgeable** store, keeping the per-play result columns in the ledger
  **append-only** (P14); the **deadline purge** runs via Section [14](14-infra-deploy-dr.md)'s O16 scheduler. The
  **erasure** follows Section [12](12-seguranca-privacidade.md) §15's decision (**today cascade-delete**); any
  anonymization is done **off-ledger**, never by UPDATE. *Split and anonymous-aggregate design pending (§15).*
- **ADR-17-C — Engagement is subordinate to guardrails.** The **north-star** (retention) **never** counts against
  the **learning** (BNCC) and **well-being** (Section [13](13-acessibilidade.md)'s norm) **guardrails**; the
  **individual ranking** is internal and **never** exposed to the child (P5). *Thresholds/targets pending (§15).*
- **ADR-17-D — 17 owns the taxonomy; Appendix D executes it.** The event taxonomy (names, schema, envelope,
  versioning) is decided here; **Appendix D** is the derived executable technical dictionary; `logs_auditoria`
  (audit) and `observabilidade.py` (infra) are **not** reused as an analytics bus; the BNCC domain **formula** is
  Section [06](06-pedagogico-bncc.md)'s.

*Cross-module decisions are not improvised here: the pending items above become an ADR or a §15 entry.*
