"""Métricas Prometheus da sincronização (Elefante e Matific) — S15 do diagnóstico e92.

Duas fontes, para valer com VÁRIOS workers (``WEB_CONCURRENCY=2``):

1. ``ColetorSync`` lê o ESTADO no BANCO na hora do scrape. Todos os workers leem o
   mesmo banco, então qualquer worker que atender o scrape responde a mesma coisa:
   idade da última execução por escola/plataforma/estado, última coleta com dado
   aplicado, execuções ativas e presas, alertas abertos, recálculo pendente,
   credenciais por status e o agendador ligado/desligado.
   - Custo FIXO por scrape: 5 consultas (6 quando há execução na fila), todas com
     caminho por índice que já existe (``ix_sync_exec_frescor``,
     ``ix_sync_exec_escola_inicio``, ``ix_sincronizacao_execucoes_status``,
     ``ix_sincronizacao_alertas_resolvido``, ``ix_sincronizacao_logs_execucao_id``).
     O histórico de execuções e o log NUNCA são varridos: a última execução de cada
     estado é um MAX por integração cadastrada (credencial ou agenda), resolvido no
     índice, e a marca de recálculo é um EXISTS por escola.
   - No PostgreSQL a transação do coletor é READ ONLY e cada consulta tem teto de
     tempo: o menor entre ``TETO_CONSULTA_MS`` e o que sobra do prazo total.
   - PRAZO TOTAL (``PRAZO_COLETOR_S``, revisão e95): a leitura roda numa thread
     própria e o scrape espera no máximo esse prazo — inclusive a espera por uma
     conexão do pool compartilhado (``pool_timeout`` de 30 s) e a abertura de uma
     conexão nova (``DB_CONNECT_TIMEOUT``, 10 s por padrão, mais longo que este
     prazo), que o teto por consulta não cobre. Passou do prazo: o
     scrape responde ``sync_coletor_sucesso 0`` e a leitura termina sozinha em
     segundo plano; enquanto ela não termina, o scrape seguinte responde 0 na hora
     (no máximo UMA leitura do banco por processo).
   - Falha ISOLADA: erro do coletor vira ``sync_coletor_sucesso 0`` (sem nenhuma
     série parcial do banco) e o resto do /metrics sai normal.
2. Contadores e histogramas EM PROCESSO para os EVENTOS (execuções finalizadas,
   duração, alunos aplicados, falhas por unidade e código), registrados num ponto
   ÚNICO: ``execucao_finalizada``, chamado só no fim de ``service.executar``, depois
   do commit. São por worker, como os ``http_*``: com 2 workers, cada scrape vê o
   contador do worker que o atendeu. A contagem exata entre workers sai do estado
   no banco (item 1) ou do modo multiprocesso do prometheus_client, que é decisão
   de infraestrutura (variável de ambiente e diretório), fora deste módulo.

Rótulos: só ``escola_id`` numérico e CÓDIGOS (plataforma, status, motivo, tipo de
alerta, severidade, unidade). Valor fora do padrão de código vira ``outro``. Nenhum
nome, mensagem, ``erro_resumo`` ou texto livre do banco é lido para o /metrics. A
CIFRA da credencial é lida só para saber se ela abre (o status ``ilegivel``, o mesmo
critério do /sync/status): o texto claro não sai do ``vault`` e nenhum segredo vai
para o /metrics.

A proteção do /metrics (``METRICS_TOKEN`` / ``METRICS_PUBLICO``, em ``app/main.py``)
não muda: o coletor só roda quando a rota já autorizou o scrape.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import exists, func, select, text, union
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import segredos_da_cifra
from app.models.sincronizacao import (
    PlataformaCredencial,
    SincronizacaoAlerta,
    SincronizacaoConfig,
    SincronizacaoExecucao,
    SincronizacaoLog,
)
from app.sync import service, vault

try:  # degradável: sem prometheus-client, tudo vira no-op
    import prometheus_client as _prom
    from prometheus_client.core import GaugeMetricFamily
except ImportError:  # pragma: no cover
    _prom = None
    GaugeMetricFamily = None

logger = logging.getLogger("constela.sync.metricas")

STATUS_ATIVOS = ("fila", "executando")
# Estados com ``finalizada_em``: os terminais do contrato (``service.STATUS_TERMINAIS``)
# e a 'cancelada' (fila liberada sem rodar).
STATUS_FINALIZADOS = ("concluida", "parcial", "sem_atualizacao", "sem_dados", "erro",
                      "cancelada")
TETO_CONSULTA_MS = 3000
# Prazo TOTAL de um scrape para ler o banco (pool + conexão + consultas). Abaixo do
# scrape_timeout padrão do Prometheus (10 s): passado o tempo-limite dele, o alvo
# inteiro cai (up=0) e somem também as séries http_* — e a regra
# ``sync_coletor_sucesso == 0`` não dispara, porque a série fica AUSENTE.
PRAZO_COLETOR_S = 5.0
BUCKETS_DURACAO_S = (5, 15, 30, 60, 120, 300, 600, 900, 1200, 1800, 2700, 3600)

_RE_CODIGO = re.compile(r"[a-z0-9_]{1,40}")


def _codigo(valor, vazio: str = "nenhum") -> str:
    """Rótulo seguro: só códigos (minúsculas, dígitos, '_'). Qualquer outra coisa
    — um nome, uma frase, um valor corrompido — vira 'outro'."""
    if valor is None or valor == "":
        return vazio
    texto = str(valor)
    return texto if _RE_CODIGO.fullmatch(texto) else "outro"


def _escola(valor) -> str:
    return str(int(valor))


def _utc_naive(valor) -> datetime | None:
    if valor is None:
        return None
    if isinstance(valor, str):
        valor = datetime.fromisoformat(valor)
    if valor.tzinfo is not None:
        valor = valor.astimezone(timezone.utc).replace(tzinfo=None)
    return valor


def _idade(agora: datetime, instante) -> float | None:
    instante = _utc_naive(instante)
    if instante is None:
        return None
    return max(0.0, (agora - instante).total_seconds())


# ---------------------------------------------------------------------------
# 1. Estado no banco (lido na hora do scrape)
# ---------------------------------------------------------------------------
_FAMILIAS_DO_BANCO = (
    ("sync_ultima_execucao_idade_segundos",
     "Segundos desde o fim (finalizada_em) da última execução da integração em cada "
     "estado.", ("escola_id", "plataforma", "status")),
    ("sync_ultimo_dado_aplicado_idade_segundos",
     "Segundos desde a última coleta do acumulado que aplicou dado (concluida, ou "
     "parcial com aluno aplicado; a coleta por período do Matific não conta) — o "
     "marco de service.ultimo_sucesso_em.", ("escola_id", "plataforma")),
    ("sync_execucoes_ativas",
     "Execuções na fila ou executando.", ("plataforma", "status")),
    ("sync_execucao_ativa_idade_segundos",
     "Segundos desde a criação (fila) ou o início (executando) da execução ativa da "
     "integração.", ("escola_id", "plataforma", "status")),
    ("sync_execucoes_presas",
     "Execuções ativas sem sinal de vida: executando sem início nem log dentro de "
     "SYNC_SEM_SINAL_S (o critério do reaper) ou na fila sem criação, "
     "disponibilidade nem log dentro de SYNC_TRAVADA_S.", ("plataforma", "status")),
    ("sync_alertas_abertos",
     "Alertas de sincronização abertos (resolvido = false).",
     ("escola_id", "plataforma", "tipo", "severidade")),
    ("sync_recalculo_pendente",
     "1 se a escola tem dado gravado esperando o recálculo das notas (alerta "
     "'recalculo_pendente' aberto ou marca recalculo_pendente numa execução da "
     "escola, de qualquer plataforma: a regra de service.recalculo_pendente_aberto); "
     "0 se não.", ("escola_id",)),
    ("sync_credencial_status",
     "Credencial de plataforma da escola: 1 na série do status atual — o DERIVADO, "
     "o mesmo do /sync/status ('ilegivel' quando a cifra não abre com as chaves "
     "deste processo, qualquer que seja o gravado).",
     ("escola_id", "plataforma", "status")),
)
_FAMILIAS_SEMPRE = (
    ("sync_agendador_ligado",
     "1 se SYNC_SCHEDULER_ENABLED está ligado neste deploy; 0 se não.", ()),
    ("sync_coletor_sucesso",
     "1 se o coletor das métricas de sincronização leu o banco neste scrape; 0 se "
     "falhou (as séries do banco ficam de fora).", ()),
    ("sync_coletor_duracao_segundos",
     "Duração da leitura do banco pelo coletor neste scrape.", ()),
)


def _familia(nome: str, ajuda: str, rotulos: tuple, valor: float | None = None):
    if rotulos:
        return GaugeMetricFamily(nome, ajuda, labels=list(rotulos))
    return GaugeMetricFamily(nome, ajuda, value=0.0 if valor is None else valor)


def preparar_sessao(db: Session) -> None:
    """No PostgreSQL: transação SÓ LEITURA e teto por consulta. No SQLite (dev e
    testes), nada: o banco é local."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(text(f"SET LOCAL statement_timeout = {int(TETO_CONSULTA_MS)}"))


