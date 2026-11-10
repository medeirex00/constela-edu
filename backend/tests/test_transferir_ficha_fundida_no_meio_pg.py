"""Transferir de turma × fusão, em transações de verdade (PostgreSQL).

A fusão segura a trava da escola (4711) e já apagou a ficha absorvida, sem
commitar; a transferência das duas fichas chega e espera a trava. Antes, ela lia
os alunos ANTES de pedir a trava (via as duas fichas, pois o apagamento ainda não
tinha commit), esperava, e depois do commit da fusão inseria a matrícula da ficha
apagada no destino: ``ForeignKeyViolation`` (500). Agora ela pede a trava antes de
ler: depois do commit, relê, vê que a ficha não existe mais e responde 409 — nada
transferido.

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_transferir_ficha_fundida_no_meio_pg.py -m postgres

Dados fictícios.
"""
from __future__ import annotations

import threading

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Aluno, Matricula, Turma, Usuario
from app.routers import academico
from app.schemas.comum import AcaoAlunos
from app.services import alunos_fusao
from tests.test_fusao_trava_escola_pg import (_ate_esperar, _fundir_rota, cena,  # noqa: F401
                                              motor_pg, pytestmark)


def _transferir(motor, c, destino, erros, respostas):
    def _alvo():
        try:
            with Session(motor) as db:
                respostas.append(academico.acoes_em_alunos(
                    dados=AcaoAlunos(acao="transferir", aluno_ids=[c["oficial"], c["stub"]],
                                     turma_id=destino),
                    escola_id=c["escola"], usuario=db.get(Usuario, c["admin"]), db=db))
        except Exception as erro:  # noqa: BLE001 — é o que o teste mede
            erros.append(erro)

    t = threading.Thread(target=_alvo, name="TRANSFERIR")
    t.start()
    return t


def test_fusao_segurando_a_trava_a_transferencia_espera_e_responde_409(motor_pg, cena,
                                                                       monkeypatch):
    with Session(motor_pg) as db:
        destino = Turma(escola_id=cena["escola"], nome="3º Ano B", ano_escolar="3º Ano",
                        ano_letivo=2026, turno="manha")
        db.add(destino)
        db.commit()
        destino_id = destino.id
        origem_id = db.execute(select(Matricula.turma_id).where(
            Matricula.aluno_id == cena["oficial"])).scalar_one()

    entrou, soltar = threading.Event(), threading.Event()
    real = alunos_fusao.fundir_par

    def _lenta(db, escola_id, manter, remover, usuario_id):
        r = real(db, escola_id, manter, remover, usuario_id)   # apagou, sem commit
        if threading.current_thread().name == "FUSAO":
            entrou.set()
            assert soltar.wait(30)
        return r

    monkeypatch.setattr(alunos_fusao, "fundir_par", _lenta)
    erros_fusao: list[Exception] = []
    erros: list[Exception] = []
    respostas: list[dict] = []
    t_fusao = _fundir_rota(motor_pg, cena, erros_fusao)
    t_transf = None
    try:
        assert entrou.wait(30), f"a fusão nem chegou a fundir: {erros_fusao}"
        t_transf = _transferir(motor_pg, cena, destino_id, erros, respostas)
        assert _ate_esperar(motor_pg, cena["escola"]), (
            f"a transferência não esperou a fusão: {erros} {respostas}")
    finally:
        soltar.set()
        t_fusao.join(60)
        if t_transf is not None:
            t_transf.join(60)
    assert not t_fusao.is_alive() and not t_transf.is_alive()

    assert erros_fusao == [], erros_fusao
    assert respostas == [], respostas
    assert len(erros) == 1, erros
    assert isinstance(erros[0], HTTPException) and erros[0].status_code == 409, (
        f"esperava 409, veio {type(erros[0]).__name__}: {erros[0]}")
    assert "Nada foi transferido" in erros[0].detail
    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["stub"]) is None                 # a fusão valeu
        assert db.execute(select(Matricula.aluno_id, Matricula.turma_id).where(
            Matricula.aluno_id.in_([cena["oficial"], cena["stub"]]))).all() == [
            (cena["oficial"], origem_id)]                           # ninguém transferido
