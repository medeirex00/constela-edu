# 13 — Acessibilidade & Bem-estar / Accessibility & Well-being

- **Status:** 🟢 aprovado / approved
- **Padrão / Standard:** [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) (16 partes)
- **Fontes / Sources:** `INDICE.md` (bloco 13, 31 subseções, decisões ⚠️ 13.15/13.19/13.20/13.21/13.26/13.29 + gap de fallback de áudio `INDICE.md:2029`), `_estado-atual/RELATORIO-2026-07-09.md` (áudio sintetizado; preferências órfãs `musica`/`reduzir_animacoes`), `apps/quest/src/design/tokens.css` (`--alvo-minimo: 48px`), `apps/quest/src/design/base.css` (`.botao3d`, `prefers-reduced-motion`), `apps/quest/src/componentes/Cosmo.tsx` / `InvocacaoSkate.tsx` (checagem de reduced-motion em JS), `apps/quest/src/entrada/entrada.css` (nota ad-hoc de contraste AA), `backend/app/quest/services/perfis.py` (`PREFERENCIAS_PERMITIDAS` + whitelist), `backend/app/quest/models/perfil.py` (coluna `preferencias` JSON), `backend/app/quest/schemas.py`, `backend/app/quest/routers/perfil.py` (aplica a whitelist), Seções [01](01-principios-imutaveis.md)/[05](05-sistemas-de-jogo.md)/[07](07-ux-fluxos-navegacao.md)/[09](09-social.md)/[10](10-professor-familia.md)/[11](11-arquitetura.md)
- **Depende de / Depends on:** princípios (P6 erro nunca pune · P7 sem FOMO/compra · P8 zero dark patterns · P9 áudio sempre pt-BR · P11 acessibilidade inegociável) → [01](01-principios-imutaveis.md); **valor** do teto diário / pausa / mecânica de progressão (Chama) → [05](05-sistemas-de-jogo.md)/[19](19-liveops.md); **superfície** das telas e da tela de preferências → [07](07-ux-fluxos-navegacao.md); **superfície** dos portais adultos (teto/pausa/horário) e invariante "push só a adultos" (aplicação) → [10](10-professor-familia.md); **meio técnico** de render híbrido / piso de desempenho → [11](11-arquitetura.md); **valores** de paleta/contraste e a **estratégia** de áudio (sintetizado × gravado) → [15](15-arte-audio-assets.md); **métricas** de uso saudável → [17](17-telemetria-metricas.md); **valores** de config (`quest.*`: teto, janela de pausa, horário) → [19](19-liveops.md).

> **Convenção / Convention:** "§N" = uma das 16 **partes deste capítulo** / one of the 16 **parts of this
> chapter**; "Seção NN" / "Section NN" = outro capítulo da Bible / another Bible chapter; "13.NN" = uma
> subseção do plano do `INDICE.md` / a subsection of the `INDICE.md` plan.
> **Escopo / Scope:** este capítulo é a **fonte canônica única** de duas normas do Constela Quest — a **norma
> de acessibilidade** (o piso obrigatório que torna o jogo utilizável por uma criança de 6 anos, não-leitora ou
> com deficiência) e a **norma de bem-estar** (o jogo serve à criança e nunca a retém). Ele **decide a norma**
> (o piso e o *framing*); **não** decide os **valores** de teto/pausa (Seções [05](05-sistemas-de-jogo.md)/[19](19-liveops.md)),
> a **superfície** das telas (Seção [07](07-ux-fluxos-navegacao.md)) ou dos portais adultos (Seção [10](10-professor-familia.md)),
> o **meio** técnico de render/áudio (Seções [11](11-arquitetura.md)/[15](15-arte-audio-assets.md)) nem os **valores**
> de paleta/contraste (Seção [15](15-arte-audio-assets.md)) — apenas os **exige** e **referencia**.

---

## 🇧🇷 Acessibilidade & Bem-estar

### 1. Objetivo
Ser a **referência definitiva de acessibilidade e bem-estar** do Constela Quest: a **norma única** que garante
que **qualquer criança** — de 6 anos, não-leitora, com baixa visão, daltônica, com dificuldade motora, ou num
tablet fraco de escola — jogue **com autonomia e dignidade**, e que o tempo de jogo seja **saudável, nunca
compulsivo**. Permite construir **sem re-decidir o piso** em cada tela e **sem improvisar regra de bem-estar**.
Decide a **norma** (o piso obrigatório de acessibilidade + o *framing* de bem-estar); **não** decide os
**valores** (teto/pausa → Seções [05](05-sistemas-de-jogo.md)/[19](19-liveops.md); paleta/contraste →
Seção [15](15-arte-audio-assets.md)), a **superfície** das telas (Seção [07](07-ux-fluxos-navegacao.md)) nem o
**meio** técnico (render → Seção [11](11-arquitetura.md); áudio sintetizado × gravado → Seção [15](15-arte-audio-assets.md)).

### 2. Contexto
No ecossistema **Hub → Edu → Quest**, o Quest é o **jogo das crianças** (1º–5º ano, 6–11 anos). Boa parte do
público **ainda não lê com fluência** — no 1º ano, a criança-**padrão** é **não-leitora**. Por isso a
acessibilidade aqui **não é recurso opcional**: é a condição para o produto existir. A norma já vive, hoje,
apenas como **Princípio 11** ([01](01-principios-imutaveis.md):47-49) e aparece **re-derivada e duplicada** em
5+ seções; a Seção [07](07-ux-fluxos-navegacao.md) já fez o **movimento-modelo** (removeu o número, passou a
citar a 13, "sem cravar limiares próprios"). Esta seção **assume a autoridade**: crava o piso **antes que as
cópias divirjam**.

**Estado atual (Q0) — parcial e desigual:**
- **Alvo de toque** — o token `--alvo-minimo: 48px` existe (`tokens.css:39`) e é aplicado via `var(--alvo-minimo)`
  no `.botao3d` (`base.css:54`) e nas telas de entrada/lobby/vestiário; ainda **não é auditado por tela**.
- **Reduced-motion** — `prefers-reduced-motion: reduce` é respeitado **globalmente** (`base.css:185-187` zera
  animações/transições; checado também em JS no `Cosmo.tsx` e `InvocacaoSkate.tsx`).
- **Áudio/narração** — funciona **offline em pt-BR**, hoje **sintetizado** (Web Speech API + WebAudio); a
  **estratégia definitiva** (sintetizado × gravado profissional) é da Seção [15](15-arte-audio-assets.md) (15.27).
- **Preferências** — a whitelist `PREFERENCIAS_PERMITIDAS` (em `services/perfis.py`) já cobre `som`, `narracao`,
  `musica` e `reduzir_animacoes`; `som`/`narracao` **já são cabeados** ao áudio pela UI (`Lobby.tsx`), mas
  `musica` e `reduzir_animacoes` estão **órfãos**: a interface **nunca lê esses toggles salvos** (só reage à
  *media query* do SO) — pendência registrada no `RELATORIO-2026-07-09.md`.
- **Lacunas** — **modo daltônico não existe**; o **contraste não é auditado sistematicamente** nem tem *ratio*
  canônico (há só notas ad-hoc, ex.: `entrada.css:171-172` cita "contraste AA" e um texto branco que reprovava
  em ~2:1); **nenhum nível-alvo WCAG normativo** foi declarado como padrão do produto; **bem-estar** (teto como
  celebração, pausa, horário) existe como intenção em [10](10-professor-familia.md), mas sem a **norma-fonte**
  que a 10 cita.

Este capítulo **crava** o piso, **converge** o número do alvo e a norma de *reduced-motion* antes da deriva, e
**ancora** as citações de bem-estar que hoje apontam para um arquivo que não existia.

