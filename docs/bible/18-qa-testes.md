# 18 — QA & Estratégia de Testes / QA & Testing Strategy

- **Status:** 🟢 aprovado / approved
- **Padrão / Standard:** [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) (16 partes)
- **Fontes / Sources:** `INDICE.md` (bloco 18, subseções 18.x), `_estado-atual/RELATORIO-2026-07-09.md`, `backend/tests/` (**29** `test_*.py` + `conftest.py`: SQLite em memória/StaticPool, TestClient FastAPI, fixtures `escola_completa`/`cliente`, autouse que zera o rate-limit; cobre RBAC `test_permissoes.py`/`test_seguranca.py`, cascade FK real `test_integridade_fk.py` (PRAGMA `foreign_keys=ON`), login infantil sem senha `test_quest_auth.py`, reset `test_reset_senha.py`, Alembic `test_alembic.py`, observabilidade `test_observabilidade.py`), `apps/web/src/test/` (**13** `*.test.tsx` Vitest+Testing Library incl. `edge-cases.test.tsx` — RBAC negativo/validação/respostas incompletas) + `vitest.config.ts` (jsdom + coverage v8), `apps/web/e2e/` (**7** specs Playwright + `auth.setup.ts` + `helpers.ts`) + `playwright.config.ts` (sobe backend+frontend reais; `seed_e2e.py`; workers 1, retries 2 no CI; só chromium), `.github/workflows/ci.yml` (6 jobs bloqueantes; a varredura de segurança fica em `security.yml`; cobertura **medida** mas **sem gate**), Seções [11](11-arquitetura.md)/[12](12-seguranca-privacidade.md)/[13](13-acessibilidade.md)/[14](14-infra-deploy-dr.md)/[15](15-arte-audio-assets.md)/[17](17-telemetria-metricas.md), Apêndice F
- **Depende de / Depends on:** princípios (P1 login código-só · P11 acessibilidade inegociável · P13 servidor é autoridade · P15 isolamento por escola · P17 piso de desempenho) → [01](01-principios-imutaveis.md); **mecanismo** de CI/CD e a **capacidade/operação** do teste de carga → [14](14-infra-deploy-dr.md); **norma** de acessibilidade (contraste 4.5:1/3:1, **playtest com não-leitor** como Done, gate por tela) → [13](13-acessibilidade.md); **auditoria de contraste (A3)** e o orçamento de peso → [15](15-arte-audio-assets.md); **taxonomia** de eventos a instrumentar → [17](17-telemetria-metricas.md); **mecanismo/contratos** de API que se exercita → [11](11-arquitetura.md); **política** de segurança (RBAC/isolamento) → [12](12-seguranca-privacidade.md); **checklists consolidados de DoD** que esta seção alimenta → Apêndice F.

> **Convenção / Convention:** "§N" = uma das 16 **partes deste capítulo** / one of the 16 **parts of this
> chapter**; "Seção NN" / "Section NN" = outro capítulo da Bible; "18.NN" = uma subseção do plano do `INDICE.md`.
> **Escopo / Scope:** este capítulo decide a **estratégia de QA e testes** do Constela Quest — a **pirâmide** de
> testes, as **metas de cobertura** e onde viram **gate**, o **método** de testar acessibilidade, carga, contrato
> e telemetria, e a **definição de pronto (DoD)** de QA. Ele **decide o que testar e o critério de aprovação**;
> **não** decide o **mecanismo** de CI/CD nem a capacidade do teste de carga (Seção [14](14-infra-deploy-dr.md)),
> a **norma** de acessibilidade (Seção [13](13-acessibilidade.md)), os **valores** de contraste/peso (Seção
> [15](15-arte-audio-assets.md)), a **taxonomia** de telemetria (Seção [17](17-telemetria-metricas.md)) nem a
> **política** de segurança (Seção [12](12-seguranca-privacidade.md)) — apenas os **testa** e **referencia**. É a
> **fonte da parte de QA** que **alimenta** o Apêndice F.

---

## 🇧🇷 QA & Estratégia de Testes

### 1. Objetivo
Ser a **referência definitiva de QA e testes** do Constela Quest: **como provamos que o produto funciona, é
seguro e é acessível** antes de chegar à criança — com uma **pirâmide** de testes real, **gates** de qualidade no
CI e um **DoD** claro. Decide a **estratégia e os critérios de aprovação**; **não** decide o **mecanismo** de
CI/CD (Seção [14](14-infra-deploy-dr.md)), a **norma** de acessibilidade (Seção [13](13-acessibilidade.md)), os
**valores** (Seção [15](15-arte-audio-assets.md)) nem a **política** (Seção [12](12-seguranca-privacidade.md)) —
apenas os **testa**. É a fonte da parte de QA que **alimenta** o Apêndice F.

### 2. Contexto
No ecossistema **Hub → Edu → Quest**, cada release toca **dado de criança** — um bug pode expor, punir ou frustrar
quem confiou seu filho/aluno. **Estado atual (Q0) — a pirâmide já existe, faltam os gates:**
- **Unit/integração (backend)** — **29** `test_*.py` (pytest) sobre `conftest.py` (SQLite em memória, TestClient,
  fixtures, reset de rate-limit): cobrem **RBAC/papéis**, **cascade FK real** (PRAGMA `foreign_keys=ON`), **login
  infantil sem senha** (código=credencial, QR, limitador por `(código,IP)` que não pune a turma, aluno inativo,
  isolamento de token Edu/Quest), o **motor de cálculo/pontuação** (`test_scoring.py` — normalização Matific/Elefante,
  a "parte mais crítica do sistema"), auth/reset, **Alembic**, observabilidade.
- **Componente (web)** — **13** `*.test.tsx` (Vitest + Testing Library), incluindo `edge-cases.test.tsx` (RBAC
  negativo, validação, respostas incompletas da API).
- **E2E** — **7** specs Playwright que sobem **backend e frontend reais** (`seed_e2e.py`); serial, retries no CI,
  **só chromium/Desktop**.
