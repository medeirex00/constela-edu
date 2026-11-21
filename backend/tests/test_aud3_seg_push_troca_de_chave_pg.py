"""A conferência da chave de sessão dos aparelhos de push (S_G_ROTACAO-1) num
PostgreSQL REAL — local e descartável (``TEST_DATABASE_URL_PG``; o nome do banco
precisa conter 'test'). Reusa os cenários do módulo SQLite e acrescenta registros
SIMULTÂNEOS de contas diferentes da mesma escola: todos gravam a impressão da chave
ao mesmo tempo (a linha única em ``configuracoes``), e nenhum pode virar 500 nem
apagar o aparelho que outro acabou de registrar.

Sem ``TEST_DATABASE_URL_PG`` (o job test-backend do CI) o módulo inteiro é pulado.
Dados 100% fictícios; chaves geradas na hora; o envio ao Expo é trocado por captura.
"""
import os
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import criar_token, hash_senha, impressao_da_chave_de_sessao
from app.main import app
from app.models import Configuracao, DispositivoMovel, Usuario
from app.services import push

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


from tests.test_aud3_seg_push_troca_de_chave import (  # noqa: E402,F401
    TOKEN_ANTIGO,
    TOKEN_NOVO,
    _chave,
    mensagens,
    test_aparelho_da_sessao_antiga_nao_recebe_depois_da_troca as test_pg_sessao_antiga,
    test_boot_apaga_os_aparelhos_sem_marca_ou_de_outra_chave as test_pg_boot,
    test_registro_depois_da_troca_tira_o_antigo_e_fica as test_pg_registro_depois,
    test_troca_sem_ninguem_para_avisar_tambem_grava as test_pg_sem_destino,
)

QUANTOS = 8


def _contas(db, eid: int) -> list[str]:
    """JWTs de QUANTOS coordenadoras fictícias da mesma escola (assinados com a chave
    de agora)."""
    jwts = []
    for i in range(QUANTOS):
        u = Usuario(escola_id=eid, nome=f"Coord Ficticia {i}",
                    email=f"coord.chave{i}@teste.local",
                    senha_hash=hash_senha("Senha-Ficticia-PG-1"), cargo="coordenador")
        db.add(u)
        db.flush()
        jwts.append(u.id)
    db.commit()
    return [criar_token(uid, 0) for uid in jwts]


def _registrar_juntos(eid: int, jwts: list[str], prefixo: str) -> list[int]:
    largada = threading.Barrier(len(jwts))
    codigos: list[int] = []

    def registrar(i: int, jwt: str) -> None:
        cli = TestClient(app, raise_server_exceptions=False)
        cli.headers["Authorization"] = f"Bearer {jwt}"
        largada.wait()
        r = cli.post(f"/api/v1/escolas/{eid}/dispositivos",
                     json={"token_push": f"ExponentPushToken[{prefixo}-{i:04d}]",
                           "plataforma": "android"})
        codigos.append(r.status_code)

    fios = [threading.Thread(target=registrar, args=(i, jwt)) for i, jwt in enumerate(jwts)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join(timeout=120)
    return codigos


def _marcas(db, eid: int) -> list[str]:
    db.expire_all()
    return list(db.execute(select(Configuracao.valor).where(
        Configuracao.escola_id == eid,
        Configuracao.namespace == push.NAMESPACE_CHAVE_DE_SESSAO)).scalars())


def test_pg_primeiros_registros_simultaneos_gravam_uma_impressao_so(db, escola_completa):
    eid = escola_completa["escola"].id
    codigos = _registrar_juntos(eid, _contas(db, eid), "primeiro")
    assert codigos == [200] * QUANTOS, codigos
    assert _marcas(db, eid) == [impressao_da_chave_de_sessao()]
    assert db.execute(select(func.count()).select_from(DispositivoMovel)
                      ).scalar_one() == QUANTOS


def test_pg_registros_simultaneos_depois_da_troca_ficam_e_os_antigos_saem(
        db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    monkeypatch.setattr(settings, "SECRET_KEY", "teste-sk0-" + "a" * 40)
    assert _registrar_juntos(eid, _contas(db, eid), "antigo") == [200] * QUANTOS

    monkeypatch.setattr(settings, "SECRET_KEY", "teste-sk1-" + "b" * 40)
    jwts = [criar_token(uid, 0) for uid in db.execute(
        select(Usuario.id).where(Usuario.email.like("coord.chave%"))).scalars()]
    codigos = _registrar_juntos(eid, jwts, "novo")
    assert codigos == [200] * QUANTOS, codigos
    db.expire_all()
    tokens = set(db.execute(select(DispositivoMovel.token_push)).scalars())
    assert tokens == {f"ExponentPushToken[novo-{i:04d}]" for i in range(QUANTOS)}
    assert _marcas(db, eid) == [impressao_da_chave_de_sessao()]


def test_pg_leitura_atrasada_da_impressao_preserva_novo_aparelho(db, escola_completa,
                                                                monkeypatch):
    eid = escola_completa["escola"].id
    uid = escola_completa["admin"].id
    monkeypatch.setattr(settings, "SECRET_KEY", _chave("antiga"))
    push.conferir_chave_de_sessao(db, eid)
    db.add(DispositivoMovel(escola_id=eid, usuario_id=uid, plataforma="android",
                           token_push=TOKEN_ANTIGO))
    db.commit()

    monkeypatch.setattr(settings, "SECRET_KEY", _chave("nova"))
    with Session(bind=db.get_bind()) as atrasada:
        @event.listens_for(atrasada, "do_orm_execute", once=True)
        def concluir_outro_cadastro(execucao):
            leitura = execucao.invoke_statement()
            # Outra transação conclui a troca e o registro depois desta leitura.
            assert push.conferir_chave_de_sessao(db, eid) == (1, True)
            db.add(DispositivoMovel(escola_id=eid, usuario_id=uid, plataforma="android",
                                   token_push=TOKEN_NOVO))
            db.commit()
            return leitura

        assert push.conferir_chave_de_sessao(atrasada, eid) == (0, False)

    assert set(db.execute(select(DispositivoMovel.token_push)).scalars()) == {TOKEN_NOVO}
