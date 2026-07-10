# 15 — Direção de Arte, Áudio & Pipeline de Assets / Art Direction, Audio & Asset Pipeline

- **Status:** 🔴 rascunho / draft
- **Padrão / Standard:** [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) (16 partes)
- **Fontes / Sources:** `INDICE.md` (bloco 15, subseções 15.1–15.40 + espelho de decisões em aberto; ⚠️ 15.9/15.11/15.12/15.27/15.35/15.38), `_estado-atual/RELATORIO-2026-07-09.md` (Q0: 3D procedural, áudio sintetizado), `docs/bible/biblia-sensorial/` (README + `00-cosmo.md` + `01-numeria.md`…`08-movi.md` + `09-raizes.md` — direção sensorial dos 9 mundos + Cosmo, 35 campos por ficha), `apps/quest/src/audio/audio.ts` (WebAudio SFX + Web Speech pt-BR; seleção de voz cai para voz de rede se não houver local; nota "OGG na Q1"), `apps/quest/src/design/tokens.css` (paleta real, tema claro/escuro, `--alvo-minimo: 48px`), `apps/quest/src/design/base.css` (UI kit + foco + reduced-motion), `apps/quest/src/lobby/materias.ts` (paletas por-mundo, inclui chave `erer`), `apps/quest/src/lobby/cenasTema.ts` (cenas SVG por matéria, geradas por agentes — inclui chave `erer`), `apps/quest/src/personagem/{Personagem,Cena3D,Itens3D}.tsx` (avatar 3D procedural R3F, sem GLB), `apps/quest/src/cosmo/Cosmo.tsx` (mascote SVG), `packages/quest-core/src/tipos.ts` (preferência `musica` órfã), `apps/quest/src/main.tsx` (@fontsource Baloo 2 + Nunito), `apps/quest/package.json` (three/@react-three/fiber/drei), Seções [03](03-universo.md)/[04](04-personagens-avatar.md)/[11](11-arquitetura.md)/[13](13-acessibilidade.md)/[14](14-infra-deploy-dr.md)
- **Depende de / Depends on:** princípios (P9 áudio sempre pt-BR · P11 acessibilidade inegociável · P17 piso de desempenho/offline-first · P18 sem tracking de terceiros) → [01](01-principios-imutaveis.md); **narrativa/direção sensorial** dos 9 mundos + Cosmo (cosmogonia, 35 campos por ficha, persona/voz-tom do Cosmo) → [03](03-universo.md) + `biblia-sensorial/`; **slots/regras** do avatar, o **rig** e o **orçamento** do avatar (12k tris/28 ossos/atlas 1024²/1 LOD/GLB ≤2 MB) + o **contrato de manifesto de assets** → [04](04-personagens-avatar.md); **mecanismo** de render híbrido (R3F/Three.js no personagem + SVG/CSS no ambiente/UI), device-alvo (11.48), degradação, lazy-load → [11](11-arquitetura.md); **norma** de acessibilidade (contraste 4.5:1/3:1 exigido, existência do modo daltônico, **valores de fonte N11 e espaçamento N1**, áudio obrigatório pt-BR + "ouvir de novo" + offline + fallback visual, reduced-motion) → [13](13-acessibilidade.md); **storage/CDN** de entrega do acervo → [14](14-infra-deploy-dr.md); regra "asset público sem token, nunca gabarito" → [12](12-seguranca-privacidade.md); **guia de voz/tom** do Cosmo e vocabulário canônico → [02](02-vocabulario.md); **superfície** das telas e da tela de preferências → [07](07-ux-fluxos-navegacao.md); **valores** de progressão/teto/pausa (que a arte só reveste) → [05](05-sistemas-de-jogo.md)/[19](19-liveops.md).

> **Convenção / Convention:** "§N" = uma das 16 **partes deste capítulo** / one of the 16 **parts of this
> chapter**; "Seção NN" / "Section NN" = outro capítulo da Bible / another Bible chapter; "15.NN" = uma
> subseção do plano do `INDICE.md` / a subsection of the `INDICE.md` plan.
> **Escopo / Scope:** este capítulo decide a **direção de arte, a estratégia de áudio e o pipeline de assets** do
> Constela Quest — a **barra de qualidade** visual/sonora, os **valores** de paleta/contraste que satisfazem a
> Seção [13](13-acessibilidade.md), a **estratégia de áudio** (sintetizado × gravado × híbrido), e o **pipeline**
> de produção/otimização/versionamento do acervo. Ele **executa** a direção sensorial da Seção [03](03-universo.md)/`biblia-sensorial/`
> e satisfaz a **norma** da Seção [13](13-acessibilidade.md); **não** decide a **narrativa** (Seção 03), as
> **regras/orçamento** do avatar (Seção 04), o **mecanismo** de render (Seção 11), a **norma** de acessibilidade
> (Seção 13) nem a **entrega** por CDN (Seção 14) — apenas os **produz, veste e referencia**.

---

## 🇧🇷 Direção de Arte, Áudio & Pipeline de Assets

### 1. Objetivo
Ser a **referência definitiva de direção de arte, áudio e produção de assets** do Constela Quest: a **barra de
qualidade** que faz o jogo parecer e soar como um **jogo moderno** — encantador, coeso e com acabamento — **sem
estourar** o tablet de escola. Permite produzir arte e som **sem re-decidir o estilo** a cada tela e **sem
improvisar formato/peso**. Decide a **execução** (barra visual/sonora, paleta, estratégia de áudio, pipeline);
**não** decide a **narrativa** (Seção [03](03-universo.md)), as **regras/orçamento** do avatar (Seção [04](04-personagens-avatar.md)),
o **mecanismo** de render (Seção [11](11-arquitetura.md)), a **norma** de acessibilidade (Seção [13](13-acessibilidade.md))
nem a **entrega** por CDN (Seção [14](14-infra-deploy-dr.md)).

### 2. Contexto
No ecossistema **Hub → Edu → Quest**, a arte é o que a criança **vê e ouve primeiro** — e o público não-leitor
depende do **som** e da **cor** para navegar. **Estado atual (Q0) — tudo gerado por código, quase nenhum asset
binário:**
- **Personagem & itens** — avatar 3D **100% procedural** em React Three Fiber (`Personagem.tsx`: primitivas
  Three.js, animação por `useFrame`, sem esqueleto/clip); itens especiais (`Itens3D.tsx`) com brilho emissivo +
  `pointLight`. **Não** há `.glb`/`.gltf`, texturas/PBR, shaders custom nem partículas de GPU.
- **Ambiente & mundos** — **SVG/CSS**, não 3D: céu em gradiente CSS, constelações SVG, `Planeta.tsx` SVG,
  partículas em `<span>` do DOM, `cenasTema.ts` = cenas *line-art* por matéria (**geradas por agentes de IA**,
  revisadas) — **inclui uma chave `erer`** (arte do mundo Raízes/ERER autorada por IA).
- **Cosmo (mascote)** — **SVG procedural** com física de mola JS (companheiro; a persona/voz vive na
  `biblia-sensorial/00-cosmo.md`).
- **Áudio** — **100% sintetizado**: SFX via WebAudio (osciladores; "erro nunca é buzina") + narração via **Web
  Speech API** pt-BR, com fallback para texto **no balão**. A seleção de voz prefere a **local**, mas **cai para
  voz de rede** se o aparelho não tiver pt-BR local. **Nenhum** arquivo de áudio no repo; `audio.ts` anota
  "áudios gravados (OGG) entram na Q1". A preferência `musica` está **órfã** (campo em `quest-core`, **sem
  player, sem toggle na UI, não consumida** por `configurarAudio`).
