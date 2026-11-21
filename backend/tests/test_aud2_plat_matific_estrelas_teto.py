"""Ajuste manual do Matific: no máximo 5 estrelas por atividade (G_AJUSTE-2).

A regra do teto (``matific_destaque.limitar_estrelas``, decisão do dono de
2026-09-15) diz que uma correção de relatório não cria estrela sem atividade: cada
atividade vale no máximo 5 estrelas. A edição manual aceitava qualquer número — 10
atividades com 5000 estrelas (um zero a mais digitado) punham a criança em 1º no
Ranking de Matemática e subiam a nota oficial, enquanto as Premiações limitavam.
Agora a barreira está na entrada: 422 com a explicação em português, nada gravado.

Dados fictícios.
"""
import pytest
from sqlalchemy import select

from app.models import SnapshotMatific

API = "/api/v1"


def _put(cliente, escola_id: int, aluno_id: int, atividades: int, estrelas: int):
    return cliente.put(f"{API}/escolas/{escola_id}/matific/{aluno_id}",
                       json={"atividades": atividades, "estrelas": estrelas,
                             "motivo": "correção do relatório"})


@pytest.mark.parametrize("atividades,estrelas", [(10, 5000), (10, 51), (0, 1)])
def test_estrelas_acima_de_5_por_atividade_sao_recusadas(cliente, db, escola_completa,
                                                         atividades, estrelas):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    resposta = _put(cliente, escola.id, ana.id, atividades, estrelas)
    assert resposta.status_code == 422, resposta.text
    mensagens = " ".join(e["msg"] for e in resposta.json()["detail"])
    assert "5 estrelas por atividade" in mensagens
    assert f"no máximo {5 * atividades}" in mensagens
    db.expire_all()
    assert db.execute(select(SnapshotMatific).where(
        SnapshotMatific.aluno_id == ana.id)).first() is None


@pytest.mark.parametrize("atividades,estrelas", [(10, 50), (10, 0), (0, 0), (7, 31)])
def test_estrelas_dentro_do_teto_sao_aceitas(cliente, escola_completa, atividades, estrelas):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    resposta = _put(cliente, escola.id, ana.id, atividades, estrelas)
    assert resposta.status_code == 200, resposta.text
    assert (resposta.json()["atividades"], resposta.json()["estrelas"]) == (atividades, estrelas)
