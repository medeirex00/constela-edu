# Rodada 2 — Secretaria simplificada, Minha Escola e Vitrine Pública — 02/11/2026

Branch `feat/navegacao-inteligencia`, a partir de `3860f10` (rodada 1, ver
`REVISAO-NAVEGACAO-E-INTELIGENCIA.md`). Tudo LOCAL: sem push, sem deploy, sem migração, sem dado real.
A demo de Jacareí (`C:\Users\Administrator\demo-jacarei`, porta 8040) e a `visual-v2` não foram tocadas.
Decisões de desenho desta rodada: D49–D54 em `docs/design/IDENTIDADE-VISUAL-V2.md` (D46–D48 são da rodada 1).

Regra que guiou a rodada: **compreensão acima da quantidade de informação**. O que era útil mudou de lugar para o
ponto em que responde a uma pergunta. A seção 1.4 diz onde ficou cada coisa e registra o que saiu de propósito.

## 1. Inteligência Pedagógica da Secretaria

### 1.1 Menu da Secretaria: do resumo ao detalhe

```
REDE MUNICIPAL       Panorama da Rede (/) · Escolas em acompanhamento · Comparar escolas
RESULTADOS           Avaliações externas · Elefante e Matific (o nome segue os módulos contratados)
RELATÓRIOS E GESTÃO  Relatórios e exportações · Ranking da Rede · Painel da Rede (metas e vitrine)
APROFUNDAR           ▸ Análises avançadas (acordeão FECHADO por padrão):
                       Diagnóstico exploratório · Relação com as plataformas ·
                       Análise detalhada por escola · Fontes e arquivos oficiais
```

Na rodada 1, a Secretaria tinha a seção "Inteligência pedagógica", com 6 abas no mesmo nível: visão geral,
avaliações, plataformas, relação, diagnóstico e por escola. Isso misturava conclusão, dado oficial e análise
exploratória.

Agora:
- o fluxo principal tem **6 telas novas** de leitura simples;
- o que é técnico ou exploratório fica nas Análises avançadas, uma área secundária identificada;
- a aba padrão dessa área (`/rede/analise`) abre com a faixa "Área técnica: análises exploratórias e estatísticas…
  Não são conclusões sobre as escolas."

### 1.2 As telas novas (`apps/web/src/pages/rede/secretaria/`)

As quatro telas de indicadores seguem o mesmo padrão: Panorama da Rede, Comparar escolas, Avaliações externas e
Elefante e Matific.
- A conclusão vem primeiro, numa frase.
- Depois vem "O que mede", com o texto único de `oQueMede.ts`.
- Cada número traz o selo de natureza: **Oficial**, **Plataforma**, **Calculado pelo Constela** ou **Exploratório**.
- A data do dado aparece junto.
- O detalhe fica por último, recolhido.

As outras duas seguem um padrão próprio:
- **Escolas em acompanhamento** tem conclusão, selo em cada sinal e recolhidos. No lugar de "O que mede", traz a
  caixa "Como ler".
- **Relatórios e exportações** é uma lista de arquivos. Cada item diz o que contém e de quando são os números.

