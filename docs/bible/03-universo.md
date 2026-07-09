# 03 — O Universo & a Fantasia / The Universe & Fantasy

- **Status:** 🔴 rascunho / draft
- **Padrão / Standard:** [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) (16 partes)
- **Fontes / Sources:** `docs/quest/README.md`, `docs/quest/02-banco-de-dados.md`, `docs/quest/03-gamificacao-progressao.md`, `docs/quest/05-roadmap.md`, `apps/quest/src/lobby/materias.ts`, `cenasTema.ts`, protótipo `constela-play-v7.html`, `_estado-atual/RELATORIO-2026-07-09.md`
- **Depende de / Depends on:** [02](02-vocabulario.md), [04](04-personagens-avatar.md), [05](05-sistemas-de-jogo.md), [06](06-pedagogico-bncc.md), [07](07-ux-fluxos-navegacao.md), [11](11-arquitetura.md), [15](15-arte-audio-assets.md)
- **Dá origem a / Spawns:** ADR (política de planeta não-ofertado), ADR (fonte da verdade do catálogo); **depende de** ADRs cross-módulo de Avatar ([04](04-personagens-avatar.md)) e Renderização ([11](11-arquitetura.md)).

---

## 🇧🇷 O Universo & a Fantasia

### 1. Objetivo
Definir a **ficção canônica** do Constela Quest: o universo, os planetas, a hierarquia do mundo
(Universo → Planeta → Jornada → Missão → Desafio), a metáfora de progresso (a Constelação) e o papel
do Cosmo na história. É o *contêiner emocional* sobre o qual todos os outros capítulos (arte, sistemas,
UX, conteúdo) constroem. Resolve o problema de **transformar "matéria escolar" em "lugar que a criança
escolhe visitar"**.

### 2. Contexto
O Constela Quest é a ponta lúdica do ecossistema **Constela (Hub → Edu → Quest)**: o Edu é a verdade
administrativa (escolas, alunos, turmas, série, BNCC); o Quest é o mundo onde esses dados viram jogo.
O universo é o que dá sentido a tudo — sem ele, seria só um **caderno digital**.

A identidade visual canônica parte do protótipo **`constela-play-v7.html`** (Princípio 16 / Seção [01](01-principios-imutaveis.md)).

**Estado atual (Q0):** os 9 planetas já existem **visualmente** (cenas temáticas, partículas,
constelações vivas, em `materias.ts`/`cenasTema.ts`), mas **sem jogabilidade** — "Jogar agora" ainda é
só um aviso na tela (*toast*). ⚠️ **Atenção:** esses assets são **scaffold** — o que é direção de arte
canônica a preservar vs. andaime a refazer é entregável da Seção [15](15-arte-audio-assets.md) (ver Parte 15).

### 3. Filosofia da funcionalidade
**Por que um universo?** O espaço é a metáfora máxima de **curiosidade e exploração**, e dá uma imagem
literal de **progresso**: estrelas que se acendem e formam constelações. Uma criança não "faz
Matemática"; ela **viaja para o Planeta Numéria**. A troca de enquadramento (matéria → lugar) é o
coração do produto.

Amarração aos 4 pilares (Seção [00](00-visao-e-norte.md)):
- **Autonomia** — a criança escolhe para qual planeta ir.
- **Progresso visível** — cada esforço acende uma estrela na Constelação.
- **Vínculo** — o Cosmo guia, e cada planeta tem identidade afetiva própria.
- **Surpresa** — cada planeta é um mundo diferente; o céu esconde coisas.

**Anti-meta:** o universo **nunca** pode virar um "menu de disciplinas". É um cosmos vivo, não uma lista.

### 4. Experiência que o jogador deve sentir
- **Encantamento e posse:** "este é o **meu** universo" — o céu lembra dela (a Constelação cresce a cada volta).
- **Curiosidade:** "o que será que tem naquele planeta?" — o mundo convida a explorar.
- **Pertencimento:** o Cosmo esperando, o planeta reconhecendo o retorno — **nunca uma tela fria**.
- **Vastidão gentil:** grande e cheio de possibilidades, mas nunca assustador ou confuso para 6 anos.

