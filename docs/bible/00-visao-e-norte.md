# 00 — Visão & Norte / Vision & North Star

- **Status:** 🔴 rascunho / draft
- **Fontes / Sources:** `docs/quest/README.md`, `docs/quest/05-roadmap.md`, `_estado-atual/RELATORIO-2026-07-09.md`, [`ADR-0001`](decisoes/ADR-0001-processo-e-governanca.md)

---

## 🇧🇷 Visão & Norte

### O que é
O Constela Quest é um **jogo educacional** para crianças do 1º ao 5º ano (6–11 anos), parte do
ecossistema Constela (o **Hub**, com o **Edu** e o **Quest** sob ele). A ambição declarada não é
"um sistema escolar com pontos", e sim um **jogo de verdade** cujo conteúdo por acaso ensina.

### Para quem
- **Jogador:** a criança de 6–11 anos, muitas vezes ainda não-leitora fluente, usando um
  tablet/Chromebook **compartilhado** no wifi da escola.
- **Comprador:** a escola/rede (licencia o produto).
- **Apoiadores:** o professor (acompanha o aprendizado) e a família (acompanha e apoia).

### Personas
Quatro pessoas que representam o público. Toda decisão deve servir a pelo menos uma sem prejudicar as outras.

- **Miguel, 6 anos — 1º ano, ainda não lê com fluência.** Usa o tablet compartilhado da escola;
  reconhece o mundo por ícones, cores e som, não por texto. *Objetivo:* brincar e se sentir capaz.
  *Frustração:* travar num botão que não sabe ler. *Exige:* áudio em tudo, ícones grandes, no máximo uma ação por tela.
- **Sofia, 10 anos — 5º ano, leitora fluente, já joga no celular.** Compara o Quest com os jogos
  que ama. *Objetivo:* personalizar seu personagem, desbloquear coisas, superar a si mesma.
  *Frustração:* sentir "cara de dever de casa". *Exige:* profundidade, encanto e progressão que valham o tempo dela.
- **Profª. Andréa — professora do 3º ano.** *Objetivo:* saber quem aprendeu o quê (BNCC) num olhar,
  sem virar trabalho extra. *Frustração:* sistema que exige configuração ou planilha. *Exige:* zero
  reconfiguração (reusa o Edu), painel claro, sem expor ranking individual da criança.
- **Dona Cláudia — mãe/responsável.** *Objetivo:* saber que a filha está segura e aprendendo.
  *Frustração:* app que pede dados demais ou empurra compras. *Exige:* privacidade (LGPD), zero compras, transparência.

> As sub-faixas do público infantil (**não-leitor** vs. **leitor fluente**) são *product-critical*:
> é o que sustenta o princípio de **áudio obrigatório**.

### Por que existe (a promessa)
Transformar o estudo em algo que a criança **escolhe** fazer. Sucesso não é "usou porque
mandaram" — é a criança **querer voltar**.

### A pergunta-guia (o norte)
Toda decisão passa por uma pergunta:
> **"Uma criança entraria no Constela Quest mesmo sem ser obrigada?"**

Se a resposta for "não", a decisão está errada.

### Os 4 pilares
1. **Autonomia** — a criança escolhe o caminho, o personagem e o ritmo.
2. **Progresso visível** — cada esforço vira algo que se vê crescer (a **Constelação**).
3. **Vínculo** — o Cosmo, o mundo e os personagens criam relação afetiva.
4. **Surpresa** — sempre há algo novo, gratuito, que encanta.

### O norte, em forma de métrica *(proposta — a calibrar)*
A pergunta-guia, virada régua de acompanhamento: **"a criança volta amanhã?"** É a leitura
afetiva de retenção que queremos privilegiar. O doc 05 usa isso como régua de corte de fase.
Os **alvos quantitativos** (ex.: retenção D1/D7/D30) e a relação formal com **aprendizado** e
**saúde de uso** ainda **não estão definidos** — proposta a calibrar na
[Seção 17 — Telemetria & Métricas](17-telemetria-metricas.md). Enquanto não houver essa
definição, não afirmamos precedência da retenção sobre o aprendizado.

### O que o Constela Quest NÃO é
- Não é um "sistema escolar gamificado" nem uma prova com fantasia.
- Não é um catálogo de exercícios com estrelinhas.
- Não compete no preço do esforço mínimo — a aposta é **encanto e qualidade**.
- Não tem compras, não pune o erro, não usa dark patterns.

### Ambição de qualidade e a tensão em aberto
O dono expressou (2026-07-09, [ADR-0001](decisoes/ADR-0001-processo-e-governanca.md)) uma
**direção forte** de qualidade de jogo moderno, com preferência por **assets profissionais**
(3D/GLB, sprites, R3F/Three.js) em vez de personagens desenhados em HTML/CSS.

