"""Infra compartilhada dos testes: banco em memória e API autenticada."""
import io
import logging
import os
import shutil
import sys
import tempfile

# Sem saída para a internet a partir do runner: o app.main dispara no import o
# diagnóstico do robô (GET a ipinfo.io/ipapi.co e o Chromium abrindo as páginas de
# login). Antes de QUALQUER import do app: o Settings lê o ambiente uma vez, no import
# de app.core.config. Os subprocessos dos testes herdam o valor.
os.environ["AUTOMACAO_VERIFICAR_NO_BOOT"] = "false"

# As pastas que a API grava (UPLOADS_DIR, EXPORTS_DIR) numa pasta temporária da sessão,
# nunca no checkout. Sem DADOS_DIR elas seriam <raiz do repositório>/uploads e /exports —
# onde ficam as entregas do dono —, e o expurgo de fundo (app/core/expurgo_arquivos.py)
# roda em todo boot do app, isto é, em todo ``with TestClient(app)``; e toda exportação de
# teste deixaria lá uma cópia. As duas explícitas, e não DADOS_DIR: um UPLOADS_DIR ou
# EXPORTS_DIR do .env de quem roda ganharia de DADOS_DIR. Antes de QUALQUER import do app,
# pelo mesmo motivo de acima; os subprocessos dos testes herdam. Apagada no fim da sessão
# (``pytest_unconfigure``). Quem precisa de pastas próprias continua trocando as duas no
# ``settings`` com monkeypatch.
_PASTA_DE_DADOS_DA_SESSAO = tempfile.mkdtemp(prefix="constela-testes-dados-")
os.environ["UPLOADS_DIR"] = os.path.join(_PASTA_DE_DADOS_DA_SESSAO, "uploads")
os.environ["EXPORTS_DIR"] = os.path.join(_PASTA_DE_DADOS_DA_SESSAO, "exports")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno,
    Configuracao,
    Escola,
    Matricula,
    NivelDificuldade,
    ReferenciaNormalizacao,
    Turma,
    Usuario,
)
from app.services import scoring
from tests._ano_letivo import ANO_DAS_DATAS_FIXAS


def pytest_configure(config):
    """Marcador dos testes que exigem PostgreSQL de verdade (corrida entre
    transações — o SQLite de um escritor só esconderia). Pulam sozinhos sem
    ``TEST_DATABASE_URL_PG``; rodar só eles: ``pytest -m postgres``."""
    config.addinivalue_line(
        "markers", "postgres: exige PostgreSQL real (TEST_DATABASE_URL_PG)")


def _retrato_do_logging() -> list:
    """Handlers, nível, propagate e disabled da raiz e de cada logger já criado."""
    loggers = [logging.getLogger()] + [
        lg for lg in list(logging.root.manager.loggerDict.values())
        if isinstance(lg, logging.Logger)]
    return [(lg, list(lg.handlers), lg.level, lg.propagate, lg.disabled) for lg in loggers]


def _restaurar_logging(retrato: list) -> None:
    for lg, handlers, nivel, propaga, desligado in retrato:
        if lg.handlers != handlers:
            lg.handlers[:] = handlers
        if lg.level != nivel:
            lg.setLevel(nivel)                     # setLevel também limpa o cache de nível
        lg.propagate, lg.disabled = propaga, desligado


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    """O logging do processo volta, depois de CADA teste, ao que era antes dele.

    Quem roda o Alembic pelo alembic.ini (``migracoes._config()`` + ``command.upgrade``:
    test_alembic, test_0039_execucao_contabilidade, test_quest_codigo_hash,
    test_desempenho_por_dimensao, ``_infra_comum.levar_a``...) faz o env.py chamar
    ``fileConfig(alembic.ini, disable_existing_loggers=False)``, que fecha e tira os
    handlers da raiz, instala um ``StreamHandler(sys.stderr)`` em texto e baixa a raiz
    para WARNING. Isso ficava pelo resto da sessão e vazava para os testes seguintes.
    Este hook resolve SÓ esse vazamento. O diagnóstico perdido no fim da sessão de
    28/10 é outra coisa (o handler preso ao stream da captura, que o pytest fecha) e
    quem resolve é o ``pytest_unconfigure`` abaixo: devolver à raiz o ``SaidaDoLog`` do
    app não basta, porque ele também escreve no stream da captura.

    Em volta do PROTOCOLO do teste (setup, chamada e teardown), e não numa fixture
    autouse de função: o retrato é tirado antes de QUALQUER fixture do teste — também
    as de módulo/sessão que nascem no setup dele — e devolvido depois do teardown, então
    nem um fileConfig dentro de fixture de escopo maior vaza. Os handlers de captura do
    pytest (caplog e relatório) são os mesmos objetos a sessão inteira (pytest 8):
    entram no retrato e voltam iguais, e dentro do teste o caplog funciona como sempre."""
    retrato = _retrato_do_logging()
    try:
        return (yield)
    finally:
        _restaurar_logging(retrato)


