"""Certificado Geral com nome longo: o texto não desce até a linha de assinatura.

O nome sai em ``.aluno`` (maiúsculas, 40px fixos) num fluxo de altura livre, e a
assinatura é absoluta a 26mm do rodapé. Um nome com mais de ~58 caracteres quebrava em
3 linhas e empurrava "Emitido em" e "Dados das plataformas" para cima da linha de
assinatura (a linha riscava o texto). Achado RELATORIOS-8.

Mede no Chromium de verdade (pula sem Playwright/Chromium, como o job da CI).
"""
import pytest

from app.services import relatorios as svc

DADOS = "Dados das plataformas: Leitura de 19/10/2026; Matemática de 18/10/2026"
ESCOLA_CURTA = "EMEF JOAO THIMOTEO"
ESCOLA_LONGA = ("EMEF PROFESSORA MARIA APARECIDA DE OLIVEIRA SANTOS CARVALHO "
                "- JARDIM CALIFÓRNIA")
NOME_43 = "Maria Eduarda Aparecida dos Santos Oliveira"
NOME_62 = "Maria Eduarda Aparecida dos Santos Oliveira de Souza Fernandes"
NOME_80 = ("Maria Eduarda Aparecida dos Santos Oliveira de Souza Fernandes "
           "Albuquerque Cavalcanti")

_MEDIR = """() => {
  const linha = document.querySelector('.assinatura .linha').getBoundingClientRect();
  let fim = 0;
  for (const el of document.querySelectorAll('.conteudo *')) {
    const r = el.getBoundingClientRect();
    if (r.height > 0) fim = Math.max(fim, r.bottom);
  }
  const range = document.createRange();
  range.selectNodeContents(document.querySelector('.aluno'));
  const linhas = new Set(Array.from(range.getClientRects()).map((r) => Math.round(r.top)));
  return [linha.top - fim, linhas.size];
}"""


def _doc(monkeypatch, escola: str, nome: str) -> str:
    """O HTML que o Chromium imprimiria (capturado sem gerar o PDF)."""
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
    with monkeypatch.context() as m:
        m.setattr(playwright.sync_api, "sync_playwright", lambda: _Playwright())
        svc._certificado_html_pdf(escola, "#1B2A4A", nome, "3º Ano A", 12, 87.5, 2026,
                                  dados_em=DADOS)
    return capturado["doc"]


def _medir(docs: list[str]) -> list[tuple[float, int]]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        pytest.skip("sem Playwright")
    with sync_playwright() as p:
        try:
            try:
                nav = p.chromium.launch()
            except Exception:  # noqa: BLE001
                nav = p.chromium.launch(channel="chrome")
        except Exception:  # noqa: BLE001
            pytest.skip("sem Chromium (igual ao job da CI)")
        try:
            # A4 paisagem a 96 px/pol (a página que o PDF imprime).
            pagina = nav.new_page(viewport={"width": 1123, "height": 794})
            medidas = []
            for doc in docs:
                pagina.set_content(doc)
                medidas.append(tuple(pagina.evaluate(_MEDIR)))
            return medidas
        finally:
            nav.close()


def test_nome_longo_nao_encosta_na_linha_de_assinatura(monkeypatch):
    casos = [(ESCOLA_CURTA, NOME_43), (ESCOLA_LONGA, NOME_43),
             (ESCOLA_CURTA, NOME_62), (ESCOLA_LONGA, NOME_62), (ESCOLA_LONGA, NOME_80)]
    docs = [_doc(monkeypatch, escola, nome) for escola, nome in casos]
    for (escola, nome), (folga, linhas) in zip(casos, _medir(docs), strict=True):
        assert linhas <= 2, (escola, nome, linhas)
        # Folga de pelo menos ~5mm entre o fim do texto e a linha de assinatura.
        assert folga >= 18, (escola, nome, folga)


def test_nome_que_ja_cabia_em_duas_linhas_nao_muda():
    """Até duas linhas no corpo de sempre (40px), nada muda; acima disso, o corpo
    encolhe — com piso legível."""
    assert svc._tam_fonte_aluno_certificado("Ana Souza") == 40
    assert svc._tam_fonte_aluno_certificado(NOME_43) == 40
    assert 22 <= svc._tam_fonte_aluno_certificado(NOME_62) < 40
    assert (svc._tam_fonte_aluno_certificado(NOME_80)
            <= svc._tam_fonte_aluno_certificado(NOME_62))
    assert svc._tam_fonte_aluno_certificado("") == 40
