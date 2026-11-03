# Identidade visual v2 do Constela Edu

Referência oficial aprovada pelo dono em 31/10/2026: três telas (Visão Geral, Ranking e
Critérios de Premiação). Este documento é a regra única para levar essa linguagem ao app
web inteiro. Ramo: `feat/identidade-visual-v2` (worktree `C:\Users\Administrator\worktrees\visual-v2`).

O que o dono destacou e que NÃO pode se perder:
- separação por blocos (cartões brancos de 20 px sobre fundo lavanda);
- a fonte e o tamanho (Poppins; títulos grandes, números grandes em negrito);
- na Visão Geral: o gráfico de alunos ativos por semana (Elefante Letrado × Matific) no
  centro, com o cartão escuro da premiação à direita e o botão de gerar certificados do
  top 3; desempenho por turma e destaques recentes embaixo;
- no Ranking: pódio dos 3 primeiros + a lista em ordem; botão de gerar certificados na
  própria tela e geração EM LOTE (ex.: top 5 Matific, top 3 Elefante);
- nos Critérios: explicação ampla e chamativa (barra colorida dos pesos, ícones pastéis),
  "mais cativante e menos extremamente pedagógico".

## 1. Regras que valem mais do que a estética

1. **Só dado real.** Nada de número de exemplo exibido como real. Quando não há dado:
   estado vazio explícito ("sem coleta" não é 0). Itens da referência SEM fonte real e
   que portanto NÃO entram (ou entram com o rótulo honesto ao lado):
   - "Próxima premiação · 12 dias": não existe data de premiação no sistema. Use
     **"Fim do Nº bimestre · em N dias"** (calendário oficial de bimestres).
   - Variação de posição (▲ 7 / ▼ 2) no ranking: não existe histórico de posição. **Omitir.**
   - "▲ 18%" nos indicadores: só com a comparação real da rota `/visao-geral` (abaixo).
   - "Contraturno", "Engajamento 10%", "Complexidade", "Frequência de uso", "Acertos
     Matific", "Brinde", "Avisar responsáveis", "Mostrar ranking aos alunos": não existem.
   - "Medalha" como documento: não existe; o botão é **"Gerar certificados"**.
   - Pontos "2.940 pts": a escala real da nota é 0–100 (ex.: "90,35"); mostrar a unidade real.
2. **Não mudar regra de negócio**: cálculo, pontuação, ranking, premiação, permissões,
   guardas de rota (App.tsx, rotasGuardadas), despacho por perfil, filtros por módulo
   (useModulos) e por turma (turmas_permitidas no backend).
3. **Não remover funcionalidade.** Texto explicativo longo pode ir para dentro de um
   "Como funciona" recolhível, tooltip ou drawer — sem apagar o conteúdo. Os textos de
   honestidade do dado (SeloFrescor, StatusIntegracao, SeloFonte, avisos de cobertura)
   ficam como estão (são garantia de dado real e estão ancorados em teste).
4. **Testes não podem ser enfraquecidos.** Se um teste precisar mudar, troque o SELETOR
   (ex.: `within(...)`), nunca a asserção. Mudança de texto visível = atualizar o teste no
   mesmo trabalho e registrar. Ver `docs/design` §6.

## 2. Tokens (já aplicados em `apps/web/tailwind.config.js` e `src/index.css`)

As escalas `indigo` e `zinc` do Tailwind foram REMAPEADAS — as telas herdam a identidade
sem trocar classe:

| Token | Valor | Uso |
|---|---|---|
| `indigo-600` | #6C5CE7 | cor de ação: botão primário, item ativo, aba ativa, links, série **Leitura · Elefante** |
| `indigo-700` | #5A4AD4 | hover; link sobre lavanda |
| `indigo-50/100` | #F3F1FE / #E8E4FD | fundo pastel violeta |
| `indigo-900/950`, `marinho-900` | #1F2250 / #17193B | barra lateral, cartão escuro de destaque |
| `zinc-50` | #F5F6FB | fundo da página (lavanda) |
| `zinc-200` | #E5E7F0 | bordas de cartão |
| `zinc-500` | #6B6F8E | texto secundário (4,9:1 no branco) |
| `zinc-900` | #1A1C38 | texto principal |
| `teal-500/600` | #14B8A6 / #0D9488 | série **Matemática · Matific** |
| `ouro-400` | #F5B942 | premiação, certificados (texto marinho por cima, NUNCA branco) |
| `medalha-ouro/prata/bronze` | #F5B942 / #CBD5E9 / #E0955A | 1º, 2º e 3º lugares |
| `rounded-cartao` | 20 px | cartões (`.card` já usa) |
| `shadow-cartao` | difusa | cartões, botões brancos |
| `shadow-pilula` | violeta | item ativo, botão primário |
| `shadow-ambar` | âmbar | botão de certificados |
| `shadow-flutuante` | — | menus, popovers, modais |

