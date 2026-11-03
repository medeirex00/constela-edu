"""Cenários do GET /sync/dashboard (painel global, só admin global) para o teste
DOURADO da resposta (``test_sync_painel_dourado.py``) e o de ORÇAMENTO de idas ao
banco (``test_sync_painel_orcamento.py``).

``mundo`` monta uma rede DETERMINÍSTICA de 28 escolas (instantes fixos em relação a
``AGORA``, que o teste congela no serviço e nos pré-requisitos) com agenda diária
ou semanal nas duas plataformas, e deixa as ``vencidas`` primeiras SEM coleta em dia
— o que o painel conta como "desatualizada". As escolas se dividem em três: rede
com tudo contratado, rede SEM Matemática (o Matific vencido dela não conta) e
escola avulsa. Também há o que os pré-requisitos do agendador olham: credencial
ilegível, agenda no horário do backup, agenda com a próxima execução fora do
horário, execução presa (executando e na fila), fila viva (com sinal de vida),
recálculo pendente (superado e não superado) e escolas com credencial e sem
agenda (ganham agenda ao ligar).

Nomes e contas são fictícios; nenhuma senha aparece na resposta.
"""
from __future__ import annotations

import threading
from datetime import timedelta

from app.core.config import settings
from app.models import Escola
from app.models.rede import ModuloRede, Rede
from app.models.sincronizacao import (
    SincronizacaoAlerta,
    SincronizacaoConfig,
    SincronizacaoLog,
)
from app.sync import prerequisitos, scheduler, service
from tests.sync_status_cenarios import AGORA, _cred, _execucao, _h

N_ESCOLAS = 28
# Horários de Brasília das agendas (o das 08:00 = 11:00 UTC cruza o backup privado).
_HORAS = ("03:00", "06:30", "04:15", "08:00", "05:45")


def congelar(monkeypatch):
    """O "agora" fixo no serviço E nos pré-requisitos, o agendador desligado e o
    ambiente dos pré-requisitos fixo (workers, teto, processos, decisão do boot):
    a resposta não pode depender da máquina que roda o teste."""
    monkeypatch.setattr(service, "_agora", lambda: AGORA)
    monkeypatch.setattr(prerequisitos, "_agora", lambda: AGORA)
    monkeypatch.setattr(service, "_vivas_neste_processo", set())
    monkeypatch.setattr(service, "_semaforo_manual", threading.BoundedSemaphore(1))
    monkeypatch.setattr(scheduler, "_decisao", None)
    for nome, valor in (("SYNC_SCHEDULER_ENABLED", False), ("SYNC_SCHEDULER_FORCAR", "false"),
                        ("SYNC_WORKERS", 1), ("SYNC_POLL_S", 30), ("SYNC_TIMEOUT_S", 180),
                        ("SYNC_TETO_EXECUCAO_S", 2700), ("SYNC_TRAVADA_S", 3600)):
        monkeypatch.setattr(settings, nome, valor)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)


def _agenda(db, eid: int, plataforma: str, i: int, *, fora_do_horario: bool = False):
    semanal = i % 5 == 0
    conf = SincronizacaoConfig(
        escola_id=eid, plataforma=plataforma, ativo=True,
        cadencia="semanal" if semanal else "diaria",
        hora_local=_HORAS[i % len(_HORAS)], dia_semana=(i % 7) if semanal else None,
        created_at=_h(24 * 40), updated_at=_h(24 * 30))
    conf.proxima_execucao = (AGORA + timedelta(hours=2) if fora_do_horario
                             else service.calcular_proxima(conf, AGORA))
    db.add(conf)


def _rede(db, nome: str, desligados=()) -> int:
    rede = Rede(nome=nome, uf="SP")
    db.add(rede)
    db.flush()
    for modulo in desligados:
        db.add(ModuloRede(rede_id=rede.id, modulo=modulo, ativo=False))
    return rede.id


