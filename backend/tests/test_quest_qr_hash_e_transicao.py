"""Quest — o QR com hash, a transição do deploy e a separação das tentativas.

Revisão de 20/10/2026 sobre a 0037 (``test_quest_codigo_hash``):

1. o hash do código deixava o ``qr_token`` — a MESMA credencial em figura — em
   texto claro e como o que o /entrar-qr consultava: o QR agora autentica pelo
   hash (``qr_token_hash``), com a mesma transição do código;
2. no deploy, o processo antigo gira código/QR só no TEXTO e deixa o hash do
   antigo: o cartão girado (perdido, vazado) continuava entrando pelo hash;
3. o /entrar-qr contava as falhas na mesma chave do código digitável: mandar o
   código de uma criança como qr_token travava o /quem e o /entrar dela, e com o
   limite persistente a trava valia para a API inteira e sobrevivia a deploys.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.main import app
from app.quest.models import QuestCredencialAluno
from app.quest.routers import auth as quest_auth
from app.quest.services import credenciais as svc

QUEM = "/api/v1/quest/auth/quem"
ENTRAR = "/api/v1/quest/auth/entrar"
ENTRAR_QR = "/api/v1/quest/auth/entrar-qr"


def _credencial(db, aluno_id) -> QuestCredencialAluno:
    db.expire_all()
    return db.execute(select(QuestCredencialAluno)
                      .where(QuestCredencialAluno.aluno_id == aluno_id)).scalar_one()


@pytest.fixture
def credencial(cliente, db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    r = cliente.post(f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/cartoes")
    assert r.status_code == 200, r.text
    return _credencial(db, escola_completa["alunos"][0].id)


def _qr(token, ip="203.0.113.10"):
    return TestClient(app).post(ENTRAR_QR, json={"qr_token": token},
                                headers={"X-Forwarded-For": ip})


def _codigo(url, codigo, ip="203.0.113.10"):
    return TestClient(app).post(url, json={"codigo": codigo},
                                headers={"X-Forwarded-For": ip})


def _reiniciar_processo():
    for lim in (quest_auth.limitador_codigo, quest_auth.limitador_ip,
                quest_auth.limitador_codigo_conta, quest_auth.limitador_ip_falha):
        lim._eventos.clear()


# --- 1. QR pelo hash ------------------------------------------------------------

def test_cartao_novo_grava_o_hash_do_qr(credencial):
    assert credencial.qr_token_hash == svc.hash_qr(credencial.qr_token)
    assert len(credencial.qr_token_hash) == 64
    assert credencial.qr_token not in credencial.qr_token_hash


def test_qr_autentica_pelo_hash_e_nao_pelo_texto(db, credencial, monkeypatch):
    """Sem o fallback (o estado depois da remoção da coluna), só o hash vale: com
    o texto trocado, o QR certo entra e o texto sozinho não."""
    monkeypatch.setattr(svc, "_FALLBACK_TEXTO_CLARO", False)
    token = credencial.qr_token
    linha = db.get(QuestCredencialAluno, credencial.id)
    linha.qr_token = "texto-trocado-de-teste-123"
    db.commit()
    assert _qr(token).status_code == 200
    assert _qr("texto-trocado-de-teste-123").status_code == 401


def test_caminho_principal_do_qr_nao_consulta_o_texto(db, credencial):
    consultas = []

    def anotar(conn, cursor, sql, params, context, executemany):
        consultas.append(sql)

    motor = db.get_bind()
    event.listen(motor, "before_cursor_execute", anotar)
    try:
        assert svc.buscar_por_qr(db, credencial.qr_token).id == credencial.id
    finally:
        event.remove(motor, "before_cursor_execute", anotar)
    assert consultas and all("qr_token_hash =" in sql for sql in consultas)


def test_qr_com_caractere_fora_do_ascii_responde_401(credencial):
    """O token vem do cliente: texto qualquer não pode virar 500 na comparação."""
    assert _qr("ação-çõ-" + "é" * 10).status_code == 401


def test_qr_sem_hash_entra_pelo_texto_e_sai_corrigido(db, credencial):
    """Backup anterior à 0037 restaurado, ou processo antigo gravando no deploy."""
    linha = db.get(QuestCredencialAluno, credencial.id)
    linha.qr_token_hash = None
    db.commit()
    assert svc.contar_hashes_divergentes(db) == 1
    assert _qr(credencial.qr_token).status_code == 200
    assert _credencial(db, credencial.aluno_id).qr_token_hash == \
        svc.hash_qr(credencial.qr_token)
    assert svc.contar_hashes_divergentes(db) == 0


def test_regenerar_troca_o_hash_do_qr_e_o_antigo_nao_entra(cliente, db, escola_completa,
                                                          credencial):
    antigo = credencial.qr_token
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    r = cliente.post(f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/cartoes"
                     "?regenerar=true")
    assert r.status_code == 200, r.text
    nova = _credencial(db, credencial.aluno_id)
    assert nova.qr_token != antigo and nova.qr_token_hash == svc.hash_qr(nova.qr_token)
    assert _qr(antigo).status_code == 401
    assert _qr(nova.qr_token).status_code == 200


# --- 2. Hash desatualizado pelo processo antigo ----------------------------------

def test_codigo_girado_so_no_texto_nao_deixa_o_antigo_entrar(db, credencial):
    """O processo antigo (sem a 0037 no código) gira o código gravando só o texto:
    o hash continua o do código ANTIGO. O antigo não entra; o novo entra e o hash
    sai refeito."""
    antigo = credencial.codigo_login
    linha = db.get(QuestCredencialAluno, credencial.id)
    linha.codigo_login = "GIRADOTESTE321"          # como o código de main grava
    db.commit()
    assert _credencial(db, credencial.aluno_id).codigo_login_hash == svc.hash_codigo(antigo)

    assert _codigo(QUEM, antigo).status_code == 401
    assert _codigo(ENTRAR, antigo).status_code == 401
    assert _codigo(ENTRAR, "GIRADOTESTE321").status_code == 200
    assert _credencial(db, credencial.aluno_id).codigo_login_hash == \
        svc.hash_codigo("GIRADOTESTE321")


def test_qr_trocado_so_no_texto_nao_deixa_o_antigo_entrar(db, credencial):
    antigo = credencial.qr_token
    linha = db.get(QuestCredencialAluno, credencial.id)
    linha.qr_token = "qr-novo-gravado-pelo-processo-antigo"
    db.commit()
    assert _qr(antigo).status_code == 401
    assert _qr("qr-novo-gravado-pelo-processo-antigo").status_code == 200
    assert _credencial(db, credencial.aluno_id).qr_token_hash == \
        svc.hash_qr("qr-novo-gravado-pelo-processo-antigo")


def test_hash_desatualizado_cedido_a_outra_linha_nao_quebra_o_indice(db, escola_completa,
                                                                     credencial):
    """Girado só no texto e, depois, o código antigo dado a OUTRA criança pelo
    processo antigo (que só confere o texto): quem tem o código entra. A outra
    linha tem id MENOR — o UPDATE dela iria primeiro e colidiria no índice único
    com o hash antigo ainda gravado na girada, se a correção não fosse ao banco
    antes. Sessão SEM autoflush, como a da aplicação (core/database.py)."""
    from sqlalchemy.orm import Session

    alunos = escola_completa["alunos"]
    girada, recebe = (db.execute(select(QuestCredencialAluno).where(
        QuestCredencialAluno.aluno_id == a.id)).scalar_one() for a in (alunos[2], alunos[0]))
    assert recebe.id < girada.id
    antigo = girada.codigo_login
    girada.codigo_login = "GIRADOTESTE321"
    recebe.codigo_login, recebe.codigo_login_hash = "TEMPORARIO999", None
    db.flush()
    recebe.codigo_login = antigo
    db.commit()

    with Session(bind=db.get_bind(), autoflush=False) as sessao:
        assert svc.buscar_por_codigo(sessao, antigo).id == recebe.id
        sessao.commit()
    db.expire_all()
    assert db.get(QuestCredencialAluno, recebe.id).codigo_login_hash == svc.hash_codigo(antigo)
    assert db.get(QuestCredencialAluno, girada.id).codigo_login_hash == \
        svc.hash_codigo("GIRADOTESTE321")


def test_preencher_corrige_hash_desatualizado_de_codigo_e_qr(db, credencial):
    """A conferência antes de remover as colunas cobre o QR: só o QR divergente
    já conta — e a correção acerta os dois."""
    linha = db.get(QuestCredencialAluno, credencial.id)
    linha.qr_token = "qr-novo-gravado-pelo-processo-antigo"
    db.commit()
    assert svc.contar_hashes_divergentes(db) == 1
    linha.codigo_login = "GIRADOTESTE321"
    db.commit()
    assert svc.contar_hashes_divergentes(db) == 1          # uma credencial
    assert svc.preencher_hashes_ausentes(db) == 1
    db.commit()
    assert svc.contar_hashes_divergentes(db) == 0
    db.expire_all()
    assert linha.qr_token_hash == svc.hash_qr("qr-novo-gravado-pelo-processo-antigo")
    assert linha.codigo_login_hash == svc.hash_codigo("GIRADOTESTE321")


# --- 3. Tentativas por QR não contam na chave do código --------------------------

def test_qr_com_o_codigo_digitavel_nao_trava_o_login_da_crianca(db, credencial):
    # Código de 8+ caracteres (o mínimo do qr_token), como os de palavra longa.
    codigo = "ESTRELA1234"   # 4 dígitos: o gerador atual nunca o sorteia
    svc.definir_codigo(db.get(QuestCredencialAluno, credencial.id), codigo)
    db.commit()
    respostas = [_qr(codigo, ip=f"203.0.113.{n // 7 + 1}").status_code for n in range(30)]
    assert 429 in respostas                 # o limite do QR continua valendo
    _reiniciar_processo()                   # o que sobra para barrar é o banco
    assert _codigo(QUEM, codigo, ip="198.51.100.9").status_code == 200
    assert _codigo(ENTRAR, codigo, ip="198.51.100.9").status_code == 200
