# Apêndice B — Contratos de API & Modelo de Dados / API & Data Contracts

- **Status:** 🟢 aprovado / approved
- **Tipo:** documento de **referência** (não segue o padrão de 16 partes do [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md), que vale só para capítulos).
- **Fontes / Sources:** **código Q0** (`backend/app/quest/routers/*`, `schemas.py`, `services/credenciais.py`, `deps.py`, `models/*`) como verdade de base; seções-donas das **regras**: [11](11-arquitetura.md) (modelo de dados + convenções de API), [20](20-migracao-importacao.md) (contratos de import), [10](10-professor-familia.md) (semântica /professor e /familia), [12](12-seguranca-privacidade.md) (RBAC/isolamento).
- **Depende de:** o **código/Alembic (base 0001)** é a fonte do DDL; este apêndice **espelha** os modelos. Se divergir do código, **o código vence** e B se corrige — B **não inventa coluna nem rota**.

> **Selo por linha/tabela:** **🟢 Q0-REAL** = existe no código de produção hoje · **🔵 aspiracional (fase)** =
> desenhado no roadmap ([Seção 23](23-roadmap.md)), **sem código**. **Toda linha marca o selo.** O gabarito
> (`quest_desafios.gabarito`) **NUNCA** é serializado para o cliente (invariante da [Seção 11](11-arquitetura.md) + Princípio 13).

---

## 🇧🇷 Contratos de API & Dados

### B.1 Convenções gerais da API

- **Base:** todas as rotas montam sob `/api/v1` (`config.py: API_V1_PREFIX="/api/v1"`; routers incluídos em `main.py` com `prefix=settings.API_V1_PREFIX`). Ex.: `POST /api/v1/quest/auth/entrar`.
- **Formato:** JSON; datas em **UTC**; validação de corpo por **Pydantic** (erro de validação → **422**).
- **Autenticação:** **JWT Bearer**. O token do **aluno** (papel `aluno`) só vale nas rotas `/quest/*` do aluno; o token do **Edu** (papel adulto) vale nas rotas `/escolas/{escola_id}/quest/*`. **Os dois mundos nunca se cruzam** (`deps.py` rejeita token sem `papel="aluno"`; rotas do Edu rejeitam o claim `papel`).
- **Papéis por rota:** checados no backend (`exigir_papeis(...)` no Edu; `get_aluno_atual` no aluno).
- **Isolamento:** toda rota adulta passa por `escola_autorizada` (isolamento por `escola_id`, Princípio 15).
- **Paginação/ETag:** previstos para os agregados e o catálogo (aspiracional — nenhuma rota de catálogo existe em Q0).

### B.2 Contrato `/quest/auth` — 🟢 Q0-REAL

Fonte: `routers/auth.py`, `schemas.py`. Login infantil **sem senha** (o código É a credencial). Rate-limit em três camadas: por `(código, IP)`, por **código puro** (freia adivinhação de um código específico mesmo trocando de IP) e por **IP** (anti-enumeração em massa).

| Método | Caminho (sob `/api/v1`) | Papéis | Request | Response | Erros | Selo |
|--------|-------------------------|--------|---------|----------|-------|:----:|
| POST | `/quest/auth/quem` | público | `QuemIn { codigo }` | `QuemOut { nome, apelido, avatar }` | 401 (código inexistente), 403 (aluno inativo), 429 | 🟢 |
| POST | `/quest/auth/entrar` | público | `EntrarIn { codigo }` | `SessaoOut { access_token, token_type, primeira_vez, perfil }` | 401, 403, 429 | 🟢 |
| POST | `/quest/auth/entrar-qr` | público | `EntrarQrIn { qr_token }` | `SessaoOut` | 401, 403, 429 | 🟢 |

**Token real** (`services/credenciais.py::criar_token_aluno`, assinado com `SECRET_KEY`/`ALGORITHM`, expira em `QUEST_SESSAO_DIAS`):

```
claims = { sub: str(credencial.id), papel: "aluno", ver: token_version, iat, exp }
```

`get_aluno_atual` (`deps.py`) valida: `papel=="aluno"` (senão 401), credencial por `sub` (senão 401), `ver == token_version` (senão 401 "peça um cartão novo" — cartão regenerado derruba sessões), aluno `status=="ativo"` e perfil `status=="ativo"` (senão 401).

> ⚠️ **Divergência a reconciliar com a [Seção 11](11-arquitetura.md)** (o INDICE descreve um contrato-alvo, não o Q0): o índice cita rotas **`renovar`/`sair`** que **não existem** e claims **`perfil_id`/`aluno_id`/`escola_id`** que o token **não carrega**. O contrato **real** é o acima. A adoção de `renovar`/`sair` e de claims adicionais é aspiracional e precisa de spec/ADR.

### B.3 Contrato `/quest/perfil` — 🟢 Q0-REAL

Fonte: `routers/perfil.py`. Exigem JWT papel `aluno` (`get_aluno_atual`) **apenas** `GET /quest/perfil` e os três `PATCH` (`/nome`, `/avatar`, `/preferencias`). Os catálogos de vestiário (`/cores`, `/aparencia`, `/personagens`) **não têm dependência de autenticação no código** — são **públicos** (o router não declara `dependencies=`).