- **CI** — `ci.yml` com **6 jobs bloqueantes** (`lint` = ruff+typecheck; `test-backend` = pytest+cov; `test-web` =
  vitest+cov; `build`; `e2e`; `docker`); a varredura de segurança (pip-audit/npm audit/Trivy) é workflow à parte
  (`security.yml`), não conta como job do `ci.yml`. A **cobertura é medida** e publicada, **mas nunca falha o build**
  (sem `--cov-fail-under` no pytest nem `coverage.thresholds` no Vitest).
- **Não existe ainda** — **teste de carga**/pico (sem k6/locust); **acessibilidade automatizada** (sem axe; o
  playtest com não-leitor da Seção [13](13-acessibilidade.md) é manual; a auditoria A3 da Seção [15](15-arte-audio-assets.md)
  não está no CI); **contract test** (sem schemathesis/pact); **testes em `apps/quest`** (Three.js/R3F — só
  typecheck), `apps/mobile` e `packages/*`; regressão visual; e2e cross-browser/mobile.

Este capítulo **formaliza** a pirâmide, define os **gates** e o **método** dos testes que faltam.

### 3. Filosofia da funcionalidade
**"Teste é o cinto de segurança de quem confiou a criança à gente."** A qualidade não é opcional num produto
infantil: o teste **prova** os invariantes antes de a criança sentir o erro. Princípios de QA que guiam esta
seção: **a pirâmide é ampla na base** (muitos unit/integração rápidos, poucos e2e caros); **o gate é mecânico**
(o que importa **falha o build**, não fica em relatório); **o teste é determinístico** (sem flaky — o `conftest`
já zera o rate-limit entre testes); e **o mais crítico tem cobertura obrigatória** — o **login código-só** (P1)
e o **isolamento por escola** (P15) já são testados **sempre**; a **acessibilidade** (P11) e o **erro que nunca
pune** (P6) ganham cobertura **na medida em que a superfície existe** (ver a nota de limitação Q0 abaixo).

Conexão com os **Princípios Imutáveis** ([01](01-principios-imutaveis.md)): **P1** (login código-só) e **P15**
(isolamento) já têm suíte; **P11** (acessibilidade) **passará a ter** cobertura automatizada + playtest (quando
adotado — §15/Q3); **P13** (servidor autoridade) é **exercitado** pelos e2e reais e ganha asserção dedicada em
Q10; **P17** (piso de desempenho) vira o **teste de carga** do pico.

> **Nota de limitação Q0.** O `axe-core` audita apenas **DOM/texto** (`apps/web`); o **canvas 3D** do `apps/quest`
> (Three.js/R3F) e o **contraste não-textual** (3:1) **não** são cobertos por axe — dependem do **playtest com
> não-leitor** e do **playtest com som desligado** (manuais, Seção [13](13-acessibilidade.md) §14) + da **auditoria
> A3** (Seção [15](15-arte-audio-assets.md)) até existirem testes de `apps/quest` (Q6). O **erro nunca pune** (P6)
> tem duas facetas: a de **segurança** (o limitador `(código,IP)` não derruba a turma) **já é testada**
> (`test_quest_auth`); a de **game-design** (resposta errada não pune a criança) fica **diferida** até o motor do
> Quest existir (Q8/§8).

### 4. Experiência que o jogador deve sentir
**A criança não sente o QA — ela sente a ausência de bugs.** Um jogo que não trava, não perde o progresso, não
expõe seu dado, não a deixa presa numa tela sem áudio. **O adulto** (escola/família) confia porque o produto é
**testado a sério**. **A equipe** libera com **coragem**: o CT vermelho impede o erro de chegar à produção, e o
verde dá a segurança de que os invariantes seguem de pé.

### 5. Fluxo completo
O **ciclo de vida de um teste**, do commit ao release. **Fluxo-alvo** (hoje, na Q0, valem os passos 1–2; os passos
3–5 estão **pendentes de adoção** — §15; o passo 6 aguarda o motor do Quest):

1. **Local** — o dev roda a suíte (pytest/vitest) antes de abrir o PR.
2. **CI (gate)** — o pipeline (mecanismo = Seção [14](14-infra-deploy-dr.md)) roda **lint+typecheck → unit+cobertura
   → componente+cobertura → e2e → build/docker**; a meta é que **cobertura abaixo da meta falhe** o build (Q2 — hoje
   a cobertura é medida sem falhar).
3. **Acessibilidade** — o **axe-core** passará a rodar nos e2e/componente (contraste/rótulos/foco — Q3, quando
   adotado); o **playtest com não-leitor** e o **playtest com som desligado** (Seção [13](13-acessibilidade.md) §14)
   são critério de **Done** manual, na granularidade que a Seção [13](13-acessibilidade.md) define (**gate por tela**).
4. **Contrato** — o **schema OpenAPI** será validado (schemathesis) na fronteira API↔cliente (Q5, quando adotado).
5. **Carga** — proposta: **antes de cada temporada**, o **teste de carga do pico 7h30** roda (⚠️ §15/Q4; método = 18;
   capacidade/execução/cadência = Seção [14](14-infra-deploy-dr.md)).
6. **Telemetria** — testes asseveram que o **servidor deriva do ledger imutável** os eventos que a Seção
   [17](17-telemetria-metricas.md) definiu (fonte primária, P13/P14), mais a instrumentação suplementar do cliente
   (Q8, quando o motor existir).
7. **Merge** — só com **todos os gates verdes**; o DoD de QA (Q12) é satisfeito e reflete no Apêndice F.

### 6. Interface (quando existir)
**N/A** — capítulo de processo, sem UI de criança. Superfícies de QA: o **painel do CI** (status dos jobs), o
**relatório de cobertura** (Codecov/artefato) e o **relatório do teste de carga**. O **painel** é operado pela
Seção [14](14-infra-deploy-dr.md); a 18 define **o que** cada um deve mostrar.

### 7. UX
A "UX de QA" é para a **equipe**: testes **rápidos e determinísticos** (base da pirâmide), **mensagens de falha
claras**, e um **gate óbvio** (vermelho = não passa). Testes **flaky** são tratados como **bug** (quarentena +
correção), nunca como ruído aceitável.

