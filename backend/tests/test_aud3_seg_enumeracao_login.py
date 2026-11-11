"""O /auth/login não revela se a conta existe pelo 429 dos limitadores da conta
(REG_SEGURANCA-2).

A chave dos limitadores de uma conta que EXISTE é ``<e-mail>#<token_version>``
(``identidade_da_conta``); a de uma conta que NÃO existe era o texto digitado.
As duas viviam no mesmo espaço de nomes: quem digitava ``<e-mail>#0`` como login
(conta inexistente) somava falhas exatamente na chave da conta real (versão 0).
Depois de 8 palpites, o login com o e-mail verdadeiro dava 429 só se a conta
existia — e 401 se não existia. Agora o texto digitado e a conta têm chaves de
espaços diferentes: nenhum texto digitado cai na chave de uma conta.

Dados fictícios; senha errada sempre (menos no controle do login certo).
"""
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.main import app

API = "/api/v1"
ERRADA = "Senha-Errada-Ficticia-1"
ADMIN = "admin@teste.local"
INEXISTENTE = "ninguem.ficticio@teste.local"


def _tentar(cli: TestClient, login: str, senha: str = ERRADA):
    return cli.post(f"{API}/auth/login", data={"username": login, "password": senha})


def _sondar(email: str, texto: str) -> tuple[int, str]:
    """8 palpites errados com ``texto`` (conta inexistente) e 1 com ``email``."""
    cli = TestClient(app)
    for _ in range(8):
        r = _tentar(cli, texto)
        assert r.status_code == 401, r.text
    r = _tentar(cli, email)
    return r.status_code, r.json().get("detail")


def test_conta_inexistente_responde_401(db, escola_completa):
    status, detalhe = _sondar(INEXISTENTE, f"{INEXISTENTE}#0")
    assert status == 401, (status, detalhe)


def test_conta_existente_responde_igual_a_inexistente(db, escola_completa):
    """admin@teste.local existe (token_version 0): o '#0' digitado não trava a
    chave dela, e o login com o e-mail responde 401 como o da conta inexistente."""
    status, detalhe = _sondar(ADMIN, f"{ADMIN}#0")
    assert status == 401, (
        f"o login revela que a conta existe: {status} {detalhe!r} (a inexistente dá 401)")


def test_versao_da_sessao_tambem_nao_vaza(db, escola_completa):
    """Depois de uma redefinição (token_version 1), tentar '#1' também não trava a
    chave da conta: a versão da sessão não vira oráculo."""
    admin = escola_completa["admin"]
    admin.token_version = 1
    db.commit()
    for versao in (0, 1, 2):
        rate_limit.limitador_login._eventos.clear()
        rate_limit.limitador_conta._eventos.clear()
        rate_limit.limitador_ip_falha_login._eventos.clear()
        status, detalhe = _sondar(ADMIN, f"{ADMIN}#{versao}")
        assert status == 401, (versao, status, detalhe)


def test_texto_com_cara_de_chave_nao_cai_na_conta(db, escola_completa):
    """Nem o texto que imita a chave interna da conta (com qualquer prefixo) soma
    falhas nela: o espaço de nomes do texto digitado é outro."""
    admin = escola_completa["admin"]
    chave = rate_limit.identidade_da_conta(admin)
    status, detalhe = _sondar(ADMIN, chave)
    assert status == 401, (chave, status, detalhe)
    assert not rate_limit.limitador_conta.bloqueado(chave)


def test_conta_que_existe_ainda_trava_pelos_proprios_palpites(db, escola_completa):
    """O limitador da conta continua valendo: 8 palpites com o e-mail travam."""
    cli = TestClient(app)
    for _ in range(8):
        assert _tentar(cli, ADMIN).status_code == 401
    r = _tentar(cli, ADMIN)
    assert r.status_code == 429, r.text
    # Travada, nem a senha certa entra até o fim da janela (o 429 vem antes da senha).
    assert _tentar(cli, ADMIN, "s3nh4").status_code == 429


def test_conta_inexistente_ainda_trava_pelos_proprios_palpites(db, escola_completa):
    cli = TestClient(app)
    for _ in range(8):
        assert _tentar(cli, INEXISTENTE).status_code == 401
    r = _tentar(cli, INEXISTENTE)
    assert r.status_code == 429, r.text


def test_liberar_conta_limpa_as_chaves_da_conta_em_qualquer_versao(db, escola_completa):
    admin = escola_completa["admin"]
    chave = rate_limit.identidade_da_conta(admin)
    rate_limit.limitador_conta.registrar_falha(chave)
    rate_limit.limitador_login.registrar_falha(rate_limit.chave_conta_ip(chave, "203.0.113.5"))
    rate_limit.limitador_conta.registrar_falha(rate_limit.identidade_digitada(f"{ADMIN}#0"))
    rate_limit.liberar_conta(admin.email)
    assert chave not in rate_limit.limitador_conta._eventos
    assert not rate_limit.limitador_login._eventos
    # O texto digitado não é a conta: a limpeza da conta não o alcança.
    assert rate_limit.identidade_digitada(f"{ADMIN}#0") in rate_limit.limitador_conta._eventos