| Tela | Rota | O que responde |
|---|---|---|
| **Panorama da Rede** | `/` (Secretaria), `/rede/visao` (Admin Global, com seletor de rede) | Três cartões-conclusão: avaliações externas (destaques oficiais com meta), Elefante e Matific no ano letivo (participação e uma métrica de cada) e escolas em acompanhamento (quantas e quais). Número escondido para proteger as crianças aparece como "protegido (poucos alunos)", não como "sem dado". Atalhos "Para fazer agora". Sem tabela nem ranking. |
| **Escolas em acompanhamento** | `/rede/acompanhamento` | Escolas com sinal de ATENÇÃO, em ordem alfabética, cada uma com dois blocos separados: "Nas avaliações externas" e "No Elefante e no Matific (ano letivo)". No bloco das plataformas, cada sinal tem dois selos: **Plataforma** (o número vem dela) e **Calculado pelo Constela** (o "abaixo da rede" usa a tolerância do Constela). "Ver a escola" abre a Visão da Escola com o **Voltar** para esta lista. Escolas sem sinal e dados incompletos ficam recolhidos. CSV dos sinais. Sem níveis nem categorias exploratórias. |
| **Comparar escolas** | `/rede/escolas` | Duas abas: "Avaliações externas" (a tabela de comparação entre escolas) e "Elefante e Matific" (escolas no período, com seletor de período). Legenda "O que significa cada coluna", que acompanha a série escolhida. Ausência escrita por extenso, nunca 0. A escola sem aluno na série escolhida aparece como "a escola não tem aluno ativo nesta série no ano letivo". |
| **Avaliações externas** | `/rede/avaliacoes-externas` | Um cartão por indicador (ICA, SARESP, IEE, Ideb, Saeb), com: o que mede; quem publica; frequência; edição mais recente; resultado da rede e meta. Quando a edição mais recente não tem número da rede, a frase diz isso (ex.: "Rede em 2021: 210,00. Na edição de 2023, não há resultado oficial da rede."). "Ver série histórica e escolas" abre o detalhe completo. A Estimativa Constela e o "sem registro oficial" ficam fora dos cartões. |
| **Elefante e Matific** | `/rede/plataformas` | Uso no período (padrão: ano letivo), com o "O que mede" de cada métrica. Evolução por bimestre. Totais acumulados, cada um com o seu período: no Elefante, "desde o início da conta"; no Matific, "no ano letivo". "Sobre os dados" fica recolhido. |
| **Relatórios e exportações** | `/rede/relatorios` | Dois grupos: "Documento para reuniões" (Boletim da rede em PDF) e "Planilhas (CSV)" (avaliações por escola, plataformas por escola no período, escolas em acompanhamento e Ranking da Rede). Cada item diz o que contém e de quando são os números, com o período real de cada parte. Por exemplo, para o Boletim: "alunos do ano letivo corrente; livros do Elefante acumulados desde o início da conta de cada aluno; Matific no ano letivo". |

Onde avaliações externas e plataformas aparecem juntas, a mesma frase se repete: "As avaliações oficiais são de
outras edições (até 2025) e as plataformas, do ano letivo de 2026: são medidas e períodos diferentes — não se
comparam diretamente". Nenhuma tela do fluxo principal põe 2026 (plataformas) ao lado de 2025 (avaliações) como se
fosse a mesma medição.

### 1.3 Linguagem e honestidade dos números

Os textos técnicos que o servidor manda passam por `textoSimples`/`textosDoFluxoPrincipal` antes de entrar no fluxo
principal. O E2E confere o texto de `main` nas seis telas novas e falha se encontrar:
- termos técnicos: Spearman, correlação, coorte, TPS, IC 95, proveniência;
- palavras causais: causa, efeito, impacto, graças.

Em Avaliações externas, Elefante e Matific, Comparar escolas, Escolas em acompanhamento e Relatórios, a conferência
roda com os recolhidos abertos.

Depois da revisão independente (seção 5), também foram corrigidos:

**Períodos reais nos rótulos.** O índice e a pontuação do Constela usam, na leitura, os livros do Elefante
**acumulados desde o início da conta** de cada aluno; só o Matific é cortado no ano letivo. Os rótulos que diziam
"ano letivo" passaram a dizer o período real, só dos módulos contratados, nestes lugares:
- Ranking da Rede: o cabeçalho, a "Diferença entre escolas" e as dicas de "Livros lidos" e "Livros/aluno";
- Painel da Rede: o atalho do Ranking, a regra dos alertas, a legenda do mapa e a visão de uma escola;
- Relatórios;
- Boletim em PDF.

**Ranking da Rede.**
- Na aba Engajamento, a coluna "Participação" era adoção (qualquer dado ÷ todos os alunos). Ela virou **"Adoção
  (alguma plataforma)"**, e a aba explica que não é a "Participação" de Comparar escolas.
- O modal "Como funciona" mostra R (percentil 90) e k (mediana) sempre, também na rede só com Matific.
- A coluna "Nível" diz o critério (Alta a partir de 80%, Média de 40% a 79,9%, Baixa abaixo de 40%).

**Painel da Rede.**
- O "Progresso das metas" respeita o campo `medida` do backend. Meta sem dado aparece como "sem dado medido",
  sem "0,0 /", barra ou "0,0%", e sai da conta "X de Y metas atingidas".