### 8. Game Design
**N/A** — a 18 **testa** o jogo, não o cria. Nota: a **economia do Edu** (normalização/pesos do ranking do lado
servidor) **já é testada** (`test_scoring.py`); os **invariantes do jogo Quest** (erro nunca pune — P6; teto =
celebração; economia auditável do jogo) entram como **casos de teste** quando o **motor do Quest** for implementado
(hoje o `quest_tentativas` não é populado em produção — Seção [17](17-telemetria-metricas.md)).

### 9. Regras de negócio
As **normas de QA** (a fonte da estratégia; o **mecanismo** de CI é da Seção [14](14-infra-deploy-dr.md), a
**norma** de acessibilidade da Seção [13](13-acessibilidade.md)):

| # | Norma | Regra | Fronteira |
|---|-------|-------|-----------|
| Q1 | **Pirâmide** | base ampla de **unit/integração** (rápidos), camada média de **componente**, topo enxuto de **e2e** (caros); cada suíte existente tem papel definido | 18 |
| Q2 | **Cobertura com gate** | meta por camada vira **gate bloqueante** — `--cov-fail-under` (pytest) + `coverage.thresholds` (Vitest); hoje a cobertura é medida **sem** falhar | 18 ⚠️ (número — §15) |
| Q3 | **Acessibilidade testável** | **axe-core** nos e2e/componente (contraste/rótulos/foco — só DOM/texto); **playtest com não-leitor** + **playtest com som desligado** = critério de Done (Seção [13](13-acessibilidade.md) §14); auditoria de contraste **A3** no CI (valores = Seção [15](15-arte-audio-assets.md); norma/limiar = Seção [13](13-acessibilidade.md)) | 18 (método) ⚠️ (adoção do gate — §15); norma/valor = [13](13-acessibilidade.md)/[15](15-arte-audio-assets.md) |
| Q4 | **Teste de carga** | **método** do pico **7h30**: perfil de carga (**login-storm** da turma inteira às 7h30, rampa/duração) e métricas de aprovação (**taxa de sucesso do login do aluno**, **p95 de latência do login**, **taxa de erro global**); a **capacidade** (nº de dispositivos/concorrência) e a **execução** são da Seção [14](14-infra-deploy-dr.md) | 18 (método) ⚠️ (ferramenta/números-limiar — §15); capacidade = [14](14-infra-deploy-dr.md) |
| Q5 | **Contract test** | validação do **contrato** na fronteira API↔web/quest/mobile (proposta: **schemathesis** sobre o OpenAPI) | 18 ⚠️ (adoção — §15) |
| Q6 | **Cobertura de todos os apps** | mínimo de teste para `apps/quest` (Three.js/R3F), `apps/mobile` e `packages/*` (hoje só typecheck) | 18 ⚠️ (mínimo — §15) |
| Q7 | **Regressão** | suíte de **não-regressão** dos invariantes; e2e ampliado para **cross-browser + viewport mobile** (o Quest é usado em **tablet**) | 18 ⚠️ (escopo — §15) |
| Q8 | **Teste de telemetria** | asseverar que o **servidor deriva do ledger imutável** os eventos que a Seção [17](17-telemetria-metricas.md) definiu (fonte primária, P13/P14), mais a instrumentação **suplementar** do cliente (não lista eventos — isso é da 17) | 18 (teste); taxonomia = [17](17-telemetria-metricas.md) |
| Q9 | **Dados de teste** | **sintéticos/determinísticos** (além do `seed_e2e.py`); **nunca** dado real de criança fora de produção (Seções [14](14-infra-deploy-dr.md) O18/[12](12-seguranca-privacidade.md)) | 18; regra = [12](12-seguranca-privacidade.md) |
| Q10 | **Segurança testada** | **RBAC/isolamento por escola** (P15), **login código-só** (P1), **servidor é autoridade** (P13 — servidor rejeita estado/pontuação forjada pelo cliente; hoje `test_scoring` cobre o cálculo server-side, a economia do jogo entra com o motor) e **child-safety** têm cobertura obrigatória (já parcial: `test_permissoes`/`test_quest_auth`/`test_scoring`); a **política** é da Seção [12](12-seguranca-privacidade.md) | 18 (cobertura); política = [12](12-seguranca-privacidade.md) |
| Q11 | **CI é o gate** | o pipeline **bloqueia** o merge; a 18 define **o que** roda e o **critério**; o **como/onde** é o `ci.yml` da Seção [14](14-infra-deploy-dr.md) | 18 define; mecanismo = [14](14-infra-deploy-dr.md) |
| Q12 | **DoD de QA** | a **definição de pronto** por tipo de mudança (backend/UI/conteúdo-config) — a 18 é a **fonte** (as normas Q1–Q14 + o esboço por tipo do §14) e **alimenta** o Apêndice F, que consolida | 18 → Apêndice F ⚠️ (virar check no CI? — §15) |
| Q13 | **Determinismo** | testes **determinísticos** (o `conftest` já zera o rate-limit); **flaky = bug** (quarentena + correção), nunca ruído aceito | 18 |
| Q14 | **Isolamento de teste** | cada teste é **independente** (banco em memória por teste, sem estado compartilhado); e2e sobem ambiente **real** e efêmero | 18 |

### 10. Arquitetura técnica
Onde o QA **toca** o código:
- **Backend** — `pytest` sobre `conftest.py` (SQLite em memória, TestClient, fixtures); a meta de cobertura vira
  `--cov-fail-under` (Q2). Novos: contract test (`schemathesis` sobre o OpenAPI do FastAPI), teste de telemetria.
- **Web** — `Vitest` + Testing Library (`vitest.config.ts`); `coverage.thresholds` (Q2); `axe-core` nos
  componentes/e2e (Q3).
- **E2E** — `Playwright` (`playwright.config.ts`) sobe backend+frontend reais (`seed_e2e.py`); amplia para
  cross-browser + viewport mobile (Q7) e integra `@axe-core/playwright` (Q3).
- **Quest/Mobile/Packages** — introduzir unit/e2e mínimos (Q6) — hoje só typecheck.
- **Carga** — ferramenta de carga (k6/locust — ⚠️) contra o ambiente que a Seção [14](14-infra-deploy-dr.md) provisiona.
- **CI** — o `ci.yml` (Seção [14](14-infra-deploy-dr.md)) ganha os gates novos; a 18 define os critérios, não edita o mecanismo.

