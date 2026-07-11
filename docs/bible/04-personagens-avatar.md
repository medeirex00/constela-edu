# 04 — Personagens & Avatar / Characters & Avatar

- **Status:** 🟢 aprovado / approved
- **Padrão / Standard:** [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) (16 partes)
- **Fontes / Sources:** `apps/quest/src/personagem/*`, `backend/app/quest/services/perfis.py` (APARENCIA, PERSONAGENS_BASE, AVATAR_PADRAO), `apps/quest/src/vestiario/*`, `apps/quest/src/cosmo/*`, [03](03-universo.md), `_estado-atual/RELATORIO-2026-07-09.md`
- **Depende de / Depends on:** renderização → [11](11-arquitetura.md); economia → [05](05-sistemas-de-jogo.md); telas/rótulos → [07](07-ux-fluxos-navegacao.md)/[02](02-vocabulario.md); telemetria → [17](17-telemetria-metricas.md); produção de arte → [15](15-arte-audio-assets.md); testes → [18](18-qa-testes.md).

> **Convenção:** "§N" = uma das 16 **partes deste capítulo**; "Seção NN" = outro capítulo da Bible.
> **Escopo:** este capítulo decide o **personagem e o avatar**; onde algo pertence a outro capítulo,
> apenas registramos a dependência.

---

## 🇧🇷 Personagens & Avatar

### 1. Objetivo
Ser a **referência definitiva do sistema de personagens** do Constela Quest: avatar 3D, personagens-base,
customização, rig/esqueleto, roupas modulares, acessórios, inventário cosmético, skins, emotes, pets,
física, animações, expressões faciais, o **pipeline artístico Blender → GLB** e os **contratos**
necessários para o avatar funcionar. Fonte única para **programadores, artistas 3D, animadores e game
designers** implementarem o personagem sem adivinhar.

### 2. Contexto
O personagem é o avatar da criança (rótulo infantil = responsabilidade da Seção [02](02-vocabulario.md))
dentro do universo (Seção [03](03-universo.md)). O **Cosmo** é o **mascote-companheiro** (Seção
[15](15-arte-audio-assets.md)), **nunca** o avatar. No ecossistema **Hub → Edu → Quest**, a identidade
administrativa vem do Edu; o avatar é a identidade **lúdica** criada e possuída **dentro do Quest** —
cosmética, por perfil, sem dado pessoal novo (Princípio 4).

**Estado atual (Q0):** avatar humanoide 3D **procedural** (montado em `personagem/` a partir de
primitivas) e **vivo** (respira, pisca, olha, acena, ação ao clicar); 6 personagens-base; vestiário com 9
categorias; itens especiais 3D; invocação do skate; whitelist no backend (`APARENCIA`). **Como o 3D é
renderizado no cliente é assunto da Seção [11](11-arquitetura.md)** (hoje: React Three Fiber).

### 3. Filosofia da funcionalidade
O avatar é o **"esse sou eu"** da criança — o principal veículo de **autonomia** e **vínculo** (pilares,
Seção [00](00-visao-e-norte.md)). Precisa ser **carismático e vivo**, nunca um boneco parado. Customizar
é **auto-expressão sem barreira** (essencial grátis, sem dinheiro real) e **equipar é um evento** — o
personagem reage, nada aparece do nada. Carrega a qualidade de jogo moderno (Seção [15](15-arte-audio-assets.md)),
subordinada ao piso de desempenho dos tablets de escola (Princípio 17).

### 4. Experiência que o jogador deve sentir
- **Posse e identidade:** "eu me reconheço nele"; orgulho de mostrar o meu astronauta.
- **Vida:** respira, pisca, olha pra mim, comemora — parece que **está aqui**.
- **Encantamento ao customizar:** cada troca é gostosa e imediata; equipar item especial é um pequeno
  espetáculo (partículas, brilho, pose).
- **Nunca punição:** customizar é só alegria; nada é "errado", nada se perde.

### 5. Fluxo completo
1. **Cerimônia (1ª vez):** escolhe um dos **6 personagens-base** (com prévia 3D; o padrão de tela é da Seção [07](07-ux-fluxos-navegacao.md)/[08](08-onboarding-ftue.md)), depois o apelido.
2. **Vestiário:** customiza; cada troca atualiza o 3D na hora e dispara a **animação de equipar**.
3. **Loja & inventário:** desbloqueia cosméticos com moedas (economia = Seção [05](05-sistemas-de-jogo.md)); o inventário guarda o que é seu.
4. **No mundo:** o avatar aparece na tela-casa e nas cenas dos planetas (Seção [03](03-universo.md)),
   vivo; monta o **skate voador**; convive com o **Cosmo**.