| Método | Caminho (sob `/api/v1`) | Papéis | Request | Response | Erros | Selo |
|--------|-------------------------|--------|---------|----------|-------|:----:|
| GET | `/quest/perfil` | aluno | — | `PerfilOut` | 401 | 🟢 |
| GET | `/quest/perfil/cores` | público | — | `list[str]` (cores do traje) | — | 🟢 |
| GET | `/quest/perfil/aparencia` | público | — | `dict { slot: [valores] }` (whitelist do vestiário) | — | 🟢 |
| GET | `/quest/perfil/personagens` | público | — | `list` (6 personagens-base) | — | 🟢 |
| PATCH | `/quest/perfil/nome` | aluno | `NomeIn { nome (2–20) }` | `PerfilOut` | 401, 422 | 🟢 |
| PATCH | `/quest/perfil/avatar` | aluno | `AvatarIn { pele, cabelo, cor_cabelo, top, camiseta, baixo, calca, tenis, chapeu, costas, aura, mao, pet, veiculo, cor }` (todos opcionais) | `PerfilOut` | 401, 422 | 🟢 |
| PATCH | `/quest/perfil/preferencias` | aluno | `PreferenciasIn { som, musica, narracao, reduzir_animacoes }` (todos opcionais) | `PerfilOut` | 401 | 🟢 |

**`PerfilOut`** (schema real): `id, apelido, codigo_amigo, nivel, xp_total, moedas, estrelas_total, sequencia_dias, avatar (dict), preferencias (dict), nome_exibicao (str|""), nome (str), dias_sem_jogar (int), codigo_login (str)`.

> ⚠️ **Divergência menor:** o INDICE cita `GET constelacao` (inexistente em Q0) e **omite** `GET /cores`, `/aparencia`, `/personagens` (que **existem**). Este apêndice documenta o **código real**; `constelacao` é aspiracional.

### B.4 Contrato `/quest/catalogo` — 🔵 aspiracional Q1+

**Nenhuma rota de catálogo existe em Q0** (as tabelas `quest_mundos/jornadas/missoes/desafios` existem, mas **sem router que as sirva**). Contrato-**alvo** (a detalhar em spec): `GET planetas`, `GET jornadas/{mundo}`, `GET missao/{id}` devolvendo os desafios **sem o campo `gabarito`**. **Autoridade do desenho:** [Seção 11](11-arquitetura.md) + [Seção 05](05-sistemas-de-jogo.md).

### B.5 Contrato `/quest/jogo` — 🔵 aspiracional Q1+

Sem router. Alvo: `POST iniciar` (abre tentativa), `POST responder` (correção **no servidor**), `POST finalizar` (recompensas server-side gravadas no ledger). Regras/valores = [Seção 05](05-sistemas-de-jogo.md); o cliente nunca corrige nem credita.

### B.6 Contrato `/quest/tarefas` — 🔵 aspiracional Q1+

Sem router. Alvo: Missões diárias/semanais (ritmo diário). Regras = [Seção 05](05-sistemas-de-jogo.md).

### B.7 Contrato `/quest/economia` — 🔵 aspiracional Q1+

Sem router. Alvo: saldo/loja/compra de cosméticos, tudo via **ledger imutável**; **sem dinheiro real** (Princípio 7). Regras = [Seção 05](05-sistemas-de-jogo.md)/[22](22-monetizacao.md).

### B.8 Contrato `/quest/social` — 🔵 aspiracional Q1+

Sem router. Alvo: amizade **só na mesma escola**, sem texto livre. Regras = [Seção 09](09-social.md).

### B.9 Contrato `/quest/salas` — 🔵 aspiracional Q4

Sem router. Alvo: partidas (Estudar com um amigo/Corrida). Regras = [Seção 09](09-social.md).

### B.10 Contrato WebSocket `/ws/quest` — 🔵 aspiracional Q4

Sem canal. Alvo: protocolo de partidas ao vivo (presença, corrida). Regras = [Seção 09](09-social.md)/[Seção 11](11-arquitetura.md).

### B.11 Contrato `/escolas/{escola_id}/quest` (professor) — 🟢 Q0-REAL (parcial)

Fonte: `routers/professor.py`. Papéis `admin`, `coordenador`, `professor` (`exigir_papeis`) + `escola_autorizada` + `exigir_turma_permitida`/`exigir_aluno_permitido` (professor restrito só vê as próprias turmas). Consumido pelo **Edu web**.

| Método | Caminho (sob `/api/v1`) | Papéis | Request | Response | Erros | Selo |
|--------|-------------------------|--------|---------|----------|-------|:----:|
| GET | `/escolas/{escola_id}/quest/turmas/{turma_id}/acessos` | admin/coord/prof | — | `list[AcessoAlunoOut]` | 401/403, 404 (turma) | 🟢 |
| POST | `/escolas/{escola_id}/quest/turmas/{turma_id}/cartoes` `?regenerar&rotacionar_codigo` | admin/coord/prof | — | **PDF** (cartões + página do professor) | 401/403, 404 (turma) | 🟢 |
| POST | `/escolas/{escola_id}/quest/alunos/{aluno_id}/cartao` `?regenerar&rotacionar_codigo` | admin/coord/prof | — | **PDF** (cartão individual) | 401/403, 404 (aluno), 422 (inativo) | 🟢 |

**`AcessoAlunoOut`**: `aluno_id, nome, nome_exibicao (str|null), apelido (str|null), codigo_login (str|null), ultimo_acesso (datetime|null), tem_credencial (bool)`.

> **Semântica** (donas [Seção 10](10-professor-familia.md)/[Seção 21](21-suporte-operacao.md)): `regenerar` troca o **QR** de todos e derruba sessões; `rotacionar_codigo` troca também o **código** (virada de ano / suspeita de vazamento). **Aspiracional** (sem router): panorama BNCC, erros comuns, trajetória, `POST atribuições` (Missão da Turma).

### B.12 ⚠️ Contrato `/quest/familia` — 🔵 aspiracional Q3

Sem router. **Pendência do dono:** quem autoriza o vínculo **responsável↔aluno** e em que fase a API entra. A tabela `responsaveis_alunos` **já existe** (B.14), mas o **vínculo só nasce autorizado por alguém da escola** (o responsável nunca se auto-vincula). Semântica = [Seção 10](10-professor-familia.md).

