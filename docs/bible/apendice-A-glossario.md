# Apêndice A — Glossário / Glossary

- **Status:** 🟢 aprovado / approved
- **Tipo:** documento de **referência** (não segue o padrão de 16 partes do [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md), que vale só para capítulos).
- **Fontes / Sources:** [02](02-vocabulario.md) (dona do vocabulário infantil), [03](03-universo.md) (universo/planetas), [05](05-sistemas-de-jogo.md) (economia/progressão), [06](06-pedagogico-bncc.md) (pedagógico), [10](10-professor-familia.md) (papéis), [11](11-arquitetura.md) (arquitetura), [12](12-seguranca-privacidade.md) (segurança/RBAC), [22](22-monetizacao.md) (negócio), [17](17-telemetria-metricas.md) (sinais de produto). Governança em [24](24-governanca.md) e [`decisoes/`](decisoes/) (Apêndice C).
- **Depende de:** todas as seções acima como **fonte-dona**. O glossário **não** é foro de decisão.

---

## 🇧🇷 Glossário

### A.1 Como usar o glossário

Este apêndice é uma **referência alfabética consolidada** de todo termo do projeto — o vocabulário
interno (código/banco), o nome que a criança vê, os termos técnicos, pedagógicos, de negócio e os
papéis de usuário. Cada verbete traz uma **definição curta**, o **par interno↔criança** (quando
houver) e um **ponteiro para a seção-dona**.

**Fronteira-mãe:** o glossário **reúne e remete; não redefine**. Para todo verbete, a **autoridade
é a seção-dona** — o texto normativo (regras, números, contratos) vive lá. Aqui há apenas a
definição curta e o ponteiro. Em caso de conflito, **a seção-dona vence** (norma [G10](24-governanca.md)).

A **[Seção 02 — Vocabulário Canônico](02-vocabulario.md)** é a dona do vocabulário infantil (mapa
interno→criança, palavras proibidas, nomes próprios, rótulos em aberto). Este glossário **consolida
e aponta** para ela; **mudar um termo canônico exige ADR** (A.14).

### A.2 Estrutura de cada verbete

Toda tabela de verbete usa os mesmos campos fixos:

| Campo | O que é |
|-------|---------|
| **Termo** | a palavra ou expressão (interna ou canônica) |
| **Categoria** | produto/game · lúdico · técnico · pedagógico · negócio · papel · sigla |
| **Definição curta** | uma frase; o texto normativo mora na seção-dona |
| **Par interno↔criança** | o nome que a criança vê/ouve, quando o termo tiver rótulo infantil |
| **Seção-dona** | onde vive a regra completa (autoridade) |
| **Status** | 🟢 fixado · ⚠️ em aberto (pende do dono / de decisão registrada) |

### A.3 Convenções de escrita

- **Ordenação:** dentro de cada categoria, ordem alfabética pela coluna **Termo**.
- **Negrito:** o **nome que a criança vê** aparece em **negrito**; o nome interno em `código`.
- **Remissivas:** "→ ver também" liga verbetes relacionados.
- **Termos proibidos:** marcados com 🚫 e listados por inteiro em A.10 (remete à Seção 02).
- **Nomes próprios** (Cosmo, planetas) **não se traduzem** — idênticos em pt-BR e no espelho EN.

### A.4 Glossário de produto e game design (economia e progressão)

> Rótulos e definições curtas; **regras e números** (fórmulas de XP, faucet de Moedas, teto diário,
> limiares) são da **[Seção 05](05-sistemas-de-jogo.md)** e a fantasia da **[Seção 03](03-universo.md)**.
> O glossário **não fixa número**.

