# 🗺️ Índice Completo — Constela Quest Bible

> **Mapa mestre de toda a documentação.** Cada seção decomposta em subseções ao nível de um
> GDD de estúdio, detalhada para que um dev implemente **sem tomar decisões de produto**.
> Construído por 9 leads + crítico de completude (CTO); reorganizado em Partes. Atualizado 2026-07-09.
>
> **Legenda:** ⚠️ = subseção que depende de **decisão do dono**.
> Índice em pt-BR; **cada documento de seção é bilíngue** (pt-BR canônico + espelho EN).

**Cobertura:** 31 seções/apêndices · 979 subseções · 186 decisões em aberto · 189 perguntas ao dono.

## Sumário

**Parte I — Produto & Visão**
- **00** · Visão & Norte
- **01** · Princípios Imutáveis
- **02** · Vocabulário Canônico

**Parte II — O Jogo: Design & UX**
- **03** · O Universo & a Fantasia
- **04** · Personagens & Avatar
- **05** · Sistemas de Jogo
- **06** · Design Pedagógico & BNCC
- **07** · UX, Fluxos & Navegação
- **08** · Onboarding & FTUE do Aluno

**Parte III — Comunidade**
- **09** · Social & Comunidade Segura / Safe Social
- **10** · Professor & Família / Teacher & Family

**Parte IV — Técnico & Segurança**
- **11** · Arquitetura Técnica
- **12** · Segurança, Privacidade & LGPD
- **13** · Acessibilidade & Bem-estar
- **14** · Infraestrutura, Deploy, Backup & Disaster Recovery (SRE/DevOps)

**Parte V — Produção & Operação**
- **15** · Direção de Arte, Áudio & Pipeline de Assets
- **16** · Localização & i18n
- **17** · Telemetria, Métricas & Analytics
- **18** · QA & Estratégia de Testes
- **19** · Live-ops & Config Remota
- **20** · Migração de Dados & Importação de Plataformas Externas
- **21** · Suporte, Sucesso do Cliente & Operação de Escola

**Parte VI — Negócio & Governança**
- **22** · Monetização & Modelo de Negócio / Business Model
- **23** · Roadmap & Fases (Q0–Q6) / Roadmap & Phases
- **24** · Governança da Bible / Bible Governance

**Apêndices**
- **A** · Apêndice A — Glossário / Glossary
- **B** · Apêndice B — Contratos de API & Modelo de Dados / API & Data Contracts
- **C** · Apêndice C — Registro de Decisões (ADR) / Decision Log
- **D** · Apêndice D — Catálogo de Eventos de Telemetria
- **E** · Apêndice E — Wireframes/Mockups de Referência
- **F** · Apêndice F — Checklists Consolidados (Definition of Done)

---

# Parte I — Produto & Visão

## 00 · Visão & Norte
**Objetivo:** Fixar o que o Constela Quest é, para quem, por que existe e a pergunta-guia que arbitra toda decisão de produto, dando ao time um norte único e verificável. Reflete a estrutura real de docs/bible/00-visao-e-norte.md (documento bilíngue PT-BR canônico / EN espelho).

| # | Subseção | Propósito |
|---|----------|-----------|
| 00.1 | Cabeçalho, status & fontes | Bloco de metadados do doc (status de rascunho, fontes: quest/README, quest/05, RELATORIO-2026-07-09, ADR-0001) que ancora rastreabilidade. |
| 00.2 | O que é | Define o produto como jogo educacional 1º–5º ano (6–11) dentro do ecossistema Constela (Hub → Edu + Quest); 'jogo de verdade cujo conteúdo por acaso ensina'. |
| 00.3 | Para quem | Separa os três públicos — jogador (criança), comprador (escola/rede) e apoiadores (professor e família) — e seus papéis. |
| 00.4 | Persona — Miguel, 6 anos (não-leitor) | Criança de 1º ano em tablet compartilhado; reconhece por ícone/cor/som; exige áudio em tudo, ícones grandes, 1 ação por tela. |
| 00.5 | Persona — Sofia, 10 anos (leitora fluente) | Aluna que compara o Quest com jogos que ama; exige profundidade, encanto e progressão que valham o tempo dela. |
| 00.6 | Persona — Profª. Andréa (professora do 3º ano) | Precisa ver aprendizado BNCC num olhar, sem reconfiguração; reusa o Edu; sem expor ranking individual da criança. |
| 00.7 | Persona — Dona Cláudia (mãe/responsável) | Quer segurança e aprendizado da filha; exige privacidade LGPD, zero compras e transparência; nota product-critical não-leitor vs leitor. |
| 00.8 | Por que existe (a promessa) | Transformar o estudo em algo que a criança escolhe fazer; sucesso é a criança querer voltar, não usar por obrigação. |
| 00.9 | A pergunta-guia (o norte) | Fixa o teste de toda decisão: 'Uma criança entraria no Constela Quest mesmo sem ser obrigada?' — se 'não', a decisão está errada. |
| 00.10 | Os 4 pilares | Autonomia, Progresso visível (a Constelação), Vínculo (Cosmo/mundo) e Surpresa — os sustentáculos do 'sim' à pergunta-guia. |
| 00.11 | ⚠️ O norte como métrica ('a criança volta amanhã?') | Régua afetiva de retenção usada como corte de fase no doc 05; alvos quantitativos (D1/D7/D30) e relação com aprendizado ficam a calibrar na Seção 17. |
| 00.12 | O que o Constela Quest NÃO é | Delimita antipadrões: não é sistema escolar gamificado, catálogo de exercícios, não compete no esforço mínimo, sem compras/punição/dark patterns. |
| 00.13 | ⚠️ Ambição de qualidade e a tensão em aberto | Registra a direção do dono por assets profissionais/3D em conflito com a arquitetura DOM/SVG-first; alcance e piso de desempenho a decidir (Seções 04/11/15). |
| 00.14 | ⚠️ Pendências desta seção (do QA) | Lista o que falta calibrar: métrica-norte quantificável + guardrails, critérios de sucesso/'definição de lançamento' e posicionamento vs. incumbentes. |
| 00.15 | Espelho bilíngue PT-BR / EN | Convenção estrutural: seção duplicada em português (canônico) e inglês (equipe internacional); ambas devem ser mantidas em paridade. |

**Perguntas ao dono:**
- Qual a métrica-norte quantificável (alvos D1/D7/D30) e seus guardrails, e como ela se relaciona formalmente com aprendizado e saúde de uso?
- Qual é a 'definição de lançamento' e os critérios objetivos de sucesso do produto?
- Como posicionar o Quest frente aos incumbentes (Matific, Elefante) — diferencial declarado de mercado?
- Qual o alcance da direção de 'assets profissionais/3D' (só avatar? jogo todo?) e como conciliá-la com o piso de desempenho em tablets/Chromebooks baratos?

---

## 01 · Princípios Imutáveis
**Objetivo:** Enumerar os compromissos que não mudam com moda, pressa ou atalho e que toda spec deve respeitar, com governança explícita de alteração por ADR. Reflete a estrutura real de docs/bible/01-principios-imutaveis.md: 18 princípios agrupados A–F (1–16 re-derivam o relatório de estado; 17–18 são acréscimos do QA).

| # | Subseção | Propósito |
|---|----------|-----------|
| 01.1 | Cabeçalho, fontes & origem dos princípios | Metadados e nota de que os princípios 1–16 re-derivam as 16 constraints do relatório e 17–18 são acréscimos da revisão de QA. |
| 01.2 | Governança de mudança | Regra dura: princípios só mudam por novo ADR aprovado pelo dono que referencie o anterior; toda spec deve ser compatível com todos. |
| 01.3 | A1 · Login só com código, sem senha/PIN | Código curto falável (ex. SOL1234) é a credencial exposta; defesa por rate-limit (código,IP) + escopo mínimo do papel aluno; QR é a mesma credencial trocável. |
| 01.4 | A2 · Sem chat livre, nunca | Nenhum campo de texto livre acessível ao aluno; comunicação só por catálogo; única exceção é o nome de exibição sob validação estrita (2–20, só letras). |
| 01.5 | ⚠️ A3 · LGPD Art. 14 — coleta mínima | Sem foto/localização; nada além do que a escola cadastrou no Edu; social opt-in por escola; retenção de telemetria configurável (padrão sugerido 24 meses, a confirmar). |
| 01.6 | A4 · Conta não fica salva ao sair | Token só em memória; boot confirma 'É você, {nome}?'; estado/constelação por perfil, nunca vaza entre contas no tablet compartilhado. |
| 01.7 | A5 · Ranking municipal individual nunca exposto a crianças | Municipal só entre escolas e só no Edu/Hub (adultos); para a criança, sua constelação e ranking de turma que zera toda semana. |
| 01.8 | B6 · Erro nunca pune | Sem perda de moedas/estrelas, sem 'vidas'; XP só cresce; estrela vale a melhor tentativa; teto diário é celebração, não bloqueio. |
| 01.9 | ⚠️ B7 · Sem compras dentro do app | Moedas só se ganham jogando; sem moeda comprável, caixas pagas ou FOMO; escola licencia; passe gratuito (formato exato a confirmar). |
| 01.10 | B8 · Zero dark patterns | Sem manipulação, pressão artificial ou 'vidas' que forcem espera/pagamento. |
| 01.11 | C9 · Narração pt-BR e áudio obrigatório | Toda instrução e falas do Cosmo são faladas em português do Brasil, pois 1º/2º ano ainda não leem com fluência. |
| 01.12 | C10 · A criança escolhe como quer ser chamada | Na 1ª sessão (cerimônia de boas-vindas), por seleção controlada — nunca texto livre. |
| 01.13 | C11 · Acessibilidade não-negociável (6–11) | Áudio em toda instrução, alvos ≥48px, máx. 1 ação primária/tela, navegação por ícone+cor+áudio, reduced-motion, modo daltônico, tempo nunca como critério único. |
| 01.14 | C12 · Vocabulário lúdico fixo | Mapa interno→criança e lista de palavras proibidas (Seção 02) são de cumprimento obrigatório na UI infantil. |
| 01.15 | D13 · Servidor é a autoridade do gabarito | Catálogo entregue ao cliente sem o campo `gabarito`; cliente devolve resposta crua e o backend confere — criança com DevTools não fabrica XP. |
| 01.16 | D14 · Economia auditável | Moedas mudam só via ledger imutável; tentativas/ledger/outbox nunca sobrescritos; regras numéricas não hardcoded (padrão no código + por escola). |
| 01.17 | D15 · Isolamento multi-escola | `escola_id` em toda tabela e rota; token do aluno (papel='aluno') nunca vale no Edu e vice-versa. |
| 01.18 | ⚠️ E16 · Reuso do Edu, zero reconfiguração | Quest reusa identidade do Edu; amizade nunca cruza escolas (teto imutável), mas escopo de lançamento (turma/escola) está aberto; integração Matific/Elefante por PDF/XLSX; identidade constela-play-v7. |
| 01.19 | F17 · Piso de desempenho e alcance | Device-alvo mínimo explícito, orçamento de carga/memória e offline-first onde couber; toda decisão de arte (inclusive 3D) subordina-se a este piso. |
| 01.20 | F18 · Sem anúncios e sem rastreamento de terceiros | Nenhum anúncio nem SDK de rastreamento de terceiros; só telemetria própria, mínima e com finalidade pedagógica/de produto. |
| 01.21 | ⚠️ O que NÃO é princípio (ainda em aberto) | Lista o que aparece nos artefatos mas não está decidido: avatar 3D vs 2D, DOM/SVG-first vs Three.js, resíduo do PIN de figuras, amizade turma vs escola. |
| 01.22 | Espelho bilíngue PT-BR / EN | Convenção estrutural: princípios duplicados em PT (canônico) e EN, mantidos em paridade. |

**Perguntas ao dono:**
- Confirmar o prazo de retenção de telemetria (24 meses?) e o gatilho de anonimização na saída do aluno?
- Qual o formato exato do passe de temporada gratuito (trilha de recompensas, duração, reset)?
- Amizade no lançamento: mesma turma ou mesma escola? Social ligado ou desligado por padrão?
- Avatar definitivo: humanoide 3D (Three.js) ou Cosmo 2D como avatar do jogador?
- Three.js é oficial no núcleo do frontend (reescrevendo o DOM/SVG-first) ou fica restrito ao avatar?
- Autorizar a limpeza dos resíduos textuais do 'PIN de figuras' consolidando o login código-só?

---

## 02 · Vocabulário Canônico
**Objetivo:** Fixar a tradução obrigatória entre os nomes internos (código/banco) e os nomes que a criança vê e ouve, além das palavras proibidas, nomes próprios, tom de voz e o guia de falas do Cosmo. Reflete a estrutura real de docs/bible/02-vocabulario.md (bilíngue; mudar um termo exige ADR).

| # | Subseção | Propósito |
|---|----------|-----------|
| 02.1 | Cabeçalho, fontes & governança do termo | Metadados e regra de que qualquer alteração de termo canônico exige ADR. |
| 02.2 | O princípio das duas línguas | Explica nome interno (código/banco/docs) vs nome que a criança vê/ouve; tabela obrigatória em UI, falas do Cosmo e todo texto infantil. |
| 02.3 | Mapa interno → criança (tabela canônica) | Tradução completa: mundo→Planeta, jornada→Jornada, missao→Missão, desafio→Desafio, progresso→Constelação, streak→Chama do Cosmo, sala→Estudar com um amigo/Corrida, etc. |
| 02.4 | ⚠️ Caso especial — tela-casa (lobby no código) | 'lobby' é palavra proibida na UI e existe só no código; o rótulo infantil da tela-casa ainda não tem nome (proposta na Seção 03). |
| 02.5 | ⚠️ Caso especial — 'Meu astronauta' (perfil) | Guarda-chuva conceitual do perfil que hoje aparece nas telas Vestiário e Carreira; o rótulo 'Meu astronauta' ainda é a confirmar. |
| 02.6 | Abas em produção (Jogar · Vestiário · Carreira) | Rótulos infantis já em produção no topo da tela-casa, registrados como canônicos. |
| 02.7 | Palavras PROIBIDAS na UI infantil | Lista de banidos (party, lobby, matchmaking, squad, ranking global, prova, exercício, tarefa, erro fatal, reprovado) por soarem a escola/competição/tecnologia adulta. |
| 02.8 | Substituições recomendadas | Mapeia proibido→permitido: prova/exercício/tarefa→Missão/Desafio; ranking global→sua Constelação/turma da semana; reprovado/erro→acolhimento ('quase!'). |
| 02.9 | Nomes próprios do universo | Fixa Constela, Constela Quest, Cosmo, Constelação; os nomes próprios dos planetas vivem na Seção 03 e não se traduzem. |
| 02.10 | Tom de voz (Cosmo e UI) | Curto e falado, caloroso e nunca professoral, sem jargão, convite não ordem, erro sempre acolhido. |
| 02.11 | Falas do Cosmo — guia ✓/✗ | Referência única (momento a momento) para UI, narração gravada e a futura IA 'Cosmo explica erros', sempre em pt-BR. |
| 02.12 | Nota — termos de economia e progressão | XP, moedas, estrelas, conquistas e pets têm rótulos lúdicos próprios, detalhados nas Seções 03 e 05. |
| 02.13 | Espelho bilíngue PT-BR / EN | Convenção estrutural: vocabulário duplicado em PT (canônico) e EN, mantidos em paridade. |

**Perguntas ao dono:**
- Qual o rótulo infantil oficial da tela-casa (o 'lobby' do código)?
- Confirmar 'Meu astronauta' como rótulo do perfil/guarda-chuva de Vestiário e Carreira?
- Oficializar os nomes próprios dos 9 planetas (catálogo detalhado na Seção 03)?

---

# Parte II — O Jogo: Design & UX

## 03 · O Universo & a Fantasia
**Objetivo:** Definir a ficção do Constela Quest — o mapa do universo, os 9 planetas-matéria e seus nomes próprios, a narrativa, o papel do Cosmo, a progressão do mundo e o tom — de modo que arte, roteiro e engenharia implementem sem tomar decisões de produto (marcando o que depende do dono). Fontes: quest/03-gamificacao-progressao.md, quest/README.md, apps/quest/src/lobby/materias.ts, Seções 00–02.

| # | Subseção | Propósito |
|---|----------|-----------|
| 03.1 | Cabeçalho, status & fontes | Metadados da seção e ancoragem nas fontes (docs quest, código materias.ts, protótipo constela-play-v7). |
| 03.2 | Premissa da fantasia (o pitch) | Fixa a metáfora-mãe: a criança é um explorador do universo Constela; estudar vira viajar entre planetas ao lado do Cosmo. |
| 03.3 | Mapa do universo — hierarquia canônica | Estrutura Universo → Planeta (matéria) → Jornada (por ano) → Missão → Desafio, espelhando o vocabulário da Seção 02. |
| 03.4 | A Constelação — o mundo pessoal de progresso | Define o mapa estelar do aluno onde cada esforço vira estrela (eu × eu de ontem), a primeira tela de progresso e metáfora central. |
| 03.5 | Catálogo dos 9 planetas — visão geral | Regra de que cada matéria é um planeta com progressão independente e identidade própria (céu, cores, nebulosas, partículas, colecionáveis) vinda do tema JSON. |
| 03.6 | Planeta Numéria — Matemática | Identidade do planeta de Matemática: paleta laranja/vermelho, anéis, partículas de glifos (+ − × ÷ = √ π); tom de desafio numérico. |
| 03.7 | Planeta Palavras — Português | Identidade do planeta de Português: paleta turquesa/azul, partículas de letras e acentos; tom de leitura e histórias. |
| 03.8 | Planeta Biozênia — Ciências | Identidade do planeta de Ciências: paleta roxo/ciano, partículas de bolhas; tom de experimento e natureza. |
| 03.9 | Planeta Terra Nova — Geografia | Identidade do planeta de Geografia: paleta verde/azul com anéis, faíscas; tom de mapas, regiões e território. |
| 03.10 | Planeta Chronos — História | Identidade do planeta de História: paleta dourado/marrom, faíscas quentes; tom de linha do tempo e personagens históricos. |
| 03.11 | Planeta Oxford — Inglês | Identidade do planeta de Inglês: paleta azul, partículas de letras; tom de vocabulário e frases em inglês. |
| 03.12 | Planeta Colorium — Artes | Identidade do planeta de Artes: paleta rosa/roxo, partículas de tinta; tom de cor, forma, música e criação. |
| 03.13 | Planeta Movi — Ed. Física | Identidade do planeta de Ed. Física (sensível): paleta verde; missões de 'desafios ativos' com confirmação do professor + quizzes de regras/saúde. |
| 03.14 | Planeta Raízes — ERER | Identidade do planeta de ERER (sensível): paleta laranja/magenta, partículas de folhas; conteúdo de culturas do Brasil sob curadoria humana. |
| 03.15 | ⚠️ Canonização e tradução dos nomes próprios | Oficializar os 9 nomes (em especial Oxford e Terra Nova, hoje só no código) e a regra de que nomes próprios não se traduzem. |
| 03.16 | ⚠️ Tratamento dos planetas sensíveis (Ed. Física & ERER) | Design próprio, curadoria pedagógica humana (não IA) e revisão de especialista; confirmar entrada em fase posterior (Q5). |
| 03.17 | ⚠️ Enquadramento narrativo & nível de enredo | Decidir se há arco/conflito/vilão macro ou se o universo é cenário de exploração sem enredo central — define quanto roteiro será produzido. |
| 03.18 | ⚠️ Lore do universo & história de origem | Define a história de fundo do universo Constela e do Cosmo e quem a roteiriza; hoje inexistente como texto canônico. |
| 03.19 | Papel do Cosmo na história | Fixa o Cosmo como companheiro-guia que fala, lembra e comemora — máquina de estados com memória curta (recepção, torcida, dica, consolo, festa, descanso), o coração emocional. |
| 03.20 | ⚠️ Fronteira Cosmo × avatar do jogador | Cosmo é hoje guia e não avatar; o papel definitivo do avatar (humanoide 3D vs Cosmo 2D) está aberto e remete à Seção 04. |
| 03.21 | ⚠️ A tela-casa como nave-mãe / porto do universo | Enquadra o 'lobby' como o hub de onde se viaja aos planetas; falta o rótulo infantil canônico (ligação com a Seção 02). |
| 03.22 | A Chama do Cosmo na ficção | Narrativiza o streak como chama viva do Cosmo, com escudo semanal e 'reacender' gentil — nunca culpa, sempre acolhimento. |
| 03.23 | Progressão do mundo — como o universo evolui | Define a evolução ao longo do tempo: temporadas de 6–8 semanas com tema visual novo e desbloqueios que renovam o mundo. |
| 03.24 | Progressão travada por ano escolar | O aluno vê apenas as jornadas do seu ano (± revisão do anterior); a série vem da matrícula, sem configuração manual. |
| 03.25 | ⚠️ Mundo vivo & eventos sazonais | Eventos pontuais (Festa Junina, Dia das Crianças, Halloween, Natal, Férias) que decoram o mapa e trazem colecionáveis limitados; calendário oficial BR a confirmar. |
| 03.26 | Colecionáveis, criaturas & álbum do universo | Criaturas/colecionáveis por planeta que aparecem ao concluir missões, reunidos num álbum na Constelação; completar rende item lendário. |
| 03.27 | Tom & atmosfera do universo | Define a paleta emocional (mágica, acolhedora, encantada, sem 'cara de dever de casa'), ancorada na estética do protótipo constela-play-v7. |
| 03.28 | Guardrails narrativos do universo | O que é sempre verdade na ficção: sem violência/morte, erro sempre acolhido, sem competição tóxica, sem jargão adulto — coerência com os Princípios Imutáveis. |
| 03.29 | ⚠️ Escopo de conteúdo no lançamento | Decidir entre 1 planeta profundo (ex.: Matemática) e 9 planetas rasos — define a densidade de conteúdo/arte a produzir primeiro. |
| 03.30 | Âncoras de arte & referências cruzadas | Aponta o formato do tema JSON (SUBJECTS/SCENES do protótipo) e remete a Seção 04 (personagens/avatar) e Seção 15 (arte, áudio, assets). |

**Perguntas ao dono:**
- Oficializar os nomes próprios dos 9 planetas, em especial Oxford e Terra Nova (hoje só placeholders no código), e confirmar a regra de não-tradução?
- Existe um arco narrativo/enredo maior (vilão, conflito, missão-macro) ou o universo é um cenário de exploração sem enredo central?
- Deve haver uma lore/história de origem escrita do universo Constela e do Cosmo — e quem produz o roteiro?
- Qual o papel definitivo do avatar do jogador frente ao Cosmo (humanoide 3D vs Cosmo 2D)?
- Qual o rótulo infantil da tela-casa/nave-mãe (o 'lobby')?
- Escopo de conteúdo no lançamento: 1 planeta profundo ou 9 rasos?
- Confirmar que Ed. Física (Movi) e ERER (Raízes) entram só na Q5 com curadoria própria?
- Qual o calendário oficial de eventos sazonais para o lançamento no Brasil?

---

## 04 · Personagens & Avatar
**Objetivo:** Definir o elenco completo (Cosmo, personagens-base, secundários) e o sistema de avatar do jogador — identidade visual, customização por slots, itens especiais, animação e física — em nível de spec que permita a um dev implementar sem tomar decisões de produto. A escolha fundadora entre avatar humanoide 3D e Cosmo 2D é explicitamente marcada como em aberto e organiza toda a seção.

| # | Subseção | Propósito |
|---|----------|-----------|
| 04.1 | Visão geral do elenco | Mapa de todos os personagens do universo (avatar do jogador, Cosmo, base, secundários) e o papel de cada um. |
| 04.2 | ⚠️ A decisão fundadora do avatar — humanoide 3D vs Cosmo 2D | Registra a escolha em aberto que define o restante da seção, com o histórico das Revisões 3/4 e o conflito arquitetural. |
| 04.3 | Cosmo — bíblia do personagem | Personalidade, biografia, papel narrativo e limites (companheiro-guia que fala e dá dicas, não chatbot). |
| 04.4 | Cosmo — máquina de estados de humor | Os estados recepção/torcida/dica/consolo/festa/descanso, seus gatilhos e comportamentos, como especificação de personagem. |
| 04.5 | Cosmo — especificação visual e técnica (SVG vivo) | Rosto, olhos, expressões, física de mola e renderização 2D atual do mascote. |
| 04.6 | ⚠️ Cosmo customizável — sistema órfão | Slots do Cosmo (rosto/chapéu/costas/mão/pet) que renderizam sem UI: decidir manter+construir UI ou remover. |
| 04.7 | ⚠️ Os 6 personagens-base (roster) | O conjunto de presets iniciais oferecidos na cerimônia; identidade, ordem e disponibilidade de cada um. |
| 04.8 | Ficha-modelo de personagem-base | Template repetível por personagem: nome, traços, paleta, voz/áudio, variações de customização inicial. |
| 04.9 | Avatar humanoide 3D — especificação técnica | Stack (Three.js/R3F/drei), geração procedural, lazy-load e requisitos de renderização do boneco. |
| 04.10 | Anatomia e rig do boneco | Estrutura de camadas trocáveis (pele, cabelo, camiseta, calça, tênis, costas, mão) e pontos de ancoragem. |
| 04.11 | Sistema de customização — modelo de slots | Como slots equipados vivem no JSON avatar do perfil e como o vestiário monta o personagem. |
| 04.12 | Catálogo canônico de slots e categorias | Definição fechada de cada categoria do vestiário (Pele, Cabelo, Camiseta, Calça, Tênis, Acessórios, Pets, Itens Especiais) e regras de exclusividade. |
| 04.13 | Itens especiais — visão | Categoria aspiracional (skate voador, varinha, asas/mochila, pets) e seu papel de desejo/status. |
| 04.14 | Skate Voador — invocação cinematográfica | Spec da animação de invocação (constelação brilha → silhueta → materializa → voa aos pés → Cosmo pula). |
| 04.15 | Pets — comportamento e companhia | Como o pet acompanha no lobby, comemora junto e funciona como item raro máximo. |
| 04.16 | Física do personagem | Física de cutucada/mola no toque, rosto vivo e resposta a interação, com parâmetros implementáveis. |
| 04.17 | Sistema de animação | Catálogo de animações (idle, comemoração, vitória, dança, reações) e quando cada uma dispara. |
| 04.18 | Estados de 'vida' do personagem | Micro-comportamentos de vida (respirar, piscar, reagir ao toque/ocioso) que dão presença ao avatar. |
| 04.19 | Cerimônia da 1ª vez — montar o personagem | Fluxo de criação inicial (nome de exibição + cabelo + camiseta) e sua ligação ao login sem senha. |
| 04.20 | Contrato de dados do avatar | Schema do JSON avatar em quest_perfis, whitelist estrita de valores e validação servidor-lado. |
| 04.21 | Reconciliação do contrato legado | Limpeza dos resíduos do avatar antigo (trocarAvatar, coresDoTraje, AstronautaConhecido) e do bug da conquista 'Estilista espacial'. |
| 04.22 | Personagens secundários por planeta | NPCs ambientais definidos no JSON 'tema' de cada mundo e como o catálogo os fornece. |
| 04.23 | Representação social do avatar | Como o avatar aparece a terceiros (apelido+avatar fora da turma; snapshot de participantes em salas). |
| 04.24 | ⚠️ Orçamento de desempenho e fallback | Custo de carga/memória do avatar no device-alvo mínimo e a estratégia de degradação (ex.: fallback 2D). |
| 04.25 | ⚠️ Pipeline de produção de assets do personagem | Quem cria os GLB e camadas trocáveis, formato de entrega e versionamento dos assets. |
| 04.26 | Acessibilidade do personagem/avatar | reduced-motion nas animações, modo daltônico nas cores de customização e áudio das telas de vestiário. |
| 04.27 | Consistência do avatar entre telas | Garantia de que o mesmo avatar aparece coerente em lobby, missão, recompensa, corrida e social. |

**Perguntas ao dono:**
- Avatar definitivo do jogador: humanoide 3D (Three.js/R3F, já em código) OU Cosmo 2D como avatar? Dois sistemas coexistem hoje e precisam de decisão única.
- Se o avatar for 3D no núcleo, isso oficializa Three.js contra a arquitetura DOM/SVG-first do doc 01? Qual o piso de desempenho e o fallback 2D no device-alvo mínimo (tablet/Chromebook modesto)?
- Pipeline de arte: quem produz os GLB, as camadas trocáveis (cabelo, roupa, etc.) e os pets? Áudios/ilustrações serão gravados profissionalmente ou seguem TTS/SVG?
- O sistema 'Cosmo customizável' (rosto/chapéu/costas/mão/pet que renderizam sem UI) deve ser mantido e ganhar UI, ou removido como código órfão?
- Quais são exatamente os 6 personagens-base (nomes, fichas, paletas, vozes) que a criança escolhe na cerimônia da 1ª vez?
- As preferências 'musica' e 'reduzir_animacoes' do perfil ganham função/UI real ou saem do modelo?

---

## 05 · Sistemas de Jogo
**Objetivo:** Especificar todos os sistemas jogáveis — core loop, economia de 3 moedas, progressão/níveis/curva, dificuldade adaptativa, Chama do Cosmo, mecânicas de desafio, chefões e recompensas — com fórmulas, casos de borda e autoridade do servidor, de forma que um dev implemente deterministicamente. Todas as regras numéricas são padrões configuráveis (namespace quest.*), nunca hardcoded.

| # | Subseção | Propósito |
|---|----------|-----------|
| 05.1 | O core loop | O laço central estudar → ganhar → evoluir e como cada volta termina com algo novo (nunca sai de mãos vazias). |
| 05.2 | Diagrama de estados de uma sessão | Do login à despedida: máquina de estados da sessão de jogo e transições entre lobby/missão/recompensa. |
| 05.3 | Anatomia de uma missão | Como o MissaoPlayer orquestra a sequência de desafios, coleta respostas e finaliza a tentativa. |
| 05.4 | Economia de 3 moedas — visão e justificativa | XP (progresso), moedas (compra), estrelas (maestria) e por que separar as três evita o erro da moeda única. |
| 05.5 | XP — regras de ganho | Fórmulas: 4×dificuldade por acerto, bônus +50% de primeira sem dica, xp_base×multiplicador de estrelas. |
| 05.6 | XP — decaimento de repetição | Rejogar missão concluída rende 50% na 2ª vez e 25% da 3ª em diante (revisão vale, farm não). |
| 05.7 | XP — teto diário como celebração | Teto diário (padrão 600) que comemora em vez de bloquear, protegendo contra uso compulsivo. |
| 05.8 | Curva de níveis | Fórmula 80+20×n, ritmo alvo de subida e legibilidade da curva para a criança. |
| 05.9 | Recompensa de subir de nível | Toda subida entrega algo concreto (moedas + item/desbloqueio) com celebração em tela cheia do Cosmo. |
| 05.10 | Moedas — ganho e ledger imutável | Origens (missão/diária/evento) e registro exclusivo via quest_transacoes_moedas; saldo é cache recomputável. |
| 05.11 | Moedas — gasto e regras | Onde se gastam (loja de cosméticos) e a proibição de compra real, caixa paga ou moeda comprável. |
| 05.12 | Estrelas — maestria por missão | Faixas 0–3 (concluiu / ≥80% / 100%), vale a melhor tentativa histórica, estrela nunca é perdida. |
| 05.13 | Estrelas como chaves | Estrelas destravam chefão/jornada e criam razão para revisitar missões (revisão espaçada disfarçada). |
| 05.14 | Balanceamento e configuração sem deploy | Todos os números vivem em configuracoes (quest.*) com padrão no código e override por escola. |
| 05.15 | Progressão do universo (planetas/jornadas/mapa) | Trilha visível de missões, chefão por estrelas e independência de progressão entre planetas. |
| 05.16 | Desbloqueio por ano escolar | A série vem da matrícula (turmas.ano_escolar); aluno vê só jornadas do seu ano + revisão do anterior. |
| 05.17 | Dificuldade adaptativa v1 (heurística) | Janela móvel de 10 respostas por mundo, sobe ≥85% / desce ≤40%, silenciosa; nível 1–5 começa em 2. |
| 05.18 | Seleção de desafios na missão | A missão sorteia desafios centrados no nível adaptativo do aluno (±1) por mundo. |
| 05.19 | Dificuldade adaptativa v2 (IA por habilidade) | Fase futura: estimativa de domínio por habilidade BNCC alimentando a seleção, com decisões auditáveis. |
| 05.20 | A Chama do Cosmo (sequência de dias) | Conta dias com ≥1 missão concluída; regra e semântica afetiva do streak. |
| 05.21 | ⚠️ Escudo semanal e regra de fim de semana | 1 falta/semana não apaga a chama (renova segunda); fim de semana conta se jogar mas não quebra. |
| 05.22 | Marcos da Chama e reacender | Marcos (3/7/14/30/60/100), colecionável do dia 100 e 'reacender' gentil que devolve 25% dos dias. |
| 05.23 | Ritmo de retorno | Cadências diária/semanal/temporada/pontual e o que cada uma oferece para justificar 'entrar hoje'. |
| 05.24 | Missões diárias e semanais | Geração no 1º acesso do dia (3 diárias + 2 semanais), viés para habilidades fracas, progresso e resgate. |
| 05.25 | Presente de login | Trilha de 7 dias com moedas/item pequeno como recompensa de retorno. |
| 05.26 | Registry de mecânicas (contrato plugável) | O contrato MecanicaProps/RespostaDesafio: cada mecânica recebe um desafio e devolve uma resposta, sem saber de XP/rede. |
| 05.27 | Mecânica: Quiz | Spec de interação, schema de corpo, gabarito server-side e requisitos de acessibilidade. |
| 05.28 | Mecânica: Arrastar e soltar | Spec com @dnd-kit (touch-first), schema de corpo e validação no servidor. |
| 05.29 | Mecânica: Ligar colunas | Spec de pares, schema de corpo, gabarito e acessibilidade. |
| 05.30 | Mecânica: Memória | Spec de pares/cartas, schema de corpo, condição de acerto e acessibilidade. |
| 05.31 | Mecânica: Completar | Spec de lacunas/completar enunciado, schema de corpo e validação. |
| 05.32 | Mecânica: Sequência | Spec de ordenação/sequência, schema de corpo e gabarito. |
| 05.33 | Mecânica: Caça-palavras | Spec de grade e palavras, schema de corpo e validação server-side. |
| 05.34 | Schema de conteúdo por mecânica | Formato do campo 'corpo' JSON por mecânica e a garantia de que 'gabarito' nunca vai ao cliente. |
| 05.35 | Autoridade do servidor sobre o gabarito | Cliente envia resposta crua, backend confere e devolve resultado/recompensa; criança com DevTools não fabrica XP. |
| 05.36 | Chefões (boss missions) | Desbloqueio por estrelas, formato da missão-chefão e conclusão da jornada com animação da constelação. |
| 05.37 | Motor de recompensas e tela de celebração | Cálculo de recompensas pós-missão (XP/moedas/estrelas/itens) e a celebração proporcional à raridade. |
| 05.38 | Colecionáveis e álbum por planeta | Drop aleatório de colecionáveis ao concluir missões; álbum na constelação e item lendário ao completar. |
| 05.39 | Conquistas (motor data-driven) | Avaliador genérico de critérios; categorias exploração/maestria/constância/social/secretas por dados, não código. |
| 05.40 | ⚠️ Passe de temporada gratuito | Trilha única de recompensas por jogar; formato exato do passe a confirmar. |
| 05.41 | Loja e rotação semanal | Rotação de 4–6 itens + seção fixa, preços calibrados, escassez honesta e proibição de dark patterns. |
| 05.42 | Modos sociais — regras de jogo | Regras de ouro de coop/corrida/pintura/x1 (derrota nunca custa nada); arquitetura detalhada na seção Social. |
| 05.43 | Motor de corrida único | Uma mecânica (acertou → avança) com 3 skins (bichinhos/espacial/trilha) definidas por JSON de tema. |
| 05.44 | Telemetria de jogo | O que quest_tentativas grava por missão/desafio de forma imutável, base de professor, família e agregados. |
| 05.45 | Anti-farm e anti-abuso | Rate limit por perfil nas rotas de jogo e decaimento de repetição contra farm. |
| 05.46 | Offline e fila de tentativas | Tentativas append-only em IndexedDB, sync ao reconectar, flag origem-offline e conferência do gabarito no sync. |
| 05.47 | ⚠️ Escopo de conteúdo do lançamento | Definir 1 planeta profundo vs 9 rasos, o que dimensiona a curva e a densidade de missões do MVP. |

