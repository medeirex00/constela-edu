"""scripts/recifrar_segredos.py + app/services/recifragem.py (A1 §3.2, letras d, e, i, j).

Cenário fictício montado pelos ESCRITORES REAIS de cada origem (vault, assistente, sessão
do Matific e cartão do Quest), com as chaves velhas (SK0, DEK0); depois a configuração da
rotação: DEK1/SK1 atuais, DEK0 em DATA_ENCRYPTION_KEYS_ANTERIORES e SK0 em
CHAVE_CIFRA_LEGADA_ANTERIOR.

* (d) ``--contar`` não grava: arquivo SQLite igual byte a byte (e, no PostgreSQL, o
  ``xmin`` de cada linha igual);
* (e) ``--executar`` leva 100% para a primária, a recontagem confere e as chaves novas,
  SOZINHAS, leem tudo; a 2ª execução não muda nada;
* (i) uma falha no meio desfaz só a origem em curso e a nova execução converge;
* (j) o mesmo em PostgreSQL real, com ``FOR UPDATE`` e ``lock_timeout`` de verdade.

Nada de valor real: chaves geradas em memória; a saída e a auditoria só têm números.
"""
from __future__ import annotations

import hashlib
import io
import json
import secrets
from datetime import datetime

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.core import security
from app.core.config import settings
from app.core.database import Base
from app.models import Aluno, Configuracao, Escola, LogAuditoria
from app.models.sincronizacao import PlataformaCredencial
from app.quest.services import credenciais as quest
from app.services import assistente, recifragem
from app.sync import aovivo, vault
from app.sync.interfaces import Credenciais
from scripts import recifrar_segredos
from tests._infra_comum import pg_url  # noqa: F401 — fixture


def _chave(prefixo: str) -> str:
    return f"{prefixo}-{secrets.token_urlsafe(40)}"


SK0, SK1 = _chave("sk0"), _chave("sk1")
DEK0, DEK1 = _chave("dek0"), _chave("dek1")
SENHAS = {"legado": "senha-ficticia-legado", "dek0": "senha-ficticia-dek0",
          "atual": "senha-ficticia-atual", "ia": "chave-ia-ficticia-0001"}
VALORES_SECRETOS = (SK0, SK1, DEK0, DEK1, *SENHAS.values())


def _config(monkeypatch, *, sk, dek="", anteriores="", legada=""):
    monkeypatch.setattr(settings, "SECRET_KEY", sk)
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", dek)
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEYS_ANTERIORES", anteriores)
    monkeypatch.setattr(settings, "CHAVE_CIFRA_LEGADA_ANTERIOR", legada)


def _rotacao(monkeypatch, *, com_anteriores=True):
    _config(monkeypatch, sk=SK1, dek=DEK1, anteriores=DEK0 if com_anteriores else "",
            legada=SK0 if com_anteriores else "")


def _engine_sqlite(url: str):
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
    return engine


def _escola(db, nome):
    e = Escola(nome=nome, ano_letivo_ativo=2026)
    db.add(e)
    db.flush()
    return e


def _popular(Sessao, monkeypatch, *, com_ilegivel: bool) -> dict:
    """Escola A: Elefante no legado (SK0, sem DEK), Matific/IA/sessão/cartão na DEK0.
    Escola B: tudo já na chave ATUAL (DEK1) — não pode ser tocado. Escola C (opcional):
    credencial e sessão de uma chave que ninguém tem (ilegíveis)."""
    db = Sessao()
    a, b = _escola(db, "ESCOLA FICTICIA A"), _escola(db, "ESCOLA FICTICIA B")
    aluno = Aluno(escola_id=a.id, nome="Aluno Ficticio Um")
    db.add(aluno)
    db.commit()
    ids = {"a": a.id, "b": b.id}

    _config(monkeypatch, sk=SK0)
    vault.salvar_credencial(db, a.id, "elefante", Credenciais("robo-a@x.invalid", SENHAS["legado"]))
    db.commit()
    _config(monkeypatch, sk=SK0, dek=DEK0)
    vault.salvar_credencial(db, a.id, "matific", Credenciais("robo-a@x.invalid", SENHAS["dek0"]))
    assistente.salvar_config_assistente(db, a.id, "anthropic", SENHAS["ia"], None)
    quest.garantir_credencial_aluno(db, a.id, aluno)
    db.commit()
    aovivo._salvar_sessao(db, a.id, {"cookies": [{"name": "c", "value": "ficticio"}]},
                          datetime(2026, 10, 24, 9, 0))
    _rotacao(monkeypatch)
    vault.salvar_credencial(db, b.id, "matific", Credenciais("robo-b@x.invalid", SENHAS["atual"]))
    assistente.salvar_config_assistente(db, b.id, "local", None, None)        # sem chave
    db.commit()
    aovivo._salvar_sessao(db, b.id, {"cookies": []}, datetime(2026, 10, 24, 9, 0))
    if com_ilegivel:
        c = _escola(db, "ESCOLA FICTICIA C")
        ids["c"] = c.id
        db.commit()
        _config(monkeypatch, sk=_chave("ninguem"), dek=_chave("ninguem-dek"))
        vault.salvar_credencial(db, c.id, "elefante", Credenciais("robo-c@x.invalid", "x"))
        db.commit()
        aovivo._salvar_sessao(db, c.id, {"cookies": []}, datetime(2026, 10, 24, 9, 0))
    _rotacao(monkeypatch)
    db.close()
    return ids


