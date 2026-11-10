"""Questões do período (S9): cada aluno numa causa só, e "a última coleta" com a data
da coleta mais recente dele.

Revisão de integração (10/11): no aviso de cobertura parcial, o aluno cuja coleta do
fim do período veio SEM as questões aparecia duas vezes — em "A última coleta é de
X: o que veio depois não está na conta" e em "a plataforma não mandou as questões:
a conta deles vai só até a coleta anterior". E o X era a coleta ANTERIOR dele (a
última que mede as questões), embora ele tivesse uma coleta mais recente — a que
veio sem as questões. O número em si estava certo; a explicação, não.

Agora:
  * "as questões não vieram" conta quem teve a conta mudada NO FIM pela coleta sem
    questões (a conta vai até a anterior) ou ficou sem diferença a medir por causa
    dela — é o que o aviso diz; esse aluno não entra em "a última coleta é de X";
  * "a última coleta é de X" fala só de quem de fato não tem coleta depois de X no
    período, e X é a coleta mais recente desses alunos;
  * a coleta sem questões que mudaria só a borda do INÍCIO não é "as questões não
    vieram": quem explica a conta é a borda do início (aqui, a base de antes do
    período: o número inclui atividade de antes dele).
Instantes em UTC, como a sync grava (00:10 em Brasília = 03:10 UTC). Dados FICTÍCIOS.
"""
from __future__ import annotations

from datetime import date, datetime

from app.models import Importacao, SnapshotElefante
from app.models.plataformas import IMPORTACAO_SEM_QUESTOES
from app.services import relatorios_periodo as rp
from app.services import relatorios_periodo_pdf as pdf
from tests.sync_integridade_comum import aluno

HOJE_OUT = date(2026, 10, 6)


def _retrato(db, escola_id, aluno_id, quando, tentativas, acertos, *, sem_questoes=False):
    imp = Importacao(escola_id=escola_id, usuario_id=None, plataforma="elefante",
                     tipo="pdf", arquivo_original=None, qtd_alunos=0, qtd_erros=0,
                     tempo_ms=0, created_at=quando,
                     status=IMPORTACAO_SEM_QUESTOES if sem_questoes else "concluida")
    db.add(imp)
    db.flush()
    db.add(SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                            data_referencia=quando, livros_unicos=3, tempo_leitura_min=40,
                            questoes_tentativas=tentativas, questoes_acertos=acertos,
                            livros_por_nivel={}))
    db.flush()


def _noite(dia: int, mes: int = 9) -> datetime:
    """A coleta da agenda: 00:10 em Brasília (03:10 UTC)."""
    return datetime(2026, mes, dia, 3, 10)


def _cena(db, escola_completa):
    eid = escola_completa["escola"].id
    t = escola_completa["turma"]
    a, b, c = (x.id for x in escola_completa["alunos"])
    d = aluno(db, eid, t, "Dalva Ficticia Prado").id
    e = aluno(db, eid, t, "Elton Ficticio Rangel").id
    # A: a coleta que mede o fim (01/10) veio sem as questões; a conta vai até 20/09.
    _retrato(db, eid, a, _noite(1), 100, 80)
    _retrato(db, eid, a, _noite(20), 130, 101)
    _retrato(db, eid, a, _noite(1, 10), 130, 101, sem_questoes=True)
    # B: a coleta dele PAROU em 24/09 (nenhuma depois): o fim falta de verdade.
    _retrato(db, eid, b, _noite(1), 50, 40)
    _retrato(db, eid, b, _noite(24), 60, 45)
    # C: as duas bordas medidas.
    _retrato(db, eid, c, _noite(1), 10, 5)
    _retrato(db, eid, c, _noite(1, 10), 20, 10)
    # D: a última coleta (25/09) veio sem as questões; a conta vai até 20/09.
    _retrato(db, eid, d, _noite(1), 70, 50)
    _retrato(db, eid, d, _noite(20), 80, 60)
    _retrato(db, eid, d, _noite(25), 80, 60, sem_questoes=True)
    # E: a coleta do INÍCIO (01/09) veio sem as questões; a base é a de 15/08 e o fim
    # está medido: o número inclui o que veio de 15/08 a 01/09.
    _retrato(db, eid, e, _noite(15, 8), 40, 30)
    _retrato(db, eid, e, _noite(1), 40, 30, sem_questoes=True)
    _retrato(db, eid, e, _noite(1, 10), 55, 40)
    db.commit()
    return eid


def _setembro(db, eid):
    return rp.gerar(db, eid, preset="mes_anterior", plataformas=("elefante",),
                    hoje=HOJE_OUT)["elefante"]


