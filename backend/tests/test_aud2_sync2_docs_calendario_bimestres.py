"""O roteiro de operação (docs/operacao/COLETA-PLATAFORMAS.md, §9 "Calendário dos
bimestres") descreve o comportamento ATUAL dos bimestres — é onde o dono vai cadastrar
o calendário de 2027.

Mudaram em c39d1e96 (recesso entre bimestres), 2371e790 (erro do calendário inválido
uma vez por valor da variável) e d6f0cd59 ("Nº bimestre" do ano letivo da escola na
virada), e o §9 não dizia nada disso. Cada frase é conferida contra o código.
"""
from datetime import date
from pathlib import Path

from app.services import periodos

DOC = Path(__file__).resolve().parents[2] / "docs" / "operacao" / "COLETA-PLATAFORMAS.md"


def _secao_9() -> str:
    texto = DOC.read_text(encoding="utf-8")
    inicio = texto.index("## 9. Calendário dos bimestres")
    return " ".join(texto[inicio:texto.index("## 10.", inicio)].split())


def test_bimestre_numerado_e_do_ano_letivo_da_escola_tambem_na_virada():
    secao = _secao_9()
    assert "ANO LETIVO" in secao and "\"Ano letivo\"" in secao, secao
    assert "4º bimestre de 2026 (05/10 a 31/12)" in secao, secao
    # O que o §9 afirma é o que o código faz: jan/2027 com a escola ainda em 2026.
    _i, _f, rotulo = periodos.resolver("bimestre_4", date(2027, 1, 15), 2026)
    assert rotulo == "4º bimestre de 2026 (05/10 a 31/12)"


def test_recesso_entre_bimestres_e_o_proximo():
    secao = _secao_9()
    assert "recesso entre dois bimestres" in secao, secao
    assert "\"Este bimestre\" é o próximo" in secao, secao
    assert "\"Bimestre anterior\" é o que acabou de terminar" in secao, secao
    # O código desta regra é conferido em test_aud_per_recesso_bimestre.py.


def test_calendario_invalido_avisa_uma_vez_por_valor():
    secao = _secao_9()
    assert "com erro no log uma vez por valor da variável" in secao, secao
