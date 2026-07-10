# 19 — Live-ops & Configuração Remota / Live-ops & Remote Configuration

- **Status:** 🔴 rascunho / draft
- **Padrão / Standard:** [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) (16 partes)
- **Fontes / Sources:** `INDICE.md` (bloco 19, subseções 19.1–19.27; ⚠️ 19.7/19.9/19.15/19.22/19.23), `_estado-atual/RELATORIO-2026-07-09.md` (Q0: sem live-ops nem config remota de `quest.*`), `backend/app/models/configuracao.py` (`Configuracao` = tabela chave-valor por escola: `escola_id`/`namespace`/`chave`/`valor` JSON; UNIQUE), `backend/app/services/scoring.py` (`obter_config(db, escola_id, namespace, chave, padrao)` = padrão-no-código → override por escola), `backend/app/services/gamificacao.py` (defaults do **Edu** `NIVEL_BASE_XP_PADRAO=100`; namespaces `gamificacao.*` — homônimo, distinto do Quest), `backend/app/quest/models/catalogo.py` (docstring "namespace `quest.*`" **não implementado**; `xp_base=40`/`moedas_base=10`; `tipo ∈ {normal|chefão|evento}`, default `normal`), `backend/app/quest/models/perfil.py` (`social_ativo` default **False** por perfil; Chama `sequencia_dias`/`escudo_sequencia`), `backend/app/quest/models/progresso.py` (`dominio` "média móvel" — **α não existe no código**; `quest_tentativas` = registro imutável), `backend/app/core/rate_limit.py` + `backend/app/quest/routers/auth.py` (rate-limit **8/5min** e **300/5min hardcoded**), `backend/app/core/config.py` (flags de **infra** `DOCS_HABILITADOS`/`METRICS_ENABLED` — Seção 14), `backend/alembic/versions/0001_esquema_inicial.py` (**sem** tabelas de temporada/evento/passe/flag), Seções [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)/[09](09-social.md)/[10](10-professor-familia.md)/[11](11-arquitetura.md)/[12](12-seguranca-privacidade.md)/[13](13-acessibilidade.md)/[14](14-infra-deploy-dr.md)/[22](22-monetizacao.md)
- **Depende de / Depends on:** princípios (P6 erro/teto = celebração · P7 sem compra no app + **passe de temporada gratuito** · P8 zero dark patterns · P15 isolamento por escola · P18 sem tracking) → [01](01-principios-imutaveis.md); **mecanismo** de entrega de config/flags + **cron** + Redis → [14](14-infra-deploy-dr.md); **schema físico** da store/tabelas + **cache HTTP/ETag** → [11](11-arquitetura.md); **mecânicas** e os **números-padrão canônicos** (teto diário 600, curva de nível, **escudo semanal da Chama**) → [05](05-sistemas-de-jogo.md); **fórmula** do domínio (α=0,3) → [06](06-pedagogico-bncc.md); **política** de rate-limit (limites/janelas seguras) e o **prazo legal** de retenção → [12](12-seguranca-privacidade.md); **norma** de bem-estar (teto/pausa/horário) → [13](13-acessibilidade.md); **ética/decisão** de A/B com criança → [17](17-telemetria-metricas.md); **regra** social (opt-in/alcance/anti-spam) e o **reset** do ranking de turma → [09](09-social.md); **moderação/SLA** e **frequência** do push da família → [10](10-professor-familia.md); **modelo de negócio** do passe (gratuidade — P7 / ADR candidato C.20) → [22](22-monetizacao.md); **conteúdo** sazonal (mundos/loja/coleções) → [03](03-universo.md)/[04](04-personagens-avatar.md)/[07](07-ux-fluxos-navegacao.md).

> **Convenção / Convention:** "§N" = uma das 16 **partes deste capítulo** / one of the 16 **parts of this
> chapter**; "Seção NN" / "Section NN" = outro capítulo da Bible; "19.NN" = uma subseção do plano do `INDICE.md`.
> **Escopo / Scope:** este capítulo decide a **configuração remota e o live-ops** do Constela Quest — o namespace
> `quest.*` de **valores sintonizáveis** (mudança em produção **sem deploy**), as **feature flags/kill-switches**
> de produto, o **rollout gradual**, e o **calendário de temporadas/eventos** (com o **passe de temporada
> gratuito**). Ele **hospeda os valores** que as Seções [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md)/[09](09-social.md)/[10](10-professor-familia.md)/[12](12-seguranca-privacidade.md)/[13](13-acessibilidade.md)
> definem, **referenciando** a seção-dona de cada regra; usa o **mecanismo de entrega/cron** da Seção [14](14-infra-deploy-dr.md)
> e o **schema/ETag** da Seção [11](11-arquitetura.md); e **obedece** a P7/P8 (o live-ops **nunca** vira FOMO,
> moeda comprável ou paywall, e a config **nunca afrouxa** uma proteção). Ele **não** decide a **mecânica** (Seção
> 05), a **política** legal (Seção 12), a **norma** de bem-estar (Seção 13), o **mecanismo** de entrega/cron/schema
> (Seções 11/14), a **ética** do A/B (Seção 17) nem o **modelo de negócio** do passe (Seção 22).

---

## 🇧🇷 Live-ops & Configuração Remota

### 1. Objetivo
Ser a **referência definitiva de configuração remota e live-ops** do Constela Quest: fazer o jogo **ajustável em
produção sem redeploy** e **vivo ao longo do ano** (temporadas, eventos) — **sem jamais** trair a criança com
FOMO, moeda comprável ou paywall (P7/P8), e **sem jamais** afrouxar uma proteção por config. Decide os **valores**
`quest.*`, as **flags/kill-switches** de produto, o **rollout** e o **calendário**; **hospeda** os números que
outras seções definem (referenciando a seção-dona), **usa** o mecanismo da Seção [14](14-infra-deploy-dr.md)/[11](11-arquitetura.md),
e **não** decide a **mecânica** (Seção [05](05-sistemas-de-jogo.md)), a **política** (Seção [12](12-seguranca-privacidade.md)),
a **norma** (Seção [13](13-acessibilidade.md)) nem o **modelo de negócio do passe** (Seção [22](22-monetizacao.md)).

### 2. Contexto
No ecossistema **Hub → Edu → Quest**, um produto usado por **milhares de escolas** precisa ser **calibrado sem
parar o serviço** e **renovado** sem reescrever código. **Estado atual (Q0) — a caixa de config existe, o `quest.*`
e o live-ops não:**
- **Store de config existe (do Edu)** — a tabela `Configuracao` (`escola_id`/`namespace`/`chave`/`valor` JSON,
  UNIQUE) + `scoring.obter_config(...)` já implementam o padrão **padrão-no-código → override por escola** (1
  nível: escola). Hoje serve **só ao Edu** (namespaces `pesos.*`, `gamificacao.*`, `desempate.*`).
- **`quest.*` é aspiracional** — só citado num docstring (`catalogo.py`); **nenhuma** chave `quest.*` é lida ou gravada.
- **Valores de jogo hardcoded/inexistentes** — `QuestMissao.xp_base=40`/`moedas_base=10` (autorais, no catálogo);
  o **teto diário** (o **600** é da Seção [05](05-sistemas-de-jogo.md)), a **curva de XP** e o **α** da média móvel
  **não existem** no código do Quest; a **Chama** é estado sem motor. Os **rate-limits** são **constantes** (`8/5min`,
  `300/5min`) em `rate_limit.py`/`auth.py`.
- **Feature flags = só de infra** (Seção 14) — `DOCS_HABILITADOS`/`METRICS_ENABLED`; **nenhuma** flag/kill-switch
  de **produto** por escola/fase, nenhum rollout gradual. `social_ativo` (default **False**) é um toggle **por-perfil**.