| Termo | Definição curta | Par interno↔criança | Seção-dona | Status |
|-------|-----------------|--------------------|:----------:|:------:|
| **XP** | moeda de **progresso**; só cresce, move o nível, nunca é gasto nem perdido | `xp` → *(exibido como XP)* | 05 | 🟢 |
| **Estrela** | **maestria por Missão (0–3)**; vale a melhor tentativa, nunca se perde; é a chave do Chefão | `estrelas` → **Estrela** | 05 | 🟢 |
| **Moeda** | ganha jogando, **gasta só em cosméticos**; muda só via ledger imutável; **sem dinheiro real** | `moedas` → **Moeda** | 05 · 22 | 🟢 |
| **Nível** | patamar de progressão que o XP faz subir; subir credita Moedas + item | `nivel` → **Nível** | 05 | 🟢 |
| **Chama do Cosmo** | **sequência** de dias jogando (streak), mostrada como continuidade, não como pressão | `sequencia_dias` → **Chama do Cosmo** | 03 · 05 | 🟢 |
| **Constelação** | metáfora central de progresso; estrelas que se acendem e formam figuras (eu × eu, nunca ranking) | `progresso` → **Constelação** | 03 · 05 | 🟢 |
| **Chefão** | Missão final e especial de uma Jornada; liberado quando as Estrelas da Jornada atingem o limiar | `missao` tipo `chefao` → **Chefão** | 05 | 🟢 |
| **Colecionável** | recompensa de identidade do planeta, concedida ao concluir uma Jornada | — → **Colecionável** | 03 · 05 | 🟢 |
| **Conquista** | marco comemorado no histórico do jogador (Carreira) | — → **Conquista** | 05 | 🟢 |
| **Missão diária** | as Missões do dia (mais as semanais) que dão ritmo de retorno — quantidade e faucet na Seção 05 | `missao` (diária) → **Missão** | 05 | 🟢 |
| **Teto diário** | limite diário de XP; ao atingir é **celebrado**, não bloqueia jogar; zera na virada do dia | — → *(celebração)* | 05 | 🟢 |
| **Passe / Temporada** | trilha de progressão de temporada; **única e gratuita** (sem passe pago) | — → **Passe** | 22 · 19 | 🟢 |
| **Presente de login** | recompensa diária de login ao entrar (trilha; duração na Seção 05) | — → **Presente** | 05 | 🟢 |

### A.5 Vocabulário lúdico (interno → criança)

> Remissão consolidada ao **mapa canônico da [Seção 02](02-vocabulario.md)** — sem duplicar a fonte.
> Este bloco é um índice; a tabela completa (com observações) vive na 02.

| Interno (código/banco) | Criança (UI/áudio) | Seção-dona | Status |
|------------------------|--------------------|:----------:|:------:|
| `mundo` / disciplina | **Planeta** | 02 · 03 | 🟢 |
| `jornada` | **Jornada** | 02 | 🟢 |
| `missao` | **Missão** | 02 | 🟢 |
| `desafio` | **Desafio** | 02 | 🟢 |
| `missao` (tipo `chefao`) | **Chefão** | 02 · 05 | 🟢 |
| `progresso` | **Constelação** | 02 · 03 | 🟢 |
| `sequencia_dias` | **Chama do Cosmo** | 02 · 05 | 🟢 |
| `sala` | **Estudar com um amigo** / **Corrida** | 02 · 09 | 🟢 |
| `tentativa` | *(invisível — nunca aparece)* | 02 | 🟢 |
| `perfil` | **Meu astronauta** *(rótulo a confirmar — A.13)* | 02 | ⚠️ |
| `codigo_amigo` | **Código de amigo** | 02 · 09 | 🟢 |
| tela-casa (`lobby` no código) | *(rótulo infantil a definir — A.13)* | 02.4 | ⚠️ |
| abas | **Jogar** · **Vestiário** · **Carreira** | 02 | 🟢 |
| mascote | **Cosmo** | 02 | 🟢 |

### A.6 Glossário técnico e de arquitetura

> Dona = **[Seção 11](11-arquitetura.md)** (arquitetura); segurança/identidade = **[Seção 12](12-seguranca-privacidade.md)**.

