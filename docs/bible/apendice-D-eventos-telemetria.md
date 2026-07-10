# Apêndice D — Catálogo de Eventos de Telemetria / Telemetry Event Catalog

- **Status:** 🟢 aprovado / approved
- **Tipo:** documento de **referência** (não segue o padrão de 16 partes do [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md), que vale só para capítulos).
- **Fontes / Sources:** **[Seção 17](17-telemetria-metricas.md)** é a **dona da taxonomia** (ADR-17-D); este apêndice a **executa**. Campos concretos vêm de `quest_tentativas`/`quest_perfis` ([Apêndice B](apendice-B-api-dados.md)). Fase = [Seção 23](23-roadmap.md).
- **Depende de:** política LGPD/retenção/erasure = [Seção 12](12-seguranca-privacidade.md); agendador de expurgo (O16) = [Seção 14](14-infra-deploy-dr.md); fórmula BNCC = [Seção 06](06-pedagogico-bncc.md); `locale` = [Seção 16](16-localizacao-i18n.md).

> **⚠️ Estado Q0: ZERO analytics de produto.** Nenhum evento deste catálogo é emitido hoje — não há SDK de
> terceiros, nem camada de emissão, nem KPI computado (P18). **TODO evento aqui é aspiracional**; a coluna **Fase**
> marca quando cada um entra (Q1+). O D **executa**, não redefine: nomes, esquema e envelope são decididos na
> [Seção 17](17-telemetria-metricas.md); novo evento entra via spec/ADR sincronizado com ela (D.36).
>
> **Legenda de fase:** **Q1** núcleo jogável/navegação/erros/derivados-de-ledger · **Q2** retenção/economia-gasta/loja/bem-estar · **Q4** social/salas · **⏸️** bloqueado (pende do dono).
> **Semáforo de privacidade (por campo):** 🟢 **pseudônimo/agregável** (ok) · 🔴 **proibido** (PII/foto/localização/texto livre/resposta bruta — nunca no evento; só no *store* expurgável, T2/T13).

---

## 🇧🇷 Catálogo de Eventos

### D.1 Convenções

Telemetria **própria** (sem SDK de terceiros — P18), **mínima** e **finalística** (P3). Datas em **UTC ISO-8601**, payload **JSON**. Nenhum evento carrega **PII direta**. O servidor é a **fonte da verdade** (P13): a telemetria de jogo é **derivada** do ledger imutável `quest_tentativas`; a instrumentação do cliente é **suplementar** (fila offline + dedup). **Fronteiras:** a [Seção 17](17-telemetria-metricas.md) é dona dos KPIs/norte; o [Apêndice B](apendice-B-api-dados.md) é dono das rotas/tabelas que **originam** os eventos derivados; este apêndice é o **dicionário de eventos**.

### D.2 Como ler

Cada família (D.18–D.27) é uma tabela de fichas de evento. **Todo** evento carrega o **envelope comum** (D.4) — a coluna "Campos" lista **só os campos próprios** (além do envelope). A coluna **Deriva de** aponta a norma T# e/ou a seção-fonte. **O que NÃO é telemetria de produto:** `logs_auditoria` (auditoria permanente, [Seção 12](12-seguranca-privacidade.md)/[11](11-arquitetura.md)) e `observabilidade.py` (infra RED, [Seção 14](14-infra-deploy-dr.md)) — não são catalogados aqui (ADR-17-D).

### D.3 Template canônico da ficha de evento

`nome (substantivo.verbo)` | `versão` | quando dispara | origem (cliente/derivado-servidor) | campos (nome/tipo/obrigatoriedade) | classe de privacidade | KPI-alvo | seção-fonte.

### D.4 Envelope comum (materializa T5) — presente em TODO evento

| Campo | Tipo | Obrigatório | Privacidade | Observação |
|-------|------|:-----------:|:-----------:|-----------|
| `event_name` | enum (`substantivo.verbo`) | sim | 🟢 | vocabulário **interno**, nunca infantil |
| `event_version` | int | sim | 🟢 | versionamento (D.9) |
| `event_id` | uuid | sim | 🟢 | **dedup** (D.14) |
| `occurred_at` | timestamp UTC | sim | 🟢 | quando ocorreu (ordenação) |
| `received_at` | timestamp UTC | sim | 🟢 | quando o servidor recebeu (clock skew) |
| `perfil_id` | int | sim | 🟢 | identidade **pseudônima** (T4) |
| `escola_id` | int | sim | 🟢 | isolamento multi-escola (P15) |
| `sessao_id` | uuid | sim | 🟢 | ⚠️ definição operacional de sessão pende ([Seção 17.4](17-telemetria-metricas.md)) |
| `origem` | enum (`web`\|`pwa-offline`\|`derivado-servidor`) | sim | 🟢 | campo real `quest_tentativas.origem` + o caso derivado |
| `locale` | str | não | 🟢 | propriedade ([Seção 16](16-localizacao-i18n.md)); **nenhum texto de UI no payload** |

