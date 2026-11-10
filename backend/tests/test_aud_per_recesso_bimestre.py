"""Recesso ENTRE bimestres (auditoria de períodos, achado PERIODOS-1).

O calendário de 2026 não tem folga entre os bimestres, mas o de qualquer outro ano
pode ter (o exemplo do próprio módulo tem 24–25/04, 10–25/07 e 02–03/10). Nesses
dias ``bimestre_sugerido`` devolvia 4: em julho, "Este bimestre" virava o 4º (de
outubro a dezembro), "Bimestre passado" virava o 3º (que nem começou), o
certificado sem número saía "4" e a evolução punha a leitura no "4º bim".

A regra é a mesma do recesso de janeiro, já documentada: fora de um bimestre, o
PRÓXIMO a ser avaliado — que é também o que a tela abre marcada
(``bimestreDeHoje`` na web). Depois do fim do 4º não há próximo no ano: fica o 4º.
Datas fictícias, nenhum dado de aluno real.
"""
import json
from datetime import date, datetime

import pytest

from app.services import bimestres, periodos
from app.services import evolucao as svc_evolucao
from app.services import relatorios as svc_relatorios

_EXEMPLO_2027 = {"2027": [["2027-02-01", "2027-04-23"], ["2027-04-26", "2027-07-09"],
                          ["2027-07-26", "2027-10-01"], ["2027-10-04", "2027-12-17"]]}
RECESSO_JULHO = date(2027, 7, 15)


@pytest.fixture(autouse=True)
def calendario_2027(monkeypatch):
    monkeypatch.setenv(bimestres.VARIAVEL_CALENDARIO, json.dumps(_EXEMPLO_2027))
    assert bimestres.ano_com_calendario(2027)


@pytest.mark.parametrize("dia,esperado", [
    (date(2027, 1, 20), 1),     # antes do ano letivo (regra de janeiro, já existia)
    (date(2027, 4, 24), 2),     # entre o 1º (até 23/04) e o 2º (desde 26/04)
    (date(2027, 4, 25), 2),
    (date(2027, 7, 10), 3),     # entre o 2º (até 09/07) e o 3º (desde 26/07)
    (date(2027, 7, 15), 3),
    (date(2027, 7, 25), 3),
    (date(2027, 10, 2), 4),     # entre o 3º (até 01/10) e o 4º (desde 04/10)
    (date(2027, 12, 20), 4),    # depois do fim do 4º: não há próximo no ano
])
def test_recesso_entre_bimestres_sugere_o_proximo(dia, esperado):
    assert bimestres.bimestre_da_data(dia) is None
    assert bimestres.bimestre_sugerido(dia) == esperado


def test_este_bimestre_e_bimestre_passado_no_recesso_de_julho():
    ini, fim, rotulo = periodos.resolver("bimestre", RECESSO_JULHO, 2027)
    assert (ini.date(), fim.date()) == (date(2027, 7, 26), date(2027, 10, 1)), rotulo
    ini, fim, rotulo = periodos.resolver("bimestre_anterior", RECESSO_JULHO, 2027)
    assert (ini.date(), fim.date()) == (date(2027, 4, 26), date(2027, 7, 9)), rotulo
    assert rotulo == "2º bimestre (26/04 a 09/07)"


def test_bimestre_passado_no_recesso_de_abril_e_o_primeiro():
    ini, fim, _ = periodos.resolver("bimestre_anterior", date(2027, 4, 24), 2027)
    assert (ini.date(), fim.date()) == (date(2027, 2, 1), date(2027, 4, 23))


def test_certificado_sem_numero_no_recesso_nao_imprime_4(monkeypatch):
    monkeypatch.setattr(svc_relatorios, "agora_br", lambda: datetime(2027, 7, 15, 10, 0))
    html = svc_relatorios._certificado_plataforma_html(
        "ESCOLA TESTE", "Ana Beatriz Souza", "elefante")
    assert '<div class="campo bimestre">3</div>' in html
    assert '<div class="campo bimestre">4</div>' not in html


def test_evolucao_por_bimestre_poe_a_leitura_do_recesso_no_proximo():
    _, rotulo = svc_evolucao._bucket_leitura(datetime(2027, 7, 15, 10), "bimestre")
    assert rotulo == "3º bim 2027"
