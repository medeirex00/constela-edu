"""Cartões de acesso do Quest — PDF para o professor imprimir e recortar.

Cada cartão carrega o que a criança precisa para entrar: QR (1 leitura =
entrou) e o código falável — SEM senha (decisão de produto, como no
Elefante Letrado). Layout A4 em grade 2×4 com linhas de corte, mais a parte
final "só do professor" (uma folha ou mais, conforme a turma): tabela nome →
código da turma inteira e o roteiro da primeira aula (cartão perdido deixa de
ser suporte).

Fontes nativas do fpdf2 (Helvetica/Courier), que o PDF declara em WinAnsi
(cp1252): o texto é codificado em cp1252 — que tem o apóstrofo tipográfico
(Sant’Anna), as aspas curvas, o travessão e as reticências — e o que ainda
ficar de fora vira a letra sem o sinal antes de cair no '?' (_texto_pdf).
"""
from __future__ import annotations

import io
import unicodedata
from datetime import datetime, timezone

from app.core.config import settings

_LARGURA_CARTAO = 92.0
_ALTURA_CARTAO = 64.0
_MARGEM_X = 9.0
_MARGEM_Y = 10.0
_ESPACO = 4.0


_CODIFICACAO = "windows-1252"
# Letras sem decomposição Unicode que não existem no cp1252.
_SEM_SINAL = str.maketrans({"Ł": "L", "ł": "l", "Đ": "D", "đ": "d", "ı": "i",
                            "Ħ": "H", "ħ": "h", "‐": "-", "‑": "-", "−": "-"})


def _cabe(caractere: str) -> bool:
    try:
        caractere.encode(_CODIFICACAO)
    except UnicodeEncodeError:
        return False
    return True


def _texto_pdf(texto) -> str:
    """Texto pronto para as fontes nativas em cp1252. Acento digitado à parte
    (forma decomposta, NFD) é juntado à letra antes; caractere fora do cp1252 vira
    a letra sem o sinal (ő → o, Ł → L); invisível (formatação ou sinal solto)
    some; só o que não tem equivalente vira '?' — nunca erro 500."""
    saida = []
    for caractere in unicodedata.normalize("NFC", str(texto)).translate(_SEM_SINAL):
        if _cabe(caractere):
            saida.append(caractere)
            continue
        base = "".join(c for c in unicodedata.normalize("NFKD", caractere)
                       if unicodedata.category(c) != "Mn")
        if base and all(_cabe(c) for c in base):
            saida.append(base)
        elif unicodedata.category(caractere) not in ("Cf", "Mn", "Me"):
            saida.append("?")
    return "".join(saida)


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


def _quebrar_em_linhas(pdf, texto: str, largura: float,
                       max_linhas: int) -> list[str]:
    """Quebra ``texto`` por palavra em até ``max_linhas`` linhas que cabem em
    ``largura`` (na fonte atual). Palavra maior que a linha é cortada por letra; o
    que sobrar depois da última linha vira "..." no fim dela."""
    resto = texto.split()
    linhas: list[str] = []
    while resto and len(linhas) < max_linhas:
        linha = resto.pop(0)
        if pdf.get_string_width(linha) > largura:
            corte = len(linha) - 1
            while corte > 1 and pdf.get_string_width(linha[:corte]) > largura:
                corte -= 1
            resto.insert(0, linha[corte:])
            linha = linha[:corte]
        while resto and pdf.get_string_width(f"{linha} {resto[0]}") <= largura:
            linha = f"{linha} {resto.pop(0)}"
        linhas.append(linha)
    if resto and linhas:
        ultima = linhas[-1]
        while len(ultima) > 1 and pdf.get_string_width(ultima.rstrip() + "...") > largura:
            ultima = ultima[:-1]
        linhas[-1] = ultima.rstrip() + "..."
    return linhas


