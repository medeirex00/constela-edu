# Coleta das plataformas (Matific e Elefante Letrado) — operação

Documento de OPERAÇÃO: o que a coleta automática faz de verdade, onde ela
falha, o que a escola vê em cada caso, o que fazer, e como validar uma coleta
para uma demonstração. A arquitetura do módulo está em `docs/SINCRONIZACAO.md`.

Estado em 20/10/2026 (consultas só de leitura, agregadas): agendador
**desligado** em produção (`SYNC_SCHEDULER_ENABLED=false`) desde 17/09 — desde
então só há coletas MANUAIS ("Sincronizar agora"). 5 escolas têm plataforma
configurada; as outras 23 não.

---

## 1. Como a coleta funciona

| Plataforma | Como o Constela obtém | Natureza do número |
|---|---|---|
| Elefante Letrado | login no painel do gestor (navegador Playwright) e leitura da **API interna** do painel: relatório por turma (`overall-course-report`) + livros lidos por aluno com data (`overall-student-books-read`) | livros/tempo/questões: **acumulado** do aluno; cada livro com a data da última leitura (`lastReadWhen`) |
| Matific | login no portal do professor (navegador) e leitura da **API interna** do Placar da Escola (`school_student`, `duration=this-year` ou `start_date`/`end_date`) | atividades/estrelas: **acumulado do ano** (`this-year`) ou do **intervalo** pedido |

Nenhuma das duas tem API pública de saída de dados. As APIs internas não são
contrato: podem mudar sem aviso (o `Diagnóstico do Elefante` e os logs avisam).

## 2. Limitações reais (e o que NÃO fazemos)

### 2.1 reCAPTCHA do Matific a partir de IP de datacenter

O login do Matific é protegido por **reCAPTCHA v3**, que pontua a sessão pela
reputação do IP e por sinais de automação. A API do Constela roda no Railway,
região **sfo (EUA)**: IP de datacenter, longe do Brasil. Consequências:

* o login pode ser **recusado com credencial correta** — e a mensagem da
  plataforma é a mesma de senha errada (o conector não consegue distinguir);
* pode aparecer um desafio (CAPTCHA) que a automação **não resolve**.

**O Constela não contorna essa proteção.** Não usamos serviço de resolução de
CAPTCHA, proxy residencial/móvel para "subir o score", nem técnicas para se
passar por pessoa. Em particular:

* `SYNC_PROXY_URL` (config, vazio por padrão) existe no código com a finalidade
  declarada de passar o reCAPTCHA saindo por IP residencial — **deve continuar
  vazio**. A mensagem de erro do login deixou de recomendá-lo (20/10/2026).
* O navegador do robô sobe com sinais de automação escondidos
  (`navigator.webdriver` e `--disable-blink-features=AutomationControlled`, em
  `backend/app/sync/connectors/navegador.py`). **Pergunta aberta ao dono**:
  remover esses dois ajustes (pode afetar o login do Elefante, que hoje funciona)
  ou mantê-los como estão. Não foram alterados nesta rodada.

Como reconhecer: a escola consegue entrar no Matific pelo navegador dela com o
mesmo usuário e senha, mas a validação no Constela falha com "senha inválida"
ou "bloqueio anti-robô da plataforma".

### 2.2 Outras limitações conhecidas

* **APIs internas não-oficiais** (Matific e Elefante): mudança de página/endpoint
  vira falha de "indisponibilidade externa" ou "formato do relatório mudou".
* **Elefante — agregado parado**: o total de livros do relatório de turma pode
  ficar parado enquanto o detalhe por aluno já tem livro novo. Por isso, a cada
  7 dias a coleta ignora o cursor e recoleta tudo (`DIAS_ENTRE_COLETAS_COMPLETAS`).
* **Elefante — livros por aluno com a plataforma lenta**: os livros de uma turma
  saem em lotes de até 6 pedidos ao mesmo tempo, e o prazo de 20 s conta da saída
  de cada pedido (antes, os últimos de uma turma grande eram abortados sem nem ter
  saído). O custo, no pior caso: com a plataforma aceitando a conexão e sem
  responder, uma turma de 40 alunos leva cerca de 7 × 20 s = 140 s para falhar
  (antes, cerca de 20 s), e uma recoleta completa com umas 15 turmas grandes, cerca
  de 35 min, perto do teto de 45 min (`SYNC_TETO_EXECUCAO_S`), segurando a vaga das
  coletas manuais nesse tempo. Não há prazo total por lote: escolhê-lo exige medir a
  latência e o protocolo (HTTP/1.1 ou HTTP/2) reais do Elefante — um prazo curto
  cortaria alunos de uma plataforma só lenta que hoje chegam.
