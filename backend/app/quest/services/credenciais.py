"""Login infantil: código falável e sessão do aluno.

Decisão de produto (09/07/2026): SEM senha/PIN — o código É a credencial,
como no Elefante Letrado. Só letras e números (nada de hífen ou símbolo):

    SOL314              código curto e falável (digitável em teclado grande)
    [QR]                mesma credencial em forma de figura — 1 leitura = entrou

A defesa contra abuso é o limitador de tentativas (por código+IP) e o fato
de o papel "aluno" só alcançar o próprio perfil de jogo. O JWT do aluno
carrega papel="aluno" e NUNCA é aceito pelas rotas do Edu — e vice-versa.
"""
from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Aluno, Matricula, Turma
from app.quest.models import QuestCredencialAluno
from app.quest.services import perfis

# Palavras do código: curtas (3–8 letras), faláveis e SEM acento na grafia
# correta (a criança que escreve certo nunca pode ser punida — nada de CEU,
# VENUS ou TROVAO, que se escrevem com acento). Uma palavra + 3 dígitos é o
# formato atual (ver gerar_codigo_login); cabe folgado em codigo_login String(20).
_PALAVRAS_CODIGO = (
    # Céu e espaço
    "SOL", "LUA", "MARTE", "COMETA", "PLANETA", "ESTRELA", "FOGUETE", "NOVA",
    "AURORA", "VEGA", "NEBULOSA", "ASTRO", "ECLIPSE", "SATURNO", "NETUNO",
    "URANO", "LUZ", "RAIO", "METEORO", "COSMOS",
    # Natureza e geografia
    "MAR", "RIO", "FLOR", "NUVEM", "TERRA", "VENTO", "BRISA", "ONDA", "ILHA",
    "FAROL", "PONTE", "TRILHA", "BOSQUE", "CAMPO", "PINGO", "CHUVA", "NEVE",
    "GELO", "FOGO", "PEDRA", "AREIA", "DUNA", "MONTE", "VALE", "LAGO", "FONTE",
    "RAIZ", "FOLHA", "GALHO", "TRONCO", "SEMENTE", "BROTO", "JARDIM", "POMAR",
    "MATA", "SELVA", "DESERTO", "RIACHO", "SERRA", "PRAIA", "NEBLINA", "ORVALHO",
    "CRISTAL", "GRUTA", "CAVERNA",
    # Animais
    "GATO", "LOBO", "RAPOSA", "URSO", "TIGRE", "ZEBRA", "GIRAFA", "MACACO",
    "COELHO", "GOLFINHO", "BALEIA", "PEIXE", "POLVO", "CAVALO", "POTRO", "TOURO",
    "VACA", "OVELHA", "CABRA", "PORCO", "GALO", "PATO", "GANSO", "PERU", "POMBO",
    "CORUJA", "TUCANO", "ARARA", "PAPAGAIO", "ABELHA", "FORMIGA", "GRILO",
    "VAGALUME", "MINHOCA", "CARACOL", "ARANHA", "SAPO", "LAGARTO", "COBRA",
    "VEADO", "TATU", "LONTRA", "CASTOR", "MORCEGO", "ESQUILO", "PANDA", "CAMELO",
    "RENA", "ALCE", "FOCA", "PINGUIM", "GAIVOTA", "PARDAL", "JOANINHA",
    # Objetos e figuras
    "BOLA", "PIPA", "LIVRO", "CANETA", "PINCEL", "TINTA", "TAMBOR", "FLAUTA",
    "SINO", "CHAVE", "TORRE", "CASTELO", "BARCO", "VELA", "REMO", "TREM",
    "TRILHO", "RODA", "MOTOR", "FADA", "DUENDE", "MAGO", "ANJO", "CORAL",
    "PRATA", "OURO", "JADE", "BAMBU",
)

# Conjunto para o formatador de exibição reconhecer as palavras (split rápido).
_CONJ_PALAVRAS = frozenset(_PALAVRAS_CODIGO)


def gerar_codigo_login(db: Session) -> str:
    """PALAVRA+NNN, curto e falável (ex.: SOL314), TUDO JUNTO no cartão. Uma
    palavra + 3 dígitos por CSPRNG (secrets). Decisão de PRODUTO — facilitar a
    digitação da criança — que troca entropia por facilidade: espaço ~147×900 ≈
    1,3×10^5 (~2^17). A defesa principal contra adivinhação passa a ser o
    limitador de tentativas por código+IP (quest/routers/auth.py). Cabe folgado
    em String(20); cartões ANTIGOS de 2 palavras + 4 dígitos seguem válidos (sem
    migração). Unicidade: coluna (unique) + esta verificação — como o espaço é
    ~132 mil, revisar o formato se a rede passar de dezenas de milhares de alunos."""
    for _ in range(200):
        palavra = secrets.choice(_PALAVRAS_CODIGO)
        codigo = f"{palavra}{secrets.randbelow(900) + 100}"   # NNN: 100–999
        existe = db.execute(
            select(QuestCredencialAluno.id)
            .where(QuestCredencialAluno.codigo_login == codigo)
        ).first()
        if existe is None:
            return codigo
    raise RuntimeError("Não foi possível gerar um código de login único.")


