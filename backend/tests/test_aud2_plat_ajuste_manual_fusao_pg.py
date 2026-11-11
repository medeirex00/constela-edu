"""Ajuste manual (Matific e Elefante) × fusão em andamento — só o PostgreSQL prova.

A fusão segura a trava da escola (4711) e já apagou a ficha absorvida, sem
commitar. O ajuste manual da MESMA ficha chega. Antes ele não pedia a trava: lia
a ficha (o apagamento ainda sem commit), gravava o retrato manual e respondia
"salvo"; quando a fusão comitava, o ``ON DELETE CASCADE`` levava o retrato junto,
a Importacao 'manual' ficava sem retrato e a auditoria apontava para uma ficha que
não existe mais — sem ninguém ser avisado (G_AJUSTE-6).

Agora as três rotas de ajuste manual (``PUT /matific/{aluno}``,
``PUT /elefante/{aluno}`` e ``PUT /elefante/{aluno}/niveis``) ESPERAM a trava,
releem a ficha depois do commit da fusão e respondem 404: nada é gravado.

E na ordem inversa (o ajuste pega a trava primeiro), a fusão espera, o retrato é
gravado na ficha absorvida e a fusão o leva para a ficha que fica — nada some.

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud2_plat_ajuste_manual_fusao_pg.py -m postgres

Dados fictícios.
"""
from __future__ import annotations

import threading

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (Aluno, Importacao, LogAuditoria, SnapshotElefante, SnapshotMatific,
                        Usuario)
from app.routers import plataformas
from app.schemas import ElefanteEdicao, MatificEdicao, NiveisLeituraEdicao
from app.services import alunos_fusao
from tests.test_fusao_trava_escola_pg import (_ate_esperar, _fundir_rota, cena,  # noqa: F401
                                              motor_pg, pytestmark)

ACAO_DA_ROTA = {"matific": "matific.editado", "elefante": "elefante.editado",
                "elefante_niveis": "elefante.niveis_informados"}


def _admin_global(motor, escola_id: int) -> int:
    """Quem pode ajustar mesmo com dado da plataforma (a cena tem uma importação
    'seed' do Matific): a corrida medida aqui é a da trava, não a da governança."""
    with Session(motor) as db:
        usuario = Usuario(escola_id=escola_id, nome="Admin Global PG",
                          email=f"global-ajuste-{escola_id}@teste.local",
                          senha_hash="x", cargo="admin", is_global=True)
        db.add(usuario)
        db.commit()
        return usuario.id


def _ajustar(rota: str, db: Session, escola_id: int, aluno_id: int, usuario: Usuario):
    if rota == "matific":
        return plataformas.editar_matific(
            aluno_id=aluno_id,
            dados=MatificEdicao(atividades=10, estrelas=30, motivo="ajuste de teste"),
            escola_id=escola_id, usuario=usuario, db=db)
    if rota == "elefante":
        return plataformas.editar_elefante(
            aluno_id=aluno_id,
            dados=ElefanteEdicao(tempo_leitura_min=12, questoes_tentativas=2,
                                 questoes_acertos=1, livros_por_nivel={"AA": 1},
                                 motivo="ajuste de teste"),
            escola_id=escola_id, usuario=usuario, db=db)
    return plataformas.informar_niveis_leitura(
        aluno_id=aluno_id,
        dados=NiveisLeituraEdicao(faixas={"nivel": 2}, motivo="ajuste de teste"),
        escola_id=escola_id, usuario=usuario, db=db)


def _disparar_ajuste(motor, cena_, rota, usuario_id, erros, respostas):
    def _alvo():
        try:
            with Session(motor) as db:
                respostas.append(_ajustar(rota, db, cena_["escola"], cena_["stub"],
                                          db.get(Usuario, usuario_id)))
        except Exception as erro:  # noqa: BLE001 — é o que o teste mede
            erros.append(erro)

    t = threading.Thread(target=_alvo, name="AJUSTE")
    t.start()
    return t