def test_cada_aluno_numa_causa_so_e_a_ultima_coleta_e_a_mais_recente(db, escola_completa):
    eid = _cena(db, escola_completa)

    ele = _setembro(db, eid)

    cob = ele["cobertura_questoes"]
    # O número não muda: A 30, B 10, C 10, D 10, E 15 (incluindo 15/08 a 01/09).
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (75, 51)
    assert cob["status"] == "parcial" and cob["alunos_medidos"] == 5
    # As questões não vieram: A e D (a coleta sem elas seria o fim da conta).
    assert cob["alunos_questoes_nao_vieram"] == 2, cob
    # "A última coleta é de X": só B, e X é a coleta mais recente dele (24/09) — não
    # a de 20/09 de A e D, que tiveram coleta depois (sem as questões).
    assert cob["alunos_sem_fim"] == 1, cob
    assert cob["coleta_fim_mais_cedo"].startswith("2026-09-24T03:10"), cob
    assert cob["fim_coberto"] is False
    # E: só a borda do início (ampliada), não "as questões não vieram" — e, como houve
    # coleta no início (só que sem as questões), não "não há coleta perto do início".
    assert cob["inclui_antes_do_inicio"] is True
    assert (cob["alunos_inicio_sem_questoes"], cob["alunos_ampliados"]) == (1, 0), cob
    assert cob["alunos_cobertura_completa"] == 1                     # C


def test_so_alunos_sem_questoes_no_fim_nao_viram_ultima_coleta(db, escola_completa):
    """Sem nenhum aluno com a coleta parada, "a última coleta é de X" não aparece: o
    fim que falta é todo explicado pelas questões que não vieram."""
    eid = escola_completa["escola"].id
    a, b, _c = (x.id for x in escola_completa["alunos"])
    for x in (a, b):
        _retrato(db, eid, x, _noite(1), 100, 80)
        _retrato(db, eid, x, _noite(20), 130, 101)
        _retrato(db, eid, x, _noite(1, 10), 130, 101, sem_questoes=True)
    db.commit()

    cob = _setembro(db, eid)["cobertura_questoes"]

    assert cob["status"] == "parcial" and cob["alunos_questoes_nao_vieram"] == 2
    assert cob["alunos_sem_fim"] == 0 and cob["fim_coberto"] is False


def test_coleta_sem_questoes_na_mesma_borda_de_uma_valida_nao_e_motivo(db, escola_completa):
    """A coleta válida mede o fim (dentro da tolerância) e a sem questões é ainda mais
    perto dele: a conta está completa, e nada de "as questões não vieram"."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0].id
    _retrato(db, eid, a, _noite(1), 100, 80)
    _retrato(db, eid, a, datetime(2026, 10, 1, 2, 40), 150, 120)      # 23:40 de 30/09
    _retrato(db, eid, a, datetime(2026, 10, 1, 3, 5), 150, 120, sem_questoes=True)
    db.commit()

    ele = _setembro(db, eid)

    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (50, 40)
    cob = ele["cobertura_questoes"]
    assert cob["status"] == "completa" and cob["alunos_questoes_nao_vieram"] == 0


def test_coleta_sem_questoes_so_antes_do_periodo_nao_e_motivo(db, escola_completa):
    """Revisão final (a sonda F): a ÚNICA coleta sem as questões é de 15/08, antes do
    período, e a única do período (20/09) TROUXE as questões. Sem a de 15/08 não há
    diferença a medir — mas quem veio sem as questões foi a base, de antes do
    período, não "uma coleta no período". Antes o aviso dizia "1 estudante(s) com
    coleta no período em que a plataforma não mandou as questões… a conta deles vai
    só até a coleta anterior"; agora ele é "uma única coleta no período"."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0].id
    _retrato(db, eid, a, _noite(15, 8), 40, 30, sem_questoes=True)
    _retrato(db, eid, a, _noite(20), 55, 40)                 # a única do período, COM questões
    db.commit()

    cob = _setembro(db, eid)["cobertura_questoes"]
    motivos = " | ".join(
        pdf._avisos_cobertura({"elefante": {"cobertura_questoes": cob}})[0]["motivos"])

    assert cob["alunos_questoes_nao_vieram"] == 0, cob
    assert cob["status"] == "sem_intervalo" and cob["alunos_sem_intervalo"] == 1, cob
    assert "com coleta no período em que a plataforma não mandou" not in motivos, motivos
    assert "uma única coleta no período" in motivos, motivos


