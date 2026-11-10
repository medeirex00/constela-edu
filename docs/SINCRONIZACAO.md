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
- **Cofre Fernet com chave dedicada** — segredo só cifrado no banco, com a
  `DATA_ENCRYPTION_KEY` (fora do banco). Ela é **obrigatória em produção**: com
  `ENV=producao` o boot recusa a DEK ausente, de exemplo ou igual à `SECRET_KEY`.
  A `SECRET_KEY` assina os JWT e, na cifra, só **decifra** as credenciais legadas
  (gravadas antes da DEK). A rotação é pelo chaveiro (`segredos_da_cifra` em
  `app/core/security.py`). A DEK que sai vai para `DATA_ENCRYPTION_KEYS_ANTERIORES`
  e, se a `SECRET_KEY` também girar, a que sai vai para `CHAVE_CIFRA_LEGADA_ANTERIOR`.
  Depois roda-se `python -m scripts.recifrar_segredos --executar`, e só então as
  anteriores saem do ambiente. Trocar a chave sem esse passo deixa as senhas
  `ilegivel`, e cada escola tem de recadastrar a sua. Sequência e regras:
  [CONTINUIDADE.md](CONTINUIDADE.md) §2 (linhas 6 a 8) e
  [PRODUCAO-ENV-E-MIGRACOES.md](operacao/PRODUCAO-ENV-E-MIGRACOES.md) §2.1 e §4.
  `Credenciais.__repr__` mascara; nada de senha em log (testado). A coluna
  `token_version` de `plataforma_credenciais` sobe a cada recadastro da senha
  (`vault.salvar_credencial`), mas nada a lê, e ela não participa da rotação da chave.
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
  Ligado, o agendador ainda **recusa subir** enquanto um pré-requisito crítico
  falha (`app/sync/prerequisitos.py`, visível no `/sync/dashboard`): siga a
  checklist de `docs/sync/REATIVAR-AGENDADOR.md` — não basta a variável.
- **Config** (env): `SYNC_WORKERS`, `SYNC_POLL_S`, `SYNC_MAX_TENTATIVAS`,
  `SYNC_BACKOFF_BASE_S`, `SYNC_TIMEOUT_S` (por passo do navegador),
  `SYNC_TETO_EXECUCAO_S` (teto TOTAL da coleta, 2700 s), `SYNC_LENTO_S`,
  `SYNC_TRAVADA_S` (janela da fila e do pré-requisito do agendador, 3600 s — tem
  de passar do teto da coleta), `SYNC_SEM_SINAL_S` (execução em `executando` sem
  nenhum registro no log há mais que isto é órfã, 900 s) e `MATIFIC_END_DATE`
  (semântica do fim do período do Matific; `desconhecida` recusa 1 dia).
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
  ativa, a escola ficaria travada. Quem está rodando dá **sinal de vida**: uma
  thread escreve no log da execução a cada `SYNC_SEM_SINAL_S`/6 (só se ninguém
  escreveu lá nesse intervalo), por no máximo 2 × `SYNC_TRAVADA_S`.
  `recuperar_execucoes_travadas` (chamada no início de cada rodada do
  scheduler), o boot, a **auto-cura no `enfileirar`** e, com o agendador
  desligado, a leitura do `/status` detectam execuções `executando` sem nenhum
  registro no log (nem início) há mais de `SYNC_SEM_SINAL_S` (15 min),
  finalizam-nas como `erro` (claim atômico) e o reaper **re-enfileira** uma nova
  tentativa. Uma coleta viva além de 60 min não é reivindicada; a morta num
  redeploy sai em ~15 min. O fim de uma execução só grava sobre `executando`
  (UPDATE condicional): reivindicada no meio, o `erro` de quem a encerrou fica,
  e o dado já gravado vira recálculo pendente. Se o `enfileirar` perde a corrida do claim para o reaper
  concorrente, ele **re-checa** o estado (em vez de devolver a órfã morta) e
  cria a execução pedida — o clique nunca some. Assim o botão "Sincronizar" e a
  agenda voltam a funcionar sozinhos, sem intervenção no banco — testado
  (`test_reaper_*`, `test_enfileirar_auto_cura`, `test_enfileirar_perde_corrida_do_reaper`).
  A órfã que morreu **depois** de gravar um arquivo (o /confirmar commita cada
  um) fica com a marca `recalculo_pendente`: o /status avisa e a próxima coleta
  (mesmo "nada mudou") ou o /recalcular recalcula as notas. A que morreu ainda
  na coleta não ganha a marca, porque nada foi gravado.
- **Alertas automáticos:** senha inválida/expirada, falha de autenticação/
  download, timeout, plataforma indisponível, parser incompatível, sincronização
  lenta.
- **Senha salva ilegível** (chave de cifra trocada sem recifrar, valor
  corrompido): a execução termina em `erro` com o motivo `credencial_ilegivel`,
  alerta crítico do mesmo nome e sem nova tentativa. A plataforma não recusou
  nada, então a credencial **não** é regravada como `invalida`: o `/status`
  deriva `ilegivel` da cifra. "Sincronizar agora" (400), o diagnóstico do
  Elefante e o placar ao vivo do Matific pedem o recadastro com o texto de
  `vault.mensagem_credencial_ilegivel`, que cita a plataforma pelo nome. "Testar
  conexão" usa outro texto: responde 200 com `ok=false`,
  `codigo=credencial_ilegivel` e `router.MENSAGEM_CREDENCIAL_ILEGIVEL`, a frase do
  aviso que o formulário de credenciais (`CredenciaisForm`) mostra com o status
  `ilegivel` ("desta plataforma" no lugar do nome). A rota não chama o conector nem
  grava nada, e com esse status a tela desabilita o botão. Salvar a senha de novo,
  ou um login que funciona, fecha o alerta.

