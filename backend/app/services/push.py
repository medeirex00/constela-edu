"""Notificações push via Expo Push Service.

Decisão: o app mobile é Expo/React Native, então usamos o serviço de push
do Expo — um único endpoint HTTPS cobre Android (FCM) e iOS (APNs) sem a
escola precisar de contas no Firebase/Apple. O envio é SEMPRE melhor
esforço: falha de push jamais derruba a operação principal (importação,
recálculo etc.).
"""
from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import DispositivoMovel

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
TAMANHO_LOTE = 100  # limite documentado do Expo por requisição


def montar_lotes(tokens: list[str], titulo: str, corpo: str,
                 dados: dict | None = None) -> list[list[dict]]:
    """Mensagens em lotes de até 100, no formato aceito pelo Expo."""
    mensagens = [
        {"to": token, "title": titulo, "body": corpo, "sound": "default",
         **({"data": dados} if dados else {})}
        for token in tokens
    ]
    return [
        mensagens[inicio:inicio + TAMANHO_LOTE]
        for inicio in range(0, len(mensagens), TAMANHO_LOTE)
    ]


def _enviar_lotes(lotes: list[list[dict]]) -> list[str]:
    """Envia os lotes e devolve os tokens rejeitados como não registrados."""
    import httpx

    invalidos: list[str] = []
    for lote in lotes:
        resposta = httpx.post(EXPO_PUSH_URL, json=lote, timeout=15.0)
        resposta.raise_for_status()
        for mensagem, resultado in zip(lote, resposta.json().get("data", [])):
            detalhes = resultado.get("details") or {}
            if detalhes.get("error") == "DeviceNotRegistered":
                invalidos.append(mensagem["to"])
    return invalidos


def notificar_escola(db: Session, escola_id: int, titulo: str, corpo: str,
                     dados: dict | None = None) -> int:
    """Push para todos os aparelhos da escola. Retorna quantos foram alvo.

    Melhor esforço: erros de rede são registrados em log e engolidos;
    tokens que o Expo reportar como mortos são removidos do banco.
    """
    tokens = db.execute(
        select(DispositivoMovel.token_push)
        .where(DispositivoMovel.escola_id == escola_id)
    ).scalars().all()
    if not tokens:
        return 0

    try:
        invalidos = _enviar_lotes(montar_lotes(list(tokens), titulo, corpo, dados))
        if invalidos:
            db.execute(delete(DispositivoMovel)
                       .where(DispositivoMovel.token_push.in_(invalidos)))
            db.commit()
    except Exception:  # noqa: BLE001 — push nunca derruba a operação principal
        logger.warning("Falha ao enviar push para a escola %s", escola_id,
                       exc_info=True)
    return len(tokens)
