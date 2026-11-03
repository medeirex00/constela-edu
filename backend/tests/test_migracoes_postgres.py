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
import hashlib
import importlib.util
import io
import json
import os
import re
import time
import tokenize
from datetime import date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, bindparam, create_engine, inspect, text
from sqlalchemy import types as sqltypes
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR
from app.core.migracoes import _config, aplicar_migracoes
from app.services import avaliacoes as svc_avaliacoes

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
                              nome="HELOISA DORVANTE GRASSETTI DE SIMULATTI FICTELLI"),
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
            nome_recebido="HELOISA DE SIMULATTI FICTELLI", turma_id=ids["turma"],
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


# ---------------------------------------------------------------------------
# 5) 0034 — indicadores de referência (aditiva), SQLite e PostgreSQL
# ---------------------------------------------------------------------------

REVISAO_0033 = "0033_identidade_aposentada"     # head versionada antes da 0034
REVISAO_0034 = "0034_indicadores_referencia"
_TABELAS_0034 = {"importacoes_indicador", "indicadores_referencia"}
_CHAVE_0034 = ["avaliacao_id", "edicao", "indicador", "abrangencia", "codigo_territorio",
               "codigo_inep", "rede_ensino", "localizacao", "etapa", "componente", "nivel"]


def _banco_na_0033(engine) -> dict:
    """Estado de produção antes da 0034, com um resultado de escola que a 0034 não
    pode tocar (ela é só de tabelas novas)."""
    _migrar(engine, REVISAO_0033)
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        av = _inserir(c, meta, "avaliacoes_externas", chave="ica", nome="ICA",
                      tipo="indicador")
        escola = _inserir(c, meta, "escolas", nome="E", ano_letivo_ativo=2026)
        _inserir(c, meta, "resultados_avaliacao", avaliacao_id=av, edicao=2025,
                 escola_id=escola, indicador="taxa_alfabetizacao", valor=97.0,
                 unidade="percentual")
    return {"avaliacao": av, "tabelas": set(inspect(engine).get_table_names())}


def _linha_referencia(c, meta, avaliacao_id: int, importacao_id: int, **extra) -> int:
    campos = dict(avaliacao_id=avaliacao_id, edicao=2025, indicador="percentual_alfabetizado",
                  abrangencia="municipio", codigo_territorio="3599999", rede_ensino="municipal",
                  unidade="percentual", valor=29.0, casas_decimais=0,
                  importacao_id=importacao_id)
    campos.update(extra)
    return _inserir(c, meta, "indicadores_referencia", **campos)


def _conferir_0034(engine, ids: dict) -> None:
    _migrar(engine, REVISAO_0034)
    insp = inspect(engine)
    assert set(insp.get_table_names()) - ids["tabelas"] == _TABELAS_0034
    colunas = {c["name"]: c for c in insp.get_columns("indicadores_referencia")}
    assert not [c for c in _CHAVE_0034 if colunas[c]["nullable"]], "chave com coluna nula"
    assert colunas["valor"]["nullable"] and colunas["motivo_ausencia"]["nullable"]
    # a precisão PUBLICADA da capa e do detalhe (o float perde o zero final)
    assert colunas["casas_decimais"]["nullable"] and colunas["casas_decimais_detalhe"]["nullable"]
    unicas = {u["name"]: u["column_names"] for u in
              insp.get_unique_constraints("indicadores_referencia")}
    assert unicas["uq_indicador_referencia_natural"] == _CHAVE_0034   # sem COALESCE
    ondelete = {fk["constrained_columns"][0]: (fk.get("options") or {}).get("ondelete")
                for fk in insp.get_foreign_keys("indicadores_referencia")}
    assert ondelete == {"avaliacao_id": "CASCADE", "importacao_id": "SET NULL",
                        "detalhe_importacao_id": "SET NULL"}            # sem FK de escola/rede
    assert "ix_indicadores_referencia_territorio" in {
        i["name"] for i in insp.get_indexes("indicadores_referencia")}
    # O plano de desfazer fica numa coluna À PARTE (nula na prévia), fora do resumo.
    colunas_imp = {c["name"]: c for c in insp.get_columns("importacoes_indicador")}
    assert colunas_imp["desfazer"]["nullable"] and not colunas_imp["resumo"]["nullable"]

    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        imp = _inserir(c, meta, "importacoes_indicador", avaliacao_id=ids["avaliacao"],
                       status="aplicada", contadores={"novas": 1}, resumo={"avisos": []})
        _linha_referencia(c, meta, ids["avaliacao"], imp)
    with engine.connect() as c:
        linha = c.execute(text("SELECT codigo_inep, localizacao, etapa, componente, nivel "
                               "FROM indicadores_referencia")).one()
        assert tuple(linha) == ("", "total", "", "", "")               # defaults do servidor
    # Mesma chave natural de novo: o banco recusa (a idempotência não depende só do código).
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            meta = MetaData()
            meta.reflect(bind=c)
            _linha_referencia(c, meta, ids["avaliacao"], imp, valor=30.0)
    # Ausência sem motivo: o CHECK recusa (ausência ≠ zero, e nunca sem explicação).
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            meta = MetaData()
            meta.reflect(bind=c)
            _linha_referencia(c, meta, ids["avaliacao"], imp, edicao=2024, valor=None)
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        _linha_referencia(c, meta, ids["avaliacao"], imp, edicao=2024, valor=None,
                          motivo_ausencia="nao_divulgado")

    if engine.dialect.name == "postgresql":
        with engine.connect() as c:
            rls = {r.relname: (r.relrowsecurity, r.relforcerowsecurity) for r in c.execute(text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname IN ('importacoes_indicador', 'indicadores_referencia')"))}
        assert rls == {t: (True, False) for t in _TABELAS_0034}         # ENABLE, nunca FORCE

    # Downgrade: remove SÓ as duas tabelas; o resultado da escola fica intacto.
    _migrar(engine, REVISAO_0033, subir=False)
    assert set(inspect(engine).get_table_names()) == ids["tabelas"]
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM resultados_avaliacao")).scalar_one() == 1
        assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))} == {
            REVISAO_0033}
    # Sobe de novo pelo caminho de produção (idempotente) até as heads.
    _migrar(engine, REVISAO_0034)
    aplicar_migracoes(engine)
    aplicar_migracoes(engine)
    heads = set(ScriptDirectory.from_config(_config()).get_heads())
    with engine.connect() as c:
        assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))} == heads
        assert c.execute(text("SELECT count(*) FROM indicadores_referencia")).scalar_one() == 0


def test_0034_indicadores_referencia_sobe_e_desce_no_sqlite(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'indicadores_0034.db'}")
    try:
        _conferir_0034(engine, _banco_na_0033(engine))
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_0034_indicadores_referencia_sobe_e_desce_no_postgres(engine_postgres):
    _conferir_0034(engine_postgres, _banco_na_0033(engine_postgres))


# ---------------------------------------------------------------------------
# 6) 0035 — resultados por escola com ausência e proveniência, etapa = série,
#    INEP único e CODMUN da rede (etapa E4), SQLite e PostgreSQL
# ---------------------------------------------------------------------------

REVISAO_0035 = "0035_resultados_escolas"
_DESCRICAO_SARESP_ANTIGA = "Avaliação de rendimento da rede estadual de São Paulo."


def _indice_existe(engine, nome: str) -> bool:
    """Pelo catálogo do banco: o inspector do SQLite pula índice de expressão."""
    with engine.connect() as c:
        if engine.dialect.name == "sqlite":
            sql = "SELECT count(*) FROM sqlite_master WHERE type = 'index' AND name = :n"
        else:
            sql = "SELECT count(*) FROM pg_indexes WHERE indexname = :n"
        return c.execute(text(sql), {"n": nome}).scalar_one() == 1


def _banco_na_0034(engine) -> dict:
    """Estado de produção antes da 0035 (como a cópia de 05/10): SAEB e SARESP com
    etapa "anos_iniciais", IDEB "anos_iniciais", a estimativa no "2_ano"."""
    _migrar(engine, REVISAO_0034)
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        av = {ch: _inserir(c, meta, "avaliacoes_externas", chave=ch, nome=ch.upper(),
                           tipo="avaliacao",
                           descricao=_DESCRICAO_SARESP_ANTIGA if ch == "saresp" else None)
              for ch in ("saeb", "ideb", "saresp", "crianca_alfabetizada")}
        e1 = _inserir(c, meta, "escolas", nome="E1", ano_letivo_ativo=2026,
                      codigo_inep="35990001")
        e2 = _inserir(c, meta, "escolas", nome="E2", ano_letivo_ativo=2026)
        _inserir(c, meta, "escolas", nome="E3", ano_letivo_ativo=2026)   # 2 sem INEP: livre
        rede = _inserir(c, meta, "redes", nome="Rede", status="ativa")
        for avid, edicao, indicador, etapa, comp, valor in (
                (av["saeb"], 2023, "proficiencia", "anos_iniciais", "matematica", 211.0),
                (av["saeb"], 2023, "proficiencia", "anos_iniciais", "portugues", 203.0),
                (av["ideb"], 2023, "ideb", "anos_iniciais", None, 5.8),
                (av["saresp"], 2025, "proficiencia", "anos_iniciais", "portugues", 187.0),
                (av["saresp"], 2025, "proficiencia", "anos_iniciais", "matematica", 197.0),
                (av["crianca_alfabetizada"], 2025, "taxa_alfabetizacao", "2_ano", None, 93.0)):
            _inserir(c, meta, "resultados_avaliacao", avaliacao_id=avid, edicao=edicao,
                     escola_id=e1, indicador=indicador, etapa=etapa, componente=comp,
                     valor=valor, unidade="u")
        # Receitas do robô gravadas antes da 0035 (o formulário sugeria "anos_iniciais").
        fontes = {nome: _inserir(c, meta, "fontes_avaliacao", avaliacao_id=av[chave],
                                 nome=nome, url="https://exemplo.invalido/x.csv",
                                 edicao=2023, indicador="proficiencia", unidade="u",
                                 mapeamento={"linha_dados": 1, "col_inep": 0,
                                             "col_valor": 1, "etapa_fixa": etapa})
                  for nome, chave, etapa in (("saeb", "saeb", "anos_iniciais"),
                                             ("saresp", "saresp", "Anos Iniciais"),
                                             ("saresp_2", "saresp", "2_ano"),
                                             ("ideb", "ideb", "anos_iniciais"))}
    return {"av": av, "e1": e1, "e2": e2, "rede": rede, "fontes": fontes}


