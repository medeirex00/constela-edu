"""Desativar, excluir e trocar a senha pelo admin REVOGAM sessões e links.

Antes: o PATCH de situação e a exclusão lógica não subiam o ``token_version``
— ao reativar/restaurar a conta, o JWT emitido antes (válido por até 8 h)
voltava a passar. O PATCH de senha subia a versão, mas não matava o link de
redefinição pendente (quem o tivesse sobrescrevia a senha entregue pelo admin),
e o consumo do link só recusava conta excluída — conta inativa aceitava.

Os quatro primeiros testes são as provas do achado com o resultado invertido.
Dados 100% fictícios.
"""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import LogAuditoria, TokenResetSenha, Usuario

SENHA = "s3nh4-forte-1"


def _login(u, s):
    return TestClient(app).post("/api/v1/auth/login", data={"username": u, "password": s})


def _cli(token):
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def _prof(db, escola_id):
    u = Usuario(escola_id=escola_id, nome="Prof Ficticia Quatro", email="p4@teste.local",
                senha_hash=hash_senha(SENHA), cargo="professor")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _consumir(link, nova):
    return TestClient(app).post("/api/v1/auth/redefinir-senha",
                                json={"token": link, "nova_senha": nova})


def _valido(link):
    return TestClient(app).get(f"/api/v1/auth/redefinir-senha/{link}").json()["valido"]


def test_desativar_e_reativar_nao_ressuscita_o_jwt(cliente, db, escola_completa):
    e = escola_completa["escola"]
    p = _prof(db, e.id)
    tok = _login("p4@teste.local", SENHA).json()["access_token"]
    base = f"/api/v1/escolas/{e.id}/usuarios/{p.id}"
    assert cliente.patch(base, json={"status": "inativo"}).status_code == 200
    assert _cli(tok).get("/api/v1/auth/me").status_code == 401
    assert cliente.patch(base, json={"status": "ativo"}).status_code == 200
    assert _cli(tok).get("/api/v1/auth/me").status_code == 401      # o MESMO token segue morto
    # A dona entra de novo com a própria senha e recebe uma sessão nova.
    novo = _login("p4@teste.local", SENHA)
    assert novo.status_code == 200
    assert _cli(novo.json()["access_token"]).get("/api/v1/auth/me").status_code == 200


def test_excluir_e_restaurar_nao_ressuscita_o_jwt(cliente, db, escola_completa):
    e = escola_completa["escola"]
    p = _prof(db, e.id)
    tok = _login("p4@teste.local", SENHA).json()["access_token"]
    base = f"/api/v1/escolas/{e.id}/usuarios/{p.id}"
    assert cliente.delete(base).status_code == 200
    assert _cli(tok).get("/api/v1/auth/me").status_code == 401
    assert cliente.patch(base, json={"status": "ativo"}).status_code == 200
    assert _cli(tok).get("/api/v1/auth/me").status_code == 401
    assert _login("p4@teste.local", SENHA).status_code == 200


def test_senha_definida_pelo_admin_mata_o_link_pendente(cliente, db, escola_completa):
    e = escola_completa["escola"]
    p = _prof(db, e.id)
    base = f"/api/v1/escolas/{e.id}/usuarios/{p.id}"
    link = cliente.post(f"{base}/redefinir-senha").json()["token"]
    assert cliente.patch(base, json={"senha": "entregue-pelo-admin-5"}).status_code == 200
    assert _login("p4@teste.local", "entregue-pelo-admin-5").status_code == 200
    assert _valido(link) is False
    assert _consumir(link, "quem-tinha-o-link-3").status_code == 400
    # A senha entregue pelo admin continua valendo; a do link nunca valeu.
    assert _login("p4@teste.local", "entregue-pelo-admin-5").status_code == 200
    assert _login("p4@teste.local", "quem-tinha-o-link-3").status_code == 401