Tipografia: **Poppins em toda a interface** (400/500/600/700). Título de página 28 px bold
(`PageHeader`); título de cartão 16–17 px semibold; número de KPI 32 px bold; rótulo de
seção 11 px semibold em caixa alta com `tracking-[0.08em]` (caixa alta só por CSS:
`uppercase`, nunca texto literal "ALUNOS"); corpo 14 px; legenda 12 px. Números com
`tabular-nums`.

Espaço: padding de cartão 20–24 px (`p-5`/`p-6`); gap de grade 20–24 px (`gap-5`/`gap-6`).

Modo escuro: continua existindo (botão de tema). As escalas remapeadas já cobrem o escuro
(`dark:bg-zinc-900` = superfície #1A1C38, `dark:bg-zinc-950` = fundo #10122A).

Ícones: lucide-react, sempre com `aria-hidden` quando decorativos. Emojis só como enfeite
textual onde já existiam (não use emoji como único portador de informação).

## 3. Componentes (`apps/web/src/components/ui.tsx`)

Antigos (mesma assinatura, visual novo): `Card`, `SecaoRecolhivel`, `PageHeader`
(descricao aceita ReactNode), `StatCard` (+ `tom`, `variacao`), `Botao` (variantes
`primario` | `secundario` (= `neutro`) | `ambar` | `perigo` | `fantasma`; `tamanho`
sm|md|lg), `Badge` (+ tons `erro`, `info`), `Mensagem`, `Carregando`, `Vazio` (+ `icone`),
`Modal` (agora role=dialog, aria-modal, Esc, foco preso; `largura`), `Drawer`, `Campo`,
`estiloInput`.

Novos: `IconePastel` (ícone em quadrado pastel; tons violeta|teal|ambar|rosa|azul|verde|neutro),
`Variacao` (pílula ▲/▼/—, só com dado real), `BotaoIcone` (redondo 40 px, `rotulo`
obrigatório), `Chip` (ex.: turma "2º A"), `RotuloSecao` (rótulo em caixa alta), `Skeleton`,
`Erro` (estado de erro com "Tentar de novo"), `Confirmacao` (modal de confirmação),
`Abas` (abas segmentadas acessíveis: tablist/tab, setas, foco itinerante), `Interruptor`
(role=switch), `Avatar` (iniciais, cor estável, aria-hidden), `iniciaisDoNome`,
`corDoAvatar`, `Medalha` (SVG com fita, sr-only "Nº lugar"), `PosicaoBolinha`,
`BarraProgresso`, `classesTabela` (classes da tabela padrão), `ESTILOS_BOTAO`/`TAMANHOS_BOTAO`
(para estilizar `<a>`/`<Link>` como botão).
Para o celular (D32–D33): `classesAbas`, `useAbaAtivaVisivel` e `mostrarAbaNaLista` (ui.tsx);
`TabelaRolavel` (components/TabelaRolavel.tsx); classes `presa-celular` e
`presa-esquerda-celular` (index.css).

Regras de uso:
- **Não editar** `ui.tsx`, `tailwind.config.js` nem `index.css` nas telas: se faltar algo
  genérico, crie um componente num arquivo NOVO em `src/components/` com nome próprio e
  registre no relatório do trabalho.
- `<select>` continua NATIVO (estilize com `estiloInput`/`appearance-none`): ~30 testes e
  o E2E usam `selectOptions`.
- Avatares, medalhas, selos e chips dentro de `<a>`/`<button>`: `aria-hidden` (já é o
  padrão do `Avatar`/`Medalha`), para não mudar o nome acessível.
- Não DUPLICAR conteúdo no DOM (ex.: pódio que repete os links/nomes da tabela): o pódio
  não leva link; o link fica só na tabela. Nada de render duplo responsivo (tabela + cards
  com `hidden md:block`) — o jsdom sem CSS mostra os dois.
- Nunca "—" como variação neutra (há testes que usam "—" como "sem dado").
- Gráficos: `Grafico.tsx` tem snapshots; só props/componentes ADITIVOS.

## 4. Casca (Layout)

- Barra lateral marinho (#17193B), logotipo oficial (símbolo "C" + constela/EDU, versão
  para fundo escuro — não inventar logotipo novo), seções em caixa alta **de cada perfil**
  sobre os grupos (D38–D43, D49–D53 e D55; antes, **PROJETO** e **GESTÃO** para todos — nenhuma rota some,
  ninguém passa a ver o que não via), item ativo em pílula violeta com sombra, cartão
  **ESCOLA** (**CONTEXTO** para a Secretaria) e cartão do usuário no rodapé.
- Cabeçalho transparente sobre a lavanda, botões redondos (busca, notificações, tema).
- Conteúdo com `max-w-7xl`, `px-8 py-8` no desktop.
- Selo em "Premiações": dias até o **fim do bimestre** pelo calendário oficial, com o texto
  completo no `title`/nome acessível (nunca "dias para a premiação").

## 5. Rotas novas no backend (só leitura, sem migração)

1. `GET /escolas/{id}/visao-geral?periodo=bimestre` — indicadores do período e da MESMA
   janela do período anterior (mesmo número de dias desde o início do bimestre anterior):
   alunos ativos (por plataforma e união, com a regra correta: Elefante = leitura no
   período; Matific = ganho > 0), livros novos, tempo de leitura, atividades do Matific.
   Sem lista de alunos, sem auditoria por visualização, recortado por turmas permitidas e
   por módulos; Secretaria negada.
2. `GET /escolas/{id}/atividade-semanal?semanas=8` — % de alunos da coorte com atividade em
   cada semana, por plataforma; semana sem coleta = `null` (lacuna no gráfico), nunca 0;
   denominador declarado.
3. `POST /escolas/{id}/certificados/lote/previa` e `POST /escolas/{id}/certificados/lote` —
   o MESMO certificado da rota individual, para até 50 alunos de uma vez, com as MESMAS
   guardas por aluno (módulo, aluno da escola, professor só os seus, ativo, 1º–5º ano,
   Lista Piloto, mérito no Geral). A prévia diz quem está apto e o motivo de cada recusa; a
   geração devolve UM PDF com uma página por aluno apto, na ordem pedida, e grava
   `certificado.emitido` por aluno. Recusado NÃO é substituído pelo próximo colocado.
4. `GET /redes/{id}/destaques` (rodada 3) — as escolas em destaque do Panorama da Rede, pelo
   MESMO critério e pela MESMA função da vitrine pública (`_top_escolas`: ativas, módulos
   contratados, k mínimo de quem conta e de quem soma, top 5), devolvendo `escola_id`. Mesma
   dependência de acesso do `/redes/{id}/dashboard`; para a Secretaria, sai da lista a escola
   cuja matéria o cartão dela esconde (grupo pequeno), contada em `fora_por_protecao`.

## 6. Decisões registradas (tomadas na implementação, revisáveis pelo dono)

- D1. Fonte única Poppins (as referências usam uma geométrica em toda a interface).
- D2. Remapear `indigo`/`zinc` em vez de reescrever as ~3.400 classes das telas.
- D3. Logotipo oficial mantido (o das referências era ilustrativo); só ganha a versão
  sobre fundo escuro.
- D4. "Dashboard" passa a se chamar "Visão geral" no menu (a referência aprovada usa esse
  nome); "Pontuação"/"Métricas" passam a "Critérios" no menu. As rotas não mudam.
- D5. Cartão de premiação: "Fim do Nº bimestre · em N dias" + pódio real da categoria
  escolhida (Leitura = Melhor Leitor; Matemática = Melhor Matemática), com a unidade real.
- D6. Comparação dos indicadores: mesma janela de dias do bimestre anterior (comparar um
  bimestre em curso com um bimestre inteiro enganaria).
- D7. "Top N" do lote = os N primeiros da lista que a tela está mostrando (aba e filtros
  atuais), na ordem do backend. Modelo do certificado pela aba: Leitura → arte Elefante,
  Matemática → arte Matific, Geral → certificado Geral.
- D8. Coluna de variação do ranking omitida (sem histórico de posição no sistema).
- D9. Critérios: a escola vê a régua EFETIVA (pesos reais de `/pontuacao/regra`) em formato
  visual, sem sliders "vivos" (ela não pode alterar); o Admin Global vê os mesmos cartões
  com os editores reais (sliders e "Salvar pesos"). Sem "prévia ao vivo" com pesos não
  salvos (não existe cálculo de prévia no backend; uma segunda fórmula no front é proibida).
  "Regras da premiação" mostra só as regras reais e fixas (4 categorias, elegibilidade,
  desempate), sem toggles fictícios.
- D10. Telão (/p/:token) e vitrine da rede (/rede/p/:token) mantêm a identidade própria
  (testes e uso em TV); fora deste ramo.
- D11. Abas Leitura e Matemática do Ranking: o bloco principal (pódio + lote) é a lista do
  PERÍODO; a classificação oficial do ano e a competição por turno ficam em seções
  recolhíveis logo abaixo. Inverter é uma prop (`inicialAberto`).
- D12. Premiações: "Certificados do pódio" em cada categoria e nas duas de Evolução (as
  artes são de participação). O lote usa o pódio exibido (até 5); Top 10/50 de uma
  premiação exigiria buscar `?limite=N` antes (decisão do dono).
- D13. Visão geral da escola: pílula de variação só com valor anterior > 0 e comparação
  não nula; o Top 3 do cartão escuro é a categoria Melhor Leitor/Melhor Matemática do
  bimestre em curso; o professor vê o cartão (o backend recorta as turmas dele) e não vê
  "Desempenho por turma" (o `/resumo-escola` nega o professor).
- D14. Rótulos honestos: o contador do Elefante é VITALÍCIO (a sync pede LIFETIME) —
  aparece como "acumulado"/"desde o início no Elefante", nunca "no ano"; o engajamento do
  Insights é dos últimos 30 dias. Cobertura parcial do Matific com texto neutro (há
  quatro causas no backend).
- D15. Visão geral (`services/visao_geral.py`): a Leitura compara os mesmos dias que a
  coleta cobriu; base do Matific bem anterior ao início não é "completa"; no gráfico
  semanal, semana cuja borda não foi coletada é lacuna (a atividade não migra de semana).
  Com coletas esparsas (agendador desligado) o gráfico mostra lacunas — é o honesto.
- D16. Confirmação antes de GRAVAR nas três importações (a prévia continua sendo a
  conferência; o diálogo resume só números reais da prévia). Livros: `window.confirm`
  virou a `Confirmacao` da v2, com o mesmo PATCH/DELETE.
- D17. Menu: Suporte no rodapé fixo da barra; abaixo de 1280 px (D25) o seletor de escola
  e o menu do usuário ficam dentro da gaveta (um só controle por largura). A pesquisa global
  acha as páginas também pelos nomes antigos (Dashboard, Pontuação, Métricas).
- D18. Cores de série: Leitura #6C5CE7, Matemática #0D9488 (teal-600; o teal-500 dava
  2,49:1 sobre branco). (A ressalva sobre a Análise educacional foi resolvida na D22.)
