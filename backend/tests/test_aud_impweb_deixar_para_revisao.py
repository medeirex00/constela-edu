"""Auditoria (tela de Importações): "Deixar para a Revisão" nunca cria ficha.

IMPORTACAO-6/WEB-3: com duas contas de mesmo nome, ignorar uma mandava a outra
sozinha, com o corpo de um "Criar" — e o backend criava a ficha. Aqui, a resposta
real e o corpo novo da tela (``deixar_para_revisao``). Dados fictícios.
"""
from tests.aud_impweb_exemplos import (
    _analise, _confirmar, _exemplo, _fichas, _linha, _motivos, _placar, _relatorio)


# --- IMPORTACAO-6, WEB-3: ignorar uma das duas contas -----------------------------

PLACAR_DUAS_CONTAS = _placar("3º Ano A", [
    {"nome": "Ana Beatriz Souza", "uuid": "uuid-ficticio-ana", "estrelas": 5, "atividades": 1},
    {"nome": "Crianca Ficticia Repetida", "uuid": "uuid-ficticio-1", "estrelas": 10,
     "atividades": 3},
    {"nome": "Crianca Ficticia Repetida", "uuid": "uuid-ficticio-2", "estrelas": 20,
     "atividades": 4}])


def test_duas_contas_ignorar_uma_a_outra_fica_na_revisao(cliente, db, escola_completa):
    """O corpo da tela com a conta 2 ignorada e a conta 1 em "Deixar para a Revisão"
    (``deixar_para_revisao``): o backend não cria a ficha — antes, sem a rival no mesmo
    envio, a conta 1 criava a ficha embora a tela dissesse "vai para Revisões"."""
    eid = escola_completa["escola"].id
    analise = _analise(cliente, eid, PLACAR_DUAS_CONTAS)
    ana, conta1, conta2 = analise["linhas"]
    assert {conta1["correspondencia"]["motivo"], conta2["correspondencia"]["motivo"]} == {
        "contas_repetidas_no_relatorio"}
    _exemplo("duas_contas_analise.json", analise)
    antes = _fichas(db, eid)
    resultado = _confirmar(cliente, eid, analise, [
        _linha(ana, aluno_id=ana["correspondencia"]["aluno_id"]),
        _linha(conta1, deixar_para_revisao=True, criar_em_turma_nome=_relatorio(analise, conta1)),
    ])
    assert (resultado["qtd_alunos"], resultado["qtd_revisoes"]) == (1, 1), resultado
    assert _fichas(db, eid) == antes
    assert _motivos(db, eid) == ["deixada_para_revisao"]
    _exemplo("duas_contas_confirmar_uma.json", resultado)
