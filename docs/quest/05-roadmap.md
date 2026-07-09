# 05 — Roadmap de Implementação

Mesma filosofia do Edu: cada fase entrega valor usável em produção e
nenhuma exige reescrever a anterior. O banco e as fronteiras do doc 01/02
já comportam todas as fases.

A régua de corte de toda fase: **uma criança real consegue usar e quer
voltar amanhã?**

## ✅ Fase Q0 — Fundação (esqueleto vivo) — entregue em 09/07/2026

Objetivo: uma criança entra com o cartão e conhece o Cosmo.

**Entregue:** módulo `backend/app/quest` (models grupos 1–3, login infantil
com código+PIN/QR, cartões PDF, 9 testes — suíte total 266), pacote
`@constela/quest-core`, app `apps/quest` (PWA, design system do protótipo,
entrada em 3 passos, lobby com Cosmo vivo, cor do traje persistida,
gaveta com preferências), botão "Cartões do Quest" na turma do Edu, CI.
**Ressalvas:** efeitos sonoros são sintetizados (WebAudio) e a narração usa
a Web Speech API — trilha musical e áudios gravados entram quando houver
assets; leitura de QR pela câmera DENTRO do app fica para quando houver
tablets de teste (o QR do cartão já funciona via câmera nativa do aparelho,
que abre a URL).

**Revisão 2 — lobby completo e customização (09/07/2026):** abas Jogar/
Vestiário/Carreira; trilho de matérias que troca o fundo para a cena
temática da disciplina e mostra as missões do dia + "Jogar agora";
vestiário estilo Roblox (cor/rosto/chapéu/veículo + editar apelido);
carreira com conquistas/estatísticas/histórico; personagem com física de
mola no toque (sem falas); 1º meio de locomoção (skate voador com jatos,
entrada saindo da constelação); e a conta deixou de ficar salva no
aparelho (token só em memória — sai/recarrega → login pelo código;
constelação e estado não vazam entre contas). Avatar ganhou slots
rosto/chapeu/veiculo no backend (whitelist).

**Revisão pós-análise (09/07/2026, mesma data):** decisões do dono do
produto aplicadas — login SEM senha/PIN (o código `SOL1234`, só letras e
números, é a credencial, como no Elefante Letrado) e cerimônia da primeira
vez em que a criança escolhe COMO quer ser chamada (nome_exibicao) e a cor
do traje. Também entregues: "Quem vai jogar?" (astronautas do aparelho),
"É você?" no boot (tablet compartilhado), sessão resiliente a queda de
Wi-Fi (cache local, só 401/403 desloga), narração pt-BR com voz explícita
+ botão "ouvir de novo" em todo passo, limitador por (código, IP) que não
pune a turma atrás do NAT, mensagem própria para aluno inativo, cartão
individual por aluno, página "só do professor" no PDF, zonas de toque do
Cosmo, céu tocável (constelação do dia), chips zerados escondidos,
despedida com confirmação, contraste/foco/gaveta acessíveis, ícones PNG
do PWA e fontes só latin (precache 1,4MB → 319KB).

- `apps/quest` criado no monorepo (Vite + React + TS + PWA), CI incluída
- Design system: tokens e componentes extraídos do `constela-play-v7.html`
  (Botao3D, Chip, Painel, Trilho, céu/cenários, tema claro/escuro) — rebrand
  PLAY → QUEST
- `packages/quest-core` (tipos + cliente HTTP nos padrões do `@constela/core`)
- Backend: módulo `app/quest` com models do doc 02 (grupos 1–3), migração
- Login infantil completo: geração de cartões no Edu (PDF QR + código +
  PIN de figuras), fluxo de entrada no Quest, JWT papel aluno
- Lobby com Cosmo vivo (portado do protótipo), perfil, apelido, cor do traje
- Áudio base: música do lobby, efeitos de UI, narração das telas de entrada

**Pronto quando**: aluno da escola-piloto loga sozinho no tablet e passeia
pelo lobby.

## Fase Q1 — Núcleo jogável (o produto mínimo encantador)

Objetivo: o loop completo estudar → ganhar → evoluir, num planeta.

- Motor de missões (`MissaoPlayer`) + registry de mecânicas
- 4 mecânicas DOM: **quiz, arrastar e soltar, ligar colunas, memória** —
  todas com áudio de instrução e validação de gabarito no servidor