### 3. Filosofia da funcionalidade
**Acessibilidade não é um recurso — é o piso.** A criança que **ainda não lê** é o usuário **padrão**, não a
exceção; se ela trava, o produto falhou. **Design universal:** o que ajuda a criança com deficiência ajuda
**todas** (o áudio que salva o não-leitor também acalma a criança ansiosa; o alvo grande que serve a mão pequena
serve a mão trêmula).

**Bem-estar é a mesma moral aplicada ao tempo:** o jogo **serve** à criança, **não a retém**. Um produto para
crianças que usa gatilhos de compulsão — vidas, espera forçada, FOMO, *streak* que pune ausência — trai a
confiança da escola e da família. Aqui, **parar é sempre uma boa despedida**, nunca uma interrupção brusca ou
uma culpa.

Conexão com os **Princípios Imutáveis** ([01](01-principios-imutaveis.md)): **P11** (acessibilidade inegociável)
é o núcleo desta seção; **P9** (áudio sempre pt-BR) é o seu principal instrumento; **P6** (o erro nunca pune)
é acessibilidade **emocional**; **P7** (sem compra/FOMO) e **P8** (zero *dark patterns*) fundam a norma de
bem-estar. Aos **4 pilares**: **autonomia** (o não-leitor navega sozinho), **progresso visível sem ansiedade**,
**vínculo sem exposição** (ranking saudável — §8), e **surpresa sem compulsão**.

### 4. Experiência que o jogador deve sentir
**A criança sente: "eu consigo sozinho".** Nunca travada, nunca perdida, nunca punida pelo erro. O **Cosmo** é
a **voz-guia** que lê tudo em voz alta e repete quando pedem "ouvir de novo". O toque é **generoso** (o dedo
pequeno sempre acerta o alvo). O erro é **acolhido** — "quase! vamos de novo" —, nunca um "X" vermelho que dói.

**Ao parar, a criança sente uma boa despedida**, não uma porta batida: o teto do dia chega como **celebração**
("você brilhou muito hoje!"), a pausa chega como o **Cosmo pedindo um descanso junto**, e o horário combinado
com a família aparece com **gentileza**, nunca como punição.

**O adulto** (professor/família) sente: **"isto respeita meu aluno/filho".** Nenhum truque para prender a
criança, nenhuma cobrança, nenhuma notificação chegando à criança pelas costas do adulto.

### 5. Fluxo completo
A acessibilidade **percorre cada passo** — não é uma tela separada, é uma **camada** sobre tudo:

1. **Entrada / retorno** — código **falável** e **falado** pelo Cosmo; ícones grandes; nenhuma etapa exige
   leitura (o fluxo "É você?" confirma pelo **nome ouvido**, não por texto lido). Detalhe do fluxo → Seção [08](08-onboarding-ftue.md).
2. **Navegação** — sempre por **ícone + cor + áudio**, nunca só por leitura. Todo destino "fala" o que é ao
   receber foco/toque.
3. **Instrução de atividade** — **áudio obrigatório em pt-BR** em toda instrução, com o controle **"ouvir de
   novo"** sempre visível. O texto (quando existe) é **redundante** ao áudio, nunca a única via.
4. **Interação / erro** — alvo ≥48px; **≤1 ação primária** por tela; o erro é **acolhido** (P6) e o **tempo
   nunca** é o único critério de sucesso/fracasso (§9).
5. **Fim de sessão / pausa** — o teto diário chega como **celebração** (valor = Seções [05](05-sistemas-de-jogo.md)/[19](19-liveops.md));
   o **lembrete de pausa** do Cosmo aparece com gentileza; o **horário permitido** (se a família configurou) é
   reforçado **no servidor** e mostrado com carinho (superfície = Seção [10](10-professor-familia.md)).
6. **Offline** — a narração toca **localmente** (síntese no dispositivo), sem depender de rede.
7. **Fallback quando o áudio não pode tocar** (mudo, *autoplay* bloqueado, sem alto-falante) — **toda**
   instrução em áudio tem um **equivalente visual sincronizado** (ícone/destaque/animação que aponta o próximo
   passo) capaz de guiar **sozinho**; um indicador persistente **"som desligado — toque para ouvir"** convida a
   religar. O não-leitor **nunca** trava por falta de som (§12; resolve o gap `INDICE.md:2029`).
8. **Hardware fraco** — os efeitos **degradam graciosamente** (menos partículas, animação simplificada), mas o
   **feedback essencial** (estado de acerto/erro/foco/seleção por cor+ícone+áudio) **permanece** (§12; piso =
   Seção [11](11-arquitetura.md)).

### 6. Interface (quando existir)
A 13 **não desenha telas** — o inventário e a posição canônica das telas são da Seção [07](07-ux-fluxos-navegacao.md).
Aqui ficam apenas as **exigências de existência** de superfícies de acessibilidade:
- **Controle "ouvir de novo"** — presente e visível em toda instrução com áudio.
- **Indicador "som desligado — toque para ouvir"** — persistente quando o áudio está mudo/bloqueado.
- **Tela de preferências de acessibilidade** — expõe, no mínimo: `musica` (liga/desliga), `reduzir_animacoes`
  (liga/desliga), **modo daltônico** (existência fixada por P11; tipos/método → §15) e **tamanho de fonte**
  (§15 ⚠️). A **posição** e o desenho dessa tela são da Seção [07](07-ux-fluxos-navegacao.md); a **exigência**
  de que ela exista e **acione de fato** as preferências é da 13 (hoje `musica`/`reduzir_animacoes` estão
  **órfãos** — §2/§10/ADR-13-C).
- **Superfícies adultas de bem-estar** (teto/pausa/horário) — desenho e posição são da Seção [10](10-professor-familia.md);
  a 13 só define a **norma** que elas materializam.

### 7. UX
A 13 é a **dona do "como se sente" acessível**. Regras de experiência:
- **Áudio pt-BR primeiro** — a voz do Cosmo é o principal canal; o texto acompanha, nunca lidera. Vocabulário
  sempre o canônico da Seção [02](02-vocabulario.md) (nenhuma palavra proibida de UI).
- **Ritmo sem pressa** — nenhuma contagem regressiva punitiva; o **tempo nunca** é o único critério (§9).
- **Feedback imediato e multissensorial** — todo estado (acerto, erro, foco, seleção) é sinalizado por **cor +
  ícone/forma + áudio** ao mesmo tempo (redundância — nunca só cor).
- **Prevenção de erro** — ≤1 ação primária por tela; alvos grandes e espaçados; confirmações faladas.
- **Foco visível** — todo elemento interativo mostra **foco** claro (para toque e, na fase futura, teclado — §13).

### 8. Game Design
Como a acessibilidade e o bem-estar **moldam a mecânica** (as mecânicas em si são das Seções [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)):
- **Tempo nunca é critério único** — velocidade pode dar bônus, **nunca** decidir sozinha sucesso/fracasso
  (crianças com dificuldade motora ou cognitiva não são penalizadas).
- **Teto diário = celebração, não bloqueio** — ao atingir o teto, a criança é **parabenizada** e convidada a
  voltar amanhã; **não** há tela de "acabou, pague/espere". O framing deriva de **P6**; o **valor** do teto é
  das Seções [05](05-sistemas-de-jogo.md)/[19](19-liveops.md) (referência: 05.7).
- **Chama gentil, sempre a favor da criança** — a sequência é a **Chama do Cosmo**, com **escudo semanal** que
  perdoa faltas e fim de semana que não quebra (mecânica = Seção [05](05-sistemas-de-jogo.md)). A **norma de
  bem-estar** da 13: a Chama **nunca envergonha** e é **sempre recuperável** — se resetar, é com **mensagem
  gentil e recomeço acolhedor** (a criança que faltou por doença/férias é recebida de volta, nunca punida).
