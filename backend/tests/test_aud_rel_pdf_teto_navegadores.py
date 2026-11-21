"""PDF bonito (cartaz, certificado, certificado da plataforma, relatórios de vitrine):
há um TETO de navegadores Chromium abertos ao mesmo tempo no processo.

Cada PDF subia o seu ``sync_playwright()`` (um processo Node do driver) e o seu
``chromium.launch()`` (~150–300 MB), sem fila: doze pedidos juntos no fim do bimestre
eram doze navegadores. Achado DESEMPENHO-4. O Chromium aqui é FALSO (não abre
navegador nenhum): conta os lançamentos simultâneos e "renderiza" devagar.
"""
import sys
import threading
import time
import types

import pytest

from app.services import relatorios as svc


class _Contador:
    def __init__(self):
        self.trava = threading.Lock()
        self.drivers = self.navegadores = 0
        self.pico_drivers = self.pico_navegadores = 0
        self.total = 0


def _playwright_falso(contador: _Contador, demora: float = 0.15, falhar: bool = False):
    class _Pagina:
        def set_content(self, *a, **k):
            time.sleep(demora)
            if falhar:
                raise RuntimeError("falha de render (forçada pelo teste)")

        def pdf(self, *a, **k):
            return b"%PDF-1.4 falso"

    class _Navegador:
        def __init__(self):
            with contador.trava:
                contador.navegadores += 1
                contador.total += 1
                contador.pico_navegadores = max(contador.pico_navegadores,
                                                contador.navegadores)

        def new_page(self, *a, **k):
            return _Pagina()

        def close(self):
            with contador.trava:
                contador.navegadores -= 1

    class _Chromium:
        def launch(self, *a, **k):
            return _Navegador()

    class _P:
        chromium = _Chromium()

    class _Driver:
        def __enter__(self):
            with contador.trava:
                contador.drivers += 1
                contador.pico_drivers = max(contador.pico_drivers, contador.drivers)
            return _P()

        def __exit__(self, *exc):
            with contador.trava:
                contador.drivers -= 1
            return False

    modulo = types.ModuleType("playwright.sync_api")
    modulo.sync_playwright = lambda: _Driver()
    return modulo


_GERADORES = [
    lambda: svc._relatorio_html_pdf("<p>relatório fictício</p>"),
    lambda: svc._html_para_pdf_paisagem("<p>certificado fictício</p>"),
    lambda: svc._cartaz_html_pdf("Escola Ficticia", 2026, [], {}),
    lambda: svc._certificado_html_pdf("Escola Ficticia", "#1B2A4A", "Aluno Ficticio",
                                      "3º Ano A", 1, 87.5, 2026),
]


def _em_paralelo(funcoes) -> list:
    saidas: list = [None] * len(funcoes)
    erros: list = []

    def rodar(i, f):
        try:
            saidas[i] = f()
        except Exception as exc:  # noqa: BLE001
            erros.append(exc)
    threads = [threading.Thread(target=rodar, args=(i, f)) for i, f in enumerate(funcoes)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not erros, erros
    return saidas


def test_doze_pdfs_juntos_nao_abrem_doze_navegadores(monkeypatch):
    contador = _Contador()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", _playwright_falso(contador))
    saidas = _em_paralelo([_GERADORES[i % 4] for i in range(12)])
    linha = (f"pico de navegadores = {contador.pico_navegadores}, de drivers = "
             f"{contador.pico_drivers}, lançados = {contador.total}")
    assert all(s == b"%PDF-1.4 falso" for s in saidas), linha
    assert contador.total == 12, linha
    teto = 2                     # o padrão por processo (``NAVEGADORES_SIMULTANEOS``)
    assert contador.pico_navegadores <= teto, linha
    assert contador.pico_drivers <= teto, linha
    assert svc.NAVEGADORES_SIMULTANEOS == teto


def test_falha_de_render_devolve_a_vaga(monkeypatch):
    contador = _Contador()
    monkeypatch.setitem(sys.modules, "playwright.sync_api",
                        _playwright_falso(contador, demora=0, falhar=True))
    for _ in range(svc.NAVEGADORES_SIMULTANEOS + 3):
        with pytest.raises(RuntimeError, match="forçada pelo teste"):
            svc._relatorio_html_pdf("<p>x</p>")
    assert contador.navegadores == 0 and contador.drivers == 0
    # Todas as vagas voltaram: um PDF bom ainda sai.
    monkeypatch.setitem(sys.modules, "playwright.sync_api", _playwright_falso(contador, 0))
    assert svc._relatorio_html_pdf("<p>x</p>") == b"%PDF-1.4 falso"


def test_sem_vaga_no_prazo_cai_na_reserva_sem_abrir_navegador(monkeypatch, caplog):
    """Esgotado o prazo de espera, o certificado sai pela reserva (fpdf) — o mesmo
    caminho de quando não há Chromium — e nenhum navegador a mais é aberto."""
    contador = _Contador()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", _playwright_falso(contador))
    monkeypatch.setattr(svc, "ESPERA_POR_NAVEGADOR_S", 0.2)
    ocupadas = 0
    try:
        while svc._VAGAS_DE_NAVEGADOR.acquire(blocking=False):
            ocupadas += 1
        assert ocupadas == svc.NAVEGADORES_SIMULTANEOS
        inicio = time.monotonic()
        with pytest.raises(svc.NavegadorOcupado):
            svc._relatorio_html_pdf("<p>x</p>")
        pdf = svc.gerar_certificado("Escola Ficticia", "#1B2A4A", "Aluno Ficticio",
                                    "3º Ano A", 1, 87.5, 2026)
        assert time.monotonic() - inicio < 5
    finally:
        for _ in range(ocupadas):
            svc._VAGAS_DE_NAVEGADOR.release()
    assert pdf[:5] == b"%PDF-"
    assert contador.total == 0
