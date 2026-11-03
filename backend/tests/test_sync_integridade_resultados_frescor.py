"""Documentos de ranking dizem DE QUANDO é o dado (frente C, 22/10/2026).

O selo de frescor do c5e78d3 (``/ranking/frescor``, ``services.frescor_ranking``)
cobria as telas de ranking. O cartaz e o certificado de Mérito saíam só com a
data de EMISSÃO: nas escolas 1, 7, 8 e 11 a coleta tinha parado em 01–05/10, e o
pôster impresso em 20/10 tinha a mesma cara de um de ontem. Agora os dois PDFs
imprimem "Dados das plataformas: Leitura de DD/MM/AAAA; Matemática de DD/MM/AAAA"
— a MESMA data do selo —, em latin-1 puro (a reserva usa as fontes do fpdf).
Nenhuma fórmula muda. Dados fictícios.
"""
import io
from datetime import date, datetime

import pytest
from pypdf import PdfReader

from app.models import Importacao, SnapshotElefante, SnapshotMatific
from app.services import frescor_ranking, relatorios as svc, scoring

API = "/api/v1"
#: 22h30 de 18/10 em Brasília = 01h30 de 19/10 em UTC: o dia do dado é 18/10.
COLETA_NOITE_UTC = datetime(2026, 10, 19, 1, 30)
COLETA_MANHA_UTC = datetime(2026, 10, 1, 10, 0)


def _texto_pdf(conteudo: bytes) -> str:
    return "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(conteudo)).pages)


def _cenario(db, escola_completa):
    escola = escola_completa["escola"]
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    for i, aluno in enumerate(escola_completa["alunos"], start=1):
        aluno.da_lista_piloto = True
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                                data_referencia=COLETA_NOITE_UTC, livros_unicos=3 * i,
                                livros_por_nivel={"D": 3 * i}, tempo_leitura_min=30 * i,
                                questoes_tentativas=i, questoes_acertos=i))
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                               data_referencia=COLETA_MANHA_UTC, atividades=5 * i,
                               estrelas=10 * i, pontuacao_media=3.0))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    db.commit()
    return escola


# ---------------------------------------------------------------------------
# A legenda
# ---------------------------------------------------------------------------
def test_legenda_usa_a_data_do_selo_em_latin1(db, escola_completa):
    escola = _cenario(db, escola_completa)
    frescor = frescor_ranking.frescor_da_escola(db, escola, date(2026, 10, 22))
    legenda = svc.legenda_data_dos_dados(frescor, ["leitura", "matematica"])
    assert legenda == ("Dados das plataformas: Leitura de 18/10/2026; "
                       "Matemática de 01/10/2026 (mais de 7 dias)")
    legenda.encode("latin-1")    # não levanta: cabe nas fontes nativas do PDF
    for proibido in ("…", "—", "“", "”", "‘", "’"):
        assert proibido not in legenda
    assert svc.legenda_data_dos_dados(frescor, ["leitura"]) == \
        "Dados das plataformas: Leitura de 18/10/2026"


def test_legenda_sem_dados_e_sem_modulo():
    frescor = {"limite_dias": 7, "dimensoes": {
        "leitura": {"contratada": True, "estado": "sem_dados", "dado_mais_recente_em": None},
        "matematica": {"contratada": False, "estado": None, "dado_mais_recente_em": None}}}
    assert svc.legenda_data_dos_dados(frescor, ["leitura", "matematica"]) == \
        "Dados das plataformas: Leitura sem dados"
    assert svc.legenda_data_dos_dados(frescor, ["matematica"]) is None
    assert svc.legenda_data_dos_dados(None, ["leitura"]) is None


# ---------------------------------------------------------------------------
# Cartaz
# ---------------------------------------------------------------------------
def _fixar_hoje(monkeypatch):
    """O "hoje" do selo na rota fica fixo: o teste não depende do relógio."""
    from app.routers import relatorios as rota
    monkeypatch.setattr(rota, "hoje_br", lambda: date(2026, 10, 22))


def _espiar_cartaz(monkeypatch):
    from app.routers import relatorios as rota
    _fixar_hoje(monkeypatch)
    chamadas = []

    def _espia(**kw):
        chamadas.append(kw)
        return b"%PDF-ficticio"
    monkeypatch.setattr(rota.svc, "gerar_cartaz_ranking", _espia)
    return chamadas


@pytest.mark.parametrize("dimensao,esperado", [
    (None, "Leitura de 18/10/2026; Matemática de 01/10/2026"),
    ("leitura", "Leitura de 18/10/2026"),
    ("matematica", "Matemática de 01/10/2026"),
])
def test_rota_do_cartaz_entrega_a_data_do_dado(db, cliente, escola_completa, monkeypatch,
                                                dimensao, esperado):
    escola = _cenario(db, escola_completa)
    chamadas = _espiar_cartaz(monkeypatch)
    url = f"{API}/escolas/{escola.id}/ranking/cartaz"
    r = cliente.get(url + (f"?dimensao={dimensao}" if dimensao else ""))
    assert r.status_code == 200, r.text
    assert esperado in chamadas[0]["dados_em"]
    if dimensao == "leitura":
        assert "Matemática" not in chamadas[0]["dados_em"]


