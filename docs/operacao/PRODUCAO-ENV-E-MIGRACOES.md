# Produção: `ENV=producao` e migrações no pre-deploy (passo a passo para o dono)

Data: 20/10/2026. Escrito junto com o código do branch `rc/infra`. **Nada aqui foi
executado no Railway**: são instruções para o dono, na ordem segura. Tudo o que diz
"comprovado" foi provado em testes LOCAIS (SQLite e PostgreSQL 16 descartável); o
comportamento do Railway vem da documentação pública (lida em 20/10) e está marcado
como tal. Origem: a proposta B de 18/10 (`PROPOSTA-env-migracao.md`, fora do
repositório), agora implementada no código.

Atualizado em 24/10/2026 (ramo `prontidao/e97b-config-prod`, A3 critérios 7 e 9): com
`ENV=producao` o boot passa a recusar também DEK ausente ou igual à `SECRET_KEY`, CORS
com `*` e `/docs` ligado, além de `SECRET_KEY` e DEK com um **valor de exemplo publicado
no repositório** (os `.env.example` agora trazem as duas vazias); o CORS de produção
perde as origens de desenvolvimento local e a origem `null`; o `ENV` é lido sem espaços
nas pontas, caixa e acento; a **lista final de variáveis** e a ordem dos passos estão no
§2.1.

Atualizado em 24/10/2026 (ramo `prontidao/e97c-quest-auth-residuos`): checklist pré-deploy
das contas com senha derivada do nome (`scripts.senhas_derivadas --contagens`, só leitura e
só números), no §3, antes do passo 0a.

## 1. Situação de hoje (fatos de 20/10)

- O serviço do backend roda **sem `ENV`** (vale `"dev"`) com o comando de partida
  `uvicorn app.main:app --host 0.0.0.0 --port 8080`, que **substitui** o
  `entrypoint.sh` da imagem. Healthcheck: `/api/health/ready` (600 s).
- Por estar em modo dev, **as migrações rodam no import do app** (`app/main.py`), em
  cada boot. É o único lugar onde elas rodam hoje.
- Mudar `ENV=producao` sozinho **desliga essas migrações em silêncio**: o próximo deploy
  com migração subiria sobre o schema velho.
- O comando de partida **não tem `--no-access-log`**: com o código do `main` de hoje, o
  uvicorn escreve no stdout (log do Railway, região sfo, EUA) uma linha de texto por
  requisição com a **URL crua** — o token do painel público, o token do link de
  redefinição de senha e o `?busca=` com nome de criança vão inteiros para o log. Este
  pacote fecha isso no próprio app, com ou sem a flag (ver a tabela abaixo); até ele
  estar no ar, só o passo 0a fecha.
- O `main` de produção está na revisão **0035**. Este pacote traz **duas** migrações:
  `0036_rls_todas_as_tabelas` e `0037_quest_codigo_hash_limites`.

## 2. O que este código muda (e por que a sequência abaixo é segura)

| Peça | Antes | Agora |
|---|---|---|
| `/api/health/ready` | só `SELECT 1` | banco **e** schema nas heads do Alembic do código. Migração pendente → **503** `{"motivo": "migracao_pendente"}`: o healthcheck reprova e **o deploy anterior continua no ar** |
| Boot com schema errado | escrevia ajustes de dados mesmo assim | sobe, não escreve nada no banco (nem ajustes de dados, nem liberação de órfãs, nem o agendador de sync — se `SYNC_SCHEDULER_ENABLED` estiver ligado, ele **não sobe** e o log diz por quê), readiness 503 e log `NÃO PRONTO — schema atras ...`. E fica 503 **até reiniciar**: se a migração for aplicada por fora com esse processo de pé, o readiness passa a `reinicio_pendente` (log `NÃO PRONTO — REINICIE o serviço ...`), porque o que o boot pulou não sobe sozinho — sem isso o Railway ativaria um processo sem a coleta automática |
| `scripts.migrate` | migrava e imprimia "Migração concluída." | idem, com `Antes:`/`Depois:`, advisory lock (dois migradores se enfileiram), `lock_timeout`, nova tentativa e códigos de saída **0** ok / **2** lock ocupado / **3** banco adiante do código / **4** recusado pelo portão de CI (só com `EXIGIR_CI_VERDE=1`, passo 5) / **1** outro erro. Rodar de novo é no-op (comprovado: SQLite e PostgreSQL) |
| `entrypoint.sh` | ignorava argumentos | com argumentos roda só o comando: se o Railway passar o pre-deploy ao ENTRYPOINT, migra e **termina** (sem uvicorn preso) |
| `/metrics` | aberto sem token em dev (= produção hoje) | **404 sem `METRICS_TOKEN` em qualquer ENV** |
| `/api/health` | IP/ASN/cidade do robô, páginas de login, agendador | só `status`, `banco`, `versao`, **em qualquer ENV** (também no 503 do banco fora); o resto em `GET /api/v1/sistema/diagnostico` (admin global). `/api/health/live` = `status`, `versao`; `/api/health/ready` = `status`, `banco`, `schema` (ou `motivo` no 503) |
| Boot com `ENV=producao` | recusava `SECRET_KEY` curta ou padrão, SQLite, `ADMIN_GLOBAL_EMAIL` malformado e chave anterior igual à atual | recusa **também** `SECRET_KEY` com um valor de exemplo do repositório (`CHAVES_DE_EXEMPLO`: o padrão do código e os valores que já saíram nos `.env.example` e no `PUBLICAR.md` — a de exemplo tinha exatamente 32 caracteres e passava), `DATA_ENCRYPTION_KEY` ausente (ou só espaços), de exemplo ou igual à `SECRET_KEY`, `CORS_ORIGINS` com `*` e `DOCS_HABILITADOS=true` — tudo numa mensagem só, `Configuração de produção recusada (ENV=producao): ...`, sem o valor de nenhuma variável. A DEK curta continua só aviso (trocá-la exige recifrar). Em dev nada disso recusa: o log do boot escreve `Configuração: o ENV=producao recusaria o boot — ...` para cada item |
| CORS | `http://localhost:5173` e `http://127.0.0.1:5173` (do padrão do código) valiam em qualquer ENV | com `ENV=producao` saem as origens http(s) em `localhost` e subdomínios (`app.localhost`), loopback (`127.0.0.0/8`, `[::1]`) e `0.0.0.0`, e a origem opaca `null` — do padrão e de um `CORS_ORIGINS` explícito —, sem derrubar o boot; as do app desktop (`tauri://localhost`, `http(s)://tauri.localhost`) ficam. Linha INFO no boot: `Configuração: CORS de produção sem as origens de desenvolvimento local (...)` |
| Logs | stderr (Railway = vermelho) e, depois da migração no import, texto em WARNING | stdout, JSON com `level` (`info`/`warn`/`error`) e `message`. A sonda do readiness não gera linha (só a mudança de motivo é logada); `httpx` e `sqlalchemy.engine` ficam em WARNING; `LOG_LEVEL=WARNING` também cala as linhas INFO do Alembic |
| Log do app × token na URL | o `http_acesso` já gravava o modelo da rota, mas o log de erro e o Sentry deixavam o token da vitrine da rede inteiro (`/publico/<token>/<token da rede>`) | o `http_acesso` grava o **modelo** da rota (`/api/v1/publico/{token}/painel`), nunca o caminho; o log de erro e o Sentry passam o caminho por `redigir_caminho` (painel da escola, vitrine da rede e redefinição de senha saem como `<token>`) |
| Linha de acesso do **uvicorn** (`uvicorn.access`, URL crua com a query) | gravada a cada requisição: o comando de partida não tem `--no-access-log` | o `configurar_logging`, no import do app, deixa esse logger sem handler e sem propagar — o mesmo efeito da flag, com o comando de partida de hoje. Funciona porque o uvicorn configura o logging **antes** de importar o app e decide por conexão se grava o acesso. Comprovado localmente com o servidor de verdade (CLI do uvicorn, sem a flag): nenhuma linha leva token nem `?busca=`; o `http_acesso` segue. A flag do passo 0a vira reforço |
| Erro de banco no log e no Sentry | a mensagem da exceção do SQLAlchemy trazia `[parameters: (...)]`: o nome da criança num INSERT de aluno, o termo da busca, o código ou o QR do Quest no caminho de transição — no `erro_nao_tratado` (traceback) e no valor da exceção enviado ao Sentry | `hide_parameters=True` no engine (SQLite e PostgreSQL): a mensagem mantém o SQL e troca os valores por `[SQL parameters hidden ...]`. Não cobre o que o **próprio PostgreSQL** escreve: o `DETAIL: Key (...)=(...)` de uma violação de UNIQUE leva o valor da coluna indexada (nenhum índice único de hoje tem nome de pessoa) |
| Texto da exceção no log (custo) | redigido inteiro, ~0,4 s por MB, com o event loop parado (o `erro_nao_tratado` formata dentro da requisição): um IntegrityError de um INSERT grande segurava o worker | acima de 16.384 caracteres, o texto de cada exceção sai com a **cabeça** e a **cauda** redigidas e o meio como `[... N caracteres omitidos]` (não é redigido nem escrito); até isso, igual a antes. Por traceback, a redação vê no máximo ~132 mil caracteres: quando o texto somado de uma cadeia ou grupo passa disso (várias exceções enormes, ou dezenas de exceções médias), as mais antigas saem só com o tipo e `[texto omitido: limite da redação do traceback]` (frames e elos ficam; um `SyntaxError` omitido perde também as linhas `File ..., line N` do próprio texto). A cadeia comum UniqueViolation → IntegrityError → PendingRollbackError cabe inteira |
| Sentry (com `SENTRY_DSN`) | só o DETAIL do banco saía; o resto do evento ia cru: a mensagem e os argumentos do log, o `extra`, os breadcrumbs, o valor de cada exceção, os cabeçalhos | todo texto do evento passa pela **mesma redação de dado pessoal do log** (também as chaves de dict e o `_meta`), e o fim de um texto que o SDK cortou recua sem deixar pedaço de dado. Custo com teto **por evento** (o hook roda com o event loop parado, inclusive no fim de cada transação amostrada): a redação vê no máximo ~66 mil caracteres (~26 ms); a `description` de um span é cortada em 1.024 como os outros textos, e a mesma consulta repetida é redigida uma vez. O que passa do teto sai como `<omitido>` (o `op` e os tempos do span ficam), nunca cru. O nome da transação de uma rota não casada (404) sai sem host, query e token |

