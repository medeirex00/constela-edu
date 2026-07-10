# 16 — Localização & i18n / Localization & i18n

- **Status:** 🔴 rascunho / draft
- **Padrão / Standard:** [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) (16 partes)
- **Fontes / Sources:** `INDICE.md` (bloco 16, subseções 16.1–16.23 + espelho de decisões em aberto; ⚠️ 16.9/16.16/16.17/16.19/16.23), `_estado-atual/RELATORIO-2026-07-09.md` (Q0: pt-BR only, sem i18n), `packages/core/src/formato.ts` (`numero`/`nota`/`dataHora` via `toLocaleString("pt-BR")`; `tempoLeitura` formata min/h **à mão**), `apps/web/src/lib/formato.ts` (reexporta `@constela/core`), `apps/quest/src/audio/audio.ts` (`escolherVoz` pt-BR; `narrar` fixa `lang="pt-BR"` — a máquina de P9), `apps/quest/src/main.tsx` (@fontsource **latin-***) + `apps/web/src/main.tsx` (@fontsource `inter`/`poppins` **CSS default multi-subset**), `apps/quest/index.html` + `apps/web/index.html` (`<html lang="pt-BR">` fixo), strings hardcoded (`apps/quest/src/{entrada/Entrada,lobby/Lobby,cerimonia/Cerimonia}.tsx`), `toLocaleString`/`localeCompare` inline (`apps/web/src/{components/Grafico,pages/PerfilAluno,pages/Usuarios}.tsx`, `apps/mobile/src/telas/Painel.tsx`), Seções [01](01-principios-imutaveis.md)/[02](02-vocabulario.md)/[03](03-universo.md)/[06](06-pedagogico-bncc.md)/[07](07-ux-fluxos-navegacao.md)/[13](13-acessibilidade.md)/[14](14-infra-deploy-dr.md)/[15](15-arte-audio-assets.md)
- **Depende de / Depends on:** **Princípio 9** (narração **sempre em pt-BR** e áudio obrigatório — **imutável**) → [01](01-principios-imutaveis.md); **vocabulário lúdico canônico** pt-BR, **nomes próprios** e a **lista de palavras proibidas** (texto-fonte) → [02](02-vocabulario.md); **nomes próprios do universo** (planetas, Cosmo) → [03](03-universo.md); **códigos BNCC** e a regra **ERER sem autoria por IA** (conteúdo) → [06](06-pedagogico-bncc.md); **superfície** das telas, o **copy** editorial (inclui o rótulo de série) e a tolerância a **expansão de layout** (≥48px) → [07](07-ux-fluxos-navegacao.md); **norma** de áudio pt-BR obrigatório → [13](13-acessibilidade.md); **UTC no banco** (a formatação pt-BR é delegada a esta seção) → [14](14-infra-deploy-dr.md); **camada de clipes de áudio por idioma** e o **pipeline/precache de assets** (fontes por script) → [15](15-arte-audio-assets.md); **whitelist de preferências** do perfil (se idioma virar preferência) → [13](13-acessibilidade.md) (ADR-13-C).

> **Convenção / Convention:** "§N" = uma das 16 **partes deste capítulo** / one of the 16 **parts of this
> chapter** (ex.: "§15" = a Parte 15, Questões em aberto — **não** a Seção 15); "Seção NN" / "Section NN" =
> outro capítulo da Bible; "16.NN" = uma subseção do plano do `INDICE.md`.
> **Escopo / Scope:** este capítulo decide o **framework de internacionalização (i18n)** do Constela Quest — a
> **externalização de strings**, o **catálogo** de traduções, a **formatação regional** (pt-BR, delegada pela
> Seção [14](14-infra-deploy-dr.md)), a **pluralização**, a **seleção de locale** e **como um novo idioma
> entraria**. O Constela é **pt-BR-only por definição no lançamento** (Princípio 9). Ele **não** decide a
> **norma** de áudio pt-BR (Seção [13](13-acessibilidade.md)/P9), o **vocabulário** e os **nomes próprios**
> (Seções [02](02-vocabulario.md)/[03](03-universo.md)), o **copy** das telas (Seção [07](07-ux-fluxos-navegacao.md)),
> o **UTC** (Seção [14](14-infra-deploy-dr.md)) nem os **clipes de áudio/pipeline de assets** (Seção [15](15-arte-audio-assets.md))
> — apenas os **referencia** e os **prepara** para múltiplos idiomas. **Mudar o idioma do ÁUDIO obrigatório colide
> com P9 e é decisão do dono via ADR — nunca da 16 sozinha.**

---

## 🇧🇷 Localização & i18n

