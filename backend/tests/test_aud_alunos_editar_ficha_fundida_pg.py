"""“Editar dados” × fusão, em transações de verdade (PostgreSQL).

A fusão segura a trava da escola (4711) e já apagou a ficha absorvida, sem
commitar; a edição dessa ficha chega. Antes ela não pedia a trava: lia a ficha (o
apagamento ainda sem commit), parava na trava de LINHA da fusão e, quando a fusão
commitava, o UPDATE batia em 0 linhas — ``StaleDataError``, 500. Agora ela ESPERA a
trava da escola, lê depois do commit da fusão e responde 404: a ficha não existe
mais, e nada foi gravado.

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud_alunos_editar_ficha_fundida_pg.py -m postgres

Achado ALUNOS-5 da auditoria. Dados fictícios.
"""
from __future__ import annotations

import threading

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Aluno, Usuario
from app.routers import academico
from app.schemas.comum import AlunoUpdate
from app.services import alunos_fusao
from tests.test_fusao_trava_escola_pg import (_ate_esperar, _fundir_rota, cena,  # noqa: F401
                                              motor_pg, pytestmark)


def _editar(motor, c, erros, respostas):
    def _alvo():
        try:
            with Session(motor) as db:
                respostas.append(academico.atualizar_aluno(
                    aluno_id=c["stub"], dados=AlunoUpdate(numero_chamada=12),
                    escola_id=c["escola"], usuario=db.get(Usuario, c["admin"]), db=db))
        except Exception as erro:  # noqa: BLE001 — é o que o teste mede
            erros.append(erro)

    t = threading.Thread(target=_alvo, name="EDICAO")
    t.start()
    return t


def test_fusao_segurando_a_trava_a_edicao_espera_e_responde_404(motor_pg, cena,
                                                                monkeypatch):
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
    respostas: list = []
    t_fusao = _fundir_rota(motor_pg, cena, erros_fusao)
    t_edicao = None
    try:
        assert entrou.wait(30), f"a fusão nem chegou a fundir: {erros_fusao}"
        t_edicao = _editar(motor_pg, cena, erros, respostas)
        esperou = _ate_esperar(motor_pg, cena["escola"])
    finally:
        soltar.set()
        t_fusao.join(60)
        if t_edicao is not None:
            t_edicao.join(60)
    assert not t_fusao.is_alive() and not t_edicao.is_alive()

    assert erros_fusao == [], erros_fusao
    assert esperou, f"a edição não esperou a trava da fusão: {erros} {respostas}"
    assert respostas == [], respostas
    assert len(erros) == 1, erros
    assert isinstance(erros[0], HTTPException) and erros[0].status_code == 404, (
        f"esperava 404, veio {type(erros[0]).__name__}: {erros[0]}")
    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["stub"]) is None                    # a fusão valeu
        assert db.get(Aluno, cena["oficial"]).numero_chamada is None  # nada gravado
