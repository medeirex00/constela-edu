"""Execução em 'executando': sinal de vida, cancelamento e fechamento condicional.

Achados N5, S7 e "worker morto" da auditoria de sincronização (relat_audit):

* ``asyncio.CancelledError`` no conector é ``BaseException``: passava por todos os
  ``except Exception`` e a execução ficava 'executando', sem fim, até 60 min;
* o único critério de órfã era a IDADE (``iniciada_em`` além de SYNC_TRAVADA_S): a
  execução morta num redeploy segurava a escola por até 60 min (o clique se juntava
  a ela), e a VIVA além disso era reivindicada;
* reivindicada a execução viva, o fim dela sobrescrevia o 'erro' ("Interrompida")
  com 'concluida'.

Agora quem roda dá sinal de vida no log da execução, a órfã é a que está calada há
mais de ``SYNC_SEM_SINAL_S`` (15 min) e o fim só grava sobre 'executando'.

Dados FICTÍCIOS, sem rede.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.sincronizacao import (
    SincronizacaoAlerta,
    SincronizacaoExecucao,
    SincronizacaoLog,
)
from app.sync import connectors, orchestrator, service, vault
from app.sync.interfaces import (
    ArquivoObtido,
    Conector,
    Credenciais,
    Estrategia,
    ResultadoValidacao,
)

EVENTO = "sync_execucao_finalizada"


@pytest.fixture(autouse=True)
def _como_em_producao(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="constela.sync")
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", False)
    monkeypatch.setattr(settings, "SYNC_SEM_SINAL_S", 900)
    monkeypatch.setattr(settings, "SYNC_TRAVADA_S", 3600)


class _Conector(Conector):
    plataforma = "matific"
    versao = "9.9.9"
    estrategia = Estrategia.NAVEGADOR

    def __init__(self, *, arquivos=(), erro=None, durante=None):
        self._arquivos, self._erro, self._durante = list(arquivos), erro, durante

    async def testar_credenciais(self, cred, ctx):
        return ResultadoValidacao(True, "ok", "ok")

    async def localizar_relatorios(self, cred, ctx):
        return []

    async def obter(self, cred, rel, ctx):
        raise NotImplementedError

    async def sincronizar(self, cred, ctx):
        ctx.log("download", "info", "baixando (fake)")
        if self._durante is not None:
            self._durante()
        if self._erro is not None:
            raise self._erro
        return self._arquivos


def _analise_ana():
    from app.services import importacao as svc
    a = svc.Analise(plataforma="matific", formato="resumo", turma_detectada="")
    a.linhas = [svc.LinhaImportacao(numero=1, nome="Ana Beatriz Souza",
                dados={"atividades": 10, "estrelas": 3, "pontuacao_media": 70.0})]
    return a, "xlsx"


def _instalar(db, escola_id, monkeypatch, conector):
    vault.salvar_credencial(db, escola_id, "matific", Credenciais(usuario="u", senha="p"))
    db.commit()
    monkeypatch.setitem(connectors._REGISTRO, "matific", conector)
    monkeypatch.setattr(orchestrator, "_parsear", lambda a: _analise_ana())


def _em_execucao(db, escola_id, *, iniciada_ha_min, log_ha_min=None):
    """Uma execução em 'executando' iniciada há N min, com o último log há M min."""
    agora = service._agora()
    ex = SincronizacaoExecucao(escola_id=escola_id, plataforma="matific", origem="manual",
                               status="executando", tentativa=1, parametros={},
                               iniciada_em=agora - timedelta(minutes=iniciada_ha_min),
                               created_at=agora - timedelta(minutes=iniciada_ha_min))
    db.add(ex)
    db.flush()
    if log_ha_min is not None:
        db.add(SincronizacaoLog(execucao_id=ex.id, escola_id=escola_id, etapa="download",
                                nivel="info", mensagem="turma coletada (fake)",
                                created_at=agora - timedelta(minutes=log_ha_min)))
    db.commit()
    return ex


def _alertas(db, escola_id, tipo):
    return db.execute(select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == escola_id, SincronizacaoAlerta.tipo == tipo,
        SincronizacaoAlerta.resolvido.is_(False))).scalars().all()


def _fins(caplog, execucao_id):
    return [r for r in caplog.records
            if r.name == "constela.sync" and r.getMessage().startswith(EVENTO)
            and r.execucao_id == execucao_id]


# --------------------------------------------------------------------------
# N5: CancelledError no conector
# --------------------------------------------------------------------------
def test_cancelamento_no_conector_termina_erro_recuperavel_e_nunca_fica_executando(
        db, escola_completa, monkeypatch, caplog):
    escola = escola_completa["escola"]
    _instalar(db, escola.id, monkeypatch, _Conector(erro=asyncio.CancelledError()))
    ex = service.enfileirar(db, escola.id, "matific", origem="manual")
    db.commit()

    service.executar(db, ex)

    db.expire_all()
    ex = db.get(SincronizacaoExecucao, ex.id)
    assert ex.status == "erro"
    assert ex.motivo == "erro_navegador"
    assert ex.finalizada_em is not None
    assert "cancelada" in (ex.erro_resumo or "")
    assert _alertas(db, escola.id, "erro_navegador")
    assert [r.origem for r in _fins(caplog, ex.id)] == ["executar"]


# --------------------------------------------------------------------------
# Sinal de vida: a viva não é reivindicada, a morta sai em minutos
# --------------------------------------------------------------------------
def test_execucao_viva_alem_de_sync_travada_com_log_recente_nao_e_reivindicada(
        db, escola_completa, monkeypatch):
    """Coleta longa (70 min, além dos 60 de SYNC_TRAVADA_S) que escreveu no log há 2
    min: nenhum caminho a reivindica — nem o clique, nem o boot, nem o /status, nem
    o reaper do agendador."""
    eid = escola_completa["escola"].id
    viva = _em_execucao(db, eid, iniciada_ha_min=70, log_ha_min=2)

    assert service._esta_travada(viva) is False
    pedido, reaproveitada = service.enfileirar_ou_reaproveitar(db, eid, "matific",
                                                               origem="manual")
    assert (pedido.id, reaproveitada) == (viva.id, True)
    assert service.finalizar_orfas_no_boot(db) == 0
    assert service.liberar_fila_sem_agendador(db, eid) == 0
    assert service.recuperar_execucoes_travadas(db) == 0
    db.expire_all()
    assert db.get(SincronizacaoExecucao, viva.id).status == "executando"
    assert not _alertas(db, eid, "interrompida")


def test_execucao_sem_sinal_ha_16_min_e_liberada_pelo_clique(db, escola_completa):
    """Worker morto num redeploy 16 min atrás (antes: até 60 min de "Sincronizando",
    com o clique se juntando a ela)."""
    eid = escola_completa["escola"].id
    morta = _em_execucao(db, eid, iniciada_ha_min=20, log_ha_min=16)

    assert service._esta_travada(morta) is True
    pedido, reaproveitada = service.enfileirar_ou_reaproveitar(db, eid, "matific",
                                                               origem="manual")
    db.commit()
    assert reaproveitada is False and pedido.id != morta.id
    db.expire_all()
    antiga = db.get(SincronizacaoExecucao, morta.id)
    assert antiga.status == "erro" and "Interrompida" in antiga.erro_resumo
    assert _alertas(db, eid, "interrompida")


def test_execucao_sem_sinal_e_liberada_pela_leitura_do_status_com_agendador_desligado(
        db, escola_completa, caplog):
    """Agendador desligado (produção): sem clique, nada a libertava e o card ficava em
    "Sincronizando". A leitura do /status (a tela relê a cada 4 s) a encerra."""
    eid = escola_completa["escola"].id
    morta = _em_execucao(db, eid, iniciada_ha_min=17, log_ha_min=None)

    assert service.liberar_fila_sem_agendador(db, eid) == 1
    db.expire_all()
    antiga = db.get(SincronizacaoExecucao, morta.id)
    assert antiga.status == "erro"
    assert _alertas(db, eid, "interrompida")
    assert [r.origem for r in _fins(caplog, morta.id)] == ["travada_no_status"]
    # Idempotente: a segunda leitura não encerra nada.
    assert service.liberar_fila_sem_agendador(db, eid) == 0


def test_status_pelo_http_libera_a_execucao_morta(db, escola_completa, cliente):
    eid = escola_completa["escola"].id
    morta = _em_execucao(db, eid, iniciada_ha_min=30, log_ha_min=20)
    r = cliente.get(f"/api/v1/escolas/{eid}/sync/status")
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(SincronizacaoExecucao, morta.id).status == "erro"


def test_execucao_com_sinal_recente_nao_e_liberada_pelo_status(db, escola_completa):
    eid = escola_completa["escola"].id
    viva = _em_execucao(db, eid, iniciada_ha_min=40, log_ha_min=5)
    assert service.liberar_fila_sem_agendador(db, eid) == 0
    db.expire_all()
    assert db.get(SincronizacaoExecucao, viva.id).status == "executando"


def test_boot_e_reaper_usam_o_sinal_de_vida(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    morta = _em_execucao(db, eid, iniciada_ha_min=25, log_ha_min=18)
    assert service.finalizar_orfas_no_boot(db) == 1
    db.expire_all()
    assert db.get(SincronizacaoExecucao, morta.id).status == "erro"

    outra = _em_execucao(db, eid, iniciada_ha_min=25, log_ha_min=18)
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", True)
    assert service.liberar_fila_sem_agendador(db, eid) == 0      # ligado: é do reaper
    assert service.recuperar_execucoes_travadas(db) == 1
    db.expire_all()
    assert db.get(SincronizacaoExecucao, outra.id).status == "erro"


# --------------------------------------------------------------------------
# O próprio sinal de vida
# --------------------------------------------------------------------------
def test_batimento_escreve_so_sem_log_recente_e_para_fora_de_executando(
        db, escola_completa):
    eid = escola_completa["escola"].id
    ex = _em_execucao(db, eid, iniciada_ha_min=30, log_ha_min=1)

    def _linhas():
        return db.scalar(select(SincronizacaoLog.id).where(
            SincronizacaoLog.execucao_id == ex.id,
            SincronizacaoLog.mensagem.like("Em andamento%")).limit(1))

    # A coleta escreveu há 1 min (< 150 s): nada a acrescentar.
    assert service.registrar_batimento_execucao(db, ex.id) is True
    assert _linhas() is None
    # Calada há 3 min: a linha de sinal de vida entra, e reabre a janela.
    for linha in db.execute(select(SincronizacaoLog).where(
            SincronizacaoLog.execucao_id == ex.id)).scalars():
        linha.created_at = service._agora() - timedelta(minutes=3)
    db.commit()
    assert service.registrar_batimento_execucao(db, ex.id) is True
    assert _linhas() is not None
    db.expire_all()
    assert service._esta_travada(db.get(SincronizacaoExecucao, ex.id)) is False
    # Fora de 'executando', o sinal para.
    ex = db.get(SincronizacaoExecucao, ex.id)
    ex.status = "concluida"
    db.commit()
    assert service.registrar_batimento_execucao(db, ex.id) is False


def test_executar_da_sinal_de_vida_enquanto_roda_e_para_no_fim(
        db, escola_completa, monkeypatch):
    escola = escola_completa["escola"]
    batidas: list[int] = []
    trava = threading.Lock()

    def _sinal(execucao_id):
        with trava:
            batidas.append(execucao_id)
        return True

    monkeypatch.setattr(service, "batimento_execucao_s", lambda: 0.02)
    monkeypatch.setattr(service, "_sinal_de_vida_da_execucao", _sinal)
    arq = ArquivoObtido(conteudo=b"PKx", nome_arquivo="m.xlsx", plataforma="matific")
    _instalar(db, escola.id, monkeypatch,
              _Conector(arquivos=[arq], durante=lambda: time.sleep(0.3)))
    ex = service.enfileirar(db, escola.id, "matific", origem="manual")
    db.commit()

    service.executar(db, ex)
    with trava:
        durante = list(batidas)
    assert len(durante) >= 3 and set(durante) == {ex.id}
    time.sleep(0.15)
    with trava:
        assert len(batidas) == len(durante)          # parou com o fim da execução


# --------------------------------------------------------------------------
# S7: fechamento condicional
# --------------------------------------------------------------------------
def test_execucao_encerrada_por_outro_caminho_nao_volta_a_concluida(
        db, escola_completa, monkeypatch, caplog):
    """Outro worker reivindica a execução no meio da coleta (o reaper ou o clique de
    antes). Antes, o fim desta thread gravava 'concluida' por cima do 'erro'
    ("Interrompida") — com a nova tentativa já na fila."""
    escola = escola_completa["escola"]
    outra_sessao = sessionmaker(bind=db.get_bind())
    alvo: dict = {}

    def _reivindicada_por_outro():
        s = outra_sessao()
        try:
            assert service._finalizar_travada(s, s.get(SincronizacaoExecucao, alvo["id"]),
                                              origem="travada_no_pedido")
            s.commit()
        finally:
            s.close()

    arq = ArquivoObtido(conteudo=b"PKx", nome_arquivo="m.xlsx", plataforma="matific")
    _instalar(db, escola.id, monkeypatch,
              _Conector(arquivos=[arq], durante=_reivindicada_por_outro))
    ex = service.enfileirar(db, escola.id, "matific", origem="manual")
    db.commit()
    alvo["id"] = ex.id
    finalizada_pelo_outro = None

    service.executar(db, ex)

    db.expire_all()
    ex = db.get(SincronizacaoExecucao, alvo["id"])
    assert ex.status == "erro"
    assert ex.erro_resumo.startswith("Interrompida")
    finalizada_pelo_outro = ex.finalizada_em
    assert finalizada_pelo_outro is not None
    # O dado gravado fica, e as notas ficam para a marca de recálculo pendente.
    assert ex.recalculo_pendente is True
    assert vault.obter_linha(db, escola.id, "matific").status != "valida"
    # Uma linha do fim só: a de quem encerrou.
    assert [r.origem for r in _fins(caplog, ex.id)] == ["travada_no_pedido"]
    assert db.scalar(select(SincronizacaoLog.id).where(
        SincronizacaoLog.execucao_id == ex.id,
        SincronizacaoLog.mensagem.like("A execução já tinha sido encerrada%")).limit(1))


def test_falha_depois_de_encerrada_por_outro_nao_reabre_nem_reenfileira(
        db, escola_completa, monkeypatch, caplog):
    """A mesma corrida quando a coleta falha depois: o 'erro' de quem encerrou fica,
    sem segundo alerta, segunda linha do fim ou nova tentativa."""
    escola = escola_completa["escola"]
    outra_sessao = sessionmaker(bind=db.get_bind())
    alvo: dict = {}

    def _reivindicada_por_outro():
        s = outra_sessao()
        try:
            service._finalizar_travada(s, s.get(SincronizacaoExecucao, alvo["id"]),
                                       origem="travada_no_pedido")
            s.commit()
        finally:
            s.close()

    from app.sync.interfaces import ErroConector
    _instalar(db, escola.id, monkeypatch, _Conector(
        durante=_reivindicada_por_outro,
        erro=ErroConector("plataforma fora", codigo="falha_download", recuperavel=True)))
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", True)   # haveria retentativa
    ex = service.enfileirar(db, escola.id, "matific", origem="manual")
    db.commit()
    alvo["id"] = ex.id

    service.executar(db, ex)

    db.expire_all()
    ex = db.get(SincronizacaoExecucao, alvo["id"])
    assert ex.status == "erro" and ex.erro_resumo.startswith("Interrompida")
    assert not _alertas(db, escola.id, "falha_download")
    assert [r.origem for r in _fins(caplog, ex.id)] == ["travada_no_pedido"]
    assert db.scalar(select(SincronizacaoExecucao.id).where(
        SincronizacaoExecucao.escola_id == escola.id,
        SincronizacaoExecucao.status == "fila")) is None
