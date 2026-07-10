"""Redefinição de senha por token — substitui o antigo "ver senha".

Garantias exercitadas:
  * admin gera um LINK (não uma senha): token único, com validade;
  * matriz: admin redefine de todos; coordenador de professores e a própria;
    professor só a própria;
  * token de USO ÚNICO e que EXPIRA; ao gerar um novo, o anterior é invalidado;
  * ao redefinir, a senha nova funciona e as sessões antigas caem;
  * a senha original NUNCA é recuperável (o endpoint antigo sumiu) nem fica em
    texto no banco.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core.security import hash_senha
from app.main import app
from app.models import TokenResetSenha, Usuario


def _cliente_como(email: str, senha: str) -> TestClient:
    cliente = TestClient(app)
    r = cliente.post("/api/v1/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cliente


def _login(email: str, senha: str):
    return TestClient(app).post("/api/v1/auth/login",
                                data={"username": email, "password": senha})


def _gerar_link(cliente, escola_id, alvo_id):
    return cliente.post(
        f"/api/v1/escolas/{escola_id}/usuarios/{alvo_id}/redefinir-senha")


@pytest.fixture()
def contas(db, escola_completa):
    """Admin (da fixture) + coordenador + 2 professores."""
    escola = escola_completa["escola"]
    criados = {}
    for nome, email, cargo, username in [
        ("Coord", "coord@teste.local", "coordenador", "coord.teste"),
        ("Prof Carla", "carla@teste.local", "professor", "carla"),
        ("Prof Bruno", "bruno@teste.local", "professor", "bruno"),
    ]:
        u = Usuario(escola_id=escola.id, nome=nome, email=email,
                    senha_hash=hash_senha("s3nh4!!!"), cargo=cargo, username=username)
        db.add(u)
        criados[username if cargo == "professor" else cargo] = u
    db.commit()
    admin = db.execute(select(Usuario)
                       .where(Usuario.email == "admin@teste.local")).scalar_one()
    return {"escola": escola, "admin": admin,
            "coordenador": criados["coordenador"],
            "carla": criados["carla"], "bruno": criados["bruno"]}


# --- Fluxo feliz ---------------------------------------------------------------

def test_admin_gera_link_e_usuario_define_nova_senha(db, contas):
    escola_id = contas["escola"].id
    admin = _cliente_como("admin@teste.local", "s3nh4")

    r = _gerar_link(admin, escola_id, contas["carla"].id)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert "senha" not in corpo                         # NUNCA devolve senha
    assert corpo["link"].endswith(corpo["token"])       # o link carrega o token
    token = corpo["token"]

    # A tela confere o link antes de mostrar o formulário.
    checagem = TestClient(app).get(f"/api/v1/auth/redefinir-senha/{token}")
    assert checagem.status_code == 200
    assert checagem.json() == {"valido": True, "nome": "Prof Carla"}

    # A pessoa escolhe a nova senha.
    troca = TestClient(app).post("/api/v1/auth/redefinir-senha",
                                 json={"token": token, "nova_senha": "NovaSenha2026"})
    assert troca.status_code == 200, troca.text

    # A nova senha funciona; a antiga não.
    assert _login("carla@teste.local", "NovaSenha2026").status_code == 200
    assert _login("carla@teste.local", "s3nh4!!!").status_code == 401

    # Uso único: o mesmo token não vale de novo.
    reuso = TestClient(app).post("/api/v1/auth/redefinir-senha",
                                 json={"token": token, "nova_senha": "OutraSenha99"})
    assert reuso.status_code == 400

    # No banco: token marcado como usado e NENHUMA senha em texto.
    db.expire_all()
    reg = db.execute(select(TokenResetSenha)
                     .where(TokenResetSenha.usuario_id == contas["carla"].id)
                     ).scalar_one()
    assert reg.usado_em is not None
    assert not hasattr(db.get(Usuario, contas["carla"].id), "senha_visivel")


def test_sessoes_antigas_caem_ao_redefinir(db, contas):
    escola_id = contas["escola"].id
    # Carla logada ANTES da redefinição.
    carla = _cliente_como("carla@teste.local", "s3nh4!!!")
    assert carla.get("/api/v1/auth/me").status_code == 200

    admin = _cliente_como("admin@teste.local", "s3nh4")
    token = _gerar_link(admin, escola_id, contas["carla"].id).json()["token"]
    TestClient(app).post("/api/v1/auth/redefinir-senha",
                         json={"token": token, "nova_senha": "NovaSenha2026"})

    # O JWT antigo da Carla deixou de valer (token_version subiu).
    assert carla.get("/api/v1/auth/me").status_code == 401


# --- Expiração e invalidação ---------------------------------------------------

def test_link_expirado_nao_funciona(db, contas):
    escola_id = contas["escola"].id
    admin = _cliente_como("admin@teste.local", "s3nh4")
    token = _gerar_link(admin, escola_id, contas["carla"].id).json()["token"]

    db.execute(update(TokenResetSenha)
               .where(TokenResetSenha.usuario_id == contas["carla"].id)
               .values(expira_em=datetime.now(timezone.utc) - timedelta(minutes=1)))
    db.commit()

    assert TestClient(app).get(
        f"/api/v1/auth/redefinir-senha/{token}").json() == {"valido": False}
    troca = TestClient(app).post("/api/v1/auth/redefinir-senha",
                                 json={"token": token, "nova_senha": "NovaSenha2026"})
    assert troca.status_code == 400


def test_novo_link_invalida_o_anterior(db, contas):
    escola_id = contas["escola"].id
    admin = _cliente_como("admin@teste.local", "s3nh4")
    token1 = _gerar_link(admin, escola_id, contas["carla"].id).json()["token"]
    token2 = _gerar_link(admin, escola_id, contas["carla"].id).json()["token"]
    assert token1 != token2

    # Só o link mais novo vale.
    assert TestClient(app).post(
        "/api/v1/auth/redefinir-senha",
        json={"token": token1, "nova_senha": "NovaSenha2026"}).status_code == 400
    assert TestClient(app).post(
        "/api/v1/auth/redefinir-senha",
        json={"token": token2, "nova_senha": "NovaSenha2026"}).status_code == 200


# --- Matriz de permissão -------------------------------------------------------

def test_matriz_de_quem_pode_redefinir(db, contas):
    escola_id = contas["escola"].id

    coord = _cliente_como("coord@teste.local", "s3nh4!!!")
    assert _gerar_link(coord, escola_id, contas["carla"].id).status_code == 200        # professor
    assert _gerar_link(coord, escola_id, contas["coordenador"].id).status_code == 200  # a própria
    assert _gerar_link(coord, escola_id, contas["admin"].id).status_code == 403        # admin, não

    prof = _cliente_como("carla@teste.local", "s3nh4!!!")
    assert _gerar_link(prof, escola_id, contas["bruno"].id).status_code == 403          # outro professor
    assert _gerar_link(prof, escola_id, contas["carla"].id).status_code == 200          # a própria


# --- Entradas inválidas --------------------------------------------------------

def test_token_invalido_e_senha_fraca(db, contas):
    escola_id = contas["escola"].id
    admin = _cliente_como("admin@teste.local", "s3nh4")
    token = _gerar_link(admin, escola_id, contas["carla"].id).json()["token"]

    # Token inexistente → 400.
    assert TestClient(app).post(
        "/api/v1/auth/redefinir-senha",
        json={"token": "token-que-nao-existe", "nova_senha": "NovaSenha2026"}
    ).status_code == 400
    # Link válido, mas senha fraca → 422 (validação de força).
    assert TestClient(app).post(
        "/api/v1/auth/redefinir-senha",
        json={"token": token, "nova_senha": "123"}).status_code == 422
    # GET de token inexistente responde inválido (sem vazar existência).
    assert TestClient(app).get(
        "/api/v1/auth/redefinir-senha/token-que-nao-existe").json() == {"valido": False}


def test_endpoint_antigo_de_ver_senha_nao_existe_mais(db, contas):
    """Não há mais como recuperar nem exibir a senha: a rota antiga some (404)."""
    escola_id = contas["escola"].id
    admin = _cliente_como("admin@teste.local", "s3nh4")
    assert admin.get(
        f"/api/v1/escolas/{escola_id}/usuarios/{contas['carla'].id}/senha"
    ).status_code == 404
    assert admin.post(
        f"/api/v1/escolas/{escola_id}/usuarios/{contas['carla'].id}/senha",
        json={}).status_code == 404
