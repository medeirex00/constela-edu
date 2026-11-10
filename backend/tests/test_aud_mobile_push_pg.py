"""Os cenários de push e de aparelhos da frente mobile (auditoria técnica) num
PostgreSQL REAL — local e descartável (``TEST_DATABASE_URL_PG``; o nome do banco
precisa conter 'test'). Sobrescreve a fixture ``db`` só neste módulo e reusa os
testes dos módulos SQLite, para as duas execuções afirmarem a mesma coisa; e prova,
pelo próprio PostgreSQL (``pg_stat_activity``), que nenhuma conexão fica "idle in
transaction" enquanto o Expo responde (API_SEGURANCA-6).

Sem ``TEST_DATABASE_URL_PG`` (o job test-backend do CI) o módulo inteiro é pulado.
Dados 100% fictícios; ``httpx.post`` trocado por um falso (sem rede)."""
import os

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.security import hash_senha
from app.main import app
from app.models import DispositivoMovel, Usuario
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


from tests.test_aud_mobile_descadastro_sem_login import (  # noqa: E402,F401
    _limitador_limpo,
    cenario,
    test_limite_de_tentativas_por_ip as test_pg_descadastro_limite,
    test_sair_sem_sessao_descadastra_e_o_push_para as test_pg_descadastro_sem_sessao,
    test_token_desconhecido_tem_a_mesma_resposta_e_nao_apaga_outro
    as test_pg_descadastro_token_desconhecido,
)
from tests.test_aud_mobile_dispositivo_token import (  # noqa: E402,F401
    test_conta_tem_teto_de_aparelhos_e_sai_o_mais_antigo as test_pg_teto_por_conta,
    test_lixo_gravado_antes_nao_vai_ao_expo_e_e_apagado as test_pg_lixo_gravado,
    test_texto_que_nao_e_token_do_expo_e_recusado as test_pg_token_fora_do_formato,
)
from tests.test_aud_mobile_push_transacao import (  # noqa: E402,F401
    test_aviso_de_uma_crianca_tambem_libera_a_transacao as test_pg_transacao_crianca,
    test_token_morto_continua_apagado_depois_da_chamada as test_pg_transacao_mortos,
)


def test_pg_nenhuma_conexao_idle_in_transaction_durante_o_expo(db, escola_completa,
                                                              monkeypatch):
    eid = escola_completa["escola"].id
    u = Usuario(escola_id=eid, nome="Coord Ficticia", email="coord.pg@teste.local",
                senha_hash=hash_senha("Senha-Coord-PG-x"), cargo="coordenador")
    db.add(u)
    db.flush()
    db.add(DispositivoMovel(escola_id=eid, usuario_id=u.id, plataforma="android",
                            token_push="ExponentPushToken[ficticio-pg-0001]"))
    db.commit()
    observador = create_engine(URL)
    estados: list[list[str]] = []

    def post(url, json=None, timeout=None):
        with observador.connect() as c:
            estados.append(list(c.execute(text(
                "SELECT state FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                "AND state = 'idle in transaction'")).scalars()))
        return httpx.Response(200, json={"data": [{"status": "ok"} for _ in json]},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)
    try:
        assert push.notificar_escola(db, eid, "t", "c") == 1
    finally:
        observador.dispose()
    assert estados == [[]], f"conexões presas durante a chamada ao Expo: {estados}"
