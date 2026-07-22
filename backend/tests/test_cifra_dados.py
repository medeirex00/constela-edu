"""Cifra de segredos em repouso (Fernet): round-trip e a chave DEDICADA.

A DATA_ENCRYPTION_KEY separa a chave que CIFRA os segredos de integração da
SECRET_KEY que ASSINA os JWT (menor raio de vazamento, rotação independente).
Deve continuar decifrando o que foi cifrado só com a SECRET_KEY (MultiFernet).
"""
from app.core import security
from app.core.config import settings


def test_cifrar_decifrar_round_trip():
    token = security.cifrar_segredo("segredo-abc-123")
    assert token != "segredo-abc-123"                 # de fato cifrado
    assert security.decifrar_segredo(token) == "segredo-abc-123"
    assert security.decifrar_segredo(None) is None


def test_chave_dedicada_ainda_decifra_o_legado():
    """Ligar a DATA_ENCRYPTION_KEY NÃO pode quebrar segredos já cifrados só com
    a SECRET_KEY — a chave legada segue como secundária de decifra."""
    original = settings.DATA_ENCRYPTION_KEY
    try:
        # Estado ANTERIOR: sem chave dedicada (cifra pela SECRET_KEY).
        object.__setattr__(settings, "DATA_ENCRYPTION_KEY", "")
        legado = security.cifrar_segredo("valor-antigo")

        # Agora liga a chave dedicada: o valor antigo AINDA decifra...
        object.__setattr__(settings, "DATA_ENCRYPTION_KEY", "chave-de-dados-dedicada-xyz")
        assert security.decifrar_segredo(legado) == "valor-antigo"
        # ...e novos segredos passam a usar a chave dedicada (round-trip ok).
        novo = security.cifrar_segredo("valor-novo")
        assert security.decifrar_segredo(novo) == "valor-novo"
    finally:
        object.__setattr__(settings, "DATA_ENCRYPTION_KEY", original)