class PrazoDoColetorEsgotado(RuntimeError):
    """A leitura do banco passou do prazo total do scrape (``PRAZO_COLETOR_S``)."""


class LeituraAnteriorEmCurso(RuntimeError):
    """A leitura de um scrape anterior ainda não terminou (uma por processo)."""


def _leitor(db: Session, fim: float | None) -> Callable:
    """``db.execute`` com o ORÇAMENTO do prazo total no PostgreSQL: antes de cada
    consulta, o teto dela passa a ser o menor entre ``TETO_CONSULTA_MS`` e o que
    sobra até ``fim`` (relógio monotônico). Antes (revisão e95), cinco consultas
    esperando lock somavam 5 × 3 s e o scrape passava dos 10 s do Prometheus com
    ``sync_coletor_sucesso 1``. Sem prazo, ou no SQLite (dev e testes), só executa."""
    postgres = fim is not None and db.get_bind().dialect.name == "postgresql"

    def ler(consulta):
        if postgres:
            restante_ms = int((fim - time.monotonic()) * 1000)
            if restante_ms <= 0:
                raise PrazoDoColetorEsgotado("prazo total do coletor esgotado")
            teto = max(100, min(int(TETO_CONSULTA_MS), restante_ms))
            db.execute(text(f"SET LOCAL statement_timeout = {teto}"))
        return db.execute(consulta)

    return ler