- **Temporadas/eventos/passe/loja: não existem** — sem tabelas nem models (só o vestígio `QuestMissao.tipo` que
  admite o valor `evento` num enum — é um **tipo de missão**, não um evento de calendário). **Sem cron/scheduler**
  (a Seção [14](14-infra-deploy-dr.md) hoje só prevê o agendador de retenção — O16).

Este capítulo **especifica** o namespace `quest.*`, o live-ops e a governança — reusando a store existente e o
mecanismo das Seções [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md), **do zero** onde não há nada.

### 3. Filosofia da funcionalidade
**"Configuração sobre deploy — e live-ops que serve a criança."** Dois princípios organizam esta seção:
1. **Nenhum número mágico no código, mas nenhuma proteção afrouxável.** Toda regra numérica sintonizável vive em
   config, com **padrão-no-código seguro** — mas os valores que são **proteção** (teto, rate-limit, pausa,
   retenção) só se movem na **direção segura** (clamp — §9/C7); calibrar a economia **sem redeploy** e **sem
   risco**.
2. **Live-ops é presente, não armadilha.** Temporadas e eventos existem para **encantar e renovar**, **nunca**
   para prender: o **passe é gratuito** (P7), a escassez é **honesta** (§9/C11), e **zero dark patterns** (P8).

Conexão com os **Princípios Imutáveis** ([01](01-principios-imutaveis.md)): **P7** (passe gratuito, sem compra) e
**P8** (zero dark patterns) são o **limite moral** do live-ops; **P6** (teto = celebração) é uma proteção que a
config **nunca** afrouxa; **P15** isola cada override por `escola_id`; **P18** (sem tracking) **restringe** o A/B —
nenhum experimento pode virar rastreamento da criança (a ética é da Seção [17](17-telemetria-metricas.md), 17.28).

### 4. Experiência que o jogador deve sentir
**A criança sente um mundo que muda e a recebe bem** — um lobby que ganha o clima da Festa Junina, um evento com
uma missão nova, uma coleção da temporada — **sem** relógio de contagem que aperta o peito, **sem** "compre agora",
**sem** item que ela perdeu para sempre (ele **volta** — C11). A renovação é **convite**, não **cobrança**. **O
adulto** (escola) sente **controle e confiança**: pode **disponibilizar** ou ocultar o social, ajustar o ritmo, e
sabe que nada será usado para manipular nem para afrouxar uma proteção. **A equipe** ajusta a economia e libera
novidades **com segurança**, auditando cada mudança.

### 5. Fluxo completo
O **ciclo de vida de uma configuração/live-op**:

1. **Define** — um valor sintonizável (`quest.*`) tem **padrão-no-código** (o número canônico da seção-dona, ex.:
   teto = **600** da Seção [05](05-sistemas-de-jogo.md)) e um **esquema** (tipo, **faixa segura**, efeito — §9/C19).
2. **Sobrepõe** — um **override** curado (global → por escola → [por turma/aluno]) muda o valor **sem deploy**,
   pela store `Configuracao` (entrega = Seção [14](14-infra-deploy-dr.md)); precedência e **clamp de proteção** em §9.
3. **Valida** — valor ausente/inválido **cai no padrão seguro** (fail-safe); um valor de proteção fora da **faixa
   segura** é **clampado** (nunca afrouxa — C7); nenhuma mudança quebra o jogo.
4. **Propaga** — a entrega leva o novo valor aos clientes (entrega = Seção [14](14-infra-deploy-dr.md); cache
   **HTTP/ETag** = Seção [11](11-arquitetura.md)).
5. **Audita** — toda mudança de config é **registrada** (`logs_auditoria`) com autor e **rollback** disponível.
6. **Agenda (live-ops)** — temporadas e eventos entram por **calendário**; a **cadência** das regras de jogo (o
   **escudo semanal da Chama** — regra da Seção [05](05-sistemas-de-jogo.md) §8i; o **reset semanal do ranking de
   turma** — regra da Seção [09](09-social.md)) é da seção-dona; a 19 apenas **agenda** o job. O **agendador** de
   live-ops é **capacidade a prover pela Seção [14](14-infra-deploy-dr.md)** (hoje só há o de retenção — O16 — ⚠️ §15).
7. **Kill-switch (incidente)** — uma alavanca de emergência desliga uma feature (social, multiplayer, IA) — **mas
   nunca** uma proteção de bem-estar/segurança/moderação/privacidade, e **nunca** parcialmente (C7); runbook em §12.

### 6. Interface (quando existir)
A 19 **não desenha telas de criança** (N/A). Superfícies **operacionais** (adultos/equipe):
- **Painel de live-ops / control room** — onde a equipe (⚠️ quem opera — §15) edita config, flags, temporadas e
  aciona kill-switches; **reusa** o Edu ou é ferramenta nova (⚠️ 19.23).
- **Catálogo de chaves `quest.*`** (documentação viva — §9/C19) — tipo, default, **faixa segura**, efeito, seção-dona.
- **Superfície da criança** afetada (loja, lobby temático) — o **desenho** é da Seção [07](07-ux-fluxos-navegacao.md);
  a 19 só liga o **conteúdo/janela**.

### 7. UX
- **Para a criança** — a renovação chega como **surpresa boa** (Seção [13](13-acessibilidade.md) rege o tom); **nada**
  de FOMO, countdown ansioso ou paywall.
- **Para a equipe** — mudar um valor é **seguro** (fail-safe + clamp + auditoria + rollback) e **claro** (catálogo
  de chaves); o kill-switch é **óbvio** e **protegido**.
- **Para a escola** — a escola **disponibiliza ou oculta** o social (nunca o **ativa** por cima do opt-in da
  criança — C14), ajusta o ritmo dentro das **faixas seguras**, com transparência (regra da Seção [09](09-social.md)).

### 8. Game Design
**N/A como mecânica** — a 19 **não cria** regra de jogo; ela **sintoniza** e **agenda**. Nota de fronteira: os
**números** (teto, curva, α, preços da loja) pertencem às regras das Seções [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md);
a 19 **hospeda** o valor e o torna ajustável **dentro da faixa segura da dona** — e a **gratuidade** do passe é da
Seção [22](22-monetizacao.md) (P7).

### 9. Regras de negócio
As **normas de config/live-ops** (a fonte única do mecanismo de sintonia; a **mecânica** é da Seção [05](05-sistemas-de-jogo.md),
a **política** da Seção [12](12-seguranca-privacidade.md), a **entrega/schema** das Seções [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)):

