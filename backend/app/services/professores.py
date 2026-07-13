"""Criação AUTOMÁTICA de contas de PROFESSOR a partir dos relatórios importados
(Lista Piloto e Elefante Letrado).

Cada nome vira um ``Professor`` (para o RBAC por turma) + um ``Usuario`` de login
na convenção pedida pelo gestor:
    usuário = Primeiro + Último nome, iniciais MAIÚSCULAS  → ex.: "PaulaVilela"
    senha   = Primeiro nome + "123"                        → ex.: "Paula123"

Idempotente: casa por NOME dentro da escola, então não duplica entre as duas
fontes nem em reimportações. Um campo com vários professores ("A, B; C") cria uma
conta para CADA um; o PRIMEIRO vira o titular da turma (``Turma.professor_id``),
que é o vínculo do RBAC (``permissoes.turmas_permitidas``).
"""
from __future__ import annotations

import logging
import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_senha
from app.models import Professor, Usuario

_log = logging.getLogger(__name__)
_DOMINIO = "professor.constelaedu.com"


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto or "")
                   if unicodedata.category(c) != "Mn")


def _chave_nome(nome: str) -> str:
    """Chave de identidade do professor: sem acento, caixa e espaços normalizados.
    Casa 'Antônio Silva' com 'Antonio  SILVA' — a MESMA pessoa entre as fontes."""
    return _sem_acento(" ".join((nome or "").split())).casefold()


def _cap_alnum(palavra: str) -> str:
    """Palavra só com letras/dígitos (sem acento), Primeira Maiúscula."""
    limpa = re.sub(r"[^A-Za-z0-9]", "", _sem_acento(palavra))
    return (limpa[:1].upper() + limpa[1:].lower()) if limpa else ""


def credenciais_professor(nome: str) -> tuple[str, str] | None:
    """(username_base, senha) na convenção pedida, ou None se o nome não servir."""
    partes = [p for p in (nome or "").split() if p]
    if not partes:
        return None
    primeiro = _cap_alnum(partes[0])
    ultimo = _cap_alnum(partes[-1]) if len(partes) > 1 else ""
    if not primeiro:
        return None
    # Deixa folga p/ sufixo de desambiguação (Usuario.username é String(30)).
    return (primeiro + ultimo)[:26], f"{primeiro}123"


def nomes_de_professores(texto: str) -> list[str]:
    """Separa vários professores de um campo ('A, B; C / D e E') e limpa/dedup."""
    bruto = re.split(r"[,;/]|\se\s|&", texto or "")
    vistos: set[str] = set()
    saida: list[str] = []
    for n in bruto:
        n = " ".join(n.split()).strip(" .-")
        chave = _sem_acento(n).casefold()
        if len(n) >= 3 and any(c.isalpha() for c in n) and chave not in vistos:
            vistos.add(chave)
            saida.append(n)
    return saida


def _identidade_livre(db: Session, base: str, escola_id: int) -> tuple[str, str]:
    """(username, email) AMBOS livres na rede — Usuario.username E Usuario.email
    são unique. Sufixa 2,3… até achar um par livre. Pré-checagem otimista: a
    corrida real (duas escolas, mesmo nome, nenhuma commitada) é resolvida pela
    UNIQUE do banco + retry em ``garantir_professor``."""
    base_l = base.lower()
    i = 1
    while True:
        username = base_l if i == 1 else f"{base_l}{i}"
        email = f"{username}@{_DOMINIO}"
        ocupado = db.execute(
            select(Usuario.id).where(
                (func.lower(Usuario.username) == username)
                | (func.lower(Usuario.email) == email))
        ).first()
        if ocupado is None:
            return username, email
        i += 1


def garantir_professor(db: Session, escola_id: int, nome: str) -> tuple[Professor | None, bool]:
    """Acha (por nome NORMALIZADO na escola) ou CRIA o Professor + o Usuario de
    login. Devolve (professor, criado_agora). Idempotente e à prova de corrida:
    NUNCA deixa a sessão poluída (usa SAVEPOINT) nem duplica a conta.

    O match é acento-insensível (``_chave_nome``) para casar a mesma professora
    escrita de formas diferentes entre a Lista Piloto e o Elefante."""
    nome = " ".join((nome or "").split())
    cred = credenciais_professor(nome)
    if cred is None:
        return None, False

    alvo = _chave_nome(nome)
    # Poucas dezenas de professores por escola: carregar e casar em Python é
    # barato e portável (SQL não tem unaccent garantido em SQLite/Postgres).
    for p in db.execute(
        select(Professor).where(Professor.escola_id == escola_id)
    ).scalars():
        if _chave_nome(p.nome) == alvo:
            return p, False

    user_base, senha = cred
    senha_hash = hash_senha(senha)
    # Retry: se DUAS escolas criarem o mesmo username ao mesmo tempo, a UNIQUE do
    # banco barra uma; o SAVEPOINT desfaz só ESTE professor (não o import de
    # alunos) e recalculamos o username já vendo a linha que a outra commitou.
    for _ in range(8):
        username, email = _identidade_livre(db, user_base, escola_id)
        prof = Professor(escola_id=escola_id, nome=nome, email=email)
        usuario = Usuario(escola_id=escola_id, nome=nome, email=email,
                          username=username, senha_hash=senha_hash,
                          cargo="professor", status="ativo")
        try:
            with db.begin_nested():
                db.add(prof)
                db.add(usuario)
                db.flush()
            return prof, True
        except IntegrityError:
            continue  # corrida: username/email levado por outra transação
    _log.warning("professor não criado após colisões repetidas de username")
    return None, False


def garantir_professores_da_turma(db: Session, escola_id: int, turma,
                                  professores_texto: str) -> int:
    """Cria as contas de TODOS os professores do campo e vincula o PRIMEIRO como
    titular da turma (se ela ainda não tiver). Devolve quantas contas criou agora."""
    criados = 0
    titular: Professor | None = None
    for nome in nomes_de_professores(professores_texto):
        prof, novo = garantir_professor(db, escola_id, nome)
        if prof is None:
            continue
        criados += int(novo)
        if titular is None:
            titular = prof
    if titular is not None and turma is not None \
            and getattr(turma, "professor_id", None) is None:
        turma.professor_id = titular.id
    return criados
