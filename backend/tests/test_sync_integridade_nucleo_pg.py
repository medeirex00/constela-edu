"""Os cenários do núcleo da sincronização em que o BANCO faz diferença (transação,
flush, IntegrityError, rollback no meio, recálculo, idempotência) rodando num
PostgreSQL REAL — local e descartável (``TEST_DATABASE_URL_PG``; o nome do banco
precisa conter 'test'). Sobrescreve a fixture ``db`` só neste módulo e reusa os
testes dos módulos SQLite, para as duas execuções afirmarem a mesma coisa."""
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


from tests.test_sync_integridade_nucleo import (  # noqa: E402,F401
    test_elefante_qtd_alunos_e_turmas_distintos as test_pg_contagem_distinta,
    test_elefante_turma_com_http_500_e_parcial_visivel as test_pg_turma_500_parcial,
    test_elefante_tudo_em_revisao_e_sem_atualizacao_com_alerta as test_pg_tudo_em_revisao,
    test_matific_campo_renomeado_nao_grava_retrato_herdado as test_pg_campo_renomeado,
    test_matific_school_student_401_e_erro_sem_acesso_ao_dado as test_pg_matific_401,
    test_matific_school_student_500_e_erro_falha_download as test_pg_matific_500,
    test_plataforma_que_tinha_alunos_e_passa_a_zero_abre_plataforma_sem_dados as test_pg_sem_dados)
from tests.test_sync_integridade_nucleo_falhas import (  # noqa: E402,F401
    test_elefante_excecao_no_meio_e_parcial_sem_leitura_parcial_e_com_notas as test_pg_exc_meio,
    test_elefante_integrity_error_no_flush_e_parcial_sem_travar_e_a_seguinte_conclui
    as test_pg_integrity_error,
    test_falha_antes_de_gravar_continua_erro_sem_dado as test_pg_falha_antes,
    test_matific_excecao_no_2o_arquivo_e_parcial_e_o_gravado_esta_nas_notas
    as test_pg_matific_exc_2o_arquivo,
    test_recalculo_que_falha_fica_pendente_e_fecha_no_proximo as test_pg_recalculo_pendente,
    test_repeticao_no_mesmo_dia_e_no_seguinte_nao_duplica_e_nao_e_sucesso as test_pg_repeticao,
    test_teto_total_aborta_perto_do_teto_e_termina_erro_timeout as test_pg_teto)
