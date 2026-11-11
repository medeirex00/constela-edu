"""PEND-31 (MOBILE-1, rota da web) — o painel da escola não finge números para a
Secretaria.

``GET /escolas/{id}/dashboard`` recorta TUDO pelas turmas permitidas, e a lista da
Secretaria é vazia de propósito (ela nunca vê nome de criança). O painel saía 200
com 0 alunos, 0 turmas, média 0,0 e 0 livros, como se fossem os números da escola.
Nenhuma tela usa esse painel para ela (a web a leva ao Panorama da Rede e o app já
responde 403 em ``/sincronizacao``): a rota passa a responder 403 com a explicação,
como o pacote do app. Dados 100% fictícios.
"""
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Rede, Usuario

API = "/api/v1"


def _login(email, senha="s3nh4"):
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _secretaria(db, escola):
    rede = Rede(nome="Rede Inventada Painel Secretaria", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(Usuario(nome="Secretaria Inventada", email="sec.painel@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador", rede_id=rede.id))
    db.commit()
    return _login("sec.painel@teste.local")


def test_secretaria_recebe_403_explicado_no_painel_da_escola(db, escola_completa):
    escola = escola_completa["escola"]
    sec = _secretaria(db, escola)
    r = sec.get(f"{API}/escolas/{escola.id}/dashboard")
    assert r.status_code == 403, r.text
    assert "Panorama da Rede" in r.json()["detail"]


def test_gestao_da_escola_segue_com_o_painel(db, escola_completa, cliente, cliente_global):
    escola = escola_completa["escola"]
    _secretaria(db, escola)
    for quem in (cliente, cliente_global):
        r = quem.get(f"{API}/escolas/{escola.id}/dashboard")
        assert r.status_code == 200, r.text
        assert r.json()["total_alunos"] == 3
