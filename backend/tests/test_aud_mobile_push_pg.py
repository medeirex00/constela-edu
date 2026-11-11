"""Os cenários de push e de aparelhos da frente mobile (auditoria técnica) num
PostgreSQL REAL — local e descartável (``TEST_DATABASE_URL_PG``; o nome do banco
precisa conter 'test'). Sobrescreve a fixture ``db`` só neste módulo e reusa os
testes dos módulos SQLite, para as duas execuções afirmarem a mesma coisa; e prova,
pelo próprio PostgreSQL (``pg_stat_activity``), que nenhuma conexão fica "idle in
transaction" enquanto o Expo responde (API_SEGURANCA-6), e que registros simultâneos
da mesma conta não deixam a conta acima do teto de aparelhos (REV-MOBILE-1).

Sem ``TEST_DATABASE_URL_PG`` (o job test-backend do CI) o módulo inteiro é pulado.
Dados 100% fictícios; ``httpx.post`` trocado por um falso (sem rede)."""
import os
import threading

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.security import hash_senha
from app.main import app
from app.models import DispositivoMovel, Usuario
from app.routers import mobile
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


# --- Teto de aparelhos sob registros em paralelo da mesma conta (REV-MOBILE-1) ---
# Cada registro grava o próprio aparelho e só depois conta os da conta. No
# PostgreSQL (READ COMMITTED) uma requisição não vê o que as outras gravaram e ainda
# não confirmaram: registros simultâneos da mesma conta (o script do achado) passavam
# todos do corte, e a conta ficava acima do teto para sempre.

def _token_da_conta(cliente_http) -> str:
    r = cliente_http.post("/api/v1/auth/login",
                          data={"username": "admin@teste.local", "password": "s3nh4"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _registrar_em_paralelo(eid: int, jwt: str, quantos: int, prefixo: str) -> list[int]:
    largada = threading.Barrier(quantos)
    codigos: list[int] = []

    def registrar(i: int) -> None:
        cli = TestClient(app)
        cli.headers["Authorization"] = f"Bearer {jwt}"
        largada.wait()
        resp = cli.post(f"/api/v1/escolas/{eid}/dispositivos",
                        json={"token_push": f"ExponentPushToken[{prefixo}-{i:04d}]",
                              "plataforma": "android"})
        codigos.append(resp.status_code)

    fios = [threading.Thread(target=registrar, args=(i,)) for i in range(quantos)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join(timeout=120)
    return codigos


def _aparelhos_da_conta(db, usuario_id: int) -> int:
    db.expire_all()
    return db.query(DispositivoMovel).filter(DispositivoMovel.usuario_id == usuario_id).count()


def test_pg_registros_simultaneos_da_mesma_conta_respeitam_o_teto(db, escola_completa,
                                                                 monkeypatch):
    """Determinístico: todos os registros contam os aparelhos da conta antes de
    qualquer um confirmar (uma barreira logo depois da contagem). Sem a serialização
    por conta, cada um só via o próprio aparelho e ninguém era cortado; com ela, um
    registro por vez faz a contagem (a barreira desiste no prazo) e vê os anteriores
    já confirmados."""
    eid = escola_completa["escola"].id
    admin = escola_completa["admin"]
    teto = mobile.MAX_APARELHOS_POR_CONTA
    quantos = teto + 3
    juntos = threading.Barrier(quantos, timeout=3)
    corte_original = mobile._aparelhos_alem_do_teto

    def corte_depois_de_todos(*args, **kwargs):
        excedentes = corte_original(*args, **kwargs)
        try:
            juntos.wait()
        except threading.BrokenBarrierError:
            pass  # serializado: nunca chegam todos ao mesmo tempo
        return excedentes

    monkeypatch.setattr(mobile, "_aparelhos_alem_do_teto", corte_depois_de_todos)
    codigos = _registrar_em_paralelo(eid, _token_da_conta(TestClient(app)), quantos,
                                     "juntos")
    assert codigos == [200] * quantos, codigos
    n = _aparelhos_da_conta(db, admin.id)
    assert n <= teto, f"{n} aparelhos na conta depois de {quantos} registros (teto {teto})"


def test_pg_rajada_de_registros_da_mesma_conta_nao_passa_do_teto(db, escola_completa):
    """A rajada do script do achado, sem ajuda: 40 registros liberados juntos."""
    eid = escola_completa["escola"].id
    admin = escola_completa["admin"]
    codigos = _registrar_em_paralelo(eid, _token_da_conta(TestClient(app)), 40, "rajada")
    assert set(codigos) == {200}, sorted(set(codigos))
    n = _aparelhos_da_conta(db, admin.id)
    assert n <= mobile.MAX_APARELHOS_POR_CONTA, f"{n} aparelhos depois da rajada"
