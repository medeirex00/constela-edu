"""“Transferir de turma” com ``turma_origem_id`` num PostgreSQL REAL — local e
descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').
A rota toma a trava da escola (``pg_advisory_xact_lock``) antes de ler origem e
destino, e o UPDATE fica restrito à matrícula do ano ativo que está na origem.
Sobrescreve a fixture ``db`` só neste módulo e reusa os testes SQLite de
``test_transferir_turma_origem``."""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]


@pytest.fixture()
def db():
    engine = create_engine(URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    sessao = TestSession()

    def _get_db():
        outra = TestSession()
        try:
            yield outra
        finally:
            outra.close()

    app.dependency_overrides[get_db] = _get_db
    yield sessao
    sessao.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


from tests.test_transferir_turma_origem import (  # noqa: E402,F401
    test_aluno_fora_da_origem_recusa_o_pedido_inteiro_sem_criar_matricula as test_pg_fora,
    test_delete_de_turma_de_ano_anterior_orienta_arquivar as test_pg_delete_ano_anterior,
    test_origem_de_outro_ano_letivo_e_recusada_e_nada_muda as test_pg_outro_ano,
    test_origem_do_ano_ativo_move_so_a_matricula_dela_e_audita_a_origem as test_pg_ano_ativo,
    test_origem_do_ano_ativo_nao_mexe_na_matricula_de_outro_ano as test_pg_historico,
    test_sem_origem_continua_movendo_a_matricula_do_ano_ativo as test_pg_sem_origem)
