"""O 429 do login diz o tempo do bloqueio que de fato vale (auditoria técnica,
achado AUTH-6).

Antes: a espera do "Aguarde N minuto(s)" era o MAIOR ``segundos_restantes`` dos
dois limitadores da conta — inclusive o que NÃO estava bloqueando, porque
``segundos_restantes`` devolvia "janela − idade do evento mais antigo" mesmo
abaixo do teto. Com 8 erros só o teto por conta+IP (5 min) bloqueia, mas o por
conta (20 em 15 min, com os mesmos 8 eventos) dominava: a tela mandava esperar
15 minutos e o acesso voltava em 5.

Agora ``segundos_restantes`` é o tempo até a chave deixar de estar bloqueada (0
quando não está). Relógio dos limitadores controlado; dados 100% fictícios.
"""
import pytest
from fastapi.testclient import TestClient
from passlib.hash import bcrypt as bcrypt_rapido

from app.core import rate_limit
from app.main import app
from app.models import Usuario

URL = "/api/v1/auth/login"
EMAIL = "espera.429@teste.local"
SENHA = "senha-certa-espera-1"


@pytest.fixture()
def relogio(monkeypatch):
    agora = [1000.0]
    for lim in (rate_limit.limitador_login, rate_limit.limitador_conta):
        monkeypatch.setattr(lim, "_agora", lambda: agora[0])
    return agora


@pytest.fixture()
def professora(db, escola_completa):
    db.add(Usuario(escola_id=escola_completa["escola"].id, nome="Prof Espera Ficticia",
                   email=EMAIL, senha_hash=bcrypt_rapido.using(rounds=4).hash(SENHA),
                   cargo="professor"))
    db.commit()


def _login(senha: str, ip: str = "198.51.100.40"):
    return TestClient(app).post(URL, data={"username": EMAIL, "password": senha},
                                headers={"X-Forwarded-For": ip})


def test_bloqueio_por_conta_e_ip_anuncia_os_5_minutos(professora, relogio):
    for i in range(8):
        assert _login(f"errada-{i}").status_code == 401
    r = _login(SENHA)
    assert r.status_code == 429
    assert r.json()["detail"] == "Muitas tentativas. Aguarde 5 minuto(s) e tente novamente."

    relogio[0] += 301                     # o teto por conta (20) nunca estourou
    assert _login(SENHA).status_code == 200


def test_espera_conta_do_primeiro_erro_que_ainda_trava(professora, relogio):
    """O bloqueio acaba quando o erro mais antigo sai da janela de 5 min."""
    assert _login("errada-0").status_code == 401
    relogio[0] += 120
    for i in range(1, 8):
        assert _login(f"errada-{i}").status_code == 401
    r = _login(SENHA)
    assert r.status_code == 429
    assert r.json()["detail"] == "Muitas tentativas. Aguarde 3 minuto(s) e tente novamente."

    relogio[0] += 181
    assert _login(SENHA).status_code == 200


def test_bloqueio_por_conta_anuncia_os_15_minutos(professora, relogio):
    """20 erros somando três IPs: o teto POR CONTA bloqueia (15 min) — é ele
    que a mensagem anuncia, num IP que nunca errou."""
    for ip, n in (("198.51.100.41", 8), ("198.51.100.42", 8), ("198.51.100.43", 4)):
        for i in range(n):
            assert _login(f"errada-{ip}-{i}", ip).status_code == 401
    r = _login(SENHA, "198.51.100.44")
    assert r.status_code == 429
    assert r.json()["detail"] == "Muitas tentativas. Aguarde 15 minuto(s) e tente novamente."

    relogio[0] += 301                     # o de conta+IP já saiu; o por conta não
    assert _login(SENHA, "198.51.100.44").status_code == 429
    relogio[0] += 600
    assert _login(SENHA, "198.51.100.44").status_code == 200


def test_segundos_restantes_e_o_tempo_ate_liberar():
    agora = [0.0]
    lim = rate_limit.LimitadorTentativas(max_tentativas=3, janela_s=300)
    lim._agora = lambda: agora[0]
    lim.registrar_falha("k")
    agora[0] = 100.0
    lim.registrar_falha("k")
    assert not lim.bloqueado("k")
    assert lim.segundos_restantes("k") == 0          # abaixo do teto: não espera
    assert lim.segundos_restantes("sem-eventos") == 0

    agora[0] = 200.0
    lim.registrar_falha("k")
    assert lim.bloqueado("k")
    assert lim.segundos_restantes("k") == 100        # o evento de t=0 sai em t=300

    # Acima do teto (pedidos simultâneos passam da conferência): só libera quando
    # a fila cai abaixo do teto, não quando o mais antigo sai.
    lim.registrar_falha("k")                         # 4 eventos: 0, 100, 200, 200
    assert lim.segundos_restantes("k") == 200        # o de t=100 sai em t=400
    agora[0] = 301.0                                 # o de t=0 saiu
    assert lim.bloqueado("k")
    assert lim.segundos_restantes("k") == 99