### B.13 Modelo de dados — convenções

- **Prefixo `quest_`** nas tabelas do jogo; tabelas do Edu referenciadas mantêm o nome próprio (`escolas`, `alunos`, `turmas`, `usuarios`).
- **`escola_id` + índice** em toda tabela ligada a aluno (isolamento multi-tenant, Princípio 15).
- **Histórico imutável:** `quest_tentativas` nunca é editada nem sobrescrita (fonte do painel do professor e dos agregados). O ledger de moedas (aspiracional) segue a mesma filosofia.
- **Caches recalculáveis:** `quest_perfis.nivel/moedas/estrelas_total` e `quest_habilidades` são **derivados** (a verdade vive nas tentativas/ledger).
- **Regras numéricas não-hardcoded:** valores (XP, preços, tetos, limites sociais) vivem em `configuracoes` no namespace `quest.*` ([Seção 19](19-liveops.md)).
- **DDL = Alembic (base 0001):** este apêndice espelha os modelos coluna-a-coluna.

### B.14 Grupo 1 — Identidade e acesso — 🟢 Q0-REAL

Fonte: `models/perfil.py`. (Autoridade: [Seção 11](11-arquitetura.md)/[Seção 12](12-seguranca-privacidade.md).)

**`quest_perfis`** — o astronauta (estado de jogo do aluno):

| Coluna | Tipo | Nulo? | Default | FK/Índice/Unique | Nota |
|--------|------|:-----:|---------|------------------|------|
| id | int | não | — | PK | |
| escola_id | int | não | — | FK `escolas.id`, index | isolamento (P15) |
| aluno_id | int | não | — | FK `alunos.id` ON DELETE CASCADE, **unique** | 1 perfil por aluno |
| nome_exibicao | str(40) | sim | NULL | — | como a criança pediu para ser chamada |
| apelido | str(60) | não | — | — | nome fora da própria turma (LGPD) |
| codigo_amigo | str(16) | não | — | **unique**, index | |
| nivel | int | não | 1 | — | cache recalculável |
| xp_total | int | não | 0 | — | cache recalculável |
| moedas | int | não | 0 | — | cache recalculável (verdade no ledger) |
| estrelas_total | int | não | 0 | — | cache recalculável |
| sequencia_dias | int | não | 0 | — | "Chama do Cosmo" |
| escudo_sequencia | bool | não | true | — | perdoa 1 falta/semana |
| ultimo_dia_ativo | date | sim | NULL | — | |
| avatar | JSON | não | {} | — | itens equipados |
| preferencias | JSON | não | {} | — | som/música/narração/reduzir_animacoes |
| dificuldade | JSON | não | {} | — | nível adaptativo por mundo (invisível) |
| social_ativo | bool | não | false | — | social **desligado por padrão** (P3) |
| status | str(20) | não | "ativo" | — | |
| created_at | datetime | não | agora | — | |

**`quest_credenciais_aluno`** — login infantil (separado do estado de jogo):

| Coluna | Tipo | Nulo? | Default | FK/Índice/Unique | Nota |
|--------|------|:-----:|---------|------------------|------|
| id | int | não | — | PK | |
| escola_id | int | não | — | FK `escolas.id`, index | |
| aluno_id | int | não | — | FK `alunos.id` CASCADE, **unique** | |
| codigo_login | str(20) | não | — | **unique**, index | falável, só letras+números; único na rede |
| qr_token | str(64) | não | — | **unique**, index | login por QR; trocável |
| token_version | int | não | 0 | — | ++ ao regenerar → derruba sessões |
| ultimo_acesso | datetime | sim | NULL | — | |
| created_at | datetime | não | agora | — | |

**`responsaveis_alunos`** — vínculo responsável↔aluno (só nasce autorizado pela escola):

| Coluna | Tipo | Nulo? | Default | FK/Índice/Unique | Nota |
|--------|------|:-----:|---------|------------------|------|
| id | int | não | — | PK | |
| escola_id | int | não | — | FK `escolas.id`, index | |
| usuario_id | int | não | — | FK `usuarios.id` CASCADE, index | responsável (cargo=responsavel) |
| aluno_id | int | não | — | FK `alunos.id` CASCADE, index | |
| parentesco | str(40) | sim | NULL | — | |
| autorizado_por | int | sim | NULL | FK `usuarios.id` SET NULL | quem da escola autorizou |
| created_at | datetime | não | agora | — | **Unique**(`usuario_id`, `aluno_id`) |

### B.15 Grupo 2 — Conteúdo pedagógico — 🟢 Q0-REAL (tabelas existem; sem rota que as exponha)

Fonte: `models/catalogo.py`. (Autoridade: [Seção 06](06-pedagogico-bncc.md)/[Seção 11](11-arquitetura.md).)

**`quest_mundos`** (Planeta = disciplina): `id` PK · `slug` str(40) unique index · `nome` str(80) · `descricao` str(500) nullable · `ordem` int=0 · `tema` JSON={} (identidade visual/sonora) · `icone` str(16)="🪐" · `ativo` bool=true · `created_at`.

**`quest_jornadas`** (trilha por ano/BNCC): `id` PK · `mundo_id` FK `quest_mundos.id` CASCADE index · `nome` str(120) · `descricao` str(500) nullable · `ano_escolar` str(30) index · `ordem` int=0 · `bncc` JSON(list)=[] (códigos de habilidade) · `estrelas_chefao` int=0 (limiar do Chefão) · `ativo` bool=true · `created_at`.

**`quest_missoes`**: `id` PK · `jornada_id` FK `quest_jornadas.id` CASCADE index · `ordem` int=0 · `nome` str(120) · `tipo` str(20)="normal" (`normal|chefao|evento`) · `icone` str(16) nullable · `descricao_crianca` str(300) nullable · `xp_base` int=40 · `moedas_base` int=10 · `config` JSON={} · `versao` int=1 (editar publicada cria nova versão) · `status` str(20)="rascunho" index (`rascunho|publicada|arquivada`) · `created_at`.

