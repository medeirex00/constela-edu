# Retenção, minimização e exclusão — o que o sistema faz (técnico)

Rodada de correção da auditoria de 20/10/2026 (frente Quest/push/exclusão). Este
documento descreve **mecanismos técnicos**. Não é parecer jurídico: os prazos, as bases
legais e o que o Município (controlador) exige são decisões do dono com assessoria
jurídica — a seção 5 lista as perguntas em aberto. Tudo o que foi criado aqui nasce
**desligado** ou com o **comportamento de antes**, exceto o que corrige vazamento
(exclusão permanente, push, hash do código do Quest).

Validação: local (SQLite + PostgreSQL 16 descartável). Nada disso foi aplicado em
produção.

---

## 1. O que já existia (inventário de prazos)

| Dado | Onde | Prazo hoje | Mecanismo |
|---|---|---|---|
| Cópias de relatórios (contêm nomes) | `exports/` | **7 dias** (`EXPORTS_RETENCAO_DIAS`; 0 desliga) | expurgo no boot e a cada hora (`core/expurgo_arquivos.py`), além de a cada nova exportação |
| Conversas do assistente de IA | `conversas_ia`, `mensagens_ia` | **90 dias** (`IA_RETENCAO_DIAS`; mínimo 1 — ao contrário das `RETENCAO_*`, 0 NÃO desliga: a purga recusa e não apaga nada, o boot com `ENV=producao` recusa e o de dev avisa no log) | no boot e por `python -m scripts.purgar_ia` (o que sai para o provedor externo e quem o liga: `ASSISTENTE-IA.md`) |
| Prévia de importação não confirmada | `uploads/temporarios/` | **24 h** (`IDADE_MAXIMA_TEMP_S`) | no boot e a cada hora (`core/expurgo_arquivos.py`), além de a cada nova análise de PDF/XLSX; some em até 25 h |
| Original de importação confirmada | `uploads/<plataforma>/` | **sem prazo** | — |
| Link de redefinição de senha | `tokens_reset_senha` (só o hash) | **60 min** (`RESET_SENHA_EXPIRA_MIN`), uso único | validade no token |
| Sessão do Edu (JWT) | navegador (`localStorage`) / celular (SecureStore) | **8 h** (`ACCESS_TOKEN_EXPIRE_MINUTES`) | expiração + `token_version` |
| Sessão do aluno no Quest (JWT) | memória do app (some ao fechar) | **30 dias** (`QUEST_SESSAO_DIAS`) | expiração + `token_version` do cartão |
| Log de auditoria | `logs_auditoria` | **permanente** (PRD §17) | — (ver 2.2) |
| Histórico de sincronização | `sincronizacao_execucoes`, `_logs`, `_alertas` | **permanente** | — (ver 2.2) |
| Avisos | `notificacoes` | **permanente** | — (ver 2.2) |
| Fila de revisão de identidade | `revisoes_identidade` | **permanente** (é a memória das decisões humanas) | — |
| Backup diário privado | repositório privado de backups | **14 dias** (decisão do dono, 13/10) | rotação dos artefatos |
| Backup do repositório público | artefatos antigos | desligado em 20/10 (`BACKUP_ENABLED=false`); os antigos expiram sozinhos | expiração do GitHub |
| Logs da aplicação | stdout → Railway (região sfo, EUA) | **do provedor** (a confirmar no plano contratado) | — |
| Erros | Sentry (EUA) | **do provedor** (a confirmar) | — |
| Push | Expo Push (EUA) → FCM/APNs | trânsito | — |

## 2. O que esta rodada criou

### 2.1 Minimização no log de auditoria — `AUDITORIA_MINIMIZAR_NOMES` (padrão `false`)

Em `app/services/audit.py`. Ligada (variável de ambiente, ou `registrar(..., minimizar=True)`
numa chamada), a entrada sobre um aluno identificado por `entidade_id` **deixa de gravar
o nome ATUAL dele** nas chaves de nome (`nome`, `aluno`, `nome_exibicao`, `apelido`,
`origem`, `origem_linha`, `nome_recebido`, em qualquer nível) — o id basta para chegar a
ele. Um nome que **difere** do cadastro (o da planilha, o recebido da plataforma, o
anterior) é a evidência do registro e **continua**.

Por que nasce desligada: muda o conteúdo da trilha de auditoria (decisão do dono) e há
efeitos colaterais conhecidos:

- o histórico de renomeação some: hoje `aluno.criado` guarda o nome inicial e
  `aluno.atualizado` o novo; com a minimização, nenhum dos dois guarda o nome (o
  anterior se perde). Se ligar, convém que `aluno.atualizado` passe a gravar
  `nome_anterior` (fora da posse desta frente: `routers/academico.py:431`);
- três testes de outras frentes afirmam o nome gravado e precisam ser ajustados ao
  ligar: `tests/test_esquecimento_nome_menor.py` (linhas 314 e 462) e
  `tests/test_import_casamento_roster.py:173`.

