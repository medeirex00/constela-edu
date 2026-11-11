"""As rotas de credencial da sincronização ("Salvar e validar" — PUT
/sync/credenciais/{plataforma} — e "Testar conexão" — POST .../testar) são
``async def`` porque o login na plataforma é um ``await`` longo, mas a sessão do
banco é SÍNCRONA. Uma rota ``async`` roda o corpo na thread do event loop do
worker: cada consulta, ``commit`` e recálculo de alerta feito ali parava o worker
inteiro (todas as escolas e perfis que caem nele, inclusive o /api/health) — ~0,2 s
por ida ao banco em produção, 12 consultas no salvar e 5 no testar.

Contrato: NENHUMA consulta SQL dessas rotas roda na thread do event loop; no loop
fica só o ``await`` do login (que continua no loop, como antes). Dados fictícios;
conector falso, nada sai da máquina.
"""
import asyncio
from contextlib import contextmanager

import pytest
from sqlalchemy import event, select
from sqlalchemy.engine import Engine

from app.models.sincronizacao import PlataformaCredencial, SincronizacaoConfig
from app.sync import connectors, vault
from app.sync.interfaces import Credenciais, ResultadoValidacao

API = "/api/v1"


@contextmanager
def _consultas_no_event_loop():
    """Comandos SQL executados com um event loop RODANDO na thread atual — a do
    worker. No threadpool (``run_in_threadpool``, dependências ``def``) não há loop."""
    no_loop: list[str] = []

    def _antes(conn, cursor, statement, params, context, executemany):  # noqa: ARG001
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        no_loop.append(statement.split(None, 1)[0].upper())

    event.listen(Engine, "before_cursor_execute", _antes)
    try:
        yield no_loop
    finally:
        event.remove(Engine, "before_cursor_execute", _antes)


class _ConectorFalso:
    def __init__(self, resultado: ResultadoValidacao):
        self.resultado = resultado
        self.recebidas: list[tuple[str, str]] = []

    async def testar_credenciais(self, cred, contexto):
        # O login é I/O: roda no loop, sem consulta nenhuma.
        await asyncio.sleep(0)
        self.recebidas.append((cred.usuario, cred.senha))
        return self.resultado


def _instalar(monkeypatch, resultado):
    falso = _ConectorFalso(resultado)
    original = connectors.obter
    monkeypatch.setattr(connectors, "obter",
                        lambda p: falso if p in ("matific", "elefante") else original(p))
    return falso


@pytest.mark.parametrize("plataforma", ["matific", "elefante"])
def test_salvar_e_validar_nao_consulta_o_banco_no_event_loop(db, cliente, escola_completa,
                                                            monkeypatch, plataforma):
    eid = escola_completa["escola"].id
    falso = _instalar(monkeypatch, ResultadoValidacao(ok=True, mensagem="Login confirmado."))
    with _consultas_no_event_loop() as no_loop:
        r = cliente.put(f"{API}/escolas/{eid}/sync/credenciais/{plataforma}",
                        json={"usuario": "robo-ficticio", "senha": "valor-ficticio-local"})
    assert r.status_code == 200, r.text
    assert no_loop == [], f"{len(no_loop)} comando(s) SQL na thread do event loop: {no_loop}"
    # O comportamento continua o mesmo: gravou cifrado, validou, ligou a agenda.
    assert r.json()["ok"] is True
    assert falso.recebidas == [("robo-ficticio", "valor-ficticio-local")]
    db.expire_all()
    assert vault.obter_credencial(db, eid, plataforma).senha == "valor-ficticio-local"
    assert vault.obter_linha(db, eid, plataforma).status == "valida"
    assert db.execute(select(SincronizacaoConfig).where(
        SincronizacaoConfig.escola_id == eid,
        SincronizacaoConfig.plataforma == plataforma)).scalars().first() is not None


