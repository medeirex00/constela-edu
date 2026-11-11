"""O id da conta da criança esquecida fora do cursor da sincronização (S_G_LGPD-2 e
REV3-LGPD-1) num PostgreSQL REAL — local e descartável (``TEST_DATABASE_URL_PG``; o
nome do banco precisa conter 'test').

Reusa os testes SQLite de ``test_aud3_lgpd_esquecimento_cursor_elefante``: a exclusão,
a coleta seguinte e a restauração de um backup anterior à exclusão (o PostgreSQL não
reaproveita id de linha apagada e o ``valor`` do cursor é JSON de verdade). Os testes
de ponta a ponta continuam em xfail estrito enquanto a sincronização e a restauração
não chamam ``exclusao_aluno.tirar_contas_esquecidas_do_cursor``.

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud3_lgpd_esquecimento_cursor_elefante_pg.py -m postgres

Dados fictícios.
"""
from __future__ import annotations

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
    if make_url(URL).host not in ("127.0.0.1", "localhost", "::1"):
        pytest.skip("estes testes recriam as tabelas: só PostgreSQL LOCAL")
    from app.quest import models as _quest  # noqa: F401
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


from tests.test_aud3_lgpd_esquecimento_cursor_elefante import (  # noqa: E402,F401
    test_coleta_seguinte_nao_regrava_a_conta_esquecida_no_cursor as test_pg_coleta_seguinte,
    test_coleta_tira_a_conta_esquecida_que_ja_estava_no_cursor as test_pg_coleta_cursor_antigo,
    test_cursor_de_outra_escola_so_perde_a_conta_com_todas_as_escolas as test_pg_outra_escola,
    test_cursor_devolvido_pela_restauracao_perde_a_conta_esquecida as test_pg_restaurado,
    test_cursor_ja_mesclado_pela_coleta_perde_a_conta_esquecida as test_pg_mesclado,
    test_exclusao_de_turma_com_alunos_tambem_tira_do_cursor as test_pg_turma,
    test_exclusao_tira_o_studentId_do_cursor_e_do_backup as test_pg_exclusao,
    test_restauracao_de_backup_anterior_nao_devolve_a_conta_ao_cursor as test_pg_restauracao,
    test_restauracao_seguida_de_coleta_nao_deixa_a_conta_no_cursor as test_pg_restauracao_coleta)
