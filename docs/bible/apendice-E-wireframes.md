# Apêndice E — Wireframes / Mockups de Referência / Reference Wireframes

- **Status:** 🟢 aprovado / approved
- **Tipo:** documento de **referência** (não segue o padrão de 16 partes do [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md), que vale só para capítulos).
- **Fontes / Sources:** **[Seção 07](07-ux-fluxos-navegacao.md)** é dona do **inventário de telas** (§6), do **grafo de navegação** (§5) e da **matriz de estados** (§12); **[Seção 08](08-onboarding-ftue.md)** é dona da **sequência da cerimônia / 1º loop** (§5). Rótulos = [Seção 02](02-vocabulario.md); arte/tokens = [Seção 15](15-arte-audio-assets.md); telemetria = [Apêndice D](apendice-D-eventos-telemetria.md).
- **Depende de:** o **fluxo/UX** é das seções-donas; este apêndice **deriva** a descrição visual/estrutural — **não cria tela, aresta, estado nem regra**.

> **Selo por tela:** **🟢 Q0-REAL** = a tela existe no app hoje (`apps/quest`) · **🔵 aspiracional (fase)** =
> desenhada, sem tela. **Wireframe textual**, não pixel-final de arte (arte fina = [Seção 15](15-arte-audio-assets.md)).
> Telas de formato aberto marcam **⚠️** (E.25 Passe · E.33 Portal da Família · E.41 ferramenta · E.44 divergências).

---

## 🇧🇷 Wireframes de Referência

### Bloco META / Convenção (E.1–E.9)

**E.1 Como usar** — o mockup é **referência normativa de layout, estado e cópia** (não pixel-final); quando aprovado, **precede** o código. Arte fina remete à [Seção 15](15-arte-audio-assets.md). O apêndice **deriva** das seções-donas; não decide UX.

**E.2 Status e fontes** — âncora dupla: o **protótipo estético `constela-play-v7`** (herança visual) e o **Q0 em produção** (`apps/quest`). Separa o **vigente** (código atual) do **legado** (protótipo).

**E.3 Relação com `constela-play-v7`** — herda estética, `SUBJECTS`/`SCENES` e o `tema` JSON por planeta; onde o protótipo diverge do código atual, **o código vence** (a divergência entra em E.44, não vira verdade).

**E.4 Convenções de leitura** — cada ficha marca *hotspots* (ações tocáveis), legendas de estado, **vocabulário infantil** ([Seção 02](02-vocabulario.md)) e notas de **áudio/narração**.

**E.5 Ficha-modelo de tela** (template repetível):

| Campo | Conteúdo |
|-------|----------|
| **Nome** | interno ↔ rótulo infantil ([Seção 02](02-vocabulario.md)) |
| **Objetivo** | a ação primária **única** da tela (07§6) |
| **Elementos / layout** | wireframe textual (estrutura, não pixel) |
| **Estados cobertos** | os 6 canônicos de E.6 |
| **Navegação** | arestas de saída + **volta garantida à Tela-casa** (07§5) |
| **Áudio** | narração de entrada / "ouvir de novo" ([Seção 13](13-acessibilidade.md)) |
| **Acessibilidade** | E.37 |
| **Telemetria** | evento disparado ([Apêndice D](apendice-D-eventos-telemetria.md)) |
| **Breakpoint** | E.8 |
| **Selo** | 🟢 Q0-REAL / 🔵 aspiracional |

**E.6 Estados canônicos que TODA tela cobre** — os **5** da matriz-dona [07§12](07-ux-fluxos-navegacao.md) + a **adição** do estado sem-licença da [Seção 19](19-liveops.md):

| Estado | Contrato de apresentação (visual + áudio + saída) |
|--------|---------------------------------------------------|
| **Carregando** | *skeleton* + Cosmo presente + áudio de espera; nunca *spinner* mudo/infinito |
| **Vazio** | ilustração acolhedora + fala do Cosmo + **ação de 1º passo** |
| **Erro** (rede/servidor) | mensagem **sem culpa** + *retry* (auto e manual) + rota de fuga; jamais tela branca |
| **Offline** | banner de sinal; o que funciona (cache) × o que exige rede; fila reconcilia ao reconectar |
| **Sem-permissão** | social desligado pela escola/família, horário bloqueado ou aluno arquivado = **rótulo acolhedor** (canônico = [Seção 02](02-vocabulario.md)); nunca "código errado" que culpe a criança; regra = [06](06-pedagogico-bncc.md)/[09](09-social.md)/[10](10-professor-familia.md) |
| **Sem-licença / recurso desligado** *(adição da [Seção 19](19-liveops.md))* | rótulo acolhedor (nunca "erro"); gatilho = *kill-switch*/flag |

