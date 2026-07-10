# 24 — Governança da Bible / Bible Governance

- **Status:** 🟢 aprovado / approved
- **Padrão / Standard:** [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) (16 partes)
- **Fontes / Sources:** `INDICE.md` (bloco 24, subseções 24.1–24.20; a 24.18 **remete** ao Apêndice C), `README.md` (os 3 portões, a regra de ouro, a legenda de status, a convenção bilíngue, o papel de estúdio), `_TEMPLATE-capitulo.md` (as 16 partes; Parte 15 = ⚠️ do dono, Parte 16 = ADR), **`decisoes/`** (o Decision Log: `ADR-0001` processo/governança e `ADR-0002` padrão de capítulo — ambos 🟢 *Aceito* 2026-07-09; e os **ADR candidatos C.12–C.26**), `_estado-atual/` (inventário de referência Q0), Seções [18](18-qa-testes.md)/[23](23-roadmap.md), Apêndices C/F
- **Depende de / Depends on:** as decisões-**fonte imutáveis** [ADR-0001](decisoes/ADR-0001-processo-e-governanca.md) (processo de estúdio, 3 portões, sem decisão autônoma, Bible = fonte única, bilíngue, versionamento Git) e [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) (16 partes, "N/A — motivo", anti-improviso) — a 24 **herda e consolida**, não redecide; o **mecanismo de ADR** (template, estados, numeração, rastreabilidade) → **Apêndice C**; o **DoD consolidado** (Parte 14 de cada seção) → **Apêndice F**; a **estratégia de testes do software** (distinta do gate de processo) → [18](18-qa-testes.md); o **roadmap do software** (distinto da governança da doc) → [23](23-roadmap.md).

> **Convenção / Convention:** "§N" = uma das 16 **partes deste capítulo** / one of the 16 **parts of this
> chapter**; "Seção NN" / "Section NN" = outro capítulo da Bible; "24.NN" = uma subseção do plano do `INDICE.md`.
> **Escopo / Scope:** este capítulo governa a **própria Bible** (a documentação) — como um capítulo **nasce, é
> aprovado, versionado e evoluído**; a **precedência de fontes** que arbitra conflitos; o **processo de ADR**; e a
> convenção bilíngue e de desacoplamento. Ele **decide o PROCESSO**; **não** decide o **conteúdo** de nenhuma seção
> (isso é da seção-dona), **não** governa o **software** (o roadmap é a Seção [23](23-roadmap.md), o QA do produto é
> a Seção [18](18-qa-testes.md)) e **não** reescreve os ADRs-fonte (`ADR-0001`/`ADR-0002` são imutáveis) — apenas os
> **formaliza** e **referencia**. Os detalhes do mecanismo de ADR descem para o **Apêndice C**.

---

## 🇧🇷 Governança da Bible

### 1. Objetivo
Ser a **referência definitiva do PROCESSO** da Constela Quest Bible: como um capítulo **nasce, é aprovado, versionado
e evoluído**, quem decide o quê, como contradições **doc × código × doc** são resolvidas por **precedência de
fontes**, e como a Bible é **espelhada** (bilíngue) e **registrada** (ADRs). **Herda** as decisões-fonte
[ADR-0001](decisoes/ADR-0001-processo-e-governanca.md)/[ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) e as
**formaliza** em capítulo; **não** redecide o conteúdo de nenhuma seção nem governa o software (Seções
[23](23-roadmap.md)/[18](18-qa-testes.md)). Alimenta os **Apêndices C e F**.

### 2. Contexto
A **Bible** (`docs/bible/`) é a **fonte oficial e única de verdade** do Constela Quest — toda decisão de produto,
game design, arte e arquitetura é registrada **antes** de virar código (`ADR-0001`). **Estado atual — a governança
já existe, dispersa; a 24 a consolida:**
- **Já vigente** (README + ADRs) — os **3 portões** (documentar → aprovar → implementar+revisar); a **regra de ouro**
  ("nada implementado de seção não-🟢"); a **legenda de status** (⬛/🔴/🟡/🟢); as **16 partes** obrigatórias
  (`ADR-0002`); a **convenção bilíngue** (pt-BR canônico + EN espelho, "nunca divergem"); o **papel de estúdio**
  (Supercell/Riot/Mojang/Epic — a organização, não a cópia dos jogos); **sem decisões autônomas** de produto.
- **Registro de decisões** — `decisoes/` é o **Decision Log**: `ADR-0001` (processo) e `ADR-0002` (padrão de
  capítulo), ambos **🟢 Aceito** com **Decisor = o dono do produto (Eduardo/Felipe)**. ADRs são **imutáveis**; reverter
  cria um **novo** ADR que referencia o anterior.
- **Mapa mestre** — `INDICE.md` (31 seções/apêndices, 979 subseções, com **⚠️ = subseção que depende do dono**); a
  **tabela do README** é o roll-up de status; o `_estado-atual/` é o **inventário de referência Q0** (verdade de base
  que as seções citam em "Fontes"), **não** decisão.
- **Pendências reais** — **15 ADR candidatos** (`C.12–C.26`: avatar 3D, Three.js, monetização imutável, Ed. Física/ERER
  etc.) aguardam **ratificação do dono**; a pasta `specs/` (Portão 1) está **vazia**; e há **divergência de status**
  (as Seções 00–02, *grandfathered* fora do padrão de 16 partes, exibem 🔴 no cabeçalho do arquivo mas 🟢 na tabela do README).

Este capítulo **formaliza** o processo, fixa a precedência de fontes e registra o que o dono precisa decidir.