> **Envelope canônico = os 10 campos acima (T5, [Seção 17](17-telemetria-metricas.md)).** `app_version` + **classe** de device
> são **propriedades PROPOSTAS fora do T5** ([Seção 17](17-telemetria-metricas.md) §15), pendentes do **veredito de minimização
> da [Seção 12](12-seguranca-privacidade.md)** — não são membros do envelope enquanto não sancionadas.
>
> **Nunca no envelope (🔴):** `nome_exibicao`, `apelido`, `codigo_amigo` (PII), `codigo_login`/`qr_token` (segredos), a **resposta bruta** da criança, foto, localização, texto livre.

### D.5 Nomenclatura

`substantivo.verbo` em `snake_case`, vocabulário **interno** (nunca o rótulo infantil): `tentativa.iniciada`, `missao.concluida`, `avatar.alterado`. Um evento = um fato consumado.

### D.6 Tipos permitidos

`int`, `decimal`, `bool`, `enum` (valores fechados), `timestamp` UTC, `uuid`. **Proibido texto livre** no payload (T2).

### D.7 Semáforo de privacidade LGPD (por campo)

Cada campo é 🟢 **pseudônimo/agregável** ou 🔴 **proibido**. Regra: só entra o que tem **finalidade**; a **resposta bruta** (`quest_tentativas.respostas[].resposta`) **nunca** vira campo de evento — vive só no *store* expurgável (T13).

### D.8 Identidade

Identidade de um evento = `perfil_id` + `escola_id` (T4/P15). **Nunca** nome/apelido/`codigo_amigo`. Join cross-escola em nível individual é **proibido** (P15).

### D.9–D.11 Versionamento, deprecação, compatibilidade

- **`event_version`** por evento; mudança **compatível** (campo novo opcional) não sobe major; **incompatível** (remover/retipar) exige nova versão e mantém a análise histórica (T6).
- **Ciclo de vida:** `proposto → ativo → depreciado → removido`.
- **Schema registry** é a **fonte única** cliente↔servidor (D.12).

### D.12–D.17 Pipeline

- **D.12 Schema registry** — contrato versionado, fonte única.
- **D.13 Validação no ingest** — evento inválido → **dead-letter** (⚠️ descartar × quarentenar pende — [Seção 17](17-telemetria-metricas.md)); nunca corrompe KPI.
- **D.14 Dedup** — idempotente por `event_id`.
- **D.15 Late-arrival** — preserva `occurred_at`; ordena por ele (não por `received_at`).
- **D.16 `occurred_at` × `received_at`** — clock skew do tablet; ambos gravados.
- **D.17 Origens + fila** — cliente com **fila IndexedDB** append-only; sync ao reconectar; flag `origem`.

---

### D.18 Família — SESSÃO & ACESSO

| Evento | Quando dispara | Campos próprios | Fase | Deriva de |
|--------|----------------|-----------------|:----:|-----------|
| `sessao.iniciada` | app abre uma sessão do aluno | `primeira_vez` (bool) | Q1 | T8 (norte D+1) |
| `sessao.encerrada` | sessão termina/expira | `duracao_seg` (int) | Q1 | T8/T10 |
| `identidade.confirmada` | boot reconhece o dono do aparelho ("É você?") | — | Q1 | T4 |
| `login.realizado` | `entrar`/`entrar-qr` com sucesso | `via` (enum `codigo`\|`qr`) | Q1 | T3 · auth ([B.2](apendice-B-api-dados.md)) |
| `login.falhou` | tentativa recusada | `motivo` (enum `codigo`\|`inativo`\|`rate_limit`) — **nunca o código** (🔴) | Q1 | T2 · anti-abuso |

### D.19 Família — NÚCLEO JOGÁVEL (derivada do ledger)