## Segurança / LGPD
- Credenciais **cifradas** (Fernet, com a `DATA_ENCRYPTION_KEY`), isoladas por
  escola, nunca devolvidas ao navegador nem escritas em log.
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
- **Mesmo id em duas turmas da coleta** (uuid do Matific, studentId do
  Elefante): não está confirmado se a API lista a criança na turma antiga e na
  nova. Forma segura: números iguais entram uma vez (sem mover a matrícula);
  números diferentes são descartados da coleta (`id_em_varias_turmas`, aviso
  `coleta_parcial`) até a turma ser corrigida na plataforma.
- **`studentId` do Elefante, regra única:** a identidade, os `ids_recebidos`, o
  cursor incremental, a busca de livros por aluno, o aluno da sonda e a
  conferência do mesmo id em duas turmas normalizam o id por
  `importacao.student_id_elefante` (sem espaços, sem o sufixo `.0`, nunca só
  zeros). Antes, só os dois primeiros: com `" 123 "` ou `123.0`, a conta `123`
  era gravada, mas a criança ficava sem cursor e sem livros datados. Os ids de
  turma, de escola e os da descoberta/diagnóstico seguem a regra própria deles.
- **Conta vinculada ausente da coleta** (aviso `contas_ausentes`, com a contagem
  e sem nome; o status do aluno e o da execução não mudam e nenhum dado é
  apagado):
  - **Matific:** conta ausente do Placar no acumulado do ano, em toda coleta
    regular — não está confirmado se o Placar lista quem não teve nenhuma
    atividade no ano.
  - **Elefante:** conta ausente dos relatórios de turma, só na **coleta
    completa** (cursor ignorado ou inexistente, a reconciliação semanal) e com
    **todas** as turmas respondendo; aluno de turma que falhou não conta (a
    coleta já é `parcial`). Entre duas completas o aviso fica como está. Os
    `studentId` recebidos passam pela mesma normalização que grava a identidade
    (`importacao.student_id_elefante`: sem espaços, sem o sufixo `.0`, nunca só
    zeros), para `" 123 "` ou `123.0` não virarem aviso falso.

## Estados da execução: "em dia", "verificado" e período (revisão e93)
- **Em dia** (fecha o alerta crítico `desatualizada`): coleta completa e sem
  falha de unidade — `concluida`, `sem_atualizacao` (nada mudou, correspondência
  pendente, total retido, linhas descartadas) ou `parcial` só por linhas
  descartadas. A `parcial` com turma/lote/aluno/endpoint que falhou não
  fecha. Pendência de identidade e defeito permanente têm alertas próprios
  (`correspondencia_pendente`, `coleta_parcial`) — antes, uma criança fora da
  Lista Piloto ou um livro sem data abriam o crítico num fim de semana.
- **Forma C (Etapa 3): tudo em revisão não é "em dia".** A pendência só conta
  como em dia se a coleta **conferiu ao menos uma conta já vinculada** a um aluno
  da escola: aplicou dado novo, comparou e achou igual ("conferido sem mudança",
  a mesma conta da importação manual) ou reteve um total menor do Matific (a
  retenção só existe para uuid vinculado nesta escola). Sem nenhuma conferida, o
  motivo é `tudo_em_revisao` (sem migração: coluna `motivo`), o alerta continua
  `correspondencia_pendente` com texto próprio (distingue a escola que já tem
  contas vinculadas — confira se o acesso é desta escola — da 1ª coleta) e o
  `desatualizada` abre depois da cadência. É a assinatura de credencial de outra
  escola ou de casamento quebrado. Vale para o /status, o painel global e a
  varredura do agendador (todos por `service._filtro_em_dia`). A tela mostra
  "Sem atualização: nenhuma conta da escola reconhecida".
  Ajustes da revisão adversarial e95:
  - **Coleta por período** só com pendências fica `correspondencia_pendente`, não
    `tudo_em_revisao`: ela nunca conta como em dia, e o Placar por período pode
    trazer só quem teve atividade (suposição a confirmar com o Matific), então não
    é sinal de acesso de outra escola.
  - A **retenção de queda** do Matific só vale para conta vinculada a aluno
    **ativo**: a linha de uma ficha transferida segue para a revisão e não conta
    como "conta da escola conferida".
  - Quando todas as contas vinculadas são de alunos que **não estão ativos**, o
    texto do alerta diz isso (antes dizia "primeira coleta").
  - Com a fila de revisão vazia (só linhas sem vínculo seguro, por exemplo linhas
    sem nome utilizável), o alerta e a tela não dizem "0 contas aguardam".
  - **Limitação:** sem agenda ativa com cadência (`sincronizacao_config.ativo` e
    `cadencia`), não existe o crítico `desatualizada`; ficam só o card e o
    `correspondencia_pendente`.
  - **Para decisão do dono:** "conta já vinculada" é mais estreito que o código. A
    ficha casada pelo nome NESTA coleta, com dado igual ao gravado, também conta
    como conferida (aceitar e ajustar este texto, ou restringir a regra).
  - **Conta aposentada (achado 5 do e95, decisão D4):** a conta duplicada que a
    escola já aposentou e a plataforma continua mandando é **descarte com motivo
    próprio** `identidade_aposentada` (em `linhas_descartadas`), fora de
    `ignorados` e de `sem_vinculo`, e não é defeito. Não abre pendência, não
    desfaz o cursor da criança de mesmo nome, não conta em `qtd_erros` e fica
    citada no log da execução. A coleta com as contas da escola conferidas e a
    aposentada junto termina `nada_mudou` (verificada e em dia). A coleta que só
    trouxe contas aposentadas não conferiu a escola: `tudo_em_revisao` (não é em
    dia nem verificação), sem alerta de pendência; na coleta por período, vira
    `nada_mudou`. Antes, toda coleta saía `correspondencia_pendente`, a
    verificação não avançava e o cursor da criança era desfeito.
