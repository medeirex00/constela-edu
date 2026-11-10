"""O link de redefinição de senha vale ao nascer, seja qual for o fuso da sessão do PostgreSQL.

``admin.redefinir_senha`` grava ``expira_em`` (instante COM fuso) numa coluna SEM fuso e
``auth._expirado`` a lê como UTC. Com a sessão em America/Sao_Paulo o PostgreSQL gravava o
relógio de Brasília e o link nascia 3 h no passado — vencido (AUTH-7). O tipo da coluna
(``database.DataHoraUTC``) agora grava UTC antes de enviar. Cenário com a API inteira sobre um
PostgreSQL descartável aberto no fuso pedido; dados fictícios. Os demais cenários do fuso estão
em ``test_aud_infra_fuso_utc.py``.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.security import hash_senha
from app.main import app
from app.models import TokenResetSenha, Usuario

URL_PG = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL_PG, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL_PG) and "test" not in (make_url(URL_PG).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]

API = "/api/v1"


@pytest.fixture(params=["UTC", "America/Sao_Paulo"])
def db(request):
    """A ``db`` do conftest trocada por um PostgreSQL com a sessão no fuso do parâmetro."""
    motor = create_engine(URL_PG, connect_args={"options": f"-c TimeZone={request.param}"})
    Base.metadata.drop_all(motor)
    Base.metadata.create_all(motor)
    Sessao = sessionmaker(bind=motor)
    sessao = Sessao()

    def _get_db():
        outra = Sessao()
        try:
            yield outra
        finally:
            outra.close()

    app.dependency_overrides[get_db] = _get_db
    yield sessao
    sessao.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(motor)
    motor.dispose()


def test_link_recem_gerado_vale_com_a_sessao_fora_de_utc(cliente, db, escola_completa):
    fuso = db.execute(text("SHOW TimeZone")).scalar()
    eid = escola_completa["escola"].id
    p = Usuario(escola_id=eid, nome="Prof Ficticio Fuso", email="prof.fuso@teste.local",
                senha_hash=hash_senha("senha-ficticia-forte-1"), cargo="professor")
    db.add(p)
    db.commit()
    link = cliente.post(f"{API}/escolas/{eid}/usuarios/{p.id}/redefinir-senha")
    assert link.status_code == 200, link.text
    db.expire_all()
    gravado = db.query(TokenResetSenha).filter_by(usuario_id=p.id).one().expira_em
    prometido = (datetime.fromisoformat(link.json()["expira_em"])
                 .astimezone(timezone.utc).replace(tzinfo=None))
    assert abs((gravado - prometido).total_seconds()) < 1, (
        f"sessão em {fuso}: a API prometeu {prometido} (UTC), o banco guardou {gravado}")
    valido = TestClient(app).get(f"{API}/auth/redefinir-senha/{link.json()['token']}").json()
    assert valido["valido"] is True, f"link recém-gerado já vencido com a sessão em {fuso}"
