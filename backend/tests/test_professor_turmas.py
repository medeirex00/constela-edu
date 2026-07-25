"""Vínculo professor ↔ turmas pela tela de Usuários (botão "Vincular turmas").

Fecha o laço do RBAC por turma: o admin marca as turmas de um professor e o
professor passa a enxergar SÓ os alunos dessas turmas."""
from sqlalchemy import select

from app.models import Professor, Turma


SENHA = "Constela#Forte2026"


def _url(escola_id: int, sufixo: str = "") -> str:
    return f"/api/v1/escolas/{escola_id}/usuarios{sufixo}"


def _login(cliente, email: str, senha: str = SENHA) -> dict:
    r = cliente.post("/api/v1/auth/login",
                     data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _prof_user(cliente, escola_id: int, nome: str, email: str,
               cargo: str = "professor") -> dict:
    r = cliente.post(_url(escola_id), json={
        "nome": nome, "email": email, "senha": SENHA, "cargo": cargo})
    assert r.status_code == 201, r.text
    return r.json()


def test_vincula_turma_e_professor_passa_a_ver_so_ela(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma_a = escola_completa["turma"]
    turma_b = Turma(escola_id=escola.id, nome="5º Ano B", ano_escolar="5º Ano",
                    ano_letivo=turma_a.ano_letivo)
    db.add(turma_b)
    db.commit()

    prof = _prof_user(cliente, escola.id, "Paula Vilela", "paula@escola.com.br")

    # Sem vínculo ainda → nenhuma turma marcada.
    r = cliente.get(_url(escola.id, f"/{prof['id']}/turmas"))
    assert r.status_code == 200 and r.json()["turma_ids"] == []

    # Admin marca a turma A.
    r = cliente.put(_url(escola.id, f"/{prof['id']}/turmas"),
                    json={"turma_ids": [turma_a.id]})
    assert r.status_code == 200, r.text
    assert r.json()["turma_ids"] == [turma_a.id]

    # Criou o Professor emparelhado pelo e-mail e apontou a turma para ele.
    p = db.execute(select(Professor).where(
        Professor.email == "paula@escola.com.br")).scalar_one()
    db.refresh(turma_a)
    assert turma_a.professor_id == p.id

    # Fim do laço: o professor logado enxerga SÓ a turma A.
    chaves = _login(cliente, "paula@escola.com.br")
    turmas = cliente.get(f"/api/v1/escolas/{escola.id}/turmas", headers=chaves).json()
    assert [t["id"] for t in turmas] == [turma_a.id]


def test_remarcar_transfere_e_desmarcar_solta(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma_a = escola_completa["turma"]
    ana = _prof_user(cliente, escola.id, "Ana Lima", "ana@escola.com.br")
    bia = _prof_user(cliente, escola.id, "Bia Rocha", "bia@escola.com.br")

    cliente.put(_url(escola.id, f"/{ana['id']}/turmas"), json={"turma_ids": [turma_a.id]})
    # Bia marca a MESMA turma → transfere (turma tem um titular por vez).
    cliente.put(_url(escola.id, f"/{bia['id']}/turmas"), json={"turma_ids": [turma_a.id]})
    assert cliente.get(_url(escola.id, f"/{ana['id']}/turmas")).json()["turma_ids"] == []
    assert cliente.get(_url(escola.id, f"/{bia['id']}/turmas")).json()["turma_ids"] == [turma_a.id]

    # Esvaziar solta a turma (fica sem titular).
    r = cliente.put(_url(escola.id, f"/{bia['id']}/turmas"), json={"turma_ids": []})
    assert r.status_code == 200 and r.json()["turma_ids"] == []
    db.refresh(turma_a)
    assert turma_a.professor_id is None


def test_coordenador_nao_recebe_turmas(cliente, escola_completa):
    escola = escola_completa["escola"]
    turma_a = escola_completa["turma"]
    coord = _prof_user(cliente, escola.id, "Cida Souza", "cida@escola.com.br",
                       cargo="coordenador")
    r = cliente.put(_url(escola.id, f"/{coord['id']}/turmas"),
                    json={"turma_ids": [turma_a.id]})
    assert r.status_code == 400
    assert "professores" in r.json()["detail"].lower()


def test_turma_inexistente_e_recusada(cliente, escola_completa):
    escola = escola_completa["escola"]
    prof = _prof_user(cliente, escola.id, "Dora Neves", "dora@escola.com.br")
    r = cliente.put(_url(escola.id, f"/{prof['id']}/turmas"),
                    json={"turma_ids": [999999]})
    assert r.status_code == 400
    assert "escola" in r.json()["detail"].lower()


def test_professor_nao_designa_as_proprias_turmas(cliente, escola_completa):
    """Só admin: um professor não pode se auto-atribuir turmas."""
    escola = escola_completa["escola"]
    turma_a = escola_completa["turma"]
    prof = _prof_user(cliente, escola.id, "Eva Pinto", "eva@escola.com.br")
    chaves = _login(cliente, "eva@escola.com.br")
    r = cliente.put(_url(escola.id, f"/{prof['id']}/turmas"),
                    json={"turma_ids": [turma_a.id]}, headers=chaves)
    assert r.status_code == 403
