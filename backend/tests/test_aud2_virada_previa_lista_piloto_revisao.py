"""PEND-56 (IMPORTACAO-10) — a prévia da Lista Piloto diz QUAIS linhas ficam para
revisão, não só quantas.

A prévia já contava "N linha(s) ficam para revisão", mas os nomes só apareciam nos
avisos depois de gravar. A simulação da prévia é a própria confirmação (só lendo) e
já gerava os mesmos avisos de revisão: agora eles vão para os avisos da prévia,
na redação de prévia ("ficará para revisão… nada será criado nem alterado") — a
confirmação continua dizendo "Nada foi criado nem alterado nesta linha".
Dados fictícios.
"""
from tests.test_aud2_virada_revisao_sem_prova import (
    BRUNO, _bruno_da_coleta_no_4a_de_2026, _enviar, _planilha)

from app.services import matriculas


def test_previa_lista_o_aviso_de_cada_linha_em_revisao(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    _bruno_da_coleta_no_4a_de_2026(db, eid)
    lista = _planilha(2026, ("5º Ano A", [BRUNO]))

    previa = _enviar(cliente, eid, lista, "analisar")

    assert previa["alunos_em_revisao"] == 1
    do_bruno = [a for a in previa["avisos"] if BRUNO[0] in a]
    assert len(do_bruno) == 1, previa["avisos"]
    assert "ficará para revisão" in do_bruno[0]
    assert "nada será criado nem alterado" in do_bruno[0]
    assert "foi criado" not in do_bruno[0]
    # a confirmação continua no passado, uma vez só
    resultado = _enviar(cliente, eid, lista)
    gravados = [a for a in resultado["avisos"] if BRUNO[0] in a]
    assert len(gravados) == 1 and "Nada foi criado nem alterado" in gravados[0]


def test_previa_sem_revisao_nao_ganha_aviso(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    previa = _enviar(cliente, eid, _planilha(2026, ("5º Ano A", [BRUNO])), "analisar")
    assert previa["alunos_em_revisao"] == 0
    assert not [a for a in previa["avisos"] if "revisão" in a], previa["avisos"]


def test_redacao_de_previa_nos_dois_motivos():
    for motivo in ("", "mudanca_de_sala_sem_prova"):
        gravado = matriculas.aviso_revisao("ANA FICTICIA", "1º Ano A", "ANA F", motivo)
        previa = matriculas.aviso_revisao("ANA FICTICIA", "1º Ano A", "ANA F", motivo,
                                          previa=True)
        assert "Nada foi criado nem alterado nesta linha" in gravado
        assert "Esta linha ficará para revisão: nada será criado nem alterado nela" in previa
        assert "foi criado" not in previa
