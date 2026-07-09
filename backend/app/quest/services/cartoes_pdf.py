"""Cartões de acesso do Quest — PDF para o professor imprimir e recortar.

Cada cartão carrega tudo o que a criança precisa para entrar: QR (1 leitura
= entrou), código falável e a sequência de 4 figuras do PIN. Layout A4 em
grade 2×4 (8 cartões por página), com linhas de corte tracejadas.

Mesmas restrições do resto dos PDFs do projeto (services/relatorios.py):
fontes nativas latin-1 — por isso as figuras aparecem pelo NOME (a criança
casa o nome com a figura na tela, que mostra o desenho).
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

_LARGURA_CARTAO = 92.0
_ALTURA_CARTAO = 64.0
_MARGEM_X = 9.0
_MARGEM_Y = 10.0
_ESPACO = 4.0


def _latin1(texto) -> str:
    return str(texto).encode("latin-1", "replace").decode("latin-1")


def _hex_para_rgb(cor: str) -> tuple[int, int, int]:
    cor = (cor or "#7C6FF0").lstrip("#")
    try:
        return tuple(int(cor[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore
    except ValueError:
        return (124, 111, 240)


def _qr_png(url: str) -> io.BytesIO:
    """QR como PNG RGB. O segno gera PNG de 1 bit (paleta), que o fpdf2
    embute com o stride errado (QR vira rabisco) — a conversão via Pillow
    (dependência do próprio fpdf2) elimina o problema."""
    import segno
    from PIL import Image

    bruto = io.BytesIO()
    segno.make(url, error="m").save(bruto, kind="png", scale=6, border=1)
    bruto.seek(0)
    buffer = io.BytesIO()
    Image.open(bruto).convert("RGB").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _desenhar_cartao(pdf, x: float, y: float, escola_nome: str,
                     turma_nome: str, cor: str, cartao: dict) -> None:
    r, g, b = _hex_para_rgb(cor)

    # Moldura de corte (tracejada) + cartão
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.2)
    with pdf.local_context():
        pdf.set_dash_pattern(dash=1.2, gap=1.2)
        pdf.rect(x, y, _LARGURA_CARTAO, _ALTURA_CARTAO)

    # Faixa superior com a cor da escola
    pdf.set_fill_color(r, g, b)
    pdf.rect(x, y, _LARGURA_CARTAO, 9, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_xy(x + 3, y + 2)
    pdf.cell(0, 5, "CONSTELA QUEST")
    pdf.set_font("helvetica", "", 7)
    pdf.set_xy(x + 3, y + 6.2)
    pdf.cell(0, 3, _latin1(f"{escola_nome} - {turma_nome}"))

    # QR à direita
    lado_qr = 24.0
    pdf.image(_qr_png(cartao["qr_url"]),
              x=x + _LARGURA_CARTAO - lado_qr - 3.5,
              y=y + 12, w=lado_qr, h=lado_qr)
    pdf.set_text_color(120, 120, 120)
    pdf.set_font("helvetica", "", 6)
    pdf.set_xy(x + _LARGURA_CARTAO - lado_qr - 3.5, y + 12 + lado_qr + 0.5)
    pdf.cell(lado_qr, 3, "aponte a camera", align="C")

    largura_texto = _LARGURA_CARTAO - lado_qr - 11

    # Nome do aluno (encolhe até caber)
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("helvetica", "B", 11)
    nome = _latin1(cartao["nome"])
    while pdf.get_string_width(nome) > largura_texto and pdf.font_size_pt > 7:
        pdf.set_font_size(pdf.font_size_pt - 0.5)
    pdf.set_xy(x + 3.5, y + 12.5)
    pdf.cell(largura_texto, 5, nome)

    # Código falável, bem grande
    pdf.set_font("helvetica", "", 7.5)
    pdf.set_text_color(110, 110, 110)
    pdf.set_xy(x + 3.5, y + 20)
    pdf.cell(largura_texto, 4, "Meu codigo:")
    pdf.set_font("courier", "B", 17)
    pdf.set_text_color(r, g, b)
    pdf.set_xy(x + 3.5, y + 24.5)
    pdf.cell(largura_texto, 8, _latin1(cartao["codigo"]))

    # PIN: as 4 figuras em ordem (nomes numerados; a tela mostra os desenhos)
    pdf.set_font("helvetica", "", 7.5)
    pdf.set_text_color(110, 110, 110)
    pdf.set_xy(x + 3.5, y + 36)
    pdf.cell(largura_texto, 4, "Minha senha secreta (toque nesta ordem):")
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("helvetica", "B", 9.5)
    pdf.set_xy(x + 3.5, y + 41)
    figuras = "  ".join(
        f"{i}. {_latin1(figura['nome'])}"
        for i, figura in enumerate(cartao["pin"], start=1))
    while pdf.get_string_width(figuras) > _LARGURA_CARTAO - 8 and pdf.font_size_pt > 6:
        pdf.set_font_size(pdf.font_size_pt - 0.5)
    pdf.cell(_LARGURA_CARTAO - 8, 5, figuras)

    # Rodapé
    pdf.set_font("helvetica", "I", 6.5)
    pdf.set_text_color(140, 140, 140)
    pdf.set_xy(x + 3.5, y + _ALTURA_CARTAO - 9)
    pdf.cell(_LARGURA_CARTAO - 8, 3.5,
             _latin1(f"Apelido no jogo: {cartao['apelido']}"))
    pdf.set_xy(x + 3.5, y + _ALTURA_CARTAO - 5.5)
    pdf.cell(_LARGURA_CARTAO - 8, 3.5,
             "Guarde este cartao como um tesouro!")


def gerar_cartoes_pdf(escola_nome: str, cor: str, turma_nome: str,
                      cartoes: list[dict]) -> bytes:
    """`cartoes`: [{nome, apelido, codigo, pin: [{nome}…], qr_url}, …]"""
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)

    por_pagina = 8  # 2 colunas × 4 linhas
    for indice, cartao in enumerate(cartoes):
        posicao = indice % por_pagina
        if posicao == 0:
            pdf.add_page()
            pdf.set_font("helvetica", "", 7)
            pdf.set_text_color(150, 150, 150)
            gerado = datetime.now(timezone.utc).strftime("%d/%m/%Y")
            pdf.set_xy(_MARGEM_X, 4)
            pdf.cell(0, 4, _latin1(
                f"Constela Quest - Cartoes de acesso - {turma_nome} - "
                f"gerado em {gerado}"))
        coluna = posicao % 2
        linha = posicao // 2
        x = _MARGEM_X + coluna * (_LARGURA_CARTAO + _ESPACO)
        y = _MARGEM_Y + linha * (_ALTURA_CARTAO + _ESPACO)
        _desenhar_cartao(pdf, x, y, escola_nome, turma_nome, cor, cartao)

    if not cartoes:
        pdf.add_page()
        pdf.set_font("helvetica", "", 11)
        pdf.set_text_color(90, 90, 90)
        pdf.set_xy(20, 30)
        pdf.cell(0, 8, "Nenhum aluno ativo nesta turma.")

    return bytes(pdf.output())
