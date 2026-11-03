"""Fila manual viva, "Sincronizar agora" de todas e o alerta 'desatualizada'
aberto por leituras simultâneas.

Achados da revisão de 20/10/2026 (rodada do agendador desligado):

* uma execução MANUAL que espera a vez no semáforo há mais de SYNC_TRAVADA_S
  era tratada como órfã só pela idade — o GET /status (a tela o chama a cada
  4 s) e o boot de outro worker a cancelavam, culpando o agendador;
* "Sincronizar agora" sem plataforma devolvia 409 e desfazia o Elefante porque o
  Matific coletava um período;
* duas leituras do /status ao mesmo tempo abriam dois alertas 'desatualizada'.
"""
from __future__ import annotations

import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.models import Escola
from app.models.sincronizacao import (SincronizacaoAlerta, SincronizacaoConfig,
                                       SincronizacaoExecucao, SincronizacaoLog)
from app.sync import connectors, service, vault
from app.sync.interfaces import Credenciais
from app.sync.service import _agora
from tests._infra_comum import pg_url  # noqa: F401 — fixture

_PERIODO = {"matific_start_date": "2026-09-01", "matific_end_date": "2026-09-30"}


def _status(cliente, escola_id):
    r = cliente.get(f"/api/v1/escolas/{escola_id}/sync/status")
    assert r.status_code == 200, r.text
    return r.json()


def _recuar(db, execucao_id, minutos):
    """Simula a espera: a execução foi criada há ``minutos``."""
    db.execute(update(SincronizacaoExecucao).where(SincronizacaoExecucao.id == execucao_id)
               .values(created_at=_agora() - timedelta(minutes=minutos)))
    db.commit()


def _esperar(condicao, segundos=3.0):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicao():
            return True
        time.sleep(0.02)
    return condicao()