### 5. Fluxo completo
Nível-mundo (a jogabilidade da missão vive na Seção [05](05-sistemas-de-jogo.md)):
1. **Boot → tela-casa:** a criança chega ao **céu/universo** (hub de retorno).
2. **Escolha do planeta:** toca num planeta-matéria; a **cena temática** assume a tela (fundo, cor,
   partículas e trilha mudam para a identidade daquele mundo).
3. **Entrada na Jornada:** o planeta mostra suas Jornadas (trilhas por ano/BNCC) → Missões.
4. **Retorno ao céu:** sempre há caminho de volta; o progresso fica visível na Constelação.
- **Primeira vez:** o universo se revela aos poucos (ligado à cerimônia e ao onboarding, Seção [08](08-onboarding-ftue.md)).
- **Retorno:** o céu "lembra" — a Constelação e a Chama do Cosmo mostram continuidade.

> A **coreografia** dessas passagens (céu→planeta→Jornada→volta) é canon deste capítulo, mas ainda **em
> aberto** — ver Parte 15.

### 6. Interface (quando existir)
As superfícies do universo (specs de tela na Seção [07](07-ux-fluxos-navegacao.md); arte na Seção [15](15-arte-audio-assets.md)):
- **Céu da tela-casa** — fundo vivo e **tocável** (constelações que se acendem).
- **Seleção de planetas** — os 9 mundos por matéria (o **modelo espacial** — mapa único navegável vs.
  trilho vs. órbita — está em aberto, Parte 15).
- **Cena do planeta** — composição por camadas (planeta + constelações vivas + partículas + primeiro
  plano temático), trocada por matéria.
- **Tela da Constelação** — o mapa de progresso pessoal (eu × eu, nunca ranking). *Se é a mesma
  superfície do céu da tela-casa ou uma tela distinta: em aberto (Parte 15).*

> ⚠️ O rótulo infantil da tela-casa está **em aberto** ("lobby" é palavra proibida) — decisão vive na
> Seção [02](02-vocabulario.md).

### 7. UX
- **Navegável sem ler:** cada planeta é reconhecível por **ícone + cor + som** (acessibilidade,
  Seção [13](13-acessibilidade.md)); a narração pt-BR **nomeia** o planeta ao entrar.
- **Vivo:** partículas ambientes e constelações que se desenham dão sensação de mundo respirando.
- **Vocabulário canônico** (Seção [02](02-vocabulario.md)): sempre "Planeta / Jornada / Missão /
  Constelação", nunca "matéria/disciplina/menu".
- **Reduced-motion:** toda a vida ambiente degrada com elegância (Seção [13](13-acessibilidade.md)).

### 8. Game Design
**Estrutura do mundo:** `Universo → Planeta (matéria) → Jornada (ano/BNCC) → Missão → Desafio`.

**A Constelação (metáfora de progresso):** a maestria numa Missão rende **estrelas (0–3)**; **concluir
uma Jornada** acende uma **estrela nova no céu pessoal** da criança, e as estrelas vão formando
**constelações** — o desenho do progresso dela. É **eu × eu**, nunca comparação (Princípio 5,
Seção [01](01-principios-imutaveis.md)). *A regra canônica de estrela/XP/economia vive na
Seção [05](05-sistemas-de-jogo.md); aqui fica a **fantasia**, não a fórmula.*

**Escopo — ficção vs. conteúdo:** o **universo tem 9 planetas** (ficção canônica, confirmada em
`materias.ts`). **Quantos planetas terão conteúdo jogável no lançamento** é decisão de conteúdo do dono
(o roadmap sugere 1 planeta profundo — Matemática/Q1 — e os demais em Q2/Q5) → **⚠️ pendente**
(Parte 15), coordenada com Seções [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md).

