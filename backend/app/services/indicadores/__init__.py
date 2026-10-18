"""Indicadores oficiais de referência (INEP/SEDUC) por território.

Pacote das etapas E2+ do plano de indicadores oficiais. Cada fonte tem um parser
PURO (bytes → linhas canônicas + avisos, sem banco) e passa pelo mesmo fluxo:
prévia (nada gravado) → aplicação (transação única, idempotente) → desfazer
(exato, pelo estado anterior guardado na importação).

* ``ica`` — parsers das planilhas "resultados e metas" do Indicador Criança
  Alfabetizada (municípios; UFs e Brasil);
* ``aeeb`` — parser ``inep_aeeb_agregados`` das tabelas agregadas TS_MUNICIPIO e
  TS_ESTADO dos microdados (percentual com 2 casas, média de LP, níveis 0–8);
  recusa qualquer arquivo de aluno;
* ``zip_parcial`` — lê só as entradas pedidas de um zip (local ou por HTTP Range),
  com CRC32 conferido e ZIP64; nunca lê o TS_ALUNO;
* ``pacote`` — o pacote recortado (CSV canônico + manifesto) e a validação dele no
  servidor;
* ``preparar`` — a linha de comando que gera o pacote nesta máquina
  (``python -m app.services.indicadores.preparar``) — dos microdados do ICA ou, só
  de zip local, do Ideb por escola;
* ``pipeline`` — prévia, aplicação, precedência entre arquivos e desfazer pelo id;
* ``consulta`` — a leitura da rede (série, metas, nível, participação, média de
  LP, níveis, SP e Brasil na mesma rede, cada número com a fonte);
* ``seduc`` — parsers dos arquivos abertos da SEDUC-SP (E4): IEE por escola (com a
  ponte CIE↔INEP), SARESP por município (CODMUN da rede) e por instância (Estado);
  o ``seduc_saresp_escola`` fica para depois (arquivo não autorizado);
* ``pipeline_seduc`` — prévia, aplicação e desfazer do SARESP oficial, inclusive a
  substituição EXPLÍCITA da média calculada pelo Constela (D2); o mesmo fluxo de
  escolas recebe outras famílias de arquivo (``Familia``);
* ``ideb`` — parser ``inep_ideb_escolas`` do Ideb por escola dos anos iniciais (E6a):
  Ideb e Saeb do 5º ano em ``resultados_avaliacao``; N, P, aprovação e metas em
  ``indicadores_referencia`` (a edição 2025 entra pelo mesmo parser);
* ``ideb_territorio`` — parsers ``inep_ideb_municipios`` e ``inep_ideb_uf_brasil``
  (E6b): o Ideb, a nota do Saeb, N, P, aprovação e metas da rede MUNICIPAL do
  município, de SP e do Brasil (por rede), em ``indicadores_referencia``;
* ``pacote_ideb`` — o pacote recortado do Ideb (topo da planilha + só a rede ou o
  território) e a validação dele no servidor; ``pipeline_ideb`` — a família do Ideb
  no fluxo de escolas (prévia, aplicação, desfazer), por escola e do território;
* ``saeb_planilha``, ``pacote_saeb`` e ``pipeline_saeb`` — a planilha do Saeb por
  Brasil, estados e municípios (E7): médias e distribuição por nível do 5º ano (rede
  municipal do município, SP e Brasil; Total separado de Urbana/Rural), o 2º ano
  amostral e a taxa de alfabetização de 2021 (só UF e Brasil, nunca o ICA);
* ``consulta_saresp`` e ``consulta_ideb`` — a leitura da rede do SARESP oficial (E5)
  e do Ideb/Saeb por escola (E8a: série 2005–2025, meta × observado na precisão
  publicada, ausência com motivo, cobertura, números sem proveniência marcados);
  ``consulta_ideb_rede`` — o bloco da REDE MUNICIPAL (E8b): Ideb da rede × meta e × o
  Brasil nas redes municipais (a UF na rede pública, como contexto rotulado), o Saeb do
  5º ano da planilha com os níveis e o contexto amostral do 2º ano;
* ``escalas`` — escalas e níveis por ano; a régua dos níveis do Saeb; cortes do
  SARESP "a confirmar";
* ``consulta_escola`` — a leitura de UMA escola (E9, ``GET /escolas/{id}/indicadores``):
  os números oficiais dela (SARESP/IEE, Ideb/Saeb) e as referências da rede, de SP e do
  Brasil (o ICA só como indicador da rede), tirados das mesmas leituras da rede, sem
  nenhuma outra escola;
* ``conferir_fontes`` — a linha de comando da conferência MANUAL das fontes (E10, D12):
  só metadados (HEAD; ``package_show`` do CKAN), comparados com as importações
  registradas e o MANIFESTO; nunca baixa, nunca aplica, nunca roda sozinha.
"""
