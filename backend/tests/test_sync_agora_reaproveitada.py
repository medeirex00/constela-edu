"""POST /sync/agora durante uma coleta em andamento: nenhuma thread extra, e a
resposta diz que o pedido se juntou a uma execução que já existia.

Episódio de 21/10 (escola 17), reproduzido na investigação de 27/10: 7 cliques em
"Sincronizar agora", todos 200, com o Elefante coletando por muito tempo. A rota
disparava uma thread NOVA para cada execução devolvida por ``enfileirar`` —
inclusive a reaproveitada que já estava 'executando' e a que já tinha a thread
dela esperando a vez. Cada thread extra só esperava o semáforo das manuais (1 vaga
por processo) para perder o claim e sair: 11 threads vivas depois de 6 cliques.
E a resposta não dizia que nada novo tinha sido pedido.

Dados 100% fictícios; sem rede (o conector é de mentira).
"""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import app.core.database as dbmod
from app.core.database import Base, get_db
from app.core.security import hash_senha
from app.main import app
from app.models import Escola, Usuario
from app.models.sincronizacao import SincronizacaoExecucao
from app.sync import connectors, service, vault
from app.sync.interfaces import Credenciais, ErroConector
from app.sync.schemas import ExecucaoOut
from app.sync.service import _agora

API = "/api/v1"


def _credenciais(db, escola_id, *plataformas):
    for plat in plataformas:
        vault.salvar_credencial(db, escola_id, plat,
                                Credenciais(usuario="robo-ficticio", senha="valor-ficticio"))
    db.commit()


# --------------------------------------------------------------------------
# Rota (threads trocadas por um registro): quem ganha thread e o que a resposta diz
# --------------------------------------------------------------------------
@pytest.fixture()
def disparos(monkeypatch):
    """Registra cada thread que a rota pediria; o registro de threads vivas do
    processo começa vazio (isolado dos outros testes)."""
    feitos: list[int] = []
    monkeypatch.setattr(service, "disparar_em_thread", feitos.append)
    monkeypatch.setattr(service, "_vivas_neste_processo", set())
    return feitos


def test_clique_durante_coleta_executando_nao_dispara_thread_e_diz_reaproveitada(
        db, escola_completa, cliente, disparos):
    e = escola_completa["escola"].id
    _credenciais(db, e, "elefante")

    r = cliente.post(f"{API}/escolas/{e}/sync/agora?plataforma=elefante")
    assert r.status_code == 200, r.text
    [primeira] = r.json()
    assert disparos == [primeira["id"]]

    ex = db.get(SincronizacaoExecucao, primeira["id"])
    ex.status, ex.iniciada_em = "executando", _agora()      # a coleta longa começou
    db.commit()

    repetidos = []
    for _ in range(3):
        r = cliente.post(f"{API}/escolas/{e}/sync/agora?plataforma=elefante")
        assert r.status_code == 200, r.text
        [dev] = r.json()
        assert dev["id"] == primeira["id"] and dev["status"] == "executando"
        assert disparos == [primeira["id"]]                 # nenhuma thread a mais
        repetidos.append(dev)

    # A resposta diz se o pedido se juntou a uma execução que já existia...
    assert primeira["reaproveitada"] is False
    for dev in repetidos:
        assert dev["reaproveitada"] is True and dev["iniciada_em"] is not None
    # ... num campo ADITIVO: todos os campos de antes continuam na resposta.
    assert set(primeira) == set(ExecucaoOut.model_fields) | {"reaproveitada"}


def test_sincronizar_todas_dispara_so_a_nova_quando_a_outra_esta_executando(
        db, escola_completa, cliente, disparos):
    e = escola_completa["escola"].id
    _credenciais(db, e, "matific", "elefante")
    longa = service.enfileirar(db, e, "elefante", origem="manual")
    longa.status, longa.iniciada_em = "executando", _agora()
    db.commit()

    r = cliente.post(f"{API}/escolas/{e}/sync/agora")

    assert r.status_code == 200, r.text
    por_plat = {x["plataforma"]: x for x in r.json()}
    assert set(por_plat) == {"matific", "elefante"}
    assert por_plat["elefante"]["id"] == longa.id
    assert disparos == [por_plat["matific"]["id"]]
    assert por_plat["elefante"]["reaproveitada"] is True
    assert por_plat["matific"]["reaproveitada"] is False


def test_fila_com_a_thread_dela_neste_processo_nao_ganha_outra(
        db, escola_completa, cliente, disparos):
    """A thread da execução já espera a vez aqui: outra só esperaria junto para
    perder o claim."""
    e = escola_completa["escola"].id
    _credenciais(db, e, "elefante")
    r = cliente.post(f"{API}/escolas/{e}/sync/agora?plataforma=elefante")
    eid = r.json()[0]["id"]
    service._vivas_neste_processo.add(eid)                  # a thread dela espera o semáforo

    r = cliente.post(f"{API}/escolas/{e}/sync/agora?plataforma=elefante")

    assert r.status_code == 200, r.text
    [dev] = r.json()
    assert dev["id"] == eid and dev["status"] == "fila"
    assert disparos == [eid]
    assert dev["reaproveitada"] is True


