"""Questões do Elefante por período: a coleta que PAROU não sai como "completa"
(frente C, 22/10/2026).

A declaração de cobertura do dono (8b7d911..3e3c512, aplicada com cherry-pick)
já marca "parcial" quando falta coleta na borda de um aluno medido e quando o
aluno foi coletado antes E depois do período mas não dentro dele. Faltava o caso
que a sincronização parcial produz (S3: uma turma inteira fora do relatório do
Elefante; agenda parada antes do bimestre; "este mês" sem coleta desde o dia
1º): o aluno ERA coletado e simplesmente deixou de ser. Ele ficava em
``alunos_sem_retrato`` e o número da escola — só de quem foi coletado — saía
"completa". Agora:

* ``alunos_coleta_interrompida``: coletado antes do período, sem nenhuma coleta
  que entre na conta → fora da conta e o número é ``parcial``;
* ``turmas_sem_coleta``: turmas JÁ coletadas alguma vez sem nenhum retrato na
  janela (a que nunca foi coletada não entra: é indistinguível de turma que não
  usa a plataforma) → ``parcial``, com os nomes na tela e no PDF.

O número em si não muda. Dados fictícios.
"""
from __future__ import annotations

from datetime import date, datetime

from app.models import Aluno, Matricula, Turma
from app.services import relatorios_periodo as rp
from app.services import relatorios_periodo_pdf as rp_pdf
from tests.test_relatorios_periodo_cobertura import _noite, _snap_elefante

HOJE_OUT = date(2026, 10, 6)


def _segunda_turma(db, escola_completa, n=2):
    escola = escola_completa["escola"]
    t = Turma(escola_id=escola.id, nome="4º Ano B", ano_escolar="4º Ano",
              ano_letivo=escola.ano_letivo_ativo)
    db.add(t)
    db.flush()
    alunos = []
    for i in range(n):
        a = Aluno(escola_id=escola.id, nome=f"Crianca Ficticia B{i}")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=t.id,
                         ano_letivo=escola.ano_letivo_ativo))
        alunos.append(a.id)
    db.flush()
    return t, alunos


def _turma_a_completa(db, eid, ids, mes_ini=(1, 9), mes_fim=(1, 10)):
    """Os 3 alunos da fixture medidos nas duas bordas de setembro."""
    for k, aid in enumerate(ids, start=1):
        _snap_elefante(db, eid, aid, _noite(*mes_ini), 10 * k, 5 * k)
        _snap_elefante(db, eid, aid, _noite(*mes_fim), 20 * k, 10 * k)


def _gerar(db, eid, **kw):
    kw.setdefault("preset", "mes_anterior")
    kw.setdefault("plataformas", ("elefante",))
    kw.setdefault("hoje", HOJE_OUT)
    return rp.gerar(db, eid, **kw)


def test_turma_que_parou_de_ser_coletada_deixa_o_numero_parcial(db, escola_completa):
    eid = escola_completa["escola"].id
    ids = [a.id for a in escola_completa["alunos"]]
    _turma_a_completa(db, eid, ids)
    _t, b_ids = _segunda_turma(db, escola_completa)
    for aid in b_ids:       # coletada em agosto e nunca mais (o relatório parou de trazê-la)
        _snap_elefante(db, eid, aid, datetime(2026, 8, 15, 12, 0), 50, 30)
    db.commit()
    ele = _gerar(db, eid)["elefante"]
    cob = ele["cobertura_questoes"]
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (60, 30), \
        "o número continua o de quem foi medido"
    assert cob["status"] == "parcial" and cob["completa"] is False
    assert cob["alunos_coleta_interrompida"] == 2
    assert [t["turma"] for t in cob["turmas_sem_coleta"]] == ["4º Ano B"]
    assert cob["turmas_sem_coleta"][0]["alunos"] == 2


def test_mes_em_andamento_sem_coleta_desde_antes_do_dia_1_e_parcial(db, escola_completa):
    """"Este mês": a turma B foi coletada pela última vez em 28/09 — no fim do
    período aberto ela não aparece em nenhuma coleta e não pode sumir calada."""
    eid = escola_completa["escola"].id
    ids = [a.id for a in escola_completa["alunos"]]
    for aid in ids:
        _snap_elefante(db, eid, aid, _noite(1, 10), 100, 80)
        _snap_elefante(db, eid, aid, _noite(6, 10), 112, 90)
    _t, b_ids = _segunda_turma(db, escola_completa, n=1)
    _snap_elefante(db, eid, b_ids[0], datetime(2026, 9, 28, 12, 0), 70, 50)
    db.commit()
    cob = _gerar(db, eid, preset="mes")["elefante"]["cobertura_questoes"]
    assert cob["status"] == "parcial"
    assert cob["alunos_coleta_interrompida"] == 1
    assert [t["turma"] for t in cob["turmas_sem_coleta"]] == ["4º Ano B"]


def test_turma_coletada_so_depois_do_periodo_e_turma_sem_coleta(db, escola_completa):
    """A primeira coleta da turma B foi em 05/10: setembro não a inclui. Não é
    coleta interrompida (não havia coleta antes), mas o número da escola não é
    o de setembro inteiro."""
    eid = escola_completa["escola"].id
    ids = [a.id for a in escola_completa["alunos"]]
    _turma_a_completa(db, eid, ids)
    _t, b_ids = _segunda_turma(db, escola_completa)
    for aid in b_ids:
        _snap_elefante(db, eid, aid, datetime(2026, 10, 5, 12, 0), 40, 20)
    db.commit()
    cob = _gerar(db, eid)["elefante"]["cobertura_questoes"]
    assert cob["alunos_coleta_interrompida"] == 0
    assert [t["turma"] for t in cob["turmas_sem_coleta"]] == ["4º Ano B"]
    assert cob["status"] == "parcial"


def test_turma_que_nunca_foi_coletada_nao_muda_a_cobertura(db, escola_completa):
    """Turma sem NENHUM retrato (ex.: não usa a plataforma) continua como antes:
    ausência, não falta de coleta — o número dos medidos segue "completa"."""
    eid = escola_completa["escola"].id
    ids = [a.id for a in escola_completa["alunos"]]
    _turma_a_completa(db, eid, ids)
    _segunda_turma(db, escola_completa)
    db.commit()
    ele = _gerar(db, eid)["elefante"]
    cob = ele["cobertura_questoes"]
    assert cob["status"] == "completa"
    assert cob["turmas_sem_coleta"] == [] and cob["alunos_coleta_interrompida"] == 0
    assert ele["alunos_sem_retrato"] == 2


def test_pdf_diz_a_coleta_interrompida_e_a_turma_em_latin1(db, escola_completa):
    eid = escola_completa["escola"].id
    ids = [a.id for a in escola_completa["alunos"]]
    _turma_a_completa(db, eid, ids)
    _t, b_ids = _segunda_turma(db, escola_completa)
    for aid in b_ids:
        _snap_elefante(db, eid, aid, datetime(2026, 8, 15, 12, 0), 50, 30)
    db.commit()
    avisos = rp_pdf._avisos_cobertura(_gerar(db, eid))
    questoes = next(a for a in avisos if a["rotulo"] == "Questões do Elefante")
    assert questoes["status"] == "parcial"
    texto = " ".join(questoes["motivos"])
    assert "2 estudante(s) coletados antes do período" in texto
    assert "4º Ano B" in texto
    for valor, detalhe in questoes["curtos"]:
        (valor + detalhe).encode("latin-1")     # a reserva do PDF usa fontes latin-1
    assert ("2 coleta interrompida", "fora da conta") in questoes["curtos"]
