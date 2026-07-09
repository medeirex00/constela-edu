# 03 — Gamificação e Progressão

Referência de tom: o jogo celebra **esforço e evolução**, nunca pune erro.
Toda regra numérica abaixo é o padrão inicial — vive em `configuracoes`
(namespace `quest.*`) e é ajustável sem deploy, como tudo no Constela.

## As três moedas da economia (e por que três)

| Recurso | Ganha-se | Gasta-se | Função psicológica |
|---|---|---|---|
| **XP** ⭐ | Qualquer atividade | Nunca | Progresso permanente — nível, passe, ranking. Só cresce: a criança nunca "perde progresso" |
| **Moedas** 🪙 | Concluir missões, diárias, eventos | Loja de cosméticos | Autonomia e desejo — "estou juntando para o pet dragão" |
| **Estrelas** ✨ | Maestria por missão (0–3 por missão) | Nunca (são chaves) | Qualidade > quantidade — destravam chefões e jornadas; incentivam revisitar missão para melhorar |

Separar progresso (XP) de poder de compra (moedas) de maestria (estrelas)
evita o erro clássico de moeda única: criança rica que não aprende, ou
criança aplicada sem nada para gastar.

## XP e a curva de níveis

- **Desafio correto**: `4 XP × dificuldade (1–5)`; bônus +50% se acertou de
  primeira, sem dica.
- **Missão concluída**: `xp_base` da missão × multiplicador de estrelas
  (1★ ×1,0 · 2★ ×1,25 · 3★ ×1,5).
- **Repetição decai**: rejogar missão já concluída rende 50% na segunda vez
  e 25% da terceira em diante (revisão vale, farm não).
- **Teto diário** de XP (padrão 600): protege contra uso compulsivo e
  mantém o ranking honesto. Ao atingir, o Cosmo comemora: *"Uau, você
  treinou demais hoje! Amanhã tem mais!"* — teto é celebração, não bloqueio.

Curva de nível (linear-progressiva, legível para criança):

```
custo do nível n → n+1  =  80 + 20 × n     (XP)
nível 1→2: 100 · 5→6: 180 · 10→11: 280 · 20→21: 480
```

Sobe-se ~1 nível a cada 2–4 dias de uso saudável no início, desacelerando
suavemente. Subir de nível SEMPRE entrega algo concreto: moedas + item ou
desbloqueio visível na hora, com celebração do Cosmo em tela cheia.

## Estrelas (maestria por missão)

| Resultado da melhor tentativa | Estrelas |
|---|---|
| Concluiu a missão | ⭐ |
| ≥ 80% de acertos | ⭐⭐ |
| 100% de acertos | ⭐⭐⭐ |