ANTES_SEM_ILEGIVEL = {
    "plataforma_credenciais": {"primaria": 1, "anterior": 2, "ilegivel": 0, "vazio": 0},
    "configuracoes.assistente": {"primaria": 0, "anterior": 1, "ilegivel": 0, "vazio": 1},
    "configuracoes.matific_sessao": {"primaria": 1, "anterior": 1, "ilegivel": 0, "vazio": 0},
}
DEPOIS_SEM_ILEGIVEL = {
    "plataforma_credenciais": {"primaria": 3, "anterior": 0, "ilegivel": 0, "vazio": 0},
    "configuracoes.assistente": {"primaria": 1, "anterior": 0, "ilegivel": 0, "vazio": 1},
    "configuracoes.matific_sessao": {"primaria": 1, "anterior": 0, "ilegivel": 0, "vazio": 0},
}


def _rodar(argv, Sessao):
    saida = io.StringIO()
    codigo = recifrar_segredos.main(argv, sessao=Sessao, saida=saida)
    return codigo, saida.getvalue()


def _cifras(Sessao) -> dict:
    db = Sessao()
    try:
        cred = {(c.escola_id, c.plataforma): c.segredo_cifrado
                for c in db.execute(select(PlataformaCredencial)).scalars()}
        conf = {(c.escola_id, c.namespace): json.dumps(c.valor, sort_keys=True)
                for c in db.execute(select(Configuracao).where(
                    Configuracao.namespace.in_(("assistente", "matific_sessao")))).scalars()}
        return {"cred": cred, "conf": conf}
    finally:
        db.close()


