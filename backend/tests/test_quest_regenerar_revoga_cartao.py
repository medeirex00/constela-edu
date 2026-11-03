"""Quest — "regenerar" revoga o cartão inteiro: código, QR e sessões.

O cartão impresso traz o QR E o código ("Meu codigo magico"), e quem abre uma
sessão pelo QR lê o código no GET /quest/perfil. ``regenerar`` trocava só o QR
e subia o ``token_version``: o código impresso no mesmo cartão (ou lido por quem
só teve o QR) abria uma sessão nova de 30 dias logo depois da "revogação". A
folha do professor, os docstrings e a bible mandavam usar ``regenerar`` para
cartão em mãos erradas. Agora ``regenerar`` troca código e QR (texto e hash
juntos, coerente com a 0037) e derruba toda sessão do aluno; o individual não
toca nos colegas; a reimpressão sem parâmetro continua com o mesmo cartão.

Regressão do achado 1 do módulo quest na revisão e97 (provas test_prova_4 e
test_prova_5, invertidas aqui). Dados fictícios (fixture escola_completa).
"""
import io

import pdfplumber
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import or_, select

from app.main import app
from app.models import LogAuditoria
from app.quest.models import QuestCredencialAluno
from app.quest.services import credenciais as svc

QUEM = "/api/v1/quest/auth/quem"
ENTRAR = "/api/v1/quest/auth/entrar"
ENTRAR_QR = "/api/v1/quest/auth/entrar-qr"
PERFIL = "/api/v1/quest/perfil"


def _cred(db, aluno_id) -> QuestCredencialAluno:
    db.expire_all()
    return db.execute(select(QuestCredencialAluno)
                      .where(QuestCredencialAluno.aluno_id == aluno_id)).scalar_one()


def _base(escola_completa) -> str:
    return f"/api/v1/escolas/{escola_completa['escola'].id}/quest"


def _cartoes_turma(cliente, escola_completa, consulta: str = ""):
    r = cliente.post(f"{_base(escola_completa)}/turmas/"
                     f"{escola_completa['turma'].id}/cartoes{consulta}")
    assert r.status_code == 200, r.text
    return r


def _cartao_individual(cliente, escola_completa, aluno_id, consulta: str = ""):
    r = cliente.post(f"{_base(escola_completa)}/alunos/{aluno_id}/cartao{consulta}")
    assert r.status_code == 200, r.text
    return r


def _codigo(rota, codigo):
    return TestClient(app).post(rota, json={"codigo": codigo})


def _qr(token):
    return TestClient(app).post(ENTRAR_QR, json={"qr_token": token})


