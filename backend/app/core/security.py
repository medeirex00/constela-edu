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
