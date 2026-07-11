# Módulo de Sincronização Automática de Plataformas

Automatiza a **obtenção** dos relatórios das plataformas externas (Matific,
Elefante Letrado, …) e os entrega ao **pipeline de importação já existente**
(`analisar → confirmar → snapshot → scoring → ranking → Quest → medalhas`). O
upload manual **continua intacto** como fallback (`ConectorManual`).

Requisito aprovado do projeto: o sistema já nasce preparado para sincronização
automática; quando não há API oficial, usa **conectores baseados em Playwright**;
tudo desacoplado por interface para trocar Playwright por API oficial no futuro
**sem alterar o restante do sistema**.

## Arquitetura (camadas desacopladas — `backend/app/sync/`)

```
interfaces.py     Conector (ABC) + DTOs + Estrategia   ← a fronteira que desacopla tudo
vault.py          Cofre de credenciais cifradas (Fernet)
connectors/
  __init__.py     Registro plugável (registrar/obter/listar)
  manual.py       Fallback (upload manual) como conector de 1ª classe
  navegador.py    Abstração `Navegador` (Protocol) + Playwright (import TARDIO)
  base.py         Ciclo de vida do navegador + template de login
  matific.py      Conector Matific   (Estrategia.NAVEGADOR)
  elefante.py     Conector Elefante  (Estrategia.NAVEGADOR)
orchestrator.py   Cola conector → pipeline de importação EXISTENTE
service.py        Motor: fila, ciclo de vida, retries/backoff, logs, alertas, agenda
scheduler.py      Worker (thread de fundo) — varre agenda + fila
router.py         API do painel (por-escola) + dashboard global
schemas.py        Contratos Pydantic da API
models →  app/models/sincronizacao.py   (5 tabelas; migrations 0007 + 0008)
frontend → apps/web/src/pages/Sincronizacao.tsx  (painel administrativo)
           apps/web/src/pages/Comecar.tsx        (assistente de onboarding)
           apps/web/src/components/CredenciaisForm.tsx (form de credencial reusável)
```

### Fluxo de uma sincronização
1. **Scheduler** (agenda vencida) ou **botão** (manual) enfileira uma
   `SincronizacaoExecucao` (`fila`).
2. **Worker** faz *claim atômico* (`UPDATE … WHERE status='fila'`) — só um
   worker/réplica pega cada execução.
3. **Conector** autentica e baixa os relatórios (`ArquivoObtido` = bytes iguais
   a um upload manual). Logs por etapa; senha nunca logada.
4. **Orquestrador** entrega cada arquivo ao `confirmar` existente → parser,
   casamento de nomes, snapshot imutável, `scoring.recalcular_escola`
   (atualiza notas, rankings, Quest, medalhas, painel público, push).
5. **Execução** guarda contadores, duração, versão do parser/conector e o link
   para a `Importacao`. Sucesso fecha alertas; falha abre alerta e re-enfileira
   com backoff se recuperável.

## Decisões arquiteturais (justificativas)

- **Conector por interface + registro** — adicionar plataforma = criar um
  conector e registrá-lo; nada mais no sistema muda. `Estrategia` +
  `justificativa` de cada conector documentam a escolha técnica.
- **Playwright atrás de `Navegador` (Protocol) com import TARDIO** — o app sobe
  e os testes rodam **sem** o pacote nem contas; só o login real o exige. Todo o
  fluxo (login → localizar → baixar) é exercitado com `NavegadorFake`. Trocar
  por API oficial = novo conector `Estrategia.API_OFICIAL`, sem tocar no núcleo.
- **Orquestrador reusa `confirmar` sem refatorá-lo** — reaproveita 100% do
  pipeline (parser, snapshots, scoring, Quest), **zero risco de regressão**. A
  auditoria "manual × scheduler" vive em `SincronizacaoExecucao`.
- **Cofre Fernet + `token_version`** — segredo só cifrado no banco (chave deriva
  da `SECRET_KEY`, fora do banco). `Credenciais.__repr__` mascara; nada de senha
  em log (testado). Rotação futura já modelada.
- **Fila em banco + claim atômico** — seguro com vários workers uvicorn/réplicas
  (o mesmo código roda como serviço separado para escalar; a fila é a verdade).
- **Scheduler fail-safe** — `SYNC_SCHEDULER_ENABLED` desligado por padrão.