**E.7 Mapa de telas / navegação global** (espinha do grafo 07§5, sem *router*):

```
Boot/Splash → {perfis no aparelho?}
  ├─ sim → "Quem vai jogar?" → (toca perfil) → Entrar/Confirmar identidade
  └─ não → Entrar por código (ou QR)
Confirmar "É você?" → {onboarding concluído? (sinal terminal `onboarding_completed_at` da Seção 08, NUNCA `nome_exibicao`)}
  ├─ não → Cerimônia (Seção 08; retoma no passo pendente, sem repetir a festa) → Tela-casa
  └─ sim → Tela-casa
Tela-casa (hub, 3 abas) → Planeta → Jornada → MissãoPlayer → Recompensa → (volta) Tela-casa
Tela-casa → Vestiário/Loja · Carreira/Constelação · Missões diárias · Social
```
**Invariante:** toda tela profunda **retorna à Tela-casa** (botão-casa) — nenhum beco sem saída (07§9).

**E.8 Grid de responsividade** — alvos: **tablet retrato/paisagem** (primário), **Chromebook**, **telefone**. Sem *overflow* horizontal; a arte se recompõe, a ação primária nunca some.

**E.9 Tokens visuais** — cor/tipografia/UI-Kit = [Seção 15](15-arte-audio-assets.md); identidade por planeta = [Seção 03](03-universo.md). O apêndice **remete**, não fixa valores.

---

### Corredor de login / entrada (E.10–E.13)

**E.10 Boot + "É você, {nome}?"** — 🟢 Q0-REAL (`Boot`, `ConfirmarIdentidade` existem)
- **Objetivo:** guarda do **tablet compartilhado** (Princípio 4) — reconhecer o dono antes de entrar.
- **Layout:** *splash* offline-first (nunca tela branca); "Quem vai jogar?" = lista **não-sensível** (apelido + miniatura, **sem token**) dos perfis recentes; card "É você, {nome}?" com avatar; botões **Sou eu!** / **trocar**.
- **Estados:** carregando (shell), vazio (sem perfis em cache → vai ao login), erro, offline (boot funciona).
- **Navegação:** toca perfil → **re-autentica** (nunca herda sessão); trocar → login.
- **Áudio:** saudação do Cosmo; nome narrado.
- **Telemetria:** `identidade.confirmada` ([D.18](apendice-D-eventos-telemetria.md)).

**E.11 Entrar por código** — 🟢 Q0-REAL (`Entrada` existe)
- **Objetivo:** login **sem senha** (o código é a credencial) em 2 etapas `quem → entrar`.
- **Layout:** campo de código curto falável (ex.: `SOL1234`), letras narradas; confirmação "É você?" embutida; botão **Entrar** · **Sou eu!**.
- **Estados:** erro de código inválido (**sem culpar a criança** — "confira o cartão"), **rate-limit** ("descanse um pouquinho"), offline.
- **Telemetria:** `login.realizado`/`login.falhou` (motivo, **nunca o código** — [D.18](apendice-D-eventos-telemetria.md)).

**E.12 Entrar por QR** — 🔵 aspiracional/parcial (código existe; QR na câmera não confirmado no Q0)
- **Objetivo:** alternativa por leitura do cartão (câmera nativa / deep-link `?qr=`), **fallback** para código.
- **Estados:** câmera negada → cai no código; QR inválido → "peça um cartão novo".

**E.13 Cerimônia da 1ª vez** — 🟢 Q0-REAL (`Cerimonia.tsx` existe) · sequência = [Seção 08](08-onboarding-ftue.md)
- **Objetivo:** estreia com pertencimento; 3 passos **narrados**: **escolher personagem** (carrossel dos 6 base) → **nome** (2–20, letras e espaços, **sem texto livre**) → **festa** (fim da cerimônia → Tela-casa).
- **Estados:** ⚠️ **bug canônico Q0** — hoje `personagensBase()` cai num *catch* silencioso que **zera os personagens sem retry** (trava a criança): deve virar o estado **Erro** (retry + fala do Cosmo). Offline: cada passo com estado de erro; retomada **não repete a festa**.
- **Telemetria:** passos do funil FTUE ([Seção 08](08-onboarding-ftue.md)/[Apêndice D](apendice-D-eventos-telemetria.md)).
- **⚠️ Divergência (E.44):** o layout de personagem depende da decisão **avatar 3D × Cosmo 2D** ([Seção 04.2](04-personagens-avatar.md)) — **não canonizar** aqui.