| Evento | Quando dispara | Campos próprios | Fase | Deriva de |
|--------|----------------|-----------------|:----:|-----------|
| `tentativa.iniciada` | abre uma Missão | `missao_id`, `missao_versao`, `modo` (enum) | Q1 | T3 · `quest_tentativas` |
| `desafio.respondido` | criança responde um Desafio | `mecanica` (enum), `dificuldade` (1–5), `bncc_codigo`, `correta` (bool), `tempo_ms` (int), `dicas` (int) — **sem a resposta bruta** (🔴) | Q1 | T2/T13 · gabarito conferido no **servidor** (P13) |
| `tentativa.finalizada` | fecha a Missão | `acertos`, `total_desafios`, `tempo_seg`, `xp_ganho`, `estrelas` | Q1 | T3 · `quest_tentativas` |

### D.20 Família — PROGRESSÃO & ECONOMIA (eco do ledger — sem dinheiro real)

| Evento | Quando dispara | Campos próprios | Fase | Deriva de |
|--------|----------------|-----------------|:----:|-----------|
| `missao.concluida` | Missão concluída (melhor resultado) | `missao_id`, `estrelas` (0–3) | Q1 | `quest_progresso` |
| `estrela.conquistada` | nova estrela na Constelação | `total_estrelas` (int) | Q1 | Seção 05 |
| `nivel.subido` | XP cruza o limiar de nível | `nivel` (int) | Q1 | Seção 05 |
| `moedas.creditadas` | Moedas ganhas (jogo/nível/diária) | `quantia` (int), `fonte` (enum) | Q1 | ledger (P14) |
| `moedas.gastas` | Moedas gastas em cosmético | `quantia` (int), `item_slug` | Q2 | ledger (P14) |

### D.21 Família — RETENÇÃO

| Evento | Quando dispara | Campos próprios | Fase | Deriva de |
|--------|----------------|-----------------|:----:|-----------|
| `chama.atualizada` | sequência de dias avança | `sequencia_dias` (int) | Q2 | `quest_perfis.sequencia_dias` |
| `chama.reacendida` | escudo perdoa uma falta | `escudo_usado` (bool) | Q2 | `escudo_sequencia` |
| `tarefa.resgatada` | diária/semanal/presente de login resgatado | `tipo` (enum `diaria`\|`semanal`\|`login`) | Q2 | Seção 05 |
| `conquista.desbloqueada` | marco atingido | `conquista_slug` | Q2 | Seção 05 |
| `colecionavel.obtido` | Jornada concluída rende colecionável | `planeta_slug`, `item_slug` | Q2 | Seção 05 · fantasia 03 |

### D.22 Família — AVATAR / VESTIÁRIO / LOJA

| Evento | Quando dispara | Campos próprios | Fase | Deriva de |
|--------|----------------|-----------------|:----:|-----------|
| `avatar.alterado` | troca de item equipado | `slot` (enum `cor`\|`roupa`\|`chapeu`\|`acessorio`\|`pet`\|`efeito`\|`moldura`) | Q1 | `quest_perfis.avatar` |
| `vestiario.aberto` | abre o Vestiário | — | Q1 | navegação |
| `item.comprado` | compra de cosmético na loja | `item_slug`, `preco` (int) | Q2 | ledger · Seção 05 |

### D.23 Família — SOCIAL / MULTIPLAYER

| Evento | Quando dispara | Campos próprios | Fase | Deriva de |
|--------|----------------|-----------------|:----:|-----------|
| `amizade.solicitada` | pedido de amizade (mesma escola) | `alvo_perfil_id` | Q4 | Seção 09 · P15 |
| `amizade.respondida` | aceite/recusa | `aceita` (bool) | Q4 | Seção 09 |
| `sala.criada` | cria sala (Estudar com um amigo/Corrida) | `modo` (enum) | Q4 | `quest_salas` (aspiracional) |
| `sala.entrada` | entra numa sala | `sala_id` | Q4 | Seção 09 |
| `partida.iniciada` | começa a partida | `modo`, `sala_id` | Q4 | `quest_tentativas.modo/sala_id` |
| `partida.finalizada` | fim da partida | `resultado` (enum) | Q4 | Seção 09 |
| `mensagem_rapida.enviada` | frase de catálogo (**só slug, nunca texto** 🔴) | `frase_slug` | Q4 | Seção 09 · T2 |

### D.24 Família — NAVEGAÇÃO / UX / ÁUDIO

| Evento | Quando dispara | Campos próprios | Fase | Deriva de |
|--------|----------------|-----------------|:----:|-----------|
| `planeta.aberto` | abre um Planeta | `mundo_slug` | Q1 | navegação |
| `aba.trocada` | troca de aba | `aba` (enum `jogar`\|`vestiario`\|`carreira`) | Q1 | navegação |
| `narracao.reproduzida` | "ouvir de novo" | `contexto` (enum) | Q1 | Seção 13 (áudio) |