- D19. Confirmação da v2 (`Confirmacao`) em TODA ação destrutiva, irreversível ou que
  expõe dado; nenhum `window.confirm` restou no app web. Trocados: Assistente de IA
  (desligar), Restaurar backup, Remover nível, Painel Público (novo endereço e nome
  completo no telão), desfazer importação (ICA e indicadores oficiais), aplicar prévia
  de indicadores oficiais, remover edição e fonte de avaliação. Novos (antes eram um
  clique): **Desativar escola** (o texto diz o efeito real — sai do seletor e da vitrine,
  o telão para, nada é apagado, o acesso de quem tem conta continua) e **remover meta**
  da rede. A ação depois do "sim" é a MESMA chamada de antes. "Aplicar esta prévia" do
  ICA segue sem diálogo: a prévia na tela é a conferência e a importação pode ser desfeita.
- D20. Secretaria (rede vinculada, só leitura): em Turmas não vê criar, editar, excluir,
  arquivar nem a seleção em massa (o backend já respondia 403). Professores já escondia.
- D21. Perfil do aluno: a aba "Histórico de Leituras" só aparece com o módulo Leitura
  contratado (`useModulos`). Os cartões de nota por plataforma continuam com "—" sem o
  módulo (convenção já existente; esconder é decisão do dono).