- Estrela nunca é perdida — vale a melhor tentativa histórica.
- Jornadas pedem estrelas para liberar o **chefão** (ex.: "junte 10 ✨
  nesta jornada") → razão natural para revisitar missões antigas =
  **revisão espaçada disfarçada de jogo**.

## Sequência de dias — "A Chama do Cosmo" 🔥

- Conta dias com pelo menos 1 missão concluída.
- **Escudo semanal automático**: 1 falta por semana não apaga a chama
  (renova toda segunda). Criança de 7 anos não controla a própria agenda —
  punir a falta pune a família, não o aluno.
- Fim de semana conta se jogar, mas **não quebra** a sequência se não jogar
  (configurável por escola).
- Marcos (3, 7, 14, 30, 60, 100 dias) dão recompensas crescentes e um
  colecionável exclusivo no dia 100.
- Perdeu a chama? Zera com mensagem gentil e um "reacender" que devolve 25%
  dos dias. Nunca tela triste, nunca culpa.

## Ritmo de retorno (por que entrar hoje?)

| Cadência | Mecânica |
|---|---|
| Diária | Presente de login (moedas/item pequeno, trilha de 7 dias) · 3 missões diárias sorteadas (com viés para habilidades fracas) · Chama |
| Semanal | 2 missões semanais maiores · ranking da turma reinicia (todo mundo recomeça — ninguém fica eternamente em último) |
| Temporada (6–8 semanas) | Passe gratuito com trilha de recompensas · tema visual novo no lobby |
| Pontual | Eventos (Festa Junina, Dia das Crianças, Halloween, Natal, Férias) com missões, mapa decorado e colecionáveis limitados |

## Planetas, jornadas e o mapa do universo

```
Universo Constela
└── Planeta (mundo/disciplina) — 9 no lançamento do catálogo
    └── Jornada (por ano escolar, em sequência)     ex.: "Vale dos Números"
        ├── Missão 1 (normal)      ●─●─●─○─○  trilha visível no mapa
        ├── Missão 2 (normal)
        ├── ...
        └── Chefão 👾 (libera com X estrelas) → conclui a jornada
```

- O aluno vê **apenas as jornadas do seu ano escolar** (± revisão do ano
  anterior liberada). A série vem da matrícula (`matriculas` → `turmas.
  ano_escolar`) — zero configuração manual.
- Concluir jornada = animação da constelação ganhando uma estrela nova no
  mapa pessoal + colecionável do planeta.
- Planetas têm **progressão independente**: empacou em Matemática? Português
  segue aberto. Nenhuma criança fica 100% travada.
- Identidade por planeta (cores, música, cenário, personagens secundários,
  colecionáveis) vem do JSON `tema` no catálogo — o protótipo
  `constela-play-v7.html` já define o formato visual (SUBJECTS/SCENES).

### Nota honesta sobre dois planetas

- **Educação Física**: atividade digital não substitui movimento. As missões
  são "desafios ativos" (vídeo curto + tarefa física) com confirmação do
  professor, mais quizzes de regras de jogos/saúde. Entra em fase posterior,
  com design próprio.
- **ERER**: conteúdo sensível que merece curadoria pedagógica humana (não
  IA) e revisão por especialista antes de publicar. O catálogo o suporta
  desde o dia 1; o conteúdo entra com calma e qualidade.

## Dificuldade adaptativa (v1 heurística, v2 IA)

- Cada desafio tem `dificuldade` 1–5; cada perfil tem nível adaptativo por
  mundo (1–5, começa em 2).
- Janela móvel das últimas 10 respostas no mundo:
  - ≥ 85% de acerto → sobe 1 (até 5) — silencioso.
  - ≤ 40% → desce 1 (até 1) — silencioso, e o Cosmo oferece uma missão de
    reforço ("Vamos treinar isso juntos?").
- A missão sorteia desafios centrados no nível adaptativo (±1).
- **A criança nunca vê o número.** Ela só sente que o jogo "é do tamanho
  dela". O professor vê (no Edu) — para ele é informação pedagógica.
- v2 (fase IA): estimativa de domínio por habilidade BNCC alimentando a
  seleção; geração de desafios sob revisão do professor.

## Conquistas e colecionáveis

- Conquistas data-driven (mesmo motor de critérios do Edu): exploração
  ("visite 3 planetas"), maestria ("10 missões com 3★"), constância
  ("Chama de 30 dias"), sociais ("complete 5 missões com um amigo"),
  secretas (surpresas — ex.: jogar no dia do aniversário).
- Colecionáveis por planeta (ex.: 12 criaturas de Ciências): aparecem
  aleatoriamente ao concluir missões do planeta; álbum de figurinhas na
  Constelação pessoal. Completar o álbum = item lendário.

## Avatar, pets e loja

- Avatar = Cosmo-base personalizável (cor do traje já existe no protótipo) +
  slots: roupa, chapéu, óculos/acessório, pet, efeito de vitória, moldura,
  dança de comemoração.
- **Pets** acompanham o astronauta no lobby e comemoram junto. São o item
  aspiracional máximo (raros, caros, adoráveis).
- Loja com rotação semanal (4–6 itens) + seção fixa. Preços calibrados:
  item comum ≈ 2 dias de jogo; lendário ≈ 3–4 semanas. **Sem caixas de
  surpresa pagas, sem moeda comprada, sem "quase acabando" agressivo** —
  escassez honesta (item de evento volta no evento do ano seguinte).

## Rankings sem toxicidade (posição firme de design)

O pedido original inclui ranking municipal para alunos. Recomendação
contrária, e o desenho reflete isso:

- **Padrão da criança**: a própria Constelação (eu × eu de ontem). É a
  primeira tela de progresso, não o ranking.
- **Ranking da turma**: semanal (zera segunda), top 3 celebrado, os demais
  veem "sua posição subiu/desceu" sem lista completa da lanterna. Sempre
  acompanhado do ranking de **evolução** (quem mais cresceu) — filosofia que
  o Edu já pratica.
- **Escola**: entre **turmas** (coletivo, não expõe criança): "3º Ano B
  somou 12.400 XP esta semana!" — cooperação intra-turma, rivalidade
  saudável inter-turmas.
- **Municipal**: só entre escolas, e só no Edu/Hub (adultos). Expor ranking
  individual municipal a crianças de 6 anos é combustível de ansiedade e
  risco LGPD sem ganho pedagógico.
- Torneios (fase futura) são o espaço certo de competição: opt-in, com
  começo/fim, medalha para todos os participantes.

## Modos sociais (resumo de design; arquitetura no doc 01)

| Modo | Jogadores | Regra de ouro |
|---|---|---|
| 🤝 **Estudar com um amigo** (missão compartilhada) | 2 | Objetivo comum ("vamos juntar 10 ⭐"); cada acerto de qualquer um avança a dupla; recompensa igual para os dois |
| 🏁 **Corrida** (3 skins: bichinhos 🐰 / espacial 🚀 / trilha) | 2 | Acertou → anda. Quem chega primeiro ganha um efeito de confete a mais; **os dois ganham XP e moedas**; derrota nunca custa nada |
| 🎨 **Pintura em dupla** | 2 | Cada acerto pinta uma parte do desenho; termina quando o desenho fica completo — não existe vencedor |
| ⚡ **X1 amistoso** | 2 | Quiz em tempo real; placar lado a lado; fim com "revanche?" e elogio para ambos |

Vocabulário interno (party/lobby/matchmaking) **jamais** aparece na UI.
Fluxo da criança: botão grande "🤝 Estudar com um amigo" → lista de amigos
online → convite → contagem 3, 2, 1 → jogando.

## Cosmo — o coração emocional

Cosmo é uma **máquina de estados com memória curta**, não um chatbot:

| Estado | Gatilho | Comportamento |
|---|---|---|
| Recepção | login | saúda pelo apelido, lembra o que ficou pendente ("Ontem você quase venceu o chefão!") |
| Torcida | durante missão | reações curtas a acertos (variadas, nunca repetidas em sequência) |
| Dica | 1º erro ou pedido | lê a `dica` do desafio (áudio) |
| Consolo/reforço | 2+ erros seguidos | *"Essa é difícil mesmo! Vamos ver juntos?"* → mostra a `explicacao`; nunca tristeza culpabilizante — Cosmo fica encorajador, não decepcionado |
| Festa | missão/nível/conquista | celebração proporcional à raridade |
| Descanso | 40+ min contínuos (configurável) | *"Ufa, que treino! Que tal esticar as pernas? Eu guardo seu lugar!"* — cuidado com a criança > engajamento |

- Falas em tabela (pt-BR) com variações; **todas com áudio** (1º/2º ano
  não leem com fluência).
- Fase IA: falas geradas/contextualizadas via `services/ia` existente, com
  guarda-corpos (catálogo de intenções permitidas, nunca texto livre da
  criança para o modelo).

## Acessibilidade (não negociável, público 6–11)

- Toda instrução tem áudio; botões ≥ 48px; máximo 1 ação primária por tela.
- Navegação sem leitura: ícones + cor + áudio sempre juntos.
- `prefers-reduced-motion` respeitado (o protótipo já faz); modo daltônico
  nas mecânicas que dependem de cor; fonte ampliável.
- Tempo nunca é o único critério: modos com pressa (corrida) são sociais e
  opcionais; missões normais não têm cronômetro punitivo.