- **Verificado** (`ultima_verificacao_em`): dado aplicado, `sem_dados`, ou
  `sem_atualizacao` por `nada_mudou`/`queda_retida`.
- **Último sucesso** (`ultimo_sucesso_em` do `/status`, o frescor da tela e a
  "última sincronização" do selo do ranking): a coleta que **aplicou dado** —
  `concluida` (sem condição) ou `parcial` com ao menos um aluno aplicado. A
  `parcial` sem aluno aplicado (abaixo) conta como verificação, mas não avança o
  último sucesso, o frescor nem o selo (P18).
- **Coleta por período do Matific** (parâmetros com datas) não conta no último
  sucesso, na verificação nem no "em dia" (não renova o acumulado dos rankings) e
  não abre `plataforma_sem_dados`.
- **`student-leaderboard`** (nomes completos do Matific) é acessório: falha ou
  forma errada vira unidade com falha (`parcial`) — também quando nenhum número
  mudou, desde que a coleta tenha conferido conta já vinculada; na 1ª coleta, sem
  nenhuma conta conferida, é `erro` —, e conta ainda não vinculada vai
  para a revisão `nome_incompleto`. A `parcial` sem nenhum aluno aplicado não é a
  "última coleta com dado" que o alerta `plataforma_sem_dados` usa de referência
  nem o último sucesso (a `concluida` e a `parcial` com aluno aplicado continuam
  sendo).
- **Motivo do `erro`** pela contabilidade é o código dominante das falhas
  (`sem_acesso_ao_dado`, `falha_download`, `parser_incompativel`).

## Escola externa: proteção contra dados de outra escola (Etapa 3)
Uma credencial é uma conta do Elefante/Matific, e a conta pode enxergar mais de
uma escola na plataforma (gestor de duas unidades, conta da Secretaria) ou ser,
por engano, a de outra escola. Antes, o código não conferia a escola. Com a
política `permitir`, os dados de outra escola criavam fichas. Com `bloquear`,
lotavam a revisão.

**Vínculo** (`backend/app/sync/escola_externa.py`). Para cada escola do Constela
e plataforma, o vínculo guarda qual escola da plataforma ela é:
- o id externo: `schoolId` do Elefante (número) ou `school_id` do Matific (uuid);
- o nome que a plataforma mostra;
- a origem: `aprendido` ou `explicito`.

Fica em `configuracoes`, namespace `sync_escola_externa`, chave = plataforma. Não
precisa de migração e não guarda segredo.

**Restauração do backup da escola (2ª revisão de integração do e97).** O vínculo
e a política de criação de aluno (namespace `sincronizacao`) continuam saindo no
arquivo do backup, mas a restauração **não** os repõe nem os apaga: ficam como
estão, e as linhas do arquivo são ignoradas, como já acontecia com os segredos
(`backup.PRESERVADAS_NA_RESTAURACAO`). Antes, restaurar um arquivo de antes do
`bloquear` fazia a política voltar a `permitir` em silêncio (a coleta seguinte
voltava a criar fichas), e o vínculo era apagado ou regravado com uma escola
externa que hoje é o vínculo de outra escola, sem a regra do 409 (as duas coletas
paravam com `escola_externa_em_outra_escola`). Para mudar a política ou o vínculo,
use as rotas próprias (Admin Global, auditadas).

| Situação na coleta | Resultado (nada é aplicado nos erros) |
|---|---|
| Sem vínculo, a conta enxerga **uma** escola | o vínculo é **aprendido** e a coleta segue |
| Sem vínculo, a conta enxerga **duas ou mais** | `erro` `conta_multiescola`, alerta crítico |
| Com vínculo, e a vinculada está entre as que a conta enxerga | a coleta segue, só com ela |
| Com vínculo, e a conta não enxerga a vinculada | `erro` `escola_externa_trocada`, alerta crítico |
| A escola da conta já é o vínculo de **outra** escola do Constela | `erro` `escola_externa_em_outra_escola`, alerta crítico |
| Sem vínculo, e **todas** as contas identificadas já são de alunos de outra escola do Constela (D8) | `erro` `contas_de_outra_escola`, alerta crítico; nada gravado, nem revisão |
| Nenhuma escola identificável na resposta | `erro` `escola_nao_identificada`, alerta crítico |
| Sem vínculo, e o nome da escola que a conta enxerga não confere com o cadastrado (D9) | a coleta **segue**, mas o vínculo **não é aprendido** (log e auditoria `sync.escola_externa_nao_aprendida`) |
| Com vínculo, e o nome na plataforma (ou nos relatórios de turma) diferente do cadastrado | só **aviso** no log (nomes variam), nunca bloqueio |

