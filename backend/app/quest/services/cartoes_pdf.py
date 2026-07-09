"""Cartões de acesso do Quest — PDF para o professor imprimir e recortar.

Cada cartão carrega o que a criança precisa para entrar: QR (1 leitura =
entrou) e o código falável — SEM senha (decisão de produto, como no
Elefante Letrado). Layout A4 em grade 2×4 com linhas de corte, mais uma
página final "só do professor": tabela nome → código da turma inteira e o
roteiro da primeira aula (cartão perdido deixa de ser suporte).

Mesmas restrições dos demais PDFs do projeto (services/relatorios.py):
fontes nativas latin-1.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from app.core.config import settings

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


def _endereco_app() -> str:
    return settings.QUEST_BASE_URL.replace("https://", "").replace(
        "http://", "").rstrip("/")


def _desenhar_cartao(pdf, x: float, y: float, escola_nome: str,
                     turma_nome: str, cor: str, cartao: dict) -> None:
    r, g, b = _hex_para_rgb(cor)

    # Moldura de corte (tracejada)
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
    lado_qr = 26.0
    pdf.image(_qr_png(cartao["qr_url"]),
              x=x + _LARGURA_CARTAO - lado_qr - 3.5,
              y=y + 12, w=lado_qr, h=lado_qr)
    pdf.set_text_color(120, 120, 120)
    pdf.set_font("helvetica", "", 6)
    pdf.set_xy(x + _LARGURA_CARTAO - lado_qr - 3.5, y + 12 + lado_qr + 0.5)
    pdf.cell(lado_qr, 3, "aponte a camera")

    largura_texto = _LARGURA_CARTAO - lado_qr - 11

    # Nome do aluno (encolhe até caber)
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("helvetica", "B", 11)
    nome = _latin1(cartao["nome"])
    while pdf.get_string_width(nome) > largura_texto and pdf.font_size_pt > 7:
        pdf.set_font_size(pdf.font_size_pt - 0.5)
    pdf.set_xy(x + 3.5, y + 12.5)
    pdf.cell(largura_texto, 5, nome)

    # Código falável, o herói do cartão — bem grande
    pdf.set_font("helvetica", "", 8)
    pdf.set_text_color(110, 110, 110)
    pdf.set_xy(x + 3.5, y + 22)
    pdf.cell(largura_texto, 4, "Meu codigo magico:")
    pdf.set_font("courier", "B", 21)
    pdf.set_text_color(r, g, b)
    pdf.set_xy(x + 3.5, y + 27)
    codigo = _latin1(cartao["codigo"])
    while pdf.get_string_width(codigo) > largura_texto and pdf.font_size_pt > 12:
        pdf.set_font_size(pdf.font_size_pt - 1)
    pdf.cell(largura_texto, 10, codigo)

    # Onde jogar (para a família, em casa)
    pdf.set_font("helvetica", "B", 8)
    pdf.set_text_color(60, 60, 60)
    pdf.set_xy(x + 3.5, y + 42)
    pdf.cell(largura_texto, 4, _latin1(f"Jogue em casa: {_endereco_app()}"))

    # Rodapé
    pdf.set_font("helvetica", "I", 6.5)
    pdf.set_text_color(140, 140, 140)
    pdf.set_xy(x + 3.5, y + _ALTURA_CARTAO - 9)
    pdf.cell(_LARGURA_CARTAO - 8, 3.5,
             _latin1(f"Apelido no jogo: {cartao['apelido']}"))
    pdf.set_xy(x + 3.5, y + _ALTURA_CARTAO - 5.5)
    pdf.cell(_LARGURA_CARTAO - 8, 3.5,
             "Guarde este cartao como um tesouro!")


def _pagina_professor(pdf, escola_nome: str, turma_nome: str, cor: str,
                      cartoes: list[dict]) -> None:
    """Página final — cola de consulta rápida (não pendurar no mural)."""
    r, g, b = _hex_para_rgb(cor)
    pdf.add_page()
    pdf.set_fill_color(r, g, b)
    pdf.rect(0, 0, 210, 20, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("helvetica", "B", 13)
    pdf.set_xy(10, 5)
    pdf.cell(0, 6, _latin1("SO DO PROFESSOR - nao pendurar no mural"))
    pdf.set_font("helvetica", "", 9)
    pdf.set_xy(10, 12)
    pdf.cell(0, 5, _latin1(f"{escola_nome} - {turma_nome} - códigos de acesso"))

    # Tabela nome → código
    pdf.set_y(26)
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("helvetica", "B", 9)
    pdf.set_fill_color(238, 238, 238)
    pdf.cell(120, 7, "Aluno", border=1, fill=True)
    pdf.cell(50, 7, _latin1("Código"), border=1, fill=True)
    pdf.ln()
    pdf.set_font("helvetica", "", 9)
    for cartao in cartoes:
        nome = _latin1(cartao["nome"])
        while pdf.get_string_width(nome) > 116 and len(nome) > 4:
            nome = nome[:-4] + "..."
        pdf.cell(120, 6.5, nome, border=1)
        pdf.set_font("courier", "B", 10)
        pdf.cell(50, 6.5, _latin1(cartao["codigo"]), border=1)
        pdf.set_font("helvetica", "", 9)
        pdf.ln()

    # Roteiro da primeira aula
    pdf.ln(4)
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(0, 6, "Primeira aula em 3 passos")
    pdf.ln(7)
    pdf.set_font("helvetica", "", 9)
    passos = [
        f"1. Abra {_endereco_app()} nos tablets (ou aponte a camera para o QR do cartao).",
        "2. Cada crianca digita o proprio codigo e confirma 'Sou eu!'. Na primeira vez,",
        "   ela escolhe como quer ser chamada e a cor do traje do astronauta.",
        "3. Cartao perdido? Consulte o codigo nesta folha - ele nao muda. So gere cartoes",
        "   com 'regenerar' se um QR cair em maos erradas (isso troca o QR de todos).",
    ]
    for linha in passos:
        pdf.cell(0, 5.5, _latin1(linha))
        pdf.ln()


def gerar_cartoes_pdf(escola_nome: str, cor: str, turma_nome: str,
                      cartoes: list[dict],
                      com_pagina_professor: bool = True) -> bytes:
    """`cartoes`: [{nome, apelido, codigo, qr_url}, …]"""
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
    elif com_pagina_professor:
        _pagina_professor(pdf, escola_nome, turma_nome, cor, cartoes)

    return bytes(pdf.output())