Já minimizado de vez (código do Quest): `quest.nome_escolhido` não grava mais o nome que
a criança escolheu (o valor vigente está no perfil e some com ele); `quest.avatar` (uma
entrada por toque no vestiário) grava só os `slots` trocados, não a aparência (tom de
pele, cabelo, acessórios) — antes guardava o avatar inteiro a cada toque; as entradas
antigas perdem o `avatar` na exclusão permanente da criança (seção 2.3); `quest.login` e
`quest.login_falhou` já mascaravam o IP e não gravam o código.

### 2.2 Expurgo por categoria — desligado (todos os prazos = 0)

`expurgar_retencao` em `app/services/audit.py` e o comando:

```
python -m scripts.expurgar_retencao --dry-run                       # só conta
python -m scripts.expurgar_retencao --dry-run --dias auditoria_quest=365
python -m scripts.expurgar_retencao --dias auditoria_quest=365      # apaga
```

| Categoria | O que entra | Variável (dias; 0 = desligado) |
|---|---|---|
| `auditoria_acesso` | `login`, `login.*`, `quest.login`, `quest.login_falhou` | `RETENCAO_AUDITORIA_ACESSO_DIAS` |
| `auditoria_quest` | `quest.*` que não é acesso | `RETENCAO_AUDITORIA_QUEST_DIAS` |
| `auditoria_alunos` | `aluno.*`, `matricula.*`, `identidade.*`, `revisao.*` | `RETENCAO_AUDITORIA_ALUNOS_DIAS` |
| `auditoria_demais` | todo o resto do log | `RETENCAO_AUDITORIA_DEMAIS_DIAS` |
| `sincronizacao_logs` | `sincronizacao_logs` | `RETENCAO_SINCRONIZACAO_LOGS_DIAS` |
| `notificacoes` | `notificacoes` | `RETENCAO_NOTIFICACOES_DIAS` |

Regras fixas do mecanismo (padrões técnicos, revisáveis com a decisão jurídica):

- as categorias do log são **disjuntas** (cada entrada cai em uma só);
- as provas do próprio esquecimento **nunca** entram: `aluno.excluido_permanente`,
  `aluno.esquecimento_fora_do_cadastro`, `ia.conversas_esquecimento`, `retencao.expurgo`,
  `turma.exclusao_com_alunos` e `backup.restaurado` (o mapa de ids das fichas que impede
  um backup antigo de trazer de volta a criança excluída; ver seção 2.3);
- `aluno.fundido` vencido **não é apagado**: fica reduzido à ligação entre as duas fichas
  (`{"mantido": {"id"}, "removido": {"id"}}`, sem nome, sem `foto_pre_fusao` nem o resto do
  detalhe; `audit.ACOES_REDUZIDAS`). É a prova de que as duas fichas são a mesma criança, que
  a restauração do backup, a exclusão permanente e a linha do tempo leem; apagada, o backup
  de antes da fusão trazia de volta a duplicata da criança excluída de vez. O resultado (e o
  `retencao.expurgo`) conta as reduções à parte;
- `auditoria_acesso` com prazo **menor que 183 dias** é recusado sem `--abaixo-do-piso`
  (referência: Marco Civil da Internet, art. 15 — guarda mínima de 6 meses de registros
  de acesso a aplicações; a aplicabilidade ao caso é pergunta jurídica, seção 5);
- o expurgo real grava `retencao.expurgo` com as contagens (sem dado pessoal);
- `--dry-run` não apaga nada; o resultado só traz contagens.

Os prazos podem morar nas variáveis acima (ambiente/`.env`) ou ser passados por
execução. Hoje as variáveis moram em `ConfigRetencao` (`app/services/audit.py`) por posse
de arquivo nesta rodada; o lugar natural é `app/core/config.py` (mesmos nomes).

Faxina técnica (não é política de retenção): `quest_limites_acesso` apaga sozinha os
contadores parados há mais de 1 dia e sem bloqueio vigente.

### 2.3 Exclusão permanente de aluno — o que acontece com cada dado

`POST /escolas/{id}/alunos/excluir-permanente` (e a exclusão de turma com alunos) →
`routers/academico._apagar_alunos_e_dados` + `services/exclusao_aluno.py`.

**Apagado**

- cadastro, matrículas, notas, leituras, snapshots Matific/Elefante, eventos da linha
  do tempo, identidades externas, Quest (perfil, credencial, progresso, tentativas),
  vínculos de responsáveis;
- avisos que apontam a criança (`notificacoes` por `aluno_id` ou `entidade`/`entidade_id`);
- conversas de IA que citam o nome, por **palavra inteira** (o `ILIKE` só pré-seleciona;
  `exclusao_aluno.conversas_ia_que_citam` decide). O nome dentro do nome **maior** de
  quem fica não conta (excluir "Joao Pedro Silva" não apaga a conversa sobre "Joao Pedro
  Silva Santos"); com homônimo vivo **exato** a conversa é apagada, como antes (não há
  como saber de qual das duas fala, e ela é do usuário, não da outra criança). Também
  pelo nome das fichas que ela absorveu por fusão (ver "Fichas absorvidas", abaixo);