**Nome da escola: critério da comparação (D9, `escola_externa.nomes_compativeis`).**
Os dois nomes são normalizados (sem acento, sem caixa, sem pontuação) e reduzidos
às palavras que identificam a escola: saem o tipo (EMEF, EMEI, Escola Municipal,
CEI…), as preposições, os títulos (Prof., Dr., Vereador, Padre…) e as letras
soltas (iniciais). São compatíveis quando as palavras do nome mais curto aparecem
no outro — todas, ou ao menos dois terços delas e no mínimo duas —, aceitando
UMA letra de diferença em palavras de 5+ letras ("Thimóteo" × "Timoteo", "Passos"
× "Pasos"). "EMEF Prof. Jorge Passos" casa com "Escola Municipal Professor Jorge
Passos"; "Maria das Dores" não casa com "Maria José". O nome que decide o
aprendizado é o da escola externa (`fantasyName` do Elefante, nome do
`accounts/current` do Matific, quando vem); o `schoolName` dos relatórios de
turma continua só aviso. Nome vazio (o Matific em
geral não manda o nome da escola) não tem o que comparar: não avisa nem impede o
aprendizado — ali valem o id, a identidade efetiva em outra escola e o D8. O
mesmo critério alimenta o aviso da importação manual e do "Testar conexão", que
diz quando a próxima coleta não vai aprender o vínculo.

Onde cada regra roda:
- O **conector** recusa antes de pedir qualquer dado de turma. Os ids já
  vinculados a outras escolas vão no contexto, porque o conector não toca o banco.
- O **serviço** confere de novo antes de aplicar e aprende o vínculo. Duas
  escolas que aprendessem a mesma escola externa ao mesmo tempo ficam as duas
  paradas. Com vínculo gravado, a escola lida pela coleta tem de ser a vinculada,
  venha de onde vier: senão `escola_externa_trocada` e nada é aplicado (revisão
  e95, achado K).
- **Vínculo aprendido e desfeito (revisão e95, achado A1).** O vínculo aprendido
  numa coleta é desfeito no fim dela quando a coleta trouxe conta já **efetiva em
  outra escola** do Constela (`identidade_de_outra_escola`): é o sinal de que a
  credencial pode ser a da outra escola, e o vínculo errado bloquearia a escola
  dona (`escola_externa_em_outra_escola`). Vale para a coleta **mista**; quando
  todas as contas são de lá, a coleta nem chega a aplicar (`contas_de_outra_escola`,
  D8). A coleta segue igual (as revisões ficam)
  e a seguinte tenta aprender de novo; a auditoria registra
  `sync.escola_externa_desfeita`. Contrapartida: uma escola com uma criança
  transferida pendente só fica com o vínculo depois de resolver essa revisão.
- No **Elefante**, numa conta de várias escolas com vínculo:
  - só as turmas com o `schoolId` vinculado são coletadas;
  - a turma de outra escola fica de fora, com log;
  - a turma **sem** `schoolId` é recusada e vira unidade com falha
    (`escola_nao_identificada`, alerta `coleta_parcial`);
  - a lista de turmas é pedida com `?schoolId=` da vinculada, nunca a chamada sem
    escola;
  - o relatório de turma vai com o `schoolId` vinculado. Antes ia o da 1ª escola
    de `active-schools`.
- O **placar ao vivo do Matific** também confere o vínculo, nos caminhos HTTP e
  navegador: ele mostraria nomes de crianças. Ele não aprende vínculo. A linha
  cuja conta é a identidade efetiva de um aluno de **outra** escola do Constela
  fica **sem link** para ficha (2ª revisão de integração do e97,
  `aovivo._fichas_da_escola`, uma consulta à regra única por placar), como na
  sincronização, que a manda para a revisão `identidade_de_outra_escola`. Antes
  ela caía no nome e ganhava o link do homônimo desta escola, e o professor dele
  a via (e podia premiá-la) como se fosse do aluno dele. A conta que também está
  vinculada a uma ficha ativa daqui continua ligando pela conta.

**Escolha explícita** em `/escolas/{id}/sync/escola-externa/{elefante|matific}`:
- `PUT {id_externo, nome}`: **só o Admin Global** (revisão e97, achado de
  autorização 2). Os demais recebem 403. Antes, o coordenador de qualquer
  escola gravava o `schoolId` de OUTRA escola sem ter credencial e travava a
  sincronização dela (`escola_externa_em_outra_escola`).
- `GET` e `DELETE`: Admin Global ou coordenação da escola, as mesmas permissões
  da credencial. Desfazer o vínculo da própria escola só a libera.
- o `PUT` recusa id fora do formato (422) e id já vinculado a outra escola do
  Constela (409);
- a mensagem de `escola_externa_em_outra_escola` que a escola vê **não** traz o
  id interno da outra escola. O id fica na auditoria
  (`sync.escola_externa_em_outra_escola`, com `outras_escolas` e `id_externo`);
- tudo vai para a auditoria (`sync.escola_externa_definida`/`_removida`/`_aprendida`);
- trocar a credencial **não** apaga o vínculo: é ele que pega a credencial de
  outra escola.

**"Testar conexão"** (e o salvar credencial) devolve, sem segredo:
- `escolas_externas`: as escolas que a conta enxerga;
- `escola_vinculada`;
- `escola_confere`;
- `aviso_escola`: o que a próxima coleta faria.