**`quest_desafios`**: `id` PK · `missao_id` FK `quest_missoes.id` CASCADE index · `ordem` int=0 · `mecanica` str(30) (`quiz|arrastar|ligar|memoria|…`) · `dificuldade` int=2 (1–5) · `bncc_codigo` str(12) nullable index · `corpo` JSON={} (enunciado/áudio/mídia/opções) · **`gabarito` JSON={} — NUNCA entregue ao cliente** · `dica` JSON={} · `explicacao` JSON={}.

### B.16 Grupo 3 — Progresso e telemetria — 🟢 Q0-REAL

Fonte: `models/progresso.py`. (Autoridade: [Seção 11](11-arquitetura.md)/[Seção 17](17-telemetria-metricas.md).)

**`quest_progresso`** (melhor resultado por aluno × missão): `id` PK · `perfil_id` FK `quest_perfis.id` CASCADE index · `missao_id` FK `quest_missoes.id` index · `estrelas` int=0 (0–3, vale a melhor) · `melhor_pct` float=0.0 · `tentativas` int=0 · `primeira_conclusao_em` datetime nullable · `ultima_tentativa_em` datetime nullable · **Unique**(`perfil_id`, `missao_id`).

**`quest_tentativas`** (**registro imutável** de cada jogada): `id` PK · `escola_id` FK index · `perfil_id` FK `quest_perfis.id` CASCADE index · `missao_id` FK `quest_missoes.id` index · `missao_versao` int=1 (versão jogada) · `modo` str(20)="solo" (`solo|coop|corrida|x1`) · `sala_id` int nullable **sem FK** (`quest_salas` ainda não existe — Q4) · `iniciada_em` datetime=agora (default) · `finalizada_em` datetime nullable · `total_desafios` int=0 · `acertos` int=0 · `tempo_seg` int=0 · `xp_ganho` int=0 · `moedas_ganhas` int=0 · `estrelas` int=0 · `respostas` JSON(list)=[] (por desafio) · `origem` str(12)="web" (`web|pwa-offline`). Índices: (`perfil_id`,`finalizada_em`), (`escola_id`,`finalizada_em`).

**`quest_habilidades`** (agregado por habilidade BNCC — **cache recalculável**): `id` PK · `perfil_id` FK `quest_perfis.id` CASCADE index · `bncc_codigo` str(12) index · `tentativas` int=0 · `acertos` int=0 · `dominio` float=0.0 (0–100, média móvel) · `ultima_atividade_em` datetime nullable · **Unique**(`perfil_id`, `bncc_codigo`).

### B.17 Grupo 4 — Economia e coleção — 🔵 aspiracional (desenhadas, **não criadas**)

Tabelas-alvo: `quest_itens`, `quest_inventario`, `quest_transacoes_moedas` (ledger imutável). **Não existem** em Q0. DDL coluna-a-coluna = spec futura; regras/valores = [Seção 05](05-sistemas-de-jogo.md).

### B.18 Grupo 5 — Ritmo diário e conquistas — 🔵 aspiracional (não criadas)

Tabelas-alvo: `quest_tarefas_periodicas`, `quest_conquistas`, `quest_conquistas_obtidas`. Design = [Seção 05](05-sistemas-de-jogo.md).

### B.19 Grupo 6 — Social e partidas — 🔵 aspiracional (não criadas)

Tabelas-alvo: `quest_amizades`, `quest_salas`, `quest_mensagens_rapidas`. Confirmado em `progresso.py`: `quest_tentativas.sala_id` **não tem FK** "porque `quest_salas` ainda não existe". Design = [Seção 09](09-social.md).

### B.20 Grupo 7 — Temporadas e eventos — 🔵 aspiracional (não criadas)

Tabelas-alvo: `quest_temporadas`, `quest_passe_progresso`, `quest_eventos`. Design = [Seção 05](05-sistemas-de-jogo.md)/[19](19-liveops.md)/[22](22-monetizacao.md).

### B.21 Grupo 8 — Integração — 🔵 aspiracional (não criada)

Tabela-alvo: `quest_outbox` (introduzida na fase **Q3** para notificações/integração; a telemetria social é Q4). Design = [Seção 11](11-arquitetura.md)/[17](17-telemetria-metricas.md).

### B.22 Tabelas adiadas (desenhadas, não criadas)

Clubes e torneios (fase Q5, condicionais). Sem DDL até virarem spec.

### B.23 ⚠️ Schemas de conteúdo por mecânica

**Pendência de design:** o formato JSON de `corpo`/`gabarito` por mecânica (`quiz`, `arrastar`, `ligar`, `memoria`, `caça-palavras`, `completar`, `sequência`). Hoje `quest_desafios.corpo/gabarito` são **JSON livre**. O contrato por mecânica é dono do **design de jogo** ([Seção 05](05-sistemas-de-jogo.md)).

### B.24 Esquema de configurações `quest.*`

Namespace das regras não-hardcoded em `configuracoes` (KV por escola). Chaves-alvo (valores = [Seção 19](19-liveops.md)/[Seção 05](05-sistemas-de-jogo.md)): XP por desafio/multiplicadores, `moedas_base`, teto diário, preços de cosméticos, limites sociais. B fornece o **mapa de chaves**, não os valores.

### B.25 Versionamento e compatibilidade

- **`quest_missoes.versao`:** editar uma missão publicada cria nova versão; a **`quest_tentativas.missao_versao`** (campo real) grava a versão jogada — análises históricas ficam corretas.
- **ETag/versão do catálogo:** aspiracional (revalidação sem rebaixar conteúdo).
- **Deprecação de contrato:** proposto → ativo → depreciado → removido (política transversal).

