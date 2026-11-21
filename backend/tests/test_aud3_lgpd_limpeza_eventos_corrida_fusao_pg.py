"""Limpeza do passivo de eventos × "Fundir duplicatas" no meio — só o PostgreSQL prova
(REG_DADOS-1; o SQLite, sem trava, está em ``test_aud3_lgpd_limpeza_eventos_corrida_fusao``).

Duas transações de verdade: a limpeza (``deduplicar_eventos_por_conteudo``, aplicar)
leu o plano e vai apagar; a gestão funde M ← R pela rota (que toma a trava da escola).
Antes, a fusão passava, movia para M a cópia que o plano velho mandava apagar e apagava
as outras: o DELETE da limpeza levava a única cópia da leitura. Agora a limpeza segura
a trava da escola desde ANTES de ler: a fusão espera, e depois funde o que a limpeza
deixou — M fica com uma cópia.

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud3_lgpd_limpeza_eventos_corrida_fusao_pg.py -m postgres

Dados fictícios.
"""
from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EventoAluno, LogAuditoria
from app.services import eventos as svc_eventos
from app.services.eventos import chave_evento, deduplicar_eventos_por_conteudo
from tests.test_fusao_trava_escola_pg import (  # noqa: F401
    _esperando_a_trava,
    _fundir_rota,
    cena,
    motor_pg,
    pytestmark,
)

TITULO = "Livro Ficticio da Corrida PG"
QUANDO = datetime(2026, 3, 10, 10, 0)
Z = 990001                                    # ficha absorvida há tempos (apagada)


def _evento(escola_id, aluno_id, origem):
    return EventoAluno(escola_id=escola_id, aluno_id=aluno_id, plataforma="elefante",
                       tipo_evento="leitura", ocorrido_em=QUANDO, conteudo_titulo=TITULO,
                       dados={}, chave_natural=chave_evento("elefante", "leitura", origem,
                                                            TITULO, QUANDO))


def _copias(motor, aluno_id):
    with Session(motor) as db:
        return list(db.execute(select(EventoAluno.id).where(
            EventoAluno.aluno_id == aluno_id, EventoAluno.conteudo_titulo == TITULO)
            .order_by(EventoAluno.id)).scalars())


def test_fusao_no_meio_da_limpeza_espera_e_a_leitura_fica(motor_pg, cena, monkeypatch):
    escola, m_id, r_id = cena["escola"], cena["oficial"], cena["stub"]
    with Session(motor_pg) as db:
        # R absorveu Z numa fusão antiga: a mesma linha duas vezes em R (r1 nativa,
        # r2 com a chave de Z). M tem a mesma linha, nativa.
        db.add(LogAuditoria(escola_id=escola, acao="aluno.fundido", entidade="aluno",
                            entidade_id=r_id,
                            detalhes={"mantido": {"id": r_id}, "removido": {"id": Z}}))
        db.add_all([_evento(escola, m_id, m_id), _evento(escola, r_id, r_id),
                     _evento(escola, r_id, Z)])
        db.commit()

    erros: list = []
    estado: dict = {}
    delete_real = svc_eventos.delete

    def _delete_com_fusao_no_meio(*args, **kwargs):
        # O plano já foi lido; a gestão clica em "Fundir" agora, noutra conexão.
        if "fusao" not in estado:
            estado["fusao"] = _fundir_rota(motor_pg, cena, erros)
            limite = time.monotonic() + 15
            while time.monotonic() < limite and estado["fusao"].is_alive():
                if _esperando_a_trava(motor_pg, escola):
                    estado["esperou"] = True
                    break
                time.sleep(0.05)
            estado["terminou_antes"] = not estado["fusao"].is_alive()
        return delete_real(*args, **kwargs)

    monkeypatch.setattr(svc_eventos, "delete", _delete_com_fusao_no_meio)
    with Session(motor_pg) as db:
        resultado = deduplicar_eventos_por_conteudo(db, escola_id=escola, aplicar=True)
        db.commit()
    estado["fusao"].join(30)
    assert not estado["fusao"].is_alive() and not erros, erros

    copias = _copias(motor_pg, m_id)
    assert len(copias) == 1, f"a leitura sumiu da linha do tempo de M: {copias}"
    assert estado.get("esperou") and not estado["terminou_antes"], (
        "a fusão não esperou a trava da limpeza: confirmou entre a leitura e o DELETE")
    assert resultado == {"alunos": 1, "eventos_duplicados": 1}   # r1, a nativa de R
    with Session(motor_pg) as db:
        [fica] = db.execute(select(EventoAluno).where(EventoAluno.id == copias[0])).scalars()
        # Fica a cópia que prova a origem (a da ficha absorvida), como sem a corrida.
        assert fica.chave_natural == chave_evento("elefante", "leitura", Z, TITULO, QUANDO)