### Tela-casa / Lobby 3 abas (E.14–E.16) — 🟢 Q0-REAL

**E.14 aba Jogar** — hub/nave-mãe: **céu tocável**, os 9 planetas-matéria ambientados ([Seção 03](03-universo.md)), Cosmo companheiro. **Ação primária: escolher um Planeta.** ⚠️ **rótulo infantil da Tela-casa em aberto** (o "lobby" do código; dona = [02.4](02-vocabulario.md)). Telemetria: `planeta.aberto`, `aba.trocada`.

**E.15 aba Vestiário** — customização do avatar por slots/categorias + **invocação de itens especiais**; entrada da economia cosmética. **Ação primária: trocar um item.** ⚠️ layout depende da decisão avatar 3D × 2D (E.44). Telemetria: `avatar.alterado`, `vestiario.aberto`.

**E.16 aba Carreira** — stats, conquistas, histórico; estado vazio "Minhas aventuras" (rótulo do Q0 **a ratificar** na [02](02-vocabulario.md)); **nunca** expõe ranking individual (P5). Constelação (progresso eu×eu) acessível daqui.

### Jornada & Jogo (E.17–E.23) — 🔵 aspiracional Q1+

- **E.17 Mapa do Planeta / Jornada** — trilha de Missões `●─●─○` + **Chefão travado por Estrelas**; progressão por ano escolar ([Seção 06](06-pedagogico-bncc.md)).
- **E.18 Constelação** — progresso **eu × eu-de-ontem** + álbum de colecionáveis; **nunca ranking**. ⚠️ identidade da superfície (mesma do céu da Tela-casa × tela distinta) **em aberto** (07§15).
- **E.19 MissãoPlayer** — casca que orquestra Desafios: enunciado, **botão de áudio**, barra de progresso, transição; apresenta Desafios **sem gabarito** (P13).
- **E.20 Mockups por mecânica** — quiz, arrastar, ligar, memória, completar, sequência, caça-palavras (touch-first). ⚠️ *schema* de corpo/gabarito por mecânica pende ([B.23](apendice-B-api-dados.md)).
- **E.21 Feedback de resposta** — acerto/erro **sempre acolhido** ("quase!"), dica, fala do Cosmo, **sem punição visual** (Princípio 6).
- **E.22 Recompensa/celebração** — fecho em tela cheia (XP/Moedas/Estrelas/item), proporcional à raridade; **nunca de mãos vazias**; subir de nível em tela cheia.
- **E.23 Tarefas do dia** — diárias/semanais + presente de login (quantidade = [Seção 05](05-sistemas-de-jogo.md)); viés a habilidades fracas.

### Economia / Loja / Temporada (E.24–E.26) — 🔵 aspiracional Q1+

- **E.24 Loja e rotação semanal** — 4–6 itens + seção fixa; escassez **honesta**, **sem dark patterns**, **sem compra real** (Princípio 7). Compra só com Moedas ganhas.
- **E.25 ⚠️ Passe de temporada** — **gratuito, sem trilho pago paralelo** (imutável, P7); **formato, layout e nº de trilhos A CONFIRMAR** pelo dono ([22.10](22-monetizacao.md) §15). Superfície do aluno **ainda não inventariada na [07§6](07-ux-fluxos-navegacao.md)** — entra aqui como **pendência**, não como tela derivada.
- **E.26 Chama do Cosmo** — estado do *streak*: marcos, escudo semanal, **reacender gentil**, **nunca culpa**.

### Social (E.27–E.31) — 🔵 aspiracional Q1+ (Q4 para partidas ao vivo)

