"""PDF do Relatório por Período: toda referência a uma seção aponta para uma seção
que existe no documento.

A linha "Tempo por registro de leitura" do resumo mandava "ver as notas finais", mas
o PDF não tem seção com esse nome: a explicação está em "O QUE ESTE RELATÓRIO NÃO
RESPONDE" (vitrine). Na reserva (fpdf), essas linhas nem tinham título. Achado
RELATORIOS-9. Escola e números INVENTADOS.
"""
import re

from app.services import relatorios_periodo_pdf as pdf
from tests.test_relatorios_periodo_pdf import (  # noqa: F401 — `cenario` é fixture
    _dados_das_duas_plataformas, _texto, _texto_da_vitrine, cenario)

# "ver “Título”" / "ver 'Título'" — e o "ver as notas finais" que não apontava para nada.
_REFERENCIA = re.compile(r"ver [“'\"]([^”'\"]+)[”'\"]")


def _detalhe_do_tempo_por_registro(dados) -> str:
    return next(fonte for rotulo, _v, fonte in pdf.linhas_resumo(dados)
                if rotulo == "Tempo por registro de leitura")


def test_vitrine_toda_referencia_aponta_para_titulo_de_secao(db, cenario):  # noqa: F811
    dados = _dados_das_duas_plataformas(db, cenario)
    html = pdf.montar_html(dados)
    titulos = {t.strip().upper() for t in re.findall(r'<h2 class="secao">([^<]+)</h2>', html)}
    texto = _texto_da_vitrine(html)
    assert "notas finais" not in texto.lower(), "o PDF manda para 'notas finais', que não existe"
    referencias = _REFERENCIA.findall(texto)
    assert referencias, "a linha do tempo por registro deixou de dizer onde está a explicação"
    faltam = [r for r in referencias if r.strip().upper() not in titulos]
    assert not faltam, (faltam, sorted(titulos))


def test_reserva_imprime_a_referencia_inteira_e_a_secao_existe(db, cenario):  # noqa: F811
    dados = _dados_das_duas_plataformas(db, cenario)
    texto = _texto(pdf._reserva(dados, "#1B2A4A"))
    detalhe = pdf._sem_tipografia(_detalhe_do_tempo_por_registro(dados))
    assert detalhe in texto, ("a referência saiu cortada na reserva", texto)
    (secao,) = _REFERENCIA.findall(detalhe)
    linhas = texto.splitlines()
    titulo = next((i for i, linha in enumerate(linhas) if linha.strip().upper() == secao.upper()), None)
    assert titulo is not None, ("a reserva não tem a seção referida", secao, texto[-900:])
    # E a explicação do tempo de cada leitura está logo depois desse título.
    nome = pdf._sem_tipografia(pdf._EXPLICACAO_NAO_RESPONDE["elefante.tempo_min_por_evento"]["nome"])
    assert any(nome in linha for linha in linhas[titulo + 1:]), texto[-900:]
