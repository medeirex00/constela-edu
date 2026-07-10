# Apêndice F — Checklists Consolidados (Definition of Done) / Consolidated Checklists

- **Status:** 🟢 aprovado / approved
- **Tipo:** documento de **referência** (não segue o padrão de 16 partes do [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md), que vale só para capítulos).
- **Fontes / Sources:** a **Parte 14** ("Checklist de implementação") de **cada** seção aprovada; o gate de QA do **[Portão 3](24-governanca.md)** com os **7 eixos** da [Seção 24.16](24-governanca.md); o DoD de QA por tipo de mudança da [Seção 18](18-qa-testes.md); o DoD por fase (Q0–Q6) da [Seção 23](23-roadmap.md).
- **Depende de:** cada critério **pertence à sua seção-dona**; o F **agrega e remete**, **não cria critério novo** (norma [G7](24-governanca.md)).

> **Como o F se posiciona:** reúne num só lugar, como listas acionáveis, os critérios de **PRONTO** já definidos
> nas seções-donas — para toda entrega ser verificada de forma **objetiva e repetível no Portão 3**, **sem recriar
> critério**. Cada item aponta a **seção-fonte**; nenhum critério órfão. Item novo entra via spec/ADR sincronizado
> com a seção-dona ([F.31](#f31-governança-dos-checklists)).

---

## 🇧🇷 Checklists Consolidados (DoD)

### F.1 Como usar os checklists

O apêndice é a **fonte consolidada** do "Pronto quando". É **obrigatório no [Portão 3](24-governanca.md)** (implementação fiel → revisão → atualização da Bible). Ele **não cria critério novo**: cada item **remete** à seção-dona, que tem a autoridade sobre a regra ([G10](24-governanca.md)).

### F.2 Anatomia de um item

Todo item segue o formato fixo: **afirmação verificável** `[ ]` + **evidência exigida** + **seção-fonte** (`NN.x`) + **severidade** — 🔴 **bloqueante** (trava o Portão 3) ou 🟡 **recomendado**. Itens ⚠️ marcam pendência do dono (número/limiar não fixado).

### F.3 DoD por TELA

- [ ] Todos os **estados** cobertos: vazio, carregando (*skeleton*), erro de rede, offline, sucesso, sem-licença — 🔴 · fonte [07§12](07-ux-fluxos-navegacao.md)/[E.6](apendice-E-wireframes.md).
- [ ] **Áudio/narração** de entrada e "ouvir de novo" em toda instrução — 🔴 · fonte [13](13-acessibilidade.md).
- [ ] **Navegação** sem beco: volta garantida à Tela-casa — 🔴 · fonte [07§5](07-ux-fluxos-navegacao.md).
- [ ] **Uma ação primária** por tela — 🟡 · fonte [07§6](07-ux-fluxos-navegacao.md).
- [ ] **Cópia canônica** (vocabulário infantil; sem palavra proibida) — 🔴 · fonte [02](02-vocabulario.md).
- [ ] **Telemetria** disparada = o evento correto — 🟡 · fonte [Apêndice D](apendice-D-eventos-telemetria.md)/[E.38](apendice-E-wireframes.md).

### F.4 DoD por FEATURE / SISTEMA

- [ ] **Spec 🟢 aprovada** antes de implementar (Regra de ouro) — 🔴 · fonte [24](24-governanca.md).
- [ ] **Testes** na pirâmide + gate de cobertura — 🔴 · fonte [18](18-qa-testes.md).
- [ ] **Regras numéricas não-hardcoded** (namespace `quest.*`) — 🔴 · fonte [19](19-liveops.md)/[B.24](apendice-B-api-dados.md).
- [ ] **Autoridade do servidor** (gabarito/recompensa server-side) — 🔴 · fonte [11](11-arquitetura.md)/P13.
- [ ] **Auditoria** dos acessos adultos sensíveis — 🔴 · fonte [12](12-seguranca-privacidade.md).

### F.5 DoD por MECÂNICA de jogo

- [ ] Contrato **`MecanicaProps`** respeitado (plugin/registry) — 🔴 · fonte [05](05-sistemas-de-jogo.md)/[11](11-arquitetura.md).
- [ ] **Gabarito no servidor**, nunca no cliente — 🔴 · fonte P13/[B.15](apendice-B-api-dados.md).
- [ ] **Schema de conteúdo** válido (⚠️ formato por mecânica pende — [B.23](apendice-B-api-dados.md)) — 🟡.
- [ ] **Acessibilidade** touch-first (alvos ≥48px, áudio) — 🔴 · fonte [13](13-acessibilidade.md).

### F.6 DoD por ENDPOINT / contrato de API

- [ ] **Papéis checados** no backend — 🔴 · fonte [12](12-seguranca-privacidade.md)/[B.1](apendice-B-api-dados.md).
- [ ] **Isolamento por `escola_id`** (P15) — 🔴 · fonte [11](11-arquitetura.md)/[12](12-seguranca-privacidade.md).
- [ ] **Erros padronizados** (401/403/404/422/429) — 🔴 · fonte [B.26](apendice-B-api-dados.md).
- [ ] **ETag/versão** onde aplicável — 🟡 · fonte [B.25](apendice-B-api-dados.md).
- [ ] **Gabarito nunca no cliente** — 🔴 · fonte [B.15](apendice-B-api-dados.md)/P13.
- [ ] Contrato **espelha o código** (DDL/rota reais) — 🔴 · fonte [Apêndice B](apendice-B-api-dados.md).

### F.7 DoD por CONTEÚDO pedagógico

- [ ] **Código BNCC** amarrado — 🔴 · fonte [06](06-pedagogico-bncc.md).
- [ ] **Áudio** de enunciado/dica/explicação — 🔴 · fonte [13](13-acessibilidade.md)/[15](15-arte-audio-assets.md).
- [ ] **Revisão humana** (curadoria; ERER sem IA) — 🔴 · fonte [03](03-universo.md)/[06](06-pedagogico-bncc.md).
- [ ] **Versão publicada** (`quest_missoes.versao`) — 🔴 · fonte [B.15](apendice-B-api-dados.md)/[B.25](apendice-B-api-dados.md).

### F.8 Gate de revisão de QA (Portão 3) — os 7 eixos

Visão consolidada e acionável dos **sete eixos** da [Seção 24.16](24-governanca.md) (F.9–F.15). A **estratégia de testes** por trás deles é da [Seção 18](18-qa-testes.md); o F **torna acionável**, não redefine.

### F.9 Eixo — Bugs e correção

- [ ] Sem regressão; severidade classificada; peso extra ao que afeta a **criança não-leitora** — 🔴 · fonte [24.16](24-governanca.md)/[18](18-qa-testes.md).

### F.10 ⚠️ Eixo — Performance no device-alvo

- [ ] Orçamento de carga/memória e fluidez no **hardware mínimo** — 🔴 · fonte [11](11-arquitetura.md). **⚠️ os números pendem do dono** (device-alvo/orçamento; ADR C.25).

### F.11 Eixo — UX e fluxo

- [ ] **1 ação primária** por tela; convite (não ordem); erro **sempre acolhido**; **sem dark patterns** — 🔴 · fonte [07](07-ux-fluxos-navegacao.md)/[08](08-onboarding-ftue.md)/P6/P8.

### F.12 Eixo — Acessibilidade

- [ ] **Áudio** em toda instrução; alvos **≥48px**; contraste; ordem de foco; `reduced-motion`; modo daltônico; **tempo nunca como critério único** — 🔴 · fonte [13](13-acessibilidade.md).

### F.13 Eixo — Responsividade

- [ ] Breakpoints-alvo (tablet retrato/paisagem, Chromebook, telefone); **sem overflow horizontal** — 🔴 · fonte [07](07-ux-fluxos-navegacao.md)/[E.8](apendice-E-wireframes.md).

### F.14 Eixo — Escalabilidade

- [ ] Pico de aula (metade das turmas às **7h30**); índices por `escola_id`; rate-limit; gatilhos de Redis/réplicas — 🔴 · fonte [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md).

### F.15 Eixo — Organização e qualidade de código

- [ ] Padrões do monorepo; tipos de `@constela/quest-core`; **sem regra numérica hardcoded** — 🟡 · fonte [11](11-arquitetura.md)/[24](24-governanca.md).

### F.16 Checklist — LGPD

- [ ] Coleta mínima; opt-in social; retenção configurável; anonimização na saída; **sem foto/localização/texto livre** — 🔴 · fonte [12](12-seguranca-privacidade.md)/P3.

### F.17 Checklist — Segurança

- [ ] Login **código-só** com rate-limit por camada; **JWT aluno × Edu rejeitado**; escopo mínimo do papel; gabarito fora do cliente; **ledger imutável** — 🔴 · fonte [12](12-seguranca-privacidade.md).

### F.18 Checklist — i18n

- [ ] *Strings* externalizadas; **sem palavra proibida**; sincronia texto↔áudio por locale; **paridade com o espelho EN** — 🔴 · fonte [16](16-localizacao-i18n.md)/[02](02-vocabulario.md).

### F.19 Checklist — Telemetria e observabilidade

- [ ] Cada ação instrumentada emite o **evento correto do [Apêndice D](apendice-D-eventos-telemetria.md)**; envelope válido; dedup offline; KPI mensurável — 🟡 · fonte [17](17-telemetria-metricas.md).

### F.20 Checklist — Áudio e narração

- [ ] Toda instrução com **áudio pt-BR**; botão "ouvir de novo"; narração offline — 🔴 · fonte [13](13-acessibilidade.md)/[15](15-arte-audio-assets.md).

### F.21 Checklist — Offline / PWA

- [ ] *Shell* offline; fila **append-only** em IndexedDB; sync **idempotente**; **token só em memória** — 🔴 · fonte [11](11-arquitetura.md)/[07](07-ux-fluxos-navegacao.md).

### F.22 Checklist — Social seguro

- [ ] Amizade **só na mesma escola**; sem texto livre; **derrota nunca pune**; anti-spam; presença/bloqueio — 🔴 · fonte [09](09-social.md)/P15.

### F.23 Checklist — Economia auditável

- [ ] Ledger imutável; saldo recomputável; **erro nunca subtrai** moedas/estrelas; **zero dinheiro real** — 🔴 · fonte [05](05-sistemas-de-jogo.md)/[22](22-monetizacao.md)/P7/P14.

### F.24 Checklist — Vocabulário e cópia infantil

- [ ] Mapa interno→criança; **sem palavras proibidas** na UI; tom do Cosmo — 🔴 · fonte [02](02-vocabulario.md)/[Apêndice A](apendice-A-glossario.md).

### F.25 Checklist — Princípios Imutáveis

- [ ] Suíte de **regressão** que trava as **16+2 invariantes** contra qualquer mudança — 🔴 · fonte [01](01-principios-imutaveis.md)/[18.23](18-qa-testes.md).

### F.26 ⚠️ Portão de release POR FASE (Q0–Q6)

- [ ] DoD de fase da [Seção 23](23-roadmap.md) satisfeito + a régua afetiva **"a criança usa e quer voltar amanhã?"** — 🔴 · fonte [23](23-roadmap.md). **⚠️ limiares numéricos (D1/D7/D30) pendem do dono** ([Seção 17](17-telemetria-metricas.md) §15).

### F.27 ⚠️ Checklist — Playtest com crianças

- [ ] Método, consentimento, roteiro e coleta 6–11 anos definidos — 🟡 · fonte [18](18-qa-testes.md) (18.17)/[13](13-acessibilidade.md). **⚠️ protocolo e caráter bloqueante A CONFIRMAR** pelo dono.

### F.28 Matriz checklist × seção-fonte

> Cruza cada bloco com a seção que o governa — garante rastreabilidade e **nenhum critério órfão**.

| Bloco | Seção-fonte |
|-------|:-----------:|
| F.3 Tela | 07 · 02 · 13 · Apêndice D/E |
| F.4 Feature | 24 · 18 · 19 · 11 · 12 |
| F.5 Mecânica | 05 · 11 · 13 |
| F.6 Endpoint | 12 · 11 · Apêndice B |
| F.7 Conteúdo | 06 · 03 · 13 · 15 |
| F.8–F.15 Sete eixos | 24.16 · 18 · 11 · 13 · 14 · 07 · 08 |
| F.16–F.25 Transversais | 12 · 16 · 17 · 09 · 05 · 22 · 02 · 01 · 13 · 15 · 11 · 07 |
| F.26 Fase | 23 · 17 |
| F.27 Playtest | 18 · 13 |

### F.29 ⚠️ Automação dos checklists em CI

- [ ] Automatizável como gate de merge: *lint* de vocabulário, testes de acessibilidade (axe-core), contrato de eventos — 🟡. **⚠️ adoção A CONFIRMAR** (liga a [24.19](24-governanca.md)/[Seção 18](18-qa-testes.md)).

### F.30 Evidência, sign-off e registro

- [ ] Como marcar "pronto", qual **evidência** anexar (teste/print/log), **quem assina** cada portão — fecha o laço de auditoria — 🔴 · fonte [24](24-governanca.md).

### F.31 Governança dos checklists

Item novo entra **via spec/ADR** e sincroniza com a **seção-dona**; **sem critério duplicado ou desatualizado**. O F **agrega**, não legisla ([G7](24-governanca.md)/[G10](24-governanca.md)).

---

## 🇬🇧 Consolidated Checklists (DoD)

### F.1 How to use the checklists

The appendix is the **consolidated source** of "Done when". It is **mandatory at [Gate 3](24-governanca.md)** (faithful implementation → review → Bible update). It **creates no new criterion**: each item **points** to the owner section, which holds authority over the rule ([G10](24-governanca.md)).

### F.2 Anatomy of an item

Every item follows the fixed format: **verifiable assertion** `[ ]` + **required evidence** + **source section** (`NN.x`) + **severity** — 🔴 **blocking** (halts Gate 3) or 🟡 **recommended**. ⚠️ items mark an owner-pending number/threshold.

### F.3 DoD per SCREEN

- [ ] All **states** covered: empty, loading (skeleton), network error, offline, success, no-license — 🔴 · source [07§12](07-ux-fluxos-navegacao.md)/[E.6](apendice-E-wireframes.md).
- [ ] Entry **audio/narration** and "hear again" on every instruction — 🔴 · source [13](13-acessibilidade.md).
- [ ] **Navigation** with no dead end: guaranteed return to Home — 🔴 · source [07§5](07-ux-fluxos-navegacao.md).
- [ ] **One primary action** per screen — 🟡 · source [07§6](07-ux-fluxos-navegacao.md).
- [ ] **Canonical copy** (child vocabulary; no forbidden word) — 🔴 · source [02](02-vocabulario.md).
- [ ] **Telemetry** fires the correct event — 🟡 · source [Appendix D](apendice-D-eventos-telemetria.md)/[E.38](apendice-E-wireframes.md).

### F.4 DoD per FEATURE / SYSTEM

- [ ] **Spec 🟢 approved** before implementing (Golden rule) — 🔴 · source [24](24-governanca.md).
- [ ] **Tests** on the pyramid + coverage gate — 🔴 · source [18](18-qa-testes.md).
- [ ] **Non-hardcoded numeric rules** (`quest.*` namespace) — 🔴 · source [19](19-liveops.md)/[B.24](apendice-B-api-dados.md).
- [ ] **Server authority** (server-side answer key/reward) — 🔴 · source [11](11-arquitetura.md)/P13.
- [ ] **Audit** of sensitive adult access — 🔴 · source [12](12-seguranca-privacidade.md).

### F.5 DoD per game MECHANIC

- [ ] **`MecanicaProps`** contract honored (plugin/registry) — 🔴 · source [05](05-sistemas-de-jogo.md)/[11](11-arquitetura.md).
- [ ] **Answer key on the server**, never on the client — 🔴 · source P13/[B.15](apendice-B-api-dados.md).
- [ ] **Valid content schema** (⚠️ per-mechanic format pending — [B.23](apendice-B-api-dados.md)) — 🟡.
- [ ] Touch-first **accessibility** (targets ≥48px, audio) — 🔴 · source [13](13-acessibilidade.md).

### F.6 DoD per ENDPOINT / API contract

- [ ] **Roles checked** in the backend — 🔴 · source [12](12-seguranca-privacidade.md)/[B.1](apendice-B-api-dados.md).
- [ ] **`escola_id` isolation** (P15) — 🔴 · source [11](11-arquitetura.md)/[12](12-seguranca-privacidade.md).
- [ ] **Standardized errors** (401/403/404/422/429) — 🔴 · source [B.26](apendice-B-api-dados.md).
- [ ] **ETag/version** where applicable — 🟡 · source [B.25](apendice-B-api-dados.md).
- [ ] **Answer key never on the client** — 🔴 · source [B.15](apendice-B-api-dados.md)/P13.
- [ ] Contract **mirrors the code** (real DDL/route) — 🔴 · source [Appendix B](apendice-B-api-dados.md).

### F.7 DoD per pedagogical CONTENT

- [ ] **BNCC code** tied — 🔴 · source [06](06-pedagogico-bncc.md).
- [ ] **Audio** for prompt/hint/explanation — 🔴 · source [13](13-acessibilidade.md)/[15](15-arte-audio-assets.md).
- [ ] **Human review** (curation; ERER without AI) — 🔴 · source [03](03-universo.md)/[06](06-pedagogico-bncc.md).
- [ ] **Published version** (`quest_missoes.versao`) — 🔴 · source [B.15](apendice-B-api-dados.md)/[B.25](apendice-B-api-dados.md).

### F.8 QA review gate (Gate 3) — the 7 axes

A consolidated, actionable view of the **seven axes** of [Section 24.16](24-governanca.md) (F.9–F.15). The **testing strategy** behind them is [Section 18](18-qa-testes.md)'s; F **makes it actionable**, it does not redefine.

### F.9 Axis — Bugs and fixes

- [ ] No regression; severity classified; extra weight to what affects the **non-reading child** — 🔴 · source [24.16](24-governanca.md)/[18](18-qa-testes.md).

### F.10 ⚠️ Axis — Performance on the target device

- [ ] Load/memory budget and smoothness on the **minimum hardware** — 🔴 · source [11](11-arquitetura.md). **⚠️ the numbers are owner-pending** (target device/budget; ADR C.25).

### F.11 Axis — UX and flow

- [ ] **1 primary action** per screen; invitation (not command); error **always welcomed**; **no dark patterns** — 🔴 · source [07](07-ux-fluxos-navegacao.md)/[08](08-onboarding-ftue.md)/P6/P8.

### F.12 Axis — Accessibility

- [ ] **Audio** on every instruction; targets **≥48px**; contrast; focus order; `reduced-motion`; colorblind mode; **time never the sole criterion** — 🔴 · source [13](13-acessibilidade.md).

### F.13 Axis — Responsiveness

- [ ] Target breakpoints (tablet portrait/landscape, Chromebook, phone); **no horizontal overflow** — 🔴 · source [07](07-ux-fluxos-navegacao.md)/[E.8](apendice-E-wireframes.md).

### F.14 Axis — Scalability

- [ ] Class peak (half the classes at **7:30**); `escola_id` indexes; rate-limit; Redis/replica triggers — 🔴 · source [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md).

### F.15 Axis — Organization and code quality

- [ ] Monorepo standards; `@constela/quest-core` types; **no hardcoded numeric rule** — 🟡 · source [11](11-arquitetura.md)/[24](24-governanca.md).

### F.16 Checklist — LGPD

- [ ] Minimal collection; social opt-in; configurable retention; anonymization on departure; **no photo/location/free text** — 🔴 · source [12](12-seguranca-privacidade.md)/P3.

### F.17 Checklist — Security

- [ ] **Code-only** login with per-layer rate-limit; **student JWT × Edu rejected**; minimal role scope; answer key off the client; **immutable ledger** — 🔴 · source [12](12-seguranca-privacidade.md).

### F.18 Checklist — i18n

- [ ] Externalized strings; **no forbidden word**; text↔audio sync per locale; **parity with the EN mirror** — 🔴 · source [16](16-localizacao-i18n.md)/[02](02-vocabulario.md).

### F.19 Checklist — Telemetry and observability

- [ ] Each instrumented action emits the **correct [Appendix D](apendice-D-eventos-telemetria.md) event**; valid envelope; offline dedup; measurable KPI — 🟡 · source [17](17-telemetria-metricas.md).

### F.20 Checklist — Audio and narration

- [ ] Every instruction with **pt-BR audio**; "hear again" button; offline narration — 🔴 · source [13](13-acessibilidade.md)/[15](15-arte-audio-assets.md).

### F.21 Checklist — Offline / PWA

- [ ] Offline **shell**; **append-only** IndexedDB queue; **idempotent** sync; **token in memory only** — 🔴 · source [11](11-arquitetura.md)/[07](07-ux-fluxos-navegacao.md).

### F.22 Checklist — Safe social

- [ ] Friendship **within the same school only**; no free text; **defeat never punishes**; anti-spam; presence/block — 🔴 · source [09](09-social.md)/P15.

### F.23 Checklist — Auditable economy

- [ ] Immutable ledger; recomputable balance; **a mistake never subtracts** coins/stars; **zero real money** — 🔴 · source [05](05-sistemas-de-jogo.md)/[22](22-monetizacao.md)/P7/P14.

### F.24 Checklist — Vocabulary and child copy

- [ ] Internal→child map; **no forbidden words** in the UI; Cosmo's tone — 🔴 · source [02](02-vocabulario.md)/[Appendix A](apendice-A-glossario.md).

### F.25 Checklist — Immutable Principles

- [ ] A **regression** suite that locks the **16+2 invariants** against any change — 🔴 · source [01](01-principios-imutaveis.md)/[18.23](18-qa-testes.md).

### F.26 ⚠️ Release gate PER PHASE (Q0–Q6)

- [ ] [Section 23](23-roadmap.md)'s phase DoD satisfied + the affective ruler **"does the child use it and want to come back tomorrow?"** — 🔴 · source [23](23-roadmap.md). **⚠️ numeric thresholds (D1/D7/D30) are owner-pending** ([Section 17](17-telemetria-metricas.md) §15).

### F.27 ⚠️ Checklist — Playtest with children

- [ ] Method, consent, script and 6–11 collection defined — 🟡 · source [18](18-qa-testes.md) (18.17)/[13](13-acessibilidade.md). **⚠️ protocol and blocking status TO CONFIRM** by the owner.

### F.28 Checklist × source-section matrix

> Crosses each block with the section that governs it — ensures traceability and **no orphan criterion**.

| Block | Source section |
|-------|:--------------:|
| F.3 Screen | 07 · 02 · 13 · Appendix D/E |
| F.4 Feature | 24 · 18 · 19 · 11 · 12 |
| F.5 Mechanic | 05 · 11 · 13 |
| F.6 Endpoint | 12 · 11 · Appendix B |
| F.7 Content | 06 · 03 · 13 · 15 |
| F.8–F.15 Seven axes | 24.16 · 18 · 11 · 13 · 14 · 07 · 08 |
| F.16–F.25 Cross-cutting | 12 · 16 · 17 · 09 · 05 · 22 · 02 · 01 · 13 · 15 · 11 · 07 |
| F.26 Phase | 23 · 17 |
| F.27 Playtest | 18 · 13 |

### F.29 ⚠️ Checklist automation in CI

- [ ] Automatable as a merge gate: vocabulary lint, accessibility tests (axe-core), event contract — 🟡. **⚠️ adoption TO CONFIRM** (links to [24.19](24-governanca.md)/[Section 18](18-qa-testes.md)).

### F.30 Evidence, sign-off and record

- [ ] How to mark "done", which **evidence** to attach (test/screenshot/log), **who signs** each gate — closes the audit loop — 🔴 · source [24](24-governanca.md).

### F.31 Governance of the checklists

A new item enters **via spec/ADR** and syncs with the **owner section**; **no duplicated or stale criterion**. F **aggregates**, it does not legislate ([G7](24-governanca.md)/[G10](24-governanca.md)).