- O cartão de alertas vazio não diz mais, em verde, "nenhuma escola sinalizada para acompanhamento". Esse texto
  contradizia a tela de mesmo nome, que usa outra regra.
- O mapa ganhou legenda (o que a cor mede, faixas e selo). O vermelho começa no mesmo corte do alerta, índice
  abaixo de 300.
- O motivo do alerta passou de "Desempenho baixo…" para "Índice do Constela baixo frente à rede…".

**Boletim em PDF.** O documento para reuniões deixou de chamar uso das plataformas de "desempenho":
- "média geral" virou "média das notas do Constela (0–100)";
- "melhor/pior escola" virou "maior/menor índice";
- entraram o aviso "não é avaliação oficial de aprendizagem", a natureza de cada número e o período no subtítulo.

**Textos que saíram do fluxo principal.**
- "a aba de plataformas" foi trocado pelo nome da tela.
- "…e nunca na relação com as avaliações" saiu do texto da cobertura.
- No aviso oficial do Ideb 2021, "impacto" virou "nota própria sobre o modo de ler o Ideb e o Saeb dessa edição".

### 1.4 Onde ficou o que já existia

| Antes | Agora |
|---|---|
| `/` da Secretaria: o Panorama antigo (`PainelRede` modo "análise") | Panorama da Rede (`PanoramaSecretaria`); o Panorama antigo continua só para o Admin Global |
| Panorama antigo: KPIs e faixa (alunos e turmas, escolas, professores, adoção, livros, tempo, atividades e estrelas, média geral 0–100) | Elefante e Matific › Totais acumulados: cadastro à parte; Elefante desde o início da conta, Matific no ano letivo |
| Panorama antigo: melhor escola, Top 5 com critério, tops das seções Leitura e Matemática, Comparativo | Ranking da Rede |
| Panorama antigo: "Escolas que precisam de atenção" | Painel da Rede › "Escolas com alerta de uso das plataformas" |
| Panorama antigo: Equidade do índice | Ranking da Rede › "Diferença entre escolas — calculado pelo Constela" |
| Progresso das metas | Painel da Rede, no topo |
| "Livros por aluno" ACUMULADO da rede (`totais.livros_por_aluno`) | **Saiu de propósito.** Fica só o "Livros novos por aluno" do período (Panorama e Elefante e Matific), porque os dois números tinham contas diferentes com o mesmo nome |
| Lista "Ranking das escolas" do Painel da Rede, com "Filtrar escola" (filtrava também o mapa e abria qualquer escola) | Cartão "Comparar as escolas", com links para Comparar escolas e Ranking da Rede. **A busca e o filtro do mapa saíram.** A escola se abre pelo mapa (as que têm coordenadas), pelos alertas de uso, pelo Ranking da Rede (as que estão na ordem) ou pelo seletor do menu lateral |
| Inteligência › Visão geral (rodada 1, `VisaoGeral.tsx`, removida) | Panorama da Rede (`/`) |
| `?ver=avaliacoes` e `?ver=indicador` | Avaliações externas, com os mesmos parâmetros do indicador (redirecionamento `replace`) |
| `?ver=plataformas` | Elefante e Matific (`escola` e `serie` vão junto) |
| `?ver=relatorios` | Relatórios e exportações (a `serie` vai junto) |
| `?ver=visao` | `/` (Secretaria) ou `/rede/visao` (Admin Global) |
| Diagnóstico pedagógico (níveis e categorias) | Análises avançadas › Diagnóstico exploratório (aba padrão), com o CSV dele |
| Relação com plataformas e Por escola | Análises avançadas (mesmas proteções) |
| Fontes dos indicadores | Análises avançadas › Fontes e arquivos oficiais |

## 2. Relatórios e Fontes

- "Relatórios e fontes" deixou de ser uma seção que misturava exportação com arquivo oficial.
- **Relatórios e exportações** ficou com o que se leva para uma reunião ou planilha, em dois grupos.
- **Fontes e arquivos oficiais** (importações, arquivos e notas dos órgãos) foi para Análises avançadas. O Admin
  Global continua com "Importações e fontes" em Redes e municípios.