Só lê, não grava vínculo. O `/status` traz `escola_externa` por plataforma.

**Identidade já efetiva em outra escola** (`identidade_aluno.marcar_ids_de_outra_escola`):
- O uuid/studentId da linha que já é o vínculo efetivo de um aluno de **outra**
  escola do Constela (não aposentado, ficha não excluída) vai para a revisão
  `identidade_de_outra_escola`.
- Nada é aplicado aqui e nada é mexido lá. Os candidatos pelo nome vão como
  sugestão.
- A sync abre o alerta crítico `identidade_de_outra_escola`. Ele fecha quando uma
  coleta completa não traz mais nenhuma dessas contas.
- **Coleta só de contas de outra escola (decisão D8, LGPD).** Sem vínculo da
  escola externa, quando **todas** as contas identificadas da coleta (linhas com
  uuid/studentId) já são a identidade efetiva de alunos de outra escola do
  Constela, a coleta é recusada **antes de aplicar qualquer linha**: `erro`
  `contas_de_outra_escola`, alerta crítico, sem nova tentativa e auditoria
  `sync.contas_de_outra_escola_recusada` (número de contas e, só ali, o id da
  outra escola). Nada é gravado: nem ficha, nem retrato, nem revisão com o nome
  da criança de lá, nem o vínculo. Critério: basta **uma** conta que já é a
  identidade **efetiva** de um aluno **ativo** desta escola (vínculo não
  aposentado, ficha nem excluída nem inativa: `identidade_aluno.efetivas_na_escola`)
  ou ainda desconhecida no Constela para a coleta seguir como antes (coleta
  mista: aplica as desta escola e manda as de lá para a revisão). Não fazem a
  conta ser "desta escola" e não livram a coleta da recusa: a identidade
  **aposentada** aqui (a conta duplicada que a escola descartou), a presa a uma
  ficha **excluída** (revisão e97b) e a presa a uma ficha **inativa** —
  transferida, arquivada ou fora da Lista Piloto (revisão de integração do e97).
  A criança que saiu desta escola para a outra é o caso da ficha inativa:
  "Marcar como transferido" troca só o status da ficha e a conta continua
  efetiva, porque a conta única de uma criança não pode ser aposentada
  (`/identidades/{plataforma}/efetiva` recusa aposentar a única). Esse filtro
  vale **só do lado "desta escola"**: do lado da outra escola
  (`efetivas_em_outra_escola`, a regra única da "conta de outra escola") a ficha
  inativa continua contando, porque é ela que manda a conta da criança
  transferida para a revisão `identidade_de_outra_escola` na escola nova e que a
  trava do D10 protege. Linha sem id não conta. Com vínculo gravado a regra não se
  aplica: a escola externa já foi conferida pelo id, e a conta de outra escola é
  a criança que mudou de escola (revisão própria). Saída para o caso legítimo
  (fichas criadas na escola errada, escola desmembrada): o Admin Global grava o
  vínculo da escola externa e confirma as contas em Revisão de identidade.
- A triagem nunca dá o caso por "seguro".
- **Quem confirma (decisão D10):** resolver aqui uma pendência cuja conta é a
  identidade efetiva de um aluno de outra escola do Constela é só do **Admin
  Global** — a gestão da escola recebe 403 com a orientação (descartar, se a
  conta não é de uma criança daqui). Confirmar faz a conta valer nas duas
  escolas: a outra não é alterada, mas na coleta seguinte dela a conta vai para a
  Revisão de identidade de lá e a criança de lá deixa de ser atualizada até
  alguém decidir. Por isso a resposta do `/resolver` traz esse aviso e a
  auditoria registra `identidade.revisao_outra_escola_confirmada` (quem, qual
  conta, qual outra escola). A decisão fica na memória e a próxima coleta desta
  escola associa pelo vínculo.
