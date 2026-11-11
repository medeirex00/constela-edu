"""O limite que os limitadores do login NÃO cobrem: o par e-mail + @ da MESMA
conta (REV3-SEG-1, sobre REG_SEGURANCA-2).

O e-mail e o @ de uma conta que existe somam falhas na mesma chave
(``identidade_da_conta``), de propósito: dois identificadores não podem dobrar o
orçamento de força bruta contra a mesma vítima. Numa conta que NÃO existe, os dois
textos são duas chaves separadas (``identidade_digitada``). Por isso quem já conhece
o par (e-mail e @) de uma conta confirma que ela existe em 9 pedidos: na que existe
o 9º dá 429; na que não existe, 401. No professor com e-mail gerado (@ em
minúsculas + domínio), o par sai só do nome.

Este arquivo prende as duas coisas: a soma do par na mesma conta (comportamento
escolhido) e o limite (``xfail`` estrito). Se um dia o login deixar de revelar a
conta pelo par (por exemplo, com o travamento silencioso que está com o dono), o
``xfail`` vira XPASS e falha: é a hora de tirar a marca e reescrever os textos de
``auth._avaliar`` e de ``rate_limit.identidade_digitada``, que hoje declaram o
limite.

Dados fictícios; senha errada sempre.
"""
import pytest
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.main import app

API = "/api/v1"
ERRADA = "Senha-Errada-Ficticia-1"
ADMIN = "admin@teste.local"
ARROBA = "AdminFicticio"
INEXISTENTE = "ninguem.ficticio@teste.local"
ARROBA_INEXISTENTE = "NinguemFicticio"


def _tentar(cli: TestClient, login: str):
    return cli.post(f"{API}/auth/login", data={"username": login, "password": ERRADA})


def _par_alternado(email: str, arroba: str) -> tuple[list[int], int]:
    """4 palpites com o e-mail e 4 com o @, alternados; depois o e-mail de novo."""
    cli = TestClient(app)
    respostas = []
    for _ in range(4):
        respostas.append(_tentar(cli, email).status_code)
        respostas.append(_tentar(cli, f"@{arroba}").status_code)
    return respostas, _tentar(cli, email).status_code


def _zerar_limitadores() -> None:
    for lim in (rate_limit.limitador_login, rate_limit.limitador_conta,
                rate_limit.limitador_ip_falha_login):
        lim._eventos.clear()


@pytest.fixture()
def admin_com_arroba(db, escola_completa):
    admin = escola_completa["admin"]
    admin.username = ARROBA
    db.commit()
    return admin


def test_email_e_arroba_da_mesma_conta_somam_no_mesmo_orcamento(admin_com_arroba):
    """Escolha registrada no código: alternar e-mail e @ não dá 16 palpites, dá 8."""
    respostas, nono = _par_alternado(ADMIN, ARROBA)
    assert respostas == [401] * 8, respostas
    assert nono == 429
    # Travada pelos dois caminhos: o @ cai na mesma chave do e-mail.
    assert _tentar(TestClient(app), f"@{ARROBA}").status_code == 429


def test_par_de_textos_sem_conta_nao_soma_na_chave_de_conta_nenhuma(admin_com_arroba):
    """O que os textos novos prometem e vale: texto que não acha conta nunca soma
    na chave de uma conta. O par inexistente fica em duas chaves ``t:`` e a conta
    real segue livre."""
    respostas, nono = _par_alternado(INEXISTENTE, ARROBA_INEXISTENTE)
    assert respostas == [401] * 8, respostas
    assert nono == 401
    chaves = set(rate_limit.limitador_conta._eventos)
    assert chaves == {rate_limit.identidade_digitada(INEXISTENTE),
                      rate_limit.identidade_digitada(ARROBA_INEXISTENTE.lower())}, chaves
    assert rate_limit.identidade_da_conta(admin_com_arroba) not in chaves
    assert _tentar(TestClient(app), ADMIN).status_code == 401


@pytest.mark.xfail(strict=True, reason=(
    "REV3-SEG-1: limite documentado. O e-mail e o @ da mesma conta somam juntos (não "
    "dobram o orçamento); sem conta, são duas chaves. Quem conhece o par confirma a "
    "conta em 9 pedidos. Fechar isso (travamento silencioso) é decisão do dono."))
def test_par_email_arroba_responde_igual_com_e_sem_conta(admin_com_arroba):
    """O limite (a sonda do revisor): conta que existe 429, que não existe 401."""
    _, existente = _par_alternado(ADMIN, ARROBA)
    _zerar_limitadores()
    _, inexistente = _par_alternado(INEXISTENTE, ARROBA_INEXISTENTE)
    assert existente == inexistente, (existente, inexistente)