### D.25 Família — GUARDRAILS DE SAÚDE & ANTI-ABUSO

| Evento | Quando dispara | Campos próprios | Fase | Deriva de |
|--------|----------------|-----------------|:----:|-----------|
| `teto_diario.atingido` | XP diário chega ao teto (celebra, não bloqueia) | `xp_dia` (int) | Q2 | T10 · Seção 13 |
| `sessao.longa` | gatilho de pausa do Cosmo | `duracao_seg` (int) | Q2 | T10 · Seção 13 |
| `sinal.anti_farm` | rejogo/abuso detectado (derivado; **não pune** — §8 da 17) | `tipo` (enum) | Q1 | T3 · alimenta rate-limit/economia |

### D.26 Família — ERROS / CRASH / DIAGNÓSTICO

| Evento | Quando dispara | Campos próprios | Fase | Deriva de |
|--------|----------------|-----------------|:----:|-----------|
| `erro.cliente` | erro tratado no cliente | `tela`, `classe` (enum) — **sem conteúdo pessoal** (🔴) | Q1 | diagnóstico |
| `crash` | falha não tratada | `tela`, `app_version`, `classe_device` — ⚠️ minimização pende (Seção 12) | Q1 | diagnóstico |

### D.27 Eventos DERIVADOS no servidor

Agregações computadas **no servidor** a partir de `quest_tentativas` (imutável) e, na fase Q3+, do `quest_outbox` — **independentes do cliente** (P13). Ex.: recomputo de `quest_habilidades` (domínio BNCC), retenção por coorte, taxa de conclusão. O **mecanismo** de outbox é da [Seção 11](11-arquitetura.md); a **fórmula** do domínio é da [Seção 06](06-pedagogico-bncc.md).

### D.28 Matriz evento × KPI × seção-fonte

> Amarra os eventos que **sustentam os KPIs-núcleo** da [Seção 17](17-telemetria-metricas.md) (§15) à sua seção-dona. Os KPIs-núcleo propostos são **quatro** (retenção D1/D7/D30 · taxa de conclusão de Missão · cobertura de domínio BNCC · taxa de sessão saudável). Eventos puramente **operacionais/diagnóstico/engajamento** têm finalidade **sem uma linha de KPI dedicada**. **Os alvos numéricos são da Seção 17 (⚠️ §15)** — o D não fixa alvo.

| Evento(s) | KPI-núcleo / sinal | Seção-fonte |
|-----------|--------------------|:-----------:|
| `sessao.iniciada` (D+1) | **Norte:** retenção "volta amanhã?" | 17 · 08 |
| `tentativa.finalizada`, `missao.concluida` | taxa de conclusão de Missão | 17 · 05 |
| `desafio.respondido` (agregado → `quest_habilidades`) | cobertura de domínio BNCC | 17 · 06 |
| `teto_diario.atingido`, `sessao.longa` | taxa de **sessão saudável** (guardrail) | 17 · 13 |
| `login.falhou`, `sinal.anti_farm` | *sinal operacional anti-abuso* (**não** KPI-núcleo; alimenta rate-limit — [17 §8](17-telemetria-metricas.md)) | 17 · 12 |

### D.29–D.33 Operação do pipeline

- **D.29 Volume/cardinalidade/amostragem** — eventos de alto volume podem ser amostrados **sem** perder fidelidade dos KPIs-núcleo (⚠️ política pende, T17/[Seção 17.25](17-telemetria-metricas.md)).
- **D.30 Estados de erro/vazio/offline no envio** — fila offline; dead-letter; sync idempotente.
- **D.31 Observabilidade do próprio ingest** — saúde do pipeline (distinta da telemetria de produto; alerta de métrica ≠ alerta de infra, T16).
- **D.32 i18n/locale** — `locale` é propriedade; **nenhum texto traduzível** no payload ([Seção 16](16-localizacao-i18n.md)).
- **D.33 Testes/fixtures + contrato em CI** — o schema registry é testado como contrato (liga a [F.19](apendice-F-checklists-dod.md)/[Seção 18](18-qa-testes.md)).

### D.34 ⚠️ Retenção e anonimização POR CLASSE de evento

> **Pendência do dono.** O **prazo** de retenção é **posse da [Seção 12](12-seguranca-privacidade.md) §15** (o D não o fixa); o padrão sugerido de **24 meses** é **só referência a confirmar**. Erasure **hoje = cascade-delete** (tudo some na exclusão do aluno); migrar para **anonimização** é decisão da 12. O cron de expurgo é O16 da [Seção 14](14-infra-deploy-dr.md).