### 11. Dependências com outros módulos
**Consome / testa:**
- **Seção [14](14-infra-deploy-dr.md)** — o **mecanismo** de CI/CD e a **capacidade** do teste de carga.
- **Seção [13](13-acessibilidade.md)** — a **norma** de acessibilidade (a 18 dá o método de teste + playtest).
- **Seção [15](15-arte-audio-assets.md)** — os **valores** de contraste (A3; norma/limiar = Seção [13](13-acessibilidade.md)) que a 18 estrutura como gate, e o **ponteiro** de validação de **peso/formato** de asset no CI (orçamento = Seção [15](15-arte-audio-assets.md) A13; piso de device = Seção [11](11-arquitetura.md)).
- **Seção [17](17-telemetria-metricas.md)** — a **taxonomia** cuja instrumentação a 18 testa.
- **Seção [11](11-arquitetura.md)** — o **mecanismo/contratos** que a 18 exercita.
- **Seção [12](12-seguranca-privacidade.md)** — a **política** cuja aplicação (RBAC/isolamento) a 18 cobre.

**Alimenta:**
- **Apêndice F** — a **parte de QA** dos checklists consolidados de DoD.
- **Seção [14](14-infra-deploy-dr.md)** — os **critérios** que os gates do `ci.yml` aplicam.

**O que quebra se mudar:** se a Seção [11](11-arquitetura.md) mudar um **contrato**, a 18 **atualiza** o contract
test; se a Seção [13](13-acessibilidade.md) mudar a **norma**, a 18 **reajusta** o gate de acessibilidade; se a
Seção [14](14-infra-deploy-dr.md) mudar o **CI**, a 18 **re-encaixa** os gates.

### 12. Casos extremos (Edge Cases)
- **Teste flaky** → quarentena imediata + correção (Q13); nunca "re-roda até passar".
- **Cobertura cai abaixo da meta** → build **falha** (Q2); PR não passa.
- **Novo endpoint sem contract test** → gate barra (Q5, quando adotado).
- **Regressão de acessibilidade** (contraste quebrado, foco perdido) → axe **falha** o build (Q3, quando adotado).
- **Dado real de criança num teste** → **proibido** (Q9); usar sintético/determinístico.
- **e2e depende de estado externo** → não: sobe ambiente real e efêmero (Q14).
- **Pico 7h30 acima da capacidade** → o teste de carga **reprova** antes da temporada (Q4).
- **Motor do Quest ainda não implementado** → os invariantes de jogo (P6) entram como teste **quando** o
  `quest_tentativas` for populado; hoje o gate cobre o que existe.
- **Mudança só de conteúdo/config** → DoD mais leve (Q12), mas os invariantes de segurança/acessibilidade seguem obrigatórios.

### 13. Escalabilidade futura
- **Cobertura de `apps/quest`** (Three.js/R3F) — testes de render/estado quando o motor amadurecer (Q6).
- **Regressão visual/snapshot** — para a UI e o personagem 3D.
- **Validação de peso/formato de asset no CI** — o ponteiro que a Seção [15](15-arte-audio-assets.md) §13 encaminha à 18 (orçamento de peso = Seção [15](15-arte-audio-assets.md) A13; piso de device = Seção [11](11-arquitetura.md)).
- **Auditoria de alvo de toque/espaçamento** (N1) — como o `axe-core` **não** audita tamanho de alvo, fica no **gate manual por-tela** da Seção [13](13-acessibilidade.md) §14 (ou em teste dedicado de CSS) até haver cobertura própria.
- **Cross-browser + mobile viewport** no e2e (Q7).
- **Teste de carga contínuo** — parte do game day (Seção [14](14-infra-deploy-dr.md)).
- **Mutation testing** e **property-based** para as regras de economia/BNCC.
- **Contract test** ampliado para o mobile e o Hub.

### 14. Checklist de implementação
**"Pronto quando" (liga ao Apêndice F). Itens ⚠️ dependem de decisão do dono (§15) antes de virarem gate:**
- [ ] **Pirâmide** documentada (papel de cada suíte: pytest/Vitest/Playwright) (Q1).
- [ ] ⚠️ **Gate de cobertura** ativo — `--cov-fail-under` (pytest) + `coverage.thresholds` (Vitest); build **falha** abaixo da meta (Q2 — número pende §15).
- [ ] ⚠️ **Acessibilidade** — `axe-core` nos e2e/componente + auditoria A3 no CI; **playtest com não-leitor** e **com som desligado** no DoD (Q3 — adoção pende §15).
- [ ] ⚠️ **Contract test** (schemathesis/OpenAPI) na fronteira API↔cliente (Q5 — adoção pende §15).
- [ ] ⚠️ **Teste de carga** do pico 7h30 com critérios de aprovação (método = 18; capacidade = Seção [14](14-infra-deploy-dr.md)) (Q4 — pende §15).
- [ ] ⚠️ **Cobertura mínima** de `apps/quest`/`apps/mobile`/`packages/*` (Q6 — mínimo pende §15).
- [ ] ⚠️ **Regressão** dos invariantes + e2e **cross-browser/mobile viewport** (Q7 — escopo pende §15).
- [ ] **Teste de telemetria** (servidor deriva do ledger os eventos da Seção [17](17-telemetria-metricas.md)) (Q8).
- [ ] **Dados de teste sintéticos** (nunca dado real de criança — Q9); testes **determinísticos e isolados** (banco em memória por teste, sem estado compartilhado), flaky = bug (Q13, Q14).
- [ ] **Segurança** (RBAC/isolamento P15, login código-só P1, **servidor é autoridade** P13, child-safety) com cobertura obrigatória (Q10).
- [ ] **CI bloqueia o merge** com todos os gates verdes (Q11).
- [ ] **DoD de QA** por tipo de mudança, refletido no **Apêndice F** (Q12).

### 15. Questões em aberto
Cada item é **decisão do dono** (⚠️); os defaults são **propostas** da 18, não decisões autônomas:

- ⚠️ **Q2 — Meta de cobertura.** A 18 já decide que a cobertura **vira gate bloqueante** (ADR-18-A); resta ao dono
  cravar o **número** por camada (proposta: backend ≥ 80% de linhas, web ≥ 70%) e o **momento de ativar**
  (`--cov-fail-under`/`thresholds`) — hoje o CI mede sem falhar.
