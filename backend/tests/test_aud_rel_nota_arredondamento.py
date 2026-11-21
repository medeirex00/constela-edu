"""Nota com uma casa nos documentos (certificado Geral, reserva fpdf e cartaz): o 5
arredonda PARA CIMA, sempre, a partir do número gravado.

O ``f"{valor:.1f}"`` arredonda o float binário: 87,25 virava "87,2", 87,35 virava
"87,3", mas 87,15 virava "87,2" e 87,45 "87,5" — sem regra que a escola reconheça.
As notas são gravadas com 2 casas (``scoring._nota_0_100``). Achado RELATORIOS-11.
"""
import io

import pytest
from pypdf import PdfReader

from app.services import relatorios as svc


@pytest.mark.parametrize("valor,texto", [
    (87.15, "87,2"), (87.25, "87,3"), (87.35, "87,4"), (87.45, "87,5"),
    (87.55, "87,6"), (87.65, "87,7"), (87.75, "87,8"), (87.85, "87,9"),
    (87.95, "88,0"), (0.05, "0,1"), (99.95, "100,0"),
    (0, "0,0"), (100, "100,0"), (85.3, "85,3"), (1000.0, "1000,0"), ("72.5", "72,5"),
    (None, "—"), ("", "—"), ("x", "—"), (float("nan"), "—"),
])
def test_fmt_nota_arredonda_o_5_para_cima(valor, texto):
    assert svc._fmt_nota(valor) == texto


def _doc_do_certificado(monkeypatch, nota: float) -> str:
    capturado = {}

    class _Pagina:
        def set_content(self, doc, wait_until=None):
            capturado["doc"] = doc

        def pdf(self, **_kw):
            return b"%PDF-ficticio"

    class _Navegador:
        def new_page(self):
            return _Pagina()

        def close(self):
            pass

    class _Playwright:
        class chromium:  # noqa: N801 — imita o atributo do Playwright
            @staticmethod
            def launch(**_kw):
                return _Navegador()

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    import playwright.sync_api
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", lambda: _Playwright())
    svc._certificado_html_pdf("ESCOLA X", "#1B2A4A", "Crianca Ficticia", "3º Ano A",
                              12, nota, 2026)
    return capturado["doc"]


def test_certificado_geral_e_reserva_imprimem_87_3_para_87_25(monkeypatch):
    doc = _doc_do_certificado(monkeypatch, 87.25)
    assert "alcançou a nota geral <b>87,3</b>" in doc

    reserva = svc._certificado_fpdf("ESCOLA X", "#1B2A4A", "Crianca Ficticia",
                                    "3º Ano A", 12, 87.25, 2026)
    texto = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(reserva)).pages)
    assert "nota geral 87,3" in texto, texto


def test_reserva_do_certificado_nao_troca_ponto_do_nome_da_turma():
    """A vírgula decimal é só da nota: o ponto do nome da turma fica."""
    reserva = svc._certificado_fpdf("ESCOLA X", "#1B2A4A", "Crianca Ficticia",
                                    "3º Ano A.1", 12, 87.25, 2026)
    texto = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(reserva)).pages)
    assert "da turma 3º Ano A.1, alcançou a nota geral 87,3" in texto, texto


def test_cartaz_usa_o_mesmo_arredondamento():
    html = svc._linhas_cartaz_html([[1, "Ana", "3º Ano A", "3º Ano", 87.15, 87.35, 87.25]])
    assert "<td>87,2</td><td>87,4</td><td class=\"geral\">87,3</td>" in html
