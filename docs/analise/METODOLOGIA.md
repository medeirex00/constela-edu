# Metodologia da análise educacional

Este documento define **o que a análise educacional calcula, com quais dados e com quais
limites**. Toda métrica de plataforma e toda relação com os indicadores oficiais que aparece
na tela sai daqui; nada que não esteja descrito aqui é calculado.

Código: `backend/app/services/analise/` (`indicadores.py`, `plataformas.py`, `relacao.py`,
`escola.py`, `diagnostico.py`, `evolucao.py`) e `backend/app/routers/analise.py`. Testes:
`backend/tests/test_analise_*.py`
(dados inventados, decisão D13). A tela não cita este arquivo: ela mostra o resumo em
linguagem simples (`metodologia_resumo` do catálogo, `metodologia` da relação e
`limitacoes` das plataformas).

## 1. Princípios

1. **Só leitura.** Nenhuma rota da análise grava nada (nem a linha do catálogo de
   avaliações) e nenhuma migração foi criada. Há teste que confere o banco antes e depois
   de todas as rotas, com todos os perfis.
2. **Oficial × estimativa × sem registro.** Só é *oficial* o número com importação oficial
   (`importacao_id` não nulo em `resultados_avaliacao`) ou o número de território de
   `indicadores_referencia`. Dois outros tipos de número ficam de fora dos **destaques** e
   da **relação estatística**, cada um com o seu nome — nunca confundidos:
   * a **Estimativa Constela** (`crianca_alfabetizada` e as médias do SARESP por escola
     calculadas pelo Constela) não entra em série oficial nenhuma: aparece só na lista
     `estimativas`, com `tipo = estimativa_constela`. A escola que só tem a estimativa fica
     com o ponto oficial nulo e o motivo **da consulta oficial** (no SARESP, por exemplo,
     `fora_do_arquivo`);
   * o **Ideb e o Saeb por escola gravados antes** pelo botão de 1 clique, sem
     `importacao_id` (a importação oficial os mantém quando são iguais aos do arquivo —
     contador `iguais_sem_proveniencia`), aparecem nas séries, na visão por escolas e na
     rota da escola **como a consulta oficial os mostra** (`consulta_ideb._numero_resultado`
     e a marca "*" da tela antiga): com o valor, `proveniencia = "sem_registro"`,
     `texto_proveniencia` ("número gravado antes, sem o registro do arquivo oficial") e
     `difere_do_oficial` (quando uma importação oficial recusou trocá-lo pelo número
     diferente do arquivo; o texto ganha "difere do arquivo oficial"). Eles são listados em
     `sem_registro_oficial` e **nunca** são chamados de estimativa.
3. **Ausência ≠ zero.** Sem número, o valor é `null` e vem o motivo (`motivo_ausencia` +
   `texto_ausencia`). Nunca se inventa ponto, interpola ou preenche lacuna.
4. **Sem ranking.** As escolas aparecem sempre em ordem alfabética (sem acento e sem caixa),
   nunca por valor.
5. **Sem causalidade.** A relação descreve escolas; não mede efeito de plataforma.
6. **Sem dado pessoal.** Nenhuma resposta traz `aluno_id`, nome de aluno ou turma — nem
   os totais brutos que refariam uma taxa escondida (ver 3.5).

## 2. Indicadores oficiais

### 2.1 De onde vêm os números

A análise **não relê** as tabelas oficiais: ela chama as mesmas consultas das telas de
indicadores e só normaliza a saída delas para um formato comum.

| Indicador | Consulta oficial | Órgão | Abrangência | Etapas | Componentes | Meta |
|---|---|---|---|---|---|---|
| `ica` | `consulta.ica_da_rede` | INEP | só a rede | 2º ano | LP | sim (2024–2030) |
| `saresp` | `consulta_saresp.saresp_da_rede` | SEDUC-SP | rede e escola | 2º e 5º ano | LP, MT | não |
| `iee` | `consulta_saresp.saresp_da_rede` | SEDUC-SP | só a escola | anos iniciais | — | sim (meta da escola) |
| `ideb` | `consulta_ideb.ideb_da_rede` (+ `consulta_ideb_rede`) | INEP | rede e escola | anos iniciais | — | sim (só 2007–2021) |
| `saeb` | `consulta_ideb.ideb_da_rede` (+ `consulta_ideb_rede`) | INEP | rede e escola | 5º ano | LP, MT | não |

* Saeb da **rede**: a planilha de resultados do INEP (localização Total, rede municipal).
  Saeb da **escola**: o arquivo do Ideb por escola (a média da escola). A nota do Saeb que
  entra no Ideb do território (só escolas urbanas) **não** é usada como série de Saeb. No
  contexto de UMA escola, o aviso diz isso com essas palavras.
* O Saeb do 2º ano é amostral (só UF e Brasil): não vira série da rede nem da escola.

### 2.2 Formato comum

Cada série tem `papel`:

* `principal` — a rede municipal (ou a escola escolhida);
* `referencia` — a **mesma rede de ensino** noutro território (UF nas redes municipais,
  Brasil nas redes municipais) ou a rede municipal quando se olha uma escola —
  `comparavel = true`;
* `contexto` — **outra rede de ensino** (rede pública, rede estadual) —
  `comparavel = false`, com `motivo_nao_comparavel`.

Cada ponto: `edicao`, `valor`, `casas` (a precisão **publicada**), `valor_detalhado`
(casas de outro arquivo, quando a consulta as tem), `motivo_ausencia`, `meta`,
`meta_casas`, `diferenca_meta`, `situacao_meta`, `instavel`, `fonte_id` (a chave do mapa
`fontes`, com o formato canônico de fonte das consultas) e a proveniência do número com
valor: `proveniencia` (`oficial` ou `sem_registro`), `texto_proveniencia` e
`difere_do_oficial`. O número sem registro não tem `fonte_id` (não há arquivo oficial
registrado para ele); a comparação com a meta é a da consulta oficial. No IEE, o ponto traz
também `icm` e `tps_zero` (ver 2.4).

### 2.3 Meta e diferença

As comparações são **as das consultas oficiais**, copiadas:

* **ICA** (`consulta.comparar`): diferença em p.p. na menor precisão publicada dos dois
  lados; **empate na precisão divulgada = `inconclusivo`** (23 × 23 pode ser 22,6 × 23,3).
* **Ideb** (`consulta_ideb_rede.comparar_meta`): Ideb ≥ meta na precisão publicada
  (1 casa) = `atingiu` — o empate conta como atingiu (leitura do INEP). As metas existem
  **só no 1º ciclo (2007–2021)**; de 2023 em diante o ponto vem com `meta = null` e
  `motivo_sem_meta = depois_do_1o_ciclo`.
* **IEE**: a situação é o **ICM (Índice de Cumprimento de Meta) oficial da SEDUC**
  (1 = cumpriu a meta, 0 = não cumpriu); a análise não decide o cumprimento.
  `diferenca_meta` = IEE − meta, na menor precisão publicada dos dois lados (a mesma conta
  do ICA), só como informação.
* **SARESP** e **Saeb**: sem meta (nada é comparado).

### 2.4 Comparabilidade e avisos

Os avisos de cada indicador são **os das consultas oficiais**, lidos a cada requisição: a
comparabilidade do Ideb e do Saeb com o período das edições reais da rede
(`consulta_ideb._avisos`), o aviso dos números sem registro (quando há algum), o aviso dos
níveis do SARESP (`consulta_saresp._niveis`, que muda quando um corte de nível é
confirmado em `escalas.CORTES_SARESP`). Além deles:

* Escalas diferentes não se comparam: SARESP × Saeb × ICA (cada série diz a escala).
* Rede municipal × rede pública/estadual: `contexto`, nunca comparação.
* SARESP do 2º ano não é o ICA. Quebras de escala do 2º ano: 2022→2023 e 2025→2026
  (`quebras` — a tela não traça a linha entre esses anos).
* SARESP com TPS = 0 (a escola não atingiu a participação mínima): a média sai com
  `instavel = true`.
* **IEE com TPS = 0**: o IEE da escola é calculado com essas mesmas médias instáveis. O
  número OFICIAL **não** é marcado instável (seria regra nova sobre número oficial): o
  ponto traz `tps_zero = true`, e a relação o exclui (ver 4.1).
* Ideb: série inteira com mudanças de universo; 2021 na pandemia.
* O ICA não existe por escola: `GET .../indicadores/ica?escola_id=` e `visao=escolas`
  respondem **400**.

### 2.5 Disponibilidade

Um indicador está `disponivel` quando há pelo menos um número **oficial** (da rede ou de
escola). Senão, `motivo_indisponivel`: `so_estimativa` (só a Estimativa Constela),
`so_sem_registro` (só números gravados antes, sem o registro do arquivo oficial),
`sem_codigo_ibge` (a rede sem o código IBGE) ou `sem_importacao`. As edições do catálogo
(`edicoes`, `edicao_mais_recente`) e os destaques contam só números oficiais.

### 2.6 Alertas do catálogo

* `cadastro` — a rede sem código IBGE ou CODMUN; escolas sem código INEP.
* `ausente` — indicador indisponível (com o motivo de 2.5).
* `insuficiente` — na edição mais recente de um indicador por escola, as escolas **sem
  número nenhum** (o motivo de cada uma está na visão por escolas).
* `sem_registro` — na mesma edição, quantas escolas têm só o número gravado antes, sem o
  registro do arquivo oficial (e quantos diferem do arquivo). Elas **não** são contadas
  como "sem resultado".
* `desatualizado` — o resultado do Ideb (por escola ou da rede) ainda não importado, com
  texto próprio, **sem o nome do arquivo** (a fonte documental fica em "Detalhes e fontes"
  e na área de importação, `/rede/avaliacoes`).
* `metodologia` — plataformas e avaliações sem ano letivo em comum.

## 3. Plataformas (Elefante Letrado e Matific)

### 3.1 Período

O período é o do serviço oficial (`periodos.resolver`, via
`relatorios_periodo.resolver_janela`): presets (`ano_letivo` é o padrão: 01/01 a 31/12 do
ano letivo ativo), `personalizado` com `inicio` e `fim`. Intervalos **inclusivos**, com os
limites em datas de Brasília, comparados com os instantes gravados em UTC, **sem
conversão** (a regra herdada das premiações — ver 5). Cada escola usa o próprio ano letivo
ativo.

**Ano letivo de referência da rede** (o `janela.ano_letivo` da rota da rede, o rótulo da
janela e o ano da evolução por bimestre): o mais comum entre as escolas **em uso** —
ativas e com aluno na coorte (no empate, o mais novo). A troca do ano letivo é manual e
escola a escola: escola fechada ou só cadastrada, sem aluno, fica parada no ano antigo e
**não decide** o ano da rede. Sem nenhuma escola em uso, valem as que têm aluno; sem
nenhuma com aluno, todas. `janela.anos_letivos` lista os anos das escolas **com aluno** (as
que são medidas, cada uma no ano dela — também a inativa que ainda tem aluno): escola sem
aluno não põe "anos letivos diferentes" na tela nem tira a relação e o diagnóstico do
"mesmo ano".

**Exceção — questões do Elefante**: seguem a regra do Relatório por Período
(`relatorios_periodo._diferenca_de_retratos`): cada coleta é convertida para Brasília, a
borda do período é medida pela coleta a até **1 h** dela (`TOLERANCIA_BORDA`: a agenda das
0h10 mede o dia anterior) e as linhas da mesma execução (a até 15 min) contam como uma
coleta, a primeira.

Datas do período e edição da avaliação só entre os anos **2000 e 2100**
(`analise.ANO_MINIMO`/`ANO_MAXIMO`): fora disso a resposta é **422**, antes de medir
qualquer escola (o ano 0 ou o 10000 não existe para `datetime` e virava erro 500 depois de
a rota já ter medido a rede inteira).

**Período da Secretaria — só blocos inteiros do calendário** (`PRESETS_DA_REDE`): nas rotas
que medem as plataformas (`/redes/{id}/analise/plataformas`, `/diagnostico`, `/relacao` e
`/escolas/{id}/analise`), a Secretaria pede o **ano letivo** ou **um bimestre** (`bimestre_1`
a `bimestre_4`, `bimestre` e `bimestre_anterior`). O personalizado, o dia, a semana, o mês, o
semestre e "todo o histórico" voltam **422** (`TEXTO_PERIODO_DA_SECRETARIA`): com dois
períodos que se sobrepõem, a diferença entre eles é o que aconteceu só no trecho que um tem
e o outro não — e esse trecho pode ter **uma** criança, que nenhum dos dois esconde (3.5,
"Blocos fixos"). O admin global e a coordenação da escola, que já veem cada criança,
continuam com todos os períodos. É uma mudança de comportamento por segurança (G_GRUPO-2,
11/2026): a Secretaria perdeu o personalizado, o dia, a semana e o mês nessas telas.

### 3.2 Coorte e série

* **Coorte**: alunos **ativos** com **matrícula no ano letivo ativo** da escola
  (`relatorios_periodo._coorte`); o nome que a função devolve é descartado na hora.
* **Série**: `elegibilidade.ano_premiavel(Turma.ano_escolar)` — 1º ao 5º ano. Fases,
  EMEI e EJA ficam **fora do recorte** (contadas só em `alunos_fora_do_recorte`, na rede).
* **Contagem**: o número de alunos por escola × série sai de UMA consulta agrupada para a
  rede inteira (a mesma população do `_coorte`; uma matrícula por aluno no ano). É ela, e
  só ela, que decide a supressão (3.5) — não depende do período nem das coletas.
* **Unidade**: a célula (escola × série); o bloco da escola é a soma das células
  **visíveis** dela; o da rede, a soma das escolas visíveis com a coleta em dia (3.5).
* **Filtro de série** (`?serie=`): o bloco da escola é o da série. A escola que tem alunos,
  mas nenhum ativo nessa série, sai com `alunos = 0` e `motivo_sem_dado =
  sem_alunos_na_serie` ("a escola não tem aluno ativo nesta série no ano letivo"); a escola
  sem aluno nenhum do 1º ao 5º ano continua `sem_alunos_no_recorte`.

### 3.3 Cobertura (ausência ≠ zero)

* **Elefante**: a escola só é medida se tem **coleta do Elefante no período ou depois do
  início dele** (`max(data_referencia) ≥ início`). Senão: `sem_coleta` (nunca coletou) ou
  `sem_coleta_no_periodo` — métricas `null`, e a escola **fica fora** das somas da rede.
* **Matific**: a escola só é medida se algum aluno tem **coleta dentro do período**
  (regra de `matific_destaque`). Senão, `sem_coleta_no_periodo`.