def test_cartaz_html_e_reserva_imprimem_a_data_do_dado(monkeypatch):
    legenda = "Dados das plataformas: Leitura de 18/10/2026"
    linhas = [[1, "Crianca Ficticia", "3º Ano A", "3º Ano", 87.5]]
    html = svc._cartaz_documento_html("ESCOLA X", 2026, linhas, {}, materia="leitura",
                                      dados_em=legenda)
    assert legenda in html and "Gerado em" in html and "⟦" not in html
    assert "⟦" not in svc._cartaz_documento_html("ESCOLA X", 2026, linhas, {},
                                                 materia="leitura")

    def _sem_chromium(*a, **k):
        raise RuntimeError("sem navegador (teste)")
    monkeypatch.setattr(svc, "_cartaz_html_pdf", _sem_chromium)
    pdf = svc.gerar_cartaz_ranking(
        escola_nome="ESCOLA X", cor="#1B2A4A", ano_letivo=2026,
        cabecalho=svc.cabecalho_cartaz_materia("leitura"), linhas=linhas,
        estatisticas={}, materia="leitura", dados_em=legenda)
    assert "Leitura de 18/10/2026" in _texto_pdf(pdf)


# ---------------------------------------------------------------------------
# Certificado de Mérito
# ---------------------------------------------------------------------------
def test_rota_do_merito_entrega_a_data_do_dado(db, cliente, escola_completa, monkeypatch):
    from app.routers import relatorios as rota
    escola = _cenario(db, escola_completa)
    _fixar_hoje(monkeypatch)
    capturado = {}

    def _falso(**kw):
        capturado.update(kw)
        return b"%PDF-ficticio"
    monkeypatch.setattr(rota.svc, "gerar_certificado", _falso)
    aluno = escola_completa["alunos"][2]
    r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{aluno.id}")
    assert r.status_code == 200, r.text
    assert "Leitura de 18/10/2026" in capturado["dados_em"]
    assert "Matemática de 01/10/2026" in capturado["dados_em"]


def test_merito_html_e_reserva_imprimem_a_data_do_dado(monkeypatch):
    legenda = "Dados das plataformas: Leitura de 18/10/2026; Matemática de 01/10/2026"
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
                              2, 81.5, 2026, dados_em=legenda)
    assert legenda in capturado["doc"] and "⟦" not in capturado["doc"]

    reserva = svc._certificado_fpdf("ESCOLA X", "#1B2A4A", "Crianca Ficticia", "3º Ano A",
                                    2, 81.5, 2026, dados_em=legenda)
    texto = _texto_pdf(reserva)
    assert "Leitura de 18/10/2026" in texto and "01/10/2026" in texto


def test_merito_sem_legenda_continua_como_antes(monkeypatch):
    reserva = svc._certificado_fpdf("ESCOLA X", "#1B2A4A", "Crianca Ficticia", "3º Ano A",
                                    2, 81.5, 2026)
    assert "Dados das plataformas" not in _texto_pdf(reserva)



# ---------------------------------------------------------------------------
# "Última sincronização com dado aplicado" segue o contrato da ETAPA 2
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status,qtd_alunos,conta", [
    ("concluida", 2, True), ("parcial", 1, True),
    # P18: a 'parcial' com 0 aluno aplicado (D2(6)) não aplicou dado. A 'concluida'
    # conta sem condição, como antes (a linha antiga com 0 aluno inclusive).
    ("parcial", 0, False), ("concluida", 0, True),
    ("sem_atualizacao", 0, False), ("sem_dados", 0, False), ("erro", 0, False),
])
def test_ultima_sincronizacao_ok_e_a_que_aplicou_dado(db, escola_completa, status, qtd_alunos,
                                                      conta):
    """``parcial`` com aluno aplicado (com falha em parte) conta como último sucesso;
    a ``parcial`` sem aluno aplicado, ``sem_atualizacao``, ``sem_dados`` e ``erro``
    não. Informativo: o estado do selo continua decidido pela data do RETRATO."""
    from app.models.sincronizacao import SincronizacaoExecucao
    escola = _cenario(db, escola_completa)
    db.add(SincronizacaoExecucao(escola_id=escola.id, plataforma="elefante", origem="manual",
                                 status=status, qtd_alunos=qtd_alunos,
                                 finalizada_em=datetime(2026, 10, 19, 2, 0)))
    db.commit()
    bloco = frescor_ranking.frescor_da_escola(db, escola, date(2026, 10, 22))["dimensoes"]["leitura"]
    assert (bloco["ultima_sincronizacao_ok_em"] is not None) is conta
    assert bloco["dado_mais_recente_em"] == "2026-10-18"
