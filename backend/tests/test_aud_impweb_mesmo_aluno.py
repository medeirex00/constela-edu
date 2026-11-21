"""Auditoria (tela de Importações): o mesmo aluno escolhido em duas linhas.

IMPORTACAO-9: a tela deixava escolher a mesma ficha em duas linhas, sem aviso. O
/confirmar agora recusa (422); aqui, a prévia real e a recusa real que a tela mostra.
Dados fictícios.
"""
from tests.aud_impweb_exemplos import (
    _analise, _exemplo, _linha, _placar, _post_confirmar)


# --- IMPORTACAO-9: o mesmo aluno escolhido em duas linhas -------------------------

def test_mesmo_aluno_em_duas_linhas_e_recusado_com_a_mensagem(cliente, db, escola_completa):
    """A conta da Ana (vínculo exato) e outra conta com o nome parecido, a Ana escolhida
    nas duas linhas: 422, nada gravado. A tela mostra a mensagem do backend."""
    eid = escola_completa["escola"].id
    ana_id = escola_completa["alunos"][0].id
    analise = _analise(cliente, eid, _placar("3º Ano A", [
        {"nome": "Ana Beatriz Souza", "uuid": "uuid-fict-ana", "estrelas": 70, "atividades": 20},
        {"nome": "Ana Beatriz Sousa", "uuid": "uuid-fict-ana2", "estrelas": 3, "atividades": 1}]))
    primeira, segunda = analise["linhas"]
    assert primeira["correspondencia"]["aluno_id"] == ana_id
    assert ana_id in [a["aluno_id"] for a in segunda["correspondencia"]["alternativas"]]
    _exemplo("mesmo_aluno_analise.json", analise)
    r = _post_confirmar(cliente, eid, analise, [_linha(l, aluno_id=ana_id)
                                                for l in analise["linhas"]])
    assert r.status_code == 422, r.text
    assert "Ana Beatriz Souza" in r.json()["detail"]
    _exemplo("mesmo_aluno_confirmar_422.json", r.json())