def _nome_em_duas_linhas(pdf, nome: str, x: float, y: float,
                         largura: float) -> None:
    """Nome que não cabe numa linha nem a 7 pt: duas linhas, no maior tamanho
    (de 9 a 7 pt) em que ele sai inteiro; a 7 pt, o que ainda sobrar vira "...".
    Ocupa de ``y`` a ``y`` + 8 mm, acima do "Meu codigo magico:" (``y`` + 9,5)."""
    pdf.set_font_size(9)
    while (pdf.font_size_pt > 7
           and _quebrar_em_linhas(pdf, nome, largura, 3)[2:]):
        pdf.set_font_size(pdf.font_size_pt - 0.5)
    for indice, linha in enumerate(_quebrar_em_linhas(pdf, nome, largura, 2)):
        pdf.set_xy(x, y + indice * 4)
        pdf.cell(largura, 4, linha)


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
    pdf.cell(0, 3, _texto_pdf(f"{escola_nome} - {turma_nome}"))

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

    # Nome do aluno: encolhe até caber numa linha (até 7 pt). O fpdf2 não corta o
    # texto que passa da célula: o que não cabe nem a 7 pt quebra em duas linhas e,
    # se ainda sobrar, termina em "..." — nunca invade o QR à direita.
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("helvetica", "B", 11)
    nome = _texto_pdf(cartao["nome"])
    while pdf.get_string_width(nome) > largura_texto and pdf.font_size_pt > 7:
        pdf.set_font_size(pdf.font_size_pt - 0.5)
    if pdf.get_string_width(nome) <= largura_texto:
        pdf.set_xy(x + 3.5, y + 12.5)
        pdf.cell(largura_texto, 5, nome)
    else:
        _nome_em_duas_linhas(pdf, nome, x + 3.5, y + 12.5, largura_texto)

    # Código falável, o herói do cartão — bem grande
    pdf.set_font("helvetica", "", 8)
    pdf.set_text_color(110, 110, 110)
    pdf.set_xy(x + 3.5, y + 22)
    pdf.cell(largura_texto, 4, "Meu codigo magico:")
    pdf.set_font("courier", "B", 21)
    pdf.set_text_color(r, g, b)
    pdf.set_xy(x + 3.5, y + 27)
    codigo = _texto_pdf(cartao["codigo"])
    while pdf.get_string_width(codigo) > largura_texto and pdf.font_size_pt > 12:
        pdf.set_font_size(pdf.font_size_pt - 1)
    pdf.cell(largura_texto, 10, codigo)

    # Onde jogar (para a família, em casa)
    pdf.set_font("helvetica", "B", 8)
    pdf.set_text_color(60, 60, 60)
    pdf.set_xy(x + 3.5, y + 42)
    pdf.cell(largura_texto, 4, _texto_pdf(f"Jogue em casa: {_endereco_app()}"))

    # Rodapé
    pdf.set_font("helvetica", "I", 6.5)
    pdf.set_text_color(140, 140, 140)
    pdf.set_xy(x + 3.5, y + _ALTURA_CARTAO - 9)
    pdf.cell(_LARGURA_CARTAO - 8, 3.5,
             _texto_pdf(f"Apelido no jogo: {cartao['apelido']}"))
    pdf.set_xy(x + 3.5, y + _ALTURA_CARTAO - 5.5)
    pdf.cell(_LARGURA_CARTAO - 8, 3.5,
             "Guarde este cartao como um tesouro!")


# Parte do professor: a quebra automática do PDF fica desligada (a grade dos
# cartões é posicionada à mão), então a quebra aqui também é manual — nada é
# desenhado abaixo de _LIMITE_INFERIOR (A4 de 297 mm, margem de 10 mm). O que
# passasse da folha continuaria no arquivo, mas sumiria da tela e da impressão.
_LIMITE_INFERIOR = 297.0 - 10.0
_ALTURA_LINHA_TABELA = 6.5
_ALTURA_LINHA_ROTEIRO = 5.5


