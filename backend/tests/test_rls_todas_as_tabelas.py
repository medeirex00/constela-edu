"""RLS em toda tabela do app — 0036 (ENABLE, nunca FORCE).

Em 20/10/2026, produção tinha 4 tabelas de ``public`` sem RLS (``metas_rede``,
``modulos_rede``, ``notificacoes`` e ``revisoes_identidade``), porque o RLS foi ligado
fora do repositório e as tabelas novas nasceram sem ele. No Supabase, ``anon`` e
``authenticated`` têm GRANT em tudo: sem RLS, a API REST do Supabase lê essas tabelas.

1. ESTÁTICO (roda sempre): nenhuma migração usa FORCE (bloquearia o próprio backend),
   e a 0036 é a sucessora da 0035.
2. REAL (marcador ``postgres``; pula sem ``TEST_DATABASE_URL_PG``):
   * banco novo → ``upgrade heads`` → 100% das tabelas com RLS, nenhuma forçada;
   * banco como o de produção (RLS ligado só em parte) → a 0036 liga o que falta,
     e rodar de novo não muda nada;
   * um papel que não é dono e não tem BYPASSRLS (como ``anon``) não lê nem grava;
     o dono (o backend) continua lendo e gravando.
"""
import os
import re
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.migracoes import _config, aplicar_migracoes
from app.models import Escola, Notificacao

VERSOES = Path(__file__).resolve().parents[1] / "alembic" / "versions"

TABELAS_SEM_RLS = text(
    "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p') "
    "AND NOT c.relrowsecurity ORDER BY 1")
TABELAS_FORCADAS = text(
    "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p') "
    "AND c.relforcerowsecurity ORDER BY 1")
TOTAL_DE_TABELAS = text(
    "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p')")

# As 4 tabelas que estavam sem RLS em produção em 20/10/2026.
SEM_RLS_EM_PRODUCAO = ("metas_rede", "modulos_rede", "notificacoes", "revisoes_identidade")


# ---------------------------------------------------------------------------
# 1) Estático
# ---------------------------------------------------------------------------

def test_nenhuma_migracao_forca_o_rls():
    """FORCE faria o RLS valer também para o dono das tabelas (o backend), que não
    tem política nenhuma: o sistema pararia de ler e gravar."""
    forcadas = [arquivo.name for arquivo in sorted(VERSOES.glob("*.py"))
                if re.search(r"FORCE\s+ROW\s+LEVEL\s+SECURITY",
                             arquivo.read_text(encoding="utf-8"), re.IGNORECASE)]
    assert forcadas == []


def test_0036_vem_depois_da_0035():
    script = ScriptDirectory.from_config(_config())
    revisao = script.get_revision("0036_rls_todas_as_tabelas")
    assert revisao.down_revision == "0035_resultados_escolas"


# ---------------------------------------------------------------------------
# 2) PostgreSQL de verdade
# ---------------------------------------------------------------------------

@pytest.fixture
def engine_postgres():
    url = os.environ.get("TEST_DATABASE_URL_PG")
    if not url:
        pytest.skip("defina TEST_DATABASE_URL_PG para rodar contra PostgreSQL real")
    # O teste APAGA o schema public: só roda em banco cujo nome diz que é de teste.
    nome = make_url(url).database or ""
    if "test" not in nome.lower():
        pytest.skip(f"TEST_DATABASE_URL_PG aponta para '{nome}': o nome precisa conter 'test'")
    engine = create_engine(url)
    assert engine.dialect.name == "postgresql"
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    yield engine
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def _migrar(engine, alvo: str) -> None:
    cfg = _config()
    with engine.begin() as conexao:
        cfg.attributes["connection"] = conexao
        command.upgrade(cfg, alvo)


def _sem_rls(engine) -> list[str]:
    with engine.connect() as c:
        return [linha[0] for linha in c.execute(TABELAS_SEM_RLS)]


