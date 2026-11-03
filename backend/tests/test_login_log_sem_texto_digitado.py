"""Login com conta inexistente: o log de auditoria (permanente) não guarda o texto cru
digitado no usuário (revisão independente dados-lgpd, d4caac4).

Antes, ``login.falhou``/``login.bloqueado`` gravavam ``form.username`` inteiro e sem
teto: a senha digitada no campo errado ia para a trilha, e um anônimo gravava ~1 MB por
pedido via multipart (valor novo a cada vez, então o limitador nunca barrava). O mesmo
texto virava CHAVE dos dois limitadores em memória (o teto deles conta chaves, não bytes).

Agora: texto acima de 200 caracteres (nenhuma conta tem identificador assim) vira
``[descartado]`` antes da busca, do limitador e do log; e, sem conta, o log só guarda o
que tem forma de e-mail ou de @usuário. O e-mail bem formado continua na trilha de força
bruta.

Dados 100% fictícios."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import rate_limit
from app.main import app
from app.models import LogAuditoria

SENHA_NO_CAMPO_ERRADO = "minhasenha#forte2026"


def _gravados(db) -> list[str | None]:
    db.expire_all()
    return [f.detalhes.get("email") for f in db.execute(select(LogAuditoria).where(
        LogAuditoria.acao.in_(("login.falhou", "login.bloqueado")))).scalars().all()]


def test_senha_no_campo_usuario_e_texto_longo_nao_vao_para_o_log(db, escola_completa):
    c = TestClient(app)
    for usuario in (SENHA_NO_CAMPO_ERRADO, "a" * 20000):
        r = c.post("/api/v1/auth/login", data={"username": usuario, "password": "x"})
        assert r.status_code == 401
    gravados = _gravados(db)
    assert SENHA_NO_CAMPO_ERRADO not in gravados
    assert all(len(g or "") <= 200 for g in gravados)
    assert gravados.count("[descartado]") == 2


def test_multipart_gigante_nao_cresce_o_log_nem_os_limitadores(db, escola_completa):
    c = TestClient(app)
    tamanho = 1000 * 1000 - 100
    for i in range(3):
        r = c.post("/api/v1/auth/login",
                   files={"username": (None, f"{i}" + "b" * tamanho),
                          "password": (None, "x")})
        assert r.status_code == 401, r.text[:200]
    assert all(len(g or "") <= 200 for g in _gravados(db))
    assert all(len(k) < 1000 for k in rate_limit.limitador_conta._eventos)
    assert all(len(k) < 1000 for k in rate_limit.limitador_login._eventos)


def test_bloqueio_de_conta_inexistente_tambem_nao_grava_o_texto(db, escola_completa):
    c = TestClient(app)
    codigos = [c.post("/api/v1/auth/login",
                      data={"username": SENHA_NO_CAMPO_ERRADO, "password": "x"}).status_code
               for _ in range(12)]
    assert 429 in codigos
    db.expire_all()
    bloqueios = [f.detalhes.get("email") for f in db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "login.bloqueado")).scalars().all()]
    assert bloqueios and set(bloqueios) == {"[descartado]"}


def test_email_e_usuario_bem_formados_de_conta_inexistente_continuam_no_log(
        db, escola_completa):
    c = TestClient(app)
    for usuario in ("Ninguem.Ficticio@Escola-Prova.test", "@ninguemficticio"):
        r = c.post("/api/v1/auth/login", data={"username": usuario, "password": "x"})
        assert r.status_code == 401
    gravados = _gravados(db)
    assert "ninguem.ficticio@escola-prova.test" in gravados
    assert "ninguemficticio" in gravados


def test_conta_existente_com_senha_errada_continua_com_o_email_da_conta(
        db, escola_completa):
    r = TestClient(app).post("/api/v1/auth/login",
                             data={"username": "ADMIN@teste.local", "password": "errada"})
    assert r.status_code == 401
    assert "admin@teste.local" in _gravados(db)
