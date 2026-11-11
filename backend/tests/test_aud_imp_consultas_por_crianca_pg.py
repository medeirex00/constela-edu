"""Os casos de ``test_aud_imp_consultas_por_crianca`` num PostgreSQL REAL — local e
descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). É no
PostgreSQL que o flush agrupado vira poucos INSERT de várias linhas e que o vínculo
novo usa ``INSERT ... ON CONFLICT DO NOTHING``. Sobrescreve a fixture ``db`` só neste
módulo."""
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


from tests.test_aud_imp_consultas_por_crianca import (  # noqa: E402,F401
    sessao_de_producao,
    test_conta_aposentada_nao_e_reativada_pelo_contexto as test_pg_conta_aposentada,
    test_lista_piloto_agrupa_matriculas_e_auditoria_das_fichas_novas as test_pg_lista_piloto_agrupa,
    test_placar_nao_consulta_o_vinculo_linha_a_linha as test_pg_placar_sem_select_por_linha,
    test_vinculo_feito_por_outra_transacao_nao_e_roubado as test_pg_vinculo_nao_e_roubado,
    test_vinculo_novo_devolve_true_e_entra_no_contexto as test_pg_vinculo_novo_devolve_true,
)
