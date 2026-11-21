"""Revisão (tela de Importações): o aviso do mesmo aluno em duas linhas diz, em cada
linha, o que ela oferece.

REV-IMPWEB-2 (sobre d606e754, IMPORTACAO-9): o aviso mandava "deixe a outra para a
Revisão" nas duas linhas — também onde "a outra" (vínculo exato, aluno novo) não tem
a opção "Deixar para a Revisão". Aqui, a prévia real em que NENHUMA das duas linhas a
oferece: a Ana (vínculo exato) e uma criança nova cujo nome lembra o dela (a Ana vem
como alternativa). Escolhida a Ana nas duas, o /confirmar recusa do mesmo jeito — a
saída é outro destino para uma delas. Dados fictícios.
"""
from tests.aud_impweb_exemplos import _analise, _exemplo, _fichas, _linha, _placar, _post_confirmar


def test_ana_e_crianca_nova_com_a_ana_nas_duas_linhas_e_recusado(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    ana_id = escola_completa["alunos"][0].id
    analise = _analise(cliente, eid, _placar("3º Ano A", [
        {"nome": "Ana Beatriz Souza", "uuid": "uuid-fict-ana", "estrelas": 70, "atividades": 20},
        {"nome": "Ana Beatriz Moura", "uuid": "uuid-fict-moura", "estrelas": 3, "atividades": 1}]))
    ana, nova = (l["correspondencia"] for l in analise["linhas"])
    assert (ana["status"], ana["aluno_id"]) == ("exato", ana_id)
    # A criança nova: nenhuma das duas linhas vai para a Revisão por motivo de identidade
    # ou de turma — nenhuma oferece "Deixar para a Revisão".
    assert (nova["status"], nova["aluno_id"]) == ("nao_encontrado", None)
    assert ana_id in [a["aluno_id"] for a in nova["alternativas"]]
    _exemplo("mesmo_aluno_novo_analise.json", analise)
    antes = _fichas(db, eid)
    r = _post_confirmar(cliente, eid, analise, [_linha(l, aluno_id=ana_id)
                                                for l in analise["linhas"]])
    assert r.status_code == 422, r.text
    assert "Ana Beatriz Souza" in r.json()["detail"]
    assert _fichas(db, eid) == antes
