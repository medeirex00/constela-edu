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

COR_PRIMARIA_PADRAO = "#4F46E5"  # índigo do tema


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
        .where(Nota.escola_id == escola_id, Nota.ano_letivo == escola.ano_letivo_ativo)
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
    pdf.cell(0, 6, escola_nome)
    pdf.set_font("helvetica", "", 10)
    pdf.set_xy(10, 13)
    agora = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    pdf.cell(0, 5, f"{titulo} - gerado em {agora}")

    pdf.set_y(28)
    pdf.set_text_color(30, 30, 30)
    largura_total = 190
    largura = largura_total / len(cabecalho)

    pdf.set_font("helvetica", "B", 9)
    pdf.set_fill_color(238, 238, 238)
    for nome in cabecalho:
        pdf.cell(largura, 7, str(nome), border=1, fill=True)
    pdf.ln()

    pdf.set_font("helvetica", "", 9)
    for linha in linhas:
        for valor in linha:
            texto = str(valor)
            if len(texto) > 28:
                texto = texto[:27] + "…"
            pdf.cell(largura, 6.5, texto, border=1)
        pdf.ln()

    return bytes(pdf.output())


def gerar_certificado(escola_nome: str, cor: str, aluno_nome: str,
                      turma: str, posicao: int | None, nota_geral: float,
                      ano_letivo: int) -> bytes:
    """Certificado individual em paisagem (PRD §99)."""
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
    pdf.cell(0, 8, f"A escola {escola_nome} certifica que", align="C")

    pdf.set_text_color(20, 20, 20)
    pdf.set_font("helvetica", "B", 26)
    pdf.set_y(78)
    pdf.cell(0, 14, aluno_nome, align="C")

    pdf.set_text_color(60, 60, 60)
    pdf.set_font("helvetica", "", 13)
    pdf.set_y(98)
    detalhe = f"da turma {turma}, alcançou a nota geral {nota_geral:.1f}".replace(".", ",")
    if posicao:
        detalhe += f" e a {posicao}ª posição no Ranking Geral"
    pdf.cell(0, 8, detalhe, align="C")
    pdf.set_y(108)
    pdf.cell(0, 8, f"no Sistema de Gestão e Premiação Escolar - ano letivo de {ano_letivo}.", align="C")

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
