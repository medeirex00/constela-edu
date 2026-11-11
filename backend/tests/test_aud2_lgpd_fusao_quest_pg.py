"""G_LGPD-3 (fusão × Constela Quest) num PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').

Reusa os testes SQLite de ``test_aud2_lgpd_fusao_quest``: o PostgreSQL não
reaproveita id de linha apagada, cumpre a UNIQUE de ``aluno_id`` do perfil e do
cartão na hora do UPDATE e devolve ``ultimo_acesso`` com fuso (o SQLite, sem).

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud2_lgpd_fusao_quest_pg.py -m postgres

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


from tests.test_aud2_lgpd_fusao_quest import (  # noqa: E402,F401
    test_as_duas_fichas_com_progresso_a_fusao_e_recusada_sem_apagar_nada as test_pg_conflito,
    test_fundir_duplicatas_mantem_o_progresso_e_o_cartao_que_a_crianca_usa as test_pg_lote,
    test_fusao_manual_mantem_o_quest_da_ficha_absorvida_em_uso as test_pg_manual,
    test_leque_com_progresso_em_duas_copias_recusa_so_a_segunda as test_pg_leque,
    test_os_dois_cartoes_usados_fica_o_mais_recente as test_pg_dois_cartoes,
    test_so_o_cartao_foi_usado_fica_o_cartao_usado as test_pg_cartao_usado,
    test_sem_uso_nenhum_fica_o_quest_da_ficha_principal as test_pg_sem_uso)
