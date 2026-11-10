"""Arquivar, excluir e marcar como transferido × fusão, em transações de verdade
(PostgreSQL).

A fusão segura a trava da escola (4711) e já apagou a ficha absorvida, sem
commitar; a ação em massa sobre as duas fichas chega. Antes ela não pedia a trava:
lia as duas fichas (o apagamento ainda sem commit) e ia gravar o status por fora da
fusão. Agora ela ESPERA a trava, relê depois do commit da fusão, vê que a ficha não
existe mais e responde 409 — ninguém muda de status.

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_acoes_alunos_ficha_fundida_no_meio_pg.py -m postgres

Dados fictícios.
"""
from __future__ import annotations

import threading

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Aluno, Usuario
from app.routers import academico
from app.schemas.comum import AcaoAlunos
from app.services import alunos_fusao
from tests.test_fusao_trava_escola_pg import (_ate_esperar, _fundir_rota, cena,  # noqa: F401
                                              motor_pg, pytestmark)

FEITO = {"arquivar": "Nada foi arquivado", "excluir": "Nada foi excluído",
         "marcar_transferido": "Nada foi marcado como transferido"}


def _acao(motor, c, acao, erros, respostas):
    def _alvo():
        try:
            with Session(motor) as db:
                respostas.append(academico.acoes_em_alunos(
                    dados=AcaoAlunos(acao=acao, aluno_ids=[c["oficial"], c["stub"]]),
                    escola_id=c["escola"], usuario=db.get(Usuario, c["admin"]), db=db))
        except Exception as erro:  # noqa: BLE001 — é o que o teste mede
            erros.append(erro)

    t = threading.Thread(target=_alvo, name="ACAO")
    t.start()
    return t


@pytest.mark.parametrize("acao", list(FEITO))
def test_fusao_segurando_a_trava_a_acao_espera_e_responde_409(motor_pg, cena, monkeypatch,
                                                              acao):
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
    t_acao = None
    try:
        assert entrou.wait(30), f"a fusão nem chegou a fundir: {erros_fusao}"
        t_acao = _acao(motor_pg, cena, acao, erros, respostas)
        assert _ate_esperar(motor_pg, cena["escola"]), (
            f"{acao}: a ação não esperou a trava da fusão: {erros} {respostas}")
    finally:
        soltar.set()
        t_fusao.join(60)
        if t_acao is not None:
            t_acao.join(60)
    assert not t_fusao.is_alive() and not t_acao.is_alive()

    assert erros_fusao == [], erros_fusao
    assert respostas == [], respostas
    assert len(erros) == 1, erros
    assert isinstance(erros[0], HTTPException) and erros[0].status_code == 409, (
        f"esperava 409, veio {type(erros[0]).__name__}: {erros[0]}")
    assert FEITO[acao] in erros[0].detail
    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["stub"]) is None                 # a fusão valeu
        assert db.get(Aluno, cena["oficial"]).status == "ativo"    # ninguém mudou
