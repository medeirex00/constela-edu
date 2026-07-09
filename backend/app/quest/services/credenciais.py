"""Login infantil: credenciais faláveis, PIN de figuras e sessão do aluno.

Criança de 6 anos não tem e-mail nem decora senha (docs/quest/04). O cartão
de acesso impresso carrega três coisas:

    SOL-1234            código curto e falável (digitável em teclado grande)
    🦊 🌙 ⭐ 🍎          PIN: 4 figuras em ordem
    [QR]                token de alta entropia — 1 leitura = entrou

O JWT do aluno carrega papel="aluno" e NUNCA é aceito pelas rotas do Edu
(get_usuario_atual rejeita tokens com papel) — e vice-versa.
"""
from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Aluno, Matricula, Turma
from app.quest.models import QuestCredencialAluno
from app.quest.services import perfis

# ---------------------------------------------------------------------------
# Catálogos do cartão
# ---------------------------------------------------------------------------

# Figuras do PIN: nomes que criança de 6 anos reconhece de ouvido, emojis
# consistentes entre plataformas e visualmente inconfundíveis entre si.
FIGURAS_PIN: list[dict] = [
    {"slug": "sol", "nome": "Sol", "emoji": "☀️"},
    {"slug": "lua", "nome": "Lua", "emoji": "🌙"},
    {"slug": "estrela", "nome": "Estrela", "emoji": "⭐"},
    {"slug": "foguete", "nome": "Foguete", "emoji": "🚀"},
    {"slug": "raposa", "nome": "Raposa", "emoji": "🦊"},
    {"slug": "gato", "nome": "Gato", "emoji": "🐱"},
    {"slug": "peixe", "nome": "Peixe", "emoji": "🐟"},
    {"slug": "borboleta", "nome": "Borboleta", "emoji": "🦋"},
    {"slug": "maca", "nome": "Maçã", "emoji": "🍎"},
    {"slug": "bola", "nome": "Bola", "emoji": "⚽"},
    {"slug": "arvore", "nome": "Árvore", "emoji": "🌳"},
    {"slug": "arcoiris", "nome": "Arco-íris", "emoji": "🌈"},
]
_SLUGS_FIGURAS = {f["slug"] for f in FIGURAS_PIN}

# Palavras do código de login: curtas, sem acento, faláveis por telefone e
# fáceis de digitar num teclado infantil. Tema: céu/natureza (universo Constela).
_PALAVRAS_CODIGO = (
    "SOL", "LUA", "CEU", "MAR", "RIO", "FLOR", "NUVEM", "TERRA",
    "MARTE", "VENUS", "COMETA", "ORION", "NOVA", "AURORA", "VEGA",
    "LUZ", "RAIO", "TROVAO", "VENTO", "BRISA", "ONDA", "ILHA",
    "PINGO", "FAROL", "PONTE", "TRILHA", "BOSQUE", "CAMPO",
)


def gerar_codigo_login(db: Session) -> str:
    """PALAVRA-NNNN único na rede toda (o aluno pode falar por telefone)."""
    for _ in range(200):
        codigo = (f"{secrets.choice(_PALAVRAS_CODIGO)}-"
                  f"{secrets.randbelow(9000) + 1000}")
        existe = db.execute(
            select(QuestCredencialAluno.id)
            .where(QuestCredencialAluno.codigo_login == codigo)
        ).first()
        if existe is None:
            return codigo
    raise RuntimeError("Não foi possível gerar um código de login único.")


def gerar_pin() -> list[str]:
    """4 figuras distintas, em ordem (a ordem faz parte do segredo)."""
    figuras = [f["slug"] for f in FIGURAS_PIN]
    pin: list[str] = []
    for _ in range(4):
        escolhida = secrets.choice(figuras)
        pin.append(escolhida)
        figuras.remove(escolhida)
    return pin


def gerar_qr_token() -> str:
    return secrets.token_urlsafe(24)


def pin_confere(credencial: QuestCredencialAluno, pin: list[str]) -> bool:
    """Comparação em tempo constante da sequência de figuras."""
    if not isinstance(pin, list) or len(pin) != 4:
        return False
    dado = ",".join(str(p).strip().lower() for p in pin)
    esperado = ",".join(credencial.pin_figuras or [])
    return hmac.compare_digest(dado.encode(), esperado.encode())


def normalizar_codigo(codigo: str) -> str:
    """Tolerante ao que uma criança digita: espaços, minúsculas, sem hífen."""
    limpo = "".join(c for c in codigo.upper().strip() if c.isalnum())
    # Reinsere o hífen entre letras e números ("SOL1234" → "SOL-1234")
    for i, ch in enumerate(limpo):
        if ch.isdigit():
            return f"{limpo[:i]}-{limpo[i:]}"
    return limpo


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


def garantir_credenciais_turma(
    db: Session, escola_id: int, turma: Turma, regenerar: bool = False,
) -> list[dict]:
    """Garante credencial + perfil para cada aluno ativo da turma.

    - Aluno novo: ganha código, PIN, QR e perfil.
    - `regenerar`: mantém o CÓDIGO (a criança decora), troca PIN + QR e
      incrementa token_version (cartão perdido → sessões antigas caem).
    Devolve os dados prontos para o PDF dos cartões.
    """
    resultado: list[dict] = []
    for aluno in alunos_da_turma(db, escola_id, turma):
        credencial = db.execute(
            select(QuestCredencialAluno)
            .where(QuestCredencialAluno.aluno_id == aluno.id)
        ).scalar_one_or_none()

        if credencial is None:
            credencial = QuestCredencialAluno(
                escola_id=escola_id,
                aluno_id=aluno.id,
                codigo_login=gerar_codigo_login(db),
                pin_figuras=gerar_pin(),
                qr_token=gerar_qr_token(),
            )
            db.add(credencial)
        elif regenerar:
            credencial.pin_figuras = gerar_pin()
            credencial.qr_token = gerar_qr_token()
            credencial.token_version = (credencial.token_version or 0) + 1

        perfil = perfis.obter_ou_criar_perfil(db, aluno)
        db.flush()
        resultado.append({
            "aluno": aluno,
            "credencial": credencial,
            "perfil": perfil,
        })
    return resultado


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
