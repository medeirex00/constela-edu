"""Vestiário do Quest: o log permanente registra QUE a criança trocou a aparência, não a
aparência dela — e a exclusão permanente leva as cópias antigas (S_G_QUEST-3).

O DEFEITO. ``PATCH /quest/perfil/avatar`` gravava ``quest.avatar`` com o avatar INTEIRO
(14 slots, com o tom de pele) a cada toque no vestiário — uma linha por toque, no log
permanente. A regra do próprio Quest para o nome (``quest.nome_escolhido``, RETENCAO-
TECNICA §2.1) é a oposta: o valor vigente está no perfil e some com ele na exclusão; o
log não precisa de cópia. E a exclusão permanente não redigia ``avatar``: o perfil do
Quest sumia, mas o histórico de aparência ficava ligado ao ``entidade_id`` dela.

Dados 100% fictícios.
"""
import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Aluno, LogAuditoria
from app.quest.models import QuestCredencialAluno
from app.services.audit import registrar
from app.services.exclusao_aluno import MARCA_REMOVIDO

ENTRAR = "/api/v1/quest/auth/entrar"
PERFIL = "/api/v1/quest/perfil"
PELES = ["#8D5524", "#4A3020", "#6E4A2C"]
TOQUES = [{"pele": PELES[0]}, {"pele": PELES[1]}, {"cabelo": "afro"},
          {"cabelo": "afro_puff"}, {"cor_cabelo": "#2B2B2B"}, {"pele": PELES[2]},
          {"chapeu": "coroa"}, {"chapeu": "nenhum"}, {"pet": "dino"},
          {"pele": PELES[0], "cabelo": "afro"}]


def _logs(db, acao, aluno_id):
    db.expire_all()
    return db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == acao, LogAuditoria.entidade == "aluno",
        LogAuditoria.entidade_id == aluno_id).order_by(LogAuditoria.id)).scalars().all()


def _entrar(cliente, db, escola, turma, aluno_id):
    r = cliente.post(f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/cartoes")
    assert r.status_code == 200, r.text
    db.expire_all()
    codigo = db.execute(select(QuestCredencialAluno.codigo_login)
                        .where(QuestCredencialAluno.aluno_id == aluno_id)).scalar_one()
    r = TestClient(app).post(ENTRAR, json={"codigo": codigo})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_cada_toque_no_vestiario_grava_so_os_slots_trocados(cliente, db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    aluno_id = escola_completa["alunos"][0].id
    cab = _entrar(cliente, db, escola, turma, aluno_id)
    for toque in TOQUES:
        r = TestClient(app).patch(f"{PERFIL}/avatar", headers=cab, json=toque)
        assert r.status_code == 200, r.text
    # O perfil guarda a aparência vigente (o vestiário continua funcionando)...
    final = TestClient(app).get(PERFIL, headers=cab).json()["avatar"]
    assert final["pele"] == PELES[0] and final["pet"] == "dino"
    # ...e o log, só QUE slots mudaram — sem nenhum valor.
    linhas = _logs(db, "quest.avatar", aluno_id)
    assert [log.detalhes for log in linhas] == [
        {"slots": sorted(toque)} for toque in TOQUES]
    texto = json.dumps([log.detalhes for log in linhas])
    assert not any(valor in texto for valor in (*PELES, "afro", "coroa", "dino"))


def test_exclusao_permanente_tira_o_avatar_das_linhas_antigas(
        cliente_global, db, escola_completa):
    """As linhas gravadas antes da correção (o avatar inteiro) perdem o avatar na
    exclusão; a de outra criança fica como está."""
    escola = escola_completa["escola"]
    sai, fica = escola_completa["alunos"][0].id, escola_completa["alunos"][1].id
    for aluno_id in (sai, fica):
        for pele in PELES:
            registrar(db, "quest.avatar", escola_id=escola.id, entidade="aluno",
                      entidade_id=aluno_id,
                      detalhes={"avatar": {"pele": pele, "cabelo": "afro", "pet": "dino"}})
    db.commit()
    r = cliente_global.post(f"/api/v1/escolas/{escola.id}/alunos/excluir-permanente",
                            json={"aluno_ids": [sai], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Aluno, sai) is None
    dela = _logs(db, "quest.avatar", sai)
    assert len(dela) == 3                                    # o fato (e quando) fica
    assert [log.detalhes for log in dela] == [{"avatar": MARCA_REMOVIDO}] * 3
    assert [log.detalhes["avatar"]["pele"] for log in _logs(db, "quest.avatar", fica)] \
        == PELES