def test_desativar_mata_o_link_e_a_reativacao_nao_o_devolve(cliente, db, escola_completa):
    e = escola_completa["escola"]
    p = _prof(db, e.id)
    base = f"/api/v1/escolas/{e.id}/usuarios/{p.id}"
    link = cliente.post(f"{base}/redefinir-senha").json()["token"]
    assert cliente.patch(base, json={"status": "inativo"}).status_code == 200
    assert _valido(link) is False
    assert _consumir(link, "quem-tinha-o-link-3").status_code == 400
    assert cliente.patch(base, json={"status": "ativo"}).status_code == 200
    assert _valido(link) is False
    assert _consumir(link, "quem-tinha-o-link-3").status_code == 400
    assert _login("p4@teste.local", "quem-tinha-o-link-3").status_code == 401
    assert _login("p4@teste.local", SENHA).status_code == 200


def test_excluir_mata_o_link_pendente(cliente, db, escola_completa):
    e = escola_completa["escola"]
    p = _prof(db, e.id)
    base = f"/api/v1/escolas/{e.id}/usuarios/{p.id}"
    link = cliente.post(f"{base}/redefinir-senha").json()["token"]
    assert cliente.delete(base).status_code == 200
    db.expire_all()
    assert all(t.usado_em is not None for t in db.execute(
        select(TokenResetSenha).where(TokenResetSenha.usuario_id == p.id)).scalars())
    assert cliente.patch(base, json={"status": "ativo"}).status_code == 200
    assert _valido(link) is False
    assert _consumir(link, "quem-tinha-o-link-3").status_code == 400


def test_link_de_conta_inativa_nao_vale_mesmo_que_escape_da_revogacao(cliente, db, escola_completa):
    """Conferência no consumo, independente da revogação: um link pendente de uma
    conta que ficou inativa por outro caminho (ex.: gravação direta) não vale."""
    e = escola_completa["escola"]
    p = _prof(db, e.id)
    link = cliente.post(f"/api/v1/escolas/{e.id}/usuarios/{p.id}/redefinir-senha").json()["token"]
    p.status = "inativo"
    db.commit()
    assert _valido(link) is False
    assert _consumir(link, "quem-tinha-o-link-3").status_code == 400


def test_nao_gera_link_para_conta_inativa(cliente, db, escola_completa):
    """O link sairia morto (o consumo o recusa e a reativação o invalida)."""
    e = escola_completa["escola"]
    p = _prof(db, e.id)
    base = f"/api/v1/escolas/{e.id}/usuarios/{p.id}"
    assert cliente.patch(base, json={"status": "inativo"}).status_code == 200
    r = cliente.post(f"{base}/redefinir-senha")
    assert r.status_code == 400 and "reative" in r.json()["detail"]
    assert cliente.patch(base, json={"status": "ativo"}).status_code == 200
    link = cliente.post(f"{base}/redefinir-senha")
    assert link.status_code == 200
    assert _consumir(link.json()["token"], "farol-cedro-lua-38").status_code == 200


def test_editar_sem_mudar_situacao_nem_senha_nao_derruba_a_sessao(cliente, db, escola_completa):
    """Renomear, mudar o @ ou mandar a MESMA situação não revoga nada."""
    e = escola_completa["escola"]
    p = _prof(db, e.id)
    tok = _login("p4@teste.local", SENHA).json()["access_token"]
    base = f"/api/v1/escolas/{e.id}/usuarios/{p.id}"
    link = cliente.post(f"{base}/redefinir-senha").json()["token"]
    assert cliente.patch(base, json={"nome": "Prof Ficticia Renomeada"}).status_code == 200
    assert cliente.patch(base, json={"status": "ativo"}).status_code == 200
    assert _cli(tok).get("/api/v1/auth/me").status_code == 200
    assert _valido(link) is True


def test_revogacao_fica_na_auditoria(cliente, db, escola_completa):
    e = escola_completa["escola"]
    p = _prof(db, e.id)
    base = f"/api/v1/escolas/{e.id}/usuarios/{p.id}"
    cliente.post(f"{base}/redefinir-senha")
    assert cliente.patch(base, json={"status": "inativo"}).status_code == 200
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "usuario.desativado",
        LogAuditoria.entidade_id == p.id)).scalars().one()
    assert log.detalhes["sessoes_encerradas"] is True
    assert log.detalhes["links_pendentes_invalidados"] == 1