> ⚠️ **Decisão em aberto, não princípio.** Essa direção **conflita** com a arquitetura
> documentada em `docs/quest` (**DOM/SVG/CSS-first**; "PixiJS, não Three.js"), e o código já
> adotou Three.js **apenas no avatar**. O alcance disso — só o personagem? o jogo todo? como
> conciliar com tablets/Chromebooks baratos? — precisa ser decidido e reconciliado, com um piso
> de desempenho. Ver [Seção 04](04-personagens-avatar.md), [Seção 11](11-arquitetura.md) e
> [Seção 15](15-arte-audio-assets.md). **Não trate como fechado.**

### Pendências desta seção (do QA)
A calibrar com o dono, quando priorizado: métrica-norte quantificável + guardrails · critérios de
sucesso e "definição de lançamento" · posicionamento/mercado vs. incumbentes (Matific, Elefante).

---

## 🇬🇧 Vision & North Star

### What it is
Constela Quest is an **educational game** for children in grades 1–5 (ages 6–11), part of the
Constela ecosystem (the **Hub**, with **Edu** and **Quest** under it). The stated ambition is not
"a school system with points", but a **real game** whose content happens to teach.

### Who it's for
- **Player:** the 6–11-year-old child, often not yet a fluent reader, on a **shared**
  tablet/Chromebook over school wifi.
- **Buyer:** the school/network (licenses the product).
- **Supporters:** the teacher (follows learning) and the family (follows and supports).

### Personas
Four people who represent the audience. Every decision must serve at least one without hurting the others.

- **Miguel, 6 — 1st grade, not yet a fluent reader.** Uses the shared school tablet; recognizes the
  world by icons, color and sound, not text. *Goal:* to play and feel capable. *Frustration:* getting
  stuck on a button he can't read. *Requires:* audio everywhere, big icons, at most one action per screen.
- **Sofia, 10 — 5th grade, fluent reader, already games on her phone.** Compares Quest to the games
  she loves. *Goal:* customize her character, unlock things, beat herself. *Frustration:* it feeling
  like "homework". *Requires:* depth, delight and progression worth her time.
- **Ms. Andréa — 3rd-grade teacher.** *Goal:* see who learned what (BNCC) at a glance, without extra
  work. *Frustration:* a system that needs setup or spreadsheets. *Requires:* zero reconfiguration
  (reuses Edu), a clear dashboard, no exposed individual child ranking.
- **Cláudia — mother/guardian.** *Goal:* to know her daughter is safe and learning. *Frustration:*
  an app that asks for too much data or pushes purchases. *Requires:* privacy (LGPD), zero purchases, transparency.

> The child sub-ranges (**non-reader** vs. **fluent reader**) are *product-critical*: they are what
> the **mandatory-audio** principle rests on.

### Why it exists (the promise)
Turn studying into something the child **chooses** to do. Success isn't "used because told to" —
it's the child **wanting to come back**.

### The guiding question (north star)
Every decision faces one question:
> **"Would a child open Constela Quest even without being told to?"**

If the answer is "no", the decision is wrong.

### The 4 pillars
1. **Autonomy** — the child chooses the path, the character and the pace.
2. **Visible progress** — every effort becomes something you watch grow (the **Constellation**).
3. **Bond** — Cosmo, the world and the characters build an emotional relationship.
4. **Surprise** — there's always something new and free that delights.

### The north star, as a metric *(proposal — to calibrate)*
The guiding question turned into a tracking measure: **"does the child come back tomorrow?"** Doc 05
uses it as a phase cut-off rule. The **quantitative targets** (e.g. D1/D7/D30 retention) and the
formal relationship with **learning** and **healthy usage** are **not yet defined** — a proposal to
calibrate in [Section 17](17-telemetria-metricas.md). Until then, we do not claim retention takes
precedence over learning.

### What Constela Quest is NOT
- Not a "gamified school system" nor a test in disguise.
- Not a catalog of exercises with little stars.
- It doesn't compete on the price of minimum effort — the bet is **delight and quality**.
- No purchases, no punishing mistakes, no dark patterns.

### Quality ambition and the open tension
The owner expressed (2026-07-09, [ADR-0001](decisoes/ADR-0001-processo-e-governanca.md)) a **strong
direction** toward modern-game quality, preferring **professional assets** (3D/GLB, sprites,
R3F/Three.js) over characters drawn in HTML/CSS.

> ⚠️ **Open decision, not a principle.** This direction **conflicts** with the architecture
> documented in `docs/quest` (**DOM/SVG/CSS-first**; "PixiJS, not Three.js"), and the code already
> adopted Three.js **only for the avatar**. Its scope — just the character? the whole game? how to
> reconcile with cheap tablets/Chromebooks? — must be decided and reconciled, with a performance
> floor. See [Sec. 04](04-personagens-avatar.md), [Sec. 11](11-arquitetura.md) and
> [Sec. 15](15-arte-audio-assets.md). **Do not treat as settled.**

### Pending for this section (from QA)
To calibrate with the owner when prioritized: quantifiable north-star metric + guardrails · success
criteria and "definition of launch" · positioning/market vs. incumbents (Matific, Elefante).