- D22. Gráficos na paleta v2, todas as séries com ≥ 3:1 no claro e no escuro: #6C5CE7,
  #0D9488, #D97706, #DC2626, #0284C7, #DB2777, #64748B, #9333EA (o #7C3AED dava 2,91:1 no
  escuro). Série principal violeta, meta ardósia tracejada, Brasil vermelho, UF âmbar.
  Escalas sequenciais = escala `indigo` remapeada. Faixas do mapa e das bolinhas da rede
  em emerald/amber/red-600; barras de peso dos Critérios em 600 (o ouro-400 dava 1,8:1).
- D23. Contraste e foco: avatares em tons 700 (iniciais brancas ≥ 4,5:1); selo de
  notificação rose-600. Modal e gaveta leem quem abriu no render e, se esse botão sumir
  (linha removida), o foco vai ao título da página em vez do `<body>`. O contêiner fixo do
  Modal tem `m-0` (dentro de um pai com `space-y-*` o véu deixava uma faixa descoberta).
- D24. Varredura visual (`e2e-visual/`): 8 larguras (1920, 1440, 1366, 1280, 1180, 1024,
  820, 768), 5 perfis (coordenação, professor, Admin Global, Admin Global com rede e
  Secretaria — a rede e a conta da Secretaria são criadas pela própria API no banco
  descartável do seed) e inspeções próprias em `inspecao.ts`, sem dependência nova: h1,
  nome acessível, rótulo de campo, alt, ids repetidos, contraste AA, elemento que passa da
  borda, texto truncado sem `title` e foco visível com Tab. Regra que saiu dela: texto com
  `truncate` que mostra um valor dinâmico leva `title` com o mesmo valor (trava em
  `src/test/truncadoComTitle.test.ts`); onde há espaço, o nome quebra em até duas linhas.
- D25. Barra lateral fixa só a partir de 1280 px (`xl`); de 1024 a 1279 px (tablet
  deitado) a navegação fica na gaveta e o conteúdo ganha ~960 px — o mesmo do notebook
  1280 com a barra. A revisão visual mostrou que com a barra em 1024 sobravam ~700 px e os
  layouts de duas colunas (`lg:`) quebravam só no tablet deitado. A lista do menu tem
  esmaecido em cima e embaixo quando há itens escondidos; as tabelas largas mostram sombra
  de rolagem lateral (`.sombra-rolagem-x`).
- D26. "Gerar certificados" do cabeçalho do Ranking em âmbar, como na Visão geral e em
  Premiações (o âmbar é da premiação/certificados).