def test_salvar_com_senha_recusada_nao_consulta_o_banco_no_event_loop(db, cliente,
                                                                     escola_completa,
                                                                     monkeypatch):
    eid = escola_completa["escola"].id
    _instalar(monkeypatch, ResultadoValidacao(ok=False, mensagem="Senha recusada.",
                                              codigo="senha_invalida"))
    with _consultas_no_event_loop() as no_loop:
        r = cliente.put(f"{API}/escolas/{eid}/sync/credenciais/elefante",
                        json={"usuario": "robo-ficticio", "senha": "valor-ficticio-local"})
    assert r.status_code == 200, r.text
    assert no_loop == [], no_loop
    assert r.json()["ok"] is False and r.json()["codigo"] == "senha_invalida"
    db.expire_all()
    assert vault.obter_linha(db, eid, "elefante").status == "invalida"


def test_salvar_com_o_conector_quebrando_continua_gravando(db, cliente, escola_completa,
                                                           monkeypatch):
    """A rede de segurança do salvar segue valendo: a credencial já gravada não vira
    500 quando o conector levanta."""
    eid = escola_completa["escola"].id

    class _Quebra:
        async def testar_credenciais(self, cred, contexto):
            raise RuntimeError("falha simulada")
    original = connectors.obter
    monkeypatch.setattr(connectors, "obter",
                        lambda p: _Quebra() if p == "elefante" else original(p))
    with _consultas_no_event_loop() as no_loop:
        r = cliente.put(f"{API}/escolas/{eid}/sync/credenciais/elefante",
                        json={"usuario": "robo-ficticio", "senha": "valor-ficticio-local"})
    assert r.status_code == 200, r.text
    assert no_loop == [], no_loop
    assert r.json()["ok"] is False and r.json()["codigo"] == "erro_navegador"
    db.expire_all()
    assert vault.obter_credencial(db, eid, "elefante") is not None


def test_testar_conexao_nao_consulta_o_banco_no_event_loop(db, cliente, escola_completa,
                                                          monkeypatch):
    eid = escola_completa["escola"].id
    vault.salvar_credencial(db, eid, "matific",
                            Credenciais(usuario="robo-ficticio", senha="valor-ficticio-local"))
    db.commit()
    falso = _instalar(monkeypatch, ResultadoValidacao(
        ok=True, mensagem="Login confirmado.",
        escolas_externas=[{"id": "e1", "nome": "ESCOLA FICTICIA"}]))
    with _consultas_no_event_loop() as no_loop:
        r = cliente.post(f"{API}/escolas/{eid}/sync/credenciais/matific/testar")
    assert r.status_code == 200, r.text
    assert no_loop == [], f"{len(no_loop)} comando(s) SQL na thread do event loop: {no_loop}"
    corpo = r.json()
    assert corpo["ok"] is True and corpo["escolas_externas"] == [
        {"id": "e1", "nome": "ESCOLA FICTICIA"}]
    assert falso.recebidas == [("robo-ficticio", "valor-ficticio-local")]
    db.expire_all()
    assert vault.obter_linha(db, eid, "matific").status == "valida"


def test_testar_sem_credencial_e_com_cifra_ilegivel_nao_consulta_no_loop(db, cliente,
                                                                        escola_completa,
                                                                        monkeypatch):
    eid = escola_completa["escola"].id
    _instalar(monkeypatch, ResultadoValidacao(ok=True, mensagem="ok"))
    with _consultas_no_event_loop() as no_loop:
        r = cliente.post(f"{API}/escolas/{eid}/sync/credenciais/elefante/testar")
    assert r.status_code == 400, r.text
    assert no_loop == [], no_loop

    vault.salvar_credencial(db, eid, "elefante",
                            Credenciais(usuario="robo-ficticio", senha="valor-ficticio-local"))
    db.commit()
    linha = db.execute(select(PlataformaCredencial).where(
        PlataformaCredencial.escola_id == eid,
        PlataformaCredencial.plataforma == "elefante")).scalar_one()
    linha.segredo_cifrado = "cifra-que-nao-abre"
    db.commit()
    with _consultas_no_event_loop() as no_loop:
        r = cliente.post(f"{API}/escolas/{eid}/sync/credenciais/elefante/testar")
    assert r.status_code == 200, r.text
    assert no_loop == [], no_loop
    assert r.json()["ok"] is False and r.json()["codigo"] == vault.CODIGO_CREDENCIAL_ILEGIVEL
