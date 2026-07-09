# 02 — Vocabulário Canônico / Canonical Vocabulary

- **Status:** 🔴 rascunho / draft
- **Fontes / Sources:** `docs/quest/README.md`, `docs/quest/03-gamificacao-progressao.md`, `docs/quest/05-roadmap.md`, `_estado-atual/RELATORIO-2026-07-09.md`

---

## 🇧🇷 Vocabulário Canônico

A criança e o sistema falam línguas diferentes. Há um **nome interno** (código, banco, docs) e um
**nome que a criança vê e ouve**. Esta tabela é obrigatória em UI, falas do Cosmo e qualquer texto
voltado à criança. Mudar um termo exige ADR.

### Mapa interno → criança
| Interno (código/banco) | Criança (UI/áudio) | Observação |
|------------------------|--------------------|------------|
| `mundo` / disciplina | **Planeta** | cada matéria é um planeta do universo |
| `jornada` | **Jornada** | trilha dentro de um planeta |
| `missao` | **Missão** | unidade jogável |
| `desafio` | **Desafio** | uma questão/interação dentro da missão |
| `missao` (tipo `chefao`) | **Chefão** | Missão final e especial de uma Jornada (regras na [Seção 05](05-sistemas-de-jogo.md)) |
| `progresso` | **Constelação** | o progresso vira estrelas que formam constelações |
| `sequencia_dias` (streak) | **Chama do Cosmo** | dias jogando; fantasia na [Seção 03](03-universo.md), regras na [Seção 05](05-sistemas-de-jogo.md) |
| `sala` | **Estudar com um amigo** / **Corrida** | o objeto `sala` em si nunca é nomeado; a criança só vê esses botões |
| `tentativa` | *(invisível)* | nunca aparece para a criança |
| `perfil` | **Meu astronauta** | guarda-chuva conceitual; hoje aparece nas telas **Vestiário** e **Carreira** (o rótulo "Meu astronauta" ainda é a confirmar) |
| `codigo_amigo` | **Código de amigo** | para adicionar colegas **da escola**; o alcance de lançamento (turma ou escola) está em aberto — ver [Seção 09](09-social.md) |
| tela-casa (`lobby` no código) | *(a definir)* | ⚠️ "lobby" é palavra **proibida** na UI — só existe no código; falta o rótulo infantil da tela-casa (proposta na [Seção 03](03-universo.md)) |
| abas | **Jogar** · **Vestiário** · **Carreira** | rótulos infantis já em produção no topo da tela-casa |
| mascote | **Cosmo** | o astronauta companheiro que fala e dá dicas |

> Termos de **economia e progressão** (XP, moedas, estrelas, conquistas, pets) têm rótulos
> lúdicos próprios, detalhados na [Seção 03](03-universo.md) e [Seção 05](05-sistemas-de-jogo.md).

### Palavras PROIBIDAS na UI infantil
Nunca usar (soam a escola/competição/tecnologia adulta): **party, lobby, matchmaking, squad,
ranking global, prova, exercício, tarefa, erro fatal, reprovado.**
- Em vez de *prova/exercício/tarefa* → **Missão** / **Desafio**.
- Em vez de *ranking global* → **sua Constelação** / **turma da semana**.
- Em vez de *reprovado/erro* → "quase!", "vamos tentar de novo?", "vamos juntos".

### Nomes próprios do universo
- **Constela** — a marca/ecossistema.
- **Constela Quest** — o jogo dos alunos.
- **Cosmo** — o mascote-companheiro (astronauta). **Hoje** é o guia que fala e dá dicas, não o
  avatar do jogador; o papel definitivo do avatar está **em aberto** (ver [Seção 04](04-personagens-avatar.md)).
- **Constelação** — a metáfora central de progresso.
- Os planetas têm nome próprio lúdico por matéria (ex.: **Numéria, Palavras, Biozênia**…) — o
  catálogo vive na [Seção 03](03-universo.md). Nomes próprios não se traduzem.

### Tom de voz (como o Cosmo e a UI falam)
- **Curto e falado.** Frases que uma criança de 6 anos entende de ouvido.
- **Caloroso, nunca professoral.** Celebra o esforço, não só o acerto.
- **Sem jargão** técnico ou escolar. Sem ironia, sem sarcasmo.
- **Convite, não ordem.** "Vamos?" no lugar de "Faça".
- **O erro é acolhido**, nunca marcado como falha (ver [Princípio 6](01-principios-imutaveis.md)).

### Falas do Cosmo — guia de voz (✓/✗)
Referência única para UI, narração gravada e a futura IA "Cosmo explica erros" (Q6). As falas reais
são sempre em **pt-BR**.

| Momento | ✓ Assim | ✗ Nunca |
|---------|---------|---------|
| Boas-vindas (1ª vez) | "Oi! Eu sou o Cosmo. Vamos explorar juntos?" | "Bem-vindo ao sistema. Faça seu cadastro." |
| Retorno no mesmo dia | "Você voltou! Bora continuar?" | "Sessão reiniciada." |
| Retorno após dias fora | "Que saudade! Sua constelação estava te esperando." | "Você ficou 5 dias sem cumprir suas tarefas." |
| Início de missão | "Essa é no Planeta Numéria. Vamos?" | "Inicie o exercício de matemática." |
| Acerto | "Isso! Você mandou bem!" | "Correto." |
| Acerto de primeira | "Uau, de primeira! Você tá voando!" | "100% de acerto registrado." |
| Erro | "Quase! Vamos tentar de novo juntos?" | "Errado. Resposta incorreta." |
| Erro repetido | "Tá difícil essa, né? Bora com uma dica." | "Você errou de novo." |
| Dica | "Psiu… olha as estrelas ali. Ajuda?" | "Dica: aplique a fórmula." |
| Subir de nível | "Você subiu de nível! Olha só o que abriu!" | "Nível incrementado." |
| Ganhar estrela | "Mais uma estrela pra sua constelação! ✨" | "Você recebeu 1 estrela." |
| Despedida | "Até amanhã? Vou cuidar da sua nave!" | "Logout efetuado." |

