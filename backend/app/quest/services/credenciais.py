"""Login infantil: código falável e sessão do aluno.

Decisão de produto (09/07/2026): SEM senha/PIN — o código É a credencial,
como no Elefante Letrado. Só letras e números (nada de hífen ou símbolo):

    SOL314              código curto e falável (digitável em teclado grande)
    [QR]                mesma credencial em forma de figura — 1 leitura = entrou

A defesa contra abuso é o limitador de tentativas PERSISTENTE (por código,
código+IP e IP — app/quest/services/limites.py) e o fato de o papel "aluno" só
alcançar o próprio perfil de jogo. O JWT do aluno carrega papel="aluno" e NUNCA
é aceito pelas rotas do Edu — e vice-versa.

Código em repouso (0037): o login procura pelo HMAC do código (``hash_codigo``),
nunca pelo texto. HMAC com chave do SERVIDOR, e não bcrypt: sem usuário, o login
precisa achar a linha pelo próprio código (busca determinística por índice); e,
com ~2^17 códigos possíveis, nenhum hash lento resistiria a quem tem o banco — o
que protege é a chave ficar FORA do banco. Quem tem só o banco (dump, backup,
réplica) não tira o código do hash; quem tem banco E chave tira, qualquer que
seja o hash (limite do formato curto, decisão de produto).

O QR é a MESMA credencial em outra forma: o /entrar-qr procura pelo
``hash_qr`` (SHA-256 do token), nunca pelo texto. Enquanto as colunas em texto
(``codigo_login`` e ``qr_token``) existirem, o ganho em repouso não se realiza:
um dump ainda traz as duas — a remoção (docs/lgpd/RETENCAO-TECNICA.md) vale para
ambas.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import segredos_da_cifra
from app.models import Aluno, LogAuditoria, Matricula, Turma
from app.quest.models import QuestCredencialAluno
from app.quest.services import perfis

logger = logging.getLogger("constela.quest")

# TRANSIÇÃO (0037): enquanto as colunas em texto (``codigo_login``, ``qr_token``)
# existirem, o TEXTO é a verdade e o hash é o índice:
#   * busca que não acha pelo hash tenta o texto e CORRIGE o hash da linha —
#     linha gravada sem hash (restauração de backup anterior à 0037, processo
#     antigo durante o deploy) e hash feito com outra chave (migração rodada
#     noutro processo);
#   * busca que acha pelo hash confere também o texto: o processo antigo, no
#     deploy, gira o código/QR só no texto e deixa o hash do ANTIGO — sem esta
#     conferência, o cartão girado (perdido, vazado) continuaria entrando.
# Sai JUNTO com as colunas — passo documentado em docs/lgpd/RETENCAO-TECNICA.md;
# antes de tirar, ``contar_hashes_divergentes`` tem de dar 0.
_FALLBACK_TEXTO_CLARO = True

# Separação de domínio: a mesma chave do servidor gera chaves HMAC diferentes
# para cada uso (o hash do código não serve como chave de nada mais).
_DOMINIO_HASH_CODIGO = "quest-codigo-login"
_DOMINIO_HASH_QR = "quest-qr-token"


def _segredos_hmac() -> list[str]:
    """Segredos na ordem de uso — o MESMO anel da cifra em repouso
    (``app.core.security.segredos_da_cifra``): o 1º GRAVA; todos CONFEREM. Com
    ``DATA_ENCRYPTION_KEY`` definida ela é a primária (a SECRET_KEY, que assina os
    JWT, fica só para conferir hashes antigos) — definir a chave dedicada não
    invalida nenhum cartão. Na rotação planejada entram as ANTERIORES
    (``DATA_ENCRYPTION_KEYS_ANTERIORES`` e ``CHAVE_CIFRA_LEGADA_ANTERIOR``): o hash
    feito com uma delas é LOCALIZADO pelo índice e regravado na primária no login
    (``buscar_por_codigo``) ou em lote (``preencher_hashes_ausentes``) — é o que
    deixa girar a chave depois que o fallback de texto sair."""
    return segredos_da_cifra()


def _chave_hmac(segredo: str) -> bytes:
    return hashlib.sha256(f"{segredo}|{_DOMINIO_HASH_CODIGO}".encode()).digest()


def hash_codigo(codigo: str, *, segredo: str | None = None) -> str:
    """HMAC-SHA256 (hex, 64) do código NORMALIZADO — o que vai para
    ``codigo_login_hash``. ``segredo`` só para conferir com chave antiga."""
    chave = _chave_hmac(segredo if segredo is not None else _segredos_hmac()[0])
    return hmac.new(chave, normalizar_codigo(codigo).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def hashes_candidatos(codigo: str) -> list[str]:
    """O hash do código em cada chave aceita (a primária primeiro)."""
    return [hash_codigo(codigo, segredo=s) for s in _segredos_hmac()]


def definir_codigo(credencial: QuestCredencialAluno, codigo: str) -> None:
    """ÚNICO ponto que grava o código: texto (transição, para exibir) e hash
    (para autenticar) andam sempre juntos."""
    normalizado = normalizar_codigo(codigo)
    credencial.codigo_login = normalizado
    credencial.codigo_login_hash = hash_codigo(normalizado)


def hash_qr(token: str) -> str:
    """SHA-256 (hex, 64) do token do QR — o que vai para ``qr_token_hash``.

    Sem chave, ao contrário do código: o token tem ~192 bits (``gerar_qr_token``),
    então ninguém o recupera do hash por tentativa, com ou sem o banco; uma chave
    só acrescentaria o modo de falha "chave trocada invalida todo QR impresso"."""
    return hashlib.sha256(f"{_DOMINIO_HASH_QR}|{(token or '').strip()}"
                          .encode("utf-8")).hexdigest()


def definir_qr_token(credencial: QuestCredencialAluno, token: str) -> None:
    """ÚNICO ponto que grava o QR: texto (transição, para a URL do cartão) e hash
    (para autenticar) andam sempre juntos."""
    credencial.qr_token = token
    credencial.qr_token_hash = hash_qr(token)


def codigo_para_exibicao(credencial: QuestCredencialAluno) -> str:
    """O código como o cartão/professor o mostram. ÚNICO ponto de leitura do
    texto: na remoção da coluna, é aqui que entra a decisão do dono (ver
    docs/lgpd/RETENCAO-TECNICA.md — regenerar ao imprimir × cópia cifrada)."""
    return credencial.codigo_login or ""

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
        # Unicidade pelo hash (o que o login consulta) e, na transição, também
        # pelo texto — a coluna antiga ainda é UNIQUE.
        existe = db.execute(
            select(QuestCredencialAluno.id)
            .where(or_(QuestCredencialAluno.codigo_login == codigo,
                       QuestCredencialAluno.codigo_login_hash.in_(
                           hashes_candidatos(codigo))))
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
                cred = QuestCredencialAluno(escola_id=escola_id, aluno_id=aluno.id)
                definir_qr_token(cred, gerar_qr_token())
                definir_codigo(cred, gerar_codigo_login(db))
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


def revogar_cartao(db: Session, credencial: QuestCredencialAluno) -> None:
    """Revoga o cartão INTEIRO: código novo, QR novo e ``token_version`` + 1.

    O cartão impresso traz o QR e o código, e quem abre uma sessão pelo QR lê o
    código no GET /quest/perfil: revogar só o QR deixava o código do mesmo cartão
    abrindo sessão nova. Os dois saem por ``definir_codigo`` e
    ``definir_qr_token``, que gravam texto e hash juntos — o antigo não casa pelo
    hash nem pelo texto do fallback (``_FALLBACK_TEXTO_CLARO``). O
    ``token_version`` derruba toda sessão do aluno emitida antes, por código ou
    por QR. O código novo nunca repete o atual (``gerar_codigo_login`` recusa
    código que já está no banco)."""
    definir_codigo(credencial, gerar_codigo_login(db))
    definir_qr_token(credencial, gerar_qr_token())
    credencial.token_version = (credencial.token_version or 0) + 1


def credencial_do_aluno(db: Session, aluno_id: int) -> QuestCredencialAluno | None:
    """A credencial do aluno (``aluno_id`` é UNIQUE), ou ``None`` se nunca teve cartão."""
    return db.execute(
        select(QuestCredencialAluno)
        .where(QuestCredencialAluno.aluno_id == aluno_id)
    ).scalar_one_or_none()


def credenciais_inativas_da_turma(db: Session, escola_id: int,
                                  turma: Turma) -> list[QuestCredencialAluno]:
    """Credenciais dos matriculados na turma que NÃO estão ativos (arquivado,
    transferido, fora_lista_piloto...) — a mesma junção de ``alunos_da_turma``,
    com o status ao contrário. Ficam fora do PDF; só a revogação as alcança."""
    inativos = (
        select(Aluno.id)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .where(Matricula.turma_id == turma.id,
               Matricula.escola_id == escola_id,
               or_(Aluno.status.is_(None), Aluno.status != "ativo"))
    )
    return list(db.execute(
        select(QuestCredencialAluno)
        .where(QuestCredencialAluno.aluno_id.in_(inativos))
        .order_by(QuestCredencialAluno.id)
    ).scalars().all())


def revogar_cartoes_inativos_da_turma(db: Session, escola_id: int, turma: Turma) -> int:
    """Revoga (``revogar_cartao``) o cartão de cada inativo da turma que já tem
    credencial; devolve quantos. Sem cartão novo nem perfil: a ficha inativa não
    recebe cartão. É o que o regenerar da TURMA faz com quem está inativo naquela
    hora — o cartão dele também foi impresso (e pode estar na folha perdida); sem
    isto, a ficha reativada depois (botão Reativar ou a Lista Piloto seguinte)
    voltava a entrar com o código, o QR e as sessões de antes da revogação.

    Sem revogação pedida, nada muda: a criança que volta segue com o mesmo cartão
    ("cartão descansando")."""
    credenciais = credenciais_inativas_da_turma(db, escola_id, turma)
    for credencial in credenciais:
        revogar_cartao(db, credencial)
        db.flush()   # sessão sem autoflush: o próximo sorteio já vê este código
    return len(credenciais)


# Auditoria de cada folha da turma impressa (POST /turmas/{id}/cartoes). Além de
# registro, é a memória de QUEM esteve na folha: a matrícula é reescrita sem
# histórico quando a criança troca de turma (Lista Piloto, troca manual).
ACAO_FOLHA_DA_TURMA = "quest.cartoes_gerados"


def aluno_ids_da_folha(dados: list[dict]) -> list[int]:
    """Os ``aluno_id`` impressos no PDF da turma, para os detalhes da auditoria
    da folha. Só ids: nenhum nome, código ou QR."""
    return [item["aluno"].id for item in dados]


def _impressos_desde_a_ultima_revogacao(db: Session, escola_id: int,
                                        turma: Turma) -> set[int]:
    """Os ``aluno_id`` das folhas da turma impressas desde a última revogação
    dela, INCLUSIVE a folha dessa revogação (que saiu com os cartões novos, ainda
    válidos). As folhas de antes caíram naquela revogação.

    A folha registrada antes deste campo não traz ``aluno_ids``: dela não há como
    saber quem estava impresso."""
    impressos: set[int] = set()
    registros = db.execute(
        select(LogAuditoria.detalhes)
        .where(LogAuditoria.acao == ACAO_FOLHA_DA_TURMA,
               LogAuditoria.escola_id == escola_id,
               LogAuditoria.entidade == "turma",
               LogAuditoria.entidade_id == turma.id)
        .order_by(LogAuditoria.id.desc())
    ).scalars().all()
    for detalhes in registros:
        detalhes = detalhes if isinstance(detalhes, dict) else {}
        ids = detalhes.get("aluno_ids")
        if isinstance(ids, list):
            impressos.update(i for i in ids if isinstance(i, int))
        if detalhes.get("rotacionou_codigo"):
            break
    return impressos


def revogar_cartoes_que_sairam_da_turma(db: Session, escola_id: int,
                                        turma: Turma) -> list[int]:
    """Revoga (``revogar_cartao``) o cartão de quem estava numa folha da turma
    impressa desde a última revogação dela e NÃO está mais matriculado nela
    (trocou de turma pela Lista Piloto ou pela troca manual); devolve os
    ``aluno_id`` revogados, em ordem.

    O regenerar da turma alcança os matriculados daquela hora (ativos no PDF,
    inativos por ``revogar_cartoes_inativos_da_turma``). Quem saiu da turma depois
    da impressão seguia com o cartão da folha — com a ficha ativa, entrando na
    hora. É a resposta à folha perdida: todo cartão impresso nela cai, como já
    caía o de quem ficou (mesmo que tenha ganhado cartão individual depois).

    Sem cartão novo nem PDF aqui: a criança ganha o cartão na turma em que está
    agora (a reimpressão de lá já sai com o código novo)."""
    impressos = _impressos_desde_a_ultima_revogacao(db, escola_id, turma)
    if not impressos:
        return []
    na_turma = set(db.execute(
        select(Matricula.aluno_id)
        .where(Matricula.turma_id == turma.id, Matricula.escola_id == escola_id)
    ).scalars().all())
    sairam = impressos - na_turma
    if not sairam:
        return []
    revogados: list[int] = []
    for credencial in db.execute(
        select(QuestCredencialAluno)
        .where(QuestCredencialAluno.aluno_id.in_(sorted(sairam)),
               QuestCredencialAluno.escola_id == escola_id)
        .order_by(QuestCredencialAluno.aluno_id)
    ).scalars().all():
        revogar_cartao(db, credencial)
        db.flush()   # sessão sem autoflush: o próximo sorteio já vê este código
        revogados.append(credencial.aluno_id)
    return revogados


def garantir_credencial_aluno(
    db: Session, escola_id: int, aluno: Aluno, regenerar: bool = False,
    rotacionar_codigo: bool = False,
) -> dict:
    """Garante credencial + perfil de UM aluno.

    - Aluno novo: ganha código, QR e perfil.
    - Sem parâmetro: reimpressão — código e QR continuam os mesmos.
    - `regenerar`: revoga o cartão (``revogar_cartao``): código e QR novos e
      as sessões antigas caem. É a resposta a cartão perdido, roubado ou com o
      QR vazado — o código impresso no mesmo cartão também deixa de entrar.
    - `rotacionar_codigo`: o mesmo efeito (nome mantido por compatibilidade;
      virada de ano letivo, suspeita de vazamento). NÃO há expiração automática
      durante o ano (a criança não perde acesso sozinha).
    """
    credencial = credencial_do_aluno(db, aluno.id)

    if credencial is None:
        credencial = _inserir_credencial_nova(db, escola_id, aluno)
    elif regenerar or rotacionar_codigo:
        revogar_cartao(db, credencial)

    perfil = perfis.obter_ou_criar_perfil(db, aluno)
    db.flush()
    return {"aluno": aluno, "credencial": credencial, "perfil": perfil}


def garantir_credenciais_turma(
    db: Session, escola_id: int, turma: Turma, regenerar: bool = False,
    rotacionar_codigo: bool = False,
) -> list[dict]:
    """Credencial + perfil para cada aluno ativo da turma (dados do PDF). Os
    inativos ficam de fora; na revogação da turma, o cartão deles cai por
    ``revogar_cartoes_inativos_da_turma`` (o router chama os dois)."""
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
    """Acha a credencial pelo HMAC do código digitado.

    O banco casa o hash por índice — e o que ele compara é um HMAC, não o código:
    o tempo da busca não diz nada sobre quantas letras o palpite acertou. Na
    volta, a igualdade é refeita em tempo constante (``hmac.compare_digest``).
    Hash feito com a chave SECUNDÁRIA é regravado na primária (rotação gradual).
    Na transição, o hash que casa mas não confere com o texto está desatualizado
    (ver ``_FALLBACK_TEXTO_CLARO``): é refeito a partir do texto e não autentica.
    """
    normalizado = normalizar_codigo(codigo)
    if not normalizado:
        return None
    candidatos = hashes_candidatos(normalizado)
    credencial = db.execute(
        select(QuestCredencialAluno)
        .where(QuestCredencialAluno.codigo_login_hash.in_(candidatos))
        .order_by(QuestCredencialAluno.id)
    ).scalars().first()
    if credencial is not None:
        gravado = credencial.codigo_login_hash or ""
        if not any(hmac.compare_digest(gravado, h) for h in candidatos):
            return None
        if _FALLBACK_TEXTO_CLARO and not hmac.compare_digest(
                credencial.codigo_login or "", normalizado):
            # Código girado só no texto (processo antigo): o digitado é o ANTIGO.
            logger.warning("quest: hash do código desatualizado na credencial %s "
                           "— refeito a partir do texto.", credencial.id)
            credencial.codigo_login_hash = hash_codigo(credencial.codigo_login or "")
            # Já no banco: se o texto achar outra linha logo abaixo, ela recebe
            # este mesmo hash antigo — e o índice é único.
            db.flush()
        else:
            if not hmac.compare_digest(gravado, candidatos[0]):
                credencial.codigo_login_hash = candidatos[0]
            return credencial
    if not _FALLBACK_TEXTO_CLARO:
        return None
    credencial = db.execute(
        select(QuestCredencialAluno)
        .where(QuestCredencialAluno.codigo_login == normalizado)
    ).scalar_one_or_none()
    if credencial is None or not hmac.compare_digest(
            credencial.codigo_login or "", normalizado):
        return None
    # Linha sem hash ou com hash de outra chave: corrige (o commit é do login).
    logger.warning("quest: hash do código ausente ou de outra chave na "
                   "credencial %s — corrigido no acesso.", credencial.id)
    credencial.codigo_login_hash = candidatos[0]
    return credencial


def preencher_hashes_ausentes(db: Session) -> int:
    """Preenche/corrige o hash do código (chave primária) e o do QR de toda
    credencial em que não conferem com o texto, enquanto as colunas existirem —
    inclusive o hash DESATUALIZADO deixado pelo processo antigo no deploy.
    Idempotente; não commita. Devolve quantas linhas mudaram."""
    mudou = 0
    for credencial in db.execute(select(QuestCredencialAluno)).scalars():
        esperado = hash_codigo(credencial.codigo_login or "")
        esperado_qr = hash_qr(credencial.qr_token or "")
        alterou = False
        if not hmac.compare_digest(credencial.codigo_login_hash or "", esperado):
            credencial.codigo_login_hash = esperado
            alterou = True
        if not hmac.compare_digest(credencial.qr_token_hash or "", esperado_qr):
            credencial.qr_token_hash = esperado_qr
            alterou = True
        mudou += alterou
    return mudou


def contar_hashes_divergentes(db: Session) -> int:
    """Quantas credenciais NÃO autenticariam (por código ou por QR) sem o
    fallback de texto — a conferência obrigatória antes de remover as colunas
    ``codigo_login`` e ``qr_token``."""
    return sum(
        1 for credencial in db.execute(select(QuestCredencialAluno)).scalars()
        if not any(hmac.compare_digest(credencial.codigo_login_hash or "", h)
                   for h in hashes_candidatos(credencial.codigo_login or ""))
        or not hmac.compare_digest(credencial.qr_token_hash or "",
                                   hash_qr(credencial.qr_token or "")))


def _mesmo_token(gravado: str | None, recebido: str) -> bool:
    # Em bytes: o qr_token vem do cliente (qualquer texto de 8 a 64 caracteres) e
    # compare_digest recusa str com caractere fora do ASCII (TypeError → 500).
    return hmac.compare_digest((gravado or "").encode("utf-8"), recebido.encode("utf-8"))


def buscar_por_qr(db: Session, qr_token: str) -> QuestCredencialAluno | None:
    """Acha a credencial pelo hash do token do QR — mesmo desenho e mesma
    transição de ``buscar_por_codigo`` (texto confere o hash; linha sem hash
    entra pelo texto e sai corrigida)."""
    token = (qr_token or "").strip()
    if not token:
        return None
    esperado = hash_qr(token)
    credencial = db.execute(
        select(QuestCredencialAluno)
        .where(QuestCredencialAluno.qr_token_hash == esperado)
    ).scalar_one_or_none()
    if credencial is not None:
        if not hmac.compare_digest(credencial.qr_token_hash or "", esperado):
            return None
        if not _FALLBACK_TEXTO_CLARO or _mesmo_token(credencial.qr_token, token):
            return credencial
        # QR trocado só no texto (processo antigo): o apresentado é o ANTIGO.
        logger.warning("quest: hash do QR desatualizado na credencial %s — "
                       "refeito a partir do texto.", credencial.id)
        credencial.qr_token_hash = hash_qr(credencial.qr_token or "")
        db.flush()   # índice único: o texto abaixo pode achar outra linha
    if not _FALLBACK_TEXTO_CLARO:
        return None
    credencial = db.execute(
        select(QuestCredencialAluno)
        .where(QuestCredencialAluno.qr_token == token)
    ).scalar_one_or_none()
    if credencial is None or not _mesmo_token(credencial.qr_token, token):
        return None
    logger.warning("quest: hash do QR ausente na credencial %s — corrigido no "
                   "acesso.", credencial.id)
    credencial.qr_token_hash = esperado
    return credencial


def url_qr(credencial: QuestCredencialAluno) -> str:
    """URL embutida no QR do cartão — abre o app já autenticando. ÚNICO ponto de
    leitura do ``qr_token`` em texto: na remoção da coluna, a decisão do dono vale
    aqui também (regenerar ao imprimir × cópia cifrada)."""
    return f"{settings.QUEST_BASE_URL.rstrip('/')}/entrar?qr={credencial.qr_token}"
