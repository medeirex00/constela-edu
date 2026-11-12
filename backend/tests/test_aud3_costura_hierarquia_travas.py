"""Hierarquia das travas da escola (costura da fase D, "hierarquia-4711-4713").

A regra documentada em ``core/database.bloquear_escola_para_recalculo`` é "nunca pedir o
recálculo (4713) segurando a trava de importação (4711)". Ela tem UMA exceção, de
propósito: ``importacoes.resolver_revisao`` pega a 4711 e recalcula dentro da mesma
transação (``recalcular_escola(commit=False)``), para a resolução, os dados aplicados e as
notas caírem num commit só.

Deadlock exige ciclo. A exceção é segura enquanto NENHUM caminho pedir a 4711 segurando a
4713 — a regra inversa, absoluta. Estes testes a guardam (a do resolver, sobre a hierarquia
em si, fica com ``tests/test_recalculo_concorrencia.py``):

* o recálculo nunca pede a trava de importação (nem de dentro do scoring);
* durante um recálculo, com qualquer caminho, a 4711 nunca é pedida;
* o resolver é o único chamador de ``recalcular_escola(commit=False)`` que ainda segura a
  4711 — o docstring registra a exceção, e um novo aninhamento tem de ser documentado ali.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from app.core import database as core_db
from app.services import scoring

APP = Path(__file__).resolve().parents[1] / "app"


def test_recalculo_nunca_pede_a_trava_de_importacao():
    fonte = inspect.getsource(scoring)
    assert "bloquear_escola_para_importacao" not in fonte
    assert "_NS_IMPORTACAO" not in fonte


def test_durante_o_recalculo_a_trava_de_importacao_nunca_e_pedida(
        db, escola_completa, monkeypatch):
    """Recálculo real da escola com a trava de importação vigiada em todos os módulos
    que a importam."""
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


def test_o_unico_recalculo_dentro_da_trava_de_importacao_e_o_do_resolver_e_esta_documentado():
    """Toda função de rota que pega a 4711 e chama ``recalcular_escola(commit=False)`` sem
    commit no meio é uma exceção à hierarquia; hoje só o resolver, registrado no
    docstring da trava do recálculo."""
    excecoes = []
    for arquivo in sorted((APP / "routers").glob("*.py")):
        fonte = arquivo.read_text(encoding="utf-8")
        for bloco in re.split(r"\n(?=def |async def |@router)", fonte):
            trava = bloco.find("bloquear_escola_para_importacao(db")
            recalc = bloco.find("recalcular_escola(db, escola_id, commit=False)")
            if trava == -1 or recalc == -1 or recalc < trava:
                continue
            if "db.commit()" in bloco[trava:recalc]:
                continue
            nome = re.search(r"def (\w+)\(", bloco)
            excecoes.append(f"{arquivo.stem}.{nome.group(1) if nome else '?'}")
    assert excecoes == ["importacoes.resolver_revisao"]
    doc = core_db.bloquear_escola_para_recalculo.__doc__ or ""
    assert "resolver_revisao" in doc
    assert "nenhum caminho pede a 4711 segurando a 4713" in " ".join(doc.split())