# Legibilidade já conferida, por (anel de chaves, cifra) → abre? Só o booleano: o
# texto claro nunca sai do ``vault``. A cifra muda a cada recadastro (Fernet tem IV
# e carimbo próprios) e o anel muda com as chaves do processo, então a entrada certa
# nunca fica velha. Teto pequeno: são no máximo duas credenciais por escola.
_legibilidade: dict[tuple[str, str], bool] = {}
_trava_legibilidade = threading.Lock()
_TETO_LEGIBILIDADE = 2048


def _anel_atual() -> str:
    """Impressão (SHA-256) do anel de chaves da cifra deste processo — só a chave
    do memo; nenhuma chave é guardada ou exposta."""
    return hashlib.sha256("\x00".join(segredos_da_cifra()).encode("utf-8")).hexdigest()


def _status_derivados(credenciais, fim: float | None) -> list[tuple]:
    """``(escola_id, plataforma, status)`` com o status DERIVADO — o critério de
    ``vault.status_efetivo`` (o do /sync/status): a credencial cuja cifra não abre
    com as chaves deste processo (rotação sem recifrar, valor corrompido, conteúdo
    fora do formato) é ``ilegivel``, qualquer que seja o gravado. Antes a métrica
    publicava o gravado, e a ilegível aparecia como 'valida'.

    Sem decifrar mais que o necessário: cada cifra é aberta UMA vez por processo e
    por anel de chaves (``_legibilidade``); os scrapes seguintes reusam o "abre ou
    não". Dentro do PRAZO TOTAL do coletor: antes de cada decifra, ``fim`` passado
    levanta ``PrazoDoColetorEsgotado`` (o scrape responde ``sync_coletor_sucesso
    0``, sem série parcial)."""
    anel = _anel_atual()
    saida: list[tuple] = []
    for linha in credenciais:          # linhas com escola_id, plataforma, status, cifra
        chave = (anel, linha.segredo_cifrado or "")
        with _trava_legibilidade:
            legivel = _legibilidade.get(chave)
        if legivel is None:
            if fim is not None and time.monotonic() >= fim:
                raise PrazoDoColetorEsgotado("prazo total do coletor esgotado")
            legivel = vault.credencial_legivel(linha)
            with _trava_legibilidade:
                if len(_legibilidade) >= _TETO_LEGIBILIDADE:
                    _legibilidade.clear()
                _legibilidade[chave] = legivel
        saida.append((linha.escola_id, linha.plataforma,
                      linha.status if legivel else vault.STATUS_ILEGIVEL))
    return saida