- **Ranking saudável** — comparação **eu × eu** (meu progresso) e ranking de turma que **zera toda semana**
  (cadência fixada por **P5**, [01](01-principios-imutaveis.md):31-33); **nunca** ranking individual exposto à
  criança (invariante de P5; mecânica na Seção [09](09-social.md)).
- **Sem gatilhos de compulsão** — **sem vidas, sem espera forçada, sem paywall, sem FOMO agressivo** (P7);
  **zero dark patterns** (P8).
- **Cada mecânica plugável declara acessibilidade** — todo novo tipo de atividade **deve declarar**, no seu
  contrato, como cumpre a norma (áudio, alvo, redundância de cor, *reduced-motion*). A **exigência** é da 13; o
  **formato** do contrato é das Seções [11](11-arquitetura.md)/[05](05-sistemas-de-jogo.md).

### 9. Regras de negócio
As **normas determinísticas** desta seção (a fonte única; qualquer cópia em outra seção é **aplicação**, não
re-decisão):

| # | Norma | Valor / Regra | Dono do valor |
|---|-------|---------------|---------------|
| N1 | **Alvo de toque mínimo** | **≥ 48×48 px**, com **espaçamento ≥ 8 px** entre alvos (⚠️ §15) | 13 (converge `tokens.css:39`) |
| N2 | **Nível de conformidade** | **WCAG 2.1 AA** como piso, com critérios AAA seletivos onde servem ao não-leitor (áudio de instrução excede AA) | 13 ⚠️ (ratificar) |
| N3 | **Contraste mínimo** | **4.5:1** texto normal · **3:1** texto grande e componentes de UI | 13 ⚠️ (ratificar); valores de paleta = Seção [15](15-arte-audio-assets.md) |
| N4 | **Áudio de instrução** | **obrigatório em pt-BR** em toda instrução + controle **"ouvir de novo"** sob demanda | 13 (P9); **meio** (sintetizado × gravado) = Seção [15](15-arte-audio-assets.md) |
| N5 | **Navegação** | **ícone + cor + áudio** — nunca só por leitura | 13 |
| N6 | **Cor nunca é canal único** | toda informação por cor tem **redundância** (forma/ícone/rótulo/áudio); **modo daltônico** reforça (existência fixada por P11; tipos/método → §15; paletas = Seção [15](15-arte-audio-assets.md)) | 13 ⚠️ (tipos/método) |
| N7 | **Reduced-motion** | respeitar `prefers-reduced-motion` (já ativo) e, **uma vez cabeado** (ADR-13-C / 13.15), o toggle `reduzir_animacoes`; **fallback estático obrigatório** em toda animação (o que reduz/permanece — abaixo) | 13 |
| N8 | **Tempo** | **nunca** critério único de sucesso/fracasso | 13 |
| N9 | **Ação primária** | **≤ 1 por tela** — *ação primária* = o único destino/comando que avança o fluxo principal da tela (os demais são secundários/de suporte) | 13 (07 aplica) |
| N10 | **Erro** | **acolhido, nunca punição** (P6) | 13 + [01](01-principios-imutaveis.md) |
| N11 | **Tamanho de fonte** | **ajustável** (preferência de perfil, passos padrão/grande/muito-grande) | 13 ⚠️ (ratificar) |
| N12 | **Push à criança** | **nunca** — notificação só a adultos (invariante) | 13 (fonte); [10](10-professor-familia.md) aplica |
| N13 | **Teto diário** | **celebração, não bloqueio** (norma); valor = Seções [05](05-sistemas-de-jogo.md)/[19](19-liveops.md) | 13 (norma, deriva de P6) + [01](01-principios-imutaveis.md) |
| N14 | **Lembrete de pausa** | gentil, do Cosmo; intervalo **configurável** (valor/default = Seção [19](19-liveops.md); proposta em §15) | 13 ⚠️ (valor = Seção [19](19-liveops.md)) |
| N15 | **Horário permitido** | reforço **no servidor**, mostrado com gentileza; a **família define a janela** (decidido na Seção [10](10-professor-familia.md) §9); em aberto só a **forma** (janela livre × faixas fixas) — §15 13.26 | 13 (norma) |
| N16 | **Dark patterns** | **zero** em toda a experiência — inclusive nas superfícies adultas de bem-estar que a 13 norma (P8) | 13 + [01](01-principios-imutaveis.md) |
| N17 | **Fallback de áudio** | quando o áudio não pode tocar, **equivalente visual sincronizado** guia sozinho + indicador "toque para ouvir" | 13 |

**Reduced-motion — o que reduz e o que permanece (N7):**
- **Reduz / vira estático:** *parallax*, câmera orbital, partículas ambientais, *idle animations* amplas do
  personagem, zoom/deslize longos, a **invocação cinematográfica** do item especial (vira **revelação
  estática**), *bounces*/tremores decorativos, movimento de fundo em *autoplay*.
- **Permanece (em forma não-vestibular):** o **feedback essencial** de estado (acerto/erro/foco/seleção) por
  **cor + ícone + áudio** com transição curta de opacidade; o **foco visível**; a troca de tela por **corte
  simples** em vez de deslize longo. *Nada essencial some com o reduced-motion — só o movimento decorativo.*

**Servidor × cliente:** **horário** e **teto** são reforçados **no servidor** (mecanismo = Seções [10](10-professor-familia.md)/[11](11-arquitetura.md));
a **norma de acessibilidade** é responsabilidade do **cliente**, verificada pelo **gate de publicação** (§14) —
o servidor não "audita contraste".

### 10. Arquitetura técnica
A 13 **não é dona de endpoints nem de modelo de dados** (contratos → Apêndice B). Onde a norma **toca** o código:
- **Preferências no perfil** — a whitelist `PREFERENCIAS_PERMITIDAS` vive em `services/perfis.py` (a coluna JSON
  `preferencias` está em `models/perfil.py`; o schema em `schemas.py`; o endpoint que a aplica em
  `routers/perfil.py`). `musica` e `reduzir_animacoes` já existem na whitelist, porém **órfãos**: a UI só lê a
  *media query* do SO. A 13 **decide cabear** esses toggles à função (o salvo **força** *reduced-motion* / liga a
  música), **mantendo** os campos no modelo — não removê-los (ADR-13-C; pendência `INDICE` 13.15 / ADR C.24). Se
  **modo daltônico** e **tamanho de fonte** virarem preferências (⚠️ §15), entram na **mesma whitelist**.
- **Áudio** — a 13 **exige** o resultado (pt-BR, inteligível, "ouvir de novo", fallback visual); o **meio**
  (síntese Web Speech × gravação profissional) é decisão da Seção [15](15-arte-audio-assets.md) (15.27). Hoje é
  **sintetizado**; a 13 não trava esse meio, só o resultado.
- **Render / degradação** — o render **híbrido** e o **piso de desempenho** são da Seção [11](11-arquitetura.md);
  a 13 define **que** os efeitos degradam preservando o feedback essencial (§12), mas o **como** técnico e o
  device-alvo são da 11 (11.48).
- **Contrato de mecânica** — a exigência "cada mecânica declara acessibilidade" adiciona **campos de
  declaração** ao contrato de atividade (formato = Seções [11](11-arquitetura.md)/[05](05-sistemas-de-jogo.md)).

### 11. Dependências com outros módulos
**Consome:**
- **Seção [01](01-principios-imutaveis.md)** — P6/P7/P8/P9/P11 (as crenças que esta seção operacionaliza).
- **Seções [05](05-sistemas-de-jogo.md)/[19](19-liveops.md)** — o **valor** do teto diário e da janela de pausa
  e a **mecânica** da Chama (a 13 só dá o *framing*).