### 3. Filosofia da funcionalidade
**"A Bible é o contrato: nada vira código sem passar por ela, e nada nela é improvisado."** A governança existe para
que **milhares de escolas** confiem num produto **planejado antes de construído**. Princípios: **documentar a
intenção** (o texto basta para implementar sem adivinhar o que o dono quis); **nada é implementado de uma seção que
não esteja 🟢** (o status é a trava); **cada capítulo decide só o seu escopo** e **referencia** a seção-dona de cada
regra (desacoplamento); **decisão cross-módulo nunca é improvisada** — vira **ADR** (§16) ou **pendência do dono ⚠️**
(§15); e **o dono é o único aprovador** — o papel técnico (Arquiteto + Game Designer + CTO) **propõe e implementa**,
mas **não** decide produto sozinho.

Conexão com os **Princípios Imutáveis** ([01](01-principios-imutaveis.md)): um **princípio imutável só muda por um
novo ADR** aprovado pelo dono que **referencie o anterior** — nunca por edição silenciosa (ecoa `01.2`). A 24 é a
guardiã dessa regra para toda a Bible.

### 4. Experiência que o jogador deve sentir
*(N/A para a criança — capítulo de processo; a "experiência" aqui é a do **time e do dono**.)* A criança **não** vive
a governança — ela colhe o resultado de um produto **coerente**. **O dono** sente **controle**:
sabe que nada é construído sem sua aprovação e que cada decisão fica **rastreável** num ADR. **A equipe** sente
**clareza**: um padrão de capítulo único, uma legenda de status, uma precedência de fontes que **encerra discussões**
("Princípios > ADR > Seção > Spec > código"), e a certeza de que **o que está 🟢 é seguro implementar**. **Um novo
integrante** entende o processo lendo **um** capítulo (este) + `ADR-0001`.

### 5. Fluxo completo
Os **3 portões** e o **ciclo de vida** — o **processo canônico** de toda funcionalidade (herdado de `ADR-0001`):

1. **Portão 1 — Documentação** — uma **spec** detalhada em `specs/` (modelo `_TEMPLATE-spec.md`) e/ou o **capítulo**
   correspondente, escrito no padrão de **16 partes** (`ADR-0002`), pt-BR canônico primeiro.
2. **Portão 2 — Aprovação** — o **dono do produto** revisa e aprova; as **questões em aberto** (Parte 15, ⚠️) são
   resolvidas **pelo dono**; decisões cross-módulo viram **ADR**.
3. **Portão 3 — Implementação fiel → Revisão → atualização** — implementa-se **exatamente** o aprovado; a **revisão de
   QA** cobre os **7 eixos** (bugs, performance, UX, acessibilidade, responsividade, escalabilidade, organização — a
   estratégia de **testes do produto** é da Seção [18](18-qa-testes.md)); e a Bible é **atualizada** para refletir o
   que foi construído.

**Ciclo de vida de um capítulo** (o status é a trava da regra de ouro):

> **⬛ não iniciado** → *(criar copiando `_TEMPLATE-capitulo.md`)* → **🔴 rascunho** → *(revisão)* → **🟡 em revisão** →
> *(aprovação do dono)* → **🟢 aprovado** — e **só 🟢 libera implementação**.

O **espelho EN** é preenchido **após** o pt-BR estar estável; o **cabeçalho** (Status / Padrão / Fontes / Depende de)
e a **tabela do README** + o `INDICE.md` são mantidos **em sincronia** com o arquivo.

### 6. Interface (quando existir)
**N/A** — capítulo de processo, sem UI. As "superfícies" da governança são a **tabela de status do README**, o
**`INDICE.md`** (mapa mestre) e o **`decisoes/README.md`** (Decision Log). A 24 define **o que** cada uma mantém; não
há tela de criança.

### 7. UX
A "UX de governança" é para a **equipe e o dono**: um **padrão único** de capítulo, uma **legenda de status** sem
ambiguidade, uma **precedência de fontes** que arbitra conflitos, e **rastreabilidade** (spec ↔ seção ↔ ADR ↔ commit).
Nada de regra improvisada; toda decisão relevante tem **um lugar** (ADR ou ⚠️).

### 8. Game Design
**N/A** — a 24 governa a **documentação**, não o jogo. A mecânica do jogo é das Seções [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md);
a 24 apenas garante que **cada decisão de game design passe pelos 3 portões** e vire ADR quando cruzar módulos.

### 9. Regras de negócio
As **normas de governança** (a 24 **formaliza**; os detalhes do mecanismo de ADR são do **Apêndice C**; o software é
das Seções [18](18-qa-testes.md)/[23](23-roadmap.md)):