def coletar_familias(db: Session, *, agora: datetime | None = None,
                     fim: float | None = None) -> list:
    """Lê o estado da sincronização e devolve as famílias de métricas do banco.
    ``fim``: instante (``time.monotonic``) até o qual as consultas podem rodar.
    Levanta em qualquer erro — quem chama (``ColetorSync``) isola a falha."""
    from app.models.escola import Escola

    agora = _utc_naive(agora) or service._agora()
    E, A, L = SincronizacaoExecucao, SincronizacaoAlerta, SincronizacaoLog
    C, Cfg = PlataformaCredencial, SincronizacaoConfig
    ler = _leitor(db, fim)

    # (1) Credenciais: tabela pequena (no máximo uma linha por escola×plataforma).
    # A cifra vem junto só para o status DERIVADO (``_status_derivados``).
    credenciais = _status_derivados(
        ler(select(C.escola_id, C.plataforma, C.status, C.segredo_cifrado)).all(), fim)

    # (2) Por integração cadastrada (credencial ou agenda): o MAX de cada estado é
    # um lookup no ix_sync_exec_frescor (status, escola_id, plataforma,
    # finalizada_em) — custo por integração, não pelo tamanho do histórico.
    pares = union(select(C.escola_id, C.plataforma),
                  select(Cfg.escola_id, Cfg.plataforma)).subquery("pares")

    def _ultima(*condicoes):
        return (select(func.max(E.finalizada_em))
                .where(E.escola_id == pares.c.escola_id, E.plataforma == pares.c.plataforma,
                       *condicoes)
                .correlate(pares).scalar_subquery())

    colunas = [_ultima(E.status == st).label(f"u_{st}") for st in STATUS_FINALIZADOS]
    # "Dado aplicado" = ``service._filtro_sucesso`` (a 'parcial' só com aluno
    # aplicado; sem a coleta por período), um MAX por estado como os de cima.
    sucesso = service._filtro_sucesso()
    colunas += [_ultima(E.status == st, sucesso).label(f"d_{st}")
                for st in service.STATUS_COM_DADO]
    integracoes = ler(
        select(pares.c.escola_id, pares.c.plataforma, *colunas)).mappings().all()

    # (3) Execuções ativas: no máximo uma por escola×plataforma (uq_sync_exec_ativa).
    ativas = ler(
        select(E.id, E.escola_id, E.plataforma, E.status, E.created_at, E.iniciada_em,
               E.disponivel_em)
        .where(E.status.in_(STATUS_ATIVOS))).all()

    # (4) Sinal de vida das ativas: o último log de cada uma (só se houver).
    ids_ativas = [a.id for a in ativas]
    ultimo_log: dict[int, datetime] = {}
    if ids_ativas:
        ultimo_log = {
            eid: _utc_naive(quando) for eid, quando in ler(
                select(L.execucao_id, func.max(L.created_at))
                .where(L.execucao_id.in_(ids_ativas))
                .group_by(L.execucao_id)).all()}

    # (5) Alertas abertos, agregados no banco.
    alertas = ler(
        select(A.escola_id, A.plataforma, A.tipo, A.severidade, func.count())
        .where(A.resolvido.is_(False))
        .group_by(A.escola_id, A.plataforma, A.tipo, A.severidade)).all()

    # (6) Marca de recálculo por ESCOLA, de qualquer plataforma — a regra de
    # ``service.recalculo_pendente_aberto``. Antes (revisão e95) ela era lida só
    # para os pares com credencial ou agenda: removida a credencial (o DELETE fecha
    # o alerta, a marca fica), a série da escola sumia com o recálculo pendente.
    # Um EXISTS por escola, pelo índice de escola_id das execuções.
    marcadas = ler(
        select(Escola.id).where(
            exists().where(E.escola_id == Escola.id, E.recalculo_pendente.is_(True))
            .correlate(Escola))).scalars().all()

    return _montar(agora, credenciais, integracoes, ativas, ultimo_log, alertas, marcadas)