**Exploração, não obrigação:** o mundo é dirigido por curiosidade e **erro nunca fecha um caminho**
(Princípio 6). *Se há progressão de desbloqueio entre planetas ou tudo fica aberto é decisão pendente (Parte 15).*

**Expansão:** mundos sazonais e eventos entram por live-ops (Seção [19](19-liveops.md)).

### 9. Regras de negócio
**Os 9 planetas canônicos** (matéria → nome de ficção; nomes próprios não se traduzem):

| Matéria (interno) | Planeta (criança) | Identidade (dica) |
|-------------------|-------------------|-------------------|
| Matemática | **Numéria** | números, lógica, geometria |
| Português | **Palavras** | leitura, escrita, linguagem |
| Ciências | **Biozênia** | vida, natureza, experimentos |
| Geografia | **Terra Nova** | mapas, lugares, planeta Terra |
| História | **Chronos** | tempo, memória, civilizações |
| Inglês | **Oxford** | segunda língua |
| Artes | **Colorium** | cor, criação, expressão |
| Ed. Física | **Movi** | corpo, movimento *(⚠️ Q5, ver Parte 15)* |
| ERER | **Raízes** | Ed. das Relações Étnico-Raciais *(⚠️ Q5, curadoria humana)* |

- Um planeta **existe para a criança** se a escola/currículo oferece aquela matéria. **⚠️ O que
  acontece quando não oferece** (o planeta some, aparece bloqueado, ou vira "em breve") é **decisão
  pendente** (Parte 15).
- **Jornadas** são liberadas pelo **ano escolar** da matrícula (`turmas.ano_escolar`); a lógica de
  gating/BNCC vive na Seção [06](06-pedagogico-bncc.md).
- **Imutável:** o **servidor é a autoridade do gabarito** — o catálogo chega ao cliente **sem** o campo
  `gabarito` (Princípio 13). **Onde vive a fonte da verdade do catálogo** (cliente hardcoded vs.
  `quest_mundos`) é **⚠️ pendente** (Parte 16).
- Estado da Constelação é **por perfil**, nunca vaza entre contas (Princípio 4).

### 10. Arquitetura técnica
**Mundo dirigido por dados.** A identidade de cada planeta é dado, não código:
- `quest_mundos` (slug, nome, `tema` JSON = identidade visual/sonora, `icone`, `ordem`, `ativo`).
- `quest_jornadas` (`mundo_id`, `ano_escolar`, `bncc`).
- Contratos de leitura no Apêndice [B](apendice-B-api-dados.md); catálogo detalhado na Seção [06](06-pedagogico-bncc.md).

> ⚠️ **Divergência atual (cross-módulo):** hoje os 9 planetas estão **hardcoded** no cliente
> (`materias.ts`/`cenasTema.ts`) e o servidor (`quest_mundos`) **não é consumido**. A fonte da verdade
> do catálogo (cliente vs. servidor) é **decisão pendente** → ADR (Parte 16), com a Seção [11](11-arquitetura.md).

> ⚠️ **Renderização do mundo:** como os planetas/cenas são construídos (DOM/SVG-first vs. Three.js)
> **não está decidido** e impacta este capítulo — ver ADR de renderização na Seção [11](11-arquitetura.md).
> **Não decidir aqui.**

### 11. Dependências com outros módulos
- **Consome:** [02](02-vocabulario.md) (nomes), [06](06-pedagogico-bncc.md) (conteúdo que preenche os
  planetas), [11](11-arquitetura.md) (catálogo + renderização), [15](15-arte-audio-assets.md) (arte/áudio das cenas).
- **Alimenta / é contêiner de:** [04](04-personagens-avatar.md) (o avatar é o protagonista **dentro**
  do mundo), [05](05-sistemas-de-jogo.md) (a Constelação materializa a progressão), [07](07-ux-fluxos-navegacao.md)
  (as telas do universo), [17](17-telemetria-metricas.md) (evento **proposto** `planeta_aberto` — a
  definir no Apêndice [D](apendice-D-eventos-telemetria.md)), [19](19-liveops.md) (mundos sazonais).