| # | Norma | Regra | Fronteira |
|---|-------|-------|-----------|
| C1 | **Config sobre deploy** | toda **regra numérica sintonizável** vive em config `quest.*` — **nenhum número mágico** no código de mecânica | 19 |
| C2 | **Store (modelo lógico)** | **reusar** a tabela `Configuracao` (`namespace`/`chave`/`valor`), com uma **camada global** para `quest.*` (hoje só por-escola) | 19 (modelo lógico) ⚠️ (§15); **schema/físico** = [11](11-arquitetura.md); entrega = [14](14-infra-deploy-dr.md) |
| C3 | **Precedência** | **padrão-no-código → global → por escola → [por turma/aluno]** (o mais específico vence), **exceto** para proteções (só direção segura — C7) e o opt-out do aluno (piso — C14); isolamento por `escola_id` (P15) | 19 + [01](01-principios-imutaveis.md) |
| C4 | **Valor referencia o dono** | cada chave cita a **seção-dona** do número canônico (ex.: teto = **600** → Seção [05](05-sistemas-de-jogo.md); α = **0,3** → Seção [06](06-pedagogico-bncc.md)); a 19 **hospeda**, **não redecide** | 19 hospeda; regra = [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md) |
| C5 | **Defaults seguros** | valor **ausente/inválido** cai no **padrão-no-código** (fail-safe); nenhuma config quebra o jogo | 19 |
| C6 | **Feature flags de produto** | flags/kill-switches **de produto** (social, multiplayer, IA, eventos) — **distintas** das flags de **infra** (`DOCS_HABILITADOS`/`METRICS_ENABLED` = Seção [14](14-infra-deploy-dr.md)); **fail-safe = desligado** | 19 |
| C7 | **Proteções: nunca desligar nem afrouxar** | **nenhum** kill-switch/override **desliga nem afrouxa** uma proteção. Toda chave de proteção declara uma **faixa de direção segura**, com override **clampado**: teto nunca **acima** do saudável ([13](13-acessibilidade.md)/[05](05-sistemas-de-jogo.md)); rate-limit nunca **acima** do exigido pela política ([12](12-seguranca-privacidade.md)); pausa nunca **abaixo** da norma ([13](13-acessibilidade.md)); retenção nunca **além** do máximo legal ([12](12-seguranca-privacidade.md)). Conjunto protegido: **bem-estar** (teto/pausa — P6/[13](13-acessibilidade.md)), **segurança** (rate-limit/login — [12](12-seguranca-privacidade.md)), **moderação/denúncia/child-safety** ([10](10-professor-familia.md)) e **privacidade** ([12](12-seguranca-privacidade.md)). **Sem kill parcial:** superfície social/UGC ligada **não** pode ter a moderação desligada — desligar a moderação **obriga** a ocultar a superfície | 19 + [01](01-principios-imutaveis.md)/[10](10-professor-familia.md)/[12](12-seguranca-privacidade.md)/[13](13-acessibilidade.md) |
| C8 | **Rollout gradual** | liberar valor/flag por **subconjunto** (escola/turma/percentual) antes do geral | 19 ⚠️ (modelo — §15) |
| C9 | **Temporadas** | **temporada** = ciclo com troca de **tema do lobby** (proposta 6–8 semanas — ⚠️ §15; o comprimento do ciclo **coincide com a duração do passe** = Seção [22](22-monetizacao.md)/22.10); conteúdo sazonal = Seções [03](03-universo.md)/[04](04-personagens-avatar.md) | 19 (operação) ⚠️ (§15) |
| C10 | **Passe (operação)** | a **operação** do passe (calendário, curadoria da trilha, janelas); a **gratuidade** é **imutável** (P7 / Seção [22](22-monetizacao.md)) — **nunca** trilho pago; o **tipo** de recompensa (só cosméticos × vantagem) é **modelo** da Seção [22](22-monetizacao.md)/economia da [05](05-sistemas-de-jogo.md) | 19 (operação); modelo/recompensa = [22](22-monetizacao.md)/[05](05-sistemas-de-jogo.md) |
| C11 | **Eventos & escassez honesta** | **evento** = janela temática curta (pode ocorrer dentro de uma temporada); item "limitado" **retorna** em ≤ N temporadas (nunca exclusivo-permanente) e a criança vê "volta em breve" — a janela mostra **data** ("até domingo"), **nunca** cronômetro regressivo/urgência (P7/P8) | 19 (operação); economia = [05](05-sistemas-de-jogo.md) |
| C12 | **Loja rotativa** | rotação (proposta 4–6 itens + seção fixa — ⚠️ §15); **sem** moeda comprável, **sem** paywall (P7); preço em **moedas ganhas** (valor = Seção [05](05-sistemas-de-jogo.md)) | 19 (rotação) ⚠️ (§15); economia = [05](05-sistemas-de-jogo.md) |
| C13 | **Rate-limit (valores)** | os **valores** (8/5min, 300/5min, janelas) passam a config `quest.*`; a **política e a faixa segura** (piso mínimo de proteção) são da Seção [12](12-seguranca-privacidade.md) — override **nunca** afrouxa (C7); o **backing** distribuído é da Seção [14](14-infra-deploy-dr.md) | 19 (valor); política/faixa = [12](12-seguranca-privacidade.md) |
| C14 | **Config social (direção única)** | a config **`social_disponivel`** (global/escola) só **disponibiliza** o social; a **ativação** de cada criança é o campo **per-perfil** `social_ativo` (opt-in dela/responsável), e o **opt-out por-aluno é um piso** que camada de maior precedência **não** sobrepõe; tetos de anti-spam, reconexão gentil, SLA de moderação (valores) — a **regra** é das Seções [09](09-social.md)/[10](10-professor-familia.md) | 19 (valor); regra = [09](09-social.md)/[10](10-professor-familia.md) |
| C15 | **Toggles de A/B** | a 19 fornece os **toggles** de experimento que a Seção [17](17-telemetria-metricas.md) consome; a **permissão ética** do A/B com criança é decisão do dono (17.28) — o toggle fica **bloqueado** até ela | 19 (toggle); ética = [17](17-telemetria-metricas.md) |
| C16 | **Auditoria & rollback** | toda mudança de config em produção é **auditada** (`logs_auditoria`) com autor, e **reversível** | 19 reusa [12](12-seguranca-privacidade.md) |
| C17 | **Cron/entrega/schema ≠ 19** | o **cron** (temporada, escudo da Chama, reset de ranking), o **cache/ETag** e o **Redis** são **mecanismo das Seções [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)**; a **cadência** das regras é da dona ([05](05-sistemas-de-jogo.md)/[09](09-social.md)); a 19 define **quais** jobs/valores | 19 define; mecanismo = [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md) |
| C18 | **Zero dark patterns** | **nenhuma** superfície de live-ops (temporada/evento/loja) usa FOMO, escassez artificial ou pressão (P8) | 19 + [01](01-principios-imutaveis.md) |
| C19 | **Catálogo de chaves** | cada `quest.*` é registrada num catálogo vivo: **tipo, default (padrão-no-código), faixa segura, efeito, seção-dona**; o default é a fonte fail-safe (C5) | 19 |

### 10. Arquitetura técnica
Onde o live-ops **toca** o código (o **schema/ETag** é da Seção [11](11-arquitetura.md), a **entrega/cron** da
Seção [14](14-infra-deploy-dr.md); contratos → Apêndice B):
- **Store `quest.*`** — **reusa** `Configuracao` (`namespace`/`chave`/`valor` JSON) + `obter_config`, estendendo a
  resolução de **1 nível** (escola) para **global → escola → [turma/aluno]** (C3). Como representar o "global"
  numa tabela cujo UNIQUE inclui `escola_id` (ex.: `escola_id` NULL/sentinela e ajuste do UNIQUE) é **schema
  físico** da Seção [11](11-arquitetura.md) (⚠️ §15).
- **Catálogo de chaves** (C19) — registro (tipo, default, **faixa segura**, efeito, seção-dona); o **default-no-código**
  é a fonte fail-safe (C5) e o **clamp** (C7) usa a faixa segura da dona.
- **Flags de produto** — categoria própria (C6), distinta das flags de infra (`config.py`); fail-safe desligado.
- **Live-ops** — tabelas de **temporada/evento/passe** (a criar; a 19 define o **conteúdo/janela**, o **schema
  físico** é da Seção [11](11-arquitetura.md) e o **cron** da Seção [14](14-infra-deploy-dr.md)); o vestígio
  `QuestMissao.tipo='evento'` é **tipo de missão**, não o sistema de eventos.
- **Auditoria** — reusa `logs_auditoria` (C16), sem duplicar a trilha.

### 11. Dependências com outros módulos
**Consome / referencia:**
- **Seção [14](14-infra-deploy-dr.md)** — o **mecanismo** de entrega de config/flags, o **cron** (incl. a
  capacidade nova de agendar live-ops — ⚠️ §15) e o Redis.
