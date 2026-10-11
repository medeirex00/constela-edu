"""A sincronização do Elefante e a conta do professor da turma.

O relatório de turma do Elefante traz o nome do professor; a sincronização cria
sozinha a conta de login de quem ainda não está cadastrado. Esta conta nasce
ATIVA mas SEM senha conhecida — nenhuma senha derivável do nome abre — e o
primeiro acesso é pelo link de redefinição gerado pela gestão. A conta de quem
já existe não é tocada. Dados sintéticos; nada sai para a internet.
"""
import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Professor, Usuario
from app.services import professores
from app.sync import orchestrator
from app.sync.interfaces import ArquivoObtido, Contexto


def _login(usuario: str, senha: str):
    return TestClient(app).post("/api/v1/auth/login",
                                data={"username": usuario, "password": senha})


def _sincronizar(db, escola, professor_txt: str, monkeypatch) -> list[str]:
    """Roda o orquestrador REAL com um relatório de turma do Elefante (JSON da
    API) e devolve as mensagens do registro técnico da sincronização."""
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)
    mensagens: list[str] = []
    payload = {"courseSchoolDescriptors": {"courseName": "3º Ano A",
                                           "teachers": professor_txt},
               "students": [{"studentId": 1, "studentName": "Ana Beatriz Souza",
                             "totalBooksRead": 42}]}
    orchestrator.aplicar_arquivo(
        db, escola,
        ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                      nome_arquivo="e.json", plataforma="elefante",
                      content_type=orchestrator.CT_ELEFANTE_API, formato_hint="resumo"),
        usuario_id=None, recalcular=False,
        contexto=Contexto(escola_id=escola.id, execucao_id=None,
                          log=lambda etapa, nivel, msg: mensagens.append(msg)))
    db.expire_all()
    return mensagens


def test_a_sync_cria_a_conta_do_professor_sem_senha_conhecida(db, escola_completa, monkeypatch):
    escola = escola_completa["escola"]
    mensagens = _sincronizar(db, escola, "Marisa Sint Quintela", monkeypatch)

    conta = db.execute(select(Usuario).where(Usuario.username == "MarisaQuintela")).scalar_one()
    assert (conta.status, conta.cargo, conta.escola_id) == ("ativo", "professor", escola.id)
    assert conta.rede_id is None and not conta.is_global

    # Nenhuma senha previsível — das convenções antigas ou óbvia — abre a conta.
    previsiveis = professores._senhas_da_convencao_antiga(conta.nome, conta.username)
    previsiveis |= {"marisa123", "Marisa123", "marisaquintela123", "MarisaQuintela123",
                    "quintela123", "marisaquintela", "12345678", conta.email}
    for senha in previsiveis:
        assert _login("MarisaQuintela", senha).status_code == 401, senha

    # O registro técnico da sincronização não ensina senha nenhuma e aponta o link.
    texto = " ".join(mensagens)
    assert "123" not in texto and "senha =" not in texto.lower()
    assert "link de redefinição" in texto

    # A turma ganhou o titular (RBAC) — o vínculo segue como antes.
    prof = db.execute(select(Professor).where(Professor.email == conta.email)).scalar_one()
    assert escola_completa["turma"].professor_id == prof.id


def test_a_sync_nao_toca_na_conta_de_quem_ja_existe(db, escola_completa, monkeypatch):
    escola = escola_completa["escola"]
    professores.garantir_professor(db, escola.id, "Iolanda Sint Barreto")
    db.commit()
    conta = db.execute(select(Usuario).where(Usuario.username == "IolandaBarreto")).scalar_one()
    conta.senha_hash = hash_senha("trevo-sino-rio-52")   # a professora já definiu a dela
    db.commit()
    hash_antes, total_antes = conta.senha_hash, db.query(Usuario).count()

    # O Elefante manda o nome em caixa alta e abreviado: é a mesma pessoa.
    _sincronizar(db, escola, "IOLANDA SINT BARRETO", monkeypatch)

    db.refresh(conta)
    assert conta.senha_hash == hash_antes and conta.status == "ativo"
    assert db.query(Usuario).count() == total_antes          # nenhuma conta nova
    assert _login("IolandaBarreto", "trevo-sino-rio-52").status_code == 200
    assert _login("IolandaBarreto", "iolanda123").status_code == 401


def test_a_conta_criada_pela_sync_entra_pelo_link_de_redefinicao(db, escola_completa, monkeypatch):
    escola = escola_completa["escola"]
    _sincronizar(db, escola, "Celina Sint Moura", monkeypatch)
    conta = db.execute(select(Usuario).where(Usuario.username == "CelinaMoura")).scalar_one()

    r = _login("admin@teste.local", "s3nh4")
    admin = TestClient(app)
    admin.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    link = admin.post(f"/api/v1/escolas/{escola.id}/usuarios/{conta.id}/redefinir-senha")
    assert link.status_code == 200, link.text
    token = link.json()["token"]
    assert TestClient(app).post("/api/v1/auth/redefinir-senha",
                                json={"token": token, "nova_senha": "pomar-vela-ilha-64"}
                                ).status_code == 200
    assert _login("CelinaMoura", "pomar-vela-ilha-64").status_code == 200
