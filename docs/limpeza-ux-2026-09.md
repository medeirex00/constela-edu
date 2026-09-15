# Limpeza de UX — setembro/2026

Princípio: **a escola usa o Constela; a escola não administra a matemática interna do
Constela.** O Admin Global cuida de fórmula, parâmetros, catálogo, configurações globais e
diagnóstico técnico. A escola consulta, filtra (período e turno), premia, acompanha e
diagnostica a própria integração.

Nada do backend foi apagado: telas somem ou mudam de lugar, endpoints e modelos ficam. A
fórmula oficial (`scoring.py`, pesos 35/30/30/5 e 40/35/25, régua A3, dificuldade por livro
v1) não mudou.

## Classificação

| Funcionalidade | Ação | Onde ficou | Motivo |
|---|---|---|---|
| Editor de níveis de dificuldade (AA…Z) | MOVE → Admin Global | `Metricas.tsx`, `Elefante.tsx` (sub-aba só `is_global`) | Só vale no perfil personalizado, que só o Admin Global liga; para a escola era uma tabela que ela não edita e que não explica a nota real (v1). |
| Dificuldade por turma / por série | MOVE → Admin Global | idem | Idem. `PUT /pontuacao-turma` e `PUT /dificuldade` passam a exigir Admin Global. |
| Pesos da nota (Leitura, Matemática, Questões) | MOVE → Admin Global | `Metricas.tsx`; `PUT /pesos/{ns}` só global | No perfil institucional o motor usa `PESOS_PADRAO`; editar não mudava nota nenhuma, mas mostrava "notas recalculadas". |
| Pontos extras por leitura na escola | MOVE → Admin Global | `Metricas.tsx`; `PUT /elefante-extra` só global | Só entra no ramo personalizado. |
| Referências de normalização (P90) | HIDE da UI comum, KEEP no backend | `Metricas.tsx` (só global); `PUT /referencias` só global; cálculo intocado | Parâmetro matemático interno; a comparabilidade depende de ele não ser editável pela escola. |
| Régua Padrão × Personalizada | MOVE → Admin Global | `Metricas.tsx` (status read-only para a escola) | Já era só global no backend. |
| Explicação "Como funciona?" | KEEP (novo) | `components/ComoFuncionaPontuacao.tsx` lendo `GET /configuracoes/dificuldade-livro` | Transparência sem configuração. Nenhum número inventado: fatores vêm da API; se falhar, mensagem amigável. |
| Diagnóstico Elefante (sonda da API) | HIDE do menu do gestor, KEEP rota/permissão | `Layout.tsx`; link "Ver diagnóstico" em Integrações | Ferramenta técnica de manutenção, não uso diário. |
| Sincronização automática | MERGE → "Integrações" | `Sincronizacao.tsx` (rota `/sincronizacao` mantida) | Responde "os dados estão atualizados?" com situação, última/próxima sincronização, dados recebidos, erros e ações. |
| Importações (upload manual) | HIDE do menu do gestor, KEEP tudo | `Layout.tsx`; link "Enviar relatório manualmente (avançado)" | É o fallback quando a sync não existe; continua acessível e o Admin Global continua vendo no menu. |
| Aba "Escolar" (placeholder) | HIDE | `Rankings.tsx`; `RankingEscolar.tsx` fica no repositório | Sem fonte de dados; era uma aba vazia. |
| Aba Geral em modo "período" | MERGE com Evolução | `RankingGeral.tsx` (aviso + botão "Ver a aba Evolução") | Chamava o mesmo endpoint da aba Evolução com os mesmos parâmetros. Decisão desta limpeza: a aba Geral mostra sempre o acumulado do ano; a classificação por período fica só em Evolução. |
| Sub-abas "Desempenho em Leitura/Matemática" | MOVE para Leitura/Matemática | `components/DesempenhoDimensao.tsx` | O mesmo cálculo aparecia em duas abas com cortes diferentes. |
| Ranking de turmas | KEEP (novo, sem cálculo novo) | `pages/RankingTurmas.tsx` sobre `GET /resumo-escola` | Ordena médias oficiais já existentes; só turmas com aluno aferido. |
| Ranking de escolas | KEEP | `rede/RankingRede.tsx` (sem edição — arquivo do workstream paralelo) | Categoria "Escolas" para Admin Global e Secretaria. `/rede/ranking` passa a abrir a tela de Rankings nessa categoria (menu do Admin Global: "Ranking da Rede"); a Secretaria continua vendo só a página da rede. |
| Premiações | KEEP (turno global) | `Premiacoes.tsx` | Pergunta diferente: "quem será premiado?". Pódios por turno vêm do backend, com a régua da escola inteira. |
| Destaque Matific ("Melhor Matemática") | KEEP, fórmula não alterada | `services/premiacoes.py` (intocado) | Já combina volume e qualidade (`calcular_matific` oficial sobre o estado no fim da janela). Ver seção abaixo. |
| Endpoints de importação, sync, configurações, rankings | KEEP | backend | Consumidores reais (front, sync in-process, mobile, telão, testes). |

