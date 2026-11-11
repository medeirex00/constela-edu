"""Cartões do Quest de uma turma de OUTRO ano letivo (S_G_QUEST-1).

Depois da virada, a turma do ano anterior lista as matrículas daquele ano (histórico).
A reimpressão da folha dela saía com o nome da turma VELHA em cada cartão ("3º Ano A"
para quem já está no "4º Ano A") e ainda criava credencial e perfil para quem não
tinha. Agora a reimpressão (sem revogação) dessa turma é recusada com 409, sem PDF e
sem mexer em nada; a turma do ano ativo segue imprimindo.

A revogação (``regenerar`` / ``rotacionar_codigo``) da turma velha NÃO é recusada: é
o único caminho em lote que derruba o cartão de quem saiu da escola e segue com a
ficha ativa (G_VIRADA-2, decisão do dono). O último teste guarda isso.

Dados 100% fictícios (fixture ``escola_completa``).
"""
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import Aluno, Escola, LogAuditoria, Matricula, Turma
from app.quest.models import QuestCredencialAluno, QuestPerfil
from app.quest.services import cartoes_pdf

ENTRAR = "/api/v1/quest/auth/entrar"


def _folha(cliente, escola_id: int, turma_id: int, consulta: str = ""):
    return cliente.post(f"/api/v1/escolas/{escola_id}/quest/turmas/{turma_id}/cartoes{consulta}")


def _codigo(db, aluno_id: int) -> str:
    db.expire_all()
    return db.execute(select(QuestCredencialAluno.codigo_login)
                      .where(QuestCredencialAluno.aluno_id == aluno_id)).scalar_one()


def _entra(codigo: str) -> int:
    return TestClient(app).post(ENTRAR, json={"codigo": codigo}).status_code


def _virada(db, escola, alunos) -> tuple[int, Turma]:
    """Ano ativo + 1 e a turma nova com a matrícula de cada criança em ``alunos``."""
    esc = db.get(Escola, escola.id)
    novo = esc.ano_letivo_ativo + 1
    esc.ano_letivo_ativo = novo
    nova = Turma(escola_id=escola.id, nome="4º Ano A", ano_escolar="4º Ano", ano_letivo=novo)
    db.add(nova)
    db.flush()
    for aluno in alunos:
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=nova.id,
                         ano_letivo=novo))
    db.commit()
    return novo, nova


def _capturar_pdf(monkeypatch) -> list[str]:
    turmas_impressas: list[str] = []
    original = cartoes_pdf.gerar_cartoes_pdf

    def _gerar(**kw):
        turmas_impressas.append(kw.get("turma_nome"))
        return original(**kw)

    monkeypatch.setattr(cartoes_pdf, "gerar_cartoes_pdf", _gerar)
    return turmas_impressas


def _contagens(db) -> tuple[int, int, int]:
    db.expire_all()
    return (db.execute(select(func.count()).select_from(QuestCredencialAluno)).scalar_one(),
            db.execute(select(func.count()).select_from(QuestPerfil)).scalar_one(),
            db.execute(select(func.count()).select_from(LogAuditoria)
                       .where(LogAuditoria.acao.like("quest.%"))).scalar_one())


def test_reimpressao_da_turma_de_outro_ano_e_recusada_sem_mexer_em_nada(
        cliente, db, escola_completa, monkeypatch):
    escola, turma_velha = escola_completa["escola"], escola_completa["turma"]
    alunos = escola_completa["alunos"]
    assert _folha(cliente, escola.id, turma_velha.id).status_code == 200
    # Criança da turma velha que nunca recebeu cartão: a recusa não cria nada para ela.
    sem_cartao = Aluno(escola_id=escola.id, nome="Crianca Ficticia Sem Cartao")
    db.add(sem_cartao)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=sem_cartao.id, turma_id=turma_velha.id,
                     ano_letivo=turma_velha.ano_letivo))
    db.commit()
    novo, nova = _virada(db, escola, alunos)
    assert _folha(cliente, escola.id, nova.id, "?rotacionar_codigo=true").status_code == 200
    folha_nova = {a.id: _codigo(db, a.id) for a in alunos}
    antes = _contagens(db)
    impressas = _capturar_pdf(monkeypatch)

    r = _folha(cliente, escola.id, turma_velha.id)

    assert r.status_code == 409, (
        f"a reimpressão da turma de {turma_velha.ano_letivo} respondeu {r.status_code} "
        f"({r.headers.get('content-type')}) com o PDF da turma {impressas}")
    texto = r.json()["detail"]
    assert f"ano letivo {turma_velha.ano_letivo}" in texto
    assert f"ano letivo {novo}" in texto
    assert "Nenhum cartão foi gerado" in texto
    assert impressas == [], f"o PDF saiu com a turma velha: {impressas}"
    assert _contagens(db) == antes, "a recusa criou credencial, perfil ou registro"
    assert {a.id: _codigo(db, a.id) for a in alunos} == folha_nova
    assert [_entra(c) for c in folha_nova.values()] == [200, 200, 200]


def test_turma_do_ano_ativo_segue_reimprimindo_com_o_mesmo_codigo(
        cliente, db, escola_completa, monkeypatch):
    escola, turma_velha = escola_completa["escola"], escola_completa["turma"]
    alunos = escola_completa["alunos"]
    _, nova = _virada(db, escola, alunos)
    assert _folha(cliente, escola.id, nova.id, "?rotacionar_codigo=true").status_code == 200
    folha_nova = {a.id: _codigo(db, a.id) for a in alunos}
    impressas = _capturar_pdf(monkeypatch)

    r = _folha(cliente, escola.id, nova.id)

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert impressas == ["4º Ano A"]
    assert {a.id: _codigo(db, a.id) for a in alunos} == folha_nova
    assert turma_velha.id != nova.id


def test_rotacionar_a_turma_de_outro_ano_segue_derrubando_o_cartao_de_quem_saiu(
        cliente, db, escola_completa):
    """Quem saiu da escola na virada segue com a ficha ativa e sem matrícula nova
    (G_VIRADA-2): a revogação da turma VELHA é o caminho em lote que derruba o
    cartão dele. A recusa vale só para a reimpressão."""
    escola, turma_velha = escola_completa["escola"], escola_completa["turma"]
    ficam, saiu = escola_completa["alunos"][:2], escola_completa["alunos"][2]
    assert _folha(cliente, escola.id, turma_velha.id).status_code == 200
    codigo_de_quem_saiu = _codigo(db, saiu.id)
    _, nova = _virada(db, escola, ficam)
    assert _folha(cliente, escola.id, nova.id, "?rotacionar_codigo=true").status_code == 200
    assert _entra(codigo_de_quem_saiu) == 200

    r = _folha(cliente, escola.id, turma_velha.id, "?rotacionar_codigo=true")

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert _entra(codigo_de_quem_saiu) == 401
