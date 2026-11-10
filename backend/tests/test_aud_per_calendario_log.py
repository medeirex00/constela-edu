"""BIMESTRES_CALENDARIO com um ano inválido não inunda o log (achado PERIODOS-10).

``_calendario_configurado`` relia e revalidava o JSON da variável a cada consulta de
um ano fora de ``PERIODOS`` e gravava de novo o mesmo ERRO a cada vez. A evolução por
bimestre do aluno consulta uma vez POR LEITURA: 500 leituras, 500 erros iguais (e,
com o Sentry ligado, 500 eventos). Agora o texto da variável é lido uma vez por valor
distinto: o erro sai uma vez, e trocar a variável continua valendo sem reiniciar.
Datas fictícias.
"""
import json
import logging
from datetime import date, datetime, timedelta

import pytest

from app.services import bimestres
from app.services import evolucao as svc_evolucao

_BOM_2027 = [["2027-02-01", "2027-04-23"], ["2027-04-26", "2027-07-09"],
             ["2027-07-26", "2027-10-01"], ["2027-10-04", "2027-12-17"]]


@pytest.fixture(autouse=True)
def _cache_limpo():
    limpar = getattr(bimestres, "_ler_calendario", None)
    if limpar is not None:
        limpar.cache_clear()
    yield
    if limpar is not None:
        limpar.cache_clear()


def _erros_de_2028(caplog):
    return [r for r in caplog.records
            if r.levelno >= logging.ERROR and "2028" in r.getMessage()]


def test_ano_invalido_gera_um_erro_so_para_500_leituras(monkeypatch, caplog):
    cal = {"2027": _BOM_2027, "2028": [["2028-02-01", "2028-04-23"]]}   # 2028 incompleto
    monkeypatch.setenv(bimestres.VARIAVEL_CALENDARIO, json.dumps(cal))
    caplog.set_level(logging.ERROR, logger="app.services.bimestres")
    inicio = datetime(2027, 3, 1, 10)
    for i in range(500):                                   # 500 leituras de um aluno
        svc_evolucao._bucket_leitura(inicio + timedelta(hours=i), "bimestre")
    assert len(_erros_de_2028(caplog)) == 1
    # O ano válido continua valendo, e o inválido continua ignorado por inteiro.
    assert bimestres.intervalo(3, 2027) == (date(2027, 7, 26), date(2027, 10, 1))
    assert not bimestres.ano_com_calendario(2028)


def test_trocar_a_variavel_vale_sem_reiniciar_e_avisa_o_novo_erro(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="app.services.bimestres")
    monkeypatch.setenv(bimestres.VARIAVEL_CALENDARIO,
                       json.dumps({"2028": [["2028-02-01", "2028-04-23"]]}))
    assert not bimestres.ano_com_calendario(2028)
    assert not bimestres.ano_com_calendario(2028)
    assert len(_erros_de_2028(caplog)) == 1
    # Corrigida a variável, o ano passa a valer na hora.
    monkeypatch.setenv(bimestres.VARIAVEL_CALENDARIO, json.dumps({"2028": [
        ["2028-02-01", "2028-04-21"], ["2028-04-24", "2028-07-07"],
        ["2028-07-24", "2028-09-29"], ["2028-10-02", "2028-12-15"]]}))
    assert bimestres.intervalo(1, 2028) == (date(2028, 2, 1), date(2028, 4, 21))
    # Um NOVO valor inválido é outro erro (uma vez).
    monkeypatch.setenv(bimestres.VARIAVEL_CALENDARIO,
                       json.dumps({"2028": [["2028-02-01", "2028-01-01"]]}))
    assert not bimestres.ano_com_calendario(2028)
    assert not bimestres.ano_com_calendario(2028)
    assert len(_erros_de_2028(caplog)) == 2


def test_json_ilegivel_tambem_avisa_uma_vez(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="app.services.bimestres")
    monkeypatch.setenv(bimestres.VARIAVEL_CALENDARIO, "{2028: isto não é json")
    for _ in range(50):
        assert not bimestres.ano_com_calendario(2028)
    ilegivel = [r for r in caplog.records if "ilegível" in r.getMessage()]
    assert len(ilegivel) == 1


def test_quem_le_o_calendario_nao_estraga_o_cache(monkeypatch):
    monkeypatch.setenv(bimestres.VARIAVEL_CALENDARIO, json.dumps({"2027": _BOM_2027}))
    cal = bimestres.calendario(2027)
    with pytest.raises(TypeError):
        cal[1] = (date(2027, 1, 1), date(2027, 1, 2))     # leitura, não escrita
    assert bimestres.intervalo(1, 2027) == (date(2027, 2, 1), date(2027, 4, 23))
