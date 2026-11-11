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
``contar`` (``registrar_falha`` para uma chave só) / ``limpar``. O TETO e a JANELA
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
import random
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, String, case, cast, column, delete, func, or_, select, values
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


def _instrucao_de_contagem(dialeto: str, itens: list[Limite], agora: datetime):
    """``INSERT ... ON CONFLICT (chave) DO UPDATE ... RETURNING`` das chaves: a 1ª
    falha de uma chave cria a linha; as seguintes somam 1 na janela corrente (ou
    recomeçam do 1 se ela venceu); ao chegar ao teto, bloqueia a chave. Teto, janela e
    bloqueio de cada linha vêm do ``Limite`` dela (``CASE`` pela chave)."""
    teto = case({x.chave: x.teto for x in itens}, value=_TABELA.c.chave)
    corte = case({x.chave: agora - timedelta(seconds=x.janela_s) for x in itens},
                 value=_TABELA.c.chave)
    fim_do_bloqueio = case({x.chave: agora + x.bloqueio for x in itens},
                           value=_TABELA.c.chave)
    vencida = _TABELA.c.janela_inicio < corte
    falhas = case((vencida, 1), else_=_TABELA.c.falhas + 1)
    novas = [(x.chave, 1, agora, agora, agora + x.bloqueio if x.teto <= 1 else None)
             for x in itens]
    nomes = ["chave", "falhas", "janela_inicio", "atualizado_em", "bloqueado_ate"]
    if dialeto == "postgresql":
        tipo_data = _TABELA.c.janela_inicio.type
        linhas = values(column("chave", String), column("falhas", Integer),
                        column("janela_inicio", tipo_data),
                        column("atualizado_em", tipo_data),
                        column("bloqueado_ate", tipo_data), name="nova").data(novas)
        # O NULL do VALUES não tem tipo (o PostgreSQL o leria como texto): CAST.
        instrucao = insert_pg(_TABELA).from_select(
            nomes, select(linhas.c.chave, linhas.c.falhas, linhas.c.janela_inicio,
                          linhas.c.atualizado_em, cast(linhas.c.bloqueado_ate, tipo_data))
            .where(_com_prazo_de_trava()))
    else:
        instrucao = insert_sqlite(_TABELA).values([dict(zip(nomes, n)) for n in novas])
    return instrucao.on_conflict_do_update(
        index_elements=[_TABELA.c.chave],
        set_={"falhas": falhas,
              "janela_inicio": case((vencida, agora), else_=_TABELA.c.janela_inicio),
              "atualizado_em": agora,
              "bloqueado_ate": case((falhas >= teto, fim_do_bloqueio),
                                    else_=_TABELA.c.bloqueado_ate)},
    ).returning(_TABELA.c.chave, _TABELA.c.falhas)


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
    return {chave_: falhas for chave_, falhas in linhas}


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
