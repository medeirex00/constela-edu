# Constela Quest

Este escopo cobre `apps/quest`, a PWA dos alunos do 1º ao 5º ano. Usa React 18, TypeScript e Vite. O mesmo backend FastAPI do Edu atende o Quest em `/api/v1/quest`, com implementação em `backend/app/quest/`. Os contratos e as chamadas compartilhadas com o Edu ficam em `packages/quest-core/`.

## Estrutura

- `src/app/` compõe o fluxo do app. `src/estado/sessao.tsx` mantém a sessão. `src/entrada/` e `src/cerimonia/` cuidam da entrada e das boas-vindas.
- `src/lobby/`, `src/jogo/`, `src/vestiario/` e `src/carreira/` abrigam as experiências do aluno.
- `src/design/`, `src/audio/`, `src/cosmo/` e `src/personagem/` concentram UI, áudio, mascote e astronauta.
- `src/test/` contém os testes de UI com Vitest e Testing Library. `public/` guarda o manifesto e os assets estáticos da PWA.

## Comandos

Execute a partir da raiz do repositório.

| Finalidade | Comando |
| --- | --- |
| Desenvolvimento | `npm run dev:quest` |
| Build e validação estática TypeScript | `npm run build:quest` |
| Testes de UI | `npm run test --workspace @constela/quest` |
| Testes de UI em modo observação | `npm run test:watch --workspace @constela/quest` |
| Validação dos contratos compartilhados | `npm run typecheck --workspace @constela/quest-core` |

O Vite usa a porta 5174 e encaminha `/api` à API local na porta 8000. O build faz `tsc` seguido de `vite build`. Para mudanças em regras ou rotas, valide também os testes de Quest no backend com `python -m pytest tests/ -q -k quest` dentro de `backend/`.

## Convenções

- Use os termos Planeta, Jornada, Missão, Desafio, Constelação e Meu astronauta conforme o vocabulário infantil de `docs/quest/README.md`. Preserve os nomes internos nos contratos. Use instruções curtas, interações adequadas ao toque e áudio para os alunos em alfabetização.
- Preserve o token do aluno apenas em memória e limpe o estado na troca de sessão. Mantenha a confirmação de identidade após a entrada pelo QR e remova a credencial da URL. Restrinja o cache da PWA aos arquivos estáticos.
- Centralize contratos em `@constela/quest-core` e a autorização, tentativas e recompensas no backend. Mantenha o gabarito fora dos dados enviados ao cliente.
- Minimize os dados infantis. Preserve o escopo escolar, o controle dos recursos sociais pela escola e o uso de mensagens pré-aprovadas. Mantenha a economia virtual sem compras com dinheiro real.

Veja [documentação do Quest](../../docs/quest/README.md), [integração com Edu e família](../../docs/quest/04-integracao-edu.md) e [convenções do backend](../../backend/AGENTS.md).