### B.26 Códigos de erro e políticas transversais

| Código | Quando | Exemplo Q0 |
|:------:|--------|-----------|
| **401** | sessão inválida/expirada; código inexistente | `entrar` com código desconhecido; `ver` ≠ token_version |
| **403** | papel sem permissão; **aluno inativo** no login | `quem`/`entrar` de aluno `status != "ativo"` |
| **404** | recurso fora do escopo | turma/aluno de outra escola |
| **422** | validação Pydantic / regra de domínio | `nome` fora de 2–20; cartão de aluno inativo |
| **429** | rate-limit excedido | tentativas de login acima do teto por (código/IP) |

Políticas: rate-limit anti-farm no login; **gabarito nunca no cliente**; isolamento por `escola_id` em toda rota adulta.

### B.27 ⚠️ Contrato de tipos compartilhados `@constela/quest-core`

**Pendência:** consolidar o contrato de **avatar** (humanoide 3D) e aposentar tipos legados do Cosmo — fonte única de tipos para o cliente (`apps/quest`) e o Edu web. Depende da decisão fundadora de avatar ([Seção 04](04-personagens-avatar.md)).

### B.28 ⚠️ Contrato de escrita do catálogo pedagógico (autoria)

**Pendência:** por qual interface `mundos → jornadas → missões → desafios` é cadastrado/publicado (admin no Edu × software futuro de matérias+questões). Define o contrato de **autoria** do catálogo. Donas = [Seção 06](06-pedagogico-bncc.md)/[Seção 11](11-arquitetura.md).

---

## 🇬🇧 API & Data Contracts

### B.1 General API conventions

- **Base:** all routes mount under `/api/v1` (`config.py: API_V1_PREFIX="/api/v1"`; routers included in `main.py` with `prefix=settings.API_V1_PREFIX`). E.g. `POST /api/v1/quest/auth/entrar`.
- **Format:** JSON; dates in **UTC**; body validated by **Pydantic** (validation error → **422**).
- **Auth:** **JWT Bearer**. The **student** token (role `aluno`) only works on the student's `/quest/*` routes; the **Edu** token (adult role) works on `/escolas/{escola_id}/quest/*`. **The two worlds never cross** (`deps.py` rejects any token without `papel="aluno"`; Edu routes reject the `papel` claim).
- **Per-route roles:** checked in the backend (`exigir_papeis(...)` on Edu; `get_aluno_atual` on the student).
- **Isolation:** every adult route goes through `escola_autorizada` (isolation by `escola_id`, Principle 15).
- **Pagination/ETag:** planned for aggregates and the catalog (aspirational — no catalog route exists in Q0).

### B.2 `/quest/auth` contract — 🟢 Q0-REAL

Source: `routers/auth.py`, `schemas.py`. Passwordless child login (the code IS the credential). Three-layer rate-limit: by `(code, IP)`, by **bare code** (curbs guessing one specific code even across IPs) and by **IP** (mass-enumeration guard).

| Method | Path (under `/api/v1`) | Roles | Request | Response | Errors | Seal |
|--------|------------------------|-------|---------|----------|--------|:----:|
| POST | `/quest/auth/quem` | public | `QuemIn { codigo }` | `QuemOut { nome, apelido, avatar }` | 401 (unknown code), 403 (inactive student), 429 | 🟢 |
| POST | `/quest/auth/entrar` | public | `EntrarIn { codigo }` | `SessaoOut { access_token, token_type, primeira_vez, perfil }` | 401, 403, 429 | 🟢 |
| POST | `/quest/auth/entrar-qr` | public | `EntrarQrIn { qr_token }` | `SessaoOut` | 401, 403, 429 | 🟢 |

**Real token** (`services/credenciais.py::criar_token_aluno`, signed with `SECRET_KEY`/`ALGORITHM`, expires in `QUEST_SESSAO_DIAS`):

```
claims = { sub: str(credencial.id), papel: "aluno", ver: token_version, iat, exp }
```

`get_aluno_atual` (`deps.py`) validates: `papel=="aluno"` (else 401), credential by `sub` (else 401), `ver == token_version` (else 401 "ask for a new card" — a regenerated card drops sessions), student `status=="ativo"` and profile `status=="ativo"` (else 401).

> ⚠️ **Divergence to reconcile with [Section 11](11-arquitetura.md)** (the INDEX describes a target contract, not Q0): it cites **`renovar`/`sair`** routes that **don't exist** and claims **`perfil_id`/`aluno_id`/`escola_id`** the token **does not carry**. The **real** contract is the one above. Adopting `renovar`/`sair` and extra claims is aspirational and needs a spec/ADR.

### B.3 `/quest/perfil` contract — 🟢 Q0-REAL

Source: `routers/perfil.py`. JWT role `aluno` (`get_aluno_atual`) is required **only** on `GET /quest/perfil` and the three `PATCH` routes (`/nome`, `/avatar`, `/preferencias`). The wardrobe catalogs (`/cores`, `/aparencia`, `/personagens`) **have no auth dependency in the code** — they are **public** (the router declares no `dependencies=`).