# --------------------------------------------------------------------------
# Manual viva na fila não é órfã pela idade
# --------------------------------------------------------------------------
def test_status_nao_cancela_manual_que_espera_o_semaforo_neste_processo(
        db, escola_completa, cliente, monkeypatch):
    """A thread desta execução está VIVA, bloqueada atrás de outra coleta. Passou
    de 30 min na fila; o /status não pode cancelá-la — e, quando ela ganha a
    vez, a coleta acontece (antes o claim falhava e nada era coletado)."""
    e = escola_completa["escola"].id
    ex = service.enfileirar(db, e, "elefante", origem="manual")
    db.commit()
    ocupado = threading.BoundedSemaphore(1)
    ocupado.acquire()                                   # outra coleta segura a vaga
    monkeypatch.setattr(service, "_semaforo_manual", ocupado)
    rodou = threading.Event()
    estado_ao_rodar: list[str] = []

    def _executar(execucao_id):
        with Session(bind=db.get_bind()) as s:
            estado_ao_rodar.append(s.get(SincronizacaoExecucao, execucao_id).status)
        rodou.set()

    monkeypatch.setattr(service, "executar_por_id", _executar)
    service.disparar_em_thread(ex.id)
    try:
        _recuar(db, ex.id, settings.SYNC_TRAVADA_S // 60 + 1)
        corpo = _status(cliente, e)
        elefante = next(p for p in corpo["plataformas"] if p["plataforma"] == "elefante")
        db.expire_all()
        assert db.get(SincronizacaoExecucao, ex.id).status == "fila"
        assert elefante["fila_parada"] is False
    finally:
        ocupado.release()                               # a outra coleta terminou
    assert rodou.wait(3)
    assert estado_ao_rodar == ["fila"]                  # ainda dá para reivindicar
    assert _esperar(lambda: ex.id not in service._vivas_neste_processo)


def test_manual_esperando_em_outro_worker_com_sinal_de_vida_nao_e_cancelada(
        db, escola_completa, cliente):
    """WEB_CONCURRENCY=2: a thread está no OUTRO processo (fora do registro
    daqui), mas deu sinal de vida no log há 2 min. Nem o /status nem o boot
    deste worker a tocam."""
    e = escola_completa["escola"].id
    ex = service.enfileirar(db, e, "elefante", origem="manual")
    db.add(SincronizacaoLog(execucao_id=ex.id, escola_id=e, etapa="scheduler",
                            nivel="info", mensagem="Aguardando a vez (teste).",
                            created_at=_agora() - timedelta(minutes=2)))
    db.commit()
    _recuar(db, ex.id, 45)

    _status(cliente, e)
    assert service.finalizar_orfas_no_boot(db) == 0
    db.expire_all()
    assert db.get(SincronizacaoExecucao, ex.id).status == "fila"


def test_manual_orfa_de_verdade_e_cancelada_sem_culpar_o_agendador(
        db, escola_completa, cliente):
    """Sem thread aqui e sem sinal de vida há mais de SYNC_TRAVADA_S: o processo
    que a esperava morreu. É cancelada — e o motivo diz isso, não "só o agendador
    rodaria", que era falso para um pedido manual."""
    e = escola_completa["escola"].id
    ex = service.enfileirar(db, e, "elefante", origem="manual")
    # Relativo à janela (não aos 30 min de antes): o último sinal de vida e a
    # criação ficam além de SYNC_TRAVADA_S, qualquer que seja o padrão.
    janela_min = settings.SYNC_TRAVADA_S // 60
    db.add(SincronizacaoLog(execucao_id=ex.id, escola_id=e, etapa="scheduler",
                            nivel="info", mensagem="Aguardando a vez (teste).",
                            created_at=_agora() - timedelta(minutes=janela_min + 10)))
    db.commit()
    _recuar(db, ex.id, janela_min + 20)

    _status(cliente, e)
    db.expire_all()
    cancelada = db.get(SincronizacaoExecucao, ex.id)
    assert cancelada.status == "cancelada"
    assert "agendador" not in cancelada.erro_resumo
    assert "sinal de vida" in cancelada.erro_resumo


def test_quem_espera_da_sinal_de_vida_e_desiste_quando_sai_da_fila(tmp_path, monkeypatch):
    """A thread que espera grava o sinal de vida a cada batimento e, se a
    execução sair da fila (cancelada/assumida em outro worker), libera a espera
    sem rodar nada. Banco em ARQUIVO: a thread usa conexão própria."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'fila.db').as_posix()}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sessao = sessionmaker(bind=engine)
    with Sessao() as s:
        escola = Escola(nome="ESCOLA FILA", ano_letivo_ativo=2026)
        s.add(escola)
        s.flush()
        ex = service.enfileirar(s, escola.id, "elefante", origem="manual")
        s.commit()
        eid = ex.id

    ocupado = threading.BoundedSemaphore(1)
    ocupado.acquire()
    monkeypatch.setattr(service, "_semaforo_manual", ocupado)
    monkeypatch.setattr(service, "batimento_fila_s", lambda: 0.05)
    respostas: list[bool] = []

    def _sinal(execucao_id):
        with Sessao() as s:
            vivo = service.registrar_espera_na_fila(s, execucao_id)
        respostas.append(vivo)
        return vivo

    monkeypatch.setattr(service, "_sinal_de_vida_da_espera", _sinal)
    rodou: list[int] = []
    monkeypatch.setattr(service, "executar_por_id", rodou.append)

    service.disparar_em_thread(eid)
    try:
        assert _esperar(lambda: len(respostas) >= 2)
        with Sessao() as s:
            sinais = s.scalar(select(func.count(SincronizacaoLog.id)).where(
                SincronizacaoLog.execucao_id == eid))
            assert sinais >= 2
            texto = s.scalars(select(SincronizacaoLog.mensagem).where(
                SincronizacaoLog.execucao_id == eid)).first()
            assert "Aguardando a vez" in texto
            # Outro worker a assumiu/cancelou enquanto esta thread esperava.
            s.execute(update(SincronizacaoExecucao).where(SincronizacaoExecucao.id == eid)
                      .values(status="cancelada"))
            s.commit()
        assert _esperar(lambda: eid not in service._vivas_neste_processo)
        assert respostas[-1] is False and rodou == []
    finally:
        ocupado.release()
        engine.dispose()


def test_sinal_de_vida_de_execucao_fora_da_fila_nao_grava(db, escola_completa):
    e = escola_completa["escola"].id
    ex = service.enfileirar(db, e, "elefante", origem="manual")
    db.commit()
    assert service.registrar_espera_na_fila(db, ex.id) is True
    ex.status = "executando"
    db.commit()
    assert service.registrar_espera_na_fila(db, ex.id) is False
    assert db.scalar(select(func.count(SincronizacaoLog.id)).where(
        SincronizacaoLog.execucao_id == ex.id)) == 1


# --------------------------------------------------------------------------
# "Sincronizar agora" de todas com o Matific coletando um período
# --------------------------------------------------------------------------
def _credenciais(db, escola_id, *plataformas):
    for plat in plataformas:
        vault.salvar_credencial(db, escola_id, plat, Credenciais(usuario="u", senha="p"))
    db.commit()


def _matific_coletando_periodo(db, escola_id):
    ex = service.enfileirar(db, escola_id, "matific", origem="manual", parametros=_PERIODO)
    ex.status, ex.iniciada_em = "executando", _agora()
    db.commit()
    return ex


def test_sincronizar_todas_segue_com_o_elefante_quando_o_matific_coleta_um_periodo(
        db, escola_completa, cliente, monkeypatch):
    e = escola_completa["escola"].id
    _credenciais(db, e, "matific", "elefante")
    assert {"matific", "elefante"} <= set(connectors.plataformas_automatizaveis())
    disparadas: list[int] = []
    monkeypatch.setattr(service, "disparar_em_thread", disparadas.append)
    periodo = _matific_coletando_periodo(db, e)

    r = cliente.post(f"/api/v1/escolas/{e}/sync/agora")

    assert r.status_code == 200, r.text
    assert [x["plataforma"] for x in r.json()] == ["elefante"]
    db.expire_all()
    elefante = db.execute(select(SincronizacaoExecucao).where(
        SincronizacaoExecucao.escola_id == e, SincronizacaoExecucao.plataforma == "elefante",
        SincronizacaoExecucao.status == "fila")).scalars().one()
    assert disparadas == [elefante.id]
    em_andamento = db.get(SincronizacaoExecucao, periodo.id)
    assert em_andamento.status == "executando" and em_andamento.parametros == _PERIODO


def test_pedido_explicito_da_plataforma_ocupada_continua_409(
        db, escola_completa, cliente, monkeypatch):
    """Pedir SÓ o Matific (o ano inteiro) enquanto ele coleta um período: devolver
    a execução do período como se fosse a pedida faria o pedido sumir."""
    e = escola_completa["escola"].id
    _credenciais(db, e, "matific", "elefante")
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)
    _matific_coletando_periodo(db, e)
    r = cliente.post(f"/api/v1/escolas/{e}/sync/agora?plataforma=matific")
    assert r.status_code == 409 and "em andamento" in r.json()["detail"]


def test_sincronizar_todas_com_so_a_ocupada_configurada_responde_409(
        db, escola_completa, cliente, monkeypatch):
    """Nada foi pedido de fato: a resposta diz a causa (e não "nenhuma
    plataforma com credencial")."""
    e = escola_completa["escola"].id
    _credenciais(db, e, "matific")
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)
    _matific_coletando_periodo(db, e)
    r = cliente.post(f"/api/v1/escolas/{e}/sync/agora")
    assert r.status_code == 409 and "matific" in r.json()["detail"]


# --------------------------------------------------------------------------
# Alerta 'desatualizada' aberto por duas leituras simultâneas (PostgreSQL)
# --------------------------------------------------------------------------
@pytest.mark.postgres
def test_duas_leituras_simultaneas_abrem_um_alerta_so(pg_url):  # noqa: F811
    """READ COMMITTED: a transação B não via o INSERT ainda não commitado da A e
    inseria o seu — dois 'desatualizada' abertos para a mesma integração. Agora B
    espera o lock da config e, liberada pelo commit da A, acha o alerta dela."""
    engine = create_engine(pg_url)
    try:
        Base.metadata.create_all(engine)
        Sessao = sessionmaker(bind=engine)
        marco = _agora() - timedelta(days=5)
        with Sessao() as s:
            escola = Escola(nome="ESCOLA CORRIDA", ano_letivo_ativo=2026)
            s.add(escola)
            s.flush()
            cfg = SincronizacaoConfig(escola_id=escola.id, plataforma="matific", ativo=True,
                                      cadencia="diaria", hora_local="03:00",
                                      created_at=marco, updated_at=marco)
            s.add(cfg)
            s.commit()
            escola_id, cfg_id = escola.id, cfg.id

        a, b = Sessao(), Sessao()
        b.execute(text("SET lock_timeout = '10s'"))   # nunca trava a suíte
        try:
            assert service.atualizar_alerta_desatualizada(a, a.get(SincronizacaoConfig, cfg_id))
            terminou = threading.Event()
            erros: list[BaseException] = []

            def _leitura_b():
                try:
                    service.atualizar_alerta_desatualizada(b, b.get(SincronizacaoConfig, cfg_id))
                    b.commit()
                except BaseException as exc:  # noqa: BLE001 — reportado abaixo
                    erros.append(exc)
                finally:
                    terminou.set()

            t = threading.Thread(target=_leitura_b)
            t.start()
            # B lê enquanto A ainda não commitou (com a serialização, B espera).
            terminou.wait(0.5)
            a.commit()
            t.join(15)
            assert terminou.is_set() and not erros, erros
        finally:
            a.close()
            b.close()

        with Sessao() as s:
            abertos = s.scalar(select(func.count(SincronizacaoAlerta.id)).where(
                SincronizacaoAlerta.escola_id == escola_id,
                SincronizacaoAlerta.tipo == "desatualizada",
                SincronizacaoAlerta.resolvido.is_(False)))
        assert abertos == 1
    finally:
        engine.dispose()