## Modelo de dados (migration `0007`)
`plataforma_credenciais` (cofre), `sincronizacao_config` (agenda),
`sincronizacao_execucoes` (histórico **permanente**), `sincronizacao_logs`
(logs por etapa, pesquisáveis), `sincronizacao_alertas` (alertas acionáveis).
Todas isoladas por `escola_id`.

## Como estender

**Nova plataforma:** criar `app/sync/connectors/<nome>.py` com uma subclasse de
`Conector` (ou `ConectorNavegador`), definindo `plataforma`, `estrategia`,
`justificativa` e os métodos; registrar em `connectors/__init__.py`. Fim — o
painel, o scheduler e o orquestrador a descobrem sozinhos.

**Trocar Playwright por API oficial (ex.: Matific liberar feed):** criar
`ConectorMatificAPI(Estrategia.API_OFICIAL)` implementando os mesmos métodos via
HTTP; registrar no lugar do de navegador. Nenhuma outra parte muda.

**Pontos de extensão (só verificáveis com conta real):** as constantes
`_URL_*`/`_SEL_*` em `matific.py`/`elefante.py` são o "contrato de UI" com cada
plataforma. Se a página mudar, ajusta-se **ali** (não no núcleo); o sistema abre
alerta `parser_incompativel`/`falha_auth` para o admin quando o login não
confirma.

## Operação e produção
- **Habilitar automação:** no servidor, `SYNC_SCHEDULER_ENABLED=true`, instalar
  `playwright` + `playwright install chromium`. Configurar credenciais por
  escola no painel (valida na hora). Sem isso, o módulo é inócuo (só manual).
- **Config** (env): `SYNC_WORKERS`, `SYNC_POLL_S`, `SYNC_MAX_TENTATIVAS`,
  `SYNC_BACKOFF_BASE_S`, `SYNC_TIMEOUT_S`, `SYNC_LENTO_S`, `SYNC_TRAVADA_S`
  (janela do reaper de execuções órfãs).
- **Recuperação:** retries com backoff exponencial até `SYNC_MAX_TENTATIVAS`;
  idempotência de fila em DUAS camadas (fast-path + **índice único parcial**
  `uq_sync_exec_ativa` na migration `0008` — o banco recusa uma segunda execução
  `fila`/`executando` por escola+plataforma, mesmo sob workers/réplicas
  concorrentes); claim atômico da fila e da agenda; o pipeline já é idempotente
  para Matific por período/leituras **e** para reimportações do MESMO dia (o
  snapshot do dia é atualizado no lugar, não empilhado — `_mesmo_dia` em
  `routers/importacoes.py`), preservando a semântica COMPLEMENTAR: o relatório
  mais recente é autoritativo para os campos que traz, e os ausentes herdam o
  valor anterior (o PDF de estrelas e o Excel por turma se completam).
- **Retomada após crash (reaper):** um worker morto/redeploy no meio deixa a
  execução presa em `executando`; como o índice de exclusão mútua a trata como
  ativa, a escola ficaria travada. `recuperar_execucoes_travadas` (chamada no
  início de cada rodada do scheduler) e a **auto-cura no `enfileirar`** detectam
  execuções `executando` com `iniciada_em` além de `SYNC_TRAVADA_S` (30 min),
  finalizam-nas como `erro` (claim atômico) e **re-enfileiram** uma nova
  tentativa. Se o `enfileirar` perde a corrida do claim para o reaper
  concorrente, ele **re-checa** o estado (em vez de devolver a órfã morta) e
  cria a execução pedida — o clique nunca some. Assim o botão "Sincronizar" e a
  agenda voltam a funcionar sozinhos, sem intervenção no banco — testado
  (`test_reaper_*`, `test_enfileirar_auto_cura`, `test_enfileirar_perde_corrida_do_reaper`).
- **Alertas automáticos:** senha inválida/expirada, falha de autenticação/
  download, timeout, plataforma indisponível, parser incompatível, sincronização
  lenta.

## Segurança / LGPD
- Credenciais **cifradas** (Fernet), isoladas por escola, nunca devolvidas ao
  navegador nem escritas em log.
- Painel exige **admin/coordenador**; o dashboard cross-escola exige usuário
  **global**; todas as consultas filtram por `escola_id` (isolamento explícito).
- Histórico **permanente** (nunca apagado) e logs de auditoria.

