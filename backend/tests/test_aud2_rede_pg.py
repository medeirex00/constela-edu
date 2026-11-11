"""Os testes da frente REDE (2ª onda da auditoria) num PostgreSQL REAL — local e
descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').

Os cartões das escolas da rede saem de ``UNION ALL`` com colunas nulas TIPADAS
(``rede._leituras_da_rede``): o PostgreSQL exige o mesmo tipo em cada posição de todos
os ramos, coisa que o SQLite não confere. Sobrescreve a fixture ``db`` só neste módulo."""
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


from tests.test_aud2_rede_adocao_contrato import (  # noqa: E402,F401
    test_adocao_do_cartao_e_dos_totais_so_conta_o_modulo_contratado as test_pg_adocao_contrato,
    test_rede_com_as_duas_plataformas_continua_contando_as_duas as test_pg_adocao_duas,
)
from tests.test_aud2_rede_indice_peso import (  # noqa: E402,F401
    test_indice_e_media_geral_da_rede_nao_pesam_as_criancas_da_fase as test_pg_indice_peso,
    test_panorama_global_pesa_redes_e_escolas_por_quem_concorre as test_pg_indice_global,
)
from tests.test_aud2_rede_peso_media_medida import (  # noqa: E402,F401
    test_meta_da_media_geral_nao_e_medida_sem_nota_calculada as test_pg_peso_media_sem_nota,
    test_panorama_global_e_meta_da_media_geral_pesam_quem_a_media_mede as test_pg_peso_media_global,
    test_peso_da_media_e_o_dos_modulos_contratados as test_pg_peso_media_contrato,
    test_quem_ainda_nao_tem_nota_calculada_nao_pesa_na_media_geral as test_pg_peso_media_pendente,
    test_quem_so_tem_leitura_itemizada_pesa_na_media_geral as test_pg_peso_media_leitura,
    test_quem_so_tem_o_matific_do_ano_passado_nao_pesa_na_media_geral as test_pg_peso_media_matific,
)
from tests.test_aud2_rede_percapita_exato import (  # noqa: E402,F401
    test_indice_e_regua_saem_do_per_capita_exato as test_pg_percapita_regua,
    test_panorama_global_compara_redes_pelo_per_capita_exato as test_pg_percapita_global,
)
from tests.test_aud2_rede_pendentes_converge import (  # noqa: E402,F401
    test_o_painel_conta_so_a_nota_de_quem_concorre as test_pg_pendentes_painel,
    test_uma_rodada_de_pendentes_zera_a_selecao_e_o_painel as test_pg_pendentes_converge,
)
