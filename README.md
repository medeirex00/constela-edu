# Constela Edu — Gestão e Premiação Escolar

Plataforma multi-escolas para acompanhar o desempenho de alunos nas plataformas
Matific e Elefante Letrado, calcular notas justas e configuráveis, gerar rankings
e apoiar premiações — conforme o PRD oficial do projeto.

> Codinome técnico interno: **SGPE** — nomes de tabelas, chaves locais e
> comentários antigos podem usar a sigla; a marca do produto é Constela Edu.

**Estado atual: 6 fases do roteiro concluídas + arquitetura multiplataforma
(Web, Desktop e Mobile).** Veja `docs/ROADMAP.md` para o histórico e
`docs/ARQUITETURA.md` para as decisões técnicas e diagramas.

## Plataformas

| Plataforma | Onde vive | Tecnologia |
|------------|-----------|-----------|
| 🌐 Web | `apps/web` | React 18 + TypeScript + Tailwind (Vite) |
| 💻 Desktop (Windows/macOS/Linux) | `apps/desktop` | Tauri 2 embrulhando o build do web — instalador pequeno, atualização automática, atalhos de teclado |
| 📱 Mobile (Android/iOS) | `apps/mobile` | Expo / React Native — offline-first, push, scanner de QR |
| ⚙️ Backend (único, para todos) | `backend` | Python 3.11+ + FastAPI + SQLAlchemy 2 |
| 📦 Código compartilhado | `packages/core` | `@constela/core`: cliente da API, tipos, autenticação e formatação |

Banco: SQLite (desenvolvimento) → PostgreSQL (produção, via Docker) — mesma base de código.

## Como rodar (desenvolvimento)

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Cria a escola JORGE PASSOS, o usuário admin e as configurações padrão.
# --demo adiciona turmas, alunos e notas de exemplo para explorar o sistema.
python scripts/seed.py --demo

uvicorn app.main:app --reload --port 8000
```

A documentação interativa da API fica em `http://localhost:8000/docs`.

### 2. Instalar os workspaces (uma vez, na raiz)

```bash
npm install --legacy-peer-deps
```

### 3. Web

```bash
npm run dev:web        # http://localhost:5173  (proxy /api → backend :8000)
```

Login inicial: `admin@sgpe.local` / `admin123` (troque em produção).

### 4. Desktop (requer Rust: https://rustup.rs)

```bash
npm run dev:desktop    # abre a janela nativa apontando para o dev server
npm run build:desktop  # gera instaladores (msi/nsis, dmg, appimage/deb)
```

Atalhos: `Ctrl+K` pesquisa global, `Alt+1..0` navegação. A atualização
automática usa o updater do Tauri — gere as chaves com
`npm run tauri -w @constela/desktop signer generate` e preencha
`apps/desktop/src-tauri/tauri.conf.json`.

### 5. Mobile

```bash
# Aponte para a API: emulador Android usa 10.0.2.2; aparelho físico, o IP da máquina
EXPO_PUBLIC_API_URL=http://10.0.2.2:8000/api/v1 npm run dev:mobile
```

Abra com o app Expo Go (ou `npx expo run:android`). Builds de loja:
`eas build -p android` / `eas build -p ios` (configure o `projectId` do EAS
em `apps/mobile/app.json`).

O app funciona offline com o último estado sincronizado e se atualiza
sozinho ao reconectar. Push chega via Expo (ex.: quando uma importação é
concluída).

## Produção com Docker (PostgreSQL + API + Web)

```bash
cp .env.example .env   # defina POSTGRES_PASSWORD e SECRET_KEY
docker compose up -d
# Web em http://localhost:8080 — API na mesma origem em /api/v1
# Primeira vez: docker compose exec backend python scripts/seed.py
```

Desktop e mobile apontam para essa mesma URL (`VITE_API_URL` /
`EXPO_PUBLIC_API_URL`).

## Testes

```bash
cd backend && python -m pytest tests/ -v       # 71 testes (motor, fases 2–6, mobile)
npm run build:web                              # typecheck + build do web
npm run typecheck:mobile                       # typecheck do app mobile
```

CI (GitHub Actions): testes do backend, build do web, typechecks e imagens
Docker em todo push; instaladores do desktop em tags `v*`
(`.github/workflows/`).

## O que está funcionando

- **Multi-escolas de verdade** com papéis validados no backend (PRD §10, §13, §20).
- **Motor de cálculo completo e auditável** (PRD Parte 3) com "Como esta
  nota foi calculada" no perfil do aluno.
- **Importações** (PDF/texto) com prévia, correspondência de nomes e
  histórico; módulos Matific/Elefante; Catálogo de Livros.
- **Evolução**: linha do tempo, ranking de evolução, comparadores, páginas
  de turma e escola.
- **Gamificação** (conquistas/XP/sequência/destaques), **relatórios**
  (PDF/Excel/CSV + certificados), usuários, backup/restauração, pesquisa
  global, notificações, simulador.
- **Painel Público** sem login com modo TV e QR code.
- **Inteligência Pedagógica** (índices e alertas) e **Assistente de IA**
  com provedor trocável (`local` por padrão — sem chave; `anthropic`/
  `openai` via `.env`).
- **Mobile**: login, dashboard, rankings, perfil do aluno, scanner de QR,
  push e offline-first. **Desktop**: tudo do web + instalador, atualização
  automática e atalhos.

## Estrutura

```
backend/    API FastAPI (única fonte de regra de negócio, 71 testes)
apps/       web (React) · desktop (Tauri) · mobile (Expo/RN)
packages/   core — TypeScript compartilhado entre os três clientes
database/   SQLite de desenvolvimento (gerado; fora do versionamento)
uploads/    arquivos importados · exports/  relatórios gerados
docs/       ARQUITETURA.md (diagramas) e ROADMAP.md
tools/      utilitários (gerador de ícones do desktop)
```
