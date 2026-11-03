"""Os achados da revisão e93 em que o BANCO faz diferença (filtro por JSON dos
parâmetros, marca de recálculo commitada antes do recálculo, troca de turma,
revisão de id repetido, data do retrato reescrito) num PostgreSQL REAL — local e
descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').
Sobrescreve a fixture ``db`` só neste módulo e reusa os testes SQLite."""
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


from tests.test_sync_revisao_dados import (  # noqa: E402,F401
    test_linha_sem_campo_essencial_nao_cria_ficha as test_pg_campo_essencial,
    test_mesmo_uuid_em_duas_turmas_com_numeros_diferentes_nao_aplica_nem_move
    as test_pg_uuid_duas_turmas,
    test_nome_de_um_token_nao_cria_ficha as test_pg_um_token,
    test_periodo_em_andamento_repetido_nao_empilha_retrato as test_pg_periodo_andamento,
    test_processo_que_morre_no_recalculo_deixa_a_marca as test_pg_morre_no_recalculo,
    test_reescrita_no_mesmo_dia_utc_leva_a_data_do_valor_novo as test_pg_data_reescrita,
    test_troca_de_turma_sem_numero_novo_recalcula as test_pg_troca_de_turma,
    test_uuid_duplicado_na_mesma_turma_com_queda_vai_para_revisao as test_pg_uuid_com_queda,
    test_ano_nao_nasce_em_turma_de_fase_com_nome_normalizado as test_pg_fase)
from tests.test_sync_revisao_regressao import (  # noqa: E402,F401
    test_r1c_defeito_permanente_com_atividade_diaria as test_pg_r1c,
    test_r3_nomes_404_nao_derruba_coleta_de_quem_tem_uuid as test_pg_r3,
    test_r4_pendencia_de_identidade_em_ferias_nao_deixa_desatualizada as test_pg_r4)
from tests.test_sync_revisao_semantica import (  # noqa: E402,F401
    test_coleta_completa_com_pendencia_fecha_falha_antiga as test_pg_fecha_falha_antiga,
    test_periodo_passado_nao_poe_a_integracao_em_dia as test_pg_periodo_passado,
    test_queda_retida_tem_motivo_proprio_e_nao_manda_para_revisao as test_pg_queda_retida,
    test_roster_2xx_objeto_fora_do_formato_e_erro as test_pg_roster_fora)