Comprovado localmente (PostgreSQL, processos separados, como o uvicorn): com
`ENV=producao` e o banco uma revisão atrás, o import **não migra**, o banco fica
idêntico e o readiness responde 503 `migracao_pendente`; depois de
`python -m scripts.migrate` num processo, um servidor novo com `ENV=producao` fica
pronto (`em_dia`) sem migrar no import. Testes: `tests/test_health_prontidao.py` e
`tests/test_migracoes_boot.py`; o agendador que não sobe com o schema errado em
`tests/test_boot_schema_errado_agendador.py` (com o processo que segue 503
`reinicio_pendente` depois de a migração ser aplicada por fora); a sonda sem linha de log e
os níveis do `httpx`/Alembic em `tests/test_readiness_sem_ruido.py`; os tokens fora do log
do app, do log do uvicorn (servidor de verdade) e do Sentry, e o nome de criança fora da
exceção de banco, em `tests/test_logs_sem_segredo.py`; o teto do texto da exceção e o
orçamento do traceback em `tests/test_logs_excecao_grande.py`; a redação do Sentry e o
teto por evento (SDK de verdade, transporte em memória) em
`tests/test_sentry_sem_dado_pessoal.py`. A saúde pública mínima com `ENV`
ausente, `dev` e `producao` (e num processo novo com `ENV=producao`) em
`tests/test_health_diagnostico.py`; as recusas do boot de produção e os avisos em dev
(inclusive o processo que não sobe sem DEK, sem mostrar a `SECRET_KEY`, o que não sobe
com as chaves de exemplo, a leitura dos dois `.env.example` — nenhum valor deles passa
pela trava — e o compose que exige as duas chaves) em
`tests/test_config_producao.py`; o CORS por ambiente (com o preflight de `localhost`
negado num processo com `ENV=producao`) em `tests/test_cors.py`.

## 2.1 Lista final das variáveis de produção e a ordem

Nomes e regras; **nenhum valor** vai neste documento. Gere cada chave com
`python -c "import secrets; print(secrets.token_urlsafe(48))"` — uma chamada por chave.

**Obrigatórias** (com `ENV=producao`, o boot recusa sem elas — o deploy reprova e o
anterior segue no ar):

| Variável | Regra | Se faltar ou estiver errada |
|---|---|---|
| `ENV` | `producao` (espaços nas pontas, maiúsculas e acento não contam: `Produção ` vale) | sem ela o app roda em modo **dev**: migra no import e **nenhuma** das recusas abaixo vale (só avisos no log), **exceto** a da `DATABASE_URL` malformada, que recusa em qualquer `ENV`. Um valor que não é nem dev nem produção (`staging`, `prd`) também roda como dev, e o log avisa `ENV com valor não reconhecido` |
| `DATABASE_URL` | PostgreSQL (`postgresql+psycopg://...`) | SQLite: recusa. Malformada (sem o `@` entre senha e host, espaço antes do esquema): recusa em **qualquer** `ENV`, com `DATABASE_URL malformada` e sem mostrar o valor. Senha com caractere especial percent-codificado (`%40`) é aceita e migra |
| `SECRET_KEY` | 32+ caracteres aleatórios, **gerados por você** | padrão do código, valor de exemplo do repositório, curta ou com menos de 32 caracteres além de espaços e quebras de linha: recusa (a de brancos, em dev, fica como está e o log avisa) |
| `DATA_ENCRYPTION_KEY` | 32+ caracteres aleatórios, **diferente** da `SECRET_KEY` | ausente, só espaços, valor de exemplo ou igual à `SECRET_KEY`: recusa. Curta: só aviso |