| # | Norma | Regra | Fronteira |
|---|-------|-------|-----------|
| G1 | **Fonte única de verdade** | a Bible é a **fonte oficial e única**; toda decisão é registrada **antes** de virar código (`ADR-0001`) | 24 (formaliza); fonte = `ADR-0001` |
| G2 | **Os 3 portões** | **documentar** (spec/capítulo) → **aprovar** (dono) → **implementar fiel + revisar + atualizar** a Bible | 24; herdado de `ADR-0001` |
| G3 | **Regra de ouro** | **nada é implementado** a partir de uma seção/spec que **não esteja 🟢** | 24 (formaliza); fonte = `ADR-0001` |
| G4 | **Ciclo de vida de status** | **⬛→🔴→🟡→🟢**; o autor rascunha, a revisão de QA leva a 🟡, **só o dono** promove a 🟢 | 24 (formaliza); legenda = README |
| G5 | **Padrão de capítulo** | **16 partes** exatas (`ADR-0002`); parte não aplicável = **"N/A — motivo"** (nunca omitida); **documentar a intenção** | 24; padrão = `ADR-0002` |
| G6 | **Bilíngue** | **pt-BR canônico + EN espelho** no mesmo arquivo, **nunca divergem**; o EN é preenchido após o pt-BR estar estável (cadência ⚠️) | 24 ⚠️ (cadência do espelho — §15) |
| G7 | **Desacoplamento** | cada capítulo **decide só o seu escopo**, **referencia** a seção-dona de cada regra e **não redefine** regra alheia; a convenção `§N`/`Seção NN`/`NN.x` é canônica | 24 |
| G8 | **Anti-improviso** | decisão que impacta **outro módulo** vira **ADR** (Parte 16) ou **pendência do dono ⚠️** (Parte 15) — **nunca** improviso | 24; padrão = `ADR-0002` |
| G9 | **Precedência de fontes** | conflito se resolve por: **Princípios Imutáveis > ADR > Seção aprovada > Spec > código** | 24 |
| G10 | **Resolução de contradição** | ao achar contradição: **registrar → abrir ADR → reconciliar** os textos; a **seção-dona** de uma regra tem autoridade sobre ela | 24 |
| G11 | **Princípio imutável** | só muda por **novo ADR** (do dono) que **referencie o anterior** — nunca edição silenciosa (ecoa `01.2`) | 24; princípios = [01](01-principios-imutaveis.md) |
| G12 | **Mecanismo de ADR** | ADR **imutável**; **reverter = novo ADR** que referencia o anterior; a **numeração, os estados e as transições** seguem o **Apêndice C** (C.4/C.5) — a 24 **aponta**, não os enumera | 24 (aponta); mecanismo = Apêndice C |
| G13 | **Aprovador = o dono** | quem aprova (Portão 2) e decide as ⚠️ é o **dono do produto** (Eduardo/Felipe); o papel técnico **propõe e implementa**, o QA **revisa** — **sem** decisão autônoma de produto | 24 ⚠️ (delegação — §15) |
| G14 | **Rastreabilidade** | **spec ↔ seção ↔ ADR ↔ commit**; commit **isolado por seção** (só `docs/bible/*`, nenhum arquivo externo) | 24 |
| G15 | **Fonte canônica de status** | **proposta** (a confirmar pelo dono, §15): o **cabeçalho do arquivo** é a fonte e a tabela do README/`INDICE.md` **espelham**; hoje há **divergência** (00–02: 🔴 no arquivo × 🟢 no README) a reconciliar | 24 ⚠️ (fonte + reconciliação — §15) |
| G16 | **Versionamento** | o **histórico do Git** é o changelog da Bible (sem arquivo `CHANGELOG` separado); um changelog explícito é decisão do dono | 24 ⚠️ (changelog — §15) |
| G17 | **`_estado-atual` é inventário** | o `_estado-atual/` é **verdade de base Q0** de **referência**, **não** decisão; define quando **reauditar** | 24; roadmap = [23](23-roadmap.md) |
| G18 | **ADR candidatos** | a 24 **reconhece** os **15 candidatos** (`C.12–C.26`) como **pendências de ratificação** e governa o fluxo **⚠️ → ADR**; **não** arbitra o mérito de nenhum (é do dono) | 24 (fluxo); mérito = dono; backlog = Apêndice C |

### 10. Arquitetura técnica
A "arquitetura" da 24 é a **estrutura do repositório de documentação** (`docs/bible/`):
- **`README.md`** — porta de entrada + **tabela de status** (roll-up) + as convenções de alto nível.
- **`INDICE.md`** — o **mapa mestre** (31 seções/apêndices, 979 subseções, ⚠️ do dono).
- **`NN-*.md`** — os **capítulos** de 16 partes, bilíngues, com o cabeçalho canônico.
- **`decisoes/`** — o **Decision Log** (ADRs imutáveis) = **Apêndice C**.
- **`specs/`** — as **specs** de funcionalidade (Portão 1; `_TEMPLATE-spec.md`) — hoje **vazia**.
- **`_estado-atual/`** — o **inventário Q0** de referência.
- **`biblia-sensorial/`** — a Bíblia Sensorial dos 9 mundos + Cosmo (ligada às Seções [03](03-universo.md)/[15](15-arte-audio-assets.md)).
- **Versionamento** — **Git**: um **commit isolado por seção** ("Bible: aprovar Seção NN"), contendo **só** arquivos `docs/bible/*` (a seção + a linha do README).

### 11. Dependências com outros módulos
**Consome / referencia:**
- **`ADR-0001`/`ADR-0002`** — as **decisões-fonte imutáveis** que a 24 herda e consolida (não reescreve).
- **Apêndice C** — o **mecanismo de ADR** (template, estados, numeração, rastreabilidade, backlog de candidatos).
- **Apêndice F** — o **DoD consolidado** (agrega a Parte 14 de cada seção; inclui os 7 eixos do Portão 3).
- **Seção [18](18-qa-testes.md)** — a **estratégia de testes do software** (a 24 é dona do **gate de processo** do Portão 3; a 18, da estratégia de testes).
- **Seção [23](23-roadmap.md)** — o **roadmap do software** (a 24 governa a **doc**, não as fases do produto).
- **`_estado-atual/`** — o **inventário Q0** que os capítulos citam.

**Alimenta:**
- **Todas as seções** — o **padrão de capítulo**, a **legenda de status**, a **convenção bilíngue** e o **desacoplamento** que cada uma segue.
- **Apêndice C** — o **fluxo** que promove uma pendência ⚠️ a ADR.
- **Apêndice F** — os **7 eixos do Portão 3** (24.16) e a Parte 14 que o DoD consolidado agrega.

