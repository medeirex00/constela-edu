"""Os testes de RESULTADO da frente C contra PostgreSQL real (``-m postgres``).

Reaproveita as funções de ``test_sync_integridade_resultados*`` coletando-as AQUI,
onde a fixture ``db`` é a de um PostgreSQL LOCAL descartável
(``TEST_DATABASE_URL_PG``, mesma régua de ``tests/_infra_comum.pg_url``: host local,
"test" no nome, schema ``public`` zerado antes e depois). Sem a variável, SKIP.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from tests._infra_comum import pg_url  # noqa: F401 — fixture
from tests.test_sync_integridade_resultados import (  # noqa: F401 — coletados aqui
    test_leitura_todo_historico_sem_filtro_traz_todas_as_turmas,
    test_merito_de_ativo_sem_matricula_no_ano_e_recusado,
)
from tests.test_sync_integridade_resultados_ano_letivo import (  # noqa: F401
    test_painel_e_ranking_da_rede_somam_so_o_matific_do_ano,
)
from tests.test_sync_integridade_resultados_ponta_a_ponta import (  # noqa: F401
    test_nova_coleta_atualiza_ranking_periodo_e_premiacao,
    test_retrato_gravado_chega_a_nota_aos_rankings_e_as_premiacoes,
)
from tests.test_sync_integridade_resultados_questoes import (  # noqa: F401
    test_turma_que_parou_de_ser_coletada_deixa_o_numero_parcial,
)

pytestmark = pytest.mark.postgres


@pytest.fixture()
def db(pg_url):  # noqa: F811 — sobrepõe o SQLite do conftest só neste módulo
    engine = create_engine(pg_url)
    Base.metadata.create_all(engine)
    Sessao = sessionmaker(bind=engine)
    sessao = Sessao()

    def _get_db():
        outra = Sessao()
        try:
            yield outra
        finally:
            outra.close()

    app.dependency_overrides[get_db] = _get_db
    yield sessao
    sessao.close()
    app.dependency_overrides.clear()
    engine.dispose()
