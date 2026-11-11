"""A prévia da Lista Piloto SÓ LÊ — num PostgreSQL REAL, local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').

REV-IMP-2: a prévia rodava a confirmação dentro de um SAVEPOINT (INSERT da turma
nova, das fichas e matrículas) e, com outra transação gravando a MESMA turma (a
confirmação da mesma lista, por exemplo), esperava a outra terminar no índice único
das turmas — e, enquanto rodava, prendia as travas que a confirmação precisava.
Agora ela só lê: não espera ninguém, não manda nenhum comando de escrita e dá os
números da confirmação. Sobrescreve a fixture ``db`` só neste módulo."""
import os
import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.models import Turma
from app.services import lista_piloto
from tests.test_aud_imp_lista_piloto_previa import _post

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


from tests.test_aud_imp_lista_piloto_previa_leitura import (  # noqa: E402,F401
    _lista,
    test_previa_de_300_criancas_nao_escreve_e_consulta_o_mesmo_que_a_de_5
    as test_pg_previa_de_300_criancas_nao_escreve,
    test_previa_so_lendo_da_os_numeros_da_confirmacao
    as test_pg_previa_so_lendo_da_os_numeros_da_confirmacao,
)


@pytest.mark.parametrize("desfecho", ["rollback", "commit"])
def test_pg_previa_nao_espera_quem_esta_gravando_a_mesma_turma(cliente, db,
                                                               escola_completa, desfecho):
    """Outra transação criou a turma da aba e só fecha depois de 3 s: a prévia
    responde sem esperar por ela (antes: 3,01 s, presa no índice único)."""
    eid = escola_completa["escola"].id
    arquivo = _lista(1, 5)
    analise = lista_piloto.analisar_matriculas(arquivo, "Lista.xlsx")
    conn = db.get_bind().connect()
    tx = conn.begin()
    outra = Session(bind=conn)
    outra.add(Turma(escola_id=eid, nome=analise.turmas[0].nome, ano_escolar="1º Ano",
                    ano_letivo=2026))
    outra.flush()
    soltar = threading.Timer(3.0, getattr(tx, desfecho))
    soltar.start()
    try:
        t0 = time.monotonic()
        previa = _post(cliente, eid, "analisar", arquivo)
        demora = time.monotonic() - t0
    finally:
        soltar.join()
        outra.close()
        conn.close()
    assert (previa["alunos_novos"], previa["alunos_atualizar"],
            previa["alunos_em_revisao"]) == (5, 0, 0)
    assert demora < 1.5, f"a prévia esperou {demora:.2f} s pela outra transação"
