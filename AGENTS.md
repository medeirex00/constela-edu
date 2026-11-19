# AGENTS.md — Ecossistema Constela

## Produtos e estrutura

- **Constela Edu** é a plataforma multi-escolas para professores e gestão. Reúne acompanhamento de Matific e Elefante Letrado, notas, rankings e relatórios. SGPE é o codinome legado e ainda aparece em identificadores e migrações. Use Constela Edu na interface.
- `apps/web/` é o Edu web (React, TypeScript, Vite e Tailwind). `apps/desktop/` empacota o mesmo frontend com Tauri. `apps/mobile/` é o cliente Expo/React Native, com fila offline, scanner e notificações. [Guia do web](apps/web/AGENTS.md).
- `backend/` é a API compartilhada (FastAPI, SQLAlchemy e Alembic). O Edu mantém dados e regras de gestão. `backend/app/quest/` é o módulo do Quest para alunos. O banco de desenvolvimento é SQLite e produção usa PostgreSQL. [Guia do backend](backend/AGENTS.md).
- **Constela Quest** é a PWA de aprendizagem para alunos do 1º ao 5º ano. A interface está em `apps/quest/`. Siga o vocabulário pedagógico registrado em [docs/quest/README.md](docs/quest/README.md). [Guia do Quest](apps/quest/AGENTS.md).
- `packages/core/` (`@constela/core`) contém o cliente HTTP, tipos e formatação compartilhados. `packages/quest-core/` (`@constela/quest-core`) contém o contrato e o cliente do Quest. Ambos são consumidos como fonte TypeScript no workspace.
- **Constela Hub** aparece em [docs/quest/README.md](docs/quest/README.md) como portal de entrada para Edu e Quest. O checkout atual contém essa referência de arquitetura. Localize o código-fonte e o manifesto de deploy do Hub antes de alterar o portal.
- `docs/` guarda arquitetura, guias operacionais, decisões pedagógicas e histórico. Consulte [HANDOFF.md](HANDOFF.md) para o estado deste checkout. `database/`, `uploads/` e `exports/` incluem dados e artefatos locais.

## Desenvolvimento e verificações

Execute os comandos npm na raiz. A CI usa Node 22 e Python 3.13. Instale os workspaces com `npm ci --legacy-peer-deps` quando precisar preparar um ambiente a partir do lockfile.

| Área | Desenvolvimento e build | Testes e lint |
| --- | --- | --- |
| Edu web | `npm run dev:web` (Vite em 5173 por padrão). `npm run build:web` (TypeScript + Vite) | `npm run test -w @constela/web`, `npm run test:cov -w @constela/web`, `npm run e2e -w @constela/web` |
| Quest | `npm run dev:quest` (Vite em 5174). `npm run build:quest` (TypeScript + Vite) | `npm run test -w @constela/quest` |
| API | Em `backend/`, `python -m uvicorn app.main:app --reload --port 8000`. Da raiz, `docker build -t sgpe-backend ./backend` | Em `backend/`, `python -m pytest -q`. Da raiz, `ruff check backend` |
| Mobile | `npm run dev:mobile`. Os perfis EAS vivem em `apps/mobile/eas.json` | `npm run typecheck:mobile`, `npm run test -w @constela/mobile` |
| Desktop | `npm run dev:desktop`, `npm run build:desktop` (requer Rust e toolchain Tauri) | Valide a interface com os testes do web e o empacotamento com o build Tauri |
| Pacotes TS | Fontes compiladas pelos consumidores | `npm run typecheck -w @constela/core`, `npm run test -w @constela/core`, `npm run typecheck -w @constela/quest-core` |

- Para preparar a API no Windows, execute `python -m venv .venv` em `backend/` e instale as dependências com `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`. Use o Python dessa venv nos comandos da API. O setup em [README.md](README.md) descreve a carga inicial para banco de desenvolvimento.
- Os dois frontends encaminham `/api` para a API local na porta 8000. Os atalhos de `.claude/launch.json` usavam 5175 para o web em desenvolvimento e 4173 para a prévia do build. Os equivalentes na raiz são `npm run dev -w @constela/web -- --port 5175 --strictPort` e, após `npm run build:web`, `npm run preview -w @constela/web -- --port 4173 --strictPort`.
- Consulte [.github/workflows/ci.yml](.github/workflows/ci.yml) para a sequência completa de lint, typecheck, cobertura, migrações PostgreSQL, E2E e build. O build do web e do Quest inclui typecheck. Para alterações no contrato, valide a API, o pacote TS e os clientes afetados.
- Trabalhe no checkout e na branch selecionados. Confira `git status --short --branch` antes de alterar arquivos e preserve o trabalho local em andamento. Alterações no remoto ou no deploy dependem do escopo da tarefa.

## Convenções compartilhadas

- Preserve a separação entre apresentação e regras de negócio. O backend valida papéis e escopo por escola. Mantenha os tipos dos clientes sincronizados com os schemas da API e preserve os formatos consumidos pelos apps.
- Siga os nomes e a organização dos módulos existentes. Use pt-BR nos textos do produto e respeite o vocabulário lúdico do Quest. Mantenha a compatibilidade com dados legados e com SQLite e PostgreSQL ao alterar modelos e migrações.
- Use dados sintéticos nos testes e demos. Mantenha segredos em variáveis de ambiente e dados escolares, arquivos importados, capturas e relatórios fora de exemplos, logs e alterações versionadas. Consulte os `.env.example` para os nomes de variáveis.
- Para operação, comece por [docs/DEPLOY.md](docs/DEPLOY.md), [docs/CI-CD.md](docs/CI-CD.md), [docs/STAGING.md](docs/STAGING.md) e [docs/DR-RUNBOOK.md](docs/DR-RUNBOOK.md). O handoff indica quais registros locais dão contexto ao deploy atual.

## Origem das instruções

O inventário do checkout e dos dois worktrees em `.claude/worktrees/` encontrou `launch.json` e `settings.local.json`. Este guia e os guias dos apps foram reconstruídos a partir do código, dos manifests, da CI e da documentação local. As permissões de shell de `settings.local.json` eram aprovações locais do Claude. As referências a `claude-api` e `artifact-design` são entradas dessa lista. Os corpos das skills e os diretórios de skills, comandos e agentes do projeto estavam ausentes. Também estavam ausentes `CLAUDE.md` e definições de servidores MCP do projeto. Os destinos para essas migrações são `.agents/skills/<nome>/SKILL.md` e `.codex/config.toml` com tabelas `[mcp_servers.<nome>]`.
