"""Plataformas da análise num PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). A seleção das coletas
das questões do Elefante (``plataformas._coletas_das_questoes``) mede a distância entre
duas linhas com uma expressão do banco (``extract(epoch ...)`` no PostgreSQL,
``julianday`` no SQLite): aqui os mesmos testes de equivalência com a regra oficial rodam
no banco de produção (inclusive as leituras em lote e a evolução, com vários períodos numa
consulta só) — e as provas de que o desempenho do Matific (derivado) não refaz as
atividades escondidas em complemento, nem o zero de uma série sem número. Sobrescreve a
fixture ``db`` só neste módulo."""
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


from tests.test_analise_plataformas import (  # noqa: E402,F401
    mundo,
    test_a_conta_com_os_retratos_essenciais_e_a_das_funcoes_oficiais as test_pg_equivalencia,
    test_contador_que_regrediu_sai_das_questoes_como_no_relatorio_por_periodo as
    test_pg_contador_regrediu,
    test_desempenho_do_total_nao_devolve_as_atividades_de_uma_crianca as
    test_pg_desempenho_uma_crianca,
    test_desempenho_do_total_nao_refaz_as_atividades_escondidas_em_complemento as
    test_pg_desempenho_complemento,
    test_estrelas_zero_de_serie_sem_numero_nao_se_refazem_pelo_total as test_pg_estrelas_zero,
    test_estrelas_zero_entre_as_escolas_da_rede as test_pg_estrelas_zero_rede,
    test_questoes_contam_a_primeira_linha_de_cada_execucao as test_pg_primeira_linha,
    test_questoes_medidas_em_brasilia_com_a_tolerancia_de_borda as test_pg_bordas_brasilia,
    test_leituras_em_lote_sao_as_das_funcoes_oficiais_de_uma_escola as test_pg_leituras_em_lote,
    test_rede_soma_as_marcas_das_somas_com_o_desempenho_derivado as test_pg_rede_desempenho,
)
# A evolução lê os 4 bimestres numa consulta por fonte (UNION ALL de vários grupos e a CTE das
# coletas do Elefante usada por todos): o caminho de vários períodos também roda no PostgreSQL.
from tests.test_analise_desempenho import (  # noqa: E402,F401
    test_evolucao_le_os_bimestres_juntos as test_pg_evolucao_bimestres_juntos,
)