def _etapas_fixas(engine) -> dict[str, str]:
    with engine.connect() as c:
        linhas = c.execute(text("SELECT nome, mapeamento FROM fontes_avaliacao")).all()
    return {nome: (json.loads(m) if isinstance(m, str) else m)["etapa_fixa"]
            for nome, m in linhas}


def _etapas(engine) -> list[tuple]:
    with engine.connect() as c:
        return sorted(tuple(r) for r in c.execute(text(
            "SELECT a.chave, r.etapa, COALESCE(r.componente, '') FROM resultados_avaliacao r "
            "JOIN avaliacoes_externas a ON a.id = r.avaliacao_id")))


def _resultado(c, meta, ids, **extra):
    campos = dict(avaliacao_id=ids["av"]["saresp"], edicao=2024, escola_id=ids["e1"],
                  indicador="proficiencia", etapa="2_ano", componente="portugues",
                  unidade="escala_saresp")
    campos.update(extra)
    return _inserir(c, meta, "resultados_avaliacao", **campos)


def _conferir_0035(engine, ids: dict) -> None:
    antes = _etapas(engine)
    assert len(antes) == 6
    _migrar(engine, REVISAO_0035)
    # Etapa = série no SAEB e no SARESP; IDEB e a estimativa intactos; mesma contagem.
    assert _etapas(engine) == sorted([
        ("saeb", "5_ano", "matematica"), ("saeb", "5_ano", "portugues"),
        ("ideb", "anos_iniciais", ""), ("saresp", "5_ano", "portugues"),
        ("saresp", "5_ano", "matematica"), ("crianca_alfabetizada", "2_ano", "")])
    insp = inspect(engine)
    colunas = {c["name"]: c for c in insp.get_columns("resultados_avaliacao")}
    assert colunas["valor"]["nullable"]
    assert colunas["motivo_ausencia"]["nullable"] and colunas["importacao_id"]["nullable"]
    ondelete = {fk["constrained_columns"][0]: (fk.get("options") or {}).get("ondelete")
                for fk in insp.get_foreign_keys("resultados_avaliacao")}
    assert ondelete["importacao_id"] == "SET NULL" and ondelete["escola_id"] == "CASCADE"
    assert "ck_resultado_valor_ou_motivo" in {
        ck["name"] for ck in insp.get_check_constraints("resultados_avaliacao")}
    assert _indice_existe(engine, "uq_resultado_natural")       # recriado depois do batch
    assert _indice_existe(engine, "uq_escolas_codigo_inep")
    assert "codigo_municipio_estadual" in {c["name"] for c in insp.get_columns("redes")}
    with engine.connect() as c:
        assert c.execute(text("SELECT descricao FROM avaliacoes_externas WHERE chave = :c"),
                         {"c": "saresp"}).scalar_one().startswith("Sistema de Avaliação")
    # A receita do robô do SAEB/SARESP segue a série (senão toda coleta cairia em erro);
    # a do IDEB e o 2º ano do SARESP ficam.
    assert _etapas_fixas(engine) == {"saeb": "5_ano", "saresp": "5_ano",
                                     "saresp_2": "2_ano", "ideb": "anos_iniciais"}

    # O índice de expressão continua barrando a duplicata (NULOS como '').
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            meta = MetaData()
            meta.reflect(bind=c)
            _resultado(c, meta, ids, avaliacao_id=ids["av"]["saeb"], edicao=2023,
                       etapa="5_ano", componente="matematica", valor=1.0)
    # Ausência sem motivo: o CHECK recusa; com motivo, entra (ausência ≠ zero).
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            meta = MetaData()
            meta.reflect(bind=c)
            _resultado(c, meta, ids, valor=None)
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        imp = _inserir(c, meta, "importacoes_indicador", avaliacao_id=ids["av"]["saresp"],
                       status="aplicada", contadores={}, resumo={})
        _resultado(c, meta, ids, valor=None, motivo_ausencia="nao_divulgado",
                   importacao_id=imp)
        _resultado(c, meta, ids, componente="matematica", valor=150.5, importacao_id=imp)
    # Apagar a importação não apaga o número (SET NULL).
    with engine.connect() as c:
        if engine.dialect.name == "sqlite":
            c.exec_driver_sql("PRAGMA foreign_keys=ON")
        c.execute(text("DELETE FROM importacoes_indicador WHERE id = :i"), {"i": imp})
        c.commit()
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM resultados_avaliacao WHERE edicao = :e "
                              "AND importacao_id IS NULL"), {"e": 2024}).scalar_one() == 2
    # INEP único (parcial: várias escolas sem INEP continuam livres).
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(text("UPDATE escolas SET codigo_inep = :c WHERE id = :e"),
                      {"c": "35990001", "e": ids["e2"]})

    # Downgrade: ausências saem antes; etapa volta; colunas, CHECK, índice das escolas
    # e coluna da rede saem; o uq_resultado_natural é recriado.
    _migrar(engine, REVISAO_0034, subir=False)
    insp = inspect(engine)
    colunas = {c["name"]: c for c in insp.get_columns("resultados_avaliacao")}
    assert not colunas["valor"]["nullable"]
    assert "motivo_ausencia" not in colunas and "importacao_id" not in colunas
    assert not insp.get_check_constraints("resultados_avaliacao")
    assert _indice_existe(engine, "uq_resultado_natural")
    assert not _indice_existe(engine, "uq_escolas_codigo_inep")
    assert "codigo_municipio_estadual" not in {c["name"] for c in insp.get_columns("redes")}
    assert _etapas(engine) == sorted([*antes, ("saresp", "2_ano", "matematica")])
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM resultados_avaliacao "
                              "WHERE valor IS NULL")).scalar_one() == 0
        assert c.execute(text("SELECT descricao FROM avaliacoes_externas WHERE chave = :c"),
                         {"c": "saresp"}).scalar_one() == _DESCRICAO_SARESP_ANTIGA
    assert _etapas_fixas(engine) == {"saeb": "anos_iniciais", "saresp": "anos_iniciais",
                                     "saresp_2": "2_ano", "ideb": "anos_iniciais"}
    with pytest.raises(IntegrityError):              # o índice recriado ainda barra
        with engine.begin() as c:
            meta = MetaData()
            meta.reflect(bind=c)
            _resultado(c, meta, ids, avaliacao_id=ids["av"]["saeb"], edicao=2023,
                       etapa="anos_iniciais", componente="matematica", valor=1.0)
    # Sobe de novo pelo caminho de produção (idempotente) até as heads.
    _migrar(engine, REVISAO_0035)
    aplicar_migracoes(engine)
    aplicar_migracoes(engine)
    heads = set(ScriptDirectory.from_config(_config()).get_heads())
    with engine.connect() as c:
        assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))} == heads
    assert len(_etapas(engine)) == 7


def test_0035_resultados_escolas_sobe_e_desce_no_sqlite(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'resultados_0035.db'}")
    try:
        _conferir_0035(engine, _banco_na_0034(engine))
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_0035_resultados_escolas_sobe_e_desce_no_postgres(engine_postgres):
    _conferir_0035(engine_postgres, _banco_na_0034(engine_postgres))


def _conferir_grafias_da_etapa_0035(engine, ids: dict) -> None:
    """O robô antigo gravava a ``etapa_fixa`` como veio ("Anos Iniciais"): a 0035 troca
    essas linhas pela MESMA regra da receita — senão a receita passaria a "5_ano" e a
    coleta seguinte abriria uma segunda série ao lado da "Anos Iniciais". E o downgrade
    devolve linhas e receita no mesmo vocabulário ("anos_iniciais")."""
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        _resultado(c, meta, ids, edicao=2024, etapa="Anos Iniciais", valor=180.0)
        _resultado(c, meta, ids, avaliacao_id=ids["av"]["saeb"], edicao=2021,
                   etapa="anos-iniciais", valor=199.0)
        _resultado(c, meta, ids, avaliacao_id=ids["av"]["ideb"], edicao=2021,
                   indicador="ideb", etapa="Anos Iniciais", componente=None, valor=5.1)

    def etapas_extras() -> list[tuple]:
        with engine.connect() as c:
            return sorted(tuple(r) for r in c.execute(text(
                "SELECT a.chave, r.edicao, r.etapa FROM resultados_avaliacao r JOIN "
                "avaliacoes_externas a ON a.id = r.avaliacao_id WHERE r.edicao IN (2021, 2024)")))

    _migrar(engine, REVISAO_0035)
    assert etapas_extras() == [("ideb", 2021, "Anos Iniciais"),     # o IDEB fica como está
                               ("saeb", 2021, "5_ano"), ("saresp", 2024, "5_ano")]
    assert _etapas_fixas(engine)["saresp"] == "5_ano"               # a receita "Anos Iniciais"
    _migrar(engine, REVISAO_0034, subir=False)
    assert etapas_extras() == [("ideb", 2021, "Anos Iniciais"),
                               ("saeb", 2021, "anos_iniciais"), ("saresp", 2024, "anos_iniciais")]
    assert _etapas_fixas(engine)["saresp"] == "anos_iniciais"       # o mesmo vocabulário