| Termo | Definição curta | Seção-dona | Status |
|-------|-----------------|:----------:|:------:|
| **Monólito modular** | um único serviço backend (FastAPI) com módulos internos (Edu + `quest`), não microsserviços | 11 | 🟢 |
| **Outbox** | tabela de eventos append-only que desacopla a escrita transacional da publicação (notificações/telemetria) | 11 · 17 | 🟢 |
| **Ledger imutável** | registro append-only de toda mudança de moeda; o saldo é recomputável; erro nunca subtrai (Princípio 14) | 05 · 11 | 🟢 |
| **PWA** | Progressive Web App: o Quest instala/roda no navegador com shell offline | 11 · 07 | 🟢 |
| **WebSocket** | canal em tempo real (ex.: presença, corrida); superfície aspiracional Q1+ | 11 | ⚠️ |
| **Mecânica-plugin / registry** | contrato `MecanicaProps` + registro que permite adicionar tipos de Desafio sem tocar no core | 05 · 11 | 🟢 |
| **R3F / Three.js** | React-Three-Fiber sobre Three.js: renderização 3D do personagem e cenas | 11 · 15 | 🟢 |
| **CDN** | rede de distribuição de assets (GLB/áudio/sprites) para carga rápida | 11 · 15 | 🟢 |
| **`escola_id`** | chave de isolamento multi-tenant; toda linha e consulta é filtrada por escola (Princípio 15) | 11 · 12 | 🟢 |
| **JWT papel `aluno`** | token do login infantil; claims reais `sub`/`papel`/`ver`/`iat`/`exp`; distinto do token do Edu | 12 | 🟢 |
| **ETag / versão** | validador de cache do catálogo; o cliente revalida sem rebaixar conteúdo | 11 | 🟢 |

### A.7 Glossário pedagógico

> Dona = **[Seção 06](06-pedagogico-bncc.md)**; a mecânica do Chefão é da [Seção 05](05-sistemas-de-jogo.md).

| Termo | Definição curta | Seção-dona | Status |
|-------|-----------------|:----------:|:------:|
| **BNCC** | Base Nacional Comum Curricular; toda Missão referencia um código de habilidade | 06 | 🟢 |
| **Código de habilidade** | identificador BNCC (ex.: `EF01MA01`) que amarra o conteúdo ao currículo | 06 | 🟢 |
| **Domínio (0–100)** | medida de maestria do aluno numa habilidade; alimenta a dificuldade adaptativa | 06 | 🟢 |
| **Dificuldade adaptativa** | ajuste do desafio ao domínio da criança (nunca punitivo) | 06 · 05 | 🟢 |
| **Ano escolar** | 1º–5º ano; recorta as Jornadas por faixa BNCC | 06 | 🟢 |
| **Revisão espaçada** | reapresentação planejada de conteúdo para fixação | 06 | 🟢 |

### A.8 Glossário de negócio

> Dona = **[Seção 22](22-monetizacao.md)** (que aponta "glossário de negócio → A.8"); A.8 **deriva**
> das definições da 22, não as reescreve. Sinais de produto (base de LTV/churn/ativação) = [Seção 17](17-telemetria-metricas.md).

| Termo | Definição curta | Seção-dona | Status |
|-------|-----------------|:----------:|:------:|
| **Licença** | direito de uso contratado por uma escola/rede; nunca vendido à criança | 22 | 🟢 |
| **Escola / Rede** | tenant (uma escola) ou grupo de escolas sob uma mantenedora | 22 · 11 | 🟢 |
| **Mantenedora** | entidade que administra uma ou mais escolas (compra/renova) | 22 | 🟢 |
| **Comprador × jogador** | o **adulto** (escola/rede) compra; a **criança** joga — nunca é compradora (Princípio 7) | 22 | 🟢 |
| **B2B / B2G** | venda para escolas privadas (B2B) e para o poder público (B2G) | 22 | 🟢 |
| **Piloto / Trial** | período inicial de avaliação numa escola antes da licença | 22 | 🟢 |
| **Ativação** | escola/turma efetivamente usando o produto (não só contratada) | 22 · 17 | 🟢 |
| **LTV** | valor de uma escola ao longo da relação (métrica de negócio) | 22 · 17 | 🟢 |
| **Churn de escola** | escola que deixa de renovar a licença | 22 · 17 | 🟢 |

### A.9 Glossário de papéis de usuário

> Donas = **[Seção 10](10-professor-familia.md)** (professor/família e vínculo) + **[Seção 12](12-seguranca-privacidade.md)** (como autentica / o que acessa, RBAC).

