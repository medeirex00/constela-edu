# 23 — Roadmap & Fases (Q0–Q6) / Roadmap & Phases (Q0–Q6)

- **Status:** 🟢 aprovado / approved
- **Padrão / Standard:** [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) (16 partes)
- **Fontes / Sources:** `INDICE.md` (bloco 23, subseções 23.1–23.20 + 6 ⚠️), **`docs/quest/05-roadmap.md`** (as 7 fases em prosa — fonte primária a espelhar), `_estado-atual/RELATORIO-2026-07-09.md` (§2, o placar honesto 🟢/🟡/⬛ por Q; "apenas a Fase Q0 está em código e produção"), e o **código Q0** — que confirma a linha de base: `backend/app/quest/routers/` tem **exatamente 3 roteadores** (`auth.py` login código-só, `perfil.py` cosmético, `professor.py` cartões/acessos); os models `catalogo.py`/`progresso.py` (grupos 1–3) **existem sem rota** (esquema pronto ≠ capacidade entregue); `backend/app/main.py` monta **tudo num monólito modular único** (15 roteadores Edu + os 3 Quest); Seções [00](00-visao-e-norte.md)/[05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)/[09](09-social.md)/[10](10-professor-familia.md)/[11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)/[17](17-telemetria-metricas.md)/[19](19-liveops.md)/[22](22-monetizacao.md), Apêndice F
- **Depende de / Depends on:** princípios (P6 erro nunca pune · P7 passe gratuito) → [01](01-principios-imutaveis.md); a **régua de corte afetiva** e a visão de lançamento → [00](00-visao-e-norte.md); o **loop de jogo** e a **mecânica** que cada fase entrega → [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md); a **regra social** (Q4) → [09](09-social.md); o **contrato adulto** (Q3) → [10](10-professor-familia.md); o **caminho de escala A→B→C** (desenho) → [11](11-arquitetura.md) e a **operação** (gatilho do Redis, réplicas) → [14](14-infra-deploy-dr.md); os **alvos** D1/D7/D30 do gate de saída → [17](17-telemetria-metricas.md); a **fase da cobrança** → [22](22-monetizacao.md); os **valores** de config/operação do passe → [19](19-liveops.md); os **checklists de DoD por fase** → Apêndice F.

> **Convenção / Convention:** "§N" = uma das 16 **partes deste capítulo** / one of the 16 **parts of this
> chapter**; "Seção NN" / "Section NN" = outro capítulo da Bible; "23.NN" = uma subseção do plano do `INDICE.md`.
> **⚠️ Desambiguação de rótulo:** "**Q0…Q6**" são as **FASES do roadmap** (dono = esta Seção 23). Não confundir com
> "**Q1…Q14**" da Seção [18](18-qa-testes.md), que são **normas de QA** — esquema numérico independente.
> **Escopo / Scope:** este capítulo é o **mapa de QUANDO** — ordena no tempo (fases Q0→Q6) as capacidades que as
> **outras seções** documentam, com um **placar honesto** de pronto-vs-planejado fiel ao estado real (só Q0 em
> produção). Ele **decide a sequência e o critério de corte de cada fase**; **não** redefine o **conteúdo** de
> nenhuma seção (a mecânica é da [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md), a arquitetura da
> [11](11-arquitetura.md), a infra da [14](14-infra-deploy-dr.md), o social da [09](09-social.md), a cobrança da
> [22](22-monetizacao.md)) — apenas os **agenda** e **referencia**. Os DoD por fase descem para o **Apêndice F**.

---

## 🇧🇷 Roadmap & Fases (Q0–Q6)

### 1. Objetivo
Ser o **mapa temporal** do Constela Quest: documentar as **7 fases (Q0–Q6)**, cada uma **entregável e usável em
produção**, com objetivo, escopo, **critério de corte** ("uma criança real usa e quer voltar amanhã?") e um **placar
honesto** de pronto-vs-planejado. Decide **a sequência e quando** cada capacidade sai do papel; **não** redefine o
**conteúdo** de cada seção (mecânica = [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md), arquitetura =
[11](11-arquitetura.md), cobrança = [22](22-monetizacao.md)) — apenas os **ordena**. Alimenta o **Apêndice F**.

### 2. Contexto
O produto é **Hub → Edu → Quest**. **Estado atual (Q0) — só a fundação está em produção; o jogo ainda não existe:**
- **Quest tem exatamente 3 roteadores** (verificado em `backend/app/quest/routers/`): **login código-só**
  (`auth.py`: `/quem`, `/entrar`, `/entrar-qr`); **perfil cosmético** (`perfil.py`: ler perfil/cores/aparência/
  personagens; trocar nome/avatar/preferências com whitelist); **lado professor** (`professor.py`: situação de
  acesso da turma, cartões PDF/QR). **Nenhuma** rota de jogo.
- **O loop de jogo NÃO existe** — não há rota que **sirva missão/desafio**, **submeta tentativa** ou **grave
  progresso**. As tabelas `quest_*` (mundo/jornada/missão/desafio, progresso/tentativa/habilidade) **existem sem
  rota** — **esquema pronto ≠ capacidade entregue**.
- **Economia gasta, social, passe/temporada, portal da família, monetização** — **todos aspiracionais** (nenhuma
  rota; economia/social/temporada nem têm tabela). O `ResponsavelAluno` é modelado **sem** roteador.
- **O que É Q0** — o **backend Edu completo** (15 roteadores: escolas/alunos/turmas, importação Matific/Elefante,
  ranking, relatórios, backup/restauração), a **infra madura** (observabilidade, health, `/metrics` Prometheus), e o
  **PWA** do aluno (login, lobby de 3 abas, vestiário, **avatar humanoide 3D** Three.js/R3F, mascote Cosmo, áudio
  pt-BR sintetizado offline). **Q0 parcial (🟡):** bug de conquista na Carreira; catálogos cosméticos com endpoint
  mas não consumidos; o modelo de jogo sem endpoint.
- **Arquitetura hoje** — um **monólito modular único** (`main.py` monta tudo); a extração por serviço é **marco
  futuro condicionado a escala**, sem código.

Este capítulo **espelha** o roadmap-fonte (`docs/quest/05-roadmap.md`), **crava** a régua de corte e **registra** o
que falta o dono decidir.

### 3. Filosofia da funcionalidade
**"Cada fase é um jogo inteiro, pequeno — nunca uma versão pela metade."** O roadmap é sequenciado para **entregar
valor usável em produção a cada fase**, e **nenhuma fase reescreve a anterior** (o banco e as fronteiras das Seções
[01](01-principios-imutaveis.md)/[02](02-vocabulario.md) já comportam todas). Princípios do roadmap: a **régua de
corte é afetiva** — "uma criança real consegue usar e **quer voltar amanhã**?" (a mesma métrica-norte da Seção
[17](17-telemetria-metricas.md)); o **placar é honesto** — ✅/🟢 pronto (fase entregue) / 🟡 parcial / ⬛ planejado,
fiel ao `_estado-atual`, e **"tabela existe" nunca é lido como "capacidade entregue"**; e a **23 só ordena o tempo** — cada
capacidade tem **dono canônico em outra seção**, e a 23 a **hospeda como fase**, sem arbitrar o conteúdo.

Conexão com os **Princípios Imutáveis** ([01](01-principios-imutaveis.md)): **P6** (erro nunca pune) e **P7** (passe
**gratuito**) valem **em todas as fases** — nenhuma fase introduz punição ou passe pago (o firewall é da Seção
[22](22-monetizacao.md)).

