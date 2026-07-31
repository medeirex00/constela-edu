"""Normalização de NOME de pessoa (PT-BR) — base compartilhada da reconciliação
por nome (deduplicação de professores e de alunos).

Casa variações da MESMA pessoa entre fontes diferentes (Matific manda o nome
curto, a Lista Piloto o completo): acento, caixa e espaços não distinguem
ninguém, e partículas (de/do/da…) não contam como sobrenome. O casamento
"nome curto ⊂ nome completo" opera sobre o CONJUNTO de tokens sem partículas.
"""
from __future__ import annotations

import unicodedata

# Partículas que não contam como sobrenome (Sueli Macedo DO Prado → "Prado").
PARTICULAS = {"de", "do", "da", "dos", "das", "e"}


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto or "")
                   if unicodedata.category(c) != "Mn")


def chave_nome(nome: str) -> str:
    """Identidade normalizada: sem acento, caixa e espaços colapsados. Casa
    'Antônio Silva' com 'Antonio  SILVA' — a MESMA pessoa entre as fontes."""
    return sem_acento(" ".join((nome or "").split())).casefold()


def tokens(nome: str) -> frozenset[str]:
    """Conjunto de palavras normalizadas (sem partículas) — base do casamento
    nome curto ↔ nome completo ('PAULA' ⊂ 'PAULA BENEDITA VILELA NOGUEIRA')."""
    return frozenset(
        sem_acento(p).casefold()
        for p in (nome or "").split()
        if sem_acento(p).casefold() not in PARTICULAS and any(c.isalnum() for c in p)
    )


def primeiro_token(nome: str) -> str:
    partes = (nome or "").split()
    return sem_acento(partes[0]).casefold() if partes else ""
