"""Redefinir a senha libera o login travado (auditoria técnica, achado AUTH-5).

Antes: quem errava a senha até o limitador travar (8 em 5 min por conta+IP, ou
20 em 15 min por conta) pedia o link, definia a senha nova, lia "Senha
redefinida. Você já pode entrar com a nova senha." e o login com a senha NOVA
respondia 429 até a janela vencer. O mesmo quando o admin definia a senha direto.
Só o login certo zerava os limitadores da conta; a redefinição (que prova a posse
da conta: só quem tem o link ou o admin redefine) não zerava.

Agora a redefinição pelo link, a senha definida pelo admin e a troca da própria
senha zeram os limitadores DA CONTA (por conta e por conta+IP, de qualquer IP).
Os tetos por IP e global não dependem da conta e ficam como estão. Dados 100%
fictícios.
"""
from fastapi.testclient import TestClient
from passlib.hash import bcrypt as bcrypt_rapido

from app.core import rate_limit
from app.main import app
from app.models import Usuario

API = "/api/v1"
EMAIL = "limite.redefinicao@teste.local"
NOVA = "pomar-vela-ilha-64"


def _login(email: str, senha: str, ip: str = "198.51.100.10"):
    return TestClient(app).post(f"{API}/auth/login",
                                data={"username": email, "password": senha},
                                headers={"X-Forwarded-For": ip})


def _professora(db, eid: int, email: str = EMAIL) -> Usuario:
    u = Usuario(escola_id=eid, nome="Professora Limite Ficticia", email=email,
                senha_hash=bcrypt_rapido.using(rounds=4).hash("senha-esquecida-77"),
                cargo="professor")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _travar_por_conta_e_ip(email: str = EMAIL, ip: str = "198.51.100.10") -> None:
    for i in range(8):
        assert _login(email, f"tentativa-errada-{i}", ip).status_code == 401
    assert _login(email, "qualquer-outra-9", ip).status_code == 429


def _redefinir_pelo_link(cliente, eid: int, usuario_id: int, senha: str = NOVA):
    link = cliente.post(f"{API}/escolas/{eid}/usuarios/{usuario_id}/redefinir-senha")
    assert link.status_code == 200, link.text
    r = TestClient(app).post(f"{API}/auth/redefinir-senha",
                             json={"token": link.json()["token"], "nova_senha": senha})
    assert r.status_code == 200, r.text
    assert "já pode entrar" in r.json()["mensagem"]


def test_link_de_redefinicao_libera_o_login_travado(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    prof = _professora(db, eid)
    _travar_por_conta_e_ip()

    _redefinir_pelo_link(cliente, eid, prof.id)

    final = _login(EMAIL, NOVA)
    assert final.status_code == 200, (final.status_code, final.json())


def test_senha_definida_pelo_admin_libera_o_login_travado(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    prof = _professora(db, eid)
    _travar_por_conta_e_ip()

    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{prof.id}", json={"senha": NOVA})
    assert r.status_code == 200, r.text

    final = _login(EMAIL, NOVA)
    assert final.status_code == 200, (final.status_code, final.json())


def test_trocar_a_propria_senha_libera_o_login_travado(cliente, db, escola_completa):
    """O admin troca a PRÓPRIA senha (com a senha atual) depois de errar no login
    em outro aparelho: o login com a senha nova entra."""
    eid = escola_completa["escola"].id
    admin = escola_completa["admin"]
    _travar_por_conta_e_ip("admin@teste.local")

    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{admin.id}",
                      json={"senha": NOVA, "senha_atual": "s3nh4"})
    assert r.status_code == 200, r.text

    final = _login("admin@teste.local", NOVA)
    assert final.status_code == 200, (final.status_code, final.json())


def test_redefinicao_libera_o_teto_por_conta_de_varios_ips(cliente, db, escola_completa):
    """O teto POR CONTA (20 em 15 min, somando IPs) e o de conta+IP de cada IP
    usado: a redefinição libera todos, inclusive num IP novo."""
    eid = escola_completa["escola"].id
    prof = _professora(db, eid)
    ips = ("198.51.100.21", "198.51.100.22", "198.51.100.23")
    for ip, n in zip(ips, (8, 8, 4)):
        for i in range(n):
            assert _login(EMAIL, f"errada-{ip}-{i}", ip).status_code == 401
    assert rate_limit.limitador_conta.bloqueado(rate_limit.identidade_da_conta(prof))
    assert _login(EMAIL, "senha-esquecida-77", "198.51.100.99").status_code == 429

    _redefinir_pelo_link(cliente, eid, prof.id)

    for ip in (*ips, "198.51.100.99"):
        final = _login(EMAIL, NOVA, ip)
        assert final.status_code == 200, (ip, final.status_code, final.json())


def test_redefinicao_nao_libera_outra_conta(cliente, db, escola_completa):
    """Zerar é só da conta redefinida: o travamento de outra conta (mesmo IP)
    continua valendo."""
    eid = escola_completa["escola"].id
    prof = _professora(db, eid)
    _professora(db, eid, email="outra.limite@teste.local")
    _travar_por_conta_e_ip()
    _travar_por_conta_e_ip("outra.limite@teste.local")

    _redefinir_pelo_link(cliente, eid, prof.id)

    assert _login(EMAIL, NOVA).status_code == 200
    assert _login("outra.limite@teste.local", "senha-esquecida-77").status_code == 429


def test_link_recusado_nao_libera_o_login(cliente, db, escola_completa):
    """Sem redefinição de fato (link inválido) os limitadores ficam."""
    eid = escola_completa["escola"].id
    _professora(db, eid)
    _travar_por_conta_e_ip()

    r = TestClient(app).post(f"{API}/auth/redefinir-senha",
                             json={"token": "token-que-nao-existe", "nova_senha": NOVA})
    assert r.status_code == 400, r.text

    assert _login(EMAIL, "senha-esquecida-77").status_code == 429


def test_limpar_prefixo_zera_so_as_chaves_da_conta():
    lim = rate_limit.LimitadorTentativas(max_tentativas=3, janela_s=300)
    for chave in ("a@teste.local|1.1.1.1", "a@teste.local|2.2.2.2",
                  "ab@teste.local|1.1.1.1", "b@teste.local|1.1.1.1"):
        lim.registrar_falha(chave)
    assert lim.limpar_prefixo("a@teste.local|") == 2
    assert set(lim._eventos) == {"ab@teste.local|1.1.1.1", "b@teste.local|1.1.1.1"}
