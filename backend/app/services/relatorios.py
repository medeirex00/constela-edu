"""Exportação de relatórios (PRD §86–§103): CSV, Excel e PDF + certificados.

Todos os formatos partem das mesmas linhas (cabeçalho + dados), garantindo
que CSV, Excel e PDF nunca divirjam. A identidade visual (nome da escola e
cor primária configurável) aparece no Excel e no PDF.
"""
from __future__ import annotations

import base64
import csv
import io
import logging
import mimetypes
import os
import re
import threading
from contextlib import contextmanager
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tempo import agora_br

from app.models import (Aluno, Escola, Leitura, Livro, Matricula, Nota,
                        SnapshotElefante, Turma)
from app.services import bimestres, elegibilidade, grupo_pequeno, scoring

_log = logging.getLogger(__name__)

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

def _recorte(consulta, turma_ids: list[int] | None):
    """Professor: só as matrículas (do ano ativo, já no join) cuja TURMA é uma
    das dele — comparando o ID da turma da matrícula. O nome da turma não serve
    de chave: nomes se repetem entre anos, e uma matrícula do ano ativo pode
    apontar para uma turma de outro ano com o nome de uma turma atual de outra
    pessoa. É o mesmo critério da evolução (`permissoes.alunos_permitidos`) e
    dos cartões do cartaz (`estatisticas_cartaz`). ``None`` = sem recorte
    (gestão); lista vazia = nenhuma linha."""
    if turma_ids is None:
        return consulta
    return consulta.where(Matricula.turma_id.in_(turma_ids))


def _consulta_ranking_geral(db: Session, escola_id: int,
                            turma_ids: list[int] | None = None):
    """``select(Nota, Aluno, Turma)`` de quem está no Ranking Geral exportado (sem
    ordem) — a fonte ÚNICA das linhas (``linhas_ranking``) e da população dos
    cartões do cartaz (``estatisticas_cartaz``), para os dois nunca divergirem.
    ``turma_ids`` (professor): só as matrículas do ano ativo nessas turmas —
    recorte pelo ID da turma da matrícula, nunca pelo nome (ver ``_recorte``)."""
    escola = db.get(Escola, escola_id)
    consulta = (
        select(Nota, Aluno, Turma)
        .join(Aluno, Nota.aluno_id == Aluno.id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id)
              & (Matricula.ano_letivo == escola.ano_letivo_ativo))
        .join(Turma, Matricula.turma_id == Turma.id)
        # Aluno.status: relatório exportado não inclui alunos arquivados/excluídos.
        .where(Nota.escola_id == escola_id, Nota.ano_letivo == escola.ano_letivo_ativo,
               Aluno.status == "ativo")
        # AS FASES NÃO CONCORREM (`services.elegibilidade`): a Nota antiga da
        # Educação Infantil (o recálculo não a apaga) não pode voltar no arquivo
        # nem no cartaz — a mesma régua de `rankings._ranking`.
        .where(Matricula.turma_id.in_(elegibilidade.turmas_premiaveis(
            db, escola_id, escola.ano_letivo_ativo)))
    )
    return _recorte(consulta, turma_ids)


def linhas_ranking(db: Session, escola_id: int,
                   turma_ids: list[int] | None = None) -> tuple[list[str], list[list]]:
    """``turma_ids`` (professor): só as matrículas do ano ativo nessas turmas —
    recorte pelo ID da turma da matrícula, nunca pelo nome (ver ``_recorte``).

    A nota da plataforma que a criança NÃO USA (sem retrato: ``Nota.aferido_*``
    falso) sai ``None`` — célula vazia no CSV/Excel, "—" no cartaz e "-" na
    reserva do PDF —, como a tela (``notaDaMateria``): a coluna vale 0.0 tanto
    para quem não usa quanto para o zero legítimo, e imprimir 0,0 afirmaria
    desempenho onde só há ausência de dado (``rankings._ranking``). A Nota Geral
    e a posição não mudam."""
    linhas = db.execute(_consulta_ranking_geral(db, escola_id, turma_ids)
                        .order_by(Nota.posicao)).all()
    cabecalho = ["Posição", "Aluno", "Turma", "Série", "Nota Matific",
                 "Nota Elefante", "Nota Geral"]
    return cabecalho, [
        [nota.posicao, aluno.nome, turma.nome, turma.ano_escolar,
         nota.nota_matific if nota.aferido_matematica else None,
         nota.nota_elefante if nota.aferido_leitura else None,
         nota.nota_geral]
        for nota, aluno, turma in linhas
    ]


def linhas_alunos(db: Session, escola_id: int,
                  turma_ids: list[int] | None = None) -> tuple[list[str], list[list]]:
    """``turma_ids``: o mesmo recorte do professor de ``linhas_ranking``."""
    escola = db.get(Escola, escola_id)
    consulta = (
        select(Aluno, Turma)
        .join(Matricula, (Matricula.aluno_id == Aluno.id)
              & (Matricula.ano_letivo == escola.ano_letivo_ativo))
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Aluno.escola_id == escola_id, Aluno.status == "ativo")
        .order_by(Turma.nome, Aluno.nome)
    )
    linhas = db.execute(_recorte(consulta, turma_ids)).all()
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

# Coluna de nota de PLATAFORMA do Ranking Geral → módulo contratado que a
# sustenta (``services/modulos``). Módulo fora do plano = a coluna não sai.
COLUNA_NOTA_MODULO = {"Nota Matific": "matematica", "Nota Elefante": "leitura"}


def sem_notas_fora_do_plano(cabecalho: list[str], linhas: list[list],
                            modulos: set[str]) -> tuple[list[str], list[list]]:
    """Tira do Ranking exportado as colunas de nota das plataformas cujo módulo a
    rede NÃO contratou (o módulo não existe para ela — nem na tela, nem no
    arquivo). As demais colunas, a ordem e as linhas ficam iguais; com tudo
    contratado devolve exatamente o que recebeu."""
    manter = [i for i, nome in enumerate(cabecalho)
              if COLUNA_NOTA_MODULO.get(nome) is None or COLUNA_NOTA_MODULO[nome] in modulos]
    if len(manter) == len(cabecalho):
        return cabecalho, linhas
    return ([cabecalho[i] for i in manter],
            [[linha[i] for i in manter if i < len(linha)] for linha in linhas])


# ---------------------------------------------------------------------------
# Geradores por formato
# ---------------------------------------------------------------------------

# INJEÇÃO DE FÓRMULA (CSV/XLSX): texto que começa com um destes caracteres vira
# FÓRMULA VIVA quando o arquivo é aberto no Excel/LibreOffice. Nome de aluno, de
# turma, título de livro... são digitados por gestor, Lista Piloto ou plataforma
# externa (sync); um nome "=HYPERLINK(...&B4&B5)" levaria, no clique, os nomes das
# crianças das linhas vizinhas para um servidor de terceiros (e97).
_INICIO_DE_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def celula_segura(valor):
    """O valor pronto para uma célula de CSV: o TEXTO que a planilha interpretaria
    como fórmula ganha um apóstrofo na frente (a neutralização da OWASP). Só ``str``
    muda — número negativo continua número."""
    if isinstance(valor, str) and valor.startswith(_INICIO_DE_FORMULA):
        return "'" + valor
    return valor


def _celula_xlsx(ws, linha: int, coluna: int, valor):
    """``ws.cell`` que nunca grava fórmula: o openpyxl transforma em fórmula todo
    ``str`` que começa com '=' — aqui ele fica TEXTO (data_type 's'). '+', '-', '@' e
    os de controle já são gravados como texto pelo openpyxl, que o Excel não avalia.

    Caractere de controle C0 que o Excel não aceita (``ILLEGAL_CHARACTERS_RE``: um
    nome colado de um PDF, vindo da plataforma...) sai do texto ANTES de gravar —
    o openpyxl levantava ``IllegalCharacterError`` e UM nome derrubava a exportação
    da escola inteira. A limpeza vem antes da proteção contra fórmula, que vale
    para o texto já limpo."""
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    if isinstance(valor, str):
        valor = ILLEGAL_CHARACTERS_RE.sub("", valor)
    celula = ws.cell(row=linha, column=coluna, value=valor)
    if isinstance(valor, str) and celula.data_type == "f":
        celula.data_type = "s"
    return celula


def gerar_csv(cabecalho: list[str], linhas: list[list]) -> bytes:
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow([celula_segura(v) for v in cabecalho])
    escritor.writerows([celula_segura(v) for v in linha] for linha in linhas)
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
    celula = _celula_xlsx(ws, 1, 1, f"{escola_nome} — {titulo}")
    celula.font = Font(bold=True, color="FFFFFF", size=13)
    celula.fill = PatternFill("solid", fgColor=cor_hex)
    celula.alignment = Alignment(horizontal="center")

    for coluna, nome in enumerate(cabecalho, start=1):
        celula = _celula_xlsx(ws, 2, coluna, nome)
        celula.font = Font(bold=True)
        celula.fill = PatternFill("solid", fgColor="EEEEEE")
    for indice, linha in enumerate(linhas, start=3):
        for coluna, valor in enumerate(linha, start=1):
            _celula_xlsx(ws, indice, coluna, valor)
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


_ROTULO_DIMENSAO = {"leitura": "Leitura", "matematica": "Matemática"}


def legenda_data_dos_dados(frescor: dict | None, dimensoes) -> str | None:
    """DE QUANDO é o dado de um documento de ranking (cartaz, certificado).

    ``"Dados das plataformas: Leitura de 19/10/2026; Matemática de 18/10/2026"``
    — a data do retrato mais recente de quem concorre, por dimensão: a MESMA do
    selo de frescor da tela (``services.frescor_ranking``, dia de Brasília). Um
    cartaz impresso com a coleta parada há três semanas tinha a mesma cara de um
    de ontem; a data de emissão não diz isso. Nenhuma fórmula muda.

    Só dimensões contratadas; sem retrato, "sem dados"; acima do limite do selo,
    "(mais de N dias)". Texto latin-1 puro (a reserva do PDF usa as fontes
    nativas do fpdf: nada de reticências, travessão ou aspas curvas). ``None``
    quando não há o que declarar (frescor indisponível)."""
    if not frescor:
        return None
    limite = frescor.get("limite_dias")
    partes = []
    for dimensao in dimensoes:
        bloco = (frescor.get("dimensoes") or {}).get(dimensao) or {}
        if not bloco.get("contratada"):
            continue
        rotulo = _ROTULO_DIMENSAO.get(dimensao, dimensao)
        dia = bloco.get("dado_mais_recente_em")
        if not dia:
            partes.append(f"{rotulo} sem dados")
            continue
        ano, mes, d = str(dia)[:10].split("-")
        texto = f"{rotulo} de {d}/{mes}/{ano}"
        if bloco.get("estado") == "desatualizado" and limite:
            texto += f" (mais de {limite} dias)"
        elif bloco.get("estado") == "parcial" and bloco.get("dado_mais_antigo_em"):
            # Parte de quem concorre tem dado ANTIGO (turma cuja coleta parou): a
            # data do retrato mais recente sozinha escondia isso no papel.
            a_ano, a_mes, a_d = str(bloco["dado_mais_antigo_em"])[:10].split("-")
            texto += f" (parte com dado de {a_d}/{a_mes}/{a_ano})"
        partes.append(texto)
    if not partes:
        return None
    return _latin1("Dados das plataformas: " + "; ".join(partes))


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
              cabecalho: list[str], linhas: list[list],
              nota_dados: str | None = None) -> bytes:
    """PDF simples de tabela (fpdf). ``nota_dados`` = a linha "Dados das
    plataformas: ..." (``legenda_data_dos_dados``) logo abaixo da faixa. Valor
    ausente (``None`` — ex.: nota da plataforma que a criança não usa) sai "-"
    (o "—" não existe nas fontes latin-1), nunca "None"."""
    from fpdf import FPDF

    linhas = [["-" if valor is None else valor for valor in linha] for linha in linhas]
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
    agora = agora_br().strftime("%d/%m/%Y")
    pdf.cell(0, 5, _latin1(f"{titulo} - gerado em {agora}"))

    pdf.set_y(28)
    if nota_dados:
        pdf.set_text_color(70, 70, 70)
        pdf.set_font("helvetica", "", 8.5)
        pdf.set_xy(10, 24.5)
        pdf.cell(0, 4, _couber(pdf, nota_dados, 190))
        pdf.set_y(30)
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
                      ano_letivo: int, logos: tuple[str, str] | None = None,
                      dados_em: str | None = None) -> bytes:
    """Certificado individual em paisagem (PRD §99).

    Renderiza um certificado ELEGANTE (moldura azul-marinho + dourado, logo
    Constela, medalha) via HTML→PDF (Chromium). Se o navegador não estiver
    disponível no ambiente (ex.: CI sem browser), cai para a versão fpdf simples
    — o certificado NUNCA falha por falta do Chromium.

    ``dados_em`` = a linha "Dados das plataformas: ..." (``legenda_data_dos_dados``)
    impressa sob a data de emissão: a posição e a nota são as do ranking
    calculado com aquele dado, e a data de emissão sozinha não diz de quando ele é."""
    try:
        return _certificado_html_pdf(escola_nome, cor, aluno_nome, turma,
                                     posicao, nota_geral, ano_letivo, logos,
                                     dados_em=dados_em)
    except Exception:  # noqa: BLE001 — sem Chromium/erro de render: usa a reserva
        return _certificado_fpdf(escola_nome, cor, aluno_nome, turma,
                                 posicao, nota_geral, ano_letivo, dados_em=dados_em)


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

