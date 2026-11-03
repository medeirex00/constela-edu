"""Junta os certificados de um LOTE num PDF só.

Cada certificado é o MESMO documento da rota individual (gerado pela mesma função,
um por aluno); aqui só se costuram as páginas, na ordem recebida.

POR QUE DEDUPLICAR AS IMAGENS. A arte oficial do Elefante/Matific vai embutida em
cada certificado (um PNG de 1492×1054, ~1,7 MB por página, medido em 31/10/2026): um
lote de 50 sairia com ~85 MB, o mesmo fundo repetido 50 vezes. Imagens de conteúdo
IDÊNTICO passam a apontar para um objeto só e as cópias órfãs saem do arquivo — o PDF
fica com o tamanho de UMA arte mais o texto de cada página. Nada do que se vê muda: a
troca só acontece entre imagens byte a byte iguais (dados e dicionário). Se a
deduplicação falhar por qualquer motivo, o lote sai sem ela (maior, mas correto).
"""
from __future__ import annotations

import hashlib
import io
import logging
from typing import Iterable

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DictionaryObject, IndirectObject, NameObject,
                           StreamObject)

logger = logging.getLogger("constela.certificados_lote")


def _bytes_do_fluxo(fluxo: StreamObject) -> bytes:
    """Os bytes GRAVADOS do fluxo (codificados), sem decodificar a imagem."""
    dados = getattr(fluxo, "_data", None)
    return dados if isinstance(dados, bytes) else fluxo.get_data()


def _canonico(valor, profundidade: int = 0) -> str:
    """Texto que identifica o CONTEÚDO de um objeto PDF — referências indiretas
    resolvidas (o número do objeto muda de um documento para outro; o conteúdo, não)."""
    if profundidade > 6:
        return "…"
    if isinstance(valor, IndirectObject):
        valor = valor.get_object()
    if isinstance(valor, StreamObject):
        corpo = {k: v for k, v in valor.items() if k != "/Length"}
        return ("stream" + _canonico(DictionaryObject(corpo), profundidade + 1)
                + hashlib.sha256(_bytes_do_fluxo(valor)).hexdigest())
    if isinstance(valor, DictionaryObject):
        return "{" + ",".join(f"{k}:{_canonico(valor.raw_get(k), profundidade + 1)}"
                              for k in sorted(valor.keys()) if k != "/Length") + "}"
    if isinstance(valor, ArrayObject):
        return "[" + ",".join(_canonico(v, profundidade + 1) for v in valor) + "]"
    return repr(valor)


def _deduplicar_imagens(escritor: PdfWriter) -> bool:
    """Faz as imagens idênticas das páginas apontarem para a primeira delas.
    Devolve se trocou alguma (aí as cópias ficaram órfãs)."""
    vistas: dict[str, IndirectObject] = {}
    trocou = False
    for pagina in escritor.pages:
        recursos = pagina.get("/Resources")
        if recursos is None:
            continue
        xobjetos = recursos.get_object().get("/XObject")
        if xobjetos is None:
            continue
        xobjetos = xobjetos.get_object()
        for nome in list(xobjetos.keys()):
            ref = xobjetos.raw_get(nome)
            if not isinstance(ref, IndirectObject):
                continue
            imagem = ref.get_object()
            if not isinstance(imagem, StreamObject) or imagem.get("/Subtype") != "/Image":
                continue
            chave = _canonico(imagem)
            primeira = vistas.setdefault(chave, ref)
            if primeira.idnum != ref.idnum:
                xobjetos[NameObject(nome)] = primeira
                trocou = True
    return trocou


def _juntar(documentos: list[bytes], *, deduplicar: bool) -> bytes:
    escritor = PdfWriter()
    for documento in documentos:
        escritor.append(PdfReader(io.BytesIO(documento)))
    if deduplicar and _deduplicar_imagens(escritor):
        escritor.compress_identical_objects(remove_duplicates=False,
                                            remove_unreferenced=True)
    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()


def juntar_pdfs(documentos: Iterable[bytes]) -> bytes:
    """Um PDF com todas as páginas de ``documentos``, na ordem recebida."""
    lista = list(documentos)
    if not lista:
        raise ValueError("nenhum documento para juntar")
    try:
        return _juntar(lista, deduplicar=True)
    except Exception:  # noqa: BLE001 — a deduplicação é otimização: sem ela, segue correto
        logger.warning("deduplicação das imagens do lote falhou; juntando sem ela",
                       exc_info=True)
        return _juntar(lista, deduplicar=False)
