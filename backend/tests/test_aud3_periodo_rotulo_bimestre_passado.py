"""REG_NUMEROS-8: em janeiro, "Bimestre passado" é o 4º bimestre do ano PASSADO e diz o ano.

Desde a PERIODOS-2 o "Nº bimestre" de um ano que não é o do calendário de hoje diz o ano
("4º bimestre de 2026 (05/10 a 31/12)"), porque em janeiro "4º bimestre (05/10 a 31/12)"
pode ser lido como o do ano novo. "Bimestre passado" em janeiro devolve a MESMA janela e
saía sem o ano — o texto que vai para o cabeçalho das Premiações, o contexto do lote de
certificados e o PDF do Relatório por Período. Só datas.
"""
import json
from datetime import date

import pytest

from app.services import periodos

CAL_2027 = {"2027": [["2027-02-01", "2027-04-23"], ["2027-04-26", "2027-07-09"],
                     ["2027-07-26", "2027-10-01"], ["2027-10-04", "2027-12-17"]]}


@pytest.mark.parametrize("ano_letivo", [2026, 2027])
@pytest.mark.parametrize("hoje", [date(2027, 1, 20), date(2027, 1, 31)])
def test_bimestre_passado_em_janeiro_diz_o_ano(monkeypatch, hoje, ano_letivo):
    monkeypatch.delenv("BIMESTRES_CALENDARIO", raising=False)
    quarto = periodos.resolver("bimestre_4", hoje, 2026)
    passado = periodos.resolver("bimestre_anterior", hoje, ano_letivo)
    assert (passado[0], passado[1]) == (quarto[0], quarto[1])      # a MESMA janela
    assert passado[2] == quarto[2] == "4º bimestre de 2026 (05/10 a 31/12)", (
        f"mesma janela, rótulos diferentes: {quarto[2]!r} × {passado[2]!r}")


def test_bimestre_passado_com_o_calendario_do_ano_novo(monkeypatch):
    """Com o calendário de 2027 cadastrado, fevereiro antes do 1º bimestre começar ainda é
    do 1º (o sugerido): o passado é o 4º de 2026, e diz o ano."""
    monkeypatch.setenv("BIMESTRES_CALENDARIO", json.dumps(CAL_2027))
    _, _, rotulo = periodos.resolver("bimestre_anterior", date(2027, 1, 20), 2027)
    assert rotulo == "4º bimestre de 2026 (05/10 a 31/12)"


def test_dentro_do_ano_nenhum_dos_dois_diz_o_ano(monkeypatch):
    """Controle: o "Bimestre passado" do mesmo ano não ganha o ano no rótulo."""
    monkeypatch.delenv("BIMESTRES_CALENDARIO", raising=False)
    hoje = date(2026, 11, 11)
    assert periodos.resolver("bimestre_anterior", hoje, 2026)[2] == "3º bimestre (24/07 a 04/10)"
    assert periodos.resolver("bimestre_3", hoje, 2026)[2] == "3º bimestre (24/07 a 04/10)"
    assert periodos.resolver("bimestre", hoje, 2026)[2] == "4º bimestre (05/10 a 31/12)"