### 4. Experiência que o jogador deve sentir
A criança **não** vive "o roadmap" — ela vive **uma fase completa por vez**: no Q0, um cartão que funciona e um
avatar que é seu; no Q1, a **primeira missão jogável**; a cada fase, algo novo que **não quebra** o que já era bom.
**A equipe** ganha um **mapa honesto**: sabe o que está pronto, o que é esquema e o que é planejado, e libera cada
fase com o critério "a criança volta amanhã?". **A escola** recebe fases **usáveis em produção**, não betas.

### 5. Fluxo completo
As **7 fases**. Cada fase é **entregável em produção**; o **critério de corte** é sempre "a criança real usa e quer
voltar amanhã?". O **conteúdo/mecânica** de cada item é da seção-dona (referências); a 23 só fixa **a fase**.

- **Q0 — Fundação** ✅ *(entregue 09/07/2026)* — login código-só, cartões PDF/QR, situação de acesso, perfil
  cosmético + vestiário + **avatar humanoide 3D**, **PWA/offline (shell/boot; sem fila de jogo)**, áudio pt-BR
  sintetizado; **Edu** completo (importação, ranking, relatórios, backup); **infra** (observabilidade/health/metrics).
  *Corte:* o **teste de corredor** na escola-piloto (uma turma de 6 anos loga sem travar). *🟡 parciais:* o **render
  do Q0 conforma-se** à arquitetura já aprovada da Seção [11](11-arquitetura.md) (híbrido oficial, ADR-2) — resta só
  **ratificar o avatar humanoide 3D** (ADR C.12); e há parciais operacionais (bug de conquista na Carreira;
  catálogos cosméticos com endpoint **não consumido**; modelo de jogo sem endpoint — ver §2).
- **Q1 — Núcleo jogável** ⬛ — o **loop**: `MissaoPlayer` + registry de **4 mecânicas DOM** (quiz, arrastar-e-soltar,
  ligar colunas, memória — **gabarito no servidor**, P13), **Planeta Matemática** completo para os **5 anos escolares
  (1º–5º)**, progressão
  **XP/níveis/moedas(ledger)/estrelas**, **telemetria desde o 1º clique** (Seções [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)/[17](17-telemetria-metricas.md)).
  *Corte:* uma turma-piloto joga **uma aula inteira sem ajuda** e pede "posso jogar de novo?".
- **Q2 — Retenção** ⬛ — missões **diárias/semanais** + presente de login + **Chama do Cosmo** (sequência),
  conquistas + colecionáveis, **vestiário completo** (loja/inventário/pets/rotação — economia **gasta**),
  constelação pessoal, dificuldade adaptativa **v1** (heurística), **Planeta Português**, **PWA offline** (cache da
  jornada + **fila de tentativas**). *Corte:* alunos **entram de casa** (sessões fora do horário de aula).
- **Q3 — Professor & Família** ⬛ — telas do professor no **Edu** (panorama, mapa BNCC, erros comuns, trajetória,
  alertas), **Missão da Turma**, **Portal da Família** (resumo/controles/push), papel `responsavel` + vínculos,
  **certificados PDF**, `quest_outbox` → notificações/mural (Seção [10](10-professor-familia.md)). *Depende* dos
  agregados de Q1/Q2. *Corte:* um professor real acompanha a turma **sem planilha**.
- **Q4 — Social** ⬛ — amizades, "**Estudar com um amigo**" (cooperativo), motor de corrida (3 skins), pintura em
  dupla, X1, **WebSocket + salas** (memória; **Redis se houver réplica**), mensagens rápidas aprovadas, ranking de
  turma (Seção [09](09-social.md)). *Ordem deliberada:* social **só após** a retenção (Q2). *Corte:* dois amigos
  jogam juntos com segurança.
- **Q5 — Mundo vivo** ⬛ — **temporadas + passe GRATUITO** (P7), eventos temáticos, **planetas restantes** (Ciências,
  Geografia, História, Inglês, Artes + **Ed. Física/Movi** e **ERER/Raízes com curadoria HUMANA, sem IA**),
  **torneios** (opt-in, medalha para todos) + **clubes** (se a demanda confirmar). *Corte:* a escola sente o jogo
  "vivo" ao longo do ano.
- **Q6 — IA (tutor invisível)** ⬛ — Cosmo **explica erros** via `services/ia` (cache+filtros), adaptativa **v2** por
  habilidade BNCC, **gerador de desafios com fila de revisão do professor**, narrativas assistidas (**adulto no
  loop**). *Corte:* a IA ajuda a criança **sem nunca** ser autoridade sozinha (P13; gabarito **no servidor**/curadoria humana).

**Escala no tempo** (⬛): o caminho **A→B→C** (Seção [11](11-arquitetura.md)) atravessa as fases — **A** (monólito +
memória) é o Q0; **B** (Redis + réplicas) entra **conforme a carga (~Q4/Q5)**; **C** (extrair o módulo Quest) é marco
futuro. Os **gatilhos/números de carga** (ex.: **~10 escolas** p/ B, **>30 escolas** p/ C) são **ilustrativos** e das
Seções [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md); a 23 só posiciona a **janela de fase**, não crava número.

**Matriz fase × sistema × seção** (23.11) — cada fase × o sistema que estreia × a seção-dona do conteúdo:

| Fase | Estado | Sistema que estreia | Seção-dona |
|------|:------:|---------------------|------------|
| Q0 | ✅/🟡 | fundação (login, cartões, perfil cosmético, PWA-shell, Edu, infra) | [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)/[10](10-professor-familia.md) |
| Q1 | ⬛ | **loop jogável** (missão/desafio/tentativa/progresso) + Matemática | [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)/[17](17-telemetria-metricas.md) |
| Q2 | ⬛ | **retenção** (diárias, loja/economia gasta, adaptativa v1, PWA-fila) | [05](05-sistemas-de-jogo.md)/[07](07-ux-fluxos-navegacao.md)/[06](06-pedagogico-bncc.md) |
| Q3 | ⬛ | **contrato adulto** (telas do professor, Portal da Família, `quest_outbox`) | [10](10-professor-familia.md) (esquema outbox = [11](11-arquitetura.md)) |
| Q4 | ⬛ | **social** (amizades, cooperativo, WebSocket+salas, ranking de turma) | [09](09-social.md) (infra ao-vivo = [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)) |
| Q5 | ⬛ | **mundo vivo** (temporadas + passe gratuito, planetas restantes, torneios) | [19](19-liveops.md)/[22](22-monetizacao.md)/[06](06-pedagogico-bncc.md) |
| Q6 | ⬛ | **IA** (explica-erro, adaptativa v2, gerador com revisão humana) | [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md) |

### 6. Interface (quando existir)
**N/A** — capítulo de planejamento. A "superfície" do roadmap é o **placar honesto** (🟢/🟡/⬛ por fase) e a **matriz
fase × sistema × seção** (23.11), mantidos fiéis ao `_estado-atual`. Não há UI de criança aqui.

### 7. UX
A "UX de roadmap" é para a **equipe**: um placar que **não mente** (esquema ≠ endpoint; Q0-parcial é marcado 🟡), um
critério de corte **verificável** ("a criança volta amanhã?" + o gate quantitativo da Seção [17](17-telemetria-metricas.md)),
e uma **matriz** que amarra cada fase às seções-donas. Nada de "quase pronto" para o que não tem rota.

