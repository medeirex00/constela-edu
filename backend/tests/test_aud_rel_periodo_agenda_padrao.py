"""Questões do período × a agenda diária PADRÃO da sincronização.

A regra "a coleta da madrugada mede o dia ANTERIOR" (``relatorios_periodo``) aceitava
como medida de uma borda só a coleta a até 1 h dela — escrita para a agenda que rodava
à 0h de Brasília. Depois da correção de fuso (``sync/fuso.py``), a agenda "03:00" que a
sincronização cria sozinha (``prerequisitos.HORA_AGENDA_AUTOMATICA``) roda às 03:00 de
BRASÍLIA: a coleta de 01/09 03:10 virava "depois do início" e a de 01/10 03:10 "depois
do fim", e setembro saía com o dia trocado (31/08 dentro, 30/09 fora) — no Relatório
por Período e na Análise das plataformas. Achado SYNC-2. Dados INVENTADOS; as coletas
são datadas pelo cálculo REAL da agenda padrão.
"""
from datetime import date, datetime, timedelta

from app.models.sincronizacao import SincronizacaoConfig
from app.services import relatorios_periodo as rp
from app.services.analise import plataformas as svc
from app.sync import prerequisitos, service
from tests.test_analise_base import nova_escola, nova_rede, retrato_elefante, turma_com_alunos
from tests.test_relatorios_periodo import _snap_matific
from tests.test_relatorios_periodo_cobertura import _gerar, _ids, _snap_elefante

HOJE = date(2026, 10, 20)


def _coleta_da_agenda_padrao(dia: date) -> datetime:
    """Instante (UTC sem fuso, como a sync grava) em que a coleta da agenda padrão
    termina no dia ``dia``: a execução calculada pela agenda + 10 min."""
    cfg = SincronizacaoConfig(escola_id=1, plataforma="elefante", ativo=True,
                              cadencia="diaria", hora_local=prerequisitos.HORA_AGENDA_AUTOMATICA)
    vespera_meio_dia_utc = datetime(dia.year, dia.month, dia.day, 15, 0) - timedelta(days=1)
    return service.calcular_proxima(cfg, vespera_meio_dia_utc) + timedelta(minutes=10)


# Os números do teste da agenda das 00:10 (test_setembro_completo_com_a_agenda_noturna).
_PONTOS = [(date(2026, 8, 31), 100, 80), (date(2026, 9, 1), 130, 100),
           (date(2026, 9, 30), 400, 300), (date(2026, 10, 1), 470, 350)]


def test_a_agenda_padrao_roda_de_madrugada_em_brasilia():
    """Premissa do cenário: a coleta padrão é às 03:10 de Brasília (06:10 UTC)."""
    assert _coleta_da_agenda_padrao(date(2026, 9, 1)) == datetime(2026, 9, 1, 6, 10)


def test_setembro_com_a_agenda_padrao_mede_setembro(db, escola_completa):
    eid, (a, *_) = _ids(escola_completa)
    for dia, tent, ok in _PONTOS:
        _snap_elefante(db, eid, a, _coleta_da_agenda_padrao(dia), tent, ok)
    ele = _gerar(db, eid)["elefante"]
    cob = ele["cobertura_questoes"]
    # A coleta de 01/09 mede o fim de 31/08 (= o início de setembro) e a de 01/10 o fim
    # de 30/09: setembro = 470 − 130, não 400 − 100 (31/08..29/09).
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (340, 250), cob
    assert cob["status"] == "completa", cob
    assert cob["coleta_inicio"].startswith("2026-09-01T06:10")
    assert cob["coleta_fim"].startswith("2026-10-01T06:10")


def test_coleta_de_tarde_no_dia_1o_nao_mede_o_inicio(db, escola_completa):
    """A janela nova é a da coleta da MADRUGADA: uma coleta à tarde do dia 1º continua
    sendo "depois do início" (o que veio antes dela não está na conta)."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, datetime(2026, 9, 1, 18, 0), 130, 100)     # 15h de Brasília
    _snap_elefante(db, eid, a, datetime(2026, 10, 1, 2, 30), 470, 350)    # 30/09 23h30
    ele = _gerar(db, eid)["elefante"]
    cob = ele["cobertura_questoes"]
    assert cob["status"] == "parcial" and cob["alunos_sem_inicio"] == 1, cob
    assert cob["fim_coberto"] is True, cob
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (340, 250)


def test_analise_das_plataformas_mede_o_mesmo_setembro(db):
    rede = nova_rede(db, nome="Rede Fictícia Agenda", codigo="3599951", codmun="9951")
    e = nova_escola(db, rede, "EMEF Fictícia Agenda", "35999511")
    for aluno in turma_com_alunos(db, e, "3º Ano", 5):
        for dia, tent, ok in _PONTOS:
            retrato_elefante(db, e, aluno, _coleta_da_agenda_padrao(dia),
                             tentativas=tent, acertos=ok)
    db.commit()
    ini, fim = date(2026, 9, 1), date(2026, 9, 30)
    dados = svc.plataformas_da_rede(db, rede, preset="personalizado", inicio=ini, fim=fim,
                                    hoje=HOJE)
    el = next(x for x in dados["escolas"] if x["escola_id"] == e.id)["elefante"]
    assert el["taxa_acerto_pct"] == round(100 * 250 / 340, 1), el
    assert el["janela_questoes"]["inicio"] == "2026-09-01T03:10:00-03:00", el
    assert el["janela_questoes"]["fim"] == "2026-10-01T03:10:00-03:00", el


def test_matific_com_a_primeira_coleta_da_agenda_no_dia_1o_nao_e_sem_inicio(db, escola_completa):
    """A declaração do Matific usa a mesma régua: base oficial na coleta da madrugada do
    dia 1º é a medida do início, não "sem coleta no início do período"."""
    eid, (a, *_) = _ids(escola_completa)
    # Sem coleta antes do período: a base oficial é a primeira dentro dele, a de 01/09.
    _snap_matific(db, eid, a, _coleta_da_agenda_padrao(date(2026, 9, 1)), 40, 20)
    _snap_matific(db, eid, a, _coleta_da_agenda_padrao(date(2026, 9, 29)), 55, 26)
    db.commit()
    r = rp.gerar(db, eid, preset="mes_anterior", plataformas=("matific",), hoje=HOJE)
    assert r["matific"]["atividades"] == 15
    cob = r["matific"]["cobertura"]
    assert cob["alunos_medidos"] == 1, cob
    assert cob["alunos_sem_inicio"] == 0 and cob["inicio_coberto"] is True, cob
