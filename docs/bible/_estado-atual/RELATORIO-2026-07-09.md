# Relatório de Estado Atual — Constela Quest

> **Documento interno de referência (pt-BR).** Fotografia fiel do que existe em
> 2026-07-09, produzida por auditoria read-only de `docs/quest/`, `backend/app/quest/`,
> `apps/quest/src/`, `packages/*` e do histórico Git. Alimenta as seções de "estado
> atual" da Constela Quest Bible. Não é decisão — é inventário.

## 1. Resumo executivo

O Constela Quest é a plataforma dos alunos (1º ao 5º ano) do ecossistema Constela,
construída como **monólito modular** dentro do mesmo monorepo e backend FastAPI do
Constela Edu (módulo `backend/app/quest` + app `apps/quest`, PWA React+Vite+TS), com
**dependência de mão única** (Quest importa o núcleo Edu; Edu nunca importa Quest).

O estado real é **assimétrico**: a documentação (`docs/quest/`, 6 Markdown maduros) e o
modelo de dados descrevem um jogo completo (economia de 3 moedas, social, temporadas,
professor/família, IA), mas **apenas a Fase Q0 (fundação) está em código e produção**.
Fundação sólida e bem arquitetada; o gargalo declarado é o conteúdo pedagógico e toda a
mecânica jogável de Q1 em diante.

## 2. Inventário por status

### 🟢 Pronto (Q0 — a casca viva)
- **Login infantil sem senha** (código `SOL1234` = credencial; QR alternativo; fluxo 2 etapas *quem* → *entrar*; rate-limit por (código, IP)).
- **Cartões PDF/QR** gerados pelo professor via Edu (turma 2×4 + página só-do-professor; individual; regenerar por `token_version`).
- **Situação de acesso da turma** (consulta pelo Edu).
- **Perfil cosmético** (GET perfil; PATCH nome/avatar/preferências com whitelists estritas).
- **Cerimônia de 1ª vez** (escolher personagem 3D → apelido → festa).
- **Lobby** com 3 abas (Jogar/Vestiário/Carreira), céu tocável, Cosmo companheiro, 9 planetas-matéria ambientados.
- **Vestiário** (customização do avatar humanoide 3D, 9 categorias, invocação do skate).
- **Avatar humanoide 3D** (Three.js/R3F/drei, procedural e vivo, lazy-load).
- **Mascote Cosmo 2D** (SVG vivo, física de mola).
- **Áudio/narração offline pt-BR** (WebAudio sintetizado + Web Speech API).
- **PWA/offline** (Workbox precache do shell; API nunca em cache; token só em memória).
- **Pacotes compartilhados** `@constela/core` + `@constela/quest-core`.

### 🟡 Parcial
- **Carreira** (stats + 8 conquistas derivadas; "Minhas aventuras" é estado vazio; conquista "Estilista espacial" usa campos do avatar legado → bug).
- **Catálogos cosméticos** (endpoints existem mas são **públicos**; o app **não os consome** — itens do vestiário estão hardcoded no cliente).
- **Cosmo customizável** (rosto/chapéu/costas/mão/pet renderizam, mas sem UI que edite — sistema órfão).
- **Modelo de dados do jogo** (10 tabelas grupos 1–3 mapeadas; **nenhum endpoint** lê/grava catálogo, progresso, tentativas).

### ⬛ Planejado (Q1–Q6, documentado, sem código)
- **Núcleo jogável** (MissaoPlayer + mecânicas; submissão de tentativa; XP/estrelas/moedas). — Q1
- **CRUD de catálogo + seeds BNCC** (pasta `conteudo/` **vazia**). — Q1
- **Economia** (moedas, loja, passe). — Q2/Q5
- **Retenção** (diárias/Chama, conquistas, constelação, adaptativa v1). — Q2
- **Professor & família** (`ResponsavelAluno` modelado, sem endpoint). — Q3
- **Social** (amizades, corrida, salas/WS, ranking de turma). — Q4
- **Mundo vivo** (temporadas/passe, eventos, planetas restantes, Redis). — Q5
- **IA** (Cosmo explica erros, adaptativa v2, gerador de desafios). — Q6
- **`quest_outbox`** (base da integração Quest→Edu) — sem model ainda.

## 3. Arquitetura (como está)

