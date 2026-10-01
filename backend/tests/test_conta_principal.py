"""Conta duplicada na MESMA plataforma: vence a de atividade mais recente.

E quando a atividade não desempata, a função **não escolhe**. Este arquivo
existe sobretudo para travar o que ela NÃO pode fazer: a escolha implícita que o
sistema tinha antes era ``linhas_aluno[-1]`` — a última linha do arquivo vencia
em silêncio. Qualquer desempate por UUID, ordem, volume ou nome é inventado.
"""
from datetime import datetime

import pytest

from app.services.conta_principal import (DETERMINADA, EMPATE, SEM_ATIVIDADE,
                                          Conta, decidir)


def test_a_mais_recente_vence():
    d = decidir([Conta("A", datetime(2026, 5, 18, 10, 0)),
                 Conta("B", datetime(2026, 9, 23, 8, 30))])
    assert d.classificacao == DETERMINADA
    assert d.principal == "B"
    assert d.aposentar == ("A",)
    assert not d.precisa_de_humano


def test_a_mais_recente_vence_independente_da_ordem_em_que_chegam():
    """Se a ordem da lista mudasse a resposta, o critério seria a ordem."""
    a = Conta("A", datetime(2026, 8, 15, 12, 0))
    b = Conta("B", datetime(2026, 9, 23, 8, 30))
    assert decidir([a, b]).principal == decidir([b, a]).principal == "B"


def test_empate_exato_vai_para_decisao_humana():
    instante = datetime(2026, 9, 23, 14, 5)
    d = decidir([Conta("A", instante), Conta("B", instante)])
    assert d.classificacao == EMPATE
    assert d.principal is None
    assert d.aposentar == ()
    assert d.precisa_de_humano
    assert "23/09/2026" in d.motivo


def test_nenhuma_com_atividade_vai_para_decisao_humana():
    d = decidir([Conta("A"), Conta("B")])
    assert d.classificacao == SEM_ATIVIDADE
    assert d.principal is None
    assert d.precisa_de_humano


def test_uma_com_atividade_vence_uma_sem():
    """"Nunca" é mais antigo que qualquer data — isso é a regra, não desempate."""
    d = decidir([Conta("A"), Conta("B", datetime(2026, 3, 2))])
    assert (d.classificacao, d.principal) == (DETERMINADA, "B")


def test_tres_contas_tambem():
    d = decidir([Conta("A", datetime(2026, 2, 1)),
                 Conta("B", datetime(2026, 9, 23)),
                 Conta("C", datetime(2026, 7, 7))])
    assert d.principal == "B"
    assert d.aposentar == ("A", "C")


# --------------------------------------------------------------------------
# O que a regra NÃO pode usar. Cada teste abaixo monta um caso em que um
# critério proibido daria uma resposta — e exige que ela não seja dada.
# --------------------------------------------------------------------------
def test_nao_desempata_por_uuid():
    d = decidir([Conta("zzzzzzzz"), Conta("aaaaaaaa")])
    assert d.principal is None, "ordenar por UUID daria uma resposta aqui"


def test_nao_desempata_por_ordem_de_chegada():
    d = decidir([Conta("primeira"), Conta("ultima")])
    assert d.principal is None, "'a última linha vence' daria 'ultima'"


def test_nao_desempata_por_status_nem_por_quem_ja_e_efetiva():
    d = decidir([Conta("A", status="efetiva"), Conta("B", status="aposentada")])
    assert d.classificacao == SEM_ATIVIDADE, (
        "o status atual é consequência de uma decisão anterior, não evidência "
        "de atividade — usá-lo seria confirmar a decisão com ela mesma")


def test_empate_de_atividade_nao_cai_no_desempate_por_status():
    instante = datetime(2026, 9, 23, 14, 5)
    d = decidir([Conta("A", instante, status="efetiva"),
                 Conta("B", instante, status="aposentada")])
    assert d.classificacao == EMPATE


def test_precisa_de_colisao():
    with pytest.raises(ValueError):
        decidir([Conta("A", datetime(2026, 9, 1))])


def test_o_motivo_sempre_diz_por_que():
    """O relatório da fila mostra este texto a um humano; ele não pode ser vazio
    nem genérico."""
    for caso in ([Conta("A", datetime(2026, 5, 1)), Conta("B", datetime(2026, 9, 1))],
                 [Conta("A"), Conta("B")],
                 [Conta("A", datetime(2026, 9, 1)), Conta("B", datetime(2026, 9, 1))]):
        d = decidir(caso)
        assert len(d.motivo) > 30, d.motivo
