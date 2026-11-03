# Revisão da navegação e da inteligência pedagógica — 01–02/11/2026

Branch `feat/navegacao-inteligencia` (worktree `C:\Users\Administrator\worktrees\navegacao-inteligencia`),
criada da V2 validada `a518ff4` (`prontidao/demo-jacarei`). Commit local, **sem push, sem deploy, sem
migração**. A identidade visual V2 (cores, Poppins, componentes de `ui.tsx`, ícones, espaçamentos,
responsividade) foi mantida: mudou a hierarquia e entrou inteligência, não o desenho.

## 0. Estado de partida (conferido)

| Item | Estado |
|---|---|
| V2 validada | `a518ff4` no worktree `worktrees\visual-v2` (ramo `prontidao/demo-jacarei`) — intocado |
| Menus antes da V2 | `a508768` (candidato) e `34f1a23` (produção) — lidos por `git show` |
| Produção | `34f1a23` (bundle `index-Izxi0Y4l.js`, conferido por GET público; API responde 401 sem login) — **sem a V2** |
| Demo de Jacareí | `C:\Users\Administrator\demo-jacarei` (porta 8040) — intocada e no ar durante todo o trabalho |
| Linha de base no worktree novo | tsc 0 · vitest 122 arquivos / 1336 testes · pytest 6117 / 508 pulados / 0 falhas (validação da V2) |

## 1. Diagnóstico da arquitetura anterior e atual

A V2 (`4c76c53`/`a518ff4`) manteve as MESMAS rotas de cada perfil, mas trocou os grupos por perfil
(pré-V2) por duas seções fixas — "Projeto" e "Gestão" — com itens "soltos" sem rótulo de grupo.
Nenhuma decisão registrada (D1–D37) pediu o reagrupamento; o resultado foi:

| Perfil | Menu na V2 (`a518ff4`) | Problema | Organização nova | Funcionalidades | Permissões |
|---|---|---|---|---|---|
| **Coordenação** | PROJETO: Visão geral · soltos Ranking Geral, Premiações, **Turmas, Alunos** · ▸Minha Escola (Visão da Escola, Professores) · ▸Inteligência · ▸Gamificação · ▸Relatórios. GESTÃO: soltos Critérios, Integrações, Revisões, **Usuários** · ▸Plataformas | Turmas e Alunos fora de "Minha Escola" (sob a chave "desempenho"); pessoas em 3 lugares (Alunos, Professores, Usuários); plataformas pedagógicas em "Gestão"; rótulos de grupo invisíveis | ESCOLA: Visão geral · ▸**Minha Escola** (aberta): Visão da Escola, Turmas, Alunos, Professores, Relatórios · ▸Acompanhamento: Elefante Letrado, Catálogo de Livros, Matific, Insights, Comparador, Assistente · ▸Reconhecimento: Ranking Geral, Premiações, Conquistas, Biblioteca de Conquistas, Painel Público. GESTÃO: ▸Dados e integrações: Integrações, Revisões de identidade · ▸Regras de pontuação: Critérios, Simulador, Editar conquistas · Usuários | as mesmas 23 rotas | nenhuma guarda nem regra do backend mudou |
| **Administração da escola** | igual à coordenação + Configurações Gerais | idem | igual, sem "Editar conquistas"; ▸Configurações: Usuários, Configurações Gerais | as mesmas rotas | idem |
| **Professora** | PROJETO: Visão geral · 6 itens soltos (Ranking, Premiações, Meus Alunos, Insights, Biblioteca, Meus Relatórios) | os 4 grupos de antes (Minhas Turmas, Desempenho, Reconhecimento, Relatórios) viraram lista sem contexto | MINHAS TURMAS: Visão geral, Meus Alunos, Insights, Meus Relatórios · RECONHECIMENTO: Ranking, Premiações, Biblioteca de Conquistas | as mesmas 7 rotas | idem (Turmas, Elefante, Matific seguem fora: guardas RotaGestao/RotaEscolaOp) |
| **Secretaria** | PROJETO: Panorama da Rede, Painel da Rede, Análise educacional, Fontes dos indicadores (4 soltos) | "Projeto" não descreve a função dela; Ranking da Rede fora do menu; a análise (4 abas) dispersa e sem perguntas | REDE MUNICIPAL: Panorama da Rede, Painel da Rede, Ranking da Rede · INTELIGÊNCIA PEDAGÓGICA: Visão geral, Avaliações externas, Elefante e Matific, Relação com plataformas, Diagnóstico pedagógico, Por escola · RELATÓRIOS E FONTES: Relatórios e exportações, Fontes dos indicadores | + Ranking da Rede e as abas da análise como itens | nenhuma tela de escola entra (Turmas, Professores, Alunos…: o backend já protege) |
| **Admin Global** | PROJETO: Visão Global, Painel da Rede · soltos Ranking Geral, Ranking da Rede, Premiações · ▸Gestão Escolar · ▸Inteligência · ▸Gamificação · ▸Avaliações · ▸Relatórios. GESTÃO: soltos Critérios, Importações, Configurações Gerais · ▸Estrutura · ▸Plataformas · ▸Monitoramento (1 item) | tudo de rede em 4 lugares; grupo "Gestão Escolar" na seção Projeto × seção "Gestão"; 3 "importar" em 3 lugares; acordeão de 1 item | ADMINISTRAÇÃO: Visão Global · ▸**Redes e municípios** (aberto): Painel da Rede, Ranking da Rede, Análise educacional, Importações e fontes, Gerenciar Rede · Escolas · Usuários · ▸Integrações e dados: Integrações, Importações, Revisões de identidade, Diagnóstico Elefante · ▸Configurações: Critérios, Simulador, Configurações Gerais · Sessões Ativas. ESCOLA SELECIONADA: ▸Gestão escolar · ▸Acompanhamento · ▸Reconhecimento | as mesmas 32 rotas | idem |

