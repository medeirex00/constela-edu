# Roteiro de Implementação

O PRD descreve um produto de vários meses. Este roteiro divide as 172 seções
em fases incrementais: cada fase entrega valor usável e nenhuma exige
reescrever o que veio antes (PRD §26). O banco e a arquitetura da Fase 1 já
comportam todas as fases seguintes.

## ✅ Fase 1 — Fundação (entregue)

PRD coberto: §1–§14, §17 (parcial), §18 (parcial), §19–§20, §23–§25,
§27–§46 (motor completo), §47–§49, §53–§54, §58–§63.

- Monorepo `/frontend /backend /database /uploads /exports /docs /scripts`
- Banco multi-escolas normalizado, histórico por matrícula/ano letivo
- Autenticação JWT + papéis validados no backend
- Motor de cálculo: normalização, pesos configuráveis (soma = 100% obrigatória),
  dificuldade por série, questões (tentativas/acertos), desempate configurável,
  recálculo automático, detalhamento auditável por aluno
- Telas: Login, Dashboard (cartão ESCOLA), Alunos, Perfil ("Como esta nota foi
  calculada"), Ranking Geral com filtros, Turmas, Professores, Métricas
  (4 módulos do §58), Configurações
- Seed da escola JORGE PASSOS + dados de demonstração + 7 testes do motor

## Fase 2 — Importações e módulos das plataformas

PRD: §15–§16, §35 (validação na importação), §50–§52, §55–§57.

- Upload de PDF e colagem de texto, detecção automática da plataforma
- Prévia com erros antes de confirmar (§51) e correspondência inteligente de
  nomes com confirmação de duplicatas prováveis (§52)
- Telas Matific e Elefante Letrado, edição manual auditada
- Catálogo de Livros com busca e filtros
- Registro completo em `importacoes` + arquivos guardados em `/uploads`

**Pré-requisito bloqueante:** amostras reais dos relatórios exportados da
Matific e do Elefante Letrado (PDF e/ou texto copiado, pode ser com nomes
fictícios). Sem elas, qualquer parser seria chute.

## Fase 3 — Evolução e histórico

PRD: §67–§78, §67–§71 já têm base pronta (snapshots imutáveis).

- Linha do tempo por aluno, gráficos por período, evolução percentual
- Ranking de Evolução independente, páginas de turma e de escola
- Comparador aluno×aluno, aluno×turma, turma×turma

## Fase 4 — Gamificação, relatórios e administração

PRD: §64, §72–§75, §79–§84 (parcial), §86–§103, §18 (usuários/backup/aparência),
§21–§22 (pesquisa global e notificações), §44 (simulador de pontuação).

- Conquistas, medalhas, XP/níveis, sequência, Aluno do Dia/Semana/Mês, mural
- Exportação PDF/Excel/CSV com identidade visual, certificados
- CRUD de usuários, backup/restauração, personalização de aparência

## Fase 5 — Painel Público

PRD: §104–§128.

- URL pública sem login, modo TV, carrossel de slides configurável,
  QR codes, perfil público restrito a dados pedagógicos

## Fase 6 — Inteligência Pedagógica e Assistente de IA

PRD: §129–§172.

- Insights e alertas automáticos, índices de engajamento/evolução/persistência
- Camada `AI Service` isolada (§154) — o frontend nunca fala direto com o
  modelo; provedor trocável (Anthropic, OpenAI, local etc.)
- Assistente Pedagógico em chat, respostas somente sobre dados do banco,
  com registro de conversas e respeito total às permissões (§169)

## Transversal (toda fase)

Logs de auditoria em toda escrita, mensagens de progresso claras (§47, §65),
paginação e consultas enxutas (§23), validação de entrada (§24).
