"""Campos de texto de entrada não passam do tamanho da coluna String(n) do modelo
(varredura que seguiu o achado contas-acesso 4 da 2ª revisão de integração).

Antes, os campos abaixo não tinham ``max_length`` (ou eram ``EmailStr``, que aceita
até 254 caracteres) e caíam numa coluna menor: o SQLite aceita qualquer tamanho e
o PostgreSQL recusa no commit (DataError), então o admin ou a coordenação da
escola recebiam 500. Agora o pedido é recusado com 422 antes do banco, e nada é
gravado. A paridade schema × coluna fica conferida aqui para não divergir de
novo; os testes de API rodam também num PG real (``..._pg.py``). Dados fictícios.
"""
import pytest
from sqlalchemy import func, select

from app.core.security import hash_senha
from app.models import Aluno, Escola, Professor, Usuario
from app.routers.admin import UsuarioCreate, UsuarioUpdate
from app.schemas.comum import (
    AlunoCreate,
    AlunoUpdate,
    EscolaCreate,
    EscolaUpdate,
    ProfessorCompletoIn,
    ProfessorCreate,
    ProfessorUpdate,
)

API = "/api/v1"

# (schema, campo, coluna do modelo que recebe o valor)
PARES = [
    (EscolaCreate, "cidade", Escola.cidade),
    (EscolaUpdate, "cidade", Escola.cidade),
    (EscolaUpdate, "logotipo_url", Escola.logotipo_url),
    (AlunoCreate, "nome", Aluno.nome),
    (AlunoCreate, "observacoes", Aluno.observacoes),
    (AlunoUpdate, "observacoes", Aluno.observacoes),
    (ProfessorCreate, "nome", Professor.nome),
    (ProfessorCreate, "email", Professor.email),
    (ProfessorCreate, "observacoes", Professor.observacoes),
    (ProfessorUpdate, "email", Professor.email),
    (ProfessorCompletoIn, "email", Professor.email),
    (ProfessorCompletoIn, "email", Usuario.email),
    (UsuarioCreate, "nome", Usuario.nome),
    (UsuarioCreate, "email", Usuario.email),
    (UsuarioUpdate, "nome", Usuario.nome),
]


def _max_length(schema, campo: str) -> int | None:
    limites = [getattr(m, "max_length", None) for m in schema.model_fields[campo].metadata]
    return next((x for x in limites if x is not None), None)


@pytest.mark.parametrize("schema,campo,coluna", PARES,
                         ids=[f"{s.__name__}.{c}" for s, c, _ in PARES])
def test_max_length_do_schema_cabe_na_coluna(schema, campo, coluna):
    limite = _max_length(schema, campo)
    assert limite is not None, f"{schema.__name__}.{campo} sem max_length"
    assert limite <= coluna.property.columns[0].type.length


def _email(total: int) -> str:
    """E-mail VÁLIDO (rótulos ≤ 63, local ≤ 64) com exatamente ``total`` caracteres."""
    resto = total - len("prof" + "x" * 36 + "@") - len(".com.br")
    partes = []
    while resto > 61:
        partes.append("d" * 60)
        resto -= 61
    partes.append("d" * resto)
    email = "prof" + "x" * 36 + "@" + ".".join(partes) + ".com.br"
    assert len(email) == total
    return email


def _contar(db, modelo, *filtros) -> int:
    db.expire_all()
    return db.execute(select(func.count()).select_from(modelo).where(*filtros)).scalar_one()


@pytest.fixture()
def apoio(db, escola_completa):
    eid = escola_completa["escola"].id
    prof = Professor(escola_id=eid, nome="Prof Ficticia")
    conta = Usuario(escola_id=eid, nome="Conta Ficticia",
                    email="conta.ficticia@escola-ficticia.com.br",
                    senha_hash=hash_senha("s3nh4"), cargo="professor")
    db.add_all([prof, conta])
    db.commit()
    return {"base": f"{API}/escolas/{eid}", "eid": eid,
            "turma_id": escola_completa["turma"].id, "prof_id": prof.id,
            "conta_id": conta.id}


def test_cadastro_de_aluno_observacoes(db, apoio, cliente):
    corpo = {"nome": "Crianca Ficticia Nova", "turma_id": apoio["turma_id"]}
    r = cliente.post(f"{apoio['base']}/alunos", json={**corpo, "observacoes": "x" * 1001})
    assert r.status_code == 422, r.text
    assert _contar(db, Aluno, Aluno.nome == corpo["nome"]) == 0
    r = cliente.post(f"{apoio['base']}/alunos", json={**corpo, "observacoes": "o" * 1000})
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("corpo", [
    {"nome": "x" * 201},
    {"nome": "Prof Nova Ficticia", "observacoes": "x" * 1001},
    {"nome": "Prof Nova Ficticia", "email": _email(201)},
])
def test_cadastro_de_professor_acima_da_coluna(db, apoio, cliente, corpo):
    antes = _contar(db, Professor)
    r = cliente.post(f"{apoio['base']}/professores", json=corpo)
    assert r.status_code == 422, r.text
    assert _contar(db, Professor) == antes


def test_cadastro_de_professor_no_limite(db, apoio, cliente):
    r = cliente.post(f"{apoio['base']}/professores", json={
        "nome": "N" * 200, "email": _email(200), "observacoes": "o" * 1000})
    assert r.status_code == 201, r.text


def test_edicao_do_email_do_professor(db, apoio, cliente):
    url = f"{apoio['base']}/professores/{apoio['prof_id']}"
    r = cliente.patch(url, json={"email": _email(201)})
    assert r.status_code == 422, r.text
    db.expire_all()
    assert db.get(Professor, apoio["prof_id"]).email is None
    r = cliente.patch(url, json={"email": _email(200)})
    assert r.status_code == 200, r.text


def test_cadastro_completo_de_professor_email(db, apoio, cliente):
    url = f"{apoio['base']}/professores/completo"
    r = cliente.post(url, json={"nome": "Prof Completa Ficticia", "email": _email(201)})
    assert r.status_code == 422, r.text
    assert _contar(db, Professor, Professor.nome == "Prof Completa Ficticia") == 0
    r = cliente.post(url, json={"nome": "Prof Completa Ficticia", "email": _email(200)})
    assert r.status_code == 201, r.text
    assert _contar(db, Usuario, Usuario.email == _email(200)) == 1


def test_cadastro_de_conta_email(db, apoio, cliente):
    corpo = {"nome": "Conta Nova Ficticia", "senha": "Ficticia-Forte-2026!"}
    r = cliente.post(f"{apoio['base']}/usuarios", json={**corpo, "email": _email(201)})
    assert r.status_code == 422, r.text
    assert _contar(db, Usuario, Usuario.nome == corpo["nome"]) == 0
    r = cliente.post(f"{apoio['base']}/usuarios", json={**corpo, "email": _email(200)})
    assert r.status_code == 201, r.text


def test_edicao_do_nome_da_conta(db, apoio, cliente):
    url = f"{apoio['base']}/usuarios/{apoio['conta_id']}"
    r = cliente.patch(url, json={"nome": "x" * 201})
    assert r.status_code == 422, r.text
    db.expire_all()
    assert db.get(Usuario, apoio["conta_id"]).nome == "Conta Ficticia"
    r = cliente.patch(url, json={"nome": "N" * 200})
    assert r.status_code == 200, r.text