Problemas transversais da V2 também corrigidos: acordeão de 1 item; ícones repetidos na barra
recolhida; barra recolhida ignorava o "primeiro acesso"; trilha sem o nível do grupo; o 1º Tab de
qualquer página com item ativo pulava o "Pular para o conteúdo" (WCAG 2.4.1); textos do Suporte e de
telas que citavam caminhos de menu antigos ("Projeto › Alunos", "no topo"…); nenhum teste travava a
estrutura por perfil nem o filtro de módulos.

## 2. Decisões de navegação (registradas como D38–D48 em `docs/design/IDENTIDADE-VISUAL-V2.md`)

- **Seção › [grupo ▸] › item, com seções de cada perfil** (no lugar de "Projeto/Gestão" para todos).
  O rótulo diz o que a pessoa faz ali.
- **Acordeão por tarefa só onde há muitos itens** (escola e global). Secretaria e professora: tudo à
  vista. O grupo do dia a dia nasce aberto (Minha Escola; Redes e municípios); o da página atual abre
  sozinho; a escolha fica guardada (`constela_menu_abertos_v3`). Grupo com um item vira item solto.
- **Um item marcado por vez**, por uma regra única que entende as abas da análise (`?ver=`); dentro
  da análise, o item de aba leva os filtros (série, escola, rede).
- **Trilha em três níveis**: Início › grupo (ou seção) › página.
- **Rótulos existentes não mudam** (casam com h1, trilha e testes); os novos são curtos o bastante
  para não serem cortados. "Certificados" não virou item próprio (estão em Premiações e Relatórios;
  a pesquisa acha por "certificados").
- **O que estava fora do menu continua fora** (Importações e Diagnóstico Elefante para a escola,
  decisão de setembro; telas de escola para a Secretaria).
- **Nenhuma guarda de rota nem regra de permissão mudou.** Cada item de cada perfil é conferido contra
  a guarda (`podeAbrirRota`) em teste; o backend continua sendo a trava.

## 3. Inteligência pedagógica da Secretaria (`/rede/analise`)

Organizada em torno das perguntas do dono, da visão geral ao detalhe (7 abas, também itens do menu):