### 8. Game Design
**N/A** — a 23 **ordena quando** cada sistema de jogo entra; **não** o desenha. A mecânica (missão/desafio/economia/
temporada) é da Seção [05](05-sistemas-de-jogo.md), o conteúdo BNCC da Seção [06](06-pedagogico-bncc.md), o social da
Seção [09](09-social.md). A 23 apenas **sequencia** (loop=Q1, retenção=Q2, social=Q4, IA=Q6).

### 9. Regras de negócio
As **normas do roadmap** (a fonte da ordenação; a **mecânica** é da Seção [05](05-sistemas-de-jogo.md), a
**arquitetura** da Seção [11](11-arquitetura.md), a **cobrança** da Seção [22](22-monetizacao.md)):

| # | Norma | Regra | Fronteira |
|---|-------|-------|-----------|
| F1 | **Régua de corte** | toda fase é "pronta" quando **uma criança real usa e quer voltar amanhã** (afetivo); o **gate quantitativo** (D1/D7/D30) remete à Seção [17](17-telemetria-metricas.md) | 23 (régua); alvos = [17](17-telemetria-metricas.md) |
| F2 | **Fase entregável** | cada fase entrega **valor usável em produção** e **nenhuma reescreve a anterior**; o banco/fronteiras das Seções [01](01-principios-imutaveis.md)/[02](02-vocabulario.md) já comportam todas | 23 |
| F3 | **Placar honesto** | pronto 🟢 / parcial 🟡 / planejado ⬛, **fiel ao `_estado-atual`**; **"tabela existe" ≠ "endpoint existe"** (esquema pronto não conta como capacidade entregue) | 23; fonte = `_estado-atual` |
| F4 | **A 23 ordena; não redefine** | a 23 diz **em qual fase** cada capacidade sai do papel; o **conteúdo** de cada uma tem **dono canônico** em outra seção | 23 (ordena); conteúdo = seção-dona |
| F5 | **Fronteira Q0/Q1 = o loop jogável** | Q1 é a **primeira** fase a expor **servir missão/desafio + submeter tentativa + gravar progresso** (inexistentes hoje) | 23; loop = [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md) |
| F6 | **Ordenação por dependência** | **social só após retenção** (Q4 depois de Q2); **IA por último** (Q6, após conteúdo+telemetria); **Portal da Família** (Q3) após os agregados de Q1/Q2 | 23 |
| F7 | **Escala por gatilho, no tempo** | a **janela de fase** (~Q4/Q5 para o Redis) é posição da 23; os **números de carga** (ex.: ~10 escolas p/ B, >30 p/ C) são **ilustrativos e da Seção [14](14-infra-deploy-dr.md)** (pendentes de ratificação); o **desenho** A→B→C é da Seção [11](11-arquitetura.md) | 23 (janela); desenho = [11](11-arquitetura.md); gatilho/números = [14](14-infra-deploy-dr.md) |
| F8 | **SQLite→Postgres NÃO é fase** | Postgres é a **produção desde Q0** (SQLite é só dev); é **paridade dev↔prod** (Seções [14](14-infra-deploy-dr.md)/[11](11-arquitetura.md)), não um marco de roadmap | 23 (não inventa fase de banco) |
| F9 | **Rótulo de fase** | "Q0–Q6" = **fase** (dono = 23); **≠** "Q1–Q14" = **norma de QA** (Seção [18](18-qa-testes.md)) — desambiguar em toda matriz/cruzamento | 23 (rótulo de fase) |
| F10 | **Riscos por fase** | conteúdo é o **gargalo** (Q1 = 1 planeta **profundo**, não 9 rasos); multiplayer prematuro (social só Q4); login de 6 anos (**teste de corredor** já em Q0); uso compulsivo (**controles da família** desde Q3); divergência visual (**design system** do Q0 é fonte única) | 23 (riscos); mitigação = seções-donas |
| F11 | **Q0 com avatar a ratificar** | Q0 foi entregue com **Three.js/3D**; o **render híbrido** (C.13) **já é oficial** pela Seção [11](11-arquitetura.md) (ADR-2, **não** revertível — o desvio DOM/SVG-first foi resolvido); resta **só ratificar o avatar** (ADR C.12) | 23 (registra); decisão = [11](11-arquitetura.md)/ADR |
| F12 | **Fase da cobrança** | **qual fase habilita cobrança/marketing** e o que é o "produto lançável" — decisão do dono; hoje **piloto gratuito**; cruza com a Seção [22](22-monetizacao.md) (B15) | 23 ⚠️ (§15); modelo = [22](22-monetizacao.md) |
| F13 | **Gate quantitativo de saída** | a 23 fixa **que cada fase tem um gate de saída** (estrutura); a **definição operacional e o alvo** da métrica (ex.: "sessões fora do horário de aula" no Q2; D1/D7/D30) são da Seção [17](17-telemetria-metricas.md) — enquanto os alvos estiverem pendentes, o **corte afetivo é o único gate acionável** | 23 (estrutura); definição+alvo = [17](17-telemetria-metricas.md) ⚠️ (§15) |
| F14 | **Escopo de conteúdo por fase** | quantos planetas por fase e a **ordem** (Matemática Q1, Português Q2, demais Q5; Ed. Física/ERER Q5 **curadoria humana**) — decisão do dono | 23 ⚠️ (§15); conteúdo = [06](06-pedagogico-bncc.md)/ADR |
| F15 | **Backlog pós-Q6** | a **integração futura** com o software próprio do dono (matérias+questões) e idiomas/novas plataformas ficam no backlog, **sem datar** (torneios/clubes ficam na Q5, não aqui) | 23 |

### 10. Arquitetura técnica
A 23 **agenda no tempo** o que a Seção [11](11-arquitetura.md) **desenha** e a Seção [14](14-infra-deploy-dr.md)
**opera**:
- **Loop de jogo (Q1)** — a camada de **rota/serviço** sobre os models `quest_*` já existentes (catálogo/progresso/
  tentativa); é o que falta para o "esquema pronto" virar capacidade.
- **Caminho A→B→C** — **A** (monólito + memória) = Q0; **B** (Redis para estado-ao-vivo/rankings/rate-limit +
  réplicas stateless) ≈ Q4/Q5 conforme carga; **C** (extrair o módulo Quest + fila real, com o `quest_outbox` como
  base) = marco futuro. **Gatilho/números** = Seções [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md).
- **Migração de rota** — `/escolas/{escola_id}/quest/*` → canônica `/api/v1/quest/*` (Seção [11](11-arquitetura.md)),
  agendada como marco, não redefinida aqui.
- **`quest_outbox`** — o **esquema/mecanismo** é da Seção [11](11-arquitetura.md) (a Seção [10](10-professor-familia.md)
  é **consumidora** do mural/notificações). Não há conflito de fase: a 23 crava a **introdução** do outbox no **Q3**
  (pré-requisito das notificações da 10), enquanto a **fiação da telemetria social** que a Seção
  [17](17-telemetria-metricas.md) chama de "alvo Q4" **permanece Q4** (só existe com o social do Q4). Alinhar apenas a
  referência de **existência/introdução** (Q3) — a 17 mantém o consumo social em Q4 (§15).