- **E.27 Amigos e código de amigo** — `COSMO-4F7B`; **sem busca por nome real**; só amigos **da escola** (P15).
- **E.28 Convite e emparelhamento** — botão → online → convite → contagem 3-2-1; **sem matchmaking com estranhos**.
- **E.29 Modos sociais** — Estudar com um amigo · Corrida · Pintura em dupla · X1; **derrota nunca custa nada** (Princípio 6).
- **E.30 Mensagens rápidas** — catálogo (saudação/elogio/convite/reação) com áudio; **sem texto livre**.
- **E.31 Ranking de turma semanal** — zera na segunda; celebra o top 3; **anti-lanterna**; ranking **de turma**, nunca individual à criança (P5).

### Superfícies adultas do Edu (E.32–E.33) — 🔵 aspiracional · fluxo = [Seção 10](10-professor-familia.md)

- **E.32 Professor no Edu** — panorama da turma, mapa BNCC, erros comuns, trajetória, alertas; **sem ruído lúdico, sem narração obrigatória, sem exposição individual da criança**.
- **E.33 ⚠️ Portal da Família** — resumo do filho + controles social/horário; **entrada e autorização do vínculo A CONFIRMAR** (fase Q3, [Seção 10](10-professor-familia.md)).

### Estados/sistema transversais (E.34–E.35)

- **E.34 Galeria consolidada de estados** — reúne as variações erro/vazio/offline por tela para verificar cobertura (liga a [F.3](apendice-F-checklists-dod.md)).
- **E.35 Telas de sistema** — sem licença, recurso desligado (*kill-switch*/flag), manutenção — o que a criança vê quando um recurso está indisponível ([Seção 19](19-liveops.md)); rótulo acolhedor, nunca "erro".

### Anotações transversais (E.36–E.39)

- **E.36 Diálogos do Cosmo em contexto** — mapeia cada fala à tela (recepção/torcida/dica/consolo/festa/descanso); guia = [Seção 02](02-vocabulario.md).
- **E.37 Acessibilidade nos mockups** — alvos **≥48px**, ordem de foco, modo daltônico, `reduced-motion`, **áudio obrigatório** de cada instrução ([Seção 13](13-acessibilidade.md)).
- **E.38 Anotação de telemetria** — marca **qual evento** cada tela/ação dispara, amarrando ao [Apêndice D](apendice-D-eventos-telemetria.md) (instrumentação por design).
- **E.39 Anotação de i18n** — *strings* externalizadas, expansão PT→EN, paridade com o espelho EN ([Seção 16](16-localizacao-i18n.md)).

### Governança & sync (E.40–E.44)

- **E.40 Sincronização mockup ↔ implementação** — o mockup aprovado é a **fonte de verdade de layout**; quando precede o código; como detectar/registrar *drift*. ⚠️ a **precedência quando divergem** (mockup × código vigente) é pendência registrada.
- **E.41 ⚠️ Ferramenta e formato dos mockups** — Figma × protótipo HTML `constela-play-v7` × outro: **escolha A CONFIRMAR** pelo dono.
- **E.42 Versionamento e nomenclatura** — segue a convenção de arquivos da Bible ([24.14](24-governanca.md)); o apêndice não inventa processo próprio.
- **E.43 Governança do mockup** — **Portão 1** ([Seção 24](24-governanca.md)): quando o mockup vira normativo, quem aprova, como entra no fluxo de *spec*.
- **E.44 ⚠️ Pendências / divergências mockup × código** — **avatar humanoide 3D × Cosmo 2D** (decisão fundadora [04.2](04-personagens-avatar.md), afeta E.13/E.15) e **catálogo cosmético hardcoded no cliente**: **não canonizar** até decisão do dono.

---

## 🇬🇧 Reference Wireframes

- **Flow owners:** **[Section 07](07-ux-fluxos-navegacao.md)** owns the screen **inventory** (§6), the **navigation graph** (§5) and the **states matrix** (§12); **[Section 08](08-onboarding-ftue.md)** owns the **ceremony / first-loop sequence** (§5). This appendix **derives** the visual/structural description — it **creates no screen, edge, state or rule**.

> **Seal per screen:** **🟢 Q0-REAL** = the screen exists in the app today (`apps/quest`) · **🔵 aspirational (phase)**
> = designed, no screen. **Textual wireframe**, not pixel-final art (fine art = [Section 15](15-arte-audio-assets.md)).
> Open-format screens carry **⚠️** (E.25 Pass · E.33 Family Portal · E.41 tool · E.44 divergences).

### META / Convention block (E.1–E.9)

