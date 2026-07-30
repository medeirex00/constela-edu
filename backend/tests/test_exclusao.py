"""Exclusão de usuários e professores por coordenador (item do dono).

Coordenador (ou superior) exclui a própria equipe; NÃO pode excluir um
administrador; professor não exclui ninguém; a Secretaria (rede) é barrada em
qualquer escrita pelo `escola_autorizada` (método ≠ GET).
"""
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Professor, Turma, Usuario

API = "/api/v1"


def _login(email: str, senha: str) -> TestClient:
    c = TestClient(app)
    tok = c.post(f"{API}/auth/login", data={"username": email, "password": senha}).json()
    c.headers["Authorization"] = f"Bearer {tok['access_token']}"
    return c


def _coordenador(db, escola_id: int) -> None:
    db.add(Usuario(escola_id=escola_id, nome="Coord", email="coord@ed.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    db.commit()


def test_coordenador_exclui_professor_e_solta_turmas(db, escola_completa):
    escola = escola_completa["escola"]
    _coordenador(db, escola.id)
    prof = Professor(escola_id=escola.id, nome="Prof X")
    db.add(prof)
    db.flush()
    turma = Turma(escola_id=escola.id, nome="9ºZ", ano_escolar="9ºZ",
                  ano_letivo=2026, professor_id=prof.id)
    db.add(turma)
    db.commit()
    tid, pid = turma.id, prof.id

    c = _login("coord@ed.local", "s3nh4")
    r = c.delete(f"{API}/escolas/{escola.id}/professores/{pid}")
    assert r.status_code == 200, r.text

    # O professor sumiu; a TURMA continua existindo (só perdeu o titular).
    nomes = [p["nome"] for p in c.get(f"{API}/escolas/{escola.id}/professores").json()]
    assert "Prof X" not in nomes
    turmas = c.get(f"{API}/escolas/{escola.id}/turmas").json()
    assert any(t["id"] == tid for t in turmas)          # a sala NÃO foi apagada


def test_coordenador_exclui_usuario(db, escola_completa):
    escola = escola_completa["escola"]
    _coordenador(db, escola.id)
    alvo = Usuario(escola_id=escola.id, nome="Prof User", email="profuser@ed.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor")
    db.add(alvo)
    db.commit()

    c = _login("coord@ed.local", "s3nh4")
    r = c.delete(f"{API}/escolas/{escola.id}/usuarios/{alvo.id}")
    assert r.status_code == 200, r.text


def test_coordenador_nao_exclui_admin(db, escola_completa):
    escola = escola_completa["escola"]
    _coordenador(db, escola.id)
    admin2 = Usuario(escola_id=escola.id, nome="Admin2", email="admin2@ed.local",
                     senha_hash=hash_senha("s3nh4"), cargo="admin")
    db.add(admin2)
    db.commit()

    c = _login("coord@ed.local", "s3nh4")
    r = c.delete(f"{API}/escolas/{escola.id}/usuarios/{admin2.id}")
    assert r.status_code == 403


def test_professor_nao_pode_excluir(db, escola_completa):
    escola = escola_completa["escola"]
    prof_user = Usuario(escola_id=escola.id, nome="P", email="p@ed.local",
                        senha_hash=hash_senha("s3nh4"), cargo="professor")
    outro = Professor(escola_id=escola.id, nome="Outro")
    db.add_all([prof_user, outro])
    db.commit()

    c = _login("p@ed.local", "s3nh4")
    r = c.delete(f"{API}/escolas/{escola.id}/professores/{outro.id}")
    assert r.status_code == 403
