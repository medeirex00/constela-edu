"""Nome da cerimônia do Quest num PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test'). É no PG que o
nome expandido pelo title() virava 500 (StringDataRightTruncation no commit); o
SQLite grava qualquer tamanho. Sobrescreve a fixture ``db`` só neste módulo e reusa
os testes de rota de ``test_quest_nome_exibicao_tamanho``. Dados fictícios."""
import os

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.quest.models import QuestPerfil

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


from tests.test_quest_nome_exibicao_tamanho import (  # noqa: E402
    NOME_QUE_EXPANDE,
    _sessao_da_crianca,
    test_rota_nome_de_20_letras_comuns_continua_200 as test_pg_nome_de_20_continua_200,
    test_rota_nome_que_expande_da_422_e_nao_grava as test_pg_nome_que_expande_da_422,
)

__all__ = ["test_pg_nome_de_20_continua_200", "test_pg_nome_que_expande_da_422"]


def test_pg_o_valor_expandido_estoura_a_coluna(cliente, db, escola_completa):
    """Controle: o que o validador ANTIGO devolvia (title() sem conferir) o PG
    recusa no flush — é exatamente o 500 que o 422 de agora evita."""
    _, aluno_id = _sessao_da_crianca(cliente, db, escola_completa)
    perfil = db.execute(select(QuestPerfil)
                        .where(QuestPerfil.aluno_id == aluno_id)).scalar_one()
    perfil.nome_exibicao = NOME_QUE_EXPANDE.title()
    with pytest.raises(DataError) as erro:
        db.flush()
    assert type(erro.value.orig).__name__ == "StringDataRightTruncation"
    db.rollback()