def _perfil(token):
    return TestClient(app).get(PERFIL, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def cartao(cliente, db, escola_completa):
    """Cartões da turma gerados; devolve o cartão impresso do 1º aluno."""
    _cartoes_turma(cliente, escola_completa)
    cred = _cred(db, escola_completa["alunos"][0].id)
    return {"aluno_id": cred.aluno_id, "codigo": cred.codigo_login,
            "qr": cred.qr_token, "hash": cred.codigo_login_hash}


def _o_cartao_antigo_nao_entra(cartao, token_antigo):
    assert _qr(cartao["qr"]).status_code == 401
    assert _codigo(ENTRAR, cartao["codigo"]).status_code == 401
    assert _codigo(QUEM, cartao["codigo"]).status_code == 401   # nem revela o nome
    assert _perfil(token_antigo).status_code == 401


def _o_cartao_novo_entra(db, aluno_id, cartao):
    novo = _cred(db, aluno_id)
    assert novo.codigo_login != cartao["codigo"] and novo.qr_token != cartao["qr"]
    r = _codigo(ENTRAR, novo.codigo_login)
    assert r.status_code == 200, r.text
    assert _perfil(r.json()["access_token"]).status_code == 200
    assert _qr(novo.qr_token).status_code == 200
    return novo


# --- 1. Cartão em mãos erradas: o código impresso deixa de entrar --------------

def test_regenerar_a_turma_revoga_o_codigo_impresso(cliente, db, escola_completa, cartao):
    intruso = _codigo(ENTRAR, cartao["codigo"])
    assert intruso.status_code == 200
    token_intruso = intruso.json()["access_token"]

    _cartoes_turma(cliente, escola_completa, "?regenerar=true")

    _o_cartao_antigo_nao_entra(cartao, token_intruso)
    # Sem sessão, o intruso também não troca mais o nome da criança
    assert TestClient(app).patch(f"{PERFIL}/nome", json={"nome": "Intruso"}, headers={
        "Authorization": f"Bearer {token_intruso}"}).status_code == 401
    _o_cartao_novo_entra(db, cartao["aluno_id"], cartao)


def test_regenerar_individual_revoga_so_o_cartao_dele(cliente, db, escola_completa,
                                                      cartao):
    colega_id = escola_completa["alunos"][1].id
    colega = _cred(db, colega_id)
    colega_codigo, colega_qr = colega.codigo_login, colega.qr_token
    token_colega = _codigo(ENTRAR, colega_codigo).json()["access_token"]
    token_intruso = _codigo(ENTRAR, cartao["codigo"]).json()["access_token"]

    _cartao_individual(cliente, escola_completa, cartao["aluno_id"], "?regenerar=true")

    _o_cartao_antigo_nao_entra(cartao, token_intruso)
    _o_cartao_novo_entra(db, cartao["aluno_id"], cartao)
    # O colega segue com o mesmo cartão e a mesma sessão
    depois = _cred(db, colega_id)
    assert (depois.codigo_login, depois.qr_token) == (colega_codigo, colega_qr)
    assert _perfil(token_colega).status_code == 200
    assert _codigo(ENTRAR, colega_codigo).status_code == 200
    assert _qr(colega_qr).status_code == 200


def test_qr_vazado_revela_o_codigo_e_regenerar_revoga_os_dois(cliente, db,
                                                              escola_completa, cartao):
    """O caso literal da folha antiga: só o QR vazou. A sessão aberta pelo QR lê
    o código no perfil; depois de regenerar, nem o QR nem o código lido entram."""
    r = _qr(cartao["qr"])
    assert r.status_code == 200, r.text
    token_qr = r.json()["access_token"]
    codigo_lido = _perfil(token_qr).json()["codigo_login"]
    assert codigo_lido == cartao["codigo"]

    _cartao_individual(cliente, escola_completa, cartao["aluno_id"], "?regenerar=true")

    _o_cartao_antigo_nao_entra(cartao, token_qr)
    assert _codigo(ENTRAR, codigo_lido).status_code == 401


def test_rotacionar_codigo_continua_com_o_mesmo_efeito(cliente, db, escola_completa,
                                                       cartao):
    token = _codigo(ENTRAR, cartao["codigo"]).json()["access_token"]
    _cartao_individual(cliente, escola_completa, cartao["aluno_id"],
                       "?rotacionar_codigo=true")
    _o_cartao_antigo_nao_entra(cartao, token)
    _o_cartao_novo_entra(db, cartao["aluno_id"], cartao)


def test_reimpressao_sem_parametro_nao_revoga_nada(cliente, db, escola_completa, cartao):
    token = _codigo(ENTRAR, cartao["codigo"]).json()["access_token"]
    _cartao_individual(cliente, escola_completa, cartao["aluno_id"])
    _cartoes_turma(cliente, escola_completa)
    mesmo = _cred(db, cartao["aluno_id"])
    assert (mesmo.codigo_login, mesmo.qr_token) == (cartao["codigo"], cartao["qr"])
    assert _perfil(token).status_code == 200
    assert _codigo(ENTRAR, cartao["codigo"]).status_code == 200
    assert _qr(cartao["qr"]).status_code == 200


# --- 2. Coerência com a 0037: texto e hash andam juntos --------------------------

def test_regenerar_grava_texto_e_hash_juntos_e_o_fallback_nao_reabre(
        cliente, db, escola_completa, cartao):
    _cartoes_turma(cliente, escola_completa, "?regenerar=true")
    novo = _cred(db, cartao["aluno_id"])
    assert novo.codigo_login_hash == svc.hash_codigo(novo.codigo_login)
    assert novo.qr_token_hash == svc.hash_qr(novo.qr_token)
    assert novo.codigo_login_hash != cartao["hash"]
    assert svc.contar_hashes_divergentes(db) == 0
    # Nenhuma linha guarda o código antigo — nem no hash (índice do login) nem no
    # texto (fallback da transição).
    assert db.execute(select(QuestCredencialAluno.id).where(or_(
        QuestCredencialAluno.codigo_login == cartao["codigo"],
        QuestCredencialAluno.codigo_login_hash.in_(
            svc.hashes_candidatos(cartao["codigo"]))))).first() is None
    assert svc.buscar_por_codigo(db, cartao["codigo"]) is None
    assert svc.buscar_por_qr(db, cartao["qr"]) is None


def test_regenerar_linha_sem_hash_de_backup_antigo(cliente, db, escola_completa, cartao):
    """Linha restaurada de backup anterior à 0037 (sem hash): entra pelo texto até
    ser regenerada; depois, o antigo não entra e o novo sai com os dois hashes."""
    linha = db.get(QuestCredencialAluno, _cred(db, cartao["aluno_id"]).id)
    linha.codigo_login_hash = None
    linha.qr_token_hash = None
    db.commit()

    _cartao_individual(cliente, escola_completa, cartao["aluno_id"], "?regenerar=true")
    assert _codigo(ENTRAR, cartao["codigo"]).status_code == 401
    assert _qr(cartao["qr"]).status_code == 401
    novo = _o_cartao_novo_entra(db, cartao["aluno_id"], cartao)
    assert novo.codigo_login_hash == svc.hash_codigo(novo.codigo_login)
    assert novo.qr_token_hash == svc.hash_qr(novo.qr_token)


# --- 3. O que fica registrado e o que a folha impressa orienta -------------------

def test_auditoria_registra_que_o_codigo_foi_trocado(cliente, db, escola_completa, cartao):
    _cartao_individual(cliente, escola_completa, cartao["aluno_id"], "?regenerar=true")
    db.expire_all()
    log = db.execute(select(LogAuditoria)
                     .where(LogAuditoria.acao == "quest.cartao_individual")
                     .order_by(LogAuditoria.id.desc())).scalars().first()
    assert log.detalhes == {"regenerou": True, "rotacionou_codigo": True}


def test_folha_do_professor_orienta_a_revogacao_que_funciona(cliente, escola_completa):
    r = _cartoes_turma(cliente, escola_completa)
    with pdfplumber.open(io.BytesIO(r.content)) as doc:
        folha = doc.pages[-1].extract_text() or ""
    assert "SO DO PROFESSOR" in folha
    # Nada de "o código não muda" nem de regenerar como troca só do QR
    assert "nao muda" not in folha
    assert "troca o QR de todos" not in folha
    assert "codigo e QR novos" in folha
    assert "os antigos param de entrar" in folha