**Obrigatória para quem coleta métricas:**

| Variável | Regra | Se faltar |
|---|---|---|
| `METRICS_TOKEN` | aleatório longo; o coletor manda `Authorization: Bearer <token>` | `/metrics` responde **404** (fechado) — nada fica público; só não há métricas |

**Ausentes (ou vazias / `false`) em produção:**

| Variável | Por quê |
|---|---|
| `DOCS_HABILITADOS` | `true` recusa o boot (`/docs`, `/redoc` e `/openapi.json` publicam o mapa da API) |
| `CORS_ORIGINS` | opcional na produção: ausente = padrão do código (`www`, `quest` e o app desktop). **No staging é obrigatória** (o front de staging não está no padrão): ver [`docs/STAGING.md`](../STAGING.md) §2b. Se definida: array JSON explícito, **sem `*`** (recusa o boot); `localhost` e subdomínios/`127.0.0.1`/`[::1]`/`0.0.0.0` e `null` saem sozinhas |
| `METRICS_PUBLICO` | opção de desenvolvimento; ignorada em produção. Em modo dev (a produção até o passo 2) ela **abre** o `/metrics`, e o log avisa `METRICS_PUBLICO=true` |
| `SCHEMA_ADIANTE_ACEITO` | só no rollback do §5 (b); remova depois de estabilizar |
| `DATA_ENCRYPTION_KEYS_ANTERIORES`, `CHAVE_CIFRA_LEGADA_ANTERIOR` | só durante uma rotação da cifra (`scripts/recifrar_segredos.py`); igual a uma chave atual recusa o boot |
| `ADMIN_GLOBAL_EMAIL` | vazia, ou UM e-mail válido (malformada recusa o boot) |
| `SYNC_SCHEDULER_FORCAR` | só por decisão do dono (`docs/sync/REATIVAR-AGENDADOR.md`) |

**Operacionais** (não recusam o boot): `SYNC_SCHEDULER_ENABLED` (`false` até a decisão
do dono), `TRUSTED_PROXY_HOPS` (`1`, o edge do Railway), `DADOS_DIR` + volume em `/dados`
(`ARMAZENAMENTO.md`), `SENTRY_DSN` e `SENTRY_ENVIRONMENT` (vazio = o valor do `ENV`),
`PUBLIC_BASE_URL`/`QUEST_BASE_URL` (padrão = domínios de produção) e, se o portão de CI
do passo 5 for ligado, `EXIGIR_CI_VERDE=1` + `GH_TOKEN`.

Tetos de falhas do login do Edu (operacionais; **ausentes = os padrões do código**, só
defina para mudar): `EDU_LOGIN_TETO_IP_FALHAS` (50) e `EDU_LOGIN_TETO_IP_JANELA_S`
(300), `EDU_LOGIN_TETO_GLOBAL_FALHAS` (400) e `EDU_LOGIN_TETO_GLOBAL_JANELA_S` (300).
Teto ≥ 1 e janela de 60 a 3600 s; fora disso o boot recusa (erro de validação da
configuração). Lidas no boot. O teto global trava o login de todas as contas por uma
janela quando atingido: o trade-off e quando subir o valor estão em
[`docs/lgpd/SESSAO-E-MFA.md`](../lgpd/SESSAO-E-MFA.md) §1.1.

`AUTOMACAO_VERIFICAR_NO_BOOT` (operacional, **não definir em produção**; padrão ligado):
o diagnóstico do robô que cada processo roda uma vez no boot, em thread de fundo — GET a
`ipinfo.io`/`ipapi.co` (IP de saída) e o Chromium abrindo as páginas de login, sem
credenciais; o resultado sai no diagnóstico protegido (`GET /api/v1/sistema/diagnostico`).
Ausente (ou vazia, ou fora da lista, com aviso no log) = ligado, o comportamento de
sempre. `false`/`0`/`off` desliga: é o que os testes (`backend/tests/conftest.py`) e o
E2E (`apps/web/playwright*.config.ts`) usam para não sair para a internet a partir do
runner.

`DB_CONNECT_TIMEOUT` (operacional, **não obrigatória**; padrão `10`): prazo, em segundos,
para abrir uma conexão nova com o PostgreSQL — o `connect_timeout` da libpq, que o
engine passa ao psycopg. Sem prazo, um banco que não responde (host fora do ar, rede
parada) prende o worker no handshake pelo padrão do driver (130 s no psycopg 3.2 da
imagem); com ele, a conexão falha em 10 s e o erro aparece (readiness 503, 500 na
requisição) em vez de travar o worker. Não precisa ser definida: ausente vale `10`. `0`
(ou negativo) tira o prazo do app (volta aos 130 s do driver); o driver não aceita menos
de 2 s. Um `?connect_timeout=` escrito na própria `DATABASE_URL` prevalece sobre ela, e a
variável `PGCONNECT_TIMEOUT` da libpq também, quando definida e não vazia no ambiente
(inclusive `0`, que volta aos 130 s do driver). Não afeta o SQLite. Não muda o pool nem
o tempo das consultas (só a abertura da conexão).

**Configuração do serviço no Railway** (não são variáveis):

| Campo | Valor | Passo |
|---|---|---|
| Custom Start Command | `uvicorn app.main:app --host 0.0.0.0 --port 8080 --no-access-log` | 0a |
| Pre-deploy Command | `python -m scripts.migrate` | 1 |
| Pre-deploy Timeout | `300` | 1 |
| Healthcheck Path | `/api/health/ready` (timeout 600 s) — **nunca desligar** | todos |

**Ordem** (cada item é um deploy; confira antes do próximo — detalhes no §3):

1. **0a** — `--no-access-log` no comando de partida.
2. **0** — publicar este código, ainda em modo dev. No log do boot, procure linhas
   `Configuração: o ENV=producao recusaria o boot — ...`: cada uma é uma variável a
   corrigir **antes** do passo 2 (é o mesmo teste que o `ENV=producao` fará).
3. **1** — pre-deploy `python -m scripts.migrate` (ainda em modo dev).
4. **2** — `ENV=producao` (com a `DATA_ENCRYPTION_KEY` própria, sem `DOCS_HABILITADOS`,
   `CORS_ORIGINS` sem `*`).
5. **3** — `METRICS_TOKEN` (e o coletor com o Bearer), se houver coletor.
6. Em todos: healthcheck em `/api/health/ready`.

## 3. Passo a passo (cada passo é um deploy próprio; verifique antes do próximo)