- O CSV do Diagnóstico exploratório saiu do fluxo principal e fica na própria aba avançada.
- No rodapé dos Relatórios há dois links para a área avançada: "fontes e arquivos oficiais" (`/rede/avaliacoes`; no
  Admin Global, "importações e fontes") e "A planilha do diagnóstico exploratório fica nas Análises avançadas".
- O CSV dos sinais traz as duas naturezas no eixo das plataformas ("Plataforma + Calculado pelo Constela"), como a tela.

## 3. Coordenação — Minha Escola

```
ESCOLA   Visão geral (/)
         ▸ Minha Escola (aberta): Visão da Escola · Turmas · Alunos · Professores · Usuários · Relatórios
         ▸ Acompanhamento · ▸ Reconhecimento
GESTÃO   ▸ Dados e integrações · ▸ Regras de pontuação · Configurações Gerais (solto, só administração da escola)
```

"Usuários" saiu de Gestão › Configurações e entrou em Minha Escola. É o **mesmo item**: rota `/usuarios`, guarda
`RotaSemSecretaria` e backend sem nenhuma mudança. O FAQ do Suporte acompanha ("Minha Escola › Usuários").

Testes:
- **Coordenação:** o E2E `navegacao.spec.ts` confere, no desktop e na gaveta do celular, que Minha Escola tem
  exatamente Visão da Escola, Turmas, Alunos, Professores, Usuários e Relatórios, e que "Usuários" não aparece em
  outro lugar. Ele também abre cada item do menu.
- **Administração da escola:** a árvore é travada pelo Vitest (`NavegacaoPerfis.test.tsx`). Os bancos de E2E não
  têm conta de admin de escola.

## 4. Vitrine Pública: causa e correção

**Sintoma:** em ambiente local (demo e ambiente de teste), "Abrir" e "Copiar" do Painel Público da escola e da
vitrine da rede, e o QR do Painel Público, levavam a um endereço que não abria a tela. A vitrine da rede não tem QR.

**Causa real.** O backend monta o link com `settings.PUBLIC_BASE_URL`, cujo padrão é `https://www.constelaedu.com`.
Os ambientes locais não definem essa variável, então o link apontava para a **produção**, onde o token local não
existe. A rota respondia (HTTP 200), mas a tela pública não achava o painel.

Somaram-se três causas secundárias:
1. o cartão da vitrine da rede não tinha botão "Abrir";
2. numa tela pública (`/p/…`, `/rede/p/…`), um token de sessão **vencido** guardado no navegador fazia
   `/auth/me` dar 401 e mandava para `/login`;
3. sem escola escolhida (a Secretaria, que opera a rede), `/painel-publico` ficava em "Carregando..." para sempre.

**Correção: quem decide a base do link é o servidor** (`routers/publico.base_do_link_publico`).

O servidor escolhe a base nesta ordem:
1. Se `PUBLIC_BASE_URL` foi **configurado** (no ambiente ou no `.env`), ele vale sempre, como antes desta rodada.
2. Senão, vale a origem da tela, desde que a tela informe uma origem de loopback.
   - Aceita só http(s) em `localhost`, `*.localhost` ou IP de loopback.
   - Recusa `tauri.localhost` (o app de desktop) e qualquer origem com caminho, consulta, credencial (mesmo vazia),
     barra invertida ou porta inválida.
   - A base é remontada a partir do host e da porta validados, nunca copiada da origem. Assim nenhuma origem
     estranha põe um domínio de fora no link.
3. Senão, o domínio publicado.

Como cada parte aplica isso:
- Os endpoints que devolvem o link aceitam o mesmo `?origem=`: GET, PUT e novo endereço do Painel Público, o QR,
  e GET e PUT da vitrine da rede.
- A tela (`lib/linkPublico.ts`) só **informa** a própria origem, e só em loopback (`comOrigemLocal`). Ela mostra,
  copia e abre o link que o servidor devolveu, sem reescrever.
- Quando o link é `localhost`, a tela avisa: o link só abre no computador onde o Constela está instalado. Para o
  telão, o celular ou o QR em outro aparelho, o servidor precisa ter o endereço dele na rede (`PUBLIC_BASE_URL`).
- Botão **Abrir vitrine** no Painel da Rede.
- Tela pública não abre sessão nem redireciona para `/login` (`AppContext.iniciarSessao` e `api.aoExpirarSessao`
  checam `ehTelaPublica`, que casa só `/p/…` e `/rede/p/…`).
