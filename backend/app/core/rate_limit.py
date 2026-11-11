"""Limitador de tentativas em memória (defesa de aplicação contra força bruta).

Janela deslizante simples por chave (ex.: e-mail+IP). O limit_req por IP do
nginx (apps/web/nginx.conf) só existe no docker-compose: na topologia real (web
na Vercel chamando a API no Railway direto) NÃO há limite de borda. Por isso o
/auth/login tem, além dos limites por (conta, IP) e por conta, um teto de FALHAS
por IP e um teto GLOBAL (``limitador_ip_falha_login`` e
``limitador_global_falha_login``, abaixo), que o router também grava no banco
(valem entre workers e sobrevivem ao deploy — ver routers/auth.py). Teto e janela
desses dois vêm das variáveis EDU_LOGIN_TETO_* (config.py). E um portão de logins
SIMULTÂNEOS por processo (``portao_login``, ``PortaoDeConcorrencia``): uma rajada
anônima não ocupa todas as threads e conexões do worker.

LIMITAÇÃO DE ESCALA (conhecida e aceita): o contador DESTE módulo é POR PROCESSO
— para os limites por (conta, IP) e por conta, é o único que existe. Com N
workers/réplicas o orçamento efetivo por chave é multiplicado por N e o estado
não é compartilhado entre instâncias. É aceitável para frear dicionário online
num deploy pequeno; para ESCALA HORIZONTAL (várias réplicas atrás do
balanceador) troque por um backend compartilhado (ex.: Redis INCR+EXPIRE) — a
interface pública (bloqueado/registrar_falha/limpar/limpar_prefixo) foi mantida
pequena de propósito para essa substituição. Decisão de infraestrutura: pende de
aprovação. Zerar a memória de um processo não alcança os outros: por isso a
troca de senha libera o login pela CHAVE (``identidade_da_conta``, com a versão
da sessão lida do banco), e não pela limpeza (``liberar_conta``).

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

    def bloquear_por(self, chave: str, segundos: float) -> None:
        """Bloqueia a chave NESTE processo por ``segundos`` (no máximo a janela): a
        recusa que a camada persistente deu (outro worker contou as falhas) passa a
        valer aqui sem ida ao banco. Nunca encurta um bloqueio mais longo.

        A fila ganha ``max_tentativas`` eventos no instante que faz o bloqueio acabar
        daqui a ``segundos`` (``bloqueado`` e ``segundos_restantes`` seguem valendo
        como para falhas de verdade). As falhas de verdade da chave FICAM, na ordem
        (REV2-AUTH2-1): quando o bloqueio aprendido acaba, elas seguem contando na
        janela delas, como se ele não tivesse existido."""
        agora = self._agora()
        segundos = max(0.0, min(float(segundos), float(self.janela_s)))
        if segundos <= self.segundos_restantes(chave):
            return
        with self._lock:
            if chave not in self._eventos and len(self._eventos) >= _MAX_CHAVES:
                self._evacuar(agora)
            marca = agora - self.janela_s + segundos
            vivos = [t for t in self._eventos.get(chave, ()) if agora - t <= self.janela_s]
            self._eventos[chave] = deque(sorted(vivos + [marca] * self.max_tentativas))

    def falhas_na_janela(self, chave: str) -> int:
        """Quantas falhas da chave estão na janela, neste processo (o que a camada em
        memória sabe quando o banco não respondeu a tempo)."""
        agora = self._agora()
        with self._lock:
            fila = self._eventos.get(chave)
            return sum(1 for t in fila if agora - t <= self.janela_s) if fila else 0


class PortaoDeConcorrencia:
    """Teto de pedidos de uma rota correndo AO MESMO TEMPO neste processo, sem fila:
    com o teto cheio, ``entrar`` devolve False na hora e quem chamou recusa o pedido
    sem esperar e sem tocar no banco. Quem entrou chama ``sair`` no fim (``finally``).

    Para rotas anônimas que qualquer um pode disparar em rajada (o /auth/login): sem
    o portão, a rajada ocupava todas as threads do worker (40 no anyio) e as conexões
    do pool (10 + 20) e as sessões já abertas esperavam na fila delas. Com ele, a
    rajada usa no máximo ``vagas`` de cada, e o resto é recusado em microssegundos.
    Por processo (como os limitadores daqui): com N workers, N × ``vagas``."""

    def __init__(self, vagas: int) -> None:
        self.vagas = vagas
        self._ocupadas = 0
        self._lock = threading.Lock()

    def entrar(self) -> bool:
        with self._lock:
            if self._ocupadas >= self.vagas:
                return False
            self._ocupadas += 1
            return True

    def sair(self) -> None:
        with self._lock:
            self._ocupadas = max(0, self._ocupadas - 1)

    @property
    def ocupadas(self) -> int:
        with self._lock:
            return self._ocupadas


def minutos_de_espera(segundos: int) -> int:
    """Os minutos do "Aguarde N minuto(s)" dos 429: ``segundos_restantes``
    arredondado para CIMA, no mínimo 1. Para baixo, 299 s viravam "4 minutos" e
    quem voltava no tempo anunciado levava outro 429. Fonte única dos textos do
    login (por conta, por IP e global) e da reautenticação (admin.py)."""
    return max(1, -(-int(segundos) // 60))


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
# Logins correndo AO MESMO TEMPO em cada processo (``PortaoDeConcorrencia``): acima
# disso, 429 na hora, sem tocar no banco. Um login leva ~1–2 s em produção (bcrypt e
# algumas idas ao banco, a ~195 ms cada) e o uso real tem poucos ao mesmo tempo; com
# 8, uma rajada anônima ocupa no máximo 8 das 40 threads e 8 das 30 conexões de cada
# worker, e as sessões já abertas seguem sendo atendidas.
# Padrão 8 (``EDU_LOGIN_SIMULTANEOS``), lido no boot como os tetos acima.
portao_login = PortaoDeConcorrencia(vagas=settings.EDU_LOGIN_SIMULTANEOS)
# No máximo UM aviso de "portão do login cheio" por minuto em cada processo.
alerta_portao_login = LimitadorTentativas(max_tentativas=1, janela_s=60)


def identidade_da_conta(usuario) -> str:
    """Identidade de uma conta que EXISTE no ``limitador_conta`` e no
    ``limitador_login``: o e-mail e a versão da sessão (``token_version``), lida
    do banco no pedido. O /auth/login e a reautenticação
    (``admin._exigir_senha_atual``) usam esta mesma chave; conta inexistente
    segue com o texto digitado.

    A versão é o que faz a troca de senha liberar o login em TODOS os processos
    da API: toda substituição da senha (link de redefinição, senha definida pelo
    admin, troca da própria senha, "Padronizar @", fusão de professores
    duplicados) sobe o ``token_version`` na mesma transação. Cada processo passa a
    contar numa chave nova, e as falhas da senha antiga, gravadas na memória de
    cada processo (ver LIMITAÇÃO DE ESCALA, no topo), deixam de travar. Outras
    ações do admin que derrubam as sessões (desativar, reativar, promover à
    Secretaria) também zeram. A versão só sobe por ação do admin ou com a senha
    atual: errar a senha não muda a chave.

    Quem digita esta chave como se fosse um login (``e-mail#versão``, conta
    inexistente) só soma falhas nela: o mesmo travamento que errar a senha da
    conta já causa (o trade-off do ``limitador_conta``)."""
    return f"{usuario.email}#{usuario.token_version or 0}"


def chave_conta_ip(identidade: str, ip: str) -> str:
    """Chave do ``limitador_login``: a conta (``identidade_da_conta``, ou o texto
    digitado quando a conta não existe) e o IP completo."""
    return f"{identidade}|{ip}"


def liberar_conta(email: str) -> None:
    """Apaga deste processo os contadores da conta, em qualquer versão da sessão
    e em qualquer IP, depois que a senha foi substituída. Só libera memória: quem
    faz o login com a senha nova entrar, em todos os processos, é a versão nova
    na chave (``identidade_da_conta``). Os tetos de falha por IP e global (acima)
    não dependem da conta e ficam como estão."""
    prefixo = f"{email}#"
    limitador_conta.limpar_prefixo(prefixo)
    limitador_login.limpar_prefixo(prefixo)
