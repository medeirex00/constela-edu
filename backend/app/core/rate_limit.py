"""Limitador de tentativas em memória (defesa de aplicação contra força bruta).

Janela deslizante simples por chave (ex.: e-mail+IP). É a segunda linha de
defesa: em produção o nginx aplica limit_req por IP na frente (apps/web/
nginx.conf).

LIMITAÇÃO DE ESCALA (conhecida e aceita): o contador é POR PROCESSO. Com N
workers/réplicas o orçamento efetivo por chave é multiplicado por N e o estado
não é compartilhado entre instâncias. É aceitável para frear dicionário online
num deploy pequeno; para ESCALA HORIZONTAL (várias réplicas atrás do
balanceador) troque por um backend compartilhado (ex.: Redis INCR+EXPIRE) — a
interface pública (bloqueado/registrar_falha/limpar) foi mantida pequena de
propósito para essa substituição. Decisão de infraestrutura: pende de aprovação.

Memória: o dicionário é LIMITADO (_MAX_CHAVES) com descarte de chaves expiradas
+ despejo das mais antigas, para que tentativas com chaves atacante-controladas
(usernames/códigos aleatórios) não cresçam sem limite e esgotem a RAM (DoS).
"""
from __future__ import annotations

import threading
import time
from collections import deque

# Teto de chaves vivas por limitador: barra exaustão de memória por chaves
# atacante-controladas. ~centenas de KB no pior caso; muito acima do uso legítimo.
_MAX_CHAVES = 100_000


class LimitadorTentativas:
    def __init__(self, max_tentativas: int, janela_s: int) -> None:
        self.max_tentativas = max_tentativas
        self.janela_s = janela_s
        self._eventos: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _agora(self) -> float:
        return time.monotonic()

    def _evacuar(self, agora: float) -> None:
        """Sob _lock: descarta chaves expiradas; se ainda no teto, despeja as de
        atividade mais antiga (teto rígido anti-OOM). Só dispara sob flood de
        chaves distintas — o uso legítimo tem pouquíssimas chaves vivas."""
        expiradas = [k for k, f in self._eventos.items()
                     if not f or agora - f[-1] > self.janela_s]
        for k in expiradas:
            del self._eventos[k]
        if len(self._eventos) >= _MAX_CHAVES:
            ordenadas = sorted(self._eventos.items(),
                               key=lambda kv: kv[1][-1] if kv[1] else 0.0)
            for k, _ in ordenadas[: max(1, _MAX_CHAVES // 10)]:
                self._eventos.pop(k, None)

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
            if chave not in self._eventos and len(self._eventos) >= _MAX_CHAVES:
                self._evacuar(agora)
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


def mascarar_ip(ip: str) -> str:
    """Reduz um IP a um prefixo de rede grosseiro para o log de auditoria
    PERMANENTE (LGPD/minimização — mascarar, não apagar; Seção 12 §9).

    IPv4 -> mantém só os 2 primeiros octetos (a.b.x.x); IPv6 -> só o primeiro
    bloco (prefixo curto). O fallback não-IP ("desconhecido", vindo de
    ip_do_cliente) passa intacto. NUNCA levanta: entrada inesperada volta
    como "desconhecido" — o log de login não pode virar 500 por causa disto.
    """
    if not ip or ip == "desconhecido":
        return ip or "desconhecido"
    if ":" in ip:  # IPv6 (inclui IPv4-mapeado ::ffff:a.b.c.d)
        bloco = ip.split(":", 1)[0]
        return f"{bloco}:x" if bloco else "desconhecido"
    partes = ip.split(".")
    if len(partes) == 4 and all(p.isdigit() for p in partes):
        return f"{partes[0]}.{partes[1]}.x.x"
    return "desconhecido"


# 8 falhas por 5 min por (e-mail, IP): trava dicionário online sem punir
# um usuário que erra a senha uma ou duas vezes.
limitador_login = LimitadorTentativas(max_tentativas=8, janela_s=300)
# Segunda camada, POR CONTA (só e-mail/usuário, sem IP): freia força-bruta
# distribuída contra UMA conta mesmo que o atacante rode vários IPs. Teto mais
# largo e janela curta para não travar um usuário que só errou algumas vezes.
# (Trade-off conhecido: 20 falhas em 15 min bloqueiam a conta por 15 min —
# possível lockout intencional de uma conta-alvo, limitado no tempo.)
limitador_conta = LimitadorTentativas(max_tentativas=20, janela_s=900)