def test_0035_troca_toda_grafia_da_etapa_no_sqlite(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'grafias_0035.db'}")
    try:
        _conferir_grafias_da_etapa_0035(engine, _banco_na_0034(engine))
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_0035_troca_toda_grafia_da_etapa_no_postgres(engine_postgres):
    _conferir_grafias_da_etapa_0035(engine_postgres, _banco_na_0034(engine_postgres))


def test_0035_recusa_no_boot_desde_a_0033_nao_deixa_a_0034_pela_metade_no_sqlite(tmp_path):
    """SQLite: o boot (``aplicar_migracoes``) sobe 0033 → heads numa execução só. Se a
    0035 recusa (INEP repetido), a 0034 da MESMA execução sai junto — antes, o pysqlite
    fazia autocommit do CREATE TABLE: as tabelas ficavam com a ``alembic_version`` em
    0033 ("nada foi alterado" era falso) e o boot seguinte quebrava com "already exists"."""
    engine = create_engine(f"sqlite:///{tmp_path / 'boot_0035.db'}")
    try:
        _migrar(engine, REVISAO_0033)
        with engine.begin() as c:
            meta = MetaData()
            meta.reflect(bind=c)
            for nome in ("A", "B"):
                _inserir(c, meta, "escolas", nome=nome, ano_letivo_ativo=2026,
                         codigo_inep="35990001")
        with pytest.raises(RuntimeError, match="0035: o mesmo código INEP"):
            aplicar_migracoes(engine)
        assert not _TABELAS_0034 & set(inspect(engine).get_table_names())
        with engine.connect() as c:
            assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))
                    } == {REVISAO_0033}
        with engine.begin() as c:
            c.execute(text("UPDATE escolas SET codigo_inep = NULL WHERE nome = :n"), {"n": "B"})
        aplicar_migracoes(engine)                                    # corrigido, sobe
        heads = set(ScriptDirectory.from_config(_config()).get_heads())
        with engine.connect() as c:
            assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))
                    } == heads
    finally:
        engine.dispose()


def _conferir_trava_0035(engine, ids: dict, montar) -> None:
    """A 0035 PARA (sem mexer em nada) quando a troca de etapa repetiria uma chave ou
    quando o mesmo INEP está em duas escolas — nunca funde nem apaga em silêncio."""
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        montar(c, meta, ids)
    antes = _etapas(engine)
    with pytest.raises(RuntimeError, match="0035"):
        _migrar(engine, REVISAO_0035)
    with engine.connect() as c:
        assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))} == {
            REVISAO_0034}
    assert _etapas(engine) == antes


def _colisao_de_etapa(c, meta, ids):
    _inserir(c, meta, "resultados_avaliacao", avaliacao_id=ids["av"]["saeb"], edicao=2023,
             escola_id=ids["e1"], indicador="proficiencia", etapa="5_ano",
             componente="matematica", valor=212.0, unidade="u")


def _inep_repetido(c, meta, ids):
    c.execute(text("UPDATE escolas SET codigo_inep = :c WHERE id = :e"),
              {"c": "35990001", "e": ids["e2"]})


def _colisao_entre_grafias(c, meta, ids):
    """"Anos Iniciais" ao lado de "anos_iniciais" na mesma chave: as duas virariam a
    mesma linha "5_ano" — PARA (nunca escolhe uma em silêncio)."""
    _inserir(c, meta, "resultados_avaliacao", avaliacao_id=ids["av"]["saeb"], edicao=2023,
             escola_id=ids["e1"], indicador="proficiencia", etapa="Anos Iniciais",
             componente="matematica", valor=212.0, unidade="u")


@pytest.mark.parametrize("montar", [_colisao_de_etapa, _inep_repetido, _colisao_entre_grafias])
def test_0035_para_sem_mexer_em_nada_no_sqlite(tmp_path, montar):
    engine = create_engine(f"sqlite:///{tmp_path / 'trava_0035.db'}")
    try:
        _conferir_trava_0035(engine, _banco_na_0034(engine), montar)
    finally:
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.parametrize("montar", [_colisao_de_etapa, _inep_repetido, _colisao_entre_grafias])
def test_0035_para_sem_mexer_em_nada_no_postgres(engine_postgres, montar):
    _conferir_trava_0035(engine_postgres, _banco_na_0034(engine_postgres), montar)


def _conferir_downgrade_0035_nao_perde_numero_sem_registro(engine, ids: dict) -> None:
    """Uma importação oficial APLICADA trocou a média calculada pelo Constela (sem
    ``importacao_id``) por uma ausência: o downgrade PARA (apagar a ausência levaria o
    número, que só existe no plano de desfazer). Desfeita a importação, ele segue."""
    _migrar(engine, REVISAO_0035)
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        chave = {"alvo": "esc", "avaliacao_id": ids["av"]["saresp"], "edicao": 2025,
                 "indicador": "proficiencia", "escola_id": ids["e1"], "etapa": "5_ano",
                 "componente": "portugues", "turma": None}
        imp = _inserir(c, meta, "importacoes_indicador", avaliacao_id=ids["av"]["saresp"],
                       status="aplicada", contadores={}, resumo={},
                       desfazer={"criadas": [], "chaves": [chave], "alteradas": [{
                           "chave": chave, "tipo": "substituicao",
                           "antes": {"valor": 187.0, "unidade": "u", "motivo_ausencia": None,
                                     "fonte": "calculado", "importacao_id": None,
                                     "codigo_inep": None, "rede_id": None},
                           "depois": {"valor": None, "unidade": "u",
                                      "motivo_ausencia": "nao_divulgado", "fonte": "oficial",
                                      "importacao_id": 0, "codigo_inep": "35990001",
                                      "rede_id": None}}]})
        c.execute(text("UPDATE resultados_avaliacao SET valor = NULL, motivo_ausencia = :m, "
                       "importacao_id = :i WHERE avaliacao_id = :a AND componente = :c"),
                  {"m": "nao_divulgado", "i": imp, "a": ids["av"]["saresp"], "c": "portugues"})
    with pytest.raises(RuntimeError, match=rf"0035 \(downgrade\).*#{imp} \(1 número"):
        _migrar(engine, REVISAO_0034, subir=False)
    with engine.connect() as c:
        assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))} == {
            REVISAO_0035}
        assert c.execute(text("SELECT count(*) FROM resultados_avaliacao "
                              "WHERE valor IS NULL")).scalar_one() == 1        # nada mexido
    with engine.begin() as c:                  # o desfazer da importação (resumido aqui)
        c.execute(text("UPDATE resultados_avaliacao SET valor = :v, motivo_ausencia = NULL, "
                       "importacao_id = NULL WHERE importacao_id = :i"), {"v": 187.0, "i": imp})
        c.execute(text("UPDATE importacoes_indicador SET status = :s WHERE id = :i"),
                  {"s": "desfeita", "i": imp})
    _migrar(engine, REVISAO_0034, subir=False)
    with engine.connect() as c:
        assert c.execute(text("SELECT valor FROM resultados_avaliacao r JOIN avaliacoes_externas "
                              "a ON a.id = r.avaliacao_id WHERE a.chave = :a AND "
                              "r.componente = :c"), {"a": "saresp", "c": "portugues"}
                         ).scalar_one() == 187.0


def test_0035_downgrade_nao_perde_numero_sem_registro_no_sqlite(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'downgrade_0035.db'}")
    try:
        _conferir_downgrade_0035_nao_perde_numero_sem_registro(engine, _banco_na_0034(engine))
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_0035_downgrade_nao_perde_numero_sem_registro_no_postgres(engine_postgres):
    _conferir_downgrade_0035_nao_perde_numero_sem_registro(
        engine_postgres, _banco_na_0034(engine_postgres))


