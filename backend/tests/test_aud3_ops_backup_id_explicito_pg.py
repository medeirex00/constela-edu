"""EXTRA-BACKUP-ID-EXPLICITO (``test_aud3_ops_backup_id_explicito.py``) num PostgreSQL
REAL, local e descartável (TEST_DATABASE_URL_PG; o nome do banco precisa conter
'test'). Mesmo padrão de ``test_backup_restauracao_d10_pg.py``.

Além dos testes do SQLite, o efeito que só o PostgreSQL mostra: o INSERT com o id do
arquivo não avança a sequência, e a PRÓXIMA ficha criada, de qualquer escola, recebe
o mesmo número e cai com ``IntegrityError``. Dados INVENTADOS.
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.models import Aluno, Escola
from app.services import backup as svc_backup

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


from tests.test_aud3_ops_backup_id_explicito import (  # noqa: E402,F401
    _arquivo,
    test_escola_id_dentro_da_linha_do_arquivo_e_ignorado as test_pg_escola_id_ignorado,
    test_id_dentro_da_linha_do_arquivo_e_ignorado as test_pg_id_ignorado,
)


def _proximo_da_sequencia(db) -> int:
    """O número que o próximo INSERT sem id em ``alunos`` vai receber (sem consumi-lo)."""
    seq = db.execute(text("SELECT pg_get_serial_sequence('alunos', 'id')")).scalar_one()
    ultimo, chamado = db.execute(
        text(f"SELECT last_value, is_called FROM {seq}")).one()
    return ultimo + 1 if chamado else ultimo


def test_pg_ficha_nova_depois_da_restauracao_nao_colide_com_o_id_do_arquivo(
        db, escola_completa):
    eid = escola_completa["escola"].id
    dados = _arquivo(db, eid)
    n = len(dados["tabelas"]["alunos"])
    # As n-1 fichas sem id tomam os n-1 próximos números; a do arquivo pega o seguinte
    # — justamente o que a sequência daria à próxima ficha criada depois.
    dados["tabelas"]["alunos"][0]["id"] = _proximo_da_sequencia(db) + n - 1

    svc_backup.restaurar(db, eid, dados)
    db.commit()

    outra = Escola(nome="EMEF Fictícia Vizinha do Backup", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    db.add(Aluno(escola_id=outra.id, nome="Ficha Nova Inventada Depois"))
    db.commit()                                 # antes: IntegrityError (alunos_pkey)
