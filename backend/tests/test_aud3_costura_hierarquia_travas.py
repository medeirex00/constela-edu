"""O cálculo de notas não tenta promover a trava compartilhada da escola."""
from __future__ import annotations

import inspect

from app.core import database as core_db
from app.services import scoring

def test_scoring_nao_adquire_a_trava_exclusiva_da_escola():
    fonte = inspect.getsource(scoring)
    assert "bloquear_escola_para_importacao" not in fonte
    assert "_NS_IMPORTACAO" not in fonte


def test_durante_o_recalculo_a_trava_exclusiva_da_escola_nao_e_pedida(
        db, escola_completa, monkeypatch):
    """Confere também chamadas indiretas no cálculo real, além do próprio scoring."""
    estado = {"recalculando": False, "violacoes": 0}
    trava_real = core_db.bloquear_escola_para_importacao

    def _travar(sessao, eid):
        if estado["recalculando"]:
            estado["violacoes"] += 1
        return trava_real(sessao, eid)

    import sys
    for nome, modulo in list(sys.modules.items()):
        if nome.startswith("app.") and getattr(modulo, "bloquear_escola_para_importacao",
                                                None) is trava_real:
            monkeypatch.setattr(modulo, "bloquear_escola_para_importacao", _travar)

    trava_do_recalculo = core_db.bloquear_escola_para_recalculo

    def _recalculo(sessao, eid):
        estado["recalculando"] = True
        return trava_do_recalculo(sessao, eid)

    monkeypatch.setattr(scoring, "bloquear_escola_para_recalculo", _recalculo, raising=False)
    monkeypatch.setattr(core_db, "bloquear_escola_para_recalculo", _recalculo)
    scoring.recalcular_escola(db, escola_completa["escola"].id)
    estado["recalculando"] = False
    assert estado["violacoes"] == 0