def _conferir_downgrade_0035_em_cadeia(engine, ids: dict, sem_coluna: bool) -> None:
    """EM CADEIA: a #1 trocou a média calculada (187,0, sem ``importacao_id``) pelo
    oficial (190,0) e a #2 — um arquivo retificado da mesma edição — trocou o oficial
    por ausência. O ANTES da #2 é a #1; o 187,0 só existe no plano da #1, que some com a
    0034: o downgrade PARA e aponta a #2 (desfeita ela, a linha volta a ter número).
    ``sem_coluna``: banco local que aplicou a 0034 antes da coluna ``desfazer`` existir
    (o plano em ``resumo['desfazer']``) — a conferência lê o plano de lá, e a recusa diz
    para criar a coluna antes de desfazer (sem ela o app não lista nem desfaz): o teste
    segue o reparo da 0034 (``ADD COLUMN desfazer JSON``) e o downgrade passa depois."""
    _migrar(engine, REVISAO_0035)
    if sem_coluna:
        with engine.begin() as c:
            c.execute(text("ALTER TABLE importacoes_indicador DROP COLUMN desfazer"))
    chave = {"alvo": "esc", "avaliacao_id": ids["av"]["saresp"], "edicao": 2025,
             "indicador": "proficiencia", "escola_id": ids["e1"], "etapa": "5_ano",
             "componente": "portugues", "turma": None}

    def estado(valor, importacao_id, fonte="oficial"):
        return {"valor": valor, "unidade": "u",
                "motivo_ausencia": None if valor is not None else "nao_divulgado",
                "fonte": fonte, "importacao_id": importacao_id, "codigo_inep": None,
                "rede_id": None}

    def importacao(c, meta, antes, depois) -> int:
        plano = {"criadas": [], "chaves": [chave],
                 "alteradas": [{"chave": chave, "antes": antes, "depois": depois}]}
        guardado = {"resumo": {"desfazer": plano}} if sem_coluna else {
            "resumo": {}, "desfazer": plano}
        return _inserir(c, meta, "importacoes_indicador", avaliacao_id=ids["av"]["saresp"],
                        status="aplicada", contadores={}, **guardado)

    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        imp1 = importacao(c, meta, estado(187.0, None, "calculado"), estado(190.0, 0))
        imp2 = importacao(c, meta, estado(190.0, imp1), estado(None, 0))
        c.execute(text("UPDATE resultados_avaliacao SET valor = NULL, motivo_ausencia = :m, "
                       "importacao_id = :i WHERE avaliacao_id = :a AND componente = :c"),
                  {"m": "nao_divulgado", "i": imp2, "a": ids["av"]["saresp"], "c": "portugues"})
    with pytest.raises(RuntimeError, match=rf"0035 \(downgrade\).*#{imp2} \(1 número") as recusa:
        _migrar(engine, REVISAO_0034, subir=False)
    reparo = "ALTER TABLE importacoes_indicador ADD COLUMN desfazer JSON"
    if sem_coluna:      # mandar só "desfaça" seria beco sem saída: o app não desfaz sem a coluna
        assert reparo in str(recusa.value)
    else:
        assert reparo not in str(recusa.value) and "Desfaça antes" in str(recusa.value)
    with engine.connect() as c:
        assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))} == {
            REVISAO_0035}
    if sem_coluna:
        with engine.begin() as c:              # o reparo da 0034: a coluna nula, plano no resumo
            c.execute(text(reparo))
    with engine.begin() as c:                  # o desfazer da #2 (resumido): volta o oficial
        c.execute(text("UPDATE resultados_avaliacao SET valor = :v, motivo_ausencia = NULL, "
                       "importacao_id = :i1 WHERE importacao_id = :i2"),
                  {"v": 190.0, "i1": imp1, "i2": imp2})
        c.execute(text("UPDATE importacoes_indicador SET status = :s WHERE id = :i"),
                  {"s": "desfeita", "i": imp2})
    _migrar(engine, REVISAO_0034, subir=False)
    with engine.connect() as c:
        assert c.execute(text("SELECT valor FROM resultados_avaliacao r JOIN avaliacoes_externas "
                              "a ON a.id = r.avaliacao_id WHERE a.chave = :a AND "
                              "r.componente = :c"), {"a": "saresp", "c": "portugues"}
                         ).scalar_one() == 190.0


@pytest.mark.parametrize("sem_coluna", [False, True], ids=["coluna", "plano_no_resumo"])
def test_0035_downgrade_nao_perde_numero_em_cadeia_no_sqlite(tmp_path, sem_coluna):
    engine = create_engine(f"sqlite:///{tmp_path / 'downgrade_cadeia_0035.db'}")
    try:
        _conferir_downgrade_0035_em_cadeia(engine, _banco_na_0034(engine), sem_coluna)
    finally:
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.parametrize("sem_coluna", [False, True], ids=["coluna", "plano_no_resumo"])
def test_0035_downgrade_nao_perde_numero_em_cadeia_no_postgres(engine_postgres, sem_coluna):
    _conferir_downgrade_0035_em_cadeia(engine_postgres, _banco_na_0034(engine_postgres),
                                       sem_coluna)


@pytest.mark.postgres
def test_0034_0035_falham_rapido_sem_esperar_lock_no_postgres(engine_postgres):
    """``lock_timeout``: com um leitor segurando ``resultados_avaliacao`` (ex.: o pg_dump
    do backup), a 0035 não espera sem prazo pelo ACCESS EXCLUSIVE do DROP INDEX —
    enquanto seguraria as FKs da 0034 em ``usuarios`` (login, heartbeat): falha em
    segundos e reverte TUDO, a 0034 junto (uma transação só)."""
    _banco_na_0033(engine_postgres)
    leitor = engine_postgres.connect()
    try:
        leitor.execute(text("SELECT count(*) FROM resultados_avaliacao")).scalar_one()
        inicio = time.monotonic()
        with pytest.raises(DBAPIError, match="lock timeout"):
            _migrar(engine_postgres, REVISAO_0035)
        assert time.monotonic() - inicio < 60
    finally:
        leitor.rollback()
        leitor.close()
    assert "importacoes_indicador" not in inspect(engine_postgres).get_table_names()
    with engine_postgres.connect() as c:
        assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))} == {
            REVISAO_0033}
        # O SET LOCAL morre com a transação: a sessão seguinte volta ao padrão.
        assert c.execute(text("SHOW lock_timeout")).scalar_one() in ("0", "0ms")
    _migrar(engine_postgres, REVISAO_0035)                  # sem o leitor, sobe


# ---------------------------------------------------------------------------
# 7) Descida da 0034 × catálogo: 'ica' e 'iee' saem SÓ quando nada aponta para
#    elas (decisão do dono, 18/10). SQLite e PostgreSQL; textos e números INVENTADOS.
# ---------------------------------------------------------------------------

# As seis avaliações do catálogo ANTES dos indicadores oficiais (o CATALOGO do f69c5ac).
_ORIGINAIS = ("saeb", "ideb", "saresp", "crianca_alfabetizada", "caed_fluencia",
              "caed_diagnostica")
_DA_ETAPA = ("ica", "iee")
_FKS_NA_0033 = [("fontes_avaliacao", "avaliacao_id"), ("resultados_avaliacao", "avaliacao_id")]
_FKS_NA_0035 = sorted(_FKS_NA_0033 + [("importacoes_indicador", "avaliacao_id"),
                                      ("indicadores_referencia", "avaliacao_id")])
_LOG_REMOVIDAS = "removida(s) do catálogo avaliacoes_externas, sem nenhum vínculo"


