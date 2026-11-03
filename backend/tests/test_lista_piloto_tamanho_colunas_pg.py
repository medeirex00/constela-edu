"""Lista Piloto × tamanho das colunas num PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). É no PG que o
valor acima da coluna virava 500 (DataError, ``StringDataRightTruncation`` /
``NumericValueOutOfRange``, no commit da confirmação); o SQLite aceita qualquer
tamanho. Prova INVERTIDA da dimensão esquemas-sync-docs: série de 32, título de
aba de 31 e nome de aluno de 201 davam 500; agora dão 200 com aviso e com as
linhas boas gravadas. Sobrescreve a fixture ``db`` só neste módulo e reusa os
testes de rota de ``test_lista_piloto_tamanho_colunas``; um ouvinte
``handle_error`` no engine garante que nenhum erro de banco ficou escondido."""
import os

import pytest
from sqlalchemy import create_engine, event
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
    erros: list = []

    @event.listens_for(engine, "handle_error")
    def _anotar(ctx):
        erros.append(type(ctx.original_exception).__name__)

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
    # Nenhum DataError engolido no caminho (o savepoint do professor, por exemplo).
    assert not [e for e in erros if "DataError" in e or "Truncation" in e
                or "OutOfRange" in e], erros


from tests.test_lista_piloto_tamanho_colunas import (  # noqa: E402,F401
    test_linha_pulada_nao_marca_ninguem_da_turma_fora_da_lista as test_pg_linha_pulada,
    test_nome_de_aluno_acima_de_200_pula_so_a_linha as test_pg_nome_201,
    test_sed_longo_e_numero_fora_do_inteiro_nao_derrubam_o_arquivo as test_pg_sed_numero,
    test_serie_com_30_no_limite_passa_sem_aviso as test_pg_serie_30,
    test_serie_fora_do_padrao_acima_de_30_e_cortada_com_aviso as test_pg_serie_32,
    test_serie_que_mudaria_a_leitura_deixa_a_aba_de_fora as test_pg_serie_muda,
    test_titulo_da_aba_de_31_vira_serie_cortada as test_pg_aba_31,
    test_turma_existente_com_nome_longo_na_planilha_continua_importando as test_pg_existente,
    test_turma_nova_com_nome_acima_de_100_fica_de_fora as test_pg_turma_101,
)