| Papel | Como autentica | O que acessa (resumo) | Seção-dona | Status |
|-------|----------------|-----------------------|:----------:|:------:|
| **Aluno** | login código-só (sem senha), JWT papel `aluno` | só o próprio Quest; nunca vê ranking individual nem Moedas de outros | 12 · 05 | 🟢 |
| **Responsável** | vínculo autorizado ao aluno (Portal da Família, fase Q3) | acompanhamento do próprio filho; sem Moedas/loja | 10 | ⚠️ |
| **Professor** | conta Edu (papel professor) | turma e progresso pedagógico; **não** vê Moedas/loja | 10 | 🟢 |
| **Coordenador / Admin de escola** | conta Edu (papel admin da escola) | gestão da escola, turmas e importação, dentro do `escola_id` | 10 · 12 | 🟢 |
| **Admin global** | conta Edu (papel admin global) | operação multi-escola, auditável | 12 | 🟢 |

### A.10 Termos PROIBIDOS na UI infantil 🚫

> Lista consolidada; **fonte e substitutos oficiais** na **[Seção 02](02-vocabulario.md)**. Soam a
> escola/competição/tecnologia adulta.

| 🚫 Proibido | Por quê | Substituto |
|------------|---------|------------|
| party | jargão de jogo adulto | **Estudar com um amigo** |
| lobby | jargão técnico | *(rótulo infantil da tela-casa — A.13)* |
| matchmaking | jargão técnico/competitivo | *(sem pareamento competitivo exposto)* |
| squad | jargão competitivo | **turma** / **amigos da escola** |
| ranking global | competição/exposição | **sua Constelação** / **turma da semana** |
| prova | escola/avaliação | **Missão** / **Desafio** |
| exercício | escola | **Missão** / **Desafio** |
| tarefa | escola/obrigação | **Missão** / **Desafio** |
| erro fatal | tecnologia/medo | "quase!" / "vamos tentar de novo?" |
| reprovado | escola/punição | "vamos juntos" / "quase!" |

### A.11 Siglas e abreviações

| Sigla | Expansão | Seção |
|-------|----------|:-----:|
| **BNCC** | Base Nacional Comum Curricular | 06 |
| **LGPD** | Lei Geral de Proteção de Dados | 12 |
| **ADR** | Architecture/Decision Record (registro de decisão) | 24 · C |
| **GDD** | Game Design Document | 05 |
| **PWA** | Progressive Web App | 11 |
| **TTS** | Text-to-Speech (narração sintetizada) | 13 · 15 |
| **R3F** | React-Three-Fiber | 11 · 15 |
| **CDN** | Content Delivery Network | 11 |
| **RACI** | Responsible/Accountable/Consulted/Informed (matriz de responsabilidade) | 21 |
| **COGS** | Cost of Goods Sold (custo do serviço prestado) | 22 |
| **LTV** | Lifetime Value | 22 · 17 |
| **RBAC** | Role-Based Access Control (controle de acesso por papel) | 12 |
| **DR** | Disaster Recovery (recuperação de desastre) | 14 |
| **DoD** | Definition of Done | 24 · F |
| **ERER** | Educação das Relações Étnico-Raciais | 03 · 06 |

### A.12 Nomes próprios do universo

> **Não se traduzem** (regra da [Seção 02](02-vocabulario.md)). O catálogo/identidade dos planetas
> é da **[Seção 03](03-universo.md)**; o glossário **lista, não batiza**.

- **Constela** — a marca/ecossistema.
- **Constela Quest** — o jogo dos alunos.
- **Cosmo** — o mascote-companheiro (astronauta) que fala e dá dicas.
- **Constelação** — a metáfora central de progresso.
- **Os 9 planetas** (matéria → planeta): **Numéria** (Matemática) · **Palavras** (Português) ·
  **Biozênia** (Ciências) · **Terra Nova** (Geografia) · **Chronos** (História) · **Oxford** (Inglês) ·
  **Colorium** (Artes) · **Movi** (Ed. Física — ⚠️ Q5) · **Raízes** (ERER — ⚠️ Q5, curadoria humana).
  *Entrada de Movi e Raízes e a confirmação definitiva dos nomes são da [Seção 03](03-universo.md).*

### A.13 ⚠️ Rótulos infantis ainda em aberto