- **Seção [07](07-ux-fluxos-navegacao.md)** — a **superfície**/posição das telas e da tela de preferências.
- **Seção [10](10-professor-familia.md)** — a **superfície** dos portais adultos (teto/pausa/horário) e a
  **aplicação** do invariante "push só a adultos".
- **Seção [11](11-arquitetura.md)** — render híbrido, piso de desempenho e o **mecanismo** de reforço no servidor.
- **Seção [15](15-arte-audio-assets.md)** — os **valores** de paleta/contraste e a **estratégia** de áudio.
- **Seção [17](17-telemetria-metricas.md)** — as **métricas** de uso saudável (sem expor ranking individual à criança).

**Alimenta:**
- **Todas as seções de tela** — o **checklist de conformidade** (§14) é **gate de publicação**; a
  Seção [07](07-ux-fluxos-navegacao.md) já cita a 13 como fonte.
- **Seção [09](09-social.md)** — a norma de **ranking saudável** (eu×eu, sem individual exposto).
- **Seção [10](10-professor-familia.md)** — a norma-fonte de bem-estar que a 10 materializa.
- **Seções [04](04-personagens-avatar.md)/[05](05-sistemas-de-jogo.md)** — a exigência de **declarar
  acessibilidade** no contrato de cada mecânica/item.

**O que quebra se mudar:** se a 13 fixar um **número de alvo diferente de 48px** (ou uma lista de norma
diferente), as menções cravadas em [01](01-principios-imutaveis.md)/[04](04-personagens-avatar.md)/[06](06-pedagogico-bncc.md)
**divergem silenciosamente**. Por isso a 13 **mantém 48px** e registra a **convergência** das cópias como
cross-fix pendente (§15) — a aplicar **sob autorização**, não neste commit.

### 12. Casos extremos (Edge Cases)
- **Áudio não pode tocar** (dispositivo no mudo, *autoplay* bloqueado, sem alto-falante) → **fallback visual+gesto**
  (N17): o equivalente visual sincronizado guia sozinho; indicador "toque para ouvir". *Resolve o gap `INDICE.md:2029`.*
- **Hardware fraco** (abaixo/no piso da Seção [11](11-arquitetura.md)) → **degradação graciosa**: menos
  partículas, animação simplificada, personagem em modo leve; **feedback essencial permanece** (⚠️ 13.29; ladder
  proposto — §15).
- **`prefers-reduced-motion` ativo + item especial 3D** (ex.: invocação do Skate) → **revelação estática**, sem
  câmera/partículas (a norma N7 vale mesmo nos momentos "mágicos").
- **Daltonismo severo** → redundância sempre ativa (N6); o modo daltônico reforça (tipos/método → §15; paletas =
  Seção [15](15-arte-audio-assets.md)).
- **Não-leitor absoluto** → o áudio + ícone conduzem 100% do fluxo; nenhuma etapa exige leitura.
- **Tela muito pequena/grande** → alvos ≥48px e ≤1 ação primária preservam a usabilidade; tamanho de fonte
  ajustável ajuda a baixa visão.
- **Conexão fraca/offline** → narração local (síntese no dispositivo), sem travar por rede.
- **Criança volta após dias** → a **Chama** tem escudo semanal que perdoa faltas; ao resetar, mensagem gentil e
  recomeço acolhedor (mecânica = Seção [05](05-sistemas-de-jogo.md)) — **sem mensagem que envergonhe** (nada de "você perdeu tudo").
- **Teto atingido** → celebração + convite para amanhã (nunca "pague/espere").
- **Fora do horário permitido** → bloqueio **gentil no servidor** (mensagem carinhosa; superfície = Seção [10](10-professor-familia.md)).
- **Criança ansiosa** → nenhuma contagem regressiva punitiva; o erro é acolhido (P6).

### 13. Escalabilidade futura
- **Suporte assistivo estendido** — leitor de tela, **navegação por teclado completa** (Chromebook) e
  *switch-access* como **fase futura** (⚠️ 13.19); o público primário hoje é o **não-leitor via áudio**, então
  o leitor de tela é secundário na priorização.
- **Novos idiomas** — a acessibilidade viaja com a **localização** (Seção [16](16-localizacao-i18n.md)). Estender
  o **áudio obrigatório** a outros idiomas colide com **P9** (áudio *sempre* pt-BR, imutável) e exige um **ADR**
  do dono referenciando P9 — decisão de [01](01-principios-imutaveis.md)/[16](16-localizacao-i18n.md), **não** da 13.
- **Libras / audiodescrição** — ganchos previstos para acessibilidade sensorial ampliada.
- **Ajuste fino por perfil** — mais preferências (contraste alto, fonte para dislexia) entram na **mesma
  whitelist** sem reescrita.
- **Auditoria automatizada** — o gate de contraste/alvo pode migrar para o **CI** (Seção [18](18-qa-testes.md)),
  além do check manual por tela.

### 14. Checklist de implementação
**A — Gate por tela (13.31) — "pronto quando" (implementa o piso WCAG 2.1 AA — N2; liga ao Apêndice F):**
- [ ] **Áudio** pt-BR presente em toda instrução **+ "ouvir de novo"** visível (N4).
- [ ] **Navegação por ícone + cor + áudio** — todo destino "fala" o que é ao foco/toque (N5).
- [ ] **Fallback visual** sincronizado guia sozinho quando o áudio não toca (N17).
- [ ] **Alvos ≥ 48px** (espaçamento ≥ 8 px — ⚠️ §15); **≤ 1 ação primária** na tela (N9).
- [ ] **Contraste** atende ao limiar **N3** (proposta 4.5:1 / 3:1 — ⚠️ §15) — **medido**, não "no olho".
- [ ] **Cor com redundância** (forma/ícone/rótulo/áudio); **[quando N6 fixar tipos/método]** testado no modo daltônico.
- [ ] **`prefers-reduced-motion`** respeitado, com **fallback estático**; **[quando cabeado — ADR-13-C/13.15]** o toggle `reduzir_animacoes` também.
- [ ] **Nenhum dark pattern**; **erro acolhido** (P6); **tempo não** é critério único.
- [ ] **Nenhuma notificação/push** disparada à criança (N12).
- [ ] **[quando N11 ratificado — §15]** a tela respeita o **tamanho de fonte** escolhido; o texto não corta/transborda (N11).

**B — Gate por build/fluxo (não por tela):**
- [ ] **Playtest com não-leitor** — a criança completa o **fluxo** sem ajuda de leitura.
- [ ] **Playtest com som desligado** — a criança completa o fluxo **só pelo fallback visual** (N17; exercita o caminho som-off).
- [ ] Preferências `musica`/`reduzir_animacoes` **acionam de fato** (não órfãs) — ADR-13-C.
- [ ] **Degrada** em hardware no piso da Seção [11](11-arquitetura.md) preservando o feedback essencial (⚠️ 13.29).

> **Bem-estar (N13/N14/N15):** o teto, a pausa e o horário são **gated na Seção [10](10-professor-familia.md)**
> (superfície adulta) e reforçados no servidor — não são itens de gate por tela aqui.

### 15. Questões em aberto
Cada item abaixo é **decisão do dono** (⚠️); os defaults são **propostas** da 13, não decisões autônomas:

- ⚠️ **13.15 — Preferências órfãs (`musica`, `reduzir_animacoes`).** Proposta: **cabear à UI/função** (o salvo
  força *reduced-motion* / liga a música), **mantendo** os campos no modelo. Alternativa: removê-los. Impacto
  cross-módulo → **ADR-13-C** (pendência `INDICE` 13.15 / ADR C.24). *(A norma N7 e o gate §14 assumem o caminho
  recomendado — cabear; se a decisão for remover, N7/§14 são ajustados.)*