- **Contrato crítico:** a decisão de **Avatar** (Seção [04](04-personagens-avatar.md)) define **quem** é
  o protagonista do universo (astronauta humanoide 3D vs. o próprio Cosmo). **Não improvisar aqui.**

### 12. Casos extremos (Edge Cases)
Intenção visual dos estados: sempre **acolhedora**, nunca "erro" ou bloqueio frio (detalhe de arte na Seção [15](15-arte-audio-assets.md)).
- **Escola não oferece a matéria:** planeta oculto / bloqueado / "em breve" → **⚠️ pendente** (Parte 15).
- **Turma multisseriada / ano indefinido:** afeta quais Jornadas do planeta abrem (regra em [06](06-pedagogico-bncc.md)).
- **Planeta sem conteúdo semeado ("em breve"):** metáfora de planeta **adormecido/em construção**, nunca erro.
- **Dia zero (constelação vazia):** o céu aparece **"por acender"**, convidando ao primeiro passo (Seção [08](08-onboarding-ftue.md)).
- **Offline:** planeta/jornada em cache é explorável; o que exige rede avisa com gentileza (Seção [07](07-ux-fluxos-navegacao.md)).
- **Planeta desativado (`ativo=false`) ou novo planeta adicionado:** o universo se recompõe sem quebrar navegação.

### 13. Escalabilidade futura
- **Novos planetas/matérias** entram como **dado de catálogo** (na fonte definida pelo ADR da Parte 16), idealmente sem deploy de código.
- **Mundos sazonais e eventos** (planetas temporários, céus de temporada) via live-ops (Seção [19](19-liveops.md)).
- **Integração com a plataforma de ensino futura do dono** (software próprio de matérias+questões):
  pode **alimentar o catálogo** de Jornadas/Missões de cada planeta — ver Seção [06](06-pedagogico-bncc.md).
- **Localização** (Seção [16](16-localizacao-i18n.md)): nomes próprios dos planetas **não** se traduzem;
  descrições e falas, sim.

### 14. Checklist de implementação
- [ ] Catálogo de planetas vem de **fonte única** definida por ADR (não hardcoded divergente).
- [ ] Cada planeta tem identidade completa (`tema`: cor, céu, partícula, ícone, som) + **nome narrado**.
- [ ] Reconhecível por **ícone + cor + som** sem depender de leitura.
- [ ] Estados **vazio ("em breve") / dia-zero / offline / desativado** cobertos com a intenção visual acolhedora (Parte 12).
- [ ] Vida ambiente respeita `prefers-reduced-motion`.
- [ ] Evento **proposto** `planeta_aberto` disparado (Apêndice [D](apendice-D-eventos-telemetria.md)).
- [ ] Constelação persistida por perfil, sem vazamento entre contas.
- [ ] DoD do capítulo conferido contra o Apêndice [F](apendice-F-checklists-dod.md).

### 15. Questões em aberto
**Escopo e regras (decisão do dono / cross-módulo):**
- ⚠️ **Escopo de conteúdo no lançamento:** 1 planeta profundo (Matemática) vs. vários — RELATORIO Seção 6; com [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md).
- ⚠️ **Planeta não-ofertado:** oculto, bloqueado ou "em breve"? → ADR próprio (Parte 16).
- ⚠️ **Regras de desbloqueio de planeta:** todos abertos desde o início, ou progressão?
- ⚠️ **Ed. Física (Movi) e ERER (Raízes):** confirmar entrada só na **Q5** e com **curadoria humana** (ERER), não IA.
- ⚠️ **Fonte da verdade do catálogo:** cliente (hardcoded) → servidor (`quest_mundos`)? → ADR (Parte 16), com [11](11-arquitetura.md).

