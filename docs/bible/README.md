# 📖 Constela Quest Bible

> **A fonte oficial e única de verdade do Constela Quest.** Toda decisão de produto,
> game design, direção artística e arquitetura é registrada aqui **antes** de virar código.
> *The official single source of truth for Constela Quest. Every product, game-design, art
> and architecture decision is recorded here **before** it becomes code.*

---

## 🇧🇷 Como esta Bible funciona

**Papel:** o desenvolvimento opera como um estúdio profissional (a *organização* de estúdios
como Supercell, Riot, Mojang, Epic — não a cópia dos jogos). Prioridade: um produto comercial
bem planejado, escalável e preparado para produção, usado por milhares de escolas.

**Os 3 portões de toda funcionalidade:**
1. **Documentação** — uma *spec* detalhada (modelo em [`_TEMPLATE-spec.md`](_TEMPLATE-spec.md)),
   guardada em [`specs/`](specs/).
2. **Aprovação** do dono do produto.
3. **Implementação fiel** → **Revisão** (bugs, performance, UX, acessibilidade,
   responsividade, escalabilidade, organização) → **atualização** da Bible.

**Regra de ouro:** nada é implementado a partir de uma seção que não esteja `🟢 APROVADO`.

**Padrão de capítulo:** todo capítulo segue as **16 partes obrigatórias** do
[`_TEMPLATE-capitulo.md`](_TEMPLATE-capitulo.md) ([ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md)) —
documentando a *intenção*, não só a funcionalidade.

**Legenda de status:** `⬛ não iniciado` · `🔴 rascunho` · `🟡 em revisão` · `🟢 aprovado`.

**Convenção bilíngue:** cada documento tem o **pt-BR como língua canônica** e o **inglês
espelhado** logo abaixo, no mesmo arquivo (as duas versões nunca divergem).

**Direção artística:** personagens, ambientes e efeitos com qualidade de jogo moderno —
assets profissionais (GLB/GLTF, sprites, R3F/Three.js, animações, partículas, shaders,
física). O HTML serve só como interface; personagens nunca são desenhados com `div`/SVG simples.

---

## 📑 Estrutura / Structure

> 🗺️ **O índice detalhado (subseção a subseção) vive em [`INDICE.md`](INDICE.md)** — 31 seções/apêndices,
> 979 subseções, com as decisões em aberto sinalizadas. Abaixo, o mapa de alto nível + status de cada documento.

