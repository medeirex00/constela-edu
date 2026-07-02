"""Infra compartilhada dos testes: banco em memória e API autenticada."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno,
    Configuracao,
    Escola,
    Matricula,
    NivelDificuldade,
    ReferenciaNormalizacao,
    Turma,
    Usuario,
)
from app.services import scoring


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # todas as sessões enxergam o mesmo banco em memória
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    sessao = TestSession()

    def _get_db():
        outra = TestSession()
        try:
            yield outra
        finally:
            outra.close()

    app.dependency_overrides[get_db] = _get_db
    yield sessao
    sessao.close()
    app.dependency_overrides.clear()


@pytest.fixture()
def escola_completa(db):
    """Escola com admin, turma, alunos e configurações padrão."""
    escola = Escola(nome="ESCOLA TESTE", ano_letivo_ativo=2026)
    db.add(escola)
    db.flush()

    admin = Usuario(escola_id=escola.id, nome="Admin", email="admin@teste.local",
                    senha_hash=hash_senha("s3nh4"), cargo="admin")
    db.add(admin)

    for namespace, valores in scoring.PESOS_PADRAO.items():
        db.add(Configuracao(escola_id=escola.id, namespace=namespace,
                            chave="valores", valor=valores))
    db.add(NivelDificuldade(escola_id=escola.id, nome="Pré-Leitor",
                            codigos=["AA", "BB"], pontos_padrao=1.0, ordem=0))
    db.add(NivelDificuldade(escola_id=escola.id, nome="Nível 2",
                            codigos=["D", "E"], pontos_padrao=4.0, ordem=1))
    db.add(ReferenciaNormalizacao(escola_id=escola.id, modo="auto"))

    turma = Turma(escola_id=escola.id, nome="3º Ano A", ano_escolar="3º Ano",
                  ano_letivo=2026)
    db.add(turma)
    db.flush()

    alunos = []
    for nome in ["Ana Beatriz Souza", "João Pedro Barbosa", "Sofia Almeida Duarte"]:
        aluno = Aluno(escola_id=escola.id, nome=nome)
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id,
                         turma_id=turma.id, ano_letivo=2026))
        alunos.append(aluno)
    db.commit()
    return {"escola": escola, "turma": turma, "alunos": alunos, "admin": admin}


@pytest.fixture()
def cliente(db, escola_completa):
    cliente = TestClient(app)
    resposta = cliente.post(
        "/api/v1/auth/login",
        data={"username": "admin@teste.local", "password": "s3nh4"},
    )
    assert resposta.status_code == 200, resposta.text
    token = resposta.json()["access_token"]
    cliente.headers["Authorization"] = f"Bearer {token}"
    return cliente
