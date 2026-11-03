"""Quest — o código de login (a credencial da criança) guardado com HMAC (0037).

Achado da auditoria de 20/10/2026: ``quest_credenciais_aluno.codigo_login`` em texto
claro era o que o login consultava — quem lesse o banco entrava em qualquer conta.

O que estes testes travam:

1. o login AUTENTICA pelo hash: com o texto da coluna antiga trocado, o código
   certo continua entrando (e o texto sozinho não serve para nada no caminho
   principal);
2. a transição não tranca nenhum cartão: linha sem hash (backup antigo) ou com
   hash de outra chave entra pelo fallback e sai corrigida; a rotação para a
   ``DATA_ENCRYPTION_KEY`` não invalida os hashes feitos com a ``SECRET_KEY``;
3. a comparação final é em tempo constante (``hmac.compare_digest``);
4. a migração 0037 preenche o hash de TODOS os códigos (e QR) existentes a partir
   do texto — e o cálculo congelado nela é idêntico ao do app;
5. a coluna antiga continua (decisão do dono) e a descida não perde nada.
"""
import hmac
import os

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.migracoes import _config
from app.main import app
from app.quest.models import QuestCredencialAluno
from app.quest.services import credenciais as svc

REVISAO_0036 = "0036_rls_todas_as_tabelas"
REVISAO_0037 = "0037_quest_codigo_hash_limites"


def _gerar_cartoes(cliente, escola_id, turma_id, **params):
    query = "&".join(f"{k}={'true' if v else 'false'}" for k, v in params.items())
    r = cliente.post(f"/api/v1/escolas/{escola_id}/quest/turmas/{turma_id}/cartoes"
                     + (f"?{query}" if query else ""))
    assert r.status_code == 200, r.text


def _credencial(db, aluno_id) -> QuestCredencialAluno:
    db.expire_all()
    return db.execute(select(QuestCredencialAluno)
                      .where(QuestCredencialAluno.aluno_id == aluno_id)).scalar_one()


def _entrar(codigo):
    return TestClient(app).post("/api/v1/quest/auth/entrar", json={"codigo": codigo})


@pytest.fixture
def credencial(cliente, db, escola_completa):
    _gerar_cartoes(cliente, escola_completa["escola"].id, escola_completa["turma"].id)
    return _credencial(db, escola_completa["alunos"][0].id)


# --- 1. O hash é gravado e é por ele que se autentica ------------------------

def test_cartao_novo_grava_hmac_do_codigo(credencial):
    assert credencial.codigo_login_hash == svc.hash_codigo(credencial.codigo_login)
    assert len(credencial.codigo_login_hash) == 64
    assert credencial.codigo_login not in credencial.codigo_login_hash
    # HMAC com chave do servidor, não um SHA-256 "puro" (que qualquer um recalcula
    # para os ~1,3×10^5 códigos possíveis a partir do banco).
    import hashlib
    assert credencial.codigo_login_hash != hashlib.sha256(
        credencial.codigo_login.encode()).hexdigest()


def test_login_autentica_pelo_hash_e_nao_pelo_texto(db, credencial, monkeypatch):
    """Sem o fallback de transição (o estado depois da remoção da coluna), só o
    hash autentica: com o texto trocado, o código certo entra e o texto não."""
    monkeypatch.setattr(svc, "_FALLBACK_TEXTO_CLARO", False)
    codigo = credencial.codigo_login
    linha = db.get(QuestCredencialAluno, credencial.id)
    linha.codigo_login = "TEXTOTROCADO999"     # o texto não confere mais com nada
    db.commit()

    assert _entrar(codigo).status_code == 200            # entrou pelo hash
    assert _entrar("TEXTOTROCADO999").status_code == 401  # o texto sozinho não entra


def test_caminho_principal_nao_consulta_o_texto(db, credencial):
    """Com o hash em dia, a busca acaba no hash: nenhuma consulta pela coluna de
    texto (o fallback só roda quando o hash não acha nada)."""
    from sqlalchemy import event

    consultas = []

    def anotar(conn, cursor, sql, params, context, executemany):
        consultas.append(sql)

    motor = db.get_bind()
    event.listen(motor, "before_cursor_execute", anotar)
    try:
        assert svc.buscar_por_codigo(db, credencial.codigo_login).id == credencial.id
    finally:
        event.remove(motor, "before_cursor_execute", anotar)
    assert consultas and all("codigo_login_hash IN" in sql for sql in consultas)


def test_comparacao_final_em_tempo_constante(db, credencial, monkeypatch):
    chamadas = []
    original = hmac.compare_digest

    def espiao(a, b):
        chamadas.append((a, b))
        return original(a, b)

    monkeypatch.setattr(svc.hmac, "compare_digest", espiao)
    assert svc.buscar_por_codigo(db, credencial.codigo_login).id == credencial.id
    assert any(credencial.codigo_login_hash in par for par in chamadas)