| # | Seção / Section | Arquivo / File | Status |
|---|-----------------|----------------|:------:|
| 00 | Visão & Norte / Vision & North Star | `00-visao-e-norte.md` | 🟢 |
| 01 | Princípios Imutáveis / Immutable Principles | `01-principios-imutaveis.md` | 🟢 |
| 02 | Vocabulário Canônico / Canonical Vocabulary | `02-vocabulario.md` | 🟢 |
| 03 | O Universo & a Fantasia / The Universe & Fantasy | `03-universo.md` | 🟢 |
| 04 | Personagens & Avatar / Characters & Avatar | `04-personagens-avatar.md` | 🟢 |
| 05 | Sistemas de Jogo / Game Systems | `05-sistemas-de-jogo.md` | 🟢 |
| 06 | Design Pedagógico & BNCC / Learning Design | `06-pedagogico-bncc.md` | 🟢 |
| 07 | UX, Fluxos & Navegação / UX, Flows & Navigation | `07-ux-fluxos-navegacao.md` | 🟢 |
| 08 | Onboarding & FTUE do Aluno / Student Onboarding | `08-onboarding-ftue.md` | 🟢 |
| 09 | Social & Comunidade Segura / Safe Social | `09-social.md` | 🟢 |
| 10 | Professor & Família / Teacher & Family | `10-professor-familia.md` | 🟢 |
| 11 | Arquitetura Técnica / Technical Architecture | `11-arquitetura.md` | 🟢 |
| 12 | Segurança, Privacidade & LGPD / Security & Privacy | `12-seguranca-privacidade.md` | 🟢 |
| 13 | Acessibilidade & Bem-estar / Accessibility & Well-being | `13-acessibilidade.md` | 🟢 |
| 14 | Infra, Deploy, Backup & DR (SRE/DevOps) / Infrastructure | `14-infra-deploy-dr.md` | 🟢 |
| 15 | Direção de Arte, Áudio & Pipeline de Assets / Art & Asset Pipeline | `15-arte-audio-assets.md` | 🟢 |
| 16 | Localização & i18n / Localization | `16-localizacao-i18n.md` | 🟢 |
| 17 | Telemetria, Métricas & Analytics / Analytics | `17-telemetria-metricas.md` | 🟢 |
| 18 | QA & Estratégia de Testes / QA & Testing | `18-qa-testes.md` | 🟢 |
| 19 | Live-ops & Configuração Remota / Live-ops | `19-liveops.md` | 🟢 |
| 20 | Migração de Dados & Importação / Data Migration & Import | `20-migracao-importacao.md` | 🟢 |
| 21 | Suporte & Operação de Escola / Support & School Ops | `21-suporte-operacao.md` | 🟢 |
| 22 | Monetização & Modelo de Negócio / Business Model | `22-monetizacao.md` | 🟢 |
| 23 | Roadmap & Fases (Q0–Q6) / Roadmap & Phases | `23-roadmap.md` | 🟢 |
| 24 | Governança da Bible / Bible Governance | `24-governanca.md` | 🟢 |
| A | Glossário / Glossary | `apendice-A-glossario.md` | ⬛ |
| B | Contratos de API & Dados / API & Data Contracts | `apendice-B-api-dados.md` | ⬛ |
| C | Registro de Decisões (ADR) / Decision Log | [`decisoes/`](decisoes/) | 🟢 |
| D | Catálogo de Eventos de Telemetria / Telemetry Event Catalog | `apendice-D-eventos-telemetria.md` | ⬛ |
| E | Wireframes/Mockups de Referência / Reference Wireframes | `apendice-E-wireframes.md` | ⬛ |
| F | Checklists Consolidados (DoD) / Consolidated Checklists | `apendice-F-checklists-dod.md` | ⬛ |

**Partes:** I — Produto & Visão (00–02) · II — O Jogo: Design & UX (03–08) · III — Comunidade (09–10) ·
IV — Técnico & Segurança (11–14) · V — Produção & Operação (15–21) · VI — Negócio & Governança (22–24) · Apêndices (A–F).

### Pastas / Folders
- [`specs/`](specs/) — especificações de funcionalidades (Portão 1). *Feature specs (Gate 1).*
- [`decisoes/`](decisoes/) — ADRs, o histórico de decisões datadas. *Architecture/Design Decision Records.*
- [`_estado-atual/`](_estado-atual/) — auditoria de referência do que existe hoje (interno, pt-BR). *Reference audit of the current state.*
- [`biblia-sensorial/`](biblia-sensorial/) — **Bíblia Sensorial do Universo**: direção artística, narrativa e emocional dos 9 mundos + o Cosmo (ligada às Seções 03 e 15). *Sensory Bible of the universe.*

---

## 🇬🇧 How this Bible works

**Role:** development runs like a professional studio (the *organization* of studios such as
Supercell, Riot, Mojang, Epic — not copying their games). Priority: a well-planned, scalable,
production-ready commercial product used by thousands of schools.

**The 3 gates for every feature:**
1. **Documentation** — a detailed spec (see [`_TEMPLATE-spec.md`](_TEMPLATE-spec.md)), stored in [`specs/`](specs/).
2. **Approval** from the product owner.
3. **Faithful implementation** → **Review** (bugs, performance, UX, accessibility, responsiveness, scalability, code organization) → **Bible update**.

**Golden rule:** nothing is implemented from a section that is not `🟢 APPROVED`.

**Chapter standard:** every chapter follows the **16 mandatory parts** in
[`_TEMPLATE-capitulo.md`](_TEMPLATE-capitulo.md) ([ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md)) —
documenting *intent*, not just the feature.

**Status legend:** `⬛ not started` · `🔴 draft` · `🟡 in review` · `🟢 approved`.

**Bilingual convention:** each document keeps **pt-BR as the canonical language** and an
**English mirror** right below it, in the same file (the two never drift apart).

**Art direction:** characters, environments and effects at modern-game quality — professional
assets (GLB/GLTF, sprites, R3F/Three.js, animations, particles, shaders, physics). HTML is
only the interface; characters are never drawn with plain `div`/SVG.