| Aba | Pergunta | O que mostra |
|---|---|---|
| Visão geral | Como está a rede? | (1) avaliações externas (destaques oficiais) · (2) plataformas no período · (3) **quais escolas merecem acompanhamento** (do diagnóstico, por nível) · (4) **o que dá para relacionar hoje** (e por quê não) · alertas e metodologia. Cada bloco com "Ver em detalhe →" |
| Avaliações externas | Como a rede performa nas avaliações? | **comparação entre escolas** (última edição oficial de IEE, Ideb, SARESP 2º/5º LP/MT, Saeb 5º LP/MT: valor, edição, posição contra a rede municipal, meta oficial, tendência) · **escolas com sinais de atenção nas avaliações** · a série histórica e "escolas numa edição" de antes, inteiras |
| Elefante e Matific | O que as plataformas mostram? | indicadores da rede no período + cobertura · **evolução no ano letivo por bimestre** · **escolas no período** (participação, livros/aluno, minutos/aluno, acerto; participação, atividades/aluno, desempenho; cobertura) |
| Relação com plataformas | Há associação? | a de antes: Spearman só quando todos os critérios valem; lado a lado sempre |
| Diagnóstico pedagógico | Onde olhar primeiro? | **hipótese exploratória**: por escola, Leitura (LP × Elefante) e Matemática (MT × Matific) — estado da avaliação e do uso, categoria (convergente favorável / atenção nas duas / divergente: uso acima e avaliação em atenção / avaliação favorável e uso abaixo / inconclusiva), nível de acompanhamento e TODOS os sinais com natureza e referência; CSV |
| Por escola | Uma escola em detalhe | a de antes |
| Relatórios e exportações | Levar os números | boletim da rede (PDF), diagnóstico (CSV), avaliações por escola (CSV), plataformas por escola no período (CSV), ranking da rede (CSV na tela dele) e fontes/histórico dos indicadores |

Backend novo, **só leitura**, `exigir_rede`: `GET /redes/{id}/analise/diagnostico` e
`GET /redes/{id}/analise/plataformas/evolucao`. Combinam as consultas que já existiam (não releem
tabelas oficiais nem recalculam plataformas); a supressão de células pequenas (k = 5) é a mesma.
Regras completas: `docs/analise/METODOLOGIA.md` §7–§8.

### 3.1 Indicadores usados e fontes

| Indicador | Fonte | Natureza na tela | Granularidade |
|---|---|---|---|
| ICA | INEP | Oficial | só a rede (2º ano, LP), com meta |
| SARESP | SEDUC-SP | Oficial | rede e escola; 2º e 5º ano, LP e MT; sem meta |
| IEE | SEDUC-SP | Oficial | só a escola; meta e ICM oficiais |
| Ideb | INEP | Oficial | rede e escola (anos iniciais); metas só até 2021 |
| Saeb | INEP | Oficial | rede (planilha) e escola (arquivo do Ideb); 5º ano LP e MT |
| Estimativa Constela / número sem registro | Constela / 1 clique antigo | rotulados à parte | nunca entram em destaques, relação ou diagnóstico |
| Elefante Letrado | coletas da plataforma | Plataforma | escola × série no período: participação, livros novos/aluno, minutos/aluno (piso), nível médio, acerto |
| Matific | coletas da plataforma | Plataforma | escola × série no período: participação, atividades/aluno, estrelas/aluno, desempenho 0–5 |
| Posição contra a rede, tendência, leituras e níveis | regras do Constela sobre os números acima | Calculado pelo Constela / Hipótese exploratória | escola |

### 3.2 Relações: o que dá e o que não dá

- **Calculável (relação estatística)**: indicador oficial por escola × métrica da plataforma do
  componente certo (LP ↔ Elefante; MT ↔ Matific; IEE/Ideb ↔ escola inteira), mesma série, **mesmo ano
  letivo** (período dentro do ano da edição e todas as escolas nele), só números oficiais, n ≥ 8
  escolas, variância nos dois lados.
- **Não calculável hoje, nos dados reais**: as plataformas são de 2026 e as avaliações por escola vão
  até 2025 — a primeira janela realista é o SARESP 2026, e com pelo menos 8 escolas com plataforma.
  A tela diz isso e mostra os números **lado a lado**.
- **Nunca**: ICA por escola (não existe), SARESP LP × Matific, estimativas, causalidade.
- O **diagnóstico** não é relação estatística: é leitura descritiva com regras escritas, rotulada
  "Hipótese exploratória", com a comparabilidade de cada leitura (mesmo ano × exploratória) e sem
  gráfico de dispersão.

### 3.3 Limitações que a interface mostra

