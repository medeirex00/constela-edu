"""Texto de arquivo enviado em TEXTO (relatório .txt/.csv/.tsv, CSV das avaliações).

O Excel em português grava o "CSV (separado por vírgulas)" em Windows-1252, o "Texto
Unicode" em UTF-16 com BOM e o "CSV UTF-8" com BOM UTF-8; a exportação das
plataformas e o texto colado vêm em UTF-8. Decodificar tudo como UTF-8 com
``errors="replace"`` trocava cada letra acentuada de um arquivo Windows-1252 por
"�" em silêncio — e o nome estragado seguia para o casamento e para a ficha nova.

Uma regra só para todos os leitores de texto enviado: a marca no começo do arquivo
(BOM) manda; sem ela, UTF-8 estrito; e, se não for UTF-8, Windows-1252 (que cobre o
Latin-1 em português). O "�" que ainda sobrar é de byte que nenhuma das duas lê — e
quem grava o texto confere (``importacao.texto_ilegivel``).
"""
from __future__ import annotations

import codecs

#: O caractere que a decodificação põe no lugar do byte que não sabe ler.
ILEGIVEL = "�"


def decodificar_texto(conteudo: bytes) -> str:
    """O texto do arquivo, nesta ordem:

    1. BOM UTF-8 → UTF-8 (sem a marca);
    2. BOM UTF-16 (LE ou BE) → UTF-16 (sem a marca);
    3. UTF-8 estrito;
    4. senão, Windows-1252.

    Nunca levanta: o byte que nem a codificação escolhida lê vira ``ILEGIVEL``."""
    if conteudo.startswith(codecs.BOM_UTF8):
        return conteudo[len(codecs.BOM_UTF8):].decode("utf-8", errors="replace")
    if conteudo.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return conteudo.decode("utf-16", errors="replace")
    try:
        return conteudo.decode("utf-8")
    except UnicodeDecodeError:
        return conteudo.decode("cp1252", errors="replace")