- Planeta Matemática completo para os 5 anos escolares (~6 jornadas/ano ×
  5 missões — conteúdo seed alinhado a códigos BNCC, em
  `backend/app/quest/conteudo/`)
- Progressão: XP, níveis, moedas (ledger), estrelas, tela de recompensa
  com celebração
- Trilha de jornadas no mapa do planeta; chefão por estrelas
- Cosmo em missão: torcida, dica, consolo, festa
- Telemetria completa (`quest_tentativas`) desde o primeiro clique

**Pronto quando**: uma turma-piloto joga uma aula inteira sem ajuda e
pergunta "posso jogar de novo?".

## Fase Q2 — Retenção (por que voltar amanhã)

- Missões diárias/semanais + presente de login + Chama do Cosmo (sequência
  com escudo)
- Conquistas (motor data-driven) + colecionáveis do planeta (álbum)
- Vestiário completo: loja, inventário, itens, pets, rotação semanal
- Constelação pessoal (tela de progresso eu × eu)
- Dificuldade adaptativa v1 (heurística silenciosa)
- Planeta Português + mecânicas caça-palavras e completar
- PWA offline: cache da jornada atual + fila de tentativas

**Pronto quando**: alunos entram em casa, sem a escola mandar (medível
pela telemetria: sessões fora do horário de aula).

## Fase Q3 — Professor e família (fechar o triângulo)

- Telas do professor no Edu: panorama da turma, mapa de habilidades BNCC,
  erros comuns, trajetória do aluno, alertas
- Missão da Turma (professor destaca uma missão da semana)
- Portal da Família: resumo, controles (social/horário), push semanal
- Papel `responsavel` + vínculos, certificados PDF
- Outbox → notificações (push existente) e mural do Edu

**Pronto quando**: na reunião de pais, o professor abre o mapa de
habilidades da turma; um responsável mostra o resumo no celular.

## Fase Q4 — Social (aprender junto)

- Amizades (pedido/aceite, código de amigo), presença online
- "🤝 Estudar com um amigo": missão compartilhada cooperativa
- Motor de corrida com as 3 skins (bichinhos, espacial, trilha)
- Pintura em dupla · X1 amistoso (quiz em tempo real)
- WebSocket + salas (memória; Redis se já houver réplica)
- Mensagens rápidas aprovadas; controles sociais por escola/turma/aluno
- Ranking da turma (semanal, com ranking de evolução) + XP coletivo entre
  turmas

**Pronto quando**: duas crianças em casas diferentes completam uma missão
juntas — e os dados chegam ao professor.

## Fase Q5 — Mundo vivo (o universo respira)

- Temporadas + passe gratuito (trilha de recompensas)
- Eventos temáticos (Festa Junina, Dia das Crianças, Natal, Férias…)
  com decoração do lobby, missões e colecionáveis limitados
- Planetas restantes: Ciências, Geografia, História, Inglês, Artes
  (+ Ed. Física com desafios ativos e ERER com curadoria — ver doc 03)
- Torneios da escola (opt-in, medalha para todos) · clubes (se a demanda
  confirmar)
- Redis + réplicas conforme carga

## Fase Q6 — IA (o tutor invisível)

- Cosmo explica erros em linguagem de criança (via `services/ia`, com
  cache e filtros)
- Dificuldade adaptativa v2 por habilidade BNCC
- Gerador de desafios com fila de revisão do professor no Edu
- Narrativas de missão gerador-assistidas (adulto no loop)

## Riscos mapeados (e resposta)

| Risco | Mitigação |
|---|---|
| **Conteúdo é o gargalo** (30 missões × 9 planetas × 5 anos é MUITO) | Q1 foca 1 planeta profundo, não 9 rasos; formato JSON + estúdio de autoria simples; gerador IA (Q6) com revisão humana multiplica produção |
| Áudio/ilustração custam produção | Biblioteca de assets por planeta definida 1x no `tema`; narração via TTS de qualidade gravada em lote |
| Crianças de 6 anos travam no login | Teste de corredor na escola-piloto já na Q0 — é o critério de pronto da fase |
| Multiplayer antes da retenção básica | Social só na Q4, deliberadamente: um jogo solo excelente com amigos depois > um multiplayer raso |
| Uso compulsivo / reclamação de pais | Tetos, pausa do Cosmo, controles da família desde Q3, zero dark patterns |
| Divergência visual entre protótipos futuros | Design system da Q0 é a fonte única; protótipos novos viram tokens, não forks |