- ⚠️ **Q4 — Teste de carga.** É requisito de release **agora** ou plano futuro? Ferramenta (**k6** proposto) e os
  **números-limiar de aprovação** (p95 de latência do login, taxa de erro global, taxa de sucesso do login)
  **sobre** o perfil de carga; o **nº de dispositivos/concorrência** no pico 7h30 é insumo de **capacidade** da
  Seção [14](14-infra-deploy-dr.md).
- ⚠️ **Q3 — Acessibilidade automatizada.** Adotar **axe-core** como gate no CI, e como **operacionalizar** o
  playtest com não-leitor (frequência, quem conduz) — a **norma** é da Seção [13](13-acessibilidade.md).
- ⚠️ **Q5 — Contract test.** Vale o custo **agora** (schemathesis sobre o OpenAPI) ou confiamos nos e2e por enquanto?
- ⚠️ **Q6 — Cobertura de quest/mobile/packages.** Ficam em **typecheck** na Q0 ou a 18 exige um **mínimo** de
  unit/e2e já nesta versão?
- ⚠️ **Q7 — e2e cross-browser/mobile.** Continua **só chromium/Desktop** ou amplia para **viewport mobile/tablet**
  (o Quest é a plataforma da criança)?
- ⚠️ **Q12 — DoD como gate.** O DoD de QA vira **check obrigatório** no CI, ou permanece **checklist humano** no Apêndice F?

### 16. ADR (Architecture Decision Record)
- **ADR-18-A — Pirâmide real com gate mecânico.** A base é unit/integração (pytest) + componente (Vitest), o topo
  é e2e (Playwright) sobre ambiente **real**; a **cobertura vira gate** (`--cov-fail-under`/`thresholds`) — o que
  importa **falha o build**, não fica em relatório. *Números pendentes (§15).*
- **ADR-18-B — Acessibilidade testada, não presumida.** `axe-core` no CI (contraste/rótulos/foco — só DOM/texto) +
  auditoria A3 (valores da Seção [15](15-arte-audio-assets.md); norma/limiar da Seção [13](13-acessibilidade.md));
  o **playtest com não-leitor** e o **playtest com som desligado** (Seção [13](13-acessibilidade.md) §14) são
  critério de **Done** manual. A 18 dá o **método**, a norma/valor ficam em 13/15.
- **ADR-18-C — A 18 define o que testar; a 14 opera o CI.** Os **critérios** e a **estratégia** são da 18; o
  **mecanismo/execução** (jobs do `ci.yml`, teste de carga) é da Seção [14](14-infra-deploy-dr.md); a 18 **não**
  edita o pipeline, só **exige** os gates.
- **ADR-18-D — Determinismo e dado sintético.** Testes **determinísticos** (banco em memória, reset de rate-limit),
  **flaky = bug**; dados **sintéticos e determinísticos** (gerados, ex. faker/fixture), **nunca** dado real de
  criança nem **derivado/anonimizado** dele (Seções [12](12-seguranca-privacidade.md)/[14](14-infra-deploy-dr.md)).
  A 18 é a **fonte da parte de QA** do Apêndice F.

*Decisões cross-módulo não são improvisadas aqui: as pendências acima viram ADR ou item de §15.*

---

## 🇬🇧 QA & Testing Strategy

### 1. Objective
To be the **definitive QA and testing reference** for Constela Quest: **how we prove the product works, is secure
and is accessible** before it reaches the child — with a real test **pyramid**, quality **gates** in CI and a
clear **DoD**. It decides the **strategy and acceptance criteria**; it does **not** decide the CI/CD **mechanism**
(Section [14](14-infra-deploy-dr.md)), the accessibility **norm** (Section [13](13-acessibilidade.md)), the
**values** (Section [15](15-arte-audio-assets.md)) nor the **policy** (Section [12](12-seguranca-privacidade.md))
— it only **tests** them. It is the source of the QA part that **feeds** Appendix F.

### 2. Context
In the **Hub → Edu → Quest** ecosystem, every release touches a **child's data** — a bug can expose, punish or
frustrate whoever entrusted their child/student. **Current state (Q0) — the pyramid already exists, the gates are
missing:**
- **Unit/integration (backend)** — **29** `test_*.py` (pytest) over `conftest.py` (in-memory SQLite, TestClient,
  fixtures, rate-limit reset): they cover **RBAC/roles**, **real FK cascade** (PRAGMA `foreign_keys=ON`),
  **passwordless child login** (code=credential, QR, per-`(code,IP)` limiter that does not punish the class,
  inactive student, Edu/Quest token isolation), the **scoring engine** (`test_scoring.py` — Matific/Elefante
  normalization, the "most critical part of the system"), auth/reset, **Alembic**, observability.
- **Component (web)** — **13** `*.test.tsx` (Vitest + Testing Library), including `edge-cases.test.tsx` (negative
  RBAC, validation, incomplete API responses).
- **E2E** — **7** Playwright specs that boot the **real backend and frontend** (`seed_e2e.py`); serial, CI
  retries, **chromium/Desktop only**.
- **CI** — `ci.yml` with **6 blocking jobs** (`lint` = ruff+typecheck; `test-backend` = pytest+cov; `test-web` =
  vitest+cov; `build`; `e2e`; `docker`); the security scan (pip-audit/npm audit/Trivy) is a separate workflow
  (`security.yml`), not counted as a `ci.yml` job. Coverage is **measured** and published, **but never fails the
  build** (no `--cov-fail-under` in pytest nor `coverage.thresholds` in Vitest).
- **Not yet present** — a **load**/peak test (no k6/locust); **automated accessibility** (no axe; Section
  [13](13-acessibilidade.md)'s non-reader playtest is manual; Section [15](15-arte-audio-assets.md)'s A3 audit is
  not in CI); **contract test** (no schemathesis/pact); **tests in `apps/quest`** (Three.js/R3F — typecheck only),
  `apps/mobile` and `packages/*`; visual regression; cross-browser/mobile e2e.

This chapter **formalizes** the pyramid, defines the **gates** and the **method** of the missing tests.