Monólito modular; banco compartilhado (PostgreSQL prod / SQLite dev, SQLAlchemy 2), tabelas
prefixadas `quest_` em 8 grupos (só 1–3 existem). Pilares técnicos declarados: **servidor é a
autoridade do gabarito** (catálogo entregue sem `gabarito`), **economia por ledger imutável**,
**histórico de tentativas imutável**, **isolamento multi-escola por `escola_id`**. Frontend:
máquina de estados de sessão sem router; **token só em memória**; dois mundos de JWT
(`papel='aluno'` rejeitado no Edu e vice-versa). 3D em Three.js lazy-carregado.

## 4. Constraints de produto imutáveis (fonte: docs + código)

1. Login só com código, sem senha/PIN (o código impresso pode ficar exposto).
2. Servidor é a autoridade do gabarito.
3. Sem chat livre — nenhum texto livre ao aluno (só o nome de exibição, validado).
4. Sem compras no app; moedas só se ganham jogando; passe de temporada gratuito.
5. Erro nunca pune; XP só cresce; estrela nunca é perdida; teto diário é celebração.
6. Narração sempre pt-BR; áudio obrigatório.
7. Conta não fica salva ao sair; boot confirma "É você, {nome}?".
8. A criança escolhe como quer ser chamada na 1ª sessão.
9. Vocabulário lúdico fixo (interno→criança); palavras proibidas na UI infantil.
10. Ranking municipal individual nunca exposto a crianças (só adultos no Edu/Hub).
11. Acessibilidade não-negociável (áudio, botões ≥48px, reduced-motion, daltônico).
12. LGPD Art. 14 — coleta mínima; social opt-in por escola; retenção configurável (padrão 24 meses).
13. Economia auditável; regras numéricas não hardcoded.
14. Amizades restritas à mesma escola.
15. Integração Matific/Elefante por PDF/XLSX (sem API self-serve).
16. Identidade visual do protótipo `constela-play-v7`.

## 5. Riscos e inconsistências (top)

- **Docs muito à frente do código:** só Q0 existe; routers/services de jogo prometidos no doc 01 estão ausentes. Risco de ler a doc como estado real.
- **Conteúdo é o gargalo:** `conteudo/` vazia, nenhuma missão BNCC semeada, sem CRUD de admin. Sem conteúdo não há jogo.
- **Contradição do avatar** (registrada nos próprios docs): Revisão 3 diz "Cosmo astronauta, em aberto"; Revisão 4 (mesma data) decide "humanoide 3D"; o código foi para 3D real. Dois sistemas coexistem.
- **Desvio arquitetural:** o doc 01 fixa "DOM/SVG/CSS primeiro; canvas só arcade futuro; PixiJS, não Three.js" — mas o frontend adotou Three.js no núcleo, sem atualizar o doc.
- **Resíduo do PIN antigo** nos docs 01/04 vs. decisão vigente de código-só.
- **Contrato de avatar desatualizado** em `quest-core` (`trocarAvatar` tipa slots do Cosmo legado; resíduos `coresDoTraje`, `AstronautaConhecido`).
- **Catálogo cosmético duplicado** (hardcoded no cliente vs. exposto pelo servidor e não consumido).
- **Assimetrias:** catálogos públicos sem token; `PATCH /preferencias` e login-QR falho sem auditoria; rate-limit em memória (não distribuído).
- **Rede em fluxo crítico sem retry:** cerimônia depende de `personagensBase()` com catch silencioso que zera a lista.

## 6. Decisões em aberto (só o dono decide)

- **Avatar definitivo:** humanoide 3D (Three.js) **ou** Cosmo 2D como avatar?
- **Three.js oficial no núcleo?** Se sim, reescrever o doc 01 (DOM/SVG-first).
- **Pipeline de arte/assets 3D:** quem produz os GLB e as camadas trocáveis? Áudios/ilustrações gravados?
- **Login:** confirmar código-só e autorizar limpeza dos resíduos de PIN.
- **Escopo de conteúdo:** 1 planeta profundo (Matemática) vs. 9 rasos.
- **Catálogo pedagógico:** por qual interface é cadastrado/publicado? Conexão com o "software de matérias+questões" futuro.
- **Amizades no lançamento:** "mesma turma" vs. "mesma escola"; social ligado/desligado por padrão.
- **Retenção:** confirmar 24 meses + gatilho de anonimização na saída.
- **Monetização:** confirmar passe 100% gratuito e zero compras in-app em toda fase.
- **Plataformas-alvo:** apps nativos/PWA instalável além da web? Em que fase?
- **Ed. Física e ERER:** confirmar entrada só na Q5 com curadoria própria.
- **Portal da família / `ResponsavelAluno`:** quando entra a API e quem autoriza o vínculo?
- **Preferências `musica` e `reduzir_animacoes`:** ganham função/UI ou saem do modelo?