- **Persistência:** estado do perfil, nunca vaza entre contas (Princípio 4).

### 6. Interface (quando existir)
As telas são da Seção [07](07-ux-fluxos-navegacao.md) e a arte da Seção [15](15-arte-audio-assets.md); aqui
só o que o **personagem exige** delas: o **Vestiário** precisa de um **palco 3D** com **prévia imediata**
ao trocar slot e a animação de equipar (a gestão do contexto de render é da Seção [11](11-arquitetura.md));
**Loja/Inventário** precisam exibir os itens que o perfil possui/pode equipar — as **miniaturas/prévias**
desses itens são responsabilidade das Seções [05](05-sistemas-de-jogo.md)/[07](07-ux-fluxos-navegacao.md);
a **tela-casa** mostra o avatar em destaque, vivo. Layout, rótulos e navegação = Seções [07](07-ux-fluxos-navegacao.md)/[02](02-vocabulario.md).

### 7. UX
Sem depender de leitura (ícones + cor + prévia 3D imediata); **feedback instantâneo** (trocar um slot
reflete no 3D **imediatamente**; o alvo técnico de latência/quadro é da Seção [11](11-arquitetura.md));
equipar item especial toca a invocação. Acessibilidade = Seção [13](13-acessibilidade.md) (alvos ≥48px,
`prefers-reduced-motion` reduz física/partículas).

### 8. Game Design
- **Personagens-base:** 6, **gratuitos**, ponto de partida 100% customizável (não travam nada).
- **Camadas de customização (cosmético, sem poder de jogo):** pele; cabelo + cor; blusa (camiseta/
  moletom/jaqueta/jardineira) + cor; baixo (calça/shorts) + cor; tênis + cor; acessório de cabeça/rosto
  (óculos/boné/coroa/fone/capacete…); costas (mochila/asas/jetpack); aura (estelar/halo/rastro); mão
  (varinha); pet; veículo (skate/patins).
- **Skins:** variações completas de aparência de um personagem-base (tema/coleção).
- **Itens especiais:** cosméticos com **invocação** (partículas, brilho, pose).
- **Emotes:** ações expressivas acionáveis. **Conjunto inicial definido:** `dança`, `pose`, `oi`, `sim`
  (expansível — §13). O **gatilho/UI** (ex.: roda de emotes) é da Seção [07](07-ux-fluxos-navegacao.md).
- **Pets:** companheiros cosméticos (gatinho/dino/estrelinha/robô). Sistema mais profundo = §13.
- **Economia:** os itens são cosméticos e se **ganham jogando**, sem compras reais (Princípio 7).
  Preços, moedas, desbloqueio e inventário = Seção [05](05-sistemas-de-jogo.md); loja rotativa e passe/temporada = Seção [19](19-liveops.md). Aqui ficam os **itens**.

### 9. Regras de negócio
- **Whitelist estrita:** todo slot/valor é validado contra `APARENCIA` no servidor; o cliente nunca
  envia hex livre nem item fora do catálogo (erro → 422). **Slots do avatar (14):** `pele, cabelo,
  cor_cabelo, top, camiseta, baixo, calca, tenis, chapeu, costas, aura, mao, pet, veiculo`. *(`APARENCIA`
  ainda mantém um 15º slot legado `cor` do Cosmo, fora do avatar 3D.)*
- **Base gratuita**; cosméticos extras se ganham jogando (nunca dinheiro real — Princípio 7).
- **Personagem-base é trocável (decidido):** a criança pode mudar de personagem-base a qualquer momento;
  **todos os cosméticos equipados são preservados** (nunca punição — Princípio 6).
- **Compatibilidade universal (decidido):** graças ao rig canônico único (§10a), **todos os cosméticos
  são compatíveis com todos os personagens-base** — não há restrições de compatibilidade.
- **Propriedade por perfil**, nunca vaza entre contas (Princípio 4); persistida no servidor.
- **Posse para equipar:** um item só é equipável se estiver no inventário do perfil; a **fonte** do
  inventário (o que se possui e como se ganha) é da Seção [05](05-sistemas-de-jogo.md).
