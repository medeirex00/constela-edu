"""Trocar a PRÓPRIA senha exige a senha atual (reautenticação).

Antes, quem achasse uma sessão aberta (computador compartilhado da sala dos
professores, sem "Sair") gerava o link de redefinição da própria dona da sessão
ou, sendo admin, trocava a senha pelo PATCH — sem saber a senha atual. A troca
derrubava a sessão da dona e o invasor ficava com credencial própria: as 8 h do
token viravam posse permanente da conta.

Agora as duas rotas pedem ``senha_atual`` quando o alvo é quem pede; as falhas
contam no limitador da CONTA (o mesmo do login). Dados 100% fictícios.
"""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import rate_limit
from app.core.security import hash_senha
from app.main import app
from app.models import LogAuditoria, TokenResetSenha, Usuario

SENHA = "s3nh4-forte-1"


def _login(usuario: str, senha: str):
    return TestClient(app).post("/api/v1/auth/login",
                                data={"username": usuario, "password": senha})


def _cli(usuario: str, senha: str) -> TestClient:
    r = _login(usuario, senha)
    assert r.status_code == 200, r.text
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _conta(db, escola_id, email, cargo, senha=SENHA):
    u = Usuario(escola_id=escola_id, nome=f"Pessoa Ficticia {cargo}", email=email,
                senha_hash=hash_senha(senha), cargo=cargo)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _link(cli, escola_id, alvo_id, **corpo):
    return cli.post(f"/api/v1/escolas/{escola_id}/usuarios/{alvo_id}/redefinir-senha",
                    **({"json": corpo} if corpo else {}))


def test_sessao_sozinha_nao_gera_o_link_da_propria_conta(db, escola_completa):
    """A prova do achado, invertida: só com o Bearer, o link para si é recusado;
    a senha da dona continua valendo e a sessão dela não cai."""
    e = escola_completa["escola"]
    p = _conta(db, e.id, "prof.x@teste.local", "professor")
    sessao = _cli("prof.x@teste.local", SENHA)

    sem = _link(sessao, e.id, p.id)
    assert sem.status_code == 422, sem.text
    assert "token" not in sem.json()
    errada = _link(sessao, e.id, p.id, senha_atual="chute-errado-1")
    assert errada.status_code == 403
    assert "token" not in errada.json()

    assert db.execute(select(TokenResetSenha)
                      .where(TokenResetSenha.usuario_id == p.id)).first() is None
    assert sessao.get("/api/v1/auth/me").status_code == 200
    assert _login("prof.x@teste.local", SENHA).status_code == 200


def test_com_a_senha_atual_o_link_para_si_continua_funcionando(db, escola_completa):
    e = escola_completa["escola"]
    p = _conta(db, e.id, "prof.x@teste.local", "professor")
    sessao = _cli("prof.x@teste.local", SENHA)
    g = _link(sessao, e.id, p.id, senha_atual=SENHA)
    assert g.status_code == 200, g.text
    troca = TestClient(app).post("/api/v1/auth/redefinir-senha",
                                 json={"token": g.json()["token"], "nova_senha": "farol-cedro-lua-38"})
    assert troca.status_code == 200, troca.text
    assert _login("prof.x@teste.local", "farol-cedro-lua-38").status_code == 200


def test_link_para_outra_pessoa_nao_pede_senha_atual(db, escola_completa):
    """A matriz de quem gera para quem não muda: coordenador → professor, sem corpo."""
    e = escola_completa["escola"]
    _conta(db, e.id, "coord.x@teste.local", "coordenador")
    prof = _conta(db, e.id, "prof.y@teste.local", "professor")
    coord = _cli("coord.x@teste.local", SENHA)
    g = _link(coord, e.id, prof.id)
    assert g.status_code == 200 and g.json()["token"]


def test_admin_troca_a_propria_senha_so_com_a_senha_atual(cliente, db, escola_completa):
    e = escola_completa["escola"]
    admin = escola_completa["admin"]
    url = f"/api/v1/escolas/{e.id}/usuarios/{admin.id}"

    assert cliente.patch(url, json={"senha": "outra-do-admin-5"}).status_code == 422
    assert cliente.patch(url, json={"senha": "outra-do-admin-5",
                                    "senha_atual": "errada-123x"}).status_code == 403
    # Nada mudou: a senha antiga vale e a sessão continua de pé.
    assert cliente.get("/api/v1/auth/me").status_code == 200
    assert _login("admin@teste.local", "s3nh4").status_code == 200

    ok = cliente.patch(url, json={"senha": "outra-do-admin-5", "senha_atual": "s3nh4"})
    assert ok.status_code == 200, ok.text
    assert _login("admin@teste.local", "outra-do-admin-5").status_code == 200
    assert _login("admin@teste.local", "s3nh4").status_code == 401
    # A senha atual nunca vai para a auditoria.
    for log in db.execute(select(LogAuditoria)).scalars():
        assert "s3nh4" not in str(log.detalhes) and "outra-do-admin-5" not in str(log.detalhes)


def test_admin_edita_a_propria_conta_sem_senha_sem_reautenticar(cliente, escola_completa):
    """Só a troca de SENHA pede a atual: nome/@ da própria conta seguem livres."""
    e = escola_completa["escola"]
    admin = escola_completa["admin"]
    r = cliente.patch(f"/api/v1/escolas/{e.id}/usuarios/{admin.id}", json={"nome": "Admin Renomeado"})
    assert r.status_code == 200, r.text


def test_admin_define_a_senha_de_outra_conta_sem_senha_atual(cliente, db, escola_completa):
    e = escola_completa["escola"]
    p = _conta(db, e.id, "prof.z@teste.local", "professor")
    r = cliente.patch(f"/api/v1/escolas/{e.id}/usuarios/{p.id}", json={"senha": "entregue-pelo-admin-5"})
    assert r.status_code == 200, r.text


def test_falhas_contam_no_limitador_da_conta_e_nao_abrem_oraculo(db, escola_completa):
    """As falhas da reautenticação somam no MESMO teto por conta do /auth/login:
    estourado, a rota responde 429 sem conferir (nem a senha certa passa) e o
    login da conta também fica barrado."""
    e = escola_completa["escola"]
    p = _conta(db, e.id, "prof.x@teste.local", "professor")
    sessao = _cli("prof.x@teste.local", SENHA)
    teto = rate_limit.limitador_conta.max_tentativas
    for _ in range(teto - 3):                       # falhas anteriores (ex.: login)
        rate_limit.limitador_conta.registrar_falha(rate_limit.identidade_da_conta(p))
    for _ in range(3):
        assert _link(sessao, e.id, p.id, senha_atual="chute-errado-1").status_code == 403
    assert _link(sessao, e.id, p.id, senha_atual=SENHA).status_code == 429
    assert _login("prof.x@teste.local", SENHA).status_code == 401
    logs = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "usuario.reautenticacao_falhou")).scalars().all()
    assert len(logs) == 3
    assert all("chute-errado-1" not in str(log.detalhes) for log in logs)
