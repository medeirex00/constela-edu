# 01 — Princípios Imutáveis / Immutable Principles

- **Status:** 🟢 aprovado / approved
- **Fontes / Sources:** `docs/quest/README.md`, `01-arquitetura.md`, `03-gamificacao-progressao.md`, `04-integracao-edu.md`, `_estado-atual/RELATORIO-2026-07-09.md`

---

## 🇧🇷 Princípios Imutáveis

Estes são os compromissos que **não mudam** com moda, pressa ou atalho. Só podem ser alterados por
um **novo ADR aprovado pelo dono** que referencie o anterior. Toda spec deve ser compatível com todos.

> Os princípios **1–16 re-derivam** as 16 constraints do [relatório de estado atual](_estado-atual/RELATORIO-2026-07-09.md)
> (mesmo conteúdo, numeração própria); os **17–18** são acréscimos desta Bible (revisão de QA, 2026-07-09).

### A. Segurança e privacidade da criança
1. **Login só com código, sem senha/PIN.** O código impresso curto e falável (ex.: `SOL1234`) é a
   credencial e pode ficar exposto, como no Elefante Letrado. Defesa: rate-limit por (código, IP)
   dimensionado para ~30 tablets atrás do NAT da escola + escopo mínimo do papel aluno. QR é a mesma
   credencial em figura, trocável.
2. **Sem chat livre, nunca.** Nenhum campo de texto livre acessível ao aluno (nem para nomear um
   pet). Comunicação só por catálogo (mensagens rápidas). Exceção única: o **nome de exibição**, que
   passa por validação estrita (2–20, só letras).
3. **LGPD Art. 14 — coleta mínima.** Sem foto, sem localização, nada além do que a escola já
   cadastrou no Edu. Recursos sociais são **opt-in por escola**. Retenção de telemetria detalhada
   configurável, com anonimização após a saída do aluno (prazo-padrão sugerido de **24 meses,
   a confirmar pelo dono** — ver decisões em aberto).
4. **Conta não fica salva ao sair.** Token só em memória; o boot no tablet compartilhado sempre
   confirma **"É você, {nome}?"** para não herdar a conta anterior. Constelação/estado por perfil,
   nunca vazam entre contas.
5. **Ranking municipal individual nunca é exposto a crianças.** Só entre escolas e apenas no
   Edu/Hub (adultos). Para a criança: a própria constelação (eu × eu) e ranking de turma que zera
   toda semana (sem lanterna exposta).

### B. Ética de jogo
6. **Erro nunca pune.** Sem perda de moedas/estrelas, sem "vidas". XP só cresce; a estrela nunca é
   perdida (vale a melhor tentativa); o teto diário é **celebração, não bloqueio**.
7. **Sem compras dentro do app.** Moedas só se ganham jogando; sem moeda comprável, sem caixas de
   surpresa pagas, sem FOMO agressivo. A escola licencia o produto; o passe de temporada é gratuito
   (o formato exato do passe fica a confirmar).
8. **Zero dark patterns.** Sem manipulação, sem pressão artificial, sem "vidas" que forçam espera ou pagamento.

### C. Experiência da criança
9. **Narração sempre em pt-BR e áudio obrigatório.** Alunos de 1º/2º ano ainda não leem com
   fluência; toda instrução e falas do Cosmo são faladas em português do Brasil.
10. **A criança escolhe como quer ser chamada** na 1ª sessão (cerimônia de boas-vindas), por seleção controlada.
11. **Acessibilidade não-negociável (6–11 anos):** toda instrução com áudio, alvos ≥ 48px, no
    máximo 1 ação primária por tela, navegação sem depender de leitura (ícone + cor + áudio),
    `prefers-reduced-motion` respeitado, modo daltônico, tempo nunca como critério único.
12. **Vocabulário lúdico fixo.** O mapa completo interno→criança e a lista de palavras
    **proibidas** na UI infantil (party, lobby, matchmaking, squad, ranking global, prova,
    exercício, tarefa, erro fatal, reprovado) vivem na [Seção 02](02-vocabulario.md) e são de
    cumprimento obrigatório.