- **Sem texto livre:** nomear pet/skin é seleção de catálogo (Princípio 2).

### 10. Arquitetura técnica
**Decisão deste capítulo:** o avatar é um **humanoide 3D autorado em GLB/GLTF** (não procedural, não
Cosmo). *Como* o GLB é renderizado no cliente (motor/renderer, integração com o resto da app) é da Seção
[11](11-arquitetura.md); o procedural atual é fallback durante a migração (§10h).

**a) Rig canônico (decidido).** Um esqueleto humanoide **único**, compartilhado por todos os personagens
e roupas. **22 ossos** (rig-base), **sem dedos**, proporção *chibi*/infantil. Ossos: `Hips`; `Spine`→`Chest`→`Neck`→
`Head`; `Eye_L/R`; `Shoulder/UpperArm/LowerArm/Hand` L/R; `UpperLeg/LowerLeg/Foot` L/R. **Sockets**
(nós vazios): `socket_head`, `socket_face`, `socket_back`, `socket_hand_R`, `socket_feet`,
`mount_vehicle`. A produção do modelo-base (topologia, skinning) é detalhada na Seção [15](15-arte-audio-assets.md),
dentro **desta** especificação de ossos/sockets.

**b) Sistema modular de roupas (decidido).** Corpo-base = **um** SkinnedMesh **segmentado por região**
(torso, bracoL/R, antebracoL/R, maoL/R, coxaL/R, canelaL/R, peL/R, cabeca, pescoco) com **visibilidade
por região**. Peças de vestuário = malhas skinadas ao **mesmo rig**; cada peça declara as **regiões que
esconde** (ex.: `calca` esconde coxa+canela) para evitar *clipping*. **Todos os módulos compartilham o
mesmo esqueleto e a mesma bind pose** (requisito, não "retarget"). **Tint paramétrico:** cada peça
suporta **1 ou 2 zonas de cor tingíveis**, cuja cor é definida pelo slot de cor correspondente. *(A
produção do material tingível e do albedo neutro é da Seção [15](15-arte-audio-assets.md).)* Mapa
cor→zona: `pele`→corpo, `cor_cabelo`→cabelo, `camiseta`→top, `calca`→baixo, `tenis`→tênis.

**c) Manifesto de assets (contrato — decidido).** O cliente resolve um avatar (JSON de slots) via um
manifesto: para cada `slot`+`valor` de `APARENCIA`, `{ tipo: skinnedMesh|socketAttach|tintOnly|effect,
assetUrl, socket, zonaDeCor, regioesEscondidas[] }`. **Fonte única:** este manifesto é servido pelo
backend (que já expõe catálogos cosméticos hoje **não consumidos** pelo cliente — fim do catálogo
duplicado). O contrato de dados do avatar (os 14 slots) permanece o mesmo.

**Classificação canônica dos 14 slots** (decisão deste capítulo):

| slot | tipo | socket / âncora | zona de cor |
|------|------|-----------------|-------------|
| `pele` | tintOnly | — | corpo |
| `cabelo` | skinnedMesh | — | — |
| `cor_cabelo` | tintOnly | — | cabelo |
| `top` | skinnedMesh | — | — |
| `camiseta` | tintOnly | — | top |
| `baixo` | skinnedMesh | — | — |
| `calca` | tintOnly | — | baixo |
| `tenis` | tintOnly | — | tênis |
| `chapeu` | socketAttach | `socket_head` (óculos: `socket_face`) | — |
| `costas` | socketAttach | `socket_back` | — |
| `aura` | effect | — | — |
| `mao` | socketAttach | `socket_hand_R` | — |
| `pet` | effect | offset relativo (GLB independente) | — |
| `veiculo` | effect/mount | `mount_vehicle` | — |

**d) Pipeline artístico Blender → GLB (decidido).** Autoria no **Blender** (corpo + rig + peças +
animações) → export **GLB** (glTF 2.0) com compressão de geometria e textura. Convenções de nome/versão
de arquivo e produção de textura/atlas = Seção [15](15-arte-audio-assets.md). O consumo em runtime
(loader/engine) = Seção [11](11-arquitetura.md).