### 11. Dependências com outros módulos
**Consome / ordena (a 23 dá a FASE; a seção dá o CONTEÚDO):**
- **Seções [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)** — loop/mecânica/conteúdo (Q1→Q6).
- **Seção [11](11-arquitetura.md)** — o caminho A→B→C, a migração de rota, o render híbrido (o **desenho**).
- **Seção [14](14-infra-deploy-dr.md)** — o **gatilho** do Redis e a operação de escala.
- **Seção [09](09-social.md)** — a regra social (Q4/fase futura).
- **Seção [10](10-professor-familia.md)** — o contrato adulto (Q3).
- **Seção [17](17-telemetria-metricas.md)** — os **alvos** do gate de saída (D1/D7/D30).
- **Seção [22](22-monetizacao.md)** — a **fase** da cobrança (B15).
- **Seção [19](19-liveops.md)** — os valores/operação do passe/temporada (Q5).
- **Seção [00](00-visao-e-norte.md)** — a régua afetiva e a visão de lançamento.

**Alimenta:**
- **Apêndice F** — os checklists de **DoD por fase**.
- **Seção [21](21-suporte-operacao.md)** — recebe da 21 as dores das escolas como **entrada priorizada** do roadmap.

**O que quebra se mudar:** se a Seção [22](22-monetizacao.md) definir a **fase da cobrança**, a 23 **posiciona** o
lançamento comercial; se a Seção [14](14-infra-deploy-dr.md) ratificar o **gatilho do Redis**, a 23 **fixa** a janela
do estágio B; se o dono decidir o **escopo de conteúdo** (23.13), a 23 **dimensiona** o Q1.

### 12. Casos extremos (Edge Cases)
- **Ler "tabela existe" como "pronto"** → **proibido** (F3): sem rota, é esquema, não capacidade.
- **Creditar o loop offline ao Q0** → não: a **fila offline de tentativas** é **Q2** (o Q0 tem só o *shell* PWA).
- **Confundir "Q2 fase" com "Q2 norma-QA"** → desambiguar sempre (F9): a fase é da 23, a norma é da Seção [18](18-qa-testes.md).
- **Tratar SQLite→Postgres como fase** → não (F8): Postgres é prod desde Q0.
- **Datar economia/social/temporada como "quase pronto"** → não: são aspiracionais (nem tabela em alguns casos).
- **Q0 (3D)** → o **render híbrido já é oficial** (Seção [11](11-arquitetura.md)/ADR-2); resta **só o avatar** a ratificar (F11).
- **`quest_outbox`** → a 23 crava a **introdução no Q3** (esquema = Seção [11](11-arquitetura.md)); o **consumo social** pela Seção [17](17-telemetria-metricas.md) **permanece Q4** (§15).
- **Social antes da retenção** → **evitado por desenho** (F6): Q4 só depois de Q2.

### 13. Escalabilidade futura
- **Backlog pós-Q6** — a **integração nativa** com o software próprio do dono (matérias+questões) e idiomas/novas
  plataformas — sem datar (F15). *(Torneios ficam firmes na Q5 e clubes na Q5 se a demanda confirmar — não aqui.)*
- **Estágio C** — extração do módulo Quest para serviço próprio, quando os gatilhos das Seções [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md) dispararem.
- **Métricas de aprendizagem** — correlacionar retenção com ganho pedagógico (Seção [17](17-telemetria-metricas.md)) quando houver dados de Q2+.

### 14. Checklist de implementação
**"Pronto quando" (liga ao Apêndice F). Itens ⚠️ dependem de decisão do dono (§15):**
- [x] **Régua de corte** afetiva fixada; gate quantitativo remetido à Seção [17](17-telemetria-metricas.md) (F1).
- [x] **Placar honesto** 🟢/🟡/⬛ fiel ao `_estado-atual`; esquema ≠ endpoint (F3).
- [x] **Q0** documentado como entregue (render híbrido **já oficial** pela Seção [11](11-arquitetura.md); **só o avatar a ratificar** — F11).
- [x] **Fronteira Q0/Q1** = o loop jogável (F5); **ordenação por dependência** (social pós-retenção; IA por último) (F6).
- [x] **7 fases** (Q0–Q6) sequenciadas, cada uma com objetivo/escopo/corte e **sem reescrever a anterior**, espelhando `docs/quest/05-roadmap.md` (F2).
- [x] **Matriz fase × sistema × seção** (§5) e **riscos por fase** (F10) registrados.
- [x] **Desacoplamento verificado** — a 23 só agenda; não redefine mecânica ([05](05-sistemas-de-jogo.md))/conteúdo ([06](06-pedagogico-bncc.md))/arquitetura ([11](11-arquitetura.md))/gatilho ([14](14-infra-deploy-dr.md))/modelo ([22](22-monetizacao.md)) (F4).
- [x] **Escala A→B→C** posicionada no tempo (~Q4/Q5 Redis); números de carga = ilustrativos/Seção [14](14-infra-deploy-dr.md) (F7).
- [x] **Desambiguação** do rótulo de fase vs norma-QA (F9); **SQLite→Postgres não é fase** (F8).
- [x] **Backlog pós-Q6** registrado sem datar (F15).
- [x] **`quest_outbox`** — a 23 crava a **introdução no Q3** (esquema = Seção [11](11-arquitetura.md)) (§10).
- [ ] ⚠️ **Alinhar a referência da Seção [17](17-telemetria-metricas.md)** à introdução do outbox no Q3 (a 17 mantém o consumo social em Q4) (§15).
- [ ] ⚠️ **Ratificação do avatar 3D do Q0** (o render híbrido já é da Seção [11](11-arquitetura.md)/ADR-2) — 23.16/ADR C.12 (§15).
- [ ] ⚠️ **Escopo de conteúdo do Q1** (1 planeta profundo vs vários rasos) (F14 — §15).
- [ ] ⚠️ **Ordem dos planetas** + Ed. Física/ERER na Q5 com curadoria humana (F14 — §15).
- [ ] ⚠️ **Fase da cobrança / lançamento comercial** (F12 — §15).
- [ ] ⚠️ **Marcos/datas-alvo** por fase (date-driven × criterion-driven) (§15).
- [ ] ⚠️ **Métricas de saída** por fase (definição+alvos = Seção [17](17-telemetria-metricas.md)) (F13 — §15).
- [ ] ⚠️ **Gatilho do Redis** (~10 escolas) ratificado (Seção [14](14-infra-deploy-dr.md) 14.37) (§15).

### 15. Questões em aberto
Cada item é **decisão do dono** (⚠️); os defaults são **propostas** da 23, não decisões autônomas (6 ⚠️ no bloco 23
do `INDICE.md`, + 2 reconciliações):

- ⚠️ **23.13 / ADR C.16 — Escopo de conteúdo do Q1.** **1 planeta profundo** (Matemática, 5 anos escolares) **vs**
  vários planetas rasos. É a **decisão-mãe** que dimensiona todo o esforço de conteúdo (o gargalo declarado). Proposta: 1 profundo.
- ⚠️ **23.14 / ADR C.22 — Ordem dos planetas.** Confirmar Matemática Q1 → Português Q2 → demais Q5; e **Ed. Física
  (Movi)** + **ERER (Raízes)** só na **Q5 com curadoria pedagógica humana** (sem autoria por IA).
- ⚠️ **23.16 / ADR C.12 — Ratificação do avatar do Q0.** O **render híbrido** (C.13) **já é oficial** pela Seção
  [11](11-arquitetura.md) (ADR-2: R3F/Three.js no personagem + SVG/CSS no ambiente) — **não** é opção revertível, o
  desvio original DOM/SVG-first já foi resolvido. Resta **só** ratificar o **avatar** (humanoide 3D vs Cosmo 2D — C.12).
- ⚠️ **23.17 — Definição de lançamento comercial.** Qual **fase** habilita cobrança e marketing, e o que compõe o
  "produto lançável". Cruza com a Seção [22](22-monetizacao.md) (B15) e a Seção [00](00-visao-e-norte.md).