- D27. O item do Admin Global para `/rede` passa a se chamar "Painel da Rede" (o mesmo da
  trilha, do h1 e do menu da Secretaria); a pesquisa ainda acha por "secretaria".
- D28. Tabelas que perdiam a coluna de ações no tablet: Turmas mostra o turno sob o nome
  (sem coluna própria, uma vez só no DOM); Usuários mostra o e-mail sob o nome; Sessões
  junta cargo e escola e mostra o último acesso sob a última atividade. Nenhum dado some.
- D29. Evolução do aluno: sem prova de coleta antes do início do período, a tela não
  afirma "era 0,0" nem mostra a variação (o backend devolve 0,0 quando não há coleta).
  Correção definitiva no backend (`inicial = null`/data da 1ª coleta) fica registrada
  como pendência.

Celular (375 e 414 px), revisão de prontidão para a demo de 04/11/2026:
- D30. Grade responsiva sempre com coluna base (`grid-cols-1` ou `grid-cols-2`): sem ela
  a trilha implícita `auto` alargava a página no celular (trava em
  `gradeComColunaBase.test.ts`). Itens de grade/flex com texto truncado levam `min-w-0`.
- D31. Cartões de indicador (`StatCard`) 2 por linha no celular; com número ímpar, o último
  ocupa a linha (`max-sm:[&>*:last-child:nth-child(odd)]:col-span-2`). O número do
  `StatCard` cai para 24 px abaixo de 640 px e quebra em vez de vazar. Exceção: o resumo
  de alertas de Insights (cartão horizontal) continua um por linha.
- D32. Tabela larga no celular: `TabelaRolavel` (rola dentro do cartão, degradê na borda e
  o aviso escrito "Deslize a tabela para o lado..." acima dela). A coluna que não pode
  sumir (nota, índice, ações) usa `presa-celular` (presa à direita) e a 1ª coluna, quando é
  ela que identifica a linha (turma, série), `presa-esquerda-celular`. Com menu ⋮ ou
  janela aberta dentro da célula presa, ela sobe acima do cabeçalho fixo (index.css).
- D33. `Abas` abaixo de 640 px: uma linha que rola de lado (sem barra visível, com sombra
  de borda), rolando sozinha até a aba ativa; do sm em diante, como antes. As abas do
  Ranking ficam em grade 2 × 2 de colunas iguais (escolha da tela).
- D34. Alvo de toque de 40 px no celular: `Botao` tamanho sm (`max-sm:min-h-10`), o ⋮ do
  `MenuSuspenso` e as setas de reordenar. A caixa de ações do `PageHeader` ocupa a linha
  toda no celular.
- D35. `Vazio` e `Erro` com `px-5` em todas as larguras (o texto encostava na borda dos
  cartões sem padding); nos cartões que já têm padding o recuo soma, sem cortar nada.
- D36. Selects de filtro (turma em Matific/Elefante, provedor do assistente) com
  `appearance-none` e o chevron da v2 também no desktop, como os demais filtros.
- D37. Datas da API sempre no fuso de Brasília (`lib/formato`: `dataHora`, `dataDia`): a API
  serializa UTC sem marca de fuso e `new Date(iso)` lia como horário local (trava em
  `formatoFuso.test.ts`).

Navegação por perfil (feat/navegacao-inteligencia, 01/11/2026 — reorganiza a hierarquia,
mesmos componentes e cores; `components/Layout.tsx`):
- D38. Menu em seção › [grupo ▸] › item, com as seções de CADA perfil no lugar de
  "Projeto"/"Gestão" fixas: Admin Global — Administração e Escola selecionada; Secretaria —
  Rede municipal, Inteligência pedagógica e Relatórios e fontes; coordenação e
  administração da escola — Escola e Gestão; professora — Minhas turmas e Reconhecimento.
  A página inicial mora no 1º grupo solto da 1ª seção. Rótulos existentes não mudam de nome nem de
  caixa; os novos vão em caixa de frase. "Critérios" virou um item só (eram dois idênticos,
  `metricas` e `pontuacao`). Nenhuma rota nem guarda mudou; a Secretaria ganhou o Ranking da
  Rede e as abas da análise (`/rede/analise?ver=…`) como itens. A árvore inteira de cada
  perfil e o `podeAbrirRota` de cada item ficam travados em `NavegacaoPerfis.test.tsx`.
- D39. Acordeão por TAREFA só onde há muitos itens (escola e global); Secretaria e professora
  sem acordeão. Grupo com um item (depois do filtro de módulos ou do cargo) é desenhado solto
  (`ehSolto`: Usuários da coordenação, Sessões Ativas do global). `inicialAberto` (Minha
  Escola; Redes e municípios) abre o grupo enquanto o usuário não escolheu; o grupo da rota
  atual abre sozinho; a escolha fica por grupo (`{chave: aberto}`) em
  `constela_menu_abertos_v3` — a chave antiga (conjunto de chaves de outra arrumação) é
  ignorada.