**e) Animação (decidido).** Clipes nomeados no GLB: `idle`, `idle_var_01/02/03`, `wave`, `celebrate`,
`spin`, `equip`, `ride_skate`, `emote_danca/pose/oi/sim`. Os **estados esperados** (Idle + variações,
hover, click, equip, emote, veículo) e os nomes de clipes/morphs são contrato deste capítulo; a
**máquina de estados e o blend em runtime** são da Seção [11](11-arquitetura.md). **Expressões faciais**
por morph targets nomeados: `blink`,
`smile`, `surprise`, `cheeks`. **Olhar** segue o ponteiro via ossos `Eye_L/R` (look-at leve). O idle do
procedural (respira/pisca/olha/weight-shift) é a **referência de sensação**.

**f) Física secundária (decidido).** Cabelo, capuz, mochila, asas e rastros com mola/*jiggle* leve,
**desligável** por `prefers-reduced-motion` e device fraco; nunca compromete o rig principal.

**g) Orçamento do avatar (contrato normativo deste capítulo).** máximo **12.000 triângulos**/avatar-base;
máximo **28 ossos** (rig-base 22 + acessórios/física secundária); **atlas máximo 1024²**; **1 nível de
LOD**; **GLB base comprimido máximo 2 MB**; **um** SkinnedMesh de corpo + N módulos. *(O device-alvo que
justifica estes limites é definido pela Seção [11](11-arquitetura.md); se ele mudar, o orçamento é revisto.)*

**h) Pet, skate e transição (decidido).** O **pet** é um GLB **independente**, com seu próprio idle,
ancorado por **offset relativo** ao avatar (não a um socket) e contabilizado no orçamento. A **invocação
do skate** passa a sequência **3D** (`equip`→`ride_skate`, com `mount_vehicle` posicionando o avatar).
**Transição:** durante a adoção do avatar GLB, o avatar procedural permanece como **fallback** até haver
**paridade funcional completa**. A estratégia de migração e implantação pertence ao **planejamento
técnico**, não a esta Bible.

### 11. Dependências com outros módulos
Registro das decisões que **não** são deste capítulo:
- **Renderização/motor 3D + piso de device** → Seção [11](11-arquitetura.md).
- **Economia** (preços, moedas, desbloqueio, inventário) → Seção [05](05-sistemas-de-jogo.md); **loja rotativa/passe/temporada** → Seção [19](19-liveops.md).
- **Telas, layout, navegação e rótulos infantis** (inclui gatilho de emotes) → Seção [07](07-ux-fluxos-navegacao.md)/[02](02-vocabulario.md).
- **Telemetria** (eventos de avatar/equipar/emote) → Seção [17](17-telemetria-metricas.md).
- **Produção de arte** (textura/atlas, naming/versão de asset, modelo-base) → Seção [15](15-arte-audio-assets.md).
- **Testes de asset** (validação glTF, orçamento em CI, teste de composição) → Seção [18](18-qa-testes.md).
Este capítulo **alimenta:** o avatar como protagonista no mundo (Seção [03](03-universo.md)).

### 12. Casos extremos (Edge Cases)
- **Falha de download de GLB/módulo (wifi de escola):** placeholder + retry por-slot; **fallback
  procedural** no slot que faltou; nunca personagem quebrado nem tela branca.
- **Device fraco:** desligar física secundária, reduzir LOD, cair para avatar estático de alta qualidade
  preservando identidade (piso = Seção [11](11-arquitetura.md)).
- **Slot inválido/legado:** servidor rejeita (whitelist); cliente ignora item desconhecido e usa o padrão.
- **Cosmético removido/descontinuado:** se um perfil tem equipado um item que deixou de existir no
  catálogo, o slot **volta ao padrão** (`AVATAR_PADRAO`) e o avatar renderiza normalmente — nunca avatar
  quebrado nem perfil bloqueado, nunca erro para a criança.
- **Offline:** avatar em cache exibido e customizável; sincroniza ao reconectar.
- **Clipping:** resolvido pelo mapa de regiões escondidas (§10b).
- **Reduced-motion:** idle mínimo, sem física secundária nem partículas de invocação.
- **Muitos itens equipados:** orçamento de partículas/draw-calls por avatar (§10g).

### 13. Escalabilidade futura
Novos cosméticos (roupas, skins, acessórios, itens especiais, emotes, pets) entram como **asset GLB +
entrada de manifesto**, respeitando o rig canônico e a bind pose — idealmente sem deploy de código.
Coleções sazonais/eventos = Seção [19](19-liveops.md). **Pets 2.0** (companheiros com comportamento
próprio) e **novos personagens-base** compatíveis com o rig são expansões previstas.