- ⚠️ **N1 — Espaçamento entre alvos.** Proposta: **≥ 8 px** entre alvos de toque (além do alvo ≥48px). Confirmar
  o valor / token.
- ⚠️ **N2 — Nível WCAG.** Proposta: **WCAG 2.1 AA** como piso + AAA seletivo. Nenhuma fonte declara nível hoje;
  precisa ratificação (é baseline normativo novo).
- ⚠️ **N3 — Contraste mínimo.** Proposta: **4.5:1 / 3:1**. Os **valores de paleta** que satisfazem isso são da
  Seção [15](15-arte-audio-assets.md).
- ⚠️ **N6 — Modo daltônico.** A **existência** é fixada por P11; em aberto os **tipos** cobertos
  (deuteranopia/protanopia/tritanopia) e o **método** (troca de paleta, padrões/texturas, ou ambos).
- ⚠️ **N11 — Tamanho de fonte ajustável.** Confirmar se entra como **preferência de perfil** e os **passos/limites**
  (proposta: padrão / grande / muito-grande).
- ⚠️ **13.19 — Suporte assistivo estendido.** Escopo e **fase** de leitor de tela / navegação por teclado /
  *switch-access* (proposta: fase futura; não-leitor via áudio é o público primário).
- ⚠️ **13.20 — Valor do teto diário.** A 13 **só referencia**; o **valor** é das Seções [05](05-sistemas-de-jogo.md)/[19](19-liveops.md)
  (05.7). Confirmar o valor de referência. (Recorte família↔escola de quem configura teto/pausa: Seção [10](10-professor-familia.md).)
- ⚠️ **13.21 — Lembrete de pausa.** Proposta de default: **40 min**, configurável (valor = Seção [19](19-liveops.md)).
- ⚠️ **13.26 — Horário permitido.** A **família define a janela** já está **decidido** (Seção [10](10-professor-familia.md) §9);
  em aberto só a **forma** (janela livre × faixas fixas). *(O papel da escola no horário, se houver, é decisão
  da Seção [10](10-professor-familia.md), dona da superfície adulta — não questão da 13.)*
- ⚠️ **13.29 — Degradação em hardware fraco.** Confirmar o **ladder** de degradação (partículas → animação →
  modo leve), ancorado no piso da Seção [11](11-arquitetura.md) (11.48).
- **Cross-fix pendente (não aplicado neste commit):** convergir o número **≥48px** e a **lista da norma**
  cravados em [01](01-principios-imutaveis.md)/[04](04-personagens-avatar.md)/[06](06-pedagogico-bncc.md) para
  **citarem a 13** (a Seção [07](07-ux-fluxos-navegacao.md) já fez). Aplicar **sob autorização explícita**.

### 16. ADR (Architecture Decision Record)
- **ADR-13-A — Piso de conformidade.** WCAG 2.1 AA como piso, com critérios AAA seletivos onde servem ao
  não-leitor (áudio de instrução excede AA). Contraste 4.5:1 / 3:1. *Pendente de ratificação (§15 · N2/N3).*
- **ADR-13-B — Áudio obrigatório com fallback visual.** Toda instrução em áudio pt-BR tem um **equivalente
  visual sincronizado** capaz de guiar sozinho quando o som não pode tocar; resolve o gap `INDICE.md:2029`.
- **ADR-13-C — Cabear as preferências órfãs.** `musica` e `reduzir_animacoes` (e futuras: daltônico, fonte)
  passam a **acionar de fato** a experiência, mantidas na whitelist do modelo — **não** removidas. *Cross-módulo:
  liga-se à pendência `INDICE` 13.15 / ADR C.24; formaliza-se ao aprovar a seção.*
- **ADR-13-D — A 13 é a fonte canônica única do piso.** O número do alvo (≥48px), a lista da norma e o
  *framing* de bem-estar têm **um único dono** (a 13); as demais seções **aplicam** e **citam**. A convergência
  das cópias existentes é cross-fix registrado em §15.

*Decisões cross-módulo não são improvisadas aqui: as pendências acima viram ADR ou item de §15.*

---

## 🇬🇧 Accessibility & Well-being

### 1. Objective
To be the **definitive reference for accessibility and well-being** in Constela Quest: the **single norm** that
guarantees that **any child** — age 6, non-reader, low-vision, colorblind, with motor difficulty, or on a weak
school tablet — plays **with autonomy and dignity**, and that play time stays **healthy, never compulsive**. It
lets us build **without re-deciding the floor** on every screen and **without improvising a well-being rule**.
It decides the **norm** (the mandatory accessibility floor + the well-being *framing*); it does **not** decide
the **values** (cap/pause → Sections [05](05-sistemas-de-jogo.md)/[19](19-liveops.md); palette/contrast →
Section [15](15-arte-audio-assets.md)), the **surface** of screens (Section [07](07-ux-fluxos-navegacao.md)),
nor the technical **medium** (render → Section [11](11-arquitetura.md); synthesized vs recorded audio →
Section [15](15-arte-audio-assets.md)).

### 2. Context
In the **Hub → Edu → Quest** ecosystem, Quest is the **children's game** (grades 1–5, ages 6–11). Much of the
audience **does not yet read fluently** — in grade 1 the **default** child is a **non-reader**. Accessibility
here is therefore **not an optional feature**: it is the condition for the product to exist. Today the norm
lives only as **Principle 11** ([01](01-principios-imutaveis.md):47-49) and appears **re-derived and duplicated**
across 5+ sections; Section [07](07-ux-fluxos-navegacao.md) already made the **model move** (dropped the number,
cited 13, "without setting its own thresholds"). This section **takes authority**: it fixes the floor **before
the copies drift**.

**Current state (Q0) — partial and uneven:**
- **Touch target** — the `--alvo-minimo: 48px` token exists (`tokens.css:39`) and is applied via
  `var(--alvo-minimo)` on `.botao3d` (`base.css:54`) and on the entry/lobby/wardrobe screens; **not yet audited
  per screen**.
- **Reduced-motion** — `prefers-reduced-motion: reduce` is respected **globally** (`base.css:185-187` zeroes
  animations/transitions; also checked in JS in `Cosmo.tsx` and `InvocacaoSkate.tsx`).
- **Audio/narration** — works **offline in pt-BR**, today **synthesized** (Web Speech API + WebAudio); the
  **definitive strategy** (synthesized vs professional recording) belongs to Section [15](15-arte-audio-assets.md) (15.27).
- **Preferences** — the `PREFERENCIAS_PERMITIDAS` whitelist (in `services/perfis.py`) already covers `som`,
  `narracao`, `musica` and `reduzir_animacoes`; `som`/`narracao` **are already wired** to audio by the UI
  (`Lobby.tsx`), but `musica` and `reduzir_animacoes` are **orphaned**: the interface **never reads those saved
  toggles** (it only reacts to the OS *media query*) — logged in `RELATORIO-2026-07-09.md`.
- **Gaps** — **no colorblind mode**; **contrast is not audited systematically** and has no canonical *ratio*
  (only ad-hoc notes, e.g. `entrada.css:171-172` mentions "AA contrast" and white text that failed at ~2:1); **no
  normative WCAG target** has been declared as a product standard; **well-being** (cap-as-celebration, pause,
  hours) exists as intent in [10](10-professor-familia.md) but with no **source norm** for the 10 to cite.

This chapter **fixes** the floor, **converges** the target number and the reduced-motion norm before drift, and
**anchors** the well-being citations that until now pointed to a file that did not exist.

### 3. Feature philosophy
**Accessibility is not a feature — it is the floor.** The child who **cannot yet read** is the **default** user,
not the exception; if they get stuck, the product failed. **Universal design:** what helps the child with a
disability helps **everyone** (the audio that saves the non-reader also calms the anxious child; the large
target for the small hand also serves the trembling hand).

