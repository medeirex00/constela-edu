"""Saída dos scripts do operador em UTF-8 — também com a saída redirecionada.

O DEFEITO. No Windows, com a saída num arquivo ou num pipe (``> diag.txt``,
``| tee``, ``| Tee-Object``), o Python escreve na página de código do sistema
(cp1252), e um caractere fora dela (``→``, ``≥``, ``≠``, um nome com letra de
outro alfabeto) derruba o script com ``UnicodeEncodeError`` NO MEIO da saída. O
``senhas_derivadas.py`` quebrava justamente na linha ``alvos: --aplicar → N``,
a que dá o número do ``--esperado``. No console interativo isso não acontece
(lá o Python já escreve em UTF-8), por isso o defeito só aparecia na hora de
guardar a saída.

A CORREÇÃO. ``forcar_saida_utf8()`` é a PRIMEIRA instrução da função de entrada
de cada script (a que o bloco ``__main__`` chama): troca ``stdout`` e ``stderr``
para UTF-8 com ``errors="replace"``, de modo que nenhum caractere derruba a
execução e o arquivo gravado sai em UTF-8 (o que o Git Bash, o ``tee`` e o Bloco
de Notas leem direito). Fluxo que já é UTF-8 (o console, o ``capsys`` do pytest)
fica intocado; fluxo sem ``reconfigure`` (um ``StringIO`` de teste) também. A
catraca ``tests/test_scripts_saida_utf8.py`` reprova script novo que não chame.

Só biblioteca padrão: o portão ``exigir_ci_verde.py`` roda como arquivo, sem
dependência instalada, no runner do GitHub e no container.
"""
from __future__ import annotations

import codecs
import sys


def _ja_utf8(fluxo) -> bool:
    try:
        return codecs.lookup(getattr(fluxo, "encoding", None) or "").name == "utf-8"
    except LookupError:
        return False


def forcar_saida_utf8() -> None:
    """``stdout``/``stderr`` em UTF-8 (``errors="replace"``) quando ainda não estão."""
    for nome in ("stdout", "stderr"):
        fluxo = getattr(sys, nome, None)
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is None or _ja_utf8(fluxo):
            continue
        try:
            reconfigurar(encoding="utf-8", errors="replace")
        except (OSError, ValueError):   # fluxo fechado ou já lido: fica como está
            pass
