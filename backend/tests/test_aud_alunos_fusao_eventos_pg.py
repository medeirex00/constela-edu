"""Fusão × eventos duplicados, no banco de produção (PostgreSQL).

Complementa ``test_aud_alunos_fusao_eventos.py`` nos dois pontos que dependem do
banco: a fusão troca a cópia nativa pela da ficha absorvida na MESMA transação
(UNIQUE ``uq_evento_natural`` de verdade), e a limpeza do passivo lê em fluxo
(cursor do servidor, ``yield_per``) e só apaga depois de ler.

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud_alunos_fusao_eventos_pg.py -m postgres

Achado ALUNOS-3 da auditoria. Dados fictícios.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Aluno, EventoAluno, LogAuditoria
from app.services import alunos_fusao
from app.services.eventos import chave_evento, deduplicar_eventos_por_conteudo
from tests.test_fusao_trava_escola_pg import cena, motor_pg, pytestmark  # noqa: F401

TITULO = "Livro Ficticio do Espelho PG"
QUANDO = datetime(2026, 3, 10, 10, 0)


def _evento(db, escola_id, aluno_id, origem, quando=QUANDO):
    db.add(EventoAluno(escola_id=escola_id, aluno_id=aluno_id, plataforma="elefante",
                       tipo_evento="leitura", ocorrido_em=quando, conteudo_titulo=TITULO,
                       chave_natural=chave_evento("elefante", "leitura", origem, TITULO,
                                                  quando)))


def _eventos(db, aluno_id):
    return list(db.execute(select(EventoAluno).where(EventoAluno.aluno_id == aluno_id)
                           .order_by(EventoAluno.id)).scalars())


def test_fusao_com_a_mesma_linha_nas_duas_fichas_fica_um_evento(motor_pg, cena):
    with Session(motor_pg) as db:
        _evento(db, cena["escola"], cena["oficial"], cena["oficial"])
        _evento(db, cena["escola"], cena["stub"], cena["stub"])
        db.commit()
        alunos_fusao.fundir_par(db, cena["escola"], db.get(Aluno, cena["oficial"]),
                                db.get(Aluno, cena["stub"]), cena["admin"])
        db.commit()
    with Session(motor_pg) as db:
        eventos = _eventos(db, cena["oficial"])
        assert len(eventos) == 1
        assert eventos[0].chave_natural == chave_evento(
            "elefante", "leitura", cena["stub"], TITULO, QUANDO)


def test_limpeza_do_passivo_le_em_fluxo_e_apaga_depois(motor_pg, cena):
    with Session(motor_pg) as db:
        _evento(db, cena["escola"], cena["oficial"], cena["oficial"])
        _evento(db, cena["escola"], cena["oficial"], cena["stub"])   # movido por fusão antiga
        _evento(db, cena["escola"], cena["oficial"], cena["oficial"], datetime(2026, 8, 6, 0, 1))
        db.add(LogAuditoria(escola_id=cena["escola"], acao="aluno.fundido", entidade="aluno",
                            entidade_id=cena["oficial"],
                            detalhes={"mantido": {"id": cena["oficial"]},
                                      "removido": {"id": cena["stub"]}}))
        db.commit()
        assert deduplicar_eventos_por_conteudo(db, escola_id=cena["escola"]) == {
            "alunos": 1, "eventos_duplicados": 1}
        db.rollback()
        assert len(_eventos(db, cena["oficial"])) == 3
        assert deduplicar_eventos_por_conteudo(db, escola_id=cena["escola"], aplicar=True) == {
            "alunos": 1, "eventos_duplicados": 1}
        db.commit()
    with Session(motor_pg) as db:
        assert [e.chave_natural for e in _eventos(db, cena["oficial"])] == [
            chave_evento("elefante", "leitura", cena["stub"], TITULO, QUANDO),
            chave_evento("elefante", "leitura", cena["oficial"], TITULO,
                         datetime(2026, 8, 6, 0, 1))]
