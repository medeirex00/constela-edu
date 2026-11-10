"""A ficha de quem NÃO está no ranking não mostra posição — nem no perfil (gestão)
nem no painel da turma.

O recálculo não apaga a Nota de quem sai da população do ranking (arquivado,
transferido, excluído, sem matrícula do ano, turma de Fase): os leitores é que
filtram. O ranking filtra; o certificado de mérito tem guarda; o perfil visto pelo
PROFESSOR passa pela lista do ranking. Já o perfil visto pela GESTÃO devolvia
``Nota.posicao`` direto — e os blocos por dimensão, ``posicao_leitura`` /
``posicao_matematica`` —, e o painel da turma com "Mostrar arquivados" também. A
ficha arquivada dizia "1º no ranking" enquanto o 1º do ranking era outra criança.

Achados ALUNOS-6 e RANKINGS-5 da auditoria. Dados fictícios.
"""
import pytest

from app.models import Importacao, SnapshotElefante
from app.services import scoring
from tests.test_ranking_fases_cobertura import cenario  # noqa: F401 (fixture)

API = "/api/v1"


def _leitores(db, escola_completa):
    """Ana (40 livros) em 1º, João (20) em 2º, Sofia (5) em 3º."""
    escola = escola_completa["escola"]
    a, b, c = escola_completa["alunos"]
    for aluno, livros in ((a, 40), (b, 20), (c, 5)):
        imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
        db.add(imp)
        db.flush()
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                                importacao_id=imp.id, livros_unicos=livros,
                                tempo_leitura_min=livros * 20,
                                questoes_tentativas=10 * livros,
                                questoes_acertos=9 * livros,
                                livros_por_nivel={"D": livros}))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola, a.id


@pytest.mark.parametrize("acao", ["arquivar", "marcar_transferido", "excluir"])
def test_perfil_de_ficha_fora_do_ranking_nao_diz_posicao(cliente, db, escola_completa,
                                                         acao):
    escola, ana_id = _leitores(db, escola_completa)
    base = f"{API}/escolas/{escola.id}"
    perfil = cliente.get(f"{base}/alunos/{ana_id}/perfil").json()
    assert perfil["posicao"] == 1                                  # controle
    assert [d["posicao"] for d in perfil["dimensoes"] if d["aferido"]] == [1]

    r = cliente.post(f"{base}/alunos/acoes", json={"aluno_ids": [ana_id], "acao": acao})
    assert r.status_code == 200, r.text

    ranking = cliente.get(f"{base}/ranking").json()
    assert ranking[0]["posicao"] == 1 and ranking[0]["aluno_id"] != ana_id
    perfil = cliente.get(f"{base}/alunos/{ana_id}/perfil").json()
    assert perfil["posicao"] is None, (
        f"a ficha ({perfil['aluno']['status']}) diz {perfil['posicao']}º no ranking, "
        "que hoje é de outra criança")
    assert all(d["posicao"] is None for d in perfil["dimensoes"]), perfil["dimensoes"]


def test_perfil_de_quem_esta_no_ranking_continua_com_a_posicao(cliente, db,
                                                               escola_completa):
    escola, _ana_id = _leitores(db, escola_completa)
    base = f"{API}/escolas/{escola.id}"
    for item in cliente.get(f"{base}/ranking").json():
        perfil = cliente.get(f"{base}/alunos/{item['aluno_id']}/perfil").json()
        assert perfil["posicao"] == item["posicao"]
        leitura = next(d for d in perfil["dimensoes"] if d["dimensao"] == "leitura")
        assert leitura["posicao"] == item["posicao"]


def test_perfil_da_fase_nao_mostra_a_posicao_congelada(cliente, cenario):  # noqa: F811
    escola_id = cenario["escola"].id
    ranking = cliente.get(f"{API}/escolas/{escola_id}/ranking").json()
    for fase_id in sorted(cenario["fases"]):
        assert fase_id not in {i["aluno_id"] for i in ranking}
        perfil = cliente.get(f"{API}/escolas/{escola_id}/alunos/{fase_id}/perfil").json()
        assert perfil["posicao"] is None, (
            "o perfil diz que a criança da Fase ocupa uma posição que é de outra criança")
        assert all(d["posicao"] is None for d in perfil["dimensoes"]), perfil["dimensoes"]
        # A nota continua lá: só a POSIÇÃO é que não vale.
        assert perfil["nota_geral"] == 99.0


def test_painel_da_turma_com_arquivados_nao_mostra_posicao_da_arquivada(
        cliente, db, escola_completa):
    escola, ana_id = _leitores(db, escola_completa)
    turma = escola_completa["turma"]
    base = f"{API}/escolas/{escola.id}"
    r = cliente.post(f"{base}/alunos/acoes", json={"aluno_ids": [ana_id], "acao": "arquivar"})
    assert r.status_code == 200, r.text
    itens = cliente.get(f"{base}/turmas/{turma.id}/alunos",
                        params={"incluir_inativos": True}).json()
    pos = {i["id"]: (i["status"], i["posicao"]) for i in itens}
    assert pos[ana_id] == ("arquivado", None), \
        f"painel da turma mostra posição de ficha arquivada: {pos}"
    ativos = sorted(p for status, p in pos.values() if status == "ativo")
    assert ativos == [1, 2]


def test_painel_da_turma_de_fase_nao_mostra_posicao(cliente, cenario):  # noqa: F811
    escola_id = cenario["escola"].id
    itens = cliente.get(f"{API}/escolas/{escola_id}/turmas/{cenario['fase'].id}/alunos").json()
    assert itens and all(i["posicao"] is None for i in itens), \
        [(i["nome"], i["posicao"]) for i in itens]
    fund = cliente.get(f"{API}/escolas/{escola_id}/turmas/{cenario['fund'].id}/alunos").json()
    assert sorted(i["posicao"] for i in fund) == [1, 2, 3]