def _migracao_0034():
    """O módulo da 0034, para chamar as funções da descida direto."""
    spec = importlib.util.spec_from_file_location(
        "migracao_0034_em_teste", VERSOES / "0034_indicadores_referencia.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _estavel(valor):
    """JSON (texto no SQLite, objeto no PostgreSQL) vira texto canônico; o resto fica
    exatamente como o driver devolveu (texto e data comparados byte a byte)."""
    if isinstance(valor, str) and valor[:1] in "{[":
        try:
            valor = json.loads(valor)
        except ValueError:
            return valor
    if isinstance(valor, (dict, list)):
        return json.dumps(valor, sort_keys=True, ensure_ascii=False)
    return valor


def _retrato(engine, tabela: str, colunas: list[str], campo: str | None = None,
             valores=None) -> list[tuple]:
    """Linhas da tabela (só as ``colunas``, as do schema da 0033) em ordem de id; com
    ``campo``, só as linhas com ``campo`` em ``valores``."""
    sql = f"SELECT {', '.join(colunas)} FROM {tabela}"
    consulta = text(sql + " ORDER BY id")
    params = {}
    if campo:
        consulta = text(f"{sql} WHERE {campo} IN :valores ORDER BY id").bindparams(
            bindparam("valores", expanding=True))
        params = {"valores": list(valores)}
    with engine.connect() as c:
        return [tuple(_estavel(v) for v in linha) for linha in c.execute(consulta, params)]


def _hash(retrato: list[tuple]) -> str:
    return hashlib.sha256(repr(retrato).encode("utf-8")).hexdigest()


def _retratos(engine, colunas: dict) -> dict:
    """As seis avaliações originais, todos os resultados e todas as receitas do robô."""
    return {"catalogo": _retrato(engine, "avaliacoes_externas", colunas["avaliacoes_externas"],
                                 "chave", _ORIGINAIS),
            "resultados": _retrato(engine, "resultados_avaliacao",
                                   colunas["resultados_avaliacao"]),
            "fontes": _retrato(engine, "fontes_avaliacao", colunas["fontes_avaliacao"])}


def _banco_com_catalogo_na_0033(engine) -> dict:
    """Estado de produção antes dos indicadores oficiais: as seis avaliações do catálogo
    antigo (com acento e microssegundo, para a comparação byte a byte valer), resultados
    de todas (inclusive um ZERO, que não é ausência) e duas receitas do robô."""
    _migrar(engine, REVISAO_0033)
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        av = {}
        for i, chave in enumerate(_ORIGINAIS):
            av[chave] = _inserir(
                c, meta, "avaliacoes_externas", chave=chave,
                nome=f"Avaliação fictícia {i} — {chave.upper()} (índice, ação)",
                tipo="indicador" if chave == "ideb" else "avaliacao",
                orgao=None if i % 2 else f"Órgão Inventado {i}",
                descricao=(_DESCRICAO_SARESP_ANTIGA if chave == "saresp"
                           else f"Descrição inventada nº {i}: não é dado real."),
                created_at=datetime(2031, 5, 5, 10, i, 7, 123456 + i))
        e1 = _inserir(c, meta, "escolas", nome="Escola Fictícia Um", ano_letivo_ativo=2026,
                      codigo_inep="35999901")
        e2 = _inserir(c, meta, "escolas", nome="Escola Fictícia Dois", ano_letivo_ativo=2026,
                      codigo_inep="35999902")
        rede = _inserir(c, meta, "redes", nome="Rede Fictícia", status="ativa")
        for chave, edicao, escola, indicador, etapa, comp, turma, valor in (
                ("saeb", 2023, e1, "proficiencia", "anos_iniciais", "matematica", None, 211.0),
                ("saeb", 2023, e1, "proficiencia", "anos_iniciais", "portugues", None, 203.0),
                ("ideb", 2023, e1, "ideb", "anos_iniciais", None, None, 5.8),
                ("saresp", 2025, e1, "proficiencia", "anos_iniciais", "portugues", None, 187.0),
                ("saresp", 2025, e2, "proficiencia", "2_ano", "portugues", None, 197.0),
                ("crianca_alfabetizada", 2025, e1, "taxa_alfabetizacao", "2_ano", None, None,
                 93.0),
                ("caed_fluencia", 2026, e2, "fluencia", None, None, "5ºA", 150.5),
                ("caed_diagnostica", 2026, e2, "acertos", None, "matematica", None, 0.0)):
            _inserir(c, meta, "resultados_avaliacao", avaliacao_id=av[chave], edicao=edicao,
                     rede_id=rede, escola_id=escola, etapa=etapa, componente=comp,
                     turma=turma, indicador=indicador, valor=valor, unidade="u",
                     fonte=f"arquivo inventado ({chave})",
                     created_at=datetime(2031, 5, 5, 11, 0, 0, 654321))
        for nome, chave, etapa in (("robo_saeb", "saeb", "anos_iniciais"),
                                   ("robo_caed", "caed_fluencia", None)):
            _inserir(c, meta, "fontes_avaliacao", avaliacao_id=av[chave], nome=nome,
                     url="https://exemplo.invalido/inventado.csv", edicao=2023,
                     indicador="proficiencia", unidade="u", cadencia="manual", ativo=False,
                     ultimo_status="nunca", created_at=datetime(2031, 5, 5, 12, 0, 0),
                     mapeamento={"linha_dados": 1, "col_inep": 0, "col_valor": 1,
                                 "etapa_fixa": etapa})
    insp = inspect(engine)
    colunas = {t: [col["name"] for col in insp.get_columns(t)]
               for t in ("avaliacoes_externas", "resultados_avaliacao", "fontes_avaliacao")}
    retrato = _retratos(engine, colunas)
    assert [len(retrato[n]) for n in ("catalogo", "resultados", "fontes")] == [6, 8, 2]
    return {"av": av, "e1": e1, "e2": e2, "rede": rede, "colunas": colunas,
            "tabelas": set(insp.get_table_names()), "retrato": retrato,
            "hash": {n: _hash(r) for n, r in retrato.items()}}


def _ids_da_etapa(engine) -> dict[str, int]:
    with engine.connect() as c:
        return dict(c.execute(text(
            "SELECT chave, id FROM avaliacoes_externas WHERE chave IN :chaves").bindparams(
            bindparam("chaves", expanding=True)), {"chaves": list(_DA_ETAPA)}).all())


def _subir_com_ica_iee_do_codigo_novo(engine) -> dict[str, int]:
    """Sobe até a 0035 e cria 'ica' e 'iee' como o código novo as cria: a
    ``obter_avaliacao`` de verdade, que a prévia do ICA e a do SARESP/IEE chamam (o GET
    /avaliacoes não as cria: ver ``_conferir_get_do_codigo_novo_nao_recria``)."""
    _migrar(engine, REVISAO_0035)
    with Session(engine) as db:
        for chave in svc_avaliacoes.CATALOGO:
            svc_avaliacoes.obter_avaliacao(db, chave)
        db.commit()
    ids = _ids_da_etapa(engine)
    assert set(ids) == set(_DA_ETAPA)
    return ids


def _importacoes_desfeitas(engine, ids: dict[str, int]) -> None:
    """O histórico que fica depois do N1: uma importação DESFEITA de cada (o desfazer já
    tirou os números de ``indicadores_referencia``)."""
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        for chave, avaliacao_id in ids.items():
            _inserir(c, meta, "importacoes_indicador", avaliacao_id=avaliacao_id,
                     parser=f"{chave}_inventado", status="desfeita", contadores={"novas": 2},
                     resumo={"avisos": []}, desfazer={"criadas": [], "alteradas": []},
                     desfeito_em=datetime(2031, 5, 6, 20, 0))


def _descer_ate_a_0033(engine, capfd) -> str:
    """Desce pelo Alembic (o comando do N3) e devolve o log dele (stderr)."""
    capfd.readouterr()
    _migrar(engine, REVISAO_0033, subir=False)
    return capfd.readouterr().err


def _conferir_como_na_0033(engine, base: dict) -> None:
    """Catálogo, resultados e receitas idênticos aos de antes de subir (byte a byte,
    contagem e hash), sem 'ica'/'iee', com as tabelas e a versão da 0033."""
    assert _ids_da_etapa(engine) == {}
    assert set(inspect(engine).get_table_names()) == base["tabelas"]
    depois = _retratos(engine, base["colunas"])
    for nome in ("catalogo", "resultados", "fontes"):
        assert len(depois[nome]) == len(base["retrato"][nome]), nome
        assert depois[nome] == base["retrato"][nome], nome
        assert _hash(depois[nome]) == base["hash"][nome], nome
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM avaliacoes_externas")).scalar_one() == 6
        assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))} == {
            REVISAO_0033}


def _conferir_fks_para_o_catalogo(engine, base: dict, capfd) -> None:
    """Inventário lido do banco: na 0033 só ``resultados_avaliacao`` e
    ``fontes_avaliacao`` apontam para o catálogo; na 0035, mais as duas tabelas da 0034.
    As quatro com ON DELETE CASCADE — é por isso que a descida confere antes de apagar."""
    mod = _migracao_0034()
    with engine.connect() as c:
        assert mod.referencias_ao_catalogo(c) == _FKS_NA_0033
        assert mod.vinculos_que_a_contagem_nao_cobre(c, _FKS_NA_0033) == []
    _migrar(engine, REVISAO_0035)
    with engine.connect() as c:
        assert mod.referencias_ao_catalogo(c) == _FKS_NA_0035
        assert mod.vinculos_que_a_contagem_nao_cobre(c, _FKS_NA_0035) == []
    insp = inspect(engine)
    for tabela, _ in _FKS_NA_0035:
        ondelete = [(fk.get("options") or {}).get("ondelete")
                    for fk in insp.get_foreign_keys(tabela)
                    if fk["referred_table"] == "avaliacoes_externas"]
        assert ondelete == ["CASCADE"], tabela
    _migrar(engine, REVISAO_0033, subir=False)
    _conferir_como_na_0033(engine, base)


def _conferir_descida_remove_ica_iee_sem_vinculo(engine, base: dict, capfd) -> None:
    """(1) Desfeitas as importações, a descida até a 0033 remove 'ica' e 'iee' e deixa
    as seis avaliações originais byte a byte iguais, e os resultados e as receitas
    delas intactos (contagem e hash)."""
    ids = _subir_com_ica_iee_do_codigo_novo(engine)
    _importacoes_desfeitas(engine, ids)
    log = _descer_ate_a_0033(engine, capfd)
    assert f"{_LOG_REMOVIDAS}: ica, iee." in log
    assert "FICOU" not in log and "FICARAM" not in log
    _conferir_como_na_0033(engine, base)


def _conferir_descida_com_importacao_aplicada(engine, base: dict, capfd) -> None:
    """Coerência com as tabelas que a própria 0034 remove: os números de uma importação
    APLICADA (não desfeita) do ICA/IEE ficam só em ``indicadores_referencia``. A descida da
    0035 NÃO recusa por isso (só pela ausência que esconde a média calculada), esses
    números saem com a tabela — como já era — e, sem outro vínculo, 'ica' e 'iee' saem do
    catálogo. O N3 manda desfazer antes: senão esses números só voltam reimportando."""
    ids = _subir_com_ica_iee_do_codigo_novo(engine)
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        for chave, avaliacao_id in ids.items():
            imp = _inserir(c, meta, "importacoes_indicador", avaliacao_id=avaliacao_id,
                           parser=f"{chave}_inventado", status="aplicada", contadores={},
                           resumo={}, desfazer={"criadas": [], "alteradas": []})
            _linha_referencia(c, meta, avaliacao_id, imp, indicador=f"{chave}_inventado")
    log = _descer_ate_a_0033(engine, capfd)
    assert f"{_LOG_REMOVIDAS}: ica, iee." in log
    _conferir_como_na_0033(engine, base)


def _conferir_resultado_manual_segura_a_ica(engine, base: dict, capfd) -> None:
    """(2) Um resultado gravado à mão na 'ica' (na tabela da escola, sem importação): a
    descida MANTÉM a 'ica' (a mesma linha, byte a byte), não apaga nenhum resultado —
    o CASCADE levaria este — e remove a 'iee', que está livre."""
    ids = _subir_com_ica_iee_do_codigo_novo(engine)
    _importacoes_desfeitas(engine, ids)
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        manual = _inserir(c, meta, "resultados_avaliacao", avaliacao_id=ids["ica"],
                          edicao=2024, rede_id=base["rede"], escola_id=base["e1"],
                          indicador="taxa_inventada", valor=1.0, unidade="percentual",
                          fonte="digitado à mão (inventado)",
                          created_at=datetime(2031, 5, 6, 9, 30, 0, 1))
    cols = base["colunas"]
    ica_antes = _retrato(engine, "avaliacoes_externas", cols["avaliacoes_externas"],
                         "chave", ["ica"])
    esperado = base["retrato"]["resultados"] + _retrato(
        engine, "resultados_avaliacao", cols["resultados_avaliacao"], "id", [manual])
    log = _descer_ate_a_0033(engine, capfd)
    assert ("a linha 'ica' do catálogo avaliacoes_externas FICOU: 1 linha(s) de "
            "resultados_avaliacao.avaliacao_id apontam para ela") in log
    assert f"{_LOG_REMOVIDAS}: iee." in log
    assert _ids_da_etapa(engine) == {"ica": ids["ica"]}
    assert _retrato(engine, "avaliacoes_externas", cols["avaliacoes_externas"],
                    "chave", ["ica"]) == ica_antes
    depois = _retratos(engine, cols)
    assert len(depois["resultados"]) == len(esperado) == 9
    assert depois["resultados"] == esperado and _hash(depois["resultados"]) == _hash(esperado)
    assert depois["catalogo"] == base["retrato"]["catalogo"]
    assert depois["fontes"] == base["retrato"]["fontes"]
    # Quem chama a função recebe a lista (aqui direto, já na 0033); e de novo não apaga.
    with engine.begin() as c:
        assert _migracao_0034().remover_linhas_sem_vinculo_do_catalogo(c) == {
            "removidas": [], "mantidas": ["ica"]}
    assert _retratos(engine, cols)["resultados"] == esperado


