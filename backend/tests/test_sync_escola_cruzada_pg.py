"""A proteção contra dados de OUTRA escola num PostgreSQL REAL — local e
descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').
O vínculo vive em ``configuracoes`` (JSON) e a marca da identidade de outra
escola é uma consulta com junção e ``IN``: o dialeto faz diferença. Sobrescreve a
fixture ``db`` só neste módulo e reusa os testes SQLite."""
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


from tests.test_sync_escola_cruzada import (  # noqa: E402,F401
    test_credencial_de_outra_escola_elefante_nao_aplica_na_segunda as test_pg_credencial_elefante,
    test_credencial_de_outra_escola_matific_nao_aplica_na_segunda as test_pg_credencial_matific,
    test_elefante_conta_com_duas_escolas_com_vinculo_explicito_coleta_so_a_vinculada
    as test_pg_duas_escolas_com_vinculo,
    test_elefante_conta_com_duas_escolas_sem_vinculo_e_erro_e_nada_aplicado
    as test_pg_duas_escolas_sem_vinculo,
    test_elefante_conta_de_uma_escola_aprende_o_vinculo_e_coleta as test_pg_aprende_elefante,
    test_elefante_curso_de_outra_escola_no_relatorio as test_pg_curso_de_outra_escola,
    test_elefante_curso_sem_school_id_em_conta_de_varias_escolas_e_recusado
    as test_pg_curso_sem_escola,
    test_elefante_escola_externa_que_muda_entre_coletas_e_erro as test_pg_escola_trocada,
    test_escola_atual_sem_vinculo_aprende_na_primeira_coleta_e_nao_duplica
    as test_pg_escola_atual,
    test_matific_escola_da_conta_muda_entre_coletas_e_erro as test_pg_matific_trocada,
    test_rota_do_vinculo_valida_recusa_duplicata_audita_e_remove as test_pg_rota_vinculo)
from tests.test_sync_identidade_outra_escola import (  # noqa: E402,F401
    test_student_id_efetivo_em_outra_escola_vai_para_revisao as test_pg_student_id_outra,
    test_uuid_efetivo_em_outra_escola_vai_para_revisao_e_nao_aplica as test_pg_uuid_outra)
