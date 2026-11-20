"""Login recusa a senha das convenções antigas de professor (Fase 3A).

Até a Fase 3A a senha nascia do nome: o @ em minúsculas + "123" e, antes, o
primeiro nome + "123". As contas antigas só deixam de ter essa senha quando a
etapa manual (scripts/senhas_derivadas.py --aplicar) roda; sem ela, quem
soubesse o nome de uma professora entrava com 1 a 4 palpites. O /auth/login
agora recusa essas senhas por conta própria (403, sem token), mesmo quando o
bcrypt confere. Dados 100% fictícios.
"""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import LogAuditoria, Usuario

SENHA_FORTE = "farol-cedro-lua-38"
MSG = "Senha expirada"


def _login(usuario: str, senha: str):
    return TestClient(app).post("/api/v1/auth/login",
                                data={"username": usuario, "password": senha})


def _conta(db, escola_id, nome, email, username, senha, cargo="professor"):
    u = Usuario(escola_id=escola_id, nome=nome, email=email, username=username,
                senha_hash=hash_senha(senha), cargo=cargo)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _zerar_limitadores():
    from app.core import rate_limit
    rate_limit.limitador_login._eventos.clear()
    rate_limit.limitador_conta._eventos.clear()


def _recusada(resposta) -> bool:
    return (resposta.status_code == 403 and "access_token" not in resposta.json()
            and MSG in resposta.json()["detail"])


def test_arroba_minusculo_mais_123_da_403_sem_token(db, escola_completa):
    e = escola_completa["escola"]
    _conta(db, e.id, "Zuleica Fictoria Tal", "z.f@teste.local", "ZuleicaTal", "zuleicatal123")
    for entrada in ("@zuleicatal", "ZuleicaTal", "z.f@teste.local"):
        _zerar_limitadores()
        r = _login(entrada, "zuleicatal123")
        assert _recusada(r), (entrada, r.status_code, r.text)


def test_primeiro_nome_mais_123_da_403_mesmo_em_conta_promovida(db, escola_completa):
    """Coordenadora promovida que manteve a senha da convenção também é barrada."""
    e = escola_completa["escola"]
    _conta(db, e.id, "Orlanda Inventada Xis", "o.i@teste.local", "OrlandaXis", "Orlanda123",
           cargo="coordenador")
    assert _recusada(_login("orlandaxis", "Orlanda123"))


def test_qualquer_caixa_da_convencao_e_recusada(db, escola_completa):
    """A comparação é casefold: a pessoa (ou quem cadastrou) digitava de vários jeitos."""
    e = escola_completa["escola"]
    u = _conta(db, e.id, "Zuleica Fictoria Tal", "z.f@teste.local", "ZuleicaTal", "x")
    for senha in ("ZULEICATAL123", "ZuleicaTal123", "Zuleica123", "zuleica123"):
        u.senha_hash = hash_senha(senha)
        db.commit()
        _zerar_limitadores()
        assert _recusada(_login("zuleicatal", senha)), senha


def test_senha_forte_da_mesma_conta_continua_entrando(db, escola_completa):
    e = escola_completa["escola"]
    u = _conta(db, e.id, "Zuleica Fictoria Tal", "z.f@teste.local", "ZuleicaTal", "zuleicatal123")
    assert _login("zuleicatal", "zuleicatal123").status_code == 403
    u.senha_hash = hash_senha(SENHA_FORTE)       # trocou a senha pelo link
    db.commit()
    _zerar_limitadores()
    r = _login("zuleicatal", SENHA_FORTE)
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


def test_senha_que_so_termina_em_123_nao_e_confundida(db, escola_completa):
    """Só as senhas que saem do nome/@ da PRÓPRIA conta são barradas."""
    e = escola_completa["escola"]
    _conta(db, e.id, "Zuleica Fictoria Tal", "z.f@teste.local", "ZuleicaTal", "segredo123")
    assert _login("zuleicatal", "segredo123").status_code == 200


def test_senha_errada_continua_401(db, escola_completa):
    """A trava só age depois do bcrypt: palpite errado segue o caminho comum."""
    e = escola_completa["escola"]
    _conta(db, e.id, "Zuleica Fictoria Tal", "z.f@teste.local", "ZuleicaTal", SENHA_FORTE)
    assert _login("zuleicatal", "zuleicatal123").status_code == 401


def test_recusa_fica_na_auditoria_e_conta_no_limitador(db, escola_completa):
    e = escola_completa["escola"]
    u = _conta(db, e.id, "Zuleica Fictoria Tal", "z.f@teste.local", "ZuleicaTal", "zuleicatal123")
    assert _login("zuleicatal", "zuleicatal123").status_code == 403
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "login.falhou", LogAuditoria.usuario_id == u.id)).scalars().one()
    assert log.detalhes["motivo"] == "senha_convencao_antiga"
    assert "zuleicatal123" not in str(log.detalhes)
    # Conta como falha: o limitador por conta+IP (8 em 5 min) acaba barrando.
    for _ in range(7):
        assert _login("zuleicatal", "zuleicatal123").status_code == 403
    assert _login("zuleicatal", "zuleicatal123").status_code == 401
    # Nenhum login bem-sucedido foi registrado nem o último acesso gravado.
    db.expire_all()
    assert db.get(Usuario, u.id).ultimo_acesso is None
    assert db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "login", LogAuditoria.usuario_id == u.id)).first() is None