**O que quebra se mudar:** se o dono mudar o **padrão de capítulo**, é um **novo ADR** que referencia o `ADR-0002`
(não uma edição desta seção); se mudar a **precedência de fontes** (G9), toda resolução de conflito se recalibra; se
delegar a **aprovação** (G13), o Portão 2 ganha um novo ator.

### 12. Casos extremos (Edge Cases)
- **Contradição doc × código** → aplica-se a **precedência** (G9): o código **nunca** vence uma seção 🟢 ou um ADR;
  registra-se e **abre-se ADR** (G10).
- **Divergência de status (00–02: 🔴 no arquivo × 🟢 no README)** → **reconciliar** pela fonte canônica (G15, ⚠️ §15).
- **Espelho EN ausente/atrasado** → o EN entra **após** o pt-BR estável; se em lote ou por commit é ⚠️ (G6, §15).
- **Alguém "edita" um ADR aceito** → **proibido** (G12): ADR é imutável; reverter = **novo** ADR referenciando o anterior.
- **Decisão autônoma de produto pelo papel técnico** → **proibido** (G13): propor alternativas e aguardar o dono.
- **Seção citada mas não-🟢 sendo implementada** → **barra** pela regra de ouro (G3).
- **ADR candidato (C.12–C.26) tratado como decidido** → não (G18): é **pendência** até o dono ratificar.
- **Retrofit das Seções 00–02** → **opcional** (`ADR-0002`); decisão do dono (§15).

### 13. Escalabilidade futura
- **Automação/CI da documentação** (24.19) — lint de vocabulário proibido, verificação de status, sincronia do
  espelho bilíngue e dos links — adoção ⚠️ (§15).
- **Delegação de aprovação + cadência/SLA** (24.20) — o dono delega specs de baixo risco ao arquiteto? há prazo de revisão? — ⚠️ (§15).
- **Changelog explícito da Bible** — além do Git (G16) — ⚠️ (§15).
- **Retrofit das Seções 00–02** para as 16 partes — quando fizer sentido (§15).
- **Rastreabilidade automatizada** — vincular ADR ↔ commit ↔ seção por ferramenta.

### 14. Checklist de implementação
**"Pronto quando" (liga ao Apêndice F). Itens ⚠️ dependem de decisão do dono (§15):**
- [x] **Bible = fonte única e oficial**; toda decisão registrada **antes** do código (G1).
- [x] **3 portões** e **regra de ouro** formalizados (G2/G3).
- [x] **Ciclo de vida de status** ⬛→🔴→🟡→🟢, com o dono promovendo a 🟢 (G4).
- [x] **Padrão de 16 partes** (`ADR-0002`) + **"N/A — motivo"** + documentar a intenção (G5).
- [x] **Desacoplamento** (`§N`/`Seção NN`/`NN.x`) + **anti-improviso** (ADR/⚠️) (G7/G8).
- [x] **Precedência de fontes** e **resolução de contradição** (G9/G10).
- [x] **Princípio imutável só por novo ADR** (G11); **mecanismo de ADR** apontando ao Apêndice C (G12).
- [x] **Rastreabilidade** spec↔seção↔ADR↔commit; **commit isolado por seção** (G14).
- [x] **`_estado-atual` = inventário**, não decisão (G17); **15 ADR candidatos** reconhecidos (G18).
- [ ] ⚠️ **Fonte canônica de status** fixada + **reconciliação** do status 00–02 (G15).
- [ ] ⚠️ **Cadência do espelho EN** (por commit × em lote) (G6).
- [ ] ⚠️ **Changelog explícito** vs só Git (G16).
- [ ] ⚠️ **Delegação de aprovação** + cadência/SLA (G13 / 24.20).
- [ ] ⚠️ **Automação/CI** da documentação (24.19).
- [ ] ⚠️ **Priorização dos ADR candidatos** `C.12–C.26` (quais primeiro) (G18).

### 15. Questões em aberto
Cada item é **decisão do dono** (⚠️); os defaults são **propostas** da 24, não decisões autônomas:

- ⚠️ **G15 / Fonte canônica de status.** A fonte é o **cabeçalho do arquivo**, a **tabela do README** ou o
  `INDICE.md`? Há **divergência real**: as Seções 00–02 exibem 🔴 no cabeçalho mas 🟢 no README. Proposta: **o cabeçalho
  do arquivo é a fonte** e o README/INDICE espelham; **reconciliar** o status 00–02 (corrigir o cabeçalho para 🟢).
- ⚠️ **G16 / 24.11–24.12 — Versionamento & changelog.** Manter **só o histórico do Git**, ou instituir um **changelog
  explícito** da Bible (por seção / marcos de release)? Proposta: só Git, com o commit "Bible: aprovar Seção NN" como marco.
- ⚠️ **G6 / 24.13 — Cadência do espelho EN.** O inglês é obrigatório **em cada commit** ou pode entrar **em lote** (como
  o `_TEMPLATE-capitulo.md` permite)? Proposta: espelho **junto** da aprovação (nunca uma seção 🟢 sem EN).
- ⚠️ **G13 / 24.20 — Delegação de aprovação & cadência.** O dono é o **único** aprovador, ou **delega** specs de baixo
  risco ao arquiteto? Há **prazo/SLA** de revisão para não bloquear o desenvolvimento?
- ⚠️ **24.19 — Automação/CI da documentação.** Adotar checagens automáticas (lint de vocabulário proibido, status,
  espelho bilíngue, links)?