> Regra: **nenhuma migração nova junto de mudança de configuração**. O pacote que traz
> este código traz também **duas** migrações — `0036_rls_todas_as_tabelas` (RLS ENABLE
> nas tabelas que faltavam) e `0037_quest_codigo_hash_limites` (colunas de hash com
> índice único em `quest_credenciais_aluno` — `codigo_login_hash` e, na versão atual
> da 0037, `qr_token_hash` —, backfill dos hashes e a tabela nova
> `quest_limites_acesso`). As duas são aplicadas no passo 0 pelo
> caminho de hoje (modo dev, no import) — veja o rollback (§5) antes.
>
> **Lock no passo 0.** As duas pedem lock exclusivo por um instante (o `ENABLE ROW
> LEVEL SECURITY` de cada tabela; o `ADD COLUMN` + índice da 0037) e desistem em **5 s**
> (`SET LOCAL lock_timeout`). No modo dev o import tenta **uma vez só** — a nova tentativa
> (3×) existe só no `scripts.migrate`. Se um leitor longo segurar a tabela (o `pg_dump`
> do backup diário: o do repositório roda às 06:00 UTC ≈ 03:00 BRT; confira o horário
> do backup do cofre), a transação reverte, o processo não sobe, o healthcheck reprova e
> o deploy anterior segue no ar, sobre a 0035 (a política de reinício do Railway pode
> subir o contêiner de novo dentro da janela do healthcheck; não conte com isso).
> Seguro, mas o passo 0 tem de ser refeito: faça o merge longe do horário dos backups.

### Checklist pré-deploy — contas com senha derivada do nome (só leitura, antes do passo 0)

O código deste pacote faz o login **recusar com 403** a senha da convenção antiga (nome ou
@ + "123": "Senha expirada: peça um link de redefinição ao administrador."), e conta de
**administração global** não tem volta garantida: o `scripts/link_redefinicao.py` recusa
conta global, e pela tela o link dela só sai por outro admin global logado, quando a conta
está vinculada a uma escola. Se uma conta global ainda usar essa senha, ela pode ficar de
fora depois do deploy. Antes do passo 0, confira só as contagens:

    cd backend
    python -m scripts.senhas_derivadas --contagens

- **Só leitura.** Sem `--aplicar` o script nunca grava: no PostgreSQL a transação abre como
  `READ ONLY` (uma escrita no caminho é recusada pelo próprio banco; comprovado em teste
  local contra o PostgreSQL 16 descartável) e termina em rollback. O `--contagens` recusa
  `--aplicar` e `--escola` antes de abrir o banco.
- **Sem dado pessoal na saída.** Só números: nem id, nem nome, nem @, nem e-mail, nem escola.
  A saída pode ir para o chamado ou o chat.
- **Onde rodar.** Num ambiente com `DATABASE_URL` apontando para o banco a conferir — de
  preferência uma cópia restaurada do backup mais recente (não toca produção; o resultado vale
  para a data do backup). Leva alguns minutos: o bcrypt confere cerca de 10 candidatos por conta.

Saída (números fictícios):

    senhas derivadas do nome — só contagens (somente leitura, nada gravado)
    total: 12
    globais: 1
    ativas: 11
    já usadas: 1
    detalhe:
      globais ativas: 1
      globais já usadas: 0
      com escola (alvos do --aplicar): 9
      sem escola (recuperação manual): 2
      nunca usadas: 9
      indeterminadas: 2
      hash não conferível (fora da etapa): 1
    ATENÇÃO: há conta GLOBAL com senha derivada. ...

O que conferir:

1. **`globais: 0`** → segue. Com `globais` acima de 0: troque a senha dessa conta **antes** do
   deploy (o código atual ainda aceita a senha derivada) e rode `--contagens` de novo até
   `globais: 0`. Depois do deploy a saída é manual.
2. **`ativas`** e **`já usadas`** dizem quantas contas recebem o 403 no primeiro login depois do
   deploy (as já usadas são as de quem entra hoje com essa senha). Combine com as escolas quem
   gera os links (Usuários → Redefinir senha). O `--aplicar` do mesmo script continua
   recomendado, só com autorização do dono e backup validado (ver o cabeçalho de
   `backend/scripts/senhas_derivadas.py`): ele também derruba as sessões abertas com a senha
   antiga (valem até 8 h) e cobre nomes e @ antigos que a trava do login não confere.
3. A lista por conta (para quem vai gerar os links) é o diagnóstico **sem** `--contagens`: ele
   mostra id, @ e escola — essa saída não vai para chat.

### Passo 0a — log de acesso do uvicorn (`--no-access-log`), antes do passo 0

**Reforço, e o único fechamento ANTES do passo 0.** A linha de acesso do uvicorn
(logger `uvicorn.access`) grava a URL **crua**, com a query string. Comprovado
localmente (21/10, uvicorn com a configuração de log padrão, a mesma do comando de
partida, e tokens fictícios), com o código do `main` de hoje: `"GET
/api/v1/publico/<token inteiro>/painel HTTP/1.1" 404` e `"GET
/api/v1/auth/redefinir-senha/<token inteiro> HTTP/1.1" 200`, enquanto o `http_acesso`
do app, na mesma requisição, grava só `/api/v1/publico/{token}/painel` e
`/api/v1/auth/redefinir-senha/{token}`. Quem lê o log do Railway abre o telão com
nomes e posições das crianças, ou troca a senha da conta enquanto o link vale. Não é
questão de linha duplicada: é segredo no log.

**Com este código (passo 0) o próprio app desliga essa linha** no import
(`configurar_logging`), com o comando de partida de hoje, sem a flag — comprovado com o
servidor de verdade em `tests/test_logs_sem_segredo.py`, que também cobre o log de
erro e o Sentry. A flag continua valendo a pena: (1) fecha o vazamento **já**, antes de
o passo 0 ir ao ar; (2) cobre um jeito de subir em que o app seja importado ANTES de o
uvicorn configurar o logging (por exemplo um script que faça `uvicorn.run(app)` com o
objeto, não com a string `app.main:app`), em que a configuração do uvicorn viria por
cima da do app.

Rotas da API com segredo ou dado pessoal na URL:

| Rota | O que vai na URL | Quem chama |
|---|---|---|
| `GET /api/v1/publico/{token}/painel` | token do painel público da escola | o telão, de tempos em tempos |
| `GET /api/v1/publico/{token}/alunos/{aluno_id}` | o mesmo token | o perfil público do aluno |
| `GET /api/v1/publico/rede/{token}` | token da vitrine da rede | a vitrine da Secretaria |
| `GET /api/v1/auth/redefinir-senha/{token}` | token do link de redefinição (vale 60 min, uso único) | a tela de redefinição, ao abrir o link |
| `GET /api/v1/escolas/{id}/alunos?busca=…`, `GET /api/v1/escolas/{id}/pesquisa?q=…` | nome (ou pedaço) de aluno digitado na busca | telas de alunos e a pesquisa global |

O token do QR do Quest **não** passa pela URL da API: vai no corpo de `POST
/api/v1/quest/auth/entrar-qr` (o `?qr=` fica na URL do app do Quest). Também ficam
fora da API, e portanto deste passo, as URLs das páginas do site (`/p/<token>`,
`/rede/p/<token>`, `/redefinir-senha?token=…`), que o host do site registra, e o
`access_log` do nginx da imagem web no caminho docker-compose.

1. Serviço do backend → **Custom Start Command**:
   `uvicorn app.main:app --host 0.0.0.0 --port 8080 --no-access-log` → **Deploy**. Só a
   partida muda: o código e o banco são os de hoje (o `entrypoint.sh` da imagem já usa
   a flag).
