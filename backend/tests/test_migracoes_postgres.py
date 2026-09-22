"""Migrações × PostgreSQL — regressão do incidente de 17/09/2026 (deploy 7bc9d54).

A 0027 fazia ``UPDATE notas SET aferido_leitura = 1`` e ``WHERE aferido_leitura = 1``.
O SQLite aceita inteiro em coluna booleana; o PostgreSQL recusa
(``DatatypeMismatch: column "aferido_leitura" is of type boolean but expression is
of type integer``). A migração abortou no entrypoint do Railway, o container não
subiu e o backend de produção caiu. A suíte só migrava em SQLite, então nada acusou.

Três travas:

1. ESTÁTICA (roda sempre): nenhuma string SQL de migração compara ou atribui um
   literal ``0``/``1`` (booleano vai como parâmetro tipado); e todo id de revisão
   cabe em ``alembic_version.version_num`` (VARCHAR(32) — o SQLite não impõe o
   tamanho, o PostgreSQL impõe).
2. INTENÇÃO (roda sempre, SQLite): a partir de um banco na 0026, o backfill da 0027
   produz exatamente ``aferido = existe snapshot da plataforma`` e ``posição = ordem
   por nota decrescente dentro de (escola, ano), desempate por aluno_id``.
3. REAL (marcador ``postgres``; pula sem ``TEST_DATABASE_URL_PG``): o MESMO cenário
   num PostgreSQL de verdade, pelo caminho de produção (``aplicar_migracoes`` da
   0026 até ``heads``), mais a segunda execução (idempotência).
"""
import io
import os
import re
import tokenize
from datetime import date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy import types as sqltypes
from sqlalchemy.engine import make_url

from app.core.config import BASE_DIR
from app.core.migracoes import _config, aplicar_migracoes

VERSOES = BASE_DIR / "alembic" / "versions"
REVISAO_ANTERIOR = "0026_modulos_rede"      # onde produção estava no incidente
TAMANHO_VERSION_NUM = 32                    # alembic_version.version_num no PostgreSQL


# ---------------------------------------------------------------------------
# 1) Travas estáticas
# ---------------------------------------------------------------------------

_LITERAL_BOOLEANO_INTEIRO = re.compile(r"(?<![<>!=])(=|<>|!=)\s*[01](?![\d.])")


def _trechos_de_string(arquivo: Path) -> list[tuple[int, str]]:
    """Conteúdo das strings do arquivo (inclusive os pedaços literais de f-strings),
    sem comentários nem código Python — é onde mora o SQL cru das migrações."""
    trechos = []
    tipos = {tokenize.STRING}
    if hasattr(tokenize, "FSTRING_MIDDLE"):   # Python ≥ 3.12 separa as f-strings
        tipos.add(tokenize.FSTRING_MIDDLE)
    fonte = arquivo.read_text(encoding="utf-8")
    for token in tokenize.generate_tokens(io.StringIO(fonte).readline):
        if token.type in tipos:
            trechos.append((token.start[0], token.string))
    return trechos


def test_nenhuma_migracao_usa_literal_inteiro_em_sql():
    """Booleano em SQL cru de migração vai como parâmetro tipado
    (``sa.bindparam(..., type_=sa.Boolean())``), nunca ``= 1``/``= 0``: o literal
    passa no SQLite e derruba o deploy no PostgreSQL."""
    ocorrencias = []
    for arquivo in sorted(VERSOES.glob("*.py")):
        for linha, trecho in _trechos_de_string(arquivo):
            if trecho.lstrip("rbuRBUfF").startswith(('"""', "'''")):
                continue                     # docstring: texto, não SQL
            if _LITERAL_BOOLEANO_INTEIRO.search(trecho):
                ocorrencias.append(f"{arquivo.name}:{linha}: {trecho.strip()[:80]}")
    assert not ocorrencias, (
        "SQL de migração com literal inteiro (quebra coluna booleana no PostgreSQL):\n"
        + "\n".join(ocorrencias))


def test_trava_estatica_pega_o_sql_do_incidente(tmp_path):
    """A trava acima não pode ser decorativa: o SQL exato que derrubou o deploy
    tem de ser acusado."""
    falsa = tmp_path / "0027_incidente.py"
    falsa.write_text(
        'COL = "aferido_leitura"\n'
        'SQL = f"UPDATE notas SET {COL} = 1 WHERE EXISTS (SELECT 1 FROM x)"\n'
        'SEL = f"SELECT id FROM notas WHERE {COL} = 1 ORDER BY id"\n',
        encoding="utf-8")
    achados = [t for _, t in _trechos_de_string(falsa) if _LITERAL_BOOLEANO_INTEIRO.search(t)]
    assert len(achados) == 2


