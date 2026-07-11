"""Infraestrutura de migrações Alembic.

Independe do conftest (que monta o schema via create_all): aqui exercitamos o
caminho REAL de produção — ``aplicar_migracoes`` sobre bancos SQLite
temporários (arquivo, não memória, para sobreviver entre conexões).
"""
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

# Importar os pacotes de modelos registra TODAS as tabelas em Base.metadata.
import app.models        # noqa: F401
import app.quest.models  # noqa: F401
from app.core.database import Base
from app.core.migracoes import _REVISAO_BASE, _config, aplicar_migracoes


@pytest.fixture
def fazer_engine(tmp_path):
    """Cria engines SQLite em arquivo temporário e as descarta ao final —
    liberar o arquivo evita travas de exclusão no Windows."""
    criadas = []

    def _criar(nome: str = "db.sqlite"):
        engine = create_engine(f"sqlite:///{tmp_path / nome}")
        criadas.append(engine)
        return engine

    yield _criar
    for engine in criadas:
        engine.dispose()


def _head() -> str:
    """Última revisão do diretório de migrações (para onde o upgrade leva)."""
    return ScriptDirectory.from_config(_config()).get_current_head()


def _versao(engine):
    if "alembic_version" not in inspect(engine).get_table_names():
        return None
    with engine.connect() as c:
        return c.execute(text("SELECT version_num FROM alembic_version")).scalar()


def test_banco_novo_recebe_schema_completo(fazer_engine):
    """Banco vazio: o upgrade cria TODAS as tabelas dos modelos e versiona."""
    engine = fazer_engine("novo.db")
    aplicar_migracoes(engine)

    tabelas = set(inspect(engine).get_table_names())
    esperadas = set(Base.metadata.tables) | {"alembic_version"}
    assert esperadas <= tabelas
    assert _versao(engine) == _head()


def test_colunas_e_indices_criticos_presentes(fazer_engine):
    """As colunas/índices críticos existem — e a senha reversível NÃO existe."""
    engine = fazer_engine("schema.db")
    aplicar_migracoes(engine)
    insp = inspect(engine)

    cols_turmas = {c["name"] for c in insp.get_columns("turmas")}
    assert {"turno", "capacidade_maxima", "observacoes", "status"} <= cols_turmas

    cols_usuarios = {c["name"] for c in insp.get_columns("usuarios")}
    assert {"username", "token_version"} <= cols_usuarios
    # A cópia reversível da senha foi REMOVIDA (0002); o reset é por token.
    assert "senha_visivel" not in cols_usuarios
    assert "tokens_reset_senha" in insp.get_table_names()

    idx_leituras = {i["name"] for i in insp.get_indexes("leituras")}
    assert {"ix_leituras_aluno_data", "ix_leituras_escola_data"} <= idx_leituras

    idx_usuarios = {i["name"]: i for i in insp.get_indexes("usuarios")}
    assert idx_usuarios["ix_usuarios_username"]["unique"]


def test_idempotente(fazer_engine):
    """Rodar duas vezes não quebra nem altera a versão."""
    engine = fazer_engine("idem.db")
    aplicar_migracoes(engine)
    aplicar_migracoes(engine)  # segunda vez: nada a fazer
    assert _versao(engine) == _head()


def test_banco_pre_alembic_e_carimbado_sem_perder_dados(fazer_engine):
    """Instalação anterior ao Alembic: adotada sem perder dados; as migrações
    seguintes (ex.: remover senha_visivel) aplicam por cima."""
    engine = fazer_engine("antigo.db")

    # Monta o schema EXATAMENTE na revisão base (0001, ainda com senha_visivel)
    # e apaga a marca de versão — assim o banco parece anterior ao Alembic.
    cfg = _config()
    with engine.begin() as conexao:
        cfg.attributes["connection"] = conexao
        command.upgrade(cfg, _REVISAO_BASE)
    with engine.begin() as c:
        c.execute(text("DROP TABLE alembic_version"))
        c.execute(text(
            "INSERT INTO escolas (nome, ano_letivo_ativo, status, created_at) "
            "VALUES ('Escola Piloto', 2026, 'ativa', '2026-01-01 00:00:00')"))
    assert _versao(engine) is None  # ainda não versionado
    cols = {c["name"] for c in inspect(engine).get_columns("usuarios")}
    assert "senha_visivel" in cols  # o legado tinha a coluna

    aplicar_migracoes(engine)

    # Adotado e migrado até o head: dado preservado, senha_visivel removida.
    assert _versao(engine) == _head()
    cols_apos = {c["name"] for c in inspect(engine).get_columns("usuarios")}
    assert "senha_visivel" not in cols_apos
    with engine.connect() as c:
        assert c.execute(text("SELECT nome FROM escolas")).scalar_one() == "Escola Piloto"


def _schema(engine):
    """Fotografia comparável do schema: tabelas, colunas (nome→tipo base), FKs
    (coluna→ON DELETE) e índices (nomes)."""
    insp = inspect(engine)
    out = {}
    for tabela in insp.get_table_names():
        if tabela == "alembic_version":
            continue
        cols = {c["name"]: str(c["type"]).upper().split("(")[0]
                for c in insp.get_columns(tabela)}
        fks = {}
        for fk in insp.get_foreign_keys(tabela):
            for col in fk["constrained_columns"]:
                fks[col] = (fk.get("options") or {}).get("ondelete")
        idx = {i["name"] for i in insp.get_indexes(tabela)}
        out[tabela] = {"cols": cols, "fks": fks, "idx": idx}
    return out