2. Verificar: `curl -s https://api.constelaedu.com/api/health/live` → 200; e, no log do
   Railway, nenhuma linha `INFO: ... "GET /api/...` nova.
3. Efeito colateral esperado: **até o passo 0** a API fica sem a linha de acesso das
   respostas 2xx/3xx — no código de hoje o `fileConfig` do Alembic baixa a raiz para
   WARNING e o `http_acesso` só aparece para 4xx/5xx; volta inteiro no passo 0. Se
   preferir não ter essa janela, acrescente a flag no mesmo deploy do passo 0 (ela não
   mexe em migração nem no caminho do ENV). Nunca depois. Desfazer: tirar a flag e
   fazer Deploy.

**O que já está gravado.** O Railway guarda as linhas antigas pelo prazo de retenção do
plano, com os tokens inteiros, e nem a flag nem este código as apagam. Feita a troca da
partida (ou publicado o passo 0):

- **Painel público da escola** (nomes de crianças): gerar um endereço novo em Painel
  público → "Gerar novo endereço" (`POST /api/v1/escolas/{id}/painel-publico/novo-token`)
  em cada escola com painel ligado. O link e o QR antigos param na hora: o telão e o QR
  impresso precisam do endereço novo — **quando fazer é decisão do dono**.
- **Vitrine da rede** (só agregado por escola): desligar e religar gera token novo.
- **Links de redefinição**: valem 60 min (`RESET_SENHA_EXPIRA_MIN`) e são de uso
  único, então os que estão no log já venceram — nada a fazer, salvo se
  `RESET_SENHA_EXPIRA_MIN` tiver sido aumentado no Railway. Nesse caso, gerar um link
  novo para a pessoa invalida os pendentes dela (só o mais novo vale).

### Passo 0 — publicar este código, sem mexer no Railway

1. Merge no `main` (o Railway faz o deploy sozinho, ainda em modo dev).
2. Verificar (sem login):
   - `curl -s https://api.constelaedu.com/api/health/ready` →
     `{"status":"ok","banco":"ok","schema":"em_dia"}`
   - `curl -s https://api.constelaedu.com/api/health` → só `status`, `banco`, `versao`
   - `curl -s -o /dev/null -w "%{http_code}\n" https://api.constelaedu.com/metrics` → `404`
   - `curl -sI https://api.constelaedu.com/api/health/live` → `x-frame-options: DENY`,
     `x-content-type-options: nosniff` e, esperado, `strict-transport-security:
     max-age=31536000` (o HSTS sai quando o proxy do Railway manda
     `X-Forwarded-Proto: https`; se não vier, ele aparece no passo 2, com o ENV)
   - Logs do Railway: linhas JSON com `"level":"info"` aparecem como **info** (não
     vermelhas); o filtro `@level:error` traz só erros de verdade.
3. Se algum coletor externo lia `/metrics`, ele passa a receber 404: defina
   `METRICS_TOKEN` (passo 3) e configure o coletor com `Authorization: Bearer <token>`.
4. Esperado nos logs: o log de acesso JSON (`"message":"http_acesso"`, com o modelo da
   rota, status, duração, usuário e escola) passa a aparecer também para 2xx/3xx —
   antes ele sumia porque o `fileConfig` do Alembic baixava a raiz para WARNING.
   **Nenhuma** linha `INFO: ... "GET /api/...` do uvicorn aparece, com ou sem a flag do
   passo 0a (o app desliga a linha de acesso dele no import). Se aparecer, o app está
   sendo importado fora da ordem esperada (ver o passo 0a): ponha a flag já e investigue
   o comando de partida.
5. Esperado também: as sondas do healthcheck (`/api/health/ready`) **não** geram linha
   de log. A prontidão escreve `Schema em dia` uma vez, no boot, e de novo só se o
   motivo mudar. As linhas do Alembic (`Running upgrade ...`, `Context impl ...`,
   `0036: ...`, `0037: ...`) aparecem só na migração do boot.
6. **Pré-checagem do passo 2:** no log do boot, as linhas `Configuração: o ENV=producao
   recusaria o boot — ...` (nível warn) dizem o que o `ENV=producao` vai recusar — por
   exemplo `DATA_ENCRYPTION_KEY ausente`, `DATA_ENCRYPTION_KEY de exemplo` ou
   `DOCS_HABILITADOS=true`. Corrija cada uma (variável no painel → Deploy) até o boot não
   escrever nenhuma. Também em `Configuração: ...`, sem o "recusaria": `ENV com valor não
   reconhecido` (o app roda como dev, sem as travas) e `METRICS_PUBLICO=true` (o `/metrics`
   está aberto sem token) — corrija já. As linhas `Cifra em repouso: ...` vêm da cifra:
   a DEK vazia ou igual à `SECRET_KEY` aparece ali **e** como `Configuração: ...` (essa
   recusa o passo 2); só a DEK curta, a DEK com vírgula (na rotação ela não cabe em
   `DATA_ENCRYPTION_KEYS_ANTERIORES`) e as chaves anteriores ainda configuradas são
   avisos que não recusam o boot.

### Passo 1 — pre-deploy, ainda em modo dev

1. No serviço do backend, campo **Pre-deploy Command**: `python -m scripts.migrate`.
2. **Pre-deploy Timeout**: `300` (o campo aparece depois de preencher o comando).
   Obrigatório: sem ele o pre-deploy não tem prazo (doc do Railway).
3. Não mude o comando de partida nem o ENV. Faça um **Deploy** normal do mesmo código.
4. Verificar no log do **pre-deploy**: `Antes: schema em_dia ...`, `Depois: schema em_dia
   ...`, `Migração concluída.`, e o deploy ativo. Se aparecer `Uvicorn running` no log do
   pre-deploy, a imagem é anterior a este código (entrypoint sem argumentos): limpe o
   pre-deploy e volte ao passo 0.

Fatos do Railway (doc pública): o pre-deploy roda num contêiner **separado**, com as
variáveis do serviço e a rede privada, **sem volumes**; saída ≠ 0 = o deploy **não
segue**, sem nova tentativa. O que a doc NÃO diz: se o comando substitui o ENTRYPOINT ou
é passado a ele (coberto pelo `entrypoint.sh` novo) e se o rollback reroda o pre-deploy
(HIPÓTESE do fórum: reroda).

### Passo 2 — `ENV=producao`

Antes, confira no painel (sem copiar valores) — a lista completa está no §2.1; qualquer
item abaixo errado faz o app recusar subir (o deploy reprova e o anterior segue; seguro,
mas trava o passo). O atalho é a pré-checagem do passo 0 (item 6): sem nenhuma linha
`o ENV=producao recusaria o boot` no log do deploy atual, só sobram os itens de
`SECRET_KEY`, `DATABASE_URL` e `ADMIN_GLOBAL_EMAIL`, que o modo dev não confere do mesmo
jeito:

- `SECRET_KEY` com **32+ caracteres** e gerada por você, nunca um valor de exemplo do
  repositório (em modo dev, uma curta ou de exemplo é trocada por uma aleatória efêmera
  — as sessões caem a cada reinício —; em produção, recusa);