* **Matific — semântica do período**: se `end_date` é inclusivo ou exclusivo não
  foi confirmado na plataforma; a importação por período data o retrato na véspera
  da data final (regra do importador, fora do módulo de sync).
* **Matific — acumulado que cai**: ver §5 (trava contra queda).
* **Contas com SSO (Google) ou verificação em duas etapas**: a automação não
  completa. Use uma conta dedicada da escola, com senha direta e sem 2FA, criada
  com o conhecimento da escola.
* **Agendador desligado**: nada roda sozinho; a escola vê "pausada no servidor".

## 3. O que a escola vê (tela Integrações) e o que fazer

Estados do selo de cada plataforma (`apps/web/src/components/StatusIntegracao.tsx`;
os campos vêm de `GET /escolas/{id}/sync/status`). **Falha nunca aparece como
sucesso**, e "última tentativa" é diferente de "último sucesso".

| Selo | Quando | O que fazer |
|---|---|---|
| **Atualizado** | última tentativa concluída **com dados** e último sucesso dentro do limite (2 dias na diária/manual, 10 na semanal) | nada |
| **Dados desatualizados (N dias)** | último sucesso mais velho que o limite (com ou sem agenda), ou agenda ativa há dias sem sucesso algum | "Sincronizar"; se a agenda está **pausada no servidor**, é o agendador desligado — não é problema da escola |
| **Sem dados na última coleta** | a última tentativa terminou sem nenhuma linha (relatório vazio/incompleto) | conferir na plataforma se as turmas têm atividade; enviar relatório manual |
| **Falhou: …** (acesso) | a plataforma recusou usuário/senha, conta pede 2FA/SSO | corrigir em "Configurar conexão"; ver §2.1 se a senha funciona no navegador |
| **Falhou: …** (plataforma) | não respondeu, demorou, mudou a página, bloqueio anti-robô, escola não localizada | tentar mais tarde; enviar o relatório manualmente |
| **Falhou: erro ao processar** | o relatório chegou e o Constela falhou ao processar (ou a execução foi interrompida) | tentar de novo; copiar o detalhe técnico para o suporte |
| **Coleta indisponível neste servidor** | o servidor não tem navegador para o robô | enviar o relatório manualmente; avisar o suporte |
| **Conexão não validada** | acesso salvo e não testado, ou a validação não terminou (página/navegador) — **não** é "senha recusada" | "Testar conexão" mais tarde |
| **Sincronizando** | execução em andamento que vai rodar | aguardar (a tela atualiza sozinha) |
| **Ainda não configurada / Sem dados ainda** | sem credencial / conectada sem nenhuma tentativa | configurar / "Sincronizar" |

Alertas (lista "Erros" do card) — mapa único em `backend/app/sync/service.py`
(`ALERTA_POR_CODIGO`, `CATEGORIA_POR_TIPO`):

| Tipo | Categoria | Fecha quando |
|---|---|---|
| `senha_invalida`, `senha_expirada`, `falha_autenticacao`, `mfa` | acesso | um login funciona (validar credencial ou execução sem erro) |
| `pagina_login`, `captcha`, `erro_navegador`, `sem_escola`, `falha_download`, `timeout` | plataforma | uma execução conclui com dados (acesso: também ao validar) |
| `erro_inesperado`, `parser_incompativel`, `interrompida` | processamento | uma execução conclui com dados |
| `plataforma_indisponivel` | servidor | uma execução conclui com dados |
| `desatualizada` | aviso | o dado volta a estar em dia, ou a agenda é desligada |
| `lento` | aviso | uma execução **termina dentro do normal** — concluída, ou sem atualização (coleta inteira sem nada novo): até 2× a mediana das últimas execuções concluídas da integração, nunca menos que `SYNC_LENTO_S` (120 s); com menos de 5 concluídas no histórico, vale só os 120 s. Só a concluída abre o aviso |
| `queda_matific` | revisão | uma coleta acumulada não encontra mais queda |