| Classe de evento | Prazo sugerido (⚠️ a confirmar) | Gatilho |
|------------------|--------------------------------|---------|
| Resposta bruta (`respostas`) | store expurgável, prazo curto | agendador O16 (Seção 14) |
| Resultado por jogada (ledger) | append-only, retido | erasure (Seção 12 §15) |
| Eventos de sessão/navegação | 24 meses (referência) | erasure |
| Agregados anônimos (se adotados) | fora do ledger, congelado antes do expurgo | decisão Seção 12 |

### D.35 ⏸️ Evento de atribuição de experimento (A/B) — BLOQUEADO

`experimento.atribuido` fica **especificado porém inativo**. **Pendência do dono / [Seção 17.28](17-telemetria-metricas.md):** é permitido A/B com público infantil? Sob quais limites éticos e de consentimento? Sem autorização, **não é emitido**.

### D.36 Governança / changelog do catálogo

Novo evento entra **via spec/ADR sincronizado com a [Seção 17](17-telemetria-metricas.md)** (dona da taxonomia, ADR-17-D). Todo evento tem **finalidade** e **classe de privacidade**: os que sustentam um KPI-núcleo aparecem em D.28; os demais (operacionais/diagnóstico/engajamento) têm finalidade **sem uma linha de KPI dedicada** — **sem evento órfão**. Mudança de esquema é **versionada** (D.9). O D **não decide** política nem cria KPI — **materializa** a decisão da 17.

---

## 🇬🇧 Telemetry Event Catalog

- **Owner of the taxonomy:** [Section 17](17-telemetria-metricas.md) (ADR-17-D); this appendix **executes** it.

> **⚠️ Q0 state: ZERO product analytics.** No event in this catalog is emitted today — no third-party SDK, no
> emit layer, no computed KPI (P18). **Every event here is aspirational**; the **Phase** column marks when each
> arrives (Q1+). D **executes**, it does not redefine: names, schema and envelope are decided in
> [Section 17](17-telemetria-metricas.md); a new event enters via spec/ADR synced with it (D.36).
>
> **Phase legend:** **Q1** core gameplay/navigation/errors/ledger-derived · **Q2** retention/spent-economy/store/well-being · **Q4** social/rooms · **⏸️** blocked (owner-pending).
> **Privacy semaphore (per field):** 🟢 **pseudonymous/aggregable** (ok) · 🔴 **forbidden** (PII/photo/location/free text/raw answer — never in the event; only in the purgeable store, T2/T13).

### D.1 Conventions

**First-party** telemetry (no third-party SDK — P18), **minimal** and **purposeful** (P3). Dates in **UTC ISO-8601**, **JSON** payload. No event carries **direct PII**. The server is the **source of truth** (P13): game telemetry is **derived** from the immutable ledger `quest_tentativas`; client instrumentation is **supplementary** (offline queue + dedup). **Boundaries:** [Section 17](17-telemetria-metricas.md) owns the KPIs/north; [Appendix B](apendice-B-api-dados.md) owns the routes/tables that **originate** derived events; this appendix is the **event dictionary**.

### D.2 How to read

Each family (D.18–D.27) is a table of event sheets. **Every** event carries the **common envelope** (D.4) — the "Fields" column lists **only the event's own fields** (beyond the envelope). The **Derives from** column points to the T# norm and/or the source section. **What is NOT product telemetry:** `logs_auditoria` (permanent audit, [Section 12](12-seguranca-privacidade.md)/[11](11-arquitetura.md)) and `observabilidade.py` (RED infra, [Section 14](14-infra-deploy-dr.md)) — not cataloged here (ADR-17-D).

### D.3 Canonical event-sheet template

`name (noun.verb)` | `version` | when it fires | origin (client/server-derived) | fields (name/type/required) | privacy class | target KPI | source section.

### D.4 Common envelope (materializes T5) — present in EVERY event

| Field | Type | Required | Privacy | Note |
|-------|------|:--------:|:-------:|------|
| `event_name` | enum (`noun.verb`) | yes | 🟢 | **internal** vocabulary, never child-facing |
| `event_version` | int | yes | 🟢 | versioning (D.9) |
| `event_id` | uuid | yes | 🟢 | **dedup** (D.14) |
| `occurred_at` | UTC timestamp | yes | 🟢 | when it happened (ordering) |
| `received_at` | UTC timestamp | yes | 🟢 | when the server received it (clock skew) |
| `perfil_id` | int | yes | 🟢 | **pseudonymous** identity (T4) |
| `escola_id` | int | yes | 🟢 | multi-school isolation (P15) |
| `sessao_id` | uuid | yes | 🟢 | ⚠️ operational session definition pending ([Section 17.4](17-telemetria-metricas.md)) |
| `origem` | enum (`web`\|`pwa-offline`\|`derivado-servidor`) | yes | 🟢 | real field `quest_tentativas.origem` + the derived case |
| `locale` | str | no | 🟢 | property ([Section 16](16-localizacao-i18n.md)); **no UI text in the payload** |