def test_ids_de_revisao_cabem_no_alembic_version_do_postgres():
    longos = [r.revision for r in ScriptDirectory.from_config(_config()).walk_revisions()
              if len(r.revision) > TAMANHO_VERSION_NUM]
    assert not longos, f"ids de revisão com mais de {TAMANHO_VERSION_NUM} caracteres: {longos}"


# ---------------------------------------------------------------------------
# Cenário compartilhado: banco na 0026 com as quatro situações do backfill
# ---------------------------------------------------------------------------

def _valor_minimo(coluna):
    """Valor válido para uma coluna NOT NULL sem default (só para montar a linha)."""
    tipo = coluna.type
    if isinstance(tipo, sqltypes.Boolean):
        return False
    if isinstance(tipo, sqltypes.Integer):
        return 0
    if isinstance(tipo, (sqltypes.Float, sqltypes.Numeric)):
        return 0.0
    if isinstance(tipo, sqltypes.DateTime):
        return datetime(2026, 1, 1)
    if isinstance(tipo, sqltypes.Date):
        return date(2026, 1, 1)
    if isinstance(tipo, sqltypes.JSON):
        return {}
    return "x"


def _inserir(conexao, meta: MetaData, tabela: str, **valores) -> int:
    """INSERT pelo schema REFLETIDO do banco (o da 0026, não o dos modelos atuais):
    preenche só o obrigatório que o cenário não informou. Devolve o id."""
    t = meta.tables[tabela]
    linha = dict(valores)
    for coluna in t.columns:
        if coluna.name in linha or coluna.primary_key:
            continue
        if not coluna.nullable and coluna.server_default is None:
            linha[coluna.name] = _valor_minimo(coluna)
    resultado = conexao.execute(t.insert().values(**linha).returning(t.c.id))
    return resultado.scalar_one()


def _montar_banco_na_0026(engine) -> dict:
    """Schema até a 0026 (estado de produção no incidente) + dados que exercitam o
    backfill: só Leitura, só Matemática, as duas, nenhuma, empate de nota e outra
    escola (a posição é por escola)."""
    cfg = _config()
    with engine.begin() as conexao:
        cfg.attributes["connection"] = conexao
        command.upgrade(cfg, REVISAO_ANTERIOR)
    ids: dict[str, int] = {}
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        e1 = _inserir(c, meta, "escolas", nome="E1", ano_letivo_ativo=2026)
        e2 = _inserir(c, meta, "escolas", nome="E2", ano_letivo_ativo=2026)
        imp = {e: {p: _inserir(c, meta, "importacoes", escola_id=e, plataforma=p, tipo="seed")
                   for p in ("elefante", "matific")} for e in (e1, e2)}
        # nome → (escola, nota_elefante, nota_matific, tem_elefante, tem_matific)
        plano = {
            "so_leitura": (e1, 50.0, 0.0, True, False),
            "as_duas": (e1, 80.0, 70.0, True, True),
            "so_matematica": (e1, 0.0, 90.0, False, True),
            "nenhuma": (e1, 0.0, 0.0, False, False),
            "nota_sem_snapshot": (e1, 95.0, 0.0, False, False),   # nota alta, NÃO aferido
            "empata_com_as_duas": (e1, 80.0, 0.0, True, False),
            "outra_escola": (e2, 10.0, 0.0, True, False),
        }
        quando = datetime(2026, 8, 3, 10, 0)
        for nome, (escola, n_ele, n_mat, tem_ele, tem_mat) in plano.items():
            aluno = _inserir(c, meta, "alunos", escola_id=escola, nome=nome.upper(), status="ativo")
            ids[nome] = aluno
            _inserir(c, meta, "notas", escola_id=escola, aluno_id=aluno, ano_letivo=2026,
                     nota_elefante=n_ele, nota_matific=n_mat, nota_geral=0.0)
            if tem_ele:
                _inserir(c, meta, "snapshots_elefante", escola_id=escola, aluno_id=aluno,
                         importacao_id=imp[escola]["elefante"], data_referencia=quando)
            if tem_mat:
                _inserir(c, meta, "snapshots_matific", escola_id=escola, aluno_id=aluno,
                         importacao_id=imp[escola]["matific"], data_referencia=quando)
        ids["livro"] = _inserir(c, meta, "livros", escola_id=e1, titulo="Livro Antigo", nivel_codigo="C")
        _inserir(c, meta, "leituras", escola_id=e1, aluno_id=ids["so_leitura"], livro_id=ids["livro"], data=quando)
    return ids


