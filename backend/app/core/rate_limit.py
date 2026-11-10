"""Limitador de tentativas em memória (defesa de aplicação contra força bruta).

Janela deslizante simples por chave (ex.: e-mail+IP). O limit_req por IP do
nginx (apps/web/nginx.conf) só existe no docker-compose: na topologia real (web
na Vercel chamando a API no Railway direto) NÃO há limite de borda. Por isso o
/auth/login tem, além dos limites por (conta, IP) e por conta, um teto de FALHAS
por IP e um teto GLOBAL (``limitador_ip_falha_login`` e
``limitador_global_falha_login``, abaixo), que o router também grava no banco
(valem entre workers e sobrevivem ao deploy — ver routers/auth.py). Teto e janela
desses dois vêm das variáveis EDU_LOGIN_TETO_* (config.py).

LIMITAÇÃO DE ESCALA (conhecida e aceita): o contador DESTE módulo é POR PROCESSO
— para os limites por (conta, IP) e por conta, é o único que existe. Com N
workers/réplicas o orçamento efetivo por chave é multiplicado por N e o estado
não é compartilhado entre instâncias. É aceitável para frear dicionário online
num deploy pequeno; para ESCALA HORIZONTAL (várias réplicas atrás do
balanceador) troque por um backend compartilhado (ex.: Redis INCR+EXPIRE) — a
interface pública (bloqueado/registrar_falha/limpar/limpar_prefixo) foi mantida
pequena de propósito para essa substituição. Decisão de infraestrutura: pende de
aprovação.

Memória: o dicionário é LIMITADO (_MAX_CHAVES) com descarte de chaves expiradas
+ despejo das mais antigas, para que tentativas com chaves atacante-controladas
(usernames/códigos aleatórios) não cresçam sem limite e esgotem a RAM (DoS).
"""
from __future__ import annotations

import ipaddress
import threading
import time
from collections import deque

# Só para os tetos de falha do login (fim do arquivo). config.py não importa nada do
# app, então não há ciclo; o import tardio de ``ip_do_cliente`` fica como estava.
from app.core.config import settings

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

    def limpar_prefixo(self, prefixo: str) -> int:
        """Zera os contadores de todas as chaves que começam com ``prefixo`` (ex.:
        as de (conta, IP) de uma conta, em qualquer IP) e devolve quantas eram.
        Percorre as chaves vivas: é para eventos raros (a redefinição de senha),
        não para o caminho de cada tentativa."""
        with self._lock:
            chaves = [k for k in self._eventos if k.startswith(prefixo)]
            for k in chaves:
                del self._eventos[k]
            return len(chaves)

    def segundos_restantes(self, chave: str) -> int:
        """Segundos até a chave deixar de estar bloqueada; 0 se não está.

        O bloqueio acaba quando a fila de eventos na janela cai abaixo do teto,
        isto é, quando sai o evento ``len - max_tentativas`` (o mais antigo, com a
        fila exatamente no teto). Abaixo do teto devolve 0: quem junta vários
        limitadores (o login) pode tomar o maior sem que o que não bloqueia
        domine a espera anunciada."""
        agora = self._agora()
        with self._lock:
            fila = self._eventos.get(chave)
            if not fila:
                return 0
            vivos = [t for t in fila if agora - t <= self.janela_s]
            excesso = len(vivos) - self.max_tentativas
            if excesso < 0:
                return 0
            return max(0, int(self.janela_s - (agora - vivos[excesso])))


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
    ip = ip.strip()
    # IPv4 PRIMEIRO (aceitando um sufixo ":porta"), ANTES do ramo IPv6 — senão
    # "1.2.3.4:8080" cairia no ramo IPv6 e vazaria o IPv4 inteiro no log.
    host = ip.rsplit(":", 1)[0] if ip.count(":") == 1 else ip
    partes = host.split(".")
    if len(partes) == 4 and all(p.isdigit() for p in partes):
        return f"{partes[0]}.{partes[1]}.x.x"
    if ":" in ip:  # IPv6 -> só o primeiro bloco (prefixo curto)
        bloco = ip.split(":", 1)[0]
        return f"{bloco}:x" if bloco else "desconhecido"
    return "desconhecido"