- **A mesma trava nos outros caminhos (rodada 3 do e97, regra única
  `identidade_aluno.efetivas_em_outra_escola`):**
  - **Importação manual com a ficha escolhida** (`/importacoes/confirmar`, linha
    com `aluno_id`): para a gestão da escola, a linha de uma conta efetiva em
    outra escola não vincula nem aplica nada — vai para a revisão
    `identidade_de_outra_escola`, com a ficha escolhida como sugestão (e a
    decisão volta a ser do Admin Global no `/resolver`). O Admin Global vincula,
    com o mesmo aviso nos `avisos` da resposta e a auditoria
    `identidade.importacao_outra_escola_confirmada` (quem, qual conta, qual outra
    escola, qual importação). A conta que **já** vale aqui para a ficha escolhida
    não é barrada (nada novo é vinculado): o dado da linha é aplicado, mas a
    pendência `identidade_de_outra_escola` dessa conta **não** é encerrada pela
    gestão da escola (4ª revisão de integração do e97,
    `importacoes._retida_pelo_d10`). Antes, a importação manual datada fechava a
    pendência e, com nome não idêntico, a fechava como decisão humana, que virava
    memória: a coleta seguinte associava a conta sem o Admin Global. Agora a
    pendência fica na fila, com um aviso nos `avisos` de que só o Admin Global a
    encerra. Vale para pendência de **qualquer** motivo dessa conta (marco 3 do
    e97), não só `identidade_de_outra_escola`: a aberta antes de a conta virar
    efetiva na outra escola (ex.: `identidade_de_ficha_inativa`, a criança
    marcada como transferida aqui) dava o mesmo atalho até a memória que o passo
    0d da coleta seguinte respeita. O `/resolver` já barrava a gestão em qualquer
    motivo (a trava dele olha a conta, não o motivo). A importação manual do
    Admin Global e a sincronização seguem a regra geral: a sincronização encerra
    a pendência sozinha quando a conta deixa de ser de outra escola, ou pela
    memória da decisão do Admin Global.
  - **Volta de uma conta aposentada** (`/identidades/{plataforma}/reativar`, ou a
    aposentada escolhida em `/identidades/{plataforma}/efetiva`): 403 para a
    gestão da escola; o Admin Global segue, com `avisos` na resposta (campo novo,
    lista vazia nos demais casos) e a auditoria
    `identidade.reativacao_outra_escola_confirmada` (`acao` `reativar` ou
    `definir_efetiva`). Escolher a conta que já é a efetiva não passa pela trava.
    Com a ficha **ativa**, a decisão do Admin Global vira memória, como no
    `/resolver` (ver "Memória da confirmação", abaixo).
  - **Volta de uma ficha excluída** (revisão de integração do e97,
    `identidade_efetiva.trava_ficha_sai_de_excluido`). A regra única ignora de
    propósito a identidade de ficha **excluída** (excluída a ficha numa escola, a
    outra vincula a mesma conta sem trava), mas **qualquer** saída de `excluido`
    faz a conta voltar a valer. Para cada ficha excluída que vai sair desse
    status, as contas não aposentadas dela passam pela regra única:
    - `POST /escolas/{id}/alunos/acoes` com `reativar`, `arquivar` ou
      `marcar_transferido`: 403 para a gestão da escola (admin ou coordenação),
      com o nome da ficha e nada da outra escola; nada muda, nem as outras fichas
      da mesma ação em massa. O Admin Global segue, com o aviso em `avisos`
      (campo novo, lista vazia nos demais casos) e a auditoria
      `aluno.reativacao_outra_escola_confirmada` por conta (plataforma, conta,
      outra escola, ação, status novo; sem nome). Em `reativar` (a ficha volta
      ativa) a decisão vira memória (ver "Memória da confirmação", abaixo); em
      `arquivar` e `marcar_transferido`, não;
    - **Lista Piloto** (reativação automática pelo RA): a ficha **não** é
      reativada e a linha **não altera nada** nela (status, nome, ficha,
      matrícula e identidade ficam como estavam), para qualquer usuário,
      inclusive o Admin Global — a planilha não é uma decisão sobre a conta. A
      resposta traz o aviso por ficha e a contagem na mensagem; a auditoria
      registra `aluno.reativacao_retida_conta_de_outra_escola` (e a contagem em
      `matriculas.importadas`). As outras linhas seguem. A reativação legítima
      não se perde: o Admin Global reativa em Alunos (com aviso e auditoria) ou,
      quando a conta deixar de valer na outra escola (a ficha de lá excluída), o
      envio seguinte da planilha reativa e aplica a linha sozinho. Foi preferido
      a aposentar a conta automaticamente porque a conta única aposentada é um
      estado que a API não cria e a coleta seguinte a descartaria em silêncio.
    - **Restauração do backup da escola** (`POST /escolas/{id}/restaurar`, só do
      Admin Global; 2ª revisão de integração do e97,
      `identidade_efetiva.conferir_restauracao`): a restauração recria as fichas
      com o status do arquivo e as identidades delas, então a ficha excluída
      depois do backup volta a valer. Depois de inserir, as contas não
      aposentadas das fichas não excluídas passam pela regra única. Para cada
      conta que ficou efetiva nas duas escolas, a auditoria
      `aluno.reativacao_outra_escola_confirmada` (`acao` `restaurar_backup`,
      plataforma, conta, outra escola; sem nome); a resposta traz o aviso em
      `avisos` (campo novo, lista vazia nos demais casos). Nada é recusado,
      porque a rota já é só do Admin Global. A restauração não decide por ficha
      nenhuma, então não grava a memória da decisão: a coleta seguinte **desta**
      escola também manda a conta para a revisão `identidade_de_outra_escola`, e
      o Admin Global decide no `/resolver`.
    - A conta aposentada da ficha não volta a valer com ela (tem a trava
      própria acima), e a ficha que não está excluída (arquivada, transferida,
      fora da Lista Piloto) não passa pela trava: ela já conta como efetiva.
    - Quem aposentou a conta (`aposentada_por_id`; usuários não entram no
      backup) volta como veio se o usuário ainda existe. Se ele foi removido em
      definitivo depois do backup, ou o arquivo veio de outro banco, a referência
      vira NULL e a conta volta aposentada, com a data e o motivo do arquivo
      (`backup.REFERENCIAS_A_USUARIO`; 4ª revisão de integração do e97). Antes o
      INSERT violava a FK e a restauração inteira voltava 400 "dados
      inconsistentes ou duplicados".
  - **Memória da confirmação** (2ª revisão de integração do e97,
    `identidade_efetiva._gravar_memoria_da_decisao`). O passo 0d de `decidir` só
    associa uma conta efetiva em outra escola quando há memória humana para ela.
    O `/resolver` grava essa memória; a reativação da ficha excluída e a volta da
    conta aposentada só gravavam a auditoria e o aviso, e a coleta seguinte
    **desta** escola mandava a conta de novo para a revisão daqui (a gestão leva
    403 no `/resolver`). Agora, quando a ficha fica **ativa** (`reativar` em
    `/alunos/acoes`, ou `/identidades/{plataforma}/reativar|efetiva` em ficha
    ativa), o Admin Global deixa a mesma memória do `/resolver`: uma revisão
    resolvida (origem `confirmacao_admin`, motivo `identidade_de_outra_escola`,
    chave da conta, ficha escolhida, quem decidiu e `resolucao` com
    `resolvida_na` = a ação). Ela aparece entre as resolvidas em Revisões, e o id
    vai na auditoria (`memoria_da_decisao`). Ficha arquivada ou transferida não
    ganha memória: com ela, a ficha inativa passaria a receber dado. A importação
    manual do Admin Global (item E) e a restauração do backup continuam sem
    gravar memória. **Fundir duplicatas** (um par ou em lote) leva a memória da
    ficha removida para a mantida (`alunos_fusao.fundir_par`, auditoria
    `aluno.fundido` com `decisoes_de_identidade_movidas`): antes o delete zerava
    a coluna (FK `SET NULL`) e a confirmação do Admin Global sumia sem aviso.