- `DATA_ENCRYPTION_KEY` definida e **diferente** da `SECRET_KEY`. Se não existir, crie
  uma chave nova: o que já está cifrado com a `SECRET_KEY` continua legível (a
  `SECRET_KEY` segue no anel só para decifrar) e o que for cifrado depois usa a DEK;
- `DOCS_HABILITADOS` ausente (ou `false`);
- `CORS_ORIGINS` ausente (padrão do código) ou um array JSON sem `*`;
- `DATABASE_URL` é PostgreSQL (SQLite é recusado em produção);
- `ADMIN_GLOBAL_EMAIL` vazio ou com UM e-mail válido (malformado = recusa subir);
- Sentry: a etiqueta `environment` passa de `dev` para `producao`. Ajuste alertas/filtros
  presos a `dev`, ou defina `SENTRY_ENVIRONMENT` de propósito.

Então: variável `ENV=producao` → **Deploy** (não "Alt+Deploy"). O pre-deploy
(`scripts.migrate`) lê as mesmas variáveis e recusa do mesmo jeito: se o log do
pre-deploy mostrar `Configuração de produção recusada (ENV=producao): ...`, corrija o que
a mensagem lista e faça novo Deploy.

Verificar: no log do app, **nenhum** `Running upgrade` no boot e a linha `Schema em dia`;
nenhuma linha `o ENV=producao recusaria o boot`; com o CORS padrão, a linha INFO
`Configuração: CORS de produção sem as origens de desenvolvimento local
(http://localhost:5173, http://127.0.0.1:5173)`; `/api/health/ready` com
`"schema":"em_dia"`; `/api/health` só com `status`, `banco`, `versao`; `/metrics` 404;
`/docs` 404. Opcional, o CORS: `curl -s -o /dev/null -D - -X OPTIONS
https://api.constelaedu.com/api/v1/auth/login -H "Origin: http://localhost:5173" -H
"Access-Control-Request-Method: POST"` → **sem** `access-control-allow-origin`; com
`Origin: https://www.constelaedu.com` → com.

O que o ENV muda, além da migração no import: recusa `SECRET_KEY` fraca ou de exemplo,
SQLite, `ADMIN_GLOBAL_EMAIL` inválido, chave anterior igual à atual,
`DATA_ENCRYPTION_KEY` ausente, de exemplo ou igual à `SECRET_KEY`, `CORS_ORIGINS` com
`*` e `DOCS_HABILITADOS=true`; tira do CORS as origens de desenvolvimento local e a
`null`; HSTS em toda resposta; a opção de
desenvolvimento `METRICS_PUBLICO` deixa de valer; etiqueta do Sentry. O ENV **não** mexe
na saúde pública (mínima em qualquer ENV), no `/metrics` (404 sem token em qualquer ENV),
no agendador (continua desligado), no robô nem nos workers.

### Passo 3 — `METRICS_TOKEN` (obrigatório se houver coletor de métricas)

Sem ele o `/metrics` fica fechado (404) e nada vaza; com ele, só o coletor que manda o
Bearer lê. Gere um valor (`python -c "import secrets; print(secrets.token_urlsafe(48))"`),
grave como variável e faça Deploy. Validar:

- `curl -s -o /dev/null -w "%{http_code}\n" https://api.constelaedu.com/metrics` → `401`
- com `-H "Authorization: Bearer <token>"` → `200` e o texto Prometheus.

### Passo 4 — deploys seguintes (rotina)

Push no `main` → build → **pre-deploy migra** (o deploy antigo segue servindo) → app
novo sobe sem migrar → healthcheck `ready` 200 → tráfego troca. Se a migração falhar, o
deploy não segue e o antigo continua no ar, sobre o schema antigo (a transação
reverte). Se o lock de tabela não sair em 5 s (`lock_timeout`), o migrate tenta 3 vezes
e sai com 2: refaça o deploy num horário de menos uso.

**Migrações precisam ser aditivas** (expand/contract): durante a troca, o código antigo
serve sobre o schema novo. Renomear/apagar coluna vai em dois deploys separados.

### Passo 5 — publicar só com o CI verde (configuração do dono)

Hoje nada impede publicar com teste reprovado: o `main` **não tem proteção** (nem
ruleset), e o Railway e a Vercel publicam a cada push no `main`, sem olhar o CI. Foi o
que aconteceu com o `34f1a23`: está no ar com o CI reprovado (pytest com erro de coleta,
ruff e E2E). O `deploy.yml` não participa disso — ele é manual, está dormente
(`DEPLOY_ENABLED` não existe) e recusa publicar sem o CI do push no `main` verde para
aquele commit (job `ci-verde`). Para o caminho real:

1. **GitHub → Settings → Rules → Rulesets → New ruleset → Import** o arquivo
   `.github/rulesets/protecao-main.json` (ou o `gh api … rulesets --method POST` de
   `docs/CI-CD.md`). Ele exige PR, **todos** os jobs do `CI` e do `Segurança` como
   checks obrigatórios (o teste `test_workflows_deploy.py` reprova se um job ficar de
   fora) e o ramo **atualizado** antes do merge — sem isso, o check de um PR vale para
   o merge de teste com uma base antiga, não para o commit que entra no `main`.
2. **Railway — em TODOS os serviços ligados a este repositório, não só no
   `@constela/backend`.** O GitHub registra quatro integrações Railway publicando a
   partir dele (Environments `constela EDU / production`, `adequate-benevolence /
   production`, `mellow-youthfulness / production` e `refreshing-adventure /
   production`; um deles já publicou o web a cada push). Em cada serviço que publica a
   partir do `main`: **Settings → "Wait for CI"** ligado, ou o repositório
   desconectado. O "Wait for CI" espera **todos** os workflows do commit — o `CI` e
   também o `Segurança` —, então os dois precisam estar verdes. **Limite documentado
   pelo Railway:** um workflow CANCELADO só bloqueia o deploy se nenhum outro workflow
   do mesmo commit passou — com o `Segurança` verde, um `CI` cancelado (à mão, ou por
   concorrência) é ignorado e o commit é publicado, inclusive com o migrate do
   Pre-deploy. Por isso:
