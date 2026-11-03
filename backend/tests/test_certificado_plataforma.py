"""Certificado por plataforma (Elefante Letrado / Matific) — preenchimento
automático (instituição, nome, bimestre, data) sobre a arte oficial, em PDF."""
from pathlib import Path

import pytest

from app.models import Aluno
from app.services import relatorios as svc

API = "/api/v1"

# Nome FICTÍCIO com a MESMA contagem de caracteres (34) E a MESMA largura medida
# (20,726 em) do nome oficial da escola 17 — o que a prova e90 pegou cortado —, nas
# duas grafias em uso (com e sem espaços em volta da barra), e um nome FICTÍCIO bem
# mais longo que qualquer escola da rede. As DUAS medidas importam: a regra nova
# olha a largura, mas a ANTIGA contava caracteres (360 / (caracteres × 0,58): 34
# caracteres → 18px = 373 px, cortado na caixa de 359 px). Um nome só com a largura
# igual e 36 caracteres saía a 17px = 352 px pela regra antiga e cabia: a volta da
# contagem de caracteres passava sem nenhum teste vermelho. Sem escrever nome de
# escola real em teste (lacuna C5 do e97).
NOME_17 = "EMEI/EMEF OTTO INVENTADO DO OSÓRIO"
NOME_17_ESPACOS = "EMEI / EMEF OTTO INVENTADO DO OSÓRIO"
LARGURA_DO_NOME_OFICIAL_17_EM = 20.726
CARACTERES_DO_NOME_OFICIAL_17 = 34
NOME_FICTICIO_LONGO = ("ESCOLA MUNICIPAL DE EDUCAÇÃO INFANTIL E ENSINO FUNDAMENTAL "
                       "PROFESSORA FICTÍCIA DE EXEMPLO DA SILVA")