### 14. Checklist de implementação
- [ ] Rig canônico (§10a: ossos + sockets + bind pose congelada) produzido conforme spec.
- [ ] Manifesto de assets (§10c) servido pelo backend e consumido pelo cliente (fim do catálogo duplicado).
- [ ] Sistema modular de roupas (§10b: corpo segmentado + regiões escondidas + tint paramétrico).
- [ ] Pipeline Blender → GLB reprodutível (produção fina = Seção [15](15-arte-audio-assets.md)).
- [ ] State machine + morph targets faciais + olhar por ossos de olho (§10e).
- [ ] Física secundária desligável (§10f); orçamento do avatar (§10g) cumprido.
- [ ] 6 personagens-base em GLB com paridade `PERSONAGENS_BASE`/`APARENCIA`.
- [ ] Fallback procedural mantido até paridade funcional completa (§10h).
- [ ] Assets passam validação e orçamento (protocolo de teste = Seção [18](18-qa-testes.md)).
- [ ] DoD conferido contra o Apêndice [F](apendice-F-checklists-dod.md).

### 15. Questões em aberto
**Dentro da responsabilidade da Seção 04, não há questões em aberto** — o sistema de personagens está
definido. O que resta são **dependências de outros capítulos**, já registradas na §11.

### 16. ADR (Architecture Decision Record)
**Decisão registrada por este capítulo:** o avatar do jogador é um **humanoide 3D autorado em GLB/GLTF**,
com **rig canônico único** (§10a), **sistema modular de roupas** (§10b), **manifesto de assets** (§10c) e
**pipeline artístico Blender → GLB** (§10d); o **Cosmo permanece mascote-companheiro**, não o avatar.
*(Decisão do dono, 2026-07-09.)*

**Decisão futura em outro capítulo (apenas registrada aqui, não decidida):** a arquitetura de renderização
(motor 3D do cliente e postura DOM/SVG vs. 3D no núcleo) → Seção [11](11-arquitetura.md).

---

## 🇬🇧 Characters & Avatar

### 1. Objective
Be the **definitive reference for the character system** of Constela Quest: 3D avatar, base characters,
customization, rig/skeleton, modular clothing, accessories, cosmetic inventory, skins, emotes, pets,
physics, animations, facial expressions, the **Blender → GLB artistic pipeline** and the **contracts**
needed for the avatar to work. Single source for **programmers, 3D artists, animators and game
designers** to implement the character without guessing.

### 2. Context
The character is the child's avatar (child-facing label = Section [02](02-vocabulario.md)'s
responsibility) inside the universe (Section [03](03-universo.md)). **Cosmo** is the **companion mascot**
(Section [15](15-arte-audio-assets.md)), **never** the avatar. In the **Hub → Edu → Quest** ecosystem, the
administrative identity comes from Edu; the avatar is the **playful** identity created and owned **inside
Quest** — cosmetic, per profile, no new personal data (Principle 4). **Current state (Q0):** a
**procedural** 3D humanoid avatar (built in `personagem/` from primitives), **alive** (breathes, blinks,
looks, waves, click action); 6 base characters; wardrobe (9 categories); 3D special items; skate
invocation; backend whitelist (`APARENCIA`). **How the 3D is rendered on the client is Section
[11](11-arquitetura.md)'s matter** (today: React Three Fiber).

### 3. Feature philosophy
The avatar is the child's **"this is me"** — the main vehicle of **autonomy** and **bond** (pillars,
Section [00](00-visao-e-norte.md)). It must be **charismatic and alive**, never a static doll. Customizing
is **barrier-free self-expression** (essentials free, no real money) and **equipping is an event** — the
character reacts, nothing pops in from nowhere. It carries modern-game quality (Section
[15](15-arte-audio-assets.md)), subordinate to the school-tablet performance floor (Principle 17).

### 4. The experience the player should feel
- **Ownership and identity:** "I recognize myself in it"; pride in showing my astronaut.
- **Life:** breathes, blinks, looks at me, celebrates — it's **here**.
- **Delight in customizing:** each change is instant and joyful; equipping a special item is a little
  spectacle (particles, glow, pose).
- **Never punishment:** customizing is pure joy; nothing is "wrong", nothing is lost.