**Perguntas ao dono:**
- Monetização: confirmar passe 100% gratuito e zero compras in-app em TODAS as fases, permanentemente?
- Qual o formato exato do passe de temporada (níveis, trilha de recompensas, XP do passe)?
- Escopo do conteúdo de lançamento: 1 planeta profundo (Matemática) vs 9 planetas rasos — impacta a curva e a régua de progressão?
- Confirmar os valores-padrão iniciais da economia (XP base, teto diário 600, curva 80+20n, preços da loja) ou tratá-los como proposta a calibrar?
- Fim de semana quebra a Chama por padrão (é configurável por escola) — qual é o padrão global de fábrica?

---

## 06 · Design Pedagógico & BNCC
**Objetivo:** Definir como o currículo BNCC se converte em conteúdo jogável, a taxonomia do catálogo (mundos → jornadas → missões → desafios), o pipeline e a autoria de conteúdo, a dificuldade pedagógica e o mapa de habilidades — de modo que designers de conteúdo e devs produzam e ingiram material alinhado sem tomar decisões de produto. O conteúdo é o gargalo declarado do projeto e esta seção o organiza.

| # | Subseção | Propósito |
|---|----------|-----------|
| 06.1 | Filosofia pedagógica | Um jogo que por acaso ensina; celebra esforço e evolução, nunca pune erro, sem 'cara de dever de casa'. |
| 06.2 | Alinhamento à BNCC — modelo | Como códigos de habilidade BNCC (ex.: EF02MA05) são a chave que liga conteúdo, telemetria e painel do professor. |
| 06.3 | Taxonomia do catálogo | A hierarquia mundos → jornadas → missões → desafios e o mapeamento interno→criança (Planeta/Jornada/Missão/Desafio). |
| 06.4 | Planeta (mundo) — definição pedagógica | Cada disciplina como um planeta; campos do catálogo (slug, tema, ordem) e mapeamento à matéria escolar. |
| 06.5 | Os 9 planetas-matéria | Numéria, Palavras, Biozênia, Terra Nova, Chronos, Oxford, Colorium, Movi, Raízes — identidade e disciplina de cada. |
| 06.6 | Jornada — unidade curricular por ano | Estrutura da jornada (ano_escolar, ordem, lista bncc, estrelas_chefao) como recorte curricular sequenciado. |
| 06.7 | Missão — unidade jogável | Campos da missão (tipo normal/chefão/evento, xp_base, config, versão, status) e sua semântica pedagógica. |
| 06.8 | Desafio — item avaliativo | Campos do desafio (mecânica, dificuldade 1–5, bncc_codigo, corpo, gabarito, dica, explicacao) como unidade de aprendizagem. |
| 06.9 | Mapa de habilidades BNCC (skill map) | Estrutura do inventário de habilidades por ano/disciplina que o catálogo precisa cobrir. |
| 06.10 | Matriz de cobertura curricular | Grade ano × disciplina × habilidade para verificar lacunas e planejar produção de conteúdo. |
| 06.11 | ⚠️ Dificuldade pedagógica (1–5) | Rubrica e critérios de calibração da dificuldade de cada desafio, definidos pelo autor pedagógico. |
| 06.12 | Dificuldade pedagógica × adaptativa | Como o rótulo estático 1–5 do desafio alimenta o nível adaptativo dinâmico do aluno (seção 05). |
| 06.13 | Progressão pedagógica dentro da jornada | Regras de sequenciamento das missões para construir habilidade de forma cumulativa. |
| 06.14 | Revisão espaçada disfarçada | Como o chefão por estrelas força revisitar missões antigas, produzindo revisão espaçada como jogo. |
| 06.15 | Formato de conteúdo (JSON versionado) | Especificação do formato dos seeds JSON e o versionamento (editar missão publicada gera nova versão). |
| 06.16 | ⚠️ Interface/estúdio de autoria | Por onde o conteúdo é cadastrado e publicado — CRUD admin, estúdio próprio ou import — ainda indefinido. |
| 06.17 | Fluxo de publicação e versionamento | Ciclo rascunho → revisão → publicada → arquivada e como tentativas guardam a versão jogada. |
| 06.18 | Seeds iniciais (pasta conteudo/) | Estrutura de arquivos por planeta/ano em backend/app/quest/conteudo/ (hoje vazia) e como são semeados. |
| 06.19 | ⚠️ Escopo do conteúdo de lançamento | Decidir 1 planeta profundo vs 9 rasos — define o volume de missões e a estratégia de produção do MVP. |
| 06.20 | Autoria assistida por IA | Gerador de desafios que SEMPRE entra como rascunho para revisão do professor/admin; IA nunca publica direto. |
| 06.21 | Escrita para não-leitores | Regras de linguagem e áudio obrigatório dos enunciados para alunos de 1º/2º ano que não leem com fluência. |
| 06.22 | Dicas e explicações pedagógicas | Autoria dos campos dica e explicacao por desafio, em linguagem de criança, acionados pelo Cosmo. |
| 06.23 | Detecção de erros comuns (mal-entendidos) | Como as alternativas erradas mais escolhidas viram 'ouro pedagógico' que revela o mal-entendido ao professor. |
| 06.24 | Agregação de domínio por habilidade | Como quest_habilidades calcula domínio 0–100 (média móvel) por (perfil, bncc_codigo) a partir das tentativas. |
| 06.25 | Mapa de calor turma × habilidade | Especificação de dados do painel do professor (domínio por habilidade, quem precisa de reforço). |
| 06.26 | Missões diárias com viés pedagógico | Regra de sorteio com viés para habilidades/mundos fracos, transformando reforço em rotina de jogo. |
| 06.27 | ⚠️ Educação Física — desafios ativos | Design próprio (vídeo curto + tarefa física + confirmação do professor); entrada e curadoria a confirmar. |
| 06.28 | ⚠️ ERER — conteúdo sensível | Curadoria humana por especialista (não IA) e revisão antes de publicar; fluxo e responsável a definir. |
| 06.29 | Governança e papéis de conteúdo | Catálogo global mantido pelo admin is_global; quem aprova, publica e ativa recursos por escola. |
| 06.30 | ⚠️ Conexão com o software de matérias+questões futuro | Como o catálogo se integra à plataforma de ensino própria do dono — integração nativa a definir. |
| 06.31 | Métricas de qualidade do conteúdo | Indicadores (taxa de erro por desafio, cobertura BNCC, revisão) para curadoria contínua do catálogo. |
| 06.32 | Convenções e localização | pt-BR obrigatório, convenção de ano_escolar herdada de turmas e nomes próprios não traduzíveis dos planetas. |

**Perguntas ao dono:**
- Por qual interface o catálogo pedagógico é cadastrado e publicado (estúdio de autoria próprio, admin do Edu, import JSON)?
- Como se conecta ao 'software de matérias+questões' futuro do dono — integração nativa, importação, ou fonte única de verdade?
- Escopo do conteúdo de lançamento: 1 planeta profundo (Matemática, 5 anos) vs 9 planetas rasos?
- Educação Física e ERER: confirmar entrada só na fase Q5, com design/curadoria próprios?
- Quem é o autor/responsável pedagógico que produz e valida o conteúdo BNCC e a rubrica de dificuldade (1–5)?
- ERER exige curadoria humana por especialista antes de publicar — quem é esse especialista e qual o fluxo de aprovação?

---

## 07 · UX, Fluxos & Navegação
**Objetivo:** Definir a arquitetura de informação, o inventário completo de telas, o grafo de navegação e o contrato transversal de estados (vazio/carregando/erro/offline/sem-permissão) que qualquer tela deve implementar, para que um dev construa a experiência sem inventar produto. Complementa a Seção 05 (Sistemas de Jogo), 13 (Acessibilidade) e 15 (Arte & Áudio), reusando o vocabulário canônico da Seção 02.

| # | Subseção | Propósito |
|---|----------|-----------|
| 07.1 | Cabeçalho, status & fontes | Bloco de metadados (status de rascunho; fontes: quest/01, quest/03, RELATORIO-2026-07-09, protótipo constela-play-v7) que ancora rastreabilidade. |
| 07.2 | Objetivo, escopo e não-escopo da seção | Delimita o que é UX/navegação aqui (telas, fluxos, estados) e o que vive em outras seções (regras de jogo em 05, arte em 15, acessibilidade em 13). |
| 07.3 | Princípios de UX infantil (derivados) | Re-deriva de 00/01/13 as regras de ouro que governam toda tela: no máximo 1 ação primária por tela, ícone+cor+áudio sempre juntos, alvo de toque ≥48px. |
| 07.4 | Arquitetura de informação — mapa conceitual | Hierarquia mestra Boot→Sessão→Tela-casa→(Jogar/Vestiário/Carreira)→Planeta→Jornada→Missão→Recompensa, com profundidade máxima e caminho sempre-de-volta. |
| 07.5 | ⚠️ Modelo de sessão como máquina de estados | Documenta o estado atual (sessão sem router; estados boot/quem/entrando/cerimônia/tela-casa/jogo) e o contrato de transição entre eles. |
| 07.6 | Inventário completo de telas — índice mestre | Catálogo canônico de todas as telas com id, nome interno, rótulo infantil (Seção 02), dono dos dados (endpoint) e pré-condições de acesso. |
| 07.7 | Tela: Boot / Splash offline-first | Primeira renderização do shell PWA sem rede; decide entre 'Quem vai jogar?' e login novo; nunca tela branca. |
| 07.8 | Tela: 'Quem vai jogar?' (perfis do aparelho) | Seleção em 1 toque dos astronautas que já entraram no tablet compartilhado; entrada rápida sem redigitar código. |
| 07.9 | Tela: Entrar por código / 'Sou eu!' | Fluxo de 2 etapas (digitar código falável tipo SOL1234 → confirmar 'Sou eu!'), sem senha/PIN, com áudio das letras. |
| 07.10 | Tela: Entrar por QR (câmera / deep-link ?qr=) | Login pela leitura do cartão via câmera ou abertura por URL ?qr=; credencial equivalente ao código. |
| 07.11 | Tela: Confirmação 'É você, {nome}?' | Guarda obrigatória na retomada de sessão para o tablet compartilhado nunca herdar a conta do turno anterior (Princípio A4). |
| 07.12 | Tela: Cerimônia de 1ª vez | Fluxo de estreia (escolher personagem → apelido → festa) referenciado em detalhe pela Seção 08; aqui entra só como nó de navegação. |
| 07.13 | ⚠️ Tela-casa (aba Jogar) | Céu tocável, Cosmo companheiro e planetas-matéria ambientados; hub de retorno; falta o rótulo infantil oficial ('lobby' é palavra proibida). |
| 07.14 | Tela: Vestiário (aba) | Customização do avatar (9 categorias), inventário e invocação do skate; entrada da economia cosmética. |
| 07.15 | Tela: Carreira (aba) | Stats, conquistas derivadas e 'Minhas aventuras'; hoje parcialmente vazia — âncora do estado-vazio 7.33. |
| 07.16 | Tela: Mapa do Planeta (jornadas) | Trilha visível de jornadas do ano escolar do aluno, com bloqueios/desbloqueios por estrelas e chefão. |
| 07.17 | Tela: Jornada (trilha de missões) | Sequência de missões ●─●─○ dentro de uma jornada, indicando progresso, próxima ação e chefão. |
| 07.18 | Tela: MissãoPlayer (host de mecânicas) | Orquestrador que carrega o plugin de mecânica, apresenta desafios sem gabarito e coleta respostas; contrato com a Seção 05. |
| 07.19 | Tela: Recompensa / celebração pós-missão | Sequência de fecho de missão (XP/estrelas/moedas/item) em tela cheia; garante 'nunca sair de mãos vazias'. |
| 07.20 | Tela: Loja & Inventário | Vitrine cosmética com rotação semanal e seção fixa; compra só com moedas ganhas; sem dinheiro real. |
| 07.21 | Tela: Constelação (progresso pessoal) | Mapa estelar eu×eu-de-ontem; primeira tela de progresso, nunca ranking; álbum de colecionáveis. |
| 07.22 | Tela: Tarefas / Diárias | Presente de login, 3 diárias sorteadas e semanais; ponto de resgate e leitura da Chama do Cosmo. |
| 07.23 | Tela: Social (amigos, convites, salas) | Lista de amigos da escola, convites e entrada nos modos ao vivo ('Estudar com um amigo'/'Corrida'); exige rede. |
| 07.24 | Telas de sistema (preferências, sair, ajuda) | Configurações permitidas ao aluno (áudio/música/reduzir-animações), sair com despedida do Cosmo e ajuda por áudio. |
| 07.25 | Grafo / mapa de navegação | Enumera arestas permitidas entre telas, transições legais, e proíbe becos sem saída — sempre há caminho para a tela-casa. |
| 07.26 | ⚠️ Roteamento & deep-links | Esquema de rotas/URLs: start_url do PWA, ?qr= de login, retomar missão, e link do Portal da Família — confirmar se vira router real. |
| 07.27 | Botão Voltar, gestos e âncora física | Comportamento do back do Android/Chromebook, swipe e garantia de rota de fuga para a tela-casa em qualquer profundidade. |
| 07.28 | Transições e animações de tela | Catálogo de transições (durações, curvas, entra/sai) e o obrigatório fallback sob prefers-reduced-motion. |
| 07.29 | Orquestração de overlays, modais e toasts | Regras de camadas (z-index), no máximo 1 modal por vez, foco preso no modal e fila de toasts não-bloqueantes. |
| 07.30 | ⚠️ Overlay exemplar: invocação do skate | Caso de referência detalhado de overlay sobre o Vestiário (abrir/fechar, foco, áudio, reversibilidade) reutilizável por outros itens. |
| 07.31 | Contrato transversal de ESTADOS de tela | Matriz obrigatória (vazio/carregando/erro/offline/sem-permissão) que toda tela declara, com visual + áudio + ação de saída. |
| 07.32 | Estado: Carregando | Skeletons, presença do Cosmo, áudio de espera e limites de tempo antes de escalar para erro; nunca spinner mudo e infinito. |
| 07.33 | Estado: Vazio | Padrão de tela-vazia acolhedora (ex.: 'Minhas aventuras' sem histórico) com ilustração, fala do Cosmo e ação de primeiro passo. |
| 07.34 | Estado: Erro (rede/servidor/gabarito) | Mensagens acolhedoras sem culpa, retry automático/manual e recuperação; cobre o catch silencioso que hoje zera personagens na cerimônia. |
| 07.35 | Estado: Offline | Banner de sinal, o que funciona (jornada em cache) vs. o que exige rede (social), fila de tentativas e reconciliação no reconectar. |
| 07.36 | Estado: Sem permissão | Social desligado pela escola/família, horário bloqueado, ou aluno arquivado ('cartão descansando') — nunca 'código errado' que culpe a criança. |
| 07.37 | Hierarquia de foco, teclado e switch | Ordem de foco por tela, navegação por teclado do Chromebook e leitores de tela/switch; ponte para a Seção 13. |
| 07.38 | Layout responsivo (tablet/celular/Chromebook) | Breakpoints, tablet-paisagem vs celular-retrato, safe areas, bloqueio/adaptação de orientação e densidade de toque. |
| 07.39 | Áudio como camada de navegação | Narração automática ao entrar em cada tela/estado, botão 'repetir', e o que o Cosmo fala em cada transição (público não-leitor). |
| 07.40 | Feedback dos controles (toque/hover/pressed/disabled) | Estados visuais e sonoros dos botões e alvos, incluindo desabilitado explicado por áudio em vez de silêncio. |
| 07.41 | Wayfinding & consistência (HUD persistente) | Posição fixa do Cosmo, botão voltar e HUD de moedas/estrelas/nível para orientação constante entre telas. |
| 07.42 | i18n de layout e navegação | Tolerância a expansão de texto PT→EN, ícones culturalmente neutros e preparo estrutural para futuros idiomas; ponte para a Seção 16. |
| 07.43 | Observabilidade de UX | Eventos de telemetria por transição de tela, funil de navegação, tempo por tela e taxa de saída; ponte para a Seção 17. |
| 07.44 | Estratégia de testes de UX & navegação | E2E dos fluxos críticos, snapshots por estado da matriz 7.31, e testes de reduced-motion, offline e tablet compartilhado; ponte para a Seção 18. |
| 07.45 | ⚠️ Decisões em aberto (UX) | Consolida pendências: router vs máquina de estados, rótulo da tela-casa, esquema de deep-link, skate como overlay ou tela, device-alvo de animação. |
| 07.46 | Espelho bilíngue PT-BR / EN | Convenção estrutural: seção duplicada em português (canônico) e inglês (equipe internacional), mantidas em paridade. |

**Perguntas ao dono:**
- Adotamos um router real com deep-links (URLs para ?qr=, retomar missão, Portal da Família) ou mantemos a máquina de estados de sessão atual sem rotas navegáveis?
- Qual é o rótulo infantil oficial da tela-casa, já que 'lobby' é palavra proibida na UI e ainda não há nome canônico?
- A invocação do skate (e futuros itens do vestiário) deve ser um overlay sobre o Vestiário ou uma tela própria dedicada?
- Confirmar o esquema de deep-link do login por QR (?qr=) e quando/como o Portal da Família entra como rota navegável?
- Qual o device-alvo mínimo (tablet/Chromebook baratos) para calibrar o orçamento de transições e animações e fixar o piso de desempenho?

---

## 08 · Onboarding & FTUE do Aluno
**Objetivo:** Especificar o primeiro loop guiado da criança — do cartão à 1ª recompensa — de forma que encante antes de instruir, ative o hábito e nunca puna, deixando explícita a relação entre a cerimônia de avatar e o tutorial. Detalha ganchos de retorno, aha-moment, medição de ativação e casos de retomada/pular, e referencia (sem detalhar) o FTUE de professor e família da Seção 10.

| # | Subseção | Propósito |
|---|----------|-----------|
| 08.1 | Cabeçalho, status & fontes | Metadados e fontes (quest/03, quest/04, RELATORIO-2026-07-09, Seções 07/02) que ancoram rastreabilidade. |
| 08.2 | Objetivo e filosofia do FTUE | Fixa a doutrina 'encanto antes de instrução' e a pergunta-guia ('entraria sem ser obrigada?') como régua do primeiro contato. |
| 08.3 | ⚠️ Definição de ativação & hipótese de aha-moment | Define o que conta como 'aluno ativado' e a hipótese do momento de encanto a validar; alvos ainda a calibrar. |
| 08.4 | Contexto real da 1ª sessão | Sala de aula com professor conduzindo, tablet compartilhado, wifi instável e roteiro da 1ª aula — restrições que moldam o desenho. |
| 08.5 | Visão macro do primeiro loop guiado | Mapa de alto nível boot→login→cerimônia→1ª missão→1ª recompensa→gancho de volta, com o único caminho feliz. |
| 08.6 | Máquina de estados do onboarding | Enumera passos, ordem, gates (o que trava/libera) e como o estado é persistido no servidor para sobreviver a interrupções. |
| 08.7 | Passo 0: Antes do app (cartão & roteiro do professor) | Pré-condição física: cartão/QR gerado e roteiro da 1ª aula; referencia o FTUE do professor na Seção 10. |
| 08.8 | Passo 1: Primeiro login | Entrada por código/QR sem conta prévia; reaproveita as telas 7.9/7.10; reconhece o aluno pela matrícula do Edu. |
| 08.9 | Passo 2: Cerimônia — criar o avatar | Escolha do personagem/traje e a relação explícita entre a cerimônia e o tutorial (a cerimônia É o primeiro tutorial de toque). |
| 08.10 | ⚠️ Passo 3: 'Como você quer ser chamada?' | Apelido por seleção/digitação validada (2–20, só letras), narrado; nunca texto livre; o nome passa a reger todas as falas. |
| 08.11 | Passo 4: A festa de boas-vindas | Primeira recompensa emocional em tela cheia que fecha a cerimônia e entrega a sensação de pertencimento. |
| 08.12 | Primeiro contato com o Cosmo | Apresentação do companheiro (voz, humor, promessa afetiva) como guia — não avatar — seguindo o guia de falas da Seção 02. |
| 08.13 | Gate de áudio & permissões | Destravar autoplay de som no 1º toque (política de navegador), sem pedir microfone/câmera exceto QR; áudio é obrigatório. |
| 08.14 | Caminho até a 1ª missão | Como o jogo aponta a única próxima ação (apontar planeta→jornada→missão de estreia) sem sobrecarregar de escolhas. |
| 08.15 | ⚠️ Desenho da 1ª missão (missão de estreia) | Missão-tutorial curada: mecânica introdutória simples, dificuldade baixa e desenho onde é impossível 'falhar'. |
| 08.16 | Ensino de mecânica embutido (aprender-fazendo) | Introdução da mecânica por demonstração do Cosmo e ação, sem muro de texto; cada mecânica declara seu micro-tutorial. |
| 08.17 | A 1ª recompensa | Entrega concreta (XP/estrela/moeda/item) com celebração proporcional; consolida 'nunca sai de mãos vazias'. |
| 08.18 | Fechamento e despedida da 1ª sessão | Encerramento com o Cosmo ('até amanhã, cuido da sua nave') que planta o gancho de retorno e evita término abrupto. |
| 08.19 | Gancho de retorno D1 (2º dia) | O que a criança encontra no dia seguinte: presente de login, início da Chama do Cosmo e continuidade visível. |
| 08.20 | Gancho de retorno D2+ e formação de hábito | Reforço da Chama e trilha de missões que puxam a 3ª/4ª sessão rumo ao hábito, sem FOMO nem pressão. |
| 08.21 | ⚠️ Pular o tutorial (leitor fluente) | Permitir que a Sofia avance rápido sem punição, definindo o mínimo inegociável antes de liberar a tela-casa. |
| 08.22 | Interromper & retomar o tutorial | Comportamento quando a rede cai, o professor encerra a aula ou o tablet troca de mão no meio da cerimônia. |
| 08.23 | Reentrada & idempotência | Garante que cerimônia interrompida não repete a festa nem duplica recompensa; estado autoritativo no servidor. |
| 08.24 | Onboarding progressivo pós-1ª sessão | Revelar Vestiário/Loja/Social/Constelação aos poucos (gating por nível/dia) para não sobrecarregar a estreia. |
| 08.25 | Estados de erro/vazio/offline no FTUE | Cerimônia sem rede (hoje há catch silencioso que zera personagens — bug a corrigir), missão não baixada e catálogo ausente. |
| 08.26 | Edge cases do FTUE | Aluno sem ano/matrícula, turma sem conteúdo semeado, código de aluno transferido, segundo aluno no mesmo aparelho. |
| 08.27 | Acessibilidade no FTUE | Estreia 100% navegável por áudio+ícone para não-leitor, modo daltônico e reduced-motion na festa; ponte para a Seção 13. |
| 08.28 | ⚠️ Métricas de ativação & funil de onboarding | Eventos por passo, taxa de conclusão da 1ª missão, tempo até a 1ª recompensa e drop-off; alvos a calibrar (Seção 17). |
| 08.29 | ⚠️ Experimentação do onboarding | A/B via live-ops de variantes da estreia com guardrails éticos para 6–11 anos; depende de autorização (Seção 19). |
| 08.30 | Roteiro de voz & i18n do FTUE | Script canônico pt-BR do Cosmo na estreia, plano de gravação de narração e espelho EN; ponte para a Seção 16. |
| 08.31 | Estratégia de testes do FTUE | E2E do primeiro loop, simulação offline, primeira-vez vs retomada e validação nos dispositivos-alvo; ponte para a Seção 18. |
| 08.32 | FTUE do Professor (menção) | Aponta o primeiro uso do professor (gerar cartões, roteiro da 1ª aula, o que ver primeiro) detalhado na Seção 10. |
| 08.33 | FTUE da Família (menção) | Aponta o primeiro acesso ao Portal da Família (consentimento LGPD, vínculo do responsável, primeira visão) detalhado na Seção 10/12. |
| 08.34 | ⚠️ Decisões em aberto (Onboarding) | Consolida pendências: definição de ativado, missão de estreia curada vs adaptativa, permitir pular, timing de revelar social e entrada da Família. |
| 08.35 | Espelho bilíngue PT-BR / EN | Convenção estrutural: seção duplicada em português (canônico) e inglês, mantidas em paridade. |

**Perguntas ao dono:**
- Qual é a definição objetiva de 'aluno ativado' e a hipótese de aha-moment que vamos medir e validar (ex.: concluiu a 1ª missão e voltou no D1)?
- A 1ª missão é uma missão de estreia curada e fixa, ou já sai da seleção adaptativa/BNCC do ano escolar do aluno?
- Podemos permitir pular o tutorial para leitores fluentes, e qual é o mínimo inegociável antes de liberar a tela-casa?
- Quais são as metas de ativação D0/D1/D2 (taxa de conclusão da 1ª missão e retorno no 2º dia)?
- Autoriza A/B testing do onboarding via live-ops e, se sim, com quais guardrails éticos para crianças de 6–11 anos?
- Quando e como o Portal da Família entra no onboarding (momento do consentimento LGPD e do vínculo do responsável)?

---

# Parte III — Comunidade

## 09 · Social & Comunidade Segura / Safe Social
**Objetivo:** Definir todo o subsistema social do Constela Quest — amizades, presença, modos multiplayer, comunicação por catálogo e rankings — de forma que 'aprender junto' encante sem nunca abrir uma superfície de risco (texto livre, dado exposto, toxicidade). Ancora nos Princípios Imutáveis 2 (sem chat livre), 3/12 (LGPD, opt-in por escola), 5/10 (ranking individual nunca exposto a crianças) e 16 (amizade nunca cruza escolas).

| # | Subseção | Propósito |
|---|----------|-----------|
| 09.1 | Objetivo e escopo do social | Delimita o que entra (amizade, modos coop/versus leves, mensagens de catálogo, rankings) e o que fica fora (chat, feed aberto, matchmaking com estranhos), amarrando aos 4 pilares. |
| 09.2 | Princípios de segurança social (re-derivação aplicada) | Reafirma como os Princípios 2/3/5/12/16 se materializam nesta seção, servindo de checklist inviolável para qualquer feature social. |
| 09.3 | Teto imutável: amizade só na mesma escola | Fixa a regra de que solicitante e destinatário compartilham `escola_id` sempre, com validação obrigatória em cada rota social e no WebSocket. |
| 09.4 | ⚠️ Alcance de amizade no lançamento (turma vs. escola) | Define se, no lançamento, o círculo de amizade é a própria turma ou a escola inteira — controla filtro do código de amigo e da lista de contatos. |
| 09.5 | ⚠️ Default de social por escola/turma (opt-in vs. opt-out) | Define o valor inicial de `social_ativo` numa nova escola/turma e se a ativação exige ação explícita do adulto. |
| 09.6 | Código de amigo (`codigo_amigo`) | Especifica formato (`COSMO-4F7B`), geração, unicidade, exibição falável/acessível e por que substitui digitar nomes — nunca há busca por nome real. |
| 09.7 | Fluxo de pedido → aceite/recusa de amizade | Passo a passo do convite (pendente→aceita/recusada), sempre decidido pela criança destinatária, com estados de UI e narração. |
| 09.8 | ⚠️ Bloqueio e denúncia de comportamento | Define status `bloqueada`, quem pode bloquear/denunciar (criança sozinha ou via adulto) e para onde vai o alerta de moderação. |
| 09.9 | ⚠️ Presença online e status | Como o sistema calcula/exibe 'amigo online agora', privacidade da presença e se existe modo invisível. |
| 09.10 | Identidade e visibilidade entre pares | Regra de que fora da própria turma a criança aparece só como apelido + avatar (nome real nunca vaza), e o que cada modo mostra do outro. |
| 09.11 | Mensagens rápidas — catálogo de comunicação segura | Schema de `quest_mensagens_rapidas` (slug, texto, áudio, categoria saudação/elogio/convite/reação, emoji) e a proibição absoluta de qualquer campo de texto livre. |
| 09.12 | ⚠️ Curadoria e versão do catálogo de mensagens | Quem cadastra/aprova as mensagens rápidas, como se versiona e quais categorias existem no lançamento. |
| 09.13 | ⚠️ Anti-spam e limites de convites/mensagens | Tetos de frequência (pedidos de amizade, convites de partida, mensagens rápidas) para impedir assédio por repetição, mesmo sem texto livre. |
| 09.14 | Modo — Estudar com um amigo (missão compartilhada) | Regras do coop 2 jogadores: objetivo comum, cada acerto avança a dupla, recompensa igual para os dois, sem perdedor. |
| 09.15 | Modo — Corrida | Regras da corrida 2 jogadores (acertou→anda; primeiro ganha confete extra; ambos ganham XP/moedas; derrota nunca custa nada). |
| 09.16 | ⚠️ Skins oficiais da Corrida | Fixa o conjunto canônico de skins — os docs divergem entre bichinhos/espacial/trilha e bichinhos/espacial/simples. |
| 09.17 | Modo — Pintura em dupla | Regras do coop cooperativo sem vencedor: cada acerto pinta parte do desenho até completar. |
| 09.18 | Modo — X1 amistoso | Regras do quiz em tempo real lado a lado, com 'revanche?' e elogio a ambos, sem punição ao perdedor. |
| 09.19 | Ciclo de vida das salas (`quest_salas`) | Estados aguardando→em_jogo→finalizada/cancelada, papel do líder, snapshot de participantes e o registro histórico da partida. |
| 09.20 | Protocolo de tempo real (WebSocket) | Especifica `/ws/quest?token=`, mensagens cliente↔servidor, autoridade do servidor sobre gabarito e sincronização de estado da sala. |
| 09.21 | Estado ao vivo: memória vs. Redis | Onde vive o estado da partida (memória em nó único, Redis quando houver réplicas) e como a linha em banco é só o histórico. |
| 09.22 | ⚠️ Reconexão e queda de wifi em partida | Comportamento quando um jogador cai (pausa, timeout, encerramento gentil) para não punir a criança pela rede fraca da escola. |
| 09.23 | Convite e emparelhamento (sem matchmaking com estranhos) | Fluxo criança: botão grande → lista de amigos online → convite → contagem 3-2-1 → jogando; jamais pareia com desconhecido. |
| 09.24 | Recompensas sociais e regra anti-punição | Como XP/moedas/estrelas são creditados nos modos sociais garantindo que derrota nunca custa nada (Princípio 6). |
| 09.25 | Ranking padrão da criança — a própria Constelação (eu × eu) | Estabelece a Constelação pessoal (eu de hoje × eu de ontem) como a tela primária de progresso, não o ranking. |
| 09.26 | Ranking de turma semanal (anti-lanterna) | Regras do ranking que zera toda segunda, celebra top 3 e nunca expõe os últimos colocados. |
| 09.27 | Ranking de evolução (quem mais cresceu) | Define o ranking paralelo por crescimento, que dá visibilidade a quem parte de baixo. |
| 09.28 | Coletivo entre turmas / XP da escola | Regras do placar coletivo por turma ('3º Ano B somou 12.400 XP') que nunca expõe criança individual. |
| 09.29 | Ranking municipal — só entre escolas, só para adultos | Fixa que ranking municipal existe apenas no Edu/Hub (adultos) e nunca aparece na experiência da criança. |
| 09.30 | ⚠️ Torneios (fase futura) | Esboça o espaço de competição opt-in, com começo/fim e medalha para todos os participantes. |
| 09.31 | Controles opt-in em três níveis (escola/turma/aluno) | Como social liga/desliga por configuração de escola, por turma e por `quest_perfis.social_ativo` (professor/responsável), e a precedência entre eles. |
| 09.32 | ⚠️ Precedência e conflito de controles sociais | Regra determinística de quem vence quando escola, turma e responsável divergem sobre ligar/desligar social. |
| 09.33 | Vocabulário e estados de UI social | Aplica o vocabulário canônico (nunca party/lobby/matchmaking) aos botões/telas sociais e lista estados vazio/carregando/erro. |
| 09.34 | Acessibilidade dos modos sociais | Áudio em todo convite, alvos ≥48px, e a garantia de que 'tempo' (corrida) é sempre social e opcional, nunca critério único. |
| 09.35 | Telemetria social e eventos de outbox | Eventos gerados (partida concluída, missão coop) e como alimentam professor/família via `quest_outbox`, sem coletar dado sensível novo. |
| 09.36 | Contratos de API social | Especifica `/quest/social/*` (amigos, convites, responder, mensagens-rápidas) e `/quest/salas/*` (criar, entrar, obter) com autorização e erros. |
| 09.37 | Modelo de dados social | Detalha `quest_amizades`, `quest_salas`, `quest_mensagens_rapidas` e índices/UNIQUE, com `escola_id` em toda linha. |
| 09.38 | Impacto no existente e fase de entrega | Mapeia dependências (Q4 no roadmap), o que precisa existir antes (retenção Q2) e riscos de reescrita. |
| 09.39 | Critério de pronto (Definition of Done) | Régua de aceite: duas crianças em casas diferentes completam uma missão juntas e os dados chegam ao professor, sem incidente de segurança. |

**Perguntas ao dono:**
- Alcance da amizade no lançamento: mesma turma ou escola inteira? (controla o filtro do código de amigo e da lista de contatos)
- O social vem ligado ou desligado por padrão numa escola/turma nova (opt-in explícito do adulto ou já ativo)?
- Qual o conjunto canônico das 3 skins da Corrida — os docs divergem entre bichinhos/espacial/trilha e bichinhos/espacial/simples?
- A criança pode bloquear/denunciar outra criança por conta própria, ou isso é mediado por professor/coordenador? Para quem vai o alerta?
- A presença 'online' é visível a todos os amigos ou só durante convites? Existe modo invisível?
- Quais os tetos de frequência para pedidos de amizade, convites de partida e mensagens rápidas (anti-assédio por repetição)?
- Quando um jogador cai por wifi no meio da partida, qual o comportamento esperado (pausa, timeout, encerrar sem penalidade)?
- Os torneios da fase futura são opt-in com medalha para todos? Há alguma premiação além da medalha?
- Quem cadastra/aprova o catálogo de mensagens rápidas e quais categorias existem no lançamento?
- Em conflito de controle social entre escola, turma e responsável, quem vence (qual a precedência determinística)?

---

## 10 · Professor & Família / Teacher & Family
**Objetivo:** Especificar os dois portais adultos que fecham o triângulo em torno da criança — o Portal do Professor (dentro do Edu, foco em aprendizagem BNCC, zero ruído lúdico) e o Portal da Família (leitura, controles e transparência LGPD) — de modo que cada audiência veja sua própria linguagem sem jamais expor à criança relatórios nem ao adulto o ruído do jogo. Ancora nos Princípios 3/12 (LGPD, coleta mínima), 5 (ranking individual só a adultos) e 16 (reuso do Edu, zero reconfiguração).