def test_rotacionar_codigo_troca_o_hash_e_o_antigo_nao_entra(cliente, db, escola_completa,
                                                            credencial):
    antigo, hash_antigo = credencial.codigo_login, credencial.codigo_login_hash
    _gerar_cartoes(cliente, escola_completa["escola"].id, escola_completa["turma"].id,
                   rotacionar_codigo=True)
    nova = _credencial(db, escola_completa["alunos"][0].id)
    assert nova.codigo_login != antigo and nova.codigo_login_hash != hash_antigo
    assert nova.codigo_login_hash == svc.hash_codigo(nova.codigo_login)
    assert _entrar(antigo).status_code == 401      # nem pelo hash nem pelo fallback
    assert _entrar(nova.codigo_login).status_code == 200


# --- 2. Transição: nenhum cartão fica trancado --------------------------------

def test_linha_sem_hash_entra_pelo_texto_e_sai_corrigida(db, credencial):
    """Backup anterior à 0037 restaurado, ou réplica antiga gravando no deploy."""
    linha = db.get(QuestCredencialAluno, credencial.id)
    linha.codigo_login_hash = None
    db.commit()

    assert _entrar(credencial.codigo_login).status_code == 200
    assert _credencial(db, credencial.aluno_id).codigo_login_hash == \
        svc.hash_codigo(credencial.codigo_login)


def test_hash_de_outra_chave_entra_e_sai_regravado(db, credencial):
    """A migração rodou num processo com outra SECRET_KEY (ex.: efêmera)."""
    linha = db.get(QuestCredencialAluno, credencial.id)
    linha.codigo_login_hash = svc.hash_codigo(credencial.codigo_login,
                                              segredo="outra-chave-de-teste-" + "x" * 20)
    db.commit()
    assert svc.contar_hashes_divergentes(db) == 1

    assert _entrar(credencial.codigo_login).status_code == 200
    db.expire_all()                       # o login gravou noutra sessão
    assert svc.contar_hashes_divergentes(db) == 0


def test_chave_dedicada_nova_nao_invalida_cartao(db, credencial, monkeypatch):
    """Definir DATA_ENCRYPTION_KEY depois: o hash feito com a SECRET_KEY confere
    pela chave secundária e é regravado na primária — sem fallback de texto."""
    monkeypatch.setattr(svc, "_FALLBACK_TEXTO_CLARO", False)
    hash_secret_key = credencial.codigo_login_hash
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", "chave-dedicada-de-teste-" + "y" * 20)

    assert _entrar(credencial.codigo_login).status_code == 200
    regravado = _credencial(db, credencial.aluno_id).codigo_login_hash
    assert regravado != hash_secret_key
    assert regravado == svc.hash_codigo(credencial.codigo_login)   # agora na dedicada


def test_sem_fallback_so_o_hash_autentica(db, credencial, monkeypatch):
    """O estado pós-remoção da coluna: sem o fallback, linha sem hash não entra —
    por isso a conferência ``contar_hashes_divergentes() == 0`` antes de remover."""
    monkeypatch.setattr(svc, "_FALLBACK_TEXTO_CLARO", False)
    linha = db.get(QuestCredencialAluno, credencial.id)
    linha.codigo_login_hash = None
    db.commit()
    assert svc.contar_hashes_divergentes(db) == 1
    assert _entrar(credencial.codigo_login).status_code == 401

    assert svc.preencher_hashes_ausentes(db) == 1
    db.commit()
    assert svc.contar_hashes_divergentes(db) == 0
    assert _entrar(credencial.codigo_login).status_code == 200