def _leaves(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _leaves(v)
    else:
        yield obj


@pytest.fixture
def sqlite_sessao(tmp_path):
    engine = _engine_sqlite(f"sqlite:///{(tmp_path / 'recifrar.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine), engine, tmp_path / "recifrar.db"
    engine.dispose()


def test_origens_batem_com_os_escritores():
    assert recifragem.NS_SESSAO_MATIFIC == aovivo._NS_SESSAO
    assert set(recifragem.ORIGENS) == {"plataforma_credenciais", "configuracoes.assistente",
                                       "configuracoes.matific_sessao"}


# --- (d) --contar não grava -----------------------------------------------------------

def test_d_contar_nao_grava_byte_a_byte(sqlite_sessao, monkeypatch):
    Sessao, engine, arquivo = sqlite_sessao
    _popular(Sessao, monkeypatch, com_ilegivel=False)
    engine.dispose()
    antes = hashlib.sha256(arquivo.read_bytes()).hexdigest()

    for argv in ([], ["--contar"]):
        codigo, saida = _rodar(argv, Sessao)
        assert codigo == 1                                  # há cifra numa anterior
        assert "anterior=2" in saida and "Pendente: 4" in saida
        engine.dispose()
        assert hashlib.sha256(arquivo.read_bytes()).hexdigest() == antes
    db = Sessao()
    assert recifragem.contar(db) == ANTES_SEM_ILEGIVEL
    assert db.scalar(select(LogAuditoria.id).where(
        LogAuditoria.acao == recifragem.ACAO_AUDITORIA)) is None
    db.close()


# --- (e) --executar leva 100% para a primária ------------------------------------------

def test_e_executar_leva_tudo_para_a_primaria_e_e_idempotente(sqlite_sessao, monkeypatch):
    Sessao, _, _ = sqlite_sessao
    ids = _popular(Sessao, monkeypatch, com_ilegivel=False)
    intocadas = _cifras(Sessao)

    codigo, saida = _rodar(["--executar"], Sessao)
    assert codigo == 0, saida
    assert "Tudo na chave atual" in saida
    db = Sessao()
    assert recifragem.contar(db) == DEPOIS_SEM_ILEGIVEL
    db.close()
    depois = _cifras(Sessao)
    # Escola B já estava na primária: nem o token muda (idempotência por linha).
    assert depois["cred"][(ids["b"], "matific")] == intocadas["cred"][(ids["b"], "matific")]
    assert depois["conf"][(ids["b"], "matific_sessao")] == \
        intocadas["conf"][(ids["b"], "matific_sessao")]
    # A sessão do Matific da escola A foi APAGADA, não recifrada.
    assert (ids["a"], "matific_sessao") not in depois["conf"]

    # As chaves NOVAS, sozinhas, leem tudo (as anteriores já podem sair).
    _rotacao(monkeypatch, com_anteriores=False)
    db = Sessao()
    assert vault.obter_credencial(db, ids["a"], "elefante").senha == SENHAS["legado"]
    assert vault.obter_credencial(db, ids["a"], "matific").senha == SENHAS["dek0"]
    assert vault.obter_credencial(db, ids["b"], "matific").senha == SENHAS["atual"]
    valor_ia = db.execute(select(Configuracao.valor).where(
        Configuracao.escola_id == ids["a"], Configuracao.namespace == "assistente")).scalar_one()
    assert security.decifrar_segredo(valor_ia["api_key_cifrada"]) == SENHAS["ia"]
    assert quest.contar_hashes_divergentes(db) == 0          # cartão do Quest na DEK1
    db.close()

    # 2ª execução: nada muda (os tokens ficam idênticos).
    _rotacao(monkeypatch)
    codigo, saida = _rodar(["--executar"], Sessao)
    assert codigo == 0
    assert "recifradas=1" not in saida and "recifradas=2" not in saida
    assert "hashes do Quest recalculados: 0" in saida
    assert _cifras(Sessao) == depois


def test_e_auditoria_e_saida_so_com_numeros(sqlite_sessao, monkeypatch, caplog, capsys):
    Sessao, _, _ = sqlite_sessao
    _popular(Sessao, monkeypatch, com_ilegivel=True)
    codigo, saida = _rodar(["--executar"], Sessao)
    db = Sessao()
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == recifragem.ACAO_AUDITORIA)).scalar_one()
    detalhes = log.detalhes
    db.close()
    assert all(isinstance(v, int) for v in _leaves(detalhes))
    assert detalhes["feito"]["plataforma_credenciais"]["recifradas"] == 2
    assert detalhes["feito"]["configuracoes.matific_sessao"]["apagadas"] == 2   # anterior + ilegível
    texto = saida + capsys.readouterr().err + caplog.text + json.dumps(detalhes)
    for valor in VALORES_SECRETOS:
        assert valor not in texto
    assert codigo == 1                         # a credencial ilegível da escola C sobrou


def test_ilegivel_fica_e_e_contado_e_aceitar_ilegiveis_libera(sqlite_sessao, monkeypatch):
    Sessao, _, _ = sqlite_sessao
    ids = _popular(Sessao, monkeypatch, com_ilegivel=True)
    ilegivel = _cifras(Sessao)["cred"][(ids["c"], "elefante")]
    # Antes: 4 numa anterior + a credencial ilegível; a SESSÃO ilegível não pesa
    # (descartável: o --executar a apaga).
    codigo, saida = _rodar(["--contar"], Sessao)
    assert codigo == 1 and "Pendente: 5" in saida
    codigo, saida = _rodar(["--executar"], Sessao)
    assert codigo == 1 and "Pendente: 1" in saida
    assert _cifras(Sessao)["cred"][(ids["c"], "elefante")] == ilegivel      # não mexe
    db = Sessao()
    c = recifragem.contar(db)
    db.close()
    assert c["plataforma_credenciais"] == {"primaria": 3, "anterior": 0, "ilegivel": 1, "vazio": 0}
    assert c["configuracoes.matific_sessao"]["ilegivel"] == 0
    codigo, _ = _rodar(["--contar", "--aceitar-ilegiveis"], Sessao)
    assert codigo == 0


