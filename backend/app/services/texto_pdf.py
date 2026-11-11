"""Texto para as fontes NATIVAS do fpdf2 (Helvetica, Times, Courier), que o PDF declara
em WinAnsi (cp1252). Fonte única do Quest (cartões de acesso) e dos PDFs de reserva dos
relatórios e do certificado (``services.relatorios``, sem navegador).

O cp1252 tem tudo o que o latin-1 tem e mais o apóstrofo tipográfico (Sant’Anna), as
aspas curvas, o travessão e as reticências. O que ainda ficar de fora vira a letra sem o
sinal (ő → o, Ł → L) antes de cair no '?' — nunca erro 500 (G_QUEST-6).
"""
from __future__ import annotations

import unicodedata

CODIFICACAO = "windows-1252"
# Letras sem decomposição Unicode que não existem no cp1252.
SEM_SINAL = str.maketrans({"Ł": "L", "ł": "l", "Đ": "D", "đ": "d", "ı": "i",
                           "Ħ": "H", "ħ": "h", "‐": "-", "‑": "-", "−": "-"})


def cabe(caractere: str) -> bool:
    try:
        caractere.encode(CODIFICACAO)
    except UnicodeEncodeError:
        return False
    return True


def texto_pdf(texto) -> str:
    """Texto pronto para as fontes nativas em cp1252. Acento digitado à parte
    (forma decomposta, NFD) é juntado à letra antes; caractere fora do cp1252 vira
    a letra sem o sinal (ő → o, Ł → L); invisível (formatação ou sinal solto)
    some; só o que não tem equivalente vira '?' — nunca erro 500."""
    saida = []
    for caractere in unicodedata.normalize("NFC", str(texto)).translate(SEM_SINAL):
        if cabe(caractere):
            saida.append(caractere)
            continue
        base = "".join(c for c in unicodedata.normalize("NFKD", caractere)
                       if unicodedata.category(c) != "Mn")
        if base and all(cabe(c) for c in base):
            saida.append(base)
        elif unicodedata.category(caractere) not in ("Cf", "Mn", "Me"):
            saida.append("?")
    return "".join(saida)
