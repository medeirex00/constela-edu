# Rodada 3 — a Secretaria em três áreas — 02/11/2026

Branch `feat/navegacao-inteligencia`, a partir de `cb9a344` (rodada 2, ver
`RODADA-2-SECRETARIA-MINHA-ESCOLA-VITRINE.md`). Tudo LOCAL: sem push, sem deploy, sem migração, sem dado real.
A demo de Jacareí e a `visual-v2` não foram tocadas. Decisões de desenho: D55–D59 em
`docs/design/IDENTIDADE-VISUAL-V2.md`.

O pedido: a Secretaria acompanha a rede, vê quais escolas usam o Constela, identifica as que se destacam e compara com as
avaliações externas — em **três áreas**. Sai da navegação dela o que não é dessa função (relatórios e exportações,
premiações individuais, gestão de usuários e configurações, diagnósticos técnicos e análises avançadas), sem quebrar
rotas nem mudar permissão de backend, e preservando o que a Coordenação e o Admin Global usam.

## 1. Menu da Secretaria

```
REDE MUNICIPAL   Panorama da Rede (/) · Escolas (/rede/escolas) · Avaliações externas (/rede/avaliacoes-externas)
```

- Sem acordeão e sem "Análises avançadas". Suporte (rodapé) e Minha conta (menu do usuário) continuam.
- **Atalhos:** Alt+1 Panorama, Alt+2 Escolas, Alt+3 Avaliações externas. As outras teclas não navegam para a Secretaria
  (levavam a telas de escola, como Conquistas e Assistente, que abriam vazias para ela).
- **Cartão Contexto:** escolher uma escola leva à ficha dela. No Suporte, o cartão só troca a escola (a regra da nota
  aparece ali). "Toda a Rede Municipal" volta ao `/` quando a tela atual é de escola.
- **Busca (Ctrl+K):** acha só as três áreas e o Suporte, inclusive pelos nomes antigos que fazem sentido ("comparar" →
  Escolas, "saresp" → Avaliações externas, "vitrine" → Panorama).
- **O `/` da Secretaria é sempre o Panorama da Rede.** O "Panorama Geral da escola" saiu; a ficha o substitui.
- **Rotas que saíram do menu e continuam abrindo** (mesmas guardas): Painel da Rede `/rede`, Escolas em acompanhamento,
  `/rede/plataformas` (o detalhe do uso, a partir do Panorama), Relatórios e exportações, Ranking da Rede (a partir de
  Escolas e do Panorama), Análises avançadas `/rede/analise`, Fontes e arquivos oficiais `/rede/avaliacoes` (a partir de
  Avaliações externas) e `/rede/visao`.
- **Admin Global:** o menu não mudou. A "Visão da rede" (`/rede/visao`) mostra o Panorama novo, com o seletor de rede e,
  só para ele, os atalhos para Relatórios e exportações e para Escolas em acompanhamento.
- **Coordenação e professora:** não mudaram. Usuários continua em Minha Escola.

## 2. Panorama da Rede (página inicial)

Conclusão primeiro, cada número com "O que mede" e selo de natureza. Avaliações externas não são o elemento principal:
aparecem só no rodapé, com o link e a frase de que avaliações e plataformas são de períodos diferentes.

1. **A rede no Constela.** Três categorias que NÃO são sinônimos:
   - escolas **cadastradas**: vinculadas à rede;
   - **ativas no cadastro**: situação do cadastro, que não indica uso;
   - **com uso no ano letivo**: ao menos um aluno do 1º ao 5º ano leu um livro no Elefante ou fez uma atividade no Matific
     no ano letivo, pelas coletas.

   As demais escolas aparecem por extenso: sem uso registrado, sem dado ou protegidas.
2. **Participação no ano letivo** por plataforma contratada.
   - Diz quantas escolas entram na soma (as com a coleta em dia ou cobrindo ao menos 90% do período).
   - Com escolas em anos letivos diferentes, não afirma um ano só.
   - Link para o detalhe do uso.