**Well-being is the same ethic applied to time:** the game **serves** the child, it does **not** retain them. A
children's product that uses compulsion triggers — lives, forced waiting, FOMO, a *streak* that punishes absence
— betrays the trust of the school and the family. Here, **stopping is always a good goodbye**, never an abrupt
interruption or a guilt trip.

Link to the **Immutable Principles** ([01](01-principios-imutaveis.md)): **P11** (accessibility is
non-negotiable) is the core of this section; **P9** (always pt-BR audio) is its main instrument; **P6** (error
never punishes) is **emotional** accessibility; **P7** (no purchase/FOMO) and **P8** (zero *dark patterns*)
found the well-being norm. To the **4 pillars**: **autonomy** (the non-reader navigates alone), **visible
progress without anxiety**, **connection without exposure** (healthy ranking — §8), and **surprise without
compulsion**.

### 4. The experience the player should feel
**The child feels: "I can do it myself."** Never stuck, never lost, never punished for a mistake. **Cosmo** is
the **guiding voice** that reads everything aloud and repeats on "hear it again". Touch is **generous** (the
small finger always hits the target). The error is **welcomed** — "almost! let's try again" — never a red "X"
that hurts.

**When they stop, the child feels a good goodbye**, not a slammed door: the daily cap arrives as **celebration**
("you shone so much today!"), the pause arrives as **Cosmo asking to rest together**, and the family-agreed
hours appear with **kindness**, never as punishment.

**The adult** (teacher/family) feels: **"this respects my student/child."** No trick to hook the child, no
pressure, no notification reaching the child behind the adult's back.

### 5. Complete flow
Accessibility **runs through every step** — it is not a separate screen, it is a **layer** over everything:

1. **Entry / return** — a **speakable** code, **spoken** by Cosmo; large icons; no step requires reading (the
   "Is it you?" flow confirms by the **heard name**, not read text). Flow detail → Section [08](08-onboarding-ftue.md).
2. **Navigation** — always by **icon + color + audio**, never reading-only. Every destination "speaks" what it
   is on focus/tap.
3. **Activity instruction** — **mandatory pt-BR audio** on every instruction, with a **"hear it again"** control
   always visible. Text (when present) is **redundant** to the audio, never the only channel.
4. **Interaction / error** — target ≥48px; **≤1 primary action** per screen; error is **welcomed** (P6) and
   **time is never** the sole success/failure criterion (§9).
5. **Session end / pause** — the daily cap arrives as **celebration** (value = Sections [05](05-sistemas-de-jogo.md)/[19](19-liveops.md));
   Cosmo's **pause reminder** appears kindly; the **permitted hours** (if the family set them) are enforced **on
   the server** and shown with care (surface = Section [10](10-professor-familia.md)).
6. **Offline** — narration plays **locally** (on-device synthesis), independent of the network.
7. **Fallback when audio cannot play** (muted, *autoplay* blocked, no speaker) — **every** audio instruction has
   a **synchronized visual equivalent** (icon/highlight/animation pointing to the next step) able to guide
   **on its own**; a persistent **"sound off — tap to hear"** indicator invites re-enabling. The non-reader
   **never** gets stuck for lack of sound (§12; resolves gap `INDICE.md:2029`).
8. **Weak hardware** — effects **degrade gracefully** (fewer particles, simplified animation), but the
   **essential feedback** (state of right/wrong/focus/selection via color+icon+audio) **remains** (§12; floor =
   Section [11](11-arquitetura.md)).

### 6. Interface (when it exists)
Section 13 **does not draw screens** — the inventory and canonical position of screens belong to
Section [07](07-ux-fluxos-navegacao.md). What stays here are only the **existence requirements** for
accessibility surfaces:
- **"Hear it again" control** — present and visible on every instruction with audio.
- **"Sound off — tap to hear" indicator** — persistent when audio is muted/blocked.
- **Accessibility preferences screen** — exposes, at minimum: `musica` (on/off), `reduzir_animacoes` (on/off),
  **colorblind mode** (existence fixed by P11; types/method → §15) and **font size** (§15 ⚠️). The **position**
  and design of that screen are Section [07](07-ux-fluxos-navegacao.md)'s; the **requirement** that it exists and
  **actually drives** the preferences is 13's (today `musica`/`reduzir_animacoes` are **orphaned** — §2/§10/ADR-13-C).
- **Adult well-being surfaces** (cap/pause/hours) — design and position are Section [10](10-professor-familia.md)'s;
  13 only defines the **norm** they materialize.

### 7. UX
Section 13 **owns the accessible "how it feels".** Experience rules:
- **pt-BR audio first** — Cosmo's voice is the main channel; text accompanies, never leads. Vocabulary always
  the canonical one from Section [02](02-vocabulario.md) (no forbidden UI word).
- **Unhurried pace** — no punishing countdown; **time is never** the sole criterion (§9).
- **Immediate, multisensory feedback** — every state (right, wrong, focus, selection) is signaled by **color +
  icon/shape + audio** at once (redundancy — never color alone).
- **Error prevention** — ≤1 primary action per screen; large, spaced targets; spoken confirmations.
- **Visible focus** — every interactive element shows clear **focus** (for touch and, in the future phase,
  keyboard — §13).

