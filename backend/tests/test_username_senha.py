"""Nome de usuário no login (estilo @) e matriz de listagem de usuários.

* Login aceita e-mail OU username (com ou sem "@" na frente); username é
  único na rede toda e sempre minúsculo.
* A LISTAGEM respeita a matriz por cargo: admin vê todos; coordenador a si e
  aos professores; professor apenas a própria conta.

A redefinição de senha por token (que substituiu o antigo "ver senha") tem
seus próprios testes em test_reset_senha.py.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Usuario


def _cliente_como(email: str, senha: str) -> TestClient:
    cliente = TestClient(app)
    resposta = cliente.post("/api/v1/auth/login",
                            data={"username": email, "password": senha})
    assert resposta.status_code == 200, resposta.text
    cliente.headers["Authorization"] = f"Bearer {resposta.json()['access_token']}"
    return cliente


@pytest.fixture()
def contas(db, escola_completa):
    """Admin (da fixture) + coordenador + 2 professores, com usernames."""
    escola = escola_completa["escola"]
    pessoas = {}
    for nome, email, cargo, username in [
        ("Coord", "coord@teste.local", "coordenador", "coord.teste"),
        ("Prof Carla", "carla@teste.local", "professor", "carla"),
        ("Prof Bruno", "bruno@teste.local", "professor", None),
    ]:
        usuario = Usuario(escola_id=escola.id, nome=nome, email=email,
                          senha_hash=hash_senha("s3nh4!!!"), cargo=cargo,
                          username=username)
        db.add(usuario)
        pessoas[cargo + ("2" if cargo + "2" not in pessoas and nome == "Prof Bruno" else "")] = usuario
    db.commit()
    admin = db.execute(
        __import__("sqlalchemy").select(Usuario)
        .where(Usuario.email == "admin@teste.local")).scalar_one()
    return {"escola": escola, "admin": admin,
            "coordenador": pessoas["coordenador"],
            "carla": pessoas["professor"], "bruno": pessoas["professor2"]}


# --- Login por nome de usuário -------------------------------------------------

def test_login_por_username_com_e_sem_arroba(db, contas):
    cliente = TestClient(app)
    for entrada in ("carla", "@carla", "CARLA"):
        resposta = cliente.post("/api/v1/auth/login",
                                data={"username": entrada, "password": "s3nh4!!!"})
        assert resposta.status_code == 200, f"{entrada}: {resposta.text}"
        assert resposta.json()["usuario"]["username"] == "carla"
    # E-mail continua funcionando normalmente.
    ok = cliente.post("/api/v1/auth/login",
                      data={"username": "carla@teste.local", "password": "s3nh4!!!"})
    assert ok.status_code == 200


def test_username_repetido_e_invalido_sao_recusados(db, contas):
    escola_id = contas["escola"].id
    admin = _cliente_como("admin@teste.local", "s3nh4")
    base = f"/api/v1/escolas/{escola_id}/usuarios"

    repetido = admin.post(base, json={
        "nome": "Outro", "email": "outro@escola.com.br",
        "senha": "SenhaForte123", "cargo": "professor",
        "username": "@Carla"})                    # normaliza p/ "carla" → conflito
    assert repetido.status_code == 409

    invalido = admin.post(base, json={
        "nome": "Outro", "email": "outro@escola.com.br",
        "senha": "SenhaForte123", "cargo": "professor",
        "username": "no me inválido!"})
    assert invalido.status_code == 422

    # PATCH define e normaliza o username (e o login novo passa a valer).
    ok = admin.patch(f"{base}/{contas['bruno'].id}", json={"username": "@Bruno.S"})
    assert ok.status_code == 200
    assert ok.json()["username"] == "bruno.s"


# --- Limitador de tentativas ---------------------------------------------------

def test_limitador_soma_email_e_username_no_mesmo_contador(db, contas):
    """Tentar pelo e-mail e depois pelo @username não pode dobrar o orçamento
    de força bruta contra a mesma conta. Conta DEDICADA: o limitador vive na
    memória do processo e um bloqueio vazaria para os demais testes."""
    db.add(Usuario(escola_id=contas["escola"].id, nome="Alvo Limite",
                   email="limite@teste.local", username="limite",
                   senha_hash=hash_senha("s3nh4!!!"), cargo="professor"))
    db.commit()

    cliente = TestClient(app)
    bloqueado_em = None
    for tentativa in range(1, 30):
        resposta = cliente.post("/api/v1/auth/login",
                                data={"username": "limite@teste.local",
                                      "password": "senha-errada"})
        if resposta.status_code == 429:
            bloqueado_em = tentativa
            break
    assert bloqueado_em is not None, "o limitador nunca bloqueou"

    # Pelo USERNAME a mesma conta já deve estar bloqueada (mesmo contador).
    via_username = cliente.post("/api/v1/auth/login",
                                data={"username": "limite",
                                      "password": "senha-errada"})
    assert via_username.status_code == 429


# --- Listagem respeita a matriz por cargo -------------------------------------

def test_listagem_respeita_a_matriz(db, contas):
    escola_id = contas["escola"].id
    base = f"/api/v1/escolas/{escola_id}/usuarios"

    coord = _cliente_como("coord@teste.local", "s3nh4!!!")
    nomes = {u["nome"] for u in coord.get(base).json()}
    assert nomes == {"Coord", "Prof Carla", "Prof Bruno"}   # sem o admin

    prof = _cliente_como("carla@teste.local", "s3nh4!!!")
    so_ela = prof.get(base).json()
    assert [u["nome"] for u in so_ela] == ["Prof Carla"]
