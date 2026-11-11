"""O 429 manda esperar o tempo que falta, arredondado para CIMA (revisão
adversarial, REV-AUTH-3; achado de origem AUTH-6).

Antes: a espera anunciada era ``segundos // 60``, arredondada para baixo. Com o
relógio real, o 429 logo depois de 8 erros mandava "Aguarde 4 minuto(s)" para um
bloqueio de 299 s: quem voltava em 4 minutos levava outro 429. O teste do AUTH-6
só via "5" porque congelava o relógio no instante das falhas. O mesmo valia no
teto por IP e global do login e na reautenticação (trocar a própria senha).

Agora os três textos usam o mesmo arredondamento para cima
(``rate_limit.minutos_de_espera``). Dados 100% fictícios.
"""
import pytest
from fastapi.testclient import TestClient
from passlib.hash import bcrypt as bcrypt_rapido

from app.core import rate_limit
from app.main import app
from app.models import Usuario

API = "/api/v1"
EMAIL = "espera.arredondada@teste.local"
SENHA = "senha-certa-arredonda-1"


@pytest.fixture()
def professora(db, escola_completa):
    u = Usuario(escola_id=escola_completa["escola"].id, nome="Prof Arredonda Ficticia",
                email=EMAIL, senha_hash=bcrypt_rapido.using(rounds=4).hash(SENHA),
                cargo="professor")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _login(usuario: str, senha: str, ip: str = "198.51.100.80"):
    return TestClient(app).post(f"{API}/auth/login",
                                data={"username": usuario, "password": senha},
                                headers={"X-Forwarded-For": ip})


def _relogio(monkeypatch, *limitadores):
    agora = [5000.0]
    for lim in limitadores:
        monkeypatch.setattr(lim, "_agora", lambda: agora[0])
    return agora


def test_relogio_real_8_erros_anunciam_os_5_minutos(professora):
    """Sem congelar o relógio: entre o 8º erro e o 429 passa uma fração de
    segundo, o bloqueio dura 299 s e a mensagem tem de dizer 5 minutos."""
    for i in range(8):
        assert _login(EMAIL, f"errada-{i}").status_code == 401
    r = _login(EMAIL, SENHA)
    assert r.status_code == 429
    assert r.json()["detail"] == "Muitas tentativas. Aguarde 5 minuto(s) e tente novamente."


@pytest.mark.parametrize(("depois_s", "minutos"), [
    (0.5, 5),      # faltam 299 s
    (60.0, 4),     # faltam 240 s: minutos inteiros não sobem
    (61.0, 4),     # faltam 239 s
    (299.0, 1),    # falta 1 s
])
def test_espera_do_login_arredonda_para_cima(professora, monkeypatch, depois_s, minutos):
    agora = _relogio(monkeypatch, rate_limit.limitador_login, rate_limit.limitador_conta)
    for i in range(8):
        assert _login(EMAIL, f"errada-{i}").status_code == 401
    agora[0] += depois_s
    r = _login(EMAIL, SENHA)
    assert r.status_code == 429
    assert r.json()["detail"] == (
        f"Muitas tentativas. Aguarde {minutos} minuto(s) e tente novamente.")


def test_teto_global_arredonda_para_cima(db, escola_completa, monkeypatch):
    """O teto GLOBAL de falhas (aqui 2, para o teste) anuncia o que falta da
    janela de 5 min arredondado para cima."""
    monkeypatch.setattr(rate_limit.limitador_global_falha_login, "max_tentativas", 2)
    agora = _relogio(monkeypatch, rate_limit.limitador_global_falha_login)
    for i in range(2):
        assert _login(f"ninguem-{i}@teste.local", "errada",
                      f"198.51.100.{90 + i}").status_code == 401
    agora[0] += 0.5
    r = _login("outra.pessoa@teste.local", "qualquer", "198.51.100.99")
    assert r.status_code == 429
    assert r.json()["detail"] == (
        "O acesso está temporariamente limitado por excesso de tentativas na "
        "plataforma. Aguarde 5 minuto(s) e tente novamente.")


def test_teto_por_ip_arredonda_para_cima(db, escola_completa, monkeypatch):
    monkeypatch.setattr(rate_limit.limitador_ip_falha_login, "max_tentativas", 2)
    agora = _relogio(monkeypatch, rate_limit.limitador_ip_falha_login)
    for i in range(2):
        assert _login(f"ninguem-ip-{i}@teste.local", "errada").status_code == 401
    agora[0] += 0.5
    r = _login("outra.pessoa@teste.local", "qualquer")
    assert r.status_code == 429
    assert r.json()["detail"] == "Muitas tentativas. Aguarde 5 minuto(s) e tente novamente."


def test_reautenticacao_arredonda_para_cima(professora, monkeypatch):
    """Trocar a própria senha com o teto por conta estourado (20 em 15 min):
    faltam 899 s, a mensagem diz 15 minutos."""
    r = _login(EMAIL, SENHA)
    assert r.status_code == 200, r.text
    sessao = TestClient(app)
    sessao.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    agora = _relogio(monkeypatch, rate_limit.limitador_conta)
    for _ in range(rate_limit.limitador_conta.max_tentativas):
        rate_limit.limitador_conta.registrar_falha(rate_limit.identidade_da_conta(professora))
    agora[0] += 1.0
    r = sessao.post(f"{API}/escolas/{professora.escola_id}/usuarios/{professora.id}"
                    "/redefinir-senha", json={"senha_atual": SENHA})
    assert r.status_code == 429
    assert r.json()["detail"] == "Muitas tentativas. Aguarde 15 minuto(s) e tente novamente."


def test_minutos_de_espera():
    m = rate_limit.minutos_de_espera
    assert [m(s) for s in (0, 1, 59, 60, 61, 240, 299, 300, 899, 900)] == [
        1, 1, 1, 1, 2, 4, 5, 5, 15, 15]
