"""Hash de senhas, política de senha e emissão/validação de tokens JWT."""
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# bcrypt trunca a senha em 72 bytes; recusar entradas maiores evita que dois
# valores diferentes com o mesmo prefixo de 72 bytes autentiquem um ao outro.
LIMITE_SENHA_BYTES = 72

# Lista curta de senhas notoriamente fracas recusadas na definição/troca.
SENHAS_PROIBIDAS = {
    "12345678", "123456789", "1234567890", "password", "senha123",
    "12341234", "constela", "constelaedu", "admin123", "qwertyui",
    "11111111", "00000000", "iloveyou", "abc12345",
}


def hash_senha(senha: str) -> str:
    return pwd_context.hash(senha)


def verificar_senha(senha: str, senha_hash: str) -> bool:
    try:
        return pwd_context.verify(senha, senha_hash)
    except ValueError:
        # Hash malformado no banco — trata como falha, nunca 500.
        return False


def verificar_senha_dummy() -> None:
    """Executa uma verificação bcrypt descartável para equalizar o tempo de
    resposta quando o e-mail não existe (evita enumeração por timing)."""
    pwd_context.dummy_verify()


# Palavras curtas e sem acento para senhas LEGÍVEIS (faladas por telefone
# sem confusão). TRÊS palavras distintas + 2 dígitos: 40×39×38×90 ≈ 5,3
# milhões de variações (~22 bits) — com o limitador de tentativas por conta
# no login, força bruta remota fica impraticável.
_PALAVRAS_SENHA = (
    "azul", "bosque", "brisa", "canoa", "cedro", "coral", "delta", "duna",
    "farol", "figo", "flor", "fogo", "gaita", "girassol", "ilha", "jade",
    "lago", "lima", "lousa", "lua", "mar", "menta", "monte", "neve",
    "ninho", "nuvem", "onda", "ouro", "pinho", "prata", "rio", "rocha",
    "sol", "trigo", "uva", "vale", "vento", "verde", "vila", "zebra",
)


def gerar_senha_legivel() -> str:
    import secrets

    palavras: list[str] = []
    restantes = list(_PALAVRAS_SENHA)
    for _ in range(3):
        escolhida = secrets.choice(restantes)
        palavras.append(escolhida)
        restantes.remove(escolhida)
    return f"{'-'.join(palavras)}-{secrets.randbelow(90) + 10}"


# --- Segredos simétricos do app (Fernet na SECRET_KEY) -----------------------
# Para valores que PRECISAM ser recuperados em texto para uso posterior — hoje,
# só a chave de API do assistente de IA. Quem obtém apenas o banco NÃO lê o
# segredo (a chave de cifra vem da SECRET_KEY, que fica fora do banco).
#
# NUNCA usar isto para SENHAS de login: senha é hash irreversível (bcrypt). Para
# devolver acesso a quem esqueceu a senha existe a redefinição por token
# (gerar_token_reset / hash_token) — a senha original jamais é recuperável.

def _derivar_fernet(segredo: str) -> bytes:
    import base64
    import hashlib

    # A string de derivação é mantida ("senha-visivel") por COMPATIBILIDADE:
    # segredos já cifrados em produção continuam legíveis após a refatoração.
    derivada = hashlib.sha256(f"{segredo}|senha-visivel".encode()).digest()
    return base64.urlsafe_b64encode(derivada)


def _fernet_dados():
    """Cifra/decifra os segredos em repouso (credenciais de plataforma, chave
    de IA, cookies do robô).

    Se ``DATA_ENCRYPTION_KEY`` estiver definida, ela é a chave PRIMÁRIA de cifra
    — SEPARADA da ``SECRET_KEY`` que assina os JWT. Assim um vazamento da
    SECRET_KEY sozinho não decifra os segredos de integração, e a chave de
    dados pode ser rotacionada de forma independente. A chave derivada da
    SECRET_KEY permanece como SECUNDÁRIA de DECIFRA (``MultiFernet``), para que
    tudo que já foi cifrado continue legível sem re-cifrar. Sem
    ``DATA_ENCRYPTION_KEY``, o comportamento é idêntico ao anterior."""
    from cryptography.fernet import Fernet, MultiFernet

    legado = Fernet(_derivar_fernet(settings.SECRET_KEY))
    dedicada = (settings.DATA_ENCRYPTION_KEY or "").strip()
    if dedicada and dedicada != settings.SECRET_KEY:
        # Cifra nova usa a dedicada (1ª); decifra tenta dedicada e depois legado.
        return MultiFernet([Fernet(_derivar_fernet(dedicada)), legado])
    return legado


def cifrar_segredo(valor: str) -> str:
    return _fernet_dados().encrypt(valor.encode("utf-8")).decode("ascii")


def decifrar_segredo(token: str | None) -> str | None:
    """Valor em texto, ou None se não houver cópia / as chaves não decifram."""
    if not token:
        return None
    try:
        return _fernet_dados().decrypt(token.encode("ascii")).decode("utf-8")
    except Exception:  # noqa: BLE001 — chave trocada/valor corrompido: sem cópia
        return None


# --- Redefinição de senha por token (fluxo profissional) ---------------------
# A senha do login é sempre hash irreversível. Quem esquece a senha recebe um
# token de USO ÚNICO e com VALIDADE; o banco guarda apenas o HASH do token
# (SHA-256), nunca o token em si — vazar o banco não permite redefinir senhas.

def gerar_token_reset() -> str:
    """Token opaco de alta entropia (256 bits) que vai no link de redefinição."""
    import secrets

    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash determinístico para guardar/consultar o token (SHA-256 em hex)."""
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validar_forca_senha(senha: str, email: str | None = None) -> str | None:
    """Devolve a mensagem de erro se a senha for fraca; None se for aceitável.
    Regra única compartilhada por todos os fluxos de senha (criar/trocar)."""
    if len(senha) < 8:
        return "A senha deve ter pelo menos 8 caracteres."
    if len(senha.encode("utf-8")) > LIMITE_SENHA_BYTES:
        return "A senha é longa demais (máximo de 72 bytes)."
    if senha.casefold() in SENHAS_PROIBIDAS:
        return "Esta senha é muito comum. Escolha uma senha mais difícil de adivinhar."
    if email:
        alvo = email.casefold().strip()
        if senha.casefold() in (alvo, alvo.split("@")[0]):
            return "A senha não pode ser igual ao e-mail."
    return None


def criar_token(usuario_id: int, token_version: int = 0) -> str:
    agora = datetime.now(timezone.utc)
    expira = agora + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(usuario_id),
        "ver": token_version,     # invalida tokens antigos ao trocar a senha
        "iat": agora,
        "exp": expira,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decodificar_token(token: str) -> dict | None:
    """Devolve o payload validado (sub/ver) ou None se inválido/expirado."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        int(payload.get("sub"))  # garante que 'sub' é um id válido
        return payload
    except (JWTError, TypeError, ValueError):
        return None