### 8. Game Design
How accessibility and well-being **shape the mechanics** (the mechanics themselves are Sections [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)'s):
- **Time is never the sole criterion** — speed may give a bonus, **never** decide success/failure alone
  (children with motor or cognitive difficulty are not penalized).
- **Daily cap = celebration, not block** — on reaching the cap the child is **congratulated** and invited back
  tomorrow; there is **no** "you're out, pay/wait" screen. The framing derives from **P6**; the cap **value** is
  Sections [05](05-sistemas-de-jogo.md)/[19](19-liveops.md)'s (ref: 05.7).
- **Gentle Flame, always for the child** — the streak is the **Cosmo's Flame**, with a **weekly shield** that
  forgives absences and a weekend that does not break it (mechanic = Section [05](05-sistemas-de-jogo.md)). The
  13 **well-being norm**: the Flame **never shames** and is **always recoverable** — if it resets, it is with a
  **gentle message and a warm restart** (a child who missed due to illness/holidays is welcomed back, never punished).
- **Healthy ranking** — **me × me** comparison (my progress) and a class ranking that **zeroes every week**
  (cadence fixed by **P5**, [01](01-principios-imutaveis.md):31-33); **never** an individual ranking exposed to
  the child (invariant of P5; mechanics in Section [09](09-social.md)).
- **No compulsion triggers** — **no lives, no forced waiting, no paywall, no aggressive FOMO** (P7);
  **zero dark patterns** (P8).
- **Every pluggable mechanic declares accessibility** — each new activity type **must declare**, in its
  contract, how it meets the norm (audio, target, color redundancy, *reduced-motion*). The **requirement** is
  13's; the contract **format** is Sections [11](11-arquitetura.md)/[05](05-sistemas-de-jogo.md)'s.

### 9. Business rules
The **deterministic norms** of this section (the single source; any copy in another section is **application**,
not re-decision):

| # | Norm | Value / Rule | Value owner |
|---|------|--------------|-------------|
| N1 | **Minimum touch target** | **≥ 48×48 px**, with **≥ 8 px spacing** between targets (⚠️ §15) | 13 (converges `tokens.css:39`) |
| N2 | **Conformance level** | **WCAG 2.1 AA** floor, with selective AAA where it serves the non-reader (instruction audio exceeds AA) | 13 ⚠️ (ratify) |
| N3 | **Minimum contrast** | **4.5:1** normal text · **3:1** large text and UI components | 13 ⚠️ (ratify); palette values = Section [15](15-arte-audio-assets.md) |
| N4 | **Instruction audio** | **mandatory in pt-BR** on every instruction + **"hear it again"** on demand | 13 (P9); **medium** (synth × recorded) = Section [15](15-arte-audio-assets.md) |
| N5 | **Navigation** | **icon + color + audio** — never reading-only | 13 |
| N6 | **Color never the sole channel** | all color-coded info has **redundancy** (shape/icon/label/audio); **colorblind mode** reinforces (existence fixed by P11; types/method → §15; palettes = Section [15](15-arte-audio-assets.md)) | 13 ⚠️ (types/method) |
| N7 | **Reduced-motion** | respect `prefers-reduced-motion` (already active) and, **once wired** (ADR-13-C / 13.15), the `reduzir_animacoes` toggle; **mandatory static fallback** on every animation (what reduces/remains — below) | 13 |
| N8 | **Time** | **never** the sole success/failure criterion | 13 |
| N9 | **Primary action** | **≤ 1 per screen** — *primary action* = the single destination/command that advances the screen's main flow (the rest are secondary/support) | 13 (07 applies) |
| N10 | **Error** | **welcomed, never punishment** (P6) | 13 + [01](01-principios-imutaveis.md) |
| N11 | **Font size** | **adjustable** (profile preference; default/large/x-large steps) | 13 ⚠️ (ratify) |
| N12 | **Push to the child** | **never** — notifications only to adults (invariant) | 13 (source); [10](10-professor-familia.md) applies |
| N13 | **Daily cap** | **celebration, not block** (norm); value = Sections [05](05-sistemas-de-jogo.md)/[19](19-liveops.md) | 13 (norm, derives from P6) + [01](01-principios-imutaveis.md) |
| N14 | **Pause reminder** | gentle, from Cosmo; **configurable** interval (value/default = Section [19](19-liveops.md); proposal in §15) | 13 ⚠️ (value = Section [19](19-liveops.md)) |
| N15 | **Permitted hours** | enforced **on the server**, shown kindly; the **family sets the window** (decided in Section [10](10-professor-familia.md) §9); open only the **form** (free window × fixed bands) — §15 13.26 | 13 (norm) |
| N16 | **Dark patterns** | **zero** across the whole experience — including the adult well-being surfaces 13 governs (P8) | 13 + [01](01-principios-imutaveis.md) |
| N17 | **Audio fallback** | when audio cannot play, a **synchronized visual equivalent** guides alone + "tap to hear" indicator | 13 |

**Reduced-motion — what reduces and what remains (N7):**
- **Reduces / becomes static:** *parallax*, orbital camera, ambient particles, large character *idle
  animations*, long zoom/slide, the **cinematic invocation** of the special item (becomes a **static reveal**),
  decorative *bounces*/shakes, *autoplay* background motion.
- **Remains (in non-vestibular form):** the **essential** state feedback (right/wrong/focus/selection) via
  **color + icon + audio** with a short opacity transition; **visible focus**; screen change by a **simple cut**
  instead of a long slide. *Nothing essential disappears with reduced-motion — only decorative motion does.*

**Server × client:** **hours** and **cap** are enforced **on the server** (mechanism = Sections [10](10-professor-familia.md)/[11](11-arquitetura.md));
the **accessibility norm** is the **client's** responsibility, verified by the **publication gate** (§14) — the
server does not "audit contrast".

### 10. Technical architecture
Section 13 **owns no endpoints and no data model** (contracts → Appendix B). Where the norm **touches** code:
- **Profile preferences** — the `PREFERENCIAS_PERMITIDAS` whitelist lives in `services/perfis.py` (the JSON
  `preferencias` column is in `models/perfil.py`; the schema in `schemas.py`; the endpoint that applies it in
  `routers/perfil.py`). `musica` and `reduzir_animacoes` already exist in the whitelist, yet **orphaned**: the UI
  only reads the OS *media query*. Section 13 **decides to wire** those toggles to their function (the saved
  value **forces** *reduced-motion* / turns music on), **keeping** the fields in the model — not removing them
  (ADR-13-C; pending `INDICE` 13.15 / ADR C.24). If **colorblind mode** and **font size** become preferences
  (⚠️ §15), they join the **same whitelist**.
- **Audio** — Section 13 **requires** the result (pt-BR, intelligible, "hear it again", visual fallback); the
  **medium** (Web Speech synthesis × professional recording) is Section [15](15-arte-audio-assets.md)'s decision
  (15.27). Today it is **synthesized**; 13 does not lock the medium, only the result.
- **Render / degradation** — the **hybrid** render and the **performance floor** are Section [11](11-arquitetura.md)'s;
  13 defines **that** effects degrade while preserving essential feedback (§12), but the technical **how** and
  the target device are 11's (11.48).
- **Mechanic contract** — the requirement "each mechanic declares accessibility" adds **declaration fields** to
  the activity contract (format = Sections [11](11-arquitetura.md)/[05](05-sistemas-de-jogo.md)).

### 11. Dependencies on other modules
**Consumes:**
- **Section [01](01-principios-imutaveis.md)** — P6/P7/P8/P9/P11 (the beliefs this section operationalizes).
- **Sections [05](05-sistemas-de-jogo.md)/[19](19-liveops.md)** — the **value** of the daily cap and pause
  window and the **Flame** mechanic (13 only provides the *framing*).
- **Section [07](07-ux-fluxos-navegacao.md)** — the **surface**/position of screens and the preferences screen.
- **Section [10](10-professor-familia.md)** — the **surface** of the adult portals (cap/pause/hours) and the
  **application** of the "push to adults only" invariant.
- **Section [11](11-arquitetura.md)** — hybrid render, performance floor and the server-side enforcement
  **mechanism**.
- **Section [15](15-arte-audio-assets.md)** — the palette/contrast **values** and the audio **strategy**.
- **Section [17](17-telemetria-metricas.md)** — the healthy-usage **metrics** (without exposing an individual
  ranking to the child).

**Feeds:**
- **All screen sections** — the **conformance checklist** (§14) is a **publication gate**;
  Section [07](07-ux-fluxos-navegacao.md) already cites 13 as source.
- **Section [09](09-social.md)** — the **healthy-ranking** norm (me×me, no exposed individual).
- **Section [10](10-professor-familia.md)** — the source well-being norm that 10 materializes.
- **Sections [04](04-personagens-avatar.md)/[05](05-sistemas-de-jogo.md)** — the requirement to **declare
  accessibility** in each mechanic/item contract.

**What breaks if it changes:** if 13 sets a **target number other than 48px** (or a different norm list), the
hardcoded mentions in [01](01-principios-imutaveis.md)/[04](04-personagens-avatar.md)/[06](06-pedagogico-bncc.md)
**drift silently**. That is why 13 **keeps 48px** and logs the **convergence** of the copies as a pending
cross-fix (§15) — to apply **under authorization**, not in this commit.

### 12. Edge cases
- **Audio cannot play** (muted device, *autoplay* blocked, no speaker) → **visual+gesture fallback** (N17): the
  synchronized visual equivalent guides alone; "tap to hear" indicator. *Resolves gap `INDICE.md:2029`.*
- **Weak hardware** (at/below Section [11](11-arquitetura.md)'s floor) → **graceful degradation**: fewer
  particles, simplified animation, light character mode; **essential feedback remains** (⚠️ 13.29; proposed
  ladder — §15).
- **`prefers-reduced-motion` active + 3D special item** (e.g. Skate invocation) → **static reveal**, no
  camera/particles (norm N7 holds even in the "magic" moments).
- **Severe colorblindness** → redundancy always on (N6); colorblind mode reinforces (types/method → §15;
  palettes = Section [15](15-arte-audio-assets.md)).
- **Absolute non-reader** → audio + icon drive 100% of the flow; no step requires reading.
- **Very small/large screen** → ≥48px targets and ≤1 primary action preserve usability; adjustable font size
  helps low vision.
- **Weak/offline connection** → local narration (on-device synthesis), no network stall.
- **Child returns after days** → the **Flame** has a weekly shield that forgives absences; if it resets, a gentle
  message and a warm restart (mechanic = Section [05](05-sistemas-de-jogo.md)) — **no shaming message** (never "you lost everything").
- **Cap reached** → celebration + invitation for tomorrow (never "pay/wait").
- **Outside permitted hours** → **gentle server-side** block (caring message; surface = Section [10](10-professor-familia.md)).
- **Anxious child** → no punishing countdown; the error is welcomed (P6).

### 13. Future scalability
- **Extended assistive support** — screen reader, **full keyboard navigation** (Chromebook) and *switch-access*
  as a **future phase** (⚠️ 13.19); the primary audience today is the **non-reader via audio**, so the screen
  reader is secondary in prioritization.
- **New languages** — accessibility travels with **localization** (Section [16](16-localizacao-i18n.md)).
  Extending the **mandatory audio** to other languages collides with **P9** (audio *always* pt-BR, immutable)
  and requires an owner **ADR** referencing P9 — a decision of [01](01-principios-imutaveis.md)/[16](16-localizacao-i18n.md),
  **not** 13's.
- **Libras (sign language) / audio description** — foreseen hooks for broader sensory accessibility.
- **Per-profile fine-tuning** — more preferences (high contrast, dyslexia font) join the **same whitelist**
  without a rewrite.
- **Automated auditing** — the contrast/target gate can move to **CI** (Section [18](18-qa-testes.md)), on top
  of the per-screen manual check.

### 14. Implementation checklist
**A — Per-screen gate (13.31) — "done when" (implements the WCAG 2.1 AA floor — N2; links to Appendix F):**
- [ ] **pt-BR audio** on every instruction **+ "hear it again"** visible (N4).
- [ ] **Navigation by icon + color + audio** — every destination "speaks" what it is on focus/tap (N5).
- [ ] **Synchronized visual fallback** guides alone when audio cannot play (N17).
- [ ] **Targets ≥ 48px** (≥ 8 px spacing — ⚠️ §15); **≤ 1 primary action** on the screen (N9).
- [ ] **Contrast** meets the **N3** threshold (proposal 4.5:1 / 3:1 — ⚠️ §15) — **measured**, not "by eye".
- [ ] **Color with redundancy** (shape/icon/label/audio); **[once N6 fixes types/method]** tested in colorblind mode.
- [ ] **`prefers-reduced-motion`** respected, with **static fallback**; **[once wired — ADR-13-C/13.15]** the `reduzir_animacoes` toggle too.
- [ ] **No dark pattern**; **error welcomed** (P6); **time not** the sole criterion.
- [ ] **No notification/push** fired to the child (N12).
- [ ] **[once N11 is ratified — §15]** the screen honors the chosen **font size**; text does not clip/overflow (N11).

**B — Per-build/flow gate (not per-screen):**
- [ ] **Playtest with a non-reader** — the child completes the **flow** without reading help.
- [ ] **Playtest with sound off** — the child completes the flow **through the visual fallback only** (N17; exercises the sound-off path).
- [ ] `musica`/`reduzir_animacoes` preferences **actually take effect** (not orphaned) — ADR-13-C.
- [ ] **Degrades** on hardware at Section [11](11-arquitetura.md)'s floor while preserving essential feedback (⚠️ 13.29).

> **Well-being (N13/N14/N15):** the cap, the pause and the hours are **gated in Section [10](10-professor-familia.md)**
> (adult surface) and enforced on the server — they are not per-screen gate items here.

### 15. Open questions
Each item below is a **owner decision** (⚠️); the defaults are 13's **proposals**, not autonomous decisions:

- ⚠️ **13.15 — Orphaned preferences (`musica`, `reduzir_animacoes`).** Proposal: **wire to UI/function** (the
  saved value forces *reduced-motion* / turns music on), **keeping** the fields in the model. Alternative:
  remove them. Cross-module impact → **ADR-13-C** (pending `INDICE` 13.15 / ADR C.24). *(Norm N7 and the §14 gate
  assume the recommended path — wiring; if the decision is to remove, N7/§14 are adjusted.)*
- ⚠️ **N1 — Spacing between targets.** Proposal: **≥ 8 px** between touch targets (on top of the ≥48px target).
  Confirm the value / token.
- ⚠️ **N2 — WCAG level.** Proposal: **WCAG 2.1 AA** floor + selective AAA. No source declares a level today;
  needs ratification (it is a new normative baseline).
- ⚠️ **N3 — Minimum contrast.** Proposal: **4.5:1 / 3:1**. The **palette values** that satisfy it are
  Section [15](15-arte-audio-assets.md)'s.
- ⚠️ **N6 — Colorblind mode.** **Existence** is fixed by P11; open are the **types** covered
  (deuteranopia/protanopia/tritanopia) and the **method** (palette swap, patterns/textures, or both).
- ⚠️ **N11 — Adjustable font size.** Confirm whether it becomes a **profile preference** and the **steps/limits**
  (proposal: default / large / x-large).
- ⚠️ **13.19 — Extended assistive support.** Scope and **phase** of screen reader / keyboard navigation /
  *switch-access* (proposal: future phase; non-reader via audio is the primary audience).
- ⚠️ **13.20 — Daily cap value.** Section 13 **only references** it; the **value** is Sections [05](05-sistemas-de-jogo.md)/[19](19-liveops.md)'s
  (05.7). Confirm the reference value. (Family↔school split of who configures cap/pause: Section [10](10-professor-familia.md).)
- ⚠️ **13.21 — Pause reminder.** Proposed default: **40 min**, configurable (value = Section [19](19-liveops.md)).
- ⚠️ **13.26 — Permitted hours.** The **family sets the window** is already **decided** (Section [10](10-professor-familia.md) §9);
  open only the **form** (free window × fixed bands). *(The school's role in the hours, if any, is a
  Section [10](10-professor-familia.md) decision — owner of the adult surface — not a 13 question.)*
- ⚠️ **13.29 — Weak-hardware degradation.** Confirm the degradation **ladder** (particles → animation → light
  mode), anchored to Section [11](11-arquitetura.md)'s floor (11.48).
- **Pending cross-fix (not applied in this commit):** converge the **≥48px** number and the **norm list**
  hardcoded in [01](01-principios-imutaveis.md)/[04](04-personagens-avatar.md)/[06](06-pedagogico-bncc.md) to
  **cite 13** (Section [07](07-ux-fluxos-navegacao.md) already did). Apply **under explicit authorization**.

### 16. ADR (Architecture Decision Record)
- **ADR-13-A — Conformance floor.** WCAG 2.1 AA as the floor, with selective AAA criteria where they serve the
  non-reader (instruction audio exceeds AA). Contrast 4.5:1 / 3:1. *Pending ratification (§15 · N2/N3).*
- **ADR-13-B — Mandatory audio with visual fallback.** Every pt-BR audio instruction has a **synchronized visual
  equivalent** able to guide alone when sound cannot play; resolves gap `INDICE.md:2029`.
- **ADR-13-C — Wire the orphaned preferences.** `musica` and `reduzir_animacoes` (and future: colorblind, font)
  now **actually drive** the experience, kept in the model whitelist — **not** removed. *Cross-module: ties to
  the pending `INDICE` 13.15 / ADR C.24; formalized on section approval.*
- **ADR-13-D — Section 13 is the single canonical source of the floor.** The target number (≥48px), the norm
  list and the well-being *framing* have **one owner** (13); other sections **apply** and **cite**. The
  convergence of existing copies is a cross-fix logged in §15.

*Cross-module decisions are not improvised here: the pending items above become an ADR or a §15 entry.*