- D40. Item ativo por uma regra única (`itemAtivo`), com `aria-current` posto à mão (Link, não
  NavLink, que ignora a consulta e acenderia todas as abas): item com aba só na aba dele; item
  sem aba perde para um irmão com a aba da URL ou para uma rota mais longa (`/configuracoes` ×
  `/configuracoes/conquistas`); `ver=visao` ou uma aba desconhecida acendem o item sem aba (a
  página abre a visão geral); `ver=indicador` (nome antigo) conta como `avaliacoes`. Um item
  marcado por vez — o destaque, o grupo que abre sozinho, a barra recolhida e a trilha usam a
  mesma função.
- D41. Trilha em três níveis (≥ 1024 px): Início › contexto › página. O contexto é o grupo do
  item ativo, ou a seção quando o item é solto, e some quando repetiria a página; detalhes
  herdam o item pai (`/alunos/12` → Minha Escola › Perfil do aluno). A página tem o nome do
  item do menu do perfil (com a aba: "Avaliações externas"); os títulos especiais valem só
  fora do menu ("Importações (avançado)" para a escola, "Usuários e acessos" para a
  professora). Na falta de espaço corta primeiro o início (4×), depois o contexto (2×).
- D42. Barra recolhida: as seções do perfil em sequência, com um fio entre elas, e o primeiro
  acesso respeitado (antes ignorado): só "Comece aqui"; para o Admin Global, também Gerenciar
  Rede, Escolas e Usuários — lista explícita (`PRIMEIRO_ACESSO_GLOBAL`), que no menu aberto
  aparece sob "Administração" (antes dependia da chave literal do grupo "estrutura").
- D43. Ícones sem repetição dentro do menu de um perfil (a barra recolhida mostra só o ícone):
  Conquistas `Star`, Biblioteca `Medal`, Catálogo `Library`, Ranking da Rede `ListOrdered`,
  Escolas `Building`, Importações e fontes / Fontes dos indicadores `FileSearch`, Usuários
  `ShieldCheck` (o `UserCog` fica só com "Minha conta"); abas da Secretaria: Visão geral
  `ChartLine`, Avaliações externas `ClipboardCheck`, Elefante e Matific `MonitorSmartphone`,
  Relação `ScatterChart`, Diagnóstico `Stethoscope`, Por escola `School`, Relatórios e
  exportações `FileDown`. Todo item tem `busca` com nomes alternativos.
- D44. Textos que citam o menu seguem o caminho da trilha (contexto › item) e o menu de quem lê:
  o FAQ é escrito para a coordenação e traduzido para o admin da escola e o Admin Global
  (`caminhosDoMenu` em `suporteConteudo.ts`, também em "Os dados estão atualizados?");
  "cartão Escola" para quem não é Secretaria; no Panorama do global, "Redes e municípios ›
  Painel da Rede". O FAQ do global deixou de mandar escolher a escola "no topo" (o seletor
  está no cartão do rodapé desde a v2).
- D45. Panorama da Rede (modo análise), cartão "Escolas que precisam de atenção": uma linha no
  pé leva ao Diagnóstico pedagógico (`/rede/analise?ver=diagnostico`; o global leva `&rede=`
  da rede aberta), só para quem lê aquela rede. A regra do cartão (motivos do painel da rede)
  não muda: o cruzamento com as avaliações externas é outra leitura, com outra fonte.
- D46. Nome de GRUPO não é cortado na barra (w-64): os grupos novos têm nomes curtos —
  "Acompanhamento" (Elefante, Catálogo, Matific, Insights, Comparador, Assistente), "Regras de
  pontuação" (Critérios, Simulador, Editar conquistas) e "Configurações" (Usuários,
  Configurações Gerais). Item comprido continua com o nome inteiro no `title` (R20).
- D47. O menu leva o item ativo à vista rolando a PRÓPRIA lista (`scrollTop`), nunca com
  `scrollIntoView`: no Chromium este move o ponto de partida do teclado e o 1º Tab da página
  pulava o "Pular para o conteúdo" (WCAG 2.4.1) — já acontecia na v2 em toda página com item
  ativo (travado no E2E `e2e-analise`).
- D48. A gaveta do celular fecha em qualquer troca de rota feita pela pessoa ("Minha conta",
  atalhos, pesquisa), menos quando a própria página reescreve a consulta (navegação REPLACE).
  Dentro da análise, o item de aba do menu leva os filtros compartilhados da URL (série,
  escola, rede) e troca só a aba. O item das plataformas da Secretaria leva o nome do que a
  rede contratou ("Elefante e Matific", "Elefante Letrado" ou "Matific"), o mesmo da aba.