NOMES_LONGOS = (NOME_17, NOME_17_ESPACOS, NOME_FICTICIO_LONGO)
# Arquivos de fonte com as métricas do Arial (o Chromium do servidor usa a
# Liberation Sans, metricamente igual): a medida independente da do serviço.
_FONTES_ARIAL = ("C:/Windows/Fonts/arial.ttf",
                 "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                 "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf")


def test_bimestre_por_mes():
    assert svc._bimestre_por_mes(2) == 1 and svc._bimestre_por_mes(4) == 1
    assert svc._bimestre_por_mes(5) == 2 and svc._bimestre_por_mes(7) == 2
    assert svc._bimestre_por_mes(8) == 3 and svc._bimestre_por_mes(9) == 3
    assert svc._bimestre_por_mes(10) == 4 and svc._bimestre_por_mes(12) == 4


def test_tam_fonte_nome_encolhe_para_nomes_longos():
    assert svc._tam_fonte_nome("Ana") == 60                      # curto → teto
    assert svc._tam_fonte_nome("Fulana Ficticia Exemplo Teste") < 42  # longo → encolhe


def test_html_plataforma_preenche_e_resolve_tudo():
    html = svc._certificado_plataforma_html("Escola Municipal Teste", "João da Silva", "elefante")
    assert "Escola Municipal Teste" in html          # instituição
    assert "João da Silva" in html                   # nome (maiúsculo é via CSS)
    assert "data:image/png;base64," in html          # a arte embutida
    assert "⟦" not in html and "⟧" not in html       # nenhum placeholder sobrou


def test_html_plataforma_arte_e_posicoes_por_plataforma():
    h_el = svc._certificado_plataforma_html("E", "A", "elefante")
    h_mt = svc._certificado_plataforma_html("E", "A", "matific")
    assert h_el != h_mt                               # arte + coordenadas diferentes


# ---------------------------------------------------------------------------
# Nome da escola na caixa do certificado (prova e90: o nome oficial da escola 17
# saía com 18px = 373,0 px numa caixa de 359,2 px e era cortado).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nome", NOMES_LONGOS)
def test_nome_longo_da_escola_cabe_na_caixa_pela_largura_medida(nome):
    largura_caixa, altura_caixa = svc.CAIXA_INSTITUICAO_PX
    tam, linhas = svc._layout_instituicao(nome)
    assert tam >= 9
    assert " ".join(linhas) == " ".join(nome.split())          # nada some do nome
    for linha in linhas:
        assert svc._largura_em(linha) * tam <= largura_caixa, (linha, tam)
    assert len(linhas) * tam <= altura_caixa                    # line-height 1
    assert svc._tam_fonte_instituicao(nome) == tam


def test_nome_ficticio_tem_a_largura_do_nome_oficial_da_escola_17():
    """A troca pelo nome fictício não afrouxa a prova: a largura é a mesma, ao
    milésimo de em, e o número de caracteres também, nas duas grafias (a com
    espaços tem 2 espaços a mais) — então ele pega a regra antiga, que contava
    caracteres, tanto quanto o nome real."""
    assert svc._largura_em(NOME_17) == pytest.approx(LARGURA_DO_NOME_OFICIAL_17_EM)
    assert svc._largura_em(NOME_17_ESPACOS) == pytest.approx(
        LARGURA_DO_NOME_OFICIAL_17_EM + 2 * svc._largura_em(" "))
    assert len(NOME_17) == CARACTERES_DO_NOME_OFICIAL_17
    assert len(NOME_17_ESPACOS) == CARACTERES_DO_NOME_OFICIAL_17 + 2
    for nome in (NOME_17, NOME_17_ESPACOS):                     # a regra antiga cortava
        antiga = max(9, min(20, int(360 / (len(nome) * 0.58))))
        assert antiga * svc._largura_em(nome) > svc.CAIXA_INSTITUICAO_PX[0], nome


def test_nome_da_escola_17_numa_linha_e_o_muito_longo_em_duas():
    tam, linhas = svc._layout_instituicao(NOME_17)
    assert linhas == [NOME_17] and tam < 18                     # antes: 18px = 373 px
    tam_longo, linhas_longo = svc._layout_instituicao(NOME_FICTICIO_LONGO)
    assert len(linhas_longo) == 2 and tam_longo >= 11


def test_nome_que_ja_cabia_nao_muda_de_corpo():
    assert svc._tam_fonte_instituicao("Escola Municipal Teste") == 20
    assert svc._tam_fonte_instituicao("EMEF FICTÍCIA AURORA") == 20


@pytest.mark.parametrize("nome", NOMES_LONGOS)
def test_nome_longo_cabe_medido_com_o_arquivo_da_fonte(nome):
    """Medida INDEPENDENTE da do serviço: o arquivo do Arial / Liberation Sans."""
    caminho = next((c for c in _FONTES_ARIAL if Path(c).exists()), None)
    if caminho is None:
        pytest.skip("sem arquivo de fonte com as métricas do Arial nesta máquina")
    from PIL import ImageFont

    tam, linhas = svc._layout_instituicao(nome)
    fonte = ImageFont.truetype(caminho, tam)
    for linha in linhas:
        assert fonte.getlength(linha) <= svc.CAIXA_INSTITUICAO_PX[0], (linha, tam)


def test_html_quebra_o_nome_muito_longo_e_escapa_cada_linha():
    html = svc._certificado_plataforma_html(NOME_FICTICIO_LONGO + " & CIA", "Aluno", "elefante")
    _tam, linhas = svc._layout_instituicao(NOME_FICTICIO_LONGO + " & CIA")
    assert "<br>".join(svc._esc_html(linha) for linha in linhas) in html
    assert "&amp; CIA" in html
    curto = svc._certificado_plataforma_html(NOME_17, "Aluno", "elefante")
    assert f"<span>{NOME_17}</span>" in curto                    # uma linha, sem <br>


def _chromium():
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        return None
    return sync_playwright


@pytest.mark.parametrize("fonte", [None, "Arial"])
def test_nome_longo_cabe_na_caixa_renderizada_pelo_chromium(fonte):
    """O navegador de verdade: o texto do nome não passa da caixa (largura nem
    altura). ``fonte=None`` é a pilha da arte (no Windows, a Trebuchet MS);
    ``Arial`` simula o servidor (Liberation Sans, mesmas métricas)."""
    sync_playwright = _chromium()
    if sync_playwright is None:
        pytest.skip("sem Playwright")
    medidas = []
    with sync_playwright() as p:
        try:
            try:
                nav = p.chromium.launch()
            except Exception:  # noqa: BLE001
                nav = p.chromium.launch(channel="chrome")
        except Exception:  # noqa: BLE001
            pytest.skip("sem Chromium (igual ao job da CI)")
        try:
            pagina = nav.new_page()
            for nome in NOMES_LONGOS:
                corpo = svc._certificado_plataforma_html(nome, "Aluno Ficticio", "elefante")
                if fonte:
                    corpo += f"<style>.instituicao{{font-family:'{fonte}'}}</style>"
                pagina.set_content("<!doctype html><html><head><meta charset='utf-8'>"
                                   f"</head><body>{corpo}</body></html>")
                medidas.append((nome, pagina.evaluate(
                    "() => { const c = document.querySelector('.instituicao');"
                    " const t = c.firstElementChild.getBoundingClientRect();"
                    " const r = c.getBoundingClientRect();"
                    " return [t.width, t.height, r.width, r.height]; }")))
        finally:
            nav.close()
    for nome, (larg_texto, alt_texto, larg_caixa, alt_caixa) in medidas:
        assert abs(larg_caixa - svc.CAIXA_INSTITUICAO_PX[0]) < 1
        assert larg_texto <= larg_caixa, (nome, larg_texto, larg_caixa)
        assert alt_texto <= alt_caixa + 0.5, (nome, alt_texto, alt_caixa)


def test_endpoint_emite_pdf_por_plataforma(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    # `da_lista_piloto=True`: a arte de participação não passa pela guarda de nota,
    # mas passa pela da Lista Piloto — ficha não confirmada não recebe NENHUM dos
    # três documentos. Ver ``test_certificado_lista_piloto``.
    aluno = Aluno(escola_id=escola.id, nome="Maria Teste", da_lista_piloto=True)
    db.add(aluno)
    db.commit()

    for modelo in ("elefante", "matific"):
        r = cliente.get(f"{API}/escolas/{escola.id}/certificados/{aluno.id}?modelo={modelo}")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:4] == b"%PDF"                # PDF de verdade