def _conferir_migracao(engine, ids: dict) -> None:
    heads = set(ScriptDirectory.from_config(_config()).get_heads())
    aplicar_migracoes(engine)                                   # caminho de produção
    with engine.connect() as c:
        assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))} == heads
        notas = {r.aluno_id: r for r in c.execute(text(
            "SELECT aluno_id, aferido_leitura, aferido_matematica, posicao_leitura, posicao_matematica "
            "FROM notas"))}
        livro = c.execute(text("SELECT origem_nivel, elefante_id FROM livros WHERE id = :i"),
                          {"i": ids["livro"]}).one()
        leitura = c.execute(text("SELECT nivel_codigo, catalogo_versao FROM leituras")).one()

    def linha(nome):
        return notas[ids[nome]]

    # aferido = existe snapshot da plataforma (nunca "nota > 0")
    assert {n for n in ids if n != "livro" and linha(n).aferido_leitura} == {
        "so_leitura", "as_duas", "empata_com_as_duas", "outra_escola"}
    assert {n for n in ids if n != "livro" and linha(n).aferido_matematica} == {"as_duas", "so_matematica"}
    # posição = nota desc dentro de (escola, ano), só aferidos, desempate por aluno_id
    assert linha("as_duas").posicao_leitura == 1              # 80, id menor que o empate
    assert linha("empata_com_as_duas").posicao_leitura == 2   # 80, id maior
    assert linha("so_leitura").posicao_leitura == 3           # 50
    assert linha("outra_escola").posicao_leitura == 1         # ranking é por escola
    assert linha("nota_sem_snapshot").posicao_leitura is None
    assert linha("so_matematica").posicao_matematica == 1     # 90
    assert linha("as_duas").posicao_matematica == 2           # 70
    assert linha("nenhuma").posicao_leitura is None and linha("nenhuma").posicao_matematica is None
    # 0030/0031: dado antigo intacto, colunas novas com o default combinado
    assert livro.origem_nivel == "legado" and livro.elefante_id is None
    assert leitura.nivel_codigo is None and leitura.catalogo_versao is None

    # idempotência: rodar de novo (o import do app em modo dev faz isso) não muda nada
    aplicar_migracoes(engine)
    with engine.connect() as c:
        assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))} == heads


# ---------------------------------------------------------------------------
# 2) Intenção do backfill — SQLite (sempre)
# ---------------------------------------------------------------------------

def test_0027_backfill_da_0026_ate_heads_no_sqlite(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'incidente_0027.db'}")
    try:
        _conferir_migracao(engine, _montar_banco_na_0026(engine))
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 3) O mesmo cenário num PostgreSQL de verdade
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


@pytest.mark.postgres
def test_0027_backfill_da_0026_ate_heads_no_postgres(engine_postgres):
    ids = _montar_banco_na_0026(engine_postgres)
    tipos = {c["name"]: c["type"] for c in inspect(engine_postgres).get_columns("notas")}
    assert "aferido_leitura" not in tipos                       # pré-condição: estado da 0026
    _conferir_migracao(engine_postgres, ids)
    tipos = {c["name"]: c["type"] for c in inspect(engine_postgres).get_columns("notas")}
    assert isinstance(tipos["aferido_leitura"], sqltypes.Boolean)
    assert isinstance(tipos["aferido_matematica"], sqltypes.Boolean)


# ---------------------------------------------------------------------------
# 4) 0032 — fila de revisão de identidade (aditiva), SQLite e PostgreSQL
# ---------------------------------------------------------------------------

REVISAO_0031 = "0031_leitura_nivel_congelado"   # estado de produção antes da 0032
REVISAO_0032 = "0032_revisoes_identidade"


def _migrar(engine, alvo: str, subir: bool = True) -> None:
    cfg = _config()
    with engine.begin() as conexao:
        cfg.attributes["connection"] = conexao
        (command.upgrade if subir else command.downgrade)(cfg, alvo)