- ⚠️ **23.18 — Marcos e datas-alvo.** O roadmap é dirigido por **data** ou só por **critério de pronto** (sem prazo
  fixo)? Havendo datas, quais? Proposta: **criterion-driven**.
- ⚠️ **23.19 — Métricas de saída (gate quantitativo).** Quais números liberam a passagem de fase (ex.: sessões fora
  do horário de aula no Q2; D1/D7/D30) — **alvos = Seção [17](17-telemetria-metricas.md)** (ADR C.26).
- ⚠️ **Gatilho do Redis (~10 escolas).** Proposta da Seção [14](14-infra-deploy-dr.md) (14.37) **pendente de
  ratificação** — a 23 depende dele para posicionar o estágio B (~Q4/Q5).
- ⚠️ **Referência do `quest_outbox`.** A 23 crava a **introdução no Q3** (pré-requisito do mural/notificações da Seção
  [10](10-professor-familia.md); esquema = Seção [11](11-arquitetura.md)); a Seção [17](17-telemetria-metricas.md) o
  cita como "alvo Q4" **por causa da telemetria social** — o que é correto (só existe no Q4). **Alinhar** apenas a
  referência de existência/introdução (Q3); o consumo social pela 17 **permanece Q4**.

### 16. ADR (Architecture Decision Record)
- **ADR-23-A — A 23 é o mapa de QUANDO; nunca o de O QUÊ.** A 23 **ordena no tempo** as capacidades das outras
  seções e mantém um **placar honesto** (só Q0 em produção); **não** redefine mecânica ([05](05-sistemas-de-jogo.md)),
  conteúdo ([06](06-pedagogico-bncc.md)), arquitetura ([11](11-arquitetura.md)) nem cobrança ([22](22-monetizacao.md)).
- **ADR-23-B — Régua de corte afetiva + gate quantitativo.** Toda fase é "pronta" quando **a criança volta amanhã**
  (qualitativo) e, **quando houver métrica de saída definida** (Seção [17](17-telemetria-metricas.md)), também a
  atinge; enquanto os alvos da 17 estiverem pendentes, o **corte afetivo é o único gate acionável**. O **placar**
  distingue **esquema pronto** de **capacidade entregue** ("tabela existe" ≠ "endpoint existe").
- **ADR-23-C — Ordenação por dependência, não por desejo.** O **loop** (Q1) precede tudo; a **retenção** (Q2) precede
  o **social** (Q4); a **IA** (Q6) vem por último (após conteúdo + telemetria); o **Portal da Família** (Q3) depende
  dos agregados de Q1/Q2. A **escala** (A→B→C) segue **gatilhos** das Seções [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md), não datas.
- **ADR-23-D — Q0 entregue; só o avatar a ratificar.** O núcleo foi para **3D** (Three.js/R3F + avatar humanoide),
  divergindo do plano original DOM/SVG-first; a Seção [11](11-arquitetura.md) já **resolveu** isso com o **render
  híbrido oficial** (ADR-2/C.13 — **não** revertível). A 23 marca o Q0 como **entregue**, restando ratificar **só o
  avatar** (ADR C.12) — registra, não reabre.

*Decisões cross-módulo não são improvisadas aqui: as pendências acima viram ADR ou item de §15.*

---

## 🇬🇧 Roadmap & Phases (Q0–Q6)

