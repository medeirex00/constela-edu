"""G_AJUSTE-1 (Análise): a Análise Educacional lê a série do Matific SEM o ajuste manual
que uma coleta posterior do mesmo ano já desmentiu — a regra das premiações e do
Relatório por Período (``matific_destaque.sem_ajustes_superados``).

``analise.plataformas._partes_retratos`` (a consulta dos retratos que a regra do Matific
lê: o último antes do início e o primeiro e o último dentro da janela) não sabia o que era
número digitado. Com uma coleta em 08/06, um AJUSTE manual para baixo em 10/06 e a coleta
seguinte em 11/06, o "último antes do início" do dia 11 era o ajuste: a Análise atribuía
ao período o degrau entre o ajuste e a coleta (55 atividades em vez de 5) e divergia das
premiações. O ajuste que nenhuma coleta desmentiu continua valendo. Dados fictícios.
"""
from datetime import datetime

from app.models import SnapshotMatific
from app.services import matific_destaque
from app.services.analise import plataformas as ap
from tests.test_aud2_motor_ajuste_manual_matific import (
    AJUSTE, COLETA_A, COLETA_B, _ajuste_manual, _coleta)

INICIO = datetime(2026, 6, 11)
FIM = datetime(2026, 6, 11, 23, 59, 59, 999999)


def _retratos(db, escola_id, aluno_id):
    lidos = ap._retratos_essenciais(db, SnapshotMatific, escola_id, ap._CAMPOS_MATIFIC,
                                    INICIO, FIM)
    return [(r.data_referencia, r.atividades) for r in lidos.get(aluno_id, [])]


def test_ajuste_desmentido_nao_e_base_do_periodo(db, escola_completa):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _coleta(db, escola.id, COLETA_A, {ana.id: (100, 400)})
    _ajuste_manual(db, escola.id, ana.id, AJUSTE, 50, 200)          # para baixo
    _coleta(db, escola.id, COLETA_B, {ana.id: (105, 420)})

    lidos = _retratos(db, escola.id, ana.id)
    assert lidos == [(COLETA_A, 100), (COLETA_B, 105)], lidos       # antes: o ajuste (50)

    serie = ap._retratos_essenciais(db, SnapshotMatific, escola.id, ap._CAMPOS_MATIFIC,
                                    INICIO, FIM)[ana.id]
    ganho = matific_destaque.ganho_no_periodo(serie, INICIO, FIM, 2026)
    assert (ganho.atividades, ganho.estrelas) == (5, 20)


def test_ajuste_sem_coleta_depois_continua_valendo(db, escola_completa):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _coleta(db, escola.id, COLETA_A, {ana.id: (100, 400)})
    _ajuste_manual(db, escola.id, ana.id, AJUSTE, 50, 200)
    assert _retratos(db, escola.id, ana.id) == [(AJUSTE, 50)]


def test_coleta_de_outro_ano_nao_desmente_o_ajuste(db, escola_completa):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _coleta(db, escola.id, COLETA_A, {ana.id: (100, 400)})
    _ajuste_manual(db, escola.id, ana.id, AJUSTE, 50, 200)
    _coleta(db, escola.id, datetime(2027, 1, 5, 12, 0), {ana.id: (3, 9)})
    assert _retratos(db, escola.id, ana.id) == [(AJUSTE, 50)]
