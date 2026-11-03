"""D19 sem atalho: a exclusão FÍSICA de aluno é do Admin Global (T25).

A 2ª revisão de integração (contas-acesso, prova 1) mostrou que o D19 fechava
só o DELETE /turmas?com_alunos=true: a coordenação, barrada ali, apagava os
MESMOS alunos pelo POST /alunos/excluir-permanente — inclusive quem tinha
matrícula em outra turma, que o D19 só desvincula — e depois excluía a turma
vazia, sem o resumo ``turma.exclusao_com_alunos``. Agora a rota direta segue a
mesma régua: 403 com a mesma mensagem do D19 para quem não é ``is_global``,
ANTES de qualquer DELETE (e antes até de conferir a confirmação). O caminho da
escola é a exclusão lógica, reversível. Dados 100% fictícios; sem rede.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import hash_senha
from app.main import app
from app.models import Aluno, LogAuditoria, Matricula, Turma, Usuario
from app.routers import academico

API = "/api/v1"


@pytest.fixture(autouse=True)
def pastas(tmp_path, monkeypatch):
    """A exclusão física apaga, no commit, as cópias em /exports e os originais
    de relatório individual: aponta as pastas para o tmp do teste."""
    uploads, exports = tmp_path / "uploads", tmp_path / "exports"
    (uploads / "elefante").mkdir(parents=True)
    exports.mkdir()
    monkeypatch.setattr(settings, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(settings, "EXPORTS_DIR", exports)


def _cliente_coordenador(db, escola_id):
    db.add(Usuario(escola_id=escola_id, nome="Coordenadora Ficticia",
                   email="coord.d19@teste.local", senha_hash=hash_senha("Senha-Coord-9x"),
                   cargo="coordenador"))
    db.commit()
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": "coord.d19@teste.local",
                                         "password": "Senha-Coord-9x"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _com_aluno_em_outra_turma(db, escola_completa) -> list[int]:
    """Os 3 alunos da turma; o 1º também tem matrícula em OUTRA turma (2025)."""
    eid = escola_completa["escola"].id
    ids = [a.id for a in escola_completa["alunos"]]
    outra = Turma(escola_id=eid, nome="Reforco Ficticio", ano_escolar="3º Ano",
                  ano_letivo=2025)
    db.add(outra)
    db.flush()
    db.add(Matricula(escola_id=eid, aluno_id=ids[0], turma_id=outra.id, ano_letivo=2025))
    db.commit()
    return ids


def _alunos_restantes(db, ids) -> int:
    db.expire_all()
    return db.execute(select(func.count()).select_from(Aluno)
                      .where(Aluno.id.in_(ids))).scalar_one()


def _exclusoes_auditadas(db) -> int:
    return db.execute(select(func.count()).select_from(LogAuditoria).where(
        LogAuditoria.acao == "aluno.excluido_permanente")).scalar_one()


def _url(eid):
    return f"{API}/escolas/{eid}/alunos/excluir-permanente"


def test_coordenacao_nao_apaga_pelo_atalho_os_alunos_que_o_d19_reserva(db, escola_completa):
    """Prova 1 invertida: o atalho fechou e a turma não fica vazia para sair."""
    eid, tid = escola_completa["escola"].id, escola_completa["turma"].id
    ids = _com_aluno_em_outra_turma(db, escola_completa)
    c = _cliente_coordenador(db, eid)

    # 1) O caminho do D19: 403 (como antes).
    r = c.delete(f"{API}/escolas/{eid}/turmas/{tid}", params={"com_alunos": "true"})
    assert r.status_code == 403, r.text

    # 2) O atalho: agora também 403, com a mesma régua e o mesmo motivo do D19.
    r = c.post(_url(eid), json={"aluno_ids": ids, "confirmacao": "EXCLUIR"})
    assert r.status_code == 403, r.text
    detalhe = r.json()["detail"]
    assert "exclusivo do Admin Global" in detalhe
    assert academico._D19_APAGA_EM_DEFINITIVO in detalhe
    assert "Excluir permanentemente 3 aluno(s)" in detalhe
    assert "“Excluir”" in detalhe                     # o caminho reversível que ela tem

    # 3) A turma NÃO ficou vazia: a exclusão simples segue barrada.
    r = c.delete(f"{API}/escolas/{eid}/turmas/{tid}")
    assert r.status_code == 409, r.text

    assert _alunos_restantes(db, ids) == 3
    assert db.get(Turma, tid) is not None
    assert db.get(Aluno, ids[0]) is not None          # o da outra turma também fica
    assert _exclusoes_auditadas(db) == 0


def test_admin_da_escola_tambem_recebe_403_e_nada_e_apagado(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    ids = [a.id for a in escola_completa["alunos"]]
    r = cliente.post(_url(eid), json={"aluno_ids": [ids[0]], "confirmacao": "EXCLUIR"})
    assert r.status_code == 403, r.text
    assert "exclusivo do Admin Global" in r.json()["detail"]
    assert _alunos_restantes(db, ids) == 3
    assert db.execute(select(func.count()).select_from(Matricula)
                      .where(Matricula.aluno_id.in_(ids))).scalar_one() == 3
    assert _exclusoes_auditadas(db) == 0


def test_recusa_vem_antes_da_confirmacao_e_de_qualquer_leitura(cliente, db, escola_completa):
    """Quem não pode excluir não descobre nada pela rota: nem se a confirmação
    está certa, nem se o id existe (403 em vez de 400/404)."""
    eid = escola_completa["escola"].id
    r = cliente.post(_url(eid), json={"aluno_ids": [999999], "confirmacao": "sim"})
    assert r.status_code == 403, r.text


def test_a_mensagem_e_a_mesma_do_d19_da_turma(cliente, db, escola_completa):
    """As duas portas de exclusão física dão o mesmo motivo e a mesma régua."""
    eid, tid = escola_completa["escola"].id, escola_completa["turma"].id
    turma = cliente.delete(f"{API}/escolas/{eid}/turmas/{tid}", params={"com_alunos": "true"})
    direta = cliente.post(_url(eid), json={"aluno_ids": [escola_completa["alunos"][0].id],
                                           "confirmacao": "EXCLUIR"})
    assert turma.status_code == direta.status_code == 403
    for detalhe in (turma.json()["detail"], direta.json()["detail"]):
        assert academico._D19_APAGA_EM_DEFINITIVO in detalhe
        assert academico._D19_EXCLUSIVO in detalhe


def test_controle_admin_global_exclui_permanentemente(cliente_global, db, escola_completa):
    eid = escola_completa["escola"].id
    ids = _com_aluno_em_outra_turma(db, escola_completa)
    r = cliente_global.post(_url(eid), json={"aluno_ids": ids, "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text
    assert r.json()["afetados"] == 3
    assert _alunos_restantes(db, ids) == 0
    assert _exclusoes_auditadas(db) == 3


def test_controle_admin_global_ainda_exige_a_confirmacao(cliente_global, db, escola_completa):
    eid = escola_completa["escola"].id
    ids = [a.id for a in escola_completa["alunos"]]
    r = cliente_global.post(_url(eid), json={"aluno_ids": ids, "confirmacao": "sim"})
    assert r.status_code == 400, r.text
    assert _alunos_restantes(db, ids) == 3
