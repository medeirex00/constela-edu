"""G_AJUSTE-1 (sync): a trava contra queda do Matific compara a coleta com o último retrato
COLETADO — não com o ajuste manual.

``orchestrator.reter_quedas_matific`` usava como base o retrato mais recente do ano,
qualquer que fosse a origem. Depois de um ajuste manual PARA CIMA (o Admin Global digita
100 atividades onde a plataforma diz 60), toda coleta seguinte com número menor que o
digitado era retida como "queda" e não era gravada: o número digitado ficava como estado
atual até a plataforma passar dele, e a coleta nunca chegava a desmenti-lo (a série já
ignora o ajuste que uma coleta posterior desmente — ``matific_destaque.sem_ajustes_superados``
—, mas a coleta nem era gravada). A queda real (abaixo do último COLETADO) continua
retida. Dados fictícios.
"""
from datetime import datetime

from app.models import SnapshotMatific
from app.models.plataformas import Importacao
from app.services.evolucao import IMPORTACAO_AJUSTE_MANUAL
from tests.test_sync_matific_queda import (  # noqa: F401  (fixture autouse do relógio)
    _aplicar, _atual, _base, _placar, _relogio_em_outubro_de_2026)


def _ajuste_manual(db, escola, aluno, *, estrelas, atividades,
                   quando=datetime(2026, 10, 5, 9, 0)):
    imp = Importacao(escola_id=escola.id, plataforma="matific",
                     tipo=IMPORTACAO_AJUSTE_MANUAL, status="concluida")
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=quando, atividades=atividades,
                           estrelas=estrelas, pontuacao_media=3.0))
    db.commit()


def test_coleta_abaixo_do_ajuste_para_cima_mas_acima_da_coleta_entra(
        db, escola_completa, monkeypatch):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _base(db, escola, ana, estrelas=150, atividades=50)             # coletado em 01/10
    _ajuste_manual(db, escola, ana, estrelas=300, atividades=100)   # digitado em 05/10

    res = _aplicar(db, escola, _placar(ana, "uuid-ana", estrelas=180, atividades=60),
                   monkeypatch)

    assert res["retidos_queda"] == 0, "a coleta foi retida pelo número digitado"
    atual = _atual(db, escola, ana)
    assert (atual.atividades, atual.estrelas) == (60, 180)


def test_coleta_abaixo_do_ultimo_coletado_continua_retida(db, escola_completa, monkeypatch):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _base(db, escola, ana, estrelas=150, atividades=50)
    _ajuste_manual(db, escola, ana, estrelas=300, atividades=100)

    res = _aplicar(db, escola, _placar(ana, "uuid-ana", estrelas=140, atividades=45),
                   monkeypatch)

    assert res["retidos_queda"] == 1
    assert _atual(db, escola, ana).atividades == 100     # nada gravado


def test_so_ajuste_manual_no_ano_nao_e_base(db, escola_completa, monkeypatch):
    """Sem retrato coletado no ano, o ajuste sozinho não segura a coleta."""
    from app.models import IdentidadeExterna
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=ana.id, plataforma="matific",
                             id_externo="uuid-ana"))
    db.commit()
    _ajuste_manual(db, escola, ana, estrelas=300, atividades=100)
    res = _aplicar(db, escola, _placar(ana, "uuid-ana", estrelas=90, atividades=30),
                   monkeypatch)
    assert res["retidos_queda"] == 0
    assert _atual(db, escola, ana).atividades == 30