Os alertas abertos desde julho/agosto em produção (`erro_navegador`,
`falha_autenticacao`, `interrompida`) fecham sozinhos na primeira execução
bem-sucedida da integração depois do deploy. Não é preciso mexer no banco.
O `lento` **não** fecha com qualquer sucesso: só quando uma execução concluída ou
sem atualização termina dentro do limite da linha acima. Numa integração do Elefante com pouco histórico
(menos de 5 execuções concluídas) o limite é de 120 s e uma coleta completa leva
minutos — o aviso pode continuar aberto depois das primeiras coletas, até o
histórico formar a mediana. Não é falha da escola.

## 4. Alternativas legítimas quando a coleta automática não funciona

1. **Exportação oficial pela escola** → Constela › Importações (com prévia):
   Matific — planilha/relatório do Placar exportado pelo professor; Elefante —
   relatório de turma ou relatórios individuais (PDF). É o caminho padrão para a
   demonstração quando o robô estiver bloqueado.
2. **Contato com o fornecedor**: pedir acesso oficial aos dados (Matific: saída
   de dados por contrato distrital/enterprise com chave de API; Elefante: API ou
   exportação oficial). Com API oficial, troca-se o conector — o resto do sistema
   não muda (`Estrategia.API_OFICIAL`).
3. **Conta dedicada da escola** com senha direta e sem 2FA, autorizada pela escola.

## 5. Matific: trava contra queda do acumulado

