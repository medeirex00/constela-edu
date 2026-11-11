"""Teto de falhas por IP e global do /auth/login com RESERVA antes da avaliação
(G_CARGA-3).

Antes o teto era conferido no começo do login e a falha contada no fim: numa rajada de
logins simultâneos de um IP só, todo pedido que passava pela conferência antes de a 50ª
falha ser gravada seguia até o bcrypt (108 palpites avaliados com 2 workers). Agora a
tentativa é reservada no banco antes de procurar a conta — conferir e somar numa
instrução atômica só — e devolvida se não virar falha: o teto vale para logins
simultâneos e entre workers, e só falhas continuam contando.

A prova com logins simultâneos num PostgreSQL real está em
``test_aud2_auth2_login_rajada_pg.py``. Aqui (SQLite) as regras da reserva. Contas e IPs
fictícios; bcrypt de custo 4 só para o teste andar rápido."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from passlib.hash import bcrypt as bcrypt_rapido
from sqlalchemy import event, select

from app.core import rate_limit
from app.core.rate_limit import LimitadorTentativas
from app.main import app
from app.models import Usuario
from app.quest.models import QuestLimiteAcesso
from app.quest.services import limites
from app.routers import auth as auth_router

URL = "/api/v1/auth/login"
SENHA = "Reserva#Certa2026"
ERRADA = "Reserva#Errada2026"
IP = "198.51.100.61"


@pytest.fixture()
def contas(db, escola_completa):
    h = bcrypt_rapido.using(rounds=4).hash(SENHA)
    emails = [f"reserva{i}@teste.local" for i in range(6)]
    for i, email in enumerate(emails):
        db.add(Usuario(escola_id=escola_completa["escola"].id, nome=f"Prof Reserva {i}",
                       email=email, username=f"ProfReserva{i}", senha_hash=h,
                       cargo="professor"))
    db.commit()
    return emails


def _login(usuario: str, senha: str, ip: str = IP, **kw):
    return TestClient(app, **kw).post(URL, data={"username": usuario, "password": senha},
                                      headers={"X-Forwarded-For": ip})


def _falhas(db) -> dict[str, int]:
    db.expire_all()
    return {chave.split(":", 1)[0]: falhas for chave, falhas in db.execute(
        select(QuestLimiteAcesso.chave, QuestLimiteAcesso.falhas))}


def _reiniciar_processo() -> None:
    for lim in (rate_limit.limitador_login, rate_limit.limitador_conta,
                rate_limit.limitador_ip_falha_login,
                rate_limit.limitador_global_falha_login):
        lim._eventos.clear()


# --- O serviço ------------------------------------------------------------------

def test_tentativa_em_andamento_ocupa_a_vaga_e_a_recusa_nao_soma(db):
    ip = limites.Limite("teste_ip:a", 3, 300)
    glob = limites.Limite("teste_global:a", 100, 300)
    reservas = [limites.reservar(db, [ip, glob]) for _ in range(3)]
    assert all(r.aceita for r in reservas)
    assert [r.falhas("teste_ip:a") for r in reservas] == [1, 2, 3]

    # A 4ª chega com as 3 ainda em andamento: recusada, e não gasta o global.
    quarta = limites.reservar(db, [ip, glob])
    assert not quarta.aceita and quarta.tomadas == ()
    assert 299 <= quarta.espera("teste_ip:a") <= 300
    assert quarta.espera("teste_global:a") is None
    assert _falhas(db) == {"teste_ip": 3, "teste_global": 3}
    assert limites.bloqueado(db, ["teste_ip:a"])

    # Uma das 3 era login certo: a vaga volta e o bloqueio sai.
    limites.devolver(db, reservas[0])
    assert _falhas(db) == {"teste_ip": 2, "teste_global": 2}
    assert not limites.bloqueado(db, ["teste_ip:a"])
    assert limites.reservar(db, [ip, glob]).aceita


def test_devolucao_so_vale_na_janela_em_que_a_vaga_foi_tomada(db, monkeypatch):
    ip = limites.Limite("teste_ip:b", 5, 300)
    antiga = limites.reservar(db, [ip])
    depois = limites._agora() + timedelta(seconds=301)
    monkeypatch.setattr(limites, "_agora", lambda: depois)
    assert limites.reservar(db, [ip]).falhas("teste_ip:b") == 1   # janela nova
    limites.devolver(db, antiga)
    assert _falhas(db) == {"teste_ip": 1}


def test_bloquear_por_vale_como_falhas_e_nunca_encurta():
    lim = LimitadorTentativas(max_tentativas=3, janela_s=300)
    lim.bloquear_por("x", 120)
    assert lim.bloqueado("x")
    assert 119 <= lim.segundos_restantes("x") <= 120
    lim.bloquear_por("x", 30)                   # não encurta
    assert lim.segundos_restantes("x") >= 119
    lim.bloquear_por("y", 10_000)               # no máximo a janela
    assert lim.segundos_restantes("y") <= 300


# --- O login ----------------------------------------------------------------------

def test_so_falhas_ficam_contadas_no_banco(db, contas):
    assert _login(contas[0], SENHA).status_code == 200
    assert _falhas(db) == {"edu_login_ip_falha": 0, "edu_login_global_falha": 0}
    assert _login(contas[0], ERRADA).status_code == 401
    assert _login("ninguem.reserva@teste.local", ERRADA).status_code == 401
    assert _falhas(db) == {"edu_login_ip_falha": 2, "edu_login_global_falha": 2}


def test_recusas_que_nao_sao_palpite_devolvem_a_vaga(db, contas, monkeypatch):
    # Conta desativada: a senha confere, não é palpite errado.
    db.execute(Usuario.__table__.update().where(Usuario.email == contas[1])
               .values(status="inativo"))
    db.commit()
    assert _login(contas[1], SENHA).status_code == 403
    # 429 do limite por (conta, IP): não chega a avaliar a senha.
    monkeypatch.setattr(rate_limit.limitador_login, "max_tentativas", 1)
    assert _login(contas[2], ERRADA).status_code == 401
    assert _login(contas[2], ERRADA).status_code == 429
    assert _falhas(db) == {"edu_login_ip_falha": 1, "edu_login_global_falha": 1}


def test_erro_inesperado_devolve_a_vaga(db, contas, monkeypatch):
    assert _login(contas[0], ERRADA).status_code == 401

    def _quebra(*_a, **_k):
        raise RuntimeError("falha inventada no meio do login")

    monkeypatch.setattr(auth_router, "_avaliar", _quebra)
    assert _login(contas[0], SENHA, raise_server_exceptions=False).status_code == 500
    assert _falhas(db) == {"edu_login_ip_falha": 1, "edu_login_global_falha": 1}


def test_bloqueio_visto_no_banco_passa_a_valer_na_memoria(db, contas, monkeypatch):
    """Outro worker contou as falhas: a reserva é recusada no banco, a espera
    anunciada é a do banco, e a memória deste processo aprende o bloqueio — as
    tentativas seguintes param nela, sem ir ao banco. O IP bloqueado não gasta o teto
    global."""
    monkeypatch.setattr(rate_limit.limitador_ip_falha_login, "max_tentativas", 3)
    for email in contas[:3]:
        assert _login(email, ERRADA).status_code == 401
    _reiniciar_processo()                                  # "outro worker"

    r = _login(contas[3], SENHA)
    assert r.status_code == 429
    assert r.json()["detail"] == "Muitas tentativas. Aguarde 5 minuto(s) e tente novamente."
    assert rate_limit.limitador_ip_falha_login.bloqueado(IP)

    consultas: list[str] = []

    def _anotar(conn, cursor, sql, params, context, executemany):
        consultas.append(sql.lower())

    motor = db.get_bind()
    event.listen(motor, "before_cursor_execute", _anotar)
    try:
        assert _login(contas[4], SENHA).status_code == 429
    finally:
        event.remove(motor, "before_cursor_execute", _anotar)
    assert not [s for s in consultas if "quest_limites_acesso" in s], consultas
    assert _falhas(db) == {"edu_login_ip_falha": 3, "edu_login_global_falha": 3}
    # Outro IP segue entrando.
    assert _login(contas[4], SENHA, ip="203.0.113.61").status_code == 200


def test_banco_sem_resposta_a_tempo_vale_so_a_memoria(db, contas, monkeypatch):
    """A linha presa além do prazo (``LimiteIndisponivel``): o login segue, a falha
    fica só na memória deste processo e nada é devolvido no banco."""
    def _ocupado(*_a, **_k):
        raise limites.LimiteIndisponivel("linha presa (simulado)")

    monkeypatch.setattr(limites, "reservar", _ocupado)
    devolucoes: list = []
    monkeypatch.setattr(limites, "devolver", lambda *a, **k: devolucoes.append(a))
    assert _login(contas[0], ERRADA).status_code == 401
    assert _login(contas[0], SENHA).status_code == 200
    assert rate_limit.limitador_ip_falha_login.falhas_na_janela(IP) == 1
    assert _falhas(db) == {}
    assert devolucoes == []
