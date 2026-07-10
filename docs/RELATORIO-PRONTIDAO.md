# Relatório de Prontidão — Constela Edu

Conclusão do roadmap priorizado de robustez/produção. Todos os commits são
**locais** (sem push/deploy), na ordem abaixo.

| Etapa | Commit | Tema |
|---|---|---|
| Observabilidade | `db812ad` | logs JSON, request/correlation id, métricas, Sentry, health |
| Testes de UI | `3c0a06d` | Vitest + Testing Library (telas prioritárias) |
| Testes de borda | `0ee26f6` | RBAC negativo, validação, respostas incompletas |
| E2E | `a4037fc` | Playwright + CI (login/cadastro/CRUD/ranking/importação/permissões) |
| Performance | `c2be320` | lazy loading, cache, memoização, janelamento, N+1, batch, índice |
| Mobile offline | `aa3dd41` | cache cifrado, boot offline, fila offline, reconexão, retry |
| CI/CD | `1e0c394` | lint, cobertura, pip-audit/npm audit/Trivy, Dependabot, deploy, branch protection |

## 1. O que foi implementado

- **Observabilidade**: middleware ASGI puro com log de acesso estruturado
  (request_id, correlation_id, usuario_id, escola_id, rota, dur_ms), métricas
  Prometheus em `/metrics`, Sentry opcional (LGPD: `send_default_pii=False`) e
  health checks (`/api/health`, `/live`, `/ready`). Corrigiu o Alembic que
  desativava os loggers em dev.
- **Testes**: 58 testes Vitest (12 telas + bordas), 15 E2E Playwright contra o
  sistema real, somados aos 310 de backend — total **383 testes**.
- **Performance**: code-splitting por rota (bundle inicial 132KB → ~74KB gz +
  vendor cacheável), cache do `useApi`, isolamento de modal (memoização),
  janelamento de listas, correção de N+1 (`selectinload`), batch na importação
  e índice composto em `notas`.
- **Mobile (Expo)**: cache do React Query cifrado em repouso (AES-256, chave no
  SecureStore), boot offline que não desloga sem rede, fila de escritas offline
  com reenvio na reconexão, retry com backoff (sem 4xx), Error Boundary e banner
  de conexão.
- **CI/CD**: pipeline com lint (ruff+tsc), testes com cobertura, build, E2E,
  imagens Docker; varredura de segurança (pip-audit, npm audit, Trivy) com cron
  semanal; Dependabot; deploy staging/produção com aprovação manual; ruleset de
  branch protection. Correções de dependência reais: `pypdf` (10 CVEs) e
  `python-multipart` (6 CVEs).

## 2. Arquivos alterados (por área)

- **Backend**: `app/core/observabilidade.py` (novo), `main.py`, `config.py`,
  `alembic/env.py` + migração `0004`, `models/nota.py`, `services/insights.py`,
  `routers/importacoes.py`, `services/matriculas.py`, `ruff.toml`,
  `requirements.txt`, `scripts/seed_e2e.py`, `tests/` (novos).
- **Web** (`apps/web`): `App.tsx`, `components/Layout.tsx`, `vite.config.ts`,
  `hooks/useApi.ts`+`useMutation.ts`+`useJanela.ts`, `pages/*` (rankings,
  Matific, Turmas…), `src/test/` (harness + 13 specs), `src/lib/__mocks__/`,
  `playwright.config.ts`, `e2e/` (7 specs).
- **Mobile** (`apps/mobile`): `App.tsx`, `contexto/Autenticacao.tsx`,
  `notificacoes.ts`, `armazenamento/` (cifra + storage + sessão), `filaOffline.ts`,
  `cliente-query.ts`, `rede.ts`, `componentes/BannerConexao.tsx`+`LimiteErro.tsx`.
- **Infra**: `.github/workflows/ci.yml`+`security.yml`+`deploy.yml`,
  `.github/dependabot.yml`, `.github/rulesets/protecao-main.json`, `docs/CI-CD.md`.

## 3. Decisões de arquitetura