### 5. Complete flow
1. **Ceremony (1st time):** pick one of the **6 base characters** (with 3D preview; the screen pattern is Section [07](07-ux-fluxos-navegacao.md)/[08](08-onboarding-ftue.md)'s), then the nickname.
2. **Wardrobe:** customize; each change updates the 3D instantly and plays the **equip animation**.
3. **Store & inventory:** unlock cosmetics with coins (economy = Section [05](05-sistemas-de-jogo.md)); the inventory holds what's yours.
4. **In the world:** the avatar appears on the home screen and in planet scenes (Section [03](03-universo.md)),
   alive; mounts the **flying skate**; coexists with **Cosmo**.
- **Persistence:** profile state, never leaks between accounts (Principle 4).

### 6. Interface (when it exists)
Screens are Section [07](07-ux-fluxos-navegacao.md)'s and art Section [15](15-arte-audio-assets.md)'s; here
only what the **character requires** of them: the **Wardrobe** needs a **3D stage** with **instant
preview** on slot change and the equip animation (render-context management is Section [11](11-arquitetura.md)'s);
**Store/Inventory** need to show items the profile owns/can equip — **thumbnails/previews** of those items
are Sections [05](05-sistemas-de-jogo.md)/[07](07-ux-fluxos-navegacao.md)'s responsibility; the **home
screen** shows the avatar featured, alive. Layout, labels and navigation = Sections [07](07-ux-fluxos-navegacao.md)/[02](02-vocabulario.md).

### 7. UX
No reading required (icons + color + instant 3D preview); **instant feedback** (changing a slot reflects
in the 3D **immediately**; the technical latency/frame target is Section [11](11-arquitetura.md)'s);
equipping a special item plays the invocation. Accessibility = Section [13](13-acessibilidade.md) (targets
≥48px, `prefers-reduced-motion` reduces physics/particles).

### 8. Game Design
- **Base characters:** 6, **free**, fully customizable starting points (they lock nothing).
- **Customization layers (cosmetic, no gameplay power):** skin; hair + color; top (t-shirt/hoodie/jacket/
  overalls) + color; bottom (pants/shorts) + color; shoes + color; head/face accessory (glasses/cap/crown/
  headphones/helmet…); back (backpack/wings/jetpack); aura (stellar/halo/trail); hand (wand); pet; vehicle
  (skate/roller-skates).
- **Skins:** full appearance variants of a base character (theme/collection).
- **Special items:** cosmetics with **invocation** (particles, glow, pose).
- **Emotes:** triggerable expressive actions. **Initial set defined:** `dance`, `pose`, `hi`, `yes`
  (expandable — §13). The **trigger/UI** (e.g. emote wheel) is Section [07](07-ux-fluxos-navegacao.md)'s.
- **Pets:** cosmetic companions (cat/dino/star/robot). Deeper system = §13.
- **Economy:** items are cosmetic and **earned by playing**, no real purchases (Principle 7). Prices,
  coins, unlock and inventory = Section [05](05-sistemas-de-jogo.md); store rotation and pass/season = Section [19](19-liveops.md). Here live the **items**.

### 9. Business rules
- **Strict whitelist:** every slot/value validated against `APARENCIA` on the server; the client never
  sends free hex nor off-catalog items (error → 422). **Avatar slots (14):** `pele, cabelo, cor_cabelo,
  top, camiseta, baixo, calca, tenis, chapeu, costas, aura, mao, pet, veiculo`. *(`APARENCIA` still keeps
  a 15th legacy `cor` slot from Cosmo, outside the 3D avatar.)*
- **Free base**; extra cosmetics earned by playing (never real money — Principle 7).
- **Base character is changeable (decided):** the child can change base character at any time; **all
  equipped cosmetics are preserved** (never punishment — Principle 6).
- **Universal compatibility (decided):** thanks to the single canonical rig (§10a), **all cosmetics are
  compatible with all base characters** — no compatibility restrictions.
- **Per-profile ownership**, never leaks (Principle 4); server-persisted.
- **Ownership to equip:** an item is equippable only if in the profile's inventory; the inventory
  **source** (what's owned and how it's earned) is Section [05](05-sistemas-de-jogo.md)'s.
- **No free text:** naming a pet/skin is catalog selection (Principle 2).

### 10. Technical architecture
**This chapter's decision:** the avatar is a **3D humanoid authored in GLB/GLTF** (not procedural, not
Cosmo). *How* the GLB is rendered on the client (engine/renderer, integration with the rest of the app) is
Section [11](11-arquitetura.md)'s; the current procedural is a fallback during migration (§10h).

**a) Canonical rig (decided).** One **shared** humanoid skeleton for all characters and clothes.
**22 bones** (base rig), **no fingers**, *chibi*/child proportions. Bones: `Hips`; `Spine`→`Chest`→`Neck`→`Head`;
`Eye_L/R`; `Shoulder/UpperArm/LowerArm/Hand` L/R; `UpperLeg/LowerLeg/Foot` L/R. **Sockets** (empty nodes):
`socket_head`, `socket_face`, `socket_back`, `socket_hand_R`, `socket_feet`, `mount_vehicle`. Base-model
production (topology, skinning) is detailed in Section [15](15-arte-audio-assets.md), within **this**
bone/socket spec.

**b) Modular clothing system (decided).** Base body = **one** SkinnedMesh **segmented by region** (torso,
armL/R, forearmL/R, handL/R, thighL/R, shinL/R, footL/R, head, neck) with **per-region visibility**.
Garments = meshes skinned to the **same rig**; each declares the **regions it hides** (e.g. `calca` hides
thigh+shin) to avoid clipping. **All modules share the same skeleton and bind pose** (a requirement, not
"retargeting"). **Parametric tint:** each piece supports **1 or 2 tintable color zones**, whose color is
set by the matching color slot. *(Producing the tintable material and the neutral albedo is Section
[15](15-arte-audio-assets.md)'s.)* Color→zone map: `pele`→body, `cor_cabelo`→hair, `camiseta`→top,
`calca`→bottom, `tenis`→shoes.

**c) Asset manifest (contract — decided).** The client resolves an avatar (slot JSON) via a manifest: for
each `slot`+`value` of `APARENCIA`, `{ tipo: skinnedMesh|socketAttach|tintOnly|effect, assetUrl, socket,
zonaDeCor, regioesEscondidas[] }`. **Single source:** this manifest is served by the backend (which
already exposes cosmetic catalogs **not consumed** by the client today — ending the duplicate catalog).
The avatar data contract (the 14 slots) stays the same.

