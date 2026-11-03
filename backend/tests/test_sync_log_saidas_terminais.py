"""UMA linha ``sync_execucao_finalizada`` por execução que chega a estado final —
por QUALQUER caminho, não só pelo fim de ``executar``.

Revisão de 28/10: o 868e3d2 escrevia a linha só no fim de ``service.executar``.
Chegavam a estado final SEM rastro no log de produção: o cancelamento de quem estava
na fila quando o módulo saiu do plano; a execução da fila substituída por um
"Sincronizar agora"; as travadas (pelo pedido, pelo reaper, pelo boot); a fila que só
o agendador rodaria; e o estado final já gravado (o commit antes do recálculo) de uma
``executar`` que saiu por exceção. Foi essa falta que impediu diagnosticar 21/10.

Agora cada caminho escreve a MESMA linha (mesmo evento e campos) com ``origem``, só
DEPOIS do commit que gravou o estado final (transação revertida não loga), e quem
perde o claim — o UPDATE condicional não pegou a linha — não escreve nada.

Dados FICTÍCIOS, sem rede. A variante PostgreSQL (com corridas de verdade entre
sessões) é ``test_sync_log_saidas_terminais_pg.py``.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.observabilidade import FormatadorJson
from app.models import ModuloRede, Rede
from app.models.sincronizacao import SincronizacaoExecucao
from app.services import modulos as svc_modulos
from app.sync import service
from app.sync.service import _agora
from tests._sync_nucleo_fakes import PlacarFake, credencial, instalar

EVENTO = "sync_execucao_finalizada"
TURMA = "3 ANO A (300396804)"
CAMPOS = ("execucao_id", "escola_id", "plataforma", "status", "motivo", "duracao_ms",
          "alunos_aplicados", "origem")


class Aborto(BaseException):
    """Um aborto que nenhum ``except Exception`` pega (como KeyboardInterrupt,
    SystemExit ou CancelledError), sem mexer no pytest."""


@pytest.fixture(autouse=True)
def _captura(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="constela.sync")
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", False)   # como em produção


def _fins(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records
            if r.name == "constela.sync" and r.getMessage().startswith(EVENTO)]


def _contagem(caplog) -> Counter:
    return Counter(r.execucao_id for r in _fins(caplog))


def _uma_linha(caplog, execucao_id, *, status, origem, proibidos=()):
    """Exatamente UMA linha para a execução, com o status e a origem esperados, os
    campos de sempre e nada de PII/texto livre (nem no texto, nem no JSON)."""
    linhas = [r for r in _fins(caplog) if r.execucao_id == execucao_id]
    assert len(linhas) == 1, (f"esperava UMA linha {EVENTO} para a execução "
                              f"{execucao_id}, veio {len(linhas)}")
    r = linhas[0]
    assert (r.status, r.origem) == (status, origem)
    assert r.origem in service.ORIGENS_DO_FIM
    for campo in CAMPOS:
        assert hasattr(r, campo), campo
    assert r.getMessage() == (f"{EVENTO} execucao={execucao_id} escola={r.escola_id} "
                              f"plataforma={r.plataforma} status={status} "
                              f"motivo={r.motivo or '-'}")
    saida = r.getMessage() + "\n" + FormatadorJson().format(r)
    assert json.loads(saida.split("\n", 1)[1])["origem"] == origem
    for proibido in ("ESCOLA TESTE", "http", *proibidos):
        assert proibido not in saida, proibido
    return r


def _execucao(db, escola_id, plataforma="matific", *, status="fila", origem="scheduler",
              tentativa=1, iniciada_ha_s=None, criada_ha_s=None, disponivel_em=None):
    ex = SincronizacaoExecucao(escola_id=escola_id, plataforma=plataforma, origem=origem,
                               status=status, tentativa=tentativa, parametros={},
                               disponivel_em=disponivel_em)
    if iniciada_ha_s is not None:
        ex.iniciada_em = _agora() - timedelta(seconds=iniciada_ha_s)
    if criada_ha_s is not None:
        ex.created_at = _agora() - timedelta(seconds=criada_ha_s)
    db.add(ex)
    db.commit()
    return ex.id


def _travada(db, escola_id, plataforma="matific", **kw):
    """Presa em 'executando' além de SYNC_TRAVADA_S (worker morto)."""
    return _execucao(db, escola_id, plataforma, status="executando",
                     iniciada_ha_s=settings.SYNC_TRAVADA_S + 600, **kw)


def _no_banco(db, execucao_id) -> SincronizacaoExecucao:
    db.expire_all()
    return db.get(SincronizacaoExecucao, execucao_id)


def _sem_matematica(db, escola):
    """A rede da escola sem o módulo do Matific."""
    rede = Rede(nome="Rede Ficticia Logs", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    for modulo in svc_modulos.TODOS:
        db.add(ModuloRede(rede_id=rede.id, modulo=modulo, ativo=(modulo != "matematica")))
    db.commit()


# --------------------------------------------------------------------------
# executar: saída cedo, claim perdido, fim normal e fim interrompido
# --------------------------------------------------------------------------
def test_executar_fora_do_plano_cancela_com_uma_linha(db, escola_completa, caplog):
    escola = escola_completa["escola"]
    eid = escola.id
    _sem_matematica(db, escola)
    exid = _execucao(db, eid, "matific", tentativa=2)
    ex = db.get(SincronizacaoExecucao, exid)

    service.executar(db, ex)
    service.executar(db, ex)          # de novo: já cancelada, ninguém a cancela outra vez

    no_banco = _no_banco(db, exid)
    assert no_banco.status == "cancelada"
    r = _uma_linha(caplog, exid, status="cancelada",
                   origem="cancelada_fora_do_plano", proibidos=(no_banco.erro_resumo,))
    assert (r.escola_id, r.plataforma, r.motivo) == (eid, "matific", None)
    assert (r.alunos_aplicados, r.duracao_ms) == (0, None)
    assert r.levelno == logging.WARNING


def test_executar_com_claim_perdido_nao_escreve(db, escola_completa, caplog):
    """Outro worker já a reivindicou: para quem perdeu não é um fim. A linha é de
    quem a encerrar — aqui, o reaper, depois que o outro worker morreu."""
    eid = escola_completa["escola"].id
    exid = _execucao(db, eid, "matific", status="executando", iniciada_ha_s=5)
    service.executar(db, db.get(SincronizacaoExecucao, exid))
    assert _no_banco(db, exid).status == "executando"
    assert _contagem(caplog)[exid] == 0

    db.execute(update(SincronizacaoExecucao).where(SincronizacaoExecucao.id == exid)
               .values(iniciada_em=_agora() - timedelta(seconds=settings.SYNC_TRAVADA_S
                                                         + 60)))
    db.commit()
    assert service.recuperar_execucoes_travadas(db) == 1
    _uma_linha(caplog, exid, status="erro", origem="travada_no_agendador")


def test_fim_normal_tem_origem_executar_e_a_segunda_chamada_nao_duplica(
        db, escola_completa, caplog):
    """Sem credencial → 'erro' pelo fim normal; a segunda chamada perde o claim."""
    eid = escola_completa["escola"].id
    exid = _execucao(db, eid, "matific", origem="manual")
    ex = db.get(SincronizacaoExecucao, exid)
    service.executar(db, ex)
    service.executar(db, ex)
    no_banco = _no_banco(db, exid)
    assert (no_banco.status, no_banco.motivo) == ("erro", "senha_invalida")
    r = _uma_linha(caplog, exid, status="erro", origem="executar",
                   proibidos=(no_banco.erro_resumo,))
    assert r.motivo == "senha_invalida" and r.duracao_ms == no_banco.duracao_ms
    assert sum(_contagem(caplog).values()) == 1


def _matific_com_dado(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [(f"u-{i}", a.nome, TURMA, 40 + i, 10 + i)
                     for i, a in enumerate(escola_completa["alunos"])]
    instalar(monkeypatch, placar=placar)
    ex = service.enfileirar(db, eid, "matific", origem="manual")
    db.commit()
    return ex


def _aborta(*_a, **_kw):
    raise Aborto("aborto simulado")


def _quebra(*_a, **_kw):
    raise RuntimeError("banco caiu (simulado)")


@pytest.mark.parametrize("onde,excecao", [
    ("_recalcular_ao_final", Aborto),               # deploy/Ctrl+C no recálculo
    ("atualizar_alerta_desatualizada", RuntimeError),  # falha de banco no fim
])
def test_estado_final_gravado_e_saida_por_excecao_escreve_uma_linha(
        db, escola_completa, monkeypatch, caplog, onde, excecao):
    """O commit antes do recálculo já gravou 'concluida'; a saída por exceção depois
    dele ainda deixa UMA linha (origem 'executar_interrompida')."""
    ex = _matific_com_dado(db, escola_completa, monkeypatch)
    exid = ex.id
    monkeypatch.setattr(service, onde, _aborta if excecao is Aborto else _quebra)

    with pytest.raises(excecao):
        service.executar(db, ex)
    db.rollback()

    no_banco = _no_banco(db, exid)
    assert no_banco.status == "concluida"
    if excecao is Aborto:              # morreu no recálculo: a marca avisa
        assert no_banco.recalculo_pendente is True
    r = _uma_linha(caplog, exid, status="concluida", origem="executar_interrompida",
                   proibidos=[a.nome for a in escola_completa["alunos"]])
    assert r.alunos_aplicados == 3 and r.duracao_ms is None
    assert r.levelno == logging.INFO


def test_aborto_antes_do_estado_final_nao_escreve_e_a_orfa_escreve_uma(
        db, escola_completa, monkeypatch, caplog):
    """Aborto ANTES de qualquer estado final: a execução segue 'executando' e não há
    linha — é a órfã. Quem a encerra depois (o boot) escreve a única linha."""
    eid = escola_completa["escola"].id
    exid = _execucao(db, eid, "matific", origem="manual")
    monkeypatch.setattr(service.vault, "obter_credencial", _aborta)
    with pytest.raises(Aborto):
        service.executar(db, db.get(SincronizacaoExecucao, exid))
    db.rollback()
    assert _no_banco(db, exid).status == "executando"
    assert _contagem(caplog)[exid] == 0

    db.execute(update(SincronizacaoExecucao).where(SincronizacaoExecucao.id == exid)
               .values(iniciada_em=_agora() - timedelta(seconds=settings.SYNC_TRAVADA_S
                                                         + 60)))
    db.commit()
    assert service.finalizar_orfas_no_boot(db) == 1
    _uma_linha(caplog, exid, status="erro", origem="orfa_no_boot")


# --------------------------------------------------------------------------
# Pedido manual substitui a da fila: linha no commit, nenhuma no rollback
# --------------------------------------------------------------------------
def test_pedido_manual_que_substitui_a_da_fila_escreve_no_commit(
        db, escola_completa, caplog):
    eid = escola_completa["escola"].id
    velha = _execucao(db, eid, "matific", origem="scheduler")
    nova, reaproveitada = service.enfileirar_ou_reaproveitar(db, eid, "matific",
                                                             origem="manual")
    assert not reaproveitada and nova.id != velha
    assert _contagem(caplog)[velha] == 0          # antes do commit, nada no log
    db.commit()
    r = _uma_linha(caplog, velha, status="cancelada", origem="cancelada_por_pedido_manual",
                   proibidos=(_no_banco(db, velha).erro_resumo,))
    assert r.alunos_aplicados == 0
    assert _contagem(caplog)[nova.id] == 0        # a nova está na fila: não é fim
    db.commit()                                   # outro commit não repete a linha
    assert _contagem(caplog)[velha] == 1


def test_substituicao_revertida_nao_escreve(db, escola_completa, caplog):
    """O rollback (o 409 do "Sincronizar agora") desfaz o cancelamento: ele não
    aconteceu, e nenhum commit seguinte faz a linha aparecer. O pedido refeito e
    commitado escreve UMA — não duas."""
    eid = escola_completa["escola"].id
    velha = _execucao(db, eid, "matific", origem="scheduler")
    service.enfileirar_ou_reaproveitar(db, eid, "matific", origem="manual")
    db.rollback()
    assert _no_banco(db, velha).status == "fila"
    db.commit()
    assert _contagem(caplog)[velha] == 0

    service.enfileirar_ou_reaproveitar(db, eid, "matific", origem="manual")
    db.commit()
    _uma_linha(caplog, velha, status="cancelada", origem="cancelada_por_pedido_manual")


def test_substituicao_em_sessao_fechada_sem_commit_nao_escreve(
        db, escola_completa, caplog):
    eid = escola_completa["escola"].id
    velha = _execucao(db, eid, "matific", origem="scheduler")
    with Session(bind=db.get_bind()) as outra:
        service.enfileirar_ou_reaproveitar(outra, eid, "matific", origem="manual")
    assert _no_banco(db, velha).status == "fila"
    assert _contagem(caplog)[velha] == 0

    db.commit()                      # a sessão de quem pediu de novo
    service.enfileirar_ou_reaproveitar(db, eid, "matific", origem="manual")
    db.commit()
    _uma_linha(caplog, velha, status="cancelada", origem="cancelada_por_pedido_manual")


def test_cancelamento_em_savepoint_revertido_nao_escreve_e_liberado_escreve(
        db, escola_completa, caplog):
    eid = escola_completa["escola"].id
    revertida = _execucao(db, eid, "matific", origem="scheduler")
    mantida = _execucao(db, eid, "elefante", origem="scheduler")
    try:
        with db.begin_nested():
            assert service._cancelar_na_fila(db, db.get(SincronizacaoExecucao, revertida),
                                             "teste", origem="cancelada_na_fila")
            raise RuntimeError("desfaz o savepoint")
    except RuntimeError:
        pass
    with db.begin_nested():
        assert service._cancelar_na_fila(db, db.get(SincronizacaoExecucao, mantida),
                                         "teste", origem="cancelada_na_fila")
    assert _contagem(caplog)[mantida] == 0        # RELEASE SAVEPOINT não é o commit
    db.commit()
    assert _no_banco(db, revertida).status == "fila"
    assert _contagem(caplog)[revertida] == 0
    _uma_linha(caplog, mantida, status="cancelada", origem="cancelada_na_fila")


def test_sincronizar_agora_que_substitui_a_da_fila_escreve_uma_linha(
        db, escola_completa, cliente, monkeypatch, caplog):
    """Pela rota: a sessão da requisição commita e a linha sai uma vez."""
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    velha = _execucao(db, eid, "elefante", origem="scheduler", disponivel_em=_agora())
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)
    r = cliente.post(f"/api/v1/escolas/{eid}/sync/agora?plataforma=elefante")
    assert r.status_code == 200, r.text
    nova = r.json()[0]["id"]
    assert nova != velha
    _uma_linha(caplog, velha, status="cancelada", origem="cancelada_por_pedido_manual")
    assert _contagem(caplog)[nova] == 0


# --------------------------------------------------------------------------
# Travadas: pelo pedido, pelo reaper do agendador e pelo boot
# --------------------------------------------------------------------------
def test_travada_achada_pelo_pedido_escreve_uma_linha(db, escola_completa, caplog):
    eid = escola_completa["escola"].id
    travada = _travada(db, eid, "matific", origem="manual")
    nova = service.enfileirar(db, eid, "matific", origem="manual")
    assert _contagem(caplog)[travada] == 0
    db.commit()
    r = _uma_linha(caplog, travada, status="erro", origem="travada_no_pedido")
    assert (r.alunos_aplicados, r.duracao_ms, r.motivo) == (None, None, None)
    assert _contagem(caplog)[nova.id] == 0


def test_reaper_do_agendador_escreve_uma_linha_e_a_nova_tentativa_nenhuma(
        db, escola_completa, caplog):
    eid = escola_completa["escola"].id
    travada = _travada(db, eid, "elefante")
    assert service.recuperar_execucoes_travadas(db) == 1
    assert service.recuperar_execucoes_travadas(db) == 0
    _uma_linha(caplog, travada, status="erro", origem="travada_no_agendador")
    assert sum(_contagem(caplog).values()) == 1       # a nova tentativa está na fila


def test_boot_escreve_uma_linha_por_orfa_e_por_fila_liberada(db, escola_completa, caplog):
    eid = escola_completa["escola"].id
    orfa = _travada(db, eid, "matific")
    agendada = _execucao(db, eid, "elefante", origem="scheduler")
    assert service.finalizar_orfas_no_boot(db) == 2
    assert service.finalizar_orfas_no_boot(db) == 0   # o boot de outro worker
    _uma_linha(caplog, orfa, status="erro", origem="orfa_no_boot")
    _uma_linha(caplog, agendada, status="cancelada", origem="fila_sem_agendador")
    assert sum(_contagem(caplog).values()) == 2


def test_status_libera_a_fila_com_uma_linha_por_execucao(
        db, escola_completa, cliente, caplog):
    """Agendador desligado: o GET /status cancela a agendada e a manual órfã (sem
    ninguém esperando) — uma linha cada, e as leituras seguintes não repetem."""
    eid = escola_completa["escola"].id
    agendada = _execucao(db, eid, "elefante", origem="scheduler")
    orfa = _execucao(db, eid, "matific", origem="manual",
                     criada_ha_s=settings.SYNC_TRAVADA_S + 600)
    for _ in range(2):
        r = cliente.get(f"/api/v1/escolas/{eid}/sync/status")
        assert r.status_code == 200, r.text
    _uma_linha(caplog, agendada, status="cancelada", origem="fila_sem_agendador")
    _uma_linha(caplog, orfa, status="cancelada", origem="fila_manual_orfa")
    assert sum(_contagem(caplog).values()) == 2


# --------------------------------------------------------------------------
# Claim perdido nas outras transições: nenhuma linha para quem perdeu
# --------------------------------------------------------------------------
def test_quem_perde_a_travada_ou_o_cancelamento_nao_escreve(db, escola_completa, caplog):
    eid = escola_completa["escola"].id
    travada = _travada(db, eid, "matific")
    na_fila = _execucao(db, eid, "elefante")
    ex_travada = db.get(SincronizacaoExecucao, travada)
    ex_fila = db.get(SincronizacaoExecucao, na_fila)

    # Quem vence (outra sessão, outro processo) encerra e commita.
    with Session(bind=db.get_bind()) as vencedora:
        assert service._finalizar_travada(
            vencedora, vencedora.get(SincronizacaoExecucao, travada),
            origem="travada_no_agendador")
        vencedora.execute(update(SincronizacaoExecucao)
                          .where(SincronizacaoExecucao.id == na_fila)
                          .values(status="executando", iniciada_em=_agora()))
        vencedora.commit()

    # Quem chega depois, com o objeto velho na mão, perde o UPDATE condicional.
    assert service._finalizar_travada(db, ex_travada, origem="orfa_no_boot") is False
    assert service._cancelar_na_fila(db, ex_fila, "teste",
                                     origem="fila_sem_agendador") is False
    db.commit()
    _uma_linha(caplog, travada, status="erro", origem="travada_no_agendador")
    assert _contagem(caplog)[na_fila] == 0            # foi reivindicada, não encerrada