**E.1 How to use** — the mockup is the **normative reference for layout, state and copy** (not pixel-final); once approved, it **precedes** the code. Fine art defers to [Section 15](15-arte-audio-assets.md). The appendix **derives** from the owner sections; it decides no UX.

**E.2 Status and sources** — a dual anchor: the aesthetic prototype **`constela-play-v7`** (visual heritage) and **Q0 in production** (`apps/quest`). It separates the **current** (today's code) from the **legacy** (prototype).

**E.3 Relation to `constela-play-v7`** — inherits aesthetics, `SUBJECTS`/`SCENES` and the per-planet `tema` JSON; where the prototype diverges from today's code, **the code wins** (the divergence goes to E.44, not into truth).

**E.4 Reading conventions** — each sheet marks hotspots (tappable actions), state captions, **child vocabulary** ([Section 02](02-vocabulario.md)) and **audio/narration** notes.

**E.5 Screen sheet template** (repeatable):

| Field | Content |
|-------|---------|
| **Name** | internal ↔ child label ([Section 02](02-vocabulario.md)) |
| **Objective** | the screen's **single** primary action (07§6) |
| **Elements / layout** | textual wireframe (structure, not pixels) |
| **States covered** | the 6 canonical of E.6 |
| **Navigation** | exit edges + **guaranteed return to the Home screen** (07§5) |
| **Audio** | entry narration / "hear again" ([Section 13](13-acessibilidade.md)) |
| **Accessibility** | E.37 |
| **Telemetry** | event fired ([Appendix D](apendice-D-eventos-telemetria.md)) |
| **Breakpoint** | E.8 |
| **Seal** | 🟢 Q0-REAL / 🔵 aspirational |

**E.6 Canonical states every screen covers** — the **5** of the owner matrix [07§12](07-ux-fluxos-navegacao.md) + the **addition** of the no-license state from [Section 19](19-liveops.md):

| State | Presentation contract (visual + audio + exit) |
|-------|-----------------------------------------------|
| **Loading** | skeleton + Cosmo present + waiting audio; never a mute/infinite spinner |
| **Empty** | welcoming illustration + Cosmo line + **first-step action** |
| **Error** (network/server) | **blame-free** message + retry (auto and manual) + escape route; never a blank screen |
| **Offline** | signal banner; what works (cache) × what needs the network; queue reconciles on reconnect |
| **No-permission** | social off by the school/family, blocked hours or an archived student = **welcoming label** (canonical = [Section 02](02-vocabulario.md)); never a "wrong code" that blames the child; rule = [06](06-pedagogico-bncc.md)/[09](09-social.md)/[10](10-professor-familia.md) |
| **No-license / feature off** *(addition from [Section 19](19-liveops.md))* | welcoming label (never "error"); trigger = kill-switch/flag |

**E.7 Screen map / global navigation** (spine of the 07§5 graph, no router):

```
Boot/Splash → {profiles on device?}
  ├─ yes → "Who's playing?" → (tap profile) → Enter/Confirm identity
  └─ no  → Enter by code (or QR)
Confirm "is it you?" → {onboarding complete? (Section 08 terminal signal `onboarding_completed_at`, NEVER `nome_exibicao`)}
  ├─ no  → Ceremony (Section 08; resumes at the pending step, no party repeat) → Home
  └─ yes → Home
Home (hub, 3 tabs) → Planet → Journey → MissionPlayer → Reward → (back) Home
Home → Wardrobe/Store · Career/Constellation · Daily Missions · Social
```
**Invariant:** every deep screen **returns to Home** (home button) — no dead ends (07§9).

**E.8 Responsiveness grid** — targets: **tablet portrait/landscape** (primary), **Chromebook**, **phone**. No horizontal overflow; art reflows, the primary action never disappears.

**E.9 Visual tokens** — color/typography/UI-Kit = [Section 15](15-arte-audio-assets.md); per-planet identity = [Section 03](03-universo.md). The appendix **defers**, it fixes no values.

---

### Login / entry corridor (E.10–E.13)

**E.10 Boot + "is it you, {name}?"** — 🟢 Q0-REAL (`Boot`, `ConfirmarIdentidade` exist)
- **Objective:** the **shared-tablet** guard (Principle 4) — recognize the owner before entering.
- **Layout:** offline-first splash (never a blank screen); "Who's playing?" = a **non-sensitive** list (nickname + thumbnail, **no token**) of recent profiles; "is it you, {name}?" card with avatar; **It's me!** / **switch** buttons.
- **States:** loading (shell), empty (no cached profiles → login), error, offline (boot works).
- **Navigation:** tap profile → **re-authenticate** (never inherits a session); switch → login.
- **Audio:** Cosmo greeting; name narrated.
- **Telemetry:** `identidade.confirmada` ([D.18](apendice-D-eventos-telemetria.md)).

**E.11 Enter by code** — 🟢 Q0-REAL (`Entrada` exists)
- **Objective:** **passwordless** login (the code is the credential) in 2 steps `quem → entrar`.
- **Layout:** short speakable code field (e.g. `SOL1234`), narrated letters; embedded "is it you?" confirmation; **Enter** · **It's me!** buttons.
- **States:** invalid code error (**never blames the child** — "check the card"), **rate-limit** ("rest a bit"), offline.
- **Telemetry:** `login.realizado`/`login.falhou` (reason, **never the code** — [D.18](apendice-D-eventos-telemetria.md)).

**E.12 Enter by QR** — 🔵 aspirational/partial (code exists; camera QR not confirmed in Q0)
- **Objective:** card-scan alternative (native camera / `?qr=` deep-link), **fallback** to code.
- **States:** camera denied → falls back to code; invalid QR → "ask for a new card".

**E.13 First-time ceremony** — 🟢 Q0-REAL (`Cerimonia.tsx` exists) · sequence = [Section 08](08-onboarding-ftue.md)
- **Objective:** debut with belonging; 3 **narrated** steps: **choose character** (carousel of the 6 base) → **name** (2–20, letters and spaces, **no free text**) → **party** (ceremony end → Home).
- **States:** ⚠️ **Q0 canonical bug** — today `personagensBase()` falls into a silent catch that **zeroes the characters with no retry** (locks the child): it must become the **Error** state (retry + Cosmo line). Offline: each step has an error state; resume **does not repeat the party**.
- **Telemetry:** FTUE funnel steps ([Section 08](08-onboarding-ftue.md)/[Appendix D](apendice-D-eventos-telemetria.md)).
- **⚠️ Divergence (E.44):** the character layout depends on the **3D avatar × 2D Cosmo** decision ([Section 04.2](04-personagens-avatar.md)) — **do not canonize** here.

### Home screen / 3-tab Lobby (E.14–E.16) — 🟢 Q0-REAL

**E.14 Play tab** — hub/mothership: **tappable sky**, the 9 subject-planets set-dressed ([Section 03](03-universo.md)), Cosmo companion. **Primary action: choose a Planet.** ⚠️ **the Home screen's child label is open** (the code's "lobby"; owner = [02.4](02-vocabulario.md)). Telemetry: `planeta.aberto`, `aba.trocada`.