> Único bloco com pendência de decisão. A **decisão-dona é a [Seção 02.4](02-vocabulario.md)** (e o
> catálogo de planetas, a [Seção 03](03-universo.md)). Os verbetes entram com status ⚠️ **sem inventar rótulo**.

| Termo interno | Situação | Decisão-dona | Status |
|---------------|----------|:------------:|:------:|
| tela-casa (`lobby` no código) | "lobby" é palavra **proibida**; falta o rótulo infantil da tela-casa | 02.4 | ⚠️ em aberto |
| `perfil` → **Meu astronauta** | rótulo guarda-chuva das telas Vestiário/Carreira **a confirmar** | 02 | ⚠️ a confirmar |
| Nomes dos 9 planetas | catálogo provisório enquanto não ratificado definitivamente | 03 | ⚠️ provisório |

### A.14 Governança do glossário

- **Todo termo novo** entra via **spec/ADR** e **sincroniza com a [Seção 02](02-vocabulario.md)**
  (para vocabulário infantil) ou com a seção-dona correspondente (técnico → 11, negócio → 22, etc.).
- **Mudar um termo canônico exige ADR** (regra da própria Seção 02); a decisão vive em
  [`decisoes/`](decisoes/) (Apêndice C, já 🟢). O glossário **não é foro de decisão**.
- **Sem critério órfão:** todo verbete aponta uma seção-dona; se a fonte muda, o verbete é
  atualizado junto (norma [G7](24-governanca.md) — desacoplamento; a seção-dona tem autoridade).
- **Bilíngue e em sincronia:** o espelho EN nunca diverge do pt-BR; nomes próprios idênticos.

---

## 🇬🇧 Glossary

### A.1 How to use the glossary

This appendix is a **consolidated alphabetical reference** for every project term — the internal
vocabulary (code/db), the name the child sees, and the technical, pedagogical, business and
user-role terms. Each entry carries a **short definition**, the **internal↔child pair** (when one
exists) and a **pointer to the owner section**.

**Mother boundary:** the glossary **gathers and points; it does not redefine.** For every entry the
**authority is the owner section** — the normative text (rules, numbers, contracts) lives there.
Here there is only the short definition and the pointer. On conflict, **the owner section wins**
(norm [G10](24-governanca.md)).

**[Section 02 — Canonical Vocabulary](02-vocabulario.md)** owns the child vocabulary (internal→child
map, forbidden words, proper names, open labels). This glossary **consolidates and points** to it;
**changing a canonical term requires an ADR** (A.14).

### A.2 Structure of each entry

Every entry table uses the same fixed fields:

| Field | What it is |
|-------|-----------|
| **Term** | the word or phrase (internal or canonical) |
| **Category** | product/game · playful · technical · pedagogical · business · role · acronym |
| **Short definition** | one sentence; the normative text lives in the owner section |
| **Internal↔child pair** | the name the child sees/hears, when the term has a child label |
| **Owner section** | where the full rule lives (authority) |
| **Status** | 🟢 fixed · ⚠️ open (pending owner / a recorded decision) |

### A.3 Writing conventions

- **Ordering:** within each category, alphabetical by the **Term** column.
- **Bold:** the **name the child sees** is **bold**; the internal name is `code`.
- **Cross-refs:** "→ see also" links related entries.
- **Forbidden terms:** marked 🚫 and listed in full in A.10 (points to Section 02).
- **Proper names** (Cosmo, planets) **are not translated** — identical in pt-BR and the EN mirror.

### A.4 Product & game-design glossary (economy and progression)

> Labels and short definitions; **rules and numbers** (XP formulas, coin faucet, daily cap,
> thresholds) belong to **[Section 05](05-sistemas-de-jogo.md)** and the fantasy to
> **[Section 03](03-universo.md)**. The glossary **fixes no number**.