def mundo(db, base, *, vencidas: int, n_escolas: int = N_ESCOLAS, extras: int = 1) -> list[int]:
    """As ``n_escolas`` (a escola do fixture é a 1ª), com as ``vencidas`` primeiras
    sem coleta em dia. ``extras`` multiplica o que NÃO é agenda (execuções presas,
    recálculos pendentes, escolas sem agenda) — o orçamento não pode crescer com
    eles também. Devolve os ids das escolas."""
    rede_toda = _rede(db, "Rede Ficticia Toda Contratada")
    rede_leitura = _rede(db, "Rede Ficticia So Leitura", desligados=("matematica",))
    redes = (rede_toda, rede_leitura, None)
    escolas = [base["escola"]]
    for i in range(1, n_escolas):
        escolas.append(Escola(nome=f"Escola Ficticia Painel {i:02d}", ano_letivo_ativo=2026))
    db.add_all(escolas[1:])
    db.flush()
    for i, escola in enumerate(escolas):
        escola.rede_id = redes[i % 3]
        eid = escola.id
        so_leitura = escola.rede_id == rede_leitura
        for j, plat in enumerate(("elefante", "matific")):
            _cred(db, eid, plat, legivel=not (i % 9 == 4 and plat == "elefante"))
            _agenda(db, eid, plat, i, fora_do_horario=(i == 7 and plat == "matific"))
            # Vencida: a última coleta em dia passou do limite da cadência (2 dias
            # na diária, 10 na semanal). Na rede só de Leitura, só o Matific vence
            # — e ele está fora do plano: a escola NÃO conta como desatualizada.
            venceu = i < vencidas and not (so_leitura and plat == "elefante")
            horas = (24 * 12 if venceu else 6) + i * 0.1 + j * 0.05
            ex = _execucao(db, eid, plat, "concluida", horas=horas, qtd_alunos=3 + i % 4)
            ex.duracao_ms = 1000 * (10 + i) + 500 * j
    _extras(db, rede_toda, extras)
    db.commit()
    return [e.id for e in escolas]


def _extras(db, rede_id: int, n: int) -> None:
    """O que não é agenda, ``n`` vezes: escola com credencial e sem agenda, Elefante
    'executando' há 3 h e Matific na fila há 3 h sem sinal de vida (presas), fila
    viva, recálculo pendente não superado e superado, parcial sem aluno (não conta
    como sincronizada), coleta por período, alertas."""
    for k in range(n):
        escola = Escola(nome=f"Escola Ficticia Extra {k:02d}", ano_letivo_ativo=2026,
                        rede_id=rede_id if k % 2 == 0 else None)
        db.add(escola)
        db.flush()
        eid = escola.id
        _cred(db, eid, "elefante")
        _cred(db, eid, "matific")
        _execucao(db, eid, "elefante", "executando", horas=3)
        _execucao(db, eid, "matific", "fila", horas=3)
        marcada = _execucao(db, eid, "elefante", "parcial", horas=30 + k, qtd_alunos=2,
                            recalculo=True, motivo="coleta_parcial")
        _execucao(db, eid, "matific", "parcial", horas=40 + k, qtd_alunos=0,
                  motivo="coleta_parcial")
        _execucao(db, eid, "matific", "concluida", horas=20 + k, qtd_alunos=2,
                  parametros={"matific_start_date": "2026-10-01",
                              "matific_end_date": "2026-10-07"})
        db.add(SincronizacaoAlerta(escola_id=eid, plataforma="elefante",
                                   tipo="recalculo_pendente", severidade="warn",
                                   mensagem="Recálculo pendente (fictício).",
                                   execucao_id=marcada.id, created_at=_h(29)))
        db.add(SincronizacaoAlerta(escola_id=eid, plataforma="matific",
                                   tipo="falha_download", severidade="critico",
                                   mensagem="A plataforma não respondeu (fictício).",
                                   created_at=_h(5)))
        db.add(SincronizacaoAlerta(escola_id=eid, plataforma="matific",
                                   tipo="desatualizada", severidade="critico",
                                   mensagem="Sem sincronização bem-sucedida (fictício).",
                                   created_at=_h(50)))
        db.add(SincronizacaoAlerta(escola_id=eid, plataforma="elefante",
                                   tipo="falha_download", severidade="critico",
                                   mensagem="Resolvido (fictício).", resolvido=True,
                                   resolvido_em=_h(4), created_at=_h(8)))
        # Outra escola: fila viva (sinal de vida há 5 min) e recálculo superado.
        viva = Escola(nome=f"Escola Ficticia Viva {k:02d}", ano_letivo_ativo=2026)
        db.add(viva)
        db.flush()
        _cred(db, viva.id, "matific")
        ex = _execucao(db, viva.id, "matific", "fila", horas=2)
        db.add(SincronizacaoLog(execucao_id=ex.id, escola_id=viva.id, etapa="fila",
                                nivel="info", mensagem="Esperando a vez (fictício).",
                                created_at=_h(0.08)))
        _execucao(db, viva.id, "elefante", "parcial", horas=50 + k, qtd_alunos=1,
                  recalculo=True)
        _execucao(db, viva.id, "elefante", "concluida", horas=26 + k, qtd_alunos=1)
        # E uma escola cuja única execução é uma parcial SEM aluno aplicado: não
        # conta como sincronizada (``_filtro_aplicou_dado``).
        vazia = Escola(nome=f"Escola Ficticia Parcial Vazia {k:02d}", ano_letivo_ativo=2026)
        db.add(vazia)
        db.flush()
        _execucao(db, vazia.id, "matific", "parcial", horas=1 + k, qtd_alunos=0,
                  motivo="coleta_parcial")
