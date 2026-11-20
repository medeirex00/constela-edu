"""Texto digitado que não acha conta não soma falhas na chave de uma conta: o 429
de quem digita ``<e-mail>#<versão>`` não revela se a conta existe (REG_SEGURANCA-2).

A chave dos limitadores de uma conta que EXISTE é ``<e-mail>#<token_version>``
(``identidade_da_conta``); a de uma conta que NÃO existe era o texto digitado.
As duas viviam no mesmo espaço de nomes: quem digitava ``<e-mail>#0`` como login
(conta inexistente) somava falhas exatamente na chave da conta real (versão 0).
Depois de 8 palpites, o login com o e-mail verdadeiro dava 429 só se a conta
existia — e 401 se não existia. Agora o texto digitado e a conta têm chaves de
espaços diferentes: texto que não acha conta nunca cai na chave de uma conta.

O caso do par e-mail + @ da mesma conta (REV3-SEG-1) é coberto em
``test_aud3_seg_login_par_email_arroba.py``.

Dados fictícios; senha errada sempre (menos no controle do login certo).
"""
from fastapi.testclient import TestClient
from passlib.hash import bcrypt as bcrypt_rapido

from app.core import rate_limit
from app.main import app
from app.models import Usuario

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
    primeira = _tentar(cli, ADMIN)
    assert primeira.status_code == 401
    for _ in range(7):
        assert _tentar(cli, ADMIN).status_code == 401
    r = _tentar(cli, ADMIN, "s3nh4")
    assert r.status_code == 401, r.text
    assert r.json() == primeira.json()


def test_conta_inexistente_ainda_trava_pelos_proprios_palpites(db, escola_completa):
    cli = TestClient(app)
    identidade = rate_limit.identidade_digitada(INEXISTENTE)
    chave = rate_limit.chave_conta_ip(identidade, "testclient")
    for _ in range(8):
        assert _tentar(cli, INEXISTENTE).status_code == 401
    assert rate_limit.limitador_login.bloqueado(chave)
    r = _tentar(cli, INEXISTENTE)
    assert r.status_code == 401, r.text
    assert rate_limit.limitador_login.falhas_na_janela(chave) == 8


def test_conta_nova_nao_herda_bloqueio_do_texto_digitado(db, escola_completa):
    cli = TestClient(app)
    for _ in range(8):
        assert _tentar(cli, INEXISTENTE).status_code == 401
    senha = "Senha-Primeiro-Login-Ficticia"
    db.add(Usuario(escola_id=escola_completa["escola"].id, nome="Novo cadastro fictício",
                   email=INEXISTENTE, senha_hash=bcrypt_rapido.using(rounds=4).hash(senha),
                   cargo="professor"))
    db.commit()
    assert _tentar(cli, INEXISTENTE, senha).status_code == 200


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