- ⚠️ **G18 / Priorização dos ADR candidatos.** Quais dos **15** (`C.12–C.26`) ratificar primeiro para **desbloquear** o
  desenvolvimento (ex.: avatar C.12 + Three.js C.13 juntos; monetização imutável C.20; login código-só C.15)?
- ⚠️ **Retrofit das Seções 00–02.** As de fundação estão *grandfathered* fora das 16 partes (`ADR-0002`); o dono
  decide **se/quando** retrofitar.
- ⚠️ **Regra de desempate explícita.** **Ratificar** como regra única a **precedência canônica** (seção-dona vence;
  cross-módulo → ADR) — o default **já é praticado** (encravado nos blocos "Escopo" de cada capítulo); resta o dono **confirmá-lo** formalmente.

### 16. ADR (Architecture Decision Record)
> *Convenção (que esta seção governa): os `ADR-24-x` abaixo são as **decisões-âncora deste capítulo** (Parte 16);
> uma decisão que afete outro módulo é **promovida** a um **ADR sequencial** (`ADR-NNNN-slug`) em `decisoes/` na
> aprovação do dono — o registro imutável vive lá, não aqui.*
- **ADR-24-A — A 24 formaliza; os ADRs-fonte decidem.** O processo (3 portões, regra de ouro, status, bilíngue,
  desacoplamento, papel de estúdio) **já foi decidido** em [ADR-0001](decisoes/ADR-0001-processo-e-governanca.md)/[ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md);
  a 24 os **consolida em narrativa** e **referencia** — qualquer mudança do padrão é um **novo ADR** que os referencia, **não** uma edição desta seção.
- **ADR-24-B — Precedência de fontes encerra conflitos.** A ordem **Princípios Imutáveis > ADR > Seção aprovada > Spec
  > código** arbitra qualquer contradição; a contradição vira **ADR** (nunca improviso), e a **seção-dona** de uma
  regra tem autoridade sobre ela.
- **ADR-24-C — O dono é o único aprovador; ADRs são imutáveis.** Só o **dono** promove 🟡→🟢 e decide as ⚠️; um ADR
  aceito **nunca** é editado — reverter é um **novo** ADR que referencia o anterior. A delegação de aprovação é
  decisão do dono (§15).
- **ADR-24-D — Um capítulo, um commit; a fonte de status (proposta).** Cada seção é aprovada num **commit isolado**
  (só `docs/bible/*`). **Proposta a ratificar pelo dono (§15):** o **cabeçalho do arquivo** é a **fonte canônica** de
  status (README/INDICE espelham); a reconciliação do status 00–02 é a pendência.

*Decisões cross-módulo não são improvisadas aqui: as pendências acima viram ADR ou item de §15.*

---

## 🇬🇧 Bible Governance

### 1. Objective
To be the **definitive reference for the PROCESS** of the Constela Quest Bible: how a chapter **is born, approved,
versioned and evolved**, who decides what, how **doc × code × doc** contradictions are resolved by **source
precedence**, and how the Bible is **mirrored** (bilingual) and **recorded** (ADRs). It **inherits** the source
decisions [ADR-0001](decisoes/ADR-0001-processo-e-governanca.md)/[ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md)
and **formalizes** them into a chapter; it does **not** re-decide any section's content nor govern the software
(Sections [23](23-roadmap.md)/[18](18-qa-testes.md)). It feeds **Appendices C and F**.

### 2. Context
The **Bible** (`docs/bible/`) is the **official single source of truth** for Constela Quest — every product,
game-design, art and architecture decision is recorded **before** it becomes code (`ADR-0001`). **Current state — the
governance already exists, scattered; 24 consolidates it:**
- **Already in force** (README + ADRs) — the **3 gates** (document → approve → implement+review); the **golden rule**
  ("nothing implemented from a non-🟢 section"); the **status legend** (⬛/🔴/🟡/🟢); the **16 mandatory parts**
  (`ADR-0002`); the **bilingual convention** (pt-BR canonical + EN mirror, "never diverge"); the **studio role**
  (Supercell/Riot/Mojang/Epic — the organization, not copying their games); **no autonomous** product decisions.
- **Decision log** — `decisoes/` is the **Decision Log**: `ADR-0001` (process) and `ADR-0002` (chapter standard), both
  **🟢 Accepted** with **Decider = the product owner (Eduardo/Felipe)**. ADRs are **immutable**; a reversal creates a
  **new** ADR referencing the previous one.
- **Master map** — `INDICE.md` (31 sections/appendices, 979 subsections, with **⚠️ = a subsection depending on the
  owner**); the **README table** is the status roll-up; `_estado-atual/` is the **Q0 reference inventory** (the base
  truth sections cite in "Sources"), **not** a decision.
- **Real pending items** — **15 candidate ADRs** (`C.12–C.26`: 3D avatar, Three.js, immutable monetization, Ed.
  Física/ERER, etc.) await the **owner's ratification**; the `specs/` folder (Gate 1) is **empty**; and there is a
  **status divergence** (Sections 00–02, *grandfathered* out of the 16-part standard, show 🔴 in the file header but 🟢 in the README table).

This chapter **formalizes** the process, sets the source precedence and records what the owner needs to decide.