def test_fila_sem_thread_neste_processo_continua_recebendo_a_sua(
        db, escola_completa, cliente, disparos):
    """Manual recente na fila sem thread AQUI (pedida em outro worker, ou num
    processo que morreu antes de ela virar órfã): este processo ainda dispara a
    sua — o claim decide quem roda (comportamento de antes, preservado)."""
    e = escola_completa["escola"].id
    _credenciais(db, e, "elefante")
    de_outro_worker = service.enfileirar(db, e, "elefante", origem="manual")
    db.commit()

    r = cliente.post(f"{API}/escolas/{e}/sync/agora?plataforma=elefante")

    assert r.status_code == 200, r.text
    [dev] = r.json()
    assert dev["id"] == de_outro_worker.id
    assert disparos == [de_outro_worker.id]
    assert dev["reaproveitada"] is True


# --------------------------------------------------------------------------
# Cliques repetidos durante uma coleta LONGA, com threads e semáforo de verdade
# --------------------------------------------------------------------------
class _SemaforoObservado:
    """Mesma semântica do BoundedSemaphore do service; sabe quem espera a vez."""

    def __init__(self, n=1):
        self._s = threading.BoundedSemaphore(n)
        self.esperando: set[int] = set()
        self._lock = threading.Lock()

    def acquire(self, blocking=True, timeout=None):
        eu = threading.get_ident()
        with self._lock:
            self.esperando.add(eu)
        try:
            if timeout is None:
                return self._s.acquire(blocking)
            return self._s.acquire(blocking, timeout)
        finally:
            with self._lock:
                self.esperando.discard(eu)

    def release(self):
        self._s.release()


class _ConectorDeMentira:
    """Delega ao conector real o que não é coleta (plataforma, estratégia,
    versão). Na coleta, fica PRESO até o teste soltar (``soltar``) ou falha na
    hora: o resultado não importa aqui, só quem roda e quantas threads."""

    def __init__(self, real, soltar: threading.Event | None = None):
        self._real = real
        self._soltar = soltar
        self.presas: set[int] = set()
        self.coletas: list[int] = []

    def __getattr__(self, nome):
        return getattr(self._real, nome)

    async def sincronizar(self, cred, contexto):
        self.coletas.append(contexto.execucao_id)
        if self._soltar is not None:
            eu = threading.get_ident()
            self.presas.add(eu)
            try:
                while not self._soltar.wait(0.01):
                    pass
            finally:
                self.presas.discard(eu)
        raise ErroConector("Falha simulada.", codigo="plataforma_indisponivel",
                           recuperavel=False)


class _Ambiente:
    """Banco SQLite em ARQUIVO (cada thread com a sua conexão, como um worker do
    uvicorn), conectores de mentira e o semáforo observado."""

    def __init__(self, tmp_path, monkeypatch):
        self.engine = create_engine(
            f"sqlite:///{(tmp_path / 'agora.sqlite').as_posix()}", poolclass=NullPool,
            connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(self.engine, "connect")
        def _pragmas(dbapi_conn, _rec):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        Base.metadata.create_all(self.engine)
        self.Sessao = sessionmaker(bind=self.engine, autoflush=False)

        def _get_db():
            s = self.Sessao()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db] = _get_db
        monkeypatch.setattr(dbmod, "SessionLocal", self.Sessao)   # o das threads
        monkeypatch.setattr(service, "_vivas_neste_processo", set())
        self.sem = _SemaforoObservado(1)
        monkeypatch.setattr(service, "_semaforo_manual", self.sem)
        self.soltar = threading.Event()
        self.conectores = {
            "elefante": _ConectorDeMentira(connectors.obter("elefante"), self.soltar),
            "matific": _ConectorDeMentira(connectors.obter("matific")),
        }
        original = connectors.obter
        monkeypatch.setattr(connectors, "obter",
                            lambda p: self.conectores.get(p) or original(p))
        self.disparos: list[int] = []
        disparar = service.disparar_em_thread

        def _disparar(execucao_id):
            self.disparos.append(execucao_id)
            disparar(execucao_id)

        monkeypatch.setattr(service, "disparar_em_thread", _disparar)
        self._threads_antes = set(threading.enumerate())

        with self.Sessao() as s:
            escola = Escola(nome="ESCOLA FICTICIA AGORA", ano_letivo_ativo=2026)
            s.add(escola)
            s.flush()
            s.add(Usuario(escola_id=escola.id, nome="Coord Ficticia",
                          email="coord@agora.local", senha_hash=hash_senha("s3nh4"),
                          cargo="coordenador"))
            _credenciais(s, escola.id, "matific", "elefante")
            self.eid = escola.id
        self.cliente = TestClient(app)
        r = self.cliente.post(f"{API}/auth/login",
                              data={"username": "coord@agora.local", "password": "s3nh4"})
        assert r.status_code == 200, r.text
        self.cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    def threads_sync(self):
        return [t for t in threading.enumerate()
                if t not in self._threads_antes and t.is_alive()
                and t.name.startswith("sync-manual-")]

    def sossegar(self, timeout=30.0):
        """Espera toda thread de sync deste teste ter terminado, estar presa na
        coleta longa ou esperando o semáforo — por 3 leituras seguidas."""
        fim = time.monotonic() + timeout
        estaveis = 0
        while time.monotonic() < fim:
            presas = self.conectores["elefante"].presas
            vivas = self.threads_sync()
            if all(t.ident in presas or t.ident in self.sem.esperando for t in vivas):
                estaveis += 1
                if estaveis >= 3:
                    return vivas
            else:
                estaveis = 0
            time.sleep(0.02)
        raise AssertionError("as threads de sync não sossegaram")

    def execucoes(self):
        with self.Sessao() as s:
            return {e.id: (e.plataforma, e.status) for e in s.execute(
                select(SincronizacaoExecucao).where(
                    SincronizacaoExecucao.escola_id == self.eid)).scalars()}

    def encerrar(self):
        self.soltar.set()
        for t in self.threads_sync():
            t.join(timeout=30)
        app.dependency_overrides.clear()
        self.engine.dispose()


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    a = _Ambiente(tmp_path, monkeypatch)
    yield a
    a.encerrar()


