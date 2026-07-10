# 21 — Suporte, Sucesso do Cliente & Operação de Escola / Support, Customer Success & School Ops

- **Status:** 🟢 aprovado / approved
- **Padrão / Standard:** [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) (16 partes)
- **Fontes / Sources:** `INDICE.md` (bloco 21, subseções 21.1–21.41), `_estado-atual/RELATORIO-2026-07-09.md`, e o **código Q0**: `backend/app/routers/admin.py` (gestão de contas/papéis; **reset por token** de uso único `POST /usuarios/{uid}/redefinir-senha`, `RESET_SENHA_EXPIRA_MIN=60`; anti-lockout do **último admin ativo**; troca de senha de terceiro incrementa `token_version`), `backend/app/routers/escolas.py` (`POST /escolas` **exclusivo de admin global**, cria **só a linha Escola**), `backend/app/routers/academico.py` (`criar_professor_completo` = professor+turma+conta com senha legível devolvida uma vez; ciclo de vida `ativo|arquivado|excluido`), `backend/app/quest/routers/professor.py` (cartões por turma/individual; `GET .../acessos`; **cartão individual não derruba a turma**; `gerar_cartao_individual`: aluno inativo → **422** "Aluno inativo não recebe cartão"), `backend/app/quest/routers/auth.py` (login da criança inativa → **403** "Seu cartão está descansando"; o **401** é para código/QR inexistente, "Não encontrei esse código"), `backend/app/quest/services/credenciais.py` (`regenerar` mantém o `codigo_login`, troca o `qr_token`, incrementa `token_version`), `backend/scripts/seed.py` (padrões pedagógicos semeados **só para 'JORGE PASSOS'**), `backend/app/services/audit.py` (`LogAuditoria`), `backend/app/main.py` (`/api/health*`, `/metrics`, `X-Request-ID` exposto "útil no relato de suporte"), Seções [08](08-onboarding-ftue.md)/[09](09-social.md)/[10](10-professor-familia.md)/[11](11-arquitetura.md)/[12](12-seguranca-privacidade.md)/[14](14-infra-deploy-dr.md)/[17](17-telemetria-metricas.md)/[19](19-liveops.md)/[20](20-migracao-importacao.md)/[22](22-monetizacao.md)/[23](23-roadmap.md), Apêndice F
- **Depende de / Depends on:** princípios (P1 login código-só · P6 erro nunca pune · P15 isolamento por escola · P16 identidade da criança vive no Edu) → [01](01-principios-imutaveis.md); **papéis** (admin/coordenador/professor/responsável) + portais + geração de cartões → [10](10-professor-familia.md); **mecânica** de incidente técnico/health/status/janela de manutenção → [14](14-infra-deploy-dr.md); **política** LGPD (base legal, retenção, erasure, auditoria) cujo **fluxo operacional** esta seção executa → [12](12-seguranca-privacidade.md); **provisionamento técnico** e **estratégia de cutover** → [20](20-migracao-importacao.md); **FTUE do aluno** (não confundir) → [08](08-onboarding-ftue.md); **regra da denúncia** → [09](09-social.md); **valores de config** `quest.*` → [19](19-liveops.md); **taxonomia** das métricas de sucesso → [17](17-telemetria-metricas.md); **planos/contratos** → [22](22-monetizacao.md); **mecanismo** (`token_version`/rate-limit/isolamento) → [11](11-arquitetura.md); **checklists operacionais** que esta seção alimenta → Apêndice F.

> **Convenção / Convention:** "§N" = uma das 16 **partes deste capítulo** / one of the 16 **parts of this
> chapter**; "Seção NN" / "Section NN" = outro capítulo da Bible; "21.NN" = uma subseção do plano do `INDICE.md`.
> **Escopo / Scope:** este capítulo decide a **estratégia de suporte, sucesso do cliente e operação de escola** —
> como uma escola é **onboardada, operada no dia a dia e mantida bem-sucedida**, de forma **executável por um time de
> suporte sem tomar decisões de produto**. Ele **decide o procedimento e a voz ao cliente**; **não** decide os
> **papéis** (Seção [10](10-professor-familia.md)), a **mecânica** de incidente/infra (Seção [14](14-infra-deploy-dr.md)),
> a **política** LGPD (Seção [12](12-seguranca-privacidade.md)), o **provisionamento técnico** (Seção [20](20-migracao-importacao.md)),
> os **valores** de config (Seção [19](19-liveops.md)), a **taxonomia** (Seção [17](17-telemetria-metricas.md)) nem
> os **planos** (Seção [22](22-monetizacao.md)) — apenas os **aplica**, **executa** e **comunica**. Os checklists
> operacionais descem para o **Apêndice F**.

---

## 🇧🇷 Suporte, Sucesso do Cliente & Operação de Escola

### 1. Objetivo
Ser a **referência definitiva de como uma escola é levada ao sucesso** no Constela: **onboarding operacional**,
**helpdesk ao professor**, **operação em sala** (cartões e login), **incidente e comunicação**, **FAQ**, **métricas
de sucesso** e **offboarding** — tudo **executável por um time de suporte**. Decide o **procedimento e a
comunicação**; **não** decide papéis (Seção [10](10-professor-familia.md)), incidente técnico (Seção
[14](14-infra-deploy-dr.md)), política LGPD (Seção [12](12-seguranca-privacidade.md)), provisionamento (Seção
[20](20-migracao-importacao.md)) nem planos (Seção [22](22-monetizacao.md)) — apenas os **aplica**. Alimenta o **Apêndice F**.

### 2. Contexto
No **Hub → Edu → Quest**, o **cliente pagante é a escola/rede** (a criança nunca é fonte de receita — P7/Seção
[22](22-monetizacao.md)), e o suporte fala com **adultos** (gestor, coordenador, professor, família). **Estado
atual (Q0) — há mecânica de operação, mas nada de helpdesk formal:**
- **Papéis** — `admin` | `coordenador` | `professor` (+ a flag `is_global` = super-admin da rede); o `responsável`
  existe só no modelo (Seção [10](10-professor-familia.md)). Listagem escopada: admin vê todos, coordenador vê
  si+professores, professor só a própria conta.
- **Gestão de contas** — criar/editar/excluir usuário (exclusão **lógica**; física só admin global com confirmação);
  **anti-lockout** (o último admin ativo é intocável; ninguém rebaixa/exclui a própria conta).
- **Reset de acesso do adulto** — `POST /usuarios/{uid}/redefinir-senha` gera um **link de uso único** que expira em
  **60 min** (guarda só o hash SHA-256); a senha é só **hash bcrypt** (recuperação por token, não reversível). Hoje o
  link (e a senha legível do professor recém-criado) **volta na resposta HTTP** para **entrega manual** — **não há
  e-mail automático nem autoatendimento** (o modelo prevê "autoatendimento futuro", desligado).
- **Suporte ao login da criança** — login **código-só** (`PALAVRA+NNNN`); o professor gera **cartões PDF** por turma
  ou **individual** (o individual **não derruba a turma**); `regenerar` **mantém o código** que a criança decorou e
  **troca o QR** (revogação por `token_version`); aluno inativo → **"cartão descansando"** (não pune, P6); situação
  de acesso por aluno em `GET .../acessos`.
- **Onboarding de escola** — **manual e fragmentado**: `POST /escolas` é **exclusivo de admin global** e cria **só a
  linha Escola** (um **casco parcial**: sem admin local, sem turmas, e **sem os padrões pedagógicos** — níveis de
  dificuldade, `ReferenciaNormalizacao`, `Configuracao` — que o `seed` cria **só para 'JORGE PASSOS'**). Não há
  signup self-service.
