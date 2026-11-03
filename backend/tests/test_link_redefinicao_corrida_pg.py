"""Consumo do link de redefinição × revogação num PostgreSQL REAL — local e
descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').
Dados 100% fictícios.

Reaproveita os testes determinísticos de ``test_link_redefinicao_corrida`` (lá a
ordem; aqui também o ``FOR UPDATE`` na leitura da conta) e prova a TRAVA com DUAS
THREADS, cada pedido na sua conexão (READ COMMITTED):

* dois consumos simultâneos do mesmo link: exatamente um 200 (antes, 200 e 200
  em 4 de 4 rodadas, sem gancho nenhum — o bcrypt fica no intervalo);
* o admin define a senha enquanto o consumo segura a conta: o PATCH espera a
  trava e grava DEPOIS (a senha do admin vale; antes, a do link a sobrescrevia);
* a revogação (desativar, promover a Secretaria) segura a conta e o consumo
  chega no meio: o consumo espera, enxerga a revogação e recusa (antes, 200 e a
  senha do link gravada na conta já revogada).

Sem sono fixo: a espera "o outro pedido está parado na trava" é conferida em
``pg_stat_activity`` (``wait_event_type = 'Lock'``), com prazo. Na versão sem a
trava o prazo vence e o teste falha pela asserção do desfecho, não por tempo.
"""
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.security import verificar_senha
from app.main import app
from app.models import Rede, Usuario
from app.routers import admin as admin_router
from app.routers import auth as auth_router
from app.services import push as svc_push

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]


@pytest.fixture()
def db():
    engine = create_engine(URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    sessao = TestSession()

    def _get_db():
        outra = TestSession()
        try:
            yield outra
        finally:
            outra.close()

    app.dependency_overrides[get_db] = _get_db
    yield sessao
    sessao.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


from tests.test_link_redefinicao_corrida import (  # noqa: E402,F401
    SENHA_ANTIGA,
    SENHA_DO_LINK,
    SENHA_OUTRA,
    _conta,
    _consumir,
    _login,
    test_cargo_mudado_no_meio_e_conferido_depois_da_trava_sem_queimar_o_link as test_pg_cargo,
    test_consumo_trava_a_conta_antes_de_marcar_o_token_condicionalmente as test_pg_ordem,
    test_desativar_no_meio_derruba_o_consumo as test_pg_desativar,
    test_link_de_uso_unico_consumido_no_meio_recusa_o_segundo as test_pg_uso_unico,
    test_promocao_a_secretaria_no_meio_derruba_o_link_da_escola as test_pg_promocao,
    test_senha_definida_pelo_admin_no_meio_vence_o_link as test_pg_senha_admin,
    test_senha_fraca_do_dono_nao_queima_o_link as test_pg_senha_fraca,
)

PRAZO_S = 10


def _em_threads(*fns, timeout=60):
    resultados = [None] * len(fns)

    def rodar(i, fn):
        try:
            resultados[i] = fn()
        except Exception as exc:  # noqa: BLE001 — devolve para a asserção
            resultados[i] = exc

    ts = [threading.Thread(target=rodar, args=(i, fn), daemon=True)
          for i, fn in enumerate(fns)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout)
    assert not any(t.is_alive() for t in ts), "thread presa (deadlock?)"
    return resultados


def _alguem_parado_na_trava(engine, desistir=None, prazo=PRAZO_S) -> bool:
    """Espera até um backend deste banco estar parado numa trava de linha (ou
    ``desistir`` disparar, ou o prazo vencer). AUTOCOMMIT: o retrato de
    ``pg_stat_activity`` é fixo dentro de uma transação."""
    fim = time.monotonic() + prazo
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        while time.monotonic() < fim:
            n = c.execute(text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                "AND pid <> pg_backend_pid()")).scalar()
            if n:
                return True
            if desistir is not None and desistir.is_set():
                return False
            time.sleep(0.02)
    return False


def _cliente_com(cabecalhos):
    c = TestClient(app)
    c.headers.update(cabecalhos)
    return c


def test_dois_consumos_simultaneos_so_um_vale(cliente, db, escola_completa):
    e = escola_completa["escola"]
    rodadas = []
    for n in range(4):
        p = _conta(db, e.id, f"paula.simult{n}@teste.local")
        r = cliente.post(f"/api/v1/escolas/{e.id}/usuarios/{p.id}/redefinir-senha")
        assert r.status_code == 200, r.text
        token = r.json()["token"]
        barreira = threading.Barrier(2)

        def um(nova, token=token, barreira=barreira):
            barreira.wait()
            return _consumir(token, nova).status_code

        rodadas.append(_em_threads(lambda: um(SENHA_DO_LINK), lambda: um(SENHA_OUTRA)))
    assert all(sorted(c) == [200, 400] for c in rodadas), rodadas


