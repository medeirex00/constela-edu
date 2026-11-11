"""S_G_GRUPO-1 num PostgreSQL REAL — local e descartável (``TEST_DATABASE_URL_PG``; o nome
do banco precisa conter 'test').

O corte "turma do ano ativo de cada escola" entra nos ``UNION ALL`` de
``rede._leituras_da_rede`` (o ramo das turmas, a contagem de alunos, os totais e a
cobertura) e no ``elegibilidade.turmas_premiaveis_da_rede(no_ano_ativo=True)``: o
PostgreSQL confere o que o SQLite deixa passar (tipos dos ramos, a correlação da coluna
por escola). Sobrescreve a fixture ``db`` só neste módulo."""
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


from tests._ano_letivo import escola_no_ano_de_hoje  # noqa: E402,F401 — fixture
from tests.test_aud3_rede_legado_turma_outro_ano import (  # noqa: E402,F401
    test_controle_sem_legado_o_cartao_e_a_soma_das_turmas as test_pg_legado_controle,
    test_diagnostico_acha_a_matricula_do_ano_numa_turma_de_outro_ano as test_pg_legado_diagnostico,
    test_legado_cartao_menos_turmas_nao_devolve_a_crianca as test_pg_legado_cartao,
    test_legado_ranking_da_rede_conta_so_quem_esta_numa_turma_do_ano as test_pg_legado_ranking,
    test_turmas_premiaveis_da_rede_no_ano_ativo_de_cada_escola as test_pg_legado_premiaveis,
)
