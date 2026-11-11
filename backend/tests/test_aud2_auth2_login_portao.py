"""Portão de logins simultâneos do /auth/login (G_CARGA-1).

Uma rajada anônima de logins ocupava todas as threads do worker (40 no anyio) e as
conexões do pool (10 + 20), e as sessões já abertas esperavam na fila delas. Agora
cada processo deixa correr no máximo ``portao_login.vagas`` logins ao mesmo tempo;
quem chega com o portão cheio recebe 429 na hora, sem nenhuma ida ao banco, e a vaga
volta em toda saída do login (sucesso, erro esperado ou exceção).

A prova com PostgreSQL real, latência e sessões abertas respondendo está em
``test_aud2_auth2_login_rajada_pg.py``. Contas fictícias; bcrypt de custo 4 só para o
teste andar rápido."""
import logging

import pytest
from fastapi.testclient import TestClient
from passlib.hash import bcrypt as bcrypt_rapido
from sqlalchemy import event, select

from app.core import rate_limit
from app.core.rate_limit import PortaoDeConcorrencia
from app.main import app
from app.models import LogAuditoria, Usuario
from app.routers import auth as auth_router

URL = "/api/v1/auth/login"
SENHA = "Portao#Certa2026"


@pytest.fixture()
def conta(db, escola_completa):
    db.add(Usuario(escola_id=escola_completa["escola"].id, nome="Prof Portao Ficticia",
                   email="portao@teste.local", username="ProfPortao",
                   senha_hash=bcrypt_rapido.using(rounds=4).hash(SENHA),
                   cargo="professor"))
    db.commit()
    return "portao@teste.local"


def _login(cli: TestClient, usuario: str, senha: str):
    return cli.post(URL, data={"username": usuario, "password": senha},
                    headers={"X-Forwarded-For": "198.51.100.31"})


def test_portao_conta_as_vagas_e_devolve_na_saida():
    portao = PortaoDeConcorrencia(vagas=2)
    assert portao.entrar() and portao.entrar()
    assert portao.entrar() is False            # cheio: recusa na hora, sem fila
    assert portao.ocupadas == 2
    portao.sair()
    assert portao.entrar() is True
    portao.sair()
    portao.sair()
    portao.sair()
    portao.sair()                              # sair a mais não fica negativo
    assert portao.ocupadas == 0


def test_portao_cheio_recusa_na_hora_sem_ir_ao_banco(db, conta, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="constela.auth")
    monkeypatch.setattr(rate_limit.portao_login, "vagas", 0)
    rate_limit.alerta_portao_login._eventos.clear()
    consultas: list[str] = []

    def _anotar(conn, cursor, sql, params, context, executemany):
        consultas.append(sql)

    motor = db.get_bind()
    event.listen(motor, "before_cursor_execute", _anotar)
    try:
        cli = TestClient(app)
        respostas = [_login(cli, conta, SENHA) for _ in range(3)]
    finally:
        event.remove(motor, "before_cursor_execute", _anotar)

    for r in respostas:
        assert r.status_code == 429, r.text
        assert r.json()["detail"] == auth_router.ERRO_LOGIN_OCUPADO
        assert r.headers["retry-after"] == "5"
    assert consultas == []                     # nem auditoria, nem limite, nem conta
    assert db.execute(select(LogAuditoria)).scalars().all() == []
    # Um aviso por minuto em cada processo, sem IP nem conta.
    avisos = [x for x in caplog.records
              if getattr(x, "evento", None) == "login.simultaneos_no_teto"]
    assert len(avisos) == 1
    assert "198.51" not in repr(vars(avisos[0])) and "portao@" not in repr(vars(avisos[0]))

    monkeypatch.setattr(rate_limit.portao_login, "vagas", 8)
    assert _login(TestClient(app), conta, SENHA).status_code == 200


def test_toda_saida_do_login_devolve_a_vaga(db, conta, monkeypatch):
    cli = TestClient(app)
    assert _login(cli, conta, SENHA).status_code == 200
    assert rate_limit.portao_login.ocupadas == 0
    assert _login(cli, conta, "Errada#2026xx").status_code == 401
    assert rate_limit.portao_login.ocupadas == 0
    assert _login(cli, "ninguem@teste.local", "Errada#2026xx").status_code == 401
    assert rate_limit.portao_login.ocupadas == 0

    def _quebra(*_a, **_k):
        raise RuntimeError("falha inventada no meio do login")

    monkeypatch.setattr(auth_router, "_login", _quebra)
    r = TestClient(app, raise_server_exceptions=False).post(
        URL, data={"username": conta, "password": SENHA})
    assert r.status_code == 500
    assert rate_limit.portao_login.ocupadas == 0


def test_portao_padrao_tem_oito_vagas_por_processo():
    assert rate_limit.portao_login.vagas == 8


def test_as_vagas_do_portao_vem_da_configuracao(monkeypatch):
    """G_CARGA-1 (configuração): as vagas do portão saem de ``EDU_LOGIN_SIMULTANEOS``
    (padrão 8), lido no boot como os ``EDU_LOGIN_TETO_*`` — a produção ajusta sem mudar
    o código. Zero barraria todo login: recusado na leitura da configuração."""
    import pydantic

    from app.core import config

    assert config.Settings.model_fields["EDU_LOGIN_SIMULTANEOS"].default == 8
    assert rate_limit.portao_login.vagas == config.settings.EDU_LOGIN_SIMULTANEOS
    monkeypatch.setenv("EDU_LOGIN_SIMULTANEOS", "12")
    assert config.Settings().EDU_LOGIN_SIMULTANEOS == 12
    monkeypatch.setenv("EDU_LOGIN_SIMULTANEOS", "0")
    with pytest.raises(pydantic.ValidationError):
        config.Settings()
