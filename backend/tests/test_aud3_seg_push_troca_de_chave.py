"""Aparelho de push registrado com uma sessão da SECRET_KEY antiga não sobrevive à
troca da chave (S_G_ROTACAO-1).

O registro em ``dispositivos_moveis`` não guardava nada da sessão que o criou, e
``push.notificar_escola`` só filtrava por escola e conta ativa. A troca da SECRET_KEY
derruba TODAS as sessões (o JWT antigo passa a dar 401), mas o aparelho registrado
com uma sessão antiga — por exemplo, por quem copiou a chave no incidente e forjou
um JWT sem senha — seguia recebendo os avisos da escola e o primeiro nome das
crianças. O código já fixava que "os aparelhos (push) saem com as sessões".

Agora cada escola guarda a impressão da chave de sessão (HMAC da SECRET_KEY, nunca a
chave) em ``configuracoes``; quando ela muda, os aparelhos da escola saem (no boot,
no registro de um aparelho e no envio do push) e o app volta a se registrar no
próximo login. Sem migração.

Dados fictícios; chaves geradas na hora; o envio ao Expo é trocado por captura.
"""
import secrets
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import hash_senha, impressao_da_chave_de_sessao
from app.main import app
from app.models import Configuracao, DispositivoMovel, Escola, LogAuditoria, Usuario
from app.services import push
from tests._infra_comum import BOOT, ambiente, levar_a, rodar, sqlite_url  # noqa: F401

API = "/api/v1"
TOKEN_ANTIGO = "ExponentPushToken[ficticio-registrado-com-a-chave-antiga]"
TOKEN_NOVO = "ExponentPushToken[ficticio-registrado-com-a-chave-nova]"


def _chave(rotulo: str) -> str:
    return f"teste-{rotulo}-" + secrets.token_urlsafe(32)


@pytest.fixture()
def mensagens(monkeypatch):
    enviadas: list[tuple[str, str]] = []

    def _falso(lotes):
        for lote in lotes:
            enviadas.extend((m["to"], m["body"]) for m in lote)
        return []

    monkeypatch.setattr(push, "_enviar_lotes", _falso)
    return enviadas


def _jwt_forjado(sk: str, usuario_id: int, ver: int) -> str:
    """O que faz quem copiou a SECRET_KEY: assina um JWT sem senha."""
    agora = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(usuario_id), "ver": ver, "iat": agora,
                       "exp": agora + timedelta(hours=8)}, sk, algorithm="HS256")


def _registrar(cliente: TestClient, eid: int, token: str):
    return cliente.post(f"{API}/escolas/{eid}/dispositivos",
                        json={"token_push": token, "plataforma": "android"})


def _logado() -> TestClient:
    cli = TestClient(app)
    r = cli.post(f"{API}/auth/login",
                 data={"username": "admin@teste.local", "password": "s3nh4"})
    assert r.status_code == 200, r.text
    cli.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cli


def _tokens(db) -> set[str]:
    db.expire_all()
    return set(db.execute(select(DispositivoMovel.token_push)).scalars())


def test_aparelho_da_sessao_antiga_nao_recebe_depois_da_troca(db, escola_completa,
                                                               monkeypatch, mensagens):
    eid = escola_completa["escola"].id
    admin = escola_completa["admin"]
    aluna = escola_completa["alunos"][0]
    sk_antiga = _chave("sk0")
    monkeypatch.setattr(settings, "SECRET_KEY", sk_antiga)

    # Antes da troca: a sessão forjada com a chave exposta registra o aparelho.
    atacante = TestClient(app)
    atacante.headers["Authorization"] = (
        f"Bearer {_jwt_forjado(sk_antiga, admin.id, admin.token_version or 0)}")
    assert _registrar(atacante, eid, TOKEN_ANTIGO).status_code == 200

    # A troca: SECRET_KEY nova; a sessão antiga cai.
    monkeypatch.setattr(settings, "SECRET_KEY", _chave("sk1"))
    assert atacante.get(f"{API}/auth/me").status_code == 401

    # A gestão entra de novo e trabalha: recalcular (avisa a escola) e o aviso de
    # UMA criança (leva o primeiro nome dela).
    gestao = _logado()
    r = gestao.post(f"{API}/escolas/{eid}/importacoes/recalcular")
    assert r.status_code == 200, r.text
    push.notificar_escola(db, eid, titulo="Novos dados no Constela Edu",
                          corpo=push.corpo_dados_atualizados(aluna.nome),
                          aluno_id=aluna.id)

    recebidas = [corpo for para, corpo in mensagens if para == TOKEN_ANTIGO]
    assert not recebidas, (
        "aparelho registrado por sessão assinada com a SECRET_KEY ANTIGA (já 401) "
        f"segue recebendo o push depois da troca: {recebidas}")
    assert TOKEN_ANTIGO not in _tokens(db)
    auditoria = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "dispositivo.chave_de_sessao_trocada")).scalars().all()
    assert [a.detalhes["removidos"] for a in auditoria] == [1]
    assert all(sk_antiga not in str(a.detalhes) for a in auditoria)


