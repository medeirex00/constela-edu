"""Achados da revisão de autorização das rotas (11/10/2026), um teste por furo.

1. Link de redefinição pendente não sobrevive à promoção da conta-alvo.
2. A Secretaria não lê a configuração (link com token e QR) do painel público.
3. A conta da Secretaria não altera a escola de onde foi promovida.
4. Slide desligado não sai na resposta do painel público nem abre o perfil.

Dados sintéticos; nada sai para a internet.
"""
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Escola, Importacao, Rede, SnapshotMatific, Usuario
from app.services import scoring

SENHA = "s3nh4-sintetica"
NOVA = "farol-cedro-lua-38"


def _login(usuario: str, senha: str = SENHA):
    return TestClient(app).post("/api/v1/auth/login",
                                data={"username": usuario, "password": senha})


def _cliente(usuario: str, senha: str = SENHA) -> TestClient:
    r = _login(usuario, senha)
    assert r.status_code == 200, r.text
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _conta(db, escola_id, email, cargo, **extra) -> Usuario:
    u = Usuario(escola_id=escola_id, nome=email.split("@")[0], email=email,
                senha_hash=hash_senha(SENHA), cargo=cargo, **extra)
    db.add(u)
    db.commit()
    return u


def _rede_da_escola(db, escola: Escola) -> Rede:
    rede = Rede(nome="Rede Sintética", uf="SP", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.commit()
    return rede


def _consumir(token: str):
    return TestClient(app).post("/api/v1/auth/redefinir-senha",
                                json={"token": token, "nova_senha": NOVA})


# --- 1. Link pendente × promoção ----------------------------------------------

def test_link_do_coordenador_cai_quando_o_professor_vira_admin(db, escola_completa):
    escola = escola_completa["escola"]
    _conta(db, escola.id, "coord.sint@teste.local", "coordenador")
    prof = _conta(db, escola.id, "prof.sint@teste.local", "professor")
    coord = _cliente("coord.sint@teste.local")
    token = coord.post(f"/api/v1/escolas/{escola.id}/usuarios/{prof.id}/redefinir-senha"
                       ).json()["token"]

    admin = _cliente("admin@teste.local", "s3nh4")
    r = admin.patch(f"/api/v1/escolas/{escola.id}/usuarios/{prof.id}", json={"cargo": "admin"})
    assert r.status_code == 200, r.text

    # O coordenador não gera link para admin — o link antigo também não vale mais.
    assert TestClient(app).get(f"/api/v1/auth/redefinir-senha/{token}").json()["valido"] is False
    assert _consumir(token).status_code == 400
    assert _login("prof.sint@teste.local", NOVA).status_code == 401
    assert _login("prof.sint@teste.local").status_code == 200       # senha intacta


def test_link_do_admin_da_escola_cai_quando_a_conta_vira_secretaria(db, escola_completa):
    escola = escola_completa["escola"]
    rede = _rede_da_escola(db, escola)
    x = _conta(db, escola.id, "x.sint@teste.local", "coordenador")
    admin = _cliente("admin@teste.local", "s3nh4")
    token = admin.post(f"/api/v1/escolas/{escola.id}/usuarios/{x.id}/redefinir-senha"
                       ).json()["token"]

    x.rede_id = rede.id          # o admin global promove a conta a Secretaria
    db.commit()

    assert _consumir(token).status_code == 400
    assert _login("x.sint@teste.local", NOVA).status_code == 401


def test_link_continua_valendo_sem_mudanca_na_conta(db, escola_completa):
    escola = escola_completa["escola"]
    _conta(db, escola.id, "coord.sint@teste.local", "coordenador")
    prof = _conta(db, escola.id, "prof.sint@teste.local", "professor")
    coord = _cliente("coord.sint@teste.local")
    token = coord.post(f"/api/v1/escolas/{escola.id}/usuarios/{prof.id}/redefinir-senha"
                       ).json()["token"]
    assert _consumir(token).status_code == 200
    assert _login("prof.sint@teste.local", NOVA).status_code == 200


# --- 2 e 3. Secretaria: painel público e escola de origem ------------------------

def test_secretaria_nao_le_link_nem_qr_do_painel_publico(db, escola_completa):
    escola = escola_completa["escola"]
    rede = _rede_da_escola(db, escola)
    _conta(db, None, "sec.sint@rede.gov", "coordenador", rede_id=rede.id)
    admin = _cliente("admin@teste.local", "s3nh4")
    assert admin.put(f"/api/v1/escolas/{escola.id}/painel-publico",
                     json={"ativo": True, "slides": ["ranking"], "intervalo_s": 8,
                           "max_posicoes": 3}).status_code == 200

    sec = _cliente("sec.sint@rede.gov")
    assert sec.get(f"/api/v1/escolas/{escola.id}/painel-publico").status_code == 403
    assert sec.get(f"/api/v1/escolas/{escola.id}/painel-publico/qr").status_code == 403
    # A gestão da escola continua lendo a configuração.
    assert admin.get(f"/api/v1/escolas/{escola.id}/painel-publico").status_code == 200


def test_secretaria_promovida_nao_altera_a_escola_de_origem(db, escola_completa):
    escola = escola_completa["escola"]
    rede = _rede_da_escola(db, escola)
    # A promoção mantém o cargo e o escola_id de onde a conta veio.
    _conta(db, escola.id, "sec.admin@rede.gov", "admin", rede_id=rede.id)
    sec = _cliente("sec.admin@rede.gov")
    r = sec.patch(f"/api/v1/escolas/{escola.id}", json={"status": "inativa", "nome": "OUTRO"})
    assert r.status_code == 403
    db.refresh(escola)
    assert (escola.status, escola.nome) != ("inativa", "OUTRO")
    # O admin da própria escola continua podendo editar.
    admin = _cliente("admin@teste.local", "s3nh4")
    assert admin.patch(f"/api/v1/escolas/{escola.id}", json={"cidade": "Caraguatatuba"}
                       ).status_code == 200


# --- 4. Slides desligados -------------------------------------------------------

def _com_notas(db, escola_completa):
    escola = escola_completa["escola"]
    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    for i, aluno in enumerate(escola_completa["alunos"]):
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                               atividades=10 * (i + 1), estrelas=20, pontuacao_media=70))
    db.commit()
    scoring.recalcular_escola(db, escola.id)