| Method | Path (under `/api/v1`) | Roles | Request | Response | Errors | Seal |
|--------|------------------------|-------|---------|----------|--------|:----:|
| GET | `/quest/perfil` | student | — | `PerfilOut` | 401 | 🟢 |
| GET | `/quest/perfil/cores` | public | — | `list[str]` (suit colors) | — | 🟢 |
| GET | `/quest/perfil/aparencia` | public | — | `dict { slot: [values] }` (wardrobe whitelist) | — | 🟢 |
| GET | `/quest/perfil/personagens` | public | — | `list` (6 base characters) | — | 🟢 |
| PATCH | `/quest/perfil/nome` | student | `NomeIn { nome (2–20) }` | `PerfilOut` | 401, 422 | 🟢 |
| PATCH | `/quest/perfil/avatar` | student | `AvatarIn { pele, cabelo, cor_cabelo, top, camiseta, baixo, calca, tenis, chapeu, costas, aura, mao, pet, veiculo, cor }` (all optional) | `PerfilOut` | 401, 422 | 🟢 |
| PATCH | `/quest/perfil/preferencias` | student | `PreferenciasIn { som, musica, narracao, reduzir_animacoes }` (all optional) | `PerfilOut` | 401 | 🟢 |

**`PerfilOut`** (real schema): `id, apelido, codigo_amigo, nivel, xp_total, moedas, estrelas_total, sequencia_dias, avatar (dict), preferencias (dict), nome_exibicao (str|""), nome (str), dias_sem_jogar (int), codigo_login (str)`.

> ⚠️ **Minor divergence:** the INDEX cites `GET constelacao` (nonexistent in Q0) and **omits** `GET /cores`, `/aparencia`, `/personagens` (which **exist**). This appendix documents the **real code**; `constelacao` is aspirational.

### B.4 `/quest/catalogo` contract — 🔵 aspirational Q1+

**No catalog route exists in Q0** (the `quest_mundos/jornadas/missoes/desafios` tables exist, but **no router serves them**). **Target** contract (spec-time): `GET planetas`, `GET jornadas/{mundo}`, `GET missao/{id}` returning challenges **without the `gabarito` field**. **Design owner:** [Section 11](11-arquitetura.md) + [Section 05](05-sistemas-de-jogo.md).

### B.5 `/quest/jogo` contract — 🔵 aspirational Q1+

No router. Target: `POST iniciar` (open attempt), `POST responder` (grading **on the server**), `POST finalizar` (server-side rewards written to the ledger). Rules/values = [Section 05](05-sistemas-de-jogo.md); the client never grades nor credits.

### B.6 `/quest/tarefas` contract — 🔵 aspirational Q1+

No router. Target: daily/weekly Missions (daily rhythm). Rules = [Section 05](05-sistemas-de-jogo.md).

### B.7 `/quest/economia` contract — 🔵 aspirational Q1+

No router. Target: balance/shop/cosmetic purchase, all via the **immutable ledger**; **no real money** (Principle 7). Rules = [Section 05](05-sistemas-de-jogo.md)/[22](22-monetizacao.md).

### B.8 `/quest/social` contract — 🔵 aspirational Q1+

No router. Target: friendship **within the same school only**, no free text. Rules = [Section 09](09-social.md).

### B.9 `/quest/salas` contract — 🔵 aspirational Q4

No router. Target: matches (Study with a friend/Race). Rules = [Section 09](09-social.md).

### B.10 WebSocket `/ws/quest` contract — 🔵 aspirational Q4

No channel. Target: live-match protocol (presence, race). Rules = [Section 09](09-social.md)/[Section 11](11-arquitetura.md).

### B.11 `/escolas/{escola_id}/quest` contract (teacher) — 🟢 Q0-REAL (partial)

Source: `routers/professor.py`. Roles `admin`, `coordenador`, `professor` (`exigir_papeis`) + `escola_autorizada` + `exigir_turma_permitida`/`exigir_aluno_permitido` (a restricted teacher sees only their own classes). Consumed by the **Edu web**.

| Method | Path (under `/api/v1`) | Roles | Request | Response | Errors | Seal |
|--------|------------------------|-------|---------|----------|--------|:----:|
| GET | `/escolas/{escola_id}/quest/turmas/{turma_id}/acessos` | admin/coord/teacher | — | `list[AcessoAlunoOut]` | 401/403, 404 (class) | 🟢 |
| POST | `/escolas/{escola_id}/quest/turmas/{turma_id}/cartoes` `?regenerar&rotacionar_codigo` | admin/coord/teacher | — | **PDF** (cards + teacher page) | 401/403, 404 (class) | 🟢 |
| POST | `/escolas/{escola_id}/quest/alunos/{aluno_id}/cartao` `?regenerar&rotacionar_codigo` | admin/coord/teacher | — | **PDF** (individual card) | 401/403, 404 (student), 422 (inactive) | 🟢 |

**`AcessoAlunoOut`**: `aluno_id, nome, nome_exibicao (str|null), apelido (str|null), codigo_login (str|null), ultimo_acesso (datetime|null), tem_credencial (bool)`.

> **Semantics** (owners [Section 10](10-professor-familia.md)/[Section 21](21-suporte-operacao.md)): `regenerar` swaps everyone's **QR** and drops sessions; `rotacionar_codigo` also swaps the **code** (year rollover / suspected leak). **Aspirational** (no router): BNCC panorama, common mistakes, trajectory, `POST atribuições` (Class Mission).

### B.12 ⚠️ `/quest/familia` contract — 🔵 aspirational Q3

No router. **Owner-pending:** who authorizes the **guardian↔student** link and in which phase the API arrives. The `responsaveis_alunos` table **already exists** (B.14), but the **link is only born authorized by someone at the school** (the guardian never self-links). Semantics = [Section 10](10-professor-familia.md).

### B.13 Data model — conventions

- **`quest_` prefix** on game tables; referenced Edu tables keep their own names (`escolas`, `alunos`, `turmas`, `usuarios`).
- **`escola_id` + index** on every student-linked table (multi-tenant isolation, Principle 15).
- **Immutable history:** `quest_tentativas` is never edited nor overwritten (source of the teacher panel and aggregates). The coin ledger (aspirational) follows the same philosophy.
- **Recomputable caches:** `quest_perfis.nivel/moedas/estrelas_total` and `quest_habilidades` are **derived** (truth lives in attempts/ledger).
- **Non-hardcoded numeric rules:** values (XP, prices, caps, social limits) live in `configuracoes` under the `quest.*` namespace ([Section 19](19-liveops.md)).
- **DDL = Alembic (base 0001):** this appendix mirrors the models column by column.

