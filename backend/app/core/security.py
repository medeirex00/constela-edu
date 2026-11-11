"""Hash de senhas, política de senha e emissão/validação de tokens JWT."""
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.core.config import separar_chaves, settings

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


# --- Segredos simétricos do app (Fernet no anel da DATA_ENCRYPTION_KEY) ------
# Para valores que PRECISAM ser recuperados em texto para uso posterior: as
# credenciais das plataformas (app/sync/vault.py), a chave de API do assistente de
# IA e a sessão salva do Matific (as origens estão em app/services/recifragem.py).
# Quem obtém apenas o banco NÃO lê o segredo: a chave que cifra é a
# DATA_ENCRYPTION_KEY (obrigatória com ENV=producao), que fica fora do banco; a
# SECRET_KEY só decifra as cifras legadas. Sem DEK, só em dev, a SECRET_KEY cifra
# como antes. A ordem do anel e a rotação estão em ``segredos_da_cifra``.
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


# Tamanho mínimo recomendado da DATA_ENCRYPTION_KEY (só AVISO e diagnóstico: a
# chave é derivada por SHA-256 e funciona com qualquer tamanho).
TAMANHO_MINIMO_DEK = 32

# Resultado de ``situacao_da_cifra``.
CIFRA_PRIMARIA = "primaria"      # abre com a chave que cifra hoje
CIFRA_ANTERIOR = "anterior"      # abre só com uma chave de decifra (recifrar)
CIFRA_ILEGIVEL = "ilegivel"      # nenhuma chave do anel abre
CIFRA_VAZIA = "vazio"            # nada gravado
SITUACOES_CIFRA = (CIFRA_PRIMARIA, CIFRA_ANTERIOR, CIFRA_ILEGIVEL, CIFRA_VAZIA)


def _dek_atual() -> str:
    return (settings.DATA_ENCRYPTION_KEY or "").strip()


def segredos_da_cifra() -> list[str]:
    """O ANEL de chaves da cifra em repouso, na ordem em que é usado: o 1º CIFRA;
    todos DECIFRAM (e conferem o hash do código do Quest, que usa a mesma régua).

        [DEK atual, DEKs anteriores..., SECRET_KEY atual (legado), SECRET_KEY anterior]

    Sem ``DATA_ENCRYPTION_KEY`` (vazia, só espaços ou igual à SECRET_KEY) a 1ª é a
    SECRET_KEY, como sempre foi. Vazias e repetidas ficam de fora. As ANTERIORES
    (``DATA_ENCRYPTION_KEYS_ANTERIORES``, ``CHAVE_CIFRA_LEGADA_ANTERIOR``) nunca
    cifram — e nada aqui toca o JWT: ``decodificar_token`` só conhece a SECRET_KEY.
    A SECRET_KEY entra sem ``.strip()`` (é o valor que deriva as cifras legadas
    desde o início); a legada anterior entra crua e sem espaços nas pontas."""
    secret_key = settings.SECRET_KEY
    dedicada = _dek_atual()
    primaria = dedicada if dedicada and dedicada != secret_key else secret_key
    legada = settings.CHAVE_CIFRA_LEGADA_ANTERIOR or ""
    # Só espaços = vazia; igual a uma chave ATUAL = rotação não feita: ignorada inteira.
    ignorar = not legada.strip() or legada.strip() in (dedicada, secret_key,
                                                       secret_key.strip())
    legadas = [] if ignorar else [legada, legada.strip()]
    ordem = [primaria, *separar_chaves(settings.DATA_ENCRYPTION_KEYS_ANTERIORES),
             secret_key, *legadas]
    anel: list[str] = []
    for segredo in ordem:
        if segredo and segredo not in anel:
            anel.append(segredo)
    return anel


def _fernets() -> list:
    from cryptography.fernet import Fernet

    return [Fernet(_derivar_fernet(s)) for s in segredos_da_cifra()]


