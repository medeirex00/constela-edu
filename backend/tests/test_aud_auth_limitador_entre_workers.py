"""A senha substituída libera o login em TODOS os processos da API (revisão
adversarial, REV-AUTH-1 e REV-AUTH-2; achados de origem AUTH-5 e AUTH-4).

Os limites por conta e por (conta, IP) do /auth/login vivem na memória de cada
processo, e a produção sobe a API com mais de um (``uvicorn --workers``,
backend/entrypoint.sh). A redefinição zerava só a memória do processo que a
atendeu: a tela dizia "Você já pode entrar", e o login com a senha NOVA recebia
429 sempre que caía no outro processo, até a janela vencer. "Padronizar @" e
"Corrigir professores duplicados" entregam @ e senha novos na folha e não
zeravam nada: com o e-mail real mantido (AUTH-4), a credencial da folha herdava
o travamento da conta.

Agora a chave dos limitadores de uma conta que EXISTE leva a versão da sessão
(``token_version``), lida do banco a cada login. Toda substituição de senha sobe
essa versão na mesma transação, então todo processo passa a contar numa chave
nova e o travamento antigo deixa de valer em qualquer um deles.

O "outro processo" é simulado guardando a memória dos limitadores antes da
troca e repondo-a depois (como se o login seguinte caísse num processo que não
viu a troca). Dados 100% fictícios.
"""
from collections import deque

from fastapi.testclient import TestClient
from passlib.hash import bcrypt as bcrypt_rapido
from sqlalchemy import select

from app.core import rate_limit
from app.main import app
from app.models import LogAuditoria, Usuario

API = "/api/v1"
EMAIL = "limite.workers@teste.local"
ANTIGA = "senha-esquecida-77"
NOVA = "pomar-vela-ilha-64"
IP = "198.51.100.60"


def _login(usuario: str, senha: str, ip: str = IP):
    return TestClient(app).post(f"{API}/auth/login",
                                data={"username": usuario, "password": senha},
                                headers={"X-Forwarded-For": ip})


def _professora(db, eid: int, email: str = EMAIL) -> Usuario:
    u = Usuario(escola_id=eid, nome="Professora Workers Ficticia", email=email,
                senha_hash=bcrypt_rapido.using(rounds=4).hash(ANTIGA),
                cargo="professor")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _travar(usuario: str = EMAIL, ip: str = IP) -> None:
    for i in range(8):
        assert _login(usuario, f"tentativa-errada-{i}", ip).status_code == 401
    assert _login(usuario, "qualquer-outra-9", ip).status_code == 429


class _OutroProcesso:
    """A memória dos limitadores por conta e por (conta, IP) de um segundo
    processo da API, que contou as mesmas falhas e NÃO atendeu a troca."""

    _LIMITADORES = (rate_limit.limitador_login, rate_limit.limitador_conta)

    def __init__(self) -> None:
        self._memoria = {lim: {k: deque(v) for k, v in lim._eventos.items()}
                         for lim in self._LIMITADORES}

    def atende_o_proximo_pedido(self) -> None:
        for lim, eventos in self._memoria.items():
            lim._eventos.clear()
            lim._eventos.update({k: deque(v) for k, v in eventos.items()})


def _link(cliente, eid: int, usuario_id: int) -> str:
    r = cliente.post(f"{API}/escolas/{eid}/usuarios/{usuario_id}/redefinir-senha")
    assert r.status_code == 200, r.text
    return r.json()["token"]


# --- REV-AUTH-1: a liberação vale no processo que não atendeu a troca ----------