- revisões de identidade **dela**: resolvidas para ela, da identidade externa dela
  (plataforma + id), ou com o nome dela quando **nenhuma outra criança da escola** tem
  o mesmo nome (com homônimo vivo, o nome também é do outro e a revisão fica);
- a conta dela no **cursor da coleta incremental** (`configuracoes`, namespace
  `sync_incremental`, uma linha por plataforma: `{id da conta: total}` — no Elefante,
  `{studentId: totalBooksRead}`), que o backup da escola leva inteiro
  (`exclusao_aluno._tirar_do_cursor_da_sincronizacao`). As contas das outras crianças
  ficam; sem a dela no cursor, a coleta seguinte só a buscaria inteira, como conta nova.
  A conta marcada como esquecida (ver "Marca de esquecimento", abaixo) volta ao cursor,
  sem a ficha, por dois caminhos: a coleta seguinte (a plataforma continua mandando a
  conta, e o cursor é gravado por mescla com o que já estava lá) e a restauração de um
  backup gerado antes da exclusão (o cursor volta do arquivo). Quem a tira do cursor
  já gravado é `exclusao_aluno.tirar_contas_esquecidas_do_cursor`: na sincronização,
  depois de gravar o cursor, com as marcas da própria escola (a regra da porta de
  identidade); na restauração, depois de recriar as configurações, com as marcas de
  qualquer escola (o arquivo pode ser de outra). Fora do cursor, a conta esquecida é
  buscada inteira a cada coleta e descartada pela porta de identidade (o custo de uma
  conta a mais na coleta).
  **Limite, enquanto as duas chamadas não entram:** a sincronização
  (`app/sync/service.py`) e a restauração (`services/backup.restaurar`) ainda não chamam
  essa função. Até lá, a coleta seguinte regrava a conta no cursor, a restauração de um
  backup anterior à exclusão a devolve (o id da conta na plataforma e o total de livros,
  sem nome nem ficha) e ela sai em todo backup seguinte. Os testes de ponta a ponta de
  `tests/test_aud3_lgpd_esquecimento_cursor_elefante.py` ficam em falha esperada até as
  chamadas entrarem e passam a exigi-las sozinhos depois; tirar este limite nesse dia;
- o arquivo original de um relatório **individual** dela (o nome do arquivo traz o nome
  dela, o arquivo foi gravado pelo servidor para esta escola e a importação não trouxe
  dado de criança que fica) e **todas** as cópias em `exports/` (não há como saber quais
  trazem o nome; o download nunca depende delas). Arquivos só somem **no commit** da
  transação: se a exclusão reverter, nada some.

**Anonimizado** (o nome vira `[removido]`, o resto do registro fica)

- log de auditoria: por valor (o nome, em qualquer chave/lista/frase) nas entradas
  **da escola**; das entradas **sem escola** (login, rede, avaliações, indicadores), só
  as da própria criança (`entidade = "aluno"` e o `entidade_id` dela) — quem exclui é a
  gestão de uma escola e não reescreve o log global; e por chave nas entradas da própria
  criança — agora também `nome_recebido` e o nome escolhido no Quest, que não tem pedaço
  do nome civil;
- log de auditoria das fichas que a criança **absorveu por fusão** (direta ou em cadeia,
  pelo log `aluno.fundido`): são dela, então as entradas com o id delas (como o
  `aluno.criado_auto` do stub da importação) contam como "da própria criança", e o nome
  delas (muitas vezes abreviado: "ANA B. SOUZA") cai também por valor, salvo quando é o
  nome de uma criança que continua na escola. Id de ficha absorvida que hoje é de uma
  ficha viva (id reaproveitado) fica de fora;
- dado pessoal que não é nome, nas entradas da própria criança e das fichas absorvidas:
  nascimento, observações, foto e a `ficha` (o RA) da `foto_pre_fusao`
  (`aluno.fundido`), as duas datas de `aluno.nascimento_divergente` e os valores dos
  itens de nascimento e de RA das `divergencias` de `aluno.fundido_com_conflito` viram
  `[removido]` (os itens ficam "nascimento [removido]" e "RA [removido]": o registro de
  que houve conflito continua, a data e o número saem); e o `avatar` inteiro das
  entradas `quest.avatar` gravadas antes da minimização do vestiário (seção 2.1) vira
  `[removido]` (a entrada, com a data da troca, fica);
- o RA da linha da Lista Piloto em `aluno.identidade_vinculada` (a importação o grava
  em todo vínculo que troca o nome, qualquer que seja o motivo) também vira
  `[removido]`: o log não guarda a via do casamento, então o número não prova ser o
  motivo da decisão. O `motivo` e a `origem` do vínculo continuam, como o "porquê
  técnico" do registro — ver `_anonimizar_logs_do_aluno`. Com isso, nenhuma entrada que
  o código grava hoje deixa o RA da criança em claro nas entradas dela;
