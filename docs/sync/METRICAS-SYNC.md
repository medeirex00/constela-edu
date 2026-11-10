# Métricas de sincronização no `/metrics`

As séries `sync_*` mostram, no formato Prometheus, o estado da sincronização do Elefante Letrado e do Matific. Código: `backend/app/sync/metricas.py`. Testes: `backend/tests/test_sync_metricas.py` (SQLite) e `test_sync_metricas_pg.py` (PostgreSQL); os achados da revisão e95 em `test_sync_metricas_revisao.py` e `test_sync_metricas_revisao_pg.py`.

Nada mudou no contrato da API: nenhuma rota, campo ou estado novo. O `/metrics` ganhou séries e continua com a mesma proteção:
- com `METRICS_TOKEN`, exige `Authorization: Bearer <token>`;
- sem token, responde 404 em qualquer `ENV`;
- `METRICS_PUBLICO` só abre fora de produção.

**Nunca defina `METRICS_PUBLICO` no serviço de produção** (revisão e95, risco que já existia). A flag só é ignorada com `ENV=producao`, e a auditoria de 20/10 registrou a API de produção rodando com `ENV=dev`: com a flag ligada, o `/metrics` abriria sem token, agora com o estado das credenciais por escola.

O coletor do banco só roda depois que a rota autorizou o scrape: um pedido recusado não faz nenhuma consulta.

## 1. Estado lido do banco a cada scrape

Vale para qualquer worker que atender o scrape, porque todos leem o mesmo banco.

| Série | Rótulos | O que é |
|---|---|---|
| `sync_ultima_execucao_idade_segundos` | `escola_id`, `plataforma`, `status` | Segundos desde o fim da última execução da integração em cada estado: `concluida`, `parcial`, `sem_atualizacao`, `sem_dados`, `erro`, `cancelada` |
| `sync_ultimo_dado_aplicado_idade_segundos` | `escola_id`, `plataforma` | Segundos desde a última coleta do acumulado que aplicou dado (`concluida`, ou `parcial` com ao menos um aluno aplicado: a `parcial` sem aluno, quando falhou só o endpoint dos nomes do Matific, não conta). A coleta por período do Matific não conta. É o marco de `service.ultimo_sucesso_em` |
| `sync_execucoes_ativas` | `plataforma`, `status` | Execuções em `fila` ou `executando`, com zero explícito para as plataformas cadastradas |
| `sync_execucao_ativa_idade_segundos` | `escola_id`, `plataforma`, `status` | Idade da execução ativa: desde a criação (fila) ou desde o início (executando) |
| `sync_execucoes_presas` | `plataforma`, `status` | Ativas sem sinal de vida. Em `executando`: início e último log mais antigos que `SYNC_SEM_SINAL_S`, o mesmo critério do reaper (`_esta_travada`). Em `fila`: criação, disponibilidade e último log, todos mais antigos que `SYNC_TRAVADA_S` (para a manual, o mesmo que `_manual_orfa`) |
| `sync_alertas_abertos` | `escola_id`, `plataforma`, `tipo`, `severidade` | Alertas com `resolvido = false`. Alerta sem plataforma aparece com `plataforma="nenhum"` |
| `sync_recalculo_pendente` | `escola_id` | 1 se há dado gravado esperando o recálculo das notas: alerta `recalculo_pendente` aberto ou marca numa execução da escola, de qualquer plataforma. É a regra de `service.recalculo_pendente_aberto` por escola. Aparece para a escola com integração, com alerta ou com a marca, mesmo depois de removida a credencial (o `DELETE` fecha o alerta e a marca fica; antes da revisão e95 a série sumia) |
| `sync_credencial_status` | `escola_id`, `plataforma`, `status` | 1 na série do status atual da credencial (`nao_validada`, `valida`, `invalida`, `expirada`, `ilegivel`). É o status **derivado**, o mesmo do `/sync/status` (`vault.status_efetivo`): a credencial cuja cifra não abre com as chaves deste processo (chave trocada sem recifrar, valor corrompido) sai `ilegivel`, qualquer que seja o gravado. Antes da rodada 3 do e97 a métrica publicava o gravado, e a ilegível aparecia como `valida`. Cada cifra é aberta uma vez por processo e por conjunto de chaves (o "abre ou não" fica em memória), dentro do prazo total do coletor |
| `sync_agendador_ligado` | — | 1 se `SYNC_SCHEDULER_ENABLED` está ligado |
| `sync_coletor_sucesso` | — | 1 se o coletor leu o banco neste scrape. Com 0, as séries do banco ficam de fora |
| `sync_coletor_duracao_segundos` | — | Quanto a leitura do banco levou neste scrape |