### 1. Objective
To be the **temporal map** of Constela Quest: to document the **7 phases (Q0–Q6)**, each **deliverable and usable in
production**, with an objective, scope, a **cut criterion** ("does a real child use it and want to come back
tomorrow?") and an **honest scoreboard** of done-vs-planned. It decides **the sequence and when** each capability
leaves the page; it does **not** redefine the **content** of each section (mechanics = [05](05-sistemas-de-jogo.md)/
[06](06-pedagogico-bncc.md), architecture = [11](11-arquitetura.md), billing = [22](22-monetizacao.md)) — it only
**orders** them. It feeds **Appendix F**.

### 2. Context
The product is **Hub → Edu → Quest**. **Current state (Q0) — only the foundation is in production; the game does not
exist yet:**
- **Quest has exactly 3 routers** (verified in `backend/app/quest/routers/`): **code-only login** (`auth.py`:
  `/quem`, `/entrar`, `/entrar-qr`); **cosmetic profile** (`perfil.py`: read profile/colors/appearance/characters;
  change name/avatar/preferences with a whitelist); **teacher side** (`professor.py`: class access status, PDF/QR
  cards). **No** game route.
- **The game loop does NOT exist** — there is no route that **serves a mission/challenge**, **submits an attempt** or
  **records progress**. The `quest_*` tables (world/journey/mission/challenge, progress/attempt/skill) **exist
  without a route** — **schema ready ≠ capability delivered**.
- **Spent economy, social, pass/season, family portal, monetization** — **all aspirational** (no route;
  economy/social/season don't even have a table). `ResponsavelAluno` is modeled **without** a router.
- **What IS Q0** — the **complete Edu backend** (15 routers: schools/students/classes, Matific/Elefante import,
  ranking, reports, backup/restore), the **mature infra** (observability, health, `/metrics` Prometheus), and the
  student **PWA** (login, 3-tab lobby, wardrobe, **3D humanoid avatar** Three.js/R3F, Cosmo mascot, synthesized
  offline pt-BR audio). **Q0 partial (🟡):** an achievement bug in Carreira; cosmetic catalogs with an endpoint but
  not consumed; the game model without an endpoint.
- **Architecture today** — a **single modular monolith** (`main.py` mounts everything); extraction into a service is
  a **future milestone conditioned on scale**, with no code.

This chapter **mirrors** the source roadmap (`docs/quest/05-roadmap.md`), **nails** the cut criterion and **records**
what the owner still has to decide.

### 3. Feature philosophy
**"Each phase is a whole, small game — never a half-finished version."** The roadmap is sequenced to **deliver usable
production value at each phase**, and **no phase rewrites the previous one** (the database and the boundaries of
Sections [01](01-principios-imutaveis.md)/[02](02-vocabulario.md) already accommodate all of them). Roadmap
principles: the **cut criterion is affective** — "can a real child use it and **want to come back tomorrow**?" (the
same north-star metric of Section [17](17-telemetria-metricas.md)); the **scoreboard is honest** — ✅/🟢 done (phase
delivered) / 🟡 partial / ⬛ planned, faithful to `_estado-atual`, and **"a table exists" is never read as "a
capability delivered"**; and **23 only orders time** — each capability has a **canonical owner in another section**, and 23
**hosts it as a phase**, without arbitrating the content.

Link to the **Immutable Principles** ([01](01-principios-imutaveis.md)): **P6** (error never punishes) and **P7**
(**free** pass) hold **in all phases** — no phase introduces punishment or a paid pass (the firewall is Section
[22](22-monetizacao.md)'s).

### 4. The experience the player should feel
The child does **not** experience "the roadmap" — they experience **one complete phase at a time**: in Q0, a card
that works and an avatar that is theirs; in Q1, the **first playable mission**; each phase, something new that **does
not break** what was already good. **The team** gains an **honest map**: they know what is done, what is schema and
what is planned, and ship each phase with the "does the child come back tomorrow?" test. **The school** receives
phases **usable in production**, not betas.

### 5. Complete flow
The **7 phases**. Each phase is **deliverable in production**; the **cut criterion** is always "does the real child
use it and want to come back tomorrow?". The **content/mechanics** of each item belongs to the owner section
(references); 23 only fixes **the phase**.

- **Q0 — Foundation** ✅ *(delivered 2026-07-09)* — code-only login, PDF/QR cards, access status, cosmetic profile +
  wardrobe + **3D humanoid avatar**, **PWA/offline (shell/boot; no game queue)**, synthesized pt-BR audio; **Edu**
  complete (import, ranking, reports, backup); **infra** (observability/health/metrics). *Cut:* the **corridor test**
  at the pilot school (a 6-year-old class logs in without getting stuck). *🟡 partials:* the **Q0 render conforms** to
  Section [11](11-arquitetura.md)'s already-approved architecture (official hybrid, ADR-2) — only the **3D humanoid
  avatar** remains to **ratify** (ADR C.12); plus operational partials (an achievement bug in Carreira; cosmetic
  catalogs with an **unconsumed** endpoint; the game model without an endpoint — see §2).
- **Q1 — Playable core** ⬛ — the **loop**: `MissaoPlayer` + a registry of **4 DOM mechanics** (quiz, drag-and-drop,
  connect columns, memory — **answer-key on the server**, P13), a complete **Planeta Matemática** for the **5 school
  years (1st–5th)**, **XP/levels/coins(ledger)/stars** progression, **telemetry from the 1st click** (Sections [05](05-sistemas-de-jogo.md)/
  [06](06-pedagogico-bncc.md)/[17](17-telemetria-metricas.md)). *Cut:* a pilot class plays **a whole lesson unaided**
  and asks "can I play again?".
- **Q2 — Retention** ⬛ — **daily/weekly** missions + a login gift + the **Chama do Cosmo** (streak), achievements +
  collectibles, the **full wardrobe** (shop/inventory/pets/rotation — **spent** economy), a personal constellation,
  adaptive difficulty **v1** (heuristic), **Planeta Português**, **PWA offline** (journey cache + **attempt queue**).
  *Cut:* students **enter from home** (sessions outside class hours).
- **Q3 — Teacher & Family** ⬛ — teacher screens in **Edu** (overview, BNCC map, common errors, trajectory, alerts),
  **Missão da Turma**, the **Family Portal** (summary/controls/push), the `responsavel` role + bindings, **PDF
  certificates**, `quest_outbox` → notifications/wall (Section [10](10-professor-familia.md)). *Depends* on the Q1/Q2
  aggregates. *Cut:* a real teacher follows the class **without a spreadsheet**.
- **Q4 — Social** ⬛ — friendships, "**Study with a friend**" (co-op), a race engine (3 skins), pair painting, X1,
  **WebSocket + rooms** (memory; **Redis if there is a replica**), quick approved messages, class ranking (Section
  [09](09-social.md)). *Deliberate order:* social **only after** retention (Q2). *Cut:* two friends play together safely.
- **Q5 — Living world** ⬛ — **seasons + a FREE pass** (P7), thematic events, the **remaining planets** (Sciences,
  Geography, History, English, Arts + **Ed. Física/Movi** and **ERER/Raízes with HUMAN curation, no AI**),
  **tournaments** (opt-in, a medal for all) + **clubs** (if demand confirms). *Cut:* the school feels the game "alive"
  through the year.
- **Q6 — AI (invisible tutor)** ⬛ — Cosmo **explains errors** via `services/ia` (cache+filters), adaptive **v2** by
  BNCC skill, a **challenge generator with a teacher review queue**, assisted narratives (**adult in the loop**).
  *Cut:* the AI helps the child **without ever** being the sole authority (P13; **server** answer-key/human curation).

**Scale over time** (⬛): the **A→B→C** path (Section [11](11-arquitetura.md)) cuts across the phases — **A**
(monolith + memory) is Q0; **B** (Redis + replicas) enters **as load requires (~Q4/Q5)**; **C** (extract the Quest
module) is a future milestone. The **load triggers/numbers** (e.g. **~10 schools** for B, **>30 schools** for C) are
**illustrative** and Sections [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)'s; 23 only positions the **phase
window**, it does not set a number.

**Phase × system × section matrix** (23.11) — each phase × the debuting system × the content's owner section:

| Phase | State | Debuting system | Owner section |
|-------|:-----:|-----------------|---------------|
| Q0 | ✅/🟡 | foundation (login, cards, cosmetic profile, PWA-shell, Edu, infra) | [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)/[10](10-professor-familia.md) |
| Q1 | ⬛ | **playable loop** (mission/challenge/attempt/progress) + Math | [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)/[17](17-telemetria-metricas.md) |
| Q2 | ⬛ | **retention** (dailies, shop/spent economy, adaptive v1, PWA queue) | [05](05-sistemas-de-jogo.md)/[07](07-ux-fluxos-navegacao.md)/[06](06-pedagogico-bncc.md) |
| Q3 | ⬛ | **adult contract** (teacher screens, Family Portal, `quest_outbox`) | [10](10-professor-familia.md) (outbox schema = [11](11-arquitetura.md)) |
| Q4 | ⬛ | **social** (friendships, co-op, WebSocket+rooms, class ranking) | [09](09-social.md) (live infra = [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)) |
| Q5 | ⬛ | **living world** (seasons + free pass, remaining planets, tournaments) | [19](19-liveops.md)/[22](22-monetizacao.md)/[06](06-pedagogico-bncc.md) |
| Q6 | ⬛ | **AI** (explain-error, adaptive v2, generator with human review) | [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md) |

### 6. Interface (when it exists)
**N/A** — a planning chapter. The roadmap "surface" is the **honest scoreboard** (🟢/🟡/⬛ per phase) and the **phase
× system × section** matrix (23.11), kept faithful to `_estado-atual`. There is no child UI here.

### 7. UX
The "roadmap UX" is for the **team**: a scoreboard that **does not lie** (schema ≠ endpoint; a Q0-partial is marked
🟡), a **verifiable** cut criterion ("does the child come back tomorrow?" + Section [17](17-telemetria-metricas.md)'s
quantitative gate), and a **matrix** binding each phase to its owner sections. No "almost done" for what has no route.

### 8. Game Design
**N/A** — 23 **orders when** each game system enters; it does **not** design it. The mechanics
(mission/challenge/economy/season) are Section [05](05-sistemas-de-jogo.md)'s, the BNCC content Section
[06](06-pedagogico-bncc.md)'s, the social Section [09](09-social.md)'s. 23 only **sequences** (loop=Q1,
retention=Q2, social=Q4, AI=Q6).

### 9. Business rules
The **roadmap norms** (the source of the ordering; the **mechanics** are Section [05](05-sistemas-de-jogo.md)'s, the
**architecture** Section [11](11-arquitetura.md)'s, the **billing** Section [22](22-monetizacao.md)'s):

| # | Norm | Rule | Boundary |
|---|------|------|----------|
| F1 | **Cut criterion** | a phase is "done" when **a real child uses it and wants to come back tomorrow** (affective); the **quantitative gate** (D1/D7/D30) refers to Section [17](17-telemetria-metricas.md) | 23 (criterion); targets = [17](17-telemetria-metricas.md) |
| F2 | **Deliverable phase** | each phase delivers **usable production value** and **none rewrites the previous one**; the DB/boundaries of Sections [01](01-principios-imutaveis.md)/[02](02-vocabulario.md) already accommodate all | 23 |
| F3 | **Honest scoreboard** | done 🟢 / partial 🟡 / planned ⬛, **faithful to `_estado-atual`**; **"a table exists" ≠ "an endpoint exists"** (schema ready does not count as delivered) | 23; source = `_estado-atual` |
| F4 | **23 orders; it does not redefine** | 23 says **in which phase** each capability leaves the page; the **content** of each has a **canonical owner** in another section | 23 (orders); content = owner section |
| F5 | **Q0/Q1 boundary = the playable loop** | Q1 is the **first** phase to expose **serving a mission/challenge + submitting an attempt + recording progress** (nonexistent today) | 23; loop = [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md) |
| F6 | **Dependency ordering** | **social only after retention** (Q4 after Q2); **AI last** (Q6, after content+telemetry); the **Family Portal** (Q3) after the Q1/Q2 aggregates | 23 |
| F7 | **Scale by trigger, over time** | the **phase window** (~Q4/Q5 for Redis) is 23's position; the **load numbers** (e.g. ~10 schools for B, >30 for C) are **illustrative and Section [14](14-infra-deploy-dr.md)'s** (pending ratification); the **design** A→B→C is Section [11](11-arquitetura.md)'s | 23 (window); design = [11](11-arquitetura.md); trigger/numbers = [14](14-infra-deploy-dr.md) |
| F8 | **SQLite→Postgres is NOT a phase** | Postgres is the **production since Q0** (SQLite is dev only); it is **dev↔prod parity** (Sections [14](14-infra-deploy-dr.md)/[11](11-arquitetura.md)), not a roadmap milestone | 23 (invents no DB phase) |
| F9 | **Phase label** | "Q0–Q6" = **phase** (owner = 23); **≠** "Q1–Q14" = **QA norm** (Section [18](18-qa-testes.md)) — disambiguate in every matrix/cross-reference | 23 (phase label) |
| F10 | **Risks per phase** | content is the **bottleneck** (Q1 = 1 **deep** planet, not 9 shallow); premature multiplayer (social only Q4); 6-year-old login (**corridor test** already in Q0); compulsive use (**family controls** from Q3); visual divergence (Q0's **design system** is the single source) | 23 (risks); mitigation = owner sections |
| F11 | **Q0 with the avatar to ratify** | Q0 was delivered with **Three.js/3D**; the **hybrid render** (C.13) is **already official** via Section [11](11-arquitetura.md) (ADR-2, **not** revertible — the DOM/SVG-first deviation is resolved); only the **avatar** remains to ratify (ADR C.12) | 23 (records); decision = [11](11-arquitetura.md)/ADR |
| F12 | **Billing phase** | **which phase enables charging/marketing** and what the "launchable product" is — an owner decision; today a **free pilot**; crosses Section [22](22-monetizacao.md) (B15) | 23 ⚠️ (§15); model = [22](22-monetizacao.md) |
| F13 | **Quantitative exit gate** | 23 fixes **that each phase has an exit gate** (structure); the **operational definition and the target** of the metric (e.g. "sessions outside class hours" in Q2; D1/D7/D30) are Section [17](17-telemetria-metricas.md)'s — while the targets are pending, the **affective cut is the only actionable gate** | 23 (structure); definition+target = [17](17-telemetria-metricas.md) ⚠️ (§15) |
| F14 | **Content scope per phase** | how many planets per phase and the **order** (Math Q1, Portuguese Q2, the rest Q5; Ed. Física/ERER Q5 **human curation**) — an owner decision | 23 ⚠️ (§15); content = [06](06-pedagogico-bncc.md)/ADR |
| F15 | **Post-Q6 backlog** | the **future integration** with the owner's own software (subjects+questions) and languages/new platforms stay in the backlog, **undated** (tournaments/clubs stay in Q5, not here) | 23 |

### 10. Technical architecture
23 **schedules over time** what Section [11](11-arquitetura.md) **designs** and Section [14](14-infra-deploy-dr.md)
**operates**:
- **Game loop (Q1)** — the **route/service** layer over the already-existing `quest_*` models (catalog/progress/
  attempt); it is what is missing for the "schema ready" to become a capability.
- **A→B→C path** — **A** (monolith + memory) = Q0; **B** (Redis for live-state/rankings/rate-limit + stateless
  replicas) ≈ Q4/Q5 as load requires; **C** (extract the Quest module + a real queue, with `quest_outbox` as the
  base) = a future milestone. **Trigger/numbers** = Sections [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md).
- **Route migration** — `/escolas/{escola_id}/quest/*` → the canonical `/api/v1/quest/*` (Section
  [11](11-arquitetura.md)), scheduled as a milestone, not redefined here.
- **`quest_outbox`** — the **schema/mechanism** is Section [11](11-arquitetura.md)'s (Section
  [10](10-professor-familia.md) is a **consumer** of the wall/notifications). There is no phase conflict: 23 nails the
  outbox's **introduction** at **Q3** (a prerequisite of §10's notifications), while the **social-telemetry wiring**
  that Section [17](17-telemetria-metricas.md) calls a "Q4 target" **stays Q4** (it only exists with Q4's social).
  Align only the **existence/introduction** reference (Q3) — 17 keeps the social consumption at Q4 (§15).

### 11. Dependencies on other modules
**Consumes / orders (23 gives the PHASE; the section gives the CONTENT):**
- **Sections [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)** — loop/mechanics/content (Q1→Q6).
- **Section [11](11-arquitetura.md)** — the A→B→C path, the route migration, the hybrid render (the **design**).
- **Section [14](14-infra-deploy-dr.md)** — the Redis **trigger** and scale operation.
- **Section [09](09-social.md)** — the social rule (Q4/future phase).
- **Section [10](10-professor-familia.md)** — the adult contract (Q3).
- **Section [17](17-telemetria-metricas.md)** — the exit-gate **targets** (D1/D7/D30).
- **Section [22](22-monetizacao.md)** — the billing **phase** (B15).
- **Section [19](19-liveops.md)** — the pass/season values/operation (Q5).
- **Section [00](00-visao-e-norte.md)** — the affective criterion and the launch vision.

**Feeds:**
- **Appendix F** — the **per-phase DoD** checklists.
- **Section [21](21-suporte-operacao.md)** — receives from 21 the schools' pains as **prioritized input** to the roadmap.

**What breaks if it changes:** if Section [22](22-monetizacao.md) defines the **billing phase**, 23 **positions** the
commercial launch; if Section [14](14-infra-deploy-dr.md) ratifies the **Redis trigger**, 23 **fixes** the stage-B
window; if the owner decides the **content scope** (23.13), 23 **sizes** Q1.

### 12. Edge cases
- **Reading "a table exists" as "done"** → **forbidden** (F3): without a route it is schema, not a capability.
- **Crediting the offline loop to Q0** → no: the **offline attempt queue** is **Q2** (Q0 has only the PWA *shell*).
- **Confusing "Q2 phase" with "Q2 QA-norm"** → always disambiguate (F9): the phase is 23's, the norm is Section [18](18-qa-testes.md)'s.
- **Treating SQLite→Postgres as a phase** → no (F8): Postgres is prod since Q0.
- **Dating economy/social/season as "almost done"** → no: they are aspirational (no table in some cases).
- **Q0 (3D)** → the **hybrid render is already official** (Section [11](11-arquitetura.md)/ADR-2); only the **avatar** remains to ratify (F11).
- **`quest_outbox`** → 23 nails the **introduction at Q3** (schema = Section [11](11-arquitetura.md)); 17's **social consumption** **stays Q4** (§15).
- **Social before retention** → **avoided by design** (F6): Q4 only after Q2.

### 13. Future scalability
- **Post-Q6 backlog** — the **native integration** with the owner's own software (subjects+questions) and
  languages/new platforms — undated (F15). *(Tournaments stay firm in Q5 and clubs in Q5 if demand confirms — not here.)*
- **Stage C** — extracting the Quest module into its own service, when Sections [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)'s triggers fire.
- **Learning metrics** — correlating retention with pedagogical gain (Section [17](17-telemetria-metricas.md)) once there is Q2+ data.

### 14. Implementation checklist
**"Done when" (links to Appendix F). Items marked ⚠️ depend on an owner decision (§15):**
- [x] **Cut criterion** (affective) fixed; the quantitative gate refers to Section [17](17-telemetria-metricas.md) (F1).
- [x] **Honest scoreboard** 🟢/🟡/⬛ faithful to `_estado-atual`; schema ≠ endpoint (F3).
- [x] **Q0** documented as delivered (hybrid render **already official** via Section [11](11-arquitetura.md); **only the avatar to ratify** — F11).
- [x] **Q0/Q1 boundary** = the playable loop (F5); **dependency ordering** (social after retention; AI last) (F6).
- [x] **7 phases** (Q0–Q6) sequenced, each with objective/scope/cut and **without rewriting the previous one**, mirroring `docs/quest/05-roadmap.md` (F2).
- [x] **Phase × system × section matrix** (§5) and **risks per phase** (F10) recorded.
- [x] **Decoupling verified** — 23 only schedules; it does not redefine mechanics ([05](05-sistemas-de-jogo.md))/content ([06](06-pedagogico-bncc.md))/architecture ([11](11-arquitetura.md))/trigger ([14](14-infra-deploy-dr.md))/model ([22](22-monetizacao.md)) (F4).
- [x] **A→B→C scale** positioned over time (~Q4/Q5 Redis); load numbers = illustrative/Section [14](14-infra-deploy-dr.md) (F7).
- [x] **Disambiguation** of phase label vs QA-norm (F9); **SQLite→Postgres is not a phase** (F8).
- [x] **Post-Q6 backlog** recorded undated (F15).
- [x] **`quest_outbox`** — 23 nails the **introduction at Q3** (schema = Section [11](11-arquitetura.md)) (§10).
- [ ] ⚠️ **Align Section [17](17-telemetria-metricas.md)'s reference** to the outbox introduction at Q3 (17 keeps the social consumption at Q4) (§15).
- [ ] ⚠️ **Ratify the Q0 3D avatar** (the hybrid render is already Section [11](11-arquitetura.md)'s/ADR-2) — 23.16/ADR C.12 (§15).
- [ ] ⚠️ **Q1 content scope** (1 deep planet vs several shallow) (F14 — §15).
- [ ] ⚠️ **Planet order** + Ed. Física/ERER at Q5 with human curation (F14 — §15).
- [ ] ⚠️ **Billing phase / commercial launch** (F12 — §15).
- [ ] ⚠️ **Milestones/target dates** per phase (date-driven × criterion-driven) (§15).
- [ ] ⚠️ **Exit metrics** per phase (definition+targets = Section [17](17-telemetria-metricas.md)) (F13 — §15).
- [ ] ⚠️ **Redis trigger** (~10 schools) ratified (Section [14](14-infra-deploy-dr.md) 14.37) (§15).

### 15. Open questions
Each item is an **owner decision** (⚠️); the defaults are 23's **proposals**, not autonomous decisions (6 ⚠️ in
`INDICE.md`'s block 23, + 2 reconciliations):

- ⚠️ **23.13 / ADR C.16 — Q1 content scope.** **1 deep planet** (Math, 5 school years) **vs** several shallow planets.
  It is the **mother decision** that sizes the whole content effort (the declared bottleneck). Proposal: 1 deep.
- ⚠️ **23.14 / ADR C.22 — Planet order.** Confirm Math Q1 → Portuguese Q2 → the rest Q5; and **Ed. Física (Movi)** +
  **ERER (Raízes)** only at **Q5 with human pedagogical curation** (no AI authoring).
- ⚠️ **23.16 / ADR C.12 — Q0 avatar ratification.** The **hybrid render** (C.13) is **already official** via Section
  [11](11-arquitetura.md) (ADR-2: R3F/Three.js on the character + SVG/CSS in the environment) — it is **not** a
  revertible option, the original DOM/SVG-first deviation is already resolved. Only the **avatar** remains to ratify
  (3D humanoid vs Cosmo 2D — C.12).
- ⚠️ **23.17 — Commercial-launch definition.** Which **phase** enables charging and marketing, and what composes the
  "launchable product". Crosses Section [22](22-monetizacao.md) (B15) and Section [00](00-visao-e-norte.md).
- ⚠️ **23.18 — Milestones and target dates.** Is the roadmap **date-driven** or only by **done criterion** (no fixed
  deadline)? If dated, which? Proposal: **criterion-driven**.
- ⚠️ **23.19 — Exit metrics (quantitative gate).** Which numbers unlock a phase transition (e.g. sessions outside
  class hours in Q2; D1/D7/D30) — **targets = Section [17](17-telemetria-metricas.md)** (ADR C.26).
- ⚠️ **Redis trigger (~10 schools).** Section [14](14-infra-deploy-dr.md)'s proposal (14.37) is **pending
  ratification** — 23 depends on it to position stage B (~Q4/Q5).
- ⚠️ **`quest_outbox` reference.** 23 nails the **introduction at Q3** (a prerequisite of Section
  [10](10-professor-familia.md)'s wall/notifications; schema = Section [11](11-arquitetura.md)); Section
  [17](17-telemetria-metricas.md) cites it as a "Q4 target" **because of the social telemetry** — which is correct (it
  only exists at Q4). **Align** only the existence/introduction reference (Q3); 17's social consumption **stays Q4**.

### 16. ADR (Architecture Decision Record)
- **ADR-23-A — 23 is the WHEN map; never the WHAT.** 23 **orders over time** the other sections' capabilities and
  keeps an **honest scoreboard** (only Q0 in production); it does **not** redefine mechanics
  ([05](05-sistemas-de-jogo.md)), content ([06](06-pedagogico-bncc.md)), architecture ([11](11-arquitetura.md)) nor
  billing ([22](22-monetizacao.md)).
- **ADR-23-B — Affective cut criterion + quantitative gate.** A phase is "done" when **the child comes back tomorrow**
  (qualitative) and, **when there is a defined exit metric** (Section [17](17-telemetria-metricas.md)), also hits it;
  while 17's targets are pending, the **affective cut is the only actionable gate**. The **scoreboard** distinguishes
  **schema ready** from **capability delivered** ("a table exists" ≠ "an endpoint exists").
- **ADR-23-C — Ordering by dependency, not by wish.** The **loop** (Q1) precedes everything; **retention** (Q2)
  precedes **social** (Q4); **AI** (Q6) comes last (after content + telemetry); the **Family Portal** (Q3) depends on
  the Q1/Q2 aggregates. **Scale** (A→B→C) follows Sections [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)'s
  **triggers**, not dates.
- **ADR-23-D — Q0 delivered; only the avatar to ratify.** The core went **3D** (Three.js/R3F + a humanoid avatar),
  diverging from the original DOM/SVG-first plan; Section [11](11-arquitetura.md) already **resolved** that with the
  **official hybrid render** (ADR-2/C.13 — **not** revertible). 23 marks Q0 as **delivered**, with only the **avatar**
  left to ratify (ADR C.12) — it records, it does not reopen.

*Cross-module decisions are not improvised here: the pending items above become an ADR or a §15 entry.*