def test_cartao_continua_mostrando_o_codigo(cliente, db, escola_completa, credencial):
    """A coluna antiga segue (decisão do dono): a página do professor e o PDF
    mostram o código, agora lido por um ponto único (codigo_para_exibicao)."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    acessos = cliente.get(f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/acessos")
    codigos = {a["aluno_id"]: a["codigo_login"] for a in acessos.json()}
    assert codigos[credencial.aluno_id] == credencial.codigo_login
    assert svc.codigo_para_exibicao(credencial) == credencial.codigo_login


# --- 3. Migração 0037: backfill a partir do texto ------------------------------

@pytest.mark.parametrize("codigo", ["SOL314", "LUAFAROL7314", "sol-31 4", "ÁRVORE123", ""])
@pytest.mark.parametrize("segredo", ["s" * 40, "chave com espaço e acento ção " * 2])
def test_calculo_congelado_na_0037_e_o_mesmo_do_app(codigo, segredo):
    from importlib import util
    caminho = (os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
               + "/alembic/versions/0037_quest_codigo_hash_limites.py")
    spec = util.spec_from_file_location("migracao_0037", caminho)
    modulo = util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert modulo.hash_codigo_0037(codigo, segredo) == svc.hash_codigo(codigo, segredo=segredo)
    # O do QR também (o mesmo valor serve de token aqui: só importa a igualdade).
    assert modulo.hash_qr_0037(codigo + segredo) == svc.hash_qr(codigo + segredo)


def _migrar(engine, alvo: str, subir: bool = True) -> None:
    cfg = _config()
    with engine.begin() as conexao:
        cfg.attributes["connection"] = conexao
        (command.upgrade if subir else command.downgrade)(cfg, alvo)


def _inserir(conexao, meta, tabela: str, **valores) -> int:
    """INSERT pelo schema REFLETIDO (o da 0036): preenche só o obrigatório que o
    cenário não informou. Devolve o id."""
    from datetime import datetime

    from sqlalchemy import types as sqltypes

    t = meta.tables[tabela]
    linha = dict(valores)
    for coluna in t.columns:
        if coluna.name in linha or coluna.primary_key:
            continue
        if not coluna.nullable and coluna.server_default is None:
            tipo = coluna.type
            if isinstance(tipo, sqltypes.Boolean):
                linha[coluna.name] = False
            elif isinstance(tipo, sqltypes.Integer):
                linha[coluna.name] = 0
            elif isinstance(tipo, sqltypes.DateTime):
                linha[coluna.name] = datetime(2026, 10, 1)
            elif isinstance(tipo, sqltypes.JSON):
                linha[coluna.name] = {}
            else:
                linha[coluna.name] = "x"
    return conexao.execute(t.insert().values(**linha).returning(t.c.id)).scalar_one()


def _banco_na_0036_com_cartoes(engine) -> dict[str, str]:
    """Estado de produção antes da 0037: códigos só em texto (formato atual e o
    antigo de 2 palavras), de duas escolas."""
    from sqlalchemy import MetaData

    _migrar(engine, REVISAO_0036)
    codigos = {"a1": "SOL314", "a2": "LUAFAROL7314", "a3": "COMETA101"}
    with engine.begin() as c:
        meta = MetaData()
        meta.reflect(bind=c)
        escolas = [_inserir(c, meta, "escolas", nome=f"Escola Teste {i}",
                            ano_letivo_ativo=2026) for i in (1, 2)]
        for i, (chave, codigo) in enumerate(codigos.items()):
            escola = escolas[0] if i < 2 else escolas[1]
            aluno = _inserir(c, meta, "alunos", escola_id=escola,
                             nome=f"Aluna Teste {chave.upper()}", status="ativo")
            _inserir(c, meta, "quest_credenciais_aluno", escola_id=escola,
                     aluno_id=aluno, codigo_login=codigo, qr_token=f"qr-teste-{i}")
    return codigos


def _conferir_0037(engine) -> None:
    codigos = _banco_na_0036_com_cartoes(engine)
    _migrar(engine, REVISAO_0037)
    with engine.connect() as c:
        linhas = c.execute(text("SELECT codigo_login, codigo_login_hash, qr_token, "
                                "qr_token_hash FROM quest_credenciais_aluno")).all()
    assert len(linhas) == len(codigos)
    for codigo, hash_, qr, hash_qr in linhas:
        assert codigo in codigos.values()            # coluna antiga INTACTA
        assert hash_ == svc.hash_codigo(codigo)      # todo cartão já impresso entra
        assert qr.startswith("qr-teste-")            # o QR em texto também fica
        assert hash_qr == svc.hash_qr(qr)            # e todo QR impresso entra
    insp = inspect(engine)
    indices = {i["name"]: i for i in insp.get_indexes("quest_credenciais_aluno")}
    assert indices["ix_quest_credenciais_aluno_codigo_login_hash"]["unique"]
    assert indices["ix_quest_credenciais_aluno_qr_token_hash"]["unique"]
    assert "quest_limites_acesso" in insp.get_table_names()

    # Descer não perde nada: o texto fica, só os hashes e a tabela de limites saem.
    _migrar(engine, REVISAO_0036, subir=False)
    insp = inspect(engine)
    assert "quest_limites_acesso" not in insp.get_table_names()
    assert not {"codigo_login_hash", "qr_token_hash"} & {
        c["name"] for c in insp.get_columns("quest_credenciais_aluno")}
    with engine.connect() as c:
        assert sorted(r[0] for r in c.execute(text(
            "SELECT codigo_login FROM quest_credenciais_aluno"))) == sorted(codigos.values())
    # E subir de novo preenche outra vez (idempotente quanto ao resultado).
    _migrar(engine, REVISAO_0037)
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM quest_credenciais_aluno "
                              "WHERE codigo_login_hash IS NULL "
                              "OR qr_token_hash IS NULL")).scalar() == 0


def test_0037_preenche_hash_e_desce_sem_perder_no_sqlite(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'quest_0037.db'}")
    try:
        _conferir_0037(engine)
    finally:
        engine.dispose()


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
    yield engine
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    engine.dispose()


@pytest.mark.postgres
def test_0037_preenche_hash_e_desce_sem_perder_no_postgres(engine_postgres):
    _conferir_0037(engine_postgres)
    with engine_postgres.connect() as c:
        rls, forcado = c.execute(text(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = 'quest_limites_acesso'")).one()
    assert rls is True and forcado is False     # ENABLE, nunca FORCE