def pytest_unconfigure(config):
    """Os handlers de log que escrevem num stream da captura passam a escrever no stderr
    REAL antes de o pytest fechar a captura.

    O ``SaidaDoLog`` do app nasce no import do ``app.main`` por este conftest, com a
    captura global já ligada: o stream dele é o ``sys.stdout`` DA CAPTURA. O pytest fecha
    esse stream no último cleanup da sessão (``stop_global_capturing``, registrado antes
    de qualquer conftest), DEPOIS deste hook. Uma exceção que sobe depois disso — de um
    ``config.add_cleanup``, ou do ``pytest_sessionfinish`` como em 28/10
    (``cleanup_dead_symlinks`` com PermissionError nos links ``*current`` do basetemp) —
    chega ao ``sys.excepthook`` do app, que loga ``excecao_nao_tratada`` no stream
    fechado: saía só "<falha ao escrever o log de constela: ValueError>" (ou
    "--- Logging error ---"), e a causa sumia. Aqui o stream ainda está aberto: o que já
    está nele sai no fim, como sempre, e o que vier depois vai para ``sys.__stderr__``,
    que o pytest nunca fecha. FileHandler fica como está (tem arquivo próprio), e um
    buffer em memória (o do caplog) não é stream da captura."""
    shutil.rmtree(_PASTA_DE_DADOS_DA_SESSAO, ignore_errors=True)
    stderr_real = sys.__stderr__
    if stderr_real is None:                        # pythonw: não há para onde mandar
        return
    loggers = [logging.getLogger()] + [
        lg for lg in list(logging.root.manager.loggerDict.values())
        if isinstance(lg, logging.Logger)]
    for lg in loggers:
        for h in list(lg.handlers):
            if (not isinstance(h, logging.StreamHandler) or isinstance(h, logging.FileHandler)
                    or isinstance(h.stream, io.StringIO)
                    or h.stream in (sys.__stdout__, stderr_real)):
                continue
            try:
                h.setStream(stderr_real)
            except Exception:  # noqa: BLE001 — stream já fechado: o flush do setStream falha
                h.stream = stderr_real


@pytest.fixture(autouse=True)
def _reset_estado_global():
    """Zera estado global em memória (singletons por processo) antes de cada
    teste — limitadores de tentativa e o cache do painel público, cujo escopo
    por escola_id (=1 nos testes) vazaria entre testes."""
    from app.core import rate_limit
    from app.quest.routers import auth as quest_auth
    from app.routers import publico

    for lim in (rate_limit.limitador_login, rate_limit.limitador_conta,
                rate_limit.limitador_ip_falha_login,
                rate_limit.limitador_global_falha_login,
                rate_limit.alerta_global_login,
                *quest_auth._DIMENSOES.values(), quest_auth._alerta_global):
        lim._eventos.clear()
    publico._cache_painel.clear()
    publico._cache_visiveis.clear()
    yield


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # todas as sessões enxergam o mesmo banco em memória
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec):
        # Integridade referencial LIGADA como em produção (Postgres) e no engine
        # da aplicação (database.py). Sem isto, a suíte inteira rodaria com a
        # checagem DESLIGADA (default do SQLite) e deixaria passar violações de
        # FK que o banco de produção rejeitaria.
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    # create_all é o atalho RÁPIDO; test_alembic garante que o schema que ele
    # monta é idêntico ao das migrações Alembic (o de produção).
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


