"""Scheduler/worker de sincronização — thread de fundo no processo da API.

Ciclo (a cada ``SYNC_POLL_S``): (1) enfileira as configs de agenda vencidas;
(2) processa as execuções da fila (respeitando ``disponivel_em``/backoff), até
``SYNC_WORKERS`` por rodada. Cada execução usa sessão de banco PRÓPRIA e é
isolada em try/except — uma falha nunca derruba o worker.

Arquitetura de fila em banco: hoje o worker roda embutido na API (deploy
pequeno). Para escala horizontal, o MESMO código roda como serviço separado
apontando para o mesmo banco — nada muda (a fila é a fonte da verdade).

DESLIGADO por padrão (``SYNC_SCHEDULER_ENABLED``): fail-safe. Ligar em produção
após configurar credenciais.
"""
from __future__ import annotations

import logging
import threading

from app.core.config import settings

logger = logging.getLogger("constela.sync")

_parar = threading.Event()
_thread: threading.Thread | None = None


def _uma_rodada() -> None:
    """Uma varredura: agenda vencida + fila. Sessão própria, sempre fechada."""
    from app.core.database import SessionLocal
    from app.sync import service

    db = SessionLocal()
    try:
        service.recuperar_execucoes_travadas(db)  # retomada após crash/redeploy
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


def _loop() -> None:
    logger.info("Scheduler de sincronização iniciado (poll=%ss).", settings.SYNC_POLL_S)
    while not _parar.is_set():
        try:
            _uma_rodada()
        except Exception:                 # noqa: BLE001
            logger.exception("Erro no loop do scheduler de sincronização.")
        _parar.wait(settings.SYNC_POLL_S)
    logger.info("Scheduler de sincronização parado.")


def iniciar() -> bool:
    """Sobe o worker se habilitado e ainda não rodando. Retorna se subiu."""
    global _thread
    if not settings.SYNC_SCHEDULER_ENABLED:
        return False
    if _thread is not None and _thread.is_alive():
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
