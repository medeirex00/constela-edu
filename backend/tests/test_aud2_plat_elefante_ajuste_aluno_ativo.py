"""Ajuste manual do Elefante só em ficha ATIVA (G_AJUSTE-6, mesmo padrão das ações
em massa e do ajuste do Matific).

A rota relê a ficha depois da trava da escola: se a fusão a apagou, 404; se ela
não está ativa (transferida, arquivada, fora da Lista Piloto), 409 — as telas
listam só os ativos e todas as visões filtram por ``status == "ativo"``, então um
retrato gravado ali não apareceria em lugar nenhum.

Dados fictícios.
"""
import pytest
from sqlalchemy import select

from app.models import Aluno, SnapshotElefante

API = "/api/v1"
CORPO = {"tempo_leitura_min": 30, "questoes_tentativas": 4, "questoes_acertos": 2,
         "livros_por_nivel": {"D": 1}, "motivo": "correção do relatório"}
FAIXAS = {"faixas": {"pre_leitor": 2}, "motivo": "dados informados pela professora"}


@pytest.mark.parametrize("situacao", ["transferido", "arquivado", "fora_lista_piloto"])
def test_ajuste_do_elefante_em_ficha_que_nao_esta_ativa_responde_409(cliente, cliente_global, db,
                                                                     escola_completa, situacao):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    aluno = db.get(Aluno, ana.id)
    aluno.status = situacao
    db.commit()
    for perfil in (cliente, cliente_global):
        edicao = perfil.put(f"{API}/escolas/{escola.id}/elefante/{ana.id}", json=CORPO)
        assert edicao.status_code == 409, edicao.text
        assert "não está ativo" in edicao.json()["detail"]
        faixas = perfil.put(f"{API}/escolas/{escola.id}/elefante/{ana.id}/niveis", json=FAIXAS)
        assert faixas.status_code == 409, faixas.text
    db.expire_all()
    assert db.execute(select(SnapshotElefante).where(
        SnapshotElefante.aluno_id == ana.id)).first() is None


def test_ficha_ativa_continua_recebendo_o_ajuste(cliente, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    assert cliente.put(f"{API}/escolas/{escola.id}/elefante/{ana.id}",
                       json=CORPO).status_code == 200
    assert cliente.put(f"{API}/escolas/{escola.id}/elefante/{ana.id}/niveis",
                       json=FAIXAS).status_code == 200


def test_ficha_inexistente_responde_404(cliente, escola_completa):
    escola = escola_completa["escola"]
    assert cliente.put(f"{API}/escolas/{escola.id}/elefante/999999",
                       json=CORPO).status_code == 404
    assert cliente.put(f"{API}/escolas/{escola.id}/matific/999999",
                       json={"atividades": 1, "estrelas": 2,
                             "motivo": "correção do relatório"}).status_code == 404