- **Observabilidade para suporte** — `/api/health*`, `/metrics`, `X-Request-ID` exposto ("útil no relato de
  suporte"), e **tudo auditado** em `logs_auditoria` (`usuario.reset_solicitado`, `quest.cartoes_gerados`, `login.falhou/bloqueado`).
- **Multi-tenant sem plano/contrato** — a `Escola` tem nome/cidade/estado/logotipo/ano letivo/status; **nada** de
  plano, assentos, contato de suporte ou datas de contrato (monetização não modelada — Seção [22](22-monetizacao.md)).
- **Não existe** — sistema de **tickets/SLA/escalonamento**; **status page** ao cliente; **onboarding self-service**;
  **e-mail automático** e **convite**; página de **Ajuda** no web; **endpoint de leitura** do log de auditoria para investigação.

Este capítulo **formaliza** a operação e o suporte, e registra o que falta decidir.

### 3. Filosofia da funcionalidade
**"A escola precisa ter sucesso mesmo com tablet compartilhado, wifi instável e um professor que nunca usou o
sistema."** O suporte é onde o produto **encosta na realidade da sala de aula pública**. Princípios: **o dia a dia
não pode depender do suporte** (regenerar um cartão, ligar o social e gerar cartões são autosserviço); **o suporte
executa, não decide o produto** (segue procedimento, escala à engenharia o que é técnico); **a voz ao cliente é de
adulto, calorosa e não técnica** (a escola ouve "estamos resolvendo", não *stack trace*); **o erro nunca pune a
criança** (cartão perdido é "cartão descansando", nunca "código errado" — P6); e **todo acesso a dado de criança é
auditado** (o suporte que "entra como" deixa rastro em `logs_auditoria` — regra da Seção [12](12-seguranca-privacidade.md)).

Conexão com os **Princípios Imutáveis** ([01](01-principios-imutaveis.md)): **P1** (login código-só) — o
troubleshooting do login parte de "o código é a credencial"; **P16** (identidade no Edu) — o suporte opera com a
identidade adulta do Edu, sem cadastro novo; **P15** (isolamento) — as ferramentas de suporte **devem** ter visão
**por escola** (▢ a construir; hoje o único ator de suporte é o **admin global**, cross-escola por natureza — o
escopo por `escola_id` é o gap a fechar); **P6** (erro nunca pune) — o roteiro trata o aluno com dó, não com culpa.

### 4. Experiência que o jogador deve sentir
A criança **não** fala com o suporte — ela sente o **resultado**: no dia da 1ª aula, o **corredor de login**
funciona ("Quem vai jogar?" → "Sou eu!" → "É você, {nome}?"), o cartão dá certo, e se algo falha o professor
**resolve na hora** (regenera o cartão individual). **O professor** sente que **não está sozinho**: um roteiro claro,
um FAQ curto, e um canal quando trava. **O gestor** sente **parceria**: onboarding conduzido, comunicação honesta em
incidente/manutenção, e um sinal de que a escola está indo bem (ou de que precisa de ajuda).

### 5. Fluxo completo
O **ciclo de vida da escola**, do contrato ao offboarding (⭐ = mecânica Q0 existe; ▢ = decisão/estratégia a fazer):

1. **Contrato** ▢ — a venda/licenciamento é da Seção [22](22-monetizacao.md); a 21 **começa depois do "go"**.
2. **Onboarding da escola** ▢/⭐ — criar a escola ⭐ (hoje `POST /escolas`, admin global) → **provisionar os padrões**
   (níveis, `ReferenciaNormalizacao`, config) e o **1º admin local** ▢ (hoje só via `seed`/admin global — **gap**) →
   turmas/professores ⭐ → **importar matrículas** (Seção [20](20-migracao-importacao.md)) → **gerar cartões** ⭐ →
   **coletar o consentimento** (termo; política = Seção [12](12-seguranca-privacidade.md)).
3. **1ª aula (corredor de login)** ⭐ — o **runbook operacional** na sala (cartões impressos, tablet, o professor
   conduz o "quem vai jogar" com as falas canônicas — Seção [02](02-vocabulario.md)). O **"Passo 0 do professor"**
   (FTUE adulto) e o artefato **"roteiro da 1ª aula"** da página só-do-professor são da Seção [10](10-professor-familia.md);
   a 21 provê a **coreografia operacional** em torno deles.
4. **Operação diária** ⭐ — o professor acompanha "situação de acesso", regenera cartões perdidos (individual, sem
   derrubar a turma), arquiva/transfere alunos ("cartão descansando").
5. **Helpdesk** ▢ — 1ª linha: reset de acesso do adulto (link de token ⭐), árvores de troubleshooting (criança não
   entra, "É você?"/conta trocada, PWA/cache, áudio), escalonamento à engenharia (Seção [14](14-infra-deploy-dr.md)).
6. **Incidente & manutenção** ▢ — a 21 **detecta/tria/escala** o técnico à Seção [14](14-infra-deploy-dr.md) e
   **comunica** à escola (tom adulto, respeitando o calendário letivo); a **mecânica interna** (severidade/on-call,
   agendamento da janela) é da 14; a **status page voltada ao cliente** é da 21 (delegação 14→21).
7. **Sucesso do cliente** ▢ — métricas de sucesso/health score (indicadores = Seção [17](17-telemetria-metricas.md)),
   intervenção proativa, renovação (comercial = Seção [22](22-monetizacao.md)), loop de feedback → Seção [23](23-roadmap.md).
8. **Offboarding** ▢ — encerramento ordenado, **retenção/anonimização** (política = Seção [12](12-seguranca-privacidade.md))
   e **continuidade pedagógica** (certificados/resumo que a escola/família leva).

### 6. Interface (quando existir)
As superfícies de operação **que já existem** são do **Edu web** (a tela de contas/reset em `Usuarios`, a de escolas
do admin global, e a de cartões/"situação de acesso" da turma — Seção [10](10-professor-familia.md)). As superfícies
**que faltam** (portal/painel de suporte, base de conhecimento, ferramenta de helpdesk, "entrar como") são **decisão
do dono** (§15). A 21 define **o que** cada superfície de suporte deve fazer; o **layout** é da Seção [07](07-ux-fluxos-navegacao.md).

### 7. UX
A UX é do **adulto**: **procedimentos curtos e acionáveis**, **árvores de decisão** ("a criança não entra → aluno
**ativo**? — se **não**, é **"cartão descansando"**: reativar a matrícula se a criança voltou, **nunca** tentar
regenerar (o sistema recusa com 422); se **sim** → cartão certo? → regenerar individual"), **comunicação honesta**
(sem jargão técnico), e **materiais em
pt-BR** com linguagem simples. Todo roteiro que **toca a criança** (o corredor de login) usa o **vocabulário
canônico** (Seção [02](02-vocabulario.md)) e respeita as **palavras proibidas** na experiência infantil.

### 8. Game Design
**N/A** — a 21 é operação **do adulto**, fora do laço de jogo. Ponto de contato: a **coreografia da 1ª aula** (o
corredor de login) é o momento em que a operação da escola **entrega** a criança ao jogo — o *handoff* da **tela**
para a Seção [08](08-onboarding-ftue.md) (FTUE do aluno) e das **falas** para a Seção [02](02-vocabulario.md); o
**Passo 0 do professor** e o **roteiro da 1ª aula** são da Seção [10](10-professor-familia.md). A 21 cuida da **sala**.

### 9. Regras de negócio
As **normas de suporte e operação** (a fonte da estratégia; papéis = Seção [10](10-professor-familia.md), incidente
técnico = Seção [14](14-infra-deploy-dr.md), política LGPD = Seção [12](12-seguranca-privacidade.md), planos = Seção [22](22-monetizacao.md)):

| # | Norma | Regra | Fronteira |
|---|-------|-------|-----------|
| S1 | **Três onboardings distintos** | onboarding da **escola** (21: tenant+admin+padrões+1ª aula) ≠ onboarding do **aluno** no jogo (Seção [08](08-onboarding-ftue.md), FTUE) ≠ **provisionamento técnico**/ETL (Seção [20](20-migracao-importacao.md)) | 21; FTUE = [08](08-onboarding-ftue.md); ETL = [20](20-migracao-importacao.md) |
| S2 | **Autosserviço × suporte** | o dia a dia (regenerar cartão, ligar social, gerar cartões, arquivar aluno) é **autosserviço**; o suporte trata o excepcional e **escala** o técnico à engenharia | 21; papéis = [10](10-professor-familia.md) |
| S3 | **Onboarding operacional da escola** | jornada do "go" à 1ª aula jogável: criar escola → padrões → 1º admin → turmas → matrículas ([20](20-migracao-importacao.md)) → cartões → consentimento; **checklist** no Apêndice F | 21 → Apêndice F |
| S4 | **Provisionar a escola nova** | a escola nova precisa dos **padrões pedagógicos** (níveis, `ReferenciaNormalizacao`, config) e de um **1º admin local**; hoje `POST /escolas` é **casco parcial** (só a linha Escola) e os padrões só existem para 'JORGE PASSOS' | 21 ⚠️ (auto-provisionar? — §15) |
| S5 | **Reset de acesso do adulto** | mecanismo Q0: **link de token** de uso único (60 min, hash SHA-256), invalidando links anteriores; **quem pode**: admin→todos, coordenador→si+professores, professor→si; **e-mail automático/convite** é decisão do dono | 21 (procedimento) ⚠️ (e-mail — §15); mecanismo = [11](11-arquitetura.md)/[12](12-seguranca-privacidade.md) |
| S6 | **Suporte ao login da criança** | cartão perdido → **regenerar individual** (não derruba a turma); roubo/vazamento → **revogar QR** (`token_version`) mantendo o **código** que a criança decorou; aluno transferido → **"cartão descansando"** (P6) | 21; mecanismo `token_version` = [11](11-arquitetura.md) |
| S7 | **Árvores de troubleshooting** | roteiros de 1ª linha: **criança não entra** (aluno ativo? cartão certo?), **"É você?"/conta trocada** (tablet compartilhado), **app não abre/cache do PWA**, **áudio/narração não toca** | 21 |
| S8 | **Incidente: detectar → escalar → comunicar** | a 21 **detecta/tria** e **escala** o técnico à Seção [14](14-infra-deploy-dr.md); **comunica** à escola em **tom adulto, não técnico**; a **mecânica interna** (severidade/on-call, sinais de health/status) é da 14, mas a **status page voltada ao cliente** (comunicação de status às escolas) é da 21 (delegação 14→21) | 21 (voz + status ao cliente); mecânica = [14](14-infra-deploy-dr.md) |
| S9 | **Comunicação de manutenção & cutover** | a 21 **comunica** a janela de manutenção (a Seção [14](14-infra-deploy-dr.md) **agenda/opera** a mecânica; a 21 pode **propor** um horário sensível ao calendário como insumo) e **comunica/agenda** o **cutover** da migração (estratégia técnica = Seção [20](20-migracao-importacao.md)), respeitando o **calendário letivo** | 21 (comunicação); janela = [14](14-infra-deploy-dr.md); cutover = [20](20-migracao-importacao.md) |
| S10 | **Fluxo LGPD dos titulares** | a 21 **executa** o fluxo operacional dos direitos (acesso/correção/exclusão/anonimização) que a Seção [12](12-seguranca-privacidade.md) **delega** ("exercidos pela escola; fluxo operacional é da 21"); **prazo/base legal/gatilho** são da 12 | 21 (execução); política = [12](12-seguranca-privacidade.md) |
| S11 | **Denúncia social encaminhada** | a denúncia que chega por um canal de **suporte** é **roteada para a fila de moderação** da Seção [10](10-professor-familia.md); a **regra** da denúncia é da Seção [09](09-social.md) e o **fluxo/fila/SLA** de moderação é da Seção [10](10-professor-familia.md) — a 21 **não** cria caminho paralelo | 21 (roteamento à fila da [10](10-professor-familia.md)); regra = [09](09-social.md); fluxo = [10](10-professor-familia.md) |
| S12 | **Ferramentas de suporte + "entrar como"** | ferramentas com **visão por escola** (P15, sem acesso indiscriminado — a ferramenta escopada é ▢); o **"entrar como" de adulto** é **sempre auditado** (`logs_auditoria`) e sob **política a definir**; o **"entrar como" de criança** engaja **P16** (identidade) e **P1** (código é a única credencial) e é **desaconselhado** — usar as ferramentas **não-impersonantes** (`GET .../acessos`, regeneração individual); qualquer exceção é **auditada e consentida** pela escola | 21 ⚠️ (política de impersonação — §15); auditoria = [12](12-seguranca-privacidade.md) |
| S13 | **Métricas de sucesso do cliente** | health score e sinais de churn **compostos** sobre a **taxonomia** da Seção [17](17-telemetria-metricas.md); a **definição do indicador composto** é da 17; as **metas** e o gatilho de intervenção são decisão do dono | 21 (metas/uso operacional) ⚠️ (metas — §15); definição do indicador = [17](17-telemetria-metricas.md) |
| S14 | **Offboarding ordenado** | encerramento da escola/turma com **continuidade pedagógica** (certificados/resumo que a família leva); a **retenção/anonimização** segue a Seção [12](12-seguranca-privacidade.md) (erasure ainda aberto) | 21 (procedimento) ⚠️ (prazo depende do erasure — §15); retenção = [12](12-seguranca-privacidade.md) |
| S15 | **Canais & SLA de suporte** | canais oficiais (e-mail/WhatsApp/telefone), categorização e **SLA por severidade**; o **SLA contratual por plano** depende da Seção [22](22-monetizacao.md) (planos ainda ⬛) | 21 ⚠️ (canais/SLA — §15); SLA-por-plano = [22](22-monetizacao.md) |
| S16 | **Gating por contrato** | se a **ativação** da escola depende de plano/contrato é **referência** à Seção [22](22-monetizacao.md); a 21 não modela billing (hoje a `Escola` não tem campo de contrato) | 21 (referencia); planos = [22](22-monetizacao.md) |
| S17 | **Materiais de suporte** | pt-BR, **linguagem simples** para gestor/família; roteiros que **tocam a criança** respeitam o **vocabulário canônico** (Seção [02](02-vocabulario.md)) e as **palavras proibidas**; coerentes com a acessibilidade (Seção [13](13-acessibilidade.md)) | 21; vocabulário = [02](02-vocabulario.md) |

### 10. Arquitetura técnica
Onde a operação **toca** o código (Q0 real, salvo ▢):
- **Contas/reset** — `admin.py` (CRUD de usuário; `POST /usuarios/{uid}/redefinir-senha` → token; anti-lockout;
  `token_version`); `auth.py` (`/redefinir-senha` público). **Mecanismo** de token/`token_version` = Seção [11](11-arquitetura.md)/[12](12-seguranca-privacidade.md).
- **Escola/provisionamento** — `escolas.py` (`POST /escolas`, admin global — **casco parcial**); `academico.py`
  (`criar_professor_completo`, ciclo de vida do aluno); `seed.py` (padrões só p/ 'JORGE PASSOS' — **gap S4**).
- **Cartões** — `quest/routers/professor.py` (turma/individual; `GET .../acessos`); `credenciais.py` (`regenerar`
  mantém código, troca QR).
- **Observabilidade** — `main.py` (`/api/health*`, `/metrics`, `X-Request-ID`); `audit.py` (`logs_auditoria`). **A
  operação** (health/status/on-call) é da Seção [14](14-infra-deploy-dr.md).
- **A construir (▢)** — ferramenta de helpdesk/tickets, status page ao cliente, e-mail/convite, endpoint de leitura de
  auditoria para suporte, "entrar como" auditado — todos **fora** do Q0 (§15).

### 11. Dependências com outros módulos
**Consome / referencia:**
- **Seção [10](10-professor-familia.md)** — os **papéis**, os **portais** (Professor/Família) e a **geração de cartões**.
- **Seção [14](14-infra-deploy-dr.md)** — a **mecânica** de incidente/health/status e a **agenda** da janela de manutenção.
- **Seção [12](12-seguranca-privacidade.md)** — a **política** LGPD (a 21 executa o **fluxo operacional** que a 12 delega).
- **Seção [20](20-migracao-importacao.md)** — o **provisionamento** e a **estratégia técnica** de cutover (a 21 comunica/agenda).
- **Seção [19](19-liveops.md)** — os **valores** de config `quest.*` (ex.: janela de horário) que a ativação **liga**;
  o **default do social é DESLIGADO (opt-in), já decidido pela Seção [09](09-social.md)** (Princípio 3 / LGPD Art. 14) — não é decisão em aberto.
- **Seção [17](17-telemetria-metricas.md)** — a **taxonomia** e a **definição** dos indicadores das métricas de sucesso.
- **Seção [22](22-monetizacao.md)** — os **planos/contratos** (SLA por plano, gating de ativação).
- **Seção [10](10-professor-familia.md)** — o **fluxo/fila/SLA de moderação** (para onde a 21 **roteia** a denúncia) e o
  **Passo 0 do professor**; **Seção [09](09-social.md)** — a **regra** da denúncia; **Seção [08](08-onboarding-ftue.md)** —
  a **FTUE do aluno** (handoff da 1ª aula); **Seção [11](11-arquitetura.md)** — `token_version`/rate-limit/isolamento.

**Alimenta:**
- **Apêndice F** — os **checklists operacionais** (ativação de escola, DoD de suporte).
- **Seção [23](23-roadmap.md)** — o **loop de feedback** do suporte para o produto.

**O que quebra se mudar:** se a Seção [22](22-monetizacao.md) definir **planos**, a 21 **fecha** o SLA por plano e o
gating; se a Seção [12](12-seguranca-privacidade.md) fechar **erasure**, a 21 **acopla** o offboarding; se a Seção
[10](10-professor-familia.md) mudar **papéis**, a 21 **reajusta** os procedimentos.

### 12. Casos extremos (Edge Cases)
- **Criança não entra** → aluno **ativo**? Se **não** (transferido/arquivado) → é **"cartão descansando"**: reativar
  a matrícula (ação de admin) se a criança voltou, **nunca** tentar regenerar (o sistema recusa com **422**, P6). Se
  **sim** → cartão **certo**? senão → regenerar **individual** (S6/S7).
- **Tablet compartilhado, "É você?" com nome errado** → o fluxo "quem vai jogar" troca de perfil; não é bug (S7).
- **Cartão perdido/roubado** → revogar QR (`token_version`) **mantendo o código** decorado (S6).
- **App não abre / tela velha** → cache do PWA (a API nunca é cacheada; forçar atualização) (S7).
- **Escola nova sem níveis de dificuldade** → a pontuação por nível fica **sem base** até alguém cadastrar (o casco
  parcial do `POST /escolas` — **gap S4**, §15).
- **Reset de acesso** → link de token **60 min**; expirado → gerar novo (S5).
- **"Entrar como" para diagnosticar** → o de **adulto** é **sempre auditado** e sem política definida **não** é feito
  às cegas; o de **criança** engaja P16/P1 e é **desaconselhado** — usar as ferramentas não-impersonantes (`GET .../acessos`,
  regeneração individual), reservando-o a exceção auditada e consentida (S12, §15).
- **Incidente técnico** → a 21 **não** conserta o backend; **escala** à Seção [14](14-infra-deploy-dr.md) e comunica
  à escola (S8).
- **Offboarding** → antes de anonimizar, entregar **certificados/resumo**; o prazo depende do erasure (Seção [12](12-seguranca-privacidade.md), §15).
- **SLA por plano sem planos** → a 21 **não** inventa planos; espera a Seção [22](22-monetizacao.md) (S15/S16).

### 13. Escalabilidade futura
- **Ferramenta de helpdesk** (tickets/fila/SLA) — canal externo (e-mail/WhatsApp) apoiado no `X-Request-ID` + `logs_auditoria`, ou painel próprio (▢/⚠️ §15).
- **Status page ao cliente** — reusando os sinais da Seção [14](14-infra-deploy-dr.md) (▢).
- **Auto-provisionamento da escola nova** (padrões + 1º admin) — fechar o gap S4 (▢/⚠️ §15).
- **E-mail automático + convite self-service** — reverter a entrega manual, entregando **só um link de uso único**
  (definir/redefinir senha), **nunca a senha em texto** (o modelo já prevê "autoatendimento futuro") (▢/⚠️ §15).
- **"Entrar como" auditado** + endpoint de leitura de auditoria para suporte (▢/⚠️ §15).
- **Customer success dedicado** (papel + cadência/QBR) — ou o dono/professor-embaixador absorve (▢/⚠️ §15).

### 14. Checklist de implementação
**"Pronto quando" (liga ao Apêndice F). Itens ⚠️ dependem de decisão do dono (§15):**
- [x] **Três onboardings** separados no vocabulário (escola/aluno/ETL) (S1).
- [ ] **Autosserviço × suporte** documentado (o que a escola resolve sozinha) (S2).
- [ ] **Jornada de onboarding da escola** (do "go" à 1ª aula) + checklist no Apêndice F (S3).
- [ ] ⚠️ **Provisionar a escola nova** (padrões + 1º admin local) — decidir auto-provisionar (gap S4).
- [x] **Reset de acesso** por link de token (60 min) — ⚠️ e-mail automático a decidir (S5).
- [x] **Suporte ao login da criança** (regenerar individual, revogar QR, "cartão descansando") (S6).
- [ ] **Árvores de troubleshooting** de 1ª linha (login/"É você?"/PWA/áudio) (S7).
- [ ] **Fluxo de incidente** (detectar→escalar→comunicar), tom adulto (S8).
- [ ] **Comunicação de manutenção & cutover** respeitando o calendário letivo (S9).
- [ ] **Fluxo LGPD dos titulares** (execução do que a Seção [12](12-seguranca-privacidade.md) delega) (S10).
- [ ] **Denúncia social** roteada à **fila de moderação da Seção [10](10-professor-familia.md)** (regra = Seção [09](09-social.md)) (S11).
- [ ] ⚠️ **Ferramentas de suporte + "entrar como" auditado** (política de impersonação) (S12).
- [ ] ⚠️ **Métricas de sucesso/health score** (metas; definição do indicador = Seção [17](17-telemetria-metricas.md)) (S13).
- [ ] ⚠️ **Offboarding** com continuidade pedagógica; retenção = Seção [12](12-seguranca-privacidade.md) (prazo depende do erasure) (S14).
- [ ] ⚠️ **Canais & SLA** de suporte (SLA por plano = Seção [22](22-monetizacao.md)) (S15).
- [ ] **Gating por contrato** = referência à Seção [22](22-monetizacao.md); a 21 não modela billing (S16).
- [x] **Política/vocabulário dos materiais** definido (pt-BR, vocabulário canônico, palavras proibidas); os materiais em si (S3/S7) ficam [ ] até serem produzidos (S17).

### 15. Questões em aberto
Cada item é **decisão do dono** (⚠️); os defaults são **propostas** da 21, não decisões autônomas (9 perguntas já
registradas no `INDICE.md`):

- ⚠️ **S15 / 21.12/21.39/21.40 — Modelo e SLA de suporte.** Canais oficiais (e-mail/WhatsApp/telefone), horário,
  tempo-alvo de resposta por severidade, e o **SLA contratual por plano** (bloqueado até a Seção [22](22-monetizacao.md)
  definir planos). Ferramenta de helpdesk (externa vs painel próprio).
- ⚠️ **21.41 / 21.31 — Customer success dedicado & renovação.** Haverá **papel de CS** com cadência/QBR e **playbook
  de renovação/expansão**, ou o dono/professor-embaixador absorve o onboarding? (a renovação/expansão cruza com a
  Seção [22](22-monetizacao.md)).
- ⚠️ **S12 / 21.37 — "Entrar como" (impersonar).** O suporte pode impersonar um **adulto** (professor) para
  diagnosticar, e sob qual **política de auditoria/consentimento**? O **"entrar como" de criança** engaja **P16**
  (identidade sagrada) e **P1** (código é a única credencial) e deve ser **desaconselhado** em favor das ferramentas
  não-impersonantes; qualquer exceção é auditada e consentida pela escola. A Seção [12](12-seguranca-privacidade.md)
  **exige** auditoria mas não define a política de suporte.
- ⚠️ **S13 / 21.29/21.30 — Métricas de sucesso.** Quais indicadores definem uma escola "de sucesso" (alunos
  ativos/semana, missões concluídas — taxonomia = Seção [17](17-telemetria-metricas.md)) e qual o **gatilho de
  intervenção proativa** do health score?
- ⚠️ **S14 / offboarding.** O que a escola/família **leva** (exportações, certificados) e em **que prazo** os dados
  são anonimizados — depende do **erasure** aberto na Seção [12](12-seguranca-privacidade.md) §15.
- ⚠️ **S4 / 21.6 — Ativação e valores de fábrica.** `POST /escolas` deve **auto-provisionar** os padrões pedagógicos
  (níveis, `ReferenciaNormalizacao`, config) e um **1º admin local**? E os **valores de fábrica** das configs
  `quest.*` (ex.: **janela de horário** = Seção [19](19-liveops.md)). *O social já é **desligado por padrão** (opt-in),
  decisão aprovada da Seção [09](09-social.md) — não está em aberto; o **prazo de retenção/anonimização** é política da
  Seção [12](12-seguranca-privacidade.md), não config da 19.*
- ⚠️ **S5 — E-mail automático & convite.** Reset e criação de conta ganham **e-mail automático** e **convite
  self-service**, entregando **só um link de uso único** (definir/redefinir senha) e **nunca a senha em texto**
  (revertendo a entrega manual do link)? O modelo já prevê "autoatendimento futuro", desligado.
- ⚠️ **21.11 — Treinamento do professor.** Material, formato e duração da capacitação mínima para conduzir a aula sem depender do suporte.
- ⚠️ **Dono do onboarding da rede.** Quem cria a **escola** e o **1º admin local** (hoje só um **admin global** —
  isto é, a própria Constela provisiona cada escola)? É esse o processo de customer success desejado?

### 16. ADR (Architecture Decision Record)
- **ADR-21-A — O suporte executa; não decide o produto.** A 21 dá **procedimentos executáveis** por um time de
  suporte, sobre a mecânica Q0 real (cartões, reset por token, ciclo de vida do aluno); **papéis** (Seção
  [10](10-professor-familia.md)), **incidente técnico** (Seção [14](14-infra-deploy-dr.md)), **política LGPD** (Seção
  [12](12-seguranca-privacidade.md)), **provisionamento** (Seção [20](20-migracao-importacao.md)) e **planos** (Seção
  [22](22-monetizacao.md)) são das donas — a 21 **aplica** e **comunica**.
- **ADR-21-B — Três onboardings, sem colisão.** Onboarding da **escola** (21), **FTUE do aluno** (Seção
  [08](08-onboarding-ftue.md)) e **provisionamento técnico/ETL** (Seção [20](20-migracao-importacao.md)) são coisas
  distintas com donos distintos; a 21 é dona só do **operacional da escola** (tenant+admin+padrões+1ª aula).
- **ADR-21-C — A voz ao cliente é da 21; a mecânica técnica não.** Em incidente/manutenção, a 21 **comunica** à escola
  em tom adulto (podendo **propor** um horário sensível ao calendário como insumo); a **severidade/on-call, o
  agendamento da janela e os sinais de status/health** são da Seção [14](14-infra-deploy-dr.md). No **cutover**, a 21
  **comunica/agenda** (estratégia técnica = Seção [20](20-migracao-importacao.md)). A **status page voltada ao
  cliente** é comunicação da 21 (delegação 14→21).
- **ADR-21-D — Acesso a dado de criança pelo suporte é sempre auditado e por escola.** As ferramentas de suporte
  **devem** ter **visão por `escola_id`** (P15 — hoje o suporte opera pelo admin global, cross-escola; o escopo é ▢) e
  o **"entrar como"** deixa rastro em `logs_auditoria` (regra da Seção [12](12-seguranca-privacidade.md)). O **"entrar
  como" de criança** engaja **P16** e **P1** e é **desaconselhado** (usar as ferramentas não-impersonantes); a
  **política** de quando/quem pode impersonar é decisão do dono (§15).

*Decisões cross-módulo não são improvisadas aqui: as pendências acima viram ADR ou item de §15.*

---

## 🇬🇧 Support, Customer Success & School Ops

### 1. Objective
To be the **definitive reference for how a school is led to success** in Constela: **operational onboarding**,
**teacher helpdesk**, **classroom operation** (cards and login), **incident and communication**, **FAQ**, **success
metrics** and **offboarding** — all **executable by a support team**. It decides the **procedure and the
communication**; it does **not** decide roles (Section [10](10-professor-familia.md)), technical incidents (Section
[14](14-infra-deploy-dr.md)), the LGPD policy (Section [12](12-seguranca-privacidade.md)), provisioning (Section
[20](20-migracao-importacao.md)) nor plans (Section [22](22-monetizacao.md)) — it only **applies** them. It feeds **Appendix F**.

### 2. Context
In **Hub → Edu → Quest**, the **paying customer is the school/network** (the child is never a revenue source —
P7/Section [22](22-monetizacao.md)), and support talks to **adults** (manager, coordinator, teacher, family).
**Current state (Q0) — there is operation mechanics, but no formal helpdesk:**
- **Roles** — `admin` | `coordenador` | `professor` (+ the `is_global` flag = network super-admin); `responsável`
  exists only in the model (Section [10](10-professor-familia.md)). Scoped listing: admin sees all, coordinator sees
  self+teachers, teacher only their own account.
- **Account management** — create/edit/delete a user (**logical** delete; physical only by a global admin with
  confirmation); **anti-lockout** (the last active admin is untouchable; nobody demotes/deletes their own account).
- **Adult access reset** — `POST /usuarios/{uid}/redefinir-senha` generates a **single-use link** expiring in
  **60 min** (stores only the SHA-256 hash); the password is only a **bcrypt hash** (token recovery, not reversible).
  Today the link (and the freshly-created teacher's readable password) **comes back in the HTTP response** for
  **manual delivery** — there is **no automatic e-mail nor self-service** (the model foresees "future self-service", off).
- **Child login support** — **code-only** login (`PALAVRA+NNNN`); the teacher generates **PDF cards** per class or
  **individually** (the individual one **does not take down the class**); `regenerar` **keeps the code** the child
  memorized and **swaps the QR** (revocation via `token_version`); an inactive student → **"resting card"** (does not
  punish, P6); per-student access status at `GET .../acessos`.
- **School onboarding** — **manual and fragmented**: `POST /escolas` is **global-admin only** and creates **just the
  Escola row** (a **partial shell**: no local admin, no classes, and **no pedagogical defaults** — difficulty levels,
  `ReferenciaNormalizacao`, `Configuracao` — which `seed` creates **only for 'JORGE PASSOS'**). There is no self-service signup.
- **Observability for support** — `/api/health*`, `/metrics`, `X-Request-ID` exposed ("useful in the support
  report"), and **everything audited** in `logs_auditoria` (`usuario.reset_solicitado`, `quest.cartoes_gerados`, `login.falhou/bloqueado`).
- **Multi-tenant without plan/contract** — the `Escola` has name/city/state/logo/school-year/status; **nothing** of a
  plan, seats, support contact or contract dates (monetization not modeled — Section [22](22-monetizacao.md)).
- **Not present** — a **ticket/SLA/escalation** system; a customer **status page**; **self-service onboarding**;
  **automatic e-mail** and **invite**; a **Help** page on web; a **read endpoint** for the audit log for investigation.

This chapter **formalizes** operation and support, and records what remains to be decided.

### 3. Feature philosophy
**"The school must succeed even with a shared tablet, flaky wifi and a teacher who has never used the system."**
Support is where the product **touches the reality of the public classroom**. Principles: **the day-to-day cannot
depend on support** (regenerating a card, turning social on, generating cards are self-service); **support executes,
does not decide the product** (follows procedure, escalates the technical to engineering); **the voice to the
customer is adult, warm and non-technical** (the school hears "we're on it", not a *stack trace*); **the error never
punishes the child** (a lost card is a "resting card", never a "wrong code" — P6); and **all access to child data is
audited** (support that "logs in as" leaves a trace in `logs_auditoria` — Section [12](12-seguranca-privacidade.md)'s rule).

Link to the **Immutable Principles** ([01](01-principios-imutaveis.md)): **P1** (code-only login) — login
troubleshooting starts from "the code is the credential"; **P16** (identity in Edu) — support operates with the Edu
adult identity, no new sign-up; **P15** (isolation) — support tools **must** have a **per-school** view (▢ to build;
today the only support actor is the **global admin**, cross-school by nature — the `escola_id` scope is the gap to
close); **P6** (error never punishes) — the script treats the student with care, not blame.

### 4. The experience the player should feel
The child does **not** talk to support — they feel the **result**: on the first day, the **login corridor** works
("Quem vai jogar?" → "Sou eu!" → "É você, {nome}?"), the card works, and if something fails the teacher **fixes it on
the spot** (regenerates the individual card). **The teacher** feels **not alone**: a clear script, a short FAQ, and a
channel when stuck. **The manager** feels **partnership**: a guided onboarding, honest communication in
incidents/maintenance, and a signal that the school is doing well (or needs help).

### 5. Complete flow
The **school lifecycle**, from contract to offboarding (⭐ = Q0 mechanics exist; ▢ = decision/strategy to do):

1. **Contract** ▢ — the sale/licensing is Section [22](22-monetizacao.md)'s; 21 **starts after the "go"**.
2. **School onboarding** ▢/⭐ — create the school ⭐ (today `POST /escolas`, global admin) → **provision the defaults**
   (levels, `ReferenciaNormalizacao`, config) and the **1st local admin** ▢ (today only via `seed`/global admin —
   **gap**) → classes/teachers ⭐ → **import enrollments** (Section [20](20-migracao-importacao.md)) → **generate cards** ⭐ →
   **collect consent** (form; policy = Section [12](12-seguranca-privacidade.md)).
3. **First class (login corridor)** ⭐ — the classroom **operational runbook** (printed cards, tablet, the teacher
   runs the "who's playing" with the canonical lines — Section [02](02-vocabulario.md)). The **"teacher's Step 0"**
   (adult FTUE) and the **"first-class script"** artifact of the teacher-only card page are Section
   [10](10-professor-familia.md)'s; 21 provides the **operational choreography** around them.
4. **Daily operation** ⭐ — the teacher tracks "access status", regenerates lost cards (individually, without taking
   down the class), archives/transfers students ("resting card").
5. **Helpdesk** ▢ — first line: adult access reset (token link ⭐), troubleshooting trees (child can't enter,
   "É você?"/swapped account, PWA/cache, audio), escalation to engineering (Section [14](14-infra-deploy-dr.md)).
6. **Incident & maintenance** ▢ — 21 **detects/triages/escalates** the technical to Section [14](14-infra-deploy-dr.md)
   and **communicates** to the school (adult tone, respecting the school calendar); the **internal mechanics**
   (severity/on-call, window scheduling) are 14's; the **customer-facing status page** is 21's (14→21 delegation).
7. **Customer success** ▢ — success metrics/health score (indicators = Section [17](17-telemetria-metricas.md)),
   proactive intervention, renewal (commercial = Section [22](22-monetizacao.md)), feedback loop → Section [23](23-roadmap.md).
8. **Offboarding** ▢ — orderly closure, **retention/anonymization** (policy = Section [12](12-seguranca-privacidade.md))
   and **pedagogical continuity** (certificates/summary the school/family takes with them).

### 6. Interface (when it exists)
The operation surfaces **that already exist** belong to the **Edu web** (the accounts/reset screen in `Usuarios`, the
global-admin school screen, and the class cards/"access status" screen — Section [10](10-professor-familia.md)). The
surfaces **that are missing** (support portal/panel, knowledge base, helpdesk tool, "log in as") are an **owner
decision** (§15). 21 defines **what** each support surface must do; the **layout** is Section [07](07-ux-fluxos-navegacao.md)'s.

### 7. UX
The UX is the **adult's**: **short, actionable procedures**, **decision trees** ("the child can't enter → **active**
student? — if **not**, it's a **"resting card"**: reactivate the enrollment if the child returned, **never** try to
regenerate (the system refuses with 422); if **yes** → right card? → regenerate individually"), **honest
communication** (no technical jargon), and **materials in pt-BR** with plain language. Every script that **touches
the child** (the login corridor) uses the **canonical
vocabulary** (Section [02](02-vocabulario.md)) and respects the **forbidden words** in the child experience.

### 8. Game Design
**N/A** — 21 is **adult** operation, outside the game loop. Point of contact: the **first-class choreography** (the
login corridor) is when school operation **hands** the child to the game — the *handoff* of the **screen** to Section
[08](08-onboarding-ftue.md) (student FTUE) and of the **lines** to Section [02](02-vocabulario.md); the **teacher's
Step 0** and the **first-class script** are Section [10](10-professor-familia.md)'s. 21 takes care of the **classroom**.

### 9. Business rules
The **support and operation norms** (the source of the strategy; roles = Section [10](10-professor-familia.md),
technical incident = Section [14](14-infra-deploy-dr.md), LGPD policy = Section [12](12-seguranca-privacidade.md), plans = Section [22](22-monetizacao.md)):

| # | Norm | Rule | Boundary |
|---|------|------|----------|
| S1 | **Three distinct onboardings** | **school** onboarding (21: tenant+admin+defaults+first class) ≠ **student** onboarding in the game (Section [08](08-onboarding-ftue.md), FTUE) ≠ **technical provisioning**/ETL (Section [20](20-migracao-importacao.md)) | 21; FTUE = [08](08-onboarding-ftue.md); ETL = [20](20-migracao-importacao.md) |
| S2 | **Self-service × support** | the day-to-day (regenerate a card, turn social on, generate cards, archive a student) is **self-service**; support handles the exceptional and **escalates** the technical to engineering | 21; roles = [10](10-professor-familia.md) |
| S3 | **School operational onboarding** | the journey from "go" to a playable first class: create school → defaults → 1st admin → classes → enrollments ([20](20-migracao-importacao.md)) → cards → consent; **checklist** in Appendix F | 21 → Appendix F |
| S4 | **Provision the new school** | a new school needs the **pedagogical defaults** (levels, `ReferenciaNormalizacao`, config) and a **1st local admin**; today `POST /escolas` is a **partial shell** (just the Escola row) and defaults exist only for 'JORGE PASSOS' | 21 ⚠️ (auto-provision? — §15) |
| S5 | **Adult access reset** | Q0 mechanism: a single-use **token link** (60 min, SHA-256 hash), invalidating previous links; **who can**: admin→all, coordinator→self+teachers, teacher→self; **automatic e-mail/invite** is an owner decision | 21 (procedure) ⚠️ (e-mail — §15); mechanism = [11](11-arquitetura.md)/[12](12-seguranca-privacidade.md) |
| S6 | **Child login support** | lost card → **regenerate individually** (does not take down the class); theft/leak → **revoke QR** (`token_version`) keeping the **code** the child memorized; transferred student → **"resting card"** (P6) | 21; `token_version` mechanism = [11](11-arquitetura.md) |
| S7 | **Troubleshooting trees** | first-line scripts: **child can't enter** (active student? right card?), **"É você?"/swapped account** (shared tablet), **app won't open/PWA cache**, **audio/narration won't play** | 21 |
| S8 | **Incident: detect → escalate → communicate** | 21 **detects/triages** and **escalates** the technical to Section [14](14-infra-deploy-dr.md); **communicates** to the school in an **adult, non-technical tone**; the **internal mechanics** (severity/on-call, health/status signals) are 14's, but the **customer-facing status page** (status communication to schools) is 21's (14→21 delegation) | 21 (voice + customer status); mechanics = [14](14-infra-deploy-dr.md) |
| S9 | **Maintenance & cutover communication** | 21 **communicates** the maintenance window (Section [14](14-infra-deploy-dr.md) **schedules/operates** the mechanics; 21 may **propose** a calendar-sensitive time as input) and **communicates/schedules** the migration **cutover** (technical strategy = Section [20](20-migracao-importacao.md)), respecting the **school calendar** | 21 (communication); window = [14](14-infra-deploy-dr.md); cutover = [20](20-migracao-importacao.md) |
| S10 | **Data-subject LGPD flow** | 21 **executes** the operational flow of the rights (access/correction/deletion/anonymization) that Section [12](12-seguranca-privacidade.md) **delegates** ("exercised by the school; the operational flow is 21's"); **deadline/legal basis/trigger** are 12's | 21 (execution); policy = [12](12-seguranca-privacidade.md) |
| S11 | **Forwarded social report** | a report arriving via a **support** channel is **routed to the moderation queue** of Section [10](10-professor-familia.md); the **rule** of the report is Section [09](09-social.md)'s and the moderation **flow/queue/SLA** is Section [10](10-professor-familia.md)'s — 21 does **not** create a parallel path | 21 (routing to [10](10-professor-familia.md)'s queue); rule = [09](09-social.md); flow = [10](10-professor-familia.md) |
| S12 | **Support tools + "log in as"** | tools with a **per-school** view (P15, no indiscriminate access — the scoped tool is ▢); **adult "log in as"** is **always audited** (`logs_auditoria`) and under a **policy to be defined**; **child "log in as"** engages **P16** (identity) and **P1** (the code is the only credential) and is **discouraged** — use the **non-impersonating** tools (`GET .../acessos`, individual regeneration); any exception is **audited and consented** by the school | 21 ⚠️ (impersonation policy — §15); audit = [12](12-seguranca-privacidade.md) |
| S13 | **Customer-success metrics** | a health score and churn signals **composed** over Section [17](17-telemetria-metricas.md)'s **taxonomy**; the **definition of the composite indicator** is 17's; the **targets** and the intervention trigger are an owner decision | 21 (targets/operational use) ⚠️ (targets — §15); indicator definition = [17](17-telemetria-metricas.md) |
| S14 | **Orderly offboarding** | closure of the school/class with **pedagogical continuity** (certificates/summary the family takes); **retention/anonymization** follows Section [12](12-seguranca-privacidade.md) (erasure still open) | 21 (procedure) ⚠️ (deadline depends on erasure — §15); retention = [12](12-seguranca-privacidade.md) |
| S15 | **Support channels & SLA** | official channels (e-mail/WhatsApp/phone), categorization and **SLA per severity**; the **contractual SLA per plan** depends on Section [22](22-monetizacao.md) (plans still ⬛) | 21 ⚠️ (channels/SLA — §15); SLA-per-plan = [22](22-monetizacao.md) |
| S16 | **Contract gating** | whether school **activation** depends on a plan/contract is a **reference** to Section [22](22-monetizacao.md); 21 does not model billing (today the `Escola` has no contract field) | 21 (references); plans = [22](22-monetizacao.md) |
| S17 | **Support materials** | pt-BR, **plain language** for manager/family; scripts that **touch the child** respect the **canonical vocabulary** (Section [02](02-vocabulario.md)) and the **forbidden words**; consistent with accessibility (Section [13](13-acessibilidade.md)) | 21; vocabulary = [02](02-vocabulario.md) |

### 10. Technical architecture
Where operation **touches** code (real Q0, except ▢):
- **Accounts/reset** — `admin.py` (user CRUD; `POST /usuarios/{uid}/redefinir-senha` → token; anti-lockout;
  `token_version`); `auth.py` (public `/redefinir-senha`). The token/`token_version` **mechanism** = Section [11](11-arquitetura.md)/[12](12-seguranca-privacidade.md).
- **School/provisioning** — `escolas.py` (`POST /escolas`, global admin — **partial shell**); `academico.py`
  (`criar_professor_completo`, student lifecycle); `seed.py` (defaults only for 'JORGE PASSOS' — **gap S4**).
- **Cards** — `quest/routers/professor.py` (class/individual; `GET .../acessos`); `credenciais.py` (`regenerar` keeps
  the code, swaps the QR).
- **Observability** — `main.py` (`/api/health*`, `/metrics`, `X-Request-ID`); `audit.py` (`logs_auditoria`). **The
  operation** (health/status/on-call) is Section [14](14-infra-deploy-dr.md)'s.
- **To build (▢)** — a helpdesk/ticket tool, a customer status page, e-mail/invite, a read endpoint for the audit log
  for support, an audited "log in as" — all **outside** Q0 (§15).

### 11. Dependencies on other modules
**Consumes / references:**
- **Section [10](10-professor-familia.md)** — the **roles**, the **portals** (Teacher/Family) and **card generation**.
- **Section [14](14-infra-deploy-dr.md)** — the **mechanics** of incident/health/status and the maintenance-window **schedule**.
- **Section [12](12-seguranca-privacidade.md)** — the LGPD **policy** (21 executes the **operational flow** 12 delegates).
- **Section [20](20-migracao-importacao.md)** — the **provisioning** and the **technical cutover** strategy (21 communicates/schedules).
- **Section [19](19-liveops.md)** — the config `quest.*` **values** (e.g. the time window) activation **turns on**;
  the **social default is OFF (opt-in), already decided by Section [09](09-social.md)** (P16) — not an open decision.
- **Section [17](17-telemetria-metricas.md)** — the **taxonomy** and the **definition** of the success-metric indicators.
- **Section [22](22-monetizacao.md)** — the **plans/contracts** (SLA per plan, activation gating).
- **Section [10](10-professor-familia.md)** — the moderation **flow/queue/SLA** (where 21 **routes** a report) and the
  **teacher's Step 0**; **Section [09](09-social.md)** — the report **rule**; **Section [08](08-onboarding-ftue.md)** —
  the student **FTUE** (first-class handoff); **Section [11](11-arquitetura.md)** — `token_version`/rate-limit/isolation.

**Feeds:**
- **Appendix F** — the **operational checklists** (school activation, support DoD).
- **Section [23](23-roadmap.md)** — the support **feedback loop** to the product.

**What breaks if it changes:** if Section [22](22-monetizacao.md) defines **plans**, 21 **closes** the per-plan SLA
and gating; if Section [12](12-seguranca-privacidade.md) closes **erasure**, 21 **couples** offboarding; if Section
[10](10-professor-familia.md) changes **roles**, 21 **re-tunes** the procedures.

### 12. Edge cases
- **Child can't enter** → **active** student? If **not** (transferred/archived) → it's a **"resting card"**:
  reactivate the enrollment (an admin action) if the child returned, **never** try to regenerate (the system refuses
  with **422**, P6). If **yes** → **right** card? otherwise → regenerate **individually** (S6/S7).
- **Shared tablet, "É você?" with wrong name** → the "who's playing" flow switches profile; not a bug (S7).
- **Lost/stolen card** → revoke the QR (`token_version`) **keeping the memorized code** (S6).
- **App won't open / stale screen** → PWA cache (the API is never cached; force a refresh) (S7).
- **New school with no difficulty levels** → per-level scoring has **no basis** until someone registers them (the
  `POST /escolas` partial shell — **gap S4**, §15).
- **Access reset** → the token link lasts **60 min**; expired → generate a new one (S5).
- **"Log in as" to diagnose** → the **adult** one is **always audited** and with no defined policy is **not** done
  blindly; the **child** one engages P16/P1 and is **discouraged** — use the non-impersonating tools (`GET .../acessos`,
  individual regeneration), reserving it for an audited and consented exception (S12, §15).
- **Technical incident** → 21 does **not** fix the backend; it **escalates** to Section [14](14-infra-deploy-dr.md) and
  communicates to the school (S8).
- **Offboarding** → before anonymizing, deliver **certificates/summary**; the deadline depends on erasure (Section [12](12-seguranca-privacidade.md), §15).
- **Per-plan SLA without plans** → 21 does **not** invent plans; it waits for Section [22](22-monetizacao.md) (S15/S16).

### 13. Future scalability
- **Helpdesk tool** (tickets/queue/SLA) — an external channel (e-mail/WhatsApp) backed by `X-Request-ID` + `logs_auditoria`, or a dedicated panel (▢/⚠️ §15).
- **Customer status page** — reusing Section [14](14-infra-deploy-dr.md)'s signals (▢).
- **Auto-provisioning of a new school** (defaults + 1st admin) — closing gap S4 (▢/⚠️ §15).
- **Automatic e-mail + self-service invite** — reverting the manual delivery, sending **only a single-use link**
  (set/reset password), **never the plaintext password** (the model already foresees "future self-service") (▢/⚠️ §15).
- **Audited "log in as"** + a read endpoint for the audit log for support (▢/⚠️ §15).
- **Dedicated customer success** (role + cadence/QBR) — or the owner/teacher-ambassador absorbs it (▢/⚠️ §15).

### 14. Implementation checklist
**"Done when" (links to Appendix F). Items marked ⚠️ depend on an owner decision (§15):**
- [x] **Three onboardings** separated in the vocabulary (school/student/ETL) (S1).
- [ ] **Self-service × support** documented (what the school resolves alone) (S2).
- [ ] **School onboarding journey** (from "go" to the first class) + checklist in Appendix F (S3).
- [ ] ⚠️ **Provision the new school** (defaults + 1st local admin) — decide to auto-provision (gap S4).
- [x] **Access reset** via token link (60 min) — ⚠️ automatic e-mail to decide (S5).
- [x] **Child login support** (regenerate individually, revoke QR, "resting card") (S6).
- [ ] **Troubleshooting trees** first-line (login/"É você?"/PWA/audio) (S7).
- [ ] **Incident flow** (detect→escalate→communicate), adult tone (S8).
- [ ] **Maintenance & cutover communication** respecting the school calendar (S9).
- [ ] **Data-subject LGPD flow** (execution of what Section [12](12-seguranca-privacidade.md) delegates) (S10).
- [ ] **Social report** routed to **Section [10](10-professor-familia.md)'s moderation queue** (rule = Section [09](09-social.md)) (S11).
- [ ] ⚠️ **Support tools + audited "log in as"** (impersonation policy) (S12).
- [ ] ⚠️ **Success metrics/health score** (targets; indicator definition = Section [17](17-telemetria-metricas.md)) (S13).
- [ ] ⚠️ **Offboarding** with pedagogical continuity; retention = Section [12](12-seguranca-privacidade.md) (deadline depends on erasure) (S14).
- [ ] ⚠️ **Channels & SLA** of support (SLA per plan = Section [22](22-monetizacao.md)) (S15).
- [ ] **Contract gating** = reference to Section [22](22-monetizacao.md); 21 does not model billing (S16).
- [x] **Materials policy/vocabulary** defined (pt-BR, canonical vocabulary, forbidden words); the materials themselves (S3/S7) stay [ ] until produced (S17).

### 15. Open questions
Each item is an **owner decision** (⚠️); the defaults are 21's **proposals**, not autonomous decisions (9 questions
already recorded in `INDICE.md`):

- ⚠️ **S15 / 21.12/21.39/21.40 — Support model and SLA.** Official channels (e-mail/WhatsApp/phone), hours,
  target response time per severity, and the **contractual SLA per plan** (blocked until Section [22](22-monetizacao.md)
  defines plans). Helpdesk tool (external vs a dedicated panel).
- ⚠️ **21.41 / 21.31 — Dedicated customer success & renewal.** Will there be a **CS role** with cadence/QBR and a
  **renewal/expansion playbook**, or does the owner/teacher-ambassador absorb the onboarding? (renewal/expansion
  crosses with Section [22](22-monetizacao.md)).
- ⚠️ **S12 / 21.37 — "Log in as" (impersonate).** May support impersonate an **adult** (teacher) to diagnose, and
  under what **audit/consent policy**? The **child "log in as"** engages **P16** (sacred identity) and **P1** (the
  code is the only credential) and must be **discouraged** in favor of the non-impersonating tools; any exception is
  audited and consented by the school. Section [12](12-seguranca-privacidade.md) **requires** the audit but does not
  define the support policy.
- ⚠️ **S13 / 21.29/21.30 — Success metrics.** Which indicators define a "successful" school (active students/week,
  completed missions — taxonomy = Section [17](17-telemetria-metricas.md)) and what is the **proactive intervention
  trigger** of the health score?
- ⚠️ **S14 / offboarding.** What does the school/family **take** (exports, certificates) and in **what time frame** are
  the data anonymized — depends on the **erasure** open in Section [12](12-seguranca-privacidade.md) §15.
- ⚠️ **S4 / 21.6 — Activation and factory values.** Should `POST /escolas` **auto-provision** the pedagogical defaults
  (levels, `ReferenciaNormalizacao`, config) and a **1st local admin**? And the **factory values** of the `quest.*`
  configs (e.g. the **time window** = Section [19](19-liveops.md)). *Social is already **off by default** (opt-in), an
  approved decision of Section [09](09-social.md) — not open; the **retention/anonymization deadline** is Section
  [12](12-seguranca-privacidade.md)'s policy, not a Section 19 config.*
- ⚠️ **S5 — Automatic e-mail & invite.** Do reset and account creation gain **automatic e-mail** and **self-service
  invite**, delivering **only a single-use link** (set/reset password) and **never the plaintext password**
  (reverting the manual delivery of the link)? The model already foresees "future self-service", off.
- ⚠️ **21.11 — Teacher training.** Material, format and duration of the minimum training to run the class without depending on support.
- ⚠️ **Owner of network onboarding.** Who creates the **school** and the **1st local admin** (today only a **global
  admin** — i.e., Constela itself provisions each school)? Is this the desired customer-success process?

### 16. ADR (Architecture Decision Record)
- **ADR-21-A — Support executes; it does not decide the product.** 21 gives **executable procedures** for a support
  team, over the real Q0 mechanics (cards, token reset, student lifecycle); **roles** (Section
  [10](10-professor-familia.md)), **technical incident** (Section [14](14-infra-deploy-dr.md)), **LGPD policy**
  (Section [12](12-seguranca-privacidade.md)), **provisioning** (Section [20](20-migracao-importacao.md)) and **plans**
  (Section [22](22-monetizacao.md)) belong to their owners — 21 **applies** and **communicates**.
- **ADR-21-B — Three onboardings, no collision.** **School** onboarding (21), **student FTUE** (Section
  [08](08-onboarding-ftue.md)) and **technical provisioning/ETL** (Section [20](20-migracao-importacao.md)) are
  distinct things with distinct owners; 21 owns only the **school operational** part (tenant+admin+defaults+first class).
- **ADR-21-C — The voice to the customer is 21's; the technical mechanics are not.** In incident/maintenance, 21
  **communicates** to the school in an adult tone (and may **propose** a calendar-sensitive time as input); the
  **severity/on-call, the window scheduling and the status/health signals** are Section [14](14-infra-deploy-dr.md)'s.
  For the **cutover**, 21 **communicates/schedules** (technical strategy = Section [20](20-migracao-importacao.md)).
  The **customer-facing status page** is 21's communication (14→21 delegation).
- **ADR-21-D — Support access to child data is always audited and per school.** Support tools **must** have a
  **per-`escola_id`** view (P15 — today support operates via the global admin, cross-school; the scope is ▢) and
  **"log in as"** leaves a trace in `logs_auditoria` (Section [12](12-seguranca-privacidade.md)'s rule). The **child
  "log in as"** engages **P16** and **P1** and is **discouraged** (use the non-impersonating tools); the **policy** of
  when/who may impersonate is an owner decision (§15).

*Cross-module decisions are not improvised here: the pending items above become an ADR or a §15 entry.*