**Ficção e forma do mundo (canon deste capítulo, a definir com o dono):**
- ⚠️ **Modelo espacial do universo:** mapa único navegável vs. seleção/trilho vs. órbita; como os 9
  planetas se dispõem; quantos visíveis por vez; há rotas/vizinhança entre eles; o que "céu tocável" faz.
- ⚠️ **Coreografia de transição** céu→planeta→Jornada→volta: existe um **"momento de viagem"** (o Cosmo/nave)?
  duração/ritmo; o céu morfa ou corta; a narração nomeia o planeta durante ou depois.
- ⚠️ **Canon da Constelação:** cada planeta desenha uma **figura-símbolo** própria? nº de estrelas por
  planeta (liga a [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)); a "Tela da Constelação" é o
  mesmo céu da tela-casa ou outra superfície?
- ⚠️ **Papel narrativo do Cosmo no universo** (distinto da decisão de avatar da Seção [04](04-personagens-avatar.md)):
  onde "mora", se conduz a viagem entre planetas, se reage por planeta.

**Direção de arte e áudio (entregável da Seção [15](15-arte-audio-assets.md)):**
- ⚠️ **Bíblia sensorial por planeta:** paleta/céu/nebulosa, motivo de partícula, motivos de primeiro
  plano, música/soundscape, colecionáveis e personagens secundários; marcar valores atuais de
  `materias.ts`/`cenasTema.ts` como **canon vs. scaffold**.

### 16. ADR (Architecture Decision Record)
Decisões que este capítulo **origina** (a registrar em `decisoes/` quando decididas):
- **ADR-candidato — Política de planeta não-ofertado** (impacto: tela-casa, gating; com [06](06-pedagogico-bncc.md)/[07](07-ux-fluxos-navegacao.md)).
- **ADR-candidato — Fonte da verdade do catálogo de mundos** (cross-módulo com [11](11-arquitetura.md)).

Decisões das quais este capítulo **depende** (donas em outros capítulos — **não improvisar aqui**):
- **Avatar do protagonista** → ADR na Seção [04](04-personagens-avatar.md).
- **Renderização do mundo (DOM/SVG vs. Three.js)** → ADR na Seção [11](11-arquitetura.md).
- **Bíblia de arte/áudio do mundo** → entregável da Seção [15](15-arte-audio-assets.md).

---

## 🇬🇧 The Universe & Fantasy

### 1. Objective
Define the **canonical fiction** of Constela Quest: the universe, the planets, the world hierarchy
(Universe → Planet → Journey → Mission → Challenge), the progress metaphor (the Constellation) and
Cosmo's role in the story. It is the *emotional container* every other chapter builds on. It solves
the problem of **turning "a school subject" into "a place the child chooses to visit"**.

### 2. Context
Constela Quest is the playful end of the **Constela ecosystem (Hub → Edu → Quest)**: Edu is the
administrative truth (schools, students, classes, grade, BNCC); Quest is the world where that data
becomes a game. The universe is what gives it all meaning — without it, it's just a **digital workbook**.
The canonical visual identity starts from the **`constela-play-v7.html`** prototype (Principle 16 / Section [01](01-principios-imutaveis.md)).

**Current state (Q0):** the 9 planets already exist **visually** (themed scenes, particles, living
constellations, in `materias.ts`/`cenasTema.ts`) but **without gameplay** — "Play now" is still just an
on-screen notice (*toast*). ⚠️ **Note:** those assets are **scaffold** — which is canonical art direction
to keep vs. scaffold to redo is a deliverable of Section [15](15-arte-audio-assets.md) (see Part 15).

### 3. Feature philosophy
**Why a universe?** Space is the ultimate metaphor for **curiosity and exploration**, and gives a
literal image of **progress**: stars that light up into constellations. A child doesn't "do Math"; she
**travels to Planet Numéria**. That reframing (subject → place) is the heart of the product.