def test_link_de_redefinicao_libera_o_login_no_outro_processo(
        cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    prof = _professora(db, eid)
    _travar()
    outro = _OutroProcesso()

    token = _link(cliente, eid, prof.id)
    r = TestClient(app).post(f"{API}/auth/redefinir-senha",
                             json={"token": token, "nova_senha": NOVA})
    assert r.status_code == 200, r.text
    assert "já pode entrar" in r.json()["mensagem"]

    outro.atende_o_proximo_pedido()
    final = _login(EMAIL, NOVA)
    assert final.status_code == 200, (final.status_code, final.json())


def test_senha_definida_pelo_admin_libera_o_login_no_outro_processo(
        cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    prof = _professora(db, eid)
    _travar()
    outro = _OutroProcesso()

    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{prof.id}", json={"senha": NOVA})
    assert r.status_code == 200, r.text

    outro.atende_o_proximo_pedido()
    final = _login(EMAIL, NOVA)
    assert final.status_code == 200, (final.status_code, final.json())


def test_trocar_a_propria_senha_libera_o_login_no_outro_processo(
        cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    admin = escola_completa["admin"]
    _travar("admin@teste.local")
    outro = _OutroProcesso()

    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{admin.id}",
                      json={"senha": NOVA, "senha_atual": "s3nh4"})
    assert r.status_code == 200, r.text

    outro.atende_o_proximo_pedido()
    final = _login("admin@teste.local", NOVA)
    assert final.status_code == 200, (final.status_code, final.json())


def test_teto_por_conta_de_varios_ips_libera_no_outro_processo(
        cliente, db, escola_completa):
    """20 erros somando três IPs (o teto POR CONTA): depois do link, o outro
    processo deixa entrar em todos os IPs, inclusive num novo."""
    eid = escola_completa["escola"].id
    prof = _professora(db, eid)
    ips = ("198.51.100.61", "198.51.100.62", "198.51.100.63")
    for ip, n in zip(ips, (8, 8, 4)):
        for i in range(n):
            assert _login(EMAIL, f"errada-{ip}-{i}", ip).status_code == 401
    assert _login(EMAIL, ANTIGA, "198.51.100.69").status_code == 429
    outro = _OutroProcesso()

    token = _link(cliente, eid, prof.id)
    r = TestClient(app).post(f"{API}/auth/redefinir-senha",
                             json={"token": token, "nova_senha": NOVA})
    assert r.status_code == 200, r.text

    for ip in (*ips, "198.51.100.69"):
        outro.atende_o_proximo_pedido()
        final = _login(EMAIL, NOVA, ip)
        assert final.status_code == 200, (ip, final.status_code, final.json())


def test_sem_troca_de_senha_o_travamento_continua_no_outro_processo(
        cliente, db, escola_completa):
    """O que NÃO substitui a senha (link recusado, outra conta trocada) não mexe
    no travamento da conta: a força bruta segue barrada."""
    eid = escola_completa["escola"].id
    _professora(db, eid)
    outra = _professora(db, eid, email="outra.workers@teste.local")
    _travar()
    outro = _OutroProcesso()

    recusado = TestClient(app).post(f"{API}/auth/redefinir-senha",
                                    json={"token": "token-que-nao-existe",
                                          "nova_senha": NOVA})
    assert recusado.status_code == 400, recusado.text
    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{outra.id}", json={"senha": NOVA})
    assert r.status_code == 200, r.text

    outro.atende_o_proximo_pedido()
    assert _login(EMAIL, ANTIGA).status_code == 429


def test_reautenticacao_e_login_seguem_no_mesmo_teto_por_conta(
        db, escola_completa):
    """As falhas da senha atual (trocar a própria senha) e as do login somam no
    MESMO teto por conta: 17 erros no login (três IPs) + 3 na reautenticação
    estouram os 20, e nem a senha certa passa em nenhuma das duas rotas."""
    eid = escola_completa["escola"].id
    prof = _professora(db, eid)
    r = _login(EMAIL, ANTIGA, "198.51.100.70")
    assert r.status_code == 200, r.text
    sessao = TestClient(app)
    sessao.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    for ip, n in (("198.51.100.71", 8), ("198.51.100.72", 8), ("198.51.100.73", 1)):
        for i in range(n):
            assert _login(EMAIL, f"errada-{ip}-{i}", ip).status_code == 401
    url = f"{API}/escolas/{eid}/usuarios/{prof.id}/redefinir-senha"
    for _ in range(3):
        assert sessao.post(url, json={"senha_atual": "chute-errado-1"}).status_code == 403
    assert sessao.post(url, json={"senha_atual": ANTIGA}).status_code == 429
    assert _login(EMAIL, ANTIGA, "198.51.100.74").status_code == 429


def test_log_do_login_continua_com_o_email(db, escola_completa):
    """A versão da sessão entra só na chave do limitador: o log de auditoria
    segue gravando o e-mail da conta."""
    _professora(db, escola_completa["escola"].id)
    _travar()
    logs = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao.in_(("login.falhou", "login.bloqueado")))).scalars().all()
    assert {log.acao for log in logs} == {"login.falhou", "login.bloqueado"}
    assert {log.detalhes["email"] for log in logs} == {EMAIL}