## Rankings

```
Ranking Geral (/ranking)
├── Alunos   (?ver=geral | leitura | matematica | evolucao)
│   ├── Geral       ordem única (Leitura + Matemática), acumulado do ano
│   ├── Leitura     classificação oficial · competição por turno · leitura no período (pontos)
│   ├── Matemática  classificação oficial · placar Matific (estrelas e atividades no período)
│   └── Evolução    crescimento na janela (única dona do período)
├── Turmas   (?ver=turmas)   média oficial por matéria, só turmas com aluno aferido
└── Escolas  (?ver=escolas)  índice per capita da rede (Admin Global e Secretaria)
```

Professor vê Alunos; coordenador e admin veem Alunos e Turmas; Admin Global com escola
selecionada vê as três; Secretaria e Admin Global em "Toda a Rede" veem Escolas.

## Turno

- Estado global `turno` no `AppContext`, persistido em `sgpe_turno`, separado de
  `sgpe_periodo`. Valores: `todos`, `''` (sem turno) ou o código da turma
  (`manha`, `tarde`, `noite`, `integral`).
- `SeletorTurno` mostra "Todos os turnos" mais os turnos que existem na escola (derivados de
  `GET /turmas`); nunca uma lista fixa.
- Backend: `GET /ranking`, `/nao-aferidos`, `/ranking/leitura` e `/ranking/matematica` aceitam
  `?turno=` com a mesma semântica de `/ranking-evolucao` (omitido = todos; vazio = sem turno;
  senão exato). Em `/ranking`, com turno informado, as posições vêm renumeradas e
  `n_aferidos` é o do conjunto filtrado. Sem turno, a posição continua sendo a carimbada da
  escola.
- Premiações: `GET /premiacoes?turnos=true` já devolvia pódios por turno; o front escolhe o
  grupo pelo turno global. A régua da Matemática continua sendo a da escola inteira (decisão
  registrada em `premiacoes.py`).

## Integrações (antiga "Sincronização automática")

Por plataforma: Situação (Funcionando / Dados desatualizados / Falhou / Ainda não configurada /
Sem dados ainda / Sincronizando / Conexão não validada), última sincronização e último
sucesso, próxima, dados recebidos, erros (alertas da plataforma com "Resolver"), "Ver
diagnóstico" (Elefante) e "Enviar relatório manualmente (avançado)".

Novos campos de `GET /sync/status` (só leitura, aditivos): por plataforma
`alunos_com_dados`, `alunos_sem_dados`, `alunos_com_zero_registros` (só Elefante; distingue
"zero livros real" de "sem dado"), `dado_mais_recente_em`; por escola
`pendencias_correspondencia_30d`. Os contadores antigos da execução aparecem como
"registros processados" e "linhas não vinculadas", porque é o que eles contam.

## Matific — fórmula do destaque (auditada, não alterada)

"Melhor Matemática" nas Premiações = `scoring.calcular_matific` (a função oficial) aplicada ao
último snapshot de cada aluno até o fim do período: `nota = norm(atividades)·0,40 +
norm(média)·0,35 + norm(estrelas)·0,25`, com saturação nos indicadores de volume
(atividades e estrelas) e referência P90 quando há 8 ou mais alunos. Exemplo do dono com a
fórmula atual (coorte pequena, régua linear pelo máximo): B (120 atividades, 540 estrelas,
média 4,5) = 86,7; A (180, 450, 2,5) = 80,3; C (90, 405, 4,5) = 73,8. Com 8 ou mais alunos a
saturação comprime a vantagem de volume de A.

