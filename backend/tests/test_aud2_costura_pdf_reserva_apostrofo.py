"""G_QUEST-6 (mesma classe de defeito) — os PDFs de reserva dos relatórios (fpdf2, sem
navegador) escrevem o nome da criança como ele é.

``relatorios._latin1`` fazia ``encode("latin-1", "replace")``: o apóstrofo tipográfico
(’), que o teclado do celular e do Mac põe sozinho em Sant’Anna, saía "Sant?Anna" no
certificado de reserva e no PDF de tabela. Agora os dois usam a mesma regra dos cartões
do Quest (``services.texto_pdf``: cp1252, que o PDF já declara; fora dele, a letra sem o
sinal antes do '?'). O PDF é lido de volta (pdfplumber). Dados fictícios.
"""
import io

import pdfplumber

from app.services import relatorios


def _texto(pdf: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return "\n".join(p.extract_text() or "" for p in doc.pages)


def test_certificado_de_reserva_escreve_o_apostrofo():
    nome = "Ana Sant’Anna Dall’Agnol"
    texto = _texto(relatorios._certificado_fpdf(
        "Escola Ficticia D’Oeste", "#1E3A8A", nome, "4º Ano A", 1, 87.5, 2026))
    assert nome in texto, texto
    assert "Escola Ficticia D’Oeste" in texto, texto
    assert "Sant?Anna" not in texto


def test_pdf_de_tabela_escreve_o_apostrofo_e_a_letra_sem_o_sinal():
    texto = _texto(relatorios.gerar_pdf(
        "Ranking", "Escola Ficticia D’Oeste", "#1E3A8A", ["Posição", "Aluno"],
        [[1, "Ana Sant’Anna"], [2, "Gergő Łucja"]]))
    assert "Ana Sant’Anna" in texto, texto
    assert "Gergo Lucja" in texto, texto       # fora do cp1252: a letra sem o sinal
    assert "?" not in texto.replace("Ranking", ""), texto


def test_os_acentos_do_portugues_continuam():
    assert relatorios._latin1("João Conceição Araújo") == "João Conceição Araújo"
