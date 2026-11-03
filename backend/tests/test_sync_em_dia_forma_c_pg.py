"""A forma C do "em dia" num PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). O filtro do
"em dia" (``service._filtro_em_dia``: ``coalesce`` do motivo + ``NOT IN``, e o
filtro por JSON dos parâmetros), a agregação do painel global e a varredura do
agendador rodam em SQL; aqui eles rodam no banco de produção. Sobrescreve a
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


from tests.test_sync_em_dia_forma_c import (  # noqa: E402,F401
    test_filtro_em_dia_por_motivo_do_sem_atualizacao as test_pg_filtro_por_motivo,
    test_matific_credencial_de_outra_escola_tudo_em_revisao as test_pg_matific_outra_escola,
    test_matific_queda_retida_com_pendencia_conta_como_conferida as test_pg_queda_com_pendencia,
    test_mistura_vinculados_conferidos_e_pendencias_e_em_dia_com_alerta as test_pg_mistura,
    test_nada_mudou_e_em_dia as test_pg_nada_mudou,
    test_parcial_por_unidade_que_falhou_nao_e_em_dia as test_pg_parcial_por_unidade,
    test_parcial_so_por_linhas_descartadas_e_em_dia as test_pg_parcial_por_descarte,
    test_primeira_coleta_tudo_em_revisao_nao_e_em_dia_e_desatualizada_abre_depois
    as test_pg_primeira_coleta,
    test_regra_unica_status_painel_e_agendador_seguem_a_forma_c as test_pg_regra_unica,
    test_vinculados_e_coleta_toda_em_revisao_nao_e_em_dia as test_pg_vinculados_em_revisao)
