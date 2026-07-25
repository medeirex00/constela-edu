"""Blindagem da integração: detecção de OBSOLESCÊNCIA (dados envelhecendo em
silêncio). Uma integração AGENDADA sem sincronização bem-sucedida além do limite
da cadência gera o alerta 'desatualizada' — o sinal de "a coleta não quebrou sem
ninguém notar". Resolve-se sozinho quando uma sync conclui com dados.
"""
from datetime import timedelta

from sqlalchemy import func, select

from app.models.sincronizacao import (SincronizacaoAlerta, SincronizacaoConfig,
                                       SincronizacaoExecucao)
from app.sync import service
from app.sync.service import _agora


def _config(db, escola_id, plataforma="matific", cadencia="diaria", ativo=True,
            ativa_ha_dias=0):
    # A referência de frescor é a ATIVAÇÃO da agenda (updated_at), não a criação;
    # o helper marca ambos para simular "agenda ativa há N dias".
    marco = _agora() - timedelta(days=ativa_ha_dias)
    cfg = SincronizacaoConfig(
        escola_id=escola_id, plataforma=plataforma, cadencia=cadencia, ativo=ativo,
        created_at=marco, updated_at=marco)
    db.add(cfg)
    db.flush()
    return cfg


def _concluida(db, escola_id, plataforma, ha_dias):
    ex = SincronizacaoExecucao(
        escola_id=escola_id, plataforma=plataforma, origem="scheduler",
        status="concluida", finalizada_em=_agora() - timedelta(days=ha_dias))
    db.add(ex)
    db.flush()
    return ex


def _alertas_abertos(db, escola_id, tipo="desatualizada") -> int:
    return db.scalar(select(func.count(SincronizacaoAlerta.id)).where(
        SincronizacaoAlerta.escola_id == escola_id,
        SincronizacaoAlerta.tipo == tipo,
        SincronizacaoAlerta.resolvido.is_(False))) or 0


def test_limite_por_cadencia():
    assert service.limite_obsolescencia("diaria") == timedelta(days=2)
    assert service.limite_obsolescencia("semanal") == timedelta(days=10)
    assert service.limite_obsolescencia("manual") is None


def test_ultimo_sucesso_ignora_falhas_e_sem_dados(db, escola_completa):
    eid = escola_completa["escola"].id
    _concluida(db, eid, "matific", ha_dias=3)
    _concluida(db, eid, "matific", ha_dias=1)  # o sucesso mais recente
    # Uma falha e um 'sem_dados' recentes NÃO contam como frescor.
    db.add(SincronizacaoExecucao(escola_id=eid, plataforma="matific", origem="scheduler",
                                 status="erro", finalizada_em=_agora()))
    db.add(SincronizacaoExecucao(escola_id=eid, plataforma="matific", origem="scheduler",
                                 status="sem_dados", finalizada_em=_agora()))
    db.flush()
    ultimo = service.ultimo_sucesso_em(db, eid, "matific")
    assert ultimo is not None and (_agora() - ultimo).days == 1


def test_esta_desatualizada_quando_sem_sucesso_ha_muito(db, escola_completa):
    eid = escola_completa["escola"].id
    cfg = _config(db, eid, cadencia="diaria", ativa_ha_dias=5)  # nunca sincronizou
    assert service.esta_desatualizada(db, cfg) is True
    # Um sucesso recente zera a obsolescência.
    _concluida(db, eid, "matific", ha_dias=0)
    assert service.esta_desatualizada(db, cfg) is False


def test_manual_e_inativa_nunca_desatualizam(db, escola_completa):
    eid = escola_completa["escola"].id
    manual = _config(db, eid, plataforma="matific", cadencia="manual", ativa_ha_dias=30)
    inativa = _config(db, eid, plataforma="elefante", cadencia="diaria", ativo=False,
                      ativa_ha_dias=30)
    assert service.esta_desatualizada(db, manual) is False
    assert service.esta_desatualizada(db, inativa) is False


def test_verificar_obsolescencia_abre_alerta_e_deduplica(db, escola_completa):
    eid = escola_completa["escola"].id
    _config(db, eid, plataforma="matific", cadencia="diaria", ativa_ha_dias=5)
    # Uma fresca (com sucesso hoje) NÃO deve alertar.
    _config(db, eid, plataforma="elefante", cadencia="diaria", ativa_ha_dias=5)
    _concluida(db, eid, "elefante", ha_dias=0)
    db.commit()

    assert service.verificar_obsolescencia(db) == 1        # só a matific
    assert _alertas_abertos(db, eid) == 1
    # Rodar de novo NÃO duplica (dedup no abrir_alerta).
    service.verificar_obsolescencia(db)
    assert _alertas_abertos(db, eid) == 1


def test_sync_bem_sucedida_resolve_desatualizada(db, escola_completa):
    eid = escola_completa["escola"].id
    service.abrir_alerta(db, eid, "matific", "desatualizada", "dado velho",
                         severidade="critico")
    db.flush()
    assert _alertas_abertos(db, eid) == 1
    # É o mesmo caminho chamado pela sync ao concluir COM dados.
    service.resolver_alertas(db, eid, "matific", ("desatualizada",))
    assert _alertas_abertos(db, eid) == 0


def test_referencia_de_frescor_e_a_ativacao_nao_a_criacao(db, escola_completa):
    """Regressão (achado da revisão): uma agenda ANTIGA reativada AGORA não pode
    alertar na hora. A folga da cadência conta do momento da ativação (updated_at),
    não da criação da linha (created_at)."""
    eid = escola_completa["escola"].id
    recem = SincronizacaoConfig(escola_id=eid, plataforma="matific", cadencia="diaria",
                                ativo=True, created_at=_agora() - timedelta(days=30),
                                updated_at=_agora())  # reativada agora
    assert service.esta_desatualizada(db, recem) is False
    # Já ativa há 30 dias sem NENHUM sucesso → aí sim está desatualizada.
    velha = SincronizacaoConfig(escola_id=eid, plataforma="matific", cadencia="diaria",
                                ativo=True, created_at=_agora() - timedelta(days=30),
                                updated_at=_agora() - timedelta(days=30))
    assert service.esta_desatualizada(db, velha) is True


def test_desligar_agenda_resolve_alerta_de_obsolescencia(db, escola_completa, cliente):
    """Regressão (achado da revisão): ao DESLIGAR a agenda (ou virar manual), o
    alerta 'desatualizada' aberto tem de fechar — senão ficaria órfão para sempre."""
    eid = escola_completa["escola"].id
    service.abrir_alerta(db, eid, "matific", "desatualizada", "velho", severidade="critico")
    db.commit()
    assert _alertas_abertos(db, eid) == 1

    r = cliente.put(f"/api/v1/escolas/{eid}/sync/config/matific",
                    json={"ativo": False, "cadencia": "manual"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert _alertas_abertos(db, eid) == 0