* **Coleta parcial** (`coleta_parcial`): a última coleta que entrou na conta (Elefante: a
  última coleta da escola; Matific: a coleta mais recente dentro do período) é de **mais de
  7 dias antes** de `mín(fim do período, hoje)` — 7 dias é a tolerância da recoleta
  semanal do Elefante. A escola mostra o que foi medido, com `coberto_ate` (a data até onde
  os números valem) e `texto_cobertura`. Na **soma da rede**, ela entra só se a coleta cobre
  **ao menos 90% do período** (contado até hoje); nesse caso o bloco da rede traz
  `escolas_coleta_parcial_na_soma`, `coberto_ate_parcial` e `texto_parcial_na_soma`. Abaixo
  de 90%, fica fora da soma (o resto do período não foi medido — não é zero). Na **relação**
  estatística, toda coleta parcial fica fora. Motivo do limite de 90%: com o agendador
  desligado, em 20/10/2026 quatro das cinco escolas com plataforma tinham a última coleta
  entre 01 e 04/10; fora da soma, a rede do ano letivo ficaria com uma escola só.
* Por escola: `cobertura`, `ultima_coleta`, `coberto_ate` e `dias_desde_ultima_coleta` de
  cada plataforma. Na rede (`cobertura`), as listas `escolas_sem_coleta`,
  `escolas_sem_coleta_no_periodo` e `escolas_coleta_parcial`, a última coleta e o primeiro
  evento do Elefante — tudo **só das escolas visíveis** (`escopo = escolas_visiveis`).
* Módulo não contratado pela rede (`modulos.modulos_da_rede`): o bloco da plataforma é
  `null` e a cobertura diz `modulo_nao_contratado`.

### 3.4 Alunos medidos e fórmulas

**Alunos medidos** (`alunos_medidos`) — o denominador das duas plataformas, pela mesma
definição: só entra quem a plataforma **conhece** no período. Quem ainda não tem conta (ou
não tem coleta) fica **fora** do denominador — não conta como zero.

* **Elefante**: o aluno da coorte com conta no Elefante — alguma coleta (retrato) da escola,
  em qualquer data — ou com leitura no período. `alunos_sem_conta` = coorte − medidos.
* **Matific**: o aluno da coorte com coleta dentro do período (o ganho existe).
  `alunos_sem_retrato` = coorte − medidos (`alunos_com_retrato` = medidos).

Notação: `n` = alunos medidos da célula. Com `n < k` (k = 5), nenhuma métrica aparece
(`motivo_sem_dado = poucos_alunos_medidos`); com `n = 0` no Elefante,
`sem_conta_na_plataforma`.

**Elefante** (`relatorios_periodo._elefante` e, para as questões,
`relatorios_periodo._diferenca_de_retratos` — a regra de `_elefante_questoes`):

| Métrica | Fórmula | Observação |
|---|---|---|
| `alunos_com_leitura` | medidos com livro novo **ou** evento de leitura no período | contagem |
| `participacao_pct` | `alunos_com_leitura ÷ n × 100` | 1 casa |
| `livros_por_aluno` | `Σ livros novos ÷ n` | 2 casas; livro novo = `Leitura.data` no período (o par da premiação "Mais Livros"); só com **nenhum ou ≥ k alunos com livro novo** (os contribuintes — §3.5) |
| `minutos_por_aluno` | `Σ Leitura.tempo_leitura_min ÷ n` | 1 casa; é um **piso** (a fonte nem sempre informa o tempo); só com **nenhum ou ≥ k alunos com tempo** |
| `nivel_medio` / `nivel_medio_posicao` | média da posição do nível (AA = 0 … Z = 29, `scoring.POS_DO_NIVEL`) dos livros novos, com o nível congelado da leitura (`coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)`); a letra é a posição arredondada | só com **≥ k alunos com livro novo de nível conhecido**; nível fora do vocabulário não entra |
| `taxa_acerto_pct` | `Σ acertos ÷ Σ tentativas × 100`, pela **diferença entre coletas** | 1 casa; só com **≥ k alunos com questão**; `janela_questoes` = o intervalo real das coletas. As exclusões são as da regra oficial (`_elefante_questoes`): o aluno **sem intervalo medido** (uma coleta só, sem base) não soma 0/0, e o aluno cujo **contador diminuiu** entre as coletas (série que mistura contas — fusão, colisão de identidade — ou recontada) **sai das questões** (continua em `n`); o bloco avisa com `contador_regrediu = true` e `texto_contador_regrediu`, sem a contagem |

**Matific** (`matific_destaque.ganho_no_periodo`, a regra de `relatorios_periodo._matific`):

| Métrica | Fórmula | Observação |
|---|---|---|
| `participacao_pct` | `alunos com atividade (ganho > 0) ÷ n × 100` | 1 casa |
| `atividades_por_aluno` | `Σ atividades ganhas ÷ n` | 2 casas; só com **nenhum ou ≥ k alunos com atividade** (os contribuintes — §3.5) |
| `estrelas_por_aluno` | `Σ estrelas ganhas ÷ n` | 2 casas; só com **≥ k alunos com atividade** (senão "estrelas ÷ atividades" das duas médias refaria o desempenho escondido) |
| `desempenho_medio` | `Σ estrelas ÷ Σ atividades` (escala 0 a 5) | 2 casas; só com **≥ k alunos com atividade**; num total, some também quando as atividades somem em complemento (§3.5) — ao lado das estrelas por aluno, ele as refaria |

Arredondamento: "meio para cima" (`ica.arredondar`), como na divulgação oficial.

**Só os retratos que a regra lê.** A análise não carrega o histórico diário inteiro: lê,
de cada aluno, só as coletas que a regra pode usar (uma consulta por escola, com `lag` e
`row_number`) — o resultado é o mesmo (há teste que confere contra as funções oficiais
sobre o histórico inteiro, também no PostgreSQL), e o custo não cresce com o histórico.

* **Matific** (`_retratos_essenciais`): o último retrato antes do início e o primeiro e o
  último dentro do período, no instante gravado (UTC), como na regra das premiações (que
  descarta os de fora do ano letivo).
* **Questões do Elefante** (`_coletas_das_questoes`), com o critério de
  `_diferenca_de_retratos` (3.1): só a primeira linha de cada execução e, delas, a última
  antes de "início − 1 h", todas a até 1 h do início, a primeira e a última do miolo do
  período, todas a até 1 h do fim (a 0h do dia seguinte) e a primeira depois disso (só
  para saber que a conta existe). Limitação: uma sequência de linhas a menos de 15 min uma
  da outra que dure mais de 15 min (só em dado antigo; hoje a sync reescreve o retrato do
  dia no lugar) conta como uma execução só.

### 3.5 Supressão de células pequenas (k = 5)

* Célula (escola × série) com 1 a 4 alunos: `suprimido = true`, **sem** o número de alunos
  e **sem** métricas.
* **Complementar, com faixa de proteção**: enquanto as células suprimidas de uma escola
  somarem de 1 a 2k − 1 (= 9) alunos, a menor célula visível também é suprimida. Assim a
  conta "total da escola − células visíveis" é sempre de pelo menos 2k alunos e não fixa o
  tamanho de nenhuma célula pequena (com união de 6 e dois motivos diferentes, a célula de
  1 aluno era revelada). O mesmo vale entre as escolas da rede (escola com menos de 5
  alunos e as menores visíveis junto). Escola suprimida suprime todas as séries dela.