def _montar(agora, credenciais, integracoes, ativas, ultimo_log, alertas,
            marcadas=()) -> list:
    """Monta as famílias a partir das linhas lidas. Rótulos que colidem depois de
    higienizados (dois valores fora do padrão viram 'outro') são AGREGADOS — série
    repetida no mesmo scrape faria o Prometheus recusar o scrape inteiro."""
    idade_estado: dict[tuple, float] = {}
    idade_dado: dict[tuple, float] = {}
    recalculo: dict[str, bool] = {}
    plataformas: set[str] = set()

    def _menor(destino: dict, chave: tuple, valor: float | None) -> None:
        if valor is not None:
            destino[chave] = min(valor, destino.get(chave, valor))

    for linha in integracoes:
        eid, plat = _escola(linha["escola_id"]), _codigo(linha["plataforma"])
        plataformas.add(plat)
        for st in STATUS_FINALIZADOS:
            _menor(idade_estado, (eid, plat, st), _idade(agora, linha[f"u_{st}"]))
        for st in service.STATUS_COM_DADO:
            _menor(idade_dado, (eid, plat), _idade(agora, linha[f"d_{st}"]))
        recalculo.setdefault(eid, False)
    for eid in marcadas:
        recalculo[_escola(eid)] = True

    limite = agora - timedelta(seconds=settings.SYNC_TRAVADA_S)
    limite_em_execucao = agora - timedelta(seconds=settings.SYNC_SEM_SINAL_S)
    ativas_por: dict[tuple, int] = defaultdict(int)
    presas_por: dict[tuple, int] = defaultdict(int)
    idade_ativa: dict[tuple, float] = {}
    for ex in ativas:
        plat, st = _codigo(ex.plataforma), _codigo(ex.status)
        plataformas.add(plat)
        if ex.status == "executando":
            desde = _utc_naive(ex.iniciada_em) or _utc_naive(ex.created_at)
            # O mesmo critério de ``service._esta_travada`` (o que o reaper finaliza).
            sinais = [m for m in (_utc_naive(ex.iniciada_em), ultimo_log.get(ex.id))
                      if m is not None]
            presa = ex.iniciada_em is not None and max(sinais) < limite_em_execucao
        else:
            desde = _utc_naive(ex.created_at)
            sinais = [m for m in (_utc_naive(ex.created_at), _utc_naive(ex.disponivel_em),
                                  ultimo_log.get(ex.id)) if m is not None]
            presa = not sinais or max(sinais) < limite
        ativas_por[(plat, st)] += 1
        presas_por[(plat, st)] += int(presa)
        idade = _idade(agora, desde)
        if idade is not None:
            idade_ativa[(_escola(ex.escola_id), plat, st)] = max(
                idade, idade_ativa.get((_escola(ex.escola_id), plat, st), idade))
    for plat in plataformas:          # zeros explícitos: a regra de alerta vê o 0
        for st in STATUS_ATIVOS:
            ativas_por[(plat, st)] += 0
            presas_por[(plat, st)] += 0

    abertos: dict[tuple, int] = defaultdict(int)
    for eid, plat, tipo, sev, n in alertas:
        chave = (_escola(eid), _codigo(plat), _codigo(tipo), _codigo(sev))
        abertos[chave] += int(n or 0)
        if tipo == "recalculo_pendente":
            recalculo[chave[0]] = True
        else:
            recalculo.setdefault(chave[0], False)

    cred_por: dict[tuple, int] = {}
    for eid, plat, st in credenciais:
        cred_por[(_escola(eid), _codigo(plat), _codigo(st))] = 1

    f = {nome: _familia(nome, ajuda, rotulos) for nome, ajuda, rotulos in _FAMILIAS_DO_BANCO}
    for chave, v in sorted(idade_estado.items()):
        f["sync_ultima_execucao_idade_segundos"].add_metric(list(chave), v)
    for chave, v in sorted(idade_dado.items()):
        f["sync_ultimo_dado_aplicado_idade_segundos"].add_metric(list(chave), v)
    for chave, v in sorted(ativas_por.items()):
        f["sync_execucoes_ativas"].add_metric(list(chave), v)
    for chave, v in sorted(idade_ativa.items()):
        f["sync_execucao_ativa_idade_segundos"].add_metric(list(chave), v)
    for chave, v in sorted(presas_por.items()):
        f["sync_execucoes_presas"].add_metric(list(chave), v)
    for chave, v in sorted(abertos.items()):
        f["sync_alertas_abertos"].add_metric(list(chave), v)
    for eid, v in sorted(recalculo.items(), key=lambda kv: int(kv[0])):
        f["sync_recalculo_pendente"].add_metric([eid], 1.0 if v else 0.0)
    for chave, v in sorted(cred_por.items()):
        f["sync_credencial_status"].add_metric(list(chave), v)
    return list(f.values())


