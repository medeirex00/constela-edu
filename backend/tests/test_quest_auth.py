"""Constela Quest — login infantil, cartões de acesso e fronteira de sessões.

Cobre o caminho crítico da Fase Q0 (docs/quest/05): professor gera cartões,
criança entra com código + PIN de figuras (ou QR), e os dois mundos de
token (Edu × Quest) nunca se aceitam.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Escola, Turma, Usuario
from app.quest.models import QuestCredencialAluno, QuestPerfil
from app.quest.routers import auth as quest_auth_router
from app.quest.services import credenciais as svc_credenciais


@pytest.fixture(autouse=True)
def limitadores_limpos():
    """Os limitadores são módulo-nível: zera entre testes para um teste de
    força bruta não bloquear o vizinho."""
    quest_auth_router.limitador_pin._eventos.clear()
    quest_auth_router.limitador_quem._eventos.clear()
    yield
    quest_auth_router.limitador_pin._eventos.clear()
    quest_auth_router.limitador_quem._eventos.clear()


def _gerar_cartoes(cliente, escola_id, turma_id, regenerar=False):
    return cliente.post(
        f"/api/v1/escolas/{escola_id}/quest/turmas/{turma_id}/cartoes"
        f"?regenerar={'true' if regenerar else 'false'}")


def _credencial_de(db, aluno_id) -> QuestCredencialAluno:
    db.expire_all()
    return db.execute(
        select(QuestCredencialAluno)
        .where(QuestCredencialAluno.aluno_id == aluno_id)
    ).scalar_one()


def _entrar(codigo, pin):
    return TestClient(app).post("/api/v1/quest/auth/entrar",
                                json={"codigo": codigo, "pin": pin})


# ---------------------------------------------------------------------------
# Cartões de acesso
# ---------------------------------------------------------------------------

def test_gerar_cartoes_cria_credenciais_e_pdf(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]

    resposta = _gerar_cartoes(cliente, escola.id, turma.id)
    assert resposta.status_code == 200, resposta.text
    assert resposta.headers["content-type"] == "application/pdf"
    assert resposta.content.startswith(b"%PDF")

    acessos = cliente.get(
        f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/acessos").json()
    assert len(acessos) == 3
    for acesso in acessos:
        assert acesso["tem_credencial"] is True
        assert "-" in acesso["codigo_login"]
        assert acesso["apelido"]

    # Segunda geração SEM regenerar: código, PIN e QR permanecem (reimpressão)
    aluno = escola_completa["alunos"][0]
    antes = _credencial_de(db, aluno.id)
    codigo_antes, pin_antes, qr_antes = (antes.codigo_login,
                                         list(antes.pin_figuras), antes.qr_token)
    assert _gerar_cartoes(cliente, escola.id, turma.id).status_code == 200
    depois = _credencial_de(db, aluno.id)
    assert (depois.codigo_login, list(depois.pin_figuras), depois.qr_token) == \
        (codigo_antes, pin_antes, qr_antes)


def test_cartoes_exigem_papel_da_escola(db, escola_completa):
    """Usuário de OUTRA escola não gera cartões (isolamento multi-escolas)."""
    outra = Escola(nome="OUTRA ESCOLA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    db.add(Usuario(escola_id=outra.id, nome="Admin B", email="b@teste.local",
                   senha_hash=hash_senha("s3nh4b"), cargo="admin"))
    db.commit()

    cliente_b = TestClient(app)
    login = cliente_b.post("/api/v1/auth/login",
                           data={"username": "b@teste.local", "password": "s3nh4b"})
    cliente_b.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    escola_a = escola_completa["escola"]
    turma_a = escola_completa["turma"]
    assert _gerar_cartoes(cliente_b, escola_a.id, turma_a.id).status_code == 403
    # Turma alheia referenciada pela própria escola: 404 (não vaza existência)
    assert _gerar_cartoes(cliente_b, outra.id, turma_a.id).status_code == 404


# ---------------------------------------------------------------------------
# Login da criança
# ---------------------------------------------------------------------------

def test_fluxo_completo_codigo_pin(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    aluno = escola_completa["alunos"][0]
    _gerar_cartoes(cliente, escola.id, turma.id)
    credencial = _credencial_de(db, aluno.id)

    anonimo = TestClient(app)

    # Catálogo de figuras é público (a tela de PIN precisa dele)
    figuras = anonimo.get("/api/v1/quest/auth/figuras").json()
    assert len(figuras) == 12 and {"slug", "nome", "emoji"} <= set(figuras[0])

    # Etapa 1 — "É você?": tolerante a como a criança digita o código
    digitado = credencial.codigo_login.replace("-", " ").lower()
    quem = anonimo.post("/api/v1/quest/auth/quem", json={"codigo": digitado})
    assert quem.status_code == 200, quem.text
    assert quem.json()["primeiro_nome"] == "Ana"
    assert quem.json()["apelido"]

    # Etapa 2 — PIN errado: mensagem gentil, sem sessão
    errado = list(reversed(credencial.pin_figuras))
    resposta = _entrar(credencial.codigo_login, errado)
    assert resposta.status_code == 401

    # PIN certo: sessão de aluno + perfil
    resposta = _entrar(credencial.codigo_login, credencial.pin_figuras)
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["perfil"]["primeiro_nome"] == "Ana"
    assert corpo["perfil"]["nivel"] == 1
    assert corpo["perfil"]["avatar"]["cor"]

    token = corpo["access_token"]
    perfil = anonimo.get("/api/v1/quest/perfil",
                         headers={"Authorization": f"Bearer {token}"})
    assert perfil.status_code == 200
    assert perfil.json()["codigo_amigo"].startswith("COSMO-")


def test_login_por_qr(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    _gerar_cartoes(cliente, escola.id, escola_completa["turma"].id)
    credencial = _credencial_de(db, escola_completa["alunos"][1].id)

    resposta = TestClient(app).post("/api/v1/quest/auth/entrar-qr",
                                    json={"qr_token": credencial.qr_token})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["perfil"]["primeiro_nome"] == "João"

    invalido = TestClient(app).post("/api/v1/quest/auth/entrar-qr",
                                    json={"qr_token": "x" * 24})
    assert invalido.status_code == 401


def test_pin_tem_limite_de_tentativas(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    _gerar_cartoes(cliente, escola.id, escola_completa["turma"].id)
    credencial = _credencial_de(db, escola_completa["alunos"][2].id)

    errado = list(reversed(credencial.pin_figuras))
    for _ in range(6):
        assert _entrar(credencial.codigo_login, errado).status_code == 401
    # 7ª tentativa: bloqueado — inclusive com o PIN CERTO
    assert _entrar(credencial.codigo_login, credencial.pin_figuras).status_code == 429


def test_regenerar_troca_pin_e_derruba_sessoes(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    aluno = escola_completa["alunos"][0]
    _gerar_cartoes(cliente, escola.id, turma.id)
    credencial = _credencial_de(db, aluno.id)
    codigo = credencial.codigo_login
    qr_antigo = credencial.qr_token

    token_antigo = _entrar(codigo, credencial.pin_figuras).json()["access_token"]

    _gerar_cartoes(cliente, escola.id, turma.id, regenerar=True)
    credencial = _credencial_de(db, aluno.id)

    # Código continua o mesmo (a criança decora); QR e sessões antigas caem
    assert credencial.codigo_login == codigo
    assert credencial.qr_token != qr_antigo
    resposta = TestClient(app).get(
        "/api/v1/quest/perfil",
        headers={"Authorization": f"Bearer {token_antigo}"})
    assert resposta.status_code == 401

    novo = _entrar(codigo, credencial.pin_figuras)
    assert novo.status_code == 200


# ---------------------------------------------------------------------------
# Fronteira entre os mundos de token
# ---------------------------------------------------------------------------

def test_token_de_aluno_nao_entra_no_edu_e_vice_versa(cliente, db,
                                                      escola_completa):
    escola = escola_completa["escola"]
    _gerar_cartoes(cliente, escola.id, escola_completa["turma"].id)
    credencial = _credencial_de(db, escola_completa["alunos"][0].id)
    token_aluno = _entrar(credencial.codigo_login,
                          credencial.pin_figuras).json()["access_token"]

    anonimo = TestClient(app)
    aluno_no_edu = anonimo.get("/api/v1/auth/me",
                               headers={"Authorization": f"Bearer {token_aluno}"})
    assert aluno_no_edu.status_code == 401

    # Token de admin do Edu não vale como sessão de aluno
    admin_no_quest = cliente.get("/api/v1/quest/perfil")
    assert admin_no_quest.status_code == 401


# ---------------------------------------------------------------------------
# Perfil: escritas permitidas ao aluno
# ---------------------------------------------------------------------------

def test_trocar_cor_do_traje_e_preferencias(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    _gerar_cartoes(cliente, escola.id, escola_completa["turma"].id)
    credencial = _credencial_de(db, escola_completa["alunos"][0].id)
    token = _entrar(credencial.codigo_login,
                    credencial.pin_figuras).json()["access_token"]
    autenticado = TestClient(app)
    autenticado.headers["Authorization"] = f"Bearer {token}"

    cores = autenticado.get("/api/v1/quest/perfil/cores").json()
    assert len(cores) >= 4

    ok = autenticado.patch("/api/v1/quest/perfil/avatar", json={"cor": cores[2]})
    assert ok.status_code == 200
    assert ok.json()["avatar"]["cor"] == cores[2]

    # Cor fora do catálogo: recusada (nenhum hex livre entra no banco)
    ruim = autenticado.patch("/api/v1/quest/perfil/avatar",
                             json={"cor": "#BADA55"})
    assert ruim.status_code == 422

    prefs = autenticado.patch("/api/v1/quest/perfil/preferencias",
                              json={"musica": False, "narracao": True})
    assert prefs.status_code == 200
    assert prefs.json()["preferencias"]["musica"] is False
    # Chave desconhecida é ignorada em silêncio (whitelist)
    extra = autenticado.patch("/api/v1/quest/perfil/preferencias",
                              json={"som": True})
    assert "hack" not in extra.json()["preferencias"]


def test_apelidos_e_codigos_unicos(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    _gerar_cartoes(cliente, escola.id, escola_completa["turma"].id)
    db.expire_all()
    perfis = db.execute(select(QuestPerfil)).scalars().all()
    assert len(perfis) == 3
    assert len({p.apelido for p in perfis}) == 3
    assert len({p.codigo_amigo for p in perfis}) == 3
    codigos = db.execute(select(QuestCredencialAluno.codigo_login)).scalars().all()
    assert len(set(codigos)) == 3
    # PINs têm 4 figuras distintas do catálogo
    for credencial in db.execute(select(QuestCredencialAluno)).scalars():
        assert len(credencial.pin_figuras) == 4
        assert len(set(credencial.pin_figuras)) == 4
        slugs = {f["slug"] for f in svc_credenciais.FIGURAS_PIN}
        assert set(credencial.pin_figuras) <= slugs
