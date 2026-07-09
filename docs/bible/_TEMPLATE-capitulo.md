# NN — [Título do Capítulo / Chapter Title]

<!--
  TEMPLATE OFICIAL DE CAPÍTULO da Constela Quest Bible (obrigatório — ADR-0002).
  Todo capítulo segue EXATAMENTE estas 16 partes, na ordem. Se uma parte não se
  aplica (ex.: "Interface" num capítulo de fundação), escreva "N/A — <motivo>",
  nunca omita o título.

  Regras de qualidade (valem para todo capítulo):
  • Documente a INTENÇÃO, não só a funcionalidade. Sempre responda:
    por que existe · que problema resolve · que sentimento deve causar ·
    como conversa com o resto do ecossistema Constela (Hub/Edu/Quest).
  • Escreva para quem vai LER daqui a 5 anos: dev, designer, artista 3D,
    animador, game designer, QA, Product Owner, futuro membro da equipe.
    Suficiente para implementar SEM adivinhar a intenção do dono.
  • Impacto em outro módulo? NÃO improvise: crie um ADR (Parte 16) ou marque
    como decisão pendente (Parte 15 + ⚠️).
  • Bilíngue: pt-BR canônico + espelho EN no mesmo arquivo.
-->

- **Status:** 🔴 rascunho / draft
- **Fontes / Sources:**
- **Depende de / Depends on:**
- **Dá origem a (ADR/spec) / Spawns:**

---

## 🇧🇷 [Título]

### 1. Objetivo
*O que este capítulo entrega e por que existe. O problema que resolve.*

### 2. Contexto
*Onde isto se encaixa no Constela Quest e no ecossistema (Hub → Edu → Quest); estado atual (o que já existe em código vs. planejado).*

### 3. Filosofia da funcionalidade
*A intenção de design. A crença por trás. Como se conecta aos 4 pilares (autonomia, progresso visível, vínculo, surpresa) e aos Princípios Imutáveis (Seção 01).*

### 4. Experiência que o jogador deve sentir
*O sentimento-alvo na criança (e nos adultos, quando aplicável). O "momento mágico". Tom emocional.*

### 5. Fluxo completo
*Passo a passo do início ao fim, incluindo primeira vez, retorno, caminhos de erro e offline.*

### 6. Interface (quando existir)
*Telas, componentes, hierarquia e estados. Remete à Seção 07 (UX/Fluxos) para o inventário canônico de telas. "N/A" se o capítulo não tem UI própria.*

### 7. UX
*Como a experiência se sente: acessibilidade (Seção 13), áudio pt-BR, ritmo, feedback, prevenção de erro, vocabulário canônico (Seção 02).*

### 8. Game Design
*Mecânicas, economia, progressão, dificuldade, recompensa, balanceamento. "N/A" quando não houver dimensão de jogo.*

### 9. Regras de negócio
*Regras determinísticas, fórmulas, limites, validações; o que o servidor decide vs. o cliente; papéis e permissões.*

### 10. Arquitetura técnica
*Componentes, dados, contratos cliente↔servidor, endpoints, modelo de dados, autoridade do gabarito, isolamento multi-escola. Remete ao Apêndice B.*

### 11. Dependências com outros módulos
*Quais seções/módulos este capítulo consome e alimenta; contratos entre eles; o que quebra se um mudar.*

### 12. Casos extremos (Edge Cases)
*Vazio, erro, offline, sem permissão, primeira vez, concorrência, dados inválidos, hardware fraco, turma multisseriada, aluno fora de faixa, etc.*

### 13. Escalabilidade futura
*Como isto cresce (mais conteúdo, mais escolas, mais plataformas) sem reescrita; ganchos previstos; dívida consciente.*

### 14. Checklist de implementação
*Lista acionável de "pronto quando" (Definition of Done) para o dev/QA; liga ao Apêndice F.*

### 15. Questões em aberto
*Decisões que só o dono toma; cada uma vira ⚠️ e, se impacta outro módulo, um ADR (Parte 16).*

### 16. ADR (Architecture Decision Record)
*ADRs originados por este capítulo (link para `decisoes/ADR-XXXX`). Decisões cross-módulo NUNCA são improvisadas aqui — viram ADR ou pendência.*

---

## 🇬🇧 [Title]

### 1. Objective
### 2. Context
### 3. Feature philosophy
### 4. The experience the player should feel
### 5. Complete flow
### 6. Interface (when it exists)
### 7. UX
### 8. Game Design
### 9. Business rules
### 10. Technical architecture
### 11. Dependencies on other modules
### 12. Edge cases
### 13. Future scalability
### 14. Implementation checklist
### 15. Open questions
### 16. ADR (Architecture Decision Record)

<!-- Preencher o espelho EN após o pt-BR estar estável. -->