### D. Integridade técnica
13. **Servidor é a autoridade do gabarito.** O catálogo é entregue ao cliente **sem** o campo
    `gabarito`; a mecânica no cliente só devolve a resposta crua e o backend confere. Criança com
    DevTools não fabrica XP.
14. **Economia auditável.** Moedas mudam só via ledger imutável; tentativas, ledger e outbox nunca
    são sobrescritos/apagados. Regras numéricas (XP, preços, tetos) não são hardcoded: padrão no
    código + personalização por escola.
15. **Isolamento multi-escola** por `escola_id` em toda tabela e rota; o token do aluno
    (`papel='aluno'`) nunca vale no Edu e vice-versa.

### E. Integração e identidade
16. **Reuso do Edu, zero reconfiguração.** O Quest reusa a identidade já cadastrada no Edu
    (escolas, alunos, turmas, série). Amizades **nunca cruzam escolas** (teto imutável); o alcance
    no lançamento — turma ou escola — está em aberto (ver [Seção 09](09-social.md)). Integração
    Matific/Elefante por PDF/XLSX (sem API self-serve). Identidade visual única do protótipo
    `constela-play-v7` (design system em `apps/quest/src/design/tokens.css`).

### F. Desempenho, alcance e publicidade
17. **Piso de desempenho e alcance.** O produto tem de rodar bem no **device-alvo mínimo**
    (tablet/Chromebook modesto e compartilhado, wifi fraco). São imutáveis: um device-alvo mínimo
    explícito, orçamento de carregamento/memória e **offline-first** onde a experiência permitir.
    Qualquer decisão de arte (inclusive "assets profissionais/3D") **subordina-se a este piso** —
    não pode quebrar o hardware real da escola. Números concretos: [Seção 11](11-arquitetura.md) e
    [Seção 15](15-arte-audio-assets.md).
18. **Sem anúncios e sem rastreamento de terceiros.** Nenhum anúncio e nenhum SDK de rastreamento
    de terceiros na experiência da criança. Só telemetria própria, mínima e com finalidade
    pedagógica/de produto (ver Princípio 3 e [Seção 12](12-seguranca-privacidade.md)).

---

### ⚠️ O que **não** é princípio (ainda em aberto)
Estes pontos aparecem nos artefatos mas **não estão decididos** — não os trate como imutáveis.
Serão resolvidos por ADR na seção correspondente:
- **Avatar:** humanoide 3D vs. Cosmo 2D → [Seção 04](04-personagens-avatar.md).
- **DOM/SVG-first vs. Three.js oficial** no núcleo do frontend → [Seção 11](11-arquitetura.md).
- **Resíduo do "PIN de figuras"** nos docs antigos vs. decisão de código-só (o código-só é o
  vigente; falta limpar os textos) → ADR de login.
- **Amizade no lançamento:** "mesma turma" vs. "mesma escola" → [Seção 09](09-social.md).

---

## 🇬🇧 Immutable Principles

These commitments **do not change** with fashion, haste or shortcuts. They may only be altered by a
**new ADR approved by the owner** that references the previous one. Every spec must comply with all.

> Principles **1–16 re-derive** the 16 constraints from the [current-state report](_estado-atual/RELATORIO-2026-07-09.md)
> (same content, our own numbering); **17–18** are additions from this Bible (QA review, 2026-07-09).

### A. Child safety & privacy
1. **Code-only login, no password/PIN.** The short, speakable printed code (e.g. `SOL1234`) is the
   credential and may be exposed, like Elefante Letrado. Defense: rate-limit per (code, IP) sized for
   ~30 tablets behind the school NAT + minimal `student` scope. QR is the same credential as a picture, rotatable.
2. **No free chat, ever.** No free-text field reachable by the student (not even to name a pet).
   Communication only via catalog (quick messages). Sole exception: the **display name**, strictly validated (2–20, letters only).
3. **LGPD Art. 14 — minimal collection.** No photo, no location, nothing beyond what the school
   already registered in Edu. Social features are **opt-in per school**. Detailed telemetry retention
   configurable, with anonymization after the student leaves (suggested default of **24 months, to
   be confirmed by the owner** — see open decisions).