**E.15 Wardrobe tab** — avatar customization by slots/categories + **special-item invocation**; cosmetic-economy entry. **Primary action: change one item.** ⚠️ layout depends on the 3D × 2D avatar decision (E.44). Telemetry: `avatar.alterado`, `vestiario.aberto`.

**E.16 Career tab** — stats, achievements, history; empty state "My adventures" (Q0 label **to ratify** in [02](02-vocabulario.md)); **never** exposes an individual ranking (P5). The Constellation (me × me progress) is reachable from here.

### Journey & Game (E.17–E.23) — 🔵 aspirational Q1+

- **E.17 Planet / Journey map** — Mission track `●─●─○` + **Boss locked by Stars**; progression by school year ([Section 06](06-pedagogico-bncc.md)).
- **E.18 Constellation** — **me × yesterday-me** progress + collectible album; **never a ranking**. ⚠️ surface identity (same as the Home sky × a distinct screen) is **open** (07§15).
- **E.19 MissionPlayer** — the shell orchestrating Challenges: prompt, **audio button**, progress bar, transition; presents Challenges **without the answer key** (P13).
- **E.20 Per-mechanic mockups** — quiz, drag, match, memory, fill-in, sequence, word-search (touch-first). ⚠️ per-mechanic body/answer-key schema pending ([B.23](apendice-B-api-dados.md)).
- **E.21 Answer feedback** — right/wrong **always welcomed** ("almost!"), hint, Cosmo line, **no visual punishment** (Principle 6).
- **E.22 Reward/celebration** — full-screen close (XP/Coins/Stars/item), proportional to rarity; **never empty-handed**; level-up full-screen.
- **E.23 Daily tasks** — dailies/weeklies + login gift (counts = [Section 05](05-sistemas-de-jogo.md)); biased to weak skills.

