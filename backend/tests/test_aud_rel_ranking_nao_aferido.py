"""Ranking Geral exportado (CSV/XLSX/PDF) e cartaz: a nota da plataforma que a criança
NÃO USA (sem retrato, ``aferido_* = False``) sai vazia/"—", nunca 0,0.

A tela recebe o carimbo ``aferido_*`` e mostra "—" (``notaDaMateria``); o arquivo e o
pôster imprimiam 0,0 — "afirmando desempenho onde só há ausência de dado"
(``rankings._ranking``). O 0,0 de quem usa e ainda não produziu continua 0,0.
Achado RELATORIOS-4.
"""
import csv
import io

from openpyxl import load_workbook

from app.models import Nota
from app.services import relatorios as svc


def _nota(db, escola, aluno, pos, nm, ne, am, al):
    db.add(Nota(escola_id=escola.id, aluno_id=aluno.id, ano_letivo=2026,
                nota_matific=nm, nota_elefante=ne, nota_geral=(nm + ne) / 2,
                posicao=pos, aferido_matematica=am, aferido_leitura=al))


def _cenario(db, escola_completa):
    """A usa as duas; B só usa o Matific; C usa o Elefante e tirou 0 legítimo."""
    escola = escola_completa["escola"]
    a, b, c = escola_completa["alunos"]
    _nota(db, escola, a, 1, 80.0, 70.0, True, True)
    _nota(db, escola, b, 2, 60.0, 0.0, True, False)
    _nota(db, escola, c, 3, 0.0, 0.0, False, True)
    db.commit()
    return escola, a, b, c


def test_linhas_do_ranking_nao_afirmam_zero_de_quem_nao_usa(db, escola_completa):
    escola, a, b, c = _cenario(db, escola_completa)
    cab, linhas = svc.linhas_ranking(db, escola.id)
    por_nome = {linha[1]: dict(zip(cab, linha)) for linha in linhas}
    assert por_nome[a.nome]["Nota Matific"] == 80.0
    assert por_nome[b.nome]["Nota Elefante"] is None
    assert por_nome[b.nome]["Nota Matific"] == 60.0
    assert por_nome[c.nome]["Nota Matific"] is None
    assert por_nome[c.nome]["Nota Elefante"] == 0.0          # zero legítimo continua
    assert [por_nome[n]["Nota Geral"] for n in (a.nome, b.nome, c.nome)] == [75.0, 30.0, 0.0]
    assert [por_nome[n]["Posição"] for n in (a.nome, b.nome, c.nome)] == [1, 2, 3]


def test_csv_e_xlsx_saem_vazios_para_quem_nao_usa(cliente, db, escola_completa):
    escola, _a, b, c = _cenario(db, escola_completa)
    url = f"/api/v1/escolas/{escola.id}/relatorios/ranking"

    resp = cliente.get(url, params={"formato": "csv"})
    assert resp.status_code == 200, resp.text
    linhas = list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))
    cab = linhas[0]
    por_nome = {linha[1]: dict(zip(cab, linha)) for linha in linhas[1:]}
    assert por_nome[b.nome]["Nota Elefante"] == "", (
        "o CSV afirma Nota Elefante 0.0 para quem não usa o Elefante")
    assert por_nome[c.nome]["Nota Matific"] == ""
    assert por_nome[c.nome]["Nota Elefante"] == "0.0"

    resp = cliente.get(url, params={"formato": "xlsx"})
    assert resp.status_code == 200, resp.text
    ws = load_workbook(io.BytesIO(resp.content)).active
    cab = [cel.value for cel in ws[2]]
    linhas_x = {row[1]: dict(zip(cab, row)) for row in ws.iter_rows(min_row=3, values_only=True)}
    assert linhas_x[b.nome]["Nota Elefante"] is None
    assert linhas_x[c.nome]["Nota Matific"] is None
    assert linhas_x[c.nome]["Nota Elefante"] == 0.0


def test_cartaz_e_reserva_mostram_traco_para_quem_nao_usa(db, escola_completa,
                                                          monkeypatch):
    escola, _a, b, _c = _cenario(db, escola_completa)
    cab, linhas = svc.linhas_ranking(db, escola.id)
    html = svc._cartaz_documento_html(escola.nome, 2026, linhas, {}, cabecalho=cab)
    trecho = html[html.index(b.nome):html.index(b.nome) + 200]
    assert "<td>60,0</td><td>—</td>" in trecho, trecho

    # Reserva fpdf (sem Chromium): a célula não vira "None".
    vistos: list[str] = []
    original = svc._couber

    def _espia(pdf, texto, largura):
        saida = original(pdf, texto, largura)
        vistos.append(saida)
        return saida

    monkeypatch.setattr(svc, "_couber", _espia)
    assert svc.gerar_pdf("Ranking Geral", escola.nome, "#1B2A4A", cab, linhas)[:4] == b"%PDF"
    assert "None" not in vistos