def formatar_codigo_exibicao(codigo: str) -> str:
    """Para o CARTÃO da criança. O formato ATUAL (uma palavra + 3 dígitos, ex.:
    SOL314) sai TUDO JUNTO — o normalizado já é a forma de exibição, sem traço.
    Cartões ANTIGOS de duas palavras (ex.: LUAFAROL7314) continuam sendo
    hifenizados (LUA-FAROL-7314) para leitura, e qualquer valor não reconhecido
    é devolvido como está — nunca quebra a impressão dos cartões já emitidos.
    O valor ARMAZENADO/consultado é sempre o normalizado (sem traço)."""
    norm = normalizar_codigo(codigo)
    casa = re.fullmatch(r"([A-Z]+)(\d{3,4})", norm)
    if casa:
        letras, digitos = casa.group(1), casa.group(2)
        for i in range(3, len(letras) - 2):   # palavras têm ≥3 letras
            if letras[:i] in _CONJ_PALAVRAS and letras[i:] in _CONJ_PALAVRAS:
                return f"{letras[:i]}-{letras[i:]}-{digitos}"
    return norm


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


def _inserir_credencial_nova(db: Session, escola_id: int, aluno: Aluno) -> QuestCredencialAluno:
    """Insere a credencial nova com RETRY em colisão de código (TOCTOU): sob
    concorrência, dois pedidos podem sortear o MESMO código e ambos passarem pela
    verificação de unicidade; o UNIQUE barra o segundo INSERT. Em vez de estourar
    500, sorteamos outro código (savepoint isola a falha sem abortar a transação).
    Se outra transação já criou a credencial DESTE aluno (colisão de aluno_id),
    devolvemos a existente."""
    for _ in range(5):
        try:
            with db.begin_nested():
                cred = QuestCredencialAluno(
                    escola_id=escola_id, aluno_id=aluno.id,
                    codigo_login=gerar_codigo_login(db), qr_token=gerar_qr_token())
                db.add(cred)
                db.flush()
            return cred
        except IntegrityError:
            existente = db.execute(
                select(QuestCredencialAluno)
                .where(QuestCredencialAluno.aluno_id == aluno.id)
            ).scalar_one_or_none()
            if existente is not None:
                return existente          # corrida em aluno_id: usa a existente
            # colisão só de código: a próxima volta sorteia outro
    raise RuntimeError("Não foi possível criar a credencial única do aluno.")


def garantir_credencial_aluno(
    db: Session, escola_id: int, aluno: Aluno, regenerar: bool = False,
    rotacionar_codigo: bool = False,
) -> dict:
    """Garante credencial + perfil de UM aluno.

    - Aluno novo: ganha código, QR e perfil.
    - `regenerar`: mantém o CÓDIGO (a criança decora), troca o QR e
      incrementa token_version (cartão perdido → sessões antigas caem).
    - `rotacionar_codigo`: troca também o CÓDIGO (novo + QR + token_version).
      Uso deliberado: virada de ano letivo, suspeita de vazamento ou ação
      manual autorizada pela escola. NÃO há expiração automática durante o ano
      (a criança não perde acesso sozinha). `rotacionar_codigo` tem precedência
      sobre `regenerar`.
    """
    credencial = db.execute(
        select(QuestCredencialAluno)
        .where(QuestCredencialAluno.aluno_id == aluno.id)
    ).scalar_one_or_none()

    if credencial is None:
        credencial = _inserir_credencial_nova(db, escola_id, aluno)
    elif rotacionar_codigo:
        credencial.codigo_login = gerar_codigo_login(db)
        credencial.qr_token = gerar_qr_token()
        credencial.token_version = (credencial.token_version or 0) + 1
    elif regenerar:
        credencial.qr_token = gerar_qr_token()
        credencial.token_version = (credencial.token_version or 0) + 1

    perfil = perfis.obter_ou_criar_perfil(db, aluno)
    db.flush()
    return {"aluno": aluno, "credencial": credencial, "perfil": perfil}


def garantir_credenciais_turma(
    db: Session, escola_id: int, turma: Turma, regenerar: bool = False,
    rotacionar_codigo: bool = False,
) -> list[dict]:
    """Credencial + perfil para cada aluno ativo da turma (dados do PDF)."""
    return [garantir_credencial_aluno(db, escola_id, aluno, regenerar,
                                      rotacionar_codigo)
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