Ties to the 4 pillars (Section [00](00-visao-e-norte.md)): **Autonomy** (choose your planet);
**Visible progress** (the Constellation); **Bond** (Cosmo and each planet's identity); **Surprise**
(each planet a new world). **Anti-goal:** the universe must **never** become a "menu of subjects" —
it's a living cosmos, not a list.

### 4. The experience the player should feel
- **Wonder and ownership:** "this is **my** universe" — the sky remembers me (the Constellation grows each return).
- **Curiosity:** "what's on that planet?" — the world invites exploration.
- **Belonging:** Cosmo waiting, the planet recognizing the return — **never a cold screen**.
- **Gentle vastness:** big and full of possibility, never scary or confusing for a 6-year-old.

### 5. Complete flow
World-level (mission gameplay lives in Section [05](05-sistemas-de-jogo.md)): Boot → home sky (return
hub) → tap a subject-planet (the themed scene takes over: background, color, particles, soundtrack shift
to that world's identity) → enter a Journey (grade/BNCC tracks) → Missions → always a path back;
progress stays visible in the Constellation. First time: the universe reveals itself gradually (tied to
the ceremony and onboarding, Section [08](08-onboarding-ftue.md)). Return: the sky "remembers" — the
Constellation and Cosmo's Flame show continuity.
> The **choreography** of these passages (sky→planet→Journey→back) is canon of this chapter but still **open** — see Part 15.

### 6. Interface (when it exists)
Universe surfaces (screen specs in Section [07](07-ux-fluxos-navegacao.md); art in Section [15](15-arte-audio-assets.md)):
home-sky (living, **tappable** constellations); planet selection (the 9 worlds — the **spatial model**,
single navigable map vs. rail vs. orbit, is open, Part 15); planet scene (layered: planet + living
constellations + particles + themed foreground, per subject); Constellation screen (personal progress,
me × me, never a ranking — *whether it is the same surface as the home sky or a separate screen is open, Part 15*).
> ⚠️ The child-facing label for the home screen is **open** ("lobby" is forbidden) — decided in Section [02](02-vocabulario.md).

### 7. UX
Navigable without reading: each planet is recognizable by **icon + color + sound** (accessibility,
Section [13](13-acessibilidade.md)); pt-BR narration **names** the planet on entry. Alive: ambient
particles and self-drawing constellations. Canonical vocabulary (Section [02](02-vocabulario.md)):
always "Planet / Journey / Mission / Constellation", never "subject/menu". Reduced-motion: all ambient
life degrades gracefully.

### 8. Game Design
World structure: `Universe → Planet (subject) → Journey (grade/BNCC) → Mission → Challenge`.

**The Constellation (progress metaphor):** mastery in a Mission yields **stars (0–3)**; **completing a
Journey** lights a **new star in the child's personal sky**, and stars gradually form **constellations**
— the drawing of her progress. It's **me × me**, never comparison (Principle 5, Section [01](01-principios-imutaveis.md)).
*The canonical star/XP/economy rule lives in Section [05](05-sistemas-de-jogo.md); here only the
**fantasy**, not the formula.*

**Scope — fiction vs. content:** the **universe has 9 planets** (canonical fiction, confirmed in
`materias.ts`). **How many planets get playable content at launch** is the owner's content decision (the
roadmap suggests 1 deep planet — Math/Q1 — and the rest in Q2/Q5) → **⚠️ pending** (Part 15), with
Sections [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md).

**Exploration, not obligation:** the world is curiosity-driven and **a mistake never closes a path**
(Principle 6). *Whether there's unlock progression between planets or all stay open is pending (Part 15).*
**Expansion:** seasonal worlds and events via live-ops (Section [19](19-liveops.md)).

### 9. Business rules
**The 9 canonical planets** (subject → fiction name; proper names are not translated):

| Subject (internal) | Planet (child) | Identity (hint) |
|--------------------|----------------|-----------------|
| Math | **Numéria** | numbers, logic, geometry |
| Portuguese | **Palavras** | reading, writing, language |
| Science | **Biozênia** | life, nature, experiments |
| Geography | **Terra Nova** | maps, places, planet Earth |
| History | **Chronos** | time, memory, civilizations |
| English | **Oxford** | second language |
| Arts | **Colorium** | color, creation, expression |
| Phys. Ed. | **Movi** | body, movement *(⚠️ Q5, see Part 15)* |
| ERER | **Raízes** | Ethnic-Racial Relations Education *(⚠️ Q5, human curation)* |

A planet **exists for the child** if the school/curriculum offers that subject. **⚠️ What happens when
it doesn't** (planet hidden, locked, or "coming soon") is a **pending decision** (Part 15). Journeys are
unlocked by the enrollment **grade** (`turmas.ano_escolar`); gating/BNCC logic lives in Section [06](06-pedagogico-bncc.md).
**Immutable:** the **server is the answer-key authority** — the catalog reaches the client **without**
the `gabarito` field (Principle 13). **Where the catalog's source of truth lives** (hardcoded client vs.
`quest_mundos`) is **⚠️ pending** (Part 16). Constellation state is **per profile**, never leaking
between accounts (Principle 4).