- `/painel-publico`:
  - para a Secretaria, diz que "A vitrine da rede fica no Painel da Rede" e leva até ela, sem chamar a API que o
    backend recusa;
  - para uma conta sem nenhuma escola, diz "Nenhuma escola disponível".

**Limite.** Em loopback e sem `PUBLIC_BASE_URL`, o link e o QR levam `localhost`. Eles só abrem na própria máquina,
e a tela diz isso.

**Onde o comportamento muda e onde não muda:**
- Na produção, sem a variável e com a tela fora de loopback, o link continua sendo o domínio publicado.
- Em instalações com `PUBLIC_BASE_URL` definido (ex.: o `docker-compose`), o link é o mesmo de antes.
- Mudam só os ambientes locais sem a variável: demo, ambiente de teste e desenvolvimento.

**Ambiente de teste 8050** (fora do repositório): `PUBLIC_BASE_URL=http://localhost:8050` foi definido em
`C:\Users\Administrator\ambiente-navegacao\ferramentas\ambiente.py`. Esse arquivo não vai na branch.

**A demo de Jacareí (8040) tem a mesma causa e não foi alterada** (regra da tarefa). Quando houver autorização, há
duas saídas:
- recompilar a demo a partir deste commit (a tela passa a informar a própria origem, e Abrir e Copiar funcionam no
  próprio computador);
- definir `PUBLIC_BASE_URL` com o endereço da máquina na rede, para o telão e o celular abrirem e o QR funcionar.

**Permissões da Vitrine (inalteradas):**

| Perfil | Painel Público (escola) | Vitrine da rede | Rotas de configuração |
|---|---|---|---|
| Admin Global | configura e abre | configura e abre | abertas |
| Coordenação | configura e abre | — | rede: 403 |
| Secretaria | — | configura e abre | escola: 403 |
| Professora | — | — | nenhuma |

Qualquer pessoa abre os links públicos, logada ou não.

## 5. Testes e revisão (números reais, árvore final)

| Suíte | Resultado |
|---|---|
| Frontend (Vitest, `npx vitest run`) | 138 arquivos, **1725/1725** |
| `tsc --noEmit` | sem erro |
| Backend (pytest completo, SQLite) | **6201 passaram**, 0 falha; 508 pulados (os que pedem PostgreSQL ou outro ambiente; os de PostgreSQL rodam na linha abaixo) |
| Backend PostgreSQL (`pytest -m postgres`, cluster PG17 descartável e local) | **505/505** |
| E2E principal (`npx playwright test`) | **48/48** |
| E2E da análise, navegação e Vitrine (`playwright.analise.config.ts`, backend **sem** `PUBLIC_BASE_URL`, como a demo) | **37 passaram**, 0 falha; 4 pulados (as capturas, que só rodam com `CAPTURAS_NAV=1` e passaram 4/4 à parte) |
| Varredura visual (`playwright.visual.config.ts`: 84 telas (perfil × rota) × 10 larguras, do celular ao desktop grande; Secretaria com as 15 rotas dela, Admin Global com `/rede/visao`) | **840 registros**: 0 erro de console, 0 falha de API, 0 rolagem lateral, 0 tela sem título. Contraste igual à base V2 (os mesmos 10 avisos antigos, num rótulo de `/metricas` do admin) |
| Build (`vite build`) | sem erro nem aviso (PWA: 241 entradas no precache) |

**Vitrine nos 4 perfis** (`e2e-analise/vitrine.spec.ts`, backend e site reais):
- **Coordenação:** liga o painel e abre o telão pela tela.
- **Admin Global:** abre o painel da escola e a vitrine da rede.
- **Secretaria:** abre a vitrine pelo Painel da Rede, e o link copiado é o mesmo. Em `/painel-publico`, é levada à
  vitrine sem "Carregando...".
- **Professora:** não tem o item no menu e a rota é barrada. Ela abre os links públicos logada, sem login e com um
  token vencido guardado no navegador.
- Em todos os casos, o link abre na mesma origem da tela, com título, conteúdo e sem erro.