# ---------------------------------------------------------------------------
# Logos institucionais (cidade / prefeitura) — OPCIONAIS, enviados POR ESCOLA em
# Configurações → Aparência. Quando existem, entram no cabeçalho dos documentos
# "de vitrine" (certificado e cartaz do ranking): brasão à esquerda, marca
# Constela ao centro, prefeitura à direita. NÃO há logo de cidade embutido no
# software — sem upload da escola, aparece só a marca Constela.
# ---------------------------------------------------------------------------
_MARCA_DIR = Path(__file__).resolve().parent.parent / "marca"


def _asset_data_uri(nome: str) -> str:
    """data: URI de um arquivo de app/marca/ (ou '' se não existir).

    Sem cache de propósito: os arquivos são lidos a cada documento (leitura de
    poucos KB, rara — o gargalo é o Chromium), para que trocar/adicionar um logo
    na pasta tenha efeito imediato, sem precisar reiniciar o processo."""
    try:
        dados = (_MARCA_DIR / nome).read_bytes()
    except OSError:
        return ""
    mime = mimetypes.guess_type(nome)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(dados).decode("ascii")


def logos_da_escola(db: Session, escola_id: int) -> tuple[str, str]:
    """(brasão, prefeitura) DESTA escola como data URIs, se foram enviados em
    Configurações → Aparência. Strings vazias quando não há — nesse caso os
    documentos saem só com a marca Constela (não existe logo de cidade embutido)."""
    cfg = scoring.obter_config(db, escola_id, "aparencia", "logos", {})
    return (str(cfg.get("brasao_data_uri") or ""),
            str(cfg.get("prefeitura_data_uri") or ""))


def _cabecalho_logos(logos: tuple[str, str] | None = None) -> str:
    """Cabeçalho com até 3 logos (brasão · Constela · prefeitura).

    Os logos da CIDADE saem SÓ do que a própria escola enviou em Configurações →
    Aparência — não há mais logo de cidade embutido no software. Escola sem logo
    próprio: aparece só a marca Constela (o produto segue genérico para qualquer
    cidade — cada escola sobe o seu)."""
    brasao, prefeitura = logos or ("", "")
    esq = f'<img class="logo-cidade" src="{brasao}" alt="Brasão da cidade">' if brasao else ""
    dire = f'<img class="logo-pref" src="{prefeitura}" alt="Prefeitura">' if prefeitura else ""
    return (f'<div class="cabecalho">{esq}'
            f'<div class="constela">{_LOGO_C_SVG}'
            f'<span class="nome">Constela <b>Edu</b></span></div>'
            f'{dire}</div>')


# Ícones (SVG dourado) das colunas de nota do cartaz do ranking.
_IC_STAR = ('<svg class="ic" width="13" height="13" viewBox="0 0 24 24">'
            '<path d="M12 2l2.9 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77 5.82 21'
            'l1.18-6.88-5-4.87 6.9-1.01z" fill="#F5B841"/></svg>')
_IC_TROFEU = ('<svg class="ic" width="13" height="13" viewBox="0 0 24 24" fill="#F5B841">'
              '<path d="M18 3H6v2H3v3a4 4 0 0 0 4 4 5 5 0 0 0 4 3v2H8v2h8v-2h-3v-2'
              'a5 5 0 0 0 4-3 4 4 0 0 0 4-4V5h-3zM5 8V7h1v3a2 2 0 0 1-1-2zm14 0'
              'a2 2 0 0 1-1 2V7h1z"/></svg>')
_IC_ELEFANTE = ('<svg class="ic" width="15" height="14" viewBox="0 0 34 32" fill="#F5B841">'
                '<ellipse cx="8" cy="14" rx="7" ry="9"/>'
                '<ellipse cx="26" cy="14" rx="7" ry="9"/>'
                '<circle cx="17" cy="14" r="10.5"/>'
                '<path d="M13.5 17h7v6.5a3 3 0 0 0 6 0v-1.2a1.1 1.1 0 0 0-2.2 0v1.2'
                'a0.8 0.8 0 0 1-1.6 0V17z"/></svg>')