**Canonical classification of the 14 slots** (this chapter's decision):

| slot | type | socket / anchor | color zone |
|------|------|-----------------|------------|
| `pele` | tintOnly | — | body |
| `cabelo` | skinnedMesh | — | — |
| `cor_cabelo` | tintOnly | — | hair |
| `top` | skinnedMesh | — | — |
| `camiseta` | tintOnly | — | top |
| `baixo` | skinnedMesh | — | — |
| `calca` | tintOnly | — | bottom |
| `tenis` | tintOnly | — | shoes |
| `chapeu` | socketAttach | `socket_head` (glasses: `socket_face`) | — |
| `costas` | socketAttach | `socket_back` | — |
| `aura` | effect | — | — |
| `mao` | socketAttach | `socket_hand_R` | — |
| `pet` | effect | relative offset (independent GLB) | — |
| `veiculo` | effect/mount | `mount_vehicle` | — |

**d) Blender → GLB artistic pipeline (decided).** Authoring in **Blender** (body + rig + pieces +
animations) → export **GLB** (glTF 2.0) with geometry/texture compression. File naming/versioning and
texture/atlas production = Section [15](15-arte-audio-assets.md). Runtime consumption (loader/engine) =
Section [11](11-arquitetura.md).

**e) Animation (decided).** Named GLB clips: `idle`, `idle_var_01/02/03`, `wave`, `celebrate`, `spin`,
`equip`, `ride_skate`, `emote_danca/pose/oi/sim`. The **expected states** (Idle + variants, hover, click,
equip, emote, vehicle) and the clip/morph names are this chapter's contract; the **runtime state machine
and blending** are Section [11](11-arquitetura.md)'s. **Facial expressions** via named morph targets: `blink`, `smile`,
`surprise`, `cheeks`. **Gaze** follows the pointer via `Eye_L/R` bones (light look-at). The procedural idle
is the **feel reference**.

**f) Secondary physics (decided).** Hair, hood, backpack, wings and trails with light spring/jiggle,
**switchable off** via `prefers-reduced-motion` and weak devices; never compromises the main rig.

