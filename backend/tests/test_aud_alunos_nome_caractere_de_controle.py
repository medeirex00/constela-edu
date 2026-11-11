"""Nome de aluno não entra com caractere de controle invisível pelo cadastro manual
nem por “Editar dados”.

Um nome colado de um PDF ou relatório pode trazer um caractere de controle (por
exemplo ``\\x02``) que não aparece na tela. A API gravava o nome assim, e um único
nome desses derruba a exportação Excel da escola inteira (o openpyxl recusa o
caractere). Agora ``AlunoCreate``/``AlunoUpdate`` trocam o caractere de controle
por espaço (sem espaço dobrado) antes de validar o tamanho — o nome que se vê é o
nome que fica. A correção da exportação em si é de outra frente.

Achado API_SEGURANCA-4 da auditoria (parte da entrada). Dados fictícios.
"""
import pytest

from app.models import Aluno

API = "/api/v1"


@pytest.mark.parametrize("colado, limpo", [
    ("Bento\x02 Fictelo Testelli", "Bento Fictelo Testelli"),
    ("Bento\x02Fictelo\x1fTestelli", "Bento Fictelo Testelli"),
    ("\x00Bento Fictelo\tTestelli\x7f", "Bento Fictelo Testelli"),
])
def test_cadastro_tira_o_caractere_de_controle_do_nome(cliente, db, escola_completa,
                                                       colado, limpo):
    escola_id = escola_completa["escola"].id
    r = cliente.post(f"{API}/escolas/{escola_id}/alunos",
                     json={"nome": colado, "turma_id": escola_completa["turma"].id})
    assert r.status_code == 201, r.text
    assert r.json()["nome"] == limpo
    db.expire_all()
    assert db.get(Aluno, r.json()["id"]).nome == limpo


def test_editar_dados_tira_o_caractere_de_controle_do_nome(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    r = cliente.patch(f"{API}/escolas/{escola_id}/alunos/{ana.id}",
                      json={"nome": "Ana\x02 Beatriz Souza"})
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "Ana Beatriz Souza"


def test_nome_que_so_tinha_controle_continua_curto_demais(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    r = cliente.post(f"{API}/escolas/{escola_id}/alunos",
                     json={"nome": "\x02A\x03", "turma_id": escola_completa["turma"].id})
    assert r.status_code == 422, r.text


def test_nome_sem_controle_nao_muda(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    r = cliente.post(f"{API}/escolas/{escola_id}/alunos",
                     json={"nome": "  Bento  Fictelo Testelli ",
                           "turma_id": escola_completa["turma"].id})
    assert r.status_code == 201, r.text
    assert r.json()["nome"] == "Bento  Fictelo Testelli"    # só o strip de sempre
