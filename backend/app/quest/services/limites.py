"""Limite de tentativas PERSISTENTE (tabela quest_limites_acesso): o login infantil
do Quest e os tetos de falhas do login do Edu.

Usuários: o login por código do Quest (quest/routers/auth.py) e, desde 31/10/2026,
o /auth/login do Edu (routers/auth.py), com os tetos de falhas POR IP e GLOBAL nas
dimensões ``edu_login_ip_falha`` e ``edu_login_global_falha`` (prefixo próprio,
nunca se mistura com as dimensões do Quest). Os limites do Edu por conta e por
(conta, IP) seguem só em memória.

Por que no banco: o limitador em memória (app.core.rate_limit) zera a cada
reinício e não é compartilhado entre workers/réplicas — o teto efetivo vira N×
com N processos, e cada deploy devolve o orçamento inteiro a quem estava barrado.
Aqui o contador e o bloqueio valem para todos os processos e sobrevivem ao
restart (o mesmo banco que todos já usam; sem Redis a mais na infraestrutura).

Contrato pequeno, o mesmo do limitador em memória: ``bloqueado`` /
``contar`` (``registrar_falha`` para uma chave só) / ``limpar``; e, para o teto que
tem de valer também para tentativas simultâneas (o login do Edu), ``reservar`` antes
de avaliar e ``devolver`` o que não virou falha. O TETO e a JANELA
de cada dimensão vêm do limitador em memória correspondente (quest/routers/auth.py;
no Edu, app.core.rate_limit, configurável por EDU_LOGIN_TETO_*), para as duas
camadas nunca divergirem.

Contagem FORA da transação da requisição (auditoria G_CARGA-1, 11/11/2026). Antes, a
falha era contada dentro da transação de quem chamava: UPDATE da linha, SELECT,
INSERT da auditoria e COMMIT, com a trava da linha presa por várias idas ao banco
(~195 ms cada em produção). A linha do teto GLOBAL é uma só para a API inteira: toda
falha passava em fila por ela, cada pedido esperando com uma thread e uma conexão do
pool presas, e 240 logins errados deixavam as sessões já abertas esperando até 75 s.
Agora:

- cada contagem é UMA instrução atômica (``INSERT ... ON CONFLICT (chave) DO UPDATE
  ... RETURNING``, todas as chaves do pedido juntas), em AUTOCOMMIT numa conexão do
  mesmo pool: a trava de cada linha dura só a execução da instrução, sem ida ao banco
  no meio, e a contagem vale na hora, sem esperar o commit de ninguém;
- a instrução liga o ``lock_timeout`` (``_PRAZO_DA_TRAVA_MS``) só para ela mesma: se
  a linha estiver presa além disso, ``LimiteIndisponivel`` e quem chama conta só na
  memória, em vez de esperar;
- todas as instruções que travam mais de uma linha travam na mesma ordem (a da
  chave), e nenhuma trava fica presa esperando outra: sem deadlock entre elas.

Quem chama não pode estar segurando conexão da sessão ao contar (conte depois do
commit): a contagem pega uma conexão do pool e, com N pedidos segurando uma e
esperando a segunda, o pool esgotaria. No SQLite (desenvolvimento e testes, um
escritor só, sem fila de travas) a instrução roda na própria sessão, que é commitada
na hora.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import math
import random
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Integer,
    String,
    and_,
    case,
    cast,
    column,
    delete,
    func,
    null,
    or_,
    select,
    values,
)
from sqlalchemy.dialects.postgresql import insert as insert_pg
from sqlalchemy.dialects.sqlite import insert as insert_sqlite
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.quest.models import QuestLimiteAcesso

logger = logging.getLogger("constela.limites")

_TABELA = QuestLimiteAcesso.__table__

# Faxina das linhas vencidas: chaves atacante-controladas (códigos aleatórios)
# não podem crescer a tabela sem limite. Probabilística para não custar uma
# consulta a mais em toda falha; a idade mínima deixa folga sobre qualquer janela.
_FAXINA_PROBABILIDADE = 0.01
_FAXINA_IDADE = timedelta(days=1)

_DOMINIO = "quest-limite"

# Quanto uma contagem espera por uma linha presa por outra transação antes de
# desistir (PostgreSQL). As contagens daqui seguram cada linha só durante a própria
# instrução (frações de milissegundo): passar disso é sinal de algo fora do normal, e
# esperar mais seria voltar à fila.
_PRAZO_DA_TRAVA_MS = 500
# SQLSTATE do PostgreSQL para "lock_not_available" (o estouro do lock_timeout).
_TRAVA_OCUPADA = "55P03"
# No máximo um aviso de "contagem sem trava" por minuto em cada processo.
_INTERVALO_DO_AVISO_S = 60.0
_ultimo_aviso = [float("-inf")]
_trava_do_aviso = threading.Lock()


class LimiteIndisponivel(Exception):
    """A linha do contador ficou presa além de ``_PRAZO_DA_TRAVA_MS`` (PostgreSQL): a
    tentativa NÃO foi contada no banco. Quem chama conta só na memória."""


@dataclass(frozen=True)
class Limite:
    """Uma chave a contar, com o teto e a janela da dimensão dela (os do limitador em
    memória correspondente). Ao chegar ao teto, a chave fica bloqueada por
    ``bloqueio_s`` (padrão: a própria janela)."""

    chave: str
    teto: int
    janela_s: int
    bloqueio_s: int | None = None

    @property
    def bloqueio(self) -> timedelta:
        return timedelta(seconds=self.bloqueio_s or self.janela_s)


def _agora() -> datetime:
    # UTC sem fuso: o schema guarda DateTime "ingênuo" (sem timezone).
    return datetime.now(timezone.utc).replace(tzinfo=None)


def chave(dimensao: str, valor: str) -> str:
    """``"<dimensão>:<HMAC>"`` — nem o IP nem o código digitado vão em texto
    para o banco. Trocar a chave do servidor só zera os contadores (inofensivo)."""
    segredo = (settings.DATA_ENCRYPTION_KEY or "").strip() or settings.SECRET_KEY
    k = hashlib.sha256(f"{segredo}|{_DOMINIO}".encode()).digest()
    digest = hmac.new(k, (valor or "").encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{dimensao}:{digest[:32]}"


def bloqueado(db: Session, chaves: list[str]) -> bool:
    """Alguma das chaves está em bloqueio temporário agora?"""
    if not chaves:
        return False
    agora = _agora()
    return db.execute(
        select(QuestLimiteAcesso.id)
        .where(QuestLimiteAcesso.chave.in_(chaves),
               QuestLimiteAcesso.bloqueado_ate.is_not(None),
               QuestLimiteAcesso.bloqueado_ate > agora)
        .limit(1)
    ).first() is not None


def _avisar_trava_ocupada() -> None:
    with _trava_do_aviso:
        agora = time.monotonic()
        if agora - _ultimo_aviso[0] < _INTERVALO_DO_AVISO_S:
            return
        _ultimo_aviso[0] = agora
    logger.warning("limite_contagem_sem_trava", extra={
        "evento": "limites.contagem_sem_trava",
        "prazo_ms": _PRAZO_DA_TRAVA_MS,
        "efeito": ("a tentativa foi contada só na memória deste processo: a linha do "
                   "contador ficou presa além do prazo"),
    })


def _executar(db: Session, instrucao, *, linhas: bool = True):
    """Roda a instrução FORA da transação da sessão: no PostgreSQL, numa conexão do
    mesmo pool em AUTOCOMMIT (a instrução é a transação inteira); nos outros bancos
    (o SQLite de desenvolvimento e dos testes), na própria sessão, commitada na hora.
    Devolve as linhas (``linhas=True``) ou quantas linhas a instrução afetou."""
    motor = db.get_bind()
    if isinstance(motor, Engine) and motor.dialect.name == "postgresql":
        with motor.connect() as conexao:
            conexao.execution_options(isolation_level="AUTOCOMMIT")
            try:
                resultado = conexao.execute(instrucao)
                return resultado.all() if linhas else (resultado.rowcount or 0)
            except DBAPIError as erro:
                original = erro.orig
                estado = (getattr(original, "sqlstate", None)
                          or getattr(original, "pgcode", None))
                if estado == _TRAVA_OCUPADA:
                    _avisar_trava_ocupada()
                    raise LimiteIndisponivel(
                        "a linha do contador ficou presa além do prazo") from erro
                raise
    resultado = db.execute(instrucao)
    saida = resultado.all() if linhas else (resultado.rowcount or 0)
    db.commit()
    return saida


def _com_prazo_de_trava():
    """Condição sempre verdadeira que liga o ``lock_timeout`` SÓ desta instrução no
    PostgreSQL: ``set_config(..., is_local => true)`` vale até o fim da transação, que
    em AUTOCOMMIT é a própria instrução. É uma subconsulta sem relação com as linhas
    (avaliada uma vez, antes da primeira linha): o prazo já vale quando a instrução
    for esperar a trava de alguma linha."""
    return (select(func.set_config("lock_timeout", f"{_PRAZO_DA_TRAVA_MS}ms", True))
            .scalar_subquery().is_not(None))


def _sem_repetidas(itens: Iterable[Limite]) -> list[Limite]:
    """As chaves em ordem (a ordem em que a instrução trava as linhas é a mesma em
    todos os pedidos), sem repetição (o PostgreSQL recusa a mesma linha duas vezes
    num ON CONFLICT DO UPDATE)."""
    por_chave: dict[str, Limite] = {}
    for item in itens:
        por_chave.setdefault(item.chave, item)
    return [por_chave[c] for c in sorted(por_chave)]


_COLUNAS_NOVAS = ["chave", "falhas", "janela_inicio", "atualizado_em", "bloqueado_ate"]


def _insercao(dialeto: str, novas: list[tuple]):
    """O ``INSERT`` das linhas ``novas`` (na ordem de ``_COLUNAS_NOVAS``), ainda sem o
    ``ON CONFLICT``. No PostgreSQL, ``INSERT ... SELECT`` de um VALUES com o
    ``lock_timeout`` ligado (``_com_prazo_de_trava``)."""
    if dialeto != "postgresql":
        return insert_sqlite(_TABELA).values([dict(zip(_COLUNAS_NOVAS, n)) for n in novas])
    tipo_data = _TABELA.c.janela_inicio.type
    linhas = values(column("chave", String), column("falhas", Integer),
                    column("janela_inicio", tipo_data),
                    column("atualizado_em", tipo_data),
                    column("bloqueado_ate", tipo_data), name="nova").data(novas)
    # O NULL do VALUES não tem tipo (o PostgreSQL o leria como texto): CAST.
    return insert_pg(_TABELA).from_select(
        _COLUNAS_NOVAS,
        select(linhas.c.chave, linhas.c.falhas, linhas.c.janela_inicio,
               linhas.c.atualizado_em, cast(linhas.c.bloqueado_ate, tipo_data))
        .where(_com_prazo_de_trava()))


def _instrucao_de_contagem(dialeto: str, itens: list[Limite], agora: datetime, *,
                           so_se_livre: bool = False):
    """``INSERT ... ON CONFLICT (chave) DO UPDATE ... RETURNING`` das chaves: a 1ª
    falha de uma chave cria a linha; as seguintes somam 1 na janela corrente (ou
    recomeçam do 1 se ela venceu); ao chegar ao teto, bloqueia a chave. Teto, janela e
    bloqueio de cada linha vêm do ``Limite`` dela (``CASE`` pela chave).

    ``so_se_livre``: só soma na chave que não está bloqueada nem cheia na janela; a
    que está fica como está e não volta no RETURNING (``reservar``)."""
    teto = case({x.chave: x.teto for x in itens}, value=_TABELA.c.chave)
    corte = case({x.chave: agora - timedelta(seconds=x.janela_s) for x in itens},
                 value=_TABELA.c.chave)
    fim_do_bloqueio = case({x.chave: agora + x.bloqueio for x in itens},
                           value=_TABELA.c.chave)
    vencida = _TABELA.c.janela_inicio < corte
    falhas = case((vencida, 1), else_=_TABELA.c.falhas + 1)
    livre = and_(or_(_TABELA.c.bloqueado_ate.is_(None), _TABELA.c.bloqueado_ate <= agora),
                 or_(vencida, _TABELA.c.falhas < teto))
    novas = [(x.chave, 1, agora, agora, agora + x.bloqueio if x.teto <= 1 else None)
             for x in itens]
    return _insercao(dialeto, novas).on_conflict_do_update(
        index_elements=[_TABELA.c.chave],
        set_={"falhas": falhas,
              "janela_inicio": case((vencida, agora), else_=_TABELA.c.janela_inicio),
              "atualizado_em": agora,
              "bloqueado_ate": case((falhas >= teto, fim_do_bloqueio),
                                    else_=_TABELA.c.bloqueado_ate)},
        where=livre if so_se_livre else None,
    ).returning(_TABELA.c.chave, _TABELA.c.falhas, _TABELA.c.janela_inicio)


def contar(db: Session, itens: Iterable[Limite]) -> dict[str, int]:
    """Conta 1 tentativa em cada chave, numa instrução só, FORA da transação da
    sessão (ver o topo do módulo). Devolve, por chave, as falhas da janela já com esta
    (o incremento é atômico: só UM pedido vê cada valor). Ao chegar ao teto, a chave
    fica bloqueada (``bloqueado``) por ``Limite.bloqueio``.

    No PostgreSQL a sessão não é tocada (chame depois do commit dela); no SQLite a
    instrução roda nela e ela é commitada. ``LimiteIndisponivel`` se uma linha ficou
    presa além do prazo: nada foi contado no banco."""
    itens = _sem_repetidas(itens)
    if not itens:
        return {}
    agora = _agora()
    linhas = _executar(db, _instrucao_de_contagem(db.get_bind().dialect.name, itens,
                                                  agora))
    if random.random() < _FAXINA_PROBABILIDADE:
        faxina(db, agora)
    return {chave_: falhas for chave_, falhas, _ in linhas}


@dataclass(frozen=True)
class Tomada:
    """Uma tentativa reservada numa chave: as falhas da janela já com ela e o início
    da janela em que entrou (a devolução só vale nessa janela)."""

    chave: str
    teto: int
    falhas: int
    janela_inicio: datetime


@dataclass(frozen=True)
class Reserva:
    """O resultado de ``reservar``: as tentativas tomadas (todas as chaves) ou, se
    alguma chave recusou, nenhuma tomada e os segundos de espera de cada recusada."""

    tomadas: tuple[Tomada, ...] = ()
    esperas: tuple[tuple[str, int], ...] = ()

    @property
    def aceita(self) -> bool:
        return not self.esperas

    def falhas(self, chave_: str) -> int:
        return next((t.falhas for t in self.tomadas if t.chave == chave_), 0)

    def espera(self, chave_: str) -> int | None:
        return next((s for c, s in self.esperas if c == chave_), None)


def reservar(db: Session, itens: Iterable[Limite]) -> Reserva:
    """RESERVA 1 tentativa em todas as chaves, ANTES de avaliá-la, ou em nenhuma
    (auditoria G_CARGA-3, 11/11/2026). Antes o teto era conferido no começo e a falha
    contada no fim: todo pedido que passava pela conferência antes de a falha do teto
    ser gravada seguia até o fim, e uma rajada simultânea de um IP só tinha bem mais
    que o teto de palpites avaliados. Aqui a conferência e a contagem são a MESMA
    instrução atômica (``_instrucao_de_contagem`` com ``so_se_livre``): só soma na chave
    que está abaixo do teto e sem bloqueio, e quem chega com ela cheia não soma nada.

    Se alguma chave recusou, as que foram tomadas na mesma instrução são devolvidas na
    hora (tudo ou nada: um IP bloqueado não gasta o teto global) e a ``Reserva`` traz a
    espera de cada recusada. A tentativa reservada que não virar falha (login certo,
    recusa por outro motivo) volta com ``devolver``: só falhas contam, como antes. Quem
    está no meio da avaliação ocupa a vaga dele: com o teto quase cheio, uma tentativa
    em andamento pode recusar outra que chegou junto. No banco, a recusa dura até a
    tentativa em andamento terminar: se ela virar falha, fica o bloqueio; se voltar, a
    chave aceita de novo. A espera da recusa é a do bloqueio (a maior possível, a que
    vale se ela virar falha). Quem recebe a recusa não deve guardá-la por essa espera
    inteira: o login do Edu a guarda na memória por poucos segundos
    (``_RECUSA_DO_BANCO_NA_MEMORIA_S`` em app.routers.auth) e depois volta ao banco.

    Mesmas regras de ``contar`` (fora da transação da sessão; ``LimiteIndisponivel``
    se uma linha ficou presa além do prazo, e então nada foi reservado)."""
    itens = _sem_repetidas(itens)
    if not itens:
        return Reserva()
    agora = _agora()
    linhas = _executar(db, _instrucao_de_contagem(db.get_bind().dialect.name, itens,
                                                  agora, so_se_livre=True))
    por_chave = {chave_: (falhas, inicio) for chave_, falhas, inicio in linhas}
    tomadas = tuple(Tomada(x.chave, x.teto, *por_chave[x.chave])
                    for x in itens if x.chave in por_chave)
    recusadas = [x for x in itens if x.chave not in por_chave]
    if not recusadas:
        if random.random() < _FAXINA_PROBABILIDADE:
            faxina(db, agora)
        return Reserva(tomadas=tomadas)
    if tomadas:
        try:
            devolver(db, Reserva(tomadas=tomadas))
        except LimiteIndisponivel:
            pass   # fica contada (o aviso já saiu): o erro é a favor do teto
    return Reserva(esperas=_esperas(db, recusadas, agora))


def _esperas(db: Session, recusadas: list[Limite],
             agora: datetime) -> tuple[tuple[str, int], ...]:
    """Segundos até cada chave recusada voltar a aceitar: o fim do bloqueio ou, com a
    janela cheia, o fim da janela (no mínimo 1)."""
    linhas = {chave_: (falhas, inicio, ate) for chave_, falhas, inicio, ate in _executar(
        db, select(_TABELA.c.chave, _TABELA.c.falhas, _TABELA.c.janela_inicio,
                   _TABELA.c.bloqueado_ate)
        .where(_TABELA.c.chave.in_([x.chave for x in recusadas])))}
    esperas = []
    for x in recusadas:
        falhas, inicio, ate = linhas.get(x.chave, (0, agora, None))
        fins = [ate] if ate is not None else []
        if falhas >= x.teto:
            fins.append(inicio + timedelta(seconds=x.janela_s))
        fim = max(fins, default=agora)
        esperas.append((x.chave, max(1, math.ceil((fim - agora).total_seconds()))))
    return tuple(esperas)


def devolver(db: Session, reserva: Reserva) -> None:
    """Desfaz as tentativas tomadas por ``reservar`` (a que não virou falha). Só na
    janela em que foram tomadas (a janela que já recomeçou não tem o que devolver), e
    a chave que volta a ficar abaixo do teto sai do bloqueio.

    A mesma forma de instrução de ``reservar`` (``INSERT ... ON CONFLICT DO UPDATE``,
    em ordem de chave): toda instrução daqui que trava mais de uma linha trava na
    mesma ordem, sem deadlock entre elas. A linha que não existe mais renasceria
    zerada (não acontece: a faxina só apaga linha parada há um dia). Fora da transação
    da sessão, como ``contar``."""
    tomadas = sorted(reserva.tomadas, key=lambda t: t.chave)
    if not tomadas:
        return
    agora = _agora()
    teto = case({t.chave: t.teto for t in tomadas}, value=_TABELA.c.chave)
    janela = case({t.chave: t.janela_inicio for t in tomadas}, value=_TABELA.c.chave)
    instrucao = _insercao(db.get_bind().dialect.name,
                          [(t.chave, 0, agora, agora, None) for t in tomadas])
    _executar(db, instrucao.on_conflict_do_update(
        index_elements=[_TABELA.c.chave],
        set_={"falhas": _TABELA.c.falhas - 1,
              "bloqueado_ate": case((_TABELA.c.falhas - 1 < teto, null()),
                                    else_=_TABELA.c.bloqueado_ate)},
        where=and_(_TABELA.c.janela_inicio == janela, _TABELA.c.falhas > 0)),
        linhas=False)


def registrar_falha(db: Session, chave_: str, *, max_tentativas: int,
                    janela_s: int, bloqueio_s: int | None = None) -> int:
    """``contar`` de uma chave só: as falhas da janela já com esta."""
    return contar(db, [Limite(chave_, max_tentativas, janela_s, bloqueio_s)])[chave_]


def limpar(db: Session, chaves: list[str]) -> None:
    """Zera as chaves (login bem-sucedido). NÃO commita: vai junto com o login, na
    transação dele (são as linhas da CONTA, não as do IP nem a global)."""
    if chaves:
        db.execute(delete(QuestLimiteAcesso)
                   .where(QuestLimiteAcesso.chave.in_(chaves))
                   .execution_options(synchronize_session=False))


def faxina(db: Session, agora: datetime | None = None) -> int:
    """Apaga contadores parados há mais de um dia e sem bloqueio vigente. Não é
    política de retenção: o contador vencido não serve para nada. Roda fora da
    transação da sessão, como a contagem (``_executar``; no SQLite, commita a sessão).

    Só apaga as linhas vencidas que NINGUÉM está segurando (``FOR UPDATE SKIP
    LOCKED``): a faxina nunca espera trava de ninguém, e a linha travada fica para a
    próxima faxina, o que é inofensivo. No SQLite o ``with_for_update`` não gera SQL
    (um escritor só) e nada muda."""
    agora = agora or _agora()
    livres = (
        select(QuestLimiteAcesso.id)
        .where(QuestLimiteAcesso.atualizado_em < agora - _FAXINA_IDADE,
               or_(QuestLimiteAcesso.bloqueado_ate.is_(None),
                   QuestLimiteAcesso.bloqueado_ate < agora))
        .with_for_update(skip_locked=True)
    )
    return _executar(
        db,
        delete(QuestLimiteAcesso)
        .where(QuestLimiteAcesso.id.in_(livres.scalar_subquery()))
        .execution_options(synchronize_session=False),
        linhas=False)