3. **Todas as escolas da rede**, inclusive inativas e sem alunos, em ordem alfabética.
   - Cada escola traz: cadastro, alunos (todas as etapas), uso por plataforma e situação geral.
   - O nome leva à ficha. Há filtro por situação; no celular, a lista vira cartões.
   - Se só a leitura do uso falhar, a lista continua (vem do cadastro) e o uso aparece como "não foi possível carregar".
4. **Escolas em destaque**, com o critério escrito: o MESMO da vitrine pública, calculado pelo mesmo código.
   - Leitura: livros por aluno (Elefante), acumulados desde o início da conta.
   - Matemática: estrelas por aluno (Matific), no ano letivo.
   - Só escolas ativas, com 5 alunos do 1º ao 5º ano e 5 que somam em cada plataforma; as 5 maiores.
   - A escola com o número escondido por proteção fica de fora, e a tela diz quantas ficaram.
   - Link para o Ranking da Rede, avisando que ele é outra medida.
5. **Reconhecimento público.** O cartão da vitrine pública (ligar, copiar, abrir): a Secretaria reconhece publicamente as
   escolas pelo Panorama. O `/painel-publico` leva a ela.
6. **Metas da rede**, recolhidas. Cada meta diz o que o número mede e, quando se sabe, de quando é. Por exemplo, a adoção
   não tem período e não é uso.

Endpoint novo, só leitura: `GET /redes/{id}/destaques`, com a mesma dependência de acesso do painel da rede (D58).

## 3. Escolas

- **Lista** (`/rede/escolas`): todas as escolas no período (padrão: ano letivo) e na série escolhidos, com o Elefante e o
  Matific. A escola inativa vem marcada.
  - Ordem alfabética ("não é ranking"); o nome leva à ficha.
  - Se a leitura do uso falhar, a lista vem do cadastro.
- **Comparação lado a lado:** marque de 2 a 4 escolas, ou abra pelo link `?comparar=`.
  - Cada escola mostra o Elefante e o Matific no período e as avaliações externas, separadas pela frase dos períodos.
  - Cada avaliação usa uma edição só: a mais recente com resultado entre as escolas comparadas. A escola cujo último
    resultado é de edição anterior aparece com o ano dele, sem o número, que fica na ficha.
- **Ficha da escola** (`/rede/escolas/{id}`, rota nova, mesma guarda das telas da rede):
  - cadastro (ativa/inativa, cidade, alunos de todas as etapas, turmas, professores);
  - situação de uso;
  - Elefante e Matific no período;
  - evolução por bimestre só da escola;
  - avaliações externas da escola, em modo simples: sem termo técnico, avisos recolhidos e o porquê quando não há
    resultado (sem código INEP, nenhuma edição com a escola…);
  - "Ver as turmas da escola" (Visão da Escola, também em modo simples para a Secretaria). Escola fora do contexto, como a
    inativa, não oferece esse link;
  - escola inexistente ou de outra rede: mensagem clara.
- **Ranking da Rede:** link na página, como outra medida (a pontuação do Constela).

## 4. Avaliações externas

- **Cartões por indicador** (ICA, SARESP, IEE, Ideb, Saeb): o que mede, quem publica, frequência, **disponibilidade** (edição
  mais recente importada, ou o motivo) e meta.
- **Detalhe de cada indicador:** série histórica (comparar edições) e escolas numa edição (comparar escolas), com o nome
  levando à ficha e as tabelas presas no celular.
- **Seção nova "Todas as escolas na edição mais recente de cada avaliação"** (antes era uma aba de Comparar escolas):
  - cada coluna é uma edição só, a mais recente com resultado entre as escolas;
  - a escola de edição anterior aparece com o ano, sem o número;
  - a escola inativa vem marcada;
  - a conclusão conta só a edição de referência de cada série;
  - as explicações ficam uma vez na legenda, não em cada célula.
- **Link de fonte:** "Arquivos oficiais de cada número". Sem link para Análises avançadas nem para Relatórios. A página de
  fontes, aberta pela Secretaria, também não aponta mais para as Análises avançadas.

## 5. Testes e revisão (árvore final)

