"""O limite do descadastro do push SEM login conta o IPv6 pela rede do assinante
(/64) e o 429 diz os minutos arredondados para cima (REG_SEGURANCA-3).

``POST /escolas/{id}/dispositivos/descadastrar`` é aberta a qualquer um e tem um
limite por IP (``mobile.limitador_descadastro``: 30 em 10 min). Ele contava o
endereço cru (``ip_do_cliente``): quem tem IPv6 recebe um /64 inteiro e trocava de
endereço a cada pedido, e o limite não valia. O login já agrupa o IPv6 em /64
(``rate_limit.rede_para_limite``). E o texto do 429 arredondava os minutos para
BAIXO (``espera // 60``): com 599 s restantes dizia "9 minuto(s)" e quem voltava no
tempo anunciado levava outro 429 (``rate_limit.minutos_de_espera``).

Dados fictícios; nenhuma rede.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models import DispositivoMovel
from app.routers import mobile

API = "/api/v1"


@pytest.fixture(autouse=True)
def _limpo(monkeypatch):
    # O padrão de produção: um proxy confiável à frente (X-Forwarded-For).
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)
    mobile.limitador_descadastro._eventos.clear()
    yield
    mobile.limitador_descadastro._eventos.clear()


def _url(escola_id: int) -> str:
    return f"{API}/escolas/{escola_id}/dispositivos/descadastrar"


def _pedir(cli: TestClient, url: str, token: str, ip: str):
    return cli.post(url, json={"token_push": token}, headers={"X-Forwarded-For": ip})


def test_mesmo_endereco_leva_429(db, escola_completa):
    cli = TestClient(app)
    url = _url(escola_completa["escola"].id)
    teto = mobile.limitador_descadastro.max_tentativas
    for i in range(teto):
        assert _pedir(cli, url, f"ExponentPushToken[chute-{i:04d}]",
                      "2001:db8:aaaa:bbbb::1").status_code == 200
    assert _pedir(cli, url, "ExponentPushToken[chute-final]",
                  "2001:db8:aaaa:bbbb::1").status_code == 429


def test_ipv6_do_mesmo_64_conta_junto(db, escola_completa):
    """O mesmo assinante (/64) troca o último bloco a cada pedido: depois do teto,
    o palpite certo não passa e o aparelho continua cadastrado."""
    db.add(DispositivoMovel(escola_id=escola_completa["escola"].id,
                            usuario_id=escola_completa["admin"].id,
                            token_push="ExponentPushToken[vitima-ficticia]",
                            plataforma="android"))
    db.commit()
    cli = TestClient(app)
    url = _url(escola_completa["escola"].id)
    teto = mobile.limitador_descadastro.max_tentativas
    status = [_pedir(cli, url, f"ExponentPushToken[chute-{i:04d}]",
                     f"2001:db8:aaaa:bbbb::{i + 1:x}").status_code
              for i in range(teto + 5)]
    assert status[:teto] == [200] * teto
    assert status[teto:] == [429] * 5, status
    r = _pedir(cli, url, "ExponentPushToken[vitima-ficticia]", "2001:db8:aaaa:bbbb::ffff")
    assert r.status_code == 429, r.text
    db.expire_all()
    assert db.query(DispositivoMovel).count() == 1


def test_outra_rede_ipv6_e_ipv4_tem_o_proprio_limite(db, escola_completa):
    """Outro /64 (outro assinante) e um IPv4 não herdam o bloqueio."""
    cli = TestClient(app)
    url = _url(escola_completa["escola"].id)
    for i in range(mobile.limitador_descadastro.max_tentativas):
        _pedir(cli, url, f"ExponentPushToken[c-{i:04d}]", f"2001:db8:aaaa:bbbb::{i + 1:x}")
    assert _pedir(cli, url, "ExponentPushToken[x-1]",
                  "2001:db8:aaaa:cccc::1").status_code == 200
    assert _pedir(cli, url, "ExponentPushToken[x-2]", "198.51.100.8").status_code == 200


def test_minutos_do_429_arredondam_para_cima(db, escola_completa, monkeypatch):
    """Com 599 s de bloqueio, o texto diz 10 minutos (como o login)."""
    cli = TestClient(app)
    url = _url(escola_completa["escola"].id)
    for i in range(mobile.limitador_descadastro.max_tentativas):
        _pedir(cli, url, f"ExponentPushToken[c-{i:04d}]", "198.51.100.7")
    monkeypatch.setattr(mobile.limitador_descadastro, "segundos_restantes",
                        lambda chave: 599)
    r = _pedir(cli, url, "ExponentPushToken[c-final]", "198.51.100.7")
    assert r.status_code == 429
    assert "Aguarde 10 minuto(s)" in r.json()["detail"], r.json()["detail"]
    assert r.headers.get("Retry-After") == "599"