"Integração" é cada par escola × plataforma com credencial ou com agenda (`sincronizacao_config`). Um par sem nenhuma das duas não aparece.

**Custo.** São 5 consultas por scrape, ou 6 quando há execução na fila. O número não cresce com as escolas nem com o histórico (teste `test_numero_de_consultas_…`). Todas têm caminho por índice que já existe:
- `ix_sync_exec_frescor`: o MAX por estado e por integração;
- `ix_sync_exec_escola_inicio` ou `ix_sincronizacao_execucoes_escola_id`: a marca de recálculo, um `EXISTS` por escola (consulta própria desde a revisão e95);
- `ix_sincronizacao_execucoes_status`: as ativas;
- `ix_sincronizacao_logs_execucao_id`: o sinal de vida da fila;
- `ix_sincronizacao_alertas_resolvido`: os alertas abertos.

Os testes conferem os planos: no SQLite, sem `SCAN` nas tabelas de execuções, logs e alertas; no PostgreSQL, sem `Seq Scan` com `enable_seqscan=off`. Isso prova que existe caminho por índice, não que o planejador o escolha: com estatísticas reais e tabelas pequenas, o PostgreSQL pode preferir varrer. A revisão e95 mediu, com o planejador real e a versão anterior das consultas, 6,2 ms por scrape no volume de produção e 13,9 ms com 100 vezes o volume. Cada scrape também faz o ping do pool, os `SET` da sessão e um `ROLLBACK`.

**Prazo total e teto por consulta (revisão e95).** A leitura do banco roda numa thread própria e o scrape espera no máximo `PRAZO_COLETOR_S` (5 s), abaixo do `scrape_timeout` padrão do Prometheus (10 s). O prazo cobre também a espera por uma conexão do pool compartilhado da aplicação (`pool_timeout` de 30 s) e a abertura de uma conexão nova (`DB_CONNECT_TIMEOUT`, 10 s por padrão, mais longo que este prazo), que o teto por consulta não cobre. No PostgreSQL a transação do coletor é `READ ONLY` e cada consulta tem como teto o menor entre 3 s (`TETO_CONSULTA_MS`) e o que sobra do prazo total. Antes, cinco consultas esperando lock somavam até 15 s com `sync_coletor_sucesso 1`, e com o pool esgotado o scrape esperava os 30 s: o alvo inteiro caía (`up=0`), sumiam também as séries `http_*`, e a regra `sync_coletor_sucesso == 0` não disparava, porque a série ficava ausente.

Quando o prazo estoura, a leitura atrasada termina sozinha em segundo plano e fecha a própria sessão. Enquanto ela não termina, o scrape seguinte responde `sync_coletor_sucesso 0` na hora: há no máximo uma leitura do banco por processo, sem empilhar threads nem conexões. O coletor continua usando o pool da aplicação (uma conexão a mais só do coletor, com `pool_timeout` e `connect_timeout` curtos, é uma opção que custa uma conexão por worker no Supabase e fica para decisão do dono).

**Falha isolada.** Se o coletor falha (banco fora, consulta lenta, prazo estourado), o `/metrics` responde 200 com `sync_coletor_sucesso 0`, sem nenhuma série parcial do banco, e as outras métricas (`http_*`) saem normalmente. O log registra `metricas_sync_coletor_falhou: <classe do erro>` (`PrazoDoColetorEsgotado` e `LeituraAnteriorEmCurso` no caso do prazo). O traceback vai no máximo a cada 10 min.

## 2. Eventos contados no processo

São registrados num ponto único: o fim de `service.executar`, depois do commit.

| Série | Tipo | Rótulos |
|---|---|---|
| `sync_execucoes_finalizadas_total` | contador | `plataforma`, `status`, `motivo` (no `erro`, o motivo é o código da falha; sem motivo, `nenhum`) |
| `sync_execucao_duracao_segundos` | histograma (5 s a 1 h) | `plataforma`, `status` |
| `sync_alunos_aplicados_total` | contador | `plataforma` |
| `sync_falhas_unidade_total` | contador | `plataforma`, `unidade` (turma, lote, aluno, endpoint, arquivo), `codigo` |

**Limite com 2 workers (`WEB_CONCURRENCY=2`).** Estes contadores são de cada processo, como os `http_*`. Cada scrape vê o contador do worker que o atendeu. **Não use `rate()` nem `increase()` sobre `sync_*_total` com `WEB_CONCURRENCY` maior que 1**: os scrapes alternam entre workers e a regra de reinício de contador do Prometheus inventa eventos. A revisão e95 simulou 2 processos reais (7 e 2 execuções) e obteve um `increase()` de 415 em 1 h sem nenhuma execução. Por isso:
- **para alertar**, use as séries do banco (seção 1);
- **para contagem exata entre workers**, é preciso o modo multiprocesso do `prometheus_client` (`PROMETHEUS_MULTIPROC_DIR`). Isso é decisão de infraestrutura e não foi feito.

