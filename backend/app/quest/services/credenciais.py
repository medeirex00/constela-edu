"""Login infantil: código falável e sessão do aluno.

Decisão de produto (09/07/2026): SEM senha/PIN — o código É a credencial,
como no Elefante Letrado. Só letras e números (nada de hífen ou símbolo):

    SOL1234             código curto e falável (digitável em teclado grande)
    [QR]                mesma credencial em forma de figura — 1 leitura = entrou

A defesa contra abuso é o limitador de tentativas (por código+IP) e o fato
de o papel "aluno" só alcançar o próprio perfil de jogo. O JWT do aluno
carrega papel="aluno" e NUNCA é aceito pelas rotas do Edu — e vice-versa.
"""
from __future__ import annotations

import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Aluno, Matricula, Turma
from app.quest.models import QuestCredencialAluno
from app.quest.services import perfis

# Palavras do código: curtas, faláveis por telefone e SEM acento na grafia
# correta (a criança que escreve certo nunca pode ser punida — nada de CEU,
# VENUS ou TROVAO, que se escrevem com acento no português da escola).
_PALAVRAS_CODIGO = (
    "SOL", "LUA", "MAR", "RIO", "FLOR", "NUVEM", "TERRA", "MARTE",
    "COMETA", "NOVA", "AURORA", "VEGA", "LUZ", "RAIO", "VENTO", "BRISA",
    "ONDA", "ILHA", "FAROL", "PONTE", "TRILHA", "BOSQUE", "CAMPO", "PINGO",
    "ESTRELA", "FOGUETE", "PLANETA", "SATURNO",
)


def gerar_codigo_login(db: Session) -> str:
    """PALAVRA+NNNN (ex.: SOL1234) único na rede toda — só letras e números."""
    for _ in range(200):
        codigo = (f"{secrets.choice(_PALAVRAS_CODIGO)}"
                  f"{secrets.randbelow(9000) + 1000}")
        existe = db.execute(
            select(QuestCredencialAluno.id)
            .where(QuestCredencialAluno.codigo_login == codigo)
        ).first()
        if existe is None:
            return codigo
    raise RuntimeError("Não foi possível gerar um código de login único.")


def gerar_qr_token() -> str:
    return secrets.token_urlsafe(24)


def normalizar_codigo(codigo: str) -> str:
    """Tolerante ao que uma criança digita: minúsculas, espaços, hífens,
    acentos ("sól 12 34" → "SOL1234"). Só sobram letras A–Z e dígitos."""
    sem_acento = unicodedata.normalize("NFD", codigo or "")
    sem_acento = "".join(c for c in sem_acento
                         if unicodedata.category(c) != "Mn")
    return "".join(c for c in sem_acento.upper()
                   if c.isascii() and c.isalnum())


# ---------------------------------------------------------------------------
# Geração por turma (fluxo do professor)
# ---------------------------------------------------------------------------

def alunos_da_turma(db: Session, escola_id: int, turma: Turma) -> list[Aluno]:
    linhas = db.execute(
        select(Aluno)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .where(Matricula.turma_id == turma.id,
               Matricula.escola_id == escola_id,
               Aluno.status == "ativo")
        .order_by(Aluno.nome)
    ).scalars().all()
    return list(linhas)


def garantir_credencial_aluno(
    db: Session, escola_id: int, aluno: Aluno, regenerar: bool = False,
) -> dict:
    """Garante credencial + perfil de UM aluno.

    - Aluno novo: ganha código, QR e perfil.
    - `regenerar`: mantém o CÓDIGO (a criança decora), troca o QR e
      incrementa token_version (cartão perdido → sessões antigas caem).
    """
    credencial = db.execute(
        select(QuestCredencialAluno)
        .where(QuestCredencialAluno.aluno_id == aluno.id)
    ).scalar_one_or_none()

    if credencial is None:
        credencial = QuestCredencialAluno(
            escola_id=escola_id,
            aluno_id=aluno.id,
            codigo_login=gerar_codigo_login(db),
            qr_token=gerar_qr_token(),
        )
        db.add(credencial)
    elif regenerar:
        credencial.qr_token = gerar_qr_token()
        credencial.token_version = (credencial.token_version or 0) + 1

    perfil = perfis.obter_ou_criar_perfil(db, aluno)
    db.flush()
    return {"aluno": aluno, "credencial": credencial, "perfil": perfil}


def garantir_credenciais_turma(
    db: Session, escola_id: int, turma: Turma, regenerar: bool = False,
) -> list[dict]:
    """Credencial + perfil para cada aluno ativo da turma (dados do PDF)."""
    return [garantir_credencial_aluno(db, escola_id, aluno, regenerar)
            for aluno in alunos_da_turma(db, escola_id, turma)]


# ---------------------------------------------------------------------------
# Sessão do aluno (JWT papel="aluno")
# ---------------------------------------------------------------------------

def criar_token_aluno(credencial: QuestCredencialAluno) -> str:
    agora = datetime.now(timezone.utc)
    expira = agora + timedelta(days=settings.QUEST_SESSAO_DIAS)
    payload = {
        "sub": str(credencial.id),
        "papel": "aluno",              # rotas do Edu rejeitam este claim
        "ver": credencial.token_version or 0,
        "iat": agora,
        "exp": expira,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def buscar_por_codigo(db: Session, codigo: str) -> QuestCredencialAluno | None:
    return db.execute(
        select(QuestCredencialAluno)
        .where(QuestCredencialAluno.codigo_login == normalizar_codigo(codigo))
    ).scalar_one_or_none()


def buscar_por_qr(db: Session, qr_token: str) -> QuestCredencialAluno | None:
    if not qr_token:
        return None
    return db.execute(
        select(QuestCredencialAluno)
        .where(QuestCredencialAluno.qr_token == qr_token.strip())
    ).scalar_one_or_none()


def url_qr(credencial: QuestCredencialAluno) -> str:
    """URL embutida no QR do cartão — abre o app já autenticando."""
    return f"{settings.QUEST_BASE_URL.rstrip('/')}/entrar?qr={credencial.qr_token}"