> **Canonical envelope = the 10 fields above (T5, [Section 17](17-telemetria-metricas.md)).** `app_version` + device **class**
> are **PROPOSED properties outside T5** ([Section 17](17-telemetria-metricas.md) §15), pending the **minimization verdict of
> [Section 12](12-seguranca-privacidade.md)** — not envelope members until sanctioned.
>
> **Never in the envelope (🔴):** `nome_exibicao`, `apelido`, `codigo_amigo` (PII), `codigo_login`/`qr_token` (secrets), the child's **raw answer**, photo, location, free text.

### D.5 Naming

`noun.verb` in `snake_case`, **internal** vocabulary (never the child label): `tentativa.iniciada`, `missao.concluida`, `avatar.alterado`. One event = one accomplished fact.

### D.6 Allowed types

`int`, `decimal`, `bool`, `enum` (closed values), UTC `timestamp`, `uuid`. **Free text forbidden** in the payload (T2).

### D.7 LGPD privacy semaphore (per field)

Each field is 🟢 **pseudonymous/aggregable** or 🔴 **forbidden**. Rule: only what has a **purpose** enters; the **raw answer** (`quest_tentativas.respostas[].resposta`) **never** becomes an event field — it lives only in the purgeable store (T13).

### D.8 Identity

An event's identity = `perfil_id` + `escola_id` (T4/P15). **Never** name/apelido/`codigo_amigo`. A cross-school individual join is **forbidden** (P15).

### D.9–D.11 Versioning, deprecation, compatibility

- **`event_version`** per event; a **compatible** change (new optional field) doesn't bump major; an **incompatible** one (remove/retype) requires a new version and keeps historical analysis (T6).
- **Lifecycle:** `proposed → active → deprecated → removed`.
- **Schema registry** is the **single source** client↔server (D.12).

### D.12–D.17 Pipeline

- **D.12 Schema registry** — versioned contract, single source.
- **D.13 Ingest validation** — invalid event → **dead-letter** (⚠️ discard × quarantine pending — [Section 17](17-telemetria-metricas.md)); never corrupts a KPI.
- **D.14 Dedup** — idempotent by `event_id`.
- **D.15 Late-arrival** — preserves `occurred_at`; orders by it (not `received_at`).
- **D.16 `occurred_at` × `received_at`** — tablet clock skew; both recorded.
- **D.17 Origins + queue** — client with an append-only **IndexedDB queue**; sync on reconnect; `origem` flag.

---

### D.18 Family — SESSION & ACCESS

| Event | When it fires | Own fields | Phase | Derives from |
|-------|---------------|-----------|:-----:|--------------|
| `sessao.iniciada` | app opens a student session | `primeira_vez` (bool) | Q1 | T8 (north D+1) |
| `sessao.encerrada` | session ends/expires | `duracao_seg` (int) | Q1 | T8/T10 |
| `identidade.confirmada` | boot recognizes the device owner ("is it you?") | — | Q1 | T4 |
| `login.realizado` | `entrar`/`entrar-qr` succeeds | `via` (enum `codigo`\|`qr`) | Q1 | T3 · auth ([B.2](apendice-B-api-dados.md)) |
| `login.falhou` | attempt refused | `motivo` (enum `codigo`\|`inativo`\|`rate_limit`) — **never the code** (🔴) | Q1 | T2 · anti-abuse |

### D.19 Family — CORE GAMEPLAY (ledger-derived)

| Event | When it fires | Own fields | Phase | Derives from |
|-------|---------------|-----------|:-----:|--------------|
| `tentativa.iniciada` | opens a Mission | `missao_id`, `missao_versao`, `modo` (enum) | Q1 | T3 · `quest_tentativas` |
| `desafio.respondido` | child answers a Challenge | `mecanica` (enum), `dificuldade` (1–5), `bncc_codigo`, `correta` (bool), `tempo_ms` (int), `dicas` (int) — **no raw answer** (🔴) | Q1 | T2/T13 · answer key checked on the **server** (P13) |
| `tentativa.finalizada` | closes the Mission | `acertos`, `total_desafios`, `tempo_seg`, `xp_ganho`, `estrelas` | Q1 | T3 · `quest_tentativas` |

