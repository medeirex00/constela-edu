"""Os testes de integridade de identidade/turma onde o banco faz diferença
(consultas novas da fila, savepoints da identidade, Lista Piloto pela rota),
com a sessão num PostgreSQL LOCAL DESCARTÁVEL (``TEST_DATABASE_URL_PG``).
Sobrescreve a fixture ``db`` só neste módulo; sem a variável, pula."""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG")]


@pytest.fixture()
def db():
    if make_url(URL).host not in ("127.0.0.1", "localhost", "::1"):
        pytest.skip("estes testes recriam as tabelas: só PostgreSQL LOCAL")
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


from tests.test_sync_integridade_identidade import (  # noqa: E402,F401
    test_transferido_nao_reativa_nao_duplica_e_nao_recebe_sozinho as test_pg_transferido,
    test_vinculado_em_turma_arquivada_recebe_na_propria_ficha as test_pg_vinculado_arquivada)
from tests.test_sync_integridade_identidade_id_duplicado import (  # noqa: E402,F401
    test_elefante_mesmo_student_id_no_resumo_segura_tambem_as_leituras as test_pg_disputa,
    test_matific_mesmo_uuid_com_nomes_diferentes_nao_aplica_em_ninguem as test_pg_uuid_dup,
    test_mesmo_uuid_mesmo_nome_numeros_diferentes_resolver_nao_escolhe_numeros as test_pg_resolver)
from tests.test_sync_integridade_identidade_nome_incompleto import (  # noqa: E402,F401
    test_decisao_do_gestor_na_revisao_vale_nas_coletas_seguintes as test_pg_decisao_gestor,
    test_nome_incompleto_nao_cria_nem_associa_com_politica_permitir as test_pg_nome_incompleto)
from tests.test_sync_integridade_identidade_turmas import (  # noqa: E402,F401
    test_as_duas_ativas_crianca_do_1o_ano_vai_para_o_1o_ano as test_pg_duas_ativas,
    test_lista_piloto_nao_matricula_em_turma_arquivada_e_avisa as test_pg_lista_piloto,
    test_sync_matific_ano_arquivado_crianca_nova_nao_nasce_na_fase as test_pg_ano_arquivado,
    test_turma_de_outro_ano_letivo_nao_serve_de_destino as test_pg_outro_ano)