@pytest.fixture()
def ano_letivo_da_escola() -> int:
    """O ano letivo da ``escola_completa``: o do mundo de datas fixas em que a suíte foi
    escrita (``tests._ano_letivo.ANO_DAS_DATAS_FIXAS``) — Listas Piloto "de 2026",
    retratos de março, relógios presos em 20/10/2026 —, que vale em qualquer ano.

    O módulo (ou o teste) que grava retratos e leituras "agora" sobrescreve esta fixture
    com o ano de HOJE (``tests._ano_letivo.escola_no_ano_de_hoje``): senão, a partir de
    01/01 do ano seguinte, o dado de agora fica fora do ano letivo da escola (TESTES-1)."""
    return ANO_DAS_DATAS_FIXAS


@pytest.fixture()
def escola_completa(db, ano_letivo_da_escola):
    """Escola com admin, turma, alunos e configurações padrão, no ano letivo
    ``ano_letivo_da_escola``."""
    ano = ano_letivo_da_escola
    escola = Escola(nome="ESCOLA TESTE", ano_letivo_ativo=ano)
    db.add(escola)
    db.flush()

    admin = Usuario(escola_id=escola.id, nome="Admin", email="admin@teste.local",
                    senha_hash=hash_senha("s3nh4"), cargo="admin")
    db.add(admin)

    for namespace, valores in scoring.PESOS_PADRAO.items():
        db.add(Configuracao(escola_id=escola.id, namespace=namespace,
                            chave="valores", valor=valores))
    db.add(NivelDificuldade(escola_id=escola.id, nome="Pré-Leitor",
                            codigo="pre_leitor", codigos=["AA", "BB"],
                            pontos_padrao=1.0, ordem=0))
    db.add(NivelDificuldade(escola_id=escola.id, nome="Nível 2",
                            codigo="nivel_2", codigos=["D", "E"],
                            pontos_padrao=4.0, ordem=1))
    db.add(ReferenciaNormalizacao(escola_id=escola.id, modo="auto"))

    turma = Turma(escola_id=escola.id, nome="3º Ano A", ano_escolar="3º Ano",
                  ano_letivo=ano)
    db.add(turma)
    db.flush()

    alunos = []
    for nome in ["Ana Beatriz Souza", "João Pedro Barbosa", "Sofia Almeida Duarte"]:
        aluno = Aluno(escola_id=escola.id, nome=nome)
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id,
                         turma_id=turma.id, ano_letivo=ano))
        alunos.append(aluno)
    db.commit()
    return {"escola": escola, "turma": turma, "alunos": alunos, "admin": admin}


@pytest.fixture()
def cliente(db, escola_completa):
    cliente = TestClient(app)
    resposta = cliente.post(
        "/api/v1/auth/login",
        data={"username": "admin@teste.local", "password": "s3nh4"},
    )
    assert resposta.status_code == 200, resposta.text
    token = resposta.json()["access_token"]
    cliente.headers["Authorization"] = f"Bearer {token}"
    return cliente


@pytest.fixture()
def cliente_global(db, escola_completa):
    """Cliente autenticado como ADMIN GLOBAL (``is_global=True``) vinculado à
    escola-base. É quem escreve nas rotas de GOVERNANÇA da fórmula (pesos,
    referências, pontos extras, dificuldade, pontuação por turma, níveis e
    perfil de scoring) — o admin/coordenador da escola só LÊ."""
    db.add(Usuario(escola_id=escola_completa["escola"].id, nome="Admin Global",
                   email="global@constela.local", senha_hash=hash_senha("s3nh4"),
                   cargo="admin", is_global=True))
    db.commit()
    cliente = TestClient(app)
    resposta = cliente.post(
        "/api/v1/auth/login",
        data={"username": "global@constela.local", "password": "s3nh4"},
    )
    assert resposta.status_code == 200, resposta.text
    cliente.headers["Authorization"] = f"Bearer {resposta.json()['access_token']}"
    return cliente


@pytest.fixture(autouse=True)
def _sem_portao_de_ci(monkeypatch):
    """EXIGIR_CI_VERDE no ambiente de quem roda os testes ligaria o portão de CI em todo
    `scripts.migrate` (saída 4): os testes que o exercitam ligam a variável sozinhos."""
    monkeypatch.delenv("EXIGIR_CI_VERDE", raising=False)
