"""G_AJUSTE-2 (a rede) num PostgreSQL REAL — local e descartável (``TEST_DATABASE_URL_PG``;
o nome do banco precisa conter 'test'): o teto de 5 estrelas por atividade é uma expressão
SQL dentro do ``UNION ALL`` tipado de ``rede._leituras_da_rede``, e o PostgreSQL confere o
tipo de cada posição dos ramos, coisa que o SQLite não faz. A fixture ``db`` e as marcas
são as do módulo PG da frente (sobrescrevem a ``db`` só aqui)."""
from tests.test_aud3_rede_estrelas_teto import (  # noqa: F401
    test_painel_da_rede_soma_as_estrelas_que_contam as test_pg_estrelas_painel,
    test_ranking_da_rede_nao_poe_no_topo_a_escola_do_retrato_inflado as test_pg_estrelas_ranking,
)
from tests.test_aud3_rede_legado_turma_outro_ano_pg import db, pytestmark  # noqa: F401