| # | Subseção | Propósito |
|---|----------|-----------|
| 10.1 | Objetivo e o triângulo criança–professor–família | Delimita o papel de cada adulto e a regra 'cada audiência, sua linguagem': professor vê aprendizagem, família vê acompanhamento, criança vê aventura. |
| 10.2 | Princípio da separação de linguagens | Fixa que o professor não vê moedas/itens/loja e a criança não vê relatórios — inviolável em toda tela desta seção. |
| 10.3 | Papéis, autenticação e onde cada portal vive | Tabela de papéis (aluno, responsável, professor, coordenador/admin, admin global), como autenticam e as rotas (`/quest/professor/*`, `/quest/familia/*`). |
| 10.4 | PORTAL DO PROFESSOR — visão geral e integração no Edu | Define que as telas são novas no Edu web consumindo dados do módulo quest via consulta local (não sincronização), reusando padrões do Edu. |
| 10.5 | Panorama da turma | Especifica os indicadores agregados de `quest_tentativas` (tempo de estudo, missões concluídas, taxa de acertos, ativos/inativos na semana). |
| 10.6 | Mapa de habilidades BNCC (heatmap) | Define o mapa de calor turma × habilidade (domínio 0–100 de `quest_habilidades`) e o drill-down para quais alunos precisam de reforço. |
| 10.7 | Erros mais comuns (o mal-entendido, não só o erro) | Especifica a leitura de `quest_tentativas.respostas` para revelar os desafios de maior erro e as alternativas erradas mais escolhidas. |
| 10.8 | Trajetória do aluno | Define a visão individual: evolução de domínio por mundo, tempo, sequência (Chama) e conquistas — a partir de agregados por perfil. |
| 10.9 | Alertas pedagógicos | Especifica alertas derivados do outbox (`alerta_dificuldade`): 'N alunos empacados na mesma habilidade', 'aluno sem acesso há X dias'. |
| 10.10 | ⚠️ Missão da Turma (atribuições) | Define o professor destacar uma missão da semana que vira card especial no lobby dos alunos, apoiada na tabela leve `quest_atribuicoes`. |
| 10.11 | ⚠️ Modelo `quest_atribuicoes` e granularidade da atribuição | Define os campos da nova tabela e se o professor atribui à turma inteira, a grupos ou a alunos, e o limite semanal. |
| 10.12 | O que o professor NÃO vê (exclusões explícitas) | Lista o que fica fora do portal do professor: moedas, itens, loja, ranking individual da criança — ruído lúdico. |
| 10.13 | ⚠️ Filtros, período e exportação de relatórios | Define seletores de período/turma/aluno, paginação nos agregados e formatos de exportação (PDF/planilha reusando o Edu). |
| 10.14 | ⚠️ Reconhecimento do professor (presente/destaque) | Define se o professor pode reconhecer um aluno (origem `presente_professor` no inventário) e como isso chega à criança sem virar competição. |
| 10.15 | ⚠️ Visão do coordenador/admin da escola | Define se há uma visão consolidada multi-turma da escola aqui ou se pertence a Live-ops/gestão, e os controles sociais que o coordenador opera. |
| 10.16 | PORTAL DA FAMÍLIA — visão geral e papel `responsavel` | Define o novo cargo `responsavel` no enum de `usuarios` (login e-mail/senha) com acesso somente-leitura a `/quest/familia/*`. |
| 10.17 | Vínculo ResponsavelAluno (modelo `responsaveis_alunos`) | Especifica a tabela de vínculo (usuario_id, aluno_id, parentesco, autorizado_por, UNIQUE) reusando `usuarios`, sem novo cadastro de pessoa. |
| 10.18 | ⚠️ Quem autoriza o vínculo e fluxo de convite | Define quem da escola confirma o vínculo (`autorizado_por`) e como o responsável recebe acesso (convite por e-mail, código, auto-cadastro validado). |
| 10.19 | ⚠️ Quando a API da Família entra (fase) | Fixa a fase de entrega do portal (Q3 no roadmap) e o que precisa existir antes (telemetria e agregados de Q1/Q2). |
| 10.20 | Painel de resumo da família | Especifica a tela-resumo: tempo de estudo por dia/semana, em linguagem simples, sem jargão BNCC. |
| 10.21 | Evolução por matéria (linguagem simples) | Define como o domínio pedagógico é traduzido para a família sem códigos BNCC nem termos técnicos. |
| 10.22 | Conquistas e nível (gancho de conversa) | Define exibir conquistas e nível para a família puxar conversa com o filho ('me conta dessa medalha!'), sem expor economia. |
| 10.23 | ⚠️ Certificados em PDF | Define gatilhos e modelo dos certificados reusando o gerador de PDF do Edu. |
| 10.24 | Controle: desligar o social do filho | Especifica o toggle da família sobre `quest_perfis.social_ativo` e sua interação com os controles de escola/turma (ver 9.31/9.32). |
| 10.25 | ⚠️ Controle: horário permitido | Define a janela de horário (ex.: não jogar após 21h) e se o bloqueio é efetivo no servidor ou apenas informativo. |
| 10.26 | ⚠️ Controle: bem-estar (teto diário e pausa) | Define teto diário de XP e a pausa do Cosmo (40 min, configurável) e quem os configura entre escola e família. |
| 10.27 | ⚠️ Notificações push (resumo semanal) | Especifica o push de resumo para a família via outbox, com opt-in e frequência, garantindo que FOMO/push nunca vai para a criança. |
| 10.28 | Transparência LGPD no portal | Define a tela que mostra exatamente o que é coletado e para quê, cumprindo o Art. 14 (melhor interesse, coleta mínima). |
| 10.29 | ⚠️ Consentimento e onboarding da escola | Define o termo de consentimento dos responsáveis como parte do onboarding da escola (documento padrão; escola coleta assinatura). |
| 10.30 | Auditoria de acessos adultos | Fixa que todo acesso de professor/responsável a dados de aluno passa por `logs_auditoria` existente. |
| 10.31 | O que a família NÃO vê (limites) | Lista exclusões do portal família (moedas/loja, ranking de outras crianças, dados de colegas) e o escopo restrito ao próprio filho. |
| 10.32 | ⚠️ Multiplicidade: vários filhos e vários responsáveis | Define visibilidade e poderes quando um responsável tem N filhos e um aluno tem N responsáveis (quem pode desligar social/impor horário). |
| 10.33 | ⚠️ Saída do aluno e ciclo de vida do vínculo | Define o que acontece ao portal/vínculo quando o aluno sai da escola (perfil pausado, anonimização após prazo, acesso do responsável revogado). |
| 10.34 | Contratos de API (professor e família) | Especifica `/quest/professor/*` (panorama, habilidades, erros-comuns, trajetória, atribuições) e `/quest/familia/*` (filhos, resumo, controles) com autorização por papel. |
| 10.35 | Modelo de dados e mudanças aditivas no núcleo | Detalha `responsaveis_alunos`, `quest_atribuicoes`, o valor `responsavel` no enum `usuarios.cargo` e a regra de que o aluno nunca entra em `usuarios`. |
| 10.36 | Eventos de domínio → notificações (outbox) | Mapeia os tipos de `quest_outbox` (missao_concluida, nivel_alcancado, conquista_obtida, alerta_dificuldade…) para push e mural do Edu. |
| 10.37 | Impacto no existente e fase de entrega | Mapeia dependências (Q3), reuso do gerador de PDF e do serviço de push do Edu, e riscos de acoplamento. |
| 10.38 | Critério de pronto (Definition of Done) | Régua de aceite: na reunião de pais o professor abre o mapa de habilidades e um responsável mostra o resumo no celular, sem reconfiguração. |

**Perguntas ao dono:**
- Quem autoriza o vínculo ResponsavelAluno — professor, coordenador/secretaria, ou processo no onboarding da escola? E como o responsável recebe acesso (convite por e-mail, código, auto-cadastro validado)?
- Confirmar a fase de entrada da API do Portal da Família (Q3 no roadmap)?
- O 'horário permitido' é bloqueio efetivo (impede login/jogo, imposto no servidor) ou apenas informativo/aviso?
- Quem define o teto diário de XP e a pausa de 40 min — escola, família ou ambos? Qual a precedência em caso de conflito?
- Certificados em PDF: quais os gatilhos (nível, conclusão de planeta, fim de temporada) e quais os modelos?
- O push semanal para a família exige opt-in explícito? A frequência é configurável?
- Missão da Turma (quest_atribuicoes): confirmar o modelo, se a atribuição é por turma/grupo/aluno e o limite semanal.
- O professor pode reconhecer/premiar um aluno (origem 'presente_professor')? Se sim, como isso chega à criança sem virar competição?
- Há visão consolidada multi-turma para coordenador/admin da escola nesta seção, ou isso pertence a Live-ops/gestão?
- Regras de multiplicidade: com vários responsáveis para um mesmo aluno, quem pode desligar o social e impor horário? Há hierarquia entre eles?
- Ao sair da escola: o acesso do responsável é revogado imediatamente? O portal reflete o perfil pausado e a anonimização após o prazo?

---

# Parte IV — Técnico & Segurança

## 11 · Arquitetura Técnica
**Objetivo:** Fixar o desenho técnico completo do Quest — monólito modular com fronteira de dependência de mão única, banco quest_ em 8 grupos, autoridade do gabarito no servidor, contrato de mecânica plugável, tempo real por WebSocket, PWA/offline e caminho de escalabilidade A>B>C — de modo que um dev implemente sem tomar nenhuma decisão de produto. Registra explicitamente como EM ABERTO a escolha DOM/SVG-first vs Three.js no núcleo e a definição do piso de desempenho/device-alvo.