def _conferir_fonte_do_robo_segura_a_iee(engine, base: dict, capfd) -> None:
    """(3) Uma receita do robô na 'iee': a descida MANTÉM a 'iee', não apaga nenhuma
    receita nem resultado e remove a 'ica', que está livre."""
    ids = _subir_com_ica_iee_do_codigo_novo(engine)
    _importacoes_desfeitas(engine, ids)
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        fonte = _inserir(c, meta, "fontes_avaliacao", avaliacao_id=ids["iee"],
                         nome="robo_iee_inventado", url="https://exemplo.invalido/iee.csv",
                         edicao=2025, indicador="iee", unidade="indice", cadencia="manual",
                         ativo=False, ultimo_status="nunca",
                         created_at=datetime(2031, 5, 6, 9, 45, 0, 2),
                         mapeamento={"linha_dados": 2, "col_inep": 0, "col_valor": 3})
    cols = base["colunas"]
    iee_antes = _retrato(engine, "avaliacoes_externas", cols["avaliacoes_externas"],
                         "chave", ["iee"])
    esperado = base["retrato"]["fontes"] + _retrato(
        engine, "fontes_avaliacao", cols["fontes_avaliacao"], "id", [fonte])
    log = _descer_ate_a_0033(engine, capfd)
    assert ("a linha 'iee' do catálogo avaliacoes_externas FICOU: 1 linha(s) de "
            "fontes_avaliacao.avaliacao_id apontam para ela") in log
    assert f"{_LOG_REMOVIDAS}: ica." in log
    assert _ids_da_etapa(engine) == {"iee": ids["iee"]}
    assert _retrato(engine, "avaliacoes_externas", cols["avaliacoes_externas"],
                    "chave", ["iee"]) == iee_antes
    depois = _retratos(engine, cols)
    assert len(depois["fontes"]) == len(esperado) == 3
    assert depois["fontes"] == esperado and _hash(depois["fontes"]) == _hash(esperado)
    assert depois["resultados"] == base["retrato"]["resultados"]
    assert depois["catalogo"] == base["retrato"]["catalogo"]


def _conferir_sobe_e_desce_de_novo(engine, base: dict, capfd) -> None:
    """(4) Idempotência: descer, subir (o código novo recria 'ica'/'iee' sob demanda) e
    descer de novo dá o mesmo resultado; subir pelo caminho de produção até as heads,
    duas vezes, não recria as linhas (nenhuma migração as cria)."""
    _conferir_descida_remove_ica_iee_sem_vinculo(engine, base, capfd)
    ids = _subir_com_ica_iee_do_codigo_novo(engine)
    _importacoes_desfeitas(engine, ids)
    log = _descer_ate_a_0033(engine, capfd)
    assert f"{_LOG_REMOVIDAS}: ica, iee." in log
    _conferir_como_na_0033(engine, base)
    aplicar_migracoes(engine)
    aplicar_migracoes(engine)
    heads = set(ScriptDirectory.from_config(_config()).get_heads())
    with engine.connect() as c:
        assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))} == heads
        assert c.execute(text("SELECT count(*) FROM avaliacoes_externas")).scalar_one() == 6
    assert _ids_da_etapa(engine) == {}


def _conferir_catalogo_sem_ica_iee(engine, base: dict, capfd) -> None:
    """(5) Instalação que subiu e nunca importou o ICA nem o IEE (sem 'ica'/'iee'): a
    descida passa sem erro e sem aviso, e nada muda."""
    _migrar(engine, REVISAO_0035)
    assert _ids_da_etapa(engine) == {}
    log = _descer_ate_a_0033(engine, capfd)
    assert "removida(s) do catálogo" not in log and "FICOU" not in log
    assert "FICARAM" not in log
    _conferir_como_na_0033(engine, base)
    with engine.begin() as c:
        assert _migracao_0034().remover_linhas_sem_vinculo_do_catalogo(c) == {
            "removidas": [], "mantidas": []}


def _ica_avulsa(engine, base: dict, com_resultado: bool) -> dict[str, int]:
    """Na 0033: uma linha 'ica' que sobrou no catálogo e, se pedido, um resultado nela."""
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        ids = {"ica": _inserir(c, meta, "avaliacoes_externas", chave="ica",
                               nome="ICA inventado", tipo="indicador",
                               created_at=datetime(2031, 5, 6, 8, 0))}
        if com_resultado:
            ids["resultado"] = _inserir(
                c, meta, "resultados_avaliacao", avaliacao_id=ids["ica"], edicao=2024,
                escola_id=base["e2"], indicador="taxa_inventada", valor=1.0,
                unidade="percentual", created_at=datetime(2031, 5, 6, 8, 1))
    return ids


def _conferir_conferencia_final_reverte(engine, base: dict, capfd) -> None:
    """Defensivo: se a contagem por id errasse (simulado: as contagens por id da única
    linha respondem 0), o DELETE levaria o resultado em cascata (PostgreSQL) ou o
    deixaria órfão (SQLite das migrações, ``foreign_keys=OFF``). A conferência final
    PARA e a transação reverte: a 'ica' e o resultado continuam lá, iguais."""
    ids = _ica_avulsa(engine, base, com_resultado=True)
    cols = base["colunas"]["resultados_avaliacao"]
    antes = _retrato(engine, "resultados_avaliacao", cols)
    assert len(antes) == 9
    mod = _migracao_0034()
    original, cegas = mod._contar, {"n": len(_FKS_NA_0033)}

    def contar_cego(bind, tabela, coluna=None, ids_=None):
        if ids_ is not None and cegas["n"]:
            cegas["n"] -= 1
            return 0
        return original(bind, tabela, coluna, ids_)

    mod._contar = contar_cego                 # só neste módulo carregado aqui
    sinal = ("'resultados_avaliacao': (9, 8)" if engine.dialect.name == "postgresql"
             else "'resultados_avaliacao.avaliacao_id': 1")
    with pytest.raises(RuntimeError, match=r"0034 \(downgrade\): remover \['ica'\]") as erro:
        with engine.begin() as c:
            mod.remover_linhas_sem_vinculo_do_catalogo(c)
    assert sinal in str(erro.value)
    assert _ids_da_etapa(engine) == {"ica": ids["ica"]}
    assert _retrato(engine, "resultados_avaliacao", cols) == antes


def _conferir_descida_parcial(engine, base: dict, capfd) -> None:
    """Descer só até a 0034 não mexe no catálogo (a 0035 não o toca); de lá até a 0033,
    'ica' e 'iee' saem e o resto fica como antes."""
    ids = _subir_com_ica_iee_do_codigo_novo(engine)
    _importacoes_desfeitas(engine, ids)
    capfd.readouterr()
    _migrar(engine, REVISAO_0034, subir=False)
    assert "do catálogo" not in capfd.readouterr().err
    assert _ids_da_etapa(engine) == ids
    log = _descer_ate_a_0033(engine, capfd)
    assert f"{_LOG_REMOVIDAS}: ica, iee." in log
    _conferir_como_na_0033(engine, base)


def _conferir_get_do_codigo_novo_nao_recria(engine, base: dict, capfd) -> None:
    """O GET /avaliacoes do código novo (a rota de verdade) NÃO cria 'ica' nem 'iee': nem
    na 0035 (instalação que ainda não importou o ICA nem o IEE), nem na 0033, depois da
    descida, com o código novo ainda no ar (entre o passo 2 e o 3 do N3). Se criasse, o
    seletor do código antigo as mostraria, e descer de novo não as tiraria (o banco já
    está na 0033: a 0034 não roda). A resposta traz as seis originais."""
    from app.routers.avaliacoes import catalogo as get_catalogo

    def abrir_o_catalogo() -> set[str]:
        with Session(engine) as db:
            return {item["chave"] for item in get_catalogo(usuario=None, db=db)}

    _migrar(engine, REVISAO_0035)
    assert abrir_o_catalogo() == set(_ORIGINAIS)
    assert _ids_da_etapa(engine) == {}
    ids = _subir_com_ica_iee_do_codigo_novo(engine)
    assert abrir_o_catalogo() == set(_ORIGINAIS)          # existem, mas fora da resposta
    _importacoes_desfeitas(engine, ids)
    log = _descer_ate_a_0033(engine, capfd)
    assert f"{_LOG_REMOVIDAS}: ica, iee." in log
    assert abrir_o_catalogo() == set(_ORIGINAIS)
    _conferir_como_na_0033(engine, base)