4. **Account is not saved on exit.** Token in memory only; boot on the shared tablet always confirms
   **"Is this you, {name}?"** so it never inherits the previous account. Constellation/state per profile, never leaking between accounts.
5. **Individual municipal ranking is never shown to children.** Only between schools and only in
   Edu/Hub (adults). For the child: their own constellation (me vs. me) and a class ranking that resets weekly (no exposed last place).

### B. Game ethics
6. **Mistakes never punish.** No loss of coins/stars, no "lives". XP only grows; a star is never
   lost (best attempt counts); the daily cap is **celebration, not a block**.
7. **No in-app purchases.** Coins are only earned by playing; no buyable currency, no paid loot
   boxes, no aggressive FOMO. Schools license the product; the season pass is free (exact pass
   format to be confirmed).
8. **Zero dark patterns.** No manipulation, no artificial pressure, no "lives" forcing waits or payment.

### C. The child's experience
9. **Narration always in pt-BR, audio mandatory.** 1st/2nd graders don't read fluently yet; every
   instruction and Cosmo's lines are spoken in Brazilian Portuguese.
10. **The child chooses how to be called** in the 1st session (welcome ceremony), via controlled selection.
11. **Non-negotiable accessibility (ages 6–11):** every instruction has audio, targets ≥ 48px, at
    most 1 primary action per screen, navigation without relying on reading (icon + color + audio),
    `prefers-reduced-motion` respected, colorblind mode, time never the sole criterion.
12. **Fixed playful vocabulary.** The full internal→child map and the list of **forbidden**
    child-UI words (party, lobby, matchmaking, squad, global ranking, test, exercise, task, fatal
    error, failed) live in [Section 02](02-vocabulario.md) and are mandatory.

### D. Technical integrity
13. **Server is the answer-key authority.** The catalog reaches the client **without** the
    `gabarito` field; the client mechanic returns only the raw answer and the backend checks it. A child with DevTools cannot fabricate XP.
14. **Auditable economy.** Coins change only via an immutable ledger; attempts, ledger and outbox
    are never overwritten/deleted. Numeric rules (XP, prices, caps) are not hardcoded: default in code + per-school customization.
15. **Multi-school isolation** by `escola_id` in every table and route; the student token
    (`papel='aluno'`) never works in Edu and vice versa.

### E. Integration & identity
16. **Reuse Edu, zero reconfiguration.** Quest reuses the identity already in Edu (schools,
    students, classes, grade). Friendships **never cross schools** (immutable ceiling); the launch
    scope — class or school — is open (see [Section 09](09-social.md)). Matific/Elefante integration
    via PDF/XLSX (no self-serve API). Single visual identity from the `constela-play-v7` prototype
    (design system in `apps/quest/src/design/tokens.css`).

### F. Performance, reach and advertising
17. **Performance and reach floor.** The product must run well on the declared **minimum target
    device** (a modest, shared tablet/Chromebook on weak wifi). Immutable: an explicit minimum
    target device, a load/memory budget and **offline-first** where the experience allows. Any art
    decision (including "professional/3D assets") **is subordinate to this floor** — it must not
    break the school's real hardware. Concrete numbers: [Sec. 11](11-arquitetura.md) and [Sec. 15](15-arte-audio-assets.md).
18. **No ads and no third-party tracking.** No advertising and no third-party tracking SDK in the
    child's experience. Only our own telemetry, minimal and for pedagogical/product purposes (see
    Principle 3 and [Sec. 12](12-seguranca-privacidade.md)).

---

### ⚠️ What is **not** a principle (still open)
These appear in the artifacts but are **not decided** — do not treat them as immutable. They'll be
resolved by ADR in the matching section:
- **Avatar:** 3D humanoid vs. 2D Cosmo → [Sec. 04](04-personagens-avatar.md).
- **DOM/SVG-first vs. official Three.js** in the frontend core → [Sec. 11](11-arquitetura.md).
- **Legacy "picture PIN" residue** vs. code-only (code-only is current; texts need cleanup) → login ADR.
- **Launch friendship:** same class vs. same school → [Sec. 09](09-social.md).