* **Motivo único**: `motivo_supressao = suprimido` e o mesmo texto para a célula pequena e
  para a escondida junto — a resposta não diz qual é qual.
* **Blocos só do que está visível**: o bloco do Elefante e do Matific de uma escola soma
  só as células visíveis dela (`blocos_parciais = true` e `texto_blocos` quando alguma
  série ficou de fora; sem nenhuma série visível, `series_suprimidas`); o bloco da rede
  soma só as escolas visíveis, com a coleta em dia, e nelas só as células visíveis
  (`escopo_blocos = escolas_visiveis`, `texto_blocos`, `escolas_com_dado` = quantas
  entraram). A diferença "bloco − partes mostradas" é sempre zero, em qualquer período e
  qualquer cobertura — a cobertura diferente de uma escola suprimida não a reabre. O total
  de alunos da rede (`rede.alunos`) continua o da rede inteira: "rede − escolas visíveis"
  é a união suprimida, de pelo menos 2k alunos.
* **Escola suprimida não mostra nada**: nem alunos, nem métricas, nem `cobertura`,
  `ultima_coleta`, `coberto_ate` ou `dias_desde_ultima_coleta` — e não entra nas listas de
  cobertura da rede.
* **Sem totais brutos**: as respostas não trazem `questoes_tentativas`,
  `questoes_acertos`, `alunos_com_questao`, `atividades`, `estrelas`,
  `alunos_com_atividade`, `livros_novos`, `tempo_min` etc. — com eles, uma taxa escondida
  (subconjunto com menos de k alunos) se refaria.
* **Complementar também por métrica**: os totais mostram médias por aluno junto com
  `alunos_medidos`, então "total − células que mostram a métrica" refaria a métrica que uma
  célula visível escondeu (poucos medidos; menos de k com nível, com questão ou com
  atividade — ex.: o desempenho de **uma** criança ativa no 3º ano). Para cada grupo de
  métricas que depende de um subconjunto (`_PROTEGIDAS`: participação/livros/minutos e
  participação/atividades pelos **medidos**; nível pelos alunos **com nível**; acerto pelos
  alunos **com questão**; estrelas/desempenho/atividades pelos alunos **com atividade**;
  livros pelos alunos **com livro novo** e minutos pelos alunos **com tempo**), a métrica some
  também do total que a revelaria:
  * **escola**: quando as crianças escondidas nas séries dela somam de 1 a k − 1 (com k ou
    mais, a diferença dá só a soma de k ou mais crianças — a proteção da própria célula);
  * **rede**: quando as escondidas nas escolas que **também** esconderam a métrica somam de
    1 a k − 1 (a escola que a mostra já fixa a soma das escondidas dela, ≥ k);
  * **rede numa série** (filtro de série): sempre que alguma célula da série a esconde —
    cruzado com o total de uma escola (outra resposta), o total da série isolaria a célula.
  **Métrica derivada de duas somas** some com qualquer uma delas: o desempenho do Matific
  (estrelas ÷ atividades) está nos dois grupos. Num total que esconde as atividades em
  complemento e mostra as estrelas por aluno (estrelas = média × `alunos_medidos`), ele
  refaria as atividades escondidas (atividades = estrelas ÷ desempenho) — então some junto
  com elas, em todo total (escola, rede, rede numa série). As estrelas por aluno continuam
  quando o grupo delas não está escondido, e a marca que a rede soma por escola segue a
  das **somas** (a escola que esconde só o desempenho ainda fixa as estrelas dela). Antes
  (9971f88), os grupos eram tratados como independentes e a escola e a rede devolviam as
  atividades exatas da série escondida — até as de **uma** criança.
  **Zero que não é sabido**: a célula que mostra a participação e tem o subconjunto vazio
  (soma zero, já sabida pela participação 0%) não conta. Mas a série com **poucos medidos**
  não mostra nada, nem a participação: se nenhuma criança medida dela teve atividade no
  Matific, o grupo das estrelas ali é vazio e soma zero **sem** que o zero seja sabido — e
  "total − séries que mostram as estrelas" o devolveria (as estrelas das crianças dela: 0).
  Por isso, nas estrelas por aluno (média por aluno **medido**, com a soma exata), quando
  nenhuma criança com atividade está escondida, valem os alunos medidos das séries sem
  número: as estrelas (e o desempenho) somem do total enquanto eles somarem de 1 a k − 1
  (na escola; na rede, entre as escolas que também as esconderam; no total da rede numa
  série, com qualquer um). Com k ou mais deles, a diferença é o zero de k ou mais crianças
  — o padrão dos medidos, o mesmo que já mostra as atividades. Com crianças ativas
  escondidas, vale a soma delas (o zero fica misturado). No Elefante, o nível e o acerto
  dividem por somas que não saem em resposta nenhuma, e a regra não muda. Antes (até
  a937245), a escola e a rede mostravam as estrelas por aluno nesse caso.
  **Contribuintes** (G_GRUPO-4): as médias por aluno **medido** — livros, minutos e
  atividades — dão a soma exata (média × `alunos_medidos`); com 6 medidos e 1 só lendo, 0,5
  livro por aluno eram os 3 livros dela. Por isso cada uma depende também de quem **soma** no
  campo (o campo > 0): com nenhum, é o zero sabido; de 1 a k − 1, some (na célula e, em
  complemento, nos totais), entra em `metricas_protegidas` e o texto diz que é proteção
  (`TEXTO_METRICAS_POUCOS_CONTRIBUINTES`). É a regra dos contribuintes do cartão da
  Secretaria (`grupo_pequeno`) e da vitrine. Releitura conta na participação, não nos livros:
  quem só releu não soma livro novo.
  O total diz quais métricas escondeu em complemento (`metricas_protegidas`) e por quê
  (`texto_metricas_protegidas`). Há teste que confere, por álgebra linear exata sobre as
  respostas (rede, rede por série e escola), que nenhuma soma de menos de k crianças
  escondidas se refaz — contando como fixada a métrica que as outras duas do trio
  atividades/estrelas/desempenho refazem (o checador antigo montava as equações chave a
  chave e não via o desempenho) e, nas estrelas, as crianças das séries sem número.
* As decisões são tomadas **uma vez, só pelas contagens** (todas as escolas × todas as
  séries) e valem iguais em todas as respostas — a rede, o filtro de série, a escola e a
  relação. Com o filtro de série, o **total da rede naquela série some** quando alguma
  célula dela está suprimida (senão ele menos as escolas visíveis daria a soma das
  suprimidas).
* **Rota da escola** (`GET /escolas/{id}/analise`): mede só a escola. Para quem também lê
  a rede (Secretaria e admin global), a decisão é a da rede inteira — a escola vê o mesmo
  que a rota da rede mostra para ela (senão a Secretaria recomporia uma escola pequena com
  o total da rede). Para o coordenador e o admin da própria escola (que não leem a rede),
  a decisão é tomada só dentro da escola: ela não perde o agregado dela por causa de outra
  escola, e a resposta não depende das outras.