@pytest.mark.parametrize("rota", list(ACAO_DA_ROTA))
def test_fusao_segurando_a_trava_o_ajuste_espera_e_responde_404(motor_pg, cena, monkeypatch,
                                                                rota):
    entrou, soltar = threading.Event(), threading.Event()
    real = alunos_fusao.fundir_par

    def _lenta(db, escola_id, manter, remover, usuario_id):
        r = real(db, escola_id, manter, remover, usuario_id)   # apagou o stub, sem commit
        if threading.current_thread().name == "FUSAO":
            entrou.set()
            assert soltar.wait(30)
        return r

    monkeypatch.setattr(alunos_fusao, "fundir_par", _lenta)
    monkeypatch.setattr(plataformas.scoring, "recalcular_escola", lambda *a, **k: 0)
    global_id = _admin_global(motor_pg, cena["escola"])
    erros_fusao: list[Exception] = []
    erros: list[Exception] = []
    respostas: list = []

    t_fusao = _fundir_rota(motor_pg, cena, erros_fusao)
    t_ajuste = None
    try:
        assert entrou.wait(30), f"a fusão nem chegou a fundir: {erros_fusao}"
        t_ajuste = _disparar_ajuste(motor_pg, cena, rota, global_id, erros, respostas)
        assert _ate_esperar(motor_pg, cena["escola"]), (
            f"{rota}: o ajuste não esperou a trava da fusão: {erros} {respostas}")
    finally:
        soltar.set()
        t_fusao.join(60)
        if t_ajuste is not None:
            t_ajuste.join(60)
    assert not t_fusao.is_alive() and not t_ajuste.is_alive()

    assert erros_fusao == [], erros_fusao
    assert respostas == [], f"{rota}: respondeu 'salvo' numa ficha que a fusão apagou"
    assert len(erros) == 1, erros
    assert isinstance(erros[0], HTTPException) and erros[0].status_code == 404, (
        f"esperava 404, veio {type(erros[0]).__name__}: {erros[0]}")
    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["stub"]) is None                 # a fusão valeu
        manuais = db.execute(select(Importacao.id).where(
            Importacao.escola_id == cena["escola"], Importacao.tipo == "manual")).all()
        logs = db.execute(select(LogAuditoria.id).where(
            LogAuditoria.escola_id == cena["escola"],
            LogAuditoria.acao == ACAO_DA_ROTA[rota])).all()
    assert manuais == [] and logs == [], "nada pode ficar gravado pela metade"


@pytest.mark.parametrize("rota", ["matific", "elefante"])
def test_ajuste_segurando_a_trava_a_fusao_espera_e_leva_o_retrato(motor_pg, cena, monkeypatch,
                                                                  rota):
    """Ordem inversa: o ajuste grava primeiro; a fusão espera e MOVE o retrato manual
    para a ficha que fica (nada some pela cascata)."""
    from app.core.database import bloquear_escola_para_importacao

    entrou, soltar = threading.Event(), threading.Event()
    real = plataformas.registrar

    def _lento(db, acao, *a, **k):
        r = real(db, acao, *a, **k)
        if threading.current_thread().name == "AJUSTE" and acao == ACAO_DA_ROTA[rota]:
            entrou.set()                     # retrato gravado, trava segura, sem commit
            assert soltar.wait(30)
        return r

    monkeypatch.setattr(plataformas, "registrar", _lento)
    monkeypatch.setattr(plataformas.scoring, "recalcular_escola", lambda *a, **k: 0)
    global_id = _admin_global(motor_pg, cena["escola"])
    erros_fusao: list[Exception] = []
    erros: list[Exception] = []
    respostas: list = []
    assert bloquear_escola_para_importacao is not None

    t_ajuste = _disparar_ajuste(motor_pg, cena, rota, global_id, erros, respostas)
    t_fusao = None
    try:
        assert entrou.wait(30), f"o ajuste nem chegou a gravar: {erros}"
        t_fusao = _fundir_rota(motor_pg, cena, erros_fusao)
        assert _ate_esperar(motor_pg, cena["escola"]), (
            f"{rota}: a fusão não esperou a trava do ajuste: {erros_fusao}")
    finally:
        soltar.set()
        t_ajuste.join(60)
        if t_fusao is not None:
            t_fusao.join(60)
    assert erros == [] and len(respostas) == 1, (erros, respostas)
    assert erros_fusao == [], erros_fusao
    modelo = SnapshotMatific if rota == "matific" else SnapshotElefante
    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["stub"]) is None
        manual = db.execute(select(Importacao.id).where(
            Importacao.escola_id == cena["escola"], Importacao.tipo == "manual")).scalar_one()
        retratos = db.execute(select(modelo.aluno_id).where(
            modelo.importacao_id == manual)).scalars().all()
    assert retratos == [cena["oficial"]], "o retrato manual sumiu na fusão"