| Term | Short definition | Internal↔child pair | Owner | Status |
|------|------------------|--------------------|:-----:|:------:|
| **XP** | **progress** currency; only grows, drives the level, never spent nor lost | `xp` → *(shown as XP)* | 05 | 🟢 |
| **Star** | **per-Mission mastery (0–3)**; best attempt counts, never lost; the Boss key | `estrelas` → **Star** | 05 | 🟢 |
| **Coin** | earned by playing, **spent only on cosmetics**; changes only via the immutable ledger; **no real money** | `moedas` → **Coin** | 05 · 22 | 🟢 |
| **Level** | progression tier the XP raises; leveling up grants Coins + an item | `nivel` → **Level** | 05 | 🟢 |
| **Cosmo's Flame** | **streak** of days played, shown as continuity, not pressure | `sequencia_dias` → **Cosmo's Flame** | 03 · 05 | 🟢 |
| **Constellation** | central progress metaphor; stars that light up and form figures (me × me, never a ranking) | `progresso` → **Constellation** | 03 · 05 | 🟢 |
| **Boss** | a Journey's final, special Mission; unlocked when the Journey's Stars reach the threshold | `missao` type `chefao` → **Boss** | 05 | 🟢 |
| **Collectible** | a planet's identity reward, granted on completing a Journey | — → **Collectible** | 03 · 05 | 🟢 |
| **Achievement** | a celebrated milestone in the player's history (Career) | — → **Achievement** | 05 | 🟢 |
| **Daily Mission** | the day's Missions (plus the weekly ones) that set the return rhythm — counts and faucet in Section 05 | `missao` (daily) → **Mission** | 05 | 🟢 |
| **Daily cap** | daily XP limit; on reaching it it's **celebrated**, does not block play; resets at day rollover | — → *(celebration)* | 05 | 🟢 |
| **Season Pass** | a season progression track; **single and free** (no paid pass) | — → **Pass** | 22 · 19 | 🟢 |
| **Login gift** | daily login reward on entering (a track; length in Section 05) | — → **Gift** | 05 | 🟢 |

### A.5 Playful vocabulary (internal → child)

> Consolidated cross-reference to the **canonical map in [Section 02](02-vocabulario.md)** — without
> duplicating the source. This block is an index; the full table (with notes) lives in 02.

| Internal (code/db) | Child (UI/audio) | Owner | Status |
|--------------------|------------------|:-----:|:------:|
| `mundo` / subject | **Planet** | 02 · 03 | 🟢 |
| `jornada` | **Journey** | 02 | 🟢 |
| `missao` | **Mission** | 02 | 🟢 |
| `desafio` | **Challenge** | 02 | 🟢 |
| `missao` (type `chefao`) | **Boss** | 02 · 05 | 🟢 |
| `progresso` | **Constellation** | 02 · 03 | 🟢 |
| `sequencia_dias` | **Cosmo's Flame** | 02 · 05 | 🟢 |
| `sala` | **Study with a friend** / **Race** | 02 · 09 | 🟢 |
| `tentativa` | *(invisible — never shown)* | 02 | 🟢 |
| `perfil` | **My astronaut** *(label to confirm — A.13)* | 02 | ⚠️ |
| `codigo_amigo` | **Friend code** | 02 · 09 | 🟢 |
| home screen (`lobby` in code) | *(child label to define — A.13)* | 02.4 | ⚠️ |
| tabs | **Play** · **Wardrobe** · **Career** | 02 | 🟢 |
| mascot | **Cosmo** | 02 | 🟢 |

### A.6 Technical & architecture glossary

> Owner = **[Section 11](11-arquitetura.md)** (architecture); security/identity = **[Section 12](12-seguranca-privacidade.md)**.

| Term | Short definition | Owner | Status |
|------|------------------|:-----:|:------:|
| **Modular monolith** | a single backend service (FastAPI) with internal modules (Edu + `quest`), not microservices | 11 | 🟢 |
| **Outbox** | append-only event table that decouples the transactional write from publishing (notifications/telemetry) | 11 · 17 | 🟢 |
| **Immutable ledger** | append-only record of every coin change; balance is recomputable; a mistake never subtracts (Principle 14) | 05 · 11 | 🟢 |
| **PWA** | Progressive Web App: Quest installs/runs in the browser with an offline shell | 11 · 07 | 🟢 |
| **WebSocket** | real-time channel (e.g. presence, race); aspirational surface Q1+ | 11 | ⚠️ |
| **Mechanic plugin / registry** | `MecanicaProps` contract + registry that lets new Challenge types be added without touching the core | 05 · 11 | 🟢 |
| **R3F / Three.js** | React-Three-Fiber over Three.js: 3D rendering of the character and scenes | 11 · 15 | 🟢 |
| **CDN** | asset delivery network (GLB/audio/sprites) for fast loading | 11 · 15 | 🟢 |
| **`escola_id`** | multi-tenant isolation key; every row and query is filtered by school (Principle 15) | 11 · 12 | 🟢 |
| **JWT role `aluno`** | the child login token; real claims `sub`/`papel`/`ver`/`iat`/`exp`; distinct from the Edu token | 12 | 🟢 |
| **ETag / version** | catalog cache validator; the client revalidates without downgrading content | 11 | 🟢 |

