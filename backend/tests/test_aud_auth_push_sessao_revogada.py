"""Trocar ou redefinir a senha derruba também o push do aparelho (auditoria
técnica, achado AUTH-1).

Antes: a troca de senha pelo admin (PATCH com ``senha``) e a redefinição pelo
link subiam o ``token_version`` — a sessão do celular caía em 401 —, mas o
aparelho seguia cadastrado para a conta, que continua ativa. ``notificar_escola``
filtra só pela situação da conta, então o celular perdido (ou da sessão
roubada) seguia mostrando "Novos dados…" e o primeiro nome da criança na tela
bloqueada. O app não consegue se descadastrar: a próxima chamada dele dá 401.

Agora toda substituição de senha apaga os aparelhos da conta junto com as
sessões e conta ``dispositivos_removidos`` na auditoria. O app registra o
aparelho de novo no próximo login. O envio ao Expo é trocado por uma captura
(sem rede). Dados 100% fictícios.
"""
import pytest
from fastapi.testclient import TestClient
from passlib.hash import bcrypt as bcrypt_rapido
from sqlalchemy import func, select

from app.main import app
from app.models import DispositivoMovel, LogAuditoria, Usuario
from app.services import push

API = "/api/v1"
EMAIL = "prof.revogada@teste.local"
SENHA = "Senha-Prof-Revogada-9"
NOVA = "pomar-vela-ilha-64"
TOKEN_PROF = "ExponentPushToken[ficticio-revogada-0001]"
TOKEN_ADMIN = "ExponentPushToken[ficticio-admin-revogada-0001]"


@pytest.fixture()
def capturados(monkeypatch):
    enviados: list[str] = []

    def _falso(lotes):
        for lote in lotes:
            enviados.extend(m["to"] for m in lote)
        return []

    monkeypatch.setattr(push, "_enviar_lotes", _falso)
    return enviados


def _login(email: str, senha: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _registrar(sessao: TestClient, eid: int, token: str) -> None:
    r = sessao.post(f"{API}/escolas/{eid}/dispositivos",
                    json={"token_push": token, "plataforma": "android"})
    assert r.status_code == 200, r.text


def _professora_com_aparelho(db, eid: int):
    prof = Usuario(escola_id=eid, nome="Professora Revogada Ficticia", email=EMAIL,
                   senha_hash=bcrypt_rapido.using(rounds=4).hash(SENHA),
                   cargo="professor")
    db.add(prof)
    db.commit()
    sessao = _login(EMAIL, SENHA)
    _registrar(sessao, eid, TOKEN_PROF)
    return prof.id, sessao


def _aparelhos(db, usuario_id: int) -> int:
    db.expire_all()
    return db.execute(select(func.count()).select_from(DispositivoMovel)
                      .where(DispositivoMovel.usuario_id == usuario_id)).scalar_one()


def _auditoria(db, acao: str, entidade_id: int) -> dict:
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == acao, LogAuditoria.entidade_id == entidade_id)
        .order_by(LogAuditoria.id.desc())).scalars().first()
    assert log is not None, acao
    return log.detalhes


def _gerar_link(cliente, eid: int, usuario_id: int) -> str:
    r = cliente.post(f"{API}/escolas/{eid}/usuarios/{usuario_id}/redefinir-senha")
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_senha_trocada_pelo_admin_apaga_o_aparelho(cliente, db, escola_completa,
                                                    capturados):
    eid = escola_completa["escola"].id
    prof_id, sessao = _professora_com_aparelho(db, eid)
    _registrar(cliente, eid, TOKEN_ADMIN)

    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{prof_id}", json={"senha": NOVA})
    assert r.status_code == 200, r.text
    assert sessao.get(f"{API}/auth/me").status_code == 401

    assert _aparelhos(db, prof_id) == 0
    assert _auditoria(db, "usuario.senha_redefinida", prof_id)["dispositivos_removidos"] == 1
    push.notificar_escola(db, eid, "Novos dados no Constela Edu",
                          push.corpo_dados_atualizados("Ana Beatriz Souza"))
    assert capturados == [TOKEN_ADMIN]          # o envio aconteceu; o dela não