### 1. Objetivo
Ser a **referência definitiva de localização e internacionalização** do Constela Quest: o **framework** que mantém
o produto **impecável em pt-BR hoje** e **pronto** para um segundo idioma **amanhã, sem reescrita** — externalizando
strings, centralizando a formatação regional e desenhando o caminho de um novo idioma. Decide o **mecanismo de
i18n** e a **formatação pt-BR** (delegada pela Seção [14](14-infra-deploy-dr.md)); **não** decide a **norma** de
áudio pt-BR (Seção [13](13-acessibilidade.md)/**P9 — imutável**), o **vocabulário/nomes próprios** (Seções
[02](02-vocabulario.md)/[03](03-universo.md)), o **copy** (Seção [07](07-ux-fluxos-navegacao.md)) nem os **assets
de áudio/fonte** (Seção [15](15-arte-audio-assets.md)).

### 2. Contexto
No ecossistema **Hub → Edu → Quest**, o público é a **criança brasileira** e o **Princípio 9** crava **narração
sempre em pt-BR**. **Estado atual (Q0) — pt-BR-only, greenfield de i18n:**
- **Biblioteca de i18n** — **nenhuma** (grep por `i18next`/`react-i18next`/`formatjs`/`react-intl`/`@lingui` em
  todos os `package.json` = zero).
- **Strings de UI** — **hardcoded em pt-BR** direto nos componentes; **não** há catálogo central de textos (ex.:
  `Lobby.tsx` "Jogar"/"Vestiário"/"Carreira"; `Entrada.tsx` `placeholder="SOL1234"`/`aria-label`; `Cerimonia.tsx`).
- **Narração (P9)** — hardcoded pt-BR: `audio.ts` `escolherVoz()` prefere pt-BR local; `narrar()` fixa `lang="pt-BR"`;
  frases pt-BR inline nas chamadas `narrar()`.
- **Formatação data/número** — **parcialmente centralizada mas bypassada**: `packages/core/src/formato.ts` tem
  `numero`/`nota`/`dataHora` via `toLocaleString("pt-BR")` e `tempoLeitura` que formata **min/h à mão** (sem
  `toLocaleString`, sem `Intl.PluralRules`); **mas** há `toLocaleString("pt-BR")`/`localeCompare("…","pt-BR")`
  **inline** espalhados que ignoram o `formato.ts` (`Grafico.tsx`, `PerfilAluno.tsx`, `Usuarios.tsx`, mobile
  `Painel.tsx`…). **Nenhum** `Intl.DateTimeFormat`/`PluralRules`/`Collator`; **nenhuma** moeda (o Quest não tem
  dinheiro, só XP).
- **Detecção de locale** — **nenhuma** (sem `navigator.language`); o idioma é constante de compilação.
- **`<html lang>`** — fixo `"pt-BR"` nos dois `index.html`; sem troca em runtime.
- **Fontes** — o **Quest é latin-only** (`main.tsx` importa `@fontsource/baloo-2/latin-*`, `nunito/latin-*`); o
  **Edu já embarca os CSS default multi-subset** (`inter/400.css` → latin+latin-ext+cirílico+grego+vietnamita;
  `poppins` → devanágari+latin+latin-ext), portanto **não** é latin-only — reduzi-lo a latin é trabalho pendente,
  não estado atual (o **precache/pipeline** de fontes é da Seção [15](15-arte-audio-assets.md) para o Quest).

Este capítulo **especifica** o framework de i18n a construir **na medida certa** — o essencial de higiene pt-BR
agora, o resto ao aprovar um 2º idioma (§15/16.23) — e **crava** que o idioma do **áudio** só muda por **ADR do
dono** (P9).

### 3. Filosofia da funcionalidade
**"pt-BR primeiro, i18n sem susto."** O idioma da criança brasileira **é** o produto (P9); a internacionalização
não é um objetivo em si — é uma **disciplina de arquitetura** que evita dívida: **nenhuma string nasce hardcoded**,
**uma única fonte** formata data/número, e o texto-fonte é o **vocabulário canônico da Seção [02](02-vocabulario.md)**.
A distinção que organiza tudo: **localizar a UI (texto) ≠ localizar o áudio.** A UI pode um dia ganhar outro idioma
por um caminho documentado; o **áudio obrigatório** é regido por **P9** e só muda por **decisão do dono (ADR)**.

Conexão com os **Princípios Imutáveis** ([01](01-principios-imutaveis.md)): **P9** (áudio sempre pt-BR) é o
**limite** desta seção — a 16 constrói o framework de texto sem tocar nesse invariante. A i18n bem-feita serve à
**acessibilidade** (Seção [13](13-acessibilidade.md)): fallback de locale que **nunca** deixa a criança sem texto,
e resiliência de layout que preserva alvos ≥48px.

### 4. Experiência que o jogador deve sentir
**A criança nunca vê a i18n** — ela vê um português **impecável, natural e caloroso**, sem "chave crua" nem data
estranha. Para o **time**, as strings ficam **organizadas e revisáveis** (não caçadas pelo JSX). Para o **futuro**,
um segundo idioma entra por um **caminho claro** (novo catálogo, subset de fonte, e — só com ADR — o áudio), sem
reescrever o app. O adulto (professor/família) recebe **datas e números no formato brasileiro**, sempre.

### 5. Fluxo completo
O **ciclo de vida de um texto** e o **caminho de um idioma**:

1. **Nasce como chave** — todo texto visível é uma **chave** no catálogo pt-BR (source-of-truth), com o termo
   vindo do vocabulário da Seção [02](02-vocabulario.md) — **nunca** um literal no JSX.
2. **Renderiza** — a UI resolve a chave pelo **locale ativo** (hoje sempre `pt-BR`), com **interpolação**
   (nome/apelido) e **pluralização** por `Intl.PluralRules`.
3. **Formata** — datas/números/ordenação passam pela **fonte única** (`formato.ts`), que recebe **ISO/UTC**
   (Seção [14](14-infra-deploy-dr.md)) e devolve o formato **pt-BR**.
4. **Narra** — se a string é falada, o **áudio pt-BR** correspondente **sempre** toca (P9; estratégia = Seção
   [15](15-arte-audio-assets.md)), com o reforço de texto/visual da Seção [13](13-acessibilidade.md) **somado** (nunca no lugar).
5. **Novo idioma (futuro)** — muda **junto**: (a) novo **catálogo** de UI; (b) **subset de fonte** se o script
   não for latino (Seção [15](15-arte-audio-assets.md)); (c) o **áudio** — **só com ADR do dono referenciando
   P9** (§15).
6. **Fallback** — locale não suportado → **cadeia de fallback até pt-BR**; chave sem tradução → pt-BR; **chave-fonte
   pt-BR ausente** → **placeholder neutro seguro + log**, nunca a chave crua nem vazio (a criança não-leitora nunca
   fica sem texto); nome próprio → **nunca traduzido**.

### 6. Interface (quando existir)
A 16 **não desenha telas** (inventário = Seção [07](07-ux-fluxos-navegacao.md)). Superfícies que o framework
**exige quando houver mais de um idioma** (todas **futuras**; hoje inexistentes):
- **`<html lang>` dinâmico** — reflete o locale ativo (hoje fixo `pt-BR`).
- **Seletor/detecção de idioma** — mecanismo de seleção (padrão pt-BR); se virar **preferência de perfil**, entra
  na **mesma whitelist** que a Seção [13](13-acessibilidade.md) governa (ADR-13-C) — a **posição** da tela é da
  Seção [07](07-ux-fluxos-navegacao.md).

### 7. UX
- **Expansão de texto** — o layout tolera texto que cresce/encolhe entre idiomas **sem quebrar** alvos ≥48px nem
  a navegação; verificável já em pt-BR por **pseudo-localização** (§14 — Checklist). A **norma de resiliência** é da 16; a
  **superfície** é da Seção [07](07-ux-fluxos-navegacao.md), que já cita a 16.
- **Fallback que nunca deixa a criança sem texto** — chave ausente resolve para pt-BR; piso pt-BR ausente →
  placeholder seguro (Seção [13](13-acessibilidade.md)).
- **Nomes próprios preservados** — Constela, Cosmo, Constelação, nomes de planeta **não se traduzem** (Seções
  [02](02-vocabulario.md)/[03](03-universo.md)).
- **Datas/números brasileiros** — sempre via a fonte única (`formato.ts`), nunca "no olho".

### 8. Game Design
**N/A** — capítulo de infraestrutura de texto, sem dimensão de jogo. Nota de fronteira: as **falas do Cosmo** e o
**copy** são conteúdo das Seções [07](07-ux-fluxos-navegacao.md)/[08](08-onboarding-ftue.md) e vocabulário da
Seção [02](02-vocabulario.md); a 16 só as **externaliza**.

### 9. Regras de negócio
As **normas de i18n** (a fonte única do mecanismo; a **norma de áudio** é da Seção [13](13-acessibilidade.md)/P9,
o **vocabulário** da Seção [02](02-vocabulario.md)):

| # | Norma | Regra | Fronteira |
|---|-------|-------|-----------|
| L1 | **Idioma-fonte** | **pt-BR** é o *source-of-truth* de toda tradução; o texto-fonte segue o vocabulário da Seção [02](02-vocabulario.md) | 16; termos = [02](02-vocabulario.md) |
| L2 | **Zero hardcoded** | nenhuma string visível vive no JSX; **toda** string é uma **chave** no catálogo — garantido por **lint** (regra *no-literal-string* / plugin i18n no CI que falha o build) | 16 |
| L3 | **Catálogo** | formato com **interpolação e plural** (proposta: **ICU MessageFormat**, que pré-filtra a biblioteca); namespaces por área (UI/Cosmo/sistema) | 16 ⚠️ (biblioteca/formato) |
| L4 | **Pluralização/ordinal** | **`Intl.PluralRules`** (substitui os ternários `=== 1 ? "" : "s"` e o "min/h" manual do `formato.ts`); o **rótulo de série** ("Nº Ano") é renderizado por ordinal, não congelado | 16 |
| L5 | **Formatação regional** | **fonte única** (`formato.ts`) para data/hora/número **e ordenação** (`Intl.Collator`), a partir de **ISO/UTC** (Seção [14](14-infra-deploy-dr.md)); **eliminar** os `toLocaleString`/`localeCompare` inline; **locale = parâmetro**, não literal | 16 (mecanismo delegado por [14](14-infra-deploy-dr.md)) |
| L6 | **Nomes próprios** | Constela, Cosmo, Constelação, nomes de planeta **não se traduzem** (registrados/congelados) | 16 registra; nomeia = [03](03-universo.md)/[02](02-vocabulario.md) |
| L7 | **Identificadores estáveis** | **códigos BNCC** (`EF02MA05`) e o **número da série** são **identificadores** não-localizáveis; o **rótulo** de série ("1º Ano") é **copy localizável** (Seções [07](07-ux-fluxos-navegacao.md)/[02](02-vocabulario.md)) via ordinal | 16; códigos = [06](06-pedagogico-bncc.md); rótulo = [07](07-ux-fluxos-navegacao.md) |
| L8 | **Lint de palavras proibidas** | mecanismo de verificação **por locale**, **referenciando** a lista canônica da Seção [02](02-vocabulario.md) (sem recopiá-la) | 16 (mecanismo); lista = [02](02-vocabulario.md) |
| L9 | **Seleção de locale** | mecanismo (padrão/detecção/preferência) com **cadeia de fallback até pt-BR**; padrão e único no lançamento = **pt-BR** | 16 ⚠️ (detecção — §15) |
| L10 | **Áudio (P9)** | a narração obrigatória é **pt-BR** (imutável); **mudar o idioma do áudio = ADR do dono** referenciando P9 — **não** é decisão da 16 | [01](01-principios-imutaveis.md)/[13](13-acessibilidade.md); ADR ⚠️ (§15) |
| L11 | **Chave ↔ áudio** | toda string **narrada** tem áudio correspondente **por locale** (framework de vínculo; assets = Seção [15](15-arte-audio-assets.md)) | 16 (framework); assets = [15](15-arte-audio-assets.md) |
| L12 | **Resiliência de layout** | o layout tolera **expansão/encolhimento** de texto entre idiomas sem quebrar alvos ≥48px; verificado por **pseudo-localização** (§14 — Checklist) | 16 (norma); superfície = [07](07-ux-fluxos-navegacao.md) |
| L13 | **Cobertura de glifos** | cada locale reconcilia sua cobertura de glifos com o **subset de fonte**; o **pipeline/precache** de assets é da Seção [15](15-arte-audio-assets.md) (Quest); o subset do **Edu** é reduzido/escolhido pela i18n | 16 concilia; pipeline = [15](15-arte-audio-assets.md) |
| L14 | **Governança de termo** | **quando** um termo canônico muda (governado pela Seção [02](02-vocabulario.md)/dono via ADR), a 16 **propaga** por catálogo/áudios (memória de tradução + glossário) | 16 (propagação); termo/ADR = [02](02-vocabulario.md) |
| L15 | **UI ≠ áudio** | localizar a **UI** (texto) é da 16; localizar o **áudio** é regido por **P9** (mudança = ADR) | 16 / [01](01-principios-imutaveis.md) |

### 10. Arquitetura técnica
Onde a i18n **toca** o código (contratos → Apêndice B):
- **Catálogo** — um catálogo de mensagens por locale (chave→texto), com **ICU MessageFormat** (interpolação +
  plural + **select**); as strings pt-BR hoje inline (`Lobby`/`Entrada`/`Cerimonia`) migram para o catálogo. A
  **biblioteca** é ⚠️ (§15): como a proposta é **ICU**, a lista curta é **formatjs** (ICU nativo), **react-i18next
  + `i18next-icu`**, ou **catálogo próprio** que implemente ICU.
- **Formatação** — `packages/core/src/formato.ts` vira a **fonte única**: recebe o **locale** como parâmetro,
  usa `Intl.DateTimeFormat`/`NumberFormat`/`PluralRules`/`Collator`, e os `toLocaleString`/`localeCompare` **inline**
  (web/mobile) são **removidos** em favor dela. As datas chegam **ISO/UTC** (Seção [14](14-infra-deploy-dr.md)).
- **Locale** — mecanismo de seleção (padrão pt-BR; detecção/preferência = ⚠️) e **`<html lang>` dinâmico**; se
  virar preferência de perfil, entra na whitelist da Seção [13](13-acessibilidade.md) (ADR-13-C).
- **Fontes** — o **Quest** é latin-only; o **Edu** já embarca subsets multi-script (reduzir a latin = pendente); os
  subsets por script se reconciliam com o **pipeline de assets** da Seção [15](15-arte-audio-assets.md).
- **Áudio** — o **vínculo chave↔áudio** por locale é framework da 16; os **clipes** e a **estratégia** são da
  Seção [15](15-arte-audio-assets.md); o **idioma** do áudio obrigatório é **P9** (mudança = ADR).

### 11. Dependências com outros módulos
**Consome / referencia:**
- **Seção [01](01-principios-imutaveis.md)** — **P9** (o limite imutável do áudio pt-BR).
- **Seção [02](02-vocabulario.md)** — o **texto-fonte** (vocabulário canônico, nomes próprios, lista de proibidas).
- **Seção [03](03-universo.md)** — os **nomes próprios** do universo (que a 16 congela, não nomeia).
- **Seção [06](06-pedagogico-bncc.md)** — os **códigos BNCC** (identificadores estáveis) e a regra **ERER sem
  autoria por IA** (conteúdo — a tradução de conteúdo ERER é **curadoria humana**, nunca IA).
- **Seção [07](07-ux-fluxos-navegacao.md)** — a **superfície**, o **copy** das telas (inclui o rótulo de série); a 16 externaliza o texto.
- **Seção [13](13-acessibilidade.md)** — a **norma** de áudio pt-BR + a whitelist de preferências.
- **Seção [14](14-infra-deploy-dr.md)** — **UTC no banco** (a formatação pt-BR é delegada a esta seção).
- **Seção [15](15-arte-audio-assets.md)** — os **clipes de áudio por idioma** e o **pipeline/precache** de assets (fontes por script).

**Alimenta:**
- **Todas as seções com texto** — o **catálogo** e a **fonte única** de formatação.
- **Seção [07](07-ux-fluxos-navegacao.md)** — a **norma de resiliência** de layout à expansão de texto.

**O que quebra se mudar:** se a Seção [14](14-infra-deploy-dr.md) mudar o **UTC/fuso**, a 16 **reajusta** a
formatação; se a Seção [02](02-vocabulario.md) mudar um **termo**, a 16 **propaga** por catálogo/áudio (L14); se
o dono aprovar um **novo idioma de áudio** (ADR/P9), a 16 e a Seção [15](15-arte-audio-assets.md) executam juntas.

### 12. Casos extremos (Edge Cases)
- **Locale não suportado** → **cadeia de fallback até pt-BR** (nunca tela sem texto).
- **Chave sem tradução** no locale ativo → resolve para **pt-BR**.
- **Chave-fonte pt-BR ausente** (chave nova ainda não no catálogo) → **placeholder neutro seguro + log**; **nunca**
  a chave crua (`lobby.jogar`) nem vazio — a criança não-leitora não fica sem texto (gate de CI: catálogo pt-BR completo).
- **Script não-latino** (futuro) → novo **subset de fonte** (pipeline da Seção [15](15-arte-audio-assets.md)) +
  prontidão **RTL** (⚠️ §15).
- **Texto que expande** (ex.: pt→de) → layout resiliente preserva alvos ≥48px, verificado por pseudo-loc (L12; superfície = Seção [07](07-ux-fluxos-navegacao.md)).
- **Áudio de instrução** → **sempre** cai para o **áudio pt-BR** correspondente (garantido por P9); o reforço
  visual da Seção [13](13-acessibilidade.md) é camada **somada**, nunca substituto; **nunca** voz de rede (Seção [15](15-arte-audio-assets.md)).
- **Nome próprio** (Cosmo, Numéria) → **nunca traduzido**, em nenhum locale (L6).
- **Data ISO/UTC** chega do servidor → formatada **pt-BR** na fonte única; nenhum `toLocaleString`/`localeCompare` inline.
- **"Inglês" como matéria/planeta** (conteúdo pedagógico da Seção [06](06-pedagogico-bncc.md)) ≠ **inglês como
  idioma da UI** (i18n) — **não se confundem**.

### 13. Escalabilidade futura
- **2º idioma (UI primeiro)** — novo catálogo + subset de fonte; **áudio depois**, e **só com ADR** (P9).
- **RTL / alfabetos não-latinos** — prontidão registrada (⚠️ 16.16); implementação sob demanda, com o pipeline da Seção [15](15-arte-audio-assets.md).
- **Conteúdo pedagógico por país/currículo** — multilíngue × por-país (⚠️ 16.17), ligado à Seção [06](06-pedagogico-bncc.md)
  e ao software futuro de matérias+questões; a **tradução de conteúdo ERER** é **curadoria humana** (Seção [06](06-pedagogico-bncc.md), sem IA).
- **Pipeline de tradução** — memória de tradução + glossário + QA em contexto; ferramenta/responsável = ⚠️ (16.19).
- **Certificados/relatórios** (Edu) ganham idiomas via o mesmo catálogo.

### 14. Checklist de implementação
**A — Agora (higiene pt-BR; independe de 16.23):**
- [ ] **Zero string hardcoded** — toda string visível é **chave** no catálogo (L2); **lint** *no-literal-string* no CI; source pt-BR (L1).
- [ ] **Catálogo** com interpolação + plural (**ICU MessageFormat**); namespaces por área (L3).
- [ ] **`Intl.PluralRules`** substitui os ternários ad-hoc e o "min/h" manual; **rótulo de série** por ordinal (L4).
- [ ] **`formato.ts` é a fonte única** de data/hora/número **e ordenação** (`Intl.Collator`); **nenhum `toLocaleString`/`localeCompare` inline** (L5).
- [ ] **Nomes próprios congelados** e **códigos BNCC/número de série** como identificadores (L6/L7).
- [ ] **Catálogo pt-BR completo** é gate de CI (build falha com chave órfã) — piso do fallback (§12).
- [ ] **Áudio permanece pt-BR** (P9); qualquer idioma de áudio passou por **ADR do dono** (L10/L15).
- [ ] **Pseudo-localização** (smoke pt-BR: +40% de comprimento) no CI — resiliência L12 já verificável sem 2º idioma.
- [ ] **Subset de fonte do Edu reduzido a latin** (aparar cirílico/grego/devanágari não usados no pt-BR), conciliado com o pipeline da Seção [15](15-arte-audio-assets.md).

**B — Ao aprovar 2º idioma (depende de 16.23):**
- [ ] **Cadeia de fallback** até pt-BR implementada (L9); **`<html lang>` dinâmico**; **seleção/detecção** de locale.
- [ ] **Lint de palavras proibidas** por locale, referenciando a Seção [02](02-vocabulario.md) (L8).
- [ ] **Layout resiliente** confirmado no **catálogo do 2º idioma real** (expansão medida; ≥48px preservado — L12).
- [ ] **Vínculo chave↔áudio** por locale coberto (L11); **cobertura de glifos** reconciliada com o subset de fonte (L13).
- [ ] **Memória de tradução + glossário**; **governança de termo** (mudança de termo canônico = ADR da Seção [02](02-vocabulario.md), propagada — L14).

### 15. Questões em aberto
Cada item é **decisão do dono** (⚠️); os defaults são **propostas** da 16, não decisões autônomas:

- ⚠️ **16.23 — Idiomas-alvo.** Há intenção real de **outro idioma** além do pt-BR (ex.: espanhol LATAM, inglês)?
  Quais, em que **fase** do roadmap, e com que **profundidade** (só UI × UI+áudio × UI+áudio+conteúdo)? Isso decide
  **quanto** da infra de i18n se constrói **agora** (bloco A) vs. só se documenta o caminho (bloco B).
- ⚠️ **16.9 / L10 — Áudio em outro idioma (colisão com P9).** Estender a **narração obrigatória** a um idioma ≠
  pt-BR **colide com P9** (imutável). Autoriza abrir um **ADR do dono referenciando P9**? Se sim, o áudio será
  **gravado por locale** ou **TTS**, e quem produz/revisa (liga à Seção [15](15-arte-audio-assets.md)).
- ⚠️ **16.3/16.4 — Biblioteca de i18n.** Adotar **formatjs** (ICU nativo), **react-i18next + `i18next-icu`**, ou
  **catálogo próprio** com ICU — nenhuma existe hoje. **ICU MessageFormat** é a proposta que **pré-filtra** a lista.
- ⚠️ **Detecção de locale.** Detecção automática via `navigator.language` × seleção manual × padrão pt-BR fixo?
  (Subordinada a 16.23: só faz sentido com um 2º idioma.)
- ⚠️ **16.16 — RTL / scripts não-latinos.** Preparar prontidão para RTL/alfabetos não-latinos (novos subsets de
  fonte no pipeline da Seção [15](15-arte-audio-assets.md)) ou o horizonte é só línguas latinas?
- ⚠️ **16.17 — Conteúdo pedagógico multilíngue.** As missões/desafios BNCC são **multilíngues** ou o catálogo é
  **por país/currículo**? (Liga à Seção [06](06-pedagogico-bncc.md) e ao software futuro; a tradução de ERER é
  **curadoria humana** — Seção [06](06-pedagogico-bncc.md), sem IA.)
- ⚠️ **16.19 — Pipeline de tradução.** Ferramenta e responsável (contratada × comunidade × IA com revisão humana).
- ⚠️ **Moeda.** O framework precisa de **formatação de moeda (BRL)** para o lado Edu/professor, ou número + XP
  bastam? (Hoje não há nenhuma formatação de moeda.)

### 16. ADR (Architecture Decision Record)
- **ADR-16-A — pt-BR é a língua-fonte; zero string hardcoded.** Todo texto visível vive num **catálogo** (source
  pt-BR, termos da Seção [02](02-vocabulario.md)); nada de literal no JSX (garantido por lint). Formato proposto:
  **ICU MessageFormat** (pré-filtra a biblioteca). *Biblioteca pendente (§15).*
- **ADR-16-B — `formato.ts` é a fonte única de formatação.** Data/hora/número/ordenação passam por `formato.ts`
  (locale = parâmetro, `Intl.*`), a partir de **ISO/UTC** (Seção [14](14-infra-deploy-dr.md)); os `toLocaleString`/`localeCompare`
  inline são removidos. *Mecanismo delegado pela Seção [14](14-infra-deploy-dr.md) — decisão da 16, não do dono.*
- **ADR-16-C — Localizar a UI ≠ localizar o áudio.** A 16 é dona da i18n de **texto/UI**; o **áudio obrigatório**
  é regido por **P9** (Seção [01](01-principios-imutaveis.md)/[13](13-acessibilidade.md)) — **mudar o idioma do
  áudio é decisão do dono via ADR referenciando P9**, executada com a Seção [15](15-arte-audio-assets.md); nunca
  da 16 sozinha.
- **ADR-16-D — Nomes próprios não se traduzem.** Constela, Cosmo, Constelação e os nomes de planeta são
  **congelados** (registrados pela 16, nomeados pelas Seções [02](02-vocabulario.md)/[03](03-universo.md)); os
  **códigos BNCC** e o **número de série** são **identificadores estáveis**, mas o **rótulo** de série ("Nº Ano")
  é copy localizável (Seção [07](07-ux-fluxos-navegacao.md)).

*Decisões cross-módulo não são improvisadas aqui: as pendências acima viram ADR ou item de §15.*

---

## 🇬🇧 Localization & i18n

### 1. Objective
To be the **definitive localization and internationalization reference** for Constela Quest: the **framework**
that keeps the product **impeccable in pt-BR today** and **ready** for a second language **tomorrow, without a
rewrite** — externalizing strings, centralizing regional formatting and designing the path of a new language. It
decides the **i18n mechanism** and the **pt-BR formatting** (delegated by Section [14](14-infra-deploy-dr.md)); it
does **not** decide the **pt-BR audio norm** (Section [13](13-acessibilidade.md)/**P9 — immutable**), the
**vocabulary/proper names** (Sections [02](02-vocabulario.md)/[03](03-universo.md)), the **copy** (Section
[07](07-ux-fluxos-navegacao.md)), nor the **audio/font assets** (Section [15](15-arte-audio-assets.md)).

### 2. Context
In the **Hub → Edu → Quest** ecosystem, the audience is the **Brazilian child** and **Principle 9** fixes
**narration always in pt-BR**. **Current state (Q0) — pt-BR-only, i18n greenfield:**
- **i18n library** — **none** (grep for `i18next`/`react-i18next`/`formatjs`/`react-intl`/`@lingui` in all
  `package.json` = zero).
- **UI strings** — **hardcoded in pt-BR** directly in components; **no** central text catalog (e.g. `Lobby.tsx`
  "Jogar"/"Vestiário"/"Carreira"; `Entrada.tsx` `placeholder="SOL1234"`/`aria-label`; `Cerimonia.tsx`).
- **Narration (P9)** — hardcoded pt-BR: `audio.ts` `escolherVoz()` prefers a local pt-BR voice; `narrar()` fixes
  `lang="pt-BR"`; pt-BR phrases inline in the `narrar()` calls.
- **Date/number formatting** — **partially centralized but bypassed**: `packages/core/src/formato.ts` has
  `numero`/`nota`/`dataHora` via `toLocaleString("pt-BR")` and `tempoLeitura` that formats **min/h by hand** (no
  `toLocaleString`, no `Intl.PluralRules`); **but** scattered inline `toLocaleString("pt-BR")`/`localeCompare("…","pt-BR")`
  bypass `formato.ts` (`Grafico.tsx`, `PerfilAluno.tsx`, `Usuarios.tsx`, mobile `Painel.tsx`…). **No**
  `Intl.DateTimeFormat`/`PluralRules`/`Collator`; **no** currency (Quest has no money, only XP).
- **Locale detection** — **none** (no `navigator.language`); language is a compile-time constant.
- **`<html lang>`** — fixed `"pt-BR"` in both `index.html`; no runtime switch.
- **Fonts** — the **Quest is latin-only** (`main.tsx` imports `@fontsource/baloo-2/latin-*`, `nunito/latin-*`); the
  **Edu already ships the default multi-subset CSS** (`inter/400.css` → latin+latin-ext+cyrillic+greek+vietnamese;
  `poppins` → devanagari+latin+latin-ext), so it is **not** latin-only — reducing it to latin is pending work, not
  the current state (the font **pre-cache/pipeline** is Section [15](15-arte-audio-assets.md)'s for the Quest).

This chapter **specifies** the i18n framework to build **right-sized** — the essential pt-BR hygiene now, the rest
on approving a 2nd language (§15/16.23) — and **fixes** that the **audio** language only changes by an **owner ADR** (P9).

### 3. Feature philosophy
**"pt-BR first, i18n without surprises."** The Brazilian child's language **is** the product (P9);
internationalization is not a goal in itself — it is an **architecture discipline** that avoids debt: **no string
is born hardcoded**, **a single source** formats date/number, and the source text is the **canonical vocabulary of
Section [02](02-vocabulario.md)**. The distinction that organizes everything: **localizing the UI (text) ≠
localizing the audio.** The UI may one day gain another language via a documented path; the **mandatory audio** is
governed by **P9** and only changes by an **owner decision (ADR)**.

Link to the **Immutable Principles** ([01](01-principios-imutaveis.md)): **P9** (always pt-BR audio) is the
**boundary** of this section — 16 builds the text framework without touching that invariant. Good i18n serves
**accessibility** (Section [13](13-acessibilidade.md)): a locale fallback that **never** leaves the child without
text, and layout resilience that preserves ≥48px targets.

### 4. The experience the player should feel
**The child never sees the i18n** — they see **impeccable, natural, warm** Portuguese, with no "raw key" nor odd
date. For the **team**, strings are **organized and reviewable** (not hunted through JSX). For the **future**, a
second language enters via a **clear path** (new catalog, font subset, and — only with an ADR — the audio), without
rewriting the app. The adult (teacher/family) always gets **Brazilian date and number formats**.

### 5. Complete flow
The **lifecycle of a text** and the **path of a language**:

1. **Born as a key** — every visible text is a **key** in the pt-BR catalog (source-of-truth), with the term
   coming from Section [02](02-vocabulario.md)'s vocabulary — **never** a JSX literal.
2. **Renders** — the UI resolves the key by the **active locale** (today always `pt-BR`), with **interpolation**
   (name/nickname) and **pluralization** via `Intl.PluralRules`.
3. **Formats** — dates/numbers/sorting go through the **single source** (`formato.ts`), which receives **ISO/UTC**
   (Section [14](14-infra-deploy-dr.md)) and returns the **pt-BR** format.
4. **Narrates** — if the string is spoken, the matching **pt-BR audio** **always** plays (P9; strategy = Section
   [15](15-arte-audio-assets.md)), with Section [13](13-acessibilidade.md)'s text/visual reinforcement **added** (never instead).
5. **New language (future)** — changes **together**: (a) a new UI **catalog**; (b) a **font subset** if the script
   is not latin (Section [15](15-arte-audio-assets.md)); (c) the **audio** — **only with an owner ADR referencing P9** (§15).
6. **Fallback** — unsupported locale → **fallback chain down to pt-BR**; untranslated key → pt-BR; **missing pt-BR
   source key** → **safe neutral placeholder + log**, never a raw key nor empty (the non-reading child is never
   left without text); proper name → **never translated**.

### 6. Interface (when it exists)
Section 16 **does not draw screens** (inventory = Section [07](07-ux-fluxos-navegacao.md)). Surfaces the framework
**requires when there is more than one language** (all **future**; absent today):
- **Dynamic `<html lang>`** — reflects the active locale (today fixed `pt-BR`).
- **Language selector/detection** — a selection mechanism (default pt-BR); if it becomes a **profile preference**,
  it joins the **same whitelist** Section [13](13-acessibilidade.md) governs (ADR-13-C) — the screen **position**
  is Section [07](07-ux-fluxos-navegacao.md)'s.

### 7. UX
- **Text expansion** — the layout tolerates text that grows/shrinks between languages **without breaking** ≥48px
  targets nor navigation; verifiable already in pt-BR via **pseudo-localization** (§14 — Checklist). The **resilience norm** is
  16's; the **surface** is Section [07](07-ux-fluxos-navegacao.md)'s, which already cites 16.
- **A fallback that never leaves the child without text** — a missing key resolves to pt-BR; a missing pt-BR floor
  → safe placeholder (Section [13](13-acessibilidade.md)).
- **Proper names preserved** — Constela, Cosmo, Constelação, planet names **are not translated** (Sections
  [02](02-vocabulario.md)/[03](03-universo.md)).
- **Brazilian dates/numbers** — always via the single source (`formato.ts`), never "by eye".

### 8. Game Design
**N/A** — a text-infrastructure chapter, no game dimension. Boundary note: **Cosmo's lines** and the **copy** are
Sections [07](07-ux-fluxos-navegacao.md)/[08](08-onboarding-ftue.md) content and Section [02](02-vocabulario.md)
vocabulary; 16 only **externalizes** them.

### 9. Business rules
The **i18n norms** (the single source of the mechanism; the **audio norm** is Section [13](13-acessibilidade.md)'s/P9,
the **vocabulary** Section [02](02-vocabulario.md)'s):

| # | Norm | Rule | Boundary |
|---|------|------|----------|
| L1 | **Source language** | **pt-BR** is the *source-of-truth* of all translation; source text follows Section [02](02-vocabulario.md)'s vocabulary | 16; terms = [02](02-vocabulario.md) |
| L2 | **Zero hardcoded** | no visible string lives in JSX; **every** string is a **key** in the catalog — enforced by a **lint** (a *no-literal-string* rule / i18n plugin failing the CI build) | 16 |
| L3 | **Catalog** | format with **interpolation and plural** (proposal: **ICU MessageFormat**, which pre-filters the library); namespaces per area (UI/Cosmo/system) | 16 ⚠️ (library/format) |
| L4 | **Pluralization/ordinal** | **`Intl.PluralRules`** (replaces the `=== 1 ? "" : "s"` ternaries and the manual "min/h" in `formato.ts`); the **grade label** ("Nth Grade") is rendered by ordinal, not frozen | 16 |
| L5 | **Regional formatting** | **single source** (`formato.ts`) for date/time/number **and sorting** (`Intl.Collator`), from **ISO/UTC** (Section [14](14-infra-deploy-dr.md)); **remove** the inline `toLocaleString`/`localeCompare`; **locale = parameter**, not literal | 16 (mechanism delegated by [14](14-infra-deploy-dr.md)) |
| L6 | **Proper names** | Constela, Cosmo, Constelação, planet names **are not translated** (registered/frozen) | 16 registers; names = [03](03-universo.md)/[02](02-vocabulario.md) |
| L7 | **Stable identifiers** | **BNCC codes** (`EF02MA05`) and the **grade number** are **identifiers** not localizable; the grade **label** ("1º Ano", the pt-BR source string) is **localizable copy** (Sections [07](07-ux-fluxos-navegacao.md)/[02](02-vocabulario.md)) via ordinal | 16; codes = [06](06-pedagogico-bncc.md); label = [07](07-ux-fluxos-navegacao.md) |
| L8 | **Forbidden-words lint** | a per-locale check mechanism, **referencing** Section [02](02-vocabulario.md)'s canonical list (without recopying it) | 16 (mechanism); list = [02](02-vocabulario.md) |
| L9 | **Locale selection** | mechanism (default/detection/preference) with a **fallback chain down to pt-BR**; default and only at launch = **pt-BR** | 16 ⚠️ (detection — §15) |
| L10 | **Audio (P9)** | the mandatory narration is **pt-BR** (immutable); **changing the audio language = owner ADR** referencing P9 — **not** 16's decision | [01](01-principios-imutaveis.md)/[13](13-acessibilidade.md); ADR ⚠️ (§15) |
| L11 | **Key ↔ audio** | every **narrated** string has matching audio **per locale** (binding framework; assets = Section [15](15-arte-audio-assets.md)) | 16 (framework); assets = [15](15-arte-audio-assets.md) |
| L12 | **Layout resilience** | the layout tolerates text **expansion/contraction** between languages without breaking ≥48px targets; verified by **pseudo-localization** (§14 — Checklist) | 16 (norm); surface = [07](07-ux-fluxos-navegacao.md) |
| L13 | **Glyph coverage** | each locale reconciles its glyph coverage with the **font subset**; the asset **pipeline/pre-cache** is Section [15](15-arte-audio-assets.md)'s (Quest); the **Edu** subset is reduced/chosen by i18n | 16 reconciles; pipeline = [15](15-arte-audio-assets.md) |
| L14 | **Term governance** | **when** a canonical term changes (governed by Section [02](02-vocabulario.md)/owner via ADR), 16 **propagates** it across catalog/audio (translation memory + glossary) | 16 (propagation); term/ADR = [02](02-vocabulario.md) |
| L15 | **UI ≠ audio** | localizing the **UI** (text) is 16's; localizing the **audio** is governed by **P9** (change = ADR) | 16 / [01](01-principios-imutaveis.md) |

### 10. Technical architecture
Where i18n **touches** code (contracts → Appendix B):
- **Catalog** — a per-locale message catalog (key→text), with **ICU MessageFormat** (interpolation + plural +
  **select**); today's inline pt-BR strings (`Lobby`/`Entrada`/`Cerimonia`) migrate to the catalog. The **library**
  is ⚠️ (§15): since the proposal is **ICU**, the shortlist is **formatjs** (native ICU), **react-i18next +
  `i18next-icu`**, or an **own catalog** implementing ICU.
- **Formatting** — `packages/core/src/formato.ts` becomes the **single source**: it takes the **locale** as a
  parameter, uses `Intl.DateTimeFormat`/`NumberFormat`/`PluralRules`/`Collator`, and the **inline** `toLocaleString`/`localeCompare`
  (web/mobile) are **removed** in its favor. Dates arrive as **ISO/UTC** (Section [14](14-infra-deploy-dr.md)).
- **Locale** — a selection mechanism (default pt-BR; detection/preference = ⚠️) and a **dynamic `<html lang>`**;
  if it becomes a profile preference, it joins Section [13](13-acessibilidade.md)'s whitelist (ADR-13-C).
- **Fonts** — the **Quest** is latin-only; the **Edu** already ships multi-script subsets (reducing to latin =
  pending); per-script subsets reconcile with Section [15](15-arte-audio-assets.md)'s asset pipeline.
- **Audio** — the **key↔audio** binding per locale is 16's framework; the **clips** and the **strategy** are
  Section [15](15-arte-audio-assets.md)'s; the mandatory audio **language** is **P9** (change = ADR).

### 11. Dependencies on other modules
**Consumes / references:**
- **Section [01](01-principios-imutaveis.md)** — **P9** (the immutable pt-BR audio boundary).
- **Section [02](02-vocabulario.md)** — the **source text** (canonical vocabulary, proper names, forbidden list).
- **Section [03](03-universo.md)** — the universe **proper names** (which 16 freezes, does not name).
- **Section [06](06-pedagogico-bncc.md)** — the **BNCC codes** (stable identifiers) and the **ERER no-AI-authorship**
  rule (content — ERER content translation is **human curation**, never AI).
- **Section [07](07-ux-fluxos-navegacao.md)** — the screen **surface**, the **copy** (including the grade label); 16 externalizes the text.
- **Section [13](13-acessibilidade.md)** — the pt-BR audio **norm** + the preferences whitelist.
- **Section [14](14-infra-deploy-dr.md)** — **UTC in the DB** (pt-BR formatting is delegated to this section).
- **Section [15](15-arte-audio-assets.md)** — the **audio clips per language** and the asset **pipeline/pre-cache** (per-script fonts).

**Feeds:**
- **Every section with text** — the **catalog** and the **single source** of formatting.
- **Section [07](07-ux-fluxos-navegacao.md)** — the layout **resilience norm** for text expansion.

**What breaks if it changes:** if Section [14](14-infra-deploy-dr.md) changes the **UTC/timezone**, 16 **re-tunes**
the formatting; if Section [02](02-vocabulario.md) changes a **term**, 16 **propagates** it across catalog/audio
(L14); if the owner approves a **new audio language** (ADR/P9), 16 and Section [15](15-arte-audio-assets.md)
execute together.

### 12. Edge cases
- **Unsupported locale** → **fallback chain down to pt-BR** (never a screen without text).
- **Untranslated key** in the active locale → resolves to **pt-BR**.
- **Missing pt-BR source key** (a new key not yet in the catalog) → **safe neutral placeholder + log**; **never**
  a raw key (`lobby.jogar`) nor empty — the non-reading child is not left without text (CI gate: complete pt-BR catalog).
- **Non-latin script** (future) → a new **font subset** (Section [15](15-arte-audio-assets.md)'s pipeline) + **RTL** readiness (⚠️ §15).
- **Text that expands** (e.g. pt→de) → resilient layout preserves ≥48px targets, verified by pseudo-loc (L12; surface = Section [07](07-ux-fluxos-navegacao.md)).
- **Instruction audio** → **always** falls to the matching **pt-BR audio** (guaranteed by P9); Section
  [13](13-acessibilidade.md)'s visual reinforcement is an **added** layer, never a substitute; **never** a network voice (Section [15](15-arte-audio-assets.md)).
- **Proper name** (Cosmo, Numéria) → **never translated**, in any locale (L6).
- **ISO/UTC date** arrives from the server → formatted **pt-BR** in the single source; no inline `toLocaleString`/`localeCompare`.
- **"English" as a subject/planet** (Section [06](06-pedagogico-bncc.md) pedagogical content) ≠ **English as the UI
  language** (i18n) — they **do not mix**.

### 13. Future scalability
- **2nd language (UI first)** — new catalog + font subset; **audio later**, and **only with an ADR** (P9).
- **RTL / non-latin alphabets** — readiness registered (⚠️ 16.16); implementation on demand, with Section [15](15-arte-audio-assets.md)'s pipeline.
- **Pedagogical content per country/curriculum** — multilingual × per-country (⚠️ 16.17), tied to Section [06](06-pedagogico-bncc.md)
  and the future subjects+questions software; **ERER content translation** is **human curation** (Section [06](06-pedagogico-bncc.md), no AI).
- **Translation pipeline** — translation memory + glossary + in-context QA; tool/owner = ⚠️ (16.19).
- **Certificates/reports** (Edu) gain languages via the same catalog.

### 14. Implementation checklist
**A — Now (pt-BR hygiene; independent of 16.23):**
- [ ] **Zero hardcoded string** — every visible string is a **key** in the catalog (L2); *no-literal-string* **lint** in CI; pt-BR source (L1).
- [ ] **Catalog** with interpolation + plural (**ICU MessageFormat**); namespaces per area (L3).
- [ ] **`Intl.PluralRules`** replaces the ad-hoc ternaries and the manual "min/h"; **grade label** by ordinal (L4).
- [ ] **`formato.ts` is the single source** of date/time/number **and sorting** (`Intl.Collator`); **no inline `toLocaleString`/`localeCompare`** (L5).
- [ ] **Proper names frozen** and **BNCC codes/grade number** as identifiers (L6/L7).
- [ ] **Complete pt-BR catalog** is a CI gate (build fails on an orphan key) — the fallback floor (§12).
- [ ] **Audio stays pt-BR** (P9); any audio language went through an **owner ADR** (L10/L15).
- [ ] **Pseudo-localization** (pt-BR smoke: +40% length) in CI — L12 resilience verifiable without a 2nd language.
- [ ] **Edu font subset reduced to latin** (trim unused cyrillic/greek/devanagari for pt-BR), reconciled with Section [15](15-arte-audio-assets.md)'s pipeline.

**B — On approving a 2nd language (depends on 16.23):**
- [ ] **Fallback chain** down to pt-BR implemented (L9); **dynamic `<html lang>`**; locale **selection/detection**.
- [ ] **Forbidden-words lint** per locale, referencing Section [02](02-vocabulario.md) (L8).
- [ ] **Resilient layout** confirmed on the **real 2nd-language catalog** (measured expansion; ≥48px preserved — L12).
- [ ] **Key↔audio binding** per locale covered (L11); **glyph coverage** reconciled with the font subset (L13).
- [ ] **Translation memory + glossary**; **term governance** (a canonical-term change = Section [02](02-vocabulario.md) ADR, propagated — L14).

### 15. Open questions
Each item is a **owner decision** (⚠️); the defaults are 16's **proposals**, not autonomous decisions:

- ⚠️ **16.23 — Target languages.** Is there real intent for **another language** beyond pt-BR (e.g. LATAM Spanish,
  English)? Which, at what roadmap **phase**, and at what **depth** (UI only × UI+audio × UI+audio+content)? This
  decides **how much** i18n infra is built **now** (block A) vs. only documenting the path (block B).
- ⚠️ **16.9 / L10 — Audio in another language (collision with P9).** Extending the **mandatory narration** to a
  language ≠ pt-BR **collides with P9** (immutable). Do you authorize opening an **owner ADR referencing P9**? If
  so, will the audio be **recorded per locale** or **TTS**, and who produces/reviews it (ties to Section [15](15-arte-audio-assets.md)).
- ⚠️ **16.3/16.4 — i18n library.** Adopt **formatjs** (native ICU), **react-i18next + `i18next-icu`**, or an **own
  catalog** with ICU — none exists today. **ICU MessageFormat** is the proposal that **pre-filters** the shortlist.
- ⚠️ **Locale detection.** Automatic detection via `navigator.language` × manual selection × fixed pt-BR default?
  (Subordinate to 16.23: it only makes sense with a 2nd language.)
- ⚠️ **16.16 — RTL / non-latin scripts.** Prepare readiness for RTL/non-latin alphabets (new font subsets in
  Section [15](15-arte-audio-assets.md)'s pipeline) or is the horizon latin languages only?
- ⚠️ **16.17 — Multilingual pedagogical content.** Are the BNCC missions/challenges **multilingual** or is the
  catalog **per country/curriculum**? (Ties to Section [06](06-pedagogico-bncc.md) and the future software; ERER
  translation is **human curation** — Section [06](06-pedagogico-bncc.md), no AI.)
- ⚠️ **16.19 — Translation pipeline.** Tool and owner (vendor × community × AI with human review).
- ⚠️ **Currency.** Does the framework need **currency formatting (BRL)** for the Edu/teacher side, or do number +
  XP suffice? (Today there is no currency formatting.)

### 16. ADR (Architecture Decision Record)
- **ADR-16-A — pt-BR is the source language; zero hardcoded string.** Every visible text lives in a **catalog**
  (pt-BR source, Section [02](02-vocabulario.md) terms); no JSX literal (enforced by lint). Proposed format:
  **ICU MessageFormat** (pre-filters the library). *Library pending (§15).*
- **ADR-16-B — `formato.ts` is the single formatting source.** Date/time/number/sorting go through `formato.ts`
  (locale = parameter, `Intl.*`), from **ISO/UTC** (Section [14](14-infra-deploy-dr.md)); the inline `toLocaleString`/`localeCompare`
  are removed. *A mechanism delegated by Section [14](14-infra-deploy-dr.md) — 16's decision, not the owner's.*
- **ADR-16-C — Localizing the UI ≠ localizing the audio.** 16 owns **text/UI** i18n; the **mandatory audio** is
  governed by **P9** (Section [01](01-principios-imutaveis.md)/[13](13-acessibilidade.md)) — **changing the audio
  language is an owner decision via an ADR referencing P9**, executed with Section [15](15-arte-audio-assets.md);
  never 16 alone.
- **ADR-16-D — Proper names are not translated.** Constela, Cosmo, Constelação and the planet names are **frozen**
  (registered by 16, named by Sections [02](02-vocabulario.md)/[03](03-universo.md)); the **BNCC codes** and the
  **grade number** are **stable identifiers**, but the grade **label** ("Nth Grade") is localizable copy (Section [07](07-ux-fluxos-navegacao.md)).

*Cross-module decisions are not improvised here: the pending items above become an ADR or a §15 entry.*