### Economy / Store / Season (E.24–E.26) — 🔵 aspirational Q1+

- **E.24 Store and weekly rotation** — 4–6 items + a fixed section; **honest** scarcity, **no dark patterns**, **no real purchase** (Principle 7). Purchase only with earned Coins.
- **E.25 ⚠️ Season pass** — **free, no parallel paid track** (immutable, P7); **format, layout and number of tracks TO CONFIRM** by the owner ([22.10](22-monetizacao.md) §15). A child surface **not yet inventoried in [07§6](07-ux-fluxos-navegacao.md)** — recorded here as a **pending item**, not a derived screen.
- **E.26 Cosmo's Flame** — streak state: milestones, weekly shield, **gentle relight**, **never guilt**.

### Social (E.27–E.31) — 🔵 aspirational Q1+ (Q4 for live matches)

- **E.27 Friends and friend code** — `COSMO-4F7B`; **no real-name search**; only **school** friends (P15).
- **E.28 Invite and pairing** — button → online → invite → 3-2-1 countdown; **no matchmaking with strangers**.
- **E.29 Social modes** — Study with a friend · Race · Duo painting · 1v1; **defeat never costs anything** (Principle 6).
- **E.30 Quick messages** — a catalog (greeting/praise/invite/reaction) with audio; **no free text**.
- **E.31 Weekly class ranking** — resets on Monday; celebrates the top 3; **anti-last-place**; a **class** ranking, never an individual one to the child (P5).

### Adult Edu surfaces (E.32–E.33) — 🔵 aspirational · flow = [Section 10](10-professor-familia.md)

- **E.32 Teacher in Edu** — class overview, BNCC map, common errors, trajectory, alerts; **no playful noise, no mandatory narration, no individual child exposure**.
- **E.33 ⚠️ Family Portal** — child summary + social/time controls; **link entry and authorization TO CONFIRM** (phase Q3, [Section 10](10-professor-familia.md)).

### Cross-cutting system states (E.34–E.35)

- **E.34 Consolidated state gallery** — gathers the error/empty/offline variations per screen to verify coverage (links to [F.3](apendice-F-checklists-dod.md)).
- **E.35 System screens** — no-license, feature off (kill-switch/flag), maintenance — what the child sees when a feature is unavailable ([Section 19](19-liveops.md)); a welcoming label, never "error".

### Cross-cutting annotations (E.36–E.39)

- **E.36 Cosmo dialogs in context** — maps each line to its screen (welcome/cheer/hint/comfort/party/rest); guide = [Section 02](02-vocabulario.md).
- **E.37 Accessibility on mockups** — targets **≥48px**, focus order, colorblind mode, `reduced-motion`, **mandatory audio** for every instruction ([Section 13](13-acessibilidade.md)).
- **E.38 Telemetry annotation** — marks **which event** each screen/action fires, tying to [Appendix D](apendice-D-eventos-telemetria.md) (instrumentation by design).
- **E.39 i18n annotation** — externalized strings, PT→EN expansion, parity with the EN mirror ([Section 16](16-localizacao-i18n.md)).

### Governance & sync (E.40–E.44)

- **E.40 Mockup ↔ implementation sync** — the approved mockup is the **layout source of truth**; when it precedes the code; how to detect/record drift. ⚠️ the **precedence when they diverge** (mockup × current code) is a recorded pending item.
- **E.41 ⚠️ Mockup tool and format** — Figma × the `constela-play-v7` HTML prototype × other: **choice TO CONFIRM** by the owner.
- **E.42 Versioning and naming** — follows the Bible's file convention ([24.14](24-governanca.md)); the appendix invents no process of its own.
- **E.43 Mockup governance** — **Gate 1** ([Section 24](24-governanca.md)): when a mockup becomes normative, who approves, how it enters the spec flow.
- **E.44 ⚠️ Pending / mockup × code divergences** — **3D humanoid avatar × 2D Cosmo** (founding decision [04.2](04-personagens-avatar.md), affects E.13/E.15) and the **client-hardcoded cosmetic catalog**: **do not canonize** until the owner decides.
