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
``registrar_falha`` / ``limpar``. O TETO e a JANELA de cada dimensão vêm do
limitador em memória correspondente (quest/routers/auth.py; no Edu,
app.core.rate_limit, configurável por EDU_LOGIN_TETO_*), para as duas camadas
nunca divergirem.

Concorrência: o incremento é um UPDATE atômico (``falhas = falhas + 1`` no
próprio banco), não ler-somar-gravar; a 1ª falha de uma chave é um INSERT num
savepoint e, se outro worker inseriu no meio, cai no UPDATE. Nada é perdido entre
processos simultâneos.
"""
from __future__ import annotations

import hashlib
import hmac
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.quest.models import QuestLimiteAcesso

# Faxina das linhas vencidas: chaves atacante-controladas (códigos aleatórios)
# não podem crescer a tabela sem limite. Probabilística para não custar uma
# consulta a mais em toda falha; a idade mínima deixa folga sobre qualquer janela.
_FAXINA_PROBABILIDADE = 0.01
_FAXINA_IDADE = timedelta(days=1)

_DOMINIO = "quest-limite"


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


def registrar_falha(db: Session, chave_: str, *, max_tentativas: int,
                    janela_s: int, bloqueio_s: int | None = None) -> int:
    """Conta 1 tentativa na janela corrente; ao atingir o teto, bloqueia a chave
    por ``bloqueio_s`` (padrão: a própria janela). Devolve as falhas da janela
    já com esta (o incremento é atômico: só UMA transação vê o valor do teto).
    NÃO commita (o chamador commita antes de responder — inclusive no caminho
    de erro)."""
    agora = _agora()
    vencida = QuestLimiteAcesso.janela_inicio < agora - timedelta(seconds=janela_s)
    incrementa = (
        update(QuestLimiteAcesso)
        .where(QuestLimiteAcesso.chave == chave_)
        .values(falhas=case((vencida, 1), else_=QuestLimiteAcesso.falhas + 1),
                janela_inicio=case((vencida, agora),
                                   else_=QuestLimiteAcesso.janela_inicio),
                atualizado_em=agora)
        .execution_options(synchronize_session=False)
    )
    if db.execute(incrementa).rowcount == 0:
        try:
            with db.begin_nested():
                db.add(QuestLimiteAcesso(chave=chave_, falhas=1, janela_inicio=agora,
                                         atualizado_em=agora))
        except IntegrityError:
            db.execute(incrementa)   # outro processo criou a linha no meio
    falhas = db.execute(
        select(QuestLimiteAcesso.falhas).where(QuestLimiteAcesso.chave == chave_)
    ).scalar_one()
    if falhas >= max_tentativas:
        db.execute(
            update(QuestLimiteAcesso)
            .where(QuestLimiteAcesso.chave == chave_)
            .values(bloqueado_ate=agora + timedelta(seconds=bloqueio_s or janela_s))
            .execution_options(synchronize_session=False))
    if random.random() < _FAXINA_PROBABILIDADE:
        faxina(db)
    return falhas


def limpar(db: Session, chaves: list[str]) -> None:
    """Zera as chaves (login bem-sucedido). NÃO commita."""
    if chaves:
        db.execute(delete(QuestLimiteAcesso)
                   .where(QuestLimiteAcesso.chave.in_(chaves))
                   .execution_options(synchronize_session=False))


def faxina(db: Session, agora: datetime | None = None) -> int:
    """Apaga contadores parados há mais de um dia e sem bloqueio vigente. Não é
    política de retenção: o contador vencido não serve para nada. NÃO commita.

    Só apaga as linhas vencidas que NINGUÉM está segurando (``FOR UPDATE SKIP
    LOCKED``). A faxina roda dentro da transação de uma falha, que já segura as
    linhas que contou — inclusive a ``global_falha``, comum a toda a rede. Um
    DELETE simples esperaria uma linha velha que outra falha (de outra escola)
    acabou de atualizar, enquanto essa outra falha espera a linha global: ciclo
    de locks, e o PostgreSQL aborta uma das duas (500 no login da criança). A
    linha travada fica para a próxima faxina, o que é inofensivo. No SQLite o
    ``with_for_update`` não gera SQL (um escritor só) e nada muda."""
    agora = agora or _agora()
    livres = (
        select(QuestLimiteAcesso.id)
        .where(QuestLimiteAcesso.atualizado_em < agora - _FAXINA_IDADE,
               or_(QuestLimiteAcesso.bloqueado_ate.is_(None),
                   QuestLimiteAcesso.bloqueado_ate < agora))
        .with_for_update(skip_locked=True)
    )
    resultado = db.execute(
        delete(QuestLimiteAcesso)
        .where(QuestLimiteAcesso.id.in_(livres.scalar_subquery()))
        .execution_options(synchronize_session=False))
    return resultado.rowcount or 0