def _painel(cliente, escola_id, slides):
    r = cliente.put(f"/api/v1/escolas/{escola_id}/painel-publico",
                    json={"ativo": True, "slides": slides, "intervalo_s": 8,
                          "max_posicoes": 3})
    assert r.status_code == 200, r.text
    return r.json()["url"].rsplit("/", 1)[-1]


def test_slide_desligado_nao_sai_no_painel_nem_abre_o_perfil(cliente, db, escola_completa):
    _com_notas(db, escola_completa)
    escola_id = escola_completa["escola"].id
    anonimo = TestClient(app)

    token = _painel(cliente, escola_id, ["ranking"])
    corpo = anonimo.get(f"/api/v1/publico/{token}/painel").json()
    assert len(corpo["ranking"]) == 3
    primeiro = corpo["ranking"][0]["aluno_id"]
    assert anonimo.get(f"/api/v1/publico/{token}/alunos/{primeiro}").status_code == 200
    assert corpo["mural"] == [] and corpo["destaques"] == [] and corpo["evolucao"] == []

    token = _painel(cliente, escola_id, ["mural"])      # a escola tira o ranking do telão
    corpo = anonimo.get(f"/api/v1/publico/{token}/painel").json()
    assert corpo["slides"] == ["mural"]
    assert corpo["ranking"] == [] and corpo["evolucao"] == [] and corpo["destaques"] == []
    assert anonimo.get(f"/api/v1/publico/{token}/alunos/{primeiro}").status_code == 404