### 10. Technical architecture
**Data-driven world.** Each planet's identity is data, not code: `quest_mundos` (slug, name, `tema`
JSON = visual/sound identity, `icone`, `ordem`, `ativo`); `quest_jornadas` (`mundo_id`, `ano_escolar`,
`bncc`). Read contracts in Appendix [B](apendice-B-api-dados.md); detailed catalog in Section [06](06-pedagogico-bncc.md).
> ⚠️ **Current divergence (cross-module):** the 9 planets are **hardcoded** on the client today
> (`materias.ts`/`cenasTema.ts`) and the server (`quest_mundos`) **isn't consumed**. The catalog's
> source of truth (client vs. server) is a **pending decision** → ADR (Part 16), with Section [11](11-arquitetura.md).
> ⚠️ **World rendering:** how planets/scenes are built (DOM/SVG-first vs. Three.js) **is not decided**
> and impacts this chapter — see the rendering ADR in Section [11](11-arquitetura.md). **Do not decide here.**

### 11. Dependencies on other modules
Consumes: [02](02-vocabulario.md) (names), [06](06-pedagogico-bncc.md) (content that fills planets),
[11](11-arquitetura.md) (catalog + rendering), [15](15-arte-audio-assets.md) (scene art/audio). Feeds /
is a container for: [04](04-personagens-avatar.md) (the avatar is the protagonist **inside** the world),
[05](05-sistemas-de-jogo.md) (the Constellation materializes progression), [07](07-ux-fluxos-navegacao.md)
(universe screens), [17](17-telemetria-metricas.md) (**proposed** `planeta_aberto` event — to define in
Appendix [D](apendice-D-eventos-telemetria.md)), [19](19-liveops.md) (seasonal worlds). **Critical
contract:** the **Avatar** decision (Section [04](04-personagens-avatar.md)) defines **who** the
protagonist of the universe is (3D humanoid astronaut vs. Cosmo itself). **Do not improvise here.**

### 12. Edge cases
Visual intent of every state: always **warm**, never "error" or a cold lock (art detail in Section [15](15-arte-audio-assets.md)).
School doesn't offer the subject → planet hidden/locked/"coming soon" → **⚠️ pending** (Part 15);
multi-grade class / undefined grade → affects which Journeys open (rule in [06](06-pedagogico-bncc.md));
planet with no seeded content ("coming soon") → a **sleeping/under-construction** planet, never an error;
day zero (empty Constellation) → the sky appears **"unlit"**, inviting the first step (Section [08](08-onboarding-ftue.md));
offline → cached planet/journey is explorable, network-only warns gently; deactivated planet
(`ativo=false`) or newly added planet → the universe recomposes without breaking navigation.

