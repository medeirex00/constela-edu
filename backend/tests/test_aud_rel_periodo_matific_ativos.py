"""Relatório por Período: retrato do Matific sem ganho não é "com atividade".

Toda coleta grava retrato de todo aluno com conta. Se ter retrato contasse como
atividade, o total "Com atividade no período" (tela, coluna por turma, marca por
aluno e PDF) empataria com a escola inteira — a mesma regra que o módulo já aplica
ao Elefante (``test_ter_retrato_na_janela_nao_e_ter_atividade``). Achado RELATORIOS-1.
"""
from datetime import date, datetime

from app.services import relatorios_periodo as rp
from app.services import relatorios_periodo_pdf as rpp
from app.services import visao_geral as vg
from tests.test_relatorios_periodo import _snap_matific

HOJE = date(2026, 10, 5)


def _parado_e_ativo(db, escola_completa):
    escola = escola_completa["escola"]
    parado, ativo, _sem = escola_completa["alunos"]
    # Os dois têm retrato no período (a coleta grava todo mundo); só um evoluiu.
    _snap_matific(db, escola.id, parado.id, datetime(2026, 8, 31, 12, 0), 10, 5)
    _snap_matific(db, escola.id, parado.id, datetime(2026, 9, 29, 12, 0), 10, 5)
    _snap_matific(db, escola.id, ativo.id, datetime(2026, 8, 31, 12, 0), 10, 5)
    _snap_matific(db, escola.id, ativo.id, datetime(2026, 9, 29, 12, 0), 18, 9)
    db.commit()
    return escola, parado, ativo


def test_retrato_do_matific_sem_ganho_nao_e_atividade(db, escola_completa):
    escola, parado, ativo = _parado_e_ativo(db, escola_completa)
    for plats in (("elefante", "matific"), ("matific",)):
        r = rp.gerar(db, escola.id, preset="mes_anterior", plataformas=plats,
                     hoje=HOJE)
        assert r["matific"]["alunos_com_atividade"] == 1
        assert r["alunos"]["com_atividade"] == 1, (
            f"{plats}: o parado (sem ganho) virou 'com atividade'")
        assert r["alunos"]["sem_atividade"] == len(escola_completa["alunos"]) - 1
        turma = r["por_turma"][0]
        assert turma["com_atividade"] == 1
        marcado = {x["aluno_id"]: x for x in r["por_aluno"]}
        assert marcado[parado.id]["sem_atividade"] is True
        assert marcado[ativo.id]["sem_atividade"] is False
        # O 0 MEDIDO continua na tabela por aluno (não é "sem retrato").
        assert marcado[parado.id]["matific"]["atividades"] == 0
        assert marcado[ativo.id]["matific"]["atividades"] == 8
        resumo = {rot: val for rot, val, _ in rpp.linhas_resumo(r)}
        assert resumo["Com atividade no período"] == resumo["Estudantes com ganho"]


def test_visao_geral_e_relatorio_concordam_sobre_quem_esta_ativo(db, escola_completa):
    escola, _parado, _ativo = _parado_e_ativo(db, escola_completa)
    tela = vg.visao_geral(db, escola, preset="mes_anterior",
                          modulos={"leitura", "matematica"}, turma_ids=None, hoje=HOJE)
    rel = rp.gerar(db, escola.id, preset="mes_anterior",
                   plataformas=("elefante", "matific"), hoje=HOJE)
    assert tela["alunos"]["ativos"] == rel["alunos"]["com_atividade"] == 1