def test_registro_depois_da_troca_tira_o_antigo_e_fica(db, escola_completa,
                                                       monkeypatch, mensagens):
    eid = escola_completa["escola"].id
    monkeypatch.setattr(settings, "SECRET_KEY", _chave("sk0"))
    assert _registrar(_logado(), eid, TOKEN_ANTIGO).status_code == 200

    monkeypatch.setattr(settings, "SECRET_KEY", _chave("sk1"))
    assert _registrar(_logado(), eid, TOKEN_NOVO).status_code == 200
    assert _tokens(db) == {TOKEN_NOVO}

    assert push.notificar_escola(db, eid, "Aviso", "Corpo fictício") == 1
    assert [para for para, _ in mensagens] == [TOKEN_NOVO]


def test_mesma_chave_o_aparelho_continua_recebendo(db, escola_completa, monkeypatch,
                                                   mensagens):
    eid = escola_completa["escola"].id
    monkeypatch.setattr(settings, "SECRET_KEY", _chave("sk0"))
    cli = _logado()
    assert _registrar(cli, eid, TOKEN_NOVO).status_code == 200
    assert _registrar(cli, eid, TOKEN_NOVO).status_code == 200      # o app reabre
    for _ in range(2):
        assert push.notificar_escola(db, eid, "Aviso", "Corpo fictício") == 1
    assert [para for para, _ in mensagens] == [TOKEN_NOVO, TOKEN_NOVO]
    assert _tokens(db) == {TOKEN_NOVO}


def test_aparelho_gravado_sem_marca_continua_recebendo(db, escola_completa, mensagens):
    """Sem impressão gravada para a escola (aparelho gravado por fora do registro):
    o envio grava a impressão atual e não apaga nada."""
    eid = escola_completa["escola"].id
    db.add(DispositivoMovel(escola_id=eid, usuario_id=escola_completa["admin"].id,
                            plataforma="android", token_push=TOKEN_NOVO))
    db.commit()
    assert push.notificar_escola(db, eid, "Aviso", "Corpo fictício") == 1
    assert [para for para, _ in mensagens] == [TOKEN_NOVO]
    db.expire_all()
    marca = db.execute(select(Configuracao.valor).where(
        Configuracao.escola_id == eid,
        Configuracao.namespace == push.NAMESPACE_CHAVE_DE_SESSAO)).scalar_one()
    assert marca == impressao_da_chave_de_sessao()


def test_troca_sem_ninguem_para_avisar_tambem_grava(db, escola_completa, monkeypatch):
    """A limpeza vale mesmo quando o envio não tem destino: os aparelhos saem e a
    impressão nova fica gravada (o commit não depende de haver push)."""
    eid = escola_completa["escola"].id
    monkeypatch.setattr(settings, "SECRET_KEY", _chave("sk0"))
    assert _registrar(_logado(), eid, TOKEN_ANTIGO).status_code == 200
    monkeypatch.setattr(settings, "SECRET_KEY", _chave("sk1"))
    assert push.notificar_escola(db, eid, "Aviso", "Corpo fictício") == 0
    db.rollback()                         # nada pendente: o que importa foi gravado
    assert _tokens(db) == set()
    marca = db.execute(select(Configuracao.valor).where(
        Configuracao.escola_id == eid,
        Configuracao.namespace == push.NAMESPACE_CHAVE_DE_SESSAO)).scalar_one()
    assert marca == impressao_da_chave_de_sessao()