### A.7 Pedagogical glossary

> Owner = **[Section 06](06-pedagogico-bncc.md)**; the Boss mechanic belongs to [Section 05](05-sistemas-de-jogo.md).

| Term | Short definition | Owner | Status |
|------|------------------|:-----:|:------:|
| **BNCC** | Brazil's national curriculum base; every Mission references a skill code | 06 | 🟢 |
| **Skill code** | BNCC identifier (e.g. `EF01MA01`) tying content to the curriculum | 06 | 🟢 |
| **Mastery (0–100)** | a student's mastery of a skill; feeds adaptive difficulty | 06 | 🟢 |
| **Adaptive difficulty** | tuning the challenge to the child's mastery (never punitive) | 06 · 05 | 🟢 |
| **School year** | 1st–5th grade; slices Journeys by BNCC band | 06 | 🟢 |
| **Spaced review** | planned re-presentation of content for retention | 06 | 🟢 |

### A.8 Business glossary

> Owner = **[Section 22](22-monetizacao.md)** (which points "business glossary → A.8"); A.8 **derives**
> from 22's definitions, it does not rewrite them. Product signals (basis of LTV/churn/activation) = [Section 17](17-telemetria-metricas.md).

| Term | Short definition | Owner | Status |
|------|------------------|:-----:|:------:|
| **License** | usage right contracted by a school/network; never sold to the child | 22 | 🟢 |
| **School / Network** | a tenant (one school) or a group of schools under an operator | 22 · 11 | 🟢 |
| **Operator (mantenedora)** | the entity administering one or more schools (buys/renews) | 22 | 🟢 |
| **Buyer × player** | the **adult** (school/network) buys; the **child** plays — never a buyer (Principle 7) | 22 | 🟢 |
| **B2B / B2G** | sales to private schools (B2B) and to the public sector (B2G) | 22 | 🟢 |
| **Pilot / Trial** | an initial evaluation period at a school before the license | 22 | 🟢 |
| **Activation** | a school/class actually using the product (not just contracted) | 22 · 17 | 🟢 |
| **LTV** | a school's value over the relationship (business metric) | 22 · 17 | 🟢 |
| **School churn** | a school that stops renewing the license | 22 · 17 | 🟢 |

### A.9 User-role glossary

> Owners = **[Section 10](10-professor-familia.md)** (teacher/family and the link) + **[Section 12](12-seguranca-privacidade.md)** (how they authenticate / what they access, RBAC).

| Role | How they authenticate | What they access (summary) | Owner | Status |
|------|-----------------------|----------------------------|:-----:|:------:|
| **Student** | code-only login (no password), JWT role `aluno` | only their own Quest; never sees individual ranking nor others' Coins | 12 · 05 | 🟢 |
| **Guardian** | authorized link to the student (Family Portal, phase Q3) | follow-up on their own child; no Coins/shop | 10 | ⚠️ |
| **Teacher** | Edu account (teacher role) | class and pedagogical progress; **does not** see Coins/shop | 10 | 🟢 |
| **Coordinator / School admin** | Edu account (school-admin role) | school, classes and import management, within `escola_id` | 10 · 12 | 🟢 |
| **Global admin** | Edu account (global-admin role) | auditable multi-school operation | 12 | 🟢 |

### A.10 FORBIDDEN words in the child UI 🚫

> Consolidated list; **source and official substitutes** in **[Section 02](02-vocabulario.md)**. They
> sound like school/competition/adult tech.

