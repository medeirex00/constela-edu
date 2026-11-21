"""Rajada de logins errados num PostgreSQL REAL, com atraso de rede no meio (G_CARGA-1).

Antes: cada falha do /auth/login (e do login por código do Quest) era contada DENTRO da
transação da requisição — UPDATE na linha do teto global, SELECT, INSERT da auditoria e
COMMIT —, com a trava da linha global presa por várias idas ao banco. Todas as falhas da
API passavam em fila por essa linha única; cada pedido esperava segurando uma thread e
uma conexão do pool. Com a API a ~195 ms do banco, 240 logins errados (abaixo dos tetos)
deixavam as sessões JÁ ABERTAS esperando até 75 s por requisição.

Agora a falha é contada numa única instrução atômica, em AUTOCOMMIT e fora da transação
da requisição (a trava da linha dura só a execução da instrução), com ``lock_timeout``
curto; e o /auth/login tem um limite de pedidos simultâneos por processo (acima dele,
429 na hora, sem tocar no banco).

O banco fica atrás de um proxy local que atrasa cada pedaço de dado nos dois sentidos
(latência, não banda). O app roda no MESMO event loop do teste (``httpx.ASGITransport``):
as rotas síncronas dividem o mesmo limite de threads do anyio, como num worker uvicorn.
Um "canário" com sessão aberta chama /auth/me durante a rajada. Dados fictícios: contas
inexistentes, IPs de documentação (RFC 5737)."""
import asyncio
import logging
import os
import threading
import time

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.security import criar_token
from app.main import app
from app.models import Usuario
from app.quest.models import QuestLimiteAcesso

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]

API = "/api/v1"
# Atraso em CADA sentido: uma ida e volta ao banco custa ~2x isto (produção: ~195 ms).
ATRASO_S = 0.025
RAJADA = 120
# O canário (sessão aberta) não pode esperar mais que isto durante a rajada. Antes da
# correção ele esperava a fila inteira das falhas (dezenas de segundos).
TETO_CANARIO_S = 3.0
# No Quest não há portão de pedidos simultâneos (decisão pendente do dono: crianças
# entrando juntas no começo da aula): a rajada ainda disputa as 40 threads e o canário
# espera a vez dele nessa fila — mas não mais a fila da trava da linha global, que o
# levava a ~12 s com estes mesmos números.
TETO_CANARIO_QUEST_S = 5.0
# Quanto a outra transação segura a linha global no teste do ``lock_timeout``.
SEGURA_S = 5.0


class _ProxyComAtraso:
    """Proxy TCP em 127.0.0.1 (porta escolhida pelo sistema) que entrega cada pedaço
    ``atraso`` segundos depois de chegar, nos dois sentidos. Não lê nem guarda nada."""

    def __init__(self, host: str, porta: int, atraso: float) -> None:
        self.host, self.porta, self.atraso = host, porta, atraso
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True,
                                        name="proxy-com-atraso")
        self._escritores: set = set()
        self._servidor = None

    def iniciar(self) -> int:
        self._thread.start()
        return asyncio.run_coroutine_threadsafe(self._abrir(), self._loop).result(10)

    async def _abrir(self) -> int:
        self._servidor = await asyncio.start_server(self._atender, "127.0.0.1", 0)
        return self._servidor.sockets[0].getsockname()[1]

    async def _atender(self, cli_r, cli_w) -> None:
        try:
            srv_r, srv_w = await asyncio.open_connection(self.host, self.porta)
        except OSError:
            cli_w.close()
            return
        self._escritores.update((cli_w, srv_w))
        await asyncio.gather(self._bombear(cli_r, srv_w), self._bombear(srv_r, cli_w),
                             return_exceptions=True)

    async def _bombear(self, leitor, escritor) -> None:
        fila: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        async def ler():
            try:
                while True:
                    dado = await leitor.read(65536)
                    await fila.put((loop.time() + self.atraso, dado))
                    if not dado:
                        return
            except OSError:
                await fila.put((loop.time(), b""))

        async def escrever():
            while True:
                quando, dado = await fila.get()
                espera = quando - loop.time()
                if espera > 0:
                    await asyncio.sleep(espera)
                if not dado:
                    escritor.close()
                    return
                try:
                    escritor.write(dado)
                    await escritor.drain()
                except OSError:
                    return

        await asyncio.gather(ler(), escrever(), return_exceptions=True)

    async def _fechar(self) -> None:
        if self._servidor is not None:
            self._servidor.close()
        for escritor in list(self._escritores):
            escritor.close()
        pendentes = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for tarefa in pendentes:
            tarefa.cancel()
        await asyncio.gather(*pendentes, return_exceptions=True)

    def parar(self) -> None:
        asyncio.run_coroutine_threadsafe(self._fechar(), self._loop).result(10)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(10)
        self._loop.close()