### D.20 Family — PROGRESSION & ECONOMY (ledger echo — no real money)

| Event | When it fires | Own fields | Phase | Derives from |
|-------|---------------|-----------|:-----:|--------------|
| `missao.concluida` | Mission completed (best result) | `missao_id`, `estrelas` (0–3) | Q1 | `quest_progresso` |
| `estrela.conquistada` | new star in the Constellation | `total_estrelas` (int) | Q1 | Section 05 |
| `nivel.subido` | XP crosses the level threshold | `nivel` (int) | Q1 | Section 05 |
| `moedas.creditadas` | Coins earned (game/level/daily) | `quantia` (int), `fonte` (enum) | Q1 | ledger (P14) |
| `moedas.gastas` | Coins spent on a cosmetic | `quantia` (int), `item_slug` | Q2 | ledger (P14) |

### D.21 Family — RETENTION

| Event | When it fires | Own fields | Phase | Derives from |
|-------|---------------|-----------|:-----:|--------------|
| `chama.atualizada` | day streak advances | `sequencia_dias` (int) | Q2 | `quest_perfis.sequencia_dias` |
| `chama.reacendida` | shield forgives a miss | `escudo_usado` (bool) | Q2 | `escudo_sequencia` |
| `tarefa.resgatada` | daily/weekly/login gift claimed | `tipo` (enum `diaria`\|`semanal`\|`login`) | Q2 | Section 05 |
| `conquista.desbloqueada` | milestone reached | `conquista_slug` | Q2 | Section 05 |
| `colecionavel.obtido` | Journey completion yields a collectible | `planeta_slug`, `item_slug` | Q2 | Section 05 · fantasy 03 |

### D.22 Family — AVATAR / WARDROBE / STORE

| Event | When it fires | Own fields | Phase | Derives from |
|-------|---------------|-----------|:-----:|--------------|
| `avatar.alterado` | equipped item changed | `slot` (enum `cor`\|`roupa`\|`chapeu`\|`acessorio`\|`pet`\|`efeito`\|`moldura`) | Q1 | `quest_perfis.avatar` |
| `vestiario.aberto` | opens the Wardrobe | — | Q1 | navigation |
| `item.comprado` | buys a cosmetic in the store | `item_slug`, `preco` (int) | Q2 | ledger · Section 05 |

### D.23 Family — SOCIAL / MULTIPLAYER

| Event | When it fires | Own fields | Phase | Derives from |
|-------|---------------|-----------|:-----:|--------------|
| `amizade.solicitada` | friend request (same school) | `alvo_perfil_id` | Q4 | Section 09 · P15 |
| `amizade.respondida` | accept/decline | `aceita` (bool) | Q4 | Section 09 |
| `sala.criada` | creates a room (Study with a friend/Race) | `modo` (enum) | Q4 | `quest_salas` (aspirational) |
| `sala.entrada` | joins a room | `sala_id` | Q4 | Section 09 |
| `partida.iniciada` | match starts | `modo`, `sala_id` | Q4 | `quest_tentativas.modo/sala_id` |
| `partida.finalizada` | match ends | `resultado` (enum) | Q4 | Section 09 |
| `mensagem_rapida.enviada` | catalog phrase (**slug only, never text** 🔴) | `frase_slug` | Q4 | Section 09 · T2 |

### D.24 Family — NAVIGATION / UX / AUDIO

| Event | When it fires | Own fields | Phase | Derives from |
|-------|---------------|-----------|:-----:|--------------|
| `planeta.aberto` | opens a Planet | `mundo_slug` | Q1 | navigation |
| `aba.trocada` | tab switch | `aba` (enum `jogar`\|`vestiario`\|`carreira`) | Q1 | navigation |
| `narracao.reproduzida` | "hear again" | `contexto` (enum) | Q1 | Section 13 (audio) |

### D.25 Family — WELL-BEING GUARDRAILS & ANTI-ABUSE

