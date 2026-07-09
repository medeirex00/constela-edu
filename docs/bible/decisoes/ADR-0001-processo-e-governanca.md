# ADR-0001 — Processo de estúdio e a Constela Quest Bible

- **Status:** 🟢 Aceito / Accepted
- **Data / Date:** 2026-07-09
- **Decisor / Decider:** Dono do produto (Eduardo/Felipe)

---

## 🇧🇷 Contexto
O projeto evoluía rápido, mas começou a perder consistência por implementar
funcionalidades imediatamente, sem documentação nem alinhamento prévio. O produto é
comercial e será usado por milhares de escolas.

## Decisão
1. **Modelo de estúdio profissional.** O papel técnico passa a ser Arquiteto de Software +
   Game Designer + CTO. A prioridade deixa de ser escrever código; passa a ser planejar.
2. **Fluxo obrigatório em 3 portões** para toda funcionalidade: (1) Documentação detalhada
   → (2) Aprovação do dono → (3) Implementação fiel → Revisão → atualização da doc.
3. **Sem decisões autônomas** de UX, interface, jogabilidade, arquitetura ou direção
   artística. Em dúvida, propor alternativas e aguardar alinhamento.
4. **Constela Quest Bible** é a fonte oficial e única de verdade (`docs/bible/`).
5. **Formato:** multi-arquivo versionado no Git (índice + uma seção por arquivo + `specs/`
   + `decisoes/`).
6. **Idioma:** bilíngue — pt-BR canônico + inglês espelhado no mesmo arquivo.
7. **Ritmo:** estrutura e processo aprovados primeiro; depois preenchimento seção a seção,
   cada uma com aprovação própria.
8. **Direção artística:** arquitetura sempre preparada para assets profissionais
   (GLB/GLTF, sprites, R3F/Three.js, animações, partículas, shaders, física); HTML só como
   interface; nada de personagens em `div`/SVG simples.
9. **Autonomia técnica** continua valendo apenas para **execução** (rodar comandos, testes,
   builds, instalar deps, refatorar, corrigir bugs) e para implementar fielmente o que já
   foi aprovado — nunca para decidir produto/design/arte.

## Consequências
- Toda nova funcionalidade nasce como spec em `specs/` (modelo em `_TEMPLATE-spec.md`).
- Nada é implementado a partir de uma seção que não esteja 🟢 APROVADO.
- Manutenção dobrada pela versão bilíngue (aceito conscientemente).
- Decisões passadas e futuras ficam rastreáveis aqui em `decisoes/`.

---

## 🇬🇧 Context
The project was moving fast but started losing consistency by implementing features
immediately, without documentation or prior alignment. It is a commercial product meant for
thousands of schools.

## Decision
1. **Professional studio model** — the technical role becomes Software Architect + Game
   Designer + CTO; planning takes priority over writing code.
2. **Mandatory 3-gate flow** for every feature: (1) detailed documentation → (2) owner
   approval → (3) faithful implementation → review → doc update.
3. **No autonomous decisions** on UX, interface, gameplay, architecture or art direction;
   when in doubt, propose alternatives and wait for alignment.
4. **Constela Quest Bible** is the official single source of truth (`docs/bible/`).
5. **Format:** multi-file, Git-versioned (index + one file per section + `specs/` + `decisoes/`).
6. **Language:** bilingual — canonical pt-BR + English mirror in the same file.
7. **Cadence:** approve structure and process first, then fill section by section, each with its own approval.
8. **Art direction:** architecture always ready for professional assets (GLB/GLTF, sprites,
   R3F/Three.js, animations, particles, shaders, physics); HTML only as interface; no plain `div`/SVG characters.
9. **Technical autonomy** now applies only to **execution** and to faithfully implementing
   what was approved — never to deciding product/design/art.

## Consequences
- Every new feature starts as a spec in `specs/` (template in `_TEMPLATE-spec.md`).
- Nothing is implemented from a section that is not 🟢 APPROVED.
- Doubled maintenance from the bilingual version (consciously accepted).
- Past and future decisions stay traceable here in `decisoes/`.