@pytest.fixture()
def db():
    """O banco PG direto (sem atraso), para montar o cenário e conferir o resultado."""
    engine = create_engine(URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()
    yield sessao
    sessao.close()
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def app_com_banco_lento(db):
    """O app falando com o banco pelo proxy com atraso, com o pool de produção
    (10 + 20 por worker)."""
    url = make_url(URL)
    proxy = _ProxyComAtraso(url.host or "127.0.0.1", url.port or 5432, ATRASO_S)
    porta = proxy.iniciar()
    lento = create_engine(url.set(host="127.0.0.1", port=porta), pool_size=10,
                          max_overflow=20, pool_timeout=30)
    Sessao = sessionmaker(bind=lento, autoflush=False, autocommit=False)

    def _get_db():
        sessao = Sessao()
        try:
            yield sessao
        finally:
            sessao.close()

    app.dependency_overrides[get_db] = _get_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        lento.dispose()
        proxy.parar()


def _rajada_com_canario(token: str, pedido) -> tuple[list[int], list[tuple[int, float]]]:
    """Dispara ``RAJADA`` pedidos de uma vez (``pedido(cliente, i)``) enquanto um canário
    com sessão aberta chama /auth/me sem parar. Devolve os status da rajada e
    (status, segundos) de cada chamada do canário."""

    async def cenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://teste", timeout=300) as cli:
            cabecalho = {"Authorization": f"Bearer {token}"}
            assert (await cli.get(f"{API}/auth/me", headers=cabecalho)).status_code == 200
            fim = asyncio.Event()
            medidas: list[tuple[int, float]] = []

            async def canario():
                while not fim.is_set():
                    inicio = time.monotonic()
                    r = await cli.get(f"{API}/auth/me", headers=cabecalho)
                    medidas.append((r.status_code, time.monotonic() - inicio))
                    await asyncio.sleep(0.05)

            tarefa = asyncio.create_task(canario())
            await asyncio.sleep(0)
            try:
                respostas = await asyncio.gather(*(pedido(cli, i) for i in range(RAJADA)))
            finally:
                fim.set()
                await tarefa
            return [r.status_code for r in respostas], medidas

    return asyncio.run(cenario())


def _sessao_aberta(db, escola_completa) -> str:
    admin = db.execute(select(Usuario).where(
        Usuario.escola_id == escola_completa["escola"].id)).scalars().first()
    return criar_token(admin.id, admin.token_version)


def test_rajada_de_logins_errados_nao_para_as_sessoes_abertas(db, escola_completa,
                                                            app_com_banco_lento):
    """O cenário da auditoria: logins errados simultâneos de 3 IPs (40 por IP, abaixo do
    teto de 50; 120 no total, abaixo do global de 400) contra contas inexistentes."""
    token = _sessao_aberta(db, escola_completa)

    async def login_errado(cli, i):
        return await cli.post(f"{API}/auth/login",
                              data={"username": f"ninguem.{i}@teste.local",
                                    "password": "Senha-Errada-2026"},
                              headers={"X-Forwarded-For": f"198.51.100.{i % 3 + 1}"})

    codigos, canario = _rajada_com_canario(token, login_errado)

    assert set(codigos) <= {401, 429}, sorted(set(codigos))
    assert canario and all(status == 200 for status, _ in canario), canario
    pior = max(segundos for _, segundos in canario)
    assert pior < TETO_CANARIO_S, (
        f"a sessão aberta esperou {pior:.1f} s durante a rajada "
        f"(401: {codigos.count(401)}, 429: {codigos.count(429)})")
    # Cada login avaliado e recusado (401) foi contado uma vez no teto global do banco.
    db.expire_all()
    globais = db.execute(select(QuestLimiteAcesso.falhas).where(
        QuestLimiteAcesso.chave.like("edu_login_global_falha:%"))).scalars().all()
    assert globais == [codigos.count(401)]


def test_teto_do_ip_vale_para_logins_simultaneos(db, escola_completa, app_com_banco_lento,
                                               monkeypatch):
    """G_CARGA-3: 120 logins errados SIMULTÂNEOS de um IP só, cada um numa conta
    diferente (pulverização). Antes o teto era conferido no começo e a falha contada
    no fim: todo pedido que passava pelo portão antes de a 50ª falha ser gravada
    seguia até o bcrypt, e bem mais de 50 palpites eram avaliados (108 medidos em
    produção simulada, com 2 workers). Agora a tentativa é RESERVADA no banco antes de
    procurar a conta: no máximo 50 são avaliadas, e cada uma conta uma vez.

    O portão de logins simultâneos fica aberto aqui (1000 vagas) para medir só o teto
    do IP."""
    from app.core import rate_limit

    monkeypatch.setattr(rate_limit.portao_login, "vagas", 1000)
    teto = rate_limit.limitador_ip_falha_login.max_tentativas

    async def cenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://teste", timeout=300) as cli:
            async def um(i):
                r = await cli.post(f"{API}/auth/login",
                                   data={"username": f"pulverizada.{i}@teste.local",
                                         "password": "Senha-Errada-2026"},
                                   headers={"X-Forwarded-For": "198.51.100.200"})
                return r.status_code
            return await asyncio.gather(*(um(i) for i in range(RAJADA)))

    codigos = asyncio.run(cenario())

    assert set(codigos) <= {401, 429}, sorted(set(codigos))
    avaliados = codigos.count(401)
    assert avaliados <= teto, f"{avaliados} palpites avaliados de um IP só (teto {teto})"
    db.expire_all()
    por_dimensao = {chave.split(":", 1)[0]: falhas for chave, falhas in db.execute(
        select(QuestLimiteAcesso.chave, QuestLimiteAcesso.falhas)).all()}
    # Cada palpite avaliado contou uma vez; os recusados (429) não contaram.
    assert por_dimensao == {"edu_login_ip_falha": avaliados,
                            "edu_login_global_falha": avaliados}


def test_login_certo_devolve_a_vaga_reservada(db, escola_completa, app_com_banco_lento):
    """No PostgreSQL também: a vaga reservada pelo login certo volta (só falhas contam),
    e a do palpite errado fica."""
    async def cenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://teste") as cli:
            codigos = []
            for senha in ("Senha-Errada-2026", "s3nh4", "s3nh4"):
                r = await cli.post(f"{API}/auth/login",
                                   data={"username": "admin@teste.local", "password": senha},
                                   headers={"X-Forwarded-For": "192.0.2.71"})
                codigos.append(r.status_code)
            return codigos

    assert asyncio.run(cenario()) == [401, 200, 200]
    db.expire_all()
    por_dimensao = {chave.split(":", 1)[0]: (falhas, ate) for chave, falhas, ate in db.execute(
        select(QuestLimiteAcesso.chave, QuestLimiteAcesso.falhas,
               QuestLimiteAcesso.bloqueado_ate)).all()}
    assert por_dimensao == {"edu_login_ip_falha": (1, None),
                            "edu_login_global_falha": (1, None)}


def test_linha_global_presa_por_outra_transacao_nao_segura_o_login(
        db, escola_completa, app_com_banco_lento, caplog):
    """``lock_timeout`` da contagem: outra transação segura a linha do teto global por
    alguns segundos; o login errado responde 401 sem esperar por ela (a falha fica só
    na memória deste processo) e sai um aviso no log."""
    from app.core import rate_limit
    from app.quest.services import limites

    caplog.set_level(logging.WARNING, logger="constela.limites")
    limites._ultimo_aviso[0] = float("-inf")
    transporte = httpx.ASGITransport(app=app)

    async def um(i):
        async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as c:
            inicio = time.monotonic()
            r = await c.post(f"{API}/auth/login",
                             data={"username": f"presa.{i}@teste.local",
                                   "password": "Senha-Errada-2026"},
                             headers={"X-Forwarded-For": "192.0.2.44"})
            return r.status_code, time.monotonic() - inicio

    assert asyncio.run(um(0))[0] == 401            # cria a linha global no banco
    outra = create_engine(URL)
    conexao = outra.connect()
    transacao = conexao.begin()
    conexao.execute(select(QuestLimiteAcesso.id).where(
        QuestLimiteAcesso.chave.like("edu_login_global_falha:%")).with_for_update()).all()
    soltar = threading.Timer(SEGURA_S, transacao.rollback)
    soltar.start()
    try:
        status, segundos = asyncio.run(um(1))
    finally:
        soltar.cancel()
        transacao.rollback()
        conexao.close()
        outra.dispose()
    assert status == 401
    assert segundos < SEGURA_S - 1, f"o login esperou a linha presa: {segundos:.1f} s"
    assert rate_limit.limitador_global_falha_login.falhas_na_janela("*") == 2
    assert [x for x in caplog.records
            if getattr(x, "evento", None) == "limites.contagem_sem_trava"]
    db.expire_all()
    assert db.execute(select(QuestLimiteAcesso.falhas).where(
        QuestLimiteAcesso.chave.like("edu_login_global_falha:%"))).scalar_one() == 1


def test_rajada_de_codigos_errados_do_quest_nao_para_as_sessoes_abertas(
        db, escola_completa, app_com_banco_lento):
    """O login por código do Quest conta as falhas na mesma tabela, com uma linha global
    do Quest: a mesma fila, a mesma correção."""
    token = _sessao_aberta(db, escola_completa)

    async def codigo_errado(cli, i):
        return await cli.post(f"{API}/quest/auth/quem",
                              json={"codigo": f"NAOEXISTE{i:04d}"},
                              headers={"X-Forwarded-For": f"203.0.113.{i % 3 + 1}"})

    codigos, canario = _rajada_com_canario(token, codigo_errado)

    assert set(codigos) <= {401, 429}, sorted(set(codigos))
    assert canario and all(status == 200 for status, _ in canario), canario
    pior = max(segundos for _, segundos in canario)
    assert pior < TETO_CANARIO_QUEST_S, (
        f"a sessão aberta esperou {pior:.1f} s durante a rajada do Quest "
        f"(401: {codigos.count(401)}, 429: {codigos.count(429)})")