def test_senha_redefinida_pelo_link_apaga_o_aparelho(cliente, db, escola_completa,
                                                     capturados):
    eid = escola_completa["escola"].id
    prof_id, sessao = _professora_com_aparelho(db, eid)
    _registrar(cliente, eid, TOKEN_ADMIN)
    token = _gerar_link(cliente, eid, prof_id)

    r = TestClient(app).post(f"{API}/auth/redefinir-senha",
                             json={"token": token, "nova_senha": NOVA})
    assert r.status_code == 200, r.text
    assert sessao.get(f"{API}/auth/me").status_code == 401

    assert _aparelhos(db, prof_id) == 0
    assert _auditoria(db, "usuario.senha_redefinida_por_token",
                      prof_id)["dispositivos_removidos"] == 1
    push.notificar_escola(db, eid, "Novos dados no Constela Edu",
                          push.corpo_dados_atualizados("Ana Beatriz Souza"))
    assert capturados == [TOKEN_ADMIN]


def test_novo_login_registra_o_aparelho_de_novo(cliente, db, escola_completa, capturados):
    """A dona legítima não perde nada: ao entrar com a senha nova, o app registra
    o aparelho de novo e os avisos voltam."""
    eid = escola_completa["escola"].id
    prof_id, _ = _professora_com_aparelho(db, eid)
    token = _gerar_link(cliente, eid, prof_id)
    assert TestClient(app).post(f"{API}/auth/redefinir-senha",
                                json={"token": token, "nova_senha": NOVA}).status_code == 200

    _registrar(_login(EMAIL, NOVA), eid, TOKEN_PROF)

    assert _aparelhos(db, prof_id) == 1
    push.notificar_escola(db, eid, titulo="t", corpo="c")
    assert TOKEN_PROF in capturados


def test_trocar_a_propria_senha_apaga_os_proprios_aparelhos(cliente, db, escola_completa,
                                                            capturados):
    """A troca da própria senha também derruba as próprias sessões (o admin entra
    de novo com a senha nova): os aparelhos dele saem junto."""
    eid = escola_completa["escola"].id
    admin = escola_completa["admin"]
    _registrar(cliente, eid, TOKEN_ADMIN)

    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{admin.id}",
                      json={"senha": NOVA, "senha_atual": "s3nh4"})
    assert r.status_code == 200, r.text

    assert _aparelhos(db, admin.id) == 0
    push.notificar_escola(db, eid, titulo="t", corpo="c")
    assert TOKEN_ADMIN not in capturados


def test_link_recusado_nao_apaga_o_aparelho(cliente, db, escola_completa, capturados):
    """Sem troca de senha de fato (a senha nova é recusada), nada é gravado: a
    sessão e o aparelho ficam."""
    eid = escola_completa["escola"].id
    prof_id, sessao = _professora_com_aparelho(db, eid)
    token = _gerar_link(cliente, eid, prof_id)

    r = TestClient(app).post(f"{API}/auth/redefinir-senha",
                             json={"token": token, "nova_senha": "prof.revogada"})
    assert r.status_code == 422, r.text

    assert sessao.get(f"{API}/auth/me").status_code == 200
    assert _aparelhos(db, prof_id) == 1


def test_mudar_so_o_nome_nao_apaga_o_aparelho(cliente, db, escola_completa, capturados):
    """Edição que não revoga sessão (nome) não mexe no aparelho."""
    eid = escola_completa["escola"].id
    prof_id, sessao = _professora_com_aparelho(db, eid)

    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{prof_id}",
                      json={"nome": "Professora Revogada Ficticia Souza"})
    assert r.status_code == 200, r.text

    assert sessao.get(f"{API}/auth/me").status_code == 200
    assert _aparelhos(db, prof_id) == 1