def _fernet_dados():
    """Cifra/decifra os segredos em repouso (credenciais de plataforma, chave
    de IA, cookies do robô).

    Se ``DATA_ENCRYPTION_KEY`` estiver definida, ela é a chave PRIMÁRIA de cifra
    — SEPARADA da ``SECRET_KEY`` que assina os JWT. Assim um vazamento da
    SECRET_KEY sozinho não decifra os segredos de integração, e a chave de
    dados pode ser rotacionada de forma independente. A chave derivada da
    SECRET_KEY permanece como SECUNDÁRIA de DECIFRA (``MultiFernet``), para que
    tudo que já foi cifrado continue legível sem re-cifrar. Sem
    ``DATA_ENCRYPTION_KEY``, o comportamento é idêntico ao anterior; isso só
    acontece em dev, porque com ``ENV=producao`` o boot recusa a DEK ausente.

    Na rotação planejada entram as chaves ANTERIORES, só de decifra (ver
    ``segredos_da_cifra``); a cifra nova sai SEMPRE com a 1ª."""
    from cryptography.fernet import MultiFernet

    fernets = _fernets()
    return fernets[0] if len(fernets) == 1 else MultiFernet(fernets)


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


def _abre(fernet, dado: bytes) -> bool:
    try:
        fernet.decrypt(dado)
        return True
    except Exception:  # noqa: BLE001 — InvalidToken/forma errada: não abre
        return False


def situacao_da_cifra(token: str | None) -> str:
    """Com que chave do anel a cifra abre — sem devolver o conteúdo:
    'primaria' (a que cifra hoje), 'anterior' (só uma de decifra: recifrar),
    'ilegivel' (nenhuma) ou 'vazio' (nada gravado). Nunca levanta."""
    if not token:
        return CIFRA_VAZIA
    try:
        dado = str(token).encode("ascii")
    except UnicodeEncodeError:
        return CIFRA_ILEGIVEL
    primeira, *demais = _fernets()
    if _abre(primeira, dado):
        return CIFRA_PRIMARIA
    if any(_abre(f, dado) for f in demais):
        return CIFRA_ANTERIOR
    return CIFRA_ILEGIVEL


def recifrar(token: str | None) -> str | None:
    """A mesma cifra refeita com a chave PRIMÁRIA (``MultiFernet.rotate``: abre
    com qualquer chave do anel e cifra com a 1ª). None se vazia ou ilegível —
    nunca levanta e nunca devolve o texto claro."""
    from cryptography.fernet import MultiFernet

    if not token:
        return None
    try:
        return MultiFernet(_fernets()).rotate(str(token).encode("ascii")).decode("ascii")
    except Exception:  # noqa: BLE001 — nenhuma chave abre / forma errada
        return None


def diagnostico_cifra() -> dict:
    """Prontidão da cifra em repouso, SÓ com booleanos e números (o valor de
    nenhuma chave sai daqui) — vai para o /sistema/diagnostico e para o aviso do
    boot (A1, lacuna L3: DEK vazia, curta ou igual à SECRET_KEY caía no legado sem
    aviso)."""
    secret_key = settings.SECRET_KEY
    dek = _dek_atual()
    atuais = {dek, secret_key, secret_key.strip()}
    anteriores = [c for c in separar_chaves(settings.DATA_ENCRYPTION_KEYS_ANTERIORES)
                  if c not in atuais]
    legada = (settings.CHAVE_CIFRA_LEGADA_ANTERIOR or "").strip()
    legada_ativa = bool(legada) and legada not in atuais
    return {
        # A DEK é a primária do anel (definida e diferente da SECRET_KEY).
        "dedicada_ativa": bool(dek) and dek != secret_key,
        "dek_tamanho_ok": len(dek) >= TAMANHO_MINIMO_DEK,
        "dek_distinta_da_secret_key": bool(dek) and dek not in (secret_key,
                                                               secret_key.strip()),
        # Chaves só de decifra em uso (DEKs anteriores + SECRET_KEY anterior).
        "anteriores_configuradas": len(anteriores) + int(legada_ativa),
        "legada_anterior_configurada": legada_ativa,
        "secret_key_efemera": bool(getattr(settings, "SECRET_KEY_EFEMERA", False)),
    }