### 3. Feature philosophy
**"A test is the seatbelt of whoever entrusted the child to us."** Quality is not optional in a children's
product: the test **proves** the invariants before the child feels the error. Guiding QA principles: **the pyramid
is wide at the base** (many fast unit/integration, few costly e2e); **the gate is mechanical** (what matters
**fails the build**, not a report); **the test is deterministic** (no flaky — `conftest` already resets the
rate-limit between tests); and **the most critical has mandatory coverage** — the **code-only login** (P1) and the
**per-school isolation** (P15) are **always** tested; **accessibility** (P11) and the **error that never punishes**
(P6) gain coverage **to the extent the surface exists** (see the Q0 limitation note below).

Link to the **Immutable Principles** ([01](01-principios-imutaveis.md)): **P1** (code-only login) and **P15**
(isolation) already have suites; **P11** (accessibility) **will gain** automated coverage + playtest (once adopted
— §15/Q3); **P13** (server authority) is **exercised** by the real e2e and gains a dedicated assertion in Q10;
**P17** (performance floor) becomes the peak **load test**.

> **Q0 limitation note.** `axe-core` audits only the **DOM/text** (`apps/web`); the **3D canvas** of `apps/quest`
> (Three.js/R3F) and **non-text contrast** (3:1) are **not** covered by axe — they rely on the **non-reader
> playtest** and the **sound-off playtest** (manual, Section [13](13-acessibilidade.md) §14) + the **A3 audit**
> (Section [15](15-arte-audio-assets.md)) until `apps/quest` tests exist (Q6). The **error never punishes** (P6)
> has two facets: the **security** one (the `(code,IP)` limiter does not take down the class) is **already tested**
> (`test_quest_auth`); the **game-design** one (a wrong answer does not punish the child) is **deferred** until the
> Quest engine exists (Q8/§8).

### 4. The experience the player should feel
**The child does not feel the QA — they feel the absence of bugs.** A game that does not crash, does not lose
progress, does not expose their data, does not trap them on a screen with no audio. **The adult** (school/family)
trusts because the product is **seriously tested**. **The team** ships with **courage**: a red CT stops the error
from reaching production, and green gives the assurance that the invariants still stand.

### 5. Complete flow
The **lifecycle of a test**, from commit to release. **Target flow** (today, in Q0, steps 1–2 hold; steps 3–5 are
**pending adoption** — §15; step 6 awaits the Quest engine):

1. **Local** — the dev runs the suite (pytest/vitest) before opening the PR.
2. **CI (gate)** — the pipeline (mechanism = Section [14](14-infra-deploy-dr.md)) runs **lint+typecheck →
   unit+coverage → component+coverage → e2e → build/docker**; the goal is for **coverage below the target to fail**
   the build (Q2 — today coverage is measured without failing).
3. **Accessibility** — **axe-core** will run in the e2e/component (contrast/labels/focus — Q3, once adopted); the
   **non-reader playtest** and the **sound-off playtest** (Section [13](13-acessibilidade.md) §14) are a manual
   **Done** criterion, at the granularity Section [13](13-acessibilidade.md) defines (**per-screen gate**).
4. **Contract** — the **OpenAPI schema** will be validated (schemathesis) at the API↔client boundary (Q5, once adopted).
5. **Load** — proposal: **before each season**, the **7:30 a.m. peak load test** runs (⚠️ §15/Q4; method = 18;
   capacity/execution/cadence = Section [14](14-infra-deploy-dr.md)).
6. **Telemetry** — tests assert that the **server derives from the immutable ledger** the events Section
   [17](17-telemetria-metricas.md) defined (primary source, P13/P14), plus the supplementary client instrumentation
   (Q8, once the engine exists).
7. **Merge** — only with **all gates green**; the QA DoD (Q12) is satisfied and reflected in Appendix F.

### 6. Interface (when it exists)
**N/A** — a process chapter, no child UI. QA surfaces: the **CI panel** (job status), the **coverage report**
(Codecov/artifact) and the **load-test report**. The **panel** is operated by Section [14](14-infra-deploy-dr.md);
18 defines **what** each must show.

### 7. UX
The "QA UX" is for the **team**: **fast, deterministic** tests (pyramid base), **clear failure messages**, and an
**obvious gate** (red = no pass). **Flaky** tests are treated as a **bug** (quarantine + fix), never as accepted noise.

### 8. Game Design
**N/A** — 18 **tests** the game, does not create it. Note: the **Edu economy** (server-side ranking normalization/
weights) is **already tested** (`test_scoring.py`); the **Quest game invariants** (error never punishes — P6; cap =
celebration; auditable game economy) enter as **test cases** once the **Quest engine** is implemented (today
`quest_tentativas` is not populated in production — Section [17](17-telemetria-metricas.md)).