class ColetorSync:
    """Coletor customizado do prometheus_client: lê o banco a cada scrape, numa
    sessão PRÓPRIA (fechada no fim) e só leitura. ``describe`` não toca o banco —
    o registro do coletor no boot não abre conexão."""

    def __init__(self, fabrica: Callable[[], Session] | None = None,
                 relogio: Callable[[], datetime] | None = None) -> None:
        self.fabrica = fabrica
        self.relogio = relogio
        self._em_curso: threading.Thread | None = None
        self._trava = threading.Lock()

    def describe(self):
        return [_familia(nome, ajuda, rotulos)
                for nome, ajuda, rotulos in _FAMILIAS_DO_BANCO + _FAMILIAS_SEMPRE]

    def collect(self):
        inicio = time.perf_counter()
        try:
            familias = self._ler_banco_com_prazo()
            sucesso = 1.0
        except Exception as erro:  # noqa: BLE001 — o coletor nunca derruba o /metrics
            _avisar_falha(erro)
            familias, sucesso = [], 0.0
        yield from familias
        (nome_ag, ajuda_ag, _), (nome_ok, ajuda_ok, _), (nome_dur, ajuda_dur, _) = (
            _FAMILIAS_SEMPRE)
        yield _familia(nome_ag, ajuda_ag, (), 1.0 if service.agendador_ligado() else 0.0)
        yield _familia(nome_ok, ajuda_ok, (), sucesso)
        yield _familia(nome_dur, ajuda_dur, (), time.perf_counter() - inicio)

    def _ler_banco_com_prazo(self) -> list:
        """Roda ``_ler_banco`` numa thread própria e espera no máximo
        ``PRAZO_COLETOR_S``. Uma leitura por vez: se a do scrape anterior ainda não
        terminou (pool esgotado, conexão pendurada), recusa na hora em vez de
        empilhar threads e conexões. A thread que passou do prazo termina sozinha
        (as consultas têm teto no PostgreSQL) e fecha a própria sessão."""
        prazo = float(PRAZO_COLETOR_S)
        resultado: dict = {}

        def _alvo():
            try:
                resultado["familias"] = self._ler_banco()
            except BaseException as erro:  # noqa: BLE001 — devolvido a quem espera
                resultado["erro"] = erro

        with self._trava:
            anterior = self._em_curso
            if anterior is not None and anterior.is_alive():
                raise LeituraAnteriorEmCurso("a leitura do scrape anterior não terminou")
            leitura = threading.Thread(target=_alvo, name="metricas-sync-coletor",
                                       daemon=True)
            self._em_curso = leitura
            leitura.start()
        leitura.join(prazo)
        if leitura.is_alive():
            raise PrazoDoColetorEsgotado(f"a leitura do banco passou de {prazo:g} s")
        if "erro" in resultado:
            raise resultado["erro"]
        return resultado["familias"]

    def _ler_banco(self) -> list:
        fim = time.monotonic() + float(PRAZO_COLETOR_S)
        fabrica = self.fabrica
        if fabrica is None:
            from app.core.database import SessionLocal
            fabrica = SessionLocal
        db = fabrica()
        try:
            preparar_sessao(db)
            agora = self.relogio() if self.relogio is not None else None
            return coletar_familias(db, agora=agora, fim=fim)
        finally:
            try:
                db.rollback()
            finally:
                db.close()