def test_executar_sem_dek_ativa_e_recusado_e_nao_grava(sqlite_sessao, monkeypatch):
    Sessao, _, _ = sqlite_sessao
    _popular(Sessao, monkeypatch, com_ilegivel=False)
    antes = _cifras(Sessao)
    for dek in ("", "   ", SK1):
        _config(monkeypatch, sk=SK1, dek=dek, anteriores=DEK0, legada=SK0)
        codigo, _ = _rodar(["--executar"], Sessao)
        assert codigo == 2
    assert _cifras(Sessao) == antes


# --- (i) falha no meio, nova execução converge ------------------------------------------

@pytest.mark.parametrize("falha_na_chamada,credenciais_gravadas", [(2, 0), (3, 2)])
def test_i_falha_no_meio_e_a_nova_execucao_converge(sqlite_sessao, monkeypatch,
                                                    falha_na_chamada, credenciais_gravadas):
    """2ª chamada = no meio de plataforma_credenciais (a origem inteira volta);
    3ª = no assistente, depois de plataforma_credenciais gravada (ela fica)."""
    Sessao, _, _ = sqlite_sessao
    _popular(Sessao, monkeypatch, com_ilegivel=False)
    original, chamadas = recifragem.recifrar, []

    def recifrar_que_falha(token):
        chamadas.append(1)
        if len(chamadas) == falha_na_chamada:
            raise RuntimeError("queda simulada no meio da recifragem")
        return original(token)

    monkeypatch.setattr(recifragem, "recifrar", recifrar_que_falha)
    db = Sessao()
    with pytest.raises(RuntimeError):
        recifragem.executar(db)
    db.close()
    db = Sessao()
    c = recifragem.contar(db)
    db.close()
    assert c["plataforma_credenciais"]["anterior"] == 2 - credenciais_gravadas
    assert c["configuracoes.assistente"]["anterior"] == 1               # voltou inteira
    assert c["configuracoes.matific_sessao"]["anterior"] == 1           # nem começou

    monkeypatch.setattr(recifragem, "recifrar", original)
    codigo, _ = _rodar(["--executar"], Sessao)
    assert codigo == 0
    db = Sessao()
    assert recifragem.contar(db) == DEPOIS_SEM_ILEGIVEL
    db.close()
    estavel = _cifras(Sessao)
    assert _rodar(["--executar"], Sessao)[0] == 0
    assert _cifras(Sessao) == estavel


# --- (j) PostgreSQL real -----------------------------------------------------------------

@pytest.mark.postgres
def test_j_postgres_contar_nao_grava_executar_converge_e_respeita_o_lock(pg_url, monkeypatch):  # noqa: F811
    engine = create_engine(pg_url)
    Base.metadata.create_all(engine)
    Sessao = sessionmaker(bind=engine)
    try:
        ids = _popular(Sessao, monkeypatch, com_ilegivel=False)

        def versoes():
            with engine.connect() as c:
                return c.execute(text(
                    "SELECT 'c' || id, xmin::text, segredo_cifrado FROM plataforma_credenciais "
                    "UNION ALL SELECT 'k' || id, xmin::text, valor::text FROM configuracoes "
                    "ORDER BY 1")).all()

        antes = versoes()
        codigo, _ = _rodar(["--contar"], Sessao)
        assert codigo == 1
        assert versoes() == antes                              # (d): nem o xmin mudou

        # Outra transação segura a linha: o FOR UPDATE espera só o lock_timeout e desiste.
        monkeypatch.setattr(recifragem, "LOCK_TIMEOUT", "300ms")
        trava = engine.connect()
        transacao = trava.begin()
        trava.execute(text("SELECT id FROM plataforma_credenciais WHERE escola_id = :e "
                           "AND plataforma = 'elefante' FOR UPDATE"), {"e": ids["a"]})
        db = Sessao()
        with pytest.raises(OperationalError) as erro:
            recifragem.executar(db)
        db.close()
        assert "lock" in str(erro.value).lower()
        transacao.rollback()
        trava.close()
        assert versoes() == antes                              # nada gravado pela metade

        codigo, saida = _rodar(["--executar"], Sessao)
        assert codigo == 0, saida
        db = Sessao()
        assert recifragem.contar(db) == DEPOIS_SEM_ILEGIVEL
        db.close()
        estavel = versoes()
        assert _rodar(["--executar"], Sessao)[0] == 0
        assert versoes() == estavel                            # 2ª execução: 0 linhas
        _rotacao(monkeypatch, com_anteriores=False)
        db = Sessao()
        assert vault.obter_credencial(db, ids["a"], "elefante").senha == SENHAS["legado"]
        assert quest.contar_hashes_divergentes(db) == 0
        db.close()
    finally:
        engine.dispose()
