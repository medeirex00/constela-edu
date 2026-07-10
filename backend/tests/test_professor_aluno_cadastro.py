"""Cadastro pela interface: professor completo (com conta de acesso e turma)
e aluno com ficha cadastral."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Aluno, Professor, Turma, Usuario


def test_professor_completo_cria_acesso_turma_e_login(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]

    r = cliente.post(f"/api/v1/escolas/{escola.id}/professores/completo", json={
        "nome": "Paula Andrade", "email": "Paula@Escola.com.br",
        "turma_id": turma.id, "criar_acesso": True,
    })
    assert r.status_code == 201, r.text
    corpo = r.json()
    assert corpo["professor"]["nome"] == "Paula Andrade"
    assert corpo["turma"] == turma.nome
    assert corpo["acesso"]["email"] == "paula@escola.com.br"   # normalizado
    senha = corpo["acesso"]["senha"]
    assert len(senha) >= 10

    db.expire_all()
    # Conta criada com cargo professor. A senha legível volta UMA vez na
    # resposta (acima) e NÃO é guardada em texto no banco — só o hash.
    conta = db.execute(select(Usuario).where(
        Usuario.email == "paula@escola.com.br")).scalar_one()
    assert conta.cargo == "professor" and conta.escola_id == escola.id
    assert not hasattr(conta, "senha_visivel")
    # Turma vinculada ao professor (é o elo do acesso restrito).
    professor = db.execute(select(Professor).where(
        Professor.escola_id == escola.id,
        Professor.nome == "Paula Andrade")).scalar_one()
    assert db.get(Turma, turma.id).professor_id == professor.id

    # A senha gerada FUNCIONA no login.
    c2 = TestClient(app)
    login = c2.post("/api/v1/auth/login",
                    data={"username": "paula@escola.com.br", "password": senha})
    assert login.status_code == 200, login.text
    assert login.json()["usuario"]["cargo"] == "professor"


def test_professor_completo_email_em_uso_e_sem_acesso(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    base = f"/api/v1/escolas/{escola.id}/professores/completo"
    # E-mail já usado por outra conta → 409, nada criado.
    db.add(Usuario(escola_id=escola.id, nome="Ocupado", email="ocupado@escola.com.br",
                   senha_hash=hash_senha("s3nh4abc"), cargo="coordenador"))
    db.commit()
    r = cliente.post(base, json={"nome": "Fulano Silva",
                                 "email": "Ocupado@escola.com.br"})
    assert r.status_code == 409
    assert db.execute(select(Professor).where(
        Professor.nome == "Fulano Silva")).scalar_one_or_none() is None

    # Sem conta de acesso: só o registro do professor.
    r2 = cliente.post(base, json={"nome": "Beltrano Souza",
                                  "email": "beltrano@escola.com.br",
                                  "criar_acesso": False})
    assert r2.status_code == 201
    assert r2.json()["acesso"] is None
    assert db.execute(select(Usuario).where(
        Usuario.email == "beltrano@escola.com.br")).scalar_one_or_none() is None


def test_professor_nao_cadastra_professor(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    db.add(Usuario(escola_id=escola.id, nome="Prof", email="prof2@t.local",
                   senha_hash=hash_senha("s3nh4abc"), cargo="professor"))
    db.commit()
    c2 = TestClient(app)
    token = c2.post("/api/v1/auth/login",
                    data={"username": "prof2@t.local", "password": "s3nh4abc"}).json()
    c2.headers["Authorization"] = f"Bearer {token['access_token']}"
    r = c2.post(f"/api/v1/escolas/{escola.id}/professores/completo",
                json={"nome": "Intruso Silva", "email": "x@y.com.br"})
    assert r.status_code == 403


def test_criar_aluno_com_ficha_sanitizada(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    r = cliente.post(f"/api/v1/escolas/{escola.id}/alunos", json={
        "nome": "Miguel Torres Lima", "turma_id": turma.id,
        "numero_chamada": 12, "data_nascimento": "2017-04-09",
        "ficha": {
            "ra": "111.222.333-4", "responsavel": "Carla Lima",
            "telefone": "12 99999-0000",
            "chave_desconhecida": "não entra",   # fora do vocabulário → cai
            "endereco": "  Rua das Flores, 10  ",
        },
    })
    assert r.status_code == 201, r.text
    db.expire_all()
    aluno = db.execute(select(Aluno).where(
        Aluno.nome == "Miguel Torres Lima")).scalar_one()
    assert aluno.ficha["ra"] == "111.222.333-4"
    assert aluno.ficha["endereco"] == "Rua das Flores, 10"   # espaços aparados
    assert "chave_desconhecida" not in aluno.ficha
    # A ficha aparece no perfil (gestor).
    perfil = cliente.get(
        f"/api/v1/escolas/{escola.id}/alunos/{aluno.id}/perfil").json()
    assert perfil["ficha"]["responsavel"] == "Carla Lima"