- A prévia da importação manual mostra o mesmo.

**Importação manual.** A escola lida do relatório (`escola_detectada`: cabeçalho do
PDF ou `schoolName` do Elefante) volta na prévia. Quando o nome não parece o da
escola cadastrada (mesmo critério do D9), vem também `aviso_escola` e a tela
mostra o aviso. É só aviso:
a confirmação continua liberada. O que barra a conta de outra escola no upload
manual é a identidade (`identidade_de_outra_escola`), não o nome.

### Suposições sobre as plataformas (NÃO confirmadas) e como o código falha seguro
| Suposição | Se não valer |
|---|---|
| Elefante: `/school/active-schools` lista as escolas que a conta enxerga (`id`, `fantasyName`) | a escola vem só do `schoolId` das turmas. Sem nenhum dos dois: `escola_nao_identificada`, nada aplicado |
| Elefante: toda turma de `get-courses-students` traz `schoolId` (e `schoolName`) | conta de uma escola: a turma sem `schoolId` é dessa escola. Conta de várias: a turma é recusada. Todas sem `schoolId`: `escola_nao_identificada` |
| Elefante: `?schoolId=` na lista de turmas e no `overall-course-report` restringe à escola pedida | não verificável daqui. A turma que vier com outro `schoolId` é descartada. O aluno do relatório não traz escola, então um relatório que misturasse escolas passaria (ver o risco abaixo) |
| Matific: o `school_id` de `accounts/current` é a escola da conta logada (uma só) | sem ele, usa-se o tráfego da página. Mais de um `school_id` no tráfego sem vínculo: `conta_multiescola`. Nenhum: `sem_escola` (como antes) |
| Matific: o `school_student` pedido com `school_id` só traz alunos dessa escola | o corpo traz `school_id` (MATIFIC_API §4.1): se ele disser **outra** escola (ou mais de uma), `escola_externa_trocada` e nada é aplicado, também no placar ao vivo (revisão e95, achado J). Sem o campo no corpo, não é verificável daqui e segue como antes. A identidade efetiva em outra escola ainda barra as contas já conhecidas |
| Um uuid/studentId identifica uma criança numa escola só | criança que mudou de escola precisa de uma confirmação humana na escola nova |

Perguntas às plataformas (somam-se às da revisão pré-implantação): o
`active-schools` é a lista completa das escolas da conta? Toda turma traz
`schoolId`? Os relatórios pedidos com `schoolId` são restritos a ela? O
`accounts/current` de um gestor de várias escolas traz qual `school_id`?

### Implantação e as 5 escolas atuais
- Nenhuma tem vínculo. Na 1ª coleta depois da implantação, quem enxerga uma escola
  só aprende o vínculo e segue igual (testado com histórico e sem duplicar). Se o
  nome da escola na plataforma não conferir com o cadastrado (D9), a coleta segue
  e o vínculo não é aprendido: o "Testar conexão" avisa antes.
- Quem enxerga **duas** (há registro de uma conta do Elefante assim, em 22/10)
  para em `conta_multiescola` até alguém escolher. Fazer isso **antes** da 1ª
  coleta: use o "Testar conexão" para ver as escolas e o `PUT` do vínculo.
- Diagnóstico só-leitura, antes de implantar, da identidade que já é efetiva em
  duas escolas. Uma contagem, sem nome:

```sql
SELECT plataforma, COUNT(*) AS contas_em_mais_de_uma_escola FROM (
  SELECT ie.plataforma, ie.id_externo
  FROM identidades_externas ie JOIN alunos a ON a.id = ie.aluno_id
  WHERE ie.status <> 'aposentada' AND a.status <> 'excluido'
  GROUP BY ie.plataforma, ie.id_externo
  HAVING COUNT(DISTINCT ie.escola_id) > 1) t
GROUP BY plataforma;
```

Cada uma dessas contas vai para a revisão `identidade_de_outra_escola` nas duas
escolas até um gestor confirmar.

**Mitigação recomendada antes da 1ª coleta (sem código):** em cada uma das 5
escolas, rodar o "Testar conexão", conferir o id e o nome da escola que a conta
enxerga e gravar o vínculo explícito (`PUT`) com o Admin Global. Assim nenhuma
das 5 depende do aprendizado automático.

**Riscos que ficam** (revisão e95; os itens marcados dependem de decisão do dono):
- Um relatório de turma do Elefante que misturasse alunos de duas escolas, com o
  `schoolId` certo na turma, não é detectável. O aluno não traz escola.
