"""Os cenários de ``test_sync_revisao_independente.py`` num PostgreSQL REAL — local e
descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').
Sobrescreve a fixture ``db`` só neste módulo e reusa os testes do módulo SQLite,
para as duas execuções afirmarem a mesma coisa.
Sem ``TEST_DATABASE_URL_PG`` (o job test-backend do CI, que nem tem o driver),
o módulo inteiro é pulado."""
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


from tests.test_sync_revisao_independente import (  # noqa: E402,F401
    test_coleta_com_aluno_aplicado_continua_dizendo_quantos as test_pg_push_com_aluno,
    test_coleta_nada_mudou_que_recalcula_pela_marca_nao_anuncia_zero_alunos
    as test_pg_push_nada_mudou_sem_zero,
    test_coleta_parcial_sem_aluno_que_recalcula_pela_marca_nao_anuncia_zero_alunos
    as test_pg_push_parcial_sem_zero,
    test_elefante_total_nao_inteiro_ou_ilegivel_nao_derruba_a_coleta as test_pg_elefante_total,
    test_execucao_com_data_inexistente_termina_periodo_invalido_sem_tocar_o_acumulado
    as test_pg_periodo_data_inexistente,
    test_leaderboard_falhando_com_total_retido_abre_o_alerta_de_queda as test_pg_lb_queda,
    test_leaderboard_falhando_sem_numero_mudado_e_parcial_nao_erro as test_pg_lb_parcial,
    test_morte_depois_de_gravar_um_arquivo_marca_recalculo_e_a_coleta_seguinte_recalcula
    as test_pg_morte_depois_de_gravar,
    test_morte_durante_a_coleta_nao_marca_recalculo as test_pg_morte_na_coleta,
    test_painel_global_nao_conta_parcial_sem_aluno_como_sincronizada
    as test_pg_painel_parcial_sem_aluno,
    test_parcial_com_aluno_aplicado_continua_avancando_o_ultimo_sucesso_e_o_selo
    as test_pg_parcial_com_aluno_ultimo_sucesso,
    test_parcial_com_aluno_aplicado_continua_referencia_do_placar_vazio
    as test_pg_parcial_com_aluno_referencia,
    test_parcial_sem_aluno_nao_avanca_o_ultimo_sucesso as test_pg_parcial_sem_aluno_sucesso,
    test_parcial_sem_aluno_nao_cala_o_alerta_do_placar_vazio as test_pg_parcial_sem_aluno,
    test_recalculo_que_falhou_e_a_coleta_seguinte_sem_aluno_nao_anuncia_zero_alunos
    as test_pg_push_recalculo_falhou_sem_zero,
    test_selo_de_frescor_nao_conta_coleta_por_periodo_como_ultima_sincronizacao
    as test_pg_selo_frescor_periodo,
    test_selo_de_frescor_nao_conta_parcial_sem_aluno as test_pg_selo_frescor_parcial_sem_aluno,
    test_status_nao_mostra_parcial_sem_aluno_como_ultimo_sucesso
    as test_pg_status_parcial_sem_aluno)
