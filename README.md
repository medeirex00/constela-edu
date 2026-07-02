# SGPE — Sistema de Gestão e Premiação Escolar

Plataforma multi-escolas para acompanhar o desempenho de alunos nas plataformas
Matific e Elefante Letrado, calcular notas justas e configuráveis, gerar rankings
e apoiar premiações — conforme o PRD oficial do projeto.

**Estado atual: Fase 3 (evolução e histórico) concluída.**
Veja `docs/ROADMAP.md` para o mapa completo das fases e `docs/ARQUITETURA.md`
para as decisões técnicas.

## Stack

| Camada   | Tecnologia |
|----------|-----------|
| Frontend | React 18 + TypeScript + Tailwind CSS + React Router (Vite) |
| Backend  | Python 3.11+ + FastAPI + SQLAlchemy 2.0 |
| Banco    | SQLite (dev) → PostgreSQL (produção, mesma base de código) |

## Como rodar

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

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Abra `http://localhost:5173` e entre com:

```
E-mail: admin@sgpe.local
Senha:  admin123          ← troque em produção
```

O Vite já faz proxy de `/api` para o backend na porta 8000.

### 3. Testes do motor de cálculo

```bash
cd backend
python -m pytest tests/ -v
```

## O que está funcionando na Fase 1

- **Multi-escolas de verdade**: toda tabela pertence a uma escola; o seletor
  ESCOLA troca todos os dados do sistema (PRD §10, §20).
- **Autenticação + papéis** (admin, coordenador, professor, visitante), com
  toda permissão validada no backend (PRD §13).
- **Motor de cálculo completo e auditável** (PRD Parte 3): normalização 0–100,
  pesos 100% configuráveis, dificuldade por série, sub-nota de questões,
  critérios de desempate e recálculo automático a cada alteração.
- **Perfil do aluno com "Como esta nota foi calculada"** — cada indicador com
  valor, referência, normalização, peso e contribuição (PRD §45).
- **Métricas** com exatamente os 4 módulos do PRD §58: Matific, Elefante
  Letrado, Dificuldade por Turma e Referências de Normalização.
- **Dashboard, Ranking Geral com filtros, Alunos com busca paginada,
  Turmas e Professores.**
- **Modo claro/escuro**, layout responsivo e correção definitiva do problema
  de toque no iPhone (elementos semânticos + `touch-action: manipulation`).
- **Logs de auditoria** de login, alterações de pesos, referências,
  dificuldade e cadastros (PRD §17).

## O que ainda não existe (por decisão de fase, não por esquecimento)

Importações de PDF/texto, módulos Matific/Elefante dedicados, catálogo de
livros, evolução/histórico visual, gamificação, painel público, relatórios e
assistente de IA. Cada um tem fase e pré-requisitos definidos em
`docs/ROADMAP.md`. **A Fase 2 (importações) precisa de relatórios reais
exportados das duas plataformas para construir os parsers.**

## Estrutura

```
backend/    API FastAPI (app/core, app/models, app/routers, app/services)
frontend/   SPA React + TS + Tailwind
database/   arquivo SQLite (gerado; fora do versionamento)
uploads/    arquivos importados (matific/, elefante/, temporarios/)
exports/    relatórios gerados
docs/       ROADMAP.md e ARQUITETURA.md
```