Correlação não é causalidade · anos e coortes diferentes · oficial × estimativa × sem registro ·
ausência ≠ zero · escalas não comparáveis entre SARESP, Saeb e ICA · outras redes só como contexto ·
Saeb do 2º ano amostral · metas do Ideb só até 2021 · quebras de escala do SARESP 2º ano · TPS = 0 deixa
a média instável · níveis do SARESP não confirmados · supressão k = 5 · coleta parcial e data até onde
vale · contador do Elefante vitalício (questões por diferença entre coletas) · tempo de leitura é piso
· bimestres de tamanhos diferentes (livros/atividades crescem com os dias) · posição contra a rede só
com ≥ 3 escolas comparáveis e com a coleta em dia.

## 4. Arquivos

**Novos**
- Backend: `backend/app/services/analise/diagnostico.py`, `backend/app/services/analise/evolucao.py`,
  `backend/tests/test_analise_diagnostico.py`, `backend/tests/test_analise_evolucao.py`.
- Web: `apps/web/src/pages/analise/{AvaliacoesExternas,PlataformasRede,EvolucaoPlataformas,Diagnostico,RelatoriosRede}.tsx`,
  `tiposDiagnostico.ts`; testes `NavegacaoPerfis`, `AnaliseAbas`, `AnaliseVisaoGeral`,
  `AnaliseAvaliacoes`, `AnalisePlataformas`, `AnaliseDiagnostico`, `AnaliseRelatorios`,
  `AnaliseLeiturasPesadas` (+ `AnaliseFixturesDiagnostico.ts`); E2E
  `e2e-analise/navegacao.spec.ts` e a ferramenta de capturas `e2e-analise/capturas-navegacao.spec.ts`
  (só com `CAPTURAS_NAV=1`).
- Docs: este arquivo.

**Alterados**
- Navegação: `components/Layout.tsx`, `hooks/useModulos.ts`, `pages/suporteConteudo.ts`,
  `pages/Suporte.tsx`, `pages/Dashboard.tsx`, `pages/Alunos.tsx`, `pages/Comecar.tsx` (textos),
  `pages/rede/RedeDashboard.tsx` (link para o diagnóstico; textos), `pages/configuracoes/ConfigConquistas.tsx`
  (link de volta), `App.tsx` (só comentário).
- Correções da V2 achadas nos testes: `pages/rede/CartaoICA.tsx` (tabela rola dentro do cartão no
  celular), `components/ui.tsx` (vigia de foco do Modal sem documento).
- Análise: `pages/analise/{AnaliseEducacional,VisaoGeral,comum,formato,PorIndicador}.tsx|ts`,
  `backend/app/routers/analise.py` (2 rotas novas; as antigas intactas).
- Testes ajustados à estrutura nova (nenhuma asserção de permissão enfraquecida): `Layout`,
  `AnaliseMenuPerfis`, `AnaliseEducacional`, `IndicadoresPerfis`, `CoordenadorConfiguracoes`,
  `ConfigConquistas`, `Suporte`, `RedeAdminVisualV2`, `test_analise_permissoes.py` (5 → 7 rotas de
  análise, todas GET), `e2e/demo-fluxos.spec.ts` (abre o grupo antes do link), `e2e-analise/analise.spec.ts`
  (7 abas, trilha, teclado).
- Docs: `docs/analise/METODOLOGIA.md` (§7 diagnóstico, §8 evolução), `docs/design/IDENTIDADE-VISUAL-V2.md` (D38–D48).

## 5. Testes (números reais, árvore final)

Todos rodados na árvore do commit (o E2E de novo depois das últimas correções):