**g) Avatar budget (this chapter's normative contract).** max **12,000 triangles**/base avatar; max
**28 bones** (base rig 22 + accessories/secondary physics); **atlas max 1024²**; **1 LOD level**;
**compressed base GLB max 2 MB**; **one** body SkinnedMesh + N modules. *(The target device that justifies
these limits is set by Section [11](11-arquitetura.md); if it changes, the budget is revised.)*

**h) Pet, skate and transition (decided).** The **pet** is an **independent** GLB, with its own idle,
anchored by a **relative offset** to the avatar (not a socket) and counted in the budget. The **skate
invocation** becomes a **3D** sequence (`equip`→`ride_skate`, with `mount_vehicle` placing the avatar).
**Transition:** while the GLB avatar is being adopted, the procedural avatar remains as a **fallback**
until **complete functional parity** exists. The migration and deployment strategy belongs to **technical
planning**, not to this Bible.

### 11. Dependencies on other modules
Record of decisions that are **not** this chapter's:
- **Rendering / 3D engine + device floor** → Section [11](11-arquitetura.md).
- **Economy** (prices, coins, unlock, inventory) → Section [05](05-sistemas-de-jogo.md); **store rotation/pass/season** → Section [19](19-liveops.md).
- **Screens, layout, navigation and child labels** (incl. emote trigger) → Section [07](07-ux-fluxos-navegacao.md)/[02](02-vocabulario.md).
- **Telemetry** (avatar/equip/emote events) → Section [17](17-telemetria-metricas.md).
- **Art production** (texture/atlas, asset naming/versioning, base model) → Section [15](15-arte-audio-assets.md).
- **Asset testing** (glTF validation, CI budget, composition test) → Section [18](18-qa-testes.md).
This chapter **feeds:** the avatar as protagonist in the world (Section [03](03-universo.md)).

### 12. Edge cases
GLB/module download failure (school wifi): per-slot placeholder + retry; **procedural fallback** for the
missing slot; never a broken character or blank screen. Weak device: disable secondary physics, reduce
LOD, drop to a high-quality static avatar preserving identity (floor = Section [11](11-arquitetura.md)).
Invalid/legacy slot: server rejects (whitelist); client ignores unknown item and uses default.
**Removed/discontinued cosmetic:** if a profile has equipped an item that no longer exists in the catalog,
the slot **reverts to the default** (`AVATAR_PADRAO`) and the avatar renders normally — never a broken
avatar or blocked profile, never an error for the child. Offline: cached avatar shown and customizable;
syncs on reconnect. Clipping: solved by the hidden-regions map
(§10b). Reduced-motion: minimal idle, no secondary physics or invocation particles. Many items equipped:
particle/draw-call budget per avatar (§10g).

### 13. Future scalability
New cosmetics (clothes, skins, accessories, special items, emotes, pets) enter as **GLB asset + manifest
entry**, respecting the canonical rig and bind pose — ideally with no code deploy. Seasonal collections/
events = Section [19](19-liveops.md). **Pets 2.0** (companions with their own behavior) and **new base
characters** compatible with the rig are planned expansions.

### 14. Implementation checklist
- [ ] Canonical rig (§10a: bones + sockets + frozen bind pose) produced to spec.
- [ ] Asset manifest (§10c) served by the backend and consumed by the client (end the duplicate catalog).
- [ ] Modular clothing (§10b: segmented body + hidden regions + parametric tint).
- [ ] Reproducible Blender → GLB pipeline (fine production = Section [15](15-arte-audio-assets.md)).
- [ ] State machine + facial morph targets + eye-bone gaze (§10e).
- [ ] Switchable secondary physics (§10f); avatar budget (§10g) met.
- [ ] 6 base characters in GLB with `PERSONAGENS_BASE`/`APARENCIA` parity.
- [ ] Procedural fallback kept until complete functional parity (§10h).
- [ ] Assets pass validation and budget (test protocol = Section [18](18-qa-testes.md)).
- [ ] DoD checked against Appendix [F](apendice-F-checklists-dod.md).

### 15. Open questions
**Within Section 04's responsibility, there are no open questions** — the character system is defined.
What remains are **dependencies on other chapters**, already recorded in §11.

### 16. ADR (Architecture Decision Record)
**Decision recorded by this chapter:** the player avatar is a **3D humanoid authored in GLB/GLTF**, with a
**single canonical rig** (§10a), a **modular clothing system** (§10b), an **asset manifest** (§10c) and a
**Blender → GLB artistic pipeline** (§10d); **Cosmo remains the companion mascot**, not the avatar.
*(Owner decision, 2026-07-09.)*

**Future decision in another chapter (only recorded here, not decided):** the rendering architecture
(client 3D engine and DOM/SVG-vs-3D stance for the core) → Section [11](11-arquitetura.md).