### 3. Feature philosophy
**"The Bible is the contract: nothing becomes code without passing through it, and nothing in it is improvised."**
Governance exists so that **thousands of schools** trust a product **planned before it is built**. Principles:
**document the intent** (the text suffices to implement without guessing what the owner wanted); **nothing is
implemented from a section that is not 🟢** (status is the lock); **each chapter decides only its own scope** and
**references** the owner section of each rule (decoupling); **a cross-module decision is never improvised** — it
becomes an **ADR** (§16) or an **owner pending item ⚠️** (§15); and **the owner is the sole approver** — the technical
role (Architect + Game Designer + CTO) **proposes and implements**, but does **not** decide product alone.

Link to the **Immutable Principles** ([01](01-principios-imutaveis.md)): an **immutable principle changes only by a
new ADR** approved by the owner that **references the previous one** — never by a silent edit (echoes `01.2`). 24 is
the guardian of that rule for the whole Bible.

### 4. The experience the player should feel
*(N/A for the child — a process chapter; the "experience" here is the **team's and the owner's**.)* The child does
**not** live the governance — they reap a **coherent** product. **The owner** feels **control**: they
know nothing is built without their approval and that each decision stays **traceable** in an ADR. **The team** feels
**clarity**: a single chapter standard, a status legend, a source precedence that **ends debates** ("Principles > ADR
> Section > Spec > code"), and the certainty that **what is 🟢 is safe to implement**. **A new member** understands
the process by reading **one** chapter (this) + `ADR-0001`.

### 5. Complete flow
The **3 gates** and the **lifecycle** — the **canonical process** of every feature (inherited from `ADR-0001`):

1. **Gate 1 — Documentation** — a detailed **spec** in `specs/` (template `_TEMPLATE-spec.md`) and/or the
   corresponding **chapter**, written in the **16-part** standard (`ADR-0002`), pt-BR canonical first.
2. **Gate 2 — Approval** — the **product owner** reviews and approves; the **open questions** (Part 15, ⚠️) are
   resolved by them; cross-module decisions become **ADRs**.
3. **Gate 3 — Faithful implementation → Review → update** — implement **exactly** what was approved; the **QA review**
   covers the **7 axes** (bugs, performance, UX, accessibility, responsiveness, scalability, organization — the
   **software test** strategy is Section [18](18-qa-testes.md)'s); and the Bible is **updated** to reflect what was built.

**A chapter's lifecycle** (status is the lock of the golden rule):

> **⬛ not started** → *(create by copying `_TEMPLATE-capitulo.md`)* → **🔴 draft** → *(review)* → **🟡 in review** →
> *(owner approval)* → **🟢 approved** — and **only 🟢 unlocks implementation**.

The **EN mirror** is filled **after** the pt-BR is stable; the **header** (Status / Standard / Sources / Depends on)
and the **README table** + `INDICE.md` are kept **in sync** with the file.

### 6. Interface (when it exists)
**N/A** — a process chapter, no UI. Governance "surfaces" are the **README status table**, the **`INDICE.md`** (master
map) and the **`decisoes/README.md`** (Decision Log). 24 defines **what** each maintains; there is no child screen.

### 7. UX
The "governance UX" is for the **team and the owner**: a **single** chapter standard, an unambiguous **status
legend**, a **source precedence** that arbitrates conflicts, and **traceability** (spec ↔ section ↔ ADR ↔ commit). No
improvised rule; every relevant decision has **one place** (an ADR or a ⚠️).

### 8. Game Design
**N/A** — 24 governs the **documentation**, not the game. Game mechanics are Sections [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)'s;
24 only ensures that **each game-design decision passes the 3 gates** and becomes an ADR when it crosses modules.

### 9. Business rules
The **governance norms** (24 **formalizes**; the ADR mechanism details are the **Appendix C**'s; the software is
Sections [18](18-qa-testes.md)/[23](23-roadmap.md)'s):

| # | Norm | Rule | Boundary |
|---|------|------|----------|
| G1 | **Single source of truth** | the Bible is the **official single source**; every decision is recorded **before** it becomes code (`ADR-0001`) | 24 (formalizes); source = `ADR-0001` |
| G2 | **The 3 gates** | **document** (spec/chapter) → **approve** (owner) → **implement faithfully + review + update** the Bible | 24; inherited from `ADR-0001` |
| G3 | **Golden rule** | **nothing is implemented** from a section/spec that is **not 🟢** | 24 (formalizes); source = `ADR-0001` |
| G4 | **Status lifecycle** | **⬛→🔴→🟡→🟢**; the author drafts, the QA review moves to 🟡, **only the owner** promotes to 🟢 | 24 (formalizes); legend = README |
| G5 | **Chapter standard** | **16 exact parts** (`ADR-0002`); a non-applicable part = **"N/A — reason"** (never omitted); **document the intent** | 24; standard = `ADR-0002` |
| G6 | **Bilingual** | **pt-BR canonical + EN mirror** in the same file, **never diverge**; the EN is filled after the pt-BR is stable (cadence ⚠️) | 24 ⚠️ (mirror cadence — §15) |
| G7 | **Decoupling** | each chapter **decides only its scope**, **references** the owner section of each rule and **does not redefine** another's rule; the `§N`/`Seção NN`/`NN.x` convention is canonical | 24 |
| G8 | **Anti-improvisation** | a decision impacting **another module** becomes an **ADR** (Part 16) or an **owner pending item ⚠️** (Part 15) — **never** improvised | 24; standard = `ADR-0002` |
| G9 | **Source precedence** | a conflict is resolved by: **Immutable Principles > ADR > approved Section > Spec > code** | 24 |
| G10 | **Contradiction resolution** | on finding a contradiction: **register → open an ADR → reconcile** the texts; the **owner section** of a rule has authority over it | 24 |
| G11 | **Immutable principle** | changes only by a **new ADR** (owner's) that **references the previous one** — never a silent edit (echoes `01.2`) | 24; principles = [01](01-principios-imutaveis.md) |
| G12 | **ADR mechanism** | an ADR is **immutable**; **reverting = a new ADR** referencing the previous; the **numbering, states and transitions** follow the **Appendix C** (C.4/C.5) — 24 **points**, it does not enumerate them | 24 (points); mechanism = Appendix C |
| G13 | **Approver = the owner** | who approves (Gate 2) and decides the ⚠️ is the **product owner** (Eduardo/Felipe); the technical role **proposes and implements**, QA **reviews** — **no** autonomous product decision | 24 ⚠️ (delegation — §15) |
| G14 | **Traceability** | **spec ↔ section ↔ ADR ↔ commit**; a commit **isolated per section** (only `docs/bible/*`, no external file) | 24 |
| G15 | **Canonical status source** | **proposal** (to be confirmed by the owner, §15): the **file header** is the source and the README table/`INDICE.md` **mirror** it; today there is a **divergence** (00–02: 🔴 in the file × 🟢 in the README) to reconcile | 24 ⚠️ (source + reconciliation — §15) |
| G16 | **Versioning** | the **Git history** is the Bible's changelog (no separate `CHANGELOG` file); an explicit changelog is an owner decision | 24 ⚠️ (changelog — §15) |
| G17 | **`_estado-atual` is an inventory** | `_estado-atual/` is a **Q0 base-truth reference**, **not** a decision; it defines when to **re-audit** | 24; roadmap = [23](23-roadmap.md) |
| G18 | **Candidate ADRs** | 24 **recognizes** the **15 candidates** (`C.12–C.26`) as **ratification pending items** and governs the **⚠️ → ADR** flow; it does **not** arbitrate the merit of any (that is the owner's) | 24 (flow); merit = owner; backlog = Appendix C |

### 10. Technical architecture
24's "architecture" is the **structure of the documentation repository** (`docs/bible/`):
- **`README.md`** — the entry point + the **status table** (roll-up) + the high-level conventions.
- **`INDICE.md`** — the **master map** (31 sections/appendices, 979 subsections, owner ⚠️).
- **`NN-*.md`** — the 16-part **chapters**, bilingual, with the canonical header.
- **`decisoes/`** — the **Decision Log** (immutable ADRs) = **Appendix C**.
- **`specs/`** — the feature **specs** (Gate 1; `_TEMPLATE-spec.md`) — today **empty**.
- **`_estado-atual/`** — the Q0 reference **inventory**.
- **`biblia-sensorial/`** — the Sensory Bible of the 9 worlds + Cosmo (linked to Sections [03](03-universo.md)/[15](15-arte-audio-assets.md)).
- **Versioning** — **Git**: a **commit isolated per section** ("Bible: aprovar Seção NN"), containing **only**
  `docs/bible/*` files (the section + the README line).

### 11. Dependencies on other modules
**Consumes / references:**
- **`ADR-0001`/`ADR-0002`** — the **immutable source decisions** 24 inherits and consolidates (does not rewrite).
- **Appendix C** — the **ADR mechanism** (template, states, numbering, traceability, candidate backlog).
- **Appendix F** — the **consolidated DoD** (aggregates each section's Part 14; includes the Gate-3 7 axes).
- **Section [18](18-qa-testes.md)** — the **software test** strategy (24 owns the Gate-3 **process gate**; 18 owns the test strategy).
- **Section [23](23-roadmap.md)** — the **software roadmap** (24 governs the **doc**, not the product phases).
- **`_estado-atual/`** — the Q0 inventory the chapters cite.

**Feeds:**
- **All sections** — the **chapter standard**, the **status legend**, the **bilingual convention** and the **decoupling** each follows.
- **Appendix C** — the **flow** that promotes a ⚠️ pending item to an ADR.
- **Appendix F** — the **Gate-3 7 axes** (24.16) and the Part 14 the consolidated DoD aggregates.

**What breaks if it changes:** if the owner changes the **chapter standard**, it is a **new ADR** referencing
`ADR-0002` (not an edit of this section); if the **source precedence** (G9) changes, every conflict resolution
recalibrates; if **approval** is delegated (G13), Gate 2 gains a new actor.

### 12. Edge cases
- **doc × code contradiction** → apply the **precedence** (G9): code **never** beats a 🟢 section or an ADR; register
  and **open an ADR** (G10).
- **Status divergence (00–02: 🔴 in file × 🟢 in README)** → **reconcile** via the canonical source (G15, ⚠️ §15).
- **EN mirror missing/late** → the EN comes **after** a stable pt-BR; whether in batch or per commit is ⚠️ (G6, §15).
- **Someone "edits" an accepted ADR** → **forbidden** (G12): an ADR is immutable; reverting = a **new** ADR referencing the previous.
- **Autonomous product decision by the technical role** → **forbidden** (G13): propose alternatives and wait for the owner.
- **A cited but non-🟢 section being implemented** → **blocked** by the golden rule (G3).
- **A candidate ADR (C.12–C.26) treated as decided** → no (G18): it is a **pending item** until the owner ratifies.
- **Retrofit of Sections 00–02** → **optional** (`ADR-0002`); an owner decision (§15).

### 13. Future scalability
- **Documentation automation/CI** (24.19) — a lint of forbidden vocabulary, status checks, bilingual-mirror sync and
  link checks — adoption ⚠️ (§15).
- **Approval delegation + cadence/SLA** (24.20) — does the owner delegate low-risk specs to the architect? is there a review deadline? — ⚠️ (§15).
- **An explicit Bible changelog** — beyond Git (G16) — ⚠️ (§15).
- **Retrofit of Sections 00–02** to the 16 parts — when it makes sense (§15).
- **Automated traceability** — linking ADR ↔ commit ↔ section by tooling.

### 14. Implementation checklist
**"Done when" (links to Appendix F). Items marked ⚠️ depend on an owner decision (§15):**
- [x] **Bible = the single, official source**; every decision recorded **before** the code (G1).
- [x] **3 gates** and the **golden rule** formalized (G2/G3).
- [x] **Status lifecycle** ⬛→🔴→🟡→🟢, with the owner promoting to 🟢 (G4).
- [x] **16-part standard** (`ADR-0002`) + **"N/A — reason"** + document the intent (G5).
- [x] **Decoupling** (`§N`/`Seção NN`/`NN.x`) + **anti-improvisation** (ADR/⚠️) (G7/G8).
- [x] **Source precedence** and **contradiction resolution** (G9/G10).
- [x] **Immutable principle only by a new ADR** (G11); **ADR mechanism** pointing to Appendix C (G12).
- [x] **Traceability** spec↔section↔ADR↔commit; **commit isolated per section** (G14).
- [x] **`_estado-atual` = inventory**, not a decision (G17); **15 candidate ADRs** recognized (G18).
- [ ] ⚠️ **Canonical status source** fixed + **reconciliation** of the 00–02 status (G15).
- [ ] ⚠️ **EN mirror cadence** (per commit × in batch) (G6).
- [ ] ⚠️ **Explicit changelog** vs Git only (G16).
- [ ] ⚠️ **Approval delegation** + cadence/SLA (G13 / 24.20).
- [ ] ⚠️ **Documentation automation/CI** (24.19).
- [ ] ⚠️ **Prioritization of the candidate ADRs** `C.12–C.26` (which first) (G18).

### 15. Open questions
Each item is an **owner decision** (⚠️); the defaults are 24's **proposals**, not autonomous decisions:

- ⚠️ **G15 / Canonical status source.** Is the source the **file header**, the **README table** or `INDICE.md`? There
  is a **real divergence**: Sections 00–02 show 🔴 in the header but 🟢 in the README. Proposal: **the file header is
  the source** and README/INDICE mirror it; **reconcile** the 00–02 status (fix the header to 🟢).
- ⚠️ **G16 / 24.11–24.12 — Versioning & changelog.** Keep **only the Git history**, or institute an **explicit
  changelog** (per section / release milestones)? Proposal: Git only, with the "Bible: aprovar Seção NN" commit as the milestone.
- ⚠️ **G6 / 24.13 — EN mirror cadence.** Is the English mandatory **per commit** or may it come **in batch** (as the
  `_TEMPLATE-capitulo.md` allows)? Proposal: the mirror **together with** approval (never a 🟢 section without EN).
- ⚠️ **G13 / 24.20 — Approval delegation & cadence.** Is the owner the **sole** approver, or does **the owner
  delegate** low-risk specs to the architect? Is there a **deadline/SLA** for review so development is not blocked?
- ⚠️ **24.19 — Documentation automation/CI.** Adopt automatic checks (forbidden-vocabulary lint, status, bilingual
  mirror, links)?
- ⚠️ **G18 / Prioritizing the candidate ADRs.** Which of the **15** (`C.12–C.26`) to ratify first to **unblock**
  development (e.g. avatar C.12 + Three.js C.13 together; immutable monetization C.20; code-only login C.15)?
- ⚠️ **Retrofit of Sections 00–02.** The foundation ones are *grandfathered* out of the 16 parts (`ADR-0002`); the
  owner decides **whether/when** to retrofit.
- ⚠️ **Explicit tie-break rule.** **Ratify** the **canonical precedence** (owner section wins; cross-module → ADR) as
  the single tie-break rule — the default is **already practiced** (embedded in each chapter's "Scope" block); the owner **confirms** it formally.

### 16. ADR (Architecture Decision Record)
> *Convention (which this section governs): the `ADR-24-x` below are this chapter's **anchor decisions** (Part 16); a
> decision that affects another module is **promoted** to a **sequential ADR** (`ADR-NNNN-slug`) in `decisoes/` on the
> owner's approval — the immutable record lives there, not here.*
- **ADR-24-A — 24 formalizes; the source ADRs decide.** The process (3 gates, golden rule, status, bilingual,
  decoupling, studio role) **was already decided** in [ADR-0001](decisoes/ADR-0001-processo-e-governanca.md)/[ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md);
  24 **consolidates them into narrative** and **references** them — any change of the standard is a **new ADR** that
  references them, **not** an edit of this section.
- **ADR-24-B — Source precedence ends conflicts.** The order **Immutable Principles > ADR > approved Section > Spec >
  code** arbitrates any contradiction; the contradiction becomes an **ADR** (never improvised), and the **owner
  section** of a rule has authority over it.
- **ADR-24-C — The owner is the sole approver; ADRs are immutable.** Only the **owner** promotes 🟡→🟢 and decides the
  ⚠️; an accepted ADR is **never** edited — reverting is a **new** ADR referencing the previous. Approval delegation
  is an owner decision (§15).
- **ADR-24-D — One chapter, one commit; the status source (proposal).** Each section is approved in an **isolated
  commit** (only `docs/bible/*`). **Proposal to be ratified by the owner (§15):** the **file header** is the
  **canonical source** of status (README/INDICE mirror it); reconciling the 00–02 status is the pending item.

*Cross-module decisions are not improvised here: the pending items above become an ADR or a §15 entry.*