def test_boot_apaga_os_aparelhos_sem_marca_ou_de_outra_chave(db, escola_completa,
                                                             monkeypatch):
    eid = escola_completa["escola"].id
    admin_id = escola_completa["admin"].id
    outra = Escola(nome="ESCOLA FICTICIA B", ano_letivo_ativo=2026)
    terceira = Escola(nome="ESCOLA FICTICIA C", ano_letivo_ativo=2026)
    db.add_all([outra, terceira])
    db.flush()
    contas = {}
    for escola in (outra, terceira):
        u = Usuario(escola_id=escola.id, nome="Coord Ficticia",
                    email=f"coord{escola.id}@teste.local",
                    senha_hash=hash_senha("Senha-Ficticia-77"), cargo="coordenador")
        db.add(u)
        db.flush()
        contas[escola.id] = u.id
    monkeypatch.setattr(settings, "SECRET_KEY", _chave("sk0"))
    impressao_antiga = impressao_da_chave_de_sessao()
    monkeypatch.setattr(settings, "SECRET_KEY", _chave("sk1"))
    # A: sem marca (aparelho de antes desta correção). B: marca de outra chave.
    # C: marca da chave atual.
    db.add(Configuracao(escola_id=outra.id, namespace=push.NAMESPACE_CHAVE_DE_SESSAO,
                        chave=push.CHAVE_IMPRESSAO, valor=impressao_antiga))
    db.add(Configuracao(escola_id=terceira.id, namespace=push.NAMESPACE_CHAVE_DE_SESSAO,
                        chave=push.CHAVE_IMPRESSAO, valor=impressao_da_chave_de_sessao()))
    for escola_id, usuario_id, sufixo in ((eid, admin_id, "a"),
                                          (outra.id, contas[outra.id], "b"),
                                          (terceira.id, contas[terceira.id], "c")):
        db.add(DispositivoMovel(escola_id=escola_id, usuario_id=usuario_id,
                                plataforma="android",
                                token_push=f"ExponentPushToken[ficticio-boot-{sufixo}]"))
    db.commit()

    assert push.conferir_chave_de_sessao_no_boot(db) == 2
    assert _tokens(db) == {"ExponentPushToken[ficticio-boot-c]"}
    marcas = dict(db.execute(select(Configuracao.escola_id, Configuracao.valor).where(
        Configuracao.namespace == push.NAMESPACE_CHAVE_DE_SESSAO)).all())
    assert set(marcas.values()) == {impressao_da_chave_de_sessao()}
    assert set(marcas) == {eid, outra.id, terceira.id}
    # Repetir (outro worker subindo) não apaga mais nada.
    assert push.conferir_chave_de_sessao_no_boot(db) == 0
    assert db.execute(select(func.count()).select_from(DispositivoMovel)).scalar_one() == 1


def test_impressao_muda_com_a_chave_e_nao_a_revela(monkeypatch):
    sk = _chave("sk0")
    monkeypatch.setattr(settings, "SECRET_KEY", sk)
    primeira = impressao_da_chave_de_sessao()
    assert primeira == impressao_da_chave_de_sessao()
    assert sk not in primeira and len(primeira) == 32
    monkeypatch.setattr(settings, "SECRET_KEY", _chave("sk1"))
    assert impressao_da_chave_de_sessao() != primeira


def test_boot_do_app_tira_os_aparelhos_de_antes_da_troca(sqlite_url):
    """O ``app.main`` (num processo novo, como o uvicorn) confere a chave no boot: o
    aparelho gravado sem impressão — de antes desta conferência, quando a chave pode
    ter sido trocada junto com o deploy — sai, e a impressão da chave nova fica."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    levar_a(sqlite_url, "heads")
    engine = create_engine(sqlite_url)
    try:
        with Session(engine) as s:
            escola = Escola(nome="ESCOLA FICTICIA BOOT", ano_letivo_ativo=2026)
            s.add(escola)
            s.flush()
            u = Usuario(escola_id=escola.id, nome="Coord Ficticia",
                        email="coord.boot@teste.local",
                        senha_hash="hash-ficticio", cargo="coordenador")
            s.add(u)
            s.flush()
            s.add(DispositivoMovel(escola_id=escola.id, usuario_id=u.id,
                                   plataforma="android",
                                   token_push="ExponentPushToken[ficticio-boot-app]"))
            s.commit()
    finally:
        engine.dispose()

    p = rodar(BOOT + "import app.main\nprint('RESULTADO=ok')\n",
              ambiente(sqlite_url, False))
    assert p.returncode == 0 and "RESULTADO=ok" in p.stdout, (
        f"saída {p.returncode}\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")

    engine = create_engine(sqlite_url)
    try:
        with Session(engine) as s:
            assert s.execute(select(func.count()).select_from(DispositivoMovel)
                             ).scalar_one() == 0
            marca = s.execute(select(Configuracao.valor).where(
                Configuracao.namespace == push.NAMESPACE_CHAVE_DE_SESSAO)).scalar_one()
            assert isinstance(marca, str) and len(marca) == 32
    finally:
        engine.dispose()