`duration=this-year` é contador do ano: só sobe. Na coleta automática, se o
total novo de **atividades ou estrelas** de um aluno com identidade Matific já
vinculada for **menor** que o do retrato atual do mesmo ano (ver "Virada
legítima" abaixo), a linha **não é aplicada** (`orchestrator.reter_quedas_matific`):

* o valor gravado fica; a auditoria registra `sync.matific_queda_retida` (id do
  aluno, gravado × recebido; sem nome);
* abre o alerta `queda_matific` (revisão humana), que fecha quando a plataforma
  voltar a mandar o acumulado certo.

**Virada legítima**: só conta como base de comparação o retrato que está, ao
mesmo tempo, no ano letivo ativo da escola **e** no ano civil da coleta (relógio
de Brasília — o ano do "this-year" do Matific). O primeiro do ano novo entra
normalmente mesmo que a escola ainda esteja com o ano letivo anterior (janeiro,
antes de a gestão virar o ano): antes, o retrato de dezembro servia de base e a
escola inteira ficava retida. Uma correção real da plataforma dentro do
ano é aceita pela **importação manual** do relatório oficial (com prévia). Coleta
por período (start/end) não é conferida (números do intervalo). Limitação: linha
ainda sem UUID vinculado não é conferida. Se o Matific zerar o acumulado no meio
do ano letivo da escola (ex.: virada em fevereiro), todos os alunos ficam retidos
até a importação manual — **pergunta ao dono** se quer uma data de virada
configurável.

## 6. Fila, repetição e agendador desligado

* Com o agendador **desligado**, uma falha recuperável **não** deixa nova
  tentativa na fila (ela nunca rodaria): a execução termina em "erro" e o log diz
  "Sem nova tentativa automática". Com ele ligado, segue o backoff de sempre.
* "Sincronizar agora" **assume** uma execução que está na fila esperando o
  agendador (nova tentativa, agendada, manual órfã): cancela-a com registro
  no log ("Substituída por um pedido manual…") e entra com os parâmetros pedidos
  (ex.: datas do período). Clique repetido do mesmo pedido é deduplicado; pedido
  **explícito** de uma plataforma (ou de um período) durante uma execução dela em
  andamento com outro pedido responde 409. No "Sincronizar agora" de **todas**, a
  plataforma ocupada fica de fora e as demais seguem (o Elefante sincroniza
  enquanto o Matific coleta um período); só se todas estiverem ocupadas a
  resposta é 409.
* Órfãs: no boot e na leitura do status, com o agendador desligado, execuções que
  só ele rodaria são canceladas com registro. Uma **manual** só é órfã quando
  ninguém mais espera por ela: sem thread no processo e sem **sinal de vida** há
  mais de 60 min (`SYNC_TRAVADA_S`). Enquanto espera a vez (um processo roda uma
  coleta manual por vez), a thread grava a cada 10 min no log da execução
  "Aguardando a vez: … (N min na fila)" — é isso que os outros workers leem. A
  idade da fila sozinha não cancela nada: um pedido esperando atrás de coletas
  completas do Elefante roda quando chegar a vez. Execução em "executando" sem
  nenhum registro no log há mais de 15 min (`SYNC_SEM_SINAL_S`) é liberada no
  boot, na leitura do status e pelo próximo pedido manual; a viva grava "Em
  andamento: …" no log a cada ~2,5 min e não é tocada, por mais longa que seja.

## 7. Fuso: o que mudou e o impacto em dados antigos

Regra: **negócio em America/Sao_Paulo, armazenamento em UTC**
(`backend/app/sync/fuso.py`).

* **Agenda**: "03:00" agora é 03:00 em Brasília (06:00 UTC). Antes rodava às
  03:00 UTC = meia-noite em Brasília. A `proxima_execucao` das agendas paradas em
  18–23/09 foi calculada pela regra antiga e **não se recalcula sozinha antes de
  religar**: o pré-requisito `fuso_da_agenda` (`backend/app/sync/prerequisitos.py`)
  recusa subir o agendador enquanto houver agenda desalinhada. Re-salve cada agenda
  ativa na tela Integrações antes de religar (salvar recalcula a data). Depois de
  ligado, a agenda vencida há mais que a própria cadência (1 dia na diária, 7 na
  semanal) só ganha a próxima data, sem enfileirar.
* **Elefante, `endPeriodCustom`**: usa o "hoje" de Brasília (era a data UTC).
  Inócuo para os dados (o período é LIFETIME), corrigido por consistência.
* **Elefante, dia da leitura (`lastReadWhen`)**: a convenção de `Leitura.data` é o
  horário de PAREDE de Brasília (é o que o relatório individual do upload manual
  traz). Data **sem fuso** (o formato visto nas capturas, `2026-06-26T08:59:43`,
  com o pedido indo com `timezoneOffset=180`) passa intacta. Data **com fuso**
  (`Z`/`+00:00`) agora é convertida para Brasília — antes o importador descartava
  o fuso e guardava o relógio UTC, e uma leitura das 21h–24h caía no dia
  seguinte. Quando isso acontece, o log da execução avisa ("N data(s) de leitura
  vieram com fuso explícito…").
  * **Dados antigos**: se esse aviso aparecer para uma escola, as leituras dela
    importadas antes podem ter o dia deslocado. Como medir (SÓ LEITURA): o
    histograma de `EXTRACT(HOUR FROM data)` das leituras da escola — pico entre 13h
    e 20h indica relógio UTC (aula 10h–17h); pico entre 10h e 17h, Brasília.
  * **Recalcular (NÃO executado; exige decisão do dono, backup e ensaio)**:
    deslocar `leituras.data` e `eventos_aluno.ocorrido_em` das leituras dessa
    escola vindas da API em −3 h e recalcular as notas. Atenção: a chave natural do
    evento usa o minuto — a recoleta completa semanal pode criar o evento de novo
    no horário convertido (a `Leitura` não duplica: é única por aluno+livro).
* **Matific, "a atividade aparece no dia seguinte"**: o retrato guarda o
  INSTANTE da coleta (UTC), correto como instante. Uma coleta das 00:10 (BRT) mede
  o fechamento do dia anterior, mas é datada no dia novo. Quem atribui retrato a
  dia (ex.: `matific_destaque.ganho_no_periodo`, premiações) compara UTC cru com
  dias de Brasília e usa a última coleta DENTRO da janela — fora do módulo de sync
  e da fórmula congelada; **pendente de decisão do dono**. Com a agenda corrigida
  (03:00 BRT) o deslocamento é o mesmo: a coleta noturna mede o dia anterior.

## 8. Robô de avaliações externas (legado)

`fontes_avaliacao` + `coletar_pendentes` gravam números **sem prévia**. Estão
**desligados por padrão** (`AVALIACOES_ROBO_HABILITADO=false`) e ligar o
agendador **não** os liga. Valores que ligam: `true`, `1`, `sim`, `yes`, `on`;
qualquer outro (vazio, `false`, um erro de digitação) deixa o robô desligado — o
valor não reconhecido também avisa no log — e não impede a API de subir. Os
indicadores oficiais entram pela importação com prévia e desfazer
(`services/indicadores`). O botão "coletar agora" de uma fonte (admin global)
continua existindo e também grava sem prévia — ele nunca sobrescreve número que
veio da importação oficial. **Pergunta ao dono**: retirar o botão.

## 9. Calendário dos bimestres

Só 2026 está cadastrado. Para outro ano: `bimestres.intervalo` recusa com
mensagem clara; a sugestão de bimestre usa o mapa por mês e avisa no log; os
períodos aproximados saem com "(aproximado: sem calendário oficial de AAAA)".
"Bimestre anterior" em janeiro/fevereiro é o 4º do ano passado pelo calendário
**dele** quando houver (jan/2027 → 4º de 2026, 05/10–31/12), mesmo sem o
calendário do ano corrente.
Para cadastrar sem deploy de código: variável `BIMESTRES_CALENDARIO`, ex.
`{"2027": [["2027-02-01","2027-04-23"], ["2027-04-26","2027-07-09"],
["2027-07-26","2027-10-01"], ["2027-10-04","2027-12-17"]]}` (datas de exemplo —
usar as da Secretaria). Calendário inválido é ignorado inteiro, com erro no log.

## 10. Validar uma coleta manual (roteiro para a demonstração)

Sem acesso a dados de crianças no relato: conte, não nomeie.

1. **Credencial**: Integrações › card da plataforma › Configurar conexão ›
   "Testar conexão" → "Conexão bem-sucedida". Se falhar, ver §2.1/§3.
2. **Coletar**: "Sincronizar <plataforma>". O selo vira "Sincronizando" e a tela
   se atualiza sozinha.
3. **Resultado**: Detalhes técnicos › Histórico: a execução nova "concluída"; em
   "ver" (logs): "Concluído: N aluno(s), M arquivo(s) (K com dados)" e, se for o
   caso, "N alerta(s) desta integração fechado(s)".
4. **Card**: selo "Atualizado"; "Último dado aplicado" = agora; "última tentativa: …
   (concluída)"; "Dados recebidos: X de Y alunos com dados"; "dado mais recente".
5. **Conferência por amostragem**: escolha 2–3 alunos e compare, na plataforma,
   livros (Elefante) ou atividades/estrelas (Matific) com o Constela. Diferença
   pequena no Matific do mesmo dia é normal (o placar anda). Constela com MAIS que
   a plataforma = queda retida (alerta `queda_matific`, §5): o valor gravado foi
   mantido até a revisão. Aluno que não aparece = revisão de identidade pendente.
6. **Trilha**: a execução aponta para a importação gerada (`importacao_id`); a
   importação aparece em Importações.
7. Se o robô estiver bloqueado (§2.1), demonstre com a **exportação oficial**
   (§4.1) e diga que é esse o caminho — não há contorno.

## 11. Critérios para religar o agendador (critérios, não resultados)

Religar (`SYNC_SCHEDULER_ENABLED=true`) só quando, medido no próprio sistema:

1. **14 dias** consecutivos de coletas (manuais ou assistidas) com sucesso diário
   em **≥ 95%** dos pares escola × plataforma configurados;
2. **0 execuções presas** no período: o pré-requisito `execucoes_presas`, que olha
   "executando" além de 45 min (o teto da coleta, `SYNC_TETO_EXECUCAO_S`, menor que
   `SYNC_TRAVADA_S` = 60 min) e "fila" sem sinal de vida além de 60 min;
3. nenhum alerta de falha aberto sem causa conhecida; `queda_matific` revisados;
4. backup diário privado verde no período;
5. decisão explícita do dono (custo/ janela de horário).

**Critério em aberto (decisão do dono):** o item 1 pede 14 dias consecutivos com
≥ 95%; o Passo 3 de `docs/sync/REATIVAR-AGENDADOR.md` pede ≥ 5 dias úteis de
coletas manuais acompanhadas. Os dois documentos são de momentos diferentes e o
código não decide entre eles: qual vale (14 dias × 5 dias úteis) é escolha do dono,
ainda não registrada.

Ao religar: `AVALIACOES_ROBO_HABILITADO` continua `false`. As agendas vencidas há
mais que a cadência (paradas em setembro) não entram de uma vez: só ganham a
próxima data e rodam no horário delas. As que vencem no mesmo horário entram
juntas e, com `SYNC_WORKERS=1`, rodam em sequência; considerar espalhar os
horários das escolas (`hora_local`) antes de ligar.