def _conferir_fk_para_outra_coluna_segura_o_catalogo(engine, base: dict, capfd) -> None:
    """Uma FK para OUTRA coluna do catálogo (a ``chave``, que tem índice único) não entra
    na contagem por id: a descida não remove NADA do catálogo e avisa. Sem isso, o
    CASCADE do PostgreSQL levaria a linha dela, e no SQLite ela ficaria órfã."""
    ids = _subir_com_ica_iee_do_codigo_novo(engine)
    _importacoes_desfeitas(engine, ids)
    with engine.begin() as c:
        c.execute(text(
            "CREATE TABLE vinculo_por_chave_inventado (id INTEGER PRIMARY KEY, "
            "avaliacao_chave VARCHAR(40) NOT NULL "
            "REFERENCES avaliacoes_externas(chave) ON DELETE CASCADE)"))
        c.execute(text("INSERT INTO vinculo_por_chave_inventado (id, avaliacao_chave) "
                       "VALUES (7, 'ica')"))
    log = _descer_ate_a_0033(engine, capfd)
    assert ("'ica', 'iee' do catálogo avaliacoes_externas FICARAM: há vínculo com o "
            "catálogo que esta descida não sabe contar (vinculo_por_chave_inventado."
            "avaliacao_chave -> avaliacoes_externas.chave)") in log
    assert "removida(s) do catálogo" not in log
    assert _ids_da_etapa(engine) == ids
    with engine.connect() as c:
        assert c.execute(text(
            "SELECT id, avaliacao_chave FROM vinculo_por_chave_inventado")).all() == [(7, "ica")]
        assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))} == {
            REVISAO_0033}
    assert _retratos(engine, base["colunas"]) == base["retrato"]
    with engine.begin() as c:
        assert _migracao_0034().remover_linhas_sem_vinculo_do_catalogo(c) == {
            "removidas": [], "mantidas": ["ica", "iee"]}


def _conferir_descida_inteira_reverte(engine, base: dict, capfd) -> None:
    """Um vínculo escondido (um gatilho inventado que, ao apagar uma linha do catálogo,
    apaga uma receita do robô) faz a conferência final PARAR a descida, e a transação
    INTEIRA volta: a versão 0035, as tabelas da 0034, as colunas da 0035, a ausência e a
    etapa 5_ano (que a descida da 0035 apaga e troca antes), 'ica', 'iee' e a receita."""
    ids = _subir_com_ica_iee_do_codigo_novo(engine)
    _importacoes_desfeitas(engine, ids)
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        _inserir(c, meta, "resultados_avaliacao", avaliacao_id=base["av"]["saresp"],
                 edicao=2030, escola_id=base["e2"], indicador="proficiencia",
                 etapa="5_ano", componente="matematica", valor=None,
                 motivo_ausencia="nao_divulgado", unidade="u",
                 created_at=datetime(2031, 5, 6, 9, 1))
        if engine.dialect.name == "postgresql":
            c.execute(text(
                "CREATE FUNCTION gatilho_inventado_apaga_receita() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN "
                "DELETE FROM fontes_avaliacao WHERE nome = 'robo_saeb'; RETURN OLD; END $$"))
            c.execute(text(
                "CREATE TRIGGER gatilho_inventado AFTER DELETE ON avaliacoes_externas "
                "FOR EACH ROW EXECUTE FUNCTION gatilho_inventado_apaga_receita()"))
        else:
            c.execute(text(
                "CREATE TRIGGER gatilho_inventado AFTER DELETE ON avaliacoes_externas "
                "BEGIN DELETE FROM fontes_avaliacao WHERE nome = 'robo_saeb'; END"))

    def estado() -> dict:
        insp = inspect(engine)
        with engine.connect() as c:
            return {
                "versao": {r[0] for r in c.execute(text(
                    "SELECT version_num FROM alembic_version"))},
                "tabelas": set(insp.get_table_names()),
                "colunas": {col["name"] for col in insp.get_columns("resultados_avaliacao")},
                "resultados": c.execute(text(
                    "SELECT id, avaliacao_id, etapa, valor, motivo_ausencia "
                    "FROM resultados_avaliacao ORDER BY id")).all(),
                "fontes": c.execute(text(
                    "SELECT id, nome FROM fontes_avaliacao ORDER BY id")).all(),
                "importacoes": c.execute(text(
                    "SELECT count(*) FROM importacoes_indicador")).scalar_one(),
                "da_etapa": _ids_da_etapa(engine)}

    antes = estado()
    assert antes["versao"] == {REVISAO_0035}
    assert {"motivo_ausencia", "importacao_id"} <= antes["colunas"]
    assert len(antes["fontes"]) == 2 and antes["importacoes"] == 2
    capfd.readouterr()
    with pytest.raises(RuntimeError, match=r"0034 \(downgrade\): remover \['ica', 'iee'\] "
                                           r"do catálogo apagaria linhas") as erro:
        _migrar(engine, REVISAO_0033, subir=False)
    assert "'fontes_avaliacao': (2, 1)" in str(erro.value)
    assert _LOG_REMOVIDAS not in capfd.readouterr().err
    assert estado() == antes


_CENARIOS_CATALOGO = [_conferir_fks_para_o_catalogo,
                      _conferir_descida_remove_ica_iee_sem_vinculo,
                      _conferir_descida_com_importacao_aplicada,
                      _conferir_resultado_manual_segura_a_ica,
                      _conferir_fonte_do_robo_segura_a_iee,
                      _conferir_sobe_e_desce_de_novo,
                      _conferir_catalogo_sem_ica_iee,
                      _conferir_conferencia_final_reverte,
                      _conferir_descida_parcial,
                      _conferir_get_do_codigo_novo_nao_recria,
                      _conferir_fk_para_outra_coluna_segura_o_catalogo,
                      _conferir_descida_inteira_reverte]


def _nome_do_cenario(cenario) -> str:
    return cenario.__name__.removeprefix("_conferir_")


@pytest.mark.parametrize("cenario", _CENARIOS_CATALOGO, ids=_nome_do_cenario)
def test_0034_descida_e_o_catalogo_no_sqlite(tmp_path, capfd, cenario):
    engine = create_engine(f"sqlite:///{tmp_path / 'catalogo_0034.db'}")
    try:
        cenario(engine, _banco_com_catalogo_na_0033(engine), capfd)
    finally:
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.parametrize("cenario", _CENARIOS_CATALOGO, ids=_nome_do_cenario)
def test_0034_descida_e_o_catalogo_no_postgres(engine_postgres, capfd, cenario):
    cenario(engine_postgres, _banco_com_catalogo_na_0033(engine_postgres), capfd)


@pytest.mark.postgres
def test_0034_descida_nao_apaga_por_baixo_de_quem_grava_no_postgres(engine_postgres, capfd):
    """Concorrência (só o PostgreSQL tem CASCADE de verdade e escritores simultâneos):
    uma transação ABERTA gravando uma receita do robô na 'iee' segura o catálogo (a
    checagem da FK). A descida espera no máximo o ``lock_timeout``, falha e reverte
    TUDO — nunca apaga a 'iee' por baixo da receita, o que o CASCADE levaria junto.
    Confirmada a receita, a descida seguinte mantém a 'iee' e remove a 'ica'. (No
    PostgreSQL 17 a espera acontece já no ``DROP TABLE indicadores_referencia``, que
    pede ACCESS EXCLUSIVE no catálogo; a trava da própria remoção é provada à parte.)"""
    base = _banco_com_catalogo_na_0033(engine_postgres)
    ids = _subir_com_ica_iee_do_codigo_novo(engine_postgres)
    _importacoes_desfeitas(engine_postgres, ids)
    meta = MetaData()
    with engine_postgres.connect() as c:
        meta.reflect(bind=c)
    gravador = engine_postgres.connect()
    try:
        _inserir(gravador, meta, "fontes_avaliacao", avaliacao_id=ids["iee"],
                 nome="robo_iee_concorrente", url="https://exemplo.invalido/iee.csv",
                 edicao=2025, indicador="iee", unidade="indice", cadencia="manual",
                 ativo=False, ultimo_status="nunca", mapeamento={})        # sem commit
        inicio = time.monotonic()
        with pytest.raises(DBAPIError, match="lock timeout") as erro:
            _migrar(engine_postgres, REVISAO_0033, subir=False)
        assert time.monotonic() - inicio < 60
        assert erro.value.statement
        gravador.commit()
    finally:
        gravador.close()
    with engine_postgres.connect() as c:
        assert {r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))} == {
            REVISAO_0035}                                               # nada mexido
    assert _ids_da_etapa(engine_postgres) == ids
    log = _descer_ate_a_0033(engine_postgres, capfd)
    assert "a linha 'iee' do catálogo avaliacoes_externas FICOU" in log
    assert f"{_LOG_REMOVIDAS}: ica." in log
    assert _ids_da_etapa(engine_postgres) == {"iee": ids["iee"]}
    depois = _retratos(engine_postgres, base["colunas"])
    assert len(depois["fontes"]) == 3
    assert depois["resultados"] == base["retrato"]["resultados"]
    assert depois["catalogo"] == base["retrato"]["catalogo"]


@pytest.mark.postgres
def test_0034_remocao_trava_a_linha_antes_de_contar_no_postgres(engine_postgres):
    """A trava da PRÓPRIA remoção (FOR UPDATE), sem o DROP da descida na frente: um
    resultado gravado na 'ica' e ainda NÃO confirmado não aparece na contagem; sem a
    trava, o DELETE esperaria o commit dele e o levaria em cascata. Com a trava, a
    remoção espera (``lock_timeout``), falha e não apaga nada; confirmado o resultado,
    ela mantém a 'ica'."""
    base = _banco_com_catalogo_na_0033(engine_postgres)
    ica = _ica_avulsa(engine_postgres, base, com_resultado=False)["ica"]
    meta = MetaData()
    with engine_postgres.connect() as c:
        meta.reflect(bind=c)
    mod = _migracao_0034()
    gravador = engine_postgres.connect()
    try:
        _inserir(gravador, meta, "resultados_avaliacao", avaliacao_id=ica, edicao=2024,
                 escola_id=base["e2"], indicador="taxa_inventada", valor=1.0,
                 unidade="percentual")                                   # sem commit
        with pytest.raises(DBAPIError, match="lock timeout") as erro:
            with engine_postgres.begin() as c:
                c.execute(text("SET LOCAL lock_timeout = '2s'"))
                mod.remover_linhas_sem_vinculo_do_catalogo(c)
        assert "FOR UPDATE" in str(erro.value.statement)
        gravador.commit()
    finally:
        gravador.close()
    with engine_postgres.begin() as c:
        assert mod.remover_linhas_sem_vinculo_do_catalogo(c) == {
            "removidas": [], "mantidas": ["ica"]}
    assert _ids_da_etapa(engine_postgres) == {"ica": ica}
    with engine_postgres.connect() as c:
        assert c.execute(text("SELECT count(*) FROM resultados_avaliacao")).scalar_one() == 9