### 13. Future scalability
New planets/subjects enter as **catalog data** (in the source defined by the Part 16 ADR), ideally with
no code deploy; seasonal worlds and events via live-ops (Section [19](19-liveops.md)); integration with
the owner's **future teaching platform** (own subjects+questions software) can **feed the catalog** of
each planet's Journeys/Missions (see Section [06](06-pedagogico-bncc.md)); localization (Section [16](16-localizacao-i18n.md)):
planet proper names are **not** translated; descriptions and lines are.

### 14. Implementation checklist
- [ ] Planet catalog comes from a **single source** defined by ADR (no divergent hardcoding).
- [ ] Each planet has full identity (`tema`: color, sky, particle, icon, sound) + **narrated name**.
- [ ] Recognizable by **icon + color + sound** without relying on reading.
- [ ] **Empty ("coming soon") / day-zero / offline / deactivated** states covered with the warm visual intent (Part 12).
- [ ] Ambient life respects `prefers-reduced-motion`.
- [ ] **Proposed** `planeta_aberto` telemetry event fired (Appendix [D](apendice-D-eventos-telemetria.md)).
- [ ] Constellation persisted per profile, no leakage between accounts.
- [ ] Chapter DoD checked against Appendix [F](apendice-F-checklists-dod.md).

### 15. Open questions
**Scope & rules (owner / cross-module decision):**
- ⚠️ **Launch content scope:** 1 deep planet (Math) vs. several — RELATORIO Section 6; with [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md).
- ⚠️ **Non-offered planet:** hidden, locked or "coming soon"? → own ADR (Part 16).
- ⚠️ **Planet unlock rules:** all open from the start, or gated progression?
- ⚠️ **Phys. Ed. (Movi) & ERER (Raízes):** confirm entry only in **Q5** and with **human curation** (ERER), not AI.
- ⚠️ **Catalog source of truth:** client (hardcoded) → server (`quest_mundos`)? → ADR (Part 16), with [11](11-arquitetura.md).

**World fiction & form (this chapter's canon, to define with the owner):**
- ⚠️ **Spatial model of the universe:** single navigable map vs. selection/rail vs. orbit; how the 9
  planets are arranged; how many visible at once; routes/adjacency between them; what "tappable sky" does.
- ⚠️ **Transition choreography** sky→planet→Journey→back: is there a **"travel moment"** (Cosmo/ship)?
  duration/rhythm; does the sky morph or cut; does narration name the planet during or after.
- ⚠️ **Constellation canon:** does each planet draw its own **symbol figure**? number of stars per planet
  (ties to [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)); is the "Constellation screen" the
  same sky as the home screen or a separate one?
- ⚠️ **Cosmo's narrative role in the universe** (distinct from the avatar decision in Section [04](04-personagens-avatar.md)):
  where it "lives", whether it drives the travel between planets, whether it reacts per planet.

**Art & audio direction (deliverable of Section [15](15-arte-audio-assets.md)):**
- ⚠️ **Per-planet sensory bible:** palette/sky/nebula, particle motif, foreground motifs, music/soundscape,
  collectibles and secondary characters; mark current `materias.ts`/`cenasTema.ts` values as **canon vs. scaffold**.

### 16. ADR (Architecture Decision Record)
Decisions this chapter **spawns** (to record in `decisoes/` once decided): **Non-offered planet policy**
(impacts home screen, gating; with [06](06-pedagogico-bncc.md)/[07](07-ux-fluxos-navegacao.md)); **World
catalog source of truth** (cross-module with [11](11-arquitetura.md)). Decisions this chapter **depends
on** (owned elsewhere — **do not improvise here**): **Protagonist avatar** → ADR in Section [04](04-personagens-avatar.md);
**World rendering (DOM/SVG vs. Three.js)** → ADR in Section [11](11-arquitetura.md); **World art/audio
bible** → deliverable of Section [15](15-arte-audio-assets.md).