def test_conta_inexistente_segue_travando_pelo_texto_digitado(db, escola_completa):
    _travar("ninguem.workers@teste.local")


# --- REV-AUTH-2: a credencial da folha entra mesmo com o login travado ---------

def _cadastro_completo(cliente, eid: int, nome: str, email: str) -> None:
    r = cliente.post(f"{API}/escolas/{eid}/professores/completo",
                     json={"nome": nome, "email": email})
    assert r.status_code == 201, r.text


def _linha(folha: list[dict], nome: str) -> dict:
    linhas = [f for f in folha if f["nome"] == nome]
    assert len(linhas) == 1, folha
    return linhas[0]


def test_padronizar_entrega_credencial_que_entra_mesmo_com_login_travado(
        cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    email = "travada.workers@escola-ficticia.com.br"
    _cadastro_completo(cliente, eid, "Travada Workers Ficticia", email)
    _travar(email)
    outro = _OutroProcesso()

    r = cliente.post(f"{API}/escolas/{eid}/professores/padronizar-usuarios")
    assert r.status_code == 200, r.text
    linha = _linha(r.json()["folha"], "Travada Workers Ficticia")
    assert linha["senha"], "a conta nunca usada deveria ganhar senha nova"
    db.expire_all()
    conta = db.execute(select(Usuario).where(
        Usuario.username == linha["usuario"])).scalar_one()
    assert conta.email == email                 # e-mail real mantido (AUTH-4)

    final = _login(linha["usuario"], linha["senha"])
    assert final.status_code == 200, (final.status_code, final.json())
    outro.atende_o_proximo_pedido()
    final = _login(email, linha["senha"])
    assert final.status_code == 200, (final.status_code, final.json())


def test_corrigir_duplicados_entrega_credencial_que_entra_mesmo_com_login_travado(
        cliente, db, escola_completa):
    from app.core.security import hash_senha
    from app.models import Professor

    eid = escola_completa["escola"].id
    email = "presa.workers@escola-ficticia.com.br"
    _cadastro_completo(cliente, eid, "Presa Workers Ficticia", email)
    curto = Professor(escola_id=eid, nome="Presa",
                      email="presa@professor.constelaedu.com")
    db.add(curto)
    db.add(Usuario(escola_id=eid, nome="Presa", email="presa@professor.constelaedu.com",
                   username="Presa", senha_hash=hash_senha("x"), cargo="professor"))
    db.commit()
    _travar(email)
    outro = _OutroProcesso()

    r = cliente.post(f"{API}/escolas/{eid}/professores/duplicados/corrigir",
                     json={"loser_ids": [curto.id]})
    assert r.status_code == 200, r.text
    linha = _linha(r.json()["folha"], "Presa Workers Ficticia")
    assert linha["senha"], "a conta nunca usada deveria ganhar senha nova"

    final = _login(linha["usuario"], linha["senha"])
    assert final.status_code == 200, (final.status_code, final.json())
    outro.atende_o_proximo_pedido()
    final = _login(email, linha["senha"])
    assert final.status_code == 200, (final.status_code, final.json())
