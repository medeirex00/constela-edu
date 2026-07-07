"""Limitador de tentativas em memória (defesa de aplicação contra força bruta).

Janela deslizante simples por chave (ex.: e-mail+IP). É a segunda linha de
defesa: em produção o nginx aplica limit_req por IP na frente (apps/web/
nginx.conf). Com múltiplos workers uvicorn o contador é por processo, o que
é aceitável — o objetivo é frear ataques online de dicionário, não ser um
contador distribuído exato.
"""
from __future__ import annotations

import threading
import time
from collections import deque


class LimitadorTentativas:
    def __init__(self, max_tentativas: int, janela_s: int) -> None:
        self.max_tentativas = max_tentativas
        self.janela_s = janela_s
        self._eventos: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _agora(self) -> float:
        return time.monotonic()

    def bloqueado(self, chave: str) -> bool:
        """True se a chave já estourou o limite dentro da janela."""
        agora = self._agora()
        with self._lock:
            fila = self._eventos.get(chave)
            if not fila:
                return False
            while fila and agora - fila[0] > self.janela_s:
                fila.popleft()
            if not fila:
                self._eventos.pop(chave, None)
                return False
            return len(fila) >= self.max_tentativas

    def registrar_falha(self, chave: str) -> None:
        agora = self._agora()
        with self._lock:
            fila = self._eventos.setdefault(chave, deque())
            while fila and agora - fila[0] > self.janela_s:
                fila.popleft()
            fila.append(agora)

    def limpar(self, chave: str) -> None:
        """Zera o contador (ex.: após login bem-sucedido)."""
        with self._lock:
            self._eventos.pop(chave, None)

    def segundos_restantes(self, chave: str) -> int:
        agora = self._agora()
        with self._lock:
            fila = self._eventos.get(chave)
            if not fila:
                return 0
            return max(0, int(self.janela_s - (agora - fila[0])))


def ip_do_cliente(request) -> str:
    """IP real do cliente considerando o proxy (nginx injeta X-Forwarded-For)."""
    encaminhado = request.headers.get("x-forwarded-for")
    if encaminhado:
        return encaminhado.split(",")[0].strip()
    return request.client.host if request.client else "desconhecido"


# 8 falhas por 5 min por (e-mail, IP): trava dicionário online sem punir
# um usuário que erra a senha uma ou duas vezes.
limitador_login = LimitadorTentativas(max_tentativas=8, janela_s=300)
