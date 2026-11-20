"""O e-mail e o @ compartilham o limite interno da conta. O status e o texto
de erro do login são uniformes, inclusive depois do limite (REV3-SEG-1).
Dados fictícios."""
import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.core import rate_limit
from app.main import app

API = "/api/v1"
ERRADA = "Senha-Errada-Ficticia-1"
ADMIN = "admin@teste.local"
ARROBA = "AdminFicticio"
INEXISTENTE = "ninguem.ficticio@teste.local"
ARROBA_INEXISTENTE = "NinguemFicticio"
MENSAGEM = ("Não foi possível entrar. Confira o e-mail ou usuário e a senha. "
            "Se precisar, peça um link de redefinição à administração.")


def _tentar(cli: TestClient, login: str, senha: str = ERRADA) -> Response:
    return cli.post(f"{API}/auth/login", data={"username": login, "password": senha})


def _par_alternado(cli: TestClient, email: str, arroba: str) -> list[Response]:
    return [_tentar(cli, login) for login in (email, f"@{arroba}") * 4]


def _assert_erro_uniforme(r: Response) -> None:
    assert r.status_code == 401
    assert r.json() == {"detail": MENSAGEM}
    assert "retry-after" not in r.headers


@pytest.fixture()
def admin_com_arroba(db, escola_completa):
    admin = escola_completa["admin"]
    admin.username = ARROBA
    db.commit()
    return admin


def test_email_e_arroba_da_mesma_conta_somam_no_mesmo_orcamento(admin_com_arroba):
    cli = TestClient(app)
    for r in _par_alternado(cli, ADMIN, ARROBA):
        _assert_erro_uniforme(r)
    identidade = rate_limit.identidade_da_conta(admin_com_arroba)
    assert rate_limit.limitador_conta.falhas_na_janela(identidade) == 8
    for login in (ADMIN, f"@{ARROBA}"):
        _assert_erro_uniforme(_tentar(cli, login, "s3nh4"))
    assert rate_limit.limitador_conta.falhas_na_janela(identidade) == 8


def test_par_de_textos_sem_conta_nao_soma_na_chave_de_conta_nenhuma(admin_com_arroba):
    """O que os textos novos prometem e vale: texto que não acha conta nunca soma
    na chave de uma conta. O par inexistente fica em duas chaves ``t:`` e a conta
    real segue livre."""
    cli = TestClient(app)
    for r in _par_alternado(cli, INEXISTENTE, ARROBA_INEXISTENTE):
        _assert_erro_uniforme(r)
    chaves = set(rate_limit.limitador_conta._eventos)
    assert chaves == {rate_limit.identidade_digitada(INEXISTENTE),
                      rate_limit.identidade_digitada(ARROBA_INEXISTENTE.lower())}, chaves
    assert rate_limit.identidade_da_conta(admin_com_arroba) not in chaves
    assert _tentar(cli, ADMIN, "s3nh4").status_code == 200


@pytest.mark.parametrize("existe", [True, False])
@pytest.mark.parametrize("teto_publico", ["ip", "global"])
def test_par_email_arroba_responde_igual_com_e_sem_conta(
        admin_com_arroba, existe, teto_publico, monkeypatch):
    """A diferença entre chaves também não altera quando sai o 429 público."""
    limitador = (rate_limit.limitador_ip_falha_login if teto_publico == "ip"
                 else rate_limit.limitador_global_falha_login)
    monkeypatch.setattr(limitador, "max_tentativas", 10)
    email, arroba = (ADMIN, ARROBA) if existe else (INEXISTENTE, ARROBA_INEXISTENTE)
    cli = TestClient(app)
    for r in _par_alternado(cli, email, arroba):
        _assert_erro_uniforme(r)
    _assert_erro_uniforme(_tentar(cli, email))
    _assert_erro_uniforme(_tentar(cli, f"@{arroba}"))
    r = _tentar(cli, INEXISTENTE)
    assert r.status_code == 429