def test_coleta_sem_questoes_dentro_do_periodo_continua_motivo(db, escola_completa):
    """Controle da sonda F: a coleta sem as questões é DENTRO do período (05/09), e a
    válida (20/09) é a única outra. Sem a de 05/09 não há diferença a medir: aí sim
    "coleta no período em que a plataforma não mandou as questões"."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0].id
    _retrato(db, eid, a, _noite(5), 40, 30, sem_questoes=True)
    _retrato(db, eid, a, _noite(20), 55, 40)
    db.commit()

    cob = _setembro(db, eid)["cobertura_questoes"]

    assert cob["alunos_questoes_nao_vieram"] == 1, cob
    assert cob["alunos_sem_intervalo"] == 0, cob


def _motivos(cob) -> str:
    return " | ".join(
        pdf._avisos_cobertura({"elefante": {"cobertura_questoes": cob}})[0]["motivos"])


def test_coleta_do_inicio_sem_questoes_nao_vira_sem_coleta_perto_do_inicio(db, escola_completa):
    """Revisão final (a sonda E): a coleta do INÍCIO (01/09) existiu, mas veio sem as
    questões. A conta parte da coleta anterior (15/08) e inclui esse intervalo — o
    número e o status ('ampliada') estão certos. O aviso dizia "não há coleta perto do
    início: a coleta-base é de 15/08…", e havia coleta exatamente no início."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0].id
    _retrato(db, eid, a, _noite(15, 8), 40, 30)
    _retrato(db, eid, a, _noite(1), 40, 30, sem_questoes=True)  # a coleta do início
    _retrato(db, eid, a, _noite(1, 10), 55, 40)
    db.commit()

    ele = _setembro(db, eid)
    cob = ele["cobertura_questoes"]
    motivos = _motivos(cob)

    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (15, 10)
    assert cob["status"] == "ampliada" and cob["inclui_antes_do_inicio"] is True
    assert cob["alunos_inicio_sem_questoes"] == 1 and cob["alunos_ampliados"] == 0, cob
    assert cob["coleta_base_inicio_sem_questoes"].startswith("2026-08-15T03:10"), cob
    assert cob["alunos_questoes_nao_vieram"] == 0, cob
    assert "não há coleta perto do início" not in motivos, motivos
    assert ("a coleta do início veio sem as questões: a conta parte da coleta de "
            "15/08/2026 00:10, 17 dias antes de 01/09/2026, e INCLUI a atividade desse "
            "intervalo") in motivos, motivos


def test_coleta_do_inicio_sem_questoes_sem_coleta_anterior_nao_vira_sem_coleta_no_inicio(
        db, escola_completa):
    """O mesmo sem coleta anterior: a conta começa na primeira coleta com as questões
    (20/09) e o que veio de 01/09 até ela fica fora — o número e o status ('parcial')
    não mudam. O aviso dizia "sem coleta no início do período", e houve."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0].id
    _retrato(db, eid, a, _noite(1), 40, 30, sem_questoes=True)   # a coleta do início
    _retrato(db, eid, a, _noite(20), 55, 40)
    _retrato(db, eid, a, _noite(1, 10), 70, 50)
    db.commit()

    ele = _setembro(db, eid)
    cob = ele["cobertura_questoes"]
    motivos = _motivos(cob)

    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (15, 10)
    assert cob["status"] == "parcial" and cob["inicio_coberto"] is False
    assert (cob["alunos_inicio_sem_questoes_sem_base"], cob["alunos_sem_inicio"]) == (1, 0), cob
    assert cob["primeira_coleta_inicio_sem_questoes"].startswith("2026-09-20T03:10"), cob
    assert "sem coleta no início do período" not in motivos.lower(), motivos
    assert ("a coleta do início veio sem as questões: a conta começa na primeira coleta "
            "com as questões (até 20/09/2026 00:10), e o que foi feito de 01/09/2026 até "
            "ela não está na conta") in motivos, motivos


def test_coleta_do_inicio_sem_questoes_ao_lado_de_quem_nao_tem_coleta_no_inicio(
        db, escola_completa):
    """Os dois casos juntos: cada aluno numa causa só, e cada aviso com a data DELE — a
    base de 15/08 é do aluno cuja coleta do início veio sem as questões; a de 20/08, do
    que não teve coleta perto do início."""
    eid = escola_completa["escola"].id
    a, b, _c = (x.id for x in escola_completa["alunos"])
    _retrato(db, eid, a, _noite(15, 8), 40, 30)
    _retrato(db, eid, a, _noite(1), 40, 30, sem_questoes=True)
    _retrato(db, eid, a, _noite(1, 10), 55, 40)
    _retrato(db, eid, b, _noite(20, 8), 10, 5)
    _retrato(db, eid, b, _noite(1, 10), 30, 20)
    db.commit()

    cob = _setembro(db, eid)["cobertura_questoes"]
    motivos = _motivos(cob)

    assert cob["status"] == "ampliada"
    assert (cob["alunos_ampliados"], cob["alunos_inicio_sem_questoes"]) == (1, 1), cob
    assert cob["coleta_inicio"].startswith("2026-08-15T03:10")      # o intervalo medido
    assert ("não há coleta perto do início para 1 estudante(s): a coleta-base é de "
            "20/08/2026 00:10, 12 dias antes de 01/09/2026") in motivos, motivos
    assert ("a coleta do início veio sem as questões para 1 estudante(s): a conta parte "
            "da coleta de 15/08/2026 00:10, 17 dias antes de 01/09/2026, e INCLUI") in motivos