---

## 🇬🇧 Canonical Vocabulary

The child and the system speak different languages. There's an **internal name** (code, database,
docs) and the **name the child sees and hears**. This table is mandatory in UI, Cosmo's lines and
any child-facing text. Changing a term requires an ADR.

### Internal → child map
| Internal (code/db) | Child (UI/audio) | Note |
|--------------------|------------------|------|
| `mundo` / subject | **Planet** | each subject is a planet in the universe |
| `jornada` | **Journey** | a track within a planet |
| `missao` | **Mission** | a playable unit |
| `desafio` | **Challenge** | a question/interaction inside a mission |
| `missao` (type `chefao`) | **Boss** | a Journey's final, special Mission (rules in [Section 05](05-sistemas-de-jogo.md)) |
| `progresso` | **Constellation** | progress becomes stars forming constellations |
| `sequencia_dias` (streak) | **Cosmo's Flame** | days playing; fantasy in [Section 03](03-universo.md), rules in [Section 05](05-sistemas-de-jogo.md) |
| `sala` | **Study with a friend** / **Race** | the `sala` object is never named; the child only sees these buttons |
| `tentativa` | *(invisible)* | never shown to the child |
| `perfil` | **My astronaut** | conceptual umbrella; today it appears as the **Vestiário** and **Carreira** screens (the "My astronaut" label is still to confirm) |
| `codigo_amigo` | **Friend code** | to add classmates **from the school**; the launch scope (class or school) is open — see [Section 09](09-social.md) |
| home screen (`lobby` in code) | *(to define)* | ⚠️ "lobby" is a **forbidden** UI word — code-only; the child-facing label for the home screen is missing (proposal in [Section 03](03-universo.md)) |
| tabs | **Play** · **Wardrobe** · **Career** | child labels already in production atop the home screen |
| mascot | **Cosmo** | the companion astronaut who speaks and gives hints |

> **Economy and progression** terms (XP, coins, stars, achievements, pets) have their own playful
> labels, detailed in [Section 03](03-universo.md) and [Section 05](05-sistemas-de-jogo.md).

### FORBIDDEN words in the child UI
Never use (they sound like school/competition/adult tech): **party, lobby, matchmaking, squad,
global ranking, test, exercise, task, fatal error, failed.**
- Instead of *test/exercise/task* → **Mission** / **Challenge**.
- Instead of *global ranking* → **your Constellation** / **this week's class**.
- Instead of *failed/error* → "almost!", "shall we try again?", "let's do it together".

### Proper names of the universe
- **Constela** — the brand/ecosystem.
- **Constela Quest** — the students' game.
- **Cosmo** — the companion mascot (astronaut). **Today** it is the guide that speaks and hints,
  not the player avatar; the avatar's final role is **open** (see [Section 04](04-personagens-avatar.md)).
- **Constellation** — the central progress metaphor.
- Planets have playful proper names per subject (e.g. **Numéria, Palavras, Biozênia**…) — the
  catalog lives in [Section 03](03-universo.md). Proper names are not translated.

### Tone of voice (how Cosmo and the UI speak)
- **Short and spoken.** Sentences a 6-year-old understands by ear.
- **Warm, never teacherly.** Celebrates effort, not just correctness.
- **No jargon**, technical or scholastic. No irony, no sarcasm.
- **Invitation, not command.** "Shall we?" instead of "Do this".
- **Mistakes are welcomed**, never marked as failure (see [Principle 6](01-principios-imutaveis.md)).

### Cosmo's lines — voice guide (✓/✗)
Single reference for UI, recorded narration and the future "Cosmo explains mistakes" AI (Q6). The
actual lines are always in **pt-BR** (English shown for the international team).

| Moment | ✓ Like this | ✗ Never |
|--------|-------------|---------|
| Welcome (1st time) | "Hi! I'm Cosmo. Shall we explore together?" | "Welcome to the system. Register now." |
| Return same day | "You're back! Shall we keep going?" | "Session restarted." |
| Return after days away | "I missed you! Your constellation was waiting." | "You went 5 days without completing your tasks." |
| Mission start | "This one's on Planet Numéria. Ready?" | "Start the math exercise." |
| Correct | "Yes! You nailed it!" | "Correct." |
| Correct first try | "Wow, first try! You're flying!" | "100% accuracy recorded." |
| Mistake | "Almost! Shall we try again together?" | "Wrong. Incorrect answer." |
| Repeated mistake | "This one's tricky, huh? Let's take a hint." | "You got it wrong again." |
| Hint | "Psst… look at those stars. Does it help?" | "Hint: apply the formula." |
| Level up | "You leveled up! Look what opened!" | "Level incremented." |
| Earn a star | "Another star for your constellation! ✨" | "You received 1 star." |
| Goodbye | "See you tomorrow? I'll look after your ship!" | "Logout complete." |