* **Blocos fixos do calendário (entre respostas de períodos diferentes)**: a proteção por
  métrica acima é a de **cada** período, e a diferença entre dois períodos que se
  sobrepõem a refaria (a auditoria refez as estrelas, o desempenho e o nível de leitura de
  uma criança com [01/03, 15/08] × [01/03, 04/10]). Por isso a Secretaria só pede uniões de
  **blocos** (3.1) e a métrica de um período que junta vários blocos — o ano letivo — só
  aparece se **nenhum** deles a esconde:
  * os blocos são uma partição do ano civil: os quatro bimestres, pelas mesmas janelas de
    `bimestre_1..4` (o calendário oficial, ou a aproximação sem ele), e as **folgas** entre
    eles (em 2026, 01/01 a 01/02, antes do 1º bimestre). Só contam os blocos que já
    começaram;
  * cada bloco é medido como um período (na mesma consulta ao banco) e marca, em cada
    célula, escola e rede da resposta, os grupos que ele esconde **com crianças dentro**: de
    1 a k − 1 no subconjunto, ou em complemento (as regras acima). Total sem nenhuma criança
    no subconjunto do bloco não marca (a soma dele é zero, e a das partes também);
  * o **resto** da conta que nenhum bloco mede é um bloco a mais (`_residuo`): no Matific, o
    ano letivo parte do zero e o bimestre parte da **primeira coleta** de quem chega no meio
    do ano (ganho zero nela); o teto das estrelas e a queda do contador também não somam
    igual; nas questões do Elefante, as bordas das coletas fazem o mesmo. O subconjunto do
    resto é o das crianças com número diferente da soma dos blocos. Livros, tempo e nível
    somam exatamente pelas datas das leituras;
  * os grupos dos alunos **medidos** (a participação) ficam fora dessa regra: são contagens,
    não números de criança;
  * a métrica escondida assim entra em `metricas_protegidas`, com o texto
    `TEXTO_METRICAS_PROTEGIDAS_BLOCOS` (ou `..._AMBOS`, quando o complemento da mesma resposta
    também esconde).
  Assim a diferença entre dois períodos aceitos é sempre uma soma de blocos que mostram a
  métrica, e "ano letivo − bimestres" não isola criança nenhuma. Vale para a Secretaria e o
  admin global (a proteção da rede), não para a coordenação da escola. Não cobre a
  diferença entre o **mesmo** período lido em dias diferentes (o bimestre em andamento muda
  a cada coleta) — ver 5.

## 4. Relação com as avaliações

### 4.1 Critérios (todos obrigatórios)

| Critério | Recusa (`motivos`) |
|---|---|
| Unidade = escola: o indicador precisa existir por escola (o ICA é só da rede) | `indicador_so_da_rede` |
| Só números oficiais (a estimativa e o número sem registro nunca entram) | `so_estimativa` / `so_sem_registro` / `sem_dado_oficial` |
| Mesma série: 2º ano ↔ 2º ano; 5º ano ↔ 5º ano; Ideb e IEE (anos iniciais) ↔ a escola inteira (1º–5º, as séries visíveis) | `serie_incompativel` |
| Componente compatível: Língua Portuguesa ↔ Elefante; Matemática ↔ Matific; Ideb e IEE aceitam os dois, com aviso de que juntam LP e MT | `componente_incompativel` |
| Plataforma contratada pela rede | `modulo_nao_contratado` |
| O período das plataformas **dentro** do ano letivo da edição, e as escolas no mesmo ano letivo (a mesma coorte) — ex.: SARESP 2025 ↔ período de 2025 | `periodo_sem_sobreposicao` |
| `n ≥ 8` escolas com os dois valores, cada célula com ≥ k alunos | `n_insuficiente` |
| Variação dos dois lados | `sem_variancia` |

**Motivo próprio de cada escola** (`pares[].motivo_escola`), calculado **sempre** — também
quando um motivo geral bloqueia a relação (aí `incluido = false` e
`motivo_exclusao = "fica de fora pelo motivo geral da relação"` para a escola sem motivo
próprio; o texto geral fica só em `textos`, sem se repetir em cada par):

* sem resultado oficial (com o motivo da fonte);
* **sem registro oficial** (o número gravado antes, sem o registro do arquivo oficial —
  `valor_oficial` vem nulo);
* média instável (SARESP com TPS = 0);
* **IEE calculado com médias de TPS = 0** (participação abaixo do mínimo);
* escola sem alunos da série; célula suprimida;
* sem dado da plataforma (sem coleta, poucos alunos medidos, módulo não contratado);
* **coleta parcial** (a coleta parou mais de 7 dias antes do fim do período — 3.3);
* **as questões contam desde uma coleta de outro ano letivo** — só na métrica de acerto:
  a janela efetiva das questões começa na última coleta antes do início, que pode ser do
  ano anterior (ex.: coleta parada nas férias); se `janela_questoes.inicio` é anterior a
  01/01 do ano da edição, o par sai. O Matific já descarta retratos de fora do ano letivo.

Os `pares` são devolvidos **sempre** (inclusive quando a relação não é calculável), com o
ano de cada lado, para a tela mostrar os dois números "lado a lado" sem afirmar associação.
No Ideb e no IEE, o lado das plataformas é o bloco da escola, que soma só as séries
visíveis.

### 4.2 Método

* **Spearman**: a correlação de Pearson dos **postos** (`avaliacoes._pearson` sobre os
  postos), com **empates pelo posto médio** (ex.: dois valores empatados nas posições 2 e
  3 recebem 2,5). Coeficiente com 3 casas.
* **Intervalo de 95%** (aproximado): transformação z de Fisher, `z = atanh(ρ)`, erro-padrão
  `EP = 1,06 / √(n − 3)`; intervalo `[tanh(z − 1,96·EP), tanh(z + 1,96·EP)]`. Esse EP é um
  pouco **mais conservador** que o `√(1,06 / (n − 3))` de Fieller, Hartley e Pearson (1957)
  para o Spearman: o intervalo sai levemente mais largo, nunca mais estreito. Com |ρ| = 1 o
  z é limitado a ±atanh(0,999999).
* **Por que n ≥ 8**: com menos de 8 escolas o intervalo de 95% fica tão largo que quase
  qualquer coeficiente é compatível com zero; a tela mostraria um número sem conteúdo.