**Mutação executada:** com a tela sem informar a origem, o E2E da Vitrine **falha** ("o link aponta para a
produção"). Ou seja, ele prova a causa real. O teste do token vencido também falha sem a correção.

**Revisão independente:** depois da implementação, 4 revisores só de leitura e um verificador cético por achado.
- Foram 33 achados: 26 confirmados e 7 refutados.
- Os 26 foram tratados: 18 com mudança de código ou de teste, e 8 só neste relatório (afirmações inexatas ou
  incompletas).
- Cada pacote de correção passou por um segundo verificador.

Testes novos desta rodada:
- telas da Secretaria: `SecretariaPanorama/Acompanhamento/Comparar/Avaliacoes/Plataformas/Relatorios/Textos`;
- Vitrine:
  - `VitrineLinkLocal`: contrato do link, `?origem=` em todas as chamadas e no QR, aviso de link local;
  - `PainelPublicoConfig`: Secretaria e conta sem escola;
  - `PainelPublicoRede`: token vencido;
  - `test_painel_publico_link_local.py`: origens aceitas e recusadas, valor configurado vencendo a origem, e os
    endpoints da escola e da rede;
- Painel da Rede (`AnalisePainelRede`, `RedeAdminVisualV2`): metas sem medida, alerta vazio, legenda do mapa e
  "Voltar para a Visão Global";
- Ranking (`RankingRede`): período real, Adoção e modal com R e k na rede só com Matific;
- boletim (`test_rede.py`): sem "desempenho" e respeitando os módulos;
- `test_analise_plataformas.py`: escola sem a série escolhida;
- `AnaliseAbas`: redirecionamentos dos links antigos, com parâmetros;
- E2E:
  - `vitrine.spec.ts`;
  - `navegacao.spec.ts`: estrutura de Minha Escola e o "tela baixa" movido para o Simulador;
  - as telas novas em `analise.spec.ts` (com a régua de linguagem também em Relatórios), `zz-rede-secretaria.spec.ts`
    e `identidade-v2.spec.ts`.

**Permissões:** nenhuma ampliada.
- As 6 rotas novas usam a guarda `RotaRede`, a mesma de `/rede/analise`, e só chamam endpoints que já existiam
  (todos com `exigir_rede`).
- "Usuários" mudou só de lugar no menu.
- No backend, as dependências de autorização não mudaram: `escola_autorizada`, `exigir_papeis`, `negar_secretaria`
  e `exigir_rede`.
- As mudanças de backend são de três tipos:
  - a base do link público;
  - um motivo novo de "sem dado", para a escola sem a série escolhida;
  - textos.
- O E2E confirma que professora e coordenação são redirecionadas das 7 rotas de rede e recebem 403 nas APIs da
  análise.

## 6. Pendências

- **Demo de Jacareí (8040):** tem a mesma causa da Vitrine (seção 4). Mudar precisa de autorização.
- **Decisão de produto, sem mudança nesta rodada:**
  - A leitura do índice e do ranking soma os livros do Elefante desde o início da conta. Agora os rótulos dizem
    isso, mas recortar pelo ano letivo mudaria a régua.
  - Na coluna "Adoção (alguma plataforma)", o numerador conta o retrato do Matific sem o corte do ano
    (`services/rede._alunos_com_qualquer_dado`).
- **Já era assim antes desta rodada:**
  - No Ranking da Rede, as colunas não seguem os módulos contratados (na rede só com Matific aparece "Adoção
    Elefante").
  - A tabela do boletim mantém as colunas Matific e Elefante na rede com uma plataforma só.
  - O PDF de reserva (fpdf, quando o Chromium falha) sai sem a introdução.
- **Sem E2E:** o menu do admin da escola é coberto só pelo Vitest (não há conta dele nos bancos de E2E).
- **Observação, não é defeito:** nas capturas do E2E da análise, os "Totais acumulados" do Elefante mostram 0 livros
  e 0 min, enquanto o uso no período mostra 1,19 livro por aluno.
  - São fontes diferentes: o acumulado vem do retrato da última coleta de cada aluno, pelo mesmo endpoint do Painel
    da Rede (`/redes/{id}/dashboard`).
  - O banco inventado desse E2E grava esse retrato com 0 livros e 0 min (`tests/test_analise_base.py:281`).
  - O banco da demo grava os livros (`seed_demo.py`).
