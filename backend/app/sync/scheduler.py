"""Scheduler/worker de sincronização — thread de fundo no processo da API.

Ciclo (a cada ``SYNC_POLL_S``): (1) enfileira as configs de agenda vencidas;
(2) processa as execuções da fila (respeitando ``disponivel_em``/backoff), até
``SYNC_WORKERS`` por rodada. Cada execução usa sessão de banco PRÓPRIA e é
isolada em try/except — uma falha nunca derruba o worker.

Arquitetura de fila em banco: hoje o worker roda embutido na API (deploy
pequeno). Para escala horizontal, o MESMO código roda como serviço separado
apontando para o mesmo banco — nada muda (a fila é a fonte da verdade).

DESLIGADO por padrão (``SYNC_SCHEDULER_ENABLED``): fail-safe. E, mesmo ligado
pela variável, RECUSA subir quando um pré-requisito CRÍTICO falha
(``app/sync/prerequisitos.py``: teto de tempo, status honesto, selo de frescor,
nenhuma execução presa, credenciais legíveis, recálculo em dia, horário fora do
backup e em Brasília, workers coerentes) — log claro e o app segue de pé. Só
``SYNC_SCHEDULER_FORCAR=true`` (decisão do dono) passa por cima da recusa. A
checklist da reativação está em ``docs/sync/REATIVAR-AGENDADOR.md``.
"""
from __future__ import annotations

import logging
import threading

from app.core.config import settings

logger = logging.getLogger("constela.sync")

_parar = threading.Event()
_thread: threading.Thread | None = None
# O que ESTE processo decidiu na última chamada de ``iniciar``: "desligado" (a
# variável), "recusado" (pré-requisito crítico falho), "iniciado" ou "forcado"
# (SYNC_SCHEDULER_FORCAR). None = ``iniciar`` ainda não rodou. O painel global
# mostra, para "agendador desligado" não esconder o motivo.
_decisao: str | None = None


def _uma_rodada() -> None:
    """Uma varredura: agenda vencida + fila. Sessão própria, sempre fechada."""
    from app.core.database import SessionLocal
    from app.sync import service

    db = SessionLocal()
    try:
        service.recuperar_execucoes_travadas(db)  # retomada após crash/redeploy
        # AUTO-CURA: garante a agenda diária de quem tem credencial e nenhuma
        # config (elimina o "re-salvar credencial"; sobrevive a restart pois a
        # config fica no Postgres, e se recria caso suma).
        service.garantir_agendas_diarias(db)
        # Blindagem: sinaliza integrações que envelheceram em silêncio (sem sync
        # bem-sucedida além do limite) — antes de enfileirar as vencidas.
        service.verificar_obsolescencia(db)
        service.enfileirar_agendados(db)
        pendentes = service.proximas_da_fila(db, limite=settings.SYNC_WORKERS)
        ids = [e.id for e in pendentes]
    finally:
        db.close()

    for execucao_id in ids:               # cada execução em sessão isolada
        if _parar.is_set():
            break
        try:
            service.executar_por_id(execucao_id)
        except Exception:                 # noqa: BLE001 — worker nunca cai
            logger.exception("Falha ao processar execução %s", execucao_id)

    _coletar_avaliacoes_pendentes()       # robô das avaliações externas (IDEB etc.)


def _coletar_avaliacoes_pendentes() -> None:
    """Coleta as fontes de avaliação externa com agenda vencida (o "robô" do IDEB).
    Sessão própria e isolada: um erro aqui nunca afeta o worker de sync.

    O robô é LEGADO (grava sem prévia) e fica DESLIGADO por padrão, atrás de
    ``AVALIACOES_ROBO_HABILITADO`` — ligar este agendador NÃO o liga junto."""
    from app.services import avaliacoes

    if not avaliacoes.robo_habilitado():
        return
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        n = avaliacoes.coletar_pendentes(db)
        if n:
            logger.info("Coleta de avaliações externas: %s fonte(s) processada(s).", n)
    except Exception:                     # noqa: BLE001 — nunca derruba o worker
        logger.exception("Falha na coleta agendada de avaliações externas.")
    finally:
        db.close()


def _loop() -> None:
    logger.info("Scheduler de sincronização iniciado (poll=%ss).", settings.SYNC_POLL_S)
    while not _parar.is_set():
        try:
            _uma_rodada()
        except Exception:                 # noqa: BLE001
            logger.exception("Erro no loop do scheduler de sincronização.")
        _parar.wait(settings.SYNC_POLL_S)
    logger.info("Scheduler de sincronização parado.")


def _abrir_sessao():
    """Sessão própria da verificação de pré-requisitos (ponto de troca nos testes)."""
    from app.core.database import SessionLocal

    return SessionLocal()


def _avaliar_prerequisitos():
    """Roda ``prerequisitos_agendador`` numa sessão própria, SÓ de leitura."""
    from app.sync import prerequisitos

    db = _abrir_sessao()
    try:
        return prerequisitos.prerequisitos_agendador(db, settings)
    finally:
        try:
            db.rollback()
        finally:
            db.close()


def _liberado_pelos_prerequisitos() -> bool:
    """Pode subir? Com um pré-requisito CRÍTICO falho (ou a própria verificação
    quebrada), NÃO — a menos que ``SYNC_SCHEDULER_FORCAR``. Nunca levanta: quem
    chama é o import do ``app.main``, e o app tem de seguir de pé."""
    global _decisao
    from app.sync import prerequisitos

    try:
        falhos = prerequisitos.criticos_falhos(_avaliar_prerequisitos())
        descricao = " | ".join(f"{v.id}: {v.motivo}" for v in falhos)
    except Exception as exc:  # noqa: BLE001 — a verificação nunca derruba o boot
        logger.exception("Pré-requisitos do agendador: a verificação falhou.")
        falhos, descricao = None, f"verificação indisponível ({type(exc).__name__})"
    if falhos == []:
        _decisao = "iniciado"
        logger.info("Agendador de sincronização: todos os pré-requisitos críticos ok.")
        return True
    if prerequisitos.forcar_habilitado(settings):
        _decisao = "forcado"
        logger.warning(
            "Agendador de sincronização INICIADO À FORÇA (SYNC_SCHEDULER_FORCAR=true) "
            "apesar de pré-requisito crítico falho — %s", descricao)
        return True
    _decisao = "recusado"
    logger.error(
        "Agendador de sincronização NÃO iniciado: pré-requisito crítico falho — %s. "
        "Corrija e reinicie (ou, só por decisão do dono, SYNC_SCHEDULER_FORCAR=true). "
        "Checklist: docs/sync/REATIVAR-AGENDADOR.md. O restante da API segue normal; "
        "a coleta continua pelo \"Sincronizar agora\".", descricao)
    return False


def iniciar() -> bool:
    """Sobe o worker se habilitado, ainda não rodando E com os pré-requisitos
    críticos ok (ou forçado). Retorna se subiu."""
    global _thread, _decisao
    if not settings.SYNC_SCHEDULER_ENABLED:
        _decisao = "desligado"
        return False
    if _thread is not None and _thread.is_alive():
        return False
    if not _liberado_pelos_prerequisitos():
        return False
    _parar.clear()
    _thread = threading.Thread(target=_loop, name="sync-scheduler", daemon=True)
    _thread.start()
    return True


def parar(timeout: float = 5.0) -> None:
    _parar.set()
    if _thread is not None:
        _thread.join(timeout=timeout)


def ativo() -> bool:
    return _thread is not None and _thread.is_alive()


def decisao() -> str | None:
    """A decisão da última chamada de ``iniciar`` neste processo (ver ``_decisao``)."""
    return _decisao