- **Paleta & tipografia** — `tokens.css` é a paleta real (ink `#231D4E`, sun `#FFC93C`, coral `#FF5470`, violet
  `#7C6FF0`, green `#3ED66E`…; tema claro/escuro); paletas por-mundo em `materias.ts`. Fontes **Baloo 2** +
  **Nunito** auto-hospedadas (`@fontsource`, woff2 — os únicos assets binários além dos ícones do PWA). **Não**
  há *ratio* de contraste auditado, paleta daltônica nem token de tamanho de fonte (lacunas que a Seção 13 aponta).
- **Acervo/pipeline** — inexistente: `public/` só tem favicon + ícones do PWA; nada entregue por CDN; sem export
  GLB, compressão de textura, atlas ou build 3D.

Este capítulo **fixa** a barra de qualidade, **audita** a paleta contra a norma da 13, **unifica** a estratégia
de áudio e **especifica** o pipeline-alvo.

### 3. Filosofia da funcionalidade
**"Reconhecível em 1 segundo, encantador para sempre."** A arte do Constela tem um **DNA** (`biblia-sensorial/`):
formas arredondadas e amigáveis, cor viva mas **legível**, brilho que celebra sem cansar. **A acessibilidade é
parte do estilo, não um freio:** a paleta é bonita **porque** tem contraste; o som guia **porque** é claro. O
princípio de produção: **procedural primeiro, asset quando o gatilho de promoção justifica** (§9/A11; gatilho em §13) — o que o
código gera bem (o Cosmo, as partículas, o brilho) fica como piso; o que a Seção [04](04-personagens-avatar.md)
decidiu autorar (personagem, itens) sobe para GLB **sem perder o piso de desempenho e offline** (P17).

Conexão com os **Princípios Imutáveis** ([01](01-principios-imutaveis.md)): **P9** (áudio sempre pt-BR) faz da
**voz do Cosmo** o instrumento central; **P11** (acessibilidade) obriga paleta com contraste + modo daltônico +
áudio que guia; **P17** (piso de desempenho/offline-first) é o **orçamento de peso** e o **pré-cache** que
disciplinam cada asset; **P18** (sem tracking) mantém o cliente **sem SDK de rastreamento de terceiros** — e o
áudio nunca envia texto de criança a **voz de rede** (§9/A6). Aos **4 pilares**: **surpresa** (o brilho, a
invocação), **autonomia** (cor+som guiam o não-leitor), **progresso visível** (a constelação que cresce),
**vínculo** (um mundo que a criança reconhece como seu).

### 4. Experiência que o jogador deve sentir
**"Que lindo — e é meu."** A criança sente um mundo **vivo e caprichado**: o Cosmo respira e reage ao toque, o
planeta pulsa, o item especial **invoca** com uma cena que arranca um "uau". A **voz** é calorosa, clara e
sempre em português — nunca robótica a ponto de assustar. A cor é **alegre e legível** (nada "lava os olhos"). O
som do **acerto** é uma faísca gostosa; o do **erro**, um "quase!" gentil — **nunca** uma buzina de reprovação
(P6). Ao final, a sensação é de um produto **cuidado**, à altura dos jogos que a criança ama.

### 5. Fluxo completo
Como a arte e o áudio **atravessam** a experiência (o inventário de telas é da Seção [07](07-ux-fluxos-navegacao.md)):

1. **Entrada** — céu temático, Cosmo recebendo com **voz** pt-BR; SFX suave de foco/toque.
2. **Cerimônia (1ª vez)** — paleta de traje viva; o personagem ganha **cor** com brilho; narração guia cada passo.
3. **Lobby / mundos** — cada matéria tem sua **paleta e cena** (`materias.ts`/`cenasTema.ts`); partículas leves;
   música ambiente **opcional** (⚠️ §15).
4. **Atividade** — feedback multissensorial (cor + ícone + **som**); instrução **falada** (áudio obrigatório — 13).
5. **Item especial / recompensa** — **invocação** cinematográfica (com versão estática sob reduced-motion — 13).
6. **Offline / primeira sessão** — a narração toca **localmente** (voz pt-BR local ou clipe gravado pré-cacheado);
   o **GLB base** é **pré-cacheado**, e o **procedural** é o fallback garantido se o GLB não estiver em cache (P17).
7. **Fallback de som** — quando o áudio não pode tocar (mudo, sem voz local, clipe indisponível), o **equivalente
   visual** guia (N17 da 13); a arte nunca depende só do som e **nunca** cai para voz de rede.
8. **Degradação em hardware fraco** — menos partículas, materiais mais simples, **procedural** como piso; o
   feedback essencial permanece (mecanismo = Seção [11](11-arquitetura.md); norma = Seção [13](13-acessibilidade.md)).

### 6. Interface (quando existir)
A 15 **não desenha telas** (inventário = Seção [07](07-ux-fluxos-navegacao.md)). Ela é dona do **look-and-feel**
que veste toda a UI: o **design system** (`tokens.css`/`base.css` — botões 3D, chips, painéis, toasts, foco
visível), a **tipografia** (Baloo 2 display + Nunito corpo), e o **kit de estados de UI** (vazio, carregando,
erro, offline) com o par **visual + som** de cada estado. A **posição** das superfícies de preferências (modo
daltônico, tamanho de fonte, música) é da Seção [07](07-ux-fluxos-navegacao.md); a 15 provê o **conteúdo visual/sonoro**.

### 7. UX
A 15 dá o **acabamento sensorial**, sempre subordinado à norma da Seção [13](13-acessibilidade.md):
- **Cor legível** — toda cor de texto/UI satisfaz o contraste **exigido pela 13** (4.5:1 texto / 3:1 texto grande
  e UI); a cor **nunca é o único canal** (forma/ícone/rótulo/áudio a acompanham).
- **Som que guia, não polui** — SFX curtos e suaves; narração calorosa; volume que não assusta; "ouvir de novo"
  sempre disponível (superfície = 13/07).
- **Movimento com propósito** — brilho e vida celebram; sob `prefers-reduced-motion` a arte tem **versão estática**.
- **Tipografia amiga do leitor iniciante** — corpo generoso, alto contraste, tamanho **ajustável** (token da 15;
  valor da 13 — §9).
- **Voz do Cosmo** — sempre dentro do **guia ✓/✗** da Seção [02](02-vocabulario.md) (nada de jargão de escola/sistema).

### 8. Game Design
**N/A como mecânica** — a 15 não cria regra de jogo; ela **veste** a mecânica das Seções [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md).
Nota de fronteira: os **skins** do motor de corrida/atividades são **arte da 15**, mas o **motor** e os **valores**
(XP, teto, pausa) são de 05/11/19 — a 15 só dá a roupa visual/sonora, nunca o número.

### 9. Regras de negócio
As **normas de arte/áudio/pipeline** (a fonte única da execução; a **norma** de acessibilidade é da Seção
[13](13-acessibilidade.md), a **narrativa** da Seção [03](03-universo.md), o **orçamento do avatar** da Seção [04](04-personagens-avatar.md)):

