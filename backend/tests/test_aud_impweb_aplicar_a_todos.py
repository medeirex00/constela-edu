"""Auditoria (tela de Importações): "Aplicar a todos" e a turma do aluno novo.

IMPORTACAO-4/WEB-1: o seletor "Turma para os novos alunos" começava na 1ª turma da
escola. Aqui, a resposta real (texto colado sem turma, escola com duas turmas) que o
teste da tela usa; o Placar da escola com turma por aluno está em
test_aud_impweb_turma_da_previa.py. Dados fictícios.
"""
from tests.aud_impweb_exemplos import _analise, _exemplo, _turma, _turmas


# --- IMPORTACAO-4, WEB-1: texto colado sem turma -----------------------------------

TEXTO_SEM_TURMA = (
    "Nome do aluno\tAtividades finalizadas\tPontuação média\tEstrelas\n"
    "Ana Beatriz Souza\t42\t85,5\t120\n"
    "Crianca Ficticia Sem Ficha\t11\t71\t36\n")


def test_sem_turma_no_relatorio_a_previa_nao_diz_turma(cliente, db, escola_completa):
    """Texto colado sem turma, escola com duas turmas: a prévia não diz turma para a
    criança nova (os três campos nulos) — quem confirma escolhe."""
    eid = escola_completa["escola"].id
    _turma(db, eid, "4º Ano B", "4º Ano")
    analise = _analise(cliente, eid, TEXTO_SEM_TURMA)
    assert analise["turma_detectada"] == ""
    corr = {l["nome"]: l["correspondencia"] for l in analise["linhas"]}
    nova = corr["Crianca Ficticia Sem Ficha"]
    assert (nova["status"], nova["turma_id"], nova["turma_nome"], nova["turma_nova"]) == (
        "nao_encontrado", None, None, None)
    _exemplo("sem_turma_analise.json", analise)
    _exemplo("sem_turma_turmas.json", _turmas(cliente, eid))
