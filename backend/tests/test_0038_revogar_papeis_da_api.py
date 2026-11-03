"""A 0038 tira de anon/authenticated (papéis da API do Supabase) todo privilégio no schema
do app — inclusive TRUNCATE, que o RLS não cobre — e os privilégios padrão para tabelas
novas. Marcador ``postgres`` (pula sem ``TEST_DATABASE_URL_PG``).

Os papéis ``anon``/``authenticated`` são do CLUSTER: o teste cria se faltarem (como o
Supabase) e nunca os apaga (podem ter privilégios em outros bancos do cluster)."""
import importlib.util
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.migracoes import _config, aplicar_migracoes
from app.models import Escola

VERSAO = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0038_revogar_papeis_da_api.py"
PAPEIS = ("anon", "authenticated")


def _modulo():
    spec = importlib.util.spec_from_file_location("m0038", VERSAO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_0038_vem_depois_da_0037_e_nao_devolve_na_descida():
    m = _modulo()
    assert m.down_revision == "0037_quest_codigo_hash_limites"
    assert m.PAPEIS_DA_API == PAPEIS
    fonte = VERSAO.read_text(encoding="utf-8")
    corpo_da_descida = fonte.split("def downgrade", 1)[1]
    assert "GRANT" not in corpo_da_descida and "FORCE" not in fonte.split('"""', 2)[2]


@pytest.fixture
def engine_postgres():
    url = os.environ.get("TEST_DATABASE_URL_PG")
    if not url:
        pytest.skip("defina TEST_DATABASE_URL_PG para rodar contra PostgreSQL real")
    nome = make_url(url).database or ""
    if "test" not in nome.lower():
        pytest.skip(f"TEST_DATABASE_URL_PG aponta para '{nome}': o nome precisa conter 'test'")
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
        for papel in PAPEIS:
            existe = c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :p"), {"p": papel}).scalar()
            if not existe:
                c.execute(text(f'CREATE ROLE "{papel}" NOLOGIN'))
    yield engine
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
        for tipo in ("TABLES", "SEQUENCES", "FUNCTIONS"):     # os globais não morrem com o schema
            c.execute(text(f'ALTER DEFAULT PRIVILEGES REVOKE ALL ON {tipo} FROM "anon", "authenticated"'))
    engine.dispose()


def _como_o_supabase(engine):
    """O que o Supabase concede: USAGE no schema, ALL em tabelas/sequências e os
    privilégios padrão do dono para tudo que for criado depois."""
    with engine.begin() as c:
        for papel in PAPEIS:
            c.execute(text(f'GRANT USAGE ON SCHEMA public TO "{papel}"'))
            c.execute(text(f'GRANT ALL ON ALL TABLES IN SCHEMA public TO "{papel}"'))
            c.execute(text(f'GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO "{papel}"'))
            for tipo in ("TABLES", "SEQUENCES", "FUNCTIONS"):
                c.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON {tipo} TO "{papel}"'))
                # E um global (sem IN SCHEMA), que o REVOKE por schema não removeria.
                c.execute(text(f'ALTER DEFAULT PRIVILEGES GRANT ALL ON {tipo} TO "{papel}"'))


def _privilegios(engine, papel, exceto=("",)):
    """(tabelas, sequências, entradas de privilégio padrão) em que o papel tem QUALQUER
    privilégio — inclusive MAINTAIN no PostgreSQL 17 e SELECT/UPDATE de sequência."""
    with engine.connect() as c:
        privilegios = ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"]
        if c.execute(text("SELECT current_setting('server_version_num')::int")).scalar() >= 170000:
            privilegios.append("MAINTAIN")
        algum = " OR ".join(f"has_table_privilege(:p, c.oid, '{x}')" for x in privilegios)
        tabelas = c.execute(text(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            f"WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m') AND c.relname <> ALL(:exceto) AND ({algum})"),
            {"p": papel, "exceto": list(exceto)}).scalar()
        sequencias = c.execute(text(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'S' AND CASE WHEN c.relkind = 'S' "
            "THEN has_sequence_privilege(:p, c.oid, 'USAGE') OR has_sequence_privilege(:p, c.oid, 'SELECT') "
            "OR has_sequence_privilege(:p, c.oid, 'UPDATE') ELSE false END"),
            {"p": papel}).scalar()
        padroes = c.execute(text(
            "SELECT count(*) FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) a "
            "WHERE d.defaclrole = (SELECT oid FROM pg_roles WHERE rolname = current_user) "
            "AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = :p)"), {"p": papel}).scalar()
    return tabelas, sequencias, padroes


def _migrar(engine, alvo):
    cfg = _config()
    with engine.begin() as conexao:
        cfg.attributes["connection"] = conexao
        command.upgrade(cfg, alvo)


@pytest.mark.postgres
def test_estado_de_producao_fica_sem_nada_para_a_api_e_tabelas_novas_tambem(engine_postgres):
    _migrar(engine_postgres, "0037_quest_codigo_hash_limites")
    _como_o_supabase(engine_postgres)
    for papel in PAPEIS:                                   # o estado lido em produção
        tabelas, sequencias, padroes = _privilegios(engine_postgres, papel)
        assert tabelas > 40 and sequencias > 40 and padroes >= 6

    aplicar_migracoes(engine_postgres)
    for papel in PAPEIS:
        assert _privilegios(engine_postgres, papel) == (0, 0, 0)
        with engine_postgres.connect() as c:          # USAGE no schema fica (decisão da 0038)
            assert c.execute(text("SELECT has_schema_privilege(:p, 'public', 'USAGE')"),
                             {"p": papel}).scalar()

    # Tabela criada DEPOIS (como faria a próxima migração, pelo mesmo papel): nasce fechada.
    with engine_postgres.begin() as c:
        c.execute(text("CREATE TABLE tabela_nova_teste (id serial PRIMARY KEY, x text)"))
    with engine_postgres.connect() as c:
        for papel in PAPEIS:
            assert not c.execute(text("SELECT has_table_privilege(:p, 'tabela_nova_teste', 'SELECT')"),
                                 {"p": papel}).scalar()
            assert not c.execute(text("SELECT has_table_privilege(:p, 'tabela_nova_teste', 'TRUNCATE')"),
                                 {"p": papel}).scalar()

    aplicar_migracoes(engine_postgres)                     # de novo: nada muda, nada quebra
    for papel in PAPEIS:
        assert _privilegios(engine_postgres, papel) == (0, 0, 0)


@pytest.mark.postgres
def test_anon_nao_trunca_nem_le_e_o_dono_continua(engine_postgres):
    _migrar(engine_postgres, "0037_quest_codigo_hash_limites")
    _como_o_supabase(engine_postgres)
    with Session(engine_postgres) as s:                # o backend grava pelo ORM, como dono
        s.add(Escola(nome="Escola Teste"))
        s.commit()
    aplicar_migracoes(engine_postgres)
    for comando in ("TRUNCATE escolas CASCADE", "SELECT count(*) FROM escolas"):
        with pytest.raises(Exception, match="permission denied"):
            with engine_postgres.begin() as c:
                c.execute(text('SET LOCAL ROLE "anon"'))
                c.execute(text(comando))
    with engine_postgres.connect() as c:
        assert c.execute(text("SELECT count(*) FROM escolas")).scalar() == 1



@pytest.mark.postgres
def test_objeto_de_outro_dono_nao_trava_e_vira_aviso(engine_postgres):
    """Como em produção, a migração roda por um papel NÃO superusuário (dono do schema,
    com BYPASSRLS). Um objeto de OUTRO dono, em que ele não tem privilégio nenhum e cujo
    dono concedeu acesso ao anon: um REVOKE em massa daria ERRO e desfaria a execução;
    a 0038 não toca nele, termina, revoga o resto e avisa a sobra."""

    url = engine_postgres.url
    # Senha fictícia: o serviço postgres:16 do CI confere senha (scram-sha-256) em toda
    # conexão TCP; sem ela, o papel de migração não entra (o PG local "trust" escondia isso).
    senha = "Fict0038teste"
    with engine_postgres.begin() as c:
        for papel, atributos in (("rev_migr_test", "LOGIN NOSUPERUSER BYPASSRLS"),
                                 ("rev_outro_test", "NOLOGIN")):
            if not c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :p"), {"p": papel}).scalar():
                c.execute(text(f'CREATE ROLE "{papel}" {atributos}'))
        c.execute(text(f"ALTER ROLE \"rev_migr_test\" PASSWORD '{senha}'"))
        c.execute(text('ALTER SCHEMA public OWNER TO "rev_migr_test"'))
    migracao = create_engine(url.set(username="rev_migr_test", password=senha))
    try:
        with migracao.connect() as c:
            assert c.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).scalar() is False
        _migrar(migracao, "0037_quest_codigo_hash_limites")
        _como_o_supabase(migracao)
        with engine_postgres.begin() as c:
            c.execute(text("CREATE TABLE alheia_test (x int)"))
            c.execute(text('ALTER TABLE alheia_test OWNER TO "rev_outro_test"'))
            c.execute(text('GRANT USAGE ON SCHEMA public TO "rev_outro_test"'))
            c.execute(text('SET LOCAL ROLE "rev_outro_test"'))
            c.execute(text('GRANT SELECT ON alheia_test TO "anon"'))
        aplicar_migracoes(migracao)                        # não levanta
        with migracao.connect() as c:                       # e chega ao head (0038 ou depois)
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar()                 == ScriptDirectory.from_config(_config()).get_current_head()
        assert _privilegios(migracao, "anon", exceto=("alheia_test",)) == (0, 0, 0)
        with engine_postgres.connect() as c:                # a sobra continua lá, e foi avisada
            assert c.execute(text("SELECT has_table_privilege('anon', 'alheia_test', 'SELECT')")).scalar()
        with migracao.connect() as c:                       # o que a 0038 lista no WARNING
            assert "alheia_test:SELECT" in _modulo()._sobras(c, "anon")
            assert [x for x in _modulo()._sobras(c, "anon") if not x.startswith("alheia_test:")] == []
    finally:
        migracao.dispose()
        with engine_postgres.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE"))
            c.execute(text("CREATE SCHEMA public"))
            c.execute(text('DROP OWNED BY "rev_migr_test", "rev_outro_test"'))
            c.execute(text('DROP ROLE "rev_migr_test"'))
            c.execute(text('DROP ROLE "rev_outro_test"'))


def test_modo_offline_gera_o_sql_sem_consultar_o_catalogo(capfd, monkeypatch):
    """``alembic upgrade 0037:0038 --sql``: sem banco, gera o bloco DO (que confere os
    papéis no próprio servidor) e avisa que a conferência das sobras só roda online."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+psycopg://ninguem@localhost/offline_test")
    capfd.readouterr()
    command.upgrade(_config(), "0037_quest_codigo_hash_limites:0038_revogar_papeis_da_api", sql=True)
    saida = capfd.readouterr()
    assert "DO $revogar$" in saida.out
    assert "REVOKE ALL ON TABLE %I.%I FROM %I" in saida.out
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE %I REVOKE ALL ON TABLES FROM %I" in saida.out
    assert "0038 em modo offline (--sql)" in saida.err


def test_bloco_do_e_valido_e_sem_parametro_de_bind():
    """O bloco vai por sa.text: nenhum ':nome' que o SQLAlchemy tomaria por parâmetro."""
    import re

    bloco = _modulo()._bloco_revogar(("anon", "authenticated"))
    assert re.search(r"(?<![:\w]):(?!:)\w", bloco) is None
    assert bloco.count("$revogar$") == 2
