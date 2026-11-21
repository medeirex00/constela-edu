"""Diagnóstico do Elefante: um por escola de cada vez.

Cliques repetidos em "Rodar diagnóstico" abriam um navegador (Chromium) para cada
clique, todos logando com a mesma conta do robô. Agora o segundo pedido da MESMA escola,
com um diagnóstico em andamento, recebe 409 "já existe um diagnóstico em andamento",
sem abrir navegador; outra escola roda normalmente, e a trava sai no fim (também em
erro).

Dados 100% fictícios; o conector é falso (nenhum navegador abre).
"""
import threading

import pytest
from sqlalchemy.orm import Session

from app.models import Escola
from app.sync import connectors, vault
from app.sync import diagnostico_elefante as diag
from app.sync.interfaces import Credenciais, ErroConector

API = "/api/v1"


class _ConectorQueEspera:
    """Segura a coleta até o teste soltar e conta quantas vezes ela começou (cada
    começo seria um navegador aberto)."""

    def __init__(self, escola_bloqueada: int | None = None):
        self.escola_bloqueada = escola_bloqueada
        self.comecos: list[int] = []
        self.comecou = threading.Event()
        self.soltar = threading.Event()

    async def diagnosticar_endpoints(self, cred, contexto):
        self.comecos.append(contexto.escola_id)
        if self.escola_bloqueada is None or contexto.escola_id == self.escola_bloqueada:
            self.comecou.set()
            assert self.soltar.wait(10), "o teste não soltou a coleta"
        return {"ok": True, "turmas": 1, "endpoints": [{"nome": "a", "estrutura": "{x:num}"}]}


@pytest.fixture()
def duas_escolas(db, escola_completa):
    a = escola_completa["escola"]
    b = Escola(nome="ESCOLA FICTICIA DOIS", ano_letivo_ativo=2026)
    db.add(b)
    db.flush()
    for escola in (a, b):
        vault.salvar_credencial(db, escola.id, "elefante",
                                Credenciais(usuario="robo@escola.invalid", senha="ficticia"))
    db.commit()
    return a.id, b.id


def _em_outra_thread(db, eid, saida):
    sessao = Session(bind=db.get_bind())
    try:
        saida["resultado"] = diag.executar(sessao, eid)
    except BaseException as exc:  # noqa: BLE001 — o teste confere
        saida["erro"] = exc
    finally:
        sessao.close()


def test_segundo_pedido_da_mesma_escola_nao_abre_outro_navegador(db, duas_escolas,
                                                                 monkeypatch):
    a, b = duas_escolas
    con = _ConectorQueEspera()
    monkeypatch.setattr(connectors, "obter", lambda p: con if p == "elefante" else None)
    saida: dict = {}
    primeiro = threading.Thread(target=_em_outra_thread, args=(db, a, saida))
    primeiro.start()
    try:
        assert con.comecou.wait(10)
        with pytest.raises(ErroConector) as exc:
            diag.executar(db, a)
        # Antes: o segundo clique abria outro navegador (comecos == [a, a]).
        assert exc.value.codigo == "ocupado" and exc.value.recuperavel is True
        assert "em andamento" in str(exc.value)
        assert con.comecos == [a]
    finally:
        con.soltar.set()
        primeiro.join(10)
    assert "erro" not in saida, saida
    assert saida["resultado"]["inventario"]["ok"] is True

    # Terminado, a trava saiu: a mesma escola roda de novo, e a outra também.
    assert diag.executar(db, a)["inventario"]["ok"] is True
    assert diag.executar(db, b)["inventario"]["ok"] is True
    assert con.comecos == [a, a, b]


def test_outra_escola_roda_durante_o_diagnostico_de_uma(db, duas_escolas, monkeypatch):
    a, b = duas_escolas
    con = _ConectorQueEspera(escola_bloqueada=a)
    monkeypatch.setattr(connectors, "obter", lambda p: con if p == "elefante" else None)
    saida: dict = {}
    primeiro = threading.Thread(target=_em_outra_thread, args=(db, a, saida))
    primeiro.start()
    try:
        assert con.comecou.wait(10)
        # A primeira escola segue no conector enquanto a segunda grava. A fixture
        # usa uma única conexão SQLite em memória para as duas sessões.
        assert diag.executar(db, b)["inventario"]["ok"] is True
        assert primeiro.is_alive()
    finally:
        con.soltar.set()
        primeiro.join(10)
    assert "erro" not in saida, saida
    assert saida["resultado"]["inventario"]["ok"] is True
    assert con.comecos == [a, b]


def test_falha_na_coleta_solta_a_trava(db, duas_escolas, monkeypatch):
    a, _b = duas_escolas

    class _Falha:
        async def diagnosticar_endpoints(self, cred, contexto):
            raise ErroConector("CAPTCHA fictício", codigo="captcha", recuperavel=True)

    monkeypatch.setattr(connectors, "obter", lambda p: _Falha() if p == "elefante" else None)
    for _ in range(2):            # a segunda não fica "ocupado" pela primeira
        with pytest.raises(ErroConector) as exc:
            diag.executar(db, a)
        assert exc.value.codigo == "captcha"


