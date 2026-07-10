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
    """IP real do cliente, RESISTENTE a spoofing de X-Forwarded-For.

    Cada proxy APPENDA no fim do XFF o IP que enxergou; o cliente só consegue
    forjar valores à ESQUERDA (antes do 1º proxy). Portanto o IP real é a Nª
    entrada A PARTIR DA DIREITA, onde N = settings.TRUSTED_PROXY_HOPS (nº de
    proxies confiáveis à frente). Nunca usamos o valor mais à esquerda (o bug
    anterior), que é totalmente controlável pelo atacante.

    Se o XFF tiver MENOS entradas que os hops confiáveis (cabeçalho ausente ou
    encurtado — típico de acesso direto, sem proxy), caímos para o peer TCP
    direto (request.client.host), que não é falsificável.
    """
    from app.core.config import settings  # import tardio: evita ciclo na carga

    hops = settings.TRUSTED_PROXY_HOPS
    encaminhado = request.headers.get("x-forwarded-for")
    if hops > 0 and encaminhado:
        partes = [p.strip() for p in encaminhado.split(",") if p.strip()]
        if len(partes) >= hops:
            return partes[-hops]
    return request.client.host if request.client else "desconhecido"


# 8 falhas por 5 min por (e-mail, IP): trava dicionário online sem punir
# um usuário que erra a senha uma ou duas vezes.
limitador_login = LimitadorTentativas(max_tentativas=8, janela_s=300)
# Segunda camada, POR CONTA (só e-mail/usuário, sem IP): freia força-bruta
# distribuída contra UMA conta mesmo que o atacante rode vários IPs. Teto mais
# largo e janela curta para não travar um usuário que só errou algumas vezes.
# (Trade-off conhecido: 20 falhas em 15 min bloqueiam a conta por 15 min —
# possível lockout intencional de uma conta-alvo, limitado no tempo.)
limitador_conta = LimitadorTentativas(max_tentativas=20, janela_s=900)