def _fmt_nota(valor) -> str:
    """Nota 0–100 com uma casa e vírgula decimal ('85,3'); '—' se vazia.

    O 5 arredonda PARA CIMA (87,25 → '87,3'), a partir do número como foi gravado
    (as notas têm 2 casas, ``scoring._nota_0_100``): o ``:.1f`` arredondava o float
    binário, e 87,25 saía '87,2' enquanto 87,15 saía '87,2' e 87,45 '87,5'. É a
    função ÚNICA de nota com uma casa dos documentos (certificado Geral e a reserva
    dele, cartaz, boletim)."""
    try:
        numero = Decimal(repr(float(valor)))
    except (TypeError, ValueError):
        return "—"
    if not numero.is_finite():
        return "—"
    return str(numero.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)).replace(".", ",")


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
  .cabecalho { display:flex; align-items:center; justify-content:center; gap:44px; }
  .cabecalho .logo-cidade { height:74px; width:74px; }
  .cabecalho .logo-pref { height:60px; width:auto; }
  .cabecalho .constela { display:flex; flex-direction:column; align-items:center; gap:4px; }
  .cabecalho .constela .nome { font-family:'Trebuchet MS','Segoe UI',sans-serif; font-weight:800;
                 font-size:19px; letter-spacing:1px; color:#1B2A4A; }
  .cabecalho .constela .nome b { color:#F5B942; }
  h1 { font-size:52px; font-weight:700; letter-spacing:8px; color:#1B2A4A; margin-top:12px; }
  .divisor { display:flex; align-items:center; gap:12px; margin:8px 0 14px; color:#C9A24B; }
  .divisor .linha { width:120px; height:1.5px; background:#C9A24B; }
  .divisor .losango { width:9px; height:9px; background:#F5B942; transform:rotate(45deg); }
  .intro { font-size:15px; color:#555; letter-spacing:.5px; }
  .aluno { font-size:⟦TAM_ALUNO⟧px; font-weight:700; color:#1B2A4A; margin:14px 0 6px; letter-spacing:.5px; text-transform:uppercase; }
  .sublinhado { width:60%; max-width:520px; height:1.5px; background:#C9A24B; margin:0 auto 16px; }
  .detalhe { font-size:15.5px; color:#444; line-height:1.7; max-width:640px; }
  .detalhe b { color:#1B2A4A; }
  .medalha { margin:14px 0 4px; }
  .emitido { font-size:12.5px; color:#666; letter-spacing:.5px; }
  .dados { font-size:10.5px; color:#7a7a7a; letter-spacing:.3px; margin-top:3px; }
  .assinatura { position:absolute; bottom:26mm; left:50%; transform:translateX(-50%); text-align:center; }
  .assinatura .linha { width:230px; height:1px; background:#8a8a8a; margin:0 auto 6px; }
  .assinatura .rotulo { font-size:12.5px; color:#555; }
</style>
⟦CANTOS⟧
<div class="frame"></div>
<div class="conteudo">
  ⟦CABECALHO⟧
  <h1>CERTIFICADO</h1>
  <div class="divisor"><span class="linha"></span><span class="losango"></span><span class="linha"></span></div>
  <p class="intro">A escola ⟦ESCOLA⟧ certifica que</p>
  <p class="aluno">⟦ALUNO⟧</p>
  <div class="sublinhado"></div>
  <p class="detalhe">da turma <b>⟦TURMA⟧</b>, alcançou a nota geral <b>⟦NOTA⟧</b>⟦POSICAO⟧<br>
     no <b>Constela Edu</b> — ano letivo de <b>⟦ANO⟧</b>.</p>
  <div class="medalha">⟦MEDALHA⟧</div>
  <p class="emitido">Emitido em <b>⟦DATA⟧</b></p>
  ⟦DADOS⟧
</div>
<div class="assinatura"><div class="linha"></div><div class="rotulo">Direção</div></div>
"""


def _esc_html(texto: str) -> str:
    # Escapa HTML e NEUTRALIZA os delimitadores de placeholder ⟦ ⟧: sem isso,
    # um nome/escola que contivesse literalmente "⟦LINHAS⟧" reintroduziria um
    # token que um .replace posterior preencheria, corrompendo o documento.
    return (str(texto).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace("⟦", "").replace("⟧", ""))


# Nome do aluno no certificado GERAL (``.aluno``): 40px de sempre, em maiúsculas, na
# largura do ``.conteudo`` (A4 paisagem, 297mm, menos 40mm de cada lado, a 96 px/pol).
_LARGURA_ALUNO_CERT_PX = (297 - 2 * 40) * 96 / 25.4
_TETO_ALUNO_CERT = 40
_PISO_ALUNO_CERT = 22
_ESPACO_LETRAS_ALUNO_CERT_PX = 0.5   # o letter-spacing do .aluno
# A Georgia Bold (a do certificado no Windows) mede ~1,11× a Helvetica Bold em
# maiúsculas; a serifa do servidor (Liberation Serif, métrica da Times) ~1,02×.
# 1,2 dá folga às duas.
_FATOR_SERIFA_ALUNO_CERT = 1.2


def _linhas_do_nome_certificado(palavras: list[str], corpo: int) -> int:
    """Quantas linhas o nome ocupa no ``.aluno`` com o corpo ``corpo``: a quebra
    gulosa do navegador (palavra que não cabe desce), com a largura de cada
    palavra pela métrica da Helvetica Bold com a folga da serifa."""
    def largura(texto: str) -> float:
        return (corpo * _FATOR_SERIFA_ALUNO_CERT * _largura_em(texto, "helveticaB")
                + _ESPACO_LETRAS_ALUNO_CERT_PX * len(texto))

    espaco = largura(" ")
    linhas, atual = 1, 0.0
    for palavra in palavras:
        w = largura(palavra)
        if atual and atual + espaco + w > _LARGURA_ALUNO_CERT_PX:
            linhas, atual = linhas + 1, w
        else:
            atual = atual + espaco + w if atual else w
    return linhas


def _tam_fonte_aluno_certificado(nome: str) -> int:
    """Corpo (px) do nome do aluno no certificado Geral: o de sempre (40px) enquanto
    o nome cabe em DUAS linhas; acima disso, o maior corpo em que ele cabe nelas
    (piso de 22px).

    O nome fica num fluxo de altura livre e a assinatura é absoluta a 26mm do
    rodapé: um nome em três linhas empurrava "Emitido em" e "Dados das
    plataformas" para baixo da linha de assinatura. A conta é pela LARGURA medida
    das palavras (``_linhas_do_nome_certificado``), não pelo número de letras."""
    palavras = str(nome or "").upper().split()
    for corpo in range(_TETO_ALUNO_CERT, _PISO_ALUNO_CERT, -1):
        if _linhas_do_nome_certificado(palavras, corpo) <= 2:
            return corpo
    return _PISO_ALUNO_CERT


# ---------------------------------------------------------------------------
# TETO DE NAVEGADORES. Cada PDF bonito sobe um driver do Playwright (processo Node) e
# um Chromium inteiro (~150-300 MB). Sem fila, N pedidos juntos (fim de bimestre:
# coordenações imprimindo cartaz, certificado, relatório) eram N navegadores, e o
# processo podia estourar a memória do contêiner e derrubar a API inteira. Aqui, no
# máximo ``NAVEGADORES_SIMULTANEOS`` por processo; o excesso espera a vez até
# ``ESPERA_POR_NAVEGADOR_S`` e, esgotado o prazo, ``NavegadorOcupado`` — que quem chama
# já trata como "sem Chromium": cai no PDF simples de reserva (fpdf), com os mesmos
# números. A exceção é a arte do certificado da plataforma, que não tem reserva
# equivalente (a dela seria o Geral, de MÉRITO): lá a falta de vaga vira 503 "tente de
# novo" (``routers/relatorios.conteudo_certificado``). Ajustáveis no ambiente:
# PDF_NAVEGADORES_SIMULTANEOS e PDF_ESPERA_POR_NAVEGADOR_S.
# ---------------------------------------------------------------------------

def _numero_do_ambiente(nome: str, padrao: float, minimo: float) -> float:
    bruto = os.environ.get(nome, "").strip()
    if not bruto:
        return padrao
    try:
        return max(minimo, float(bruto))
    except ValueError:
        _log.warning("%s=%r não é um número; usando %s", nome, bruto, padrao)
        return padrao


NAVEGADORES_SIMULTANEOS = int(_numero_do_ambiente("PDF_NAVEGADORES_SIMULTANEOS", 2, 1))
ESPERA_POR_NAVEGADOR_S = _numero_do_ambiente("PDF_ESPERA_POR_NAVEGADOR_S", 30.0, 0.0)
_VAGAS_DE_NAVEGADOR = threading.BoundedSemaphore(NAVEGADORES_SIMULTANEOS)


class NavegadorOcupado(RuntimeError):
    """Todas as vagas de navegador seguiram ocupadas durante a espera."""


@contextmanager
def _navegador():
    """Um Chromium aberto, DENTRO do teto: a vaga é pega antes de subir o driver e
    devolvida depois de fechar o navegador — também quando a renderização falha."""
    if not _VAGAS_DE_NAVEGADOR.acquire(timeout=ESPERA_POR_NAVEGADOR_S):
        raise NavegadorOcupado(
            f"{NAVEGADORES_SIMULTANEOS} PDF(s) já em geração; sem vaga em "
            f"{ESPERA_POR_NAVEGADOR_S:g} s")
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            try:
                navegador = p.chromium.launch()
            except Exception:  # noqa: BLE001 — sem chromium baixado: tenta o Chrome do sistema
                navegador = p.chromium.launch(channel="chrome")
            try:
                yield navegador
            finally:
                navegador.close()
    finally:
        _VAGAS_DE_NAVEGADOR.release()


def _certificado_html_pdf(escola_nome: str, cor: str, aluno_nome: str,
                          turma: str, posicao: int | None, nota_geral: float,
                          ano_letivo: int, logos: tuple[str, str] | None = None,
                          dados_em: str | None = None) -> bytes:
    """Renderiza o certificado bonito em PDF via Chromium (Playwright)."""
    cantos = "".join(
        _CANTO_SVG.replace('class="canto"', f'class="canto {c}"')
        for c in ("c-tl", "c-tr", "c-bl", "c-br"))
    pos_txt = (f" e a <b>{posicao}ª posição</b> no Ranking Geral" if posicao else "")
    dados_html = f'<p class="dados">{_esc_html(dados_em)}</p>' if dados_em else ""
    html = (_CERT_TEMPLATE
            .replace("⟦CANTOS⟧", cantos)
            .replace("⟦CABECALHO⟧", _cabecalho_logos(logos))
            .replace("⟦MEDALHA⟧", _MEDALHA_SVG)
            .replace("⟦ESCOLA⟧", _esc_html(escola_nome))
            .replace("⟦TAM_ALUNO⟧", str(_tam_fonte_aluno_certificado(aluno_nome)))
            .replace("⟦ALUNO⟧", _esc_html(aluno_nome))
            .replace("⟦TURMA⟧", _esc_html(turma or "—"))
            .replace("⟦NOTA⟧", _fmt_nota(nota_geral))
            .replace("⟦POSICAO⟧", pos_txt)
            .replace("⟦ANO⟧", str(ano_letivo))
            .replace("⟦DATA⟧", agora_br().strftime("%d/%m/%Y"))
            .replace("⟦DADOS⟧", dados_html))
    doc = f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'></head><body>{html}</body></html>"

    with _navegador() as navegador:
        pagina = navegador.new_page()
        pagina.set_content(doc, wait_until="networkidle")
        pdf = pagina.pdf(prefer_css_page_size=True, print_background=True,
                         landscape=True)
    return pdf


# ---------------------------------------------------------------------------
# Certificado POR PLATAFORMA (Elefante Letrado / Matific) — arte oficial como
# fundo A4 e campos preenchidos AUTOMATICAMENTE (instituição, nome, bimestre,
# data). Um único mecanismo, genérico para as duas plataformas: muda só a arte.
# ---------------------------------------------------------------------------
_MESES = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
          "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _bimestre_por_mes(mes: int) -> int:
    """Bimestre pelo MÊS — aproximação legada, mantida só como rede de segurança
    para anos sem calendário oficial cadastrado.

    Não é mais o que decide o número impresso: isso agora é
    :func:`app.services.bimestres.bimestre_sugerido`, que usa as datas reais. O
    mapa por mês erra exatamente onde a pergunta importa — pelo calendário de
    2026 o 3º bimestre vai até 04/10, e este mapa já dizia 4 no dia 01/10."""
    return bimestres.por_mes_legado(mes)


# Caixa do nome da escola no certificado da plataforma (``.instituicao``): 32% ×
# 4,2% da página A4 paisagem (297 × 210 mm) a 96 px/pol ≈ 359,2 × 33,3 px. O
# texto mira 95% dela: folga para o arredondamento e o hinting do navegador.
_PX_POR_MM = 96 / 25.4
CAIXA_INSTITUICAO_PX = (0.32 * 297 * _PX_POR_MM, 0.042 * 210 * _PX_POR_MM)
_FOLGA_INSTITUICAO = 0.95
_TETO_INSTITUICAO = 20        # o corpo de antes: nome que já cabia não muda
_PISO_INSTITUICAO = 9
_PISO_UMA_LINHA = 11          # abaixo disso, duas linhas maiores leem melhor


def _largura_em(texto: str, fonte: str = "helvetica") -> float:
    """Largura do texto em "em" pelas métricas da Helvetica (as do fpdf) — que são
    as do Arial e as da Liberation Sans, a fonte com que o Chromium do servidor
    desenha o certificado (Debian com ``fonts-liberation``, sem Trebuchet MS nem
    Segoe UI: a pilha da arte cai no Arial). Onde a Trebuchet MS existe (Windows)
    o mesmo texto sai MAIS ESTREITO, então a medida é conservadora. Caractere fora
    da tabela (fora do latin-1) conta 1 em, mais largo que qualquer letra.
    ``fonte`` = a tabela do fpdf (``"helveticaB"`` para o negrito)."""
    from fpdf.fonts import CORE_FONTS_CHARWIDTHS

    larguras = CORE_FONTS_CHARWIDTHS[fonte]
    return sum(larguras.get(c, 1000) for c in texto) / 1000


def _layout_instituicao(nome: str) -> tuple[int, list[str]]:
    """(corpo em px, linhas) do nome da escola que CABE na caixa, pela LARGURA
    MEDIDA do texto — não pelo número de caracteres.

    A regra anterior (360 / (caracteres × 0,58)) supunha letra média de 0,58 em;
    nome em MAIÚSCULAS passa disso, e o nome oficial da escola 17, "EMEI/EMEF JOÃO
    THIMÓTEO DO ROSÁRIO" (20,7 em), saía com 18px = 373 px numa caixa de 359 px:
    cortado pelo ``overflow:hidden``. Agora o corpo é o maior que cabe em 95% da
    largura, com o teto de 20px de antes (nenhum certificado que já cabia muda).
    Nome tão longo que ficaria abaixo de 11px numa linha vai em DUAS linhas
    (quebra no espaço que equilibra as metades), se isso der um corpo maior — as
    duas linhas cabem na altura da caixa (antes, a quebra a 20px saía por cima do
    traço impresso na arte)."""
    nome = " ".join(str(nome or "").split())
    largura, altura = (CAIXA_INSTITUICAO_PX[0] * _FOLGA_INSTITUICAO,
                       CAIXA_INSTITUICAO_PX[1] * _FOLGA_INSTITUICAO)
    em = _largura_em(nome)
    uma = min(_TETO_INSTITUICAO, int(largura / em)) if em else _TETO_INSTITUICAO
    palavras = nome.split(" ")
    if uma >= _PISO_UMA_LINHA or len(palavras) < 2:
        return max(_PISO_INSTITUICAO, uma), [nome]
    maior, linhas = min(
        ((max(_largura_em(" ".join(palavras[:i])), _largura_em(" ".join(palavras[i:]))),
          [" ".join(palavras[:i]), " ".join(palavras[i:])])
         for i in range(1, len(palavras))),
        key=lambda par: par[0])
    duas = min(_TETO_INSTITUICAO, int(altura / 2), int(largura / maior))   # line-height 1
    if duas > uma:
        return max(_PISO_INSTITUICAO, duas), linhas
    return max(_PISO_INSTITUICAO, uma), [nome]


def _tam_fonte_instituicao(nome: str) -> int:
    """Corpo (px) do nome da escola no certificado — ver ``_layout_instituicao``."""
    return _layout_instituicao(nome)[0]


def _tam_fonte_nome(nome: str) -> int:
    """Corpo do nome que cabe na faixa central entre os traços (encolhe para
    nomes longos). Um pouco maior para dar mais destaque ao nome do aluno."""
    return max(26, min(60, int(600 / (max(len(nome), 1) * 0.56))))


# Campos dinâmicos posicionados em % da página (paisagem), calibrados sobre a
# arte 1492×1054 — as duas plataformas compartilham o MESMO layout.
_CERT_PLATAFORMA_TEMPLATE = """<style>
  @page { size: A4 landscape; margin: 0; }
  * { margin:0; padding:0; box-sizing:border-box; }
  html,body { width:297mm; height:210mm; }
  body { position:relative; overflow:hidden;
         font-family:'Trebuchet MS','Segoe UI',Arial,sans-serif;
         -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  .fundo { position:absolute; inset:0; width:100%; height:100%; object-fit:fill; z-index:0; }
  .campo { position:absolute; z-index:1; display:flex; align-items:center;
           justify-content:center; text-align:center; line-height:1; overflow:hidden; }
  .instituicao { left:28.5%; top:⟦INST⟧%; width:32%; height:4.2%; color:#333333;
                 white-space:nowrap; }
  .nome { left:19%; top:⟦NOME⟧%; width:62%; height:10%; background:⟦FUNDOCOR⟧;
          font-weight:800; color:#16235a; text-transform:uppercase; letter-spacing:.5px; }
  .bimestre { left:⟦BIML⟧%; top:⟦BIMT⟧%; width:4%; height:3%; font-weight:700; color:#333333; font-size:17px; }
  /* A DATA É UM BLOCO SÓ. Antes eram duas caixas absolutas independentes
     (.dia e .mes), cada uma centrando o próprio texto numa largura fixa, cada
     uma tendo de pousar num tracinho desenhado no PNG — e a cola entre elas
     ("de") e o ano eram pixels da arte. O dia do Matific caía 10,6% da página à
     esquerda do tracinho dele, e o mês saía por cima do traço. Aqui a frase
     inteira é uma linha de texto normal, centrada numa caixa única: dia, mês e
     ano não têm como se separar, e o espaçamento entre eles passa a ser o da
     tipografia, não a diferença de dois números mágicos. A faixa branca cobre a
     linha impressa na arte — a mesma técnica que o .nome já usava —, o que de
     quebra tira o ano de 2026 que estava CRAVADO no PNG. */
  .data { left:30%; top:⟦DT⟧%; width:40%; height:4.2%; background:⟦FUNDOCOR⟧;
          color:#333333; font-size:19px; white-space:nowrap; }
  .data .v { display:inline-block; padding:0 .7em; margin:0 .12em;
             border-bottom:1.6px solid #4a4a4a; }
</style>
<img class="fundo" src="⟦FUNDO⟧" alt="">
<div class="campo instituicao" style="font-size:⟦TAM_INST⟧px"><span>⟦INSTITUICAO⟧</span></div>
<div class="campo nome" style="font-size:⟦TAM_NOME⟧px">⟦ALUNO⟧</div>
<div class="campo bimestre">⟦BIMESTRE⟧</div>
<div class="campo data"><span><span class="v">⟦DIA⟧</span> de <span
     class="v">⟦MES⟧</span> de ⟦ANO⟧</span></div>
"""


def _html_para_pdf_paisagem(corpo: str) -> bytes:
    """Renderiza HTML em PDF A4 paisagem via Chromium (Playwright), com fundo
    impresso (para a arte de fundo aparecer)."""
    doc = (f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
           f"</head><body>{corpo}</body></html>")
    with _navegador() as navegador:
        pagina = navegador.new_page()
        pagina.set_content(doc, wait_until="networkidle")
        pdf = pagina.pdf(prefer_css_page_size=True, print_background=True, landscape=True)
    return pdf


# Posições dos campos (em % da página) POR arte. Só a ALTURA (e a altura do
# bimestre, que pousa num branco no meio de uma frase) muda entre as duas artes:
# a horizontal de todo o resto é centralização, não coordenada. Os dois números
# que sobravam aqui — DIAL e MESL, o "esquerda do dia" e o "esquerda do mês" —
# sumiram junto com as caixas independentes da data; eram eles que erravam.
# Os valores vêm de MEDIÇÃO dos traços na arte 1492×1054 (varredura de pixel),
# não de tentativa e erro: traço da data em 91,37% (matific) e 97,06%
# (elefante); a caixa fica ~2,7% acima para a sublinha cair sobre ele.
_CERT_POS = {
    # FUNDOCOR = a cor REAL do papel de cada arte, amostrada do PNG (a moda dos
    # pixels da faixa). Com #ffffff a máscara aparecia como um retângulo mais
    # claro que o resto do certificado — o fundo do Matific é #fdfdfd e o do
    # Elefante #fcfcfc, e dois níveis de diferença bastam para o olho ver a
    # emenda numa impressão.
    "elefante": {"INST": "38", "NOME": "45.6", "BIML": "44", "BIMT": "61",
                 "DT": "94.4", "FUNDOCOR": "#fcfcfc"},
    "matific":  {"INST": "33.6", "NOME": "42", "BIML": "47.8", "BIMT": "58.4",
                 "DT": "88.7", "FUNDOCOR": "#fdfdfd"},
}


def _certificado_plataforma_html(escola_nome: str, aluno_nome: str,
                                 plataforma: str, *,
                                 bimestre: int | None = None) -> str:
    """Monta o HTML do certificado da plataforma com a arte e os campos
    preenchidos (instituição, nome, bimestre e data de hoje).

    ``bimestre`` explícito manda; sem ele, cai no bimestre do mês de emissão,
    como antes. O padrão pelo relógio faz o MESMO aluno, com os MESMOS dados,
    receber "3" num dia e "4" no seguinte quando a entrega atravessa a virada —
    por isso quem emite pode fixar o número."""
    chave = "elefante" if plataforma.lower().startswith("elef") else "matific"
    fundo = _asset_data_uri(f"certificado-{chave}.png")
    agora = agora_br()
    # BIMESTRE AVALIADO e DATA DE EMISSÃO são coisas diferentes, e aqui elas se
    # separam: o bimestre é a escolha de quem emite (ou, sem escolha, o bimestre
    # em que HOJE cai pelo calendário oficial — não pelo mês do relógio); a data
    # é sempre o dia da emissão. Um certificado do 3º bimestre emitido em
    # 01/10/2026 é normal, e agora sai escrito assim.
    numero = bimestre if bimestre else bimestres.bimestre_sugerido(agora.date())
    tam_inst, linhas_inst = _layout_instituicao(escola_nome)
    html = (_CERT_PLATAFORMA_TEMPLATE
            .replace("⟦FUNDO⟧", fundo)
            .replace("⟦TAM_NOME⟧", str(_tam_fonte_nome(aluno_nome)))
            .replace("⟦TAM_INST⟧", str(tam_inst))
            .replace("⟦INSTITUICAO⟧", "<br>".join(_esc_html(linha) for linha in linhas_inst))
            .replace("⟦ALUNO⟧", _esc_html(aluno_nome))
            .replace("⟦BIMESTRE⟧", str(numero))
            .replace("⟦DIA⟧", f"{agora.day:02d}")
            .replace("⟦MES⟧", _MESES[agora.month])
            .replace("⟦ANO⟧", str(agora.year)))
    for token, valor in _CERT_POS[chave].items():
        html = html.replace(f"⟦{token}⟧", valor)
    return html


def gerar_certificado_plataforma(escola_nome: str, aluno_nome: str,
                                 plataforma: str, *,
                                 bimestre: int | None = None) -> bytes:
    """Certificado de desempenho da PLATAFORMA (Elefante Letrado / Matific): a
    arte oficial como fundo A4 paisagem, com instituição, nome do aluno, bimestre
    e data preenchidos automaticamente. Vetor (texto) sobre a arte embutida =
    pronto para impressão. Genérico para as duas plataformas."""
    return _html_para_pdf_paisagem(
        _certificado_plataforma_html(escola_nome, aluno_nome, plataforma,
                                     bimestre=bimestre))


def _certificado_fpdf(escola_nome: str, cor: str, aluno_nome: str,
                      turma: str, posicao: int | None, nota_geral: float,
                      ano_letivo: int, dados_em: str | None = None) -> bytes:
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
        f"da turma {turma}, alcançou a nota geral {_fmt_nota(nota_geral)}")
    if posicao:
        detalhe += f" e a {posicao}ª posição no Ranking Geral"
    pdf.cell(0, 8, detalhe, align="C")
    pdf.set_y(108)
    pdf.cell(0, 8, f"no Constela Edu - ano letivo de {ano_letivo}.", align="C")

    pdf.set_y(150)
    pdf.set_font("helvetica", "", 11)
    emitido = agora_br().strftime("%d/%m/%Y")
    pdf.cell(0, 8, f"Emitido em {emitido}", align="C")
    if dados_em:
        pdf.set_y(157)
        pdf.set_font("helvetica", "", 9)
        pdf.set_text_color(110, 110, 110)
        pdf.cell(0, 6, _couber(pdf, dados_em, 250), align="C")
        pdf.set_text_color(60, 60, 60)

    pdf.set_y(168)
    pdf.set_draw_color(120, 120, 120)
    pdf.line(110, 172, 187, 172)
    pdf.set_y(174)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 6, "Direção", align="C")

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Cartaz do Ranking Geral (pôster): documento "de vitrine" com a MESMA marca do
# certificado (moldura navy+dourado, 3 logos), a TABELA COMPLETA (todos os
# alunos, paginada automaticamente pelo Chromium) e um rodapé comemorativo.
# ---------------------------------------------------------------------------

def _materias_dos_cartoes(modulos) -> list[str]:
    """As matérias cujos números o cartaz do Ranking Geral mostra nos cartões: as
    contratadas (``modulos``; ``None`` = todas, como em ``services/modulos``)."""
    return [m for m in CARTAZ_MATERIAS if modulos is None or m in modulos]


def estatisticas_cartaz(db: Session, escola_id: int,
                        turma_ids: list[int] | None = None,
                        modulos: set[str] | None = None) -> dict:
    """Totais para os cartões do pôster: atividades (Matific) e livros
    (Elefante). Módulo fora do plano não é somado (``modulos``; ``None`` = todos):
    com uma matéria só, os totais são os do cartaz daquela matéria
    (``estatisticas_cartaz_materia`` — Leitura: livros e tempo; Matemática:
    atividades e estrelas), dos mesmos alunos.

    Soma o SNAPSHOT ATUAL (o mais recente por data de referência — o mesmo
    critério usado no ranking e no painel, via scoring._snapshots_atuais), e só
    da MESMA população da tabela: exatamente os alunos das linhas do cartaz
    (``_consulta_ranking_geral`` — ativos, matriculados no ano numa turma que
    concorre, com Nota do ano; ``turma_ids`` = o recorte do professor). Assim os
    números batem com a tabela e com "estudantes ranqueados", sem inflar com a
    Educação Infantil, com quem ainda não tem nota, com alunos de anos anteriores
    ou arquivados nem com correções para menos. Best-effort: qualquer falha vira
    zero — o cartaz nunca quebra por causa das estatísticas."""
    materias = _materias_dos_cartoes(modulos)
    try:
        escola = db.get(Escola, escola_id)
        cohort = {aluno.id for _nota, aluno, _turma
                  in db.execute(_consulta_ranking_geral(db, escola_id, turma_ids))}
        if len(materias) == 1:
            return estatisticas_cartaz_materia(db, escola_id, materias[0], sorted(cohort))
        if not materias:
            return {}
        # Matific é contador DO ANO: o retrato de outro ano letivo não soma.
        m_atuais = scoring.snapshots_matific_do_ano(db, escola_id, escola.ano_letivo_ativo)
        e_atuais = scoring._snapshots_atuais(db, escola_id, SnapshotElefante)
        atividades = sum(s.atividades for aid, s in m_atuais.items() if aid in cohort)
        livros = sum(s.livros_unicos for aid, s in e_atuais.items() if aid in cohort)
        return {"atividades": int(atividades), "livros": int(livros)}
    except Exception:  # noqa: BLE001 — cartões decorativos: nunca derrubam o cartaz
        # Chave ausente vira 0 no cartão (``_cartaz_documento_html``); só as do plano.
        return {"atividades": 0, "livros": 0} if len(materias) > 1 else {}


def estatisticas_cartaz_materia(db: Session, escola_id: int, materia: str,
                                aluno_ids: list[int]) -> dict:
    """Totais para os cartões do pôster DE UMA MATÉRIA — só números daquela
    matéria e só dos alunos que o cartaz LISTA (``aluno_ids`` = os aferidos da
    dimensão, as linhas do ranking por dimensão).

    Leitura: livros lidos e minutos de leitura (Elefante). Matemática:
    atividades e estrelas (Matific). A fonte é a MESMA de `estatisticas_cartaz`
    — o snapshot ATUAL de cada aluno (scoring._snapshots_atuais), sem janela
    nova —; muda só a população, que deixa de ser "ativos matriculados" e passa
    a ser exatamente a tabela do cartaz. Sem isso o cartaz de Leitura mostrava
    as atividades do Matific e somava livros de quem nem aparece na lista (a
    Educação Infantil, por exemplo, que não concorre). Best-effort, como os
    cartões do Ranking Geral: qualquer falha vira zero."""
    listados = set(aluno_ids)
    try:
        if materia == "leitura":
            atuais = scoring._snapshots_atuais(db, escola_id, SnapshotElefante)
            snaps = [s for aid, s in atuais.items() if aid in listados]
            return {"livros": int(sum(s.livros_unicos or 0 for s in snaps)),
                    "tempo_leitura_min": int(sum(s.tempo_leitura_min or 0 for s in snaps))}
        # Matific é contador DO ANO: a mesma janela que fez o aluno ser aferido
        # (``scoring.snapshots_matific_do_ano``) — retrato de outro ano não soma.
        escola = db.get(Escola, escola_id)
        atuais = scoring.snapshots_matific_do_ano(db, escola_id, escola.ano_letivo_ativo)
        snaps = [s for aid, s in atuais.items() if aid in listados]
        return {"atividades": int(sum(s.atividades or 0 for s in snaps)),
                "estrelas": int(sum(s.estrelas or 0 for s in snaps))}
    except Exception:  # noqa: BLE001 — cartões decorativos: nunca derrubam o cartaz
        if materia == "leitura":
            return {"livros": 0, "tempo_leitura_min": 0}
        return {"atividades": 0, "estrelas": 0}


_CARTAZ_TEMPLATE = """<style>
  @page { size: A4 portrait; margin: 13mm 12mm 12mm; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: Georgia,'Times New Roman',serif; color:#25304a;
         -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  .barra { height:5px; border-radius:3px;
           background:linear-gradient(90deg,#1B2A4A,#C9A24B 50%,#1B2A4A); }
  .cabecalho { display:flex; align-items:center; justify-content:space-between; gap:16px; margin:12px 2px 2px; }
  .cabecalho .logo-cidade { height:60px; width:60px; }
  .cabecalho .logo-pref { height:50px; width:auto; }
  .cabecalho .constela { display:flex; flex-direction:column; align-items:center; gap:2px; }
  .cabecalho .constela .nome { font-family:'Trebuchet MS','Segoe UI',sans-serif; font-weight:800;
                 font-size:15px; letter-spacing:.5px; color:#1B2A4A; }
  .cabecalho .constela .nome b { color:#F5B942; }
  h1 { text-align:center; font-size:33px; font-weight:700; letter-spacing:7px; color:#1B2A4A; margin-top:8px; }
  .divisor { display:flex; align-items:center; justify-content:center; gap:10px; margin:6px 0 10px; }
  .divisor .linha { width:80px; height:1.5px; background:#C9A24B; }
  .divisor .losango { width:8px; height:8px; background:#F5B942; transform:rotate(45deg); }
  .pills { display:flex; justify-content:center; gap:10px; flex-wrap:wrap; margin-bottom:12px; }
  .pill { font-family:'Trebuchet MS','Segoe UI',sans-serif; font-size:10.5px; letter-spacing:.6px;
          text-transform:uppercase; padding:5px 14px; border-radius:20px; }
  .pill.ano { background:#1B2A4A; color:#fff; }
  .pill.escola { background:#F3ECDA; color:#8A6D2B; border:1px solid #E4D3A6; }
  table { width:100%; border-collapse:collapse; font-size:11px; }
  thead { display:table-header-group; }
  thead th { background:#1B2A4A; color:#fff; font-family:'Trebuchet MS','Segoe UI',sans-serif;
             font-weight:700; font-size:9.5px; letter-spacing:.4px; text-transform:uppercase;
             padding:8px 6px; text-align:center; }
  thead th.esq { text-align:left; }
  .ic { vertical-align:middle; margin-right:4px; }
  tbody td { padding:5.5px 6px; border-bottom:1px solid #ECEEF2; text-align:center;
             font-variant-numeric:tabular-nums; }
  tbody td.aluno { text-align:left; font-weight:600; color:#25304a; }
  tbody td.turma, tbody td.serie { text-align:left; color:#5a6478; }
  tbody td.geral { font-weight:800; color:#1B2A4A; }
  tbody tr.top td { background:#FBF6E9; }
  tbody tr:nth-child(even):not(.top) td { background:#FAFBFC; }
  .medalha { display:inline-flex; width:23px; height:23px; border-radius:50%; align-items:center;
             justify-content:center; font-family:'Trebuchet MS',sans-serif; font-weight:800;
             font-size:12px; color:#1B2A4A; }
  .m1 { background:linear-gradient(#F8DA7B,#E3A62A); }
  .m2 { background:linear-gradient(#E5E9EF,#B7BFCC); }
  .m3 { background:linear-gradient(#E7BE86,#C07F3C); color:#fff; }
  .rodape { break-inside:avoid; }
  .tiles { display:flex; gap:10px; margin:16px 0 12px; }
  .tile { flex:1; text-align:center; border:1px solid #E7E3D4; border-radius:10px; padding:12px 6px; background:#FCFAF4; }
  .tile .n { font-family:'Trebuchet MS','Segoe UI',sans-serif; font-size:23px; font-weight:800; color:#1B2A4A; }
  .tile .r { font-size:9px; letter-spacing:.5px; text-transform:uppercase; color:#8A6D2B; margin-top:3px; }
  .banner { display:flex; align-items:center; justify-content:center; gap:8px; text-align:center;
            background:#1B2A4A; color:#fff; border-radius:10px; padding:12px 16px; font-size:12px; letter-spacing:.3px; }
  .banner b { color:#F5D98A; }
  .frase { text-align:center; font-style:italic; color:#6b7488; font-size:12.5px; margin:13px 0 4px; }
  .frase::before { content:'“'; color:#C9A24B; } .frase::after { content:'”'; color:#C9A24B; }
  .rodape-marca { text-align:center; font-family:'Trebuchet MS','Segoe UI',sans-serif; font-size:9.5px;
                  letter-spacing:1.5px; text-transform:uppercase; color:#1B2A4A;
                  margin-top:10px; padding-top:9px; border-top:1px solid #E7E3D4; }
  .gerado { text-align:center; font-size:8.5px; color:#9aa2b1; margin-top:4px; }
</style>
<div class="barra"></div>
⟦CABECALHO⟧
<h1>⟦TITULO⟧</h1>
<div class="divisor"><span class="linha"></span><span class="losango"></span><span class="linha"></span></div>
<div class="pills">
  <span class="pill ano">Constela Edu · Ano letivo de ⟦ANO⟧</span>
  <span class="pill escola">⟦ESCOLA⟧</span>
</div>
<table>
  <thead><tr>
    <th>Posição</th><th class="esq">Aluno</th><th class="esq">Turma</th><th class="esq">Série</th>
    ⟦COLUNAS_NOTA⟧
  </tr></thead>
  <tbody>⟦LINHAS⟧</tbody>
</table>
<div class="rodape">
  <div class="tiles">⟦TILES⟧</div>
  <div class="banner">⟦IC_STAR⟧<span><b>Parabéns</b> a todos os estudantes por cada passo na jornada do conhecimento!</span></div>
  <div class="frase">Cada conquista é uma estrela no caminho do conhecimento</div>
  <div class="rodape-marca">Constela Edu — Conectando aprendizagem, inspirando futuros</div>
  <div class="gerado">Gerado em ⟦DATA⟧⟦DADOS⟧</div>
</div>
"""


# Cabeçalho completo do cartaz e o <th> de cada nota de plataforma (a coluna só
# sai quando o módulo está no plano — ver ``sem_notas_fora_do_plano``).
_CABECALHO_CARTAZ = ["Posição", "Aluno", "Turma", "Série", "Nota Matific",
                     "Nota Elefante", "Nota Geral"]
_TH_NOTA_PLATAFORMA = {"Nota Matific": "<th>⟦IC_STAR⟧Nota Matific</th>",
                       "Nota Elefante": "<th>⟦IC_ELE⟧Nota Elefante</th>"}


def _th_notas_cartaz(cabecalho: list[str] | None) -> str:
    cabecalho = cabecalho or _CABECALHO_CARTAZ
    return "".join(th for nome, th in _TH_NOTA_PLATAFORMA.items() if nome in cabecalho)


# Cartaz POR MATÉRIA: rótulo da matéria e ícone da coluna da nota. As chaves
# são as dimensões oficiais do ranking (`?dimensao=` de `/ranking`).
CARTAZ_MATERIAS: dict[str, tuple[str, str]] = {
    "leitura": ("Leitura", _IC_ELEFANTE),
    "matematica": ("Matemática", _IC_STAR),
}


def cabecalho_cartaz_materia(materia: str) -> list[str]:
    """Colunas do cartaz de UMA matéria: só a nota daquela matéria."""
    rotulo, _ = CARTAZ_MATERIAS[materia]
    return ["Posição", "Aluno", "Turma", "Série", f"Nota de {rotulo}"]


def _linhas_cartaz_html(linhas: list[list], cabecalho: list[str] | None = None,
                        materia: str | None = None) -> str:
    cabecalho = list(cabecalho or _CABECALHO_CARTAZ)
    notas_plataforma = [nome for nome in _TH_NOTA_PLATAFORMA if nome in cabecalho]
    partes = []
    for linha in linhas:
        if materia:
            # Cartaz da matéria: [posição, aluno, turma, série, nota da matéria].
            pos, nome, turma, serie, nota_materia = (list(linha) + [""] * 5)[:5]
        else:
            valores = dict(zip(cabecalho, list(linha) + [""] * len(cabecalho)))
            pos, nome, turma, serie, ng = (valores.get(c, "") for c in
                                           ("Posição", "Aluno", "Turma", "Série", "Nota Geral"))
        try:
            pos_int = int(pos)
        except (TypeError, ValueError):
            pos_int = 0
        if 1 <= pos_int <= 3:
            classe = {1: "m1", 2: "m2", 3: "m3"}[pos_int]
            pos_html = f'<span class="medalha {classe}">{pos_int}</span>'
            tr_classe = "top"
        else:
            pos_html = f"{pos_int}º"
            tr_classe = ""
        partes.append(
            f'<tr class="{tr_classe}"><td class="pos">{pos_html}</td>'
            f'<td class="aluno">{_esc_html(nome)}</td>'
            f'<td class="turma">{_esc_html(turma)}</td>'
            f'<td class="serie">{_esc_html(serie)}</td>'
            + (f'<td class="geral">{_fmt_nota(nota_materia)}</td></tr>' if materia
               else "".join(f"<td>{_fmt_nota(valores[c])}</td>" for c in notas_plataforma)
                    + f'<td class="geral">{_fmt_nota(ng)}</td></tr>'))
    return "".join(partes)


def _faixa_anos(linhas: list[list]) -> tuple[str, str]:
    """Deriva 'N' e rótulo do 4º cartão a partir das séries dos alunos
    ('2º–5º' / 'anos atendidos'). Sem séries numéricas, cai para nº de turmas."""
    anos = []
    for linha in linhas:
        m = re.match(r"\s*(\d+)", str(linha[3]) if len(linha) > 3 else "")
        if m:
            anos.append(int(m.group(1)))
    if anos:
        lo, hi = min(anos), max(anos)
        return (f"{lo}º–{hi}º", "anos atendidos") if lo != hi else (f"{lo}º", "ano")
    turmas = len({linha[2] for linha in linhas if len(linha) > 2})
    return str(turmas), ("turmas" if turmas != 1 else "turma")


def _tempo_cartaz(minutos) -> str:
    """Minutos de leitura para o cartão do cartaz de Leitura: '45 min',
    '10h 50min', '1.250h' (milhar com ponto). Mesma escrita do relatório por
    período, com o milhar para os totais da escola inteira."""
    try:
        minutos = max(0, int(minutos or 0))
    except (TypeError, ValueError):
        minutos = 0
    if minutos < 60:
        return f"{minutos} min"
    horas, resto = divmod(minutos, 60)
    horas_txt = f"{horas:,}".replace(",", ".")
    return f"{horas_txt}h {resto}min" if resto else f"{horas_txt}h"


def gerar_cartaz_ranking(escola_nome: str, cor: str, ano_letivo: int,
                         cabecalho: list[str], linhas: list[list],
                         estatisticas: dict,
                         logos: tuple[str, str] | None = None,
                         materia: str | None = None,
                         dados_em: str | None = None,
                         modulos: set[str] | None = None) -> bytes:
    """Cartaz do Ranking em PDF (todos os alunos). HTML→Chromium com o layout
    completo; sem navegador, cai para o PDF simples de ranking (reserva).

    ``materia`` ausente = cartaz do Ranking Geral (notas Matific, Elefante e
    Geral). ``materia`` = ``leitura`` | ``matematica`` = cartaz DAQUELA matéria:
    título com o nome dela e uma só coluna de nota — as linhas chegam como
    ``[posição, aluno, turma, série, nota da matéria]`` (ver
    `cabecalho_cartaz_materia`). ``estatisticas`` são os totais dos cartões:
    `estatisticas_cartaz` no Ranking Geral, `estatisticas_cartaz_materia` (só a
    matéria, só os alunos listados) no cartaz da matéria. ``dados_em`` = a
    linha "Dados das plataformas: ..." (``legenda_data_dos_dados``), impressa
    ao lado da data de emissão — também na reserva. ``modulos`` = os módulos
    contratados (``None`` = todos): no Ranking Geral, os cartões só das
    matérias do plano."""
    titulo = (f"Ranking de {CARTAZ_MATERIAS[materia][0]}" if materia
              else "Ranking Geral")
    try:
        return _cartaz_html_pdf(escola_nome, ano_letivo, linhas, estatisticas, logos,
                                cabecalho=cabecalho, materia=materia, dados_em=dados_em,
                                modulos=modulos)
    except Exception:  # noqa: BLE001 — sem Chromium/erro: PDF simples de ranking
        return gerar_pdf(titulo, escola_nome, cor, cabecalho, linhas,
                         nota_dados=dados_em)


def _cartaz_documento_html(escola_nome: str, ano_letivo: int, linhas: list[list],
                           estatisticas: dict, logos: tuple[str, str] | None = None,
                           materia: str | None = None,
                           cabecalho: list[str] | None = None,
                           dados_em: str | None = None,
                           modulos: set[str] | None = None) -> str:
    """HTML completo do cartaz (o que o Chromium imprime). Separado da
    impressão para o conteúdo poder ser conferido sem navegador. ``modulos`` =
    os módulos contratados (``None`` = todos): decide os cartões do Ranking
    Geral."""
    def _mil(n) -> str:
        return f"{int(n):,}".replace(",", ".")

    faixa_n, faixa_r = _faixa_anos(linhas)
    # Os dois primeiros cartões são DA MATÉRIA do cartaz: no de Leitura não
    # aparece atividade do Matific, no de Matemática não aparece livro do
    # Elefante (os totais vêm de `estatisticas_cartaz_materia`, só dos alunos
    # listados). O Ranking Geral segue com atividades + livros — só das
    # matérias do plano (``modulos``): com uma só, os cartões são os do cartaz
    # dela; o módulo não contratado não aparece, nem zerado.
    materias = [materia] if materia else _materias_dos_cartoes(modulos)
    if materias == ["leitura"]:
        tiles = [
            (_mil(estatisticas.get("livros", 0)), "livros lidos"),
            (_tempo_cartaz(estatisticas.get("tempo_leitura_min", 0)), "tempo de leitura"),
        ]
    elif materias == ["matematica"]:
        tiles = [
            (_mil(estatisticas.get("atividades", 0)), "atividades"),
            (_mil(estatisticas.get("estrelas", 0)), "estrelas"),
        ]
    elif materias:
        tiles = [
            (_mil(estatisticas.get("atividades", 0)), "atividades"),
            (_mil(estatisticas.get("livros", 0)), "livros lidos"),
        ]
    else:
        tiles = []
    tiles += [
        (_mil(len(linhas)), "estudantes ranqueados"),
        (faixa_n, faixa_r),
    ]
    tiles_html = "".join(
        f'<div class="tile"><div class="n">{n}</div><div class="r">{r}</div></div>'
        for n, r in tiles)

    if materia:
        rotulo, icone = CARTAZ_MATERIAS[materia]
        titulo = f"RANKING DE {rotulo.upper()}"
        colunas_nota = f"<th>{icone}Nota de {rotulo}</th>"
    else:
        titulo = "RANKING GERAL"
        # Só as notas de plataforma que o cabeçalho traz (módulo no plano).
        colunas_nota = _th_notas_cartaz(cabecalho) + "<th>⟦IC_TRO⟧Nota Geral</th>"

    # As colunas entram ANTES dos ícones: as do Ranking Geral usam marcadores.
    html = (_CARTAZ_TEMPLATE
            .replace("⟦COLUNAS_NOTA⟧", colunas_nota)
            .replace("⟦TITULO⟧", titulo)
            .replace("⟦CABECALHO⟧", _cabecalho_logos(logos))
            .replace("⟦IC_STAR⟧", _IC_STAR)
            .replace("⟦IC_ELE⟧", _IC_ELEFANTE)
            .replace("⟦IC_TRO⟧", _IC_TROFEU)
            .replace("⟦ANO⟧", str(ano_letivo))
            .replace("⟦ESCOLA⟧", _esc_html(escola_nome))
            .replace("⟦LINHAS⟧", _linhas_cartaz_html(linhas, cabecalho, materia))
            .replace("⟦TILES⟧", tiles_html)
            .replace("⟦DATA⟧", agora_br().strftime("%d/%m/%Y"))
            .replace("⟦DADOS⟧", f" &middot; {_esc_html(dados_em)}" if dados_em else ""))
    return (f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
            f"</head><body>{html}</body></html>")


def _cartaz_html_pdf(escola_nome: str, ano_letivo: int, linhas: list[list],
                     estatisticas: dict, logos: tuple[str, str] | None = None,
                     cabecalho: list[str] | None = None,
                     materia: str | None = None,
                     dados_em: str | None = None,
                     modulos: set[str] | None = None) -> bytes:
    doc = _cartaz_documento_html(escola_nome, ano_letivo, linhas, estatisticas,
                                 logos, materia=materia, cabecalho=cabecalho,
                                 dados_em=dados_em, modulos=modulos)

    with _navegador() as navegador:
        pagina = navegador.new_page()
        pagina.set_content(doc, wait_until="networkidle")
        pdf = pagina.pdf(prefer_css_page_size=True, print_background=True)
    return pdf


# ---------------------------------------------------------------------------
# Relatórios "de vitrine" em PDF — Lista de Alunos e Catálogo de Livros.
# Mesma família visual dos demais documentos (faixa com os 3 logos, título,
# cartões de estatística, tabelas navy+zebra), com rodapé/numeração de página
# em TODAS as páginas via header/footer do Chromium. Reserva: gerar_pdf simples.
# ---------------------------------------------------------------------------

_REPORT_CSS = """<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: Georgia,'Times New Roman',serif; color:#25304a;
         -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  .faixa { border:1.5px solid #1B2A4A; border-left:6px solid #C9A24B; border-radius:6px;
           padding:9px 22px; }
  .faixa .cabecalho { display:flex; align-items:center; justify-content:space-between; width:100%; gap:16px; }
  .faixa .logo-cidade { height:48px; width:48px; }
  .faixa .logo-pref { height:34px; width:auto; }
  .faixa .constela { display:flex; flex-direction:column; align-items:center; gap:1px; }
  .faixa .constela .nome { font-family:'Trebuchet MS','Segoe UI',sans-serif; font-weight:800;
                 font-size:19px; letter-spacing:1px; color:#1B2A4A; }
  .faixa .constela .nome b { color:#F5B942; }
  h1 { text-align:center; font-size:30px; font-weight:700; letter-spacing:3px; color:#1B2A4A; margin-top:14px; }
  .escola-nome { text-align:center; font-size:13px; font-weight:700; letter-spacing:.4px; color:#1B2A4A; margin-top:7px; }
  .subtitulo { text-align:center; font-size:11.5px; color:#6b7488; margin-top:3px; }
  .tiles { display:flex; border:1px solid #E4D3A6; border-radius:8px; overflow:hidden; margin:14px 0 10px; }
  .tile { flex:1; padding:9px 16px; border-left:1px solid #EFE9DA; }
  .tile:first-child { border-left:0; }
  .tile .n { font-family:'Trebuchet MS','Segoe UI',sans-serif; font-size:17px; font-weight:800; color:#1B2A4A; }
  .tile .r { font-size:8.5px; letter-spacing:.4px; text-transform:uppercase; color:#8A6D2B; margin-top:2px; }
  .intro { font-size:10.5px; color:#6b7488; line-height:1.5; margin-bottom:4px; }
  .secao { font-size:15px; font-weight:700; color:#1B2A4A; letter-spacing:1px; margin:16px 0 6px; break-after:avoid; }
  table.tab { width:100%; border-collapse:collapse; font-size:10.5px; }
  table.tab thead { display:table-header-group; }
  table.tab thead th { background:#1B2A4A; color:#fff; font-family:'Trebuchet MS','Segoe UI',sans-serif;
             font-weight:700; font-size:8.5px; letter-spacing:.4px; text-transform:uppercase;
             padding:8px 10px; text-align:center; }
  table.tab thead th.esq { text-align:left; }
  table.tab tbody td { padding:6px 10px; border-bottom:1px solid #ECEEF2; text-align:center;
             font-variant-numeric:tabular-nums; }
  table.tab tbody td.esq { text-align:left; }
  table.tab tbody td.num { color:#8a93a5; width:38px; }
  table.tab tbody td.nome { font-weight:600; color:#25304a; }
  table.tab tbody tr:nth-child(even) td { background:#F7F8FA; }
  .sit { font-weight:700; color:#5a6478; }
  .sit.ativo { color:#2FA24B; }
  .sit .dot { display:inline-block; width:7px; height:7px; border-radius:50%;
              background:#2FA24B; margin-right:5px; vertical-align:middle; }
</style>"""

# Rodapé com numeração — renderizado pelo Chromium em TODAS as páginas. Precisa
# de estilo inline (o CSS da página não se aplica ao template de rodapé).
_REPORT_FOOTER = (
    '<div style="width:100%; box-sizing:border-box; padding:4px 11mm 0; margin:0 6mm;'
    ' border-top:1px solid #C9A24B; font-family:Georgia,serif; font-size:8px;'
    ' color:#8a93a5; display:flex; justify-content:space-between; align-items:center;">'
    '<span>CONSTELA EDU &bull; Conectando aprendizagem, inspirando futuros.</span>'
    '<span>Página <span class="pageNumber"></span></span></div>')


def _report_tiles(tiles: list[tuple[str, str]]) -> str:
    return ('<div class="tiles">' + "".join(
        f'<div class="tile"><div class="n">{_esc_html(n)}</div>'
        f'<div class="r">{_esc_html(r)}</div></div>' for n, r in tiles) + '</div>')


def _relatorio_shell(titulo: str, escola_nome: str, subtitulo: str,
                     tiles: list[tuple[str, str]], intro: str, corpo: str,
                     logos: tuple[str, str] | None = None) -> str:
    return (_REPORT_CSS
            + '<div class="faixa">' + _cabecalho_logos(logos) + '</div>'
            + f'<h1>{_esc_html(titulo)}</h1>'
            + f'<p class="escola-nome">{_esc_html(escola_nome)}</p>'
            + f'<p class="subtitulo">{subtitulo}</p>'
            + _report_tiles(tiles)
            + f'<p class="intro">{intro}</p>'
            + corpo)


def _relatorio_html_pdf(html_body: str) -> bytes:
    """Renderiza um relatório 'de vitrine' (A4 retrato) com rodapé/numeração."""
    doc = (f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
           f"</head><body>{html_body}</body></html>")
    with _navegador() as navegador:
        pagina = navegador.new_page()
        pagina.set_content(doc, wait_until="networkidle")
        pdf = pagina.pdf(
            format="A4", print_background=True, display_header_footer=True,
            header_template="<div></div>", footer_template=_REPORT_FOOTER,
            margin={"top": "12mm", "bottom": "16mm", "left": "11mm", "right": "11mm"})
    return pdf


def _faixa_anos_relatorio(series) -> tuple[str, str]:
    anos = [int(m.group(1)) for s in series
            if (m := re.match(r"\s*(\d+)", str(s)))]
    if anos:
        lo, hi = min(anos), max(anos)
        return (f"{lo}º → {hi}º", "anos") if lo != hi else (f"{lo}º", "ano")
    return str(len({s for s in series if s})), "séries"


def gerar_lista_alunos_pdf(escola_nome: str, cor: str, ano_letivo: int,
                           cabecalho: list[str], linhas: list[list],
                           logos: tuple[str, str] | None = None) -> bytes:
    """Lista de Alunos em PDF de vitrine (agrupada por turma). Reserva: PDF simples."""
    try:
        return _relatorio_html_pdf(_shell_lista_alunos(escola_nome, ano_letivo, linhas, logos))
    except Exception:  # noqa: BLE001 — sem Chromium/erro: PDF simples
        return gerar_pdf("Lista de Alunos", escola_nome, cor, cabecalho, linhas)


def _shell_lista_alunos(escola_nome: str, ano_letivo: int, linhas: list[list],
                        logos: tuple[str, str] | None = None) -> str:
    from itertools import groupby

    # linhas de linhas_alunos: [Aluno, Turma, Série, Nº de chamada, Situação]
    total = len(linhas)
    turmas = {linha[1] for linha in linhas}
    faixa_n, faixa_r = _faixa_anos_relatorio([linha[2] for linha in linhas])
    ativos = sum(1 for linha in linhas if str(linha[4]).lower().startswith("ativ"))
    pct = f"{round(100 * ativos / total)}%" if total else "—"
    tiles = [(str(total), "alunos cadastrados"), (str(len(turmas)), "turmas"),
             (faixa_n, faixa_r), (pct, "status ativo")]

    corpo = []
    for turma, grupo in groupby(linhas, key=lambda linha: linha[1]):
        corpo.append(f'<h2 class="secao">{_esc_html(turma)}</h2>')
        corpo.append('<table class="tab"><thead><tr>'
                     '<th>Nº</th><th class="esq">Nome do estudante</th>'
                     '<th>Série</th><th>Nº de chamada</th><th>Situação</th>'
                     '</tr></thead><tbody>')
        for i, linha in enumerate(grupo, 1):
            nome, _turma, serie, chamada, status = (list(linha) + [""] * 5)[:5]
            ativo = str(status).lower().startswith("ativ")
            chamada_txt = str(chamada) if chamada not in (None, "", 0, "0") else "—"
            dot = '<span class="dot"></span>' if ativo else ''
            corpo.append(
                f'<tr><td class="num">{i:02d}</td>'
                f'<td class="esq nome">{_esc_html(nome)}</td>'
                f'<td>{_esc_html(serie)}</td>'
                f'<td>{_esc_html(chamada_txt)}</td>'
                f'<td class="sit {"ativo" if ativo else ""}">{dot}'
                f'{_esc_html(str(status).capitalize())}</td></tr>')
        corpo.append('</tbody></table>')

    subtitulo = (f"Cadastro escolar · Ano letivo de {ano_letivo} · "
                 f"Gerado em {agora_br().strftime('%d/%m/%Y')}")
    intro = ("Relação oficial de estudantes cadastrados no Constela Edu. A situação "
             "corresponde ao status registrado no momento da emissão deste relatório.")
    return _relatorio_shell("Lista de Alunos", escola_nome, subtitulo, tiles,
                            intro, "".join(corpo), logos)


def gerar_catalogo_livros_pdf(escola_nome: str, cor: str, ano_letivo: int,
                              cabecalho: list[str], linhas: list[list],
                              logos: tuple[str, str] | None = None) -> bytes:
    """Catálogo de Livros em PDF de vitrine. Reserva: PDF simples."""
    try:
        return _relatorio_html_pdf(_shell_catalogo(escola_nome, ano_letivo, linhas, logos))
    except Exception:  # noqa: BLE001 — sem Chromium/erro: PDF simples
        return gerar_pdf("Catálogo de Livros", escola_nome, cor, cabecalho, linhas)


def _shell_catalogo(escola_nome: str, ano_letivo: int, linhas: list[list],
                    logos: tuple[str, str] | None = None) -> str:
    # linhas de linhas_livros: [Título, Autor, Nível, Categoria, Leituras]
    total = len(linhas)
    autores = {linha[1] for linha in linhas if len(linha) > 1 and linha[1]}
    niveis = {linha[2] for linha in linhas if len(linha) > 2 and linha[2]}
    leituras = sum(int(linha[4] or 0) for linha in linhas if len(linha) > 4)
    tiles = [(str(total), "livros no acervo"), (str(len(autores)), "autores"),
             (str(len(niveis)), "níveis"),
             (f"{leituras:,}".replace(",", "."), "leituras")]

    corpo = ['<table class="tab"><thead><tr>'
             '<th class="esq">Título</th><th class="esq">Autor</th><th>Nível</th>'
             '<th class="esq">Categoria</th><th>Leituras</th>'
             '</tr></thead><tbody>']
    for linha in linhas:
        titulo, autor, nivel, categoria, leituras_n = (list(linha) + [""] * 5)[:5]
        corpo.append(
            f'<tr><td class="esq nome">{_esc_html(titulo)}</td>'
            f'<td class="esq">{_esc_html(autor or "—")}</td>'
            f'<td>{_esc_html(nivel or "—")}</td>'
            f'<td class="esq">{_esc_html(categoria or "—")}</td>'
            f'<td>{_esc_html(leituras_n)}</td></tr>')
    corpo.append('</tbody></table>')

    subtitulo = (f"Acervo de leitura · Ano letivo de {ano_letivo} · "
                 f"Gerado em {agora_br().strftime('%d/%m/%Y')}")
    intro = ("Catálogo de livros disponíveis no Constela Edu, com o total de "
             "leituras registradas por título.")
    return _relatorio_shell("Catálogo de Livros", escola_nome, subtitulo, tiles,
                            intro, "".join(corpo), logos)


# ---------------------------------------------------------------------------
# Boletim da REDE (Secretaria) — documento de vitrine MUNICIPAL: panorama da
# rede, equidade entre escolas, escolas em atenção e o ranking das escolas.
# Mesma família visual (faixa com os 3 logos da cidade, cartões, tabelas
# navy+zebra, rodapé/numeração). SÓ dados agregados por escola — nunca PII de
# criança. Parte do dashboard_rede (services/rede.py), a mesma fonte do painel.
# ---------------------------------------------------------------------------

def _escola_comparada(cartao: dict) -> bool:
    """A escola entra no "Ranking das escolas" do Boletim? Quem decide é a marca
    ``comparada`` de ``rede.dashboard_rede`` — a MESMA régua do Ranking da Rede,
    da equidade e do índice que o próprio Boletim mostra (algum aluno que
    concorre, 1º–5º ano, tem dado). Sem ela, a tabela numerava todas as escolas
    e o PDF dizia "pior escola 1000 · diferença 0" acima de "2º · Índice 0,0"
    para a escola em que só a Educação Infantil usa a plataforma.

    Cartão sem a marca (dado montado fora do ``dashboard_rede``) segue listado
    como antes: a marca só tira da tabela quem o painel disse que está fora."""
    return cartao.get("comparada", True) is not False


_NOME_DA_MATERIA = {"leitura": "Leitura", "matematica": "Matemática"}


def _motivo_fora_da_comparacao(cartao: dict) -> str:
    """Por que a escola não está no "Ranking das escolas" do Boletim.

    A escola que a Secretaria vê escondida (grupo pequeno, sem nenhuma matéria
    visível pontuada) TEM aluno do 1º ao 5º ano com dado, só que poucos: o texto
    de "sem aluno com dado" seria falso num documento oficial. Ela leva o texto
    do painel (``grupo_pequeno.TEXTOS_ESCOLA``), com as matérias escondidas."""
    if cartao.get("grupo_pequeno"):
        oculto = cartao.get("oculto") or {}
        materias = [nome for dimensao, nome in _NOME_DA_MATERIA.items()
                    if (oculto.get(dimensao) or {}).get("motivo")
                    == grupo_pequeno.MOTIVO_GRUPO_PEQUENO]
        texto = grupo_pequeno.TEXTOS_ESCOLA[grupo_pequeno.MOTIVO_GRUPO_PEQUENO]
        return f"{' e '.join(materias)}: {texto}" if materias else texto
    return "Sem aluno do 1º ao 5º ano com dado das plataformas contratadas."


# Coluna de média 0–100 de cada plataforma no Boletim: (módulo, rótulo, campo do
# cartão da escola). Só sai a do módulo contratado (``_medias_do_boletim``).
_MEDIAS_DO_BOLETIM = (("matematica", "Matific", "media_matific"),
                      ("leitura", "Elefante", "media_elefante"))


def _medias_do_boletim(dados: dict) -> list[tuple[str, str]]:
    """``(rótulo, campo)`` das médias de plataforma que o Boletim mostra: só as
    dos módulos contratados (``dados['modulos']``; sem a chave — dado montado fora
    do ``dashboard_rede`` — tudo contratado, como em ``services/modulos``). O que
    a rede não contratou não existe para ela: uma coluna "Matific" com 0,0 em
    todas as escolas seria lida como nota zero em matemática."""
    contratados = dados.get("modulos") or [m for m, _, _ in _MEDIAS_DO_BOLETIM]
    return [(rotulo, campo) for modulo, rotulo, campo in _MEDIAS_DO_BOLETIM
            if modulo in contratados]


def linhas_boletim_rede(dados: dict) -> tuple[list[str], list[list]]:
    """Cabeçalho + linhas do ranking de escolas — base da reserva fpdf e do CSV,
    para o boletim nunca divergir do painel. Só as escolas COMPARADAS
    (``_escola_comparada``): é um ranking, e a escola fora da comparação não tem
    posição nem índice a mostrar. Só as médias das plataformas contratadas
    (``_medias_do_boletim``).

    As médias saem por ``_fmt_nota``, como na tabela HTML: a média nula (matéria
    escondida da Secretaria, grupo pequeno) vira '—', nunca 'None'. O índice
    segue número (é ele que ordena a tabela)."""
    # A coluna que ORDENA a tabela é o Índice (per capita, comparável entre
    # escolas) — sem ela, a Secretaria leria "1º lugar com Geral 25,8" acima de
    # "2º lugar com Geral 100" e concluiria que o boletim está quebrado. As
    # médias 0–100 continuam, como nota INTERNA de cada escola.
    medias = _medias_do_boletim(dados)
    cabecalho = ["#", "Escola", "Alunos", "Adoção %", "Índice",
                 *(rotulo for rotulo, _ in medias), "Geral"]
    linhas = [
        [e.get("posicao", ""), e["nome"], e["total_alunos"], e["adocao"],
         e.get("pontuacao_geral", 0), *(_fmt_nota(e[campo]) for _, campo in medias),
         _fmt_nota(e["media_geral"])]
        for e in dados.get("escolas", []) if _escola_comparada(e)
    ]
    return cabecalho, linhas


# O que cada plataforma leva ao índice do boletim e DE QUANDO é: a leitura é o
# último retrato de cada aluno no Elefante (acumulado desde o início da conta);
# a matemática é o contador do ano letivo do Matific (``rede._matific_no_ano_ativo``).
# Módulo fora do plano não é citado (``services/modulos``).
_PLATAFORMAS_DO_BOLETIM = {
    "leitura": ("Elefante: acumulado desde o início da conta",
                "livros lidos (Elefante, acumulado desde o início da conta)"),
    "matematica": ("Matific: ano letivo", "estrelas (Matific, no ano letivo)"),
}


def _shell_boletim_rede(rede_nome: str, dados: dict,
                        logos: tuple[str, str] | None = None) -> str:
    t = dados.get("totais", {})
    eq = dados.get("equidade", {})
    # Documento para reuniões: cada quadro diz O QUE mede. "adoção" e "média
    # geral" soltos eram lidos como desempenho escolar.
    tiles = [
        (str(t.get("escolas", 0)), "escolas na rede"),
        (f'{int(t.get("alunos", 0)):,}'.replace(",", "."), "alunos"),
        (_fmt_nota(t.get("adocao")) + "%", "alunos com dado de alguma plataforma"),
        (_fmt_nota(t.get("media_geral")), "média das notas do Constela (0–100)"),
    ]
    # Sem a chave (dado montado fora do ``dashboard_rede``) = tudo contratado,
    # como em ``services/modulos``.
    contratados = dados.get("modulos") or list(_PLATAFORMAS_DO_BOLETIM)
    plataformas = [p for m, p in _PLATAFORMAS_DO_BOLETIM.items() if m in contratados]

    # Equidade no ÍNDICE (0–1000, per capita): é o único número comparável entre
    # escolas. Medida nas médias 0–100 ela respondia à dispersão interna de cada
    # escola, não à distância real entre elas. "Maior/menor índice", não
    # "melhor/pior escola": o índice mede o uso das plataformas.
    corpo = ['<h2 class="secao">Equidade entre escolas '
             '<span style="font-weight:400;font-size:.7em">'
             '(índice do Constela, 0–1000 · 1000 = a escola de maior índice da rede)'
             '</span></h2>']
    corpo.append(_report_tiles([
        (_fmt_nota(eq.get("gap_indice")), "diferença maior↔menor índice"),
        (_fmt_nota(eq.get("escola_maior_indice")), "maior índice"),
        (_fmt_nota(eq.get("escola_menor_indice")), "menor índice"),
        (str(eq.get("escolas_abaixo_do_indice_medio", 0)), "abaixo do índice médio"),
    ]))

    atencao = dados.get("atencao", [])
    if atencao:
        corpo.append('<h2 class="secao">Escolas que precisam de atenção</h2>')
        corpo.append('<table class="tab"><thead><tr>'
                     '<th class="esq">Escola</th><th class="esq">Motivo</th>'
                     '</tr></thead><tbody>')
        for e in atencao:
            corpo.append(
                f'<tr><td class="esq nome">{_esc_html(e["nome"])}</td>'
                f'<td class="esq">{_esc_html(e.get("motivo_atencao") or "")}</td></tr>')
        corpo.append('</tbody></table>')

    # As médias de plataforma: só as dos módulos do plano (``_medias_do_boletim``).
    medias = _medias_do_boletim(dados)
    corpo.append('<h2 class="secao">Ranking das escolas</h2>')
    corpo.append('<table class="tab"><thead><tr>'
                 '<th>#</th><th class="esq">Escola</th><th>Alunos</th><th>Adoção</th>'
                 '<th>Índice</th>'
                 + "".join(f"<th>{rotulo}</th>" for rotulo, _ in medias)
                 + '<th>Geral</th></tr></thead><tbody>')
    escolas = dados.get("escolas", [])
    for e in [c for c in escolas if _escola_comparada(c)]:
        corpo.append(
            f'<tr><td class="num">{_esc_html(str(e.get("posicao", "")))}º</td>'
            f'<td class="esq nome">{_esc_html(e["nome"])}</td>'
            f'<td>{_esc_html(str(e["total_alunos"]))}</td>'
            f'<td>{_fmt_nota(e["adocao"])}%</td>'
            f'<td><b>{_fmt_nota(e.get("pontuacao_geral", 0))}</b></td>'
            + "".join(f"<td>{_fmt_nota(e[campo])}</td>" for _, campo in medias)
            + f'<td>{_fmt_nota(e["media_geral"])}</td></tr>')
    corpo.append('</tbody></table>')
    medidas = " e ".join(medida for _, medida in plataformas)
    colunas_0_100 = " · ".join([*(rotulo for rotulo, _ in medias), "Geral"])
    corpo.append(
        '<p style="font-size:.72em;color:#5b6474;margin-top:.4em">'
        f'<b>Índice</b> (0–1000, calculado pelo Constela): {medidas} por aluno do '
        '1º ao 5º ano, na régua da rede — 1000 é a escola de maior índice do '
        'município. É o número que ordena esta tabela e o único comparável entre '
        'escolas de tamanhos diferentes. '
        f'<b>{colunas_0_100}</b> (0–100): nota INTERNA de cada escola, '
        'calculada contra os próprios alunos dela — servem para acompanhar a escola '
        'ao longo do tempo, não para compará-la com outra.</p>')
    # Secretaria: os totais e as médias da rede deixam de fora a matéria das
    # escolas com menos de k alunos com dado (grupo pequeno), e o número difere do
    # que o Admin Global vê. O documento diz isso, com o texto do painel.
    protecao = t.get("grupo_pequeno") or {}
    if any(protecao.get(d) for d in grupo_pequeno.DIMENSOES):
        corpo.append(
            '<p style="font-size:.72em;color:#5b6474;margin-top:.4em">'
            f'<b>Proteção das crianças:</b> {_esc_html(protecao.get("texto") or "")} '
            'Na tabela, “—” é a matéria que não aparece por esse motivo.</p>')

    # A escola FORA da comparação não some do documento: o cartão "escolas na
    # rede" a conta, e a Secretaria precisa achá-la. Vai à parte, só com a
    # cobertura (alunos e adoção) e o MOTIVO de cada uma — sem posição e sem
    # índice, que ela não tem.
    fora = [e for e in escolas if not _escola_comparada(e)]
    if fora:
        corpo.append('<h2 class="secao">Escolas fora da comparação</h2>')
        corpo.append(
            '<p style="font-size:.72em;color:#5b6474;margin:.2em 0 .4em">'
            'Sem posição nem índice: não há o que comparar com as demais '
            'escolas (o motivo de cada uma está na tabela). Os alunos delas '
            'continuam no total de alunos e na adoção da rede.</p>')
        corpo.append('<table class="tab"><thead><tr>'
                     '<th class="esq">Escola</th><th>Alunos</th><th>Adoção</th>'
                     '<th class="esq">Motivo</th></tr></thead><tbody>')
        for e in fora:
            corpo.append(
                f'<tr><td class="esq nome">{_esc_html(e["nome"])}</td>'
                f'<td>{_esc_html(str(e["total_alunos"]))}</td>'
                f'<td>{_fmt_nota(e["adocao"])}%</td>'
                f'<td class="esq">{_esc_html(_motivo_fora_da_comparacao(e))}</td></tr>')
        corpo.append('</tbody></table>')

    # O período de cada plataforma vai ao subtítulo: a leitura NÃO é do ano
    # letivo, e sem isso o documento não dizia de quando são os números.
    subtitulo = " · ".join(["Rede de ensino",
                            f"Gerado em {agora_br().strftime('%d/%m/%Y')}",
                            *(periodo for periodo, _ in plataformas)])
    usam = "as plataformas" if len(plataformas) > 1 else "a plataforma"
    intro = ("Panorama consolidado da rede: a adoção (alunos com dado de alguma "
             "plataforma), o índice de cada escola, a nota do Constela (0–100, cada "
             "aluno comparado com os colegas da própria escola), a equidade entre as "
             "escolas e as unidades que pedem atenção. "
             f"Mostra quanto e como as crianças usam {usam} — não é avaliação "
             "oficial de aprendizagem. <b>Plataforma</b>: o uso e a adoção. "
             "<b>Calculado pelo Constela</b>: o índice e as notas. Apenas dados "
             "agregados por escola — sem identificação de estudantes.")
    return _relatorio_shell("Boletim da Rede", rede_nome, subtitulo, tiles,
                            intro, "".join(corpo), logos)


def gerar_boletim_rede(rede_nome: str, dados: dict, cor: str = COR_PRIMARIA_PADRAO,
                       logos: tuple[str, str] | None = None) -> bytes:
    """Boletim da rede em PDF (vitrine A4 com rodapé/numeração). HTML→Chromium;
    sem navegador (ou erro de render), cai para o PDF simples com a tabela do
    ranking (reserva)."""
    # Monta o HTML FORA do try: um erro de FORMA dos dados (chave faltando) deve
    # aparecer como 500 visível — não degradar calado para a reserva feia. Só a
    # RENDERIZAÇÃO (que pode faltar navegador) fica protegida pela reserva.
    shell = _shell_boletim_rede(rede_nome, dados, logos)
    try:
        return _relatorio_html_pdf(shell)
    except Exception:  # noqa: BLE001 — sem Chromium/erro de render: reserva fpdf
        # Loga (com traceback) para uma falha que NÃO seja 'sem navegador' ficar
        # observável, em vez de o documento de vitrine degradar em silêncio.
        _log.warning("Boletim da rede: render HTML->PDF falhou; usando reserva fpdf.",
                     exc_info=True)
        cabecalho, linhas = linhas_boletim_rede(dados)
        return gerar_pdf("Boletim da Rede", rede_nome, cor, cabecalho, linhas)
