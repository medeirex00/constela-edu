"""'Minha conta' (autoatendimento): qualquer perfil consulta a PRÓPRIA conta via
/auth/me — inclusive a Secretaria (rede_id, sem escola). Ao mesmo tempo, a
Secretaria continua SEM gerenciar usuários de terceiros e SEM acesso a dados
individuais de alunos. Não cria permissão nova: só reusa /auth/me (já existente).
"""
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Rede, Usuario


def _login(email: str, senha: str = "s3nh4") -> TestClient:
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _cenario(db, escola_completa):
    escola = escola_completa["escola"]
    rede = Rede(nome="Rede MC", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(Usuario(escola_id=escola.id, nome="Coord MC", email="coord@mc.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    # Secretaria: rede vinculada, SEM escola própria (pior caso do "Minha conta").
    db.add(Usuario(escola_id=None, nome="Secretaria MC", email="sec@mc.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador", rede_id=rede.id))
    db.commit()
    return {"escola": escola.id, "rede": rede.id, "aluno": escola_completa["alunos"][0].id}


def test_secretaria_ve_a_propria_conta(db, escola_completa):
    _cenario(db, escola_completa)
    r = _login("sec@mc.local").get("/api/v1/auth/me")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["email"] == "sec@mc.local"
    assert corpo["nome"] == "Secretaria MC"
    assert corpo["cargo"] == "coordenador"
    assert corpo["rede_id"] is not None
    assert corpo["is_global"] is False


def test_secretaria_nao_gerencia_usuarios_de_terceiros(db, escola_completa):
    ids = _cenario(db, escola_completa)
    sec = _login("sec@mc.local")
    novo = {"nome": "Novo", "email": "novo@mc.local", "senha": "Senha@1234", "cargo": "professor"}
    # Criar usuário é gestão (admin-only) + escrita da Secretaria é barrada → 403.
    assert sec.post(f"/api/v1/escolas/{ids['escola']}/usuarios", json=novo).status_code == 403


def test_outros_perfis_tambem_veem_a_propria_conta(db, escola_completa):
    _cenario(db, escola_completa)
    for email in ("admin@teste.local", "coord@mc.local"):
        r = _login(email).get("/api/v1/auth/me")
        assert r.status_code == 200, email
        assert r.json()["email"] == email


def test_secretaria_continua_sem_dado_individual_de_aluno(db, escola_completa):
    ids = _cenario(db, escola_completa)
    sec = _login("sec@mc.local")
    # Histórico individual de aluno segue barrado (negar_dado_individual) → 403.
    r = sec.get(f"/api/v1/escolas/{ids['escola']}/alunos/{ids['aluno']}/leituras")
    assert r.status_code == 403