| 🚫 Forbidden | Why | Substitute |
|-------------|-----|------------|
| party | adult game jargon | **Study with a friend** |
| lobby | technical jargon | *(child label for the home screen — A.13)* |
| matchmaking | technical/competitive jargon | *(no competitive pairing exposed)* |
| squad | competitive jargon | **class** / **school friends** |
| global ranking | competition/exposure | **your Constellation** / **this week's class** |
| test | school/assessment | **Mission** / **Challenge** |
| exercise | school | **Mission** / **Challenge** |
| task | school/obligation | **Mission** / **Challenge** |
| fatal error | technology/fear | "almost!" / "shall we try again?" |
| failed | school/punishment | "let's do it together" / "almost!" |

### A.11 Acronyms & abbreviations

| Acronym | Expansion | Section |
|---------|-----------|:-------:|
| **BNCC** | Base Nacional Comum Curricular (Brazil's curriculum base) | 06 |
| **LGPD** | Lei Geral de Proteção de Dados (Brazil's data-protection law) | 12 |
| **ADR** | Architecture/Decision Record | 24 · C |
| **GDD** | Game Design Document | 05 |
| **PWA** | Progressive Web App | 11 |
| **TTS** | Text-to-Speech (synthesized narration) | 13 · 15 |
| **R3F** | React-Three-Fiber | 11 · 15 |
| **CDN** | Content Delivery Network | 11 |
| **RACI** | Responsible/Accountable/Consulted/Informed (responsibility matrix) | 21 |
| **COGS** | Cost of Goods Sold | 22 |
| **LTV** | Lifetime Value | 22 · 17 |
| **RBAC** | Role-Based Access Control | 12 |
| **DR** | Disaster Recovery | 14 |
| **DoD** | Definition of Done | 24 · F |
| **ERER** | Educação das Relações Étnico-Raciais (Ethnic-Racial Relations Education) | 03 · 06 |

### A.12 Proper names of the universe

> **Not translated** (Section 02 rule). The planets' catalog/identity belongs to
> **[Section 03](03-universo.md)**; the glossary **lists, it does not name**.

- **Constela** — the brand/ecosystem.
- **Constela Quest** — the students' game.
- **Cosmo** — the companion mascot (astronaut) who speaks and gives hints.
- **Constellation** — the central progress metaphor.
- **The 9 planets** (subject → planet): **Numéria** (Math) · **Palavras** (Portuguese) ·
  **Biozênia** (Science) · **Terra Nova** (Geography) · **Chronos** (History) · **Oxford** (English) ·
  **Colorium** (Arts) · **Movi** (Phys. Ed. — ⚠️ Q5) · **Raízes** (ERER — ⚠️ Q5, human curation).
  *Movi and Raízes entry and the definitive confirmation of the names belong to [Section 03](03-universo.md).*

### A.13 ⚠️ Child labels still open

> The only block with a pending decision. The **owner decision is [Section 02.4](02-vocabulario.md)**
> (and the planet catalog, [Section 03](03-universo.md)). Entries carry ⚠️ status **without inventing a label**.

| Internal term | Situation | Owner decision | Status |
|---------------|-----------|:--------------:|:------:|
| home screen (`lobby` in code) | "lobby" is a **forbidden** word; the child label for the home screen is missing | 02.4 | ⚠️ open |
| `perfil` → **My astronaut** | umbrella label for the Wardrobe/Career screens **to confirm** | 02 | ⚠️ to confirm |
| Names of the 9 planets | provisional catalog until definitively ratified | 03 | ⚠️ provisional |

### A.14 Governance of the glossary

- **Every new term** enters via **spec/ADR** and **syncs with [Section 02](02-vocabulario.md)** (for
  child vocabulary) or with the corresponding owner section (technical → 11, business → 22, etc.).
- **Changing a canonical term requires an ADR** (Section 02's own rule); the decision lives in
  [`decisoes/`](decisoes/) (Appendix C, already 🟢). The glossary **is not a decision forum**.
- **No orphan criteria:** every entry points to an owner section; if the source changes, the entry is
  updated with it (norm [G7](24-governanca.md) — decoupling; the owner section holds authority).
- **Bilingual and in sync:** the EN mirror never diverges from pt-BR; proper names identical.