@pytest.mark.postgres
def test_banco_novo_sobe_com_rls_em_todas_as_tabelas(engine_postgres):
    aplicar_migracoes(engine_postgres)
    with engine_postgres.connect() as c:
        total = c.execute(TOTAL_DE_TABELAS).scalar()
        forcadas = [linha[0] for linha in c.execute(TABELAS_FORCADAS)]
    assert total > 40                       # o schema inteiro, não um banco vazio
    assert _sem_rls(engine_postgres) == []
    assert forcadas == []


@pytest.mark.postgres
def test_0036_liga_o_que_faltava_no_banco_de_producao_e_e_idempotente(engine_postgres):
    # Estado de produção antes da 0036: RLS ligado à mão em parte das tabelas.
    _migrar(engine_postgres, "0035_resultados_escolas")
    with engine_postgres.begin() as c:
        todas = [linha[0] for linha in c.execute(TABELAS_SEM_RLS)]
        for tabela in todas:
            if tabela not in SEM_RLS_EM_PRODUCAO:
                c.execute(text(f'ALTER TABLE "{tabela}" ENABLE ROW LEVEL SECURITY'))
    assert set(SEM_RLS_EM_PRODUCAO) <= set(_sem_rls(engine_postgres))

    aplicar_migracoes(engine_postgres)
    assert _sem_rls(engine_postgres) == []
    aplicar_migracoes(engine_postgres)              # de novo: nada muda, nada quebra
    assert _sem_rls(engine_postgres) == []
    with engine_postgres.connect() as c:
        assert [linha[0] for linha in c.execute(TABELAS_FORCADAS)] == []


@pytest.mark.postgres
def test_papel_sem_bypass_nao_le_nem_grava_e_o_dono_continua(engine_postgres):
    aplicar_migracoes(engine_postgres)
    papel = f"rls_teste_{uuid.uuid4().hex[:8]}"   # papel do cluster: nome único, apagado no fim
    with Session(engine_postgres) as s:                # o backend grava pelo ORM, como dono
        escola = Escola(nome="Escola Teste")
        s.add(escola)
        s.flush()
        s.add(Notificacao(escopo="escola", escola_id=escola.id, tipo="teste",
                          titulo="Aviso de teste"))
        s.commit()
    with engine_postgres.begin() as c:
        c.execute(text(f'CREATE ROLE "{papel}" NOLOGIN NOBYPASSRLS'))
        c.execute(text(f'GRANT USAGE ON SCHEMA public TO "{papel}"'))
        c.execute(text(f'GRANT SELECT, INSERT ON notificacoes, escolas TO "{papel}"'))
        # Como no Supabase (anon tem GRANT também nas sequências): sem isto o INSERT
        # pararia na sequência e o teste não provaria o RLS.
        c.execute(text(f'GRANT USAGE ON SEQUENCE notificacoes_id_seq TO "{papel}"'))
    try:
        with engine_postgres.begin() as c:
            c.execute(text(f'SET LOCAL ROLE "{papel}"'))
            assert c.execute(text("SELECT count(*) FROM notificacoes")).scalar() == 0
            assert c.execute(text("SELECT count(*) FROM escolas")).scalar() == 0
        with pytest.raises(Exception, match="row-level security"):
            with engine_postgres.begin() as c:
                c.execute(text(f'SET LOCAL ROLE "{papel}"'))
                c.execute(text(
                    "INSERT INTO notificacoes (escopo, tipo, severidade, titulo, created_at) "
                    "VALUES ('rede', 'teste', 'info', 'invasor', now())"))
        with engine_postgres.connect() as c:          # o dono (o backend) segue normal
            assert c.execute(text("SELECT count(*) FROM notificacoes")).scalar() == 1
    finally:
        with engine_postgres.begin() as c:
            c.execute(text(f'REVOKE ALL ON notificacoes, escolas FROM "{papel}"'))
            c.execute(text(f'REVOKE ALL ON SEQUENCE notificacoes_id_seq FROM "{papel}"'))
            c.execute(text(f'REVOKE USAGE ON SCHEMA public FROM "{papel}"'))
            c.execute(text(f'DROP ROLE "{papel}"'))