3. **Railway — portão de CI no Pre-deploy (recomendado)**, no serviço do backend, sem
   mudar o comando do passo 1 (continua `python -m scripts.migrate`): crie as variáveis
   - `EXIGIR_CI_VERDE=1` — o migrate consulta o CI (`scripts/exigir_ci_verde.py`) ANTES
     de tocar no banco e sai com **4** se o `CI` do push no `main` do commit do deploy
     (`RAILWAY_GIT_COMMIT_SHA`) não estiver `completed/success` — cancelado,
     reprovado, em andamento ou ausente; aí o deploy não segue e o anterior continua no
     ar;
   - `GH_TOKEN` — **obrigatório**, mesmo com o repositório público: sem token, o
     limite do GitHub é de 60 consultas por hora **por IP**, e o IP de saída do Railway
     é compartilhado com outros clientes (um 403/429 recusaria um deploy com o CI
     verde). Use um token fine-grained só deste repositório, com leitura de Actions;
     anote a data de expiração — vencido, o GitHub responde 401 e TODO deploy é
     recusado.

   **Não use `a && b` no Pre-deploy:** o Railway roda o Pre-deploy de um serviço com
   Dockerfile sem shell, e o `&&` chegaria ao Python como argumento (o segundo comando
   nunca rodaria; o portão recusa argumentos por isso). Depois de criar as variáveis,
   faça um Deploy e confira no log do Pre-deploy, nesta ordem: `CI do push no main para
   o commit …: completed/success`, depois `Antes:`, `Depois:` e `Migração concluída.`.
   O portão recusa também um `railway up` (que não traz o commit) e falha fechado se a
   API do GitHub estiver fora do ar. **Emergência:** apague `EXIGIR_CI_VERDE` e aplique
   a mudança com um deploy NOVO (o *Deploy* das mudanças pendentes, ou um commit no
   `main` pelo fluxo normal) — decisão consciente, registrada. **Rollback e Redeploy
   não servem para isso:** o Railway os refaz com as variáveis gravadas NAQUELE deploy,
   então a variável apagada ou um `GH_TOKEN` trocado não chegam a eles. Pelo mesmo
   motivo, prefira um token de validade longa: cada troca invalida o Rollback para
   todos os deploys anteriores (vão com o token velho). Um Rollback para uma imagem
   que já tem o portão exige o CI verde daquele commit; para uma imagem anterior a
   ele, a variável é ignorada. **Com o portão ligado, o `deploy.yml` não publica o
   backend** (ele usa `railway up`): o deploy manual do backend passa a ser o *Deploy*
   do commit pelo próprio Railway. O web, em job separado, continua publicando por
   ele.
4. **Vercel → Project → Settings**: exigir os checks do GitHub antes de promover para
   produção (Deployment Checks), ou tirar a publicação automática do `main` e usar o
   `deploy.yml` (jobs `staging-web`/`producao-web`, separados dos do backend), que já
   tem o portão `ci-verde`.
5. **Se o `deploy.yml` for ligado** (`DEPLOY_ENABLED=true`): criar os Environments
   `staging` e `producao` com *Deployment branches and tags: main* (e *Required
   reviewers* no `producao`) e guardar `RAILWAY_TOKEN`, `RAILWAY_SERVICE_*` e `VERCEL_*`
   **somente como Environment secrets** de cada um — nenhum em *Repository secrets* ou
   *Organization secrets* (apague as cópias se existirem). Um "Run workflow" num ramo
   roda o `deploy.yml` daquele ramo, que pode ter o portão removido; a regra de ramos
   do Environment só o barra se os segredos forem do Environment: um segredo de
   repositório é lido por qualquer job de qualquer ramo, com ou sem Environment.

A concorrência do `CI` não cancela mais nada no `main` (cada run tem o seu grupo): com
o grupo por ramo, dois pushes seguidos cancelavam o CI do primeiro. Um cancelamento à
mão continua possível — só o portão do item 3 o barra no caminho real.

Os passos 1 e 2 só funcionam depois que o `CI` e o `Segurança` do `main` estiverem
verdes; antes disso, bloqueiam todo deploy. O candidato `rc/auditoria-2026-10-20`
corrige as reprovações do `CI` de hoje, conferidas localmente job a job (o build
das imagens Docker e o Trivy não rodam nesta máquina).

## 4. Riscos

- **Se o ENV mudar antes do pre-deploy, as migrações param.** Com este código, o
  próximo deploy que trouxer migração **reprova no healthcheck** (`migracao_pendente`)
  em vez de servir quebrado — seguro, mas bloqueado até configurar o pre-deploy (passo 1)
  e fazer novo Deploy. O mesmo vale se alguém **apagar** o pre-deploy um dia.
- **Migrar na mão não salva o deploy que já subiu com o schema errado.** O processo que
  bootou com `migracao_pendente` (ou `schema_adiante`) pulou o agendador, os ajustes de
  dados e a liberação de órfãs, e fica 503 `reinicio_pendente` até um boot novo, mesmo
  com o schema já em dia. Depois de migrar, faça um **Deploy** novo (ou Restart). O 503
  só segura o tráfego enquanto o Railway consulta o healthcheck, ou seja, na ativação
  do deploy (HIPÓTESE pela doc pública, a conferir): um contêiner do deployment JÁ ativo
  que reinicie sobre o schema errado serve sem agendador até o próximo boot — o
  `GET /api/v1/sistema/diagnostico` mostra `scheduler_sync` com `habilitado` true e
  `ativo` false, e `schema.motivo`.
- Healthcheck desligado: sem ele o Railway ativa o deploy assim que o contêiner sobe e
  a proteção do readiness não vale. Mantenha `/api/health/ready`.
- **Configuração recusada no passo 2** (DEK, CORS, `/docs` ou as recusas antigas): o
  processo não importa, o pre-deploy sai com erro e o deploy não segue — o anterior
  continua no ar, em modo dev. Seguro, mas o passo fica travado até corrigir a variável
  que a mensagem lista (ela nunca traz o valor). A pré-checagem do passo 0 evita a
  surpresa.
- **Criar a DEK agora e trocar a `SECRET_KEY` depois** (rotação do incidente): o que foi
  cifrado com a `SECRET_KEY` antes da DEK só abre com ela. Na troca, guarde a antiga em
  `CHAVE_CIFRA_LEGADA_ANTERIOR` e rode `python -m scripts.recifrar_segredos` antes de
  apagá-la (sequência no próprio script).
- **`docker compose`** (caminho alternativo, já com `ENV=producao`): o `.env.example` da
  raiz traz `SECRET_KEY` e `DATA_ENCRYPTION_KEY` **vazias**, e o compose (`${VAR:?}`) não
  sobe sem as duas. Antes, `cp .env.example .env && docker compose up -d` subia a
  produção com as chaves de exemplo, públicas no repositório (token de admin forjável,
  credenciais das escolas decifráveis); se o valor de exemplo for colado de volta, o boot
  recusa. `POSTGRES_PASSWORD` só com letras e dígitos (vai crua na `DATABASE_URL` do
  compose): o compose não percent-codifica a senha, então um `%41` é lido como `A` (outra
  senha, em silêncio) e um `@` desloca o host.
- **Se a produção de hoje usar uma chave de exemplo** (NÃO verificado — sem acesso ao
  painel): com este código, mesmo em modo dev, a `SECRET_KEY` de exemplo vira a efêmera
  (as sessões caem a cada reinício e as cifras legadas, feitas com ela, ficam ilegíveis
  até a rotação) e a DEK de exemplo vira aviso no log do passo 0. Nos dois casos a chave
  é pública: trate como a rotação do incidente (chave nova; a antiga em
  `CHAVE_CIFRA_LEGADA_ANTERIOR` ou `DATA_ENCRYPTION_KEYS_ANTERIORES` só até o
  `recifrar_segredos --executar`).
- `WEB_CONCURRENCY` > 1 ou mais de uma réplica em modo dev: as migrações no import agora
  se enfileiram pelo advisory lock (PostgreSQL), mas o caminho certo é o pre-deploy.