| Suíte | Resultado | Linha de base (`a518ff4`) |
|---|---|---|
| TypeScript (`tsc --noEmit`) | 0 erros | 0 |
| Vitest (web) | **130 arquivos, 1501 testes, 0 falhas** — duas rodadas seguidas limpas | 122 / 1336 |
| Build de produção (`vite build`) | ok | ok |
| Pytest completo (SQLite) | **6149 passaram, 508 pulados, 0 falhas** (41 min) | 6117 / 508 / 0 |
| Pytest PostgreSQL (`-m postgres`, cluster descartável com senha) | **505 passaram, 0 falhas** | 505 / 0 |
| E2E principal (Playwright, CI=true, sem nova tentativa) | **42 / 42** | 42 / 42 |
| E2E da análise + navegação (`playwright.analise.config.ts`) | **26 passaram, 0 falhas** (4 pulados = a ferramenta de capturas, só com `CAPTURAS_NAV=1`) | o teste de teclado da Secretaria já falhava (procurava um botão que a V2 removeu) |
| Varredura visual da V2 (5 perfis × 10 larguras) | **5 / 5**; 760 registros; rolagem lateral 0; contraste: os mesmos 10 da V2 (rótulo desabilitado, isento) | 760; 0; 10 |

O E2E de navegação (`e2e-analise/navegacao.spec.ts`, 14 testes) clica em CADA item do menu dos quatro
perfis, no desktop e na gaveta do celular, e confere a página, o item marcado (um só), o título, a
ausência de 5xx/exceção e de rolagem lateral; confere que a URL direta de tela de outro perfil cai
no início; que o menu rola sozinho até o item ativo numa tela baixa sem roubar o 1º Tab; e que as
rotas novas dão 403 à coordenação e à professora e 200 à Secretaria, sem nome de criança nem
`aluno_id`. As correções da revisão foram conferidas por mutação (o teste falha sem a correção).

## 6. Revisão adversarial

Cinco lentes independentes (permissões e dado pessoal; metodologia; navegação; telas novas;
regressão), cada achado verificado por um cético que tentava refutá-lo: 20 achados, **15 confirmados
e corrigidos com teste** (a maioria conferida por mutação), 5 refutados. A lente de permissões e dado
pessoal não achou nada. Depois disso, os testes acharam três defeitos que já vinham da V2, todos
corrigidos e travados em teste:
- o 1º Tab de qualquer página com item ativo no menu pulava o "Pular para o conteúdo" (o menu rolava
  até o item com `scrollIntoView`, que no Chromium move o ponto de partida do teclado);
- na página "Fontes dos indicadores", a tabela do ICA (município × estado × Brasil) passava 12 px da
  tela em 375 px (a varredura da V2 não tinha ICA nos dados de teste);
- o vigia de foco da janela modal (`ui.tsx`) disparava depois de o teste terminar e derrubava, às vezes,
  a suíte inteira do vitest com "document is not defined".

## 7. Evidências visuais

Capturas ANTES (`a518ff4`) e DEPOIS, com os mesmos dados inventados (seed do E2E da análise), dos 4
perfis — menu aberto no desktop e na gaveta do celular, e as telas principais — geradas por
`e2e-analise/capturas-navegacao.spec.ts`, fora do repositório (pasta de rascunho da sessão).

## 8. Pendências reais

1. **Desempenho com dados reais não medido**: a evolução por bimestre chama a medição de plataformas
   até 4 vezes (com dados reais, `/plataformas` já levou ~12 s). A tela espera até 60 s e guarda a
   resposta por 60 s; medir antes de publicar e, se preciso, cachear/otimizar no backend.
2. **Relação estatística ainda não calculável nos dados reais** (anos diferentes) — estrutural; a tela
   explica e mostra lado a lado.
3. **Data da coleta parcial na evolução por escola**: a marca "coleta parcial" aparece, mas sem a data
   (o backend ainda não repassa `coberto_ate` por bimestre).
4. **Pesquisa global e atalhos** abrem as abas da análise sem levar os filtros (o menu leva).
5. **Guias em PDF** (`docs/guias`, fora do repositório versionado) citam caminhos de menu antigos —
   revisar antes de distribuir.
6. Até 60 s depois de importar resultados oficiais, o diagnóstico pode mostrar a resposta guardada.
7. **Publicação**: esta branch está sobre a V2, que ainda não está em produção (produção = `34f1a23`).
   Nada foi publicado; publicar depende das autorizações pendentes da V2.
8. O E2E da análise (onde ficam os testes de navegação por perfil) não roda no CI — só o E2E principal
   roda (situação anterior).
9. Decisões de produto que ficam com o dono: telas Elefante/Matific para a professora (hoje são telas de
   gestão); item próprio de "Certificados"; Professores (com e-mails da equipe) fora do menu da
   Secretaria, como antes.