- **A3 (decidido, D9):** se a escola dona ainda não tem histórico no Constela
  (nenhuma identidade), a credencial dela cadastrada noutra escola não ensina
  mais o vínculo errado quando o nome diverge: a escola errada coleta sem gravar
  o vínculo, e a dona aprende o dela. Ficam: (1) nome vazio ou parecido demais
  (critério acima) continua aprendendo; (2) a coleta da escola errada segue a
  política dela — com `permitir`, as crianças da dona viram fichas na escola
  errada, e a coleta seguinte da dona cai no D8 (`contas_de_outra_escola`) até o
  Admin Global corrigir (com `bloquear`, vão para a revisão e a dona segue
  normal).
- **A2 (decidido, D8):** a coleta sem vínculo em que todas as contas já são de
  outra escola é recusada sem gravar nada (ver acima). Fica de fora a coleta
  **parcialmente** de outra escola (ao menos uma conta desconhecida ou efetiva
  de um aluno ativo desta escola; a de ficha transferida, arquivada ou fora da
  Lista Piloto não conta): as contas efetivas lá continuam indo para a fila de Revisões desta
  escola com nome e número, e a conta desconhecida segue a política da escola
  (com `permitir`, vira ficha). A mitigação continua sendo o vínculo explícito
  antes da 1ª coleta e a política `bloquear`.
- **B (mitigado na e97):** a escolha explícita confia em quem a faz (auditada):
  o `PUT` não exige que a credencial desta escola tenha mostrado aquele id. Como
  o `PUT` passou a ser só do Admin Global, um gestor de escola não reserva mais a
  escola de outra. Exigir a posse (o id ter aparecido no "Testar conexão")
  continua opcional e é decisão do dono.
- **V (decidido, D10):** resolver a revisão de uma conta efetiva noutra escola
  passou a ser só do Admin Global, com aviso e auditoria (ver acima). O efeito na
  outra escola continua (a conta cai em revisão lá na coleta seguinte): é a
  decisão consciente de quem confirma. Os outros caminhos que faziam a conta
  valer em duas escolas sem a trava — a importação manual com a ficha escolhida
  (item E) e a volta de uma conta aposentada (`/identidades/{plataforma}/reativar`
  ou a aposentada escolhida em `/efetiva`) — passaram a ter a mesma regra na
  rodada 3 do e97; a volta de uma ficha excluída (`/alunos/acoes` em qualquer
  ramo de status e a reativação pela Lista Piloto), na revisão de integração do
  e97; e a restauração do backup da escola, na 2ª revisão de integração (aviso e
  auditoria; ver "A mesma trava nos outros caminhos", acima). Fica de fora, por ser
  decisão pendente do dono (P6/D18), o tratamento da conta da criança marcada
  como transferida: hoje ela continua efetiva, conta na regra única vista da
  outra escola e vira a pendência `identidade_de_ficha_inativa` a cada coleta
  desta.
- **E (orientação, D11; trava na rodada 3 do e97):** para a gestão da escola,
  escolher a ficha na importação manual não grava mais a identidade: a linha vai
  para a revisão `identidade_de_outra_escola`, e a confirmação é feita em Revisão
  de identidade, pelo Admin Global (D10). Para o Admin Global, a importação grava
  a identidade com aviso e auditoria; a revisão pendente segue a regra geral do
  encerramento automático (com o arquivo sem a data do relatório ela fica
  pendente, e a coleta seguinte continua revisando a conta até a decisão em
  Revisão de identidade). O texto do motivo (`motivo_texto`, também na prévia) e
  a orientação da tela de Revisões continuam valendo.

## Decisões deliberadas (não são bugs)
- **Snapshots sem `ano_letivo`** — os snapshots datam por `data_referencia`; a
  virada de ano é derivada da data, não de uma coluna. Decisão de produto: o
  acumulado é contínuo; separar por ano seria outro modelo de relatório.
- **Ano letivo nos RESULTADOS: Matific é do ano, Elefante é vitalício.** O
  contador do Matific que a sync coleta é do ano (`this-year`): todo indicador
  anual, ranking, premiação, painel da escola, painel/ranking da rede, cartaz,
  telão e resumo de turma usa só o retrato DENTRO do ano letivo ativo
  (`scoring.snapshots_matific_do_ano` / `matific_destaque.janela_ano_letivo`);
  quem só tem retrato de outro ano não é aferido em Matemática (ausência, não
  zero). O Elefante NÃO recebe esse corte por desenho: a sync pede LIFETIME e o
  contador é vitalício (livro lido não "zera" na virada) — a nota anual de
  Leitura carrega os anos anteriores. Trocar isso (diferença entre o retrato
  atual e o último antes do início do ano, e `Leitura.data` filtrada pelo ano)
  é decisão do dono, porque muda todas as notas de Leitura da rede. Travado em
  `tests/test_sync_integridade_resultados_ano_letivo.py`.
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
erro `credencial_ilegivel` sem regravar `invalida`, **claim rowcount 0 não
reprocessa**), fila (idempotência +
**índice único de execução ativa**), agenda (cadências, **multi-escola**,
desativar limpa `proxima_execucao`), API (RBAC, isolamento, **/agora parcial**,
onboarding), ON DELETE (**cascata da execução e purga da escola**), e
reimportação do **mesmo dia idempotente** (Matific + Elefante).