- O pre-deploy também roda os ajustes de dados idempotentes (`garantir_dados_base`:
  purga de retenção da IA, código das faixas, promoção do admin global). Ficam gravados
  mesmo que o app novo reprove depois — são os mesmos de qualquer boot de hoje.
- Um deploy com volume anexado tem um pequeno downtime (doc do Railway) — ver
  `ARMAZENAMENTO.md`.

## 5. Rollback

- **Desfazer o passo 2:** apagar `ENV` → Deploy. O boot volta a migrar no import
  (no-op, o banco está em dia).
- **Desfazer o passo 1:** limpar o Pre-deploy Command → Deploy **novo** (um Rollback
  pode restaurar a configuração da época do deployment — HIPÓTESE).
- **Rollback de código SEM migração no meio:** "Rollback" do Railway normal.
- **Rollback de código ATRAVESSANDO uma migração** (o banco já está numa revisão que o
  código antigo não conhece):
  - código antigo **anterior a este branch**, em modo dev: o import quebra
    (`Can't locate revision`) → com healthcheck o rollback falha e o atual segue;
  - código antigo **com este branch**, `ENV=producao`: o pre-deploy antigo sai com 3
    (`RECUSADO`) e, se o app subir, o readiness dá 503 `schema_adiante` → o rollback falha
    com segurança;
  - para voltar de fato: (a) **descer o schema com o código NOVO**
    (`alembic downgrade <revisão anterior>`, pela máquina do dono com a `DATABASE_URL` de
    produção — perde o que a migração criou; faça backup avulso antes) e então o Rollback;
    ou (b) se a migração for aditiva e o código antigo tiver este branch: um **Deploy
    novo** do código antigo (commit de revert) com `SCHEMA_ADIANTE_ACEITO=<id exato da
    revisão>` — o pre-deploy sai com 0 **sem migrar** (o schema não muda), mas roda os
    ajustes de dados idempotentes de todo boot (`garantir_dados_base`: código das faixas,
    promoção do admin global, purga de retenção da IA — ver §4); o boot do app também os
    roda, porque `adiante_aceito` não conta como schema errado, e o agendador sobe se
    estiver ligado. O readiness fica `adiante_aceito`. Remova a variável depois de
    estabilizar.
  - **Voltar do passo 0 para o `main` de hoje (0035, o 34f1a23 em produção).** O código
    de hoje é anterior a este branch: o caminho (b) não existe para ele, só o (a),
    descendo **quatro** revisões (0039 → 0038 → 0037 → 0036) —
    `alembic downgrade 0035_resultados_escolas`, com o código NOVO e **backup avulso
    antes** (o 34f1a23 em modo dev nem importa com o banco na 0039:
    `Can't locate revision '0039_execucao_contabilidade'`). O que a descida faz:
    - `0039_execucao_contabilidade` → **apaga** as 5 colunas novas de
      `sincronizacao_execucoes` (`qtd_linhas`, `qtd_em_revisao`, `qtd_falhas`,
      `recalculo_pendente`, `motivo`); as linhas ficam. Depois da descida o código antigo
      não conhece os estados `parcial` e `sem_atualizacao` gravados pelo novo: no
      histórico e no "último sucesso" do antigo, essas execuções são ignoradas (a tela
      antiga as mostra como "Sem dados ainda");
    - `0038_revogar_papeis_da_api` → **não devolve** os privilégios de `anon` e
      `authenticated` (de propósito: devolver reabriria as tabelas à API); só muda a
      `alembic_version`. O código antigo não usa esses papéis;
    - `0037_quest_codigo_hash_limites` → **apaga** a tabela `quest_limites_acesso` (os
      contadores e bloqueios temporários de tentativa de login do Quest — e também os
      tetos de falhas do login do Edu, dimensões `edu_login_ip_falha` e
      `edu_login_global_falha`: derrubar a tabela os zera, inclusive um bloqueio em
      curso) e as colunas de hash com os índices (`codigo_login_hash`,
      `qr_token_hash`). Nenhum cartão deixa de
      entrar: o código e o token do QR em texto continuam em `codigo_login`/`qr_token`,
      que é o que o código antigo usa, e uma nova subida refaz os hashes pelo backfill;
    - `0036_rls_todas_as_tabelas` → não desliga o RLS (de propósito): só muda a
      `alembic_version`. O código antigo não é afetado (o backend é o dono das tabelas).
- **Web e API na MESMA janela (sincronização, etapa 2).** O web do 34f1a23 não conhece
  os estados `parcial` e `sem_atualizacao`: com a API nova, ele mostra uma integração
  saudável ("nada mudou", o resultado mais comum) como "Sem dados ainda". Publique o
  web junto com a API e force a atualização do service worker (PWA) — quem estiver com
  o bundle antigo em cache vê o estado errado até recarregar. O web novo contra a API
  antiga degrada bem (os campos novos são opcionais).

## 6. Onde está cada coisa no código

- `app/core/prontidao.py` — regra do readiness (em_dia / migracao_pendente /
  schema_adiante / adiante_aceito / adiante_apos_boot / reinicio_pendente).
- `app/core/observabilidade.py` — `configurar_logging` (JSON no stdout, linha de acesso
  do uvicorn desligada) e o higienizador de eventos do Sentry.
- `app/core/database.py` — `opcoes_do_engine` (pool e `hide_parameters`) e
  `argumentos_de_conexao_pg` (`connect_timeout` do PostgreSQL, de `DB_CONNECT_TIMEOUT`).
- `app/core/migracoes.py` — `estado_do_schema`, advisory lock (namespace 4714),
  `SchemaAdianteDoCodigo`.
- `scripts/migrate.py` — pre-deploy; códigos de saída.
- `app/core/config.py` — `ENV`, `MIGRACAO_LOCK_TIMEOUT` (5s), `MIGRACAO_ESPERA_VEZ`
  (120s), `MIGRACAO_TENTATIVAS` (3), `MIGRACAO_PAUSA_S` (5), `SCHEMA_ADIANTE_ACEITO`,
  `METRICS_TOKEN`, `METRICS_PUBLICO`; o ENV reconhecido (`normalizar_env`,
  `ENV_DE_PRODUCAO`, `ENV_DE_DESENVOLVIMENTO`); as chaves de exemplo
  (`CHAVES_DE_EXEMPLO`, `chave_de_exemplo` — um valor de exemplo novo num `.env.example`
  tem de entrar ali); as recusas do boot de produção
  (`_validar_producao`, `riscos_de_producao`), os avisos em dev
  (`avisos_de_configuracao`/`registrar_avisos_de_configuracao`, chamado no import de
  `app/main.py`) e o CORS por ambiente (`origem_de_desenvolvimento`,
  `_cors_por_ambiente`, `CORS_ORIGINS_REMOVIDAS`).
- `app/main.py` — `/api/health`, `/api/health/live`, `/api/health/ready` e `/metrics`.
- `GET /api/v1/sistema/diagnostico` (admin global) — schema (revisões banco × código),
  robô, agendador, métricas e armazenamento.