def test_rota_responde_409_com_um_diagnostico_em_andamento(cliente, db, duas_escolas,
                                                          monkeypatch):
    a, _b = duas_escolas
    con = _ConectorQueEspera()
    monkeypatch.setattr(connectors, "obter", lambda p: con if p == "elefante" else None)
    saida: dict = {}
    primeiro = threading.Thread(target=_em_outra_thread, args=(db, a, saida))
    primeiro.start()
    try:
        assert con.comecou.wait(10)
        r = cliente.post(f"{API}/escolas/{a}/sync/elefante/diagnostico")
        assert r.status_code == 409, r.text
        detalhe = r.json()["detail"]
        assert "em andamento" in detalhe
        # REV2-SYNC2-3: quem recebe o 409 é OUTRA aba, outra pessoa ou quem recarregou
        # a página — o diagnóstico só tem o POST (nenhum GET do último inventário) e a
        # tela só mostra a resposta do PRÓPRIO pedido. O texto não pode prometer "veja
        # o resultado" do que está rodando: diz que ele não aparece ali e manda rodar de
        # novo depois (o novo diagnóstico compara com o último inventário gravado).
        assert "veja o resultado" not in detalhe.lower(), detalhe
        assert "O resultado dele não aparece aqui" in detalhe, detalhe
        assert "aguarde alguns minutos e rode de novo" in detalhe, detalhe
        assert "o novo diagnóstico mostra o que mudou desde o último" in detalhe, detalhe
    finally:
        con.soltar.set()
        primeiro.join(10)
    assert con.comecos == [a]


def test_rota_do_diagnostico_so_tem_o_post():
    """Premissa do texto do 409 (REV2-SYNC2-3): não há rota que mostre o resultado do
    diagnóstico de outro pedido. Se um GET do último inventário surgir, o texto do
    ``_OCUPADO`` pode voltar a apontar para ele."""
    from app.sync.router import router
    metodos = {m for rota in router.routes
               if getattr(rota, "path", "").endswith("/elefante/diagnostico")
               for m in getattr(rota, "methods", set())}
    assert metodos == {"POST"}, metodos


# --- Entre workers (PostgreSQL): o advisory lock ------------------------------
@pytest.fixture()
def motor_pg():
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    url = os.environ.get("TEST_DATABASE_URL_PG")
    if not url:
        pytest.skip("defina TEST_DATABASE_URL_PG para rodar contra PostgreSQL real")
    u = make_url(url)
    if "test" not in (u.database or "").lower() or u.host not in ("127.0.0.1", "localhost",
                                                                   "::1"):
        pytest.skip("só PostgreSQL LOCAL de teste")
    motor = create_engine(url)
    yield motor
    motor.dispose()


@pytest.mark.postgres
def test_outro_worker_com_o_diagnostico_da_escola_recebe_ocupado(motor_pg, monkeypatch):
    from sqlalchemy import text

    monkeypatch.setattr(diag, "engine", motor_pg)
    with motor_pg.connect() as outro_worker:
        assert outro_worker.execute(text("SELECT pg_try_advisory_lock(:ns, :k)"),
                                    {"ns": diag._LOCK_NS, "k": 7}).scalar() is True
        with pytest.raises(ErroConector) as exc:
            with diag._um_por_escola(7):
                pytest.fail("entrou com o diagnóstico do outro worker em andamento")
        assert exc.value.codigo == "ocupado"
        # A trava deste processo saiu junto (o próximo pedido não fica preso nela).
        assert diag._trava_da_escola(7).acquire(blocking=False)
        diag._trava_da_escola(7).release()
        outro_worker.execute(text("SELECT pg_advisory_unlock(:ns, :k)"),
                             {"ns": diag._LOCK_NS, "k": 7})
        outro_worker.commit()

    with diag._um_por_escola(7):
        # Durante o robô, a conexão da trava não fica "idle in transaction".
        with motor_pg.connect() as c:
            estados = c.execute(text(
                "SELECT state FROM pg_stat_activity a JOIN pg_locks l ON l.pid = a.pid "
                "WHERE l.locktype = 'advisory' AND l.classid = :ns AND l.objid = :k"),
                {"ns": diag._LOCK_NS, "k": 7}).scalars().all()
        assert estados == ["idle"], estados
    with motor_pg.connect() as c:                 # e no fim a trava saiu
        assert c.execute(text("SELECT pg_try_advisory_lock(:ns, :k)"),
                         {"ns": diag._LOCK_NS, "k": 7}).scalar() is True
        c.execute(text("SELECT pg_advisory_unlock(:ns, :k)"), {"ns": diag._LOCK_NS, "k": 7})
        c.commit()