| Suíte | Resultado |
|---|---|
| Frontend (Vitest) | 141 arquivos, **1900/1900** |
| `tsc --noEmit` | sem erro |
| Backend (pytest completo, SQLite) | **6217 passaram**, 0 falha; 508 pulados (os que pedem PostgreSQL ou outro ambiente) |
| Backend PostgreSQL (`-m postgres`, cluster PG17 descartável) | **505/505** |
| E2E principal | **49/49** |
| E2E da análise, navegação e Vitrine (backend sem `PUBLIC_BASE_URL`) | **41 passaram**, 0 falha; 4 pulados (as capturas, que só rodam com `CAPTURAS_NAV=1` e passaram 4/4 à parte) |
| Varredura visual (`playwright.visual.config.ts`: 93 telas (perfil × rota) × 10 larguras; a Secretaria com as três áreas, a comparação, a ficha, a seção de escolas das avaliações e as rotas antigas) | **930 registros**: 0 erro de console, 0 falha de API, 0 rolagem lateral, 0 tela sem título. Contraste igual à base V2 (os mesmos 10 avisos antigos, num rótulo de `/metricas` do admin) |
| Build (`vite build`) | sem erro nem aviso (PWA: 246 entradas no precache) |

**Navegação e permissões dos quatro perfis** (E2E e Vitest):
- **Secretaria:** exatamente 3 itens; Alt+1/2/3; Contexto → ficha; rotas antigas abrindo; nenhum item de premiação,
  usuários, configurações, relatórios ou análises.
- **Admin Global:** menu igual ao de antes (6 itens em "Redes e municípios"); Visão da rede com o Panorama novo.
- **Coordenação:** Minha Escola com Usuários, no desktop e na gaveta.
- **Coordenação e professora:** redirecionadas de todas as rotas de rede, inclusive da ficha; 403 nas APIs da rede,
  inclusive `/destaques`.
- **Vitrine:** abre nos 4 perfis, com a Secretaria pelo Panorama, inclusive com um token vencido guardado no navegador.

**Permissões:** nenhuma guarda de rota existente nem dependência de backend mudou. A rota nova da ficha usa `RotaRede`. O
endpoint novo usa a mesma dependência do painel da rede e devolve só agregados por escola.

**Revisão:**
- Cada pacote de implementação (5) e de correção (3 + 3 + 2) passou por um verificador.
- A revisão independente final (4 dimensões, um cético por achado) teve 33 achados: 24 confirmados, todos corrigidos, e 9
  refutados. Entre os corrigidos:
  - o caminho do Admin Global para os relatórios;
  - a lista de escolas que não pode sumir sem o dado de uso;
  - não misturar edições nas comparações;
  - "livro" (não "livro novo", porque o número conta a releitura);
  - o denominador do Matific;
  - o escopo da participação;
  - o período de cada meta;
  - anos letivos misturados;
  - a escola inativa no contexto;
  - a Visão da Escola sem escola.

## 6. Pendências e decisões do dono

- **Período dos destaques e do índice:** a leitura soma os livros desde o início da conta de cada aluno, como a vitrine e
  o Ranking. Está dito na tela. Recortar pelo ano letivo mudaria a régua (decisão de produto).
- **Adoção:** o numerador da adoção no Ranking conta o retrato do Matific sem o corte do ano (`_alunos_com_qualquer_dado`).
  Vem de antes.
- **Ranking da Rede:** as colunas não seguem os módulos contratados. Vem de antes.
- **Demo de Jacareí (8040):** tem a causa da Vitrine e o menu antigo. Não foi alterada; precisa de autorização.
- **"Voltar para a ficha":** ao voltar da Visão da Escola, a ficha abre sem a consulta da lista. O "‹ Escolas" volta à
  lista padrão.
- **Capturas do E2E:** o banco inventado grava o acumulado do Elefante com 0 livros, então a lista de destaques de Leitura
  aparece vazia nas capturas. No banco da demo e com dado real, ela aparece.
- **Meta "atividades":** a nota da meta diz "do ano letivo, pela última coleta". Convém o dono confirmar que o total do
  Matific que alimenta a meta é do ano letivo.
