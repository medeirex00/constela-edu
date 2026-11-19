# Constela Edu Web

Este escopo cobre `apps/web`, a SPA administrativa do Constela Edu. Usa React 18, TypeScript, Vite, React Router e Tailwind. O desktop Tauri reutiliza seu build.

## Estrutura

- `src/App.tsx` registra as rotas. `src/components/Layout.tsx` organiza a navegação e o layout.
- `src/pages/` contém as telas. `src/components/` reúne a UI compartilhada, incluindo `ui.tsx`.
- `src/context/` mantém sessão, escopo e estado compartilhado. `src/hooks/` contém utilitários de consulta e mutação, como `useApi` e `useMutation`.
- `src/lib/api.ts` adapta `@constela/core` para web e desktop. `@constela/quest-core` fornece contratos e chamadas do Quest usados nas telas do professor.
- `src/test/` contém os testes de UI com Vitest e Testing Library. `e2e/` contém os cenários Playwright. `public/` guarda o manifesto PWA e os assets estáticos.

## Comandos

Execute a partir da raiz do repositório.

| Finalidade | Comando |
| --- | --- |
| Desenvolvimento | `npm run dev:web` |
| Build e validação estática TypeScript | `npm run build:web` |
| Testes de UI | `npm run test --workspace @constela/web` |
| Cobertura de UI, com pisos do CI | `npm run test:cov --workspace @constela/web` |
| Testes de ponta a ponta | `npm run e2e --workspace @constela/web` |

O Vite usa a porta 5173 por padrão e encaminha `/api` para a API local na porta 8000. O build faz `tsc` seguido de `vite build`. A instalação do Chromium para os testes E2E é `npx playwright install chromium` em `apps/web`. A suíte E2E usa Vite, FastAPI e SQLite de teste semeado por `backend/scripts/seed_e2e.py`. Mantenha os serviços e o banco de teste isolados de qualquer ambiente com dados reais.

## Convenções

- Reutilize componentes, tokens visuais e estados de carregamento, erro e vazio. Escreva rótulos e mensagens em português brasileiro.
- Reutilize os hooks e o cliente HTTP existentes. Quando o contrato mudar, mantenha os schemas Pydantic e os tipos compartilhados em sincronia.
- Preserve os guardas de rota, de perfil e de módulo. O backend é a autoridade para permissões, escopo de rede/escola/turma, pontuação e rankings.
- Use a base relativa `/api/v1` por padrão no desenvolvimento e em deploy de mesma origem. Configure `VITE_API_URL` com a URL absoluta terminada em `/api/v1` no desktop e no deploy web em que a Vercel acessa a API no Railway.
- Restrinja o cache da PWA aos arquivos estáticos do aplicativo. Preserve as exclusões de `/api` e `/p/` no fallback do service worker e mantenha as respostas autenticadas fora do cache.

Veja [Arquitetura](../../docs/ARQUITETURA.md), [CI/CD](../../docs/CI-CD.md) e [Publicação](../../docs/PUBLICAR.md).
