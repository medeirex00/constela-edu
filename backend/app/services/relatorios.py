"""Exportação de relatórios (PRD §86–§103): CSV, Excel e PDF + certificados.

Todos os formatos partem das mesmas linhas (cabeçalho + dados), garantindo
que CSV, Excel e PDF nunca divirjam. A identidade visual (nome da escola e
cor primária configurável) aparece no Excel e no PDF.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Aluno, Escola, Leitura, Livro, Matricula, Nota, Turma
from app.services import scoring

COR_PRIMARIA_PADRAO = "#1B2A4A"  # azul profundo da marca Constela Edu


def cor_primaria(db: Session, escola_id: int) -> str:
    aparencia = scoring.obter_config(db, escola_id, "aparencia", "valores", {})
    cor = str(aparencia.get("cor_primaria") or COR_PRIMARIA_PADRAO)
    if not cor.startswith("#") or len(cor) != 7:
        return COR_PRIMARIA_PADRAO
    return cor


# ---------------------------------------------------------------------------
# Fontes de dados (mesmas linhas para todos os formatos)
# ---------------------------------------------------------------------------

def linhas_ranking(db: Session, escola_id: int) -> tuple[list[str], list[list]]:
    escola = db.get(Escola, escola_id)
    linhas = db.execute(
        select(Nota, Aluno, Turma)
        .join(Aluno, Nota.aluno_id == Aluno.id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id)
              & (Matricula.ano_letivo == escola.ano_letivo_ativo))
        .join(Turma, Matricula.turma_id == Turma.id)
        # Aluno.status: relatório exportado não inclui alunos arquivados/excluídos.
        .where(Nota.escola_id == escola_id, Nota.ano_letivo == escola.ano_letivo_ativo,
               Aluno.status == "ativo")
        .order_by(Nota.posicao)
    ).all()
    cabecalho = ["Posição", "Aluno", "Turma", "Série", "Nota Matific",
                 "Nota Elefante", "Nota Geral"]
    return cabecalho, [
        [nota.posicao, aluno.nome, turma.nome, turma.ano_escolar,
         nota.nota_matific, nota.nota_elefante, nota.nota_geral]
        for nota, aluno, turma in linhas
    ]


def linhas_alunos(db: Session, escola_id: int) -> tuple[list[str], list[list]]:
    escola = db.get(Escola, escola_id)
    linhas = db.execute(
        select(Aluno, Turma)
        .join(Matricula, (Matricula.aluno_id == Aluno.id)
              & (Matricula.ano_letivo == escola.ano_letivo_ativo))
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Aluno.escola_id == escola_id, Aluno.status == "ativo")
        .order_by(Turma.nome, Aluno.nome)
    ).all()
    cabecalho = ["Aluno", "Turma", "Série", "Nº de chamada", "Situação"]
    return cabecalho, [
        [aluno.nome, turma.nome, turma.ano_escolar,
         aluno.numero_chamada or "", aluno.status]
        for aluno, turma in linhas
    ]


def linhas_livros(db: Session, escola_id: int) -> tuple[list[str], list[list]]:
    from sqlalchemy import func

    contagem = dict(db.execute(
        select(Leitura.livro_id, func.count(Leitura.id))
        .where(Leitura.escola_id == escola_id)
        .group_by(Leitura.livro_id)
    ).all())
    livros = db.execute(
        select(Livro).where(Livro.escola_id == escola_id).order_by(Livro.titulo)
    ).scalars().all()
    cabecalho = ["Título", "Autor", "Nível", "Categoria", "Leituras"]
    return cabecalho, [
        [livro.titulo, livro.autor or "", livro.nivel_codigo,
         livro.categoria or "", contagem.get(livro.id, 0)]
        for livro in livros
    ]


FONTES = {
    "ranking": ("Ranking Geral", linhas_ranking),
    "alunos": ("Lista de Alunos", linhas_alunos),
    "livros": ("Catálogo de Livros", linhas_livros),
}


# ---------------------------------------------------------------------------
# Geradores por formato
# ---------------------------------------------------------------------------

def gerar_csv(cabecalho: list[str], linhas: list[list]) -> bytes:
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(cabecalho)
    escritor.writerows(linhas)
    # BOM para o Excel pt-BR abrir com acentuação correta
    return b"\xef\xbb\xbf" + saida.getvalue().encode("utf-8")


def gerar_xlsx(titulo: str, escola_nome: str, cor: str,
               cabecalho: list[str], linhas: list[list]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = titulo[:31]

    cor_hex = cor.lstrip("#").upper()
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cabecalho))
    celula = ws.cell(row=1, column=1, value=f"{escola_nome} — {titulo}")
    celula.font = Font(bold=True, color="FFFFFF", size=13)
    celula.fill = PatternFill("solid", fgColor=cor_hex)
    celula.alignment = Alignment(horizontal="center")

    for coluna, nome in enumerate(cabecalho, start=1):
        celula = ws.cell(row=2, column=coluna, value=nome)
        celula.font = Font(bold=True)
        celula.fill = PatternFill("solid", fgColor="EEEEEE")
    for indice, linha in enumerate(linhas, start=3):
        for coluna, valor in enumerate(linha, start=1):
            ws.cell(row=indice, column=coluna, value=valor)
    for coluna in range(1, len(cabecalho) + 1):
        largura = max(
            [len(str(cabecalho[coluna - 1]))]
            + [len(str(linha[coluna - 1])) for linha in linhas[:200]]
        )
        ws.column_dimensions[ws.cell(row=2, column=coluna).column_letter].width = min(40, largura + 4)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _hex_para_rgb(cor: str) -> tuple[int, int, int]:
    cor = cor.lstrip("#")
    return int(cor[0:2], 16), int(cor[2:4], 16), int(cor[4:6], 16)


def _latin1(texto) -> str:
    """As fontes nativas do PDF só suportam latin-1: os acentos do português
    passam intactos; qualquer outro caractere vira '?' em vez de derrubar o
    relatório inteiro com erro 500."""
    return str(texto).encode("latin-1", "replace").decode("latin-1")


def _couber(pdf, texto, largura: float) -> str:
    """Corta o texto para caber na LARGURA REAL da célula (não em nº fixo de
    letras), terminando com '...' (o '…' não existe em latin-1)."""
    texto = _latin1(texto)
    if pdf.get_string_width(texto) <= largura - 2:
        return texto
    while texto and pdf.get_string_width(texto + "...") > largura - 2:
        texto = texto[:-1]
    return texto + "..."


def _larguras_colunas(pdf, cabecalho: list[str], linhas: list[list],
                      total: float) -> list[float]:
    """Largura proporcional ao conteúdo de cada coluna (com piso), para a
    coluna de nomes — hoje com nomes COMPLETOS da lista de matrículas — não
    ficar espremida como as colunas numéricas."""
    pesos = []
    for i, nome in enumerate(cabecalho):
        maior = pdf.get_string_width(str(nome)) + 4
        for linha in linhas[:300]:
            if i < len(linha):
                maior = max(maior, pdf.get_string_width(_latin1(linha[i])) + 4)
        pesos.append(min(maior, total * 0.45))  # nenhuma coluna domina a página
    fator = total / sum(pesos)
    return [p * fator for p in pesos]


def gerar_pdf(titulo: str, escola_nome: str, cor: str,
              cabecalho: list[str], linhas: list[list]) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    r, g, b = _hex_para_rgb(cor)
    pdf.set_fill_color(r, g, b)
    pdf.rect(0, 0, 210, 22, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("helvetica", "B", 14)
    pdf.set_xy(10, 6)
    pdf.cell(0, 6, _latin1(escola_nome))
    pdf.set_font("helvetica", "", 10)
    pdf.set_xy(10, 13)
    agora = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    pdf.cell(0, 5, _latin1(f"{titulo} - gerado em {agora}"))

    pdf.set_y(28)
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("helvetica", "", 9)
    larguras = _larguras_colunas(pdf, cabecalho, linhas, total=190)

    pdf.set_font("helvetica", "B", 9)
    pdf.set_fill_color(238, 238, 238)
    for nome, largura in zip(cabecalho, larguras):
        pdf.cell(largura, 7, _couber(pdf, nome, largura), border=1, fill=True)
    pdf.ln()

    pdf.set_font("helvetica", "", 9)
    for linha in linhas:
        for valor, largura in zip(linha, larguras):
            pdf.cell(largura, 6.5, _couber(pdf, valor, largura), border=1)
        pdf.ln()

    return bytes(pdf.output())


def gerar_certificado(escola_nome: str, cor: str, aluno_nome: str,
                      turma: str, posicao: int | None, nota_geral: float,
                      ano_letivo: int) -> bytes:
    """Certificado individual em paisagem (PRD §99).

    Renderiza um certificado ELEGANTE (moldura azul-marinho + dourado, logo
    Constela, medalha) via HTML→PDF (Chromium). Se o navegador não estiver
    disponível no ambiente (ex.: CI sem browser), cai para a versão fpdf simples
    — o certificado NUNCA falha por falta do Chromium."""
    try:
        return _certificado_html_pdf(escola_nome, cor, aluno_nome, turma,
                                     posicao, nota_geral, ano_letivo)
    except Exception:  # noqa: BLE001 — sem Chromium/erro de render: usa a reserva
        return _certificado_fpdf(escola_nome, cor, aluno_nome, turma,
                                 posicao, nota_geral, ano_letivo)


# Logo oficial (C) embutida como SVG — a mesma de identidade/logo-oficial.png.
_LOGO_C_SVG = (
    '<svg viewBox="0 0 100 100" width="66" height="66">'
    '<rect width="100" height="100" rx="22" fill="#1B2A4A"/>'
    '<path d="M 67,20.555 A 34,34 0 1 0 67,79.445" fill="none" stroke="#FFFFFF"'
    ' stroke-width="7" stroke-linecap="round"/>'
    '<circle cx="33" cy="79.445" r="4.2" fill="#FFFFFF"/>'
    '<circle cx="16" cy="50" r="4.6" fill="#FFFFFF"/>'
    '<circle cx="33" cy="20.555" r="4.2" fill="#FFFFFF"/>'
    '<circle cx="50" cy="50" r="12.5" fill="#F5B942"/></svg>'
)
_CANTO_SVG = (
    '<svg viewBox="0 0 300 300" class="canto">'
    '<path d="M0,0 L300,0 Q140,8 78,86 Q14,168 0,300 Z" fill="#1B2A4A"/>'
    '<path d="M0,0 L232,0 Q108,12 60,74 Q14,140 0,232 Z" fill="none"'
    ' stroke="#F5B942" stroke-width="5" opacity="0.9"/></svg>'
)
_MEDALHA_SVG = (
    '<svg viewBox="0 0 72 100" width="66" height="92">'
    '<path d="M27 46 L18 82 L31 73 L36 86 L41 73 L54 82 L45 46 Z" fill="#1B2A4A"/>'
    '<circle cx="36" cy="30" r="26" fill="#F5B942" stroke="#1B2A4A" stroke-width="3"/>'
    '<circle cx="36" cy="30" r="19" fill="none" stroke="#1B2A4A" stroke-width="1.5" opacity="0.45"/>'
    '<path d="M36 15 l4.2 9.4 10.3 1 -7.7 6.9 2.4 10.1 -9.2 -5.4 -9.2 5.4 2.4 -10.1'
    ' -7.7 -6.9 10.3 -1 Z" fill="#1B2A4A"/></svg>'
)

_CERT_TEMPLATE = """<style>
  @page { size: A4 landscape; margin: 0; }
  * { margin:0; padding:0; box-sizing:border-box; }
  html,body { width:297mm; height:210mm; -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  body { font-family: Georgia,'Times New Roman',serif; background:#ffffff; position:relative; overflow:hidden; }
  .canto { position:absolute; width:118mm; height:118mm; }
  .c-tl { top:0; left:0; }
  .c-tr { top:0; right:0; transform:scaleX(-1); }
  .c-bl { bottom:0; left:0; transform:scaleY(-1); }
  .c-br { bottom:0; right:0; transform:scale(-1,-1); }
  .frame { position:absolute; inset:11mm; border:2px solid #1B2A4A; }
  .frame::after { content:""; position:absolute; inset:3.5mm; border:1px solid #C9A24B; }
  .conteudo { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center;
              justify-content:flex-start; text-align:center; padding:20mm 40mm 0; }
  .marca { display:flex; flex-direction:column; align-items:center; gap:4px; }
  .marca .nome { font-family:'Trebuchet MS','Segoe UI',sans-serif; font-weight:800; font-size:19px;
                 letter-spacing:1px; color:#1B2A4A; }
  .marca .nome b { color:#F5B942; }
  h1 { font-size:52px; font-weight:700; letter-spacing:8px; color:#1B2A4A; margin-top:14px; }
  .divisor { display:flex; align-items:center; gap:12px; margin:8px 0 14px; color:#C9A24B; }
  .divisor .linha { width:120px; height:1.5px; background:#C9A24B; }
  .divisor .losango { width:9px; height:9px; background:#F5B942; transform:rotate(45deg); }
  .intro { font-size:15px; color:#555; letter-spacing:.5px; }
  .aluno { font-size:40px; font-weight:700; color:#1B2A4A; margin:14px 0 6px; letter-spacing:.5px; text-transform:uppercase; }
  .sublinhado { width:60%; max-width:520px; height:1.5px; background:#C9A24B; margin:0 auto 16px; }
  .detalhe { font-size:15.5px; color:#444; line-height:1.7; max-width:640px; }
  .detalhe b { color:#1B2A4A; }
  .medalha { margin:14px 0 4px; }
  .emitido { font-size:12.5px; color:#666; letter-spacing:.5px; }
  .assinatura { position:absolute; bottom:26mm; left:50%; transform:translateX(-50%); text-align:center; }
  .assinatura .linha { width:230px; height:1px; background:#8a8a8a; margin:0 auto 6px; }
  .assinatura .rotulo { font-size:12.5px; color:#555; }
</style>
⟦CANTOS⟧
<div class="frame"></div>
<div class="conteudo">
  <div class="marca">⟦LOGO⟧<span class="nome">Constela <b>Edu</b></span></div>
  <h1>CERTIFICADO</h1>
  <div class="divisor"><span class="linha"></span><span class="losango"></span><span class="linha"></span></div>
  <p class="intro">A escola ⟦ESCOLA⟧ certifica que</p>
  <p class="aluno">⟦ALUNO⟧</p>
  <div class="sublinhado"></div>
  <p class="detalhe">da turma <b>⟦TURMA⟧</b>, alcançou a nota geral <b>⟦NOTA⟧</b>⟦POSICAO⟧<br>
     no <b>Constela Edu</b> — ano letivo de <b>⟦ANO⟧</b>.</p>
  <div class="medalha">⟦MEDALHA⟧</div>
  <p class="emitido">Emitido em <b>⟦DATA⟧</b></p>
</div>
<div class="assinatura"><div class="linha"></div><div class="rotulo">Direção</div></div>
"""


def _esc_html(texto: str) -> str:
    return (str(texto).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _certificado_html_pdf(escola_nome: str, cor: str, aluno_nome: str,
                          turma: str, posicao: int | None, nota_geral: float,
                          ano_letivo: int) -> bytes:
    """Renderiza o certificado bonito em PDF via Chromium (Playwright)."""
    from playwright.sync_api import sync_playwright

    cantos = "".join(
        _CANTO_SVG.replace('class="canto"', f'class="canto {c}"')
        for c in ("c-tl", "c-tr", "c-bl", "c-br"))
    pos_txt = (f" e a <b>{posicao}ª posição</b> no Ranking Geral" if posicao else "")
    html = (_CERT_TEMPLATE
            .replace("⟦CANTOS⟧", cantos)
            .replace("⟦LOGO⟧", _LOGO_C_SVG)
            .replace("⟦MEDALHA⟧", _MEDALHA_SVG)
            .replace("⟦ESCOLA⟧", _esc_html(escola_nome))
            .replace("⟦ALUNO⟧", _esc_html(aluno_nome))
            .replace("⟦TURMA⟧", _esc_html(turma or "—"))
            .replace("⟦NOTA⟧", f"{nota_geral:.1f}".replace(".", ","))
            .replace("⟦POSICAO⟧", pos_txt)
            .replace("⟦ANO⟧", str(ano_letivo))
            .replace("⟦DATA⟧", datetime.now(timezone.utc).strftime("%d/%m/%Y")))
    doc = f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'></head><body>{html}</body></html>"

    with sync_playwright() as p:
        try:
            navegador = p.chromium.launch()
        except Exception:  # noqa: BLE001 — sem chromium baixado: tenta o Chrome do sistema
            navegador = p.chromium.launch(channel="chrome")
        try:
            pagina = navegador.new_page()
            pagina.set_content(doc, wait_until="networkidle")
            pdf = pagina.pdf(prefer_css_page_size=True, print_background=True,
                             landscape=True)
        finally:
            navegador.close()
    return pdf


def _certificado_fpdf(escola_nome: str, cor: str, aluno_nome: str,
                      turma: str, posicao: int | None, nota_geral: float,
                      ano_letivo: int) -> bytes:
    """Reserva simples (sem navegador): moldura + texto, 100% em Python."""
    from fpdf import FPDF

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_page()
    r, g, b = _hex_para_rgb(cor)

    pdf.set_draw_color(r, g, b)
    pdf.set_line_width(1.2)
    pdf.rect(8, 8, 281, 194)
    pdf.set_line_width(0.3)
    pdf.rect(12, 12, 273, 186)

    pdf.set_text_color(r, g, b)
    pdf.set_font("helvetica", "B", 30)
    pdf.set_y(40)
    pdf.cell(0, 14, "CERTIFICADO", align="C")

    pdf.set_text_color(60, 60, 60)
    pdf.set_font("helvetica", "", 13)
    pdf.set_y(62)
    pdf.cell(0, 8, _latin1(f"A escola {escola_nome} certifica que"), align="C")

    pdf.set_text_color(20, 20, 20)
    pdf.set_font("helvetica", "B", 26)
    pdf.set_y(78)
    # Nomes completos (lista de matrículas) podem ser longos: reduz a fonte
    # até caber na moldura, em vez de vazar pela borda.
    nome_cert = _latin1(aluno_nome)
    while pdf.get_string_width(nome_cert) > 250 and pdf.font_size_pt > 14:
        pdf.set_font_size(pdf.font_size_pt - 2)
    pdf.cell(0, 14, nome_cert, align="C")

    pdf.set_text_color(60, 60, 60)
    pdf.set_font("helvetica", "", 13)
    pdf.set_y(98)
    detalhe = _latin1(
        f"da turma {turma}, alcançou a nota geral {nota_geral:.1f}".replace(".", ","))
    if posicao:
        detalhe += f" e a {posicao}ª posição no Ranking Geral"
    pdf.cell(0, 8, detalhe, align="C")
    pdf.set_y(108)
    pdf.cell(0, 8, f"no Constela Edu - ano letivo de {ano_letivo}.", align="C")

    pdf.set_y(150)
    pdf.set_font("helvetica", "", 11)
    emitido = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    pdf.cell(0, 8, f"Emitido em {emitido}", align="C")

    pdf.set_y(168)
    pdf.set_draw_color(120, 120, 120)
    pdf.line(110, 172, 187, 172)
    pdf.set_y(174)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 6, "Direção", align="C")

    return bytes(pdf.output())