| Event | When it fires | Own fields | Phase | Derives from |
|-------|---------------|-----------|:-----:|--------------|
| `teto_diario.atingido` | daily XP hits the cap (celebrates, doesn't block) | `xp_dia` (int) | Q2 | T10 · Section 13 |
| `sessao.longa` | Cosmo's pause trigger | `duracao_seg` (int) | Q2 | T10 · Section 13 |
| `sinal.anti_farm` | replay/abuse detected (derived; **does not punish** — 17 §8) | `tipo` (enum) | Q1 | T3 · feeds rate-limit/economy |

### D.26 Family — ERRORS / CRASH / DIAGNOSTICS

| Event | When it fires | Own fields | Phase | Derives from |
|-------|---------------|-----------|:-----:|--------------|
| `erro.cliente` | handled client error | `tela`, `classe` (enum) — **no personal content** (🔴) | Q1 | diagnostics |
| `crash` | unhandled failure | `tela`, `app_version`, `classe_device` — ⚠️ minimization pending (Section 12) | Q1 | diagnostics |

### D.27 SERVER-DERIVED events

Aggregations computed **on the server** from `quest_tentativas` (immutable) and, from phase Q3+, the `quest_outbox` — **independent of the client** (P13). E.g.: recompute of `quest_habilidades` (BNCC domain), retention by cohort, completion rate. The outbox **mechanism** is [Section 11](11-arquitetura.md)'s; the domain **formula** is [Section 06](06-pedagogico-bncc.md)'s.

### D.28 Event × KPI × source-section matrix

> Ties the events that **sustain the core KPIs** of [Section 17](17-telemetria-metricas.md) (§15) to their owner section. The proposed core KPIs are **four** (retention D1/D7/D30 · Mission completion rate · BNCC domain coverage · healthy-session rate). Purely **operational/diagnostic/engagement** events have a purpose **without a dedicated KPI line**. **Numeric targets are Section 17's (⚠️ §15)** — D fixes no target.

| Event(s) | Core KPI / signal | Source section |
|----------|-------------------|:--------------:|
| `sessao.iniciada` (D+1) | **North:** retention "comes back tomorrow?" | 17 · 08 |
| `tentativa.finalizada`, `missao.concluida` | Mission completion rate | 17 · 05 |
| `desafio.respondido` (aggregated → `quest_habilidades`) | BNCC domain coverage | 17 · 06 |
| `teto_diario.atingido`, `sessao.longa` | **healthy-session** rate (guardrail) | 17 · 13 |
| `login.falhou`, `sinal.anti_farm` | *anti-abuse operational signal* (**not** a core KPI; feeds rate-limit — [17 §8](17-telemetria-metricas.md)) | 17 · 12 |

### D.29–D.33 Pipeline operation

- **D.29 Volume/cardinality/sampling** — high-volume events may be sampled **without** losing core-KPI fidelity (⚠️ policy pending, T17/[Section 17.25](17-telemetria-metricas.md)).
- **D.30 Error/empty/offline send states** — offline queue; dead-letter; idempotent sync.
- **D.31 Ingest observability** — pipeline health (distinct from product telemetry; metric alert ≠ infra alert, T16).
- **D.32 i18n/locale** — `locale` is a property; **no translatable text** in the payload ([Section 16](16-localizacao-i18n.md)).
- **D.33 Tests/fixtures + CI contract** — the schema registry is tested as a contract (links to [F.19](apendice-F-checklists-dod.md)/[Section 18](18-qa-testes.md)).

### D.34 ⚠️ Retention & anonymization PER event CLASS

> **Owner-pending.** The retention **deadline** is **owned by [Section 12](12-seguranca-privacidade.md) §15** (D does not set it); the suggested **24-month** default is **reference only, to confirm**. Erasure **today = cascade-delete** (everything goes on student deletion); migrating to **anonymization** is 12's decision. The purge cron is [Section 14](14-infra-deploy-dr.md)'s O16.

| Event class | Suggested deadline (⚠️ to confirm) | Trigger |
|-------------|-----------------------------------|---------|
| Raw answer (`respostas`) | purgeable store, short deadline | O16 scheduler (Section 14) |
| Per-play result (ledger) | append-only, retained | erasure (Section 12 §15) |
| Session/navigation events | 24 months (reference) | erasure |
| Anonymous aggregates (if adopted) | off-ledger, frozen before purge | Section 12 decision |

### D.35 ⏸️ Experiment-assignment (A/B) event — BLOCKED

`experimento.atribuido` stays **specified but inactive**. **Owner-pending / [Section 17.28](17-telemetria-metricas.md):** is A/B with a child audience allowed? Under what ethical and consent limits? Without authorization, it is **not emitted**.

### D.36 Catalog governance / changelog

A new event enters **via spec/ADR synced with [Section 17](17-telemetria-metricas.md)** (owner of the taxonomy, ADR-17-D). Every event has a **purpose** and a **privacy class**: those that sustain a core KPI appear in D.28; the rest (operational/diagnostic/engagement) have a purpose **without a dedicated KPI line** — **no orphan events**. A schema change is **versioned** (D.9). D **does not decide** policy nor create a KPI — it **materializes** 17's decision.