- revisões de **outra** criança: a excluída — e a ficha que ela absorveu por fusão —
  sai da lista de candidatos; a candidata de quem **continua** (ficha existente) fica
  intacta, e a de outra ficha que não existe mais perde o nome se ele era o da excluída;
- mensagens de sincronização (`sincronizacao_logs`, `_alertas`, `_execucoes.erro_resumo`);
- `importacoes.arquivo_original` que trazia o nome;
- original que traz dado de criança que **fica** (é a prova da importação dela, §15):
  **renomeado** no disco, no commit, para `AAAAMMDD_HHMMSS_importacao-<id>.<ext>`, e a
  linha passa a apontar o novo nome — o conteúdo fica, o nome da excluída sai do disco e
  do banco.

Regra única para o texto (revisões, mensagens, `arquivo_original`): o trecho que é
também o nome — ou parte do nome — de uma criança que **continua** na escola não é
tocado. Excluir "Joao Pedro Silva" não mexe em "Joao Pedro Silva Testelli" nem no homônimo
vivo "Joao Pedro Silva".

**Fichas absorvidas por fusão** (`exclusao_aluno.fichas_absorvidas`, lidas uma vez, antes
de anonimizar o log de onde vêm os nomes): são a mesma criança. O nome que ela tinha
nelas — o do stub criado pela importação ou pela coleta, muitas vezes abreviado ("ANA B.
SOUZA") — é procurado em **tudo** acima como o nome dela: log de auditoria, revisões de
identidade, mensagens de sincronização, `arquivo_original` (e o arquivo) e conversas da
IA. Salvo quando esse nome é também o nome — ou parte do nome — de uma criança que
continua na escola (`exclusao_aluno.nomes_absorvidos_que_contam`, a mesma regra do log):
o stub "ANA SOUZA" não prova ser dela se "Ana Souza Lima" continua.

**Fica por obrigação de auditoria, sem nome**

- o log de auditoria, com o `entidade_id` como referência anônima — inclusive
  `aluno.excluido_permanente` (quem excluiu e quando),
  `aluno.esquecimento_fora_do_cadastro` (só contagens) e `backup.restaurado` (os mapas
  {id novo: id do arquivo} das fichas, turmas e importações recriadas —
  `alunos_id_anterior`, `turmas_id_anterior`, `importacoes_id_anterior` — e
  `referencias_reapontadas`, as contagens do que, fora do arquivo, foi ligado às linhas
  recriadas ou ficou sem equivalente; só números e contagens). Com esses mapas a
  restauração reaponta a fila de revisões de identidade e as execuções da sincronização
  para as linhas recriadas, também numa restauração seguinte;
- o registro de cada importação (quem, quando, quantos) e o histórico das sincronizações.

**Marca de esquecimento das contas da plataforma** (só a exclusão permanente de aluno;
a exclusão de turma com alunos não grava a marca)

- A conta da criança no Matific ou no Elefante Letrado continua existindo lá, e a coleta
  seguinte a manda de novo. Sem memória, ela era uma conta desconhecida: com a política
  padrão ("permitir") a ficha voltava inteira (nome, conta, retrato, ranking) e o log
  gravava o nome de novo; com "bloquear", o nome voltava para a fila de revisões e para
  o log.
- Agora o `aluno.excluido_permanente` de cada criança leva `contas_esquecidas`:
  `[{"plataforma", "marca"}]`, em que a marca é o HMAC-SHA256 do id externo com a chave
  do servidor (`exclusao_aluno.marca_da_conta`; a mesma família de chaves da cifra em
  repouso). Nem o nome nem o id da conta ficam em claro. Entram as contas vinculadas à
  ficha (inclusive a aposentada e as que ela absorveu por fusão) e, das revisões dela,
  só as que **provam** ser dela: a resolvida para ela e a pendência em que o motor achou
  a ficha dela como a única correspondência segura e só não associou por uma trava
  (`outra_identidade_na_plataforma` — a segunda conta que a coleta mandou para a fila —,
  `ficha_inativa`, `deixada_para_revisao`), sem nenhuma ficha que continua na escola
  entre os candidatos (`exclusao_aluno._donas_pela_pendencia`). A pendência que só tem o
  nome dela, com motivo de dúvida de identidade (`homonimo_em_outra_sala`,
  `nome_casa_em_outra_sala`, `candidatos_multiplos`, `correspondencia_insegura`,
  `criacao_bloqueada_por_politica`, `contas_repetidas_no_relatorio`, `sem_turma`…), é
  apagada (guarda o nome), mas a conta **não** entra: pode ser de outra criança, de
  mesmo nome e ainda sem ficha, que a marca tiraria das coletas para sempre. Conta
  vinculada a uma criança que continua na escola nunca entra.
- A porta única de identidade (`identidade_aluno.decidir`) ignora a linha de conta
  marcada antes de qualquer outro passo, com o motivo `conta_esquecida`: não associa,
  não cria ficha, não abre revisão. A marca vale na escola que excluiu.
- Limites: a linha **sem** a conta (relatório ou planilha só com o nome, como a Lista
  Piloto) não tem como ser reconhecida e pode cadastrar a criança de novo — o modal da
  exclusão avisa e pede o encerramento da conta na plataforma; a conta que estava só
  numa pendência de dúvida (acima) não é marcada — se era mesmo da criança excluída, a
  coleta seguinte a trata como conta nova (com "permitir", cria a ficha; com
  "bloquear", volta para a fila); exclusões feitas antes
  desta versão não têm a marca (as contas não foram guardadas); levantar a marca (a
  criança voltou à escola) ainda não tem ação própria — decisão do dono.
- Troca de chave: a marca gravada com uma chave só é reconhecida enquanto essa chave
  estiver no anel (`DATA_ENCRYPTION_KEY`, `DATA_ENCRYPTION_KEYS_ANTERIORES`, `SECRET_KEY`,
  `CHAVE_CIFRA_LEGADA_ANTERIOR`). O id em claro não existe mais para regravá-la: ver a
  seção 3.

**Fora do alcance do código** (precisa de procedimento ou decisão)

- backups já feitos (o dado excluído persiste até a rotação — 14 dias no privado). A
  restauração do backup JSON da escola pelo app (só o Admin Global) não traz de volta a
  criança excluída de vez depois do arquivo, nem os dados dela, e avisa quantas ficaram de
  fora (`backup.restaurar`, pelo `aluno.excluido_permanente` do log, feito em qualquer
  escola: vale também para o arquivo de uma escola restaurado em outra) — com uma
  exceção enquanto a restauração não chama `tirar_contas_esquecidas_do_cursor`: o id da
  conta dela na plataforma, com o total de livros, volta no cursor da coleta incremental
  (ver o limite do cursor, acima). Vale também para o
  arquivo gerado antes de outra restauração, que troca os ids das fichas: cada
  restauração grava em `backup.restaurado` o mapa {id novo: id do arquivo} (só números,
  preservado do expurgo) e a seguinte segue essa linhagem, gravada em qualquer escola
  (o arquivo de uma escola gerado antes de uma restauração dela e restaurado em outra
  também não traz a criança de volta). A ficha que o arquivo de uma escola criou em outra
  é a mesma criança: excluída de vez uma delas, a outra não volta com o backup de
  nenhuma das duas escolas gerado ANTES da exclusão (o aviso diz "nesta ou em outra
  escola"); o backup gerado depois dela traz a ficha viva da outra escola como estava (o
  "depois" do arquivo é medido no log inteiro, de qualquer escola). A ficha viva da outra
  escola não é apagada pela exclusão — exclua-a lá também. Ressalva:
  restauração feita antes desse mapa existir (ou com o registro apagado) quebra a
  linhagem — a criança excluída depois dela pode voltar, sem aviso; confira a exclusão
  manualmente. A restauração também não traz de volta a ficha que foi **fundida** na
  criança excluída de vez (a duplicata absorvida é a mesma criança): nos dois sentidos da
  fusão e também em outra escola, pela ligação do `aluno.fundido` no log; o aviso conta
  **crianças**, não fichas (a duplicata fundida e a oficial do mesmo arquivo são uma só).
  O arquivo leva `importacoes.usuario_id` (o id de quem importou): volta como veio se o
  usuário existe e vira NULL se não existe mais, como `identidades_externas.aposentada_por_id`.
  O texto que o
  arquivo guarda fora das tabelas da criança (ex.: `importacoes.arquivo_original` de um
  relatório individual antigo) volta como estava no arquivo;
- originais de relatório de **turma** (várias crianças no mesmo PDF/XLSX): ficam (com o
  conteúdo; só o nome do arquivo é tratado, como acima);
- original cujo caminho **outra escola** também registra: o arquivo não é apagado nem
  renomeado (pode ser dela — `arquivo_original` também guarda o nome que o cliente
  mandou — e o `/confirmar` não marca qual linha o servidor gravou); só a linha desta
  escola fica `[removido]`. O arquivo fica no disco com o nome. Pergunta 9 da seção 5;
- prévias não confirmadas em `uploads/temporarios/` (expiram em 24 h; o expurgo de fundo as apaga em até 25 h);
- logs da aplicação (Railway) e eventos do Sentry;
- cópias fora do sistema (downloads, e-mail) e a **plataforma de origem**: a conta
  continua ativa lá até ser encerrada. O Constela passa a ignorá-la nas coletas (marca
  de esquecimento, acima), mas não a encerra.

Teste: `tests/test_exclusao_alcance_total.py` varre **todas** as tabelas e colunas de
texto/JSON depois da exclusão (dados fictícios) e falha se sobrar o nome ou o id;
`tests/test_aud3_lgpd_esquecimento_cursor_elefante.py` (e o `_pg`) faz o mesmo com o id
da conta do Elefante (cursor e backup, também depois da coleta seguinte e da restauração
de um backup anterior à exclusão) e `tests/test_aud3_lgpd_esquecimento_absorvida_fora_do_log.py`
com o nome da ficha absorvida por fusão;
`tests/test_exclusao_escopo_e_homonimos.py` prova que o esquecimento não passa do que
é da criança (log global, homônimo e nome maior de quem fica, conversas da IA,
original de outra escola, original com dado de quem fica);
`tests/test_aud2_lgpd_esquecimento_conta.py` (e o `_pg`, com a exclusão chegando no meio
de uma coleta) prova que a coleta seguinte não traz a criança de volta, com "permitir" e
com "bloquear", nem pela segunda conta que estava na fila; e
`tests/test_aud2_lgpd_esquecimento_homonima.py` prova que a conta de outra criança, de
mesmo nome e na fila por dúvida, não é marcada junto (a coleta seguinte cria a ficha
dela).

### 2.4 Quest — código de login, limite de tentativas e portão

- **Código com hash (0037).** O login procura `codigo_login_hash` = HMAC-SHA256 do código
  normalizado com chave do servidor (`DATA_ENCRYPTION_KEY` se definida, senão
  `SECRET_KEY`; a outra fica só para conferir hashes antigos) e confere com
  `hmac.compare_digest`. Backfill a partir do texto na própria migração: todo cartão já
  impresso continua entrando. Limite do desenho: com ~1,3×10^5 códigos possíveis, quem
  tiver o banco **e** a chave recupera qualquer código.
- **QR com hash (0037).** O QR do cartão é a mesma credencial em outra forma: o
  `/quest/auth/entrar-qr` procura `qr_token_hash` = SHA-256 do token (sem chave: o token
  tem ~192 bits, não se recupera do hash por tentativa), com backfill na migração — todo
  QR impresso continua entrando.
- **As colunas em texto `codigo_login` e `qr_token` CONTINUAM** (pedido do dono: só
  remover depois da troca confirmada). **Enquanto elas existirem, quem tiver só o banco
  (dump, backup, réplica) ainda entra na conta de qualquer criança** — pelo código ou
  pelo QR: o ganho em repouso só se realiza depois do passo de remoção abaixo, que vale
  para as duas. Na transição o texto é a verdade e o hash é o índice (o login confere os
  dois; ver `_FALLBACK_TEXTO_CLARO`). Cada uma é lida em um ponto só:
  `codigo_para_exibicao` (PDF dos cartões, página "só do professor" nome → código e o
  `codigo_login` de `GET /escolas/{id}/quest/turmas/{t}/acessos` e do perfil do aluno —
  este último não é usado por nenhum app hoje) e `url_qr` (a URL impressa no QR).
- **Limite persistente.** `quest_limites_acesso`: por código, por código+IP, por IP
  (revelação de nome), anti-enumeração por IP e **global** (revisão e97), com bloqueio
  temporário que vale entre workers e sobrevive ao restart. Chaves são HMAC (nem IP nem
  código digitado em texto).
  - **Login do Edu (desde 31/10/2026).** A mesma tabela guarda os tetos de falhas do
    `/auth/login` do Edu, em dimensões próprias: `edu_login_ip_falha` (chave = HMAC do
    IP de quem tentou entrar — adultos da escola e da rede —, com o IPv6 contado pela
    rede /64) e `edu_login_global_falha` (um contador só para a API inteira, sem IP).
    Mesma faxina técnica: o contador parado há mais de 1 dia e sem bloqueio vigente é
    apagado sozinho. Teto e janela em `docs/lgpd/SESSAO-E-MFA.md` §1.1.
  - **IPv6 por rede.** Nas dimensões por IP, o IPv6 conta pela rede /64
    (`QUEST_LIMITE_PREFIXO_IPV6`, padrão 64, faixa 32–128): um /64 é o que o provedor
    entrega a um assinante, e contar por endereço deixava trocar de "IP" a cada
    palpite. IPv4 segue por endereço (as chaves já gravadas continuam valendo).
  - **Aluno inativo conta, uma vez por cartão.** O 403 ("cartão descansando") no
    `/quem` e no `/entrar` deixou de ser um oráculo de existência grátis:
    - no **código+IP** conta em todo toque: o 9º toque do mesmo cartão no mesmo IP em
      5 min já recebe "Ufa, quantas tentativas" (429);
    - no **anti-enumeração por IP** (teto 50 em 5 min) e no **global** conta só o
      **primeiro** 403 de cada (código, IP) na janela do código+IP — os toques
      repetidos do mesmo cartão não somam (não revelam nada novo). Quem varre
      códigos **diferentes** continua pagando 1 por código, como no código
      inexistente: 60 cartões inativos distintos do mesmo IP esgotam o teto.
    - Efeito no NAT da escola: 7 crianças inativas tocando 8 vezes cada gastam 7 do
      teto do IP (antes, 56 — passava de 50 e travava a sala inteira, inclusive o QR
      dos colegas). Os colegas ativos seguem entrando.
  - **Teto global.** As falhas do login por código (código inexistente e o primeiro
    403 de cada cartão inativo por IP) de TODOS os IPs somam numa chave só. Ao chegar a
    `QUEST_LIMITE_GLOBAL_FALHAS` (padrão 400) em `QUEST_LIMITE_GLOBAL_JANELA_S`
    (padrão 300 s), o `/quem` e o `/entrar` respondem 429 para todo mundo até o fim
    do bloqueio (checado antes de procurar o código: mesma resposta para código
    válido ou não) e sai no log um alerta `quest_limite_global_atingido` (campo
    `evento=quest.limite_global_atingido`, nível warn, um por janela por processo,
    sem IP nem código).
  - **Trade-off do teto global (aceito).** Sob ataque, as crianças também esperam:
    quem sustenta ~400 falhas a cada 5 min mantém o login por **código** suspenso
    enquanto durar o ataque. Limites do dano: só falhas contam (login certo não), o
    429 não realimenta o contador, o padrão fica muito acima das falhas de uso real
    (erros de digitação de várias turmas ao mesmo tempo) e o **QR do cartão**
    (`/entrar-qr`, ~192 bits, não adivinhável) fica fora do teto global e segue
    entrando. Alternativa recusada: liberar durante o bloqueio os IPs com login
    recente — um único código válido conhecido "carimbaria" IPs novos e anularia o
    teto.
  - **Risco residual.** O teto global limita a VAZÃO, não fecha a enumeração: no teto,
    são até ~115 mil palpites por dia somando todos os IPs (com 1.500 cartões ativos,
    da ordem de mil contas por dia para um atacante paciente — que, ao mesmo tempo,
    derruba o login por código). O fechamento estrutural é mudar o formato ou o fator
    (2 palavras + 4 dígitos, já aceito para cartões antigos, ou exigir o código da
    turma/escola junto) — decisão de produto, não feita aqui.
- **Portão `QUEST_ALUNO_HABILITADO`** (padrão `true` = como hoje; **o padrão NÃO mudou**
  na revisão e97, por decisão do dono). Com `false`, `/quest/auth/*`, `/quest/perfil*` e
  `/quest/conquistas` respondem 404 igual a rota inexistente; os cartões do professor
  continuam. **Recomendação (reforçada pela revisão e97):** `false` em produção enquanto
  o app do aluno não estiver publicado — é a única medida que tira a superfície de
  enumeração da internet; os limites acima só reduzem a vazão. Mora em
  `app/quest/config.py` por posse de arquivo; o lugar natural é `Settings`.

#### Decisão necessária antes de remover as colunas em texto

A tela precisa MOSTRAR o código e o QR (cartão impresso e página do professor). Opções,
valendo para os dois:

- **A — regenerar ao imprimir.** Nenhum texto guardado; cada impressão gera código novo
  (mostrado só no PDF daquele momento). Mais seguro; a criança perde o código decorado a
  cada reimpressão e a página do professor não consegue mostrar o código depois.
- **B — cópia cifrada para exibição.** `codigo_login_cifrado` com o Fernet que já cifra os
  segredos em repouso (`app.core.security.cifrar_segredo`), lido só para imprimir; o
  login segue pelo HMAC. Mantém o fluxo atual (reimpressão com o mesmo código); quem tem
  banco + chave lê os códigos (igual ao HMAC, dado o espaço pequeno).

#### Passo de remoção futura (não executado)

1. Dono decide A ou B; implementar a exibição em `codigo_para_exibicao`/`definir_codigo`
   e em `url_qr`/`definir_qr_token`.
2. Em produção: `contar_hashes_divergentes(db) == 0` (todas as credenciais autenticam
   pelo hash, por código e por QR); se não, `preencher_hashes_ausentes(db)` e commit.
3. Definir `DATA_ENCRYPTION_KEY` **antes** (o hash passa a não depender da `SECRET_KEY`
   dos JWT; sem o texto, trocar a chave primária sem a antiga na lista invalida todos os
   cartões). A lista existe: `DATA_ENCRYPTION_KEYS_ANTERIORES` e
   `CHAVE_CIFRA_LEGADA_ANTERIOR` conferem o hash e o login o regrava na primária;
   `python -m scripts.recifrar_segredos --executar` regrava todos de uma vez. Faça a
   conferência do passo 2 **sem** chaves anteriores configuradas (com elas, o hash de
   uma anterior conta como válido).
4. Ajustar a restauração de backup para recalcular o hash (backups anteriores à 0037 só
   têm o texto).
5. Desligar `_FALLBACK_TEXTO_CLARO` em `app/quest/services/credenciais.py` e, numa
   migração nova, remover `codigo_login` e `qr_token` (e os índices únicos delas).

### 2.5 Push

O aviso "dados da plataforma atualizados" (resolução de pendência de identidade) levava
o nome completo da criança para a tela bloqueada do celular, via Expo/FCM/APNs. Agora
leva só o primeiro nome (`push.corpo_dados_atualizados`; sem nome: "Um aluno ...").

## 3. Procedimentos em produção (não executados)

- **Ligar um prazo**: rodar antes `python -m scripts.expurgar_retencao --dry-run --dias
  <categoria>=<N>` e conferir as contagens; depois definir a variável e agendar o
  comando (Railway Cron ou equivalente). Sem decisão jurídica, não ligar.
- **Portão do Quest**: `QUEST_ALUNO_HABILITADO=false` no serviço da API e reiniciar.
- **Alerta `quest_limite_global_atingido` no log**: há varredura distribuída do código
  do Quest e o login por código está suspenso até o fim da janela (o QR segue). Se o
  alerta se repetir janela após janela, desligar o portão acima é a resposta que
  encerra a exposição; subir `QUEST_LIMITE_GLOBAL_FALHAS` só faz sentido se o alerta
  vier de uso real (muitas turmas errando ao mesmo tempo), nunca para "destravar"
  durante um ataque.
- **Migração 0037**: aplica no boot (ENV ausente = dev) como as demais; em produção o
  backfill usa a chave do próprio serviço. Conferir depois:
  `SELECT count(*) FROM quest_credenciais_aluno WHERE codigo_login_hash IS NULL OR
  qr_token_hash IS NULL` = 0.
- **Troca de chave × contas esquecidas**: ao girar `DATA_ENCRYPTION_KEY` (ou a
  `SECRET_KEY`), mantenha a anterior no anel (`DATA_ENCRYPTION_KEYS_ANTERIORES` /
  `CHAVE_CIFRA_LEGADA_ANTERIOR`) enquanto houver `aluno.excluido_permanente` com
  `contas_esquecidas` gravado com ela. Tirar a chave do anel apaga, em silêncio, a
  memória dessas contas: a coleta seguinte volta a tratá-las como contas novas.

## 4. O que NÃO foi feito (e por quê)

- Nenhum prazo foi ligado e a minimização global ficou desligada: decisão jurídica/do
  dono.
- A coluna `codigo_login` não foi removida: pedido explícito (aguardar a confirmação).
- O Quest não foi desligado: decisão do dono (há a configuração).
- Backups, logs do provedor e Sentry não têm expurgo pelo app: estão fora do banco.

## 5. Decisões jurídicas pendentes (perguntas ao dono / assessoria)

1. **Prazos por categoria.** Quanto tempo guardar cada categoria da tabela 2.2? Os
   registros de acesso (login) têm referência de guarda mínima de 6 meses no Marco Civil
   (art. 15, para provedor de aplicação que atua com fins econômicos): vale para o
   Constela como operador do Município? Há prazo máximo?
2. **Temporalidade de documentos públicos × eliminação em 60 dias da minuta.** Dados de
   rede municipal de ensino podem ser documento público sujeito à tabela de
   temporalidade do Município (Lei 8.159/1991 e normas locais). A minuta de contrato
   (Anexo II, LGPD) prevê eliminação em 60 dias ao fim do contrato. Quem guarda o quê:
   o Município recebe uma exportação antes da eliminação? O log de auditoria é
   documento do Município a ser entregue, e não eliminado?
3. **Exclusão permanente × guarda escolar.** A exclusão física é irreversível. O registro
   escolar oficial da criança vive em outro sistema (o Constela não é o sistema de
   registro)? Se não, a exclusão pode conflitar com obrigação de guarda.
4. **Backups × pedido de exclusão.** O dado excluído persiste até 14 dias no backup
   privado. Aceitável, ou é preciso procedimento de exclusão também nos backups?
5. **Minimização global.** Ligar `AUDITORIA_MINIMIZAR_NOMES` (perde-se o histórico de
   nomes do log; ver 2.1)?
6. **Transferência internacional.** API (Railway, EUA), Sentry (EUA) e Expo Push (EUA)
   recebem dados (inclusive o primeiro nome no push e o IP mascarado nos logs). Precisa
   constar do Anexo II como suboperadores com país e base (LGPD art. 33)?
7. **Originais de relatório de turma.** Guardar para sempre (prova da importação, §15) ou
   com prazo? Na exclusão de uma criança, eles ficam (várias crianças no mesmo arquivo).
8. **Quest em produção.** Desligar as rotas do aluno até o app ser publicado?
9. **Original apontado por duas escolas.** Hoje o arquivo não é apagado nem renomeado
   (fica no disco com o nome da excluída, sem ponteiro desta escola) porque não há como
   provar de quem é. Marcar no `/confirmar` o caminho gerado pelo servidor (coluna ou
   flag em `importacoes`, fora desta frente) permitiria tratar o arquivo da escola
   dona e ignorar a linha de outra escola. Vale a mudança?
10. **Log de auditoria da escola × nome de quem fica.** O critério por valor do log
   (`academico._anonimizar_logs_do_aluno`) redige o valor inteiro que contém o nome
   excluído, inclusive o nome **maior** de uma criança que continua ("Joao Pedro Silva
   Santos" ao excluir "Joao Pedro Silva") e o homônimo vivo (troca assumida no código
   para o homônimo adulto). As revisões, as mensagens e as conversas já preservam o nome
   maior de quem fica. Aplicar a mesma regra ao log (perde-se menos auditoria de quem
   fica; o homônimo exato continua redigido)?
