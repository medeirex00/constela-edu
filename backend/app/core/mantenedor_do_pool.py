"""Mantenedor do pool: N conexões PRONTAS para a próxima requisição (só PostgreSQL).

A Secretaria entra poucas vezes por dia, então o caso comum em produção é o pool FRIO (logo
depois de um deploy ou reinício, sem conexão aberta) ou PARADO (a última requisição foi há
minutos). Na bancada (195 ms entre a API e o banco), quem pagava era a requisição do usuário:

* conexão NOVA: ~0,8 s (TCP, SCRAM e início da sessão). Com o pool frio o Panorama dá
  6,2-6,4 s, contra 4,5 s com o pool aquecido;
* conexão parada há mais de ``DB_PING_OCIOSO_S`` (30 s): um ping na retirada, ~0,2 s
  (``database.instalar_ping_por_ociosidade``);
* conexão com mais de ``DB_POOL_RECYCLE`` (1800 s) de vida: reaberta na retirada, ~0,8 s.

O mantenedor é uma thread daemon por processo (cada worker uvicorn tem a sua), ligada no
startup do app e parada no shutdown. Logo no boot e depois a cada ``DB_POOL_AQUECIDO_S``
(padrão 20 s, menor que o ``DB_PING_OCIOSO_S``), ele retira AO MESMO TEMPO
``DB_POOL_AQUECIDO_CONEXOES`` conexões (padrão 8: as chamadas em voo do Panorama da
Secretaria, 6 da página mais o sinal de presença e o contador de notificações), roda
``SELECT 1`` em cada e devolve todas. Retirar ao mesmo tempo é o que garante conexões
DISTINTAS: uma de cada vez, o pool LIFO devolveria sempre a mesma. O efeito:

* boot: o primeiro ciclo abre as N conexões em paralelo (pré-aquece o pool);
* nenhuma das N fica parada mais que um intervalo, então a requisição não paga o ping;
* a conexão perto do ``DB_POOL_RECYCLE`` (margem de 2 intervalos) é reaberta PELO
  MANTENEDOR, antes que um usuário a pegue. A hora de abertura fica no registro de cada
  conexão (``marcar_abertura``, instalado junto do engine);
* conexão morta no ``SELECT 1`` (o banco ou o pooler reiniciou) é trocada no mesmo ciclo.

Fora o do boot, cada ciclo espera uma calmaria de ``CALMARIA_S`` (2 s sem requisição com
conexão nem devolução), com teto de ``ESPERA_MAXIMA_S`` (5 s): não compete com uma página que
está carregando em camadas.

Limites, de propósito:

* não segura conexão entre ciclos. Cada uma fica fora do pool só o tempo do ``SELECT 1`` (uma
  ida, em AUTOCOMMIT: sem BEGIN nem ROLLBACK) e da espera pelas outras do mesmo ciclo;
* não abre mais que N. As conexões que já estão com requisições (``checkedout``) são quentes
  por definição e são descontadas. N fica limitado ao ``DB_POOL_SIZE``, e o total mantido é
  N vezes o número de workers;
* não derruba a API. Erro vira aviso no log, no máximo um a cada ``JANELA_DO_AVISO_S``, só
  com o TIPO da exceção (a mensagem do driver pode trazer host e usuário do banco). O ciclo
  seguinte tenta de novo;
* não liga no SQLite (desenvolvimento e testes) nem com ``0`` em qualquer das duas variáveis;
* as conexões além das N que o pool guardar (até ``DB_POOL_SIZE`` paradas, sobra de uma
  rajada maior) ficam como antes: quem pegar uma delas paga o ping ou a reabertura.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, replace

from sqlalchemy import event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import QueuePool

from app.core.config import settings

logger = logging.getLogger("constela")

# Hora em que a conexão do DB-API foi ABERTA, no registro dela (``time.time()``, o mesmo
# relógio do ``pool_recycle``). O pool limpa o ``info`` ao reabrir; o evento grava de novo.
_ABERTA_EM = "constela_aberta_em"

# No máximo um aviso de falha no log por janela; as outras falhas só são contadas.
JANELA_DO_AVISO_S = 300.0

# Teto da espera de um ciclo pelas suas retiradas. Abrir uma conexão nova leva até
# ``DB_CONNECT_TIMEOUT`` (10 s); passado o teto, o ciclo devolve o que já tem.
PRAZO_DO_CICLO_S = 20.0

# Quantas vezes seguidas uma retirada troca a conexão perto da reciclagem.
_RENOVACOES_POR_RETIRADA = 3

# Antes de cada ciclo (menos o do boot), o mantenedor espera uma CALMARIA: nenhuma conexão
# com requisição e nenhuma devolvida por requisição nos últimos ``CALMARIA_S``. Uma página
# chama a API em camadas (a sessão, depois a página), com intervalos curtos entre elas; o
# ciclo que caísse num desses intervalos seguraria as conexões paradas bem quando a camada
# seguinte chega, e ela abriria conexões novas. A espera tem teto (``ESPERA_MAXIMA_S``, e
# nunca a ponto de passar do ``DB_PING_OCIOSO_S``): com o servidor sempre ocupado, o ciclo
# roda assim mesmo, descontando as conexões em uso.
CALMARIA_S = 2.0
ESPERA_MAXIMA_S = 5.0

# Marca as threads do próprio mantenedor: a devolução feita por elas não conta como uso.
_local = threading.local()


def marcar_abertura(motor) -> None:
    """Grava no registro de cada conexão NOVA do pool a hora em que ela foi aberta.

    É o que o mantenedor consulta para reabrir a conexão antes do ``pool_recycle``. Vai
    junto do engine (``database.py``), antes da primeira conexão: as abertas no boot
    (migrações, prontidão, ajustes de dados) também ficam marcadas."""

    def _aberta(_dbapi_connection, registro) -> None:
        registro.info[_ABERTA_EM] = time.time()

    event.listen(motor, "connect", _aberta)


@dataclass
class Resumo:
    """O que um ciclo fez."""

    pedidas: int = 0        # conexões que o ciclo retirou (N menos as que estavam em uso)
    prontas: int = 0        # com o SELECT 1 respondido
    renovadas: int = 0      # reabertas por estarem perto do DB_POOL_RECYCLE
    reconectadas: int = 0   # mortas no SELECT 1 e trocadas no mesmo ciclo
    falhas: list[str] = field(default_factory=list)  # o tipo da exceção de cada falha


class _Rodada:
    """As retiradas de UM ciclo: cada trabalhador avisa quando terminou e segura a conexão
    até ``liberar``, para que todas fiquem fora do pool ao mesmo tempo."""

    def __init__(self, pedidas: int) -> None:
        self._resumo = Resumo(pedidas=pedidas)
        self._cond = threading.Condition()
        self._terminadas = 0
        self.liberar = threading.Event()

    def terminou(self, *, pronta: bool = False, renovadas: int = 0, reconectadas: int = 0,
                 falha: BaseException | None = None) -> None:
        with self._cond:
            r = self._resumo
            r.prontas += int(pronta)
            r.renovadas += renovadas
            r.reconectadas += reconectadas
            if falha is not None:
                r.falhas.append(type(falha).__name__)
            self._terminadas += 1
            self._cond.notify_all()

    def esperar(self, prazo_s: float) -> None:
        with self._cond:
            self._cond.wait_for(
                lambda: self._terminadas >= self._resumo.pedidas or self.liberar.is_set(),
                timeout=prazo_s)

    def soltar(self) -> None:
        self.liberar.set()
        with self._cond:
            self._cond.notify_all()

    def resumo(self) -> Resumo:
        with self._cond:
            return replace(self._resumo, falhas=list(self._resumo.falhas))


class _AvisoComPausa:
    """Aviso de falha no log com limite de frequência (um por janela) e o aviso da volta."""

    def __init__(self, janela_s: float = JANELA_DO_AVISO_S, relogio=time.monotonic) -> None:
        self.janela_s = janela_s
        self._relogio = relogio
        self._ultimo: float | None = None
        self._caladas = 0
        self._em_falha = False

    def falhou(self, texto: str) -> bool:
        """Registra a falha; devolve se ela foi para o log (a primeira da janela)."""
        agora = self._relogio()
        self._em_falha = True
        if self._ultimo is not None and agora - self._ultimo < self.janela_s:
            self._caladas += 1
            return False
        extra = (f" ({self._caladas} falha(s) a mais desde o aviso anterior)"
                 if self._caladas else "")
        logger.warning("Mantenedor do pool: %s; tenta de novo no próximo ciclo%s.", texto, extra)
        self._ultimo, self._caladas = agora, 0
        return True

    def voltou(self) -> None:
        if self._em_falha:
            logger.info("Mantenedor do pool: o banco voltou a responder.")
        self._em_falha = False


class MantenedorDoPool:
    """Uma thread que, a cada ``intervalo_s``, deixa ``conexoes`` conexões prontas no pool."""

    def __init__(self, motor, *, intervalo_s: float, conexoes: int,
                 reciclagem_s: float | None = None, prazo_s: float = PRAZO_DO_CICLO_S,
                 calmaria_s: float = CALMARIA_S, espera_maxima_s: float = ESPERA_MAXIMA_S,
                 aviso: _AvisoComPausa | None = None) -> None:
        self.intervalo_s = float(intervalo_s)
        self.conexoes = int(conexoes)
        self.prazo_s = float(prazo_s)
        self.calmaria_s = float(calmaria_s)
        self.espera_maxima_s = float(espera_maxima_s)
        self._motor_base = motor
        self._pool = motor.pool
        self._ultima_devolucao = float("-inf")
        self._ouvindo = False
        # Mesmo pool, em AUTOCOMMIT: o SELECT 1 é uma ida só (sem BEGIN e sem ROLLBACK). A
        # troca é local na conexão e o SQLAlchemy a desfaz na devolução.
        self._motor = motor.execution_options(isolation_level="AUTOCOMMIT")
        # Reabre a conexão com MAIS que isto de vida: o ``pool_recycle`` menos 2 intervalos
        # (o tempo até o ciclo seguinte, com folga), mas nunca antes da metade dele.
        self.limite_da_reciclagem_s: float | None = None
        if reciclagem_s is not None and reciclagem_s > 0:
            self.limite_da_reciclagem_s = max(reciclagem_s - 2 * self.intervalo_s,
                                              reciclagem_s / 2)
        self._aviso = aviso or _AvisoComPausa()
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._rodada: _Rodada | None = None

    # --- um ciclo -----------------------------------------------------------------------

    def ciclo(self) -> Resumo:
        """Retira as conexões ao mesmo tempo, roda ``SELECT 1`` em cada e devolve todas."""
        pedidas = max(0, self.conexoes - self._pool.checkedout())
        if pedidas == 0:
            return Resumo()
        rodada = _Rodada(pedidas)
        self._rodada = rodada
        trabalhadores = [threading.Thread(target=self._trabalhar, args=(rodada,), daemon=True,
                                          name=f"pool-aquecido-{i + 1}")
                         for i in range(pedidas)]
        try:
            for t in trabalhadores:
                t.start()
            rodada.esperar(self.prazo_s)
        finally:
            rodada.soltar()
            self._rodada = None
        fim = time.monotonic() + self.prazo_s
        for t in trabalhadores:
            t.join(max(0.0, fim - time.monotonic()))
        return rodada.resumo()

    def _perto_da_reciclagem(self, conexao) -> bool:
        if self.limite_da_reciclagem_s is None:
            return False
        aberta = conexao.info.get(_ABERTA_EM)
        return aberta is not None and time.time() - aberta >= self.limite_da_reciclagem_s

    def _retirar_pronta(self):
        """Uma conexão do pool; a que está perto da reciclagem é descartada e reaberta aqui."""
        renovadas = 0
        while True:
            conexao = self._motor.connect()
            if renovadas >= _RENOVACOES_POR_RETIRADA or not self._perto_da_reciclagem(conexao):
                return conexao, renovadas
            # Fecha a conexão velha e devolve o registro VAZIO ao topo do pool (LIFO): a
            # retirada seguinte o pega e abre a conexão nova aqui, não na requisição.
            conexao.invalidate()
            conexao.close()
            renovadas += 1

    def _trabalhar(self, rodada: _Rodada) -> None:
        _local.mantenedor = True
        conexao = None
        renovadas = reconectadas = 0
        try:
            for tentativa in range(2):
                conexao, n = self._retirar_pronta()
                renovadas += n
                try:
                    conexao.exec_driver_sql("SELECT 1").scalar()
                    break
                except DBAPIError as erro:
                    if tentativa or not erro.connection_invalidated:
                        raise
                    # Conexão morta (o banco ou o pooler reiniciou): o SQLAlchemy já a
                    # descartou e marcou o pool; a troca acontece neste mesmo ciclo.
                    conexao.close()
                    conexao = None
                    reconectadas += 1
        except Exception as erro:  # noqa: BLE001 — o mantenedor nunca derruba a API
            rodada.terminou(renovadas=renovadas, reconectadas=reconectadas, falha=erro)
        else:
            rodada.terminou(pronta=True, renovadas=renovadas, reconectadas=reconectadas)
            rodada.liberar.wait(self.prazo_s)   # segura até as outras retiradas do ciclo
        finally:
            if conexao is not None:
                try:
                    conexao.close()
                except Exception:  # noqa: BLE001
                    pass

    # --- a thread -----------------------------------------------------------------------

    def _registrar(self, resumo: Resumo) -> None:
        if resumo.falhas:
            tipos = ", ".join(sorted(set(resumo.falhas)))
            self._aviso.falhou(f"{len(resumo.falhas)} de {resumo.pedidas} conexão(ões) "
                               f"sem resposta ({tipos})")
        elif resumo.pedidas:
            self._aviso.voltou()
            logger.debug("Mantenedor do pool: %d pronta(s), %d renovada(s), %d reconectada(s).",
                         resumo.prontas, resumo.renovadas, resumo.reconectadas)

    def _na_devolucao(self, _dbapi_connection, _registro) -> None:
        if not getattr(_local, "mantenedor", False):
            self._ultima_devolucao = time.monotonic()

    def _esperar_calmaria(self) -> None:
        """Espera não haver requisição com conexão nem devolução recente, até o teto."""
        limite = time.monotonic() + self.espera_maxima_s
        while not self._parar.is_set():
            agora = time.monotonic()
            ocupado = (self._pool.checkedout() > 0
                       or agora - self._ultima_devolucao < self.calmaria_s)
            if not ocupado or agora >= limite:
                return
            self._parar.wait(min(0.1, limite - agora))

    def _laco(self) -> None:
        primeiro = True                      # o primeiro ciclo é imediato (pré-aquece)
        while not self._parar.is_set():
            if not primeiro:
                self._esperar_calmaria()
                if self._parar.is_set():
                    break
            primeiro = False
            try:
                self._registrar(self.ciclo())
            except Exception as erro:  # noqa: BLE001
                self._aviso.falhou(f"o ciclo falhou ({type(erro).__name__})")
            self._parar.wait(self.intervalo_s)

    def iniciar(self) -> None:
        if self.vivo():
            return
        if not self._ouvindo:
            event.listen(self._motor_base, "checkin", self._na_devolucao)
            self._ouvindo = True
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name="pool-aquecido", daemon=True)
        self._thread.start()

    def parar(self, timeout: float = 5.0) -> None:
        self._parar.set()
        rodada = self._rodada
        if rodada is not None:
            rodada.soltar()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def vivo(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


def criar_para(motor, config=settings) -> MantenedorDoPool | None:
    """O mantenedor do engine do app, ou ``None`` quando ele não se aplica: banco que não é
    PostgreSQL (o SQLite do desenvolvimento e dos testes), pool sem fila (``QueuePool``) ou
    ``DB_POOL_AQUECIDO_S``/``DB_POOL_AQUECIDO_CONEXOES`` zero ou negativo."""
    if motor.dialect.name != "postgresql" or not isinstance(motor.pool, QueuePool):
        return None
    intervalo, conexoes = config.DB_POOL_AQUECIDO_S, config.DB_POOL_AQUECIDO_CONEXOES
    if intervalo <= 0 or conexoes <= 0:
        logger.info("Mantenedor do pool desligado (DB_POOL_AQUECIDO_S=%s, "
                    "DB_POOL_AQUECIDO_CONEXOES=%s).", intervalo, conexoes)
        return None
    teto = motor.pool.size()
    if teto > 0 and conexoes > teto:
        logger.warning("Mantenedor do pool: DB_POOL_AQUECIDO_CONEXOES=%d passa do "
                       "DB_POOL_SIZE=%d; mantém %d.", conexoes, teto, teto)
        conexoes = teto
    # A espera pela calmaria nunca empurra o ciclo seguinte para além do limite do ping
    # (com folga de 2 s); com os padrões, 20 + 5 = 25 s < 30 s.
    espera = min(ESPERA_MAXIMA_S, intervalo / 4)
    ping = config.DB_PING_OCIOSO_S
    if ping > 0:
        espera = max(0.0, min(espera, ping - intervalo - 2))
        if ping <= intervalo:
            logger.warning("Mantenedor do pool: DB_POOL_AQUECIDO_S=%s não é menor que "
                           "DB_PING_OCIOSO_S=%s; a requisição pode pagar o ping da conexão "
                           "parada.", intervalo, ping)
    return MantenedorDoPool(motor, intervalo_s=intervalo, conexoes=conexoes,
                            reciclagem_s=config.DB_POOL_RECYCLE, espera_maxima_s=espera)


_trava = threading.Lock()
_atual: MantenedorDoPool | None = None


def iniciar(motor, config=settings) -> bool:
    """Liga o mantenedor do processo (startup do app). Idempotente; nunca levanta."""
    global _atual
    with _trava:
        if _atual is not None and _atual.vivo():
            return True
        try:
            mantenedor = criar_para(motor, config)
            if mantenedor is None:
                return False
            mantenedor.iniciar()
        except Exception as erro:  # noqa: BLE001 — sem o mantenedor a API segue como antes
            logger.warning("Mantenedor do pool não iniciou (%s).", type(erro).__name__)
            return False
        _atual = mantenedor
        logger.info("Mantenedor do pool ligado: %d conexão(ões) prontas, ciclo a cada %.0f s.",
                    mantenedor.conexoes, mantenedor.intervalo_s)
        return True


def parar(timeout: float = 5.0) -> None:
    """Para o mantenedor do processo (shutdown do app). Sem mantenedor, nada a fazer."""
    global _atual
    with _trava:
        mantenedor, _atual = _atual, None
    if mantenedor is not None:
        mantenedor.parar(timeout)


def ativo() -> bool:
    return _atual is not None and _atual.vivo()
