"""Quest — nome longo da criança não é desenhado por cima do QR do cartão (G_QUEST-2).

``_desenhar_cartao`` reduzia a fonte do nome só até 7 pt e então desenhava o nome
inteiro numa linha: o fpdf2 não corta o texto que passa da largura da célula. A
partir de ~48 caracteres (nomes de 5 a 7 partes existem na rede) o fim do nome caía
sobre o padrão de localização superior esquerdo do QR, que é a porta de entrada das
crianças de 6 e 7 anos. Agora o nome que não cabe numa linha a 7 pt quebra em duas
linhas e, se ainda sobrar, termina em "..." — sempre dentro da coluna de texto.

O PDF é lido de volta (pdfplumber): posição de cada caractere do nome × a imagem do QR.
Dados fictícios.
"""
import io

import pdfplumber
import pytest

from app.quest.services import cartoes_pdf

MM = 72 / 25.4  # pt por mm
# 1º cartão da página: x=9 mm, y=10 mm; nome entre y+12 e y+21 mm (antes do
# "Meu codigo magico:", em y+22 mm).
_TOPO_NOME, _FIM_NOME = (10 + 12) * MM, (10 + 21) * MM


def _cartao(nome: str) -> dict:
    return {"nome": nome, "apelido": "Estrela Valente", "codigo": "SOL-LUA-314",
            "qr_url": "https://quest.exemplo.test/entrar?qr=" + "x" * 32}


def _nome_desenhado(nome: str):
    """(caracteres do nome, caixa do QR, topo do rótulo "Meu codigo magico:")."""
    pdf = cartoes_pdf.gerar_cartoes_pdf("ESCOLA FICTICIA", "#7C6FF0", "3o Ano A",
                                        [_cartao(nome)], com_pagina_professor=False)
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        pagina = doc.pages[0]
        qr = pagina.images[0]
        chars = [c for c in pagina.chars
                 if "Helvetica-Bold" in c["fontname"]
                 and _TOPO_NOME <= c["top"] <= _FIM_NOME]
        rotulo = [c for c in pagina.chars if c["text"] == "M" and c["size"] < 8.5
                  and "Bold" not in c["fontname"] and c["top"] > _TOPO_NOME]
        linhas = pagina.within_bbox((9 * MM, _TOPO_NOME - 1, qr["x0"], _FIM_NOME)
                                    ).extract_text() or ""
    return chars, qr, min(c["top"] for c in rotulo), linhas


NOMES = [
    "Ana Ficticia",
    "Maria Eduarda Aparecida dos Santos Oliveira Ferr",          # 48: invadia
    "Enzo Gabriel Cavalcanti de Albuquerque Pereira Neto",        # 51: 'Neto' no QR
    "Maria Eduarda Aparecida dos Santos Oliveira Ferreira Lima de Albuquerque Neto",
    " ".join(["Pereira"] * 28)[:200],                              # 200 (tamanho da coluna)
    "W" * 200,                                                     # sem espaço nenhum
]


@pytest.mark.parametrize("nome", NOMES, ids=lambda n: f"{len(n)}-caracteres")
def test_nome_fica_na_coluna_de_texto_e_longe_do_qr(nome):
    chars, qr, topo_rotulo, _ = _nome_desenhado(nome)
    assert chars, "o nome não foi desenhado"
    sobre_qr = "".join(c["text"] for c in chars if c["x1"] > qr["x0"])
    fim = max(c["x1"] for c in chars)
    assert fim <= qr["x0"], (
        f"nome invade o QR: termina em {fim / MM:.1f} mm, QR começa em "
        f"{qr['x0'] / MM:.1f} mm; letras sobre o QR: {sobre_qr!r}")
    # Nem por baixo: o nome termina antes do rótulo do código.
    assert max(c["bottom"] for c in chars) <= topo_rotulo
    # Legível: nunca abaixo dos 7 pt de antes.
    assert min(c["size"] for c in chars) >= 7 - 0.01


def test_nome_que_cabe_em_duas_linhas_sai_inteiro():
    nome = "Enzo Gabriel Cavalcanti de Albuquerque Pereira Neto"
    _, _, _, linhas = _nome_desenhado(nome)
    assert " ".join(linhas.split()) == nome


def test_nome_que_nem_em_duas_linhas_cabe_termina_em_reticencias():
    nome = " ".join(["Pereira"] * 28)[:200]
    _, _, _, linhas = _nome_desenhado(nome)
    partes = linhas.splitlines()
    assert len(partes) == 2, partes
    assert partes[-1].endswith("...")


def test_nome_curto_continua_numa_linha_no_tamanho_de_antes():
    chars, _, _, linhas = _nome_desenhado("Ana Ficticia")
    assert linhas.strip() == "Ana Ficticia"
    assert {round(c["size"], 1) for c in chars} == {11.0}