| # | Norma | Regra | Fronteira |
|---|-------|-------|-----------|
| A1 | **Barra de qualidade** | acabamento de "jogo moderno", **verificável por proxies**: paleta que passa A3 + **coesão entre mundos** (mesma família tipográfica, mesma linguagem de brilho/sombra, mesmo raio de canto, mesma escala de partícula) + referência de barra nomeada (§15) | 15 |
| A2 | **Paleta — fonte única** | `tokens.css` é a **única fonte de verdade** da cor de UI; `materias.ts`/`cenasTema.ts` **derivam** dela | 15 (converge 3 fontes) |
| A3 | **Contraste (valores)** | as cores reais **devem** satisfazer **4.5:1** (texto) / **3:1** (texto grande e UI), **auditadas por medição** (razão WCAG, via ferramenta) sobre o inventário enumerado de `tokens.css` (temas claro/escuro) + derivações de `materias.ts`; os tokens que **reprovarem são ajustados antes de publicar** | 15 (valor); limiar + def. "texto grande" = [13](13-acessibilidade.md) |
| A4 | **Cor nunca é canal único** | toda cor que **codifica estado** tem redundância (forma/ícone/rótulo/áudio) | 15 aplica; norma = [13](13-acessibilidade.md) |
| A5 | **Modo daltônico (paletas)** | redundância sempre ativa; paletas seguras e/ou **padrões/texturas** onde a cor codifica estado; cobrir deuteranopia/protanopia/tritanopia | 15 ⚠️ (método/tipos — §15); existência = [13](13-acessibilidade.md) |
| A6 | **Estratégia de áudio** | **híbrido**: manifesto de **falas-marca** gravadas (OGG) + **Web Speech** (primário no texto dinâmico) — cascata em §10 (clipe → voz local → fallback visual); **sem voz de rede**; **offline** só com voz/clipe **local** (N17) | 15 ⚠️ (§15/15.27); norma = [13](13-acessibilidade.md) |
| A7 | **SFX** | curtos, suaves, WebAudio; **erro nunca é buzina** de reprovação (P6) | 15 |
| A8 | **Música ambiente** | opcional por mundo; a preferência `musica` está **órfã hoje** (sem player/UI); **a cabear se a música existir** (fiação/"manter no modelo" = ADR-13-C) | 15 ⚠️ (existência do conteúdo — §15) |
| A9 | **Tipografia** | Baloo 2 (display) + Nunito (corpo), auto-hospedadas; a 15 **cria o token** de tamanho ajustável | 15 (token/execução); **valor/norma N11 = [13](13-acessibilidade.md)** |
| A10 | **Espaçamento entre alvos** | a 15 **implementa** o token `--espaco-alvo` | 15 (token/execução); **valor/norma N1 = [13](13-acessibilidade.md)** |
| A11 | **Estratégia de asset** | **procedural** (Q0) = piso de desempenho, degradação **e fallback offline**; **GLB/GLTF autoral** = barra-alvo **decidida pela [04](04-personagens-avatar.md)** — a 15 é dona da **produção** (não de *se* migra) | 15 ⚠️ (produção/verba — §15) |
| A12 | **Formatos & compressão** | **glTF 2.0** + **Draco** (geometria) + **KTX2/Basis** (textura); atlas de sprites; áudio **OGG** | 15 |
| A13 | **Orçamento** | **avatar = contrato da [04](04-personagens-avatar.md) §10g** (≤ 12.000 tris, ≤ 28 ossos, atlas ≤ 1024², 1 LOD, GLB base ≤ 2 MB — revisto só se a [11](11-arquitetura.md) mudar o device); a 15 decide **compressão**, **FPS-alvo** e o orçamento dos **assets não-avatar** | 15 ⚠️ (compressão/FPS/não-avatar — §15); avatar = [04](04-personagens-avatar.md); device = [11](11-arquitetura.md) |
| A14 | **Acervo público** | asset público **sem token, nunca gabarito** nem dado de aluno (Seção [12](12-seguranca-privacidade.md)); versionado, entregue pela Seção [14](14-infra-deploy-dr.md) | 15 respeita 12; entrega = 14 |
| A15 | **Fidelidade à Bíblia Sensorial** | silhueta/escala **travadas por espécie**; modos de comunicação diversos; ouro de Terra Nova **metálico-frio** × âmbar quente do Chronos | 15 executa; direção = [03](03-universo.md) |
| A16 | **Raízes/ERER** | arte + áudio + ficha **só por curadoria humana especializada** (Q5); **sem autoria por IA**; nenhum asset gerado por agentes (ex.: `erer` de `cenasTema.ts`/`materias.ts`) sobrevive — é **descartado e re-autorado** | 15 + [03](03-universo.md)/`biblia-sensorial/09-raizes.md` |

### 10. Arquitetura técnica
Onde a arte/áudio **tocam** o código (o **mecanismo** de render é da Seção [11](11-arquitetura.md); contratos de
asset → Apêndice B):
- **Paleta** — `tokens.css` (variáveis CSS, tema por `[data-theme]`) é a fonte única; a auditoria de contraste
  (A3) **mede** as combinações reais enumeradas e **ajusta** as que reprovarem; `materias.ts` passa a
  **referenciar** os tokens.
- **Áudio (cascata de seleção)** — `audio.ts` mantém os SFX WebAudio; a **narração** ganha um **manifesto de
  clipes** (chave→OGG) para as **falas-marca** (conjunto canônico fixo do Cosmo; o **texto** segue o guia da
  [02](02-vocabulario.md)/`00-cosmo`). Em runtime: (1) existe clipe para a chave → **toca o clipe gravado**; (2)
  senão (texto dinâmico) → **Web Speech** com voz pt-BR **local** (mecanismo **primário** aí); (3) sem voz local
  ou clipe indisponível → **fallback visual** (N17). **Nunca** voz de rede (privacidade — [12](12-seguranca-privacidade.md)).
  A estratégia definitiva substitui a nota "OGG na Q1".
- **Personagem/itens** — o **rig canônico único**, o **orçamento** (04 §10g) e o **contrato de manifesto**
  (tipo/`assetUrl`/socket/zona de cor) são da Seção [04](04-personagens-avatar.md); a 15 produz os **GLB** que
  preenchem esse contrato, mantendo o **procedural** como piso de degradação e fallback offline.
- **Ambiente/mundos** — SVG/CSS (11); `cenasTema.ts` deixa de ser andaime e vira **candidato a canônico após
  revisão humana** — **exceto** a entrada `erer` (Raízes/ERER), que **não** segue esse caminho: é **descartada e
  re-autorada** por curadoria humana especializada (A16/Q5), nunca apenas revisada.
- **Pipeline** — build de assets fora do bundle da app (export → Draco/KTX2 → versionamento) para o acervo que a
  Seção [14](14-infra-deploy-dr.md) entrega por CDN; o **GLB base é pré-cacheado** (offline-first); nada de
  gabarito no acervo público (12).

### 11. Dependências com outros módulos
**Consome / executa:**
- **Seção [03](03-universo.md)** + `biblia-sensorial/` — a **direção sensorial** (paleta/sons/música/efeitos/falas
  por mundo, 35 campos; persona e **voz-tom** do Cosmo). A 15 **executa**, não redefine.
- **Seção [04](04-personagens-avatar.md)** — os **slots**, o **rig**, o **orçamento** do avatar e o **contrato de
  manifesto** de assets; a 15 produz a **arte** que os preenche.
- **Seção [11](11-arquitetura.md)** — o **mecanismo** de render híbrido, o **device-alvo** (11.48) e a **degradação**.
- **Seção [13](13-acessibilidade.md)** — a **norma** (contraste, daltônico, **fonte N11 e espaçamento N1**, áudio
  pt-BR, reduced-motion); a 13 deferiu à 15 os **valores** de **paleta/contraste** (13.6), o **método/paletas do
  daltônico** (N6) e a **estratégia de áudio** (13.27) — **não** os valores de fonte/espaçamento (esses são da 13).
- **Seção [02](02-vocabulario.md)** — o **guia de voz/tom** do Cosmo (a 15 dá a **voz gravada**, não o tom).