def test_cliques_repetidos_durante_coleta_longa_nao_acumulam_threads(amb):
    """Cenário C da investigação: o Elefante fica preso coletando do 1º ao 6º
    clique em "Sincronizar agora" (sem plataforma). Thread só nasce para execução
    NOVA; as vivas são sempre 1 (a coleta longa) + a da execução que espera a vez.
    Antes: 2 threads por clique, 11 vivas depois de 6 cliques."""
    url = f"{API}/escolas/{amb.eid}/sync/agora"
    novas: list[int] = []
    linha = []
    respostas = []
    for n in range(1, 7):
        antes = amb.execucoes()
        r = amb.cliente.post(url)
        assert r.status_code == 200, r.text
        vivas = amb.sossegar()
        if n == 1:
            assert amb.conectores["elefante"].presas or _esperar(
                lambda: bool(amb.conectores["elefante"].presas))
            vivas = amb.sossegar()
        estados = amb.execucoes()
        na_fila = sum(1 for _p, st in estados.values() if st == "fila")
        for x in r.json():
            if x["id"] not in antes:
                novas.append(x["id"])
        respostas.append((antes, r.json()))
        linha.append({"clique": n, "vivas": len(vivas), "na_fila": na_fila,
                      "disparos": len(amb.disparos), "novas": len(novas),
                      "nomes": sorted(t.name for t in vivas)})
        # Uma thread por execução que ainda precisa rodar — nenhuma duplicada.
        assert amb.disparos == novas, linha
        assert len(vivas) == 1 + na_fila, linha
        assert len({t.name for t in vivas}) == len(vivas), linha
    assert linha[-1]["vivas"] <= 2, linha
    # A resposta diz, por execução, se o pedido se juntou a uma que já existia.
    elefante_id = next(x["id"] for x in respostas[0][1] if x["plataforma"] == "elefante")
    for n, (antes, corpo) in enumerate(respostas, start=1):
        for x in corpo:
            assert x["reaproveitada"] is (x["id"] in antes), (n, x)
        if n > 1:
            el = next(x for x in corpo if x["plataforma"] == "elefante")
            assert el["id"] == elefante_id
            assert el["reaproveitada"] is True and el["status"] == "executando"
    # Durante a coleta longa, o Elefante foi coletado UMA vez (a do 1º clique).
    assert amb.conectores["elefante"].coletas == [elefante_id]

    # A coleta longa termina; o clique seguinte cria as duas e dispara as duas.
    amb.soltar.set()
    for t in amb.threads_sync():
        t.join(timeout=30)
    assert amb.threads_sync() == []
    antes = amb.execucoes()
    r = amb.cliente.post(url)
    assert r.status_code == 200, r.text
    assert all(x["id"] not in antes and x["reaproveitada"] is False for x in r.json())
    assert amb.disparos[-2:] == [x["id"] for x in r.json()]


def _esperar(condicao, segundos=10.0):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicao():
            return True
        time.sleep(0.02)
    return condicao()