def _banco_na_0031(engine) -> dict:
    _migrar(engine, REVISAO_0031)
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        e = _inserir(c, meta, "escolas", nome="E", ano_letivo_ativo=2026)
        return {
            "escola": e,
            "turma": _inserir(c, meta, "turmas", escola_id=e, nome="5ºA",
                              ano_escolar="5º Ano", ano_letivo=2026),
            "aluno": _inserir(c, meta, "alunos", escola_id=e, status="ativo",
                              nome="HELOISA DEL GIUDICE DE SOUZA FIDELIX"),
            "importacao": _inserir(c, meta, "importacoes", escola_id=e,
                                   plataforma="elefante", tipo="texto"),
        }


def _conferir_0032(engine, ids: dict) -> None:
    _migrar(engine, REVISAO_0032)
    insp = inspect(engine)
    assert "revisoes_identidade" in insp.get_table_names()
    assert {"ix_revisoes_identidade_escola_id", "ix_revisoes_identidade_escola_status",
            "ix_revisoes_identidade_escola_chave"} <= {
        i["name"] for i in insp.get_indexes("revisoes_identidade")}
    ondelete = {fk["constrained_columns"][0]: (fk.get("options") or {}).get("ondelete")
                for fk in insp.get_foreign_keys("revisoes_identidade")}
    assert ondelete["aluno_escolhido_id"] == "SET NULL"
    assert ondelete["importacao_id"] == "SET NULL"
    assert ondelete["turma_id"] == "SET NULL"
    assert ondelete["escola_id"] is None

    # Uma pendência real (JSON de verdade no tipo do banco) sobrevive à exclusão da
    # ficha escolhida: o histórico da decisão não some com o aluno.
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        tabela = meta.tables["revisoes_identidade"]
        rid = _inserir(
            c, meta, "revisoes_identidade", escola_id=ids["escola"],
            chave="elefante|id:9|resumo||", chave_identidade="elefante|id:9",
            plataforma="elefante", formato="resumo", id_externo="9",
            nome_recebido="HELOISA DE SOUZA FIDELIX", turma_id=ids["turma"],
            motivo="correspondencia_insegura",
            candidatos=[{"aluno_id": ids["aluno"], "nome": "HELOISA", "status": "ativo"}],
            linhas=[{"livros_unicos": 3, "elefante_student_id": "9"}],
            contexto={"tipo": "texto"}, origem="sincronizacao",
            importacao_id=ids["importacao"], ocorrencias=1, status="resolvida",
            aluno_escolhido_id=ids["aluno"])
        linha = c.execute(tabela.select().where(tabela.c.id == rid)).one()
        assert linha.candidatos[0]["aluno_id"] == ids["aluno"]
        assert linha.linhas == [{"livros_unicos": 3, "elefante_student_id": "9"}]
    with engine.connect() as c:
        if engine.dialect.name == "sqlite":
            c.exec_driver_sql("PRAGMA foreign_keys=ON")
        c.execute(text("DELETE FROM alunos WHERE id = :a"), {"a": ids["aluno"]})
        c.commit()
    with engine.connect() as c:
        assert c.execute(text("SELECT aluno_escolhido_id FROM revisoes_identidade "
                              "WHERE id = :r"), {"r": rid}).scalar_one() is None

    # Downgrade: remove SÓ a tabela nova; o resto do banco fica intacto.
    _migrar(engine, REVISAO_0031, subir=False)
    assert "revisoes_identidade" not in inspect(engine).get_table_names()
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM turmas")).scalar_one() == 1
        assert c.execute(text("SELECT count(*) FROM importacoes")).scalar_one() == 1
    # Sobe de novo e convive com as demais heads (caminho de produção, idempotente).
    _migrar(engine, REVISAO_0032)
    aplicar_migracoes(engine)
    aplicar_migracoes(engine)
    heads = set(ScriptDirectory.from_config(_config()).get_heads())
    with engine.connect() as c:
        assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))} == heads


def test_0032_revisoes_identidade_sobe_e_desce_no_sqlite(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'revisoes_0032.db'}")
    try:
        _conferir_0032(engine, _banco_na_0031(engine))
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_0032_revisoes_identidade_sobe_e_desce_no_postgres(engine_postgres):
    _conferir_0032(engine_postgres, _banco_na_0031(engine_postgres))