* **Interpretação**: se o intervalo inclui o zero, a tela diz que **não dá para afirmar**
  associação. Se não inclui, descreve o sentido ("escolas com X mais alto tendem a ter Y
  mais alto") — sempre com o aviso de que **correlação não é causalidade**.

## 5. Limitações conhecidas

* **Contador vitalício do Elefante.** O Elefante informa os contadores de cada aluno
  desde a criação da conta (relatório `LIFETIME`), não do ano. Questões do período só pela
  diferença entre duas coletas; o intervalo real é o das coletas (`janela_questoes`).
* **Data da leitura.** `Leitura.data` é a data informada na **primeira** importação de
  cada livro; releitura não move a data (ela aparece só nos eventos). Fundir alunos perde
  a data da releitura. Histórico anterior à primeira coleta fica comprimido perto dela.
* **Tempo e eventos são pisos**: o tempo pode faltar na fonte; dois eventos do mesmo livro
  no mesmo minuto viram um.
* **Atraso da coleta do Elefante**: o cursor só busca quem mudou de total de livros; a
  recoleta completa é semanal — leituras podem chegar até ~7 dias depois (daí a tolerância
  da coleta parcial, 3.3).
* **Matific é retrato do dia**: o contador é o acumulado do **ano acadêmico** do Matific
  (o calendário deles vai de 29/12/2025 a 31/01/2027); o código supõe a virada em 01/01.
  Reimportar no mesmo dia sobrescreve o retrato. Contador que regride vira ganho 0.
* **Deslocamento de fuso**: as coletas são gravadas em UTC e o período é contado em datas
  de Brasília (UTC−3) sem conversão nos filtros herdados: a coleta da madrugada (~00:10
  BRT) mede o dia anterior; leituras das 21h à meia-noite podem cair no dia seguinte; o
  "setembro" do Matific pode virar 31/08–29/09. A análise não corrige isso (é a regra das
  premiações); só mostra as datas das coletas com o fuso explícito. As **questões do
  Elefante** são a exceção: medidas em Brasília, com a tolerância de 1 h nas bordas, como
  no Relatório por Período (3.1).
* **Plataformas só do ano letivo em curso (2026) × avaliações até 2025** (SARESP 2025;
  Saeb/Ideb 2023): **não há ano em comum** hoje, e a relação fica sempre "lado a lado".
  Medir 2025 nas plataformas é inviável (Matific sem dado de 2025; Elefante só com
  leituras parciais de 2025 atribuídas à turma de 2026).
* **Coortes diferentes entre anos**: o 5º ano do SARESP 2025 saiu do Fundamental I; o 2º
  ano de 2025 está hoje no 3º. Mesma escola e mesma série **não** são as mesmas crianças.
* **Transferidos e inativos** saem de todas as contas, com o histórico.
* **Saeb da escola × da rede**: a escola vem do arquivo do Ideb por escola; a rede, da
  planilha (localização Total). A nota do Saeb dentro do Ideb do território é só de escolas
  urbanas e não é usada aqui.
* **Supressão tem custo**: a faixa de proteção (2k) esconde, junto com uma célula pequena,
  células vizinhas maiores; o bloco da escola (e o lado das plataformas na relação com o
  Ideb e o IEE) passa a somar só as séries visíveis. A supressão complementar por métrica
  (3.5) também esconde médias de totais grandes — sobretudo no total da rede filtrado por
  série e em períodos curtos, em que mais séries têm menos de k crianças ativas.
* **Médias por aluno escondidas com poucos contribuintes** (desde G_GRUPO-4): livros,
  minutos e atividades por aluno somem quando de 1 a k − 1 crianças somam nelas (§3.5) —
  sobretudo em bimestres de pouco uso. A participação continua: é contagem.
* **O mesmo período em dias diferentes**: o bimestre em andamento (e o ano letivo, que o
  contém) muda a cada coleta; a diferença entre a leitura de hoje e a de ontem é o que
  aconteceu entre as duas coletas, que pode ser de uma criança só. A proteção por blocos
  (3.5) fecha a diferença entre períodos, não a diferença no tempo. Fechar esta exigiria
  medir só até o último bimestre fechado (os números do bimestre corrente sumiriam das
  telas da Secretaria) ou esconder as médias protegidas enquanto o bimestre corre —
  decisão do dono, registrada na auditoria (G_GRUPO-2). O mesmo vale para os cartões do
  Painel da Rede.
* **Nada disto é causalidade**: escolas diferem em muitas coisas além do uso das
  plataformas.

## 6. Códigos

* Ausência (`motivo_ausencia`): `nao_divulgado`, `participacao_baixa`, `fora_do_arquivo`,
  `sem_importacao`, `sem_codigo_inep`, `cadastrado_depois_da_importacao`,
  `codigo_inep_alterado`, `estimativa_mantida_d2`, `sem_resultado`, `sem_registro_oficial`
  (o único registro da edição é uma ausência gravada antes, sem o registro do arquivo).
* Proveniência (`proveniencia`): `oficial`, `sem_registro`.
* Sem meta (`motivo_sem_meta`): `depois_do_1o_ciclo`, `antes_das_metas`,
  `sem_arquivo_oficial`, `sem_meta_no_arquivo`, `sem_meta`, `sem_meta_na_edicao`.
* Indisponível (`motivo_indisponivel`): `so_estimativa`, `so_sem_registro`,
  `sem_codigo_ibge`, `sem_importacao`.
* Cobertura das plataformas: `ok`, `coleta_parcial`, `sem_coleta`, `sem_coleta_no_periodo`,
  `modulo_nao_contratado`, `sem_alunos_no_recorte`.
* Bloco sem número (`motivo_sem_dado`), além dos de cobertura: `poucos_alunos_medidos`,
  `sem_conta_na_plataforma`, `series_suprimidas`, `sem_dado_nas_escolas_visiveis` (rede),
  `sem_alunos_na_serie` (escola, com o filtro de série: nenhum aluno ativo na série; 3.2).
* Supressão: `suprimido`.
* Período recusado à Secretaria (422): o texto `TEXTO_PERIODO_DA_SECRETARIA` (3.1).
* Alertas: `cadastro`, `ausente`, `insuficiente`, `sem_registro`, `desatualizado`,
  `metodologia`.
* Recusa da relação: ver 4.1.
* Diagnóstico pedagógico (sinais, estados, categorias e níveis): ver 7.5 a 7.7.

## 7. Diagnóstico pedagógico (exploratório)

`GET /redes/{id}/analise/diagnostico?periodo&inicio&fim` (`exigir_rede`: a Secretaria da
própria rede e o admin global; o período como em 3.1, padrão `ano_letivo`). Serviço:
`diagnostico.py`. Só leitura (há teste com o banco igual antes e depois, com todos os
perfis).

### 7.1 O que é — e o que não é

* **Hipótese exploratória, calculada pelo Constela.** Para cada escola da rede, diz onde as
  avaliações oficiais e o uso das plataformas apontam para o mesmo lado e onde divergem, com
  regras escritas e cada sinal rastreável até o número. Serve para decidir **onde olhar
  primeiro**; não é avaliação da escola nem causa e efeito.
* **Não é a relação estatística** (seção 4): não calcula coeficiente nem exige o mesmo ano
  letivo — por isso declara a comparabilidade (7.6) e **não tem gráfico de dispersão** (anos
  diferentes fariam uma relação inválida).
* **Sem ranking**: TODAS as escolas da rede, em ordem alfabética (`ordem_nome`).
* **Sem dado pessoal**: nenhum `aluno_id`, nome de aluno ou turma; o k é o da análise (5).

### 7.2 De onde vêm os números

Nada é relido nem medido de novo: o diagnóstico **combina** as saídas que já existem.

* **Oficiais**: `indicadores.indicadores_da_escola` — as séries da escola (com a
  proveniência, a meta oficial, o `instavel`, o `tps_zero` do IEE) e a série
  `rede_municipal` como referência; as quebras de escala são as da consulta oficial (2.4).
  As referências da rede na resposta (`referencias_rede`) são os pontos da mesma série
  `rede_municipal`.
* **Plataformas**: `plataformas.plataformas_da_rede` na janela pedida — a mesma cobertura, a
  mesma soma da rede (só escolas visíveis com a coleta em dia, 3.5) e a **mesma decisão de
  supressão**: escola suprimida na aba de plataformas é suprimida aqui (há teste que confere
  os números de cada escola contra a rota de plataformas).

### 7.3 Avaliações oficiais por escola (`oficiais`)

Séries, nesta ordem: IEE (anos iniciais), Ideb (anos iniciais), SARESP 5º ano LP e MT,
SARESP 2º ano LP e MT, Saeb 5º ano LP e MT (o ICA fica de fora: não existe por escola). Por
série, a **última edição com número oficial** da escola (`proveniencia = oficial`). A
Estimativa Constela e o número sem registro do arquivo oficial **nunca** entram — viram
sinal de dados (7.5).

| Campo | Regra |
|---|---|
| `valor_rede`, `diferenca_rede`, `posicao_rede` | a rede municipal na **mesma edição**, só se a série é comparável; diferença na menor precisão publicada dos dois lados (a conta do ICA, `consulta._diferenca`); posição `acima` / `abaixo` / `na_media` |
| `motivo_sem_comparacao` | sempre que a posição é nula: IEE (não existe para a rede), média instável, rede sem resultado oficial na edição, série não comparável |
| `anterior`, `tendencia` | a edição oficial **anterior da mesma série** (pulando as edições sem número oficial); `subiu` / `caiu` / `estavel`; nula se houver **quebra de escala entre as duas** (o motivo é o texto da quebra) ou se uma das duas for instável (`motivo_sem_tendencia` diz qual: com só a **anterior** instável, a atual é estável e mantém a posição contra a rede — o motivo cita a edição anterior, nunca "não se compara com a rede") |
| `situacao_meta` | a da consulta oficial: IEE pelo ICM da SEDUC; Ideb ≥ meta (só até 2021) |
| `instavel`, `tps_zero` | SARESP com TPS = 0; IEE calculado com médias de TPS = 0 (o número oficial do IEE continua **não** marcado instável — 2.4) |

**Tolerâncias** ("na média" = diferença **menor** que; diferença igual já é acima/abaixo):

| Indicador | Posição contra a rede | Tendência |
|---|---|---|
| IEE | — (não existe para a rede) | 0,2 |
| Ideb | 0,2 | 0,2 |
| SARESP (2º e 5º ano) | 5 pontos | 5 pontos |
| Saeb (5º ano) | 5 pontos | 5 pontos |

**Média instável** (TPS = 0) e o **IEE calculado com ela** nunca geram sinal de posição nem
de tendência; a meta oficial do IEE (ICM) continua valendo como sinal oficial.

### 7.4 Plataformas por escola (`plataformas`)

Da janela pedida: `cobertura` e `ultima_coleta` da escola e, por plataforma (`null` se o
módulo não é contratado): Elefante — `participacao_pct`, `livros_por_aluno`,
`minutos_por_aluno`, `taxa_acerto_pct`; Matific — `participacao_pct`,
`atividades_por_aluno`, `desempenho_medio`; e `suprimido` (escola suprimida, poucos medidos,
séries suprimidas ou participação/intensidade escondidas em complemento).

`posicao_participacao` e `posicao_intensidade` (intensidade = livros novos por aluno no
Elefante; atividades por aluno no Matific) contra o valor da **rede na mesma janela**, só
quando:

1. a escola não está suprimida e tem o número;
2. a cobertura da escola é `ok` (coleta parcial ou ausente: sem posição — sem dado não é
   zero);
3. a rede tem o número (não suprimida nem sem coleta);
4. pelo menos **3 escolas** da rede (visíveis, com a cobertura `ok`) têm a métrica — com
   menos, a "rede" é quase a própria escola.

Tolerâncias: participação **5 p.p.** (diferença em pontos percentuais, 1 casa);
intensidade **15% do valor da rede** (diferença relativa, em %, 1 casa; com a rede em 0,
qualquer valor positivo é acima). Senão, posição nula com `motivo_sem_comparacao` (a média
escondida em complemento diz que está protegida — não que falta). A
referência da rede inclui a própria escola (está em `referencias_plataformas`, com quantas
escolas têm cada métrica).

### 7.5 Sinais (`sinais[]`)

Cada sinal: `codigo`, `eixo` (`avaliacao` | `plataforma` | `dados`), `componente` (`lp` |
`mt` | `geral`), `natureza` (`oficial` | `calculado` | `plataforma` | `dados`), `direcao`
(`favoravel` | `atencao` | `informativo`), `texto` (pt-BR, com edição/período e valores) e
`referencia` ("IEE 2025", "Ideb 2023", "SARESP 2025 · 5º ano · LP", "Elefante ·
01/01/2026–31/12/2026"...). Também `ano`, `indicador` e `plataforma`, para a exportação.

| Código | Eixo | Natureza | Direção |
|---|---|---|---|
| `meta_atingida` / `meta_nao_atingida` (IEE pelo ICM; Ideb até 2021) | avaliação (geral) | oficial | favorável / atenção |
| `acima_da_rede` / `abaixo_da_rede` / `na_media_da_rede` (Ideb, SARESP, Saeb) | avaliação | calculado | favorável / atenção / informativo |
| `subiu` / `caiu` / `estavel` (IEE, Ideb, SARESP, Saeb) | avaliação | calculado | favorável / atenção / informativo |
| `participacao_acima_da_rede` / `_abaixo_da_rede` / `_na_media` | plataforma (Elefante → lp, Matific → mt) | plataforma | favorável / atenção / informativo |
| `intensidade_acima_da_rede` / `_abaixo_da_rede` / `_na_media` | plataforma | plataforma | favorável / atenção / informativo |
| `sem_codigo_inep`, `sem_resultado_oficial`, `so_estimativa`, `numero_sem_registro`, `media_instavel`, `coleta_parcial`, `sem_coleta_no_periodo`, `sem_alunos_no_recorte`, `sem_conta_na_plataforma`, `modulo_nao_contratado`, `celula_protegida` | dados | dados | **sempre** informativo |

Componente dos sinais de avaliação: SARESP e Saeb → `lp`/`mt`; IEE e Ideb → `geral`.
**Falta de dado nunca vira atenção.**

### 7.6 Leituras por componente (`leituras.lp`, `leituras.mt`)

* `avaliacao` — o estado dos sinais de avaliação **do componente** (SARESP e Saeb de LP ou
  de MT); sem nenhum, os **gerais** (IEE e Ideb), com `base = "geral"` (senão
  `"componente"`; sem sinal nenhum, `null`). Estado: `favoravel` (só favoráveis),
  `atencao` (só atenção), `misto` (os dois) ou `sem_dado` — **nenhum sinal favorável nem de
  atenção**: ou não há número comparável, ou há e está na média/estável. O `motivo` diz
  qual dos dois casos é. O nome `sem_dado` é o do contrato, mas o sentido é "sem sinal com
  direção": a tela deve escrevê-lo como "Sem sinal" e mostrar o `motivo` — nunca "sem dado"
  para quem está na média.
* `plataforma` — o mesmo com o Elefante (lp) ou o Matific (mt).
* `categoria`: favorável + favorável → `convergente_favoravel`; atenção + atenção →
  `convergente_atencao`; atenção (avaliação) + favorável (plataforma) →
  `divergente_uso_alto`; favorável (avaliação) + atenção (plataforma) →
  `divergente_uso_baixo`; qualquer `misto` ou `sem_dado` → `inconclusiva`, com `motivo`.
* `texto` curto; `anos = {avaliacao, plataforma}`: `avaliacao` = a maior edição entre os
  sinais **favoráveis/de atenção** da avaliação (os que decidem o estado — o mesmo filtro de
  `referencias`; um "na média" mais novo não muda o ano); sem nenhum sinal com direção, a
  maior edição dos sinais informativos, **só para exibir**. `plataforma` = o ano letivo da
  janela.
* `comparabilidade`:
  * `mesmo_ano` (ainda assim associação, nunca causa) só quando **todos** os anos desses
    sinais com direção são o ano letivo das plataformas, **todas** as escolas estão nesse ano
    letivo (`janela.anos_letivos` com um ano só) e o período está dentro dele — a mesma
    exigência da relação (4, `periodo_sem_sobreposicao`);
  * `exploratoria` nos outros casos (resultados oficiais de outra edição/coorte e uso das
    plataformas em outro ano: não mede a mesma população nem o mesmo período), com os anos
    no `texto_comparabilidade` ("Avaliação de 2023 e 2025; plataformas de 2026", escolas em
    anos letivos diferentes ou o período que não cabe no ano);
  * `null` quando falta um dos lados, ou quando a avaliação não tem nenhum sinal com direção
    e cumpriria o resto do `mesmo_ano` (nenhuma edição decide a leitura — nunca "mesmo
    ano"); sempre com `texto_comparabilidade`.
* `referencias` = as referências dos sinais favoráveis/de atenção usados.

### 7.7 Nível de acompanhamento (`acompanhamento`)

Na ordem (vale o primeiro que se aplica):

1. `prioritario` — alguma leitura `convergente_atencao`;
2. `acompanhar` — alguma `divergente_uso_alto`, ou meta oficial do IEE ou do Ideb não
   atingida (na última edição oficial);
3. `oportunidade` — alguma `divergente_uso_baixo`;
4. `dados_insuficientes` — sem nenhum número oficial **e** sem plataforma medida;
5. `sem_sinal` — o resto.

`motivos` = os textos que levaram ao nível, cada um com a referência dos sinais. No
`sem_sinal` sem nenhum sinal favorável nem de atenção (tudo na média, estável ou sem
comparação válida — média instável, primeira edição, coleta parcial, k), o motivo diz
isso: falta de comparação não é tranquilidade.

O `texto` da leitura põe as duas fontes lado a lado ("apontam para o mesmo lado" /
"apontam para lados opostos"), sem "mas" nem verbo de efeito: divergência não é
explicação. Do lado da avaliação não se escreve "em relação à rede", porque o sinal pode
ser a meta oficial ou a tendência; do lado da plataforma, sim (o único sinal com direção ali
é a posição contra a rede).

### 7.8 Resposta

`rede`, `janela` (a da rota de plataformas), `gerado_em`, `k_minimo`, `modulos`,
`criterios` (`tolerancias`, `n_minimo_escolas_comparacao = 3`, `regras` em pt-BR),
`referencias_rede` (a rede municipal nas edições usadas e na mais recente de cada série),
`referencias_plataformas`, `escolas[]` (`id`, `nome`, `codigo_inep`, `status`,
`pendencias`, `oficiais`, `plataformas`, `sinais`, `leituras`, `acompanhamento`), `resumo`
(`por_nivel`, `por_categoria` por componente, `escolas_total`, `escolas_com_oficial`,
`escolas_com_plataforma`, `anos`), `limitacoes`, `metodologia` e `fontes` (as fontes de
cada número oficial citado).

### 7.9 Limitações

* Hoje as avaliações por escola vão até 2025 (SARESP/IEE) e 2023 (Ideb/Saeb) e as
  plataformas são de 2026: toda leitura é **exploratória** — mesma escola e mesma série não
  são as mesmas crianças.
* As tolerâncias são **critérios do Constela** (para não chamar de diferença o ruído de
  arredondamento ou de escola pequena), não critérios oficiais.
* A referência das plataformas é a soma da rede com a própria escola dentro; com poucas
  escolas medidas (menos de 3), não há posição.
* Saeb: o da escola vem do arquivo do Ideb por escola e o da rede, da planilha do INEP
  (mesma escala e mesma rede de ensino, fontes diferentes).
* Ideb e Saeb: 2021 foi a edição da pandemia, e o universo avaliado e os critérios mudaram
  ao longo das edições (o aviso da consulta oficial vale para a série toda); a tendência é
  calculada (não há quebra de escala declarada), mas deve ser lida com cuidado.
* Coleta parcial, coleta ausente e a supressão k deixam a plataforma sem posição: a escola
  aparece, com o sinal de dados, e nunca com zero.

## 8. Evolução das plataformas por bimestre

`GET /redes/{id}/analise/plataformas/evolucao?serie&escola_id&so_escola` (`exigir_rede`).
Serviço: `evolucao.py`. Só leitura.

* **Cada bimestre é um período da rota de plataformas**: `plataformas_da_rede` com o preset
  oficial `bimestre_1..4` (o calendário oficial de `services/bimestres`, pelo serviço de
  períodos). Os números de cada bimestre são exatamente os da aba de plataformas com aquele
  bimestre — a mesma coorte, a mesma cobertura e as mesmas fórmulas (há teste que confere,
  bimestre a bimestre, rede e escolas). Os bimestres são lidos JUNTOS
  (`plataformas_da_rede_por_periodo`): as consultas ao banco são as mesmas para um ou
  quatro bimestres e para qualquer número de escolas (em produção a API fica a ~195 ms do
  banco por consulta).
* **`so_escola`** (a ficha da escola; pede `escola_id`): mede só a escola, com a supressão
  decidida pela rede inteira — os números dela são os mesmos da evolução da rede. A rede não
  é medida: `rede` sai nulo em cada bimestre e `filtros.so_escola = true`. Sem
  `escola_id`: 422; escola de outra rede: 404, como sempre.
* **Só os bimestres que já começaram** (início ≤ hoje); o que contém hoje vem com
  `em_andamento = true` (números parciais, até hoje).
* **Ano**: o ano letivo de referência da rede (3.1: o mais comum entre as escolas em uso);
  na ficha (`so_escola`), o ano letivo da própria escola. Se ele não é o ano de hoje (a virada de ano antes de a escola trocar o ano letivo), as datas são as do
  calendário daquele ano, pedidas como período personalizado — o mesmo resultado. Ano sem
  calendário oficial: as datas aproximadas do serviço de períodos, com o aviso em
  `limitacoes` (`calendario_oficial = false`).
* **Resposta**: `ano_letivo`, `k_minimo`, `filtros`, `modulos`, `calendario_oficial`,
  `bimestres[]` (`numero`, `rotulo`, `inicio`, `fim`, `em_andamento`, `rede` — Elefante:
  `participacao_pct`, `livros_por_aluno`, `minutos_por_aluno`; Matific: `participacao_pct`,
  `atividades_por_aluno`; `escolas_com_dado` e `escolas_parciais` por plataforma —, e
  `escolas[]` em ordem alfabética com `cobertura`, `suprimido` e, por plataforma,
  `participacao_pct` e a intensidade) e `limitacoes`. Plataforma não contratada: `null`. Sem
  número: o campo nulo com `motivo_sem_dado`/`texto_sem_dado` do serviço (ausência ≠ zero);
  escola suprimida: `motivo_sem_dado = suprimido` em todos os bimestres.
* **Supressão**: decidida pelas contagens (3.5), igual em todos os bimestres; a proteção por
  métrica é a de cada período. A rota não abre nada que a rota de plataformas já não mostre
  escolhendo o bimestre.
* **Limitações**: bimestres têm tamanhos diferentes (e o em andamento vai só até hoje):
  livros e atividades por aluno crescem com o número de dias — compare a participação com
  mais tranquilidade; a escola sem coleta num bimestre aparece sem dado naquele bimestre.