- **Seção [11](11-arquitetura.md)** — o **schema físico** da store/tabelas e o **cache HTTP/ETag**.
- **Seção [05](05-sistemas-de-jogo.md)** — as **mecânicas**, os **números-padrão canônicos** (teto 600, curva,
  economia) e a **regra do escudo semanal** da Chama.
- **Seção [06](06-pedagogico-bncc.md)** — a **fórmula** do domínio (α=0,3).
- **Seção [12](12-seguranca-privacidade.md)** — a **política e a faixa segura** do rate-limit; o **prazo legal** de retenção.
- **Seção [13](13-acessibilidade.md)** — a **norma** de bem-estar (a 19 fixa o número **dentro** da norma).
- **Seção [17](17-telemetria-metricas.md)** — a **ética** do A/B (a 19 dá o toggle).
- **Seções [09](09-social.md)/[10](10-professor-familia.md)** — a **regra** social/reset de ranking e o SLA/push.
- **Seção [22](22-monetizacao.md)** — o **modelo** do passe (gratuidade — P7 / ADR candidato C.20).

**Alimenta:**
- **Todas as seções com número sintonizável** — o **namespace `quest.*`** e o catálogo de chaves.
- **Seções [03](03-universo.md)/[04](04-personagens-avatar.md)/[07](07-ux-fluxos-navegacao.md)** — o **calendário**
  de temporadas/eventos/loja que dá vida ao conteúdo sazonal.

**O que quebra se mudar:** se a Seção [05](05-sistemas-de-jogo.md) mudar um **número-padrão** (ex.: teto), a 19
**atualiza a chave** (o default segue a dona); se as Seções [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)
mudarem o **schema/cron**, a 19 **reaponta**; se a Seção [22](22-monetizacao.md) fixar o **formato** do passe, a 19 **opera-o**.

### 12. Casos extremos (Edge Cases)
- **Valor de config ausente/inválido** → **padrão-no-código** (fail-safe C5); log de aviso.
- **Override tenta afrouxar uma proteção** (subir teto/rate-limit, encurtar pausa, estender retenção) → **clampado**
  à faixa segura da dona (C7); **bloqueado** se tentar desligar; proteções são inegociáveis.
- **Escola grava `social_disponivel=true`** → só **disponibiliza** o social; a **ativação** continua sendo o
  `social_ativo` **per-perfil** da criança (opt-in), cujo opt-out é piso (C14) — nunca "social forçado".
- **Kill parcial** (social ligado + moderação desligada) → **proibido** (C7): desligar a moderação oculta a superfície.
- **Rollback de config** → volta ao valor anterior auditado (C16); se a chave afeta estado do aluno, o recomputo é
  a partir de `quest_tentativas` (o registro imutável — Seção [17](17-telemetria-metricas.md)); **quais** chaves
  são *forward-only* × recomputo retroativo é ⚠️ (§15).
- **Item "limitado" de evento** → **retorna** em temporada futura (C11); **nunca** exclusivo-permanente.
- **Temporada expira** → o lobby volta ao tema base; nada é "perdido" de forma punitiva (P6/P8).
- **Config divergente entre escolas** → isolada por `escola_id` (P15); nenhuma escola vê a config de outra.
- **A/B com criança sem autorização** → **não roda** enquanto a decisão ética (17.28) estiver aberta (toggle bloqueado — C15).
- **Mudança em produção durante o pico** → propagação por cache/ETag (Seção [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)); mudança destrutiva em janela segura.

### 13. Escalabilidade futura
- **Config por turma/aluno** — estender a precedência (C3) além de escola quando houver demanda.
- **Rollout percentual/segmentado** — além de lista de escolas (⚠️ 19.22).
- **Calendário anual** — temporadas (ciclos com tema) e eventos temáticos (janelas curtas: Festa Junina, Dia das
  Crianças, Férias) — curadoria, sem FOMO.
- **Editor de catálogo pedagógico** ao vivo (19.15) — ligado ao software futuro de matérias+questões.
- **Escala do live-ops** — gatilhos para Redis (salas/presença/cache) = **mecanismo da Seção [14](14-infra-deploy-dr.md)**.

### 14. Checklist de implementação
**"Pronto quando" (liga ao Apêndice F):**
- [ ] **Namespace `quest.*`** com **catálogo de chaves** (tipo/default/**faixa segura**/efeito/seção-dona) documentado (C1/C4/C19).
- [ ] **Store** reusando `Configuracao` com **camada global → escola** (C2/C3); schema = Seção [11](11-arquitetura.md); entrega = Seção [14](14-infra-deploy-dr.md).
- [ ] **Defaults seguros** — valor ausente/inválido cai no padrão-no-código (C5).
- [ ] **Números-padrão** (teto 600, α 0,3, rate-limit 8/5min) **hospedados** citando a seção-dona (C4/C13); nada mágico no código.
- [ ] **Proteções clampadas** — override **nunca** afrouxa teto/rate-limit/pausa/retenção; conjunto protegido inclui moderação/child-safety (C7); **sem kill parcial**.
- [ ] **`social_ativo` de direção única** — config só disponibiliza; ativação = opt-in da criança; opt-out = piso (C14).
- [ ] **Feature flags de produto** distintas das de infra; **fail-safe desligado** (C6).
- [ ] **Rollout gradual** por subconjunto antes do geral (C8); **toggles de A/B** fornecidos mas bloqueados até 17.28 (C15).
- [ ] **Auditoria + rollback** de toda mudança de config (`logs_auditoria`) (C16).
- [ ] **Live-ops sem dark patterns** — passe **gratuito**, escassez **honesta** (retorno previsível, sem countdown ansioso), **zero FOMO/paywall** (C10/C11/C12/C18).
- [ ] **Cron/cache/ETag/Redis** operando pelas Seções [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md) (C17), não reimplementados aqui.
- [ ] **Isolamento por `escola_id`** em todo override (P15 — C3).

### 15. Questões em aberto
Cada item é **decisão do dono** (⚠️); os defaults são **propostas** da 19, não decisões autônomas:

- ⚠️ **19.2 / C2 — Modelo da store `quest.*`.** Proposta: **reusar** `Configuracao` com uma **camada global**
  (default global → override por escola). Confirmar o **escopo** (global × por-escola × por-turma) e a
  **representação** do "global" (ex.: `escola_id` NULL/sentinela; impacto no UNIQUE e em `obter_config` — **schema
  físico** = Seção [11](11-arquitetura.md)).
- ⚠️ **Agendador de live-ops (14).** O cron de temporada/Chama/ranking é uma **capacidade nova** a prover pela Seção
  [14](14-infra-deploy-dr.md) (hoje só há o agendador de retenção — O16). *(O escudo da Chama pode ser lazy/on-access
  em vez de cron — confirmar com Seções [05](05-sistemas-de-jogo.md)/[11](11-arquitetura.md).)*
- ⚠️ **19.9 / C10 — Formato do passe (gratuito).** P7 crava o passe **gratuito** ("formato exato a confirmar" — ADR
  **candidato** C.20). A **operação** (calendário/trilha/janelas) é da 19; o **tipo de recompensa** ("só cosméticos"),
  o **nº de trilhos** e **linear × por níveis** são **modelo da Seção [22](22-monetizacao.md)/economia da [05](05-sistemas-de-jogo.md)** — **sem** trilho pago.
