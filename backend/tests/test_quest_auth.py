"""Constela Quest — login infantil (sem senha), cartões e fronteira de sessões.

Fluxo de produto (09/07/2026): o CÓDIGO é a credencial (como no Elefante
Letrado), só letras e números. Cobre: cartões, login por código e QR,
limitador por (código, IP), aluno inativo, nome de exibição da cerimônia
e o isolamento entre tokens do Edu e do Quest.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Escola, Usuario
from app.quest.models import QuestCredencialAluno, QuestPerfil
from app.quest.routers import auth as quest_auth_router
from app.quest.services import credenciais as svc_credenciais


@pytest.fixture(autouse=True)
def limitadores_limpos():
    """Os limitadores são módulo-nível: zera entre testes."""
    quest_auth_router.limitador_codigo._eventos.clear()
    quest_auth_router.limitador_ip._eventos.clear()
    yield
    quest_auth_router.limitador_codigo._eventos.clear()
    quest_auth_router.limitador_ip._eventos.clear()


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


def _entrar(codigo):
    return TestClient(app).post("/api/v1/quest/auth/entrar",
                                json={"codigo": codigo})


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
        # Código só com letras e números — nada de hífen ou símbolo
        assert acesso["codigo_login"].isalnum()
        assert acesso["apelido"]

    # Segunda geração SEM regenerar: código e QR permanecem (reimpressão)
    aluno = escola_completa["alunos"][0]
    antes = _credencial_de(db, aluno.id)
    codigo_antes, qr_antes = antes.codigo_login, antes.qr_token
    assert _gerar_cartoes(cliente, escola.id, turma.id).status_code == 200
    depois = _credencial_de(db, aluno.id)
    assert (depois.codigo_login, depois.qr_token) == (codigo_antes, qr_antes)


def test_cartao_individual_nao_derruba_a_turma(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    _gerar_cartoes(cliente, escola.id, turma.id)
    perdido = escola_completa["alunos"][0]
    colega = escola_completa["alunos"][1]
    qr_colega_antes = _credencial_de(db, colega.id).qr_token
    qr_perdido_antes = _credencial_de(db, perdido.id).qr_token

    resposta = cliente.post(
        f"/api/v1/escolas/{escola.id}/quest/alunos/{perdido.id}/cartao"
        "?regenerar=true")
    assert resposta.status_code == 200, resposta.text
    assert resposta.content.startswith(b"%PDF")

    # Só o QR do dono do cartão perdido muda; o colega segue intocado
    assert _credencial_de(db, perdido.id).qr_token != qr_perdido_antes
    assert _credencial_de(db, colega.id).qr_token == qr_colega_antes


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
    assert _gerar_cartoes(cliente_b, outra.id, turma_a.id).status_code == 404


# ---------------------------------------------------------------------------
# Login da criança (código = credencial)
# ---------------------------------------------------------------------------

def test_fluxo_completo_por_codigo(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    aluno = escola_completa["alunos"][0]
    _gerar_cartoes(cliente, escola.id, turma.id)
    credencial = _credencial_de(db, aluno.id)

    anonimo = TestClient(app)

    # Etapa 1 — "É você?": tolerante a como a criança digita (minúsculas,
    # espaços, hífen inventado, acento)
    digitado = f" {credencial.codigo_login[:3].lower()}-{credencial.codigo_login[3:]} "
    quem = anonimo.post("/api/v1/quest/auth/quem", json={"codigo": digitado})
    assert quem.status_code == 200, quem.text
    assert quem.json()["nome"] == "Ana"

    # Etapa 2 — entrar (sem senha): primeira vez sinalizada
    resposta = _entrar(credencial.codigo_login)
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["primeira_vez"] is True
    assert corpo["perfil"]["nome"] == "Ana"
    assert corpo["perfil"]["nome_exibicao"] == ""

    # Segundo login: já não é primeira vez
    assert _entrar(credencial.codigo_login).json()["primeira_vez"] is False

    token = corpo["access_token"]
    perfil = anonimo.get("/api/v1/quest/perfil",
                         headers={"Authorization": f"Bearer {token}"})
    assert perfil.status_code == 200
    assert perfil.json()["codigo_amigo"].startswith("COSMO-")


def test_codigo_normaliza_acentos(db, escola_completa, cliente):
    escola = escola_completa["escola"]
    _gerar_cartoes(cliente, escola.id, escola_completa["turma"].id)
    credencial = _credencial_de(db, escola_completa["alunos"][0].id)
    # Criança que escreve "certo" com acento nunca é punida
    com_acento = credencial.codigo_login.replace("A", "Á").lower()
    assert svc_credenciais.normalizar_codigo(com_acento) == credencial.codigo_login


def test_login_por_qr(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    _gerar_cartoes(cliente, escola.id, escola_completa["turma"].id)
    credencial = _credencial_de(db, escola_completa["alunos"][1].id)

    resposta = TestClient(app).post("/api/v1/quest/auth/entrar-qr",
                                    json={"qr_token": credencial.qr_token})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["perfil"]["nome"] == "João"

    invalido = TestClient(app).post("/api/v1/quest/auth/entrar-qr",
                                    json={"qr_token": "x" * 24})
    assert invalido.status_code == 401


def test_limite_por_codigo_nao_pune_a_turma(cliente, db, escola_completa):
    """O erro repetido num código não bloqueia o código da colega (cenário
    NAT da escola: todos os tablets saem pelo mesmo IP)."""
    escola = escola_completa["escola"]
    _gerar_cartoes(cliente, escola.id, escola_completa["turma"].id)
    alvo = _credencial_de(db, escola_completa["alunos"][2].id)
    colega = _credencial_de(db, escola_completa["alunos"][1].id)

    inexistente = "XX" + alvo.codigo_login  # sempre falha, mesma chave
    for _ in range(8):
        assert _entrar(inexistente).status_code == 401
    # 9ª tentativa do MESMO código: bloqueada
    assert _entrar(inexistente).status_code == 429
    # A colega (outro código, mesmo IP) entra normalmente
    assert _entrar(colega.codigo_login).status_code == 200


def test_aluno_inativo_recebe_mensagem_propria(cliente, db, escola_completa):
    """Transferido/arquivado não pode achar que 'errou o código'."""
    escola = escola_completa["escola"]
    _gerar_cartoes(cliente, escola.id, escola_completa["turma"].id)
    aluno = escola_completa["alunos"][0]
    credencial = _credencial_de(db, aluno.id)
    aluno_db = db.get(type(aluno), aluno.id)
    aluno_db.status = "arquivado"
    db.commit()

    resposta = _entrar(credencial.codigo_login)
    assert resposta.status_code == 403
    assert "descansando" in resposta.json()["detail"]


def test_regenerar_troca_qr_e_derruba_sessoes(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    aluno = escola_completa["alunos"][0]
    _gerar_cartoes(cliente, escola.id, turma.id)
    credencial = _credencial_de(db, aluno.id)
    codigo = credencial.codigo_login
    qr_antigo = credencial.qr_token

    token_antigo = _entrar(codigo).json()["access_token"]

    _gerar_cartoes(cliente, escola.id, turma.id, regenerar=True)
    credencial = _credencial_de(db, aluno.id)

    # Código continua o mesmo (a criança decora); QR e sessões antigas caem
    assert credencial.codigo_login == codigo
    assert credencial.qr_token != qr_antigo
    resposta = TestClient(app).get(
        "/api/v1/quest/perfil",
        headers={"Authorization": f"Bearer {token_antigo}"})
    assert resposta.status_code == 401
    assert _entrar(codigo).status_code == 200


# ---------------------------------------------------------------------------
# Fronteira entre os mundos de token
# ---------------------------------------------------------------------------

def test_b3_quem_conta_revelacao_contra_o_teto_por_ip(cliente, db, escola_completa,
                                                      monkeypatch):
    """B3: revelar um nome no /quem conta contra o teto POR IP — colher nomes em
    massa do mesmo IP é bloqueado (429), mesmo acertando códigos válidos."""
    escola = escola_completa["escola"]
    _gerar_cartoes(cliente, escola.id, escola_completa["turma"].id)
    cred = _credencial_de(db, escola_completa["alunos"][0].id)

    # Teto baixo só para o teste (o real é 300/5min, inviável de exercitar aqui).
    monkeypatch.setattr(quest_auth_router.limitador_ip, "max_tentativas", 3)

    anon = TestClient(app)  # todas as requisições do TestClient saem do mesmo IP
    url = "/api/v1/quest/auth/quem"
    for _ in range(3):
        assert anon.post(url, json={"codigo": cred.codigo_login}).status_code == 200
    # 4ª revelação do MESMO IP: barrada — a colheita de nomes trava.
    assert anon.post(url, json={"codigo": cred.codigo_login}).status_code == 429


def test_token_de_aluno_nao_entra_no_edu_e_vice_versa(cliente, db,
                                                      escola_completa):
    escola = escola_completa["escola"]
    _gerar_cartoes(cliente, escola.id, escola_completa["turma"].id)
    credencial = _credencial_de(db, escola_completa["alunos"][0].id)
    token_aluno = _entrar(credencial.codigo_login).json()["access_token"]

    anonimo = TestClient(app)
    aluno_no_edu = anonimo.get("/api/v1/auth/me",
                               headers={"Authorization": f"Bearer {token_aluno}"})
    assert aluno_no_edu.status_code == 401

    admin_no_quest = cliente.get("/api/v1/quest/perfil")
    assert admin_no_quest.status_code == 401


# ---------------------------------------------------------------------------
# Perfil: nome escolhido, avatar e preferências
# ---------------------------------------------------------------------------

def _cliente_aluno(cliente, db, escola_completa, indice=0) -> TestClient:
    escola = escola_completa["escola"]
    _gerar_cartoes(cliente, escola.id, escola_completa["turma"].id)
    credencial = _credencial_de(db, escola_completa["alunos"][indice].id)
    token = _entrar(credencial.codigo_login).json()["access_token"]
    autenticado = TestClient(app)
    autenticado.headers["Authorization"] = f"Bearer {token}"
    return autenticado


def test_cerimonia_escolhe_nome(cliente, db, escola_completa):
    aluno = _cliente_aluno(cliente, db, escola_completa)

    # Nome válido: espaços extras somem, capitalização bonita
    ok = aluno.patch("/api/v1/quest/perfil/nome", json={"nome": "  duda  "})
    assert ok.status_code == 200, ok.text
    assert ok.json()["nome_exibicao"] == "Duda"
    assert ok.json()["nome"] == "Duda"          # falas passam a usar o escolhido

    # Números/símbolos: recusados com mensagem clara
    ruim = aluno.patch("/api/v1/quest/perfil/nome", json={"nome": "Duda123"})
    assert ruim.status_code == 422

    curto = aluno.patch("/api/v1/quest/perfil/nome", json={"nome": "D"})
    assert curto.status_code == 422


def test_trocar_cor_do_traje_e_preferencias(cliente, db, escola_completa):
    aluno = _cliente_aluno(cliente, db, escola_completa)

    cores = aluno.get("/api/v1/quest/perfil/cores").json()
    ok = aluno.patch("/api/v1/quest/perfil/avatar", json={"cor": cores[2]})
    assert ok.status_code == 200
    assert ok.json()["avatar"]["cor"] == cores[2]

    ruim = aluno.patch("/api/v1/quest/perfil/avatar", json={"cor": "#BADA55"})
    assert ruim.status_code == 422

    prefs = aluno.patch("/api/v1/quest/perfil/preferencias",
                        json={"musica": False, "narracao": True})
    assert prefs.status_code == 200
    assert prefs.json()["preferencias"]["musica"] is False


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
    assert all(c.isalnum() for c in codigos)