def _como_endereco(valor: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """O endereço IP em ``valor`` (tolera ``[v6]:porta``, ``v4:porta`` e a zona
    ``%eth0``), ou None se não for IP."""
    texto = (valor or "").strip()
    if texto.startswith("["):
        texto = texto[1:].split("]", 1)[0]
    elif texto.count(":") == 1:
        texto = texto.rsplit(":", 1)[0]
    texto = texto.split("%", 1)[0]
    try:
        return ipaddress.ip_address(texto)
    except ValueError:
        return None


def rede_para_limite(ip: str, prefixo_ipv6: int = 64) -> str:
    """Valor que identifica o CLIENTE nas chaves dos limitadores por IP.

    IPv6: o provedor entrega a um único assinante um /64 inteiro (2^64
    endereços, e muitas nuvens dão /64 por máquina). Contar por endereço deixava
    o atacante trocar de "IP" de graça a cada palpite, e o teto por IP deixava de
    valer. Por isso o IPv6 vira a rede ``<prefixo>::/<prefixo_ipv6>`` (padrão
    /64). IPv4: o próprio endereço, como antes (o NAT da escola já é um IP só, e
    agrupar /24 puniria vizinhos sem relação). IPv4 mapeado em IPv6
    (``::ffff:a.b.c.d``) é tratado como o IPv4. O que não é IP
    ("desconhecido", "testclient") passa intacto. Nunca levanta.

    Só para CHAVE de limite: o log de auditoria segue com ``mascarar_ip``.
    """
    endereco = _como_endereco(ip)
    if endereco is None:
        return ip
    if isinstance(endereco, ipaddress.IPv6Address):
        if endereco.ipv4_mapped is not None:
            return str(endereco.ipv4_mapped)
        prefixo = min(128, max(0, int(prefixo_ipv6)))
        return str(ipaddress.ip_network(f"{endereco}/{prefixo}", strict=False))
    return str(endereco)


# 8 falhas por 5 min por (e-mail, IP): trava dicionário online sem punir
# um usuário que erra a senha uma ou duas vezes. Chave: ``chave_conta_ip``.
limitador_login = LimitadorTentativas(max_tentativas=8, janela_s=300)
# Segunda camada, POR CONTA (só e-mail/usuário, sem IP): freia força-bruta
# distribuída contra UMA conta mesmo que o atacante rode vários IPs. Teto mais
# largo e janela curta para não travar um usuário que só errou algumas vezes.
# (Trade-off conhecido: 20 falhas em 15 min bloqueiam a conta por 15 min —
# possível lockout intencional de uma conta-alvo, limitado no tempo.)
limitador_conta = LimitadorTentativas(max_tentativas=20, janela_s=900)
# Terceira camada, POR IP (só FALHAS, em qualquer conta, exista ela ou não):
# freia a PULVERIZAÇÃO de senhas — um único IP testando poucas senhas em MUITAS
# contas, que escapa das duas camadas acima (cada conta fica abaixo do seu teto).
# A chave é ``rede_para_limite(ip)``: IPv6 agrupado em /64, IPv4 por endereço.
# Generoso para uma escola inteira atrás do mesmo NAT errando a senha de vez em
# quando. O router confere ANTES de procurar a conta e grava também no banco.
# Teto e janela: EDU_LOGIN_TETO_IP_FALHAS / EDU_LOGIN_TETO_IP_JANELA_S (padrão 50
# em 5 min; config.py). Lidos no import, como os do Quest: mudar exige reiniciar.
limitador_ip_falha_login = LimitadorTentativas(
    max_tentativas=settings.EDU_LOGIN_TETO_IP_FALHAS,
    janela_s=settings.EDU_LOGIN_TETO_IP_JANELA_S)
# Teto GLOBAL de falhas do /auth/login (todos os IPs somados, chave única): freia
# a pulverização distribuída que fica abaixo do teto de cada IP. Ao chegar nele, o
# login da API inteira responde 429 até o fim do bloqueio e sai um log de alerta
# (``login.limite_global_atingido``). Trade-off aceito, o mesmo do Quest: sob
# ataque, as contas legítimas também esperam a janela (as sessões já abertas
# seguem valendo). Por isso o teto fica muito acima das falhas do uso real.
# Teto e janela: EDU_LOGIN_TETO_GLOBAL_FALHAS / EDU_LOGIN_TETO_GLOBAL_JANELA_S
# (padrão 400 em 5 min) — a produção pode subir o teto sem mudar o código.
limitador_global_falha_login = LimitadorTentativas(
    max_tentativas=settings.EDU_LOGIN_TETO_GLOBAL_FALHAS,
    janela_s=settings.EDU_LOGIN_TETO_GLOBAL_JANELA_S)
# No máximo UM alerta do teto global por janela em cada processo (sob ataque, toda
# falha acima do teto chegaria ao alerta).
alerta_global_login = LimitadorTentativas(
    max_tentativas=1, janela_s=settings.EDU_LOGIN_TETO_GLOBAL_JANELA_S)


def chave_conta_ip(identidade: str, ip: str) -> str:
    """Chave do ``limitador_login``: a conta (e-mail canônico, ou o texto
    digitado quando a conta não existe) e o IP completo."""
    return f"{identidade}|{ip}"


def liberar_conta(identidade: str) -> None:
    """Zera os limites DA CONTA — o por conta e os por (conta, IP) de qualquer
    IP — depois que a senha foi substituída (link de redefinição, senha definida
    pelo admin ou troca da própria senha). A substituição prova a posse da conta,
    como o login certo, que também zera: sem isto a tela dizia "você já pode
    entrar" e a senha NOVA recebia 429 até a janela vencer. Os tetos de falha por
    IP e global (acima) não dependem da conta e ficam como estão."""
    limitador_conta.limpar(identidade)
    limitador_login.limpar_prefixo(chave_conta_ip(identidade, ""))
