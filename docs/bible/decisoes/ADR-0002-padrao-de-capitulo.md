# ADR-0002 — Padrão obrigatório de capítulo da Bible

- **Status:** 🟢 Aceito / Accepted
- **Data / Date:** 2026-07-09
- **Decisor / Decider:** Dono do produto (Eduardo/Felipe)
- **Relacionado / Related:** [ADR-0001](ADR-0001-processo-e-governanca.md), [`_TEMPLATE-capitulo.md`](../_TEMPLATE-capitulo.md)

---

## 🇧🇷 Contexto
A Bible precisa ser a fonte de verdade útil por 5+ anos, lida por dev, designer, artista 3D,
animador, game designer, QA, PO e futuros membros da equipe. Sem um padrão único, os capítulos
divergem em profundidade e deixam a intenção do dono implícita.

## Decisão
1. **Todo capítulo segue EXATAMENTE 16 partes, na ordem:** (1) Objetivo · (2) Contexto ·
   (3) Filosofia da funcionalidade · (4) Experiência que o jogador deve sentir · (5) Fluxo completo ·
   (6) Interface (quando existir) · (7) UX · (8) Game Design · (9) Regras de negócio ·
   (10) Arquitetura técnica · (11) Dependências com outros módulos · (12) Casos extremos ·
   (13) Escalabilidade futura · (14) Checklist de implementação · (15) Questões em aberto ·
   (16) ADR. Parte não aplicável recebe **"N/A — <motivo>"**, nunca é omitida.
2. **Documentar a intenção, não só a funcionalidade.** Todo capítulo explicita: por que existe ·
   que problema resolve · que sentimento deve causar · como conversa com o ecossistema Constela.
3. **Padrão de qualidade:** o texto deve bastar para implementar **sem adivinhar** a intenção do dono.
4. **Regra anti-improviso:** decisão que impacta outro módulo **nunca** é improvisada — vira **ADR**
   (Parte 16) ou **decisão pendente** (Parte 15, marcada ⚠️).
5. **Bilíngue:** pt-BR canônico + espelho EN no mesmo arquivo.
6. O modelo vive em [`_TEMPLATE-capitulo.md`](../_TEMPLATE-capitulo.md).

## Consequências
- Capítulos ficam comparáveis, completos e à prova de "adivinhação".
- As Seções 00–02 foram escritas antes deste padrão (formato de fundação). Ficam **grandfathered**
  como referência; retrofit para as 16 partes é opcional e será proposto se/quando fizer sentido.
- Cada capítulo tende a gerar ADRs — o registro em `decisoes/` cresce por design.

---

## 🇬🇧 Context
The Bible must be a source of truth useful for 5+ years, read by devs, designers, 3D artists,
animators, game designers, QA, PO and future team members. Without a single standard, chapters
diverge in depth and leave the owner's intent implicit.

## Decision
1. **Every chapter follows EXACTLY 16 parts, in order:** (1) Objective · (2) Context ·
   (3) Feature philosophy · (4) The experience the player should feel · (5) Complete flow ·
   (6) Interface (when it exists) · (7) UX · (8) Game Design · (9) Business rules ·
   (10) Technical architecture · (11) Dependencies on other modules · (12) Edge cases ·
   (13) Future scalability · (14) Implementation checklist · (15) Open questions · (16) ADR.
   A non-applicable part gets **"N/A — <reason>"**, never omitted.
2. **Document intent, not just the feature:** why it exists · what problem it solves · what feeling
   it should cause · how it talks to the Constela ecosystem.
3. **Quality bar:** the text must be enough to implement **without guessing** the owner's intent.
4. **Anti-improvisation rule:** a decision impacting another module is **never** improvised — it
   becomes an **ADR** (Part 16) or a **pending decision** (Part 15, marked ⚠️).
5. **Bilingual:** canonical pt-BR + EN mirror in the same file.
6. The template lives in [`_TEMPLATE-capitulo.md`](../_TEMPLATE-capitulo.md).

## Consequences
- Chapters become comparable, complete and guess-proof.
- Sections 00–02 predate this standard (foundation format); they are **grandfathered** as reference;
  retrofitting to the 16 parts is optional and will be proposed if/when it makes sense.
- Each chapter tends to spawn ADRs — the `decisoes/` log grows by design.