def test_patch_senha_durante_o_consumo_espera_a_trava_e_vence(
        cliente, db, escola_completa, monkeypatch):
    e = escola_completa["escola"]
    p = _conta(db, e.id, "paula.patch@teste.local")
    base = f"/api/v1/escolas/{e.id}/usuarios/{p.id}"
    token = cliente.post(f"{base}/redefinir-senha").json()["token"]
    engine = db.get_bind()
    no_meio, patch_feito = threading.Event(), threading.Event()
    viu_a_espera = {}
    original = auth_router.validar_forca_senha

    def envolvida(senha, email=None, **kw):
        if email:            # a chamada da rota: depois da trava e da marcação
            no_meio.set()
            viu_a_espera["patch_parado"] = _alguem_parado_na_trava(engine, patch_feito)
        return original(senha, email, **kw)

    monkeypatch.setattr(auth_router, "validar_forca_senha", envolvida)
    cab = dict(cliente.headers)

    def admin():
        assert no_meio.wait(PRAZO_S)
        cod = _cliente_com(cab).patch(base, json={"senha": SENHA_OUTRA}).status_code
        patch_feito.set()
        return cod

    cod_consumo, cod_patch = _em_threads(
        lambda: _consumir(token, SENHA_DO_LINK).status_code, admin)
    monkeypatch.undo()
    assert (cod_consumo, cod_patch) == (200, 200)
    assert viu_a_espera["patch_parado"] is True      # o PATCH esperou a trava
    # Ordem serial consumo → PATCH: a senha que o admin entregou é a que vale.
    assert _login(p.email, SENHA_OUTRA).status_code == 200
    assert _login(p.email, SENHA_DO_LINK).status_code == 401


def _revogacao_segura_a_conta(monkeypatch, alvo_modulo, nome_funcao):
    """Faz a revogação PARAR depois de gravar a conta e marcar os links (as travas
    de linha seguras, sem commit) até o teste liberar."""
    gravou, liberar = threading.Event(), threading.Event()
    original = getattr(alvo_modulo, nome_funcao)

    def envolvida(sessao, *args, **kw):
        resultado = original(sessao, *args, **kw)
        sessao.flush()
        gravou.set()
        liberar.wait(PRAZO_S * 3)
        return resultado

    monkeypatch.setattr(alvo_modulo, nome_funcao, envolvida)
    return gravou, liberar


def _consumo_chega_durante_a_revogacao(engine, token, gravou, liberar, revogar):
    """Revogação parada com a conta travada → o consumo chega e para na trava →
    a revogação commita → o consumo continua. Devolve (revogação, consumo)."""
    consumo_feito = threading.Event()

    def consumir():
        assert gravou.wait(PRAZO_S)
        try:
            return _consumir(token, SENHA_DO_LINK).status_code
        finally:
            consumo_feito.set()

    def maestro():
        assert gravou.wait(PRAZO_S)
        parado = _alguem_parado_na_trava(engine, consumo_feito)
        liberar.set()
        return parado

    cod_rev, cod_consumo, consumo_parou = _em_threads(revogar, consumir, maestro)
    return cod_rev, cod_consumo, consumo_parou


def test_desativar_segurando_a_conta_o_consumo_espera_e_recusa(
        cliente, db, escola_completa, monkeypatch):
    e = escola_completa["escola"]
    p = _conta(db, e.id, "paula.desat@teste.local")
    base = f"/api/v1/escolas/{e.id}/usuarios/{p.id}"
    token = cliente.post(f"{base}/redefinir-senha").json()["token"]
    gravou, liberar = _revogacao_segura_a_conta(monkeypatch, admin_router, "_revogar_acessos")
    cab = dict(cliente.headers)
    cod_rev, cod_consumo, consumo_parou = _consumo_chega_durante_a_revogacao(
        db.get_bind(), token, gravou, liberar,
        lambda: _cliente_com(cab).patch(base, json={"status": "inativo"}).status_code)
    monkeypatch.undo()
    assert cod_rev == 200
    assert consumo_parou is True                     # o consumo esperou a trava
    assert cod_consumo == 400                        # ...e enxergou a revogação
    db.expire_all()
    u = db.get(Usuario, p.id)
    assert u.status == "inativo"
    assert verificar_senha(SENHA_ANTIGA, u.senha_hash)
    assert cliente.patch(base, json={"status": "ativo"}).status_code == 200
    assert _login(p.email, SENHA_DO_LINK).status_code == 401
    assert _login(p.email, SENHA_ANTIGA).status_code == 200


def test_promover_segurando_a_conta_o_consumo_espera_e_recusa(
        cliente, cliente_global, db, escola_completa, monkeypatch):
    e = escola_completa["escola"]
    rede = Rede(nome="Rede Trava Ficticia", status="ativa")
    db.add(rede)
    db.flush()
    e.rede_id = rede.id
    db.commit()
    p = _conta(db, e.id, "carla.trava@teste.local", cargo="coordenador")
    token = cliente.post(
        f"/api/v1/escolas/{e.id}/usuarios/{p.id}/redefinir-senha").json()["token"]
    # A promoção (rede.py) apaga os aparelhos DEPOIS de gravar a conta e marcar
    # os links: é aí que ela para, com as travas seguras.
    gravou, liberar = _revogacao_segura_a_conta(
        monkeypatch, svc_push, "remover_aparelhos_da_conta")
    cab = dict(cliente_global.headers)
    cod_rev, cod_consumo, consumo_parou = _consumo_chega_durante_a_revogacao(
        db.get_bind(), token, gravou, liberar,
        lambda: _cliente_com(cab).put(f"/api/v1/redes/{rede.id}/usuarios",
                                      json={"usuario_ids": [p.id]}).status_code)
    monkeypatch.undo()
    assert cod_rev == 200
    assert consumo_parou is True
    assert cod_consumo == 400
    assert _login(p.email, SENHA_DO_LINK).status_code == 401