- **Observabilidade em ASGI puro** (não BaseHTTPMiddleware): o contexto propaga
  via `contextvars` até endpoints síncronos no threadpool. Métricas usam a rota
  como TEMPLATE (baixa cardinalidade). Tudo degrada para no-op sem lib/DSN.
- **Fronteira única de teste no web**: todo consumo de API passa por `../lib/api`;
  mockar só esse ponto exercita telas + hooks + contexto reais (só o HTTP é falso).
  E2E complementa contra o backend real com seed determinístico + storageState.
- **Cache no cliente com invalidação explícita** em vez de tempos longos: 60s
  cosméticos nos dropdowns + `limparCacheApi` no ponto de mutação.
- **Mobile offline com criptografia por chave no SecureStore**: dado grande
  (cache) fica cifrado no AsyncStorage; só a chave (pequena) vai ao keystore do
  SO. Boot restaura a sessão salva e só desloga em 401 — nunca por falta de rede.
- **Segurança no CI com política em camadas**: bloqueia o determinístico
  (lint/test/build/e2e) e o urgente (crítico/corrigível); o restante
  framework-pinned fica visível e é conduzido pelo Dependabot — evita um
  pipeline nascer permanentemente vermelho.

## 4. Riscos remanescentes

- **CVEs framework-pinned** (aceitos e documentados): starlette (fixado pelo
  FastAPI), `ecdsa`/`pyasn1` (transitivos; usamos JWT HS256), e a árvore do Expo
  (mobile) com highs — todos dependem de upgrade de framework/SDK conduzido pelo
  Dependabot.
- **Mobile não executado em runtime**: sem emulador no ambiente; verificado por
  typecheck + teste isolado da criptografia. Falta um smoke test em aparelho.
- **Trivy e deploys** só rodam no GitHub/servidores (não validados localmente);
  configurados de forma conservadora para não falharem à toa.
- **Cobertura desigual no web** (~28% global): as telas fora do escopo (ex.:
  PerfilAluno, TurmaDetalhe, painéis públicos) têm pouca cobertura de unidade.

## 5. Testes executados (verificação final desta conclusão)

| Suíte | Resultado |
|---|---|
| Backend `pytest` | **310 passed** · cobertura **91%** |
| Web `vitest` | **58 passed** |
| E2E `playwright` | **15 passed** |
| `ruff check` (backend) | limpo |
| `tsc` (mobile) + `vite build` (web) | verdes |
| `pip-audit` (com allowlist) · `npm audit --audit-level=critical` | verdes |

## 6. Impacto na prontidão do sistema

- **Operabilidade**: dá para monitorar, achar erros por `request_id`, medir
  latência e identificar gargalos (observabilidade + health checks).
- **Confiabilidade**: 383 testes automatizados travam regressões; o CI barra
  merges vermelhos (com branch protection ativa).
- **Segurança**: parsers de upload/formulário atualizados; varredura contínua +
  Dependabot; segredos e dados de crianças protegidos (LGPD).
- **Desempenho**: carga inicial do web ~45% menor; menos idas ao banco em
  importações e rankings.
- **Resiliência mobile**: uso offline real, sem logout indevido e sem dado
  sensível em texto plano no aparelho.

## 7. Pendências deixadas propositalmente para fases futuras

- **Follow-ups da auditoria de performance**: N+1 de `db.get(Aluno)` na
  importação; 8 SELECTs de config no recálculo; N+1 em `acessos_da_turma`
  (Quest); janelamento nos demais rankings; subsets de fonte no PWA.
- **Upgrades de framework** (via Dependabot): FastAPI/starlette e Expo SDK, para
  zerar os CVEs hoje na allowlist.
- **Ampliar cobertura de unidade no web** para as telas fora do escopo atual.
- **Ativar (fora do código)**: branch protection (importar o ruleset) e o CD
  (Environments + segredos Railway/Vercel) — passo a passo em `docs/CI-CD.md`.
- **Smoke test do mobile em aparelho/emulador** (Expo Go).