A fórmula não foi alterada nesta tarefa. Alternativas documentadas para decisão do dono:
"estrelas de qualidade" (estrelas × média/5 → B 486, C 364, A 225) e "média ajustada com
piso" (média bayesiana com peso da coorte e piso de 10 atividades → B 4,3, C 4,3, A 2,7).
Pendência conhecida e não corrigida aqui: aluno com snapshot só antes do início da janela
ainda entra no pódio do período (xfail em teste untracked do workstream paralelo).

## O que ficou de fora de propósito

- Arquivos do workstream paralelo (`Configuracoes.tsx`, `Dashboard.tsx`, `PerfilAluno.tsx`,
  `Simulador.tsx`, `Matific.tsx`, `rede/*`, `routers/sistema.py`, etc.): não editados. Itens
  a repassar: `Configuracoes.tsx` mostra pesos legados em somente leitura para a escola;
  `PerfilAluno.tsx` diz "Configuráveis em Métricas"; `Simulador.tsx` e `POST /simulador`
  honram a configuração local mesmo no perfil institucional; `RankingRede.tsx` renderiza o
  próprio cabeçalho quando embutido na categoria Escolas; `Matific.tsx` rotula a média como
  0–100 numa escala 0–5.
- Atalho Alt+5 continua em `/importacoes`.
- Alterações de fórmula (Matific, piso da janela) e "Ranking de turmas" por dimensão no
  backend: decisões de produto pendentes.

## Revisão adversarial (triagem)

Cinco lentes revisaram a mudança (governança, cálculos e turno, aderência ao mandato,
regressão, cobertura de testes) e levantaram 37 achados. A etapa automática de refutação
não chegou a rodar, então a triagem foi feita manualmente contra o código.

Corrigidos nesta mesma entrega:

- Cartaz por matéria voltou a ter botão (classificação oficial de Leitura e de Matemática).
- Ranking legado com recorte (professor ou turno) passa a carimbar `n_aferidos`; o cabeçalho
  da aba Geral diz se a posição é do turno, do filtro ou da escola inteira.
- Placar Matific ao vivo: turmas homônimas em turnos diferentes saem do filtro de turno com
  aviso, em vez de misturar alunos.
- Premiações: mensagem de turno sem alunos corrigida, aviso e "Melhor Evolução" só com os
  dados do recorte atual, motivo do seletor desabilitado em texto visível.
- Categoria Escolas sem cabeçalho duplicado; `/rede/ranking` roteado para a tela de Rankings.
- Editores de peso com os campos desabilitados em modo somente leitura.
- "Como funciona?" não mostra os pesos institucionais quando a escola está na régua
  personalizada; teste de paridade garante que os números do front batem com
  `scoring.PESOS_PADRAO`.
- Aviso de escola sem níveis, para a escola, sem citar telas que ela não vê.
- Integrações: motivo de falha em linguagem humana (texto técnico só como detalhe),
  "não foi possível contar" distinto de "0 de 0", dado mais recente só dos alunos pontuados,
  links do banner honestos sobre onde as pendências aparecem.
- Trilha do topo mostra "Pontuação" para a escola; acessibilidade dos seletores de turno e
  das abas.
- Testes que faltavam: lista "Ainda não aferidos", turno na aba Evolução, escola sem turmas
  com turno persistido, turno sem alunos nas Premiações, Secretaria nas rotas de governança.

Não corrigidos, de propósito:

- "Ver diagnóstico" continua visível para a escola no card do Elefante: é o fluxo pedido
  (Integrações → Elefante Letrado → Ver diagnóstico).
- Consulta transitória com o turno persistido antes de as turmas da escola carregarem: o
  resultado final é correto e evitá-la exigiria segurar todas as telas de ranking.
- `exigir_papeis_escola` ficou sem uso em `deps.py`, que está fora do escopo.
- Arquivos do workstream paralelo (`Configuracoes.tsx`, `PerfilAluno.tsx`): pendências
  listadas na seção anterior.

