"""Nome de turma e de escola (e a série da turma) não entram com caractere de
controle invisível.

O DEFEITO (REV-ALUNOS-4, sobre o API_SEGURANCA-4). O conserto do nome do aluno
(``_nome_sem_controle`` em ``AlunoCreate``/``AlunoUpdate``) deixou de fora as
outras portas do mesmo ``schemas/comum.py``: ``TurmaCreate``/``TurmaUpdate`` e
``EscolaCreate``/``EscolaUpdate`` aceitavam ``\\x02`` no nome. Um nome de turma
assim gravava e derrubava a exportação Excel da escola inteira (500). A série
(``ano_escolar``) vai para a mesma coluna da planilha e tinha a mesma porta.

O CONSERTO. O mesmo validador nos nomes de turma e de escola e na série: cada
trecho com caractere de controle vira um espaço (sem espaço dobrado) antes de
conferir o tamanho. A defesa da exportação em si é de outra frente.

Dados fictícios.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Escola, Turma

API = "/api/v1"


def _sem_excecao(cliente) -> TestClient:
    http = TestClient(app, raise_server_exceptions=False)
    http.headers.update(cliente.headers)
    return http


def test_editar_turma_tira_o_caractere_de_controle_e_a_exportacao_continua(
        cliente, db, escola_completa):
    """A sonda do revisor."""
    eid, tid = escola_completa["escola"].id, escola_completa["turma"].id
    r = cliente.put(f"{API}/escolas/{eid}/turmas/{tid}",
                    json={"nome": "3º Ano\x02 A", "ano_escolar": "3º\x02 Ano"})
    print("PUT TURMA:", r.status_code, repr(r.json().get("nome")))
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "3º Ano A"
    assert r.json()["ano_escolar"] == "3º Ano"
    db.expire_all()
    turma = db.get(Turma, tid)
    assert (turma.nome, turma.ano_escolar) == ("3º Ano A", "3º Ano")
    x = _sem_excecao(cliente).get(f"{API}/escolas/{eid}/relatorios/alunos",
                                  params={"formato": "xlsx"})
    print("EXPORT XLSX:", x.status_code, x.text[:120] if x.status_code != 200 else "ok")
    assert x.status_code == 200


def test_criar_turma_tira_o_caractere_de_controle(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    r = cliente.post(f"{API}/escolas/{eid}/turmas", json={
        "nome": "\x024º Ano\x1fB", "ano_escolar": "4º Ano\x7f",
        "ano_letivo": 2026})
    assert r.status_code == 201, r.text
    assert (r.json()["nome"], r.json()["ano_escolar"]) == ("4º Ano B", "4º Ano")


@pytest.mark.parametrize("campo", ["nome", "ano_escolar"])
def test_turma_so_com_caractere_de_controle_e_recusada(cliente, escola_completa, campo):
    eid, tid = escola_completa["escola"].id, escola_completa["turma"].id
    r = cliente.put(f"{API}/escolas/{eid}/turmas/{tid}", json={campo: "\x02\x03"})
    assert r.status_code == 422, r.text


def test_criar_e_editar_escola_tira_o_caractere_de_controle(cliente_global, db,
                                                            escola_completa):
    r = cliente_global.post(f"{API}/escolas", json={"nome": "EMEF\x02 Ficticia Testelli"})
    assert r.status_code == 201, r.text
    assert r.json()["nome"] == "EMEF Ficticia Testelli"
    eid = escola_completa["escola"].id
    r = cliente_global.patch(f"{API}/escolas/{eid}", json={"nome": "ESCOLA\x02 TESTE\x1f"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Escola, eid).nome == "ESCOLA TESTE"


def test_nome_sem_caractere_de_controle_passa_intacto(cliente, escola_completa):
    eid, tid = escola_completa["escola"].id, escola_completa["turma"].id
    r = cliente.put(f"{API}/escolas/{eid}/turmas/{tid}", json={"nome": "3º  Ano  A"})
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "3º  Ano  A"
