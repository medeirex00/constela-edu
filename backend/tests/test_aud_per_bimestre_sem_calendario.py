"""Ano SEM calendário oficial: "Este bimestre" e "Bimestre passado" usam a MESMA
janela aproximada do "Nº bimestre" (achado PERIODOS-3).

Sem calendário cadastrado (2027 enquanto ninguém configurar), ``periodos._bimestre``
usava dois mapas diferentes: "bimestre"/"bimestre_anterior" em blocos civis de dois
meses (``(mês-1)//2``) e "bimestre_N" pelo inverso do mapa por mês da sugestão
(jan–abr, mai–jul, ago–set, out–dez). Em 15/10/2027, "Este bimestre" cobria 01/09–31/10
(setembro é do 3º) enquanto o seletor e o certificado sugeriam o 4º (01/10–31/12): duas
opções da mesma lista medindo coisas diferentes. Agora "este" é o número sugerido e
"anterior" é o número anterior (o 4º do ano passado em jan–abr), na janela do numerado.
"""
from datetime import date

import pytest

from app.services import bimestres, periodos


@pytest.fixture(autouse=True)
def _sem_configuracao(monkeypatch):
    monkeypatch.delenv(bimestres.VARIAVEL_CALENDARIO, raising=False)


def _datas(preset, hoje, ano_letivo=None):
    i, f, rotulo = periodos.resolver(preset, hoje, ano_letivo or hoje.year)
    return i.date(), f.date(), rotulo


@pytest.mark.parametrize("hoje", [
    date(2027, 1, 10), date(2027, 3, 10), date(2027, 5, 20), date(2027, 7, 31),
    date(2027, 8, 20), date(2027, 9, 30), date(2027, 10, 15), date(2027, 12, 31),
])
def test_este_bimestre_e_o_numerado_sugerido(hoje):
    assert not bimestres.ano_com_calendario(2027)
    numero = bimestres.bimestre_sugerido(hoje)
    este = _datas("bimestre", hoje)
    numerado = _datas(f"bimestre_{numero}", hoje)
    assert este[:2] == numerado[:2], (hoje, este, numerado)
    assert este[2] == "Este bimestre (aproximado: sem calendário oficial de 2027)"


@pytest.mark.parametrize("hoje,anterior", [
    (date(2027, 5, 20), 1), (date(2027, 8, 20), 2), (date(2027, 10, 15), 3),
])
def test_bimestre_passado_e_o_numerado_anterior(hoje, anterior):
    ant = _datas("bimestre_anterior", hoje)
    num = _datas(f"bimestre_{anterior}", hoje)
    assert ant[:2] == num[:2], (hoje, ant, num)
    assert ant[2] == "Bimestre anterior (aproximado: sem calendário oficial de 2027)"


def test_bimestre_passado_no_1o_aproximado_e_o_4o_oficial_do_ano_passado():
    """Março/2027 é do 1º pelo mapa por mês: o anterior é o 4º de 2026, que TEM
    calendário — e não jan/fev de 2027 (o bloco civil de antes)."""
    assert _datas("bimestre_anterior", date(2027, 3, 10)) == (
        date(2026, 10, 5), date(2026, 12, 31), "4º bimestre (05/10 a 31/12)")


def test_sem_nenhum_dos_dois_calendarios_o_anterior_e_out_a_dez():
    """Jan/2028, sem 2028 nem 2027: o 4º aproximado de 2027 é out–dez (como o
    "4º bimestre" pedido em 2027), e não nov–dez."""
    i, f, rotulo = _datas("bimestre_anterior", date(2028, 1, 15))
    assert (i, f) == (date(2027, 10, 1), date(2027, 12, 31))
    assert (i, f) == _datas("bimestre_4", date(2027, 12, 1))[:2]
    assert rotulo == "Bimestre anterior (aproximado: sem calendário oficial de 2027)"