Rodada 2 — a Secretaria precisa ENTENDER o que vê (01/11/2026; reorganiza o menu, mesmos
componentes, cores e ícones lucide; nenhuma guarda nem permissão mudou):
- D49. Menu da Secretaria em quatro seções, do resumo ao detalhe — **Rede municipal**
  (Panorama da Rede `/`, Escolas em acompanhamento `/rede/acompanhamento`, Comparar escolas
  `/rede/escolas`), **Resultados** (Avaliações externas `/rede/avaliacoes-externas` e Elefante
  e Matific `/rede/plataformas` — avaliações oficiais e plataformas em itens separados, como
  nunca entram na mesma conta), **Relatórios e gestão** (Relatórios e exportações `/rede/relatorios`,
  Ranking da Rede, Painel da Rede) e **Aprofundar**, com UM acordeão, **Análises avançadas**
  (Diagnóstico exploratório `/rede/analise` — aba padrão, também `ver=diagnostico` —,
  Relação com as plataformas `?ver=relacao`, Análise detalhada por escola `?ver=escola`,
  Fontes e arquivos oficiais `/rede/avaliacoes`). O acordeão nasce FECHADO (sem
  `inicialAberto`): é a área secundária, técnica; abre sozinho só quando a rota é dele e, se
  a pessoa o abre pelo botão, vale a escolha dela (chave `avancadas` em
  `constela_menu_abertos_v3`). Na barra recolhida os itens dele aparecem como os demais (nada
  some). O item da tela das plataformas segue os módulos contratados (D48). "Fontes dos
  indicadores" continua o h1 de `/rede/avaliacoes`; o menu e a trilha dizem onde ele mora
  ("Análises avançadas › Fontes e arquivos oficiais"). As rotas novas usam a guarda
  `RotaRede` (a mesma de `/rede/analise`) e o teste exige que estejam no espelho
  `lib/rotasGuardadas.ts` (rota fora dele seria tratada como "sem guarda"). Substitui, para a
  Secretaria, o menu de D38/D39/D43 (seções "Inteligência pedagógica" e "Relatórios e fontes",
  sem acordeão) e a parte de D40 sobre os `ver` antigos: `/rede/analise?ver=visao`,
  `avaliacoes`, `indicador`, `plataformas` e `relatorios` viraram telas próprias e a página
  redireciona (Navigate replace) — nesse instante NENHUM item acende (antes `ver=visao`
  acendia a Visão geral e `ver=indicador` as Avaliações externas), senão o acordeão abriria
  pela rota e ficaria aberto depois do redirecionamento.
- D50. Admin Global, "Redes e municípios": Painel da Rede · **Visão da rede** `/rede/visao`
  (o Panorama da Secretaria com o seletor de rede) · Ranking da Rede · **Análises avançadas**
  (era "Análise educacional") · Importações e fontes · Gerenciar Rede. As telas novas da
  Secretaria não ganham item no menu do global: ele chega a elas pelos links da Visão da
  rede, e elas são `filhas` do item (`ItemNav.filhas`, endereço exato) — a Visão da rede fica
  acesa e a trilha diz "Redes e municípios › Comparar escolas" (o nome da tela vem dos
  títulos especiais). Entre as páginas que leem a rede escolhida em `?rede=` (essas telas e
  as Análises avançadas), o item do menu leva a rede junto (`destinoDoItem`,
  `PAGINAS_COM_REDE`): antes, quem escolhia a rede 2 na Visão da rede e voltava pelo menu caía
  na primeira rede sem aviso. Painel da Rede e Importações e fontes escolhem a rede de outro
  jeito e ficam com o caminho deles.
- D51. Coordenação e administração da escola: **Usuários** volta para **Minha Escola**
  (Visão da Escola, Turmas, Alunos, Professores, Usuários, Relatórios — as pessoas e as
  contas de acesso no mesmo lugar, como antes da v2); o acordeão "Configurações" saiu;
  **Configurações Gerais** fica solto na seção Gestão, só para o administrador (trilha
  "Gestão › Configurações Gerais"; `/configuracoes/conquistas` herda esse contexto). O Admin
  Global não muda (Usuários solto em Administração). O FAQ do Suporte segue: "Minha Escola ›
  Usuários" para os dois perfis da escola, "Administração › Usuários" para o global (a troca
  de "Minha Escola › Usuários" vem antes da de "Minha Escola ›" → "Gestão escolar ›"); o FAQ
  da Secretaria passou a usar os caminhos do menu dela, sem termo estatístico e sem causa e
  efeito.
- D52. Ícones novos, sem repetição dentro de cada perfil: Escolas em acompanhamento `Flag`
  (o sino fica com as notificações), Comparar escolas `GitCompareArrows` (a Secretaria não
  tem o Comparador de alunos), Avaliações externas `ClipboardCheck`, Elefante e Matific
  `MonitorSmartphone`, Relatórios e exportações `FileDown`, grupo Análises avançadas
  `FlaskConical`, Diagnóstico exploratório `Stethoscope`, Relação com as plataformas
  `ScatterChart`, Análise detalhada por escola `School`, Fontes e arquivos oficiais
  `FileSearch`. No global, Visão da rede `ChartLine` (o ícone da antiga "Visão geral" da
  análise, que o Panorama substitui) e Análises avançadas `Microscope` — o `FlaskConical` já
  é o Simulador no menu dele e a barra recolhida mostra só o ícone.
