"""PEND-57 (REV-IMPWEB-2, resto no backend) — a recusa do mesmo aluno em duas
linhas diz uma saída que a tela oferece.

A mensagem mandava "deixe a outra para a Revisão de identidade". No caso real da
Ana (vínculo exato) + uma criança nova com a Ana como alternativa, NENHUMA das duas
linhas oferece "Deixar para a Revisão": a saída que sempre existe é escolher outro
destino para a outra linha. Dados fictícios.
"""
from tests.aud_impweb_exemplos import _analise, _linha, _placar, _post_confirmar

FIM = "Ligue o aluno a uma linha só e escolha outro destino para a outra. Nada foi gravado."


def test_recusa_sem_revisao_disponivel_nao_manda_para_a_revisao(cliente, db,
                                                                escola_completa):
    eid = escola_completa["escola"].id
    ana_id = escola_completa["alunos"][0].id
    analise = _analise(cliente, eid, _placar("3º Ano A", [
        {"nome": "Ana Beatriz Souza", "uuid": "uuid-fict-ana", "estrelas": 70, "atividades": 20},
        {"nome": "Ana Beatriz Moura", "uuid": "uuid-fict-moura", "estrelas": 3, "atividades": 1}]))

    r = _post_confirmar(cliente, eid, analise, [_linha(l, aluno_id=ana_id)
                                                for l in analise["linhas"]])

    assert r.status_code == 422, r.text
    detalhe = r.json()["detail"]
    assert detalhe.endswith(FIM), detalhe
    assert "Revisão" not in detalhe