- ⚠️ **Temporadas/eventos/loja na Q0.** Entram no lançamento (com calendário) ou em fase posterior? **Duração** da
  temporada (proposta 6–8 semanas — o comprimento do ciclo **sincroniza com a duração do passe**, decidido uma vez
  na Seção [22](22-monetizacao.md)/22.10), **cadência** dos eventos, e o **modelo da loja** (armazenamento, "seção
  fixa", 4–6 itens, curadoria da rotação).
- ⚠️ **19.22 / C8 — Rollout gradual.** Por **lista** de escolas × **percentual/segmento**; quem aprova a abertura geral.
- ⚠️ **19.23 — Painel operacional / control room.** Quem opera o live-ops (admin global × escola) e por qual painel
  (reusa o Edu × ferramenta nova); rigor de auditoria/rollback.
- ⚠️ **19.7 / C14 — Controles sociais.** Escopo (escola/turma/aluno) e default de **`social_disponivel`** (proposta:
  **desligado**; o `social_ativo` per-perfil é o opt-in da criança, default `False`); alcance no lançamento (turma ×
  escola) — a **regra** é da Seção [09](09-social.md).
- ⚠️ **19.15 — Interface de autoria/publicação do catálogo pedagógico** e a conexão com o software futuro de matérias+questões.
- ⚠️ **C15 — A/B com criança.** É permitido (17.28)? Sob quais limites éticos/consentimento — a 19 só fornece o toggle (bloqueado até então).
- ⚠️ **Propagação de rollback.** Quais chaves `quest.*` são *forward-only* e quais disparam **recomputo** do estado
  do aluno (a partir de `quest_tentativas`) — por classe de chave (referência à dona [05](05-sistemas-de-jogo.md)/[17](17-telemetria-metricas.md)).
- ⚠️ **Valores a confirmar.** Janela de pausa (proposta 40 min — Seção [13](13-acessibilidade.md)), frequência do
  push da família e SLA de moderação (Seção [10](10-professor-familia.md)), tetos de anti-spam social (Seção [09](09-social.md)).
  O **prazo de retenção** (24 meses) é **número legal de posse da Seção [12](12-seguranca-privacidade.md)** (executado
  por 14/17); se exposto em config, é **GLOBAL-only** (sem override por escola).

### 16. ADR (Architecture Decision Record)
- **ADR-19-A — Configuração sobre deploy; `quest.*` reusa a store existente.** Nenhum número mágico no código de
  mecânica; os valores sintonizáveis vivem em `quest.*` sobre a tabela `Configuracao` (com camada global), com
  **padrão-no-código seguro** (fail-safe) e catálogo de chaves (C19); **schema** = Seção [11](11-arquitetura.md),
  entrega = Seção [14](14-infra-deploy-dr.md). *Escopo/representação do global pendentes (§15).*
- **ADR-19-B — O valor referencia o dono.** Cada chave `quest.*` cita a **seção-dona** do número canônico (teto =
  Seção [05](05-sistemas-de-jogo.md); α = Seção [06](06-pedagogico-bncc.md); rate-limit = política da Seção [12](12-seguranca-privacidade.md);
  teto/pausa = norma da Seção [13](13-acessibilidade.md) com o **valor** em 05/19); a 19 **hospeda e sintoniza**,
  nunca redecide a regra.
- **ADR-19-C — Live-ops sem dark patterns; proteções inegociáveis.** Temporadas/eventos/loja obedecem a **P7/P8**:
  passe **gratuito** (modelo = Seção [22](22-monetizacao.md); imutabilidade ancorada em **P7** — ADR candidato
  C.20), escassez **honesta** (retorno previsível, sem countdown ansioso), **zero FOMO/paywall**; e **nenhum**
  kill-switch/override **desliga nem afrouxa** uma proteção de **bem-estar** (teto/pausa — P6), **segurança**
  (rate-limit/login), **moderação/child-safety** (Seção [10](10-professor-familia.md)) ou **privacidade** (Seção
  [12](12-seguranca-privacidade.md)) — clamp por faixa segura, sem kill parcial, e `social_ativo` de direção única.
- **ADR-19-D — Cron/entrega/schema são das Seções 11/14.** O **cron** (temporada, escudo da Chama, reset de
  ranking — a **cadência** é regra de [05](05-sistemas-de-jogo.md)/[09](09-social.md)), o **cache/ETag** (desenho da
  Seção [11](11-arquitetura.md)) e o **Redis** (Seção [14](14-infra-deploy-dr.md)) são **mecanismo**; a 19 define
  **quais** jobs e **quais** valores, sem reimplementar o mecanismo. *O agendador de live-ops é capacidade nova da 14 (§15).*

*Decisões cross-módulo não são improvisadas aqui: as pendências acima viram ADR ou item de §15.*

---

## 🇬🇧 Live-ops & Remote Configuration

### 1. Objective
To be the **definitive remote-configuration and live-ops reference** for Constela Quest: making the game
**tunable in production without a redeploy** and **alive throughout the year** (seasons, events) — **without ever**
betraying the child with FOMO, purchasable currency or a paywall (P7/P8), and **without ever** loosening a
protection via config. It decides the `quest.*` **values**, the product **flags/kill-switches**, the **rollout**
and the **calendar**; it **hosts** the numbers other sections define (referencing the owner section), **uses**
Section [14](14-infra-deploy-dr.md)/[11](11-arquitetura.md)'s mechanism, and does **not** decide the **mechanics**
(Section [05](05-sistemas-de-jogo.md)), the **policy** (Section [12](12-seguranca-privacidade.md)), the **norm**
(Section [13](13-acessibilidade.md)), nor the **pass business model** (Section [22](22-monetizacao.md)).

### 2. Context
In the **Hub → Edu → Quest** ecosystem, a product used by **thousands of schools** must be **calibrated without
stopping the service** and **refreshed** without rewriting code. **Current state (Q0) — the config box exists,
`quest.*` and live-ops do not:**
- **A config store exists (Edu's)** — the `Configuracao` table (`escola_id`/`namespace`/`chave`/`valor` JSON,
  UNIQUE) + `scoring.obter_config(...)` already implement **code-default → per-school override** (1 level: school).
  Today it serves **only Edu** (namespaces `pesos.*`, `gamificacao.*`, `desempate.*`).
- **`quest.*` is aspirational** — mentioned only in a docstring (`catalogo.py`); **no** `quest.*` key is read or written.
- **Hardcoded/nonexistent game values** — `QuestMissao.xp_base=40`/`moedas_base=10` (authorial, in the catalog);
  the **daily cap** (the **600** is Section [05](05-sistemas-de-jogo.md)'s), the **XP curve** and the moving-average
  **α** **do not exist** in Quest's code; the **Flame** is state without an engine. The **rate-limits** are
  **constants** (`8/5min`, `300/5min`) in `rate_limit.py`/`auth.py`.
- **Feature flags = infra only** (Section 14) — `DOCS_HABILITADOS`/`METRICS_ENABLED`; **no** product flag/kill-switch
  per school/phase, no gradual rollout. `social_ativo` (default **False**) is a **per-profile** toggle.
- **Seasons/events/pass/store: do not exist** — no tables nor models (only the trace that `QuestMissao.tipo` admits
  the value `evento` in an enum — a **mission type**, not a calendar event). **No cron/scheduler** (Section
  [14](14-infra-deploy-dr.md) today only foresees the retention scheduler — O16).

This chapter **specifies** the `quest.*` namespace, live-ops and governance — reusing the existing store and
Sections [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)'s mechanism, **from scratch** where there is nothing.

### 3. Feature philosophy
**"Configuration over deploy — and live-ops that serves the child."** Two principles organize this section:
1. **No magic number in code, but no loosenable protection.** Every tunable numeric rule lives in config, with a
   **safe code-default** — but values that are a **protection** (cap, rate-limit, pause, retention) only move in the
   **safe direction** (clamp — §9/C7); calibrate the economy **without a redeploy** and **without risk**.
2. **Live-ops is a gift, not a trap.** Seasons and events exist to **delight and refresh**, **never** to trap: the
   **pass is free** (P7), scarcity is **honest** (§9/C11), and **zero dark patterns** (P8).

Link to the **Immutable Principles** ([01](01-principios-imutaveis.md)): **P7** (free pass, no purchase) and **P8**
(zero dark patterns) are the **moral boundary** of live-ops; **P6** (cap = celebration) is a protection config
**never** loosens; **P15** isolates each override by `escola_id`; **P18** (no tracking) **restricts** A/B — no
experiment may become tracking of the child (the ethics are Section [17](17-telemetria-metricas.md)'s, 17.28).

### 4. The experience the player should feel
**The child feels a world that changes and welcomes them** — a lobby that takes on the Festa Junina mood, an event
with a new mission, a season collection — **without** a countdown clock that tightens the chest, **without** "buy
now", **without** an item lost forever (it **returns** — C11). Renewal is an **invitation**, not a **demand**. **The
adult** (school) feels **control and confidence**: they can **make available** or hide social, adjust the pace, and
know nothing will be used to manipulate nor to loosen a protection. **The team** tunes the economy and ships novelty
**safely**, auditing every change.

### 5. Complete flow
The **lifecycle of a config/live-op**:

1. **Defines** — a tunable value (`quest.*`) has a **code-default** (the owner section's canonical number, e.g. cap
   = **600** from Section [05](05-sistemas-de-jogo.md)) and a **schema** (type, **safe range**, effect — §9/C19).
2. **Overrides** — a curated **override** (global → per-school → [per-class/student]) changes the value **without a
   deploy**, via the `Configuracao` store (delivery = Section [14](14-infra-deploy-dr.md)); precedence and the
   **protection clamp** in §9.
3. **Validates** — a missing/invalid value **falls back to the safe default** (fail-safe); a protection value outside
   the **safe range** is **clamped** (never loosens — C7); no change breaks the game.
4. **Propagates** — delivery carries the new value to the clients (delivery = Section [14](14-infra-deploy-dr.md);
   **HTTP/ETag** cache = Section [11](11-arquitetura.md)).
5. **Audits** — every config change is **logged** (`logs_auditoria`) with author and an available **rollback**.
6. **Schedules (live-ops)** — seasons and events enter by **calendar**; the **cadence** of game rules (the **weekly
   Flame shield** — Section [05](05-sistemas-de-jogo.md) §8i's rule; the **weekly class-ranking reset** — Section
   [09](09-social.md)'s rule) belongs to the owner section; 19 only **schedules** the job. The live-ops **scheduler**
   is a **capability to be provided by Section [14](14-infra-deploy-dr.md)** (today there is only the retention one —
   O16 — ⚠️ §15).
7. **Kill-switch (incident)** — an emergency lever turns off a feature (social, multiplayer, AI) — **but never** a
   well-being/security/moderation/privacy protection, and **never** partially (C7); runbook in §12.

### 6. Interface (when it exists)
Section 19 **draws no child screens** (N/A). **Operational** surfaces (adults/team):
- **Live-ops panel / control room** — where the team (⚠️ who operates — §15) edits config, flags, seasons and
  triggers kill-switches; **reuses** Edu or is a new tool (⚠️ 19.23).
- **`quest.*` key catalog** (living documentation — §9/C19) — type, default, **safe range**, effect, owner section.
- **Affected child surface** (store, themed lobby) — the **design** is Section [07](07-ux-fluxos-navegacao.md)'s;
  19 only wires the **content/window**.

### 7. UX
- **For the child** — renewal arrives as a **good surprise** (Section [13](13-acessibilidade.md) governs the tone);
  **no** FOMO, anxious countdown or paywall.
- **For the team** — changing a value is **safe** (fail-safe + clamp + audit + rollback) and **clear** (key catalog);
  the kill-switch is **obvious** and **protected**.
- **For the school** — the school **makes available or hides** social (never **activates** it over the child's
  opt-in — C14), adjusts the pace within the **safe ranges**, transparently (Section [09](09-social.md)'s rule).

### 8. Game Design
**N/A as a mechanic** — 19 **does not create** a game rule; it **tunes** and **schedules**. Boundary note: the
**numbers** (cap, curve, α, store prices) belong to the rules of Sections [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md);
19 **hosts** the value and makes it adjustable **within the owner's safe range** — and the pass's **free** nature is
Section [22](22-monetizacao.md)'s (P7).

### 9. Business rules
The **config/live-ops norms** (the single source of the tuning mechanism; the **mechanics** are Section [05](05-sistemas-de-jogo.md)'s,
the **policy** Section [12](12-seguranca-privacidade.md)'s, the **delivery/schema** Sections [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)'s):

| # | Norm | Rule | Boundary |
|---|------|------|----------|
| C1 | **Config over deploy** | every **tunable numeric rule** lives in `quest.*` config — **no magic number** in mechanic code | 19 |
| C2 | **Store (logical model)** | **reuse** the `Configuracao` table (`namespace`/`chave`/`valor`), with a **global layer** for `quest.*` (today per-school only) | 19 (logical model) ⚠️ (§15); **physical schema** = [11](11-arquitetura.md); delivery = [14](14-infra-deploy-dr.md) |
| C3 | **Precedence** | **code-default → global → per-school → [per-class/student]** (most specific wins), **except** for protections (safe direction only — C7) and the student's opt-out (a floor — C14); isolation by `escola_id` (P15) | 19 + [01](01-principios-imutaveis.md) |
| C4 | **Value references the owner** | each key cites the **owner section** of the canonical number (e.g. cap = **600** → Section [05](05-sistemas-de-jogo.md); α = **0.3** → Section [06](06-pedagogico-bncc.md)); 19 **hosts**, does **not** re-decide | 19 hosts; rule = [05](05-sistemas-de-jogo.md)/[06](06-pedagogico-bncc.md) |
| C5 | **Safe defaults** | a **missing/invalid** value falls back to the **code-default** (fail-safe); no config breaks the game | 19 |
| C6 | **Product feature flags** | product flags/kill-switches (social, multiplayer, AI, events) — **distinct** from **infra** flags (`DOCS_HABILITADOS`/`METRICS_ENABLED` = Section [14](14-infra-deploy-dr.md)); **fail-safe = off** | 19 |
| C7 | **Protections: never off, never loosened** | **no** kill-switch/override **turns off or loosens** a protection. Every protection key declares a **safe-direction range**, with the override **clamped**: cap never **above** the healthy one ([13](13-acessibilidade.md)/[05](05-sistemas-de-jogo.md)); rate-limit never **above** the policy's ([12](12-seguranca-privacidade.md)); pause never **below** the norm ([13](13-acessibilidade.md)); retention never **beyond** the legal maximum ([12](12-seguranca-privacidade.md)). Protected set: **well-being** (cap/pause — P6/[13](13-acessibilidade.md)), **security** (rate-limit/login — [12](12-seguranca-privacidade.md)), **moderation/report/child-safety** ([10](10-professor-familia.md)) and **privacy** ([12](12-seguranca-privacidade.md)). **No partial kill:** a social/UGC surface left on **cannot** have moderation off — turning off moderation **forces** hiding the surface | 19 + [01](01-principios-imutaveis.md)/[10](10-professor-familia.md)/[12](12-seguranca-privacidade.md)/[13](13-acessibilidade.md) |
| C8 | **Gradual rollout** | release a value/flag to a **subset** (school/class/percentage) before general | 19 ⚠️ (model — §15) |
| C9 | **Seasons** | a **season** = a cycle with a **lobby theme** swap (proposal 6–8 weeks — ⚠️ §15; the cycle length **coincides with the pass duration** = Section [22](22-monetizacao.md)/22.10); seasonal content = Sections [03](03-universo.md)/[04](04-personagens-avatar.md) | 19 (operation) ⚠️ (§15) |
| C10 | **Pass (operation)** | the pass **operation** (calendar, track curation, windows); the **free** nature is **immutable** (P7 / Section [22](22-monetizacao.md)) — **never** a paid track; the reward **type** (cosmetics only × advantage) is Section [22](22-monetizacao.md)'s **model** / [05](05-sistemas-de-jogo.md)'s economy | 19 (operation); model/reward = [22](22-monetizacao.md)/[05](05-sistemas-de-jogo.md) |
| C11 | **Events & honest scarcity** | an **event** = a short themed window (may occur within a season); a "limited" item **returns** within ≤ N seasons (never permanent-exclusive) and the child sees "back soon" — the window shows a **date** ("until Sunday"), **never** a regressive timer/urgency (P7/P8) | 19 (operation); economy = [05](05-sistemas-de-jogo.md) |
| C12 | **Rotating store** | rotation (proposal 4–6 items + a fixed section — ⚠️ §15); **no** purchasable currency, **no** paywall (P7); price in **earned coins** (value = Section [05](05-sistemas-de-jogo.md)) | 19 (rotation) ⚠️ (§15); economy = [05](05-sistemas-de-jogo.md) |
| C13 | **Rate-limit (values)** | the **values** (8/5min, 300/5min, windows) move to `quest.*` config; the **policy and safe range** (minimum protection floor) are Section [12](12-seguranca-privacidade.md)'s — an override **never** loosens (C7); the distributed **backing** is Section [14](14-infra-deploy-dr.md)'s | 19 (value); policy/range = [12](12-seguranca-privacidade.md) |
| C14 | **Social config (one-directional)** | the **`social_disponivel`** config (global/school) only **makes social available**; each child's **activation** is the **per-profile** `social_ativo` field (their/guardian opt-in), and the **per-student opt-out is a floor** no higher-precedence layer overrides; anti-spam caps, gentle reconnect, moderation SLA (values) — the **rule** is Sections [09](09-social.md)/[10](10-professor-familia.md)'s | 19 (value); rule = [09](09-social.md)/[10](10-professor-familia.md) |
| C15 | **A/B toggles** | 19 provides the experiment **toggles** Section [17](17-telemetria-metricas.md) consumes; the **ethical permission** for A/B with a child is the owner's decision (17.28) — the toggle stays **blocked** until then | 19 (toggle); ethics = [17](17-telemetria-metricas.md) |
| C16 | **Audit & rollback** | every production config change is **audited** (`logs_auditoria`) with author, and **reversible** | 19 reuses [12](12-seguranca-privacidade.md) |
| C17 | **Cron/delivery/schema ≠ 19** | the **cron** (season, Flame shield, ranking reset), the **cache/ETag** and **Redis** are **Sections [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)'s mechanism**; the **cadence** of the rules is the owner's ([05](05-sistemas-de-jogo.md)/[09](09-social.md)); 19 defines **which** jobs/values | 19 defines; mechanism = [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md) |
| C18 | **Zero dark patterns** | **no** live-ops surface (season/event/store) uses FOMO, artificial scarcity or pressure (P8) | 19 + [01](01-principios-imutaveis.md) |
| C19 | **Key catalog** | each `quest.*` is registered in a living catalog: **type, default (code-default), safe range, effect, owner section**; the default is the fail-safe source (C5) | 19 |

### 10. Technical architecture
Where live-ops **touches** code (the **schema/ETag** is Section [11](11-arquitetura.md)'s, the **delivery/cron**
Section [14](14-infra-deploy-dr.md)'s; contracts → Appendix B):
- **`quest.*` store** — **reuses** `Configuracao` (`namespace`/`chave`/`valor` JSON) + `obter_config`, extending the
  **1-level** (school) resolution to **global → school → [class/student]** (C3). How the "global" is represented in a
  table whose UNIQUE includes `escola_id` (e.g. `escola_id` NULL/sentinel and a UNIQUE adjustment) is Section
  [11](11-arquitetura.md)'s **physical schema** (⚠️ §15).
- **Key catalog** (C19) — a registry (type, default, **safe range**, effect, owner section); the **code-default** is
  the fail-safe source (C5) and the **clamp** (C7) uses the owner's safe range.
- **Product flags** — its own category (C6), distinct from infra flags (`config.py`); fail-safe off.
- **Live-ops** — season/event/pass tables (to create; 19 defines the **content/window**, the **physical schema** is
  Section [11](11-arquitetura.md)'s and the **cron** Section [14](14-infra-deploy-dr.md)'s); the `QuestMissao.tipo='evento'`
  trace is a **mission type**, not the event system.
- **Audit** — reuses `logs_auditoria` (C16), without duplicating the trail.

### 11. Dependencies on other modules
**Consumes / references:**
- **Section [14](14-infra-deploy-dr.md)** — the config/flag **delivery mechanism**, the **cron** (incl. the new
  capability to schedule live-ops — ⚠️ §15) and Redis.
- **Section [11](11-arquitetura.md)** — the store/tables **physical schema** and the **HTTP/ETag cache**.
- **Section [05](05-sistemas-de-jogo.md)** — the **mechanics**, the **canonical default numbers** (cap 600, curve,
  economy) and the **weekly Flame-shield** rule.
- **Section [06](06-pedagogico-bncc.md)** — the domain **formula** (α=0.3).
- **Section [12](12-seguranca-privacidade.md)** — the rate-limit **policy and safe range**; the retention **legal deadline**.
- **Section [13](13-acessibilidade.md)** — the well-being **norm** (19 sets the number **within** the norm).
- **Section [17](17-telemetria-metricas.md)** — the A/B **ethics** (19 gives the toggle).
- **Sections [09](09-social.md)/[10](10-professor-familia.md)** — the social **rule**/ranking reset and the SLA/push.
- **Section [22](22-monetizacao.md)** — the pass **model** (free — P7 / candidate ADR C.20).

**Feeds:**
- **Every section with a tunable number** — the **`quest.*` namespace** and the key catalog.
- **Sections [03](03-universo.md)/[04](04-personagens-avatar.md)/[07](07-ux-fluxos-navegacao.md)** — the
  season/event/store **calendar** that brings seasonal content to life.

**What breaks if it changes:** if Section [05](05-sistemas-de-jogo.md) changes a **default number** (e.g. cap), 19
**updates the key** (the default follows the owner); if Sections [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)
change the **schema/cron**, 19 **re-points**; if Section [22](22-monetizacao.md) fixes the pass **format**, 19 **operates it**.

### 12. Edge cases
- **Missing/invalid config value** → the **code-default** (fail-safe C5); a warning log.
- **An override tries to loosen a protection** (raise cap/rate-limit, shorten pause, extend retention) → **clamped**
  to the owner's safe range (C7); **blocked** if it tries to turn it off; protections are non-negotiable.
- **A school sets `social_disponivel=true`** → it only **makes social available**; the **activation** remains the
  child's **per-profile** `social_ativo` (opt-in), whose opt-out is a floor (C14) — never "forced social".
- **Partial kill** (social on + moderation off) → **forbidden** (C7): turning off moderation hides the surface.
- **Config rollback** → back to the previous audited value (C16); if the key affects student state, the recompute is
  from `quest_tentativas` (the immutable record — Section [17](17-telemetria-metricas.md)); **which** keys are
  *forward-only* × retroactive recompute is ⚠️ (§15).
- **Event "limited" item** → it **returns** in a future season (C11); **never** permanent-exclusive.
- **A season expires** → the lobby returns to the base theme; nothing is punitively "lost" (P6/P8).
- **Config diverging between schools** → isolated by `escola_id` (P15); no school sees another's config.
- **A/B with a child without authorization** → **does not run** while the ethical decision (17.28) is open (toggle blocked — C15).
- **A change in production during the peak** → propagation by cache/ETag (Section [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md)); a destructive change in a safe window.

### 13. Future scalability
- **Per-class/student config** — extend the precedence (C3) beyond school when there is demand.
- **Percentage/segment rollout** — beyond a school list (⚠️ 19.22).
- **Annual calendar** — seasons (themed cycles) and themed events (short windows: Festa Junina, Children's Day,
  holidays) — curation, no FOMO.
- **Live pedagogical-catalog editor** (19.15) — tied to the future subjects+questions software.
- **Live-ops scaling** — triggers for Redis (rooms/presence/cache) = **Section [14](14-infra-deploy-dr.md)'s mechanism**.

### 14. Implementation checklist
**"Done when" (links to Appendix F):**
- [ ] **`quest.*` namespace** with a documented **key catalog** (type/default/**safe range**/effect/owner section) (C1/C4/C19).
- [ ] **Store** reusing `Configuracao` with a **global → school layer** (C2/C3); schema = Section [11](11-arquitetura.md); delivery = Section [14](14-infra-deploy-dr.md).
- [ ] **Safe defaults** — a missing/invalid value falls back to the code-default (C5).
- [ ] **Default numbers** (cap 600, α 0.3, rate-limit 8/5min) **hosted** citing the owner section (C4/C13); nothing magic in code.
- [ ] **Clamped protections** — an override **never** loosens cap/rate-limit/pause/retention; the protected set includes moderation/child-safety (C7); **no partial kill**.
- [ ] **One-directional `social_ativo`** — config only makes available; activation = child's opt-in; opt-out = floor (C14).
- [ ] **Product feature flags** distinct from infra ones; **fail-safe off** (C6).
- [ ] **Gradual rollout** to a subset before general (C8); **A/B toggles** provided but blocked until 17.28 (C15).
- [ ] **Audit + rollback** of every config change (`logs_auditoria`) (C16).
- [ ] **Live-ops without dark patterns** — **free** pass, **honest** scarcity (predictable return, no anxious countdown), **zero FOMO/paywall** (C10/C11/C12/C18).
- [ ] **Cron/cache/ETag/Redis** operating via Sections [11](11-arquitetura.md)/[14](14-infra-deploy-dr.md) (C17), not reimplemented here.
- [ ] **Isolation by `escola_id`** on every override (P15 — C3).

### 15. Open questions
Each item is a **owner decision** (⚠️); the defaults are 19's **proposals**, not autonomous decisions:

- ⚠️ **19.2 / C2 — `quest.*` store model.** Proposal: **reuse** `Configuracao` with a **global layer** (global
  default → per-school override). Confirm the **scope** (global × per-school × per-class) and the **representation**
  of "global" (e.g. `escola_id` NULL/sentinel; impact on UNIQUE and `obter_config` — **physical schema** = Section [11](11-arquitetura.md)).
- ⚠️ **Live-ops scheduler (14).** The season/Flame/ranking cron is a **new capability** to be provided by Section
  [14](14-infra-deploy-dr.md) (today there is only the retention scheduler — O16). *(The Flame shield could be
  lazy/on-access instead of a cron — confirm with Sections [05](05-sistemas-de-jogo.md)/[11](11-arquitetura.md).)*
- ⚠️ **19.9 / C10 — Pass format (free).** P7 fixes the pass as **free** ("exact format TBC" — **candidate** ADR
  C.20). The **operation** (calendar/track/windows) is 19's; the **reward type** ("cosmetics only"), the **number of
  tracks** and **linear × leveled** are Section [22](22-monetizacao.md)'s **model** / [05](05-sistemas-de-jogo.md)'s economy — **no** paid track.
- ⚠️ **Seasons/events/store in Q0.** Do they enter at launch (with a calendar) or a later phase? Season **duration**
  (proposal 6–8 weeks — the cycle length **syncs with the pass duration**, decided once in Section [22](22-monetizacao.md)/22.10),
  event **cadence**, and the **store model** (storage, "fixed section", 4–6 items, rotation curation).
- ⚠️ **19.22 / C8 — Gradual rollout.** By a school **list** × **percentage/segment**; who approves the general opening.
- ⚠️ **19.23 — Operational panel / control room.** Who operates live-ops (global admin × school) and via which panel
  (reuse Edu × new tool); audit/rollback rigor.
- ⚠️ **19.7 / C14 — Social controls.** Scope (school/class/student) and the **`social_disponivel`** default (proposal:
  **off**; the per-profile `social_ativo` is the child's opt-in, default `False`); launch reach (class × school) —
  the **rule** is Section [09](09-social.md)'s.
- ⚠️ **19.15 — Pedagogical-catalog authoring/publishing interface** and the connection to the future subjects+questions software.
- ⚠️ **C15 — A/B with a child.** Is it allowed (17.28)? Under what ethical/consent limits — 19 only provides the toggle (blocked until then).
- ⚠️ **Rollback propagation.** Which `quest.*` keys are *forward-only* and which trigger a **recompute** of student
  state (from `quest_tentativas`) — per key class (referencing the owner [05](05-sistemas-de-jogo.md)/[17](17-telemetria-metricas.md)).
- ⚠️ **Values to confirm.** Pause window (proposal 40 min — Section [13](13-acessibilidade.md)), family push frequency
  and moderation SLA (Section [10](10-professor-familia.md)), social anti-spam caps (Section [09](09-social.md)). The
  **retention deadline** (24 months) is a **legal number owned by Section [12](12-seguranca-privacidade.md)** (executed
  by 14/17); if exposed in config, it is **GLOBAL-only** (no per-school override).

### 16. ADR (Architecture Decision Record)
- **ADR-19-A — Configuration over deploy; `quest.*` reuses the existing store.** No magic number in mechanic code;
  the tunable values live in `quest.*` on the `Configuracao` table (with a global layer), with a **safe code-default**
  (fail-safe) and a key catalog (C19); **schema** = Section [11](11-arquitetura.md), delivery = Section [14](14-infra-deploy-dr.md).
  *Scope/global representation pending (§15).*
- **ADR-19-B — The value references the owner.** Each `quest.*` key cites the **owner section** of the canonical
  number (cap = Section [05](05-sistemas-de-jogo.md); α = Section [06](06-pedagogico-bncc.md); rate-limit = Section
  [12](12-seguranca-privacidade.md)'s policy; cap/pause = Section [13](13-acessibilidade.md)'s norm with the **value**
  in 05/19); 19 **hosts and tunes**, never re-decides the rule.
- **ADR-19-C — Live-ops without dark patterns; non-negotiable protections.** Seasons/events/store obey **P7/P8**: a
  **free** pass (model = Section [22](22-monetizacao.md); immutability anchored in **P7** — candidate ADR C.20),
  **honest** scarcity (predictable return, no anxious countdown), **zero FOMO/paywall**; and **no** kill-switch/override
  **turns off or loosens** a protection of **well-being** (cap/pause — P6), **security** (rate-limit/login),
  **moderation/child-safety** (Section [10](10-professor-familia.md)) or **privacy** (Section [12](12-seguranca-privacidade.md))
  — clamped by a safe range, no partial kill, and a one-directional `social_ativo`.
- **ADR-19-D — Cron/delivery/schema are Sections 11/14's.** The **cron** (season, Flame shield, ranking reset — the
  **cadence** is Sections [05](05-sistemas-de-jogo.md)/[09](09-social.md)'s rule), the **cache/ETag** (Section
  [11](11-arquitetura.md)'s design) and **Redis** (Section [14](14-infra-deploy-dr.md)) are **mechanism**; 19 defines
  **which** jobs and **which** values, without reimplementing the mechanism. *The live-ops scheduler is a new Section 14 capability (§15).*

*Cross-module decisions are not improvised here: the pending items above become an ADR or a §15 entry.*
