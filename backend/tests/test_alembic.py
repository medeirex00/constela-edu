"""Infraestrutura de migrações Alembic.

Independe do conftest (que monta o schema via create_all): aqui exercitamos o
caminho REAL de produção — ``aplicar_migracoes`` sobre bancos SQLite
temporários (arquivo, não memória, para sobreviver entre conexões).
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

# Importar os pacotes de modelos registra TODAS as tabelas em Base.metadata.
import app.models        # noqa: F401
import app.quest.models  # noqa: F401
from app.core.config import BASE_DIR
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


def _head() -> set[str]:
    """Revisões FINAIS do diretório de migrações (para onde o upgrade leva).

    Conjunto, não string: frentes independentes podem partir da mesma revisão
    (RAMOS) e conviver — ``app.core.migracoes`` aplica ``heads``, todos eles."""
    return set(ScriptDirectory.from_config(_config()).get_heads())


def _versao(engine):
    """Revisões carimbadas no banco (conjunto — um banco com ramos tem mais de
    uma linha em ``alembic_version``); ``None`` se ainda não é versionado."""
    if "alembic_version" not in inspect(engine).get_table_names():
        return None
    with engine.connect() as c:
        return {linha[0] for linha in
                c.execute(text("SELECT version_num FROM alembic_version")).all()}


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
    assert _versao(engine) == {_REVISAO_BASE}
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


# ---------------------------------------------------------------------------
# CHECKOUT LIMPO — as revisões VERSIONADAS aplicam sozinhas
# ---------------------------------------------------------------------------
# O diretório `alembic/versions` de uma máquina de desenvolvimento pode conter
# revisões de OUTRO workstream que ainda não estão no git (hoje:
# `0029_curriculo_fase1`). Quem clona o repositório não as recebe. Se uma revisão
# nossa encadear numa dessas, o deploy/checkout limpo QUEBRA ("revision not
# present") e ninguém percebe localmente — porque localmente o arquivo existe.
#
# Os dois testes abaixo montam um `script_location` temporário com APENAS as
# revisões que um checkout limpo teria e provam que elas sobem sozinhas.

# Revisões DESTA frente ainda não commitadas (o `git add` é do dono). Assim que
# entrarem no git, `git ls-files` já as devolve e este conjunto vira redundante —
# é uma ponte, não uma lista de exceções permanentes.
_MIGRACOES_DESTA_FRENTE = {
    "0030_livro_identidade_oficial.py",
    "0031_leitura_nivel_congelado.py",
}

# env.py MÍNIMO para o diretório temporário: aplica as revisões sobre a conexão
# injetada. NÃO importa nada de `app` de propósito — este teste é sobre a CADEIA
# de revisões, não sobre o env.py da aplicação (coberto pelos testes acima).
_ENV_PY_DE_TESTE = '''\
from alembic import context

conexao = context.config.attributes["connection"]
context.configure(connection=conexao,
                  render_as_batch=conexao.dialect.name == "sqlite")
with context.begin_transaction():
    context.run_migrations()
'''

_DIR_VERSOES = BASE_DIR / "alembic" / "versions"
_RE_REVISION = re.compile(r"^revision(?::[^=]+)?\s*=\s*['\"]([^'\"]+)['\"]", re.M)
_RE_DOWN = re.compile(r"^down_revision(?::[^=]+)?\s*=\s*(None|['\"]([^'\"]+)['\"])", re.M)


def _no_git() -> set[str]:
    """Nomes dos arquivos de revisão RASTREADOS pelo git (o que um clone recebe)."""
    try:
        saida = subprocess.run(
            ["git", "-C", str(BASE_DIR.parent), "ls-files", "backend/alembic/versions"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as erro:  # git ausente no runner
        pytest.skip(f"git indisponível: {erro}")
    if saida.returncode != 0:
        pytest.skip(f"git ls-files falhou: {saida.stderr.strip()[:200]}")
    rastreados = {Path(linha).name for linha in saida.stdout.splitlines()
                  if linha.strip().endswith(".py")}
    if not rastreados:
        pytest.skip("nenhuma revisão rastreada pelo git (checkout sem histórico?)")
    return rastreados


def _montar_versoes_do_checkout(destino: Path) -> tuple[Path, set[str], set[str]]:
    """Monta um `script_location` só com o que um CHECKOUT LIMPO teria.

    Devolve ``(diretório, incluídas, excluídas)`` — nomes de arquivo."""
    presentes = {p.name for p in _DIR_VERSOES.glob("*.py")}
    incluidas = (_no_git() | _MIGRACOES_DESTA_FRENTE) & presentes
    excluidas = presentes - incluidas

    (destino / "versions").mkdir(parents=True, exist_ok=True)
    (destino / "env.py").write_text(_ENV_PY_DE_TESTE, encoding="utf-8")
    for nome in sorted(incluidas):
        shutil.copy2(_DIR_VERSOES / nome, destino / "versions" / nome)
    return destino, incluidas, excluidas


def test_revisao_versionada_nunca_encadeia_em_revisao_fora_do_git(tmp_path):
    """Trava de regressão: nenhuma revisão que vai para o git pode ter
    `down_revision` apontando para uma revisão que só existe nesta máquina.

    Falha com o nome do culpado (o `upgrade` do teste seguinte também falharia,
    mas com um erro de resolução do Alembic, bem menos legível)."""
    _, incluidas, excluidas = _montar_versoes_do_checkout(tmp_path / "alembic_git")

    def _ids(nomes):
        saida = {}
        for nome in nomes:
            texto = (_DIR_VERSOES / nome).read_text(encoding="utf-8")
            casou = _RE_REVISION.search(texto)
            assert casou, f"{nome}: sem `revision = '...'`"
            saida[casou.group(1)] = nome
        return saida

    ids_do_checkout = _ids(incluidas)
    ids_de_fora = _ids(excluidas)

    for nome in sorted(incluidas):
        casou = _RE_DOWN.search((_DIR_VERSOES / nome).read_text(encoding="utf-8"))
        assert casou, f"{nome}: sem `down_revision = ...`"
        anterior = casou.group(2)          # None (base) → group(2) é None
        if anterior is None:
            continue
        assert anterior not in ids_de_fora, (
            f"{nome} encadeia em '{anterior}' ({ids_de_fora[anterior]}), que NÃO está no "
            "git: um checkout limpo não teria essa revisão e o upgrade quebraria. "
            "Encadeie na última revisão VERSIONADA — ramos irmãos convivem "
            "(app.core.migracoes aplica 'heads').")
        assert anterior in ids_do_checkout, (
            f"{nome} encadeia em '{anterior}', que não existe em nenhum arquivo de revisão.")


def test_checkout_limpo_aplica_migracoes_versionadas_sozinhas(fazer_engine, tmp_path):
    """Só com as revisões do git (sem a `0029` do outro workstream), um SQLite
    novo sobe até `heads` com o schema completo — inclusive as colunas desta
    frente (`livros.elefante_id`, `leituras.nivel_codigo`)."""
    dir_alembic, incluidas, excluidas = _montar_versoes_do_checkout(tmp_path / "alembic_git")

    cfg = Config()                       # sem alembic.ini: só o script_location importa
    cfg.set_main_option("script_location", str(dir_alembic))
    assert ScriptDirectory.from_config(cfg).get_heads(), "nenhum head no recorte versionado"

    engine = fazer_engine("checkout_limpo.db")
    with engine.connect() as conexao:
        conexao.exec_driver_sql("PRAGMA foreign_keys=OFF")   # migrações em lote (SQLite)
        cfg.attributes["connection"] = conexao
        command.upgrade(cfg, "heads")                        # heads: todos os ramos
        conexao.commit()

    insp = inspect(engine)
    tabelas = set(insp.get_table_names())
    assert {"alembic_version", "escolas", "usuarios", "alunos", "turmas", "matriculas",
            "livros", "leituras", "notas", "snapshots_elefante"} <= tabelas

    cols_livros = {c["name"] for c in insp.get_columns("livros")}
    assert {"elefante_id", "nivel_fonte", "origem_nivel", "word_count",
            "atualizado_em"} <= cols_livros, "a 0030 não aplicou no checkout limpo"
    cols_leituras = {c["name"] for c in insp.get_columns("leituras")}
    assert {"nivel_codigo", "catalogo_versao"} <= cols_leituras, \
        "a 0031 não aplicou no checkout limpo"
    cols_notas = {c["name"] for c in insp.get_columns("notas")}
    assert {"nota_elefante_institucional", "nota_matific_institucional"} <= cols_notas

    # O recorte é REAL: enquanto a 0029 estiver fora do git, as tabelas dela não
    # existem neste banco (se existissem, o teste não estaria provando nada).
    if any(nome.startswith("0029") for nome in excluidas):
        assert not [t for t in tabelas if t.startswith("cur_")]


@pytest.mark.parametrize("como", ["reencadear_a_0030", "acrescentar_revisao_nova"])
def test_a_trava_do_checkout_limpo_realmente_pega_o_encadeamento_proibido(
        fazer_engine, tmp_path, monkeypatch, como):
    """META-TESTE: uma trava que nunca falha não protege nada.

    Reproduz, num diretório de revisões TEMPORÁRIO (o repositório não é tocado),
    as duas formas de cometer o erro — reencadear uma revisão existente na `0029`
    (fora do git) ou acrescentar uma revisão nova já encadeada nela — e exige que
    AS DUAS travas acusem: a estrutural com mensagem legível nomeando o arquivo
    culpado, e o `upgrade` de verdade quebrando o recorte do checkout limpo.

    Sem isto, um regex que parasse de casar (ou um recorte que passasse a incluir
    tudo) deixaria os dois testes acima verdes para sempre."""
    versoes = tmp_path / "versoes_mutadas"
    versoes.mkdir()
    for arquivo in _DIR_VERSOES.glob("*.py"):
        shutil.copy2(arquivo, versoes / arquivo.name)

    if como == "reencadear_a_0030":
        culpado = "0030_livro_identidade_oficial.py"
        alvo = versoes / culpado
        texto = alvo.read_text(encoding="utf-8").replace(
            "down_revision: Union[str, None] = '0028_nota_institucional'",
            "down_revision: Union[str, None] = '0029_curriculo_fase1'")
        assert "'0029_curriculo_fase1'" in texto, "a mutação não pegou"
        alvo.write_text(texto, encoding="utf-8")
        extras: set[str] = set()
    else:
        culpado = "0032_revisao_nova_de_teste.py"
        (versoes / culpado).write_text(
            "from typing import Sequence, Union\n"
            "revision: str = '0032_revisao_nova_de_teste'\n"
            "down_revision: Union[str, None] = '0029_curriculo_fase1'\n"
            "branch_labels = None\ndepends_on = None\n"
            "def upgrade() -> None:\n    pass\n"
            "def downgrade() -> None:\n    pass\n", encoding="utf-8")
        extras = {culpado}          # como se já estivesse a caminho do git

    monkeypatch.setattr("tests.test_alembic._DIR_VERSOES", versoes)
    if extras:
        monkeypatch.setattr("tests.test_alembic._MIGRACOES_DESTA_FRENTE",
                            _MIGRACOES_DESTA_FRENTE | extras)
    # Pré-condição: a `0029` tem de estar mesmo FORA do git — se o outro
    # workstream a commitar, o cenário deixa de existir e o teste não se aplica.
    # Perguntado DIRETO ao git, não por `_no_git`: usar o próprio helper que está
    # sob teste faria um recorte afrouxado (que passasse a incluir tudo) virar um
    # SKIP silencioso em vez da falha que ele merece.
    try:
        rastreada = subprocess.run(
            ["git", "-C", str(BASE_DIR.parent), "ls-files", "--error-unmatch",
             "backend/alembic/versions/0029_curriculo_fase1.py"],
            capture_output=True, text=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        rastreada = False       # sem git: `_no_git` lá dentro é quem pula
    if rastreada:
        pytest.skip("a 0029 entrou no git: o cenário do encadeamento proibido não existe mais")

    with pytest.raises(AssertionError) as estrutural:
        test_revisao_versionada_nunca_encadeia_em_revisao_fora_do_git(tmp_path / "e1")
    assert culpado in str(estrutural.value)
    assert "0029_curriculo_fase1" in str(estrutural.value)

    with pytest.raises(Exception) as upgrade:      # ResolutionError/KeyError do Alembic
        test_checkout_limpo_aplica_migracoes_versionadas_sozinhas(fazer_engine, tmp_path / "e2")
    assert "0029_curriculo_fase1" in str(upgrade.value)