## API (resumo)
Por escola (`/escolas/{escola_id}/sync`): `GET /status` (inclui
`lista_piloto_importada` / `integracao_configurada` do onboarding e, por
plataforma, `cadencia`/`hora_local`/`dia_semana`), `PUT|POST|DELETE
/credenciais/{plataforma}[/testar]`, `PUT /config/{plataforma}`, `POST /agora`,
`GET /historico`, `GET /execucoes/{id}`, `GET /logs`, `GET /alertas`,
`POST /alertas/{id}/resolver`. Global: `GET /sync/dashboard`.

> **`/agora` é a ação única.** Sincronizar já é reprocessar (obtém e importa de
> novo); a idempotência do pipeline garante que reexecutar não duplica dados,
> então não existe um `/reprocessar` separado — evita dois endpoints idênticos.

## Onboarding — assistente "Comece aqui" (`/comecar`)
Fluxo ÚNICO que leva a escola do zero ao ar em poucos minutos, reaproveitando os
componentes existentes (só orquestra os passos):
**Escola → Turmas e alunos (Lista Piloto) → Integrações (credenciais + testar) →
Pronto**. O assistente lê o `GET /status` e **retoma** no passo certo
(`lista_piloto_importada` / `integracao_configurada`). Sem redirecionamento
automático por tempo (WCAG 3.2.5) — o avanço é sempre por ação do usuário.
Frontend: `apps/web/src/pages/Comecar.tsx` + `components/CredenciaisForm.tsx`
(formulário de credencial reutilizado pelo painel e pelo wizard).

## Riscos remanescentes
- Os **seletores de login** Matific/Elefante são plausíveis mas **não
  verificados com conta real** (dependência externa) — pontos de extensão
  documentados; o sistema falha com alerta claro, não silenciosamente.
- Playwright é dependência **opcional** (import tardio) — precisa ser instalado
  no ambiente que roda a automação real.

## Decisões deliberadas (não são bugs)
- **Snapshots sem `ano_letivo`** — os snapshots datam por `data_referencia`; a
  virada de ano é derivada da data, não de uma coluna. Decisão de produto: o
  acumulado é contínuo; separar por ano seria outro modelo de relatório.
- **`SYNC_WORKERS`** é o teto de concorrência do worker de fundo; a fila em banco
  é a fonte de verdade (o nome remete a “quantos processam em paralelo”, não a
  processos SO). Documentado para evitar confusão em produção.
- **Agenda no fuso do servidor** — `hora_local` é interpretada no fuso do
  processo (UTC no Railway). Escolha consciente: simplicidade > por-escola
  timezone enquanto todas as escolas-piloto estão no mesmo fuso. Migrar para
  tz-aware por escola é aditivo (coluna + conversão em `calcular_proxima`).
- **Purga por escola** coberta por teste: apagar a `Escola` remove as 5 tabelas
  do módulo (CASCADE por `escola_id`); `logs` seguem a execução (CASCADE) e o
  `alerta` guarda histórico com `execucao_id` em NULL.
- **Relatório mais recente é autoritativo (complementar).** No mesmo dia, um
  relatório diário sobrescreve os campos que traz — inclusive para MENOS — sem
  empilhar um segundo ponto. Consequência aceita: se um import por período
  (com piso anti-regressão) e um diário caírem no mesmo dia, o diário (o mais
  recente) vence. É consistente com o design "o último relatório manda"
  (testado em `test_xlsx_sem_estrelas_preserva_estrelas_do_pdf_anterior`); um
  piso global quebraria essa complementaridade. Correção de valor pontual é
  feita pela edição manual, não por reimport.

## Cobertura de testes (backend `tests/test_sync.py`, `tests/test_importacao.py`)
Cofre (roundtrip/isolamento/rotação, **decifra falha → None**), conectores
(login ok/erro/SSO/download vazio, **sem vazar senha**), orquestrador (reusa
pipeline, resolve ator, sem-linhas), motor (sucesso, **erro genérico sem vazar
segredo**, retry com backoff, **limite de tentativas**, credencial ilegível →
inválida, **claim rowcount 0 não reprocessa**), fila (idempotência +
**índice único de execução ativa**), agenda (cadências, **multi-escola**,
desativar limpa `proxima_execucao`), API (RBAC, isolamento, **/agora parcial**,
onboarding), ON DELETE (**cascata da execução e purga da escola**), e
reimportação do **mesmo dia idempotente** (Matific + Elefante).