@pytest.mark.postgres
def test_0034_fk_de_outro_schema_segura_o_catalogo_no_postgres(engine_postgres, capfd):
    """Uma FK vinda de OUTRO schema (o inspetor só lê o padrão) para o id do catálogo:
    a descida a acha em ``pg_constraint``, não remove NADA do catálogo e avisa — sem
    isso, o CASCADE levaria a linha dela sem ninguém notar."""
    base = _banco_com_catalogo_na_0033(engine_postgres)
    ids = _subir_com_ica_iee_do_codigo_novo(engine_postgres)
    _importacoes_desfeitas(engine_postgres, ids)
    esquema = "esquema_inventado_catalogo_0034"
    try:
        with engine_postgres.begin() as c:
            c.execute(text(f"DROP SCHEMA IF EXISTS {esquema} CASCADE"))
            c.execute(text(f"CREATE SCHEMA {esquema}"))
            c.execute(text(
                f"CREATE TABLE {esquema}.vinculo (id integer PRIMARY KEY, avaliacao_id "
                "integer NOT NULL REFERENCES public.avaliacoes_externas(id) "
                "ON DELETE CASCADE)"))
            c.execute(text(f"INSERT INTO {esquema}.vinculo VALUES (7, :i)"), {"i": ids["iee"]})
        log = _descer_ate_a_0033(engine_postgres, capfd)
        assert ("'ica', 'iee' do catálogo avaliacoes_externas FICARAM: há vínculo com o "
                f"catálogo que esta descida não sabe contar ({esquema}.vinculo.avaliacao_id "
                "-> avaliacoes_externas.id)") in log
        assert _ids_da_etapa(engine_postgres) == ids
        with engine_postgres.connect() as c:
            assert c.execute(text(f"SELECT id, avaliacao_id FROM {esquema}.vinculo")).all() == [
                (7, ids["iee"])]
        assert _retratos(engine_postgres, base["colunas"]) == base["retrato"]
    finally:
        with engine_postgres.begin() as c:
            c.execute(text(f"DROP SCHEMA IF EXISTS {esquema} CASCADE"))


@pytest.mark.postgres
def test_0034_vinculo_conhecido_conta_mesmo_sem_fk_no_postgres(engine_postgres, capfd):
    """Banco em que a FK de ``fontes_avaliacao`` para o catálogo sumiu: a reflexão não a
    vê, mas o vínculo conhecido conta. A receita do robô na 'iee' SEGURA a 'iee' (sem
    isso, a 'iee' sairia e a receita ficaria apontando para nada, sem a conferência
    final notar) e a 'ica', livre, sai."""
    base = _banco_com_catalogo_na_0033(engine_postgres)
    ids = _subir_com_ica_iee_do_codigo_novo(engine_postgres)
    _importacoes_desfeitas(engine_postgres, ids)
    nome_fk = next(fk["name"] for fk in inspect(engine_postgres).get_foreign_keys(
        "fontes_avaliacao") if fk["referred_table"] == "avaliacoes_externas")
    with engine_postgres.begin() as c:
        c.execute(text(f'ALTER TABLE fontes_avaliacao DROP CONSTRAINT "{nome_fk}"'))
        meta = MetaData()
        meta.reflect(bind=c)
        _inserir(c, meta, "fontes_avaliacao", avaliacao_id=ids["iee"], nome="robo_iee_sem_fk",
                 url="https://exemplo.invalido/iee.csv", edicao=2025, indicador="iee",
                 unidade="indice", cadencia="manual", ativo=False, ultimo_status="nunca",
                 mapeamento={})
    with engine_postgres.connect() as c:
        assert ("fontes_avaliacao", "avaliacao_id") in _migracao_0034().referencias_ao_catalogo(c)
    log = _descer_ate_a_0033(engine_postgres, capfd)
    assert ("a linha 'iee' do catálogo avaliacoes_externas FICOU: 1 linha(s) de "
            "fontes_avaliacao.avaliacao_id apontam para ela") in log
    assert f"{_LOG_REMOVIDAS}: ica." in log
    assert _ids_da_etapa(engine_postgres) == {"iee": ids["iee"]}
    depois = _retratos(engine_postgres, base["colunas"])
    assert len(depois["fontes"]) == 3
    assert depois["fontes"][:2] == base["retrato"]["fontes"]
    assert depois["resultados"] == base["retrato"]["resultados"]
    assert depois["catalogo"] == base["retrato"]["catalogo"]


@pytest.mark.postgres
@pytest.mark.parametrize("modo", ["papel_que_nao_e_dono", "dono_com_force"])
def test_0034_rls_ativa_para_quem_desce_segura_o_catalogo_no_postgres(engine_postgres, modo):
    """Com ROW LEVEL SECURITY ativa para quem roda a descida numa tabela que aponta para
    o catálogo (papel que não é dono nem tem BYPASSRLS; ou o dono com FORCE, proibido no
    projeto mas possível num banco), a contagem não vê as linhas e o CASCADE (ação de
    integridade, que ignora a RLS) as levaria: nada sai do catálogo. Um papel
    temporário, sem login, removido no fim."""
    base = _banco_com_catalogo_na_0033(engine_postgres)
    ica = _ica_avulsa(engine_postgres, base, com_resultado=False)["ica"]
    with engine_postgres.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        _inserir(c, meta, "fontes_avaliacao", avaliacao_id=ica, nome="robo_ica_rls",
                 url="https://exemplo.invalido/ica.csv", edicao=2025, indicador="ica",
                 unidade="percentual", cadencia="manual", ativo=False,
                 ultimo_status="nunca", mapeamento={})
    papel = f"papel_inventado_rls_{os.getpid()}"
    try:
        with engine_postgres.begin() as c:
            c.execute(text(f'CREATE ROLE "{papel}" NOLOGIN NOSUPERUSER NOBYPASSRLS'))
    except DBAPIError as exc:
        pytest.skip(f"o usuário do PostgreSQL de teste não cria papel: {exc.orig}")
    mod = _migracao_0034()
    try:
        with engine_postgres.begin() as c:
            c.execute(text(f'GRANT USAGE ON SCHEMA public TO "{papel}"'))
            c.execute(text("GRANT SELECT, UPDATE, DELETE ON avaliacoes_externas, "
                           f'resultados_avaliacao, fontes_avaliacao TO "{papel}"'))
            if modo == "dono_com_force":
                c.execute(text(f'ALTER TABLE fontes_avaliacao OWNER TO "{papel}"'))
                c.execute(text("ALTER TABLE fontes_avaliacao FORCE ROW LEVEL SECURITY"))
            c.execute(text("ALTER TABLE fontes_avaliacao ENABLE ROW LEVEL SECURITY"))
        with engine_postgres.begin() as c:
            c.execute(text(f'SET LOCAL ROLE "{papel}"'))
            assert c.execute(text("SELECT count(*) FROM fontes_avaliacao")).scalar_one() == 0
            refs = mod.referencias_ao_catalogo(c)
            assert refs == _FKS_NA_0033
            assert mod.vinculos_que_a_contagem_nao_cobre(c, refs) == [
                "fontes_avaliacao (row level security ativa para quem roda a descida)"]
            assert mod.remover_linhas_sem_vinculo_do_catalogo(c) == {
                "removidas": [], "mantidas": ["ica"]}
        assert _ids_da_etapa(engine_postgres) == {"ica": ica}
        with engine_postgres.connect() as c:
            assert c.execute(text("SELECT count(*) FROM fontes_avaliacao")).scalar_one() == 3
    finally:
        with engine_postgres.begin() as c:
            c.execute(text("ALTER TABLE fontes_avaliacao NO FORCE ROW LEVEL SECURITY"))
            c.execute(text("ALTER TABLE fontes_avaliacao DISABLE ROW LEVEL SECURITY"))
            c.execute(text(f'REASSIGN OWNED BY "{papel}" TO CURRENT_USER'))
            c.execute(text(f'DROP OWNED BY "{papel}"'))
            c.execute(text(f'DROP ROLE "{papel}"'))


def test_0034_descida_offline_gera_o_sql_sem_a_limpeza_do_catalogo(capfd):
    """``alembic downgrade 0034:0033 --sql`` (modo offline, sem banco): gera o SQL da
    descida (as duas tabelas) e avisa que a limpeza do catálogo só roda online — sem a
    guarda, quebrava ao ler o catálogo pelo bind simulado."""
    capfd.readouterr()
    command.downgrade(_config(), f"{REVISAO_0034}:{REVISAO_0033}", sql=True)
    saida = capfd.readouterr()
    assert "DROP TABLE indicadores_referencia" in saida.out
    assert "DROP TABLE importacoes_indicador" in saida.out
    assert "avaliacoes_externas" not in saida.out
    assert "0034 (downgrade) em modo offline (--sql)" in saida.err