### 9. Business rules
The **QA norms** (the source of the strategy; the CI **mechanism** is Section [14](14-infra-deploy-dr.md)'s, the
accessibility **norm** Section [13](13-acessibilidade.md)'s):

| # | Norm | Rule | Boundary |
|---|------|------|----------|
| Q1 | **Pyramid** | a wide base of **unit/integration** (fast), a middle **component** layer, a lean top of **e2e** (costly); each existing suite has a defined role | 18 |
| Q2 | **Coverage with a gate** | the per-layer target becomes a **blocking gate** — `--cov-fail-under` (pytest) + `coverage.thresholds` (Vitest); today coverage is measured **without** failing | 18 ⚠️ (number — §15) |
| Q3 | **Testable accessibility** | **axe-core** in e2e/component (contrast/labels/focus — DOM/text only); **non-reader playtest** + **sound-off playtest** = Done criterion (Section [13](13-acessibilidade.md) §14); contrast audit **A3** in CI (values = Section [15](15-arte-audio-assets.md); norm/threshold = Section [13](13-acessibilidade.md)) | 18 (method) ⚠️ (gate adoption — §15); norm/value = [13](13-acessibilidade.md)/[15](15-arte-audio-assets.md) |
| Q4 | **Load test** | the **method** for the **7:30 a.m.** peak: load profile (**login-storm** of the whole class at 7:30, ramp/duration) and acceptance metrics (**student-login success rate**, **p95 login latency**, **global error rate**); the **capacity** (device count/concurrency) and **execution** are Section [14](14-infra-deploy-dr.md)'s | 18 (method) ⚠️ (tool/threshold-numbers — §15); capacity = [14](14-infra-deploy-dr.md) |
| Q5 | **Contract test** | **contract** validation at the API↔web/quest/mobile boundary (proposal: **schemathesis** over OpenAPI) | 18 ⚠️ (adoption — §15) |
| Q6 | **All apps covered** | a minimum of tests for `apps/quest` (Three.js/R3F), `apps/mobile` and `packages/*` (today typecheck only) | 18 ⚠️ (minimum — §15) |
| Q7 | **Regression** | a **non-regression** suite of the invariants; e2e widened to **cross-browser + mobile viewport** (Quest is used on **tablet**) | 18 ⚠️ (scope — §15) |
| Q8 | **Telemetry test** | assert that the **server derives from the immutable ledger** the events Section [17](17-telemetria-metricas.md) defined (primary source, P13/P14), plus the **supplementary** client instrumentation (does not list events — that is 17's) | 18 (test); taxonomy = [17](17-telemetria-metricas.md) |
| Q9 | **Test data** | **synthetic/deterministic** (beyond `seed_e2e.py`); **never** real child data outside production (Sections [14](14-infra-deploy-dr.md) O18/[12](12-seguranca-privacidade.md)) | 18; rule = [12](12-seguranca-privacidade.md) |
| Q10 | **Security tested** | **RBAC/per-school isolation** (P15), **code-only login** (P1), **server is authority** (P13 — the server rejects state/score forged by the client; today `test_scoring` covers the server-side calculation, the game economy arrives with the engine) and **child-safety** have mandatory coverage (already partial: `test_permissoes`/`test_quest_auth`/`test_scoring`); the **policy** is Section [12](12-seguranca-privacidade.md)'s | 18 (coverage); policy = [12](12-seguranca-privacidade.md) |
| Q11 | **CI is the gate** | the pipeline **blocks** the merge; 18 defines **what** runs and the **criterion**; the **how/where** is Section [14](14-infra-deploy-dr.md)'s `ci.yml` | 18 defines; mechanism = [14](14-infra-deploy-dr.md) |
| Q12 | **QA DoD** | the **definition of done** per change type (backend/UI/content-config) — 18 is the **source** (the Q1–Q14 norms + the §14 per-type sketch) and **feeds** Appendix F, which consolidates | 18 → Appendix F ⚠️ (become a CI check? — §15) |
| Q13 | **Determinism** | **deterministic** tests (`conftest` already resets the rate-limit); **flaky = bug** (quarantine + fix), never accepted noise | 18 |
| Q14 | **Test isolation** | each test is **independent** (per-test in-memory DB, no shared state); e2e boot a **real** ephemeral environment | 18 |

### 10. Technical architecture
Where QA **touches** code:
- **Backend** — `pytest` over `conftest.py` (in-memory SQLite, TestClient, fixtures); the coverage target becomes
  `--cov-fail-under` (Q2). New: contract test (`schemathesis` over FastAPI's OpenAPI), telemetry test.
- **Web** — `Vitest` + Testing Library (`vitest.config.ts`); `coverage.thresholds` (Q2); `axe-core` in
  components/e2e (Q3).
- **E2E** — `Playwright` (`playwright.config.ts`) boots the real backend+frontend (`seed_e2e.py`); widened to
  cross-browser + mobile viewport (Q7) and integrating `@axe-core/playwright` (Q3).
- **Quest/Mobile/Packages** — introduce minimal unit/e2e (Q6) — today typecheck only.
- **Load** — a load tool (k6/locust — ⚠️) against the environment Section [14](14-infra-deploy-dr.md) provisions.
- **CI** — Section [14](14-infra-deploy-dr.md)'s `ci.yml` gains the new gates; 18 defines the criteria, does not edit the mechanism.

### 11. Dependencies on other modules
**Consumes / tests:**
- **Section [14](14-infra-deploy-dr.md)** — the CI/CD **mechanism** and the load-test **capacity**.
- **Section [13](13-acessibilidade.md)** — the accessibility **norm** (18 gives the test method + playtest).
- **Section [15](15-arte-audio-assets.md)** — the contrast **values** (A3; norm/threshold = Section [13](13-acessibilidade.md)) that 18 structures as a gate, and the **pointer** for asset weight/format validation in CI (budget = Section [15](15-arte-audio-assets.md) A13; device floor = Section [11](11-arquitetura.md)).
- **Section [17](17-telemetria-metricas.md)** — the **taxonomy** whose instrumentation 18 tests.
- **Section [11](11-arquitetura.md)** — the **mechanism/contracts** 18 exercises.
- **Section [12](12-seguranca-privacidade.md)** — the **policy** whose application (RBAC/isolation) 18 covers.

**Feeds:**
- **Appendix F** — the **QA part** of the consolidated DoD checklists.
- **Section [14](14-infra-deploy-dr.md)** — the **criteria** the `ci.yml` gates apply.

**What breaks if it changes:** if Section [11](11-arquitetura.md) changes a **contract**, 18 **updates** the
contract test; if Section [13](13-acessibilidade.md) changes the **norm**, 18 **re-tunes** the accessibility gate;
if Section [14](14-infra-deploy-dr.md) changes the **CI**, 18 **re-fits** the gates.

### 12. Edge cases
- **Flaky test** → immediate quarantine + fix (Q13); never "re-run until it passes".
- **Coverage drops below target** → the build **fails** (Q2); the PR does not pass.
- **New endpoint without a contract test** → the gate blocks (Q5, once adopted).
- **Accessibility regression** (broken contrast, lost focus) → axe **fails** the build (Q3, once adopted).
- **Real child data in a test** → **forbidden** (Q9); use synthetic/deterministic.
- **e2e depends on external state** → no: it boots a real ephemeral environment (Q14).
- **7:30 a.m. peak above capacity** → the load test **fails** before the season (Q4).
- **The Quest engine is not yet implemented** → the game invariants (P6) enter as tests **when** `quest_tentativas`
  is populated; today the gate covers what exists.
- **Content/config-only change** → a lighter DoD (Q12), but the security/accessibility invariants remain mandatory.

### 13. Future scalability
- **`apps/quest` coverage** (Three.js/R3F) — render/state tests as the engine matures (Q6).
- **Visual/snapshot regression** — for the UI and the 3D character.
- **Asset weight/format validation in CI** — the pointer Section [15](15-arte-audio-assets.md) §13 forwards to 18 (weight budget = Section [15](15-arte-audio-assets.md) A13; device floor = Section [11](11-arquitetura.md)).
- **Touch-target/spacing audit** (N1) — since `axe-core` does **not** audit target size, it stays in Section [13](13-acessibilidade.md) §14's **manual per-screen gate** (or a dedicated CSS test) until it has its own coverage.
- **Cross-browser + mobile viewport** in e2e (Q7).
- **Continuous load test** — part of the game day (Section [14](14-infra-deploy-dr.md)).
- **Mutation testing** and **property-based** for the economy/BNCC rules.
- **Contract test** widened to mobile and the Hub.

### 14. Implementation checklist
**"Done when" (links to Appendix F). Items marked ⚠️ depend on an owner decision (§15) before becoming a gate:**
- [ ] **Pyramid** documented (role of each suite: pytest/Vitest/Playwright) (Q1).
- [ ] ⚠️ **Coverage gate** active — `--cov-fail-under` (pytest) + `coverage.thresholds` (Vitest); the build **fails** below the target (Q2 — number pending §15).
- [ ] ⚠️ **Accessibility** — `axe-core` in e2e/component + A3 audit in CI; **non-reader playtest** and **sound-off playtest** in the DoD (Q3 — adoption pending §15).
- [ ] ⚠️ **Contract test** (schemathesis/OpenAPI) at the API↔client boundary (Q5 — adoption pending §15).
- [ ] ⚠️ **Load test** of the 7:30 a.m. peak with acceptance criteria (method = 18; capacity = Section [14](14-infra-deploy-dr.md)) (Q4 — pending §15).
- [ ] ⚠️ **Minimum coverage** of `apps/quest`/`apps/mobile`/`packages/*` (Q6 — minimum pending §15).
- [ ] ⚠️ **Regression** of the invariants + **cross-browser/mobile-viewport** e2e (Q7 — scope pending §15).
- [ ] **Telemetry test** (server derives Section [17](17-telemetria-metricas.md)'s events from the ledger) (Q8).
- [ ] **Synthetic test data** (never real child data — Q9); **deterministic and isolated** tests (per-test in-memory DB, no shared state), flaky = bug (Q13, Q14).
- [ ] **Security** (RBAC/isolation P15, code-only login P1, **server is authority** P13, child-safety) with mandatory coverage (Q10).
- [ ] **CI blocks the merge** with all gates green (Q11).
- [ ] **QA DoD** per change type, reflected in **Appendix F** (Q12).

### 15. Open questions
Each item is a **owner decision** (⚠️); the defaults are 18's **proposals**, not autonomous decisions:

- ⚠️ **Q2 — Coverage target.** 18 already decides that coverage **becomes a blocking gate** (ADR-18-A); the owner
  still has to set the per-layer **number** (proposal: backend ≥ 80% lines, web ≥ 70%) and the **moment to activate**
  it (`--cov-fail-under`/`thresholds`) — today CI measures without failing.
- ⚠️ **Q4 — Load test.** Is it a release requirement **now** or a future plan? Tool (**k6** proposed) and the
  **threshold acceptance numbers** (p95 login latency, global error rate, login success rate) **over** the load
  profile; the **device count/concurrency** at the 7:30 a.m. peak is a **capacity** input of Section
  [14](14-infra-deploy-dr.md).
- ⚠️ **Q3 — Automated accessibility.** Adopt **axe-core** as a CI gate, and how to **operationalize** the non-reader
  playtest (frequency, who runs it) — the **norm** is Section [13](13-acessibilidade.md)'s.
- ⚠️ **Q5 — Contract test.** Is it worth the cost **now** (schemathesis over OpenAPI) or do we trust the e2e for now?
- ⚠️ **Q6 — quest/mobile/packages coverage.** Do they stay at **typecheck** in Q0 or does 18 require a **minimum**
  of unit/e2e already in this version?
- ⚠️ **Q7 — cross-browser/mobile e2e.** Does it stay **chromium/Desktop only** or widen to **mobile/tablet
  viewport** (Quest is the child's platform)?
- ⚠️ **Q12 — DoD as a gate.** Does the QA DoD become a **required check** in CI, or remain a **human checklist** in Appendix F?

### 16. ADR (Architecture Decision Record)
- **ADR-18-A — Real pyramid with a mechanical gate.** The base is unit/integration (pytest) + component (Vitest),
  the top is e2e (Playwright) over a **real** environment; **coverage becomes a gate** (`--cov-fail-under`/`thresholds`)
  — what matters **fails the build**, not a report. *Numbers pending (§15).*
- **ADR-18-B — Accessibility tested, not assumed.** `axe-core` in CI (contrast/labels/focus — DOM/text only) + the
  A3 audit (Section [15](15-arte-audio-assets.md)'s values; Section [13](13-acessibilidade.md)'s norm/threshold);
  the **non-reader playtest** and the **sound-off playtest** (Section [13](13-acessibilidade.md) §14) are a manual
  **Done** criterion. 18 gives the **method**, the norm/value stay in 13/15.
- **ADR-18-C — 18 defines what to test; 14 operates the CI.** The **criteria** and **strategy** are 18's; the
  **mechanism/execution** (`ci.yml` jobs, load test) is Section [14](14-infra-deploy-dr.md)'s; 18 does **not** edit
  the pipeline, it only **requires** the gates.
- **ADR-18-D — Determinism and synthetic data.** **Deterministic** tests (in-memory DB, rate-limit reset),
  **flaky = bug**; **synthetic and deterministic** data (generated, e.g. faker/fixture), **never** real child data
  nor data **derived/anonymized** from it (Sections [12](12-seguranca-privacidade.md)/[14](14-infra-deploy-dr.md)).
  18 is the **source of the QA part** of Appendix F.

*Cross-module decisions are not improvised here: the pending items above become an ADR or a §15 entry.*
