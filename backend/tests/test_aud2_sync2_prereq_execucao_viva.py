"""Pré-requisito ``execucoes_presas`` do agendador: a execução 'executando' que ainda dá
sinal de vida não é "presa", por mais antiga que seja.

Antes, a verificação decidia pela IDADE (iniciada há mais de min(teto, SYNC_TRAVADA_S)
= 45 min com o padrão), enquanto o resto do sistema decide pelo SINAL DE VIDA (o último
registro no log há mais de ``SYNC_SEM_SINAL_S``): o boot (``finalizar_orfas_no_boot``)
mantinha a execução viva e o pré-requisito a chamava de presa. O teto de 45 min vale
só para a coleta; a aplicação e o recálculo vêm depois. Resultado: um deploy (ou o
reinício de um worker) no meio de uma coleta longa do Elefante subia o processo novo
SEM agendador, com um ERROR mandando "liberar" uma execução viva — e prometendo que o
boot a finalizaria, o que não acontece.

Agora o 'executando' é decidido pela mesma regra do boot (``service._orfas_em_execucao``).

Dados 100% fictícios; nenhum agendador é ligado.
"""
from __future__ import annotations

from datetime import timedelta

from app.core.config import settings
from app.models.sincronizacao import SincronizacaoExecucao, SincronizacaoLog
from app.sync import prerequisitos, service


class _Cfg:
    """``settings`` com o teto e a janela padrão do contrato."""

    def __init__(self, **sobre):
        self.__dict__["_sobre"] = {"SYNC_TETO_EXECUCAO_S": 2700, "SYNC_TRAVADA_S": 3600,
                                   "SYNC_SEM_SINAL_S": 900, **sobre}

    def __getattr__(self, nome):
        sobre = self.__dict__["_sobre"]
        return sobre[nome] if nome in sobre else getattr(settings, nome)


def _presas(db, agora, cfg=None):
    resultado = {v.id: v for v in prerequisitos.prerequisitos_agendador(
        db, cfg or _Cfg(), agora=agora)}
    return resultado["execucoes_presas"]


def _executando(db, eid, plataforma, *, iniciada_ha_min, sinal_ha_min=None):
    agora = service._agora()
    ex = SincronizacaoExecucao(escola_id=eid, plataforma=plataforma, origem="manual",
                               status="executando",
                               iniciada_em=agora - timedelta(minutes=iniciada_ha_min),
                               created_at=agora - timedelta(minutes=iniciada_ha_min))
    db.add(ex)
    db.flush()
    if sinal_ha_min is not None:
        db.add(SincronizacaoLog(execucao_id=ex.id, escola_id=eid, etapa="aplicacao",
                                nivel="info", mensagem="ainda trabalhando (ensaio)",
                                created_at=agora - timedelta(minutes=sinal_ha_min)))
    db.commit()
    return ex


def test_execucao_viva_ha_50_min_nao_e_presa_e_o_boot_concorda(db, escola_completa,
                                                                monkeypatch):
    monkeypatch.setattr(settings, "SYNC_SEM_SINAL_S", 900)
    eid = escola_completa["escola"].id
    viva = _executando(db, eid, "elefante", iniciada_ha_min=50, sinal_ha_min=1)
    # Para o boot, está viva: nenhuma órfã, nada finalizado.
    assert service._orfas_em_execucao(db) == []
    assert service.finalizar_orfas_no_boot(db) == 0
    db.refresh(viva)
    assert viva.status == "executando"

    v = _presas(db, service._agora())
    # Antes: False — "#1 escola 1/elefante 'executando' há 50 min. Libere-as (o boot
    # finaliza as órfãs antigas...)".
    assert v.critico and v.ok is True, v.motivo


def test_execucao_viva_alem_da_janela_de_60_min_continua_viva(db, escola_completa):
    """A aplicação e o recálculo vêm depois do teto da coleta: com sinal de vida
    recente, nem 70 min (além de SYNC_TRAVADA_S) a tornam presa."""
    eid = escola_completa["escola"].id
    _executando(db, eid, "elefante", iniciada_ha_min=70, sinal_ha_min=2)
    assert _presas(db, service._agora()).ok is True


def test_execucao_sem_sinal_de_vida_e_presa_e_o_boot_a_libera(db, escola_completa,
                                                              monkeypatch):
    monkeypatch.setattr(settings, "SYNC_SEM_SINAL_S", 900)
    eid = escola_completa["escola"].id
    muda = _executando(db, eid, "elefante", iniciada_ha_min=50, sinal_ha_min=16)
    v = _presas(db, service._agora())
    assert v.critico and v.ok is False
    assert f"#{muda.id} escola {eid}/elefante 'executando' sem sinal de vida" in v.motivo
    assert "15 min" in v.motivo
    # O que a mensagem promete é verdade: o boot encerra exatamente esta.
    assert [ex.id for ex in service._orfas_em_execucao(db)] == [muda.id]
    assert service.finalizar_orfas_no_boot(db) == 1
    assert _presas(db, service._agora()).ok is True


def test_janela_do_sinal_de_vida_vem_da_configuracao_avaliada(db, escola_completa):
    """A verificação usa a ``SYNC_SEM_SINAL_S`` da configuração e o ``agora`` que
    recebe (o painel global e os testes avaliam com os seus)."""
    eid = escola_completa["escola"].id
    _executando(db, eid, "matific", iniciada_ha_min=50, sinal_ha_min=10)
    agora = service._agora()
    assert _presas(db, agora, _Cfg(SYNC_SEM_SINAL_S=900)).ok is True
    assert _presas(db, agora, _Cfg(SYNC_SEM_SINAL_S=300)).ok is False
    # Meia hora depois, sem novo sinal: presa também com a janela de 15 min.
    assert _presas(db, agora + timedelta(minutes=30), _Cfg()).ok is False


def test_teto_coerente_nao_cita_mais_a_verificacao_por_idade(db):
    v = {x.id: x for x in prerequisitos.prerequisitos_agendador(
        db, _Cfg(SYNC_TRAVADA_S=1800, SYNC_TIMEOUT_S=180),
        agora=service._agora())}["teto_coerente"]
    assert v.ok is False
    # Antes: "a verificação 'execucoes_presas' acusaria como presa uma coleta ainda
    # VIVA entre 1800 s e 2700 s" — ela decide pelo sinal de vida, não pela idade.
    assert "execucoes_presas" not in v.motivo
    assert "sinal de vida" in v.motivo and "(3600 s)" in v.motivo, v.motivo
