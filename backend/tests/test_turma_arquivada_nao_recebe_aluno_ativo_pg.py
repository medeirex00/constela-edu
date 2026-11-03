"""D17 pelo outro lado num PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). A recusa de
reativar agrupa as matrículas do ano por turma arquivada (GROUP BY no PG é mais
estrito que no SQLite) e o cadastro toma a trava de importação da escola
(``pg_advisory_xact_lock``) antes de olhar a turma; a consolidação de turmas
duplicadas e o /resolver da fila também (3ª revisão). Sobrescreve a fixture ``db``
só neste módulo e reusa os testes SQLite de
``test_turma_arquivada_nao_recebe_aluno_ativo``."""
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


from tests.test_turma_arquivada_nao_recebe_aluno_ativo import (  # noqa: E402,F401
    test_a_transferir_para_turma_arquivada_e_recusado as test_pg_transferir_recusado,
    test_b_pedido_misto_e_recusado_inteiro as test_pg_reativar_misto,
    test_b_reativar_alunos_de_turma_arquivada_e_recusado as test_pg_reativar_recusado,
    test_b_reativar_depois_de_transferir_para_turma_ativa_passa as test_pg_reativar_depois,
    test_c_cadastrar_aluno_em_turma_arquivada_e_recusado as test_pg_cadastrar_recusado,
    test_c_controle_cadastrar_em_turma_ativa_continua as test_pg_cadastrar_ativa,
    test_d_consolidar_em_canonica_arquivada_e_recusado as test_pg_consolidar_recusado,
    test_d_controle_consolidar_em_canonica_ativa_continua as test_pg_consolidar_ativa,
    test_d_pedido_com_um_grupo_recusado_nao_consolida_nenhum as test_pg_consolidar_misto,
    test_e_controle_resolver_criar_em_turma_ativa_continua as test_pg_resolver_ativa,
    test_e_fila_nao_desfaz_a_rede_de_seguranca_da_turma_arquivada as test_pg_resolver_fila,
    test_e_resolver_criar_em_turma_arquivada_e_recusado as test_pg_resolver_recusado)