def test_schema_do_create_all_bate_com_o_das_migracoes(fazer_engine):
    """Fidelidade de produção: o schema que o conftest monta rápido (create_all)
    é IDÊNTICO ao que as migrações Alembic produzem (o schema de produção).

    É o que autoriza a suíte a usar create_all como atalho — este teste trava a
    deriva: um modelo novo sem migração (ou uma migração sem o modelo) quebra
    aqui, em vez de só estourar em produção."""
    from sqlalchemy import create_engine as _criar
    from sqlalchemy.pool import StaticPool

    e_create = _criar("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    Base.metadata.create_all(e_create)
    e_migr = fazer_engine("paridade.db")
    aplicar_migracoes(e_migr)

    atual, producao = _schema(e_create), _schema(e_migr)
    e_create.dispose()

    assert set(atual) == set(producao)
    for tabela in atual:
        assert atual[tabela]["cols"] == producao[tabela]["cols"], f"colunas: {tabela}"
        assert atual[tabela]["fks"] == producao[tabela]["fks"], f"FKs: {tabela}"
        assert atual[tabela]["idx"] == producao[tabela]["idx"], f"índices: {tabela}"


def test_ondelete_aplicado_pela_migracao(fazer_engine):
    """A migração 0003 aplica os ON DELETE no banco (não só o create_all)."""
    engine = fazer_engine("ondelete.db")
    aplicar_migracoes(engine)
    insp = inspect(engine)

    def od(tabela: str, coluna: str):
        for fk in insp.get_foreign_keys(tabela):
            if coluna in fk["constrained_columns"]:
                return (fk.get("options") or {}).get("ondelete")
        return "SEM_FK"

    assert od("leituras", "aluno_id") == "CASCADE"
    assert od("tokens_reset_senha", "usuario_id") == "CASCADE"
    assert od("tokens_reset_senha", "criado_por") == "SET NULL"
    assert od("turmas", "professor_id") == "SET NULL"
    assert od("logs_auditoria", "usuario_id") == "SET NULL"
    # RESTRICT preservado (sem ON DELETE): tenant, matrícula/turma, snapshot
    assert od("leituras", "escola_id") is None
    assert od("matriculas", "turma_id") is None
    assert od("snapshots_matific", "importacao_id") is None


# As 10 tabelas que a 0001 define e que faltavam no banco de produção carimbado
# em 0001 (nascido antes das features Quest/responsáveis). Ordem reversa de
# dependência para o DROP (filhos antes dos pais).
_TABELAS_DO_INCIDENTE = [
    "quest_tentativas", "quest_progresso", "quest_habilidades",
    "responsaveis_alunos", "quest_credenciais_aluno", "quest_perfis",
    "quest_desafios", "quest_missoes", "quest_jornadas", "quest_mundos",
]


def test_0002a_repara_baseline_carimbado_sem_tabelas_do_quest(fazer_engine):
    """Regressão do incidente de produção (a 0002a): um banco CARIMBADO em 0001
    SEM as 10 tabelas de Quest/responsáveis deve migrar até o head sem quebrar —
    a 0002a recria as tabelas ausentes ANTES de a 0003 adicionar FKs a elas.
    Sem a 0002a, a 0003 abortava o boot com 'quest_perfis does not exist'."""
    engine = fazer_engine("incidente.db")

    # 1) Sobe o baseline 0001 (cria TODAS as tabelas, inclusive as 10) e então
    #    DROPa as 10 — reproduzindo o banco de produção carimbado em 0001 que
    #    nunca teve essas tabelas. O alembic_version permanece em '0001'.
    cfg = _config()
    with engine.begin() as conexao:
        cfg.attributes["connection"] = conexao
        command.upgrade(cfg, _REVISAO_BASE)
    with engine.begin() as c:
        for tabela in _TABELAS_DO_INCIDENTE:
            c.execute(text(f"DROP TABLE {tabela}"))

    # Pré-condição: estado EXATO do incidente (carimbado 0001, tabelas ausentes).
    presentes = set(inspect(engine).get_table_names())
    assert _versao(engine) == _REVISAO_BASE
    assert not (set(_TABELAS_DO_INCIDENTE) & presentes), "pré-condição não reproduzida"

    # 2) Caminho REAL de produção: migra do 0001 até o head. Sem a 0002a isto
    #    estouraria na 0003 (FK sobre quest_perfis inexistente).
    aplicar_migracoes(engine)

    # 3) Migrou até o fim e recriou TODAS as 10 tabelas.
    assert _versao(engine) == _head()
    apos = set(inspect(engine).get_table_names())
    assert set(_TABELAS_DO_INCIDENTE) <= apos

    # 4) O schema reparado é IDÊNTICO ao dos modelos (colunas, FKs/ON DELETE,
    #    índices) para as 10 tabelas — a 0002a não pode recriar uma tabela
    #    "quase igual", e a 0003 tem de aplicar as FKs sobre as recriadas.
    #    (create_all == schema de produção é garantido por
    #    test_schema_do_create_all_bate_com_o_das_migracoes; comparar com ele
    #    evita abrir um 2º banco em arquivo.)
    from sqlalchemy import create_engine as _criar
    from sqlalchemy.pool import StaticPool

    e_ref = _criar("sqlite://", connect_args={"check_same_thread": False},
                   poolclass=StaticPool)
    Base.metadata.create_all(e_ref)
    reparado_s, ref_s = _schema(engine), _schema(e_ref)
    e_ref.dispose()
    for tabela in _TABELAS_DO_INCIDENTE:
        assert reparado_s[tabela] == ref_s[tabela], f"schema divergente: {tabela}"
