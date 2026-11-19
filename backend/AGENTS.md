# Backend de Constela Edu e Constela Quest

Este escopo cobre `backend/`. A API FastAPI usa SQLAlchemy 2, Pydantic e Alembic. As regras de negócio e as autorizações ficam no servidor. SQLite atende o desenvolvimento e os testes locais. PostgreSQL atende a produção e o teste de migrações do CI.

## Estrutura

- `app/main.py` configura a aplicação e registra rotas. `app/routers/` expõe a API do Edu. `app/schemas/` define seus contratos.
- `app/core/` reúne configuração, banco, autenticação, autorização, tempo e observabilidade.
- `app/models/` define persistência. `app/services/` concentra as regras de negócio, incluindo o motor de pontuação em `app/services/pontuacao/`.
- `app/sync/` contém conectores, orquestração e agendamento de sincronização. `app/quest/` tem dependências, modelos, rotas, schemas e serviços do Quest.
- `alembic/versions/` contém migrações. `scripts/` reúne seeds e rotinas operacionais. `tests/` contém a suíte pytest.

## Comandos

Use o ambiente virtual do backend e instale suas dependências com `python -m pip install -r requirements.txt` a partir de `backend/`. O CI e a imagem Docker usam Python 3.13.

| Finalidade | Comando | Diretório |
| --- | --- | --- |
| Desenvolvimento | `python -m uvicorn app.main:app --reload --port 8000` | `backend/` |
| Dados de demonstração, em banco local | `python scripts/seed.py --demo` | `backend/` |
| Testes | `python -m pytest tests/ -q` | `backend/` |
| Cobertura, com piso de 88% | `python -m pytest -q --cov=app --cov-report=term` | `backend/` |
| Lint | `ruff check backend` | Raiz |
| Migrações no banco de desenvolvimento | `python -m scripts.migrate` | `backend/` |
| Build de imagem | `docker build -t sgpe-backend ./backend` | Raiz |

O CI usa Ruff 0.15.21 e exercita a aplicação repetida das migrações em PostgreSQL 16. O entrypoint aplica as migrações antes de iniciar o Uvicorn. Use um `DATABASE_URL` local de desenvolvimento ao iniciar a API, aplicar migrações ou executar o seed.

Confira as pontas com `python -m alembic heads` em `backend/`. Neste checkout, a migração local ainda fora do índice `0029_curriculo_fase1` e a sequência versionada `0030`–`0033` partem de `0028_nota_institucional`. O executor local usa `upgrade heads` e aceita os dois ramos. A verificação de PostgreSQL no CI usa `get_current_head()`, que exige uma única ponta. Valide a topologia em um banco descartável antes de usar esse conjunto em um banco compartilhado.

## Convenções

- Use dependências existentes em `app/core/deps.py` e `app/quest/deps.py` para validar identidade, papel, módulo e escopo. Preserve a separação entre tokens do Edu e do Quest. Aplique os filtros de rede, escola, turma e aluno conforme o recurso e o papel.
- Implemente regras nos serviços e mantenha os contratos validados nos schemas. Reutilize as regras de pontuação, identidade, períodos, permissões e sincronização para preservar o comportamento entre telas e clientes.
- Ao alterar o schema, crie uma migração Alembic compatível com dados já existentes e verifique SQLite e PostgreSQL. Teste alterações de autorização com o papel e o escopo permitidos e com os respectivos casos de acesso indevido.
- Preserve a fronteira do módulo Quest. Use o cadastro existente de escola, turma e aluno. Mantenha tabelas do módulo com prefixo `quest_` e a integração do professor nas rotas próprias do Quest.
- Use fixtures sintéticas e bancos descartáveis para testes e seeds. Mantenha credenciais, dados de alunos e artefatos gerados fora dos commits e logs.

Veja [Arquitetura](../docs/ARQUITETURA.md), [Permissões](../docs/permissoes/), [Sincronização](../docs/SINCRONIZACAO.md), [Quest](../docs/quest/README.md) e [CI/CD](../docs/CI-CD.md).