- D53. A pesquisa do topo acha as telas pelos nomes antigos e pelo assunto (`busca`):
  "análise educacional", "inteligência pedagógica" e "diagnóstico pedagógico" levam ao
  Diagnóstico exploratório (e "diagnóstico" também a Escolas em acompanhamento), "fontes dos
  indicadores" às Fontes e arquivos oficiais, "visão geral" ao Panorama, "vitrine"/"metas" ao
  Painel da Rede, "boletim"/"csv" a Relatórios e exportações; no global, "análise
  educacional" às Análises avançadas e "panorama da rede" à Visão da rede. Achar um item do
  acordeão fechado e abri-lo pela pesquisa abre o grupo (a rota é dele).
- D54. Rótulo de item do menu QUEBRA em até duas linhas (`line-clamp-2`, `leading-snug` —
  1,375 não corta o acento das maiúsculas) em vez de cortar com reticências, com altura
  MÍNIMA (36 px subitem, 40 px item solto) no lugar da fixa: o item de uma linha fica igual.
  Medido pelas larguras do Poppins (tabela hmtx, sem kerning) na barra de 256 px: cabem 178 px
  num item solto (14 px) e 146 px num subitem (13 px); "Escolas em acompanhamento" (≈218 px)
  e os quatro itens das Análises avançadas (≈160–192 px) cortavam — como já cortavam
  "Biblioteca de Conquistas" (≈164) e "Revisões de identidade" (≈152), que agora também
  quebram. O `title` com o nome inteiro continua (R20). Nomes de grupo seguem numa linha
  (D46: "Análises avançadas" ≈143 de 150 px).

### Rodada 3 — a Secretaria em três áreas (02/11/2026; `docs/navegacao/RODADA-3-SECRETARIA-TRES-AREAS.md`)

- D55. Menu da Secretaria com UMA seção, **Rede municipal**, e três itens soltos: **Panorama da
  Rede** `/` (LayoutDashboard; acende também em `/rede/plataformas`), **Escolas**
  `/rede/escolas` (School; acende na ficha `/rede/escolas/{id}`, em `/rede/ranking` e em
  `/escola`) e **Avaliações externas** `/rede/avaliacoes-externas` (ClipboardCheck; acende em
  `/rede/avaliacoes`). Sem acordeão e sem Análises avançadas para ela; Relatórios, Painel da
  Rede, Escolas em acompanhamento, Ranking e as análises saem do menu dela, mas as rotas e as
  guardas continuam (o Admin Global e os links internos usam). Supersede D49 para a Secretaria.
- D56. Atalhos da Secretaria: Alt+1 Panorama, Alt+2 Escolas, Alt+3 Avaliações externas; as
  demais teclas não navegam para ela (levavam a telas de escola sem uso para a rede). O
  cartão **Contexto** dela leva à FICHA da escola escolhida; "Toda a Rede Municipal" volta ao
  `/` quando a tela atual é de escola. O `/` dela é sempre o Panorama da Rede (o "Panorama
  Geral da escola" saiu; a ficha o substitui).
- D57. Cadastrada × ativa × com uso não são sinônimos: CADASTRADA é estar vinculada à rede;
  ATIVA é a situação do cadastro (não diz uso); COM USO no ano letivo é ter ao menos um aluno
  do 1º ao 5º ano que leu um livro no Elefante (inclusive releitura) ou fez uma atividade no
  Matific, pelas coletas (`situacaoDeUso.ts`). Sem coleta, sem conta ou sem alunos é SEM DADO; escola ou
  número escondido é PROTEGIDA; "sem uso registrado" só com a coleta em dia (ou com a data da
  coleta parcial). Os números de contas/retratos do painel (`adocao`, `alunos_com_dados`) não
  contam como uso.
- D58. Escolas em destaque = o critério da vitrine pública, escrito na tela (leitura: livros
  por aluno do Elefante, acumulados desde o início da conta; matemática: estrelas por aluno
  do Matific, no ano letivo; ativas; k mínimo; top 5 por plataforma), com o cartão da vitrine
  ("Reconhecimento público") logo abaixo: a Secretaria reconhece publicamente as escolas pelo
  Panorama. As metas da rede ficam no Panorama, recolhidas.
- D59. Ficha da escola `/rede/escolas/{id}` (por URL, não pelo contexto): cadastro, situação
  de uso, Elefante e Matific no período, evolução por bimestre SÓ da escola, avaliações
  externas da escola em modo simples (sem termo técnico; o porquê quando não há resultado) e
  "Ver as turmas". Comparação lado a lado de 2 a 4 escolas em Escolas (`?comparar=`). A tabela
  de todas as escolas nas avaliações mora em Avaliações externas. Nas duas, uma edição só por
  avaliação e série (a mais recente com resultado entre as escolas mostradas): a escola cujo
  último resultado é de edição anterior aparece com o ano dele, sem o número (que fica na ficha).