_INTERVALO_TRACEBACK_S = 600
_ultimo_traceback = [0.0]
_trava_aviso = threading.Lock()


def _avisar_falha(erro: BaseException) -> None:
    """Log da falha do coletor sem inundar: o nome do erro a cada scrape; o
    traceback (já redigido pelo formatador de log) no máximo a cada 10 min."""
    with _trava_aviso:
        agora = time.monotonic()
        completo = agora - _ultimo_traceback[0] >= _INTERVALO_TRACEBACK_S
        if completo:
            _ultimo_traceback[0] = agora
    logger.warning("metricas_sync_coletor_falhou: %s", type(erro).__name__,
                   exc_info=erro if completo else None)


_coletor: ColetorSync | None = None
_trava_registro = threading.Lock()


def registrar_coletor() -> ColetorSync | None:
    """Registra o coletor no registro GLOBAL do prometheus_client (uma vez por
    processo; chamadas seguintes devolvem o mesmo). None sem prometheus-client."""
    global _coletor
    if _prom is None:  # pragma: no cover
        return None
    with _trava_registro:
        if _coletor is None:
            coletor = ColetorSync()
            _prom.REGISTRY.register(coletor)
            _coletor = coletor
    return _coletor


def coletor_global() -> ColetorSync | None:
    return _coletor


# ---------------------------------------------------------------------------
# 2. Eventos em processo (ponto único: fim de ``service.executar``)
# ---------------------------------------------------------------------------
if _prom is not None:
    _M_FINALIZADAS = _prom.Counter(
        "sync_execucoes_finalizadas_total",
        "Execuções de sincronização finalizadas por este processo, por estado e motivo "
        "(no 'erro', o motivo é o código da falha).",
        ["plataforma", "status", "motivo"])
    _M_DURACAO = _prom.Histogram(
        "sync_execucao_duracao_segundos",
        "Duração das execuções de sincronização finalizadas por este processo.",
        ["plataforma", "status"], buckets=BUCKETS_DURACAO_S)
    _M_ALUNOS = _prom.Counter(
        "sync_alunos_aplicados_total",
        "Alunos distintos com dado novo ou alterado, somados por execução finalizada "
        "neste processo.", ["plataforma"])
    _M_FALHAS = _prom.Counter(
        "sync_falhas_unidade_total",
        "Unidades da coleta que falharam (turma, lote, aluno, endpoint, arquivo), por "
        "código, nas execuções finalizadas neste processo.",
        ["plataforma", "unidade", "codigo"])
else:  # pragma: no cover
    _M_FINALIZADAS = _M_DURACAO = _M_ALUNOS = _M_FALHAS = None


def execucao_finalizada(*, plataforma: str | None, status: str | None,
                        motivo: str | None, duracao_ms: int | None,
                        alunos_aplicados: int, falhas) -> None:
    """Registra o fim de UMA execução. Chamado só por ``service.executar``, depois
    do commit (conta só o que ficou gravado)."""
    if _M_FINALIZADAS is None:  # pragma: no cover
        return
    plat, st = _codigo(plataforma), _codigo(status)
    _M_FINALIZADAS.labels(plat, st, _codigo(motivo)).inc()
    _M_DURACAO.labels(plat, st).observe(max(0.0, (duracao_ms or 0) / 1000.0))
    if alunos_aplicados:
        _M_ALUNOS.labels(plat).inc(int(alunos_aplicados))
    for falha in falhas or ():
        _M_FALHAS.labels(plat, _codigo((falha or {}).get("unidade")),
                         _codigo((falha or {}).get("codigo"))).inc()