| # | Subseção | Propósito |
|---|----------|-----------|
| 11.1 | Princípio arquitetural: monólito modular | Por que o Quest nasce como módulo com fronteira dentro do backend FastAPI do Edu, e não como microsserviço no dia 1. |
| 11.2 | Regra de dependência de mão única (quest → núcleo) | Fixa que quest e edu importam o núcleo compartilhado, mas edu NUNCA importa quest.models/services diretamente. |
| 11.3 | Fronteira do módulo e superfície do núcleo compartilhado | Lista o que o núcleo expõe (escolas, alunos, turmas, matrículas, usuários, configuração, auditoria, services/ia) e como o Edu consome o Quest (rotas /quest/professor/* e outbox). |
| 11.4 | Gatilhos objetivos de extração para serviço próprio | Define os limiares medíveis (>30 escolas ativas, WS >2 réplicas, time 2+ devs) que autorizam extrair o módulo. |
| 11.5 | Estrutura de pastas do backend (app/quest) | Mapa canônico de routers/, models/, schemas/, services/ (regra pura sem import de FastAPI) e conteudo/ (seeds). |
| 11.6 | Estrutura de pastas do frontend (apps/quest) | Mapa canônico de app/, design/, cosmo/, lobby/, planetas/, jogo/, social/, vestiario/, constelacao/, audio/, estado/, servicos/. |
| 11.7 | Pacotes compartilhados (@constela/core e quest-core) | Define quest-core como fonte única dos tipos da API e cliente, consumidos pelo app aluno e pelas telas de professor no Edu web. |
| 11.8 | Stack tecnológico canônico | Tabela camada→tecnologia→justificativa (React+Vite+TS PWA, dnd-kit, Howler+Web Speech, TanStack+Zustand, FastAPI, SQLAlchemy 2, Postgres/SQLite, Redis, CDN). |
| 11.9 | Convenções do banco quest_ (prefixo e regras herdadas) | Fixa prefixo quest_, datas UTC, escola_id indexado em toda tabela de aluno, imutabilidade de histórico e regras numéricas não-hardcoded. |
| 11.10 | Banco — Grupo 1: Identidade e acesso | Especifica quest_perfis, quest_credenciais_aluno e responsaveis_alunos com seus campos e chaves. |
| 11.11 | Banco — Grupo 2: Conteúdo pedagógico (catálogo global) | Especifica quest_mundos, quest_jornadas, quest_missoes e quest_desafios, incluindo versionamento de missão e o campo gabarito. |
| 11.12 | Banco — Grupo 3: Progresso e telemetria | Especifica quest_progresso, quest_tentativas (imutável) e quest_habilidades (cache recalculável) e suas rotinas de recomputação. |
| 11.13 | Banco — Grupo 4: Economia e coleção | Especifica quest_itens, quest_inventario e o ledger imutável quest_transacoes_moedas com saldo como cache. |
| 11.14 | Banco — Grupo 5: Ritmo diário e conquistas | Especifica quest_tarefas_periodicas e o par quest_conquistas/quest_conquistas_obtidas com critérios data-driven. |
| 11.15 | Banco — Grupo 6: Social e partidas | Especifica quest_amizades, quest_salas e quest_mensagens_rapidas (catálogo, sem texto livre). |
| 11.16 | Banco — Grupo 7: Temporadas e eventos | Especifica quest_temporadas, quest_passe_progresso e quest_eventos, com o passe gratuito de trilha única. |
| 11.17 | Banco — Grupo 8: Integração (quest_outbox) | Especifica a tabela de eventos de domínio, seus tipos, payload e campos de processamento. |
| 11.18 | Tabelas adiadas (clubes e torneios) | Documenta o desenho de clubes/torneios que entra na fase Mundo Vivo sem alterar a arquitetura existente. |
| 11.19 | Mudanças aditivas e retrocompatíveis no núcleo | Fixa os dois únicos acréscimos ao Edu: cargo 'responsavel' em usuarios e o papel 'aluno' fora de usuarios (via credenciais). |
| 11.20 | Autoridade do gabarito no servidor | Estabelece que o backend confere a resposta crua contra o gabarito e devolve o resultado, tornando impossível fabricar XP no cliente. |
| 11.21 | Contrato de entrega do catálogo sem gabarito | Fixa que missões/desafios chegam ao cliente sempre sem o campo gabarito, inclusive no cache offline. |
| 11.22 | Contrato de mecânica plugável (registry) | Define a interface MecanicaProps/RespostaDesafio e o registry MECANICAS que permite adicionar um tipo de atividade só criando pasta + schema. |
| 11.23 | Schema de conteúdo e validador por mecânica | Define que cada mecânica declara o schema JSON do seu corpo de desafio e um validador, mais suas necessidades de acessibilidade. |
| 11.24 | Motor de corrida único (três skins por JSON) | Fixa que Corrida do Saber/Bichinhos/Espacial são o mesmo motor parametrizado por JSON de tema, não por código. |
| 11.25 | Economia por ledger imutável | Estabelece que moedas mudam só via quest_transacoes_moedas e o saldo é consequência auditável e recomputável. |
| 11.26 | Contrato cliente↔servidor da tentativa | Define o ciclo iniciar → responder desafio → finalizar com recompensas calculadas no servidor. |
| 11.27 | Tempo real: máquina de estados da sala | Define os estados aguardando→em_jogo→finalizada/cancelada e a orquestração líder/convidado do WebSocket. |
| 11.28 | Protocolo de mensagens do WebSocket /ws/quest | Especifica os eventos (join, começar, desafio-n sem gabarito, resposta, placar, recompensas) e o formato de cada um. |
| 11.29 | Estado da sala: memória do processo → Redis pub/sub | Define como o estado vivo migra de dicionário em memória (fase A) para hash+pub/sub no Redis quando há réplicas. |
| 11.30 | Reconexão e tolerância de queda | Fixa a tolerância de 30s de queda com reenvio do estado no rejoin (wifi de escola). |
| 11.31 | Abandono de partida sem punição | Define que partida abandonada vira missão quase-completa com recompensa parcial, nunca penalidade. |
| 11.32 | PWA: service worker e precache do shell | Fixa que o app abre sempre offline via Workbox, com o shell em precache e a API jamais em cache. |
| 11.33 | Cache de conteúdo da jornada atual | Define quais missões (JSON + áudios) ficam em cache para jogar sem rede e como são pré-carregadas. |
| 11.34 | Fila offline em IndexedDB (tentativas append-only) | Especifica a fila de tentativas offline sincronizada ao reconectar, com flag origem_offline e conferência do gabarito no sync. |
| 11.35 | Política do que nunca é cacheado | Fixa que API dinâmica, gabarito e token de sessão nunca entram em cache/persistência local. |
| 11.36 | Modos sociais exigem rede | Define que corridas/salas dependem de conexão e são sinalizados com ícone de sinal na UI. |
| 11.37 | Estado do cliente e sessão sem router | Fixa TanStack Query (servidor) + Zustand (jogo/sessão) e a máquina de estados de sessão do boot ao lobby. |
| 11.38 | Dois mundos de JWT (isolamento de papéis) | Define que o token papel 'aluno' carrega hoje `{sub=id da credencial, papel, ver, iat, exp}` (escola_id/aluno_id/perfil vêm de lookup da credencial, não de claim) e é rejeitado no Edu e vice-versa; contrato unificado é alvo. |
| 11.39 | Escalabilidade A>B>C (caminho, não big-bang) | Tabela estágio→gatilho→mudança: A instância única, B Redis+réplicas, C extração para serviço próprio + fila real. |
| 11.40 | Cenário de dimensionamento (pico de aula) | Fixa o pico previsível (meia escola entrando 7h30) como cenário de capacidade, não a média diária. |
| 11.41 | Assets em CDN e cache HTTP por ETag | Define que trilhas/ilustrações vão por CDN e o catálogo usa cache HTTP com ETag por mudar raramente. |
| 11.42 | Outbox como base de extração (produtor imutável) | Fixa que o produtor de eventos não muda quando o outbox migrar de polling para fila real na extração. |
| 11.43 | Observabilidade e auditoria (reuso de logs_auditoria) | Define que toda escrita relevante passa pela auditoria existente e o mínimo de logs/métricas operacionais. |
| 11.44 | Ambientes, migrações e paridade dev/prod | Fixa SQLite em dev e PostgreSQL em prod com SQLAlchemy 2 e a estratégia de migrações aditivas. |
| 11.45 | Rate-limit distribuído (memória → Redis) | Aponta o gap arquitetural atual (rate-limit em memória, não distribuído) e o alvo com réplicas; detalhe de política vai à Seção 12. |
| 11.46 | Definition of Done técnico e testes de contrato | Define os testes de contrato (mecânica, API tentativa, WS, sync offline) que fecham a implementação de cada peça. |
| 11.47 | ⚠️ DECISÃO: renderização DOM/SVG-first vs Three.js no núcleo | Reconciliar o doc 01 (DOM/SVG/CSS-first, 'PixiJS não Three.js') com o código que já usa Three.js no avatar, definindo o alcance oficial. |
| 11.48 | ⚠️ DECISÃO: piso de desempenho e device-alvo mínimo | Definir device-alvo mínimo explícito e o orçamento de carregamento/memória/FPS ao qual toda arte e mecânica se subordina. |
| 11.49 | ⚠️ DECISÃO: plataformas-alvo (PWA instalável vs nativo) | Definir se há app instalável/nativo além da web e em que fase entra. |
| 11.50 | ⚠️ DECISÃO: pipeline de produção de assets 3D/arte | Definir quem produz os GLB e camadas trocáveis e se áudios/ilustrações são gravados ou sintetizados. |
| 11.51 | ⚠️ DECISÃO: interface de autoria/publicação do catálogo pedagógico | Definir por qual ferramenta o conteúdo BNCC é cadastrado/publicado e a conexão com o software de matérias+questões futuro. |

**Perguntas ao dono:**
- DOM/SVG/CSS-first (doc 01) vs Three.js no núcleo do frontend: qual é a decisão oficial e qual o alcance dela — só o avatar (como já está no código), a tela-casa, ou o jogo todo?
- Qual é o device-alvo mínimo explícito (modelo/classe de tablet e Chromebook, RAM, GPU, versão de navegador) que serve de piso imutável?
- Qual o orçamento concreto de carregamento e memória (peso do bundle inicial, tempo até jogável, teto de RAM/VRAM, taxa de quadros mínima) que toda arte e mecânica deve respeitar?
- Plataformas-alvo além da web responsiva: PWA instalável e/ou apps nativos? Em que fase cada uma entra?
- Pipeline de arte/assets: quem produz os GLB 3D e as camadas cosméticas trocáveis; os áudios e ilustrações são gravados/desenhados por fornecedor ou sintetizados como hoje?
- Por qual interface o catálogo pedagógico (mundos/jornadas/missões/desafios/gabarito) é cadastrado e publicado, e como isso se conecta ao software futuro de matérias+questões do dono?
- Escopo de conteúdo de lançamento — 1 planeta profundo (ex.: Matemática) vs 9 planetas rasos — para dimensionar a arquitetura de conteúdo e seeds?

---

## 12 · Segurança, Privacidade & LGPD
**Objetivo:** Especificar o modelo de segurança e privacidade infantil de forma implementável — modelo de ameaça do login código-só (sem senha), JWT de papel aluno com escopo mínimo, rate-limit, token_version, isolamento multi-escola, e conformidade com a LGPD Art. 14 (coleta mínima, retenção, anonimização, opt-in social). Marca como EM ABERTO as decisões de política que só o dono confirma (prazo de retenção, gatilho de anonimização, autorização de vínculo, DPO).

| # | Subseção | Propósito |
|---|----------|-----------|
| 12.1 | Escopo e princípios de segurança | Amarra a seção aos princípios imutáveis 1, 3, 13, 14, 15 e 18 e define o que está dentro/fora do escopo. |
| 12.2 | Modelo de ameaça do login código-só | Enumera atacantes (criança curiosa, colega, adulto malicioso, script automatizado) e os vetores contra o código impresso exposto. |
| 12.3 | O código impresso É a credencial | Fixa as propriedades do código (curto, falável, só letras+números, decorável) e por que pode ficar exposto, como no Elefante Letrado. |
| 12.4 | QR como mesma credencial em figura (rotatável) | Define o qr_token como forma alternativa e trocável da mesma credencial, sem inventar segundo fator. |
| 12.5 | Rate-limit por (código, IP) | Especifica o limitador dimensionado para ~30 tablets atrás do NAT da escola como principal defesa contra abuso. |
| 12.6 | Rate-limit distribuído (gap atual → Redis) | Registra que o limitador está em memória hoje e o alvo distribuído com réplicas para não ser burlado por instância. |
| 12.7 | Escopo mínimo do papel aluno | Fixa que o token aluno só alcança rotas /quest/* não-administrativas e nunca rotas do Edu. |
| 12.8 | JWT de papel aluno (claims e TTL) | Registra o TTL (token de 30 dias no aparelho compartilhado); os claims Q0 reais são `{sub, papel, ver, iat, exp}` (desenho do JWT = Seção 11; a 12 defere). |
| 12.9 | token_version e invalidação de sessão | Especifica a invalidação por versão que revoga cartões/QR antigos ao regenerar. |
| 12.10 | Conta não salva ao sair e boot 'É você, {nome}?' | Fixa token só em memória e a confirmação obrigatória no boot para não herdar a conta do turno anterior. |
| 12.11 | Dois mundos de JWT (isolamento de papéis) | Garante que o token aluno é rejeitado no Edu e o token Edu não vale no Quest. |
| 12.12 | Renovação e expiração de sessão | Define o comportamento ao expirar sem punir a criança; em Q0 NÃO há rotas `renovar`/`sair` (o token expira; regenerar o cartão invalida via token_version) — renovar/sair é alvo aspiracional. |
| 12.13 | Papéis e autorização por rota | Tabela aluno/responsável/professor/coordenador/admin global com o que cada um autentica e acessa, checado no backend. |
| 12.14 | ⚠️ Autorização do vínculo do responsável | Define responsaveis_alunos e o campo autorizado_por; quem da escola confirma o vínculo e quando a API entra fica a decidir. |
| 12.15 | Isolamento multi-escola por escola_id | Fixa escola_id indexado e filtrado em toda tabela e rota, idêntico ao Edu. |
| 12.16 | ⚠️ Social nunca cruza escolas (teto imutável) | Fixa que amizades jamais atravessam escolas; o alcance de lançamento (turma vs escola) é decisão de produto pendente. |
| 12.17 | Sem chat livre (nenhum texto livre ao aluno) | Fixa que nenhuma tabela acessível ao papel aluno tem campo de texto livre, nem para nomear pet. |
| 12.18 | Exceção validada: nome de exibição | Especifica a validação estrita do apelido (2–20, só letras) e a lista negra de termos, única exceção ao 'sem texto livre'. |
| 12.19 | Catálogo sem gabarito como controle de integridade | Trata a autoridade do gabarito no servidor como controle anti-fraude de segurança, não só de arquitetura. |
| 12.20 | Economia auditável como controle antifraude | Fixa o ledger imutável e a impossibilidade de editar saldo direto como defesa contra farm/adulteração. |
| 12.21 | Auditoria de acessos a dados de aluno | Define que acessos de professores/responsáveis a dados de crianças passam por logs_auditoria. |
| 12.22 | LGPD Art. 14 — melhor interesse e coleta mínima | Fixa que o Quest não coleta foto, localização nem dado além do que a escola já cadastrou no Edu. |
| 12.23 | Base legal e consentimento | Define o tratamento no contexto do serviço educacional e o termo de consentimento dos responsáveis no onboarding da escola. |
| 12.24 | ⚠️ Opt-in social por escola | Fixa que recursos sociais são desligados até a escola optar por ativá-los; o default é decisão de produto. |
| 12.25 | Transparência ao titular (Portal da Família) | Define que a família enxerga exatamente o que é coletado e para quê. |
| 12.26 | ⚠️ Política de retenção da telemetria detalhada | Define retenção configurável das respostas das tentativas; o prazo-padrão sugerido de 24 meses precisa de confirmação. |
| 12.27 | ⚠️ Anonimização na saída do aluno | Especifica perfil pausado → 'Aluno removido' e telemetria perdendo o vínculo nominal; o gatilho exato fica a confirmar. |
| 12.28 | Agregados pedagógicos que sobrevivem | Define quais dados permanecem após anonimização (agregados sem vínculo nominal) e por quê. |
| 12.29 | Sem anúncios e sem rastreamento de terceiros | Fixa a proibição de qualquer anúncio ou SDK de tracking de terceiros na experiência da criança. |
| 12.30 | Telemetria própria mínima e finalística | Define que só há telemetria própria, mínima e com finalidade pedagógica/de produto declarada. |
| 12.31 | Segurança de assets/CDN e conteúdo público | Define o que pode ficar público na CDN (cosméticos, trilhas) sem expor dado de aluno nem gabarito. |
| 12.32 | Regeneração de cartões | Fixa regeneração individual por aluno sem derrubar a turma, com código imutável e só o QR trocando. |
| 12.33 | Mensagem para aluno transferido/arquivado | Define a mensagem acolhedora ('cartão descansando') em vez de 'código errado' que faria a criança se culpar. |
| 12.34 | Tratamento de dados dos responsáveis | Define o cargo 'responsavel' em usuarios (e-mail/senha) e o escopo de leitura restrito a /quest/familia/*. |
| 12.35 | ⚠️ Resposta a incidentes e vazamentos | Define o processo mínimo de detecção, contenção e notificação; o procedimento formal precisa ser definido pelo dono. |
| 12.36 | ⚠️ Direitos do titular (acesso/eliminação) | Define como atender pedidos de acesso/eliminação de dados via escola; o fluxo formal fica a decidir. |
| 12.37 | ⚠️ Encarregado (DPO) e política de privacidade pública | Define a necessidade de um Encarregado designado e de política pública além do termo de escola; pendente do dono. |
| 12.38 | Definition of Done de segurança (checklist de revisão) | Checklist obrigatório de revisão (escopo de token, isolamento, ausência de texto livre, gabarito, auditoria) para dar uma feature por pronta. |

**Perguntas ao dono:**
- Confirmar em definitivo o login código-só (sem senha/PIN) e autorizar a limpeza dos resíduos de 'PIN de figuras' nos docs antigos?
- Confirmar o prazo de retenção da telemetria detalhada (respostas das tentativas) — o padrão sugerido é 24 meses?
- Qual o gatilho exato de anonimização quando o aluno sai da escola: imediato ao arquivar, ao fim do prazo de retenção, ou outro?
- Quem autoriza o vínculo responsável↔aluno (escola, professor, coordenador) e em que fase entra a API do Portal da Família?
- Recursos sociais entram ligados ou desligados por padrão, e o alcance de lançamento é 'mesma turma' ou 'mesma escola'?
- Há Encarregado (DPO) designado e uma política de privacidade pública a publicar, além do termo de consentimento no onboarding da escola?
- Existe processo formal de resposta a incidente e de atendimento aos direitos do titular (acesso/eliminação) via escola?

---

## 13 · Acessibilidade & Bem-estar
**Objetivo:** Garantir que uma criança de 6–11 anos, muitas vezes não-leitora e em hardware modesto compartilhado, consiga jogar por conta própria e de forma saudável — áudio obrigatório pt-BR, alvos ≥48px, uma ação por tela, navegação sem leitura (ícone+cor+áudio), reduced-motion, modo daltônico, teto de uso saudável e zero dark patterns. Marca como EM ABERTO as preferências ainda indefinidas e o escopo de suporte assistivo estendido.

| # | Subseção | Propósito |
|---|----------|-----------|
| 13.1 | Princípio: acessibilidade não-negociável (6–11 anos) | Fixa o Princípio 11 como piso obrigatório de toda tela e mecânica, sem exceção por prazo ou estética. |
| 13.2 | As duas sub-faixas: não-leitor vs leitor fluente | Ancoram-se nas personas Miguel (não-leitor) e Sofia (leitora) para justificar áudio obrigatório e profundidade simultâneos. |
| 13.3 | Áudio obrigatório: toda instrução falada em pt-BR | Fixa que nenhuma instrução, botão ou fala depende de texto lido — tudo tem narração em português do Brasil. |
| 13.4 | Fonte de áudio: TTS vs pré-gravado (regra por contexto) | Define quando usar Web Speech sintetizado e quando exigir áudio pré-gravado como fallback, garantindo cobertura offline. |
| 13.5 | Guia de voz do Cosmo (✓/✗) | Remete à Seção 02 como referência única de tom para UI, narração gravada e IA futura (acerto, erro acolhido, dica). |
| 13.6 | Repetir áudio / narração sob demanda | Fixa um controle sempre disponível para a criança reouvir a instrução quantas vezes quiser. |
| 13.7 | Alvos de toque ≥ 48px (tamanho e espaçamento) | Especifica o alvo mínimo e o espaçamento entre alvos para dedos pequenos em tela compartilhada. |
| 13.8 | Uma ação primária por tela | Fixa que cada tela infantil oferece no máximo uma ação primária clara, evitando sobrecarga. |
| 13.9 | Navegação sem depender de leitura (ícone + cor + áudio) | Exige que todo caminho seja compreensível pelos três canais juntos, nunca só por texto. |
| 13.10 | Modo daltônico (cor nunca como único canal) | Define paletas seguras e a regra de que informação por cor sempre tem redundância em forma/ícone/áudio. |
| 13.11 | prefers-reduced-motion respeitado | Especifica o que é reduzido (partículas, transições grandes) e o que permanece quando a preferência está ativa. |
| 13.12 | Tempo nunca como critério único | Fixa que nenhuma missão falha só por tempo; o cronômetro pode dar bônus mas nunca punir. |
| 13.13 | Contraste, legibilidade e tamanho de fonte | Define contraste mínimo e o tamanho de fonte ajustável guardado em preferências do perfil. |
| 13.14 | Preferências de acessibilidade no perfil | Especifica os campos de preferências (som, música, narração, reduzir animações, tamanho de fonte) e como a UI os expõe. |
| 13.15 | ⚠️ Destino das preferências 'musica' e 'reduzir_animacoes' | Registra que esses dois campos modelados precisam de UI/função definida ou remoção — decisão do dono. |
| 13.16 | Feedback multissensorial de acerto/erro | Define a combinação de sinal visual + áudio (e háptico onde houver) para confirmar cada interação sem depender de leitura. |
| 13.17 | Erro acolhido, nunca punição | Fixa a linguagem 'quase!/vamos juntos' e a ausência de qualquer perda mecânica ao errar (liga ao Princípio 6). |
| 13.18 | Requisitos de acessibilidade declarados por mecânica | Exige que cada mecânica plugável declare áudio de instrução, alvo mínimo e suporte daltônico no seu contrato. |
| 13.19 | ⚠️ Escopo de suporte assistivo estendido | Define se leitor de tela e navegação por teclado entram além do público infantil e em que fase — pendente do dono. |
| 13.20 | ⚠️ Teto diário de XP como celebração, não bloqueio | Fixa que o teto diário comemora e não trava; o valor-padrão vem da regra de progressão e precisa de confirmação. |
| 13.21 | ⚠️ Lembrete de pausa do Cosmo | Define o lembrete de pausa (sugerido 40 min, configurável); o default precisa de confirmação do dono. |
| 13.22 | Escudo de sequência (não punir faltas) | Fixa a proteção da Chama do Cosmo (1 falta protegida por semana) para que a sequência não vire pressão. |
| 13.23 | Zero dark patterns | Proíbe 'só falta 1!', timers de oferta, FOMO artificial e qualquer manipulação na experiência da criança. |
| 13.24 | Notificações push só para adultos | Fixa que todo push é para responsável/professor; a criança nunca recebe gatilho de FOMO. |
| 13.25 | Controles de bem-estar da família | Define os controles no Portal da Família (desligar social, horário permitido, resumo semanal). |
| 13.26 | ⚠️ Definição do controle de horário permitido | Especifica se a janela de uso é faixa livre configurada pela família ou faixas fixas — pendente do dono. |
| 13.27 | Sem vidas, sem espera forçada, sem compra | Fixa a ausência de mecânicas de energia/vidas ou paywall que forcem espera ou pagamento. |
| 13.28 | Ranking saudável (eu×eu e turma que zera) | Define que a criança só vê a própria constelação e a turma da semana, sem lanterna nem ranking individual exposto. |
| 13.29 | ⚠️ Acessibilidade x device-alvo (degradação graciosa) | Define como animações e efeitos degradam em hardware fraco, ligando-se ao piso de desempenho da Seção 11. |
| 13.30 | Playtest com não-leitores e testes de acessibilidade | Define o método de validação (playtest com crianças reais, verificação de alvos/contraste/áudio) como parte do Done. |
| 13.31 | Checklist de conformidade por tela (gate de revisão) | Fornece o checklist obrigatório (áudio, 48px, uma ação, ícone+cor+áudio, reduced-motion, daltônico) que toda tela passa antes de publicar. |

**Perguntas ao dono:**
- As preferências 'musica' e 'reduzir_animacoes' do perfil ganham UI e função própria, ou saem do modelo?
- O escopo de acessibilidade inclui suporte a leitor de tela e navegação por teclado além do público-alvo infantil? Em que fase?
- Confirmar os valores-padrão do teto diário de XP (celebração) e do lembrete de pausa do Cosmo (sugerido 40 min)?
- O controle de 'horário permitido' da família é faixa livre definida por eles ou faixas fixas pré-definidas?
- Em hardware abaixo do device-alvo mínimo, a redução de animações deve ser ativada automaticamente (ligado ao piso de desempenho da Seção 11)?

---

## 14 · Infraestrutura, Deploy, Backup & Disaster Recovery (SRE/DevOps)
**Objetivo:** Definir toda a operação de infraestrutura, entrega contínua, backup e recuperação de desastre do Constela Quest para que a plataforma sustente turmas inteiras entrando em horário de pico de aula sem perda de dados, com continuidade e observabilidade. Ancora no as-is real (frontend Vercel + backend Railway/FastAPI único + PostgreSQL, 1 instância, salas em memória) e no caminho de escala do doc quest/01, sem exigir que o dev/operador tome decisões de produto.

| # | Subseção | Propósito |
|---|----------|-----------|
| 14.1 | Cabeçalho, status & fontes | Metadados do doc e ancoragem nas fontes (quest/01 escalabilidade, RELATORIO-2026-07-09, memória producao-urls, ADR-0001). |
| 14.2 | Princípios de SRE do Quest | Fixa que o dimensionamento é o pico previsível de aula (metade das turmas às 7h30), não a média diária, e que dado de aprendizagem é imutável e insubstituível. |
| 14.3 | Topologia atual (as-is) — inventário | Descreve o que existe hoje: Vercel (constelaedu.com→www), Railway (backend + Postgres gerenciado), deploy no push para main, envs mínimos. |
| 14.4 | ⚠️ Matriz de ambientes (dev / staging / prod) | Define cada ambiente, seus limites de acesso, dados que pode conter e para que serve, incluindo o CI. |
| 14.5 | Paridade dev↔prod e o risco SQLite × Postgres | Regra de minimizar divergência entre dev (SQLite) e prod (Postgres); onde a diferença é aceitável e onde é armadilha (tipos JSON, índices, transações). |
| 14.6 | ⚠️ Provisionamento e Infra-as-Code | Como a infra é declarada/reproduzível (arquivos de config do provedor, versionados) para recriar um ambiente do zero. |
| 14.7 | Configuração por ambiente e variáveis | Catálogo de variáveis de ambiente e a convenção do projeto: default = produção no código, dev sobrescreve no .env (lição do PUBLIC_BASE_URL). |
| 14.8 | Gestão de segredos — inventário e cofre | Onde vivem segredos (chave JWT, credencial do banco, chave do provedor de IA, do CDN), quem acessa e proibição de commit em repo. |
| 14.9 | ⚠️ Rotação da chave JWT e token_version | Procedimento e cadência de rotação da chave de assinatura JWT sem derrubar sessões válidas, articulado com token_version dos alunos. |
| 14.10 | Pipeline de CI/CD | Estágios do pipeline (lint, testes da suíte, build, migração, deploy) disparados no push para main, e o que bloqueia a promoção. |
| 14.11 | Deploy do frontend (apps/quest PWA) | Build/publish do PWA e cache-busting do service worker (Workbox precache), evitando o problema histórico do cache de favicon/HTML preso. |
| 14.12 | Deploy do backend (FastAPI) | Build da imagem, health/readiness gate antes de receber tráfego e verificação de fumaça pós-deploy. |
| 14.13 | Rollback de código | Critérios objetivos de rollback e o procedimento (reverter versão anterior) para frontend e backend, incluindo o caso de rollback com migração já aplicada. |
| 14.14 | Feature flags e desacoplar deploy de release | Uso de flags (namespace quest.*) para publicar código dormente e ligar recurso por escola sem novo deploy — ponte com a Seção 19 (Live-ops). |
| 14.15 | Migrações de esquema — política expand/contract | Padrão de migração aditiva-primeiro (expandir, migrar dados, contrair) para toda mudança de tabela quest_*, coerente com o histórico imutável. |
| 14.16 | Migrações zero-downtime durante pico de aula | Regras para aplicar migração sem lock longo enquanto crianças jogam (índices concorrentes, colunas nullable, sem rewrite de tabela grande no horário de aula). |
| 14.17 | Janela segura e migrações destrutivas em duas fases | Quando drop/rename só pode ocorrer (código já não usa a coluna) e como agendar a fase destrutiva fora do horário letivo. |
| 14.18 | Backfill e recomputação de agregados | Como popular colunas novas e recomputar caches recalculáveis (quest_habilidades, saldo do ledger) em lote sem travar o banco. |
| 14.19 | Backup do Postgres — política | Frequência de snapshot, retenção de WAL e point-in-time recovery (PITR), cobrindo tentativas, ledger e outbox (dados imutáveis). |
| 14.20 | ⚠️ RPO e RTO — alvos por classe de dado | Define quanto dado se aceita perder (RPO) e em quanto tempo restaurar (RTO), diferenciando telemetria pedagógica de estado cosmético. |
| 14.21 | Restore testado — ensaio periódico | Rotina de teste de restauração de backup (game day) que prova o RTO/RPO na prática; um backup não testado não conta. |
| 14.22 | ⚠️ Criptografia e retenção dos backups | Criptografia em repouso/trânsito dos backups, prazo de retenção e local de armazenamento sob LGPD (dado de criança). |
| 14.23 | Isolamento multi-escola no backup/restore | Como restaurar ou exportar dados de uma única escola (escola_id) sem tocar nas demais, para incidente localizado e para LGPD. |
| 14.24 | ⚠️ Disaster Recovery — cenários e runbooks | Catálogo de desastres (perda do banco, região do provedor fora, corrupção de dados) com runbook passo-a-passo de recuperação para cada um. |
| 14.25 | Continuidade em queda de dependência | Comportamento quando cai o Postgres, o CDN de assets ou o provedor de IA — degradar em vez de falhar por completo. |
| 14.26 | Degradação graciosa e o PWA sob incidente | Como o shell offline e a fila de tentativas em IndexedDB (quest/01) protegem a criança durante indisponibilidade parcial do backend. |
| 14.27 | Observabilidade — logs estruturados | Formato de log (JSON, correlação por request/escola_id, sem dado sensível de criança), níveis e agregação central. |
| 14.28 | ⚠️ Observabilidade — métricas e dashboards | Métricas RED/USE (latência, erro, throughput por rota; CPU/memória/conexões do banco) e os dashboards mínimos de operação. |
| 14.29 | Observabilidade — tracing distribuído | Rastros correlacionados atravessando frontend→API→banco (e WebSocket) para diagnosticar lentidão no pico. |
| 14.30 | Fronteira observabilidade × auditoria (logs_auditoria) | Distingue telemetria operacional (efêmera) da auditoria de negócio imutável já existente no Edu; o que vai em cada uma. |
| 14.31 | ⚠️ SLI/SLO e error budget | Define os indicadores (disponibilidade da API, sucesso de login do aluno, latência de submissão de tentativa) e as metas de nível de serviço. |
| 14.32 | ⚠️ Alertas e política de plantão (on-call) | Quais condições alertam, por qual canal, com que severidade e quem responde fora do horário comercial. |
| 14.33 | Resposta a incidente — severidades e runbooks | Classificação de severidade, papéis (comandante do incidente), fluxo de mitigação e post-mortem sem culpa. |
| 14.34 | ⚠️ Janela de manutenção e comunicação às escolas | Como agendar manutenção respeitando o horário letivo e como avisar as escolas com antecedência — ponte com a Seção 21. |
| 14.35 | Página de status pública | Statuspage que informa incidente/manutenção em linguagem para gestor/professor, reduzindo volume de chamados. |
| 14.36 | ⚠️ CDN de assets (áudio, sprites, GLB) | Estratégia de armazenamento + CDN (Cloudflare R2 ou equivalente) para assets que não passam pelo backend, com cache/ETag e versionamento. |
| 14.37 | Redis — quando entra e o que passa a viver nele | Gatilho de adoção do Redis (~10 escolas/réplicas) e escopo: estado ao vivo das salas, presença, cache de rankings/catálogo, rate limit distribuído. |
| 14.38 | Escalonamento horizontal (API stateless, salas WS) | Como replicar o backend sem quebrar as salas em memória (migrar para Redis pub/sub) e o gatilho de extração do módulo quest. |
| 14.39 | Rate limiting distribuído | Migração do limitador por (código, IP) e por perfil de memória local para armazenamento distribuído quando houver réplicas. |
| 14.40 | ⚠️ Capacidade e teste de carga (cenário 7h30) | Cenário de carga de referência (turmas simultâneas de uma escola no início da aula) e como validar a capacidade antes de cada temporada. |
| 14.41 | ⚠️ Custos de infra e orçamento (FinOps) | Acompanhamento de custo por ambiente/serviço (banco, CDN, IA) e teto orçamentário que dispara alerta. |
| 14.42 | Segurança de infraestrutura | TLS obrigatório, hardening do host, atualização de dependências (dependabot), superfície de rede mínima e varredura de segredos — complementa a Seção 12. |
| 14.43 | Ambiente e dados de teste | Uso de dados sintéticos/anonimizados fora de produção; proibição de copiar dado real de criança para dev/staging. |
| 14.44 | Fuso e tempo na operação | Convenção UTC no banco, formatação pt-BR nos clientes, e o cuidado com data_ref de diárias/semanais e ultimo_dia_ativo — ponte com a Seção 16. |
| 14.45 | Checklist de prontidão de produção (go-live) | Lista objetiva que precisa estar verde antes de expor uma escola nova (backup testado, alertas ligados, SLO definido, runbooks prontos). |

**Perguntas ao dono:**
- Existe verba/decisão para um ambiente de staging dedicado, ou o fluxo permanece dev→prod direto no push para main?
- Quais alvos de RPO/RTO o negócio aceita (ex.: perder no máximo X minutos de dados; restaurar em até Y)?
- Qual stack de observabilidade adotar (nativo do Railway, Grafana/Prometheus, serviço pago) e há orçamento para isso?
- Quem assume o plantão (on-call) e qual disponibilidade/SLA prometemos às escolas contratantes?
- Qual janela de manutenção é aceitável dado que as escolas usam em horário de aula (madrugada BR? fim de semana?) e por qual canal comunicá-la?
- Confirmar o provedor de CDN (Cloudflare R2 foi citado) e o orçamento de armazenamento/banda para áudio e GLB dos avatares?
- Qual a política de retenção dos backups e onde são armazenados (região/provedor), atendendo à LGPD de dados de criança?
- Autorizar a rotação periódica da chave JWT e definir a cadência (ex.: trimestral) e o procedimento aceito de invalidação?

---

# Parte V — Produção & Operação

## 15 · Direção de Arte, Áudio & Pipeline de Assets
**Objetivo:** Fixar a linguagem visual, sonora e de personagens do Constela Quest e o pipeline industrial que produz, versiona, entrega e valida cada asset, subordinando toda escolha estética ao piso de desempenho do device-alvo (Princípio 17) e ao vocabulário/acessibilidade da criança.

| # | Subseção | Propósito |
|---|----------|-----------|
| 15.1 | Norte de arte & os 4 pilares em imagem | Traduz autonomia/progresso/vínculo/surpresa em diretrizes visuais concretas que orientam toda decisão estética. |
| 15.2 | Pilares do estilo visual (o 'look' Constela) | Define o estilo-mãe (cartoon espacial acolhedor do constela-play-v7): formas, contornos, brilho, materialidade. |
| 15.3 | Moodboard & referências aprovadas/proibidas | Lista referências-alvo e antirreferências (ex.: 'cara de dever de casa') para calibrar fornecedores e agentes de arte. |
| 15.4 | Design tokens como fonte única | Estabelece apps/quest/src/design/tokens.css do protótipo v7 como origem canônica de cor, espaçamento, raio, sombra e elevação 3D. |
| 15.5 | Paleta de cores (claro/escuro + por planeta) | Especifica paleta base e as paletas c1/c2/sky claro+escuro por planeta vindas do JSON tema (SUBJECTS). |
| 15.6 | Paleta acessível & modo daltônico | Garante contraste mínimo e variação não-dependente de cor (ícone+forma+áudio) exigida pelo Princípio 11. |
| 15.7 | Tipografia | Define famílias, escala e pesos, restritos a subset latin para caber no orçamento de precache (1,4MB→319KB). |
| 15.8 | Iconografia & sistema de símbolos | Padroniza ícones grandes e legíveis por não-leitores (Miguel, 6 anos), com significado reconhecível sem texto. |
| 15.9 | ⚠️ Design do avatar humanoide (camadas trocáveis) | Especifica o boneco estilo Roblox e seus slots: pele, cabelo, camiseta, calça, tênis, acessórios, costas(mochila/asas), mão(varinha), pet, skate. |
| 15.10 | Design do mascote Cosmo (2D SVG vivo) | Fixa anatomia, rosto vivo, física de mola e estados emocionais do Cosmo como companheiro que fala. |
| 15.11 | ⚠️ Papel definitivo do avatar (3D humanoide vs Cosmo 2D) | Resolve a contradição Revisão 3/4: quem é o avatar do jogador e o que vira legado a limpar. |
| 15.12 | ⚠️ Estratégia de renderização 2D vs 3D no núcleo | Decide DOM/SVG/CSS-first vs Three.js/R3F oficial e onde cada um pode ser usado, conciliando com o piso de hardware. |
| 15.13 | Personagens secundários por planeta | Define elenco de apoio de cada planeta (do JSON tema) e regras de consistência de estilo entre eles. |
| 15.14 | Ambientes e os 9 planetas (SUBJECTS/SCENES) | Especifica corpo, atmosfera, iluminação, primeiro-plano e partículas de Numéria, Palavras, Biozênia, Terra Nova, Chronos, Oxford, Colorium, Movi, Raízes. |
| 15.15 | Cena-casa (tela-home/lobby) e trilho de seleção | Define o cenário da tela-casa que troca de fundo por planeta e o trilho de matérias (rótulo infantil ainda pendente). |
| 15.16 | Sistema visual da Constelação | Especifica como estrelas nascem, brilham e se desenham para representar progresso (eu × eu) no mapa pessoal. |
| 15.17 | UI Kit / biblioteca de componentes | Cataloga Botao3D, Chip, Painel, Toast, Trilho e demais componentes com estados (vazio/carregando/erro/sucesso). |
| 15.18 | Alvos de toque, foco e ergonomia infantil | Fixa alvos ≥48px, 1 ação primária por tela e feedback de foco visível para 6–11 anos. |
| 15.19 | Arte de recompensa e celebração | Define as telas cheias de festa (XP/nível/estrela/conquista) proporcionais à raridade, sem punição visual do erro. |
| 15.20 | Arte dos itens cosméticos e raridade | Especifica linguagem visual por tipo (roupa/chapéu/óculos/acessório/pet/efeito/moldura/dança) e por raridade (comum→lendária). |
| 15.21 | Pets — o item aspiracional máximo | Define arte, animação de comemoração e presença no lobby dos pets como topo de desejo. |
| 15.22 | Skins do motor de corrida (bichinhos/espacial/trilha) | Fixa as 3 skins temáticas de um único motor de corrida, definidas por JSON de tema, não por código. |
| 15.23 | Efeitos, partículas e 'juice' | Define biblioteca de efeitos (confete, rastros, invocação do skate) e seu comportamento sob prefers-reduced-motion. |
| 15.24 | Direção de áudio (visão sonora) | Estabelece a identidade sonora acolhedora e o papel de música, efeitos e narração na experiência. |
| 15.25 | Trilha musical por planeta e lobby | Define trilhas por planeta (URL no JSON tema) e música da tela-casa, hoje ausentes (só WebAudio sintetizado). |
| 15.26 | Biblioteca de efeitos sonoros (SFX) | Cataloga SFX de UI, acerto, erro acolhido, recompensa e transições, migrando de sintetizado para gravado. |
| 15.27 | ⚠️ Narração pt-BR: TTS vs áudio gravado | Decide a estratégia definitiva de narração obrigatória (Web Speech API atual vs banco de áudios gravados em lote). |
| 15.28 | Guia de voz e casting do Cosmo | Especifica timbre, ritmo e direção de locução das falas do Cosmo conforme o guia ✓/✗ da Seção 02. |
| 15.29 | Pipeline de assets 3D (GLB/GLTF) | Define especificação técnica de malhas, materiais, rig, camadas trocáveis, compressão (Draco/KTX2) e orçamento de polígonos. |
| 15.30 | Pipeline de assets 2D (SVG/sprites/ilustração) | Define formato, otimização e resolução das ilustrações de planeta (arte SVG gerada por agentes) e sprites. |
| 15.31 | Pipeline de áudio (formatos e loudness) | Fixa formatos (ex.: ogg/aac/mp3), taxa, normalização de loudness e sprites de áudio para eficiência. |
| 15.32 | Convenção de nomeação de assets | Define nomenclatura estável (planeta/categoria/slug/variação) que casa com slug de itens e catálogo do banco. |
| 15.33 | Versionamento e imutabilidade de assets | Estabelece versionamento por conteúdo (hash), regra de nunca sobrescrever asset publicado e ligação à versao de missão. |
| 15.34 | Armazenamento, CDN e entrega | Define storage/CDN (Cloudflare R2 ou equivalente), cache HTTP com ETag e assets fora do backend. |
| 15.35 | ⚠️ Orçamento de performance (por device-alvo) | Fixa limites concretos de tamanho de download inicial, memória, texturas e draw calls por device-alvo mínimo. |
| 15.36 | Estratégia de carregamento e streaming | Define lazy-load do 3D, precache do shell, cache da jornada atual e degradação graciosa em wifi fraco. |
| 15.37 | Arte segura para localização | Proíbe texto embutido em imagem/áudio não externalizado, garantindo troca de idioma sem re-render de arte (liga à Seção 16). |
| 15.38 | ⚠️ Ferramentas e autoria (quem produz os assets) | Define ferramentas e responsáveis pela produção de GLBs, camadas trocáveis, ilustrações e áudios gravados. |
| 15.39 | Governança e fluxo de aprovação de assets | Estabelece o caminho asset novo → revisão → publicação e quem aprova a consistência com o design system. |
| 15.40 | Checklist de 'pronto' de arte (Definition of Done) | Lista os critérios de aceite de um asset: performance, acessibilidade, naming, versão e consistência de estilo. |

**Perguntas ao dono:**
- O avatar definitivo do jogador é o humanoide 3D (Three.js/R3F) ou o Cosmo 2D? (Revisão 3 vs Revisão 4, mesma data, ainda em conflito)
- Three.js/R3F passa a ser oficial no núcleo do frontend, exigindo reescrever o doc 01 (DOM/SVG/CSS-first, 'PixiJS não Three.js')? Se sim, com que limites?
- Quem produz os assets 3D (GLB) e as camadas trocáveis do avatar, e sob qual verba/prazo?
- A narração definitiva será áudio gravado em lote (TTS de qualidade) substituindo a Web Speech API? Quem grava e quando entra?
- As trilhas musicais e ilustrações por planeta são produzidas por fornecedor, por agentes de IA, ou mistos? Quem faz a curadoria de consistência?
- Qual é o device-alvo mínimo explícito (modelo/RAM/GPU de tablet e Chromebook da escola) para calibrar o orçamento de performance e o teto de 3D?
- Qual o orçamento máximo de download inicial e de memória aceitável no device-alvo (para fechar os limites de 15.35)?
- O Cosmo customizável (rosto/chapéu/costas/mão/pet já renderizáveis mas órfãos de UI) entra no escopo de arte ou é aposentado?

---

## 16 · Localização & i18n
**Objetivo:** Definir a arquitetura de internacionalização que mantém o pt-BR como língua canônica e obrigatória na narração (Princípio 9), preserva nomes próprios do universo e prepara — sem custo prematuro — a expansão para outros idiomas em textos, áudio, conteúdo pedagógico e formatação regional.

| # | Subseção | Propósito |
|---|----------|-----------|
| 16.1 | Objetivo e escopo do i18n | Delimita o que é localizável agora (interface, narração, conteúdo) e o que fica preparado para o futuro. |
| 16.2 | pt-BR como língua canônica (source of truth) | Fixa o português do Brasil como origem de toda tradução e como língua obrigatória da narração infantil. |
| 16.3 | Externalização de strings (zero texto hardcoded) | Obriga toda string visível a viver em catálogo de mensagens, nunca embutida em componente ou modelo. |
| 16.4 | Formato e chaveamento do catálogo de mensagens | Define estrutura de chaves, namespaces e formato (ex.: ICU MessageFormat) para UI, falas do Cosmo e sistema. |
| 16.5 | Plurais, gênero e concordância | Especifica regras de pluralização e concordância de gênero para frases que interpolam nome/apelido da criança. |
| 16.6 | Registro de nomes próprios não-traduzíveis | Congela Constela, Constela Quest, Cosmo, Constelação e os nomes de planeta (Numéria, Palavras…) como intraduzíveis. |
| 16.7 | Glossário canônico e vocabulário lúdico no i18n | Amarra o mapa interno→criança da Seção 02 ao sistema de tradução para consistência de termos. |
| 16.8 | Lint de palavras proibidas por locale | Automatiza a proibição de party/lobby/matchmaking/prova/exercício etc. em qualquer string infantil traduzida. |
| 16.9 | Localização de áudio/narração | Define como narração e falas do Cosmo são geradas/gravadas por locale, mantendo pt-BR como piso obrigatório. |
| 16.10 | Sincronia texto↔áudio | Garante que toda string narrada tenha áudio correspondente por locale e o vínculo chave→áudio se mantenha. |
| 16.11 | Formatação de números, datas e hora | Fixa armazenamento em UTC e formatação regional pt-BR (e futura por locale) nos clientes. |
| 16.12 | Convenções de ano/série escolar | Padroniza '1º Ano'…'5º Ano' (convenção de turmas.ano_escolar) e sua eventual tradução/adaptação de currículo. |
| 16.13 | BNCC e códigos independentes de idioma | Mantém códigos de habilidade (ex.: EF02MA05) como identificadores estáveis, não localizáveis. |
| 16.14 | Expansão de texto e resiliência de layout | Exige layouts que absorvam crescimento/encolhimento de texto entre idiomas sem quebrar alvos ≥48px. |
| 16.15 | Fontes e cobertura de glifos por locale | Concilia idiomas futuros com a restrição de subset de fonte para caber no orçamento de precache (Seção 15). |
| 16.16 | ⚠️ Prontidão para RTL e alfabetos não-latinos | Registra o nível de preparo para direção RTL e scripts não-latinos, sem implementar antes de decidido. |
| 16.17 | ⚠️ Localização do conteúdo pedagógico (catálogo) | Define como enunciados, dicas, explicações e mídia de desafios são traduzidos e alinhados a currículo local. |
| 16.18 | Seleção de locale e fallback | Especifica como o locale é escolhido (escola/aluno/aparelho) e a cadeia de fallback até pt-BR. |
| 16.19 | ⚠️ Pipeline e fluxo de tradução | Define ferramenta, formato de exportação/importação e quem traduz/revisa cada camada de conteúdo. |
| 16.20 | Memória de tradução e glossário compartilhado | Estabelece TM/glossário para consistência entre UI, narração e conteúdo ao longo do tempo. |
| 16.21 | QA de tradução em contexto | Define revisão in-app das strings (não só planilha), com foco em falas do Cosmo e não-leitores. |
| 16.22 | Governança de mudança de termo | Fixa que alterar termo canônico exige ADR e propaga por todas as línguas e áudios. |
| 16.23 | ⚠️ Roadmap de idiomas futuros | Registra quais idiomas entram, em que fase e com que profundidade (UI/áudio/conteúdo). |

**Perguntas ao dono:**
- Há intenção real de outros idiomas além do pt-BR (ex.: espanhol para LATAM, inglês)? Quais e em que fase do roadmap?
- Quanto investir agora em infraestrutura i18n vs entregar pt-BR-only e adaptar depois (o espelho EN dos docs é só para o time internacional)?
- O conteúdo pedagógico (missões/desafios BNCC) é multilíngue ou o catálogo é por país/currículo? Como isso se relaciona com o software futuro de matérias+questões?
- Em idiomas futuros a narração será gravada por locale ou TTS? Quem produz e revisa?
- Precisamos preparar RTL/alfabetos não-latinos ou o horizonte é apenas línguas latinas?
- Quem é o responsável e qual a ferramenta oficial do pipeline de tradução (contratada, comunidade, ou IA com revisão humana)?

---

## 17 · Telemetria, Métricas & Analytics
**Objetivo:** Definir a métrica-norte, os KPIs, os guardrails de aprendizado e de saúde de uso, e a taxonomia de eventos do Constela Quest, usando exclusivamente telemetria própria e mínima (Princípios 3 e 18), sem SDK de terceiros, com privacidade LGPD embutida por design.

| # | Subseção | Propósito |
|---|----------|-----------|
| 17.1 | Objetivo e princípios da telemetria | Fixa telemetria própria, mínima e de finalidade pedagógica/de produto, sem rastreamento de terceiros nem anúncios. |
| 17.2 | ⚠️ Métrica-norte quantificável | Converte 'a criança volta amanhã?' em métrica-norte medível com alvo numérico (hoje só proposta a calibrar). |
| 17.3 | ⚠️ Guardrails de aprendizado | Define métricas e limiares que impedem otimizar retenção às custas do aprendizado real (domínio BNCC). |
| 17.4 | ⚠️ Guardrails de saúde de uso e bem-estar | Define sinais e limites de uso saudável (sessão longa, teto diário, pausa do Cosmo) como métrica de proteção. |
| 17.5 | Árvore de KPIs e relação com o norte | Organiza a hierarquia de indicadores e como cada um sobe até a métrica-norte e respeita os guardrails. |
| 17.6 | ⚠️ KPIs de retenção (D1/D7/D30) | Define retenção por coorte e seus alvos, base da régua de corte de fase do roadmap. |
| 17.7 | KPIs de engajamento | Define sessões/dia, duração, missões concluídas e uso fora do horário de aula (sinal de vontade genuína). |
| 17.8 | KPIs de aprendizado | Define domínio por habilidade BNCC, taxa de acerto e curva de dificuldade adaptativa como medida pedagógica. |
| 17.9 | KPIs de adoção/negócio | Define escolas ativas, turmas ativas e alunos ativos como saúde do produto para o comprador. |
| 17.10 | Taxonomia de eventos — convenção de nomes | Fixa padrão de nomeação e granularidade de eventos, alinhado ao vocabulário interno (não ao infantil). |
| 17.11 | Catálogo de eventos do produto | Lista os eventos-núcleo (início/fim de tentativa, resposta, subir de nível, conquista, sessão, alerta de dificuldade). |
| 17.12 | Esquema e versionamento de eventos | Define contrato de payload por evento e política de versão para não quebrar análises históricas. |
| 17.13 | Dicionário de propriedades | Documenta cada propriedade de evento, tipo e significado para leitura consistente. |
| 17.14 | Identidade e pseudonimização nos eventos | Garante que eventos usem perfil_id/escola_id e nunca PII direta da criança (Princípio 3). |
| 17.15 | Instrumentação no cliente | Define onde e como o app dispara eventos, incluindo fila offline (IndexedDB) e sincronização ao reconectar. |
| 17.16 | Telemetria derivada no servidor | Define eventos/agregações originados de quest_tentativas (imutável) e quest_outbox, sem depender do cliente. |
| 17.17 | Pipeline e armazenamento de dados | Especifica o fluxo tentativas→agregados e onde vivem os dados brutos vs derivados. |
| 17.18 | Jobs de agregação e recomputação | Define a rotina que mantém quest_habilidades como cache recalculável, sem agregado órfão após correção. |
| 17.19 | Dashboards internos de produto | Define os painéis do time (norte, guardrails, funis) e sua fonte de dados. |
| 17.20 | Métricas expostas ao professor (Edu) | Delimita quais agregados viram painel do professor (panorama, mapa BNCC, erros comuns) sem expor moedas/loja. |
| 17.21 | ⚠️ Privacidade e LGPD na telemetria | Define retenção configurável (padrão 24 meses a confirmar) e gatilho de anonimização na saída do aluno. |
| 17.22 | Minimização de dados (o que NÃO coletar) | Lista explicitamente dados proibidos (foto, localização, texto livre) e o teto do que é coletável. |
| 17.23 | Consentimento e escopo de opt-in | Amarra a coleta ao consentimento da escola/responsável e ao opt-in social por escola. |
| 17.24 | Semântica offline/sync da telemetria | Define deduplicação, ordenação e flag origem (web/pwa-offline) das tentativas sincronizadas. |
| 17.25 | Amostragem e controle de volume | Define se/como amostrar eventos de alto volume sem perder fidelidade dos KPIs-núcleo. |
| 17.26 | Acesso a dados e auditoria | Registra acessos de adultos a dados de aluno via logs_auditoria e limita quem lê telemetria bruta. |
| 17.27 | Sinais anti-farm e anti-abuso | Define métricas que detectam farm de XP e abuso de login, alimentando rate-limit e economia auditável. |
| 17.28 | ⚠️ Prontidão para experimentação/A-B | Define se e como rodar experimentos, com a restrição ética de público infantil. |
| 17.29 | Alertas de anomalia de métrica | Define monitoramento que dispara quando norte/guardrails saem da faixa esperada. |
| 17.30 | Definição de 'conseguimos medir o norte' | Critério de pronto: o mínimo de instrumentação para calcular métrica-norte e guardrails de forma confiável. |

**Perguntas ao dono:**
- Qual a definição quantitativa da métrica-norte e seus alvos (ex.: retenção D1/D7/D30 mínimos por coorte)?
- Quais são os limiares dos guardrails de aprendizado que, se violados, invalidam um ganho de retenção?
- Quais são os limites de saúde de uso (duração máxima saudável, teto diário, gatilho de pausa) tratados como guardrail formal?
- Confirma retenção de telemetria detalhada em 24 meses e o gatilho exato de anonimização quando o aluno sai da escola?
- É permitido rodar experimentos A/B com crianças? Sob quais limites éticos e de consentimento?
- Retenção tem ou não precedência formal sobre aprendizado? (o doc 00 hoje não afirma precedência até esta calibração)

---

## 18 · QA & Estratégia de Testes
**Objetivo:** Definir a estratégia completa de qualidade — testes de backend, frontend, mecânicas e gabarito, playtest com crianças, matriz de dispositivos-alvo, CI e critérios de pronto — de modo que cada fase entregue algo que uma criança real consegue usar e quer repetir, sem regressão nas invariantes imutáveis.

| # | Subseção | Propósito |
|---|----------|-----------|
| 18.1 | Objetivo e filosofia de QA | Fixa a régua central ('a criança consegue usar sozinha e quer voltar?') como critério máximo de qualidade. |
| 18.2 | Pirâmide e estratégia de testes | Define a proporção entre unidade, integração, E2E e testes manuais/playtest e onde cada risco é coberto. |
| 18.3 | Testes unitários de backend (services puros) | Cobre regra de negócio sem FastAPI: progressao, economia, conquistas, tarefas, habilidades, salas. |
| 18.4 | Testes de integração/API | Valida rotas /quest/* com papéis, isolamento por escola_id e contratos Pydantic. |
| 18.5 | Testes de gabarito e autoridade do servidor | Garante que o catálogo sai sem gabarito e que o backend confere a resposta crua (criança com DevTools não fabrica XP). |
| 18.6 | Testes de invariantes de economia/ledger | Prova imutabilidade do ledger, recomputabilidade do saldo e que erro nunca subtrai moedas/estrelas. |
| 18.7 | Testes de mecânicas (registry plugável) | Cobre cada plugin (quiz, arrastar, ligar, memória, completar, sequência, caça-palavras) pelo contrato MecanicaProps. |
| 18.8 | Validação de conteúdo do catálogo | Valida schema JSON por mecânica, presença de áudio de instrução, dica, explicação e código BNCC em cada desafio. |
| 18.9 | Testes de frontend (componentes) | Cobre componentes do design system e telas com estados vazio/carregando/erro/sucesso. |
| 18.10 | Testes E2E de fluxos-chave | Valida login por código, cerimônia da 1ª vez, jogar missão e receber recompensa ponta a ponta. |
| 18.11 | Testes automatizados de acessibilidade | Verifica alvos ≥48px, contraste, navegação sem leitura, prefers-reduced-motion e modo daltônico. |
| 18.12 | QA de áudio e narração | Confere que toda instrução tem áudio pt-BR e o botão 'ouvir de novo' funciona em cada passo. |
| 18.13 | Testes de PWA/offline | Valida shell offline, cache da jornada atual, fila append-only de tentativas e sync ao reconectar. |
| 18.14 | Testes de multiplayer/WebSocket | Cobre salas, convite, reconexão de 30s e a regra de que partida abandonada nunca pune. |
| 18.15 | Testes de performance e carga | Simula o pico de aula (metade das turmas entrando às 7h30) e valida o orçamento do device-alvo. |
| 18.16 | ⚠️ Matriz de dispositivos e navegadores-alvo | Define o conjunto exato de tablets/Chromebooks e navegadores em que o produto deve rodar bem. |
| 18.17 | ⚠️ Protocolo de playtest com crianças | Define método, consentimento, faixa etária, roteiro e coleta de observação com 6–11 anos. |
| 18.18 | Teste de corredor na escola-piloto | Formaliza o teste na escola-piloto como critério de pronto de fase (login sem ajuda foi o de Q0). |
| 18.19 | Métricas de usabilidade do playtest | Define o que se mede no playtest (tempo até jogar, travas, pedido de 'jogar de novo'). |
| 18.20 | QA de localização | Valida strings externalizadas, ausência de palavra proibida e sincronia texto↔áudio por locale (liga à Seção 16). |
| 18.21 | Testes de segurança | Cobre rate-limit por (código, IP), isolamento de JWT aluno vs Edu e escopo mínimo do papel aluno. |
| 18.22 | Testes de conformidade LGPD/privacidade | Verifica coleta mínima, opt-in social, retenção configurável e anonimização na saída. |
| 18.23 | Suíte de regressão | Define o conjunto que trava as 16+2 invariantes imutáveis contra regressão em cada mudança. |
| 18.24 | Dados de teste, fixtures e seeds | Padroniza seeds de catálogo BNCC e fixtures de perfil/turma para testes reprodutíveis. |
| 18.25 | Pipeline de CI e portões | Define os gates automáticos (lint, testes, build, acessibilidade) que bloqueiam merge. |
| 18.26 | Ambientes de QA (staging/piloto) | Define ambientes de teste, dados sintéticos e a fronteira com a escola-piloto real. |
| 18.27 | ⚠️ Fluxo de QA de conteúdo pedagógico | Define revisão pedagógica humana das missões, com curadoria especial de ERER antes de publicar. |
| 18.28 | Triagem de bugs e severidade | Padroniza classificação de severidade e prioridade, com peso extra a itens que afetam criança não-leitora. |
| 18.29 | ⚠️ Critério de pronto e portão de release | Consolida a Definition of Done por fase e o que precisa passar para liberar em produção. |
| 18.30 | QA de rollout/piloto e beta | Define a estratégia de liberação gradual e coleta de feedback antes da abertura ampla. |

**Perguntas ao dono:**
- Qual é a matriz exata de dispositivos e navegadores-alvo (modelos de tablet/Chromebook e versões) que definem 'roda bem'?
- Qual a cadência dos playtests com crianças, e qual o processo de consentimento/logística com as escolas-piloto?
- Quem faz a revisão pedagógica das missões e a curadoria de ERER, e esse aval é bloqueante para publicar?
- Quais são os limiares numéricos do portão de release (cobertura de testes, resultado de playtest, métricas mínimas)?
- Escopo de conteúdo do primeiro release jogável: 1 planeta profundo (Matemática) ou 9 rasos? (afeta o que QA precisa cobrir)

---

## 19 · Live-ops & Config Remota
**Objetivo:** Definir como o Constela Quest é operado ao vivo sem redeploy — temporadas, eventos, feature flags, kill-switch, regras numéricas por escola e publicação de conteúdo — mantendo a economia auditável, as regras não-hardcoded e o controle social granular exigidos pelos princípios imutáveis.

| # | Subseção | Propósito |
|---|----------|-----------|
| 19.1 | Objetivo e princípio 'config sobre deploy' | Fixa que regras, conteúdo e ajustes de operação mudam por configuração, não por novo build. |
| 19.2 | Arquitetura de config remota | Define o uso de configuracoes (namespace quest.*) como base de toda parametrização por escola. |
| 19.3 | Hierarquia e precedência de config | Estabelece a cadeia padrão-no-código → override por escola (→ turma/aluno onde aplicável) e como resolvê-la. |
| 19.4 | Registro de regras numéricas não-hardcoded | Cataloga XP, multiplicadores, preços, tetos e curva de nível como valores configuráveis com padrão no código. |
| 19.5 | Sistema de feature flags | Define flags para ligar/desligar funcionalidades por escola/fase sem redeploy. |
| 19.6 | Kill-switch e alavancas de emergência | Define desligamentos rápidos (ex.: social, multiplayer, IA) para conter incidente sem derrubar o produto. |
| 19.7 | ⚠️ Controles sociais por escola/turma/aluno | Especifica o opt-in social por escola e os desligamentos por turma e por aluno (social_ativo). |
| 19.8 | Ciclo de vida de temporadas | Define abertura, vigência e encerramento de quest_temporadas e a troca de tema visual do lobby. |
| 19.9 | ⚠️ Configuração do passe de temporada | Especifica a trilha de recompensas do passe gratuito e seu formato exato de operação. |
| 19.10 | Eventos temáticos: agendamento e config | Define agendamento e config de quest_eventos (Festa Junina, Dia das Crianças…) com missões e itens limitados. |
| 19.11 | Rotação da loja | Configura a rotação semanal (4–6 itens) + seção fixa sem deploy, com escassez honesta (item volta no ano seguinte). |
| 19.12 | Config de tarefas diárias/semanais | Parametriza quantidade, alvos e viés para habilidades fracas das missões periódicas. |
| 19.13 | Parâmetros da dificuldade adaptativa | Expõe janelas, limiares (≥85% sobe, ≤40% desce) e faixas como config ajustável por escola. |
| 19.14 | Publicação de conteúdo e versionamento do catálogo | Define o fluxo rascunho→publicada→arquivada e como tentativas guardam a versão jogada da missão. |
| 19.15 | ⚠️ Interface de autoria/publicação do catálogo | Define por qual interface o conteúdo pedagógico é cadastrado e publicado, e a conexão com o software futuro de matérias+questões. |
| 19.16 | Hotfix de conteúdo ao vivo | Permite corrigir uma missão/desafio publicado sem redeploy, gerando nova versão auditável. |
| 19.17 | Config de onboarding de escola | Parametriza consentimento LGPD, opt-in social e ativação de recursos no ingresso de uma nova escola. |
| 19.18 | Auditoria e rollback de config | Registra toda mudança de config em logs_auditoria e permite reverter a um estado anterior conhecido. |
| 19.19 | Validação e defaults seguros de config | Garante que valor ausente/ inválido cai no padrão do código, nunca quebra o jogo da criança. |
| 19.20 | Cache e propagação de config | Define cache HTTP (ETag) e invalidação para que mudança de config chegue rápido sem sobrecarregar o backend. |
| 19.21 | Jobs agendados e cron de operação | Define tarefas temporais: início/fim de temporada, renovação do escudo da Chama (2ª feira), reset semanal de ranking. |
| 19.22 | ⚠️ Rollout gradual e config em estágio | Permite liberar mudança para um subconjunto de escolas antes da abertura geral. |
| 19.23 | ⚠️ Painel operacional / control room | Define quem opera o live-ops e por qual painel (flags, temporadas, eventos, kill-switch). |
| 19.24 | Runbook de incidente e kill-switch | Documenta o procedimento passo a passo para acionar alavancas de emergência sob incidente. |
| 19.25 | Alvo e segmentação multi-escola de config | Define como uma config/evento é direcionada a escolas/turmas específicas respeitando o isolamento por escola_id. |
| 19.26 | Documentação e catálogo de chaves de config | Mantém a lista viva de chaves quest.* com tipo, default, faixa e efeito de cada uma. |
| 19.27 | Escala do live-ops (Redis/réplicas) | Define os gatilhos e a mudança para Redis (salas/presença/cache) conforme a carga cresce. |

**Perguntas ao dono:**
- Qual é o formato exato do passe de temporada (níveis, ritmo, recompensas) confirmado como 100% gratuito?
- Por qual interface o catálogo pedagógico é cadastrado e publicado, e como ela se integra ao software futuro de matérias+questões?
- O social vem ligado ou desligado por padrão numa escola nova, e o alcance de amizade no lançamento é 'mesma turma' ou 'mesma escola'?
- Quem opera o live-ops (temporadas, eventos, flags, kill-switch) e por qual painel — reaproveita o Edu ou é ferramenta nova?
- Podemos fazer rollout gradual/segmentado de config e conteúdo entre escolas, e com quais critérios?
- Confirma que não há compras in-app em nenhuma fase e que toda regra numérica permanece configurável por escola?
- Ed. Física e ERER entram só na Q5 com curadoria própria, conforme documentado?

---

## 20 · Migração de Dados & Importação de Plataformas Externas
**Objetivo:** Especificar toda a ingestão e migração de dados de terceiros para o Constela Quest — matrículas vindas do Constela Edu e o reconhecimento/casamento/fusão dos cadastros antigos criados por relatórios Matific/Elefante (PDF/XLSX) — com idempotência, deduplicação, dry-run, rollback e auditoria. Reflete a política real já validada ('casar é automático e reversível; fundir é sempre manual') e a regra de ouro de que um falso-positivo é muito pior que um falso-negativo, de modo que um dev implemente sem tomar decisões de produto.

| # | Subseção | Propósito |
|---|----------|-----------|
| 20.1 | Cabeçalho, status & fontes | Metadados e ancoragem: quest/04, lista_piloto.py/importacoes.py do Edu, memória importacao-matriculas-casamento e arquivos-exemplo-relatorios em Downloads. |
| 20.2 | Escopo da migração/importação | Delimita o que entra (roster de matrículas, casamento de cadastros antigos, provisionamento Quest) e o que fica fora, evitando confundir com autoria de conteúdo (Seção 06). |
| 20.3 | Modelo mental — identidade vive no Edu | Fixa que o Quest não duplica cadastro: alunos/turmas/escolas são do núcleo Edu e o Quest apenas deriva quest_perfis e credenciais (dependência de mão única). |
| 20.4 | Fontes de dados e formatos | Catálogo das fontes: matrículas do Edu (Lista Piloto XLSX), relatórios Matific (PDF/XLSX) e Elefante (turma/individual), com o layout esperado de cada. |
| 20.5 | Por que PDF/XLSX (sem API self-serve) | Registra a restrição herdada: Matific/Elefante não expõem API self-serve, então a coleta é por arquivo exportado — não é escolha, é limitação externa. |
| 20.6 | Verdade de base dos parsers | Aponta os arquivos-exemplo reais em Downloads como a fonte de verdade dos parsers; nenhum parser muda sem validar contra eles. |
| 20.7 | Pipeline de importação — estágios | Visão de estágios: upload → parse → normalizar → casar → pré-visualizar → aplicar → auditar, com o dado nunca alterando produção antes da confirmação. |
| 20.8 | Parser de relatório Matific (PDF/XLSX) | Contrato de extração do Matific: colunas/campos lidos, nome abreviado, ausência de RA e como os erros de layout são reportados. |
| 20.9 | Parser de relatório Elefante (turma/individual) | Contrato de extração do Elefante nos dois formatos (turma e individual) e os campos que produz. |
| 20.10 | Normalização de nomes | Regras determinísticas de normalização (acentos, caixa, tokenização, abreviação→completo) que alimentam o casamento sem ambiguidade. |
| 20.11 | Importação de matrículas do Edu (Lista Piloto) | Fluxo confirmar_matriculas: ingerir a planilha oficial da escola como fonte canônica de roster com nome completo, RA e turma. |
| 20.12 | Chave de identidade e precedência de casamento | Ordem determinística de casamento: RA → nome completo exato + turma → abreviação POSICIONAL, e só quando inequívoco na turma. |
| 20.13 | Tratamento de RA placeholder/ausente | RA como '0', 'S/RA' ou curto demais é tratado como ausência (ra_util), nunca como chave de casamento. |
| 20.14 | Casar (atualizar cadastro antigo) — automático e reversível | Define o casamento: substituir o nome abreviado antigo pelo completo mantendo o mesmo aluno_id; é automático porque é reversível. |
| 20.15 | Fundir cadastros distintos — sempre manual | Regra dura: unir dois aluno_id distintos é irreversível e NUNCA automático; fica para a ferramenta manual 'Fundir alunos'. |
| 20.16 | Reconhecimento de cadastros já existentes | Como o import detecta que um aluno já foi criado por upload de relatório anterior e evita recriá-lo (dedup natural). |
| 20.17 | Overlap de turma e desambiguação | Uso de série+letra da turma (ignorando a palavra 'ano' e o turno) para desambiguar homônimos, com lista de sets por turma — nunca unir tokens de anos diferentes. |
| 20.18 | Vetos de casamento | Condições que vetam um casamento aparentemente válido (data de nascimento divergente e outros sinais de contradição). |
| 20.19 | Regra de ouro — falso-positivo ≫ falso-negativo | Fixa que renomear a criança errada é muito pior que deixar uma duplicata; na dúvida, cria novo cadastro + aviso ao gestor. |
| 20.20 | Idempotência do import | Reexecutar o mesmo arquivo não duplica nem altera duas vezes; a operação converge para o mesmo estado. |
| 20.21 | Deduplicação | Chave natural e heurística de detecção de duplicatas dentro do próprio arquivo e contra a base existente. |
| 20.22 | Resolução de conflitos — fila de revisão | Casos ambíguos (ex.: 'AGATHA V' casando 3 crianças) vão para uma fila que o gestor decide manualmente, nunca resolvida por adivinhação. |
| 20.23 | Dry-run (pré-visualização) | Modo que mostra exatamente o que será casado, criado, ignorado e marcado como ambíguo antes de qualquer escrita. |
| 20.24 | Aplicação transacional e rollback | O import é atômico por lote; falha no meio reverte tudo, e há um caminho de desfazer um import já aplicado. |
| 20.25 | ⚠️ Provisionamento Quest a partir de alunos | Como criar quest_perfis + quest_credenciais_aluno para os alunos matriculados, com isolamento por escola_id. |
| 20.26 | Geração de codigo_login e qr_token | Regras de geração de código falável (só letras+números, ex. SOL1234) e qr_token únicos na migração, com tratamento de colisão. |
| 20.27 | Preservação de histórico ao casar | Ao casar, snapshots/leituras/notas do cadastro antigo são preservados (mesmo aluno_id) — o import nunca destrói telemetria. |
| 20.28 | Aluno transferido/arquivado | Como o import trata aluno que saiu: perfil pausado e 'cartão descansando', nunca 'código errado' que faça a criança se culpar. |
| 20.29 | ⚠️ Fusão de perfis Quest | Quando dois quest_perfis precisam ser fundidos, regras para combinar progresso, ledger e tentativas sem violar a imutabilidade — sempre manual. |
| 20.30 | Auditoria da migração | Todo vínculo que troca identidade gera log aluno.identidade_vinculada (quem/quando/o quê) em logs_auditoria, para reconstruir qualquer decisão. |
| 20.31 | Estados de erro do import | Comportamento com arquivo inválido, colunas faltando, encoding errado ou PDF ilegível — mensagem clara ao gestor, zero escrita parcial. |
| 20.32 | Estado vazio e parcial | Planilha vazia ou cobrindo só parte da turma não apaga quem não está nela; ausência não é sinal de exclusão. |
| 20.33 | Limites e desempenho | Import de escola grande em lote, com paginação/streaming e teto de tamanho, sem estourar timeout (ponte com a Seção 14). |
| 20.34 | Relatório pós-import | Sumário legível ao gestor: quantos casados, criados, ambíguos e ignorados, com a lista dos casos que exigem atenção. |
| 20.35 | Reprocessamento e correção | Como corrigir um import errado (reverter o vínculo, reimportar) preservando o histórico e sem renomear crianças em cascata. |
| 20.36 | Segurança e LGPD do import | Tratamento do arquivo-fonte com dados de criança: acesso restrito, retenção mínima e descarte após o import — complementa a Seção 12. |
| 20.37 | Convenções e i18n | ano_escolar herdado de turmas, datas em UTC, nomes em pt-BR e o cuidado com caracteres latin-1 nos PDFs gerados. |
| 20.38 | Testes com nomes reais | Suíte que usa nomes reais da Lista Piloto (inclusive >28 letras e homônimos), porque bugs de casamento só aparecem fora dos nomes curtos de teste. |
| 20.39 | ⚠️ Migração inicial da escola-piloto (cutover) | Plano de corte da primeira escola: big-bang vs. por turma vs. período de coexistência, e como validar antes de expor as crianças. |
| 20.40 | ⚠️ Integração futura com o software de matérias+questões | Como o catálogo/identidade se conectará à plataforma de ensino própria do dono — fonte única, import ou espelho — a definir. |
| 20.41 | ⚠️ Import de progresso pedagógico de terceiros | Se e como desempenho histórico do Matific/Elefante entra no Quest, ou se o Quest começa do zero pedagogicamente. |

**Perguntas ao dono:**
- Além das matrículas (roster), deve-se importar progresso/desempenho histórico do Matific/Elefante para dentro do Quest, ou o Quest começa do zero pedagogicamente?
- O quest_perfil é criado automaticamente para todo aluno matriculado, ou só quando o professor gera os cartões / o aluno entra pela 1ª vez?
- Como se dará a integração futura com o software de matérias+questões (fonte única de verdade, importação ou espelho)?
- Qual o plano de corte (cutover) da escola-piloto: big-bang, por turma, ou período de coexistência Edu/Matific/Elefante?
- Por quanto tempo o arquivo-fonte (PDF/XLSX com dados de criança) pode ser retido após o import, sob a LGPD?
- Confirmar que a fusão de perfis Quest (progresso/ledger/tentativas), e não só de cadastro Edu, segue a mesma política manual 'na dúvida, não funde'?

---

## 21 · Suporte, Sucesso do Cliente & Operação de Escola
**Objetivo:** Definir como uma escola é levada ao sucesso operacional com o Constela Quest — onboarding, helpdesk ao professor, operação em sala (cartões e login), fluxo de incidente e comunicação, FAQ, métricas de sucesso do cliente e offboarding — de forma executável por um time de suporte sem tomar decisões de produto. Ancora nas realidades do produto (tablet compartilhado, wifi instável, cartões PDF, login código-só, zero configuração para o professor).

| # | Subseção | Propósito |
|---|----------|-----------|
| 21.1 | Cabeçalho, status & fontes | Metadados e ancoragem: quest/04 (login e cartões), quest/05 (critérios de pronto por fase), RELATORIO-2026-07-09, Seções 10/12/14. |
| 21.2 | Personas de suporte e operação | Mapeia quem o suporte atende (gestor/coordenador, professor, família/responsável) e o admin global interno, com o que cada um pode e precisa fazer. |
| 21.3 | Modelo de operação (autosserviço vs. suporte) | Divide o que a escola resolve sozinha (regenerar cartão, ligar social) do que exige suporte, e a fronteira entre operação e engenharia. |
| 21.4 | Onboarding da escola — jornada | Passo a passo do primeiro contrato até a primeira aula jogável, com marcos e responsável por cada etapa. |
| 21.5 | Pré-requisitos técnicos da escola | Checklist de dispositivos (tablet/Chromebook), navegador, instalação do PWA e requisitos de wifi antes de ativar. |
| 21.6 | ⚠️ Ativação e configuração inicial | Ligar a escola: configurações namespace quest.* (social opt-in/opt-out, horários, retenção) e valores padrão de fábrica. |
| 21.7 | Termo de consentimento LGPD no onboarding | Fornecer o documento padrão de consentimento dos responsáveis para a escola coletar assinatura, como já faz com autorização de imagem — complementa a Seção 12. |
| 21.8 | Provisionamento de turmas e alunos | Como as turmas/alunos entram (importação da Seção 20) e viram perfis prontos para jogar. |
| 21.9 | Geração e impressão dos cartões | Fluxo do professor no Edu: PDF por turma (2×4) + página 'só do professor' (nome→código e roteiro), e o caso do cartão individual. |
| 21.10 | Roteiro da 1ª aula (corredor de login) | Script operacional da primeira sessão: 'Quem vai jogar?', digitar código, 'Sou eu!', cerimônia de boas-vindas — o teste de corredor da escola-piloto. |
| 21.11 | ⚠️ Treinamento do professor | Material, formato e duração da capacitação mínima do professor para conduzir a aula sem depender do suporte. |
| 21.12 | ⚠️ Helpdesk — canais e SLA | Canais oficiais de atendimento, horário e tempo-alvo de resposta por severidade. |
| 21.13 | Categorização de chamados | Taxonomia de tickets (login, áudio, offline, cartão, social, pedagógico, cobrança) que alimenta métricas e roteamento. |
| 21.14 | Troubleshooting do professor — árvore de decisão | Fluxograma de diagnóstico de primeira linha que o professor/gestor segue antes de abrir chamado. |
| 21.15 | Troubleshooting: criança não entra | Diagnóstico de falha de login (código digitado errado, QR ilegível, rate-limit por código+IP atrás do NAT da escola) e a mensagem correta em cada caso. |
| 21.16 | Troubleshooting: 'É você?' e conta trocada | Como resolver a criança do turno seguinte herdando o astronauta anterior no tablet compartilhado (confirmação de boot, sair da conta). |
| 21.17 | Troubleshooting: app não abre / cache do PWA | Diagnóstico de shell offline preso, service worker desatualizado e a lição do cache (trocar nome de arquivo, não só query string). |
| 21.18 | Troubleshooting: áudio/narração não toca | Passos para o caso crítico de não-leitores sem áudio (permissão do navegador, volume do aparelho, fallback de narração). |
| 21.19 | Regeneração de cartões em campo | Reemitir cartão individual sem derrubar a turma; o código nunca muda (a criança decora), só o QR é trocado. |
| 21.20 | Cartão perdido/roubado e revogação de QR | Fluxo de revogação via token_version que invalida cartões antigos, e quando isso é necessário. |
| 21.21 | Aluno transferido/arquivado | Operação de saída de um aluno: perfil pausado e mensagem 'cartão descansando', preservando a autoestima da criança. |
| 21.22 | Fluxo de incidente — detecção a escalonamento | Como o suporte detecta, triagem e escala um incidente de plataforma para a engenharia — ponte com a Seção 14 (severidades/on-call). |
| 21.23 | Comunicação de incidente às escolas | Canal, tom (para adulto, não técnico) e cadência das atualizações durante uma indisponibilidade. |
| 21.24 | Comunicação de manutenção programada | Aviso antecipado de janela de manutenção respeitando o horário letivo — coordenado com a Seção 14. |
| 21.25 | Base de conhecimento e FAQ | Estrutura da central de ajuda por audiência (professor, gestor, família) com os artigos mínimos de lançamento. |
| 21.26 | FAQ da família | Perguntas do responsável sobre o Portal da Família, privacidade, controles (social/horário) e ausência de compras. |
| 21.27 | Solicitações LGPD dos titulares | Fluxo operacional para pedidos de acesso/correção/exclusão/anonimização de dados de criança, com prazos e quem autoriza — complementa a Seção 12. |
| 21.28 | Denúncia/moderação social encaminhada | Como um relato de comportamento (bloqueio/denúncia) chega ao suporte e é tratado — ponte com a Seção 09 (Social). |
| 21.29 | ⚠️ Métricas de sucesso do cliente | Indicadores de ativação, adoção e engajamento por escola (alunos ativos/semana, missões concluídas, professores usando o painel). |
| 21.30 | Health score e sinais de churn | Composição de um score de saúde da conta e os sinais que disparam intervenção proativa do sucesso do cliente. |
| 21.31 | ⚠️ Playbook de renovação e expansão | Cadência de acompanhamento (QBR) e ações para renovar contrato e expandir para mais turmas/escolas da rede. |
| 21.32 | Coleta de feedback e loop com produto | Como pedidos e dores das escolas viram entrada priorizada no roadmap (Seção 23) sem virar promessa não gerenciada. |
| 21.33 | Offboarding da escola/turma | Encerramento ordenado: desativação de acesso, exportação do que a escola tem direito e comunicação às famílias. |
| 21.34 | Retenção/anonimização no offboarding | O que acontece com os dados após a saída (perfil pausado → anonimização após o prazo), coerente com a política de retenção — complementa a Seção 12. |
| 21.35 | Continuidade pedagógica na saída | O que a família/aluno leva consigo (certificados PDF, resumo de progresso) para que a saída não apague o valor construído. |
| 21.36 | Ferramentas internas de suporte | Painel administrativo e recursos que o suporte usa para diagnosticar (visão de escola/turma) sem acesso indiscriminado. |
| 21.37 | ⚠️ Runbook de acesso a dado de aluno pelo suporte | Política de 'entrar como'/impersonar e de consulta a dado de criança pelo suporte, sempre auditada em logs_auditoria. |
| 21.38 | i18n e acessibilidade dos materiais de suporte | Materiais em pt-BR, linguagem simples para o gestor/família e coerência com a acessibilidade infantil (Seção 13). |
| 21.39 | ⚠️ Modelo de suporte e SLA contratual por plano | Define os níveis de suporte por tipo de contrato (tempo de resposta, horário, canais) — a decidir pelo dono. |
| 21.40 | ⚠️ Ferramenta de helpdesk e canais oficiais | Qual sistema de tickets e quais canais (e-mail, WhatsApp, telefone) são oficiais — a decidir pelo dono. |
| 21.41 | ⚠️ Papel de Customer Success dedicado | Se haverá função dedicada de sucesso do cliente e sua cadência, ou se o dono/professor-embaixador absorve o onboarding. |

**Perguntas ao dono:**
- Qual o modelo e o SLA de suporte por tipo de contrato (canais, horário de atendimento, tempo-alvo de resposta)?
- Qual ferramenta de helpdesk e quais canais oficiais de atendimento à escola/professor (e-mail, WhatsApp, telefone)?
- Haverá papel dedicado de Customer Success, ou o próprio dono/professor-embaixador absorve o onboarding e o acompanhamento?
- O suporte pode 'entrar como' (impersonar) professor/aluno para diagnosticar — e sob qual política de auditoria e consentimento?
- Quais métricas definem uma escola 'de sucesso' (ex.: % de alunos ativos/semana, nº de missões) e qual o gatilho de intervenção proativa?
- No offboarding, o que exatamente a escola/família leva consigo (exportações, certificados) e em que prazo os dados são anonimizados?
- Qual o valor de fábrica das configurações sensíveis por escola na ativação (social opt-in vs. opt-out, horário permitido, retenção)?

---

# Parte VI — Negócio & Governança

## 22 · Monetização & Modelo de Negócio / Business Model
**Objetivo:** Fixar como o produto gera receita — licenciamento pela escola/rede, passe de temporada 100% gratuito e zero compras in-app — e deixar explícito tudo que depende do dono (unidade de licença, preço, planos, plataformas-alvo). Serve para o dev construir o encanamento comercial (gating por licença, provisioning, firewall entre economia do jogo e dinheiro real) sem tomar nenhuma decisão de produto.

| # | Subseção | Propósito |
|---|----------|-----------|
| 22.1 | Princípios de monetização (âncora nos Princípios 6–8 e 18) | Reafirma as travas imutáveis: sem compras no app, moeda só se ganha jogando, passe gratuito, zero dark patterns, sem anúncios/rastreamento — qualquer feature comercial nasce compatível com elas. |
| 22.2 | Modelo de receita: licenciamento pela escola/rede | Estabelece que o comprador é a escola/rede que licencia o produto e o jogador (criança) nunca é fonte de receita direta. |
| 22.3 | ⚠️ Unidade de licenciamento | Define o que exatamente é licenciado (escola inteira, rede/mantenedora, por aluno ativo, por turma) — parâmetro que dita todo o gating e faturamento. |
| 22.4 | ⚠️ Planos, tiers e pacote de recursos por plano | Especifica se há níveis de licença e quais recursos (social, IA, relatórios avançados) ficam em cada um. |
| 22.5 | ⚠️ Precificação e moeda | Faixa de preço, unidade (ex.: R$/aluno/ano) e moeda de cobrança — decisão exclusiva do dono. |
| 22.6 | ⚠️ Trial, piloto e freemium por escola | Regras do período gratuito/piloto: duração, limites de uso e o que fica travado antes da conversão. |
| 22.7 | ⚠️ Ciclo de faturamento e cobrança | Periodicidade (anual/mensal), quem emite nota (rede vs. escola) e integração com o financeiro do Edu — a confirmar pelo dono. |
| 22.8 | Gating de recursos por licença (mecanismo técnico) | Como a licença ativa/desativa recursos via `configuracoes` namespace `quest.*` por escola — o mecanismo é dev; o mapa recurso↔plano vem de 22.4. |
| 22.9 | Passe de temporada: gratuidade imutável | Fixa que o passe é 100% gratuito, trilha única de recompensas por jogar, sem trilha paga paralela. |
| 22.10 | ⚠️ Passe de temporada: formato definitivo | Número de níveis, duração (6–8 semanas), curva de XP do passe e recompensas — formato ainda a confirmar pelo dono. |
| 22.11 | ⚠️ Plataformas-alvo e fase de entrada | Define se, além de web/PWA instalável, haverá apps nativos (iOS/Android) e/ou desktop, e em qual fase (Q?). |
| 22.12 | ⚠️ Distribuição e entrega | Decide entre PWA instalável sem loja (padrão atual) vs. publicação em Play Store / App Store / Chromebook, com implicações de política de loja. |
| 22.13 | Firewall economia-do-jogo × dinheiro real | Garante por design que moedas/estrelas/XP jamais convertem em dinheiro, compra ou reembolso — regra técnica implementável e auditável. |
| 22.14 | Estrutura de custos (COGS) | Mapeia os custos que sustentam o preço-piso: CDN/assets, TTS/áudio gravado, chamadas de IA (Q6), infra Railway/Redis, storage de telemetria. |
| 22.15 | Onboarding comercial e contratação da escola | Fluxo de provisioning da escola licenciada e o termo de consentimento LGPD dos responsáveis (remete às Seções 10 e 12). |
| 22.16 | Controle de uso e antipirataria por licença | Como se contam escolas/alunos ativos e se impõe o limite da licença (o gatilho >30 escolas do doc 01 também vive aqui). |
| 22.17 | ⚠️ Métricas de negócio | Indicadores comerciais (ativação de escola, churn de escola, LTV, alunos ativos por licença) — definição de metas remete à Seção 17. |
| 22.18 | ⚠️ Roadmap de monetização por fase | Em que fase a cobrança real entra (hoje é piloto gratuito) e o que precede a comercialização. |
| 22.19 | Conformidade: publicidade e terceiros | Reafirma ausência de anúncios e de SDK de rastreamento de terceiros na experiência da criança (Princípio 18). |

**Perguntas ao dono:**
- Qual é a unidade de licenciamento: escola inteira, rede/mantenedora, por aluno ativo ou por turma?
- Haverá planos/tiers de licença? Se sim, quais recursos (social, IA, relatórios) ficam em cada plano?
- Qual a faixa de preço e a unidade de cobrança (ex.: R$/aluno/ano) e a moeda?
- Como funciona o trial/piloto: gratuito por quanto tempo e com quais limites de uso?
- Ciclo de cobrança (anual/mensal) e quem emite a nota — a rede ou a escola?
- Em que fase (Q?) a cobrança de verdade entra? Hoje tudo é piloto gratuito?
- Além de web/PWA instalável, haverá apps nativos (iOS/Android) e/ou desktop, e em qual fase?
- Distribuição por lojas (Play/App Store/Chromebook) ou só PWA instalável sem loja?
- Confirmar como imutável: passe 100% gratuito e zero compras in-app em TODAS as fases?
- Formato definitivo do passe: número de níveis, duração (6–8 semanas) e recompensas?

---

## 23 · Roadmap & Fases (Q0–Q6) / Roadmap & Phases
**Objetivo:** Documentar as 7 fases (Q0–Q6), cada uma entregável e usável, com objetivo, escopo, critério de corte ('uma criança real usa e quer voltar amanhã?') e um placar honesto de pronto-vs-planejado fiel ao relatório de estado (só Q0 em produção). Serve para o dev sequenciar o trabalho sabendo o que está feito, o que está adiado e o que depende de decisão do dono.

| # | Subseção | Propósito |
|---|----------|-----------|
| 23.1 | Filosofia de fases | Cada fase entrega valor usável em produção e nenhuma exige reescrever a anterior; o banco e as fronteiras dos docs 01/02 já comportam todas. |
| 23.2 | Régua de corte universal | Fixa o critério afetivo de pronto de toda fase: 'uma criança real consegue usar e quer voltar amanhã?'. |
| 23.3 | Como ler pronto vs. planejado | Legenda 🟢 pronto / 🟡 parcial / ⬛ planejado e o vínculo com o inventário do `_estado-atual`, evitando ler a doc como estado real. |
| 23.4 | Q0 — Fundação (esqueleto vivo) [entregue 2026-07-09] | Escopo entregue (login infantil, cartões PDF, lobby com Cosmo, vestiário, PWA, models grupos 1–3) e ressalvas (áudio sintetizado, QR na câmera nativa). |
| 23.5 | Q1 — Núcleo jogável | Loop estudar→ganhar→evoluir num planeta: MissaoPlayer + registry de 4 mecânicas, Matemática completa, XP/moedas/estrelas, telemetria — com critério de pronto próprio. |
| 23.6 | Q2 — Retenção | Diárias/semanais, Chama do Cosmo, conquistas, colecionáveis, vestiário/loja, constelação pessoal, adaptativa v1, Português + 2 mecânicas, PWA offline. |
| 23.7 | Q3 — Professor & Família | Telas do professor no Edu (panorama, BNCC, erros comuns, trajetória, alertas), Missão da Turma, Portal da Família, papel responsável, certificados. |
| 23.8 | Q4 — Social | Amizades, Estudar com um amigo, motor de corrida (3 skins), pintura em dupla, X1, WebSocket/salas, mensagens rápidas, ranking de turma. |
| 23.9 | Q5 — Mundo vivo | Temporadas + passe gratuito, eventos temáticos, planetas restantes (Ed. Física e ERER com curadoria), torneios/clubes, Redis conforme carga. |
| 23.10 | Q6 — IA (o tutor invisível) | Cosmo explica erros via `services/ia`, adaptativa v2 por habilidade BNCC, gerador de desafios com fila de revisão humana, narrativas assistidas. |
| 23.11 | Matriz fase × sistema × seção da Bible | Cruza cada fase com os sistemas que toca e as seções da Bible correspondentes, para rastrear onde a spec de cada entrega vive. |
| 23.12 | Dependências e ordenação entre fases | Explicita o que bloqueia o quê (ex.: social só após retenção; IA só após conteúdo e telemetria) e por que a ordem é essa. |
| 23.13 | ⚠️ Escopo de conteúdo por fase | Decidir 1 planeta profundo (Matemática) vs. 9 planetas rasos no Q1 — decisão do dono que dimensiona todo o esforço de conteúdo. |
| 23.14 | ⚠️ Ordem de entrada dos planetas | Sequência dos mundos (Matemática Q1, Português Q2, demais Q5) e a confirmação de Ed. Física e ERER só na Q5 com curadoria própria. |
| 23.15 | Riscos por fase e mitigação | Registra os riscos mapeados (conteúdo é o gargalo, multiplayer prematuro, login de 6 anos, uso compulsivo, divergência visual) e a resposta de cada um. |
| 23.16 | ⚠️ Reconciliação de desvios já ocorridos em Q0 | Consolidar ou reverter os desvios do plano (Three.js e avatar humanoide 3D no núcleo, contra o doc DOM/SVG-first) — pendência que trava o fechamento de Q0. |
| 23.17 | ⚠️ Definição de lançamento comercial | Qual fase habilita cobrança e marketing e o que compõe o 'produto lançável' — critério ainda não definido (também sinalizado na Seção 00). |
| 23.18 | ⚠️ Marcos e datas-alvo por fase | Se o roadmap é dirigido por data ou só por critério de pronto; e, havendo datas, quais são — a definir pelo dono. |
| 23.19 | ⚠️ Métricas de saída (gate quantitativo) por fase | Além da régua afetiva, quais números liberam a passagem de fase (ex.: sessões fora do horário de aula em Q2) — metas remetem à Seção 17. |
| 23.20 | Backlog pós-Q6 e itens adiados | O que fica fora das 7 fases: clubes/torneios (se a demanda confirmar) e a integração futura com o software próprio de matérias+questões do dono. |

**Perguntas ao dono:**
- Escopo de conteúdo do Q1: 1 planeta profundo (Matemática) para os 5 anos, ou vários planetas rasos?
- Confirmar Ed. Física e ERER apenas na Q5, com curadoria pedagógica própria?
- Qual é a 'definição de lançamento comercial': qual fase habilita cobrança e marketing?
- O roadmap tem datas-alvo por fase ou é dirigido só pelo critério de pronto (sem prazo fixo)?
- Como reconciliar os desvios de Q0 (Three.js e avatar humanoide 3D no núcleo): consolidar como oficial ou reverter para DOM/SVG-first?
- Confirmar a ordem dos planetas após Matemática (Português na Q2, demais na Q5)?
- Haverá metas quantitativas de saída de fase (ex.: retenção D1/D7) além da régua afetiva 'volta amanhã'?

---

## 24 · Governança da Bible / Bible Governance
**Objetivo:** Definir quem decide o quê, o fluxo de aprovação em 3 portões, como contradições (doc×código×doc) são resolvidas por precedência de fontes, e como a Bible é versionada, espelhada em dois idiomas e registrada em changelog. Torna o próprio processo operável e auditável, herdando o que o ADR-0001 já fixou.

| # | Subseção | Propósito |
|---|----------|-----------|
| 24.1 | Papéis e responsabilidades | Dono do produto = decisor único de produto/design/arte; papel técnico (Arquiteto+GD+CTO) = propõe e implementa; QA = revisa — sem decisões autônomas de produto. |
| 24.2 | Matriz de autoridade (RACI) | Separa o que o dono aprova (produto, UX, jogabilidade, arte, arquitetura) do que a autonomia técnica cobre (execução: rodar, testar, refatorar, corrigir bugs). |
| 24.3 | Os 3 portões de toda funcionalidade | Documentação (spec) → Aprovação do dono → Implementação fiel + Revisão + atualização da Bible, como rito obrigatório. |
| 24.4 | Regra de ouro | Nada é implementado a partir de uma seção ou spec que não esteja 🟢 aprovada. |
| 24.5 | Ciclo de vida de uma seção (status e transições) | Estados ⬛ não iniciado → 🔴 rascunho → 🟡 em revisão → 🟢 aprovado e quem promove cada transição. |
| 24.6 | Ciclo de vida de uma spec (Portão 1) | Como uma feature nasce como spec em `specs/NNN-nome.md` a partir do `_TEMPLATE-spec.md` e evolui até aprovação. |
| 24.7 | Fluxo de aprovação e registro | Quem submete, como o dono aprova e onde a aprovação fica registrada (commit/ADR/status), para ser rastreável depois. |
| 24.8 | Precedência de fontes (hierarquia normativa) | Ordem de autoridade — Princípios Imutáveis > ADR > Seção aprovada > Spec > código — usada para resolver qualquer conflito. |
| 24.9 | Resolução de contradições | Procedimento quando doc, código e doc divergem (ex.: avatar 3D vs. Cosmo, Three.js vs. DOM/SVG): registrar, abrir ADR, reconciliar textos. |
| 24.10 | Alteração de princípios imutáveis | Um princípio só muda por novo ADR aprovado pelo dono que referencie o anterior — nunca por edição silenciosa. |
| 24.11 | Versionamento no Git | Convenção multi-arquivo (índice + seção por arquivo + specs/ + decisoes/), padrão de branch/PR e mensagem de commit para mudanças na Bible. |
| 24.12 | Changelog da Bible | Onde e como registrar o histórico de mudanças por seção (o que mudou, por qual ADR/spec, quando). |
| 24.13 | Convenção bilíngue e sincronização | pt-BR canônico + inglês espelhado no mesmo arquivo, com a regra de quando o espelho deve estar sincronizado (por commit vs. em lote). |
| 24.14 | Numeração e nomenclatura | Padrão de nomes de arquivos, numeração de seções, apêndices (A–C), specs (NNN) e ADRs (NNNN). |
| 24.15 | Relação com o `_estado-atual` | O relatório de estado é inventário (não decisão); define quando reauditar e como ele alimenta as seções de 'estado atual'. |
| 24.16 | Checklist da revisão de QA (Portão 3) | Itens obrigatórios da revisão pós-implementação: bugs, performance, UX, acessibilidade, responsividade, escalabilidade, organização. |
| 24.17 | Rastreabilidade spec ↔ seção ↔ ADR ↔ commit | Como amarrar cada entrega de código à spec e ao ADR que a autorizaram, fechando o laço de auditoria. |
| 24.18 | Gestão central de decisões em aberto | Registro único das pendências que só o dono decide, com responsável e ponteiro para o ADR candidato (remete ao Apêndice C). |
| 24.19 | ⚠️ Automação e CI da documentação | Proposta de checagens automáticas: lint de vocabulário proibido, verificação de status, sincronia do espelho bilíngue e links — adoção a confirmar. |
| 24.20 | ⚠️ Delegação de aprovação e cadência (SLA) | Se o dono delega aprovação de specs de baixo risco ao arquiteto e se há prazo/cadência de revisão para evitar bloqueios. |

**Perguntas ao dono:**
- O dono é o único aprovador ou delega a aprovação de specs de baixo risco/execução ao papel técnico?
- Há SLA/cadência para revisão e aprovação de specs, para não bloquear o desenvolvimento?
- Adotamos automação de CI da doc (lint de vocabulário proibido, checagem de status, sincronia bilíngue, links)?
- O inglês espelhado é obrigatório em cada commit ou pode entrar em lote depois (como o template já permite)?

---

# Apêndices

## A · Apêndice A — Glossário / Glossary
**Objetivo:** Ser a referência alfabética única de todo termo do projeto — vocabulário interno, o que a criança vê, termos de negócio, técnicos e pedagógicos — cada verbete com definição, mapeamento interno↔criança e ponteiro para a seção que o governa. Esta seção descreve a estrutura e a governança do glossário, não o preenche verbete a verbete.

| # | Subseção | Propósito |
|---|----------|-----------|
| A.1 | Como usar o glossário | Escopo do apêndice e sua relação com a Seção 02 (Vocabulário Canônico): o glossário reúne e remete, não redefine. |
| A.2 | Estrutura de cada verbete | Campos fixos de um verbete: termo, categoria, definição curta, par interno↔criança (quando houver), seção-fonte e status. |
| A.3 | Convenções de escrita | Ordenação alfabética, uso de negrito, remissivas 'ver também', e a marcação visual de termos proibidos na UI infantil. |
| A.4 | Glossário de produto e game design | Termos de economia e progressão: XP, moedas, estrelas, Chama do Cosmo, passe, temporada, conquista, colecionável, sequência, teto diário. |
| A.5 | Vocabulário lúdico (interno → criança) | Remissão consolidada ao mapa da Seção 02 (mundo→Planeta, jornada, missão, desafio, progresso→Constelação) sem duplicar a fonte. |
| A.6 | Glossário técnico e de arquitetura | Monólito modular, outbox, ledger imutável, PWA, WebSocket, mecânica-plugin/registry, R3F/Three.js, CDN, escola_id, JWT papel aluno. |
| A.7 | Glossário pedagógico | BNCC, código de habilidade, domínio (0–100), dificuldade adaptativa, ano escolar, chefão, revisão espaçada. |
| A.8 | Glossário de negócio | Licença, escola/rede, mantenedora, comprador vs. jogador, LTV, churn de escola, ativação, piloto. |
| A.9 | Glossário de papéis de usuário | Aluno, responsável, professor, coordenador/admin de escola, admin global — como autentica e o que acessa. |
| A.10 | Termos proibidos na UI infantil | Lista consolidada (party, lobby, matchmaking, squad, ranking global, prova, exercício, tarefa, erro fatal, reprovado) com seus substitutos — remete à Seção 02. |
| A.11 | Siglas e abreviações | Expansão de BNCC, LGPD, ADR, GDD, PWA, TTS, R3F, CDN, RACI, COGS, LTV. |
| A.12 | Nomes próprios do universo | Cosmo (mascote) e os planetas com nome lúdico (Numéria, Palavras, Biozênia, Terra Nova, Chronos, Oxford, Colorium, Movi, Raízes) — não se traduzem. |
| A.13 | ⚠️ Rótulos infantis ainda em aberto | Verbetes cujo rótulo para a criança não está fixado: a tela-casa (hoje 'lobby' no código, palavra proibida) e o rótulo de perfil ('Meu astronauta'). |
| A.14 | Governança do glossário | Todo termo novo entra via spec/ADR e sincroniza com a Seção 02; mudança de termo canônico exige ADR. |

**Perguntas ao dono:**
- Confirmar o rótulo infantil da tela-casa (hoje 'lobby' no código, proibido na UI)?
- Confirmar 'Meu astronauta' como rótulo do perfil, ou outro nome?
- Os nomes próprios dos 9 planetas (Numéria, Palavras, Biozênia…) estão definitivos?

---

## B · Apêndice B — Contratos de API & Modelo de Dados / API & Data Contracts
**Objetivo:** Ser a referência autoritativa de cada rota REST/WebSocket (método, caminho, request, response, autorização, erros — com o gabarito NUNCA indo ao cliente) e das 8 grupos de tabelas `quest_*` (colunas, chaves, índices, imutabilidade/ledger). Serve para o dev implementar o contrato exatamente como especificado, sem inferir formato.

| # | Subseção | Propósito |
|---|----------|-----------|
| B.1 | Convenções gerais da API | Base `/api/v1/quest/`, JSON, JWT Bearer, papéis checados por rota no backend, isolamento por escola_id, paginação nos agregados, cache ETag no catálogo, datas UTC. |
| B.2 | Contrato — /auth | Q0 real: rotas `quem`/`entrar`/`entrar-qr` (código curto ou QR, sem senha/PIN), claims do JWT papel aluno `{sub, papel, ver, iat, exp}`, rate-limit por (código, IP). Aspiracional (sem código): `renovar`/`sair` e claims adicionais (perfil_id/aluno_id/escola_id, hoje derivados por lookup). |
| B.3 | Contrato — /perfil | Q0 real: GET perfil, GET /cores, GET /aparencia, GET /personagens, PATCH /nome, PATCH /avatar (whitelist de slots), PATCH /preferencias — nenhum campo administrativo exposto ao aluno. Aspiracional (sem código): GET constelacao. |
| B.4 | Contrato — /catalogo | GET planetas, GET jornadas do planeta, GET missão/{id} com desafios entregues SEM o campo `gabarito`. |
| B.5 | Contrato — /jogo | POST iniciar tentativa, POST responder desafio, POST finalizar → recompensas calculadas no servidor (autoridade do gabarito, XP/moedas/estrelas server-side). |
| B.6 | Contrato — /tarefas | GET hoje (diárias + semanais + presente de login) e POST resgatar — geração e viés por habilidade fraca acontecem no servidor. |
| B.7 | Contrato — /economia | GET loja, POST comprar, GET inventário, GET passe — compra debita via ledger; sem qualquer entrada de dinheiro real. |
| B.8 | Contrato — /social | GET amigos, POST convites, POST responder convite, GET mensagens-rapidas (catálogo) — sem texto livre, sempre na mesma escola. |
| B.9 | Contrato — /salas | POST criar, POST entrar por código, GET estado — a linha em banco é o registro histórico; o estado ao vivo fica em memória/Redis. |
| B.10 | Contrato — WebSocket /ws/quest | Protocolo de mensagens das partidas ao vivo, máquina de estados da sala, tolerância a queda de 30s e reenvio de estado no rejoin — desafios sem gabarito. |
| B.11 | Contrato — /professor | GET panorama da turma, habilidades BNCC, erros comuns, trajetória do aluno; POST atribuições (Missão da Turma) — consumido pelo Edu, sem ruído lúdico. |
| B.12 | ⚠️ Contrato — /familia | GET filhos, GET resumo do filho, PATCH controles (social/horário) — leitura para o responsável; momento de entrada e autorização do vínculo a confirmar. |
| B.13 | Modelo de dados — convenções | Prefixo `quest_`, escola_id + índice em toda tabela de aluno, histórico imutável (tentativas/ledger/outbox), regras numéricas em `configuracoes` `quest.*`. |
| B.14 | Grupo 1 — Identidade e acesso | `quest_perfis`, `quest_credenciais_aluno`, `responsaveis_alunos` e os dois acréscimos aditivos ao núcleo (cargo `responsavel`; aluno fora de `usuarios`). |
| B.15 | Grupo 2 — Conteúdo pedagógico (catálogo global) | `quest_mundos`, `quest_jornadas`, `quest_missoes`, `quest_desafios` — versão de missão, BNCC, e `gabarito` que nunca sai do servidor. |
| B.16 | Grupo 3 — Progresso e telemetria | `quest_progresso` (estrelas por missão), `quest_tentativas` (imutável, fonte de tudo), `quest_habilidades` (cache recalculável por BNCC). |
| B.17 | Grupo 4 — Economia e coleção | `quest_itens`, `quest_inventario`, `quest_transacoes_moedas` (ledger imutável; saldo do perfil é cache recomputável). |
| B.18 | Grupo 5 — Ritmo diário e conquistas | `quest_tarefas_periodicas`, `quest_conquistas` e `quest_conquistas_obtidas` — critérios data-driven avaliados por serviço genérico. |
| B.19 | Grupo 6 — Social e partidas | `quest_amizades`, `quest_salas`, `quest_mensagens_rapidas` — sem campo de texto livre acessível ao aluno. |
| B.20 | Grupo 7 — Temporadas e eventos | `quest_temporadas`, `quest_passe_progresso`, `quest_eventos` — passe gratuito, trilha única de recompensas. |
| B.21 | Grupo 8 — Integração | `quest_outbox`: tipos de evento de domínio, consumidores atuais (push/mural) e o caminho para fila real quando o quest for extraído. |
| B.22 | Tabelas adiadas (desenhadas, não criadas) | Clubes e torneios: como se encaixam no modelo (clubes referenciam perfis; torneios referenciam salas) sem mudar o desenho atual. |
| B.23 | ⚠️ Schemas de conteúdo por mecânica | Formato do `corpo` e do `gabarito` (JSON) de cada mecânica (quiz, arrastar, ligar, memória, caça-palavras, completar, sequência) — schema de cada uma a definir no design. |
| B.24 | Esquema de configurações `quest.*` | Namespace das regras não-hardcoded (XP, preços, tetos, limites sociais) — chaves, tipos e valores-padrão por escola. |
| B.25 | Versionamento e compatibilidade da API | Versão de missão gravada na tentativa, ETag do catálogo, política de deprecação e retrocompatibilidade dos contratos. |
| B.26 | Códigos de erro e políticas transversais | Formato de erro, 401/403 por papel, validação Pydantic, rate-limit por perfil nas rotas de jogo (anti-farm). |
| B.27 | ⚠️ Contrato de tipos compartilhados (`@constela/quest-core`) | Fonte única dos tipos da API para o cliente e o Edu web; nota sobre a consolidação do contrato de avatar (aposentar tipos legados do Cosmo). |
| B.28 | ⚠️ Contrato de escrita do catálogo pedagógico (autoria) | Por qual interface o catálogo (mundos→jornadas→missões→desafios) é cadastrado/publicado e a conexão com o software futuro de matérias+questões. |

**Perguntas ao dono:**
- Quem autoriza o vínculo responsável↔aluno e em que fase (Q3) a API /familia entra?
- As preferências `musica` e `reduzir_animacoes` permanecem no modelo (ganham UI/função) ou saem?
- Confirmar login código-só e autorizar a remoção dos resíduos de PIN dos contratos de /auth e docs?
- Por qual interface o catálogo pedagógico é cadastrado e publicado — admin no Edu, ou o software futuro de matérias+questões? Isso define o contrato de escrita.
- Consolidar o contrato de avatar (humanoide 3D) no @constela/quest-core, aposentando os tipos legados do Cosmo?

---

## C · Apêndice C — Registro de Decisões (ADR) / Decision Log
**Objetivo:** Manter o índice de todos os ADRs e o template/processo canônico para registrar cada decisão de produto, design ou arquitetura de forma numerada, datada e imutável. Inclui o backlog de ADRs candidatos que mapeia, uma a uma, as decisões que só o dono pode tomar.

| # | Subseção | Propósito |
|---|----------|-----------|
| C.1 | Propósito e princípios do ADR | Cada decisão relevante vira ADR numerado, datado e imutável; uma reversão cria um novo ADR que referencia o anterior — nunca se edita o antigo. |
| C.2 | Índice de ADRs (tabela viva) | Tabela mestre número/título/status/data, mantida em sincronia com `decisoes/README.md` (hoje só o ADR-0001). |
| C.3 | Template canônico de ADR | Campos obrigatórios: número, status, data, decisor, contexto, decisão, consequências, ADRs relacionados — bilíngue (pt-BR canônico + inglês). |
| C.4 | Estados e transições de um ADR | Proposto → Aceito / Rejeitado → Substituído / Depreciado, e quem promove cada transição. |
| C.5 | Numeração e nomenclatura | Padrão `ADR-NNNN-slug.md` e regra de alocação sequencial do número. |
| C.6 | Fluxo: de decisão em aberto a ADR aprovado | Como uma pendência do registro central (Seção 24.18) vira proposta de ADR, é decidida pelo dono e registrada. |
| C.7 | Rastreabilidade ADR ↔ Princípios ↔ Seções ↔ Specs | Como um ADR aponta os princípios que altera, as seções que atualiza e as specs que autoriza. |
| C.8 | Convenção de reversão e supersessão | Como um novo ADR referencia e substitui o anterior, mantendo o histórico legível. |
| C.9 | Governança do índice e espelho bilíngue | Quando atualizar a tabela e como manter o espelho pt-BR/inglês sem divergência. |
| C.10 | ADR-0001 — Processo de estúdio e a Bible (âncora) | Referência ao ADR já aceito que fundou o modelo de estúdio, os 3 portões e o formato da Bible. |
| C.11 | Backlog de ADRs candidatos (visão geral) | Lista as decisões em aberto da auditoria como futuros ADRs, cada uma detalhada nas subseções seguintes. |
| C.12 | ⚠️ ADR candidato — Avatar definitivo (humanoide 3D vs. Cosmo 2D) | Resolve qual é o avatar do jogador; hoje coexistem dois sistemas (código foi para 3D; docs dizem 'em aberto'). |
| C.13 | ⚠️ ADR candidato — Three.js oficial no núcleo | Decide se Three.js/R3F entra oficialmente no núcleo do frontend, exigindo reescrever o doc DOM/SVG-first ('PixiJS, não Three.js'). |
| C.14 | ⚠️ ADR candidato — Pipeline de arte e assets 3D | Define quem produz os GLB/camadas trocáveis e os áudios/ilustrações gravados, e o orçamento de produção. |
| C.15 | ⚠️ ADR candidato — Login código-só e limpeza do PIN | Confirma o login sem senha/PIN como vigente e autoriza remover os resíduos de 'PIN de figuras' dos docs 01/04 e contratos. |
| C.16 | ⚠️ ADR candidato — Escopo de conteúdo do Q1 | 1 planeta profundo (Matemática) vs. 9 planetas rasos — dimensiona o gargalo de conteúdo. |
| C.17 | ⚠️ ADR candidato — Interface de autoria do catálogo pedagógico | Por qual interface o conteúdo é cadastrado/publicado e a conexão com o software futuro de matérias+questões. |
| C.18 | ⚠️ ADR candidato — Amizades no lançamento e default social | 'Mesma turma' vs. 'mesma escola' e se o social nasce ligado ou desligado por padrão. |
| C.19 | ⚠️ ADR candidato — Retenção e anonimização de dados | Confirma o prazo de retenção da telemetria (padrão sugerido 24 meses) e o gatilho de anonimização na saída do aluno. |
| C.20 | ⚠️ ADR candidato — Monetização imutável | Eleva a princípio: passe 100% gratuito e zero compras in-app em todas as fases. |
| C.21 | ⚠️ ADR candidato — Plataformas-alvo e fase | Apps nativos/desktop além do PWA instalável e em qual fase entram. |
| C.22 | ⚠️ ADR candidato — Ed. Física e ERER na Q5 | Confirma a entrada desses dois planetas só na Q5, com curadoria pedagógica humana própria. |
| C.23 | ⚠️ ADR candidato — Portal da Família / vínculo responsável | Quando a API /familia entra e quem autoriza o vínculo responsável↔aluno. |
| C.24 | ⚠️ ADR candidato — Preferências `musica` e `reduzir_animacoes` | Decide se essas preferências ganham função/UI ou saem do modelo de dados. |
| C.25 | ⚠️ ADR candidato — Device-alvo mínimo e orçamento de desempenho | Fixa o hardware-alvo mínimo (tablet/Chromebook modesto) e os números concretos de carregamento/memória (Princípio 17). |
| C.26 | ⚠️ ADR candidato — Métrica-norte quantificável | Transforma 'volta amanhã?' em metas (D1/D7/D30) e guardrails de aprendizado e saúde de uso (Seção 00/17). |

**Perguntas ao dono:**
- Quais dos ADRs candidatos (C.12–C.26) você quer decidir primeiro para desbloquear o desenvolvimento?
- Avatar definitivo e Three.js no núcleo são a decisão mais urgente (dois sistemas coexistem hoje) — quer resolvê-los juntos num único ADR ou separados?
- Confirma elevar a monetização (passe grátis + zero compras) a ADR imutável agora?
- Autoriza abrir o ADR de login código-só para limpar formalmente os resíduos de PIN nos docs e contratos?

---

## D · Apêndice D — Catálogo de Eventos de Telemetria
**Objetivo:** Ser a referência autoritativa e versionada de cada evento de telemetria (nome, gatilho, campos, tipos, privacidade), no mesmo espírito do Apêndice B, para que o dev instrumente o cliente e valide no ingest sem inferir formato. Complementa a Seção 17 (que define norte/KPIs/guardrails) fornecendo o dicionário técnico executável, mais convenções de versionamento/deprecação, validação de esquema e deduplicação de eventos offline tardios.

| # | Subseção | Propósito |
|---|----------|-----------|
| D.1 | Convenções gerais do catálogo de eventos | Fixa base do pipeline (telemetria própria, sem SDK de terceiros), datas UTC ISO-8601, transporte, formato JSON e a regra de que nenhum evento carrega PII direta da criança. |
| D.2 | Como ler este catálogo | Delimita o papel do apêndice (executa, não redefine) e sua relação com a Seção 17 (KPIs/norte) e o Apêndice B (tabelas/rotas que originam eventos derivados). |
| D.3 | Template canônico de ficha de evento | Define o formato repetível de cada verbete de evento: nome, versão, quando dispara, origem, campos (nome/tipo/obrigatoriedade), classe de privacidade, KPI-alvo e seção-fonte. |
| D.4 | Envelope comum do evento | Especifica os campos presentes em TODO evento (event_name, event_version, event_id, occurred_at, received_at, perfil_id, escola_id, sessao_id, origem, app_version, locale). |
| D.5 | Convenção de nomenclatura de eventos | Fixa o padrão de nomes (substantivo.verbo em snake_case, alinhado ao vocabulário interno e nunca ao infantil) e a granularidade esperada por evento. |
| D.6 | Tipos e formatos de campo permitidos | Lista os tipos aceitos (inteiro, decimal, booleano, enum, timestamp UTC, uuid), tratamento de nulos e a proibição de campos de texto livre no payload. |
| D.7 | Classificação de privacidade dos campos (semáforo LGPD) | Rotula cada campo como pseudônimo/agregável/proibido, garantindo coleta mínima (Princípio 3) e que nome de exibição, foto ou localização nunca entrem em evento. |
| D.8 | Identidade e pseudonimização nos eventos | Define que a chave é perfil_id + escola_id (nunca aluno real nem nome), como sessao_id é gerado e como o isolamento multi-escola se reflete em cada evento. |
| D.9 | Convenção de versionamento de eventos | Estabelece o campo event_version e a semântica de incremento (mudança compatível vs. incompatível de payload) para não quebrar análises históricas. |
| D.10 | Política de deprecação e ciclo de vida de um evento | Define estados de um evento (proposto → ativo → depreciado → removido), janela de convivência de versões e como sinalizar um evento em fim de vida. |
| D.11 | Compatibilidade retroativa e migração de análises | Regra de que versões antigas continuam legíveis, como campos novos entram como opcionais e como consolidar séries históricas ao subir de versão. |
| D.12 | Registro de esquema (schema registry / fonte única) | Define onde vive o contrato de cada evento (fonte única de verdade compartilhada cliente↔servidor) e como o dev consome esse esquema. |
| D.13 | Validação de esquema no ingest | Especifica a validação obrigatória de todo evento recebido contra o esquema versionado, com rejeição de payload inválido e encaminhamento a dead-letter. |
| D.14 | Deduplicação de eventos | Define event_id idempotente e a janela/estratégia de dedup para que reenvio de rede ou sync duplicado não conte duas vezes o mesmo fato. |
| D.15 | Eventos offline tardios (late-arrival) | Trata o evento gerado offline e sincronizado horas depois: preservar occurred_at original, marcar received_at, dedup por event_id e não distorcer coortes diárias. |
| D.16 | Ordenação e relógio (occurred_at vs received_at) | Define a distinção entre horário do fato e horário de recepção, tolerância a clock skew do tablet e qual timestamp cada KPI usa. |
| D.17 | Origem e caminho de entrega do evento | Enumera as origens (web, pwa-offline, derivado-servidor), a fila IndexedDB append-only no cliente e o sync ao reconectar (liga às Seções 5.46 e 17.24). |
| D.18 | Família de eventos — Sessão e acesso | Cataloga boot/confirmação de identidade, login por código/QR (sucesso/falha), início e fim de sessão, com seus payloads versionados. |
| D.19 | Família de eventos — Núcleo jogável (tentativa e resposta) | Cataloga tentativa_iniciada, desafio_respondido (mecânica, dificuldade, BNCC, acerto), tentativa_finalizada, com o gabarito conferido no servidor. |
| D.20 | Família de eventos — Progressão e economia | Cataloga missao_concluida (estrelas), nivel_subido, moedas_creditadas/gastas (eco do ledger) e estrela_conquistada, sem qualquer dinheiro real. |
| D.21 | Família de eventos — Retenção | Cataloga chama_atualizada/reacendida, tarefa_resgatada (diária/semanal/presente de login), conquista_desbloqueada e colecionavel_obtido. |
| D.22 | Família de eventos — Avatar, vestiário e loja | Cataloga avatar_alterado (slot), vestiario_aberto, item_comprado e invocação de itens especiais, refletindo o contrato de avatar. |
| D.23 | Família de eventos — Social e multiplayer | Cataloga amizade_solicitada/respondida, sala criada/entrada, partida iniciada/finalizada e mensagem_rapida_enviada (só slug de catálogo, nunca texto). |
| D.24 | Família de eventos — Navegação, UX e áudio | Cataloga planeta_aberto, aba_trocada (Jogar/Vestiário/Carreira) e narracao_reproduzida ('ouvir de novo'), sinais de usabilidade sem PII. |
| D.25 | Família de eventos — Guardrails de saúde e anti-abuso | Cataloga teto_diario_atingido (celebração), sessao_longa (gatilho de pausa do Cosmo) e sinais anti-farm/abuso de login (liga às Seções 17.4/17.27). |
| D.26 | Família de eventos — Erros de cliente, crash e diagnóstico | Cataloga erro_cliente e crash com contexto técnico mínimo (tela, versão, classe de device) para observabilidade, sem capturar conteúdo pessoal. |
| D.27 | Eventos derivados no servidor | Define eventos/agregações originados de quest_tentativas (imutável) e quest_outbox, independentes do cliente para não perder dados quando o app não emite. |
| D.28 | Matriz evento × KPI × seção | Cruza cada evento com o KPI que alimenta (Seção 17.5–17.9) e a seção-fonte, garantindo que todo evento tem finalidade e todo KPI tem instrumentação. |
| D.29 | Volume, cardinalidade e amostragem por evento | Estima frequência de cada evento e define se/como amostrar eventos de alto volume sem perder fidelidade dos KPIs-núcleo (liga à Seção 17.25). |
| D.30 | Estados de erro/vazio/offline no envio | Especifica comportamento quando não há rede, buffer local cheio, envio falho ou payload rejeitado — sempre sem interromper o jogo da criança. |
| D.31 | Observabilidade do pipeline de ingest | Define métricas de saúde do próprio pipeline (taxa de rejeição de esquema, taxa de dedup, atraso de sync, eventos em dead-letter) e seus alertas. |
| D.32 | i18n e locale nos eventos | Define locale como propriedade padrão do envelope e a regra de que nenhum evento transporta texto traduzível ou copy da UI (liga à Seção 16 i18n). |
| D.33 | Testes e fixtures do catálogo | Define fixtures de payload por evento, testes de contrato cliente↔ingest e a checagem em CI de que todo evento emitido casa com seu esquema versionado. |
| D.34 | ⚠️ Retenção e anonimização por classe de evento | Define por quanto tempo cada classe de evento é guardada e o gatilho de anonimização na saída do aluno — padrão sugerido a confirmar pelo dono. |
| D.35 | ⚠️ Evento de atribuição de experimento (A/B) | Especifica o evento que registra a variante de um experimento, condicionado à autorização de A/B com crianças ainda pendente do dono. |
| D.36 | Governança e mudança do catálogo | Regra de que novo evento ou campo entra via spec/ADR, sincroniza com a Seção 17 e é registrado em changelog, sem evento órfão ou não documentado. |

**Perguntas ao dono:**
- Confirmar o prazo de retenção por classe de evento (padrão sugerido 24 meses) e o gatilho exato de anonimização quando o aluno sai da escola (liga à Seção 17.21).
- É permitido emitir eventos de atribuição de experimento (A/B) com público infantil? Sob quais limites éticos e de consentimento (liga à Seção 17.28)?
- Qual o destino operacional dos eventos rejeitados no ingest (dead-letter): descartar, quarentenar para revisão, e quem revisa?
- Podemos coletar app_version e uma classe de device (não o modelo exato) por evento para diagnóstico, sem ferir a minimização (Princípio 3/18)?
- Amostragem de eventos de alto volume é autorizada, ou todo evento-núcleo deve ser 100% coletado para não perder fidelidade dos KPIs?

---

## E · Apêndice E — Wireframes/Mockups de Referência
**Objetivo:** Estabelecer o conjunto canônico de telas de referência que amarra vocabulário (Seção 02), estados (vazio/carregando/erro/offline/sucesso) e navegação, sua relação com o protótipo constela-play-v7, e a convenção de mantê-los sincronizados com a implementação. Serve para o dev construir cada tela sabendo layout, estados, cópia e telemetria disparada sem tomar decisões de UX.

| # | Subseção | Propósito |
|---|----------|-----------|
| E.1 | Como usar este apêndice | Define o mockup como referência normativa de layout, estado e cópia (não pixel-final de arte) e sua precedência frente ao código, remetendo arte fina à Seção 15. |
| E.2 | Status e fontes | Metadados do apêndice e ancoragem no protótipo constela-play-v7 e no que já está em produção (Q0), separando o vigente do legado. |
| E.3 | Relação com o protótipo constela-play-v7 | Fixa o que se herda do protótipo (estética, SUBJECTS/SCENES, tema JSON) e onde o protótipo diverge do código atual, evitando ler o protótipo como estado real. |
| E.4 | Convenções de leitura de um mockup | Define anotações padrão (hotspots, legendas de estado, marcação de vocabulário infantil, notas de áudio) e como o dev lê fluxo e interação a partir da tela. |
| E.5 | Ficha-modelo de tela | Template repetível por tela: nome interno↔infantil, objetivo, entradas/saídas, estados cobertos, navegação, áudio/narração, acessibilidade, telemetria disparada e breakpoint. |
| E.6 | Catálogo de estados canônicos | Fixa o conjunto que TODA tela deve cobrir (vazio, carregando/skeleton, erro de rede, offline, sucesso, sem licença/recurso desligado) como requisito de completude. |
| E.7 | Mapa de telas e navegação global | Fluxograma tela→tela do produto (acesso → casa → planeta → missão → recompensa → social/adulto), a espinha de navegação sem router. |
| E.8 | Grid de responsividade e breakpoints | Define os pontos de quebra de referência (tablet retrato/paisagem, Chromebook, telefone) e o alvo mínimo em que o layout deve funcionar. |
| E.9 | Tokens visuais referenciados | Remete os tokens de cor/tipografia à Seção 15 e a identidade por planeta à Seção 03, sem redefini-los, para os mockups não fixarem valores próprios. |
| E.10 | Tela — Boot / 'É você, {nome}?' | Confirmação de identidade no tablet compartilhado (Princípio 4), com estado de troca de perfil e nenhuma conta salva. |
| E.11 | Tela — Entrar por código | Fluxo de 2 etapas quem→entrar com código curto falável, incluindo erro de código inválido e estado de rate-limit. |
| E.12 | Tela — Entrar por QR | Alternativa por QR na câmera nativa, com fallback para código quando não houver câmera/permissão. |
| E.13 | Fluxo — Cerimônia da 1ª vez | Sequência escolher personagem → apelido (seleção controlada, sem texto livre) → festa, ligada ao login sem senha. |
| E.14 | Tela-casa (lobby) — aba Jogar | Hub com céu tocável, 9 planetas-matéria ambientados e Cosmo companheiro; a nave-mãe de onde se viaja aos planetas. |
| E.15 | Tela-casa — aba Vestiário | Customização do avatar por slots/categorias e invocação de itens especiais; layout depende da decisão de avatar (3D vs 2D). |
| E.16 | Tela-casa — aba Carreira | Stats e conquistas do aluno, incluindo o estado vazio 'Minhas aventuras' e sem exposição de ranking individual. |
| E.17 | Tela — Mapa do planeta / jornada | Trilha visível de missões com chefão travado por estrelas e progressão por ano escolar. |
| E.18 | Tela — Constelação (progresso pessoal) | Mapa estelar eu×eu-de-ontem como tela primária de progresso, com o álbum de colecionáveis do universo. |
| E.19 | Tela — MissaoPlayer (casca de missão) | Orquestra a sequência de desafios: enunciado, botão de áudio, progresso e transição entre desafios. |
| E.20 | Mockups por mecânica de desafio | Layout e estados de cada mecânica (quiz, arrastar, ligar, memória, completar, sequência, caça-palavras), touch-first e acessível. |
| E.21 | Tela — Feedback de resposta | Retorno de acerto/erro sempre acolhido ('quase!'), dica e fala do Cosmo, sem punição visual. |
| E.22 | Tela — Recompensa e celebração pós-missão | Celebração proporcional à raridade (XP/moedas/estrelas/itens) e o subir de nível em tela cheia do Cosmo. |
| E.23 | Tela — Tarefas do dia | Diárias, semanais e presente de login com progresso e resgate, viés para habilidades fracas. |
| E.24 | Tela — Loja e rotação semanal | Rotação de 4–6 itens + seção fixa com preços e escassez honesta, sem dark patterns nem compra real. |
| E.25 | ⚠️ Tela — Passe de temporada | Trilha única gratuita de recompensas; layout e formato exato ainda a confirmar pelo dono. |
| E.26 | Tela — Chama do Cosmo | Estado do streak (marcos, escudo semanal, reacender gentil), sempre acolhimento e nunca culpa. |
| E.27 | Tela — Amigos e código de amigo | Lista de amigos e código falável (COSMO-4F7B) para convite/aceite, sem busca por nome real. |
| E.28 | Tela — Convite e emparelhamento | Fluxo botão grande → amigos online → convite → contagem 3-2-1, sem matchmaking com estranhos. |
| E.29 | Telas — Modos sociais | Estudar com um amigo, Corrida (3 skins), Pintura em dupla e X1, com a regra de que derrota nunca custa nada. |
| E.30 | Tela — Mensagens rápidas | Catálogo de mensagens (saudação/elogio/convite/reação) com áudio, sem nenhum campo de texto livre. |
| E.31 | Tela — Ranking de turma semanal | Ranking que zera na segunda, celebra o top 3 e nunca expõe os últimos colocados (anti-lanterna). |
| E.32 | Telas — Professor no Edu | Panorama da turma, mapa BNCC, erros comuns, trajetória do aluno e alertas, sem ruído lúdico nem exposição individual à criança. |
| E.33 | ⚠️ Telas — Portal da Família | Resumo do filho e controles (social/horário) para o responsável; entrada e autorização do vínculo ainda a confirmar. |
| E.34 | Galeria consolidada de estados de erro/vazio/offline | Reúne as variações de estado por tela num só lugar para verificação de cobertura, evitando telas sem estado tratado. |
| E.35 | Telas de sistema | Sem licença, recurso desligado por kill-switch/flag e manutenção — o que a criança vê quando um recurso está indisponível (liga à Seção 19). |
| E.36 | Diálogos do Cosmo em contexto | Mapeia cada fala do Cosmo à tela onde aparece (recepção/torcida/dica/consolo/festa/descanso), remetendo ao guia da Seção 02.11. |
| E.37 | Acessibilidade nos mockups | Anota nas telas os alvos ≥48px, ordem de foco, modo daltônico, reduced-motion e o áudio obrigatório de cada instrução (liga à Seção 13). |
| E.38 | Anotação de telemetria nos mockups | Marca em cada tela/ação qual evento é disparado, amarrando os mockups ao Apêndice D e garantindo instrumentação por design. |
| E.39 | Anotação de i18n nos mockups | Marca strings externalizadas, expansão de texto entre idiomas e a paridade com o espelho EN (liga à Seção 16). |
| E.40 | Convenção de sincronização mockup ↔ implementação | Define a fonte de verdade de layout, quando o mockup precede o código e como detectar/registrar drift entre a tela desenhada e a construída. |
| E.41 | ⚠️ Ferramenta e formato dos mockups | Define em qual ferramenta e formato os mockups são produzidos e versionados; escolha ainda pendente do dono. |
| E.42 | Versionamento e nomenclatura dos arquivos | Padrão de nomes, numeração e versão dos arquivos de mockup, alinhado à convenção de arquivos da Bible (Seção 24.14). |
| E.43 | Governança do mockup (Portão 1) | Define quando um mockup vira normativo, quem aprova e como ele entra no fluxo de spec como referência de tela aprovada. |
| E.44 | ⚠️ Pendências: divergências mockup × código atual | Registra os conflitos vigentes (avatar 3D vs Cosmo 2D, catálogo cosmético hardcoded no cliente) que os mockups não podem canonizar até decisão do dono. |

**Perguntas ao dono:**
- Qual a ferramenta e o formato canônico dos mockups (Figma, protótipo HTML constela-play-v7, outro) e onde eles vivem no repositório?
- Os mockups devem canonizar o avatar humanoide 3D ou o Cosmo 2D? A decisão fundadora ainda aberta (Seção 04.2) muda Cerimônia e Vestiário.
- Qual o layout e os estados de referência do passe de temporada e do Portal da Família, telas ainda sem formato definido?
- Quando mockup e código em produção divergirem, qual é a fonte de verdade de layout — o mockup aprovado precede o código, ou o código vigente vira a referência?
- Qual o rótulo infantil canônico da tela-casa (o 'lobby' do código) a ser gravado nos mockups (liga à Seção 02.4)?

---

## F · Apêndice F — Checklists Consolidados (Definition of Done)
**Objetivo:** Reunir num só lugar, como listas de verificação acionáveis, os critérios de pronto espalhados pela Bible — DoD por tela/feature, o gate de revisão de QA da Seção 24.16, e as conformidades de LGPD/segurança, acessibilidade, performance no device-alvo e i18n. Serve para que toda entrega seja verificada de forma objetiva e repetível no Portão 3, sem recriar critérios.

| # | Subseção | Propósito |
|---|----------|-----------|
| F.1 | Como usar os checklists | Define o apêndice como fonte consolidada que remete à seção-dona de cada critério (não cria critério novo) e é obrigatório no Portão 3 de revisão. |
| F.2 | Anatomia de um item de checklist | Fixa o formato de cada item: afirmação verificável, evidência exigida, seção-fonte e severidade (bloqueante vs. recomendado). |
| F.3 | Definition of Done — por tela | Critérios de pronto de uma tela: todos os estados (vazio/carregando/erro/offline/sucesso), áudio, navegação, telemetria e cópia com vocabulário canônico. |
| F.4 | Definition of Done — por feature/sistema | Critérios de pronto de um sistema: spec aprovada, testes, regras numéricas não-hardcoded (quest.*), autoridade do servidor e auditoria. |
| F.5 | Definition of Done — por mecânica de jogo | Critérios de pronto de uma mecânica: contrato MecanicaProps, gabarito conferido no servidor, schema de conteúdo válido e acessibilidade. |
| F.6 | Definition of Done — por endpoint/contrato de API | Critérios de pronto de uma rota: papéis checados, isolamento por escola_id, erros padronizados, ETag/versão e gabarito nunca no cliente (remete ao Apêndice B). |
| F.7 | Definition of Done — por conteúdo pedagógico | Critérios de pronto de uma missão/desafio: código BNCC, áudio de enunciado, dica, explicação, revisão humana e versão publicada. |
| F.8 | Gate de revisão de QA (Portão 3) — visão consolidada | Reúne os sete eixos da Seção 24.16 (bugs, performance, UX, acessibilidade, responsividade, escalabilidade, organização) num único gate acionável. |
| F.9 | Checklist — Bugs e correção | Verifica severidade classificada, ausência de regressão e peso extra a itens que afetam a criança não-leitora. |
| F.10 | ⚠️ Checklist — Performance no device-alvo | Verifica orçamento de carga/memória e fluidez no hardware mínimo; os números concretos dependem da definição do device-alvo pelo dono. |
| F.11 | Checklist — UX e fluxo | Verifica 1 ação primária por tela, convite (não ordem), erro sempre acolhido e ausência de dark patterns. |
| F.12 | Checklist — Acessibilidade | Verifica áudio em toda instrução, alvos ≥48px, contraste, ordem de foco, reduced-motion, modo daltônico e tempo nunca como critério único (Seção 13). |
| F.13 | Checklist — Responsividade | Verifica os breakpoints-alvo, retrato/paisagem e ausência de overflow horizontal nas telas. |
| F.14 | Checklist — Escalabilidade | Verifica comportamento no pico de aula (metade das turmas às 7h30), índices por escola_id, rate-limit e gatilhos de Redis/réplicas. |
| F.15 | Checklist — Organização e qualidade de código | Verifica padrões do monorepo, tipos vindos de @constela/quest-core e ausência de regra numérica hardcoded. |
| F.16 | Checklist — Conformidade LGPD | Verifica coleta mínima, opt-in social, retenção configurável, anonimização na saída e ausência de foto/localização/texto livre (Seção 12). |
| F.17 | Checklist — Segurança | Verifica login código-só com rate-limit por (código, IP), JWT aluno rejeitado no Edu e vice-versa, escopo mínimo do papel, gabarito fora do cliente e ledger imutável. |
| F.18 | Checklist — i18n/localização | Verifica strings externalizadas, ausência de palavra proibida, sincronia texto↔áudio por locale e paridade com o espelho EN (Seção 16). |
| F.19 | Checklist — Telemetria e observabilidade | Verifica que cada ação instrumentada emite o evento correto do Apêndice D, com envelope válido, dedup offline e KPI mensurável. |
| F.20 | Checklist — Áudio e narração | Verifica que toda instrução tem áudio pt-BR, o botão 'ouvir de novo' funciona e a narração opera offline em cada passo. |
| F.21 | Checklist — Offline/PWA | Verifica shell offline, fila append-only de tentativas em IndexedDB, sync idempotente ao reconectar e token só em memória. |
| F.22 | Checklist — Social seguro | Verifica amizade só na mesma escola, ausência de texto livre, derrota que nunca pune, anti-spam e controles de presença/bloqueio. |
| F.23 | Checklist — Economia auditável | Verifica ledger imutável, saldo recomputável, erro que nunca subtrai moedas/estrelas e a ausência total de dinheiro real. |
| F.24 | Checklist — Vocabulário e cópia infantil | Verifica o mapa interno→criança, a ausência de palavras proibidas na UI e o tom de voz do Cosmo (Seção 02). |
| F.25 | Checklist — Conformidade com os Princípios Imutáveis | Verifica a suíte de regressão que trava as 16+2 invariantes imutáveis contra qualquer mudança (Seção 01 e 18.23). |
| F.26 | ⚠️ Portão de release por fase | Consolida a Definition of Done de fase e a régua 'a criança usa e quer voltar'; os limiares numéricos de saída dependem do dono. |
| F.27 | ⚠️ Checklist — Playtest com crianças | Verifica método, consentimento, roteiro e coleta com 6–11 anos; protocolo e caráter bloqueante ainda a confirmar pelo dono. |
| F.28 | Matriz checklist × seção-fonte | Cruza cada item de checklist com a seção que o governa, garantindo rastreabilidade e nenhum critério órfão. |
| F.29 | ⚠️ Automação dos checklists em CI | Define o que é automatizável (lint de vocabulário, testes de acessibilidade, contrato de eventos) como gate de merge; adoção a confirmar pelo dono. |
| F.30 | Evidência, sign-off e registro | Define como marcar pronto, qual evidência anexar e quem assina cada portão, fechando o laço de auditoria da entrega. |
| F.31 | Governança dos checklists | Regra de que item novo entra via spec/ADR e sincroniza com a seção-dona, mantendo os checklists vivos e sem critério duplicado ou desatualizado. |

**Perguntas ao dono:**
- Qual o device-alvo mínimo (modelos de tablet/Chromebook) e os números concretos de orçamento de carga/memória que tornam o checklist de performance verificável (Princípio 17)?
- Quais são os limiares numéricos do portão de release por fase (cobertura de testes, resultado de playtest, métricas mínimas) além da régua afetiva 'a criança volta amanhã'?
- O protocolo e o consentimento de playtest com crianças são item bloqueante do DoD antes de liberar uma fase em produção?
- Adotamos automação dos checklists em CI (lint de vocabulário proibido, testes de acessibilidade, contrato de eventos) como gate de merge obrigatório (liga à Seção 24.19)?

---

# 🔓 Decisões em aberto (consolidado)

Tudo marcado ⚠️ ou levantado como pergunta, reunido para resolvermos um a um, no dono canônico de cada.

### 00 · Visão & Norte
- ⚠️ **O norte como métrica ('a criança volta amanhã?')** — Régua afetiva de retenção usada como corte de fase no doc 05; alvos quantitativos (D1/D7/D30) e relação com aprendizado ficam a calibrar na Seção 17.
- ⚠️ **Ambição de qualidade e a tensão em aberto** — Registra a direção do dono por assets profissionais/3D em conflito com a arquitetura DOM/SVG-first; alcance e piso de desempenho a decidir (Seções 04/11/15).
- ⚠️ **Pendências desta seção (do QA)** — Lista o que falta calibrar: métrica-norte quantificável + guardrails, critérios de sucesso/'definição de lançamento' e posicionamento vs. incumbentes.
- ❓ Qual a métrica-norte quantificável (alvos D1/D7/D30) e seus guardrails, e como ela se relaciona formalmente com aprendizado e saúde de uso?
- ❓ Qual é a 'definição de lançamento' e os critérios objetivos de sucesso do produto?
- ❓ Como posicionar o Quest frente aos incumbentes (Matific, Elefante) — diferencial declarado de mercado?
- ❓ Qual o alcance da direção de 'assets profissionais/3D' (só avatar? jogo todo?) e como conciliá-la com o piso de desempenho em tablets/Chromebooks baratos?

### 01 · Princípios Imutáveis
- ⚠️ **A3 · LGPD Art. 14 — coleta mínima** — Sem foto/localização; nada além do que a escola cadastrou no Edu; social opt-in por escola; retenção de telemetria configurável (padrão sugerido 24 meses, a confirmar).
- ⚠️ **B7 · Sem compras dentro do app** — Moedas só se ganham jogando; sem moeda comprável, caixas pagas ou FOMO; escola licencia; passe gratuito (formato exato a confirmar).
- ⚠️ **E16 · Reuso do Edu, zero reconfiguração** — Quest reusa identidade do Edu; amizade nunca cruza escolas (teto imutável), mas escopo de lançamento (turma/escola) está aberto; integração Matific/Elefante por PDF/XLSX; identidade constela-play-v7.
- ⚠️ **O que NÃO é princípio (ainda em aberto)** — Lista o que aparece nos artefatos mas não está decidido: avatar 3D vs 2D, DOM/SVG-first vs Three.js, resíduo do PIN de figuras, amizade turma vs escola.
- ❓ Confirmar o prazo de retenção de telemetria (24 meses?) e o gatilho de anonimização na saída do aluno?
- ❓ Qual o formato exato do passe de temporada gratuito (trilha de recompensas, duração, reset)?
- ❓ Amizade no lançamento: mesma turma ou mesma escola? Social ligado ou desligado por padrão?
- ❓ Avatar definitivo: humanoide 3D (Three.js) ou Cosmo 2D como avatar do jogador?
- ❓ Three.js é oficial no núcleo do frontend (reescrevendo o DOM/SVG-first) ou fica restrito ao avatar?
- ❓ Autorizar a limpeza dos resíduos textuais do 'PIN de figuras' consolidando o login código-só?

### 02 · Vocabulário Canônico
- ⚠️ **Caso especial — tela-casa (lobby no código)** — 'lobby' é palavra proibida na UI e existe só no código; o rótulo infantil da tela-casa ainda não tem nome (proposta na Seção 03).
- ⚠️ **Caso especial — 'Meu astronauta' (perfil)** — Guarda-chuva conceitual do perfil que hoje aparece nas telas Vestiário e Carreira; o rótulo 'Meu astronauta' ainda é a confirmar.
- ❓ Qual o rótulo infantil oficial da tela-casa (o 'lobby' do código)?
- ❓ Confirmar 'Meu astronauta' como rótulo do perfil/guarda-chuva de Vestiário e Carreira?
- ❓ Oficializar os nomes próprios dos 9 planetas (catálogo detalhado na Seção 03)?

### 03 · O Universo & a Fantasia
- ⚠️ **Canonização e tradução dos nomes próprios** — Oficializar os 9 nomes (em especial Oxford e Terra Nova, hoje só no código) e a regra de que nomes próprios não se traduzem.
- ⚠️ **Tratamento dos planetas sensíveis (Ed. Física & ERER)** — Design próprio, curadoria pedagógica humana (não IA) e revisão de especialista; confirmar entrada em fase posterior (Q5).
- ⚠️ **Enquadramento narrativo & nível de enredo** — Decidir se há arco/conflito/vilão macro ou se o universo é cenário de exploração sem enredo central — define quanto roteiro será produzido.
- ⚠️ **Lore do universo & história de origem** — Define a história de fundo do universo Constela e do Cosmo e quem a roteiriza; hoje inexistente como texto canônico.
- ⚠️ **Fronteira Cosmo × avatar do jogador** — Cosmo é hoje guia e não avatar; o papel definitivo do avatar (humanoide 3D vs Cosmo 2D) está aberto e remete à Seção 04.
- ⚠️ **A tela-casa como nave-mãe / porto do universo** — Enquadra o 'lobby' como o hub de onde se viaja aos planetas; falta o rótulo infantil canônico (ligação com a Seção 02).
- ⚠️ **Mundo vivo & eventos sazonais** — Eventos pontuais (Festa Junina, Dia das Crianças, Halloween, Natal, Férias) que decoram o mapa e trazem colecionáveis limitados; calendário oficial BR a confirmar.
- ⚠️ **Escopo de conteúdo no lançamento** — Decidir entre 1 planeta profundo (ex.: Matemática) e 9 planetas rasos — define a densidade de conteúdo/arte a produzir primeiro.
- ❓ Oficializar os nomes próprios dos 9 planetas, em especial Oxford e Terra Nova (hoje só placeholders no código), e confirmar a regra de não-tradução?
- ❓ Existe um arco narrativo/enredo maior (vilão, conflito, missão-macro) ou o universo é um cenário de exploração sem enredo central?
- ❓ Deve haver uma lore/história de origem escrita do universo Constela e do Cosmo — e quem produz o roteiro?
- ❓ Qual o papel definitivo do avatar do jogador frente ao Cosmo (humanoide 3D vs Cosmo 2D)?
- ❓ Qual o rótulo infantil da tela-casa/nave-mãe (o 'lobby')?
- ❓ Escopo de conteúdo no lançamento: 1 planeta profundo ou 9 rasos?
- ❓ Confirmar que Ed. Física (Movi) e ERER (Raízes) entram só na Q5 com curadoria própria?
- ❓ Qual o calendário oficial de eventos sazonais para o lançamento no Brasil?

### 04 · Personagens & Avatar
- ⚠️ **A decisão fundadora do avatar — humanoide 3D vs Cosmo 2D** — Registra a escolha em aberto que define o restante da seção, com o histórico das Revisões 3/4 e o conflito arquitetural.
- ⚠️ **Cosmo customizável — sistema órfão** — Slots do Cosmo (rosto/chapéu/costas/mão/pet) que renderizam sem UI: decidir manter+construir UI ou remover.
- ⚠️ **Os 6 personagens-base (roster)** — O conjunto de presets iniciais oferecidos na cerimônia; identidade, ordem e disponibilidade de cada um.
- ⚠️ **Orçamento de desempenho e fallback** — Custo de carga/memória do avatar no device-alvo mínimo e a estratégia de degradação (ex.: fallback 2D).
- ⚠️ **Pipeline de produção de assets do personagem** — Quem cria os GLB e camadas trocáveis, formato de entrega e versionamento dos assets.
- ❓ Avatar definitivo do jogador: humanoide 3D (Three.js/R3F, já em código) OU Cosmo 2D como avatar? Dois sistemas coexistem hoje e precisam de decisão única.
- ❓ Se o avatar for 3D no núcleo, isso oficializa Three.js contra a arquitetura DOM/SVG-first do doc 01? Qual o piso de desempenho e o fallback 2D no device-alvo mínimo (tablet/Chromebook modesto)?
- ❓ Pipeline de arte: quem produz os GLB, as camadas trocáveis (cabelo, roupa, etc.) e os pets? Áudios/ilustrações serão gravados profissionalmente ou seguem TTS/SVG?
- ❓ O sistema 'Cosmo customizável' (rosto/chapéu/costas/mão/pet que renderizam sem UI) deve ser mantido e ganhar UI, ou removido como código órfão?
- ❓ Quais são exatamente os 6 personagens-base (nomes, fichas, paletas, vozes) que a criança escolhe na cerimônia da 1ª vez?
- ❓ As preferências 'musica' e 'reduzir_animacoes' do perfil ganham função/UI real ou saem do modelo?

### 05 · Sistemas de Jogo
- ⚠️ **Escudo semanal e regra de fim de semana** — 1 falta/semana não apaga a chama (renova segunda); fim de semana conta se jogar mas não quebra.
- ⚠️ **Passe de temporada gratuito** — Trilha única de recompensas por jogar; formato exato do passe a confirmar.
- ⚠️ **Escopo de conteúdo do lançamento** — Definir 1 planeta profundo vs 9 rasos, o que dimensiona a curva e a densidade de missões do MVP.
- ❓ Monetização: confirmar passe 100% gratuito e zero compras in-app em TODAS as fases, permanentemente?
- ❓ Qual o formato exato do passe de temporada (níveis, trilha de recompensas, XP do passe)?
- ❓ Escopo do conteúdo de lançamento: 1 planeta profundo (Matemática) vs 9 planetas rasos — impacta a curva e a régua de progressão?
- ❓ Confirmar os valores-padrão iniciais da economia (XP base, teto diário 600, curva 80+20n, preços da loja) ou tratá-los como proposta a calibrar?
- ❓ Fim de semana quebra a Chama por padrão (é configurável por escola) — qual é o padrão global de fábrica?

### 06 · Design Pedagógico & BNCC
- ⚠️ **Dificuldade pedagógica (1–5)** — Rubrica e critérios de calibração da dificuldade de cada desafio, definidos pelo autor pedagógico.
- ⚠️ **Interface/estúdio de autoria** — Por onde o conteúdo é cadastrado e publicado — CRUD admin, estúdio próprio ou import — ainda indefinido.
- ⚠️ **Escopo do conteúdo de lançamento** — Decidir 1 planeta profundo vs 9 rasos — define o volume de missões e a estratégia de produção do MVP.
- ⚠️ **Educação Física — desafios ativos** — Design próprio (vídeo curto + tarefa física + confirmação do professor); entrada e curadoria a confirmar.
- ⚠️ **ERER — conteúdo sensível** — Curadoria humana por especialista (não IA) e revisão antes de publicar; fluxo e responsável a definir.
- ⚠️ **Conexão com o software de matérias+questões futuro** — Como o catálogo se integra à plataforma de ensino própria do dono — integração nativa a definir.
- ❓ Por qual interface o catálogo pedagógico é cadastrado e publicado (estúdio de autoria próprio, admin do Edu, import JSON)?
- ❓ Como se conecta ao 'software de matérias+questões' futuro do dono — integração nativa, importação, ou fonte única de verdade?
- ❓ Escopo do conteúdo de lançamento: 1 planeta profundo (Matemática, 5 anos) vs 9 planetas rasos?
- ❓ Educação Física e ERER: confirmar entrada só na fase Q5, com design/curadoria próprios?
- ❓ Quem é o autor/responsável pedagógico que produz e valida o conteúdo BNCC e a rubrica de dificuldade (1–5)?
- ❓ ERER exige curadoria humana por especialista antes de publicar — quem é esse especialista e qual o fluxo de aprovação?

### 07 · UX, Fluxos & Navegação
- ⚠️ **Modelo de sessão como máquina de estados** — Documenta o estado atual (sessão sem router; estados boot/quem/entrando/cerimônia/tela-casa/jogo) e o contrato de transição entre eles.
- ⚠️ **Tela-casa (aba Jogar)** — Céu tocável, Cosmo companheiro e planetas-matéria ambientados; hub de retorno; falta o rótulo infantil oficial ('lobby' é palavra proibida).
- ⚠️ **Roteamento & deep-links** — Esquema de rotas/URLs: start_url do PWA, ?qr= de login, retomar missão, e link do Portal da Família — confirmar se vira router real.
- ⚠️ **Overlay exemplar: invocação do skate** — Caso de referência detalhado de overlay sobre o Vestiário (abrir/fechar, foco, áudio, reversibilidade) reutilizável por outros itens.
- ⚠️ **Decisões em aberto (UX)** — Consolida pendências: router vs máquina de estados, rótulo da tela-casa, esquema de deep-link, skate como overlay ou tela, device-alvo de animação.
- ❓ Adotamos um router real com deep-links (URLs para ?qr=, retomar missão, Portal da Família) ou mantemos a máquina de estados de sessão atual sem rotas navegáveis?
- ❓ Qual é o rótulo infantil oficial da tela-casa, já que 'lobby' é palavra proibida na UI e ainda não há nome canônico?
- ❓ A invocação do skate (e futuros itens do vestiário) deve ser um overlay sobre o Vestiário ou uma tela própria dedicada?
- ❓ Confirmar o esquema de deep-link do login por QR (?qr=) e quando/como o Portal da Família entra como rota navegável?
- ❓ Qual o device-alvo mínimo (tablet/Chromebook baratos) para calibrar o orçamento de transições e animações e fixar o piso de desempenho?

### 08 · Onboarding & FTUE do Aluno
- ⚠️ **Definição de ativação & hipótese de aha-moment** — Define o que conta como 'aluno ativado' e a hipótese do momento de encanto a validar; alvos ainda a calibrar.
- ⚠️ **Passo 3: 'Como você quer ser chamada?'** — Apelido por seleção/digitação validada (2–20, só letras), narrado; nunca texto livre; o nome passa a reger todas as falas.
- ⚠️ **Desenho da 1ª missão (missão de estreia)** — Missão-tutorial curada: mecânica introdutória simples, dificuldade baixa e desenho onde é impossível 'falhar'.
- ⚠️ **Pular o tutorial (leitor fluente)** — Permitir que a Sofia avance rápido sem punição, definindo o mínimo inegociável antes de liberar a tela-casa.
- ⚠️ **Métricas de ativação & funil de onboarding** — Eventos por passo, taxa de conclusão da 1ª missão, tempo até a 1ª recompensa e drop-off; alvos a calibrar (Seção 17).
- ⚠️ **Experimentação do onboarding** — A/B via live-ops de variantes da estreia com guardrails éticos para 6–11 anos; depende de autorização (Seção 19).
- ⚠️ **Decisões em aberto (Onboarding)** — Consolida pendências: definição de ativado, missão de estreia curada vs adaptativa, permitir pular, timing de revelar social e entrada da Família.
- ❓ Qual é a definição objetiva de 'aluno ativado' e a hipótese de aha-moment que vamos medir e validar (ex.: concluiu a 1ª missão e voltou no D1)?
- ❓ A 1ª missão é uma missão de estreia curada e fixa, ou já sai da seleção adaptativa/BNCC do ano escolar do aluno?
- ❓ Podemos permitir pular o tutorial para leitores fluentes, e qual é o mínimo inegociável antes de liberar a tela-casa?
- ❓ Quais são as metas de ativação D0/D1/D2 (taxa de conclusão da 1ª missão e retorno no 2º dia)?
- ❓ Autoriza A/B testing do onboarding via live-ops e, se sim, com quais guardrails éticos para crianças de 6–11 anos?
- ❓ Quando e como o Portal da Família entra no onboarding (momento do consentimento LGPD e do vínculo do responsável)?

### 09 · Social & Comunidade Segura / Safe Social
- ⚠️ **Alcance de amizade no lançamento (turma vs. escola)** — Define se, no lançamento, o círculo de amizade é a própria turma ou a escola inteira — controla filtro do código de amigo e da lista de contatos.
- ⚠️ **Default de social por escola/turma (opt-in vs. opt-out)** — Define o valor inicial de `social_ativo` numa nova escola/turma e se a ativação exige ação explícita do adulto.
- ⚠️ **Bloqueio e denúncia de comportamento** — Define status `bloqueada`, quem pode bloquear/denunciar (criança sozinha ou via adulto) e para onde vai o alerta de moderação.
- ⚠️ **Presença online e status** — Como o sistema calcula/exibe 'amigo online agora', privacidade da presença e se existe modo invisível.
- ⚠️ **Curadoria e versão do catálogo de mensagens** — Quem cadastra/aprova as mensagens rápidas, como se versiona e quais categorias existem no lançamento.
- ⚠️ **Anti-spam e limites de convites/mensagens** — Tetos de frequência (pedidos de amizade, convites de partida, mensagens rápidas) para impedir assédio por repetição, mesmo sem texto livre.
- ⚠️ **Skins oficiais da Corrida** — Fixa o conjunto canônico de skins — os docs divergem entre bichinhos/espacial/trilha e bichinhos/espacial/simples.
- ⚠️ **Reconexão e queda de wifi em partida** — Comportamento quando um jogador cai (pausa, timeout, encerramento gentil) para não punir a criança pela rede fraca da escola.
- ⚠️ **Torneios (fase futura)** — Esboça o espaço de competição opt-in, com começo/fim e medalha para todos os participantes.
- ⚠️ **Precedência e conflito de controles sociais** — Regra determinística de quem vence quando escola, turma e responsável divergem sobre ligar/desligar social.
- ❓ Alcance da amizade no lançamento: mesma turma ou escola inteira? (controla o filtro do código de amigo e da lista de contatos)
- ❓ O social vem ligado ou desligado por padrão numa escola/turma nova (opt-in explícito do adulto ou já ativo)?
- ❓ Qual o conjunto canônico das 3 skins da Corrida — os docs divergem entre bichinhos/espacial/trilha e bichinhos/espacial/simples?
- ❓ A criança pode bloquear/denunciar outra criança por conta própria, ou isso é mediado por professor/coordenador? Para quem vai o alerta?
- ❓ A presença 'online' é visível a todos os amigos ou só durante convites? Existe modo invisível?
- ❓ Quais os tetos de frequência para pedidos de amizade, convites de partida e mensagens rápidas (anti-assédio por repetição)?
- ❓ Quando um jogador cai por wifi no meio da partida, qual o comportamento esperado (pausa, timeout, encerrar sem penalidade)?
- ❓ Os torneios da fase futura são opt-in com medalha para todos? Há alguma premiação além da medalha?
- ❓ Quem cadastra/aprova o catálogo de mensagens rápidas e quais categorias existem no lançamento?
- ❓ Em conflito de controle social entre escola, turma e responsável, quem vence (qual a precedência determinística)?

### 10 · Professor & Família / Teacher & Family
- ⚠️ **Missão da Turma (atribuições)** — Define o professor destacar uma missão da semana que vira card especial no lobby dos alunos, apoiada na tabela leve `quest_atribuicoes`.
- ⚠️ **Modelo `quest_atribuicoes` e granularidade da atribuição** — Define os campos da nova tabela e se o professor atribui à turma inteira, a grupos ou a alunos, e o limite semanal.
- ⚠️ **Filtros, período e exportação de relatórios** — Define seletores de período/turma/aluno, paginação nos agregados e formatos de exportação (PDF/planilha reusando o Edu).
- ⚠️ **Reconhecimento do professor (presente/destaque)** — Define se o professor pode reconhecer um aluno (origem `presente_professor` no inventário) e como isso chega à criança sem virar competição.
- ⚠️ **Visão do coordenador/admin da escola** — Define se há uma visão consolidada multi-turma da escola aqui ou se pertence a Live-ops/gestão, e os controles sociais que o coordenador opera.
- ⚠️ **Quem autoriza o vínculo e fluxo de convite** — Define quem da escola confirma o vínculo (`autorizado_por`) e como o responsável recebe acesso (convite por e-mail, código, auto-cadastro validado).
- ⚠️ **Quando a API da Família entra (fase)** — Fixa a fase de entrega do portal (Q3 no roadmap) e o que precisa existir antes (telemetria e agregados de Q1/Q2).
- ⚠️ **Certificados em PDF** — Define gatilhos e modelo dos certificados reusando o gerador de PDF do Edu.
- ⚠️ **Controle: horário permitido** — Define a janela de horário (ex.: não jogar após 21h) e se o bloqueio é efetivo no servidor ou apenas informativo.
- ⚠️ **Controle: bem-estar (teto diário e pausa)** — Define teto diário de XP e a pausa do Cosmo (40 min, configurável) e quem os configura entre escola e família.
- ⚠️ **Notificações push (resumo semanal)** — Especifica o push de resumo para a família via outbox, com opt-in e frequência, garantindo que FOMO/push nunca vai para a criança.
- ⚠️ **Consentimento e onboarding da escola** — Define o termo de consentimento dos responsáveis como parte do onboarding da escola (documento padrão; escola coleta assinatura).
- ⚠️ **Multiplicidade: vários filhos e vários responsáveis** — Define visibilidade e poderes quando um responsável tem N filhos e um aluno tem N responsáveis (quem pode desligar social/impor horário).
- ⚠️ **Saída do aluno e ciclo de vida do vínculo** — Define o que acontece ao portal/vínculo quando o aluno sai da escola (perfil pausado, anonimização após prazo, acesso do responsável revogado).
- ❓ Quem autoriza o vínculo ResponsavelAluno — professor, coordenador/secretaria, ou processo no onboarding da escola? E como o responsável recebe acesso (convite por e-mail, código, auto-cadastro validado)?
- ❓ Confirmar a fase de entrada da API do Portal da Família (Q3 no roadmap)?
- ❓ O 'horário permitido' é bloqueio efetivo (impede login/jogo, imposto no servidor) ou apenas informativo/aviso?
- ❓ Quem define o teto diário de XP e a pausa de 40 min — escola, família ou ambos? Qual a precedência em caso de conflito?
- ❓ Certificados em PDF: quais os gatilhos (nível, conclusão de planeta, fim de temporada) e quais os modelos?
- ❓ O push semanal para a família exige opt-in explícito? A frequência é configurável?
- ❓ Missão da Turma (quest_atribuicoes): confirmar o modelo, se a atribuição é por turma/grupo/aluno e o limite semanal.
- ❓ O professor pode reconhecer/premiar um aluno (origem 'presente_professor')? Se sim, como isso chega à criança sem virar competição?
- ❓ Há visão consolidada multi-turma para coordenador/admin da escola nesta seção, ou isso pertence a Live-ops/gestão?
- ❓ Regras de multiplicidade: com vários responsáveis para um mesmo aluno, quem pode desligar o social e impor horário? Há hierarquia entre eles?
- ❓ Ao sair da escola: o acesso do responsável é revogado imediatamente? O portal reflete o perfil pausado e a anonimização após o prazo?

### 11 · Arquitetura Técnica
- ⚠️ **DECISÃO: renderização DOM/SVG-first vs Three.js no núcleo** — Reconciliar o doc 01 (DOM/SVG/CSS-first, 'PixiJS não Three.js') com o código que já usa Three.js no avatar, definindo o alcance oficial.
- ⚠️ **DECISÃO: piso de desempenho e device-alvo mínimo** — Definir device-alvo mínimo explícito e o orçamento de carregamento/memória/FPS ao qual toda arte e mecânica se subordina.
- ⚠️ **DECISÃO: plataformas-alvo (PWA instalável vs nativo)** — Definir se há app instalável/nativo além da web e em que fase entra.
- ⚠️ **DECISÃO: pipeline de produção de assets 3D/arte** — Definir quem produz os GLB e camadas trocáveis e se áudios/ilustrações são gravados ou sintetizados.
- ⚠️ **DECISÃO: interface de autoria/publicação do catálogo pedagógico** — Definir por qual ferramenta o conteúdo BNCC é cadastrado/publicado e a conexão com o software de matérias+questões futuro.
- ❓ DOM/SVG/CSS-first (doc 01) vs Three.js no núcleo do frontend: qual é a decisão oficial e qual o alcance dela — só o avatar (como já está no código), a tela-casa, ou o jogo todo?
- ❓ Qual é o device-alvo mínimo explícito (modelo/classe de tablet e Chromebook, RAM, GPU, versão de navegador) que serve de piso imutável?
- ❓ Qual o orçamento concreto de carregamento e memória (peso do bundle inicial, tempo até jogável, teto de RAM/VRAM, taxa de quadros mínima) que toda arte e mecânica deve respeitar?
- ❓ Plataformas-alvo além da web responsiva: PWA instalável e/ou apps nativos? Em que fase cada uma entra?
- ❓ Pipeline de arte/assets: quem produz os GLB 3D e as camadas cosméticas trocáveis; os áudios e ilustrações são gravados/desenhados por fornecedor ou sintetizados como hoje?
- ❓ Por qual interface o catálogo pedagógico (mundos/jornadas/missões/desafios/gabarito) é cadastrado e publicado, e como isso se conecta ao software futuro de matérias+questões do dono?
- ❓ Escopo de conteúdo de lançamento — 1 planeta profundo (ex.: Matemática) vs 9 planetas rasos — para dimensionar a arquitetura de conteúdo e seeds?

### 12 · Segurança, Privacidade & LGPD
- ⚠️ **Autorização do vínculo do responsável** — Define responsaveis_alunos e o campo autorizado_por; quem da escola confirma o vínculo e quando a API entra fica a decidir.
- ⚠️ **Social nunca cruza escolas (teto imutável)** — Fixa que amizades jamais atravessam escolas; o alcance de lançamento (turma vs escola) é decisão de produto pendente.
- ⚠️ **Opt-in social por escola** — Fixa que recursos sociais são desligados até a escola optar por ativá-los; o default é decisão de produto.
- ⚠️ **Política de retenção da telemetria detalhada** — Define retenção configurável das respostas das tentativas; o prazo-padrão sugerido de 24 meses precisa de confirmação.
- ⚠️ **Anonimização na saída do aluno** — Especifica perfil pausado → 'Aluno removido' e telemetria perdendo o vínculo nominal; o gatilho exato fica a confirmar.
- ⚠️ **Resposta a incidentes e vazamentos** — Define o processo mínimo de detecção, contenção e notificação; o procedimento formal precisa ser definido pelo dono.
- ⚠️ **Direitos do titular (acesso/eliminação)** — Define como atender pedidos de acesso/eliminação de dados via escola; o fluxo formal fica a decidir.
- ⚠️ **Encarregado (DPO) e política de privacidade pública** — Define a necessidade de um Encarregado designado e de política pública além do termo de escola; pendente do dono.
- ❓ Confirmar em definitivo o login código-só (sem senha/PIN) e autorizar a limpeza dos resíduos de 'PIN de figuras' nos docs antigos?
- ❓ Confirmar o prazo de retenção da telemetria detalhada (respostas das tentativas) — o padrão sugerido é 24 meses?
- ❓ Qual o gatilho exato de anonimização quando o aluno sai da escola: imediato ao arquivar, ao fim do prazo de retenção, ou outro?
- ❓ Quem autoriza o vínculo responsável↔aluno (escola, professor, coordenador) e em que fase entra a API do Portal da Família?
- ❓ Recursos sociais entram ligados ou desligados por padrão, e o alcance de lançamento é 'mesma turma' ou 'mesma escola'?
- ❓ Há Encarregado (DPO) designado e uma política de privacidade pública a publicar, além do termo de consentimento no onboarding da escola?
- ❓ Existe processo formal de resposta a incidente e de atendimento aos direitos do titular (acesso/eliminação) via escola?

### 13 · Acessibilidade & Bem-estar
- ⚠️ **Destino das preferências 'musica' e 'reduzir_animacoes'** — Registra que esses dois campos modelados precisam de UI/função definida ou remoção — decisão do dono.
- ⚠️ **Escopo de suporte assistivo estendido** — Define se leitor de tela e navegação por teclado entram além do público infantil e em que fase — pendente do dono.
- ⚠️ **Teto diário de XP como celebração, não bloqueio** — Fixa que o teto diário comemora e não trava; o valor-padrão vem da regra de progressão e precisa de confirmação.
- ⚠️ **Lembrete de pausa do Cosmo** — Define o lembrete de pausa (sugerido 40 min, configurável); o default precisa de confirmação do dono.
- ⚠️ **Definição do controle de horário permitido** — Especifica se a janela de uso é faixa livre configurada pela família ou faixas fixas — pendente do dono.
- ⚠️ **Acessibilidade x device-alvo (degradação graciosa)** — Define como animações e efeitos degradam em hardware fraco, ligando-se ao piso de desempenho da Seção 11.
- ❓ As preferências 'musica' e 'reduzir_animacoes' do perfil ganham UI e função própria, ou saem do modelo?
- ❓ O escopo de acessibilidade inclui suporte a leitor de tela e navegação por teclado além do público-alvo infantil? Em que fase?
- ❓ Confirmar os valores-padrão do teto diário de XP (celebração) e do lembrete de pausa do Cosmo (sugerido 40 min)?
- ❓ O controle de 'horário permitido' da família é faixa livre definida por eles ou faixas fixas pré-definidas?
- ❓ Em hardware abaixo do device-alvo mínimo, a redução de animações deve ser ativada automaticamente (ligado ao piso de desempenho da Seção 11)?

### 14 · Infraestrutura, Deploy, Backup & Disaster Recovery (SRE/DevOps)
- ⚠️ **Matriz de ambientes (dev / staging / prod)** — Define cada ambiente, seus limites de acesso, dados que pode conter e para que serve, incluindo o CI.
- ⚠️ **Provisionamento e Infra-as-Code** — Como a infra é declarada/reproduzível (arquivos de config do provedor, versionados) para recriar um ambiente do zero.
- ⚠️ **Rotação da chave JWT e token_version** — Procedimento e cadência de rotação da chave de assinatura JWT sem derrubar sessões válidas, articulado com token_version dos alunos.
- ⚠️ **RPO e RTO — alvos por classe de dado** — Define quanto dado se aceita perder (RPO) e em quanto tempo restaurar (RTO), diferenciando telemetria pedagógica de estado cosmético.
- ⚠️ **Criptografia e retenção dos backups** — Criptografia em repouso/trânsito dos backups, prazo de retenção e local de armazenamento sob LGPD (dado de criança).
- ⚠️ **Disaster Recovery — cenários e runbooks** — Catálogo de desastres (perda do banco, região do provedor fora, corrupção de dados) com runbook passo-a-passo de recuperação para cada um.
- ⚠️ **Observabilidade — métricas e dashboards** — Métricas RED/USE (latência, erro, throughput por rota; CPU/memória/conexões do banco) e os dashboards mínimos de operação.
- ⚠️ **SLI/SLO e error budget** — Define os indicadores (disponibilidade da API, sucesso de login do aluno, latência de submissão de tentativa) e as metas de nível de serviço.
- ⚠️ **Alertas e política de plantão (on-call)** — Quais condições alertam, por qual canal, com que severidade e quem responde fora do horário comercial.
- ⚠️ **Janela de manutenção e comunicação às escolas** — Como agendar manutenção respeitando o horário letivo e como avisar as escolas com antecedência — ponte com a Seção 21.
- ⚠️ **CDN de assets (áudio, sprites, GLB)** — Estratégia de armazenamento + CDN (Cloudflare R2 ou equivalente) para assets que não passam pelo backend, com cache/ETag e versionamento.
- ⚠️ **Capacidade e teste de carga (cenário 7h30)** — Cenário de carga de referência (turmas simultâneas de uma escola no início da aula) e como validar a capacidade antes de cada temporada.
- ⚠️ **Custos de infra e orçamento (FinOps)** — Acompanhamento de custo por ambiente/serviço (banco, CDN, IA) e teto orçamentário que dispara alerta.
- ❓ Existe verba/decisão para um ambiente de staging dedicado, ou o fluxo permanece dev→prod direto no push para main?
- ❓ Quais alvos de RPO/RTO o negócio aceita (ex.: perder no máximo X minutos de dados; restaurar em até Y)?
- ❓ Qual stack de observabilidade adotar (nativo do Railway, Grafana/Prometheus, serviço pago) e há orçamento para isso?
- ❓ Quem assume o plantão (on-call) e qual disponibilidade/SLA prometemos às escolas contratantes?
- ❓ Qual janela de manutenção é aceitável dado que as escolas usam em horário de aula (madrugada BR? fim de semana?) e por qual canal comunicá-la?
- ❓ Confirmar o provedor de CDN (Cloudflare R2 foi citado) e o orçamento de armazenamento/banda para áudio e GLB dos avatares?
- ❓ Qual a política de retenção dos backups e onde são armazenados (região/provedor), atendendo à LGPD de dados de criança?
- ❓ Autorizar a rotação periódica da chave JWT e definir a cadência (ex.: trimestral) e o procedimento aceito de invalidação?

### 15 · Direção de Arte, Áudio & Pipeline de Assets
- ⚠️ **Design do avatar humanoide (camadas trocáveis)** — Especifica o boneco estilo Roblox e seus slots: pele, cabelo, camiseta, calça, tênis, acessórios, costas(mochila/asas), mão(varinha), pet, skate.
- ⚠️ **Papel definitivo do avatar (3D humanoide vs Cosmo 2D)** — Resolve a contradição Revisão 3/4: quem é o avatar do jogador e o que vira legado a limpar.
- ⚠️ **Estratégia de renderização 2D vs 3D no núcleo** — Decide DOM/SVG/CSS-first vs Three.js/R3F oficial e onde cada um pode ser usado, conciliando com o piso de hardware.
- ⚠️ **Narração pt-BR: TTS vs áudio gravado** — Decide a estratégia definitiva de narração obrigatória (Web Speech API atual vs banco de áudios gravados em lote).
- ⚠️ **Orçamento de performance (por device-alvo)** — Fixa limites concretos de tamanho de download inicial, memória, texturas e draw calls por device-alvo mínimo.
- ⚠️ **Ferramentas e autoria (quem produz os assets)** — Define ferramentas e responsáveis pela produção de GLBs, camadas trocáveis, ilustrações e áudios gravados.
- ❓ O avatar definitivo do jogador é o humanoide 3D (Three.js/R3F) ou o Cosmo 2D? (Revisão 3 vs Revisão 4, mesma data, ainda em conflito)
- ❓ Three.js/R3F passa a ser oficial no núcleo do frontend, exigindo reescrever o doc 01 (DOM/SVG/CSS-first, 'PixiJS não Three.js')? Se sim, com que limites?
- ❓ Quem produz os assets 3D (GLB) e as camadas trocáveis do avatar, e sob qual verba/prazo?
- ❓ A narração definitiva será áudio gravado em lote (TTS de qualidade) substituindo a Web Speech API? Quem grava e quando entra?
- ❓ As trilhas musicais e ilustrações por planeta são produzidas por fornecedor, por agentes de IA, ou mistos? Quem faz a curadoria de consistência?
- ❓ Qual é o device-alvo mínimo explícito (modelo/RAM/GPU de tablet e Chromebook da escola) para calibrar o orçamento de performance e o teto de 3D?
- ❓ Qual o orçamento máximo de download inicial e de memória aceitável no device-alvo (para fechar os limites de 15.35)?
- ❓ O Cosmo customizável (rosto/chapéu/costas/mão/pet já renderizáveis mas órfãos de UI) entra no escopo de arte ou é aposentado?

### 16 · Localização & i18n
- ⚠️ **Prontidão para RTL e alfabetos não-latinos** — Registra o nível de preparo para direção RTL e scripts não-latinos, sem implementar antes de decidido.
- ⚠️ **Localização do conteúdo pedagógico (catálogo)** — Define como enunciados, dicas, explicações e mídia de desafios são traduzidos e alinhados a currículo local.
- ⚠️ **Pipeline e fluxo de tradução** — Define ferramenta, formato de exportação/importação e quem traduz/revisa cada camada de conteúdo.
- ⚠️ **Roadmap de idiomas futuros** — Registra quais idiomas entram, em que fase e com que profundidade (UI/áudio/conteúdo).
- ❓ Há intenção real de outros idiomas além do pt-BR (ex.: espanhol para LATAM, inglês)? Quais e em que fase do roadmap?
- ❓ Quanto investir agora em infraestrutura i18n vs entregar pt-BR-only e adaptar depois (o espelho EN dos docs é só para o time internacional)?
- ❓ O conteúdo pedagógico (missões/desafios BNCC) é multilíngue ou o catálogo é por país/currículo? Como isso se relaciona com o software futuro de matérias+questões?
- ❓ Em idiomas futuros a narração será gravada por locale ou TTS? Quem produz e revisa?
- ❓ Precisamos preparar RTL/alfabetos não-latinos ou o horizonte é apenas línguas latinas?
- ❓ Quem é o responsável e qual a ferramenta oficial do pipeline de tradução (contratada, comunidade, ou IA com revisão humana)?

### 17 · Telemetria, Métricas & Analytics
- ⚠️ **Métrica-norte quantificável** — Converte 'a criança volta amanhã?' em métrica-norte medível com alvo numérico (hoje só proposta a calibrar).
- ⚠️ **Guardrails de aprendizado** — Define métricas e limiares que impedem otimizar retenção às custas do aprendizado real (domínio BNCC).
- ⚠️ **Guardrails de saúde de uso e bem-estar** — Define sinais e limites de uso saudável (sessão longa, teto diário, pausa do Cosmo) como métrica de proteção.
- ⚠️ **KPIs de retenção (D1/D7/D30)** — Define retenção por coorte e seus alvos, base da régua de corte de fase do roadmap.
- ⚠️ **Privacidade e LGPD na telemetria** — Define retenção configurável (padrão 24 meses a confirmar) e gatilho de anonimização na saída do aluno.
- ⚠️ **Prontidão para experimentação/A-B** — Define se e como rodar experimentos, com a restrição ética de público infantil.
- ❓ Qual a definição quantitativa da métrica-norte e seus alvos (ex.: retenção D1/D7/D30 mínimos por coorte)?
- ❓ Quais são os limiares dos guardrails de aprendizado que, se violados, invalidam um ganho de retenção?
- ❓ Quais são os limites de saúde de uso (duração máxima saudável, teto diário, gatilho de pausa) tratados como guardrail formal?
- ❓ Confirma retenção de telemetria detalhada em 24 meses e o gatilho exato de anonimização quando o aluno sai da escola?
- ❓ É permitido rodar experimentos A/B com crianças? Sob quais limites éticos e de consentimento?
- ❓ Retenção tem ou não precedência formal sobre aprendizado? (o doc 00 hoje não afirma precedência até esta calibração)

### 18 · QA & Estratégia de Testes
- ⚠️ **Matriz de dispositivos e navegadores-alvo** — Define o conjunto exato de tablets/Chromebooks e navegadores em que o produto deve rodar bem.
- ⚠️ **Protocolo de playtest com crianças** — Define método, consentimento, faixa etária, roteiro e coleta de observação com 6–11 anos.
- ⚠️ **Fluxo de QA de conteúdo pedagógico** — Define revisão pedagógica humana das missões, com curadoria especial de ERER antes de publicar.
- ⚠️ **Critério de pronto e portão de release** — Consolida a Definition of Done por fase e o que precisa passar para liberar em produção.
- ❓ Qual é a matriz exata de dispositivos e navegadores-alvo (modelos de tablet/Chromebook e versões) que definem 'roda bem'?
- ❓ Qual a cadência dos playtests com crianças, e qual o processo de consentimento/logística com as escolas-piloto?
- ❓ Quem faz a revisão pedagógica das missões e a curadoria de ERER, e esse aval é bloqueante para publicar?
- ❓ Quais são os limiares numéricos do portão de release (cobertura de testes, resultado de playtest, métricas mínimas)?
- ❓ Escopo de conteúdo do primeiro release jogável: 1 planeta profundo (Matemática) ou 9 rasos? (afeta o que QA precisa cobrir)

### 19 · Live-ops & Config Remota
- ⚠️ **Controles sociais por escola/turma/aluno** — Especifica o opt-in social por escola e os desligamentos por turma e por aluno (social_ativo).
- ⚠️ **Configuração do passe de temporada** — Especifica a trilha de recompensas do passe gratuito e seu formato exato de operação.
- ⚠️ **Interface de autoria/publicação do catálogo** — Define por qual interface o conteúdo pedagógico é cadastrado e publicado, e a conexão com o software futuro de matérias+questões.
- ⚠️ **Rollout gradual e config em estágio** — Permite liberar mudança para um subconjunto de escolas antes da abertura geral.
- ⚠️ **Painel operacional / control room** — Define quem opera o live-ops e por qual painel (flags, temporadas, eventos, kill-switch).
- ❓ Qual é o formato exato do passe de temporada (níveis, ritmo, recompensas) confirmado como 100% gratuito?
- ❓ Por qual interface o catálogo pedagógico é cadastrado e publicado, e como ela se integra ao software futuro de matérias+questões?
- ❓ O social vem ligado ou desligado por padrão numa escola nova, e o alcance de amizade no lançamento é 'mesma turma' ou 'mesma escola'?
- ❓ Quem opera o live-ops (temporadas, eventos, flags, kill-switch) e por qual painel — reaproveita o Edu ou é ferramenta nova?
- ❓ Podemos fazer rollout gradual/segmentado de config e conteúdo entre escolas, e com quais critérios?
- ❓ Confirma que não há compras in-app em nenhuma fase e que toda regra numérica permanece configurável por escola?
- ❓ Ed. Física e ERER entram só na Q5 com curadoria própria, conforme documentado?

### 20 · Migração de Dados & Importação de Plataformas Externas
- ⚠️ **Provisionamento Quest a partir de alunos** — Como criar quest_perfis + quest_credenciais_aluno para os alunos matriculados, com isolamento por escola_id.
- ⚠️ **Fusão de perfis Quest** — Quando dois quest_perfis precisam ser fundidos, regras para combinar progresso, ledger e tentativas sem violar a imutabilidade — sempre manual.
- ⚠️ **Migração inicial da escola-piloto (cutover)** — Plano de corte da primeira escola: big-bang vs. por turma vs. período de coexistência, e como validar antes de expor as crianças.
- ⚠️ **Integração futura com o software de matérias+questões** — Como o catálogo/identidade se conectará à plataforma de ensino própria do dono — fonte única, import ou espelho — a definir.
- ⚠️ **Import de progresso pedagógico de terceiros** — Se e como desempenho histórico do Matific/Elefante entra no Quest, ou se o Quest começa do zero pedagogicamente.
- ❓ Além das matrículas (roster), deve-se importar progresso/desempenho histórico do Matific/Elefante para dentro do Quest, ou o Quest começa do zero pedagogicamente?
- ❓ O quest_perfil é criado automaticamente para todo aluno matriculado, ou só quando o professor gera os cartões / o aluno entra pela 1ª vez?
- ❓ Como se dará a integração futura com o software de matérias+questões (fonte única de verdade, importação ou espelho)?
- ❓ Qual o plano de corte (cutover) da escola-piloto: big-bang, por turma, ou período de coexistência Edu/Matific/Elefante?
- ❓ Por quanto tempo o arquivo-fonte (PDF/XLSX com dados de criança) pode ser retido após o import, sob a LGPD?
- ❓ Confirmar que a fusão de perfis Quest (progresso/ledger/tentativas), e não só de cadastro Edu, segue a mesma política manual 'na dúvida, não funde'?

### 21 · Suporte, Sucesso do Cliente & Operação de Escola
- ⚠️ **Ativação e configuração inicial** — Ligar a escola: configurações namespace quest.* (social opt-in/opt-out, horários, retenção) e valores padrão de fábrica.
- ⚠️ **Treinamento do professor** — Material, formato e duração da capacitação mínima do professor para conduzir a aula sem depender do suporte.
- ⚠️ **Helpdesk — canais e SLA** — Canais oficiais de atendimento, horário e tempo-alvo de resposta por severidade.
- ⚠️ **Métricas de sucesso do cliente** — Indicadores de ativação, adoção e engajamento por escola (alunos ativos/semana, missões concluídas, professores usando o painel).
- ⚠️ **Playbook de renovação e expansão** — Cadência de acompanhamento (QBR) e ações para renovar contrato e expandir para mais turmas/escolas da rede.
- ⚠️ **Runbook de acesso a dado de aluno pelo suporte** — Política de 'entrar como'/impersonar e de consulta a dado de criança pelo suporte, sempre auditada em logs_auditoria.
- ⚠️ **Modelo de suporte e SLA contratual por plano** — Define os níveis de suporte por tipo de contrato (tempo de resposta, horário, canais) — a decidir pelo dono.
- ⚠️ **Ferramenta de helpdesk e canais oficiais** — Qual sistema de tickets e quais canais (e-mail, WhatsApp, telefone) são oficiais — a decidir pelo dono.
- ⚠️ **Papel de Customer Success dedicado** — Se haverá função dedicada de sucesso do cliente e sua cadência, ou se o dono/professor-embaixador absorve o onboarding.
- ❓ Qual o modelo e o SLA de suporte por tipo de contrato (canais, horário de atendimento, tempo-alvo de resposta)?
- ❓ Qual ferramenta de helpdesk e quais canais oficiais de atendimento à escola/professor (e-mail, WhatsApp, telefone)?
- ❓ Haverá papel dedicado de Customer Success, ou o próprio dono/professor-embaixador absorve o onboarding e o acompanhamento?
- ❓ O suporte pode 'entrar como' (impersonar) professor/aluno para diagnosticar — e sob qual política de auditoria e consentimento?
- ❓ Quais métricas definem uma escola 'de sucesso' (ex.: % de alunos ativos/semana, nº de missões) e qual o gatilho de intervenção proativa?
- ❓ No offboarding, o que exatamente a escola/família leva consigo (exportações, certificados) e em que prazo os dados são anonimizados?
- ❓ Qual o valor de fábrica das configurações sensíveis por escola na ativação (social opt-in vs. opt-out, horário permitido, retenção)?

### 22 · Monetização & Modelo de Negócio / Business Model
- ⚠️ **Unidade de licenciamento** — Define o que exatamente é licenciado (escola inteira, rede/mantenedora, por aluno ativo, por turma) — parâmetro que dita todo o gating e faturamento.
- ⚠️ **Planos, tiers e pacote de recursos por plano** — Especifica se há níveis de licença e quais recursos (social, IA, relatórios avançados) ficam em cada um.
- ⚠️ **Precificação e moeda** — Faixa de preço, unidade (ex.: R$/aluno/ano) e moeda de cobrança — decisão exclusiva do dono.
- ⚠️ **Trial, piloto e freemium por escola** — Regras do período gratuito/piloto: duração, limites de uso e o que fica travado antes da conversão.
- ⚠️ **Ciclo de faturamento e cobrança** — Periodicidade (anual/mensal), quem emite nota (rede vs. escola) e integração com o financeiro do Edu — a confirmar pelo dono.
- ⚠️ **Passe de temporada: formato definitivo** — Número de níveis, duração (6–8 semanas), curva de XP do passe e recompensas — formato ainda a confirmar pelo dono.
- ⚠️ **Plataformas-alvo e fase de entrada** — Define se, além de web/PWA instalável, haverá apps nativos (iOS/Android) e/ou desktop, e em qual fase (Q?).
- ⚠️ **Distribuição e entrega** — Decide entre PWA instalável sem loja (padrão atual) vs. publicação em Play Store / App Store / Chromebook, com implicações de política de loja.
- ⚠️ **Métricas de negócio** — Indicadores comerciais (ativação de escola, churn de escola, LTV, alunos ativos por licença) — definição de metas remete à Seção 17.
- ⚠️ **Roadmap de monetização por fase** — Em que fase a cobrança real entra (hoje é piloto gratuito) e o que precede a comercialização.
- ❓ Qual é a unidade de licenciamento: escola inteira, rede/mantenedora, por aluno ativo ou por turma?
- ❓ Haverá planos/tiers de licença? Se sim, quais recursos (social, IA, relatórios) ficam em cada plano?
- ❓ Qual a faixa de preço e a unidade de cobrança (ex.: R$/aluno/ano) e a moeda?
- ❓ Como funciona o trial/piloto: gratuito por quanto tempo e com quais limites de uso?
- ❓ Ciclo de cobrança (anual/mensal) e quem emite a nota — a rede ou a escola?
- ❓ Em que fase (Q?) a cobrança de verdade entra? Hoje tudo é piloto gratuito?
- ❓ Além de web/PWA instalável, haverá apps nativos (iOS/Android) e/ou desktop, e em qual fase?
- ❓ Distribuição por lojas (Play/App Store/Chromebook) ou só PWA instalável sem loja?
- ❓ Confirmar como imutável: passe 100% gratuito e zero compras in-app em TODAS as fases?
- ❓ Formato definitivo do passe: número de níveis, duração (6–8 semanas) e recompensas?

### 23 · Roadmap & Fases (Q0–Q6) / Roadmap & Phases
- ⚠️ **Escopo de conteúdo por fase** — Decidir 1 planeta profundo (Matemática) vs. 9 planetas rasos no Q1 — decisão do dono que dimensiona todo o esforço de conteúdo.
- ⚠️ **Ordem de entrada dos planetas** — Sequência dos mundos (Matemática Q1, Português Q2, demais Q5) e a confirmação de Ed. Física e ERER só na Q5 com curadoria própria.
- ⚠️ **Reconciliação de desvios já ocorridos em Q0** — Consolidar ou reverter os desvios do plano (Three.js e avatar humanoide 3D no núcleo, contra o doc DOM/SVG-first) — pendência que trava o fechamento de Q0.
- ⚠️ **Definição de lançamento comercial** — Qual fase habilita cobrança e marketing e o que compõe o 'produto lançável' — critério ainda não definido (também sinalizado na Seção 00).
- ⚠️ **Marcos e datas-alvo por fase** — Se o roadmap é dirigido por data ou só por critério de pronto; e, havendo datas, quais são — a definir pelo dono.
- ⚠️ **Métricas de saída (gate quantitativo) por fase** — Além da régua afetiva, quais números liberam a passagem de fase (ex.: sessões fora do horário de aula em Q2) — metas remetem à Seção 17.
- ❓ Escopo de conteúdo do Q1: 1 planeta profundo (Matemática) para os 5 anos, ou vários planetas rasos?
- ❓ Confirmar Ed. Física e ERER apenas na Q5, com curadoria pedagógica própria?
- ❓ Qual é a 'definição de lançamento comercial': qual fase habilita cobrança e marketing?
- ❓ O roadmap tem datas-alvo por fase ou é dirigido só pelo critério de pronto (sem prazo fixo)?
- ❓ Como reconciliar os desvios de Q0 (Three.js e avatar humanoide 3D no núcleo): consolidar como oficial ou reverter para DOM/SVG-first?
- ❓ Confirmar a ordem dos planetas após Matemática (Português na Q2, demais na Q5)?
- ❓ Haverá metas quantitativas de saída de fase (ex.: retenção D1/D7) além da régua afetiva 'volta amanhã'?

### 24 · Governança da Bible / Bible Governance
- ⚠️ **Automação e CI da documentação** — Proposta de checagens automáticas: lint de vocabulário proibido, verificação de status, sincronia do espelho bilíngue e links — adoção a confirmar.
- ⚠️ **Delegação de aprovação e cadência (SLA)** — Se o dono delega aprovação de specs de baixo risco ao arquiteto e se há prazo/cadência de revisão para evitar bloqueios.
- ❓ O dono é o único aprovador ou delega a aprovação de specs de baixo risco/execução ao papel técnico?
- ❓ Há SLA/cadência para revisão e aprovação de specs, para não bloquear o desenvolvimento?
- ❓ Adotamos automação de CI da doc (lint de vocabulário proibido, checagem de status, sincronia bilíngue, links)?
- ❓ O inglês espelhado é obrigatório em cada commit ou pode entrar em lote depois (como o template já permite)?

### A · Apêndice A — Glossário / Glossary
- ⚠️ **Rótulos infantis ainda em aberto** — Verbetes cujo rótulo para a criança não está fixado: a tela-casa (hoje 'lobby' no código, palavra proibida) e o rótulo de perfil ('Meu astronauta').
- ❓ Confirmar o rótulo infantil da tela-casa (hoje 'lobby' no código, proibido na UI)?
- ❓ Confirmar 'Meu astronauta' como rótulo do perfil, ou outro nome?
- ❓ Os nomes próprios dos 9 planetas (Numéria, Palavras, Biozênia…) estão definitivos?

### B · Apêndice B — Contratos de API & Modelo de Dados / API & Data Contracts
- ⚠️ **Contrato — /familia** — GET filhos, GET resumo do filho, PATCH controles (social/horário) — leitura para o responsável; momento de entrada e autorização do vínculo a confirmar.
- ⚠️ **Schemas de conteúdo por mecânica** — Formato do `corpo` e do `gabarito` (JSON) de cada mecânica (quiz, arrastar, ligar, memória, caça-palavras, completar, sequência) — schema de cada uma a definir no design.
- ⚠️ **Contrato de tipos compartilhados (`@constela/quest-core`)** — Fonte única dos tipos da API para o cliente e o Edu web; nota sobre a consolidação do contrato de avatar (aposentar tipos legados do Cosmo).
- ⚠️ **Contrato de escrita do catálogo pedagógico (autoria)** — Por qual interface o catálogo (mundos→jornadas→missões→desafios) é cadastrado/publicado e a conexão com o software futuro de matérias+questões.
- ❓ Quem autoriza o vínculo responsável↔aluno e em que fase (Q3) a API /familia entra?
- ❓ As preferências `musica` e `reduzir_animacoes` permanecem no modelo (ganham UI/função) ou saem?
- ❓ Confirmar login código-só e autorizar a remoção dos resíduos de PIN dos contratos de /auth e docs?
- ❓ Por qual interface o catálogo pedagógico é cadastrado e publicado — admin no Edu, ou o software futuro de matérias+questões? Isso define o contrato de escrita.
- ❓ Consolidar o contrato de avatar (humanoide 3D) no @constela/quest-core, aposentando os tipos legados do Cosmo?

### C · Apêndice C — Registro de Decisões (ADR) / Decision Log
- ⚠️ **ADR candidato — Avatar definitivo (humanoide 3D vs. Cosmo 2D)** — Resolve qual é o avatar do jogador; hoje coexistem dois sistemas (código foi para 3D; docs dizem 'em aberto').
- ⚠️ **ADR candidato — Three.js oficial no núcleo** — Decide se Three.js/R3F entra oficialmente no núcleo do frontend, exigindo reescrever o doc DOM/SVG-first ('PixiJS, não Three.js').
- ⚠️ **ADR candidato — Pipeline de arte e assets 3D** — Define quem produz os GLB/camadas trocáveis e os áudios/ilustrações gravados, e o orçamento de produção.
- ⚠️ **ADR candidato — Login código-só e limpeza do PIN** — Confirma o login sem senha/PIN como vigente e autoriza remover os resíduos de 'PIN de figuras' dos docs 01/04 e contratos.
- ⚠️ **ADR candidato — Escopo de conteúdo do Q1** — 1 planeta profundo (Matemática) vs. 9 planetas rasos — dimensiona o gargalo de conteúdo.
- ⚠️ **ADR candidato — Interface de autoria do catálogo pedagógico** — Por qual interface o conteúdo é cadastrado/publicado e a conexão com o software futuro de matérias+questões.
- ⚠️ **ADR candidato — Amizades no lançamento e default social** — 'Mesma turma' vs. 'mesma escola' e se o social nasce ligado ou desligado por padrão.
- ⚠️ **ADR candidato — Retenção e anonimização de dados** — Confirma o prazo de retenção da telemetria (padrão sugerido 24 meses) e o gatilho de anonimização na saída do aluno.
- ⚠️ **ADR candidato — Monetização imutável** — Eleva a princípio: passe 100% gratuito e zero compras in-app em todas as fases.
- ⚠️ **ADR candidato — Plataformas-alvo e fase** — Apps nativos/desktop além do PWA instalável e em qual fase entram.
- ⚠️ **ADR candidato — Ed. Física e ERER na Q5** — Confirma a entrada desses dois planetas só na Q5, com curadoria pedagógica humana própria.
- ⚠️ **ADR candidato — Portal da Família / vínculo responsável** — Quando a API /familia entra e quem autoriza o vínculo responsável↔aluno.
- ⚠️ **ADR candidato — Preferências `musica` e `reduzir_animacoes`** — Decide se essas preferências ganham função/UI ou saem do modelo de dados.
- ⚠️ **ADR candidato — Device-alvo mínimo e orçamento de desempenho** — Fixa o hardware-alvo mínimo (tablet/Chromebook modesto) e os números concretos de carregamento/memória (Princípio 17).
- ⚠️ **ADR candidato — Métrica-norte quantificável** — Transforma 'volta amanhã?' em metas (D1/D7/D30) e guardrails de aprendizado e saúde de uso (Seção 00/17).
- ❓ Quais dos ADRs candidatos (C.12–C.26) você quer decidir primeiro para desbloquear o desenvolvimento?
- ❓ Avatar definitivo e Three.js no núcleo são a decisão mais urgente (dois sistemas coexistem hoje) — quer resolvê-los juntos num único ADR ou separados?
- ❓ Confirma elevar a monetização (passe grátis + zero compras) a ADR imutável agora?
- ❓ Autoriza abrir o ADR de login código-só para limpar formalmente os resíduos de PIN nos docs e contratos?

### D · Apêndice D — Catálogo de Eventos de Telemetria
- ⚠️ **Retenção e anonimização por classe de evento** — Define por quanto tempo cada classe de evento é guardada e o gatilho de anonimização na saída do aluno — padrão sugerido a confirmar pelo dono.
- ⚠️ **Evento de atribuição de experimento (A/B)** — Especifica o evento que registra a variante de um experimento, condicionado à autorização de A/B com crianças ainda pendente do dono.
- ❓ Confirmar o prazo de retenção por classe de evento (padrão sugerido 24 meses) e o gatilho exato de anonimização quando o aluno sai da escola (liga à Seção 17.21).
- ❓ É permitido emitir eventos de atribuição de experimento (A/B) com público infantil? Sob quais limites éticos e de consentimento (liga à Seção 17.28)?
- ❓ Qual o destino operacional dos eventos rejeitados no ingest (dead-letter): descartar, quarentenar para revisão, e quem revisa?
- ❓ Podemos coletar app_version e uma classe de device (não o modelo exato) por evento para diagnóstico, sem ferir a minimização (Princípio 3/18)?
- ❓ Amostragem de eventos de alto volume é autorizada, ou todo evento-núcleo deve ser 100% coletado para não perder fidelidade dos KPIs?

### E · Apêndice E — Wireframes/Mockups de Referência
- ⚠️ **Tela — Passe de temporada** — Trilha única gratuita de recompensas; layout e formato exato ainda a confirmar pelo dono.
- ⚠️ **Telas — Portal da Família** — Resumo do filho e controles (social/horário) para o responsável; entrada e autorização do vínculo ainda a confirmar.
- ⚠️ **Ferramenta e formato dos mockups** — Define em qual ferramenta e formato os mockups são produzidos e versionados; escolha ainda pendente do dono.
- ⚠️ **Pendências: divergências mockup × código atual** — Registra os conflitos vigentes (avatar 3D vs Cosmo 2D, catálogo cosmético hardcoded no cliente) que os mockups não podem canonizar até decisão do dono.
- ❓ Qual a ferramenta e o formato canônico dos mockups (Figma, protótipo HTML constela-play-v7, outro) e onde eles vivem no repositório?
- ❓ Os mockups devem canonizar o avatar humanoide 3D ou o Cosmo 2D? A decisão fundadora ainda aberta (Seção 04.2) muda Cerimônia e Vestiário.
- ❓ Qual o layout e os estados de referência do passe de temporada e do Portal da Família, telas ainda sem formato definido?
- ❓ Quando mockup e código em produção divergirem, qual é a fonte de verdade de layout — o mockup aprovado precede o código, ou o código vigente vira a referência?
- ❓ Qual o rótulo infantil canônico da tela-casa (o 'lobby' do código) a ser gravado nos mockups (liga à Seção 02.4)?

### F · Apêndice F — Checklists Consolidados (Definition of Done)
- ⚠️ **Checklist — Performance no device-alvo** — Verifica orçamento de carga/memória e fluidez no hardware mínimo; os números concretos dependem da definição do device-alvo pelo dono.
- ⚠️ **Portão de release por fase** — Consolida a Definition of Done de fase e a régua 'a criança usa e quer voltar'; os limiares numéricos de saída dependem do dono.
- ⚠️ **Checklist — Playtest com crianças** — Verifica método, consentimento, roteiro e coleta com 6–11 anos; protocolo e caráter bloqueante ainda a confirmar pelo dono.
- ⚠️ **Automação dos checklists em CI** — Define o que é automatizável (lint de vocabulário, testes de acessibilidade, contrato de eventos) como gate de merge; adoção a confirmar pelo dono.
- ❓ Qual o device-alvo mínimo (modelos de tablet/Chromebook) e os números concretos de orçamento de carga/memória que tornam o checklist de performance verificável (Princípio 17)?
- ❓ Quais são os limiares numéricos do portão de release por fase (cobertura de testes, resultado de playtest, métricas mínimas) além da régua afetiva 'a criança volta amanhã'?
- ❓ O protocolo e o consentimento de playtest com crianças são item bloqueante do DoD antes de liberar uma fase em produção?
- ❓ Adotamos automação dos checklists em CI (lint de vocabulário proibido, testes de acessibilidade, contrato de eventos) como gate de merge obrigatório (liga à Seção 24.19)?

---

# 🧪 Notas do crítico de completude

> As **8 lacunas estruturais** originais já foram supridas pelas novas seções **07, 08, 14, 20, 21** e
> apêndices **D, E, F**. As lacunas de detalhe abaixo devem ser integradas quando cada seção for escrita.
> *Referências de número abaixo são do rascunho provisório — servem como guia de conteúdo, não como âncora.*

### Lacunas de detalhe a integrar

| Seção | Subseção que falta | Motivo |
|-------|--------------------|--------|
| 05 — Sistemas de Jogo | Fuso horário e virada de dia/semana | Teto diário, Chama do Cosmo, missões diárias/semanais, escudo de segunda e reset do ranking semanal dependem todos da definição de 'dia' e 'semana', mas nenhuma subseção fixa o fuso horário de referência (UTC? fuso da escola? do aparelho?) nem o horário de corte. Sem isso o dev não implementa determinismicamente reset nem detecta abuso de virada de dia. |
| 05 — Sistemas de Jogo | Idempotência e concorrência de tentativas e do ledger | 5.10/5.35/5.46 tratam ledger imutável e sync offline, mas não há regra de chave de idempotência para finalizar tentativa (double-submit, retry de rede, reenvio da fila offline) nem tratamento de compras/creditos simultâneos. Sem isso há risco de XP/moedas duplicados no reconectar. |
| 05 — Sistemas de Jogo | Estado inicial/vazio do jogador novo | Não há especificação do primeiro estado: constelação zerada, nível 1, zero estrelas, sem diárias geradas, sem colecionáveis. O core loop e a tela de progresso precisam do comportamento de 'dia zero' explícito. |
| 04 — Personagens & Avatar | Avatar padrão pré-cerimônia e falha de carregamento de asset | 4.19 define a cerimônia e 4.24 o fallback 2D de performance, mas falta o estado do avatar antes de qualquer escolha (default determinístico) e o comportamento de erro quando o GLB/camada falha ao baixar (placeholder, retry, degradação) — caminho comum em wifi de escola. |
| 06 — Design Pedagógico & BNCC | Aluno fora de faixa, turma multisseriada e ano indefinido | 5.16/3.24 travam a progressão pela matrícula (turmas.ano_escolar), mas não cobrem turma multisseriada (comum no Brasil rural), aluno adiantado/defasado, ou matrícula sem ano definido. Sem isso o gating de jornadas quebra para uma parcela real de alunos. |
| 10 — Professor & Família | Estados vazios dos painéis e professor multi-turma/multi-escola | 10.5–10.9 assumem dados existentes; falta o estado vazio (turma recém-criada sem telemetria, aluno que nunca jogou) e o caso de professor com várias turmas/escolas ou docência compartilhada, que afeta seleção de escopo e agregação. |
| 10 — Professor & Família | Troca de professor titular e transferência de turma | 10.33 cobre saída do aluno, mas não a rotatividade do adulto: substituição do professor, transferência de turma entre docentes, e o que acontece com atribuições/Missão da Turma e histórico de acesso nesse handover. |
| 11 — Arquitetura Técnica | Backup, restauração e disaster recovery | Nenhuma subseção trata backup do Postgres, RPO/RTO, teste de restore ou recuperação de desastre — inaceitável para base com dados de crianças. 11.44 só cobre migrações/paridade dev-prod. |
| 11 — Arquitetura Técnica | Deploy, rollback de código e migrações zero-downtime | 19 cobre config-sobre-deploy, mas falta a engenharia de release do próprio código: estratégia de deploy, rollback de versão, migração de esquema sem downtime durante o pico de aula, e compatibilidade de esquema durante o rollout. |
| 11 — Arquitetura Técnica | Gestão de segredos e rotação da chave JWT | 12.9 trata token_version por aluno, mas não há tratamento da chave de assinatura do JWT (armazenamento, rotação, revogação em massa) nem gestão de segredos (DB, Redis, CDN) — pré-requisito de segurança. |
| 11 — Arquitetura Técnica | Concorrência e entrega do outbox (idempotência do consumidor) | 11.17/11.42 definem o outbox como produtor imutável, mas não a semântica de entrega (at-least-once vs exactly-once), locking do processador, deduplicação no consumidor de push/mural e retry/dead-letter para eventos que falham. |
| 12 — Segurança, Privacidade & LGPD | Espaço do código de login e defesa contra enumeração | 12.3–12.5 fixam a credencial e o rate-limit, mas não a entropia/tamanho do espaço de códigos nem defesa contra enumeração sistemática (colisão, adivinhação dentro da mesma escola). Sem dimensionar o espaço, o rate-limit isolado não garante segurança. |
| 12 — Segurança, Privacidade & LGPD | Segurança e criptografia de backups | Dados de crianças em backup precisam de criptografia em repouso, controle de acesso e retenção/descarte dos próprios backups — tema ausente e não coberto por 12.22–12.28 (que tratam dados vivos). |
| 09 — Social & Comunidade Segura | Workflow de moderação e amizade órfã | 9.8 cria bloqueio/denúncia mas não define a fila de moderação, quem trata, SLA e destino do alerta; e falta o comportamento da amizade quando o amigo é transferido/arquivado (vínculo órfão, presença, salas). |
| 19 — Live-ops & Config Remota | Observabilidade operacional (SLO/SLI, alertas, on-call, manutenção) | 11.43 promete observabilidade mínima e 19.24 um runbook, mas falta SLO/SLI, monitoramento de uptime, alertas operacionais, escala de plantão e comunicação de janela de manutenção às escolas — necessário para operar em produção. |
| 18 — QA & Estratégia de Testes | Testes de migração/upgrade de banco e de restore de backup | 18 cobre unidade a E2E e carga, mas não valida o caminho de migração de esquema entre versões nem a recuperação a partir de backup — os dois riscos operacionais de maior impacto ficam sem cobertura. |
| 18 — QA & Estratégia de Testes | Testes de concorrência/race na economia | 18.6 prova invariantes do ledger em cenário sequencial, mas não há teste de corrida (compras/creditos simultâneos, reenvio offline concorrente) que é onde a economia auditável realmente falha. |
| B — Contratos de API & Modelo de Dados | Contrato de leitura de config quest.* e health/status | B.23 descreve o esquema de configurações mas não há endpoint para o cliente buscar as regras numéricas por escola, nem endpoint de health/status/versão para operação e PWA — ambos necessários para implementar. |
| B — Contratos de API & Modelo de Dados | Chaves de idempotência nas rotas de escrita | B.4 (finalizar tentativa) e B.6 (comprar) não especificam header/campo de idempotência nem o comportamento de reenvio, deixando ambíguo o retry seguro do cliente offline. |
| 17 — Telemetria, Métricas & Analytics | Qualidade de dados e deduplicação de eventos offline tardios | 17.24 menciona flag de origem, mas falta a política de validação de esquema no ingest, descarte de evento malformado e deduplicação/ordenação de eventos que chegam muito atrasados após reconexão. |
| 02 — Vocabulário Canônico | Vocabulário de erro, vazio e offline para a criança | 2.10/2.11 dão o tom e falas de acerto/erro pedagógico, mas não há guia canônico do que a criança vê/ouve em falha de rede, tela vazia, item indisponível ou app offline — texto/áudio que o dev vai precisar para todos os estados de erro. |
| 15 — Direção de Arte, Áudio & Pipeline | Catálogo canônico de estados de UI (vazio/carregando/erro/offline) | 15.17 lista componentes com estados, mas não há um catálogo transversal padronizando o visual+áudio de cada estado (vazio, carregando, erro, offline, sem permissão) reutilizável por todas as telas. |
| 03 — O Universo & a Fantasia | Comportamento quando a escola não oferece uma matéria/planeta | Assume-se 9 planetas, mas não há regra para quando a escola/currículo não contempla uma matéria: o planeta some, aparece bloqueado, ou vira 'em breve'? Afeta a montagem da tela-casa e o gating. |
| 13 — Acessibilidade & Bem-estar | Degradação quando o áudio obrigatório não pode tocar | 13.3 exige áudio em toda instrução, mas falta o comportamento quando o áudio não está disponível (dispositivo no mudo, autoplay bloqueado pelo navegador, sem alto-falante) — caso real que precisa de fallback visual/gesto para não travar o não-leitor. |

### Temas transversais mapeados a um dono canônico (17)

- **Escopo de conteúdo no lançamento (1 planeta profundo vs 9 rasos)** → Decisão de produto: mora como ADR candidato em C.16 e como fase em 23.13. As demais (3.29/5.47/6.19) devem apenas referenciar, não redecidir.
- **Renderização DOM/SVG-first vs Three.js no núcleo** → Decisão técnica arbitrada por ADR em C.13; a especificação técnica canônica vive em 11.47. 04/15/23 devem só apontar o ADR.
- **Avatar do jogador: humanoide 3D vs Cosmo 2D** → Canônico na Seção 04 (4.2) por ser dona do avatar; ADR em C.12. 03 e 15 referenciam.
- **Retenção de telemetria (24 meses) e anonimização na saída** → Política canônica na Seção 12 (LGPD); ADR em C.19. 17.21 e 1.5 apenas remetem para não divergir de prazo.
- **Passe de temporada gratuito e seu formato** → Mecânica em 05, gratuidade imutável como princípio em 22.9/ADR C.20, operação/config em 19.9. Formato exato decidido uma vez (22.10) e referenciado.
- **Social: default (opt-in) e alcance turma vs escola** → Regra de produto canônica na Seção 09 (9.4/9.5), teto legal em 12.16, ADR em C.18; 19.7 é só o mecanismo de config.
- **Rótulo infantil da tela-casa (o 'lobby')** → Pertence ao Vocabulário (2.4) como decisão única; 03, 15 e o glossário A.13 apenas remetem.
- **Device-alvo mínimo e orçamento de desempenho** → Número canônico fixado em 11.48 (arquitetura) via ADR C.25; 4.24/15.35/18.16 consomem esse piso, não o redefinem.
- **Interface de autoria/publicação do catálogo pedagógico** → Decisão de produto em 6.16 + ADR C.17; contrato de escrita em B.27; 19.15 é a operação de publicação. Consolidar para uma fonte.
- **Rate-limit distribuído (memória → Redis)** → O gap arquitetural e o alvo distribuído vivem em 11.45; 12.6 deve apenas referenciar como controle de segurança, sem duplicar o desenho.
- **Preferências 'musica' e 'reduzir_animacoes' órfãs** → Destino canônico na Seção 13 (13.15, acessibilidade) com ADR C.24; a menção em 04 é só levantamento.
- **Motor de corrida único e as 3 skins (divergência bichinhos/espacial/trilha vs simples)** → Motor/mecânica canônica em 05/11; skins como arte em 15.22; a divergência de nomenclatura deve ser resolvida em um só lugar (9.16) e propagada.
- **Métrica-norte quantificável e guardrails** → Definição operacional e alvos na Seção 17; 0.11 mantém só a régua afetiva; ADR C.26 fixa os números.
- **Ed. Física (Movi) e ERER (Raízes): entrada na Q5 e curadoria humana** → Design e curadoria pedagógica em 06 (6.27/6.28), fase em 23.14/ADR C.22, gate de QA em 18.27; 03 só descreve identidade.
- **Controles sociais opt-in em três níveis e precedência** → Regra de precedência determinística canônica em 9.32; 10.24 (toggle família), 12.24 (base legal) e 19.7 (config) referenciam essa regra única.
- **Autoridade do gabarito no servidor** → Princípio em 1.15, contrato técnico canônico em 11.20; 05/12/18/B são aplicações e testes que citam 11.20 sem redefinir.
- **Login código-só e limpeza dos resíduos de 'PIN de figuras'** → Modelo de ameaça e contrato em 12.2/B.1; princípio em 1.3; a limpeza autorizada via ADR C.15. Uma fonte para o formato do código.