### B.14 Group 1 — Identity & access — 🟢 Q0-REAL

Source: `models/perfil.py`. (Authority: [Section 11](11-arquitetura.md)/[Section 12](12-seguranca-privacidade.md).)

**`quest_perfis`** — the astronaut (student's game state):

| Column | Type | Null? | Default | FK/Index/Unique | Note |
|--------|------|:-----:|---------|-----------------|------|
| id | int | no | — | PK | |
| escola_id | int | no | — | FK `escolas.id`, index | isolation (P15) |
| aluno_id | int | no | — | FK `alunos.id` ON DELETE CASCADE, **unique** | 1 profile per student |
| nome_exibicao | str(40) | yes | NULL | — | how the child asked to be called |
| apelido | str(60) | no | — | — | name outside their own class (LGPD) |
| codigo_amigo | str(16) | no | — | **unique**, index | |
| nivel | int | no | 1 | — | recomputable cache |
| xp_total | int | no | 0 | — | recomputable cache |
| moedas | int | no | 0 | — | recomputable cache (truth in the ledger) |
| estrelas_total | int | no | 0 | — | recomputable cache |
| sequencia_dias | int | no | 0 | — | "Cosmo's Flame" |
| escudo_sequencia | bool | no | true | — | forgives 1 miss/week |
| ultimo_dia_ativo | date | yes | NULL | — | |
| avatar | JSON | no | {} | — | equipped items |
| preferencias | JSON | no | {} | — | sound/music/narration/reduce-motion |
| dificuldade | JSON | no | {} | — | adaptive level per world (invisible) |
| social_ativo | bool | no | false | — | social **off by default** (P3) |
| status | str(20) | no | "ativo" | — | |
| created_at | datetime | no | now | — | |

**`quest_credenciais_aluno`** — child login (separate from game state):

| Column | Type | Null? | Default | FK/Index/Unique | Note |
|--------|------|:-----:|---------|-----------------|------|
| id | int | no | — | PK | |
| escola_id | int | no | — | FK `escolas.id`, index | |
| aluno_id | int | no | — | FK `alunos.id` CASCADE, **unique** | |
| codigo_login | str(20) | no | — | **unique**, index | speakable, letters+digits only; unique across the network |
| qr_token | str(64) | no | — | **unique**, index | QR login; swappable |
| token_version | int | no | 0 | — | ++ on regenerate → drops sessions |
| ultimo_acesso | datetime | yes | NULL | — | |
| created_at | datetime | no | now | — | |

**`responsaveis_alunos`** — guardian↔student link (born authorized by the school only):

| Column | Type | Null? | Default | FK/Index/Unique | Note |
|--------|------|:-----:|---------|-----------------|------|
| id | int | no | — | PK | |
| escola_id | int | no | — | FK `escolas.id`, index | |
| usuario_id | int | no | — | FK `usuarios.id` CASCADE, index | guardian (role=responsavel) |
| aluno_id | int | no | — | FK `alunos.id` CASCADE, index | |
| parentesco | str(40) | yes | NULL | — | |
| autorizado_por | int | yes | NULL | FK `usuarios.id` SET NULL | who at the school authorized |
| created_at | datetime | no | now | — | **Unique**(`usuario_id`, `aluno_id`) |

### B.15 Group 2 — Pedagogical content — 🟢 Q0-REAL (tables exist; no route serves them)

Source: `models/catalogo.py`. (Authority: [Section 06](06-pedagogico-bncc.md)/[Section 11](11-arquitetura.md).)

**`quest_mundos`** (Planet = subject): `id` PK · `slug` str(40) unique index · `nome` str(80) · `descricao` str(500) nullable · `ordem` int=0 · `tema` JSON={} (visual/audio identity) · `icone` str(16)="🪐" · `ativo` bool=true · `created_at`.

**`quest_jornadas`** (track by year/BNCC): `id` PK · `mundo_id` FK `quest_mundos.id` CASCADE index · `nome` str(120) · `descricao` str(500) nullable · `ano_escolar` str(30) index · `ordem` int=0 · `bncc` JSON(list)=[] (skill codes) · `estrelas_chefao` int=0 (Boss threshold) · `ativo` bool=true · `created_at`.

**`quest_missoes`**: `id` PK · `jornada_id` FK `quest_jornadas.id` CASCADE index · `ordem` int=0 · `nome` str(120) · `tipo` str(20)="normal" (`normal|chefao|evento`) · `icone` str(16) nullable · `descricao_crianca` str(300) nullable · `xp_base` int=40 · `moedas_base` int=10 · `config` JSON={} · `versao` int=1 (editing a published mission creates a new version) · `status` str(20)="rascunho" index (`rascunho|publicada|arquivada`) · `created_at`.

**`quest_desafios`**: `id` PK · `missao_id` FK `quest_missoes.id` CASCADE index · `ordem` int=0 · `mecanica` str(30) (`quiz|arrastar|ligar|memoria|…`) · `dificuldade` int=2 (1–5) · `bncc_codigo` str(12) nullable index · `corpo` JSON={} (prompt/audio/media/options) · **`gabarito` JSON={} — NEVER sent to the client** · `dica` JSON={} · `explicacao` JSON={}.

### B.16 Group 3 — Progress & telemetry — 🟢 Q0-REAL

Source: `models/progresso.py`. (Authority: [Section 11](11-arquitetura.md)/[Section 17](17-telemetria-metricas.md).)

**`quest_progresso`** (best result per student × mission): `id` PK · `perfil_id` FK `quest_perfis.id` CASCADE index · `missao_id` FK `quest_missoes.id` index · `estrelas` int=0 (0–3, best counts) · `melhor_pct` float=0.0 · `tentativas` int=0 · `primeira_conclusao_em` datetime nullable · `ultima_tentativa_em` datetime nullable · **Unique**(`perfil_id`, `missao_id`).

**`quest_tentativas`** (**immutable record** of each play): `id` PK · `escola_id` FK index · `perfil_id` FK `quest_perfis.id` CASCADE index · `missao_id` FK `quest_missoes.id` index · `missao_versao` int=1 (version played) · `modo` str(20)="solo" (`solo|coop|corrida|x1`) · `sala_id` int nullable **no FK** (`quest_salas` doesn't exist yet — Q4) · `iniciada_em` datetime=now (default) · `finalizada_em` datetime nullable · `total_desafios` int=0 · `acertos` int=0 · `tempo_seg` int=0 · `xp_ganho` int=0 · `moedas_ganhas` int=0 · `estrelas` int=0 · `respostas` JSON(list)=[] (per challenge) · `origem` str(12)="web" (`web|pwa-offline`). Indexes: (`perfil_id`,`finalizada_em`), (`escola_id`,`finalizada_em`).

**`quest_habilidades`** (per-BNCC-skill aggregate — **recomputable cache**): `id` PK · `perfil_id` FK `quest_perfis.id` CASCADE index · `bncc_codigo` str(12) index · `tentativas` int=0 · `acertos` int=0 · `dominio` float=0.0 (0–100, moving average) · `ultima_atividade_em` datetime nullable · **Unique**(`perfil_id`, `bncc_codigo`).

### B.17 Group 4 — Economy & collection — 🔵 aspirational (designed, **not created**)

Target tables: `quest_itens`, `quest_inventario`, `quest_transacoes_moedas` (immutable ledger). **Do not exist** in Q0. Column-by-column DDL = future spec; rules/values = [Section 05](05-sistemas-de-jogo.md).

### B.18 Group 5 — Daily rhythm & achievements — 🔵 aspirational (not created)

Target tables: `quest_tarefas_periodicas`, `quest_conquistas`, `quest_conquistas_obtidas`. Design = [Section 05](05-sistemas-de-jogo.md).

### B.19 Group 6 — Social & matches — 🔵 aspirational (not created)

Target tables: `quest_amizades`, `quest_salas`, `quest_mensagens_rapidas`. Confirmed in `progresso.py`: `quest_tentativas.sala_id` has **no FK** "because `quest_salas` doesn't exist yet". Design = [Section 09](09-social.md).

### B.20 Group 7 — Seasons & events — 🔵 aspirational (not created)

Target tables: `quest_temporadas`, `quest_passe_progresso`, `quest_eventos`. Design = [Section 05](05-sistemas-de-jogo.md)/[19](19-liveops.md)/[22](22-monetizacao.md).

### B.21 Group 8 — Integration — 🔵 aspirational (not created)

Target table: `quest_outbox` (introduced in phase **Q3** for notifications/integration; social telemetry is Q4). Design = [Section 11](11-arquitetura.md)/[17](17-telemetria-metricas.md).

### B.22 Deferred tables (designed, not created)

Clubs and tournaments (phase Q5, conditional). No DDL until they become a spec.

### B.23 ⚠️ Per-mechanic content schemas

**Design pending:** the JSON format of `corpo`/`gabarito` per mechanic (`quiz`, `arrastar`, `ligar`, `memoria`, `word-search`, `fill-in`, `sequence`). Today `quest_desafios.corpo/gabarito` are **free JSON**. The per-mechanic contract is owned by **game design** ([Section 05](05-sistemas-de-jogo.md)).

### B.24 `quest.*` configuration schema

Namespace of non-hardcoded rules in `configuracoes` (per-school KV). Target keys (values = [Section 19](19-liveops.md)/[Section 05](05-sistemas-de-jogo.md)): XP per challenge/multipliers, `moedas_base`, daily cap, cosmetic prices, social limits. B provides the **key map**, not the values.

### B.25 Versioning & compatibility

- **`quest_missoes.versao`:** editing a published mission creates a new version; **`quest_tentativas.missao_versao`** (real field) records the version played — historical analyses stay correct.
- **Catalog ETag/version:** aspirational (revalidate without downgrading content).
- **Contract deprecation:** proposed → active → deprecated → removed (cross-cutting policy).

### B.26 Error codes & cross-cutting policies

| Code | When | Q0 example |
|:----:|------|-----------|
| **401** | invalid/expired session; unknown code | `entrar` with an unknown code; `ver` ≠ token_version |
| **403** | role lacks permission; **inactive student** at login | `quem`/`entrar` for a student with `status != "ativo"` |
| **404** | resource out of scope | class/student from another school |
| **422** | Pydantic validation / domain rule | `nome` outside 2–20; card for an inactive student |
| **429** | rate-limit exceeded | login attempts above the (code/IP) cap |

Policies: anti-farm login rate-limit; **gabarito never on the client**; `escola_id` isolation on every adult route.

### B.27 ⚠️ Shared-types contract `@constela/quest-core`

**Pending:** consolidate the **avatar** contract (3D humanoid) and retire legacy Cosmo types — single source of types for the client (`apps/quest`) and the Edu web. Depends on the founding avatar decision ([Section 04](04-personagens-avatar.md)).

### B.28 ⚠️ Pedagogical-catalog authoring contract

**Pending:** through which interface `mundos → jornadas → missões → desafios` is registered/published (admin in Edu × the future subjects+questions software). Defines the catalog **authoring** contract. Owners = [Section 06](06-pedagogico-bncc.md)/[Section 11](11-arquitetura.md).