def avisos_da_cifra() -> list[str]:
    """Frases para o log do boot (nunca com valor de chave)."""
    d = diagnostico_cifra()
    dek = _dek_atual()
    avisos: list[str] = []
    if not dek:
        avisos.append("DATA_ENCRYPTION_KEY vazia: os segredos em repouso (credenciais "
                      "das plataformas, chave de IA, sessão do Matific) são cifrados com "
                      "a chave derivada da SECRET_KEY; trocar a SECRET_KEY os deixa "
                      "ilegíveis.")
    elif not d["dek_distinta_da_secret_key"]:
        avisos.append("DATA_ENCRYPTION_KEY igual à SECRET_KEY: ignorada; os segredos em "
                      "repouso seguem na chave derivada da SECRET_KEY (legado).")
    elif not d["dek_tamanho_ok"]:
        avisos.append(f"DATA_ENCRYPTION_KEY com menos de {TAMANHO_MINIMO_DEK} "
                      "caracteres: gere uma chave longa e aleatória.")
    if "," in dek:
        # Só aviso (não recusa o ENV=producao): a chave funciona hoje; o problema é na
        # rotação, quando ela vai para a lista separada por vírgula e vira pedaços.
        avisos.append("DATA_ENCRYPTION_KEY contém vírgula: na rotação ela não cabe em "
                      "DATA_ENCRYPTION_KEYS_ANTERIORES (lista separada por vírgula) e o "
                      "que ela cifrou ficaria ilegível; gere a chave com "
                      "secrets.token_urlsafe(48).")
    if d["anteriores_configuradas"]:
        avisos.append(f"{d['anteriores_configuradas']} chave(s) ANTERIOR(es) da cifra "
                      "configurada(s), só para decifrar: rode `python -m "
                      "scripts.recifrar_segredos --executar` e apague-as depois.")
    return avisos


def registrar_avisos_da_cifra(logger) -> int:
    """Escreve os avisos de ``avisos_da_cifra`` no log (boot). Devolve quantos."""
    avisos = avisos_da_cifra()
    for aviso in avisos:
        logger.warning("Cifra em repouso: %s", aviso)
    return len(avisos)


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


def validar_forca_senha(senha: str, email: str | None = None, *,
                        nome: str | None = None, usuario: str | None = None) -> str | None:
    """Devolve a mensagem de erro se a senha for fraca; None se for aceitável.
    Regra única compartilhada por todos os fluxos de senha (criar/trocar).

    Com ``nome``/``usuario`` (o dono da senha), recusa também as senhas das
    convenções antigas de professor ("nomesobrenome123", "Primeiro123"): a regra
    está publicada no histórico do repositório, e quem se acostumou a ela
    tenderia a escolhê-la de novo pelo link — e a conta voltaria a ser
    calculável a partir do nome."""
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
    if nome or usuario:
        # Import tardio: o serviço de professores importa este módulo.
        from app.services.professores import _senhas_da_convencao_antiga
        convencoes = {c.casefold() for c in _senhas_da_convencao_antiga(nome or "", usuario)}
        if senha.casefold() in convencoes:
            return ("Esta senha segue um padrão fácil de adivinhar (nome + 123). "
                    "Escolha outra.")
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
    except (jwt.PyJWTError, TypeError, ValueError):
        return None


def impressao_da_chave_de_sessao() -> str:
    """Impressão da chave que assina as sessões (SECRET_KEY), para saber se ela mudou
    sem guardá-la: HMAC-SHA256 de um rótulo fixo com a chave, 32 caracteres hex. Não
    revela a chave (nem serve para assinar nada).

    Trocar a SECRET_KEY derruba TODAS as sessões (``decodificar_token`` só conhece a
    atual). Os aparelhos de push registrados com as sessões antigas saem junto
    (``push.conferir_chave_de_sessao``): a impressão fica gravada por escola, e a
    diferença mostra que a chave mudou."""
    import hashlib
    import hmac

    return hmac.new(settings.SECRET_KEY.encode("utf-8"), b"constela:sessao:dispositivo-push",
                    hashlib.sha256).hexdigest()[:32]