**Alimenta:**
- **Seção [14](14-infra-deploy-dr.md)** — o **acervo versionado** que a 14 entrega por CDN.
- **Seção [07](07-ux-fluxos-navegacao.md)** — o **look-and-feel** e o kit de estados que vestem as telas.
- **Seção [13](13-acessibilidade.md)** — fecha os valores das ⚠️ que a 13 deixou à 15 (**paleta, daltônico, áudio**).

**O que quebra se mudar:** se a Seção [11](11-arquitetura.md) mudar o device-alvo, a 15 **recalibra** compressão/FPS
e a 04 revisa o orçamento; se a Seção [04](04-personagens-avatar.md) mudar o contrato de manifesto/rig, a 15
**re-exporta** os GLB; se a Seção [13](13-acessibilidade.md) mudar o limiar de contraste, a 15 **re-audita** a paleta.

### 12. Casos extremos (Edge Cases)
- **Áudio não pode tocar** (mudo/autoplay bloqueado/**sem voz pt-BR local**) → **clipe gravado** (se houver) ou
  **fallback visual** sincronizado (N17 da 13); **nunca** voz de rede. A arte guia sem som.
- **GLB não está em cache / primeira sessão offline** → **procedural** como fallback garantido (não só p/
  hardware fraco); o GLB base é **pré-cacheado** para o caso online (P17 offline-first).
- **Hardware fraco** → **procedural** + materiais simples + menos partículas; GLB com **LOD** baixo (contrato 04);
  feedback essencial mantido.
- **`prefers-reduced-motion`** → versões **estáticas** de invocação/partículas/parallax (13).
- **Daltonismo** → redundância sempre ativa + paletas seguras + padrões (A5).
- **Contraste reprovado numa cor atual** → a auditoria A3 **ajusta o token** antes de publicar; nenhuma cor "no
  olho" passa no gate.
- **Asset pesado demais** → **rejeitado** no pipeline pelo orçamento (A13/04); nunca vai a produção sem caber no device.
- **Mundo Raízes/ERER** → nenhuma arte/áudio gerada por IA; qualquer asset de agente (ex.: `erer` de `cenasTema.ts`)
  é **descartado**; só entra por **curadoria humana especializada** (A16/Q5).
- **Cosmo × avatar** (identidade) → o **avatar** é o personagem do jogador (Seção [04](04-personagens-avatar.md));
  o **Cosmo** é o **companheiro/voz** (`biblia-sensorial/00-cosmo.md`) — a 15 não funde os dois.

### 13. Escalabilidade futura
- **Migração procedural → GLB** (decidida pela [04](04-personagens-avatar.md)) por lotes — **gatilho de promoção**:
  personagem/mundo autoral **E** que cabe no orçamento (A13) **E** com verba aprovada (§15.38); o Cosmo, as
  partículas e o brilho **permanecem procedurais** (piso). Ordem proposta: os 6 personagens-base primeiro (maior
  presença em tela), sem quebrar o piso procedural.
- **Novas vozes/idiomas** — a camada de clipes se estende via localização (Seção [16](16-localizacao-i18n.md));
  o áudio obrigatório pt-BR permanece o padrão (P9).
- **Subsets de fonte por script** — quando a Seção [16](16-localizacao-i18n.md) aprovar um novo idioma, o pipeline
  de assets (A12) passa a incluir o **subset de fonte** do script (latin-ext / não-latino / RTL) e o **precache por
  locale**, dentro do orçamento de peso (A13).
- **Trilha musical** por mundo (opcional) e SFX mais ricos, dentro do orçamento.
- **Modo daltônico** ampliado (mais paletas/padrões); **alto contraste**; fonte para dislexia (novos tokens).
- **Pipeline automatizado** — validação de peso/formato/contraste no CI (Seção [18](18-qa-testes.md)).

### 14. Checklist de implementação
**"Pronto quando" (liga ao Apêndice F):**
- [ ] **Paleta auditada** — inventário enumerado de `tokens.css` (claro/escuro) + derivações de `materias.ts`
  **medido** ≥ 4.5:1 / 3:1 (A3); tokens reprovados **ajustados**; `tokens.css` é a fonte única.
- [ ] **Cor com redundância** (A4); **método daltônico** ratificado (A5/§15) e paletas definidas.
- [ ] **Tokens** de **tamanho de fonte** e **espaçamento de alvo** criados (A9/A10) — **valores conforme a Seção [13](13-acessibilidade.md)**.
- [ ] **Estratégia de áudio** implementada (A6): manifesto de clipes + Web Speech (voz local) + fallback visual; **offline** pt-BR; **sem voz de rede**.
- [ ] **SFX** revisados (A7 — sem buzina de erro); **música**: SE aprovada → toggle `musica` cabeado a asset/player; SENÃO → campo mantido (ADR-13-C) e divergência encaminhada à Seção [13](13-acessibilidade.md).
- [ ] **Pipeline de asset** (A12): glTF 2.0 + Draco + KTX2; atlas; áudio OGG; validação de **orçamento** (A13).
- [ ] **Avatar dentro do contrato da [04](04-personagens-avatar.md)** (≤12k tris/≤28 ossos/atlas ≤1024²/1 LOD/GLB ≤2 MB); **compressão/FPS** validados no **device-alvo** (11.48).
- [ ] **GLB base pré-cacheado** e **fallback procedural garantido** (offline-first — P17).
- [ ] **Acervo público** sem gabarito/dado de aluno (A14); versionado e pronto p/ CDN (Seção [14](14-infra-deploy-dr.md)).
- [ ] **Barra de qualidade (A1)**: coesão visual entre mundos revisada por amostra contra a rubrica (paleta/brilho/raio/partícula).
- [ ] **Fidelidade à Bíblia Sensorial (A15)** conferida antes de publicar: silhueta/escala por espécie, cor-chave por mundo e modos de comunicação — contra `biblia-sensorial/`.
- [ ] **Raízes/ERER**: **nenhum asset gerado por agentes** sobrevive (o `erer` de `cenasTema.ts`/`materias.ts` é re-autorado por curadoria humana — A16).
- [ ] **Canon vs andaime** decidido por asset (preservar se passa A1/A3 e a Bíblia Sensorial ratifica; senão refazer).

### 15. Questões em aberto
Cada item é **decisão do dono** (⚠️); os defaults são **propostas** da 15, não decisões autônomas:

- ⚠️ **15.27 — Estratégia de áudio (A6).** Proposta: **híbrido** (falas-marca gravadas em OGG + Web Speech de voz
  **local** para texto dinâmico), preservando o requisito da 13 (offline pt-BR + "ouvir de novo" + fallback
  visual; **sem voz de rede**). Alternativas: manter 100% sintetizado ou 100% gravado. Definir a **voz gravada
  (casting/timbre)** que **executa** o guia de tom da Seção [02](02-vocabulario.md)/`00-cosmo` — não o "tom" em si.
- ⚠️ **15.38 — Produção de assets.** Quem produz os **GLB** (personagem/itens), as **narrações gravadas** e a
  **música** — fornecedor × agentes de IA × misto — e sob qual **verba/prazo**. Quem faz a **curadoria** de
  consistência. *(A migração para GLB já é decidida pela [04](04-personagens-avatar.md); aqui é só a produção.)*
- ⚠️ **A11 — Quais procedurais permanecem.** Confirmar o que fica **procedural** como piso (Cosmo, partículas,
  brilho) e o que vira GLB autoral — sem reabrir *se* migra (decisão da [04](04-personagens-avatar.md)).
- ⚠️ **15.35 / A13 — Orçamento fino (não-avatar).** **Compressão** (parâmetros Draco/KTX2), **FPS-alvo** e o
  orçamento dos **assets não-avatar** (itens especiais, pets, props de mundo) — co-calibrados com o device-alvo
  (11.48). *(O orçamento do **avatar** — 12k tris/28 ossos/1024²/1 LOD/≤2 MB — é da [04](04-personagens-avatar.md);
  o **ladder de degradação** é 13.29 da [13](13-acessibilidade.md)/mecanismo da [11](11-arquitetura.md).)*
- ⚠️ **A5 / N6 — Modo daltônico.** Confirmar os **tipos** (deuteranopia/protanopia/tritanopia) e o **método**
  (troca de paleta × padrões/texturas × ambos — proposta: **ambos**) — a 13 fixou a existência e deferiu os
  valores à 15.
- ⚠️ **A8 — Música.** O Quest terá **trilha/ambiente** por mundo? Se sim, a preferência `musica` ganha
  asset/player (fiação = ADR-13-C); se **não**, o campo **permanece** no modelo (ADR-13-C decidiu **manter**) e a
  divergência (toggle sem função) é **encaminhada à Seção [13](13-acessibilidade.md)** para revisão do ADR-13-C —
  **a 15 não remove** o campo.
- ⚠️ **Canon vs andaime.** Quais valores de `materias.ts`, `cenasTema.ts` (cenas geradas por agentes), `Cosmo.tsx`
  e `tokens.css` **preservar como direção canônica** (se passam A1/A3 e a Bíblia Sensorial ratifica) vs. **refazer**
  — **exceto** o `erer`, sempre re-autorado (A16). A 03 marca isso como entregável da 15.
- **Nota de fronteira (não é decisão da 15):** as ⚠️ **15.9** (design do avatar humanoide), **15.11** (papel do
  avatar 3D × Cosmo 2D) e **15.12** (estratégia de render 2D × 3D / Three.js oficial) já são **decididas** pelas
  Seções [04](04-personagens-avatar.md) e [11](11-arquitetura.md); a contradição histórica do `docs/quest/01`
  ("DOM/SVG-first, PixiJS não Three.js") é **legado** — a 15 segue 04/11.

### 16. ADR (Architecture Decision Record)
- **ADR-15-A — `tokens.css` é a fonte única da cor.** Toda cor de UI deriva de `tokens.css`; `materias.ts`/`cenasTema.ts`
  referenciam; a paleta é **auditada por contraste medido** (4.5:1/3:1 — limiar da Seção [13](13-acessibilidade.md));
  tokens reprovados são ajustados antes de publicar.
- **ADR-15-B — Áudio híbrido com cascata (proposto).** Narração = **falas-marca gravadas (OGG)** → **Web Speech**
  (voz **local**, primário no texto dinâmico) → **fallback visual** (13); **nunca** voz de rede (P18/[12](12-seguranca-privacidade.md));
  offline garantido só com voz/clipe local. SFX seguem WebAudio, sem buzina de erro. *Pendente de ratificação (§15/15.27).*
- **ADR-15-C — Procedural é o piso; GLB é a barra-alvo decidida pela 04.** O 3D procedural (Q0) é o **piso de
  desempenho, degradação e fallback offline**; a migração para **GLB/GLTF autoral** (pipeline glTF 2.0 + Draco +
  KTX2, dentro do orçamento da [04](04-personagens-avatar.md) §10g) é decisão da **Seção [04](04-personagens-avatar.md)** —
  a 15 é dona da **produção** e da compressão/FPS. *Produção/verba pendentes (§15/15.38).*
- **ADR-15-D — A 15 executa a Bíblia Sensorial; Raízes/ERER só por curadoria humana.** A direção sensorial dos 9
  mundos + Cosmo é da Seção [03](03-universo.md)/`biblia-sensorial/`; a 15 dá a execução. O mundo **Raízes/ERER**
  não tem arte/áudio/ficha gerada por IA — **só curadoria humana especializada (Q5)**; qualquer asset de agente
  (ex.: `erer`) é **descartado e re-autorado**, nunca apenas revisado.

*Decisões cross-módulo não são improvisadas aqui: as pendências acima viram ADR ou item de §15.*

---

## 🇬🇧 Art Direction, Audio & Asset Pipeline

### 1. Objective
To be the **definitive reference for art direction, audio and asset production** in Constela Quest: the **quality
bar** that makes the game look and sound like a **modern game** — charming, cohesive and polished — **without
blowing up** the school tablet. It lets us produce art and sound **without re-deciding the style** on every
screen and **without improvising format/weight**. It decides the **execution** (visual/audio bar, palette, audio
strategy, pipeline); it does **not** decide the **narrative** (Section [03](03-universo.md)), the avatar
**rules/budget** (Section [04](04-personagens-avatar.md)), the render **mechanism** (Section [11](11-arquitetura.md)),
the accessibility **norm** (Section [13](13-acessibilidade.md)), nor the CDN **delivery** (Section [14](14-infra-deploy-dr.md)).

### 2. Context
In the **Hub → Edu → Quest** ecosystem, art is what the child **sees and hears first** — and the non-reading
audience depends on **sound** and **color** to navigate. **Current state (Q0) — everything code-generated, almost
no binary asset:**
- **Character & items** — 3D avatar **100% procedural** in React Three Fiber (`Personagem.tsx`: Three.js
  primitives, `useFrame` animation, no skeleton/clip); special items (`Itens3D.tsx`) with emissive glow +
  `pointLight`. **No** `.glb`/`.gltf`, textures/PBR, custom shaders, nor GPU particles.
- **Environment & worlds** — **SVG/CSS**, not 3D: CSS-gradient sky, SVG constellations, `Planeta.tsx` SVG, DOM
  `<span>` particles, `cenasTema.ts` = per-subject *line-art* scenes (**AI-agent-generated**, reviewed) —
  **including an `erer` key** (Raízes/ERER world art authored by AI).
- **Cosmo (mascot)** — **procedural SVG** with JS spring physics (companion; the persona/voice lives in
  `biblia-sensorial/00-cosmo.md`).
- **Audio** — **100% synthesized**: SFX via WebAudio (oscillators; "error is never a buzzer") + narration via the
  **Web Speech API** pt-BR, with a fallback to text **in the bubble**. Voice selection prefers the **local** one
  but **falls back to a network voice** if the device has no local pt-BR. **No** audio file in the repo; `audio.ts`
  notes "recorded audio (OGG) comes in Q1". The `musica` preference is **orphaned** (a field in `quest-core`,
  **no player, no UI toggle, not consumed** by `configurarAudio`).
- **Palette & typography** — `tokens.css` is the real palette (ink `#231D4E`, sun `#FFC93C`, coral `#FF5470`,
  violet `#7C6FF0`, green `#3ED66E`…; light/dark theme); per-world palettes in `materias.ts`. **Baloo 2** +
  **Nunito** self-hosted fonts (`@fontsource`, woff2 — the only binary assets besides PWA icons). **No** audited
  contrast *ratio*, colorblind palette, nor font-size token (gaps Section 13 flags).
- **Catalog/pipeline** — nonexistent: `public/` only has favicon + PWA icons; nothing delivered by CDN; no GLB
  export, texture compression, atlas, nor 3D build.

This chapter **fixes** the quality bar, **audits** the palette against Section 13's norm, **unifies** the audio
strategy and **specifies** the target pipeline.

### 3. Feature philosophy
**"Recognizable in 1 second, charming forever."** Constela's art has a **DNA** (`biblia-sensorial/`): friendly
rounded shapes, vivid but **legible** color, glow that celebrates without tiring. **Accessibility is part of the
style, not a brake:** the palette is beautiful **because** it has contrast; the sound guides **because** it is
clear. The production principle: **procedural first, asset when the promotion trigger justifies it** (§9/A11; trigger in §13) —
what code renders well (Cosmo, particles, glow) stays as the floor; what Section [04](04-personagens-avatar.md)
decided to author (character, items) rises to GLB **without losing the performance and offline floor** (P17).

Link to the **Immutable Principles** ([01](01-principios-imutaveis.md)): **P9** (always pt-BR audio) makes
**Cosmo's voice** the central instrument; **P11** (accessibility) mandates a palette with contrast + colorblind
mode + guiding audio; **P17** (performance floor/offline-first) is the **weight budget** and **pre-cache** that
discipline every asset; **P18** (no tracking) keeps the client **without a third-party tracking SDK** — and audio
never sends a child's text to a **network voice** (§9/A6). To the **4 pillars**: **surprise** (the glow, the
invocation), **autonomy** (color+sound guide the non-reader), **visible progress** (the growing constellation),
**connection** (a world the child recognizes as theirs).

### 4. The experience the player should feel
**"How beautiful — and it's mine."** The child feels a **lively, careful** world: Cosmo breathes and reacts to
touch, the planet pulses, the special item **invokes** with a scene that draws a "wow". The **voice** is warm,
clear and always in Portuguese — never so robotic that it scares. Color is **cheerful and legible** (nothing
"washes out the eyes"). The **correct-answer** sound is a pleasant spark; the **error** one, a gentle "almost!" —
**never** a failing buzzer (P6). In the end, the feeling is of a **cared-for** product, up to the games the child loves.

### 5. Complete flow
How art and audio **run through** the experience (the screen inventory is Section [07](07-ux-fluxos-navegacao.md)'s):

1. **Entry** — themed sky, Cosmo welcoming with a pt-BR **voice**; soft focus/tap SFX.
2. **Ceremony (first time)** — vivid outfit palette; the character gains **color** with glow; narration guides each step.
3. **Lobby / worlds** — each subject has its **palette and scene** (`materias.ts`/`cenasTema.ts`); light particles;
   **optional** ambient music (⚠️ §15).
4. **Activity** — multisensory feedback (color + icon + **sound**); **spoken** instruction (mandatory audio — 13).
5. **Special item / reward** — cinematic **invocation** (with a static version under reduced-motion — 13).
6. **Offline / first session** — narration plays **locally** (local pt-BR voice or pre-cached recorded clip); the
   **base GLB** is **pre-cached**, and **procedural** is the guaranteed fallback if the GLB is not cached (P17).
7. **Sound fallback** — when audio cannot play (muted, no local voice, clip unavailable), the **visual
   equivalent** guides (Section 13's N17); the art never depends on sound alone and **never** falls back to a
   network voice.
8. **Weak-hardware degradation** — fewer particles, simpler materials, **procedural** as the floor; essential
   feedback remains (mechanism = Section [11](11-arquitetura.md); norm = Section [13](13-acessibilidade.md)).

### 6. Interface (when it exists)
Section 15 **does not draw screens** (inventory = Section [07](07-ux-fluxos-navegacao.md)). It owns the
**look-and-feel** that dresses the whole UI: the **design system** (`tokens.css`/`base.css` — 3D buttons, chips,
panels, toasts, visible focus), the **typography** (Baloo 2 display + Nunito body), and the **UI-state kit**
(empty, loading, error, offline) with each state's **visual + sound** pair. The **position** of the preference
surfaces (colorblind mode, font size, music) is Section [07](07-ux-fluxos-navegacao.md)'s; 15 provides the
**visual/audio content**.

### 7. UX
Section 15 gives the **sensory polish**, always subordinate to Section [13](13-acessibilidade.md)'s norm:
- **Legible color** — every text/UI color meets the contrast **required by 13** (4.5:1 text / 3:1 large text and
  UI); color is **never the only channel** (shape/icon/label/audio accompany it).
- **Sound that guides, not pollutes** — short, soft SFX; warm narration; a volume that does not scare; "hear it
  again" always available (surface = 13/07).
- **Motion with purpose** — glow and life celebrate; under `prefers-reduced-motion` the art has a **static version**.
- **Beginner-reader-friendly typography** — generous body, high contrast, **adjustable** size (15's token; 13's
  value — §9).
- **Cosmo's voice** — always within Section [02](02-vocabulario.md)'s ✓/✗ guide (no school/system jargon).

### 8. Game Design
**N/A as a mechanic** — 15 creates no game rule; it **dresses** the mechanics of Sections [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md).
Boundary note: the **skins** of the racing/activity engine are **15's art**, but the **engine** and the **values**
(XP, cap, pause) are 05/11/19's — 15 only gives the visual/audio dress, never the number.

### 9. Business rules
The **art/audio/pipeline norms** (the single source of execution; the accessibility **norm** is Section
[13](13-acessibilidade.md)'s, the **narrative** Section [03](03-universo.md)'s, the **avatar budget** Section [04](04-personagens-avatar.md)'s):

| # | Norm | Rule | Boundary |
|---|------|------|----------|
| A1 | **Quality bar** | "modern-game" polish, **verifiable by proxies**: a palette that passes A3 + **cross-world cohesion** (same type family, same glow/shadow language, same corner radius, same particle scale) + a named reference bar (§15) | 15 |
| A2 | **Palette — single source** | `tokens.css` is the **single source of truth** for UI color; `materias.ts`/`cenasTema.ts` **derive** from it | 15 (converges 3 sources) |
| A3 | **Contrast (values)** | the real colors **must** meet **4.5:1** (text) / **3:1** (large text and UI), **audited by measurement** (WCAG ratio, via a tool) over the enumerated inventory of `tokens.css` (light/dark) + `materias.ts` derivations; tokens that **fail are adjusted before publishing** | 15 (value); threshold + "large text" def. = [13](13-acessibilidade.md) |
| A4 | **Color never the sole channel** | every color that **encodes state** has redundancy (shape/icon/label/audio) | 15 applies; norm = [13](13-acessibilidade.md) |
| A5 | **Colorblind mode (palettes)** | redundancy always on; safe palettes and/or **patterns/textures** where color encodes state; cover deuteranopia/protanopia/tritanopia | 15 ⚠️ (method/types — §15); existence = [13](13-acessibilidade.md) |
| A6 | **Audio strategy** | **hybrid**: a manifest of recorded **brand phrases** (OGG) + **Web Speech** (primary for dynamic text) — cascade in §10 (clip → local voice → visual fallback); **no network voice**; **offline** only with a **local** voice/clip (N17) | 15 ⚠️ (§15/15.27); norm = [13](13-acessibilidade.md) |
| A7 | **SFX** | short, soft, WebAudio; **error is never a failing buzzer** (P6) | 15 |
| A8 | **Ambient music** | optional per world; the `musica` preference is **orphaned today** (no player/UI); **to be wired if music exists** (wiring/"keep in model" = ADR-13-C) | 15 ⚠️ (content existence — §15) |
| A9 | **Typography** | Baloo 2 (display) + Nunito (body), self-hosted; 15 **creates the token** for adjustable size | 15 (token/execution); **value/norm N11 = [13](13-acessibilidade.md)** |
| A10 | **Target spacing** | 15 **implements** the `--espaco-alvo` token | 15 (token/execution); **value/norm N1 = [13](13-acessibilidade.md)** |
| A11 | **Asset strategy** | **procedural** (Q0) = performance floor, degradation **and offline fallback**; **authored GLB/GLTF** = target bar **decided by [04](04-personagens-avatar.md)** — 15 owns the **production** (not *whether* it migrates) | 15 ⚠️ (production/budget — §15) |
| A12 | **Formats & compression** | **glTF 2.0** + **Draco** (geometry) + **KTX2/Basis** (texture); sprite atlas; audio **OGG** | 15 |
| A13 | **Budget** | **avatar = [04](04-personagens-avatar.md) §10g contract** (≤ 12,000 tris, ≤ 28 bones, atlas ≤ 1024², 1 LOD, base GLB ≤ 2 MB — revised only if [11](11-arquitetura.md) changes the device); 15 decides **compression**, **target FPS** and the **non-avatar** asset budget | 15 ⚠️ (compression/FPS/non-avatar — §15); avatar = [04](04-personagens-avatar.md); device = [11](11-arquitetura.md) |
| A14 | **Public catalog** | public asset **without token, never the answer key** nor student data (Section [12](12-seguranca-privacidade.md)); versioned, delivered by Section [14](14-infra-deploy-dr.md) | 15 respects 12; delivery = 14 |
| A15 | **Fidelity to the Sensory Bible** | silhouette/scale **locked per species**; diverse communication modes; Terra Nova gold **metallic-cold** × Chronos warm amber | 15 executes; direction = [03](03-universo.md) |
| A16 | **Raízes/ERER** | art + audio + sheet **only by specialized human curation** (Q5); **no AI authorship**; no agent-generated asset (e.g. `cenasTema.ts`/`materias.ts` `erer`) survives — it is **discarded and re-authored** | 15 + [03](03-universo.md)/`biblia-sensorial/09-raizes.md` |

### 10. Technical architecture
Where art/audio **touch** code (the render **mechanism** is Section [11](11-arquitetura.md)'s; asset contracts →
Appendix B):
- **Palette** — `tokens.css` (CSS variables, theme via `[data-theme]`) is the single source; the contrast audit
  (A3) **measures** the enumerated real combinations and **adjusts** those that fail; `materias.ts` now
  **references** the tokens.
- **Audio (selection cascade)** — `audio.ts` keeps the WebAudio SFX; **narration** gains a **clip manifest**
  (key→OGG) for the **brand phrases** (Cosmo's fixed canonical set; the **text** follows Section [02](02-vocabulario.md)/`00-cosmo`).
  At runtime: (1) a clip exists for the key → **play the recorded clip**; (2) else (dynamic text) → **Web Speech**
  with a **local** pt-BR voice (the **primary** mechanism there); (3) no local voice or clip unavailable →
  **visual fallback** (N17). **Never** a network voice (privacy — [12](12-seguranca-privacidade.md)). The
  definitive strategy replaces the "OGG in Q1" note.
- **Character/items** — the **single canonical rig**, the **budget** (04 §10g) and the **manifest contract**
  (type/`assetUrl`/socket/color zone) are Section [04](04-personagens-avatar.md)'s; 15 produces the **GLB** that
  fill that contract, keeping the **procedural** as the degradation floor and offline fallback.
- **Environment/worlds** — SVG/CSS (11); `cenasTema.ts` stops being scaffold and becomes a **canonical candidate
  after human review** — **except** the `erer` entry (Raízes/ERER), which does **not** follow that path: it is
  **discarded and re-authored** by specialized human curation (A16/Q5), never merely reviewed.
- **Pipeline** — an asset build outside the app bundle (export → Draco/KTX2 → versioning) for the catalog that
  Section [14](14-infra-deploy-dr.md) delivers via CDN; the **base GLB is pre-cached** (offline-first); no answer
  key in the public catalog (12).

### 11. Dependencies on other modules
**Consumes / executes:**
- **Section [03](03-universo.md)** + `biblia-sensorial/` — the **sensory direction** (palette/sounds/music/effects/lines
  per world, 35 fields; Cosmo's persona and **voice-tone**). 15 **executes**, does not redefine.
- **Section [04](04-personagens-avatar.md)** — the **slots**, the **rig**, the avatar **budget** and the asset
  **manifest contract**; 15 produces the **art** that fills them.
- **Section [11](11-arquitetura.md)** — the hybrid render **mechanism**, the **target device** (11.48) and the **degradation**.
- **Section [13](13-acessibilidade.md)** — the **norm** (contrast, colorblind, **font N11 and spacing N1**, pt-BR
  audio, reduced-motion); 13 deferred to 15 the **values** of **palette/contrast** (13.6), the **colorblind
  method/palettes** (N6) and the **audio strategy** (13.27) — **not** the font/spacing values (those are 13's).
- **Section [02](02-vocabulario.md)** — Cosmo's **voice/tone guide** (15 gives the **recorded voice**, not the tone).

**Feeds:**
- **Section [14](14-infra-deploy-dr.md)** — the **versioned catalog** it delivers via CDN.
- **Section [07](07-ux-fluxos-navegacao.md)** — the **look-and-feel** and state kit that dress the screens.
- **Section [13](13-acessibilidade.md)** — closes the values the 13 deferred to 15 (**palette, colorblind, audio**).

**What breaks if it changes:** if Section [11](11-arquitetura.md) changes the target device, 15 **recalibrates**
compression/FPS and 04 revises the budget; if Section [04](04-personagens-avatar.md) changes the manifest
contract/rig, 15 **re-exports** the GLB; if Section [13](13-acessibilidade.md) changes the contrast threshold, 15
**re-audits** the palette.

### 12. Edge cases
- **Audio cannot play** (muted/autoplay blocked/**no local pt-BR voice**) → **recorded clip** (if any) or
  synchronized **visual fallback** (Section 13's N17); **never** a network voice. The art guides without sound.
- **GLB not cached / first offline session** → **procedural** as the guaranteed fallback (not only for weak
  hardware); the base GLB is **pre-cached** for the online case (P17 offline-first).
- **Weak hardware** → **procedural** + simple materials + fewer particles; GLB at low **LOD** (04 contract);
  essential feedback kept.
- **`prefers-reduced-motion`** → **static** versions of invocation/particles/parallax (13).
- **Colorblindness** → redundancy always on + safe palettes + patterns (A5).
- **A current color fails contrast** → the A3 audit **adjusts the token** before publishing; no "by eye" color passes the gate.
- **Asset too heavy** → **rejected** by the pipeline budget (A13/04); never ships without fitting the device.
- **Raízes/ERER world** → no AI-generated art/audio; any agent asset (e.g. `cenasTema.ts` `erer`) is
  **discarded**; it enters only by **specialized human curation** (A16/Q5).
- **Cosmo × avatar** (identity) → the **avatar** is the player's character (Section [04](04-personagens-avatar.md));
  **Cosmo** is the **companion/voice** (`biblia-sensorial/00-cosmo.md`) — 15 does not merge the two.

### 13. Future scalability
- **Procedural → GLB migration** (decided by [04](04-personagens-avatar.md)) in batches — **promotion trigger**:
  an authored character/world **AND** fitting the budget (A13) **AND** with approved funding (§15.38); Cosmo,
  particles and glow **stay procedural** (the floor). Proposed order: the 6 base characters first (most on-screen
  presence), without breaking the procedural floor.
- **New voices/languages** — the clip layer extends via localization (Section [16](16-localizacao-i18n.md)); the
  mandatory pt-BR audio stays the default (P9).
- **Per-script font subsets** — when Section [16](16-localizacao-i18n.md) approves a new language, the asset
  pipeline (A12) starts including the script's **font subset** (latin-ext / non-latin / RTL) and the **per-locale
  pre-cache**, within the weight budget (A13).
- **Musical score** per world (optional) and richer SFX, within budget.
- **Colorblind mode** expanded (more palettes/patterns); **high contrast**; dyslexia font (new tokens).
- **Automated pipeline** — weight/format/contrast validation in CI (Section [18](18-qa-testes.md)).

### 14. Implementation checklist
**"Done when" (links to Appendix F):**
- [ ] **Palette audited** — enumerated inventory of `tokens.css` (light/dark) + `materias.ts` derivations
  **measured** ≥ 4.5:1 / 3:1 (A3); failed tokens **adjusted**; `tokens.css` is the single source.
- [ ] **Color with redundancy** (A4); **colorblind method** ratified (A5/§15) and palettes defined.
- [ ] **Tokens** for **font size** and **target spacing** created (A9/A10) — **values per Section [13](13-acessibilidade.md)**.
- [ ] **Audio strategy** implemented (A6): clip manifest + Web Speech (local voice) + visual fallback; **offline** pt-BR; **no network voice**.
- [ ] **SFX** reviewed (A7 — no error buzzer); **music**: IF approved → `musica` toggle wired to asset/player; ELSE → field kept (ADR-13-C) and divergence routed to Section [13](13-acessibilidade.md).
- [ ] **Asset pipeline** (A12): glTF 2.0 + Draco + KTX2; atlas; OGG audio; **budget** validation (A13).
- [ ] **Avatar within the [04](04-personagens-avatar.md) contract** (≤12k tris/≤28 bones/atlas ≤1024²/1 LOD/GLB ≤2 MB); **compression/FPS** validated on the **target device** (11.48).
- [ ] **Base GLB pre-cached** and **procedural fallback guaranteed** (offline-first — P17).
- [ ] **Public catalog** without answer key/student data (A14); versioned and CDN-ready (Section [14](14-infra-deploy-dr.md)).
- [ ] **Quality bar (A1)**: cross-world visual cohesion reviewed on a sample against the rubric (palette/glow/radius/particle).
- [ ] **Sensory Bible fidelity (A15)** checked before publishing: silhouette/scale per species, key color per world and communication modes — against `biblia-sensorial/`.
- [ ] **Raízes/ERER**: **no agent-generated asset** survives (the `cenasTema.ts`/`materias.ts` `erer` is re-authored by human curation — A16).
- [ ] **Canon vs scaffold** decided per asset (preserve if it passes A1/A3 and the Sensory Bible ratifies; else redo).

### 15. Open questions
Each item is a **owner decision** (⚠️); the defaults are 15's **proposals**, not autonomous decisions:

- ⚠️ **15.27 — Audio strategy (A6).** Proposal: **hybrid** (recorded brand phrases in OGG + **local**-voice Web
  Speech for dynamic text), preserving Section 13's requirement (offline pt-BR + "hear it again" + visual
  fallback; **no network voice**). Alternatives: keep 100% synthesized or 100% recorded. Define the **recorded
  voice (casting/timbre)** that **executes** Section [02](02-vocabulario.md)/`00-cosmo`'s tone guide — not the "tone" itself.
- ⚠️ **15.38 — Asset production.** Who produces the **GLB** (character/items), the **recorded narrations** and the
  **music** — vendor × AI agents × mixed — and under what **budget/timeline**. Who does the consistency
  **curation**. *(The migration to GLB is already decided by [04](04-personagens-avatar.md); here it's only production.)*
- ⚠️ **A11 — Which procedurals stay.** Confirm what stays **procedural** as the floor (Cosmo, particles, glow) and
  what becomes authored GLB — without reopening *whether* it migrates (Section [04](04-personagens-avatar.md)'s decision).
- ⚠️ **15.35 / A13 — Fine budget (non-avatar).** **Compression** (Draco/KTX2 params), **target FPS** and the
  **non-avatar** asset budget (special items, pets, world props) — co-calibrated to the target device (11.48).
  *(The **avatar** budget — 12k tris/28 bones/1024²/1 LOD/≤2 MB — is [04](04-personagens-avatar.md)'s; the
  **degradation ladder** is Section [13](13-acessibilidade.md)'s 13.29 / Section [11](11-arquitetura.md)'s mechanism.)*
- ⚠️ **A5 / N6 — Colorblind mode.** Confirm the **types** (deuteranopia/protanopia/tritanopia) and the **method**
  (palette swap × patterns/textures × both — proposal: **both**) — 13 fixed the existence and deferred the values to 15.
- ⚠️ **A8 — Music.** Will Quest have a **score/ambient** per world? If yes, the `musica` preference gets an
  asset/player (wiring = ADR-13-C); if **not**, the field **stays** in the model (ADR-13-C decided to **keep** it)
  and the divergence (orphan toggle) is **routed to Section [13](13-acessibilidade.md)** for an ADR-13-C review —
  **15 does not remove** the field.
- ⚠️ **Canon vs scaffold.** Which values of `materias.ts`, `cenasTema.ts` (agent-generated scenes), `Cosmo.tsx`
  and `tokens.css` to **preserve as canonical direction** (if they pass A1/A3 and the Sensory Bible ratifies) vs.
  **redo** — **except** the `erer`, always re-authored (A16). 03 marks this as 15's deliverable.
- **Boundary note (not a 15 decision):** the ⚠️ **15.9** (humanoid avatar design), **15.11** (3D avatar × 2D
  Cosmo role) and **15.12** (2D × 3D render strategy / Three.js official) are already **decided** by Sections
  [04](04-personagens-avatar.md) and [11](11-arquitetura.md); the historical `docs/quest/01` contradiction
  ("DOM/SVG-first, PixiJS not Three.js") is **legacy** — 15 follows 04/11.

### 16. ADR (Architecture Decision Record)
- **ADR-15-A — `tokens.css` is the single source of color.** Every UI color derives from `tokens.css`;
  `materias.ts`/`cenasTema.ts` reference it; the palette is **audited by measured contrast** (4.5:1/3:1 — Section
  [13](13-acessibilidade.md)'s threshold); failed tokens are adjusted before publishing.
- **ADR-15-B — Hybrid audio with a cascade (proposed).** Narration = **recorded brand phrases (OGG)** → **Web
  Speech** (**local** voice, primary for dynamic text) → **visual fallback** (13); **never** a network voice
  (P18/[12](12-seguranca-privacidade.md)); offline is guaranteed only with a local voice/clip. SFX stay WebAudio,
  no error buzzer. *Pending ratification (§15/15.27).*
- **ADR-15-C — Procedural is the floor; GLB is the target bar decided by 04.** The procedural 3D (Q0) is the
  **performance, degradation and offline-fallback floor**; the migration to **authored GLB/GLTF** (glTF 2.0 +
  Draco + KTX2 pipeline, within Section [04](04-personagens-avatar.md) §10g's budget) is **Section [04](04-personagens-avatar.md)'s**
  decision — 15 owns the **production** and the compression/FPS. *Production/budget pending (§15/15.38).*
- **ADR-15-D — 15 executes the Sensory Bible; Raízes/ERER only by human curation.** The sensory direction of the
  9 worlds + Cosmo is Section [03](03-universo.md)'s/`biblia-sensorial/`'s; 15 gives the execution. The
  **Raízes/ERER** world has no AI-generated art/audio/sheet — **only specialized human curation (Q5)**; any agent
  asset (e.g. `erer`) is **discarded and re-authored**, never merely reviewed.

*Cross-module decisions are not improvised here: the pending items above become an ADR or a §15 entry.*
