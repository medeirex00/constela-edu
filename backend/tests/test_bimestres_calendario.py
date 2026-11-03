"""Calendário dos bimestres fora de 2026: comportamento EXPLÍCITO e configurável.

Achado da auditoria de 20/10/2026: só 2026 tinha datas. Para 2027 o sistema
seguia com o mapa por mês, aproximado, rotulado como se fosse o oficial ("3º
bimestre") — datas silenciosamente erradas. Agora: recusa clara onde a pergunta
é "quais são as datas", aviso onde a tela precisa de um número, rótulo que diz
"aproximado" e uma forma de cadastrar o ano novo sem mexer no código.
"""
import json
import logging
from datetime import date

import pytest

from app.services import bimestres, periodos

# Datas de EXEMPLO para os testes (não são o calendário real de 2027).
_EXEMPLO_2027 = {"2027": [["2027-02-01", "2027-04-23"], ["2027-04-26", "2027-07-09"],
                          ["2027-07-26", "2027-10-01"], ["2027-10-04", "2027-12-17"]]}


@pytest.fixture(autouse=True)
def _sem_configuracao(monkeypatch):
    monkeypatch.delenv(bimestres.VARIAVEL_CALENDARIO, raising=False)
    bimestres._avisados.clear()
    yield
    bimestres._avisados.clear()


def test_ano_sem_calendario_recusa_com_mensagem_que_diz_como_configurar():
    with pytest.raises(bimestres.CalendarioNaoDefinido) as exc:
        bimestres.intervalo(1, 2027)
    assert "BIMESTRES_CALENDARIO" in str(exc.value)
    assert isinstance(exc.value, ValueError)             # quem tratava ValueError segue ok


def test_sugestao_sem_calendario_avisa_no_log_uma_vez(caplog):
    with caplog.at_level(logging.WARNING, logger="app.services.bimestres"):
        assert bimestres.bimestre_sugerido(date(2027, 3, 10)) == 1
        assert bimestres.bimestre_sugerido(date(2027, 8, 10)) == 3
    avisos = [r for r in caplog.records if "2027 não cadastrado" in r.getMessage()]
    assert len(avisos) == 1


def test_rotulo_do_periodo_aproximado_diz_que_e_aproximado():
    i, f, rotulo = periodos.resolver("bimestre_3", date(2027, 10, 1), 2027)
    assert rotulo == "3º bimestre (aproximado: sem calendário oficial de 2027)"
    _, _, este = periodos.resolver("bimestre", date(2027, 10, 1), 2027)
    assert "aproximado" in este and "2027" in este


def test_bimestre_anterior_em_janeiro_usa_o_calendario_oficial_do_ano_passado():
    """Jan/fev de 2027 (sem calendário): o anterior é o 4º de 2026 — que TEM
    calendário (05/10–31/12). Antes saía nov/dez com "sem calendário oficial de
    2026": 27 dias de outubro fora do prêmio e um cabeçalho falso."""
    for hoje in (date(2027, 1, 15), date(2027, 2, 27)):
        i, f, rotulo = periodos.resolver("bimestre_anterior", hoje, 2027)
        assert (i.date(), f.date()) == (date(2026, 10, 5), date(2026, 12, 31)), hoje
        assert rotulo == "4º bimestre (05/10 a 31/12)"
        assert "aproximado" not in rotulo


def test_bimestre_anterior_sem_nenhum_dos_dois_calendarios_continua_aproximado():
    """Jan/2028: nem 2028 nem 2027 têm calendário — aí, sim, a aproximação, e o
    rótulo diz de qual ano. Março/2027 continua no legado de 2027 (jan/fev)."""
    i, f, rotulo = periodos.resolver("bimestre_anterior", date(2028, 1, 15), 2028)
    assert (i.date(), f.date()) == (date(2027, 11, 1), date(2027, 12, 31))
    assert rotulo == "Bimestre anterior (aproximado: sem calendário oficial de 2027)"
    i, f, rotulo = periodos.resolver("bimestre_anterior", date(2027, 3, 10), 2027)
    assert (i.date(), f.date()) == (date(2027, 1, 1), date(2027, 2, 28))
    assert rotulo == "Bimestre anterior (aproximado: sem calendário oficial de 2027)"


def test_calendario_configurado_por_variavel_de_ambiente(monkeypatch):
    monkeypatch.setenv(bimestres.VARIAVEL_CALENDARIO, json.dumps(_EXEMPLO_2027))
    assert bimestres.ano_com_calendario(2027)
    assert bimestres.intervalo(3, 2027) == (date(2027, 7, 26), date(2027, 10, 1))
    assert bimestres.bimestre_da_data(date(2027, 10, 2)) is None      # recesso entre bimestres
    assert bimestres.bimestre_da_data(date(2027, 10, 4)) == 4
    i, f, rotulo = periodos.resolver("bimestre_3", date(2027, 10, 1), 2027)
    assert (i.date(), f.date()) == (date(2027, 7, 26), date(2027, 10, 1))
    assert rotulo == "3º bimestre (26/07 a 01/10)"                    # oficial, sem "aproximado"


def test_a_constante_de_2026_vence_a_configuracao(monkeypatch):
    monkeypatch.setenv(bimestres.VARIAVEL_CALENDARIO, json.dumps(
        {"2026": [["2026-01-05", "2026-03-01"], ["2026-03-02", "2026-06-01"],
                  ["2026-06-02", "2026-09-01"], ["2026-09-02", "2026-12-01"]]}))
    assert bimestres.intervalo(3, 2026) == (date(2026, 7, 24), date(2026, 10, 4))


@pytest.mark.parametrize("pares", [
    [["2027-02-01", "2027-04-23"]],                                         # só 1
    [["2027-02-01", "2027-04-23"], ["2027-04-20", "2027-07-09"],            # sobrepõe
     ["2027-07-26", "2027-10-01"], ["2027-10-04", "2027-12-17"]],
    [["2027-02-01", "2027-04-23"], ["2027-04-26", "2027-07-09"],            # outro ano
     ["2027-07-26", "2027-10-01"], ["2027-10-04", "2028-01-10"]],
    [["2027-02-01", "2027-01-23"], ["2027-04-26", "2027-07-09"],            # fim < início
     ["2027-07-26", "2027-10-01"], ["2027-10-04", "2027-12-17"]],
    [["2027-02-01", "data"], ["2027-04-26", "2027-07-09"],                  # ilegível
     ["2027-07-26", "2027-10-01"], ["2027-10-04", "2027-12-17"]],
])
def test_calendario_invalido_e_ignorado_inteiro_com_erro_no_log(monkeypatch, caplog, pares):
    monkeypatch.setenv(bimestres.VARIAVEL_CALENDARIO, json.dumps({"2027": pares}))
    with caplog.at_level(logging.ERROR, logger="app.services.bimestres"):
        assert not bimestres.ano_com_calendario(2027)
    assert any("inválido" in r.getMessage() for r in caplog.records)
    with pytest.raises(bimestres.CalendarioNaoDefinido):
        bimestres.intervalo(1, 2027)


def test_json_ilegivel_nao_derruba_nada(monkeypatch):
    monkeypatch.setenv(bimestres.VARIAVEL_CALENDARIO, "{isto não é json")
    assert not bimestres.ano_com_calendario(2027)
    assert bimestres.ano_com_calendario(2026)
