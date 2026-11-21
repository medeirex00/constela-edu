"""Ano letivo ativo da escola: faixa aceita e correção de um ano digitado errado (G_VIRADA-4).

Antes:

* ``EscolaCreate``/``EscolaUpdate`` aceitavam qualquer inteiro: com 10000, as Premiações e o
  Dashboard respondiam 500 ('year 10000 is out of range');
* um ano digitado adiante (2072 em vez de 2027) prendia a escola depois da 1ª Lista Piloto:
  o recálculo grava Notas no ano errado e a trava do histórico recusava para sempre voltar ao
  ano certo, chamando de "histórico de notas de 2072" as Notas de um ano que nem começou.

O que estes testes sustentam:

* o ano letivo fica entre 2000 e 2100 (a faixa de ``TurmaCreate``), no cadastro e no PATCH;
* as Notas de um ano que ainda não começou no calendário não são histórico: voltar para o ano
  certo é aceito e descarta essas Notas (cache do motor), com a contagem na auditoria;
* o histórico continua protegido: não se volta para antes de um ano já encerrado com Notas,
  nem para antes do ano ativo que já começou e tem Notas.

Dados INVENTADOS (fixture ``escola_completa``); o relógio fica em 11/11/2026.
"""
from datetime import date

import pytest
from sqlalchemy import func, select

from app.core import tempo
from app.models import LogAuditoria, Matricula, Nota, Turma
from app.services import scoring

API = "/api/v1"
HOJE = date(2026, 11, 11)


@pytest.fixture(autouse=True)
def _relogio(monkeypatch):
    monkeypatch.setattr(tempo, "hoje_br", lambda: HOJE)


def _patch_ano(cliente, eid, ano):
    return cliente.patch(f"{API}/escolas/{eid}", json={"ano_letivo_ativo": ano})


def _notas_por_ano(db, eid) -> dict[int, int]:
    db.expire_all()
    return dict(db.execute(select(Nota.ano_letivo, func.count()).where(Nota.escola_id == eid)
                           .group_by(Nota.ano_letivo)).all())


def _matricular_no_ano(db, escola_completa, ano):
    """O que a Lista Piloto faz no ano ativo: turma e matrícula do ano, e o recálculo."""
    escola = escola_completa["escola"]
    turma = Turma(escola_id=escola.id, nome="5º Ano A", ano_escolar="5º Ano", ano_letivo=ano)
    db.add(turma)
    db.flush()
    for aluno in escola_completa["alunos"][:2]:
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                         ano_letivo=ano))
    db.commit()
    scoring.recalcular_escola(db, escola.id)


@pytest.mark.parametrize("ano", [1999, 2101, 10000])
def test_ano_fora_da_faixa_e_recusado_no_patch(cliente_global, db, escola_completa, ano):
    eid = escola_completa["escola"].id
    r = _patch_ano(cliente_global, eid, ano)
    assert r.status_code == 422, r.text
    db.expire_all()
    assert db.get(type(escola_completa["escola"]), eid).ano_letivo_ativo == 2026


def test_ano_fora_da_faixa_e_recusado_no_cadastro(cliente_global):
    r = cliente_global.post(f"{API}/escolas", json={"nome": "EMEF Fictícia Ano Absurdo",
                                                   "ano_letivo_ativo": 10000})
    assert r.status_code == 422, r.text


def test_ano_digitado_adiante_pode_ser_corrigido(cliente_global, db, escola_completa):
    eid = escola_completa["escola"].id
    scoring.recalcular_escola(db, eid)                       # as Notas de 2026 (histórico)
    assert _patch_ano(cliente_global, eid, 2072).status_code == 200     # digitou 2072
    _matricular_no_ano(db, escola_completa, 2072)
    assert _notas_por_ano(db, eid) == {2026: 3, 2072: 2}
    corrigir = _patch_ano(cliente_global, eid, 2027)
    assert corrigir.status_code == 200, corrigir.text
    assert corrigir.json()["ano_letivo_ativo"] == 2027
    # As Notas de 2072 (um ano que não começou) saem; as de 2026 ficam intactas.
    assert _notas_por_ano(db, eid) == {2026: 3}
    log = db.execute(select(LogAuditoria).where(LogAuditoria.escola_id == eid,
                                                LogAuditoria.acao == "escola.atualizada")
                     .order_by(LogAuditoria.id.desc())).scalars().first()
    assert log.detalhes["ano_letivo_ativo"] == 2027
    assert log.detalhes["notas_descartadas"] == {"2072": 2}


def test_historico_encerrado_continua_protegido(cliente_global, db, escola_completa):
    """Com o ano errado no ar, voltar para ANTES do último ano encerrado com Notas (2026)
    continua recusado — e a mensagem fala do ano encerrado, não do ano digitado errado."""
    eid = escola_completa["escola"].id
    scoring.recalcular_escola(db, eid)
    assert _patch_ano(cliente_global, eid, 2072).status_code == 200
    _matricular_no_ano(db, escola_completa, 2072)
    r = _patch_ano(cliente_global, eid, 2025)
    assert r.status_code == 409, r.text
    assert "2026" in r.json()["detail"] and "2072" not in r.json()["detail"]
    assert _notas_por_ano(db, eid) == {2026: 3, 2072: 2}


def test_ano_ativo_que_ja_comecou_continua_protegido(cliente_global, db, escola_completa):
    """2026 já começou e tem Notas: voltar para 2025 reescreveria o histórico (como antes)."""
    eid = escola_completa["escola"].id
    scoring.recalcular_escola(db, eid)
    r = _patch_ano(cliente_global, eid, 2025)
    assert r.status_code == 409, r.text
    assert "2026" in r.json()["detail"]
    assert _notas_por_ano(db, eid) == {2026: 3}
