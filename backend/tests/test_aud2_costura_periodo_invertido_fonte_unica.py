"""PERIODOS-6 (fonte única da frase): o Relatório por Período diz a data invertida com a
MESMA frase do serviço de períodos (``periodos.mensagem_datas_invertidas``), não uma cópia.

As duas frases eram idênticas em dois lugares (``relatorios_periodo.resolver_janela`` e
``periodos``); ``test_aud2_ops_periodo_invertido.py`` comparava as respostas. Uma mudança
no texto de um lado divergiria do outro sem ninguém ver. Dados fictícios.
"""
from datetime import date

import pytest

from app.services import periodos
from app.services import relatorios_periodo as rp


def test_a_data_invertida_usa_a_frase_do_servico_de_periodos(monkeypatch):
    monkeypatch.setattr(periodos, "mensagem_datas_invertidas",
                        lambda inicio, fim: f"frase unica {inicio:%d/%m} > {fim:%d/%m}")
    with pytest.raises(rp.RelatorioInvalido) as erro:
        rp.resolver_janela("personalizado", 2026, inicio=date(2026, 9, 30),
                           fim=date(2026, 9, 1), hoje=date(2026, 11, 11))
    assert str(erro.value) == "frase unica 30/09 > 01/09"