Execuções feitas fora dos workers da API nunca entram nestes contadores: por exemplo, a rodada por `executar_por_id` num processo à parte (o roteiro da sincronização manual da cerimônia). Elas aparecem só no estado do banco.

Execuções fechadas fora do `executar` não passam pelo ponto único: as órfãs finalizadas pelo reaper ou no boot e as canceladas na fila. Elas aparecem no estado do banco, em `sync_ultima_execucao_idade_segundos{status="erro"|"cancelada"}`.

## 3. Rótulos e dados pessoais

Os rótulos levam só o `escola_id` numérico e códigos. Um valor fora do padrão `[a-z0-9_]{1,40}` vira `outro`. Rótulos que colidem depois disso são somados numa série só, porque série repetida faria o Prometheus recusar o scrape.

O coletor não lê nomes, mensagens de alerta ou de log nem `erro_resumo`. A cifra da credencial é lida só para saber se ela abre (o status `ilegivel`): o texto claro não sai do `vault` e nenhum segredo vai para o `/metrics`. O teste `test_metrics_nao_expoe_nome_mensagem_nem_segredo` confere isso no corpo do `/metrics`.

## 4. Regras de alerta sugeridas (exemplos; nada foi configurado)

```promql
sync_coletor_sucesso == 0                                    # por 5 min: o /metrics não lê o banco
absent(sync_coletor_sucesso)                                 # a série sumiu (scrape falhou inteiro)
up{job="constela-api"} == 0                                  # o alvo caiu (ajuste o job ao seu Prometheus)
sync_execucoes_presas > 0                                    # execução presa
sync_ultimo_dado_aplicado_idade_segundos > 2 * 86400         # sem dado novo há 2 dias (LIMITE_FRESCOR_SEM_AGENDA)
(sync_credencial_status == 1)
  unless on(escola_id, plataforma) sync_ultimo_dado_aplicado_idade_segundos   # credencial que NUNCA aplicou dado
sync_alertas_abertos{severidade="critico"} > 0
sync_recalculo_pendente == 1
sync_credencial_status{status=~"invalida|expirada|ilegivel"} == 1
```

A regra de credencial inclui `ilegivel`: a senha salva não abre mais com as chaves do servidor e a integração só volta com o recadastro. Antes da rodada 3 do e97 essa credencial aparecia como `valida` e a regra só disparava depois de uma sincronização falhar e gravar `invalida`.

A regra de frescor (`> 2 * 86400`) não enxerga a integração que nunca aplicou dado (por exemplo, só erros desde o cadastro): a série `sync_ultimo_dado_aplicado_idade_segundos` não existe para ela. A regra com `unless` cobre esse caso (revisão e95).

O "em dia" (que fecha `desatualizada`) não é exposto de propósito: a regra está em revisão (decisão 1 do e94).

**Com as outras frentes da Etapa 3 juntas (ramo de teste `rev/etapa3`).** Nada muda nas séries; os valores novos saem com o próprio código, sem virar `outro` (teste `test_sync_etapa3_integracao.py`):
- forma C do "em dia" (`rev/em-dia-c`): o sinal confiável, lido do banco, é o `desatualizada` crítico em `sync_alertas_abertos`, que abre depois da cadência (só com agenda ativa com cadência). Nas séries lidas do banco, uma última execução `sem_atualizacao/tudo_em_revisao` é igual a uma `nada_mudou` (revisão e95). O motivo `tudo_em_revisao` aparece no contador `sync_execucoes_finalizadas_total{status="sem_atualizacao",motivo="tudo_em_revisao"}`, mas esse contador é por processo: com `WEB_CONCURRENCY` maior que 1 ele não serve para alerta (seção 2), e não conta as execuções fora dos workers. Uma série lida do banco com o estado e o motivo da última execução de cada integração (por exemplo `sync_ultima_execucao_info{escola_id,plataforma,status,motivo} 1`) daria o sinal na hora; fica como proposta para decisão do dono. O "em dia" continua sem série própria;
- escola externa (`rev/escola-cruzada`): os erros `conta_multiescola`, `escola_externa_trocada`, `escola_externa_em_outra_escola` e `escola_nao_identificada` aparecem como `motivo` no contador do `erro` e como `tipo` crítico em `sync_alertas_abertos`, assim como a revisão `identidade_de_outra_escola`. A regra `sync_alertas_abertos{severidade="critico"} > 0` já os cobre.