def _folha_professor(pdf, escola_nome: str, turma_nome: str, cor: str,
                     continuacao: bool) -> None:
    """Abre uma folha da parte do professor com a faixa do topo. Toda folha leva
    o aviso: impressas, elas se separam."""
    r, g, b = _hex_para_rgb(cor)
    pdf.add_page()
    pdf.set_fill_color(r, g, b)
    pdf.rect(0, 0, 210, 20, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("helvetica", "B", 13)
    pdf.set_xy(10, 5)
    titulo = "SO DO PROFESSOR - nao pendurar no mural"
    pdf.cell(0, 6, _texto_pdf(titulo + (" (continuacao)" if continuacao else "")))
    pdf.set_font("helvetica", "", 9)
    pdf.set_xy(10, 12)
    pdf.cell(0, 5, _texto_pdf(f"{escola_nome} - {turma_nome} - códigos de acesso"))
    pdf.set_y(26)
    pdf.set_text_color(30, 30, 30)


def _cabecalho_tabela(pdf) -> None:
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("helvetica", "B", 9)
    pdf.set_fill_color(238, 238, 238)
    pdf.cell(120, 7, "Aluno", border=1, fill=True)
    pdf.cell(50, 7, _texto_pdf("Código"), border=1, fill=True)
    pdf.ln()
    pdf.set_font("helvetica", "", 9)


def _pagina_professor(pdf, escola_nome: str, turma_nome: str, cor: str,
                      cartoes: list[dict]) -> None:
    """Parte final — cola de consulta rápida (não pendurar no mural). Ocupa
    quantas folhas a turma pedir: a tabela nome → código continua na folha
    seguinte (faixa e cabeçalho de novo, 39 linhas por folha) e o roteiro da 1ª
    aula vai inteiro para a seguinte quando não cabe abaixo da tabela."""
    _folha_professor(pdf, escola_nome, turma_nome, cor, continuacao=False)

    # Tabela nome → código
    _cabecalho_tabela(pdf)
    for cartao in cartoes:
        if pdf.get_y() + _ALTURA_LINHA_TABELA > _LIMITE_INFERIOR:
            _folha_professor(pdf, escola_nome, turma_nome, cor, continuacao=True)
            _cabecalho_tabela(pdf)
        nome = _texto_pdf(cartao["nome"])
        while pdf.get_string_width(nome) > 116 and len(nome) > 4:
            nome = nome[:-4] + "..."
        pdf.cell(120, _ALTURA_LINHA_TABELA, nome, border=1)
        pdf.set_font("courier", "B", 10)
        pdf.cell(50, _ALTURA_LINHA_TABELA, _texto_pdf(cartao["codigo"]), border=1)
        pdf.set_font("helvetica", "", 9)
        pdf.ln()

    # Roteiro da primeira aula — inteiro na mesma folha
    passos = [
        f"1. Abra {_endereco_app()} nos tablets (ou aponte a camera para o QR do cartao).",
        "2. Cada crianca digita o proprio codigo e confirma 'Sou eu!'. Na primeira vez,",
        "   ela escolhe como quer ser chamada e a cor do traje do astronauta.",
        # A ação do menu do aluno no painel da turma (TurmaDetalhe.tsx) regenera o
        # cartão individual: troca código E QR (o cartão traz os dois), o que revoga.
        "3. Esqueceu o cartao? Consulte o codigo nesta folha. Perdeu ou caiu em maos erradas?",
        "   Use 'Novo cartao do Quest' no menu do aluno, na turma: codigo e QR novos; os antigos param de entrar.",
    ]
    altura_roteiro = 4 + 7 + len(passos) * _ALTURA_LINHA_ROTEIRO
    if pdf.get_y() + altura_roteiro > _LIMITE_INFERIOR:
        _folha_professor(pdf, escola_nome, turma_nome, cor, continuacao=True)
    pdf.ln(4)
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(0, 6, "Primeira aula em 3 passos")
    pdf.ln(7)
    pdf.set_font("helvetica", "", 9)
    for linha in passos:
        pdf.cell(0, _ALTURA_LINHA_ROTEIRO, _texto_pdf(linha))
        pdf.ln()


def gerar_cartoes_pdf(escola_nome: str, cor: str, turma_nome: str,
                      cartoes: list[dict],
                      com_pagina_professor: bool = True) -> bytes:
    """`cartoes`: [{nome, apelido, codigo, qr_url}, …]"""
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.core_fonts_encoding = _CODIFICACAO
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
            pdf.cell(0, 4, _texto_pdf(
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
