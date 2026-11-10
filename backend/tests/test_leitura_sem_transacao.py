"""Rotas de LEITURA sem transação (``database.leitura_sem_transacao``, ``SessionLeitura``).

Em produção (API a ~195 ms do banco) o BEGIN e o ROLLBACK de cada requisição eram duas idas
ao banco sem dado nenhum. As rotas MARCADAS rodam numa sessão em AUTOCOMMIT do mesmo pool.

* a lista é FECHADA: as rotas marcadas são exatamente as desta lista, todas GET;
* o ``get_db`` de verdade escolhe a sessão pela marca da rota casada (os testes comuns
  trocam o ``get_db`` por um da fixture e não passariam por aqui);
* cada rota marcada, com a Secretaria e com o admin global, roda numa sessão que RECUSA
  escrita (flush com objeto novo, alterado ou apagado; commit; INSERT, UPDATE, DELETE, DDL,
  ``FOR UPDATE``, ``SET LOCAL``, advisory lock) e responde 200;
* no PostgreSQL de teste: a sessão de leitura não abre transação, a conexão volta ao pool
  com transação para quem grava, e o psycopg não prepara comandos.

Dados INVENTADOS (``test_analise_base``; decisão D13).
"""
import os
import re
import sys

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core import database
from app.core.database import get_db
from app.core.security import hash_senha
from app.main import app
from app.models import Usuario
from tests.test_analise_base import HOJE, mundo_plataformas

PREFIXO = "/api/v1"
# A lista fechada (as telas da Secretaria e o que elas leem na abertura da sessão). Rota nova
# aqui só depois de conferir que ela, as dependências e os serviços nunca gravam.
MARCADAS = {
    "/auth/me", "/escolas", "/redes", "/redes/{rede_id}/dashboard", "/redes/{rede_id}/destaques",
    "/redes/{rede_id}/ranking/frescor", "/redes/{rede_id}/publico",
    "/redes/{rede_id}/analise/indicadores", "/redes/{rede_id}/analise/indicadores/{chave}",
    "/redes/{rede_id}/analise/plataformas", "/redes/{rede_id}/analise/plataformas/evolucao",
    "/redes/{rede_id}/analise/diagnostico", "/redes/{rede_id}/analise/relacao",
    "/escolas/{escola_id}/analise", "/notificacoes/contador",
}
_ESCRITA = re.compile(r"^\s*(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE|LOCK)\b"
                      r"|\bFOR\s+(UPDATE|SHARE|NO\s+KEY\s+UPDATE)\b|\bSET\s+LOCAL\b|pg_advisory",
                      re.IGNORECASE)


def _rotas_marcadas() -> dict[str, set[str]]:
    return {r.path.removeprefix(PREFIXO): set(r.methods) for r in app.routes
            if isinstance(r, APIRoute) and database.e_leitura_sem_transacao(r.endpoint)}


def test_a_lista_das_rotas_sem_transacao_e_fechada_e_so_de_get():
    marcadas = _rotas_marcadas()
    assert set(marcadas) == MARCADAS
    assert all(metodos == {"GET"} for metodos in marcadas.values()), marcadas


def test_a_marca_devolve_a_propria_funcao():
    def rota():
        return 1
    assert database.leitura_sem_transacao(rota) is rota
    assert database.e_leitura_sem_transacao(rota)
    assert not database.e_leitura_sem_transacao(lambda: None)
    assert not database.e_leitura_sem_transacao(None)


class _Requisicao:
    def __init__(self, endpoint):
        self.scope = {"endpoint": endpoint}


def test_get_db_escolhe_a_sessao_pela_marca_da_rota(monkeypatch):
    criadas = []

    class _Fabrica:
        def __init__(self, nome):
            self.nome = nome

        def __call__(self):
            criadas.append(self.nome)
            return Session()

    monkeypatch.setattr(database, "SessionLocal", _Fabrica("local"))
    monkeypatch.setattr(database, "SessionLeitura", _Fabrica("leitura"))
    marcada = next(r.endpoint for r in app.routes
                   if isinstance(r, APIRoute) and r.path == f"{PREFIXO}/auth/me")
    comum = next(r.endpoint for r in app.routes
                 if isinstance(r, APIRoute) and r.path == f"{PREFIXO}/presenca/heartbeat")
    for pedido in (_Requisicao(marcada), _Requisicao(comum), None):
        gerador = get_db(pedido) if pedido is not None else get_db()
        next(gerador)
        gerador.close()
    assert criadas == ["leitura", "local", "local"]   # o boot e os scripts: a de sempre


# --- A varredura: cada rota marcada numa sessão que recusa escrita -----------------------------

class _Recusa(Exception):
    pass


# As travas advisory do app. No PostgreSQL são ``pg_advisory_xact_lock`` (o filtro de SQL as
# vê); no SQLite não emitem SQL nenhum, então a varredura as troca por um invólucro.
TRAVAS = ("bloquear_escola_para_importacao", "bloquear_fonte_para_coleta",
          "bloquear_escola_para_recalculo")


def test_a_varredura_conhece_todas_as_travas_do_app():
    assert {n for n in dir(database) if n.startswith("bloquear_")} == set(TRAVAS)


def _so_leitura(sessao) -> bool:
    alvo = sessao.get_bind() if hasattr(sessao, "get_bind") else sessao
    return bool(alvo.get_execution_options().get("constela_so_leitura"))


@pytest.fixture()
def varredura(db, monkeypatch):
    """O ``get_db`` DE VERDADE (sem o override da fixture), com as duas fábricas no banco do
    teste: a de leitura recusa qualquer escrita e as duas contam quantas sessões abriram."""
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: HOJE)
    base = mundo_plataformas(db)
    rede = base["rede"]
    hash_ = hash_senha("s3nh4-leitura")
    db.add_all([Usuario(nome="Secretaria Leitura", email="sec@leitura.local", senha_hash=hash_,
                        cargo="coordenador", rede_id=rede.id),
                Usuario(nome="Global Leitura", email="glob@leitura.local", senha_hash=hash_,
                        cargo="admin", is_global=True)])
    db.commit()
    motor = db.get_bind()
    abertas = {"local": 0, "leitura": 0}
    escritas: list[str] = []

    def _fabrica(nome, so_leitura):
        fabrica = sessionmaker(bind=motor.execution_options(constela_so_leitura=so_leitura))

        def _abrir():
            abertas[nome] += 1
            return fabrica()
        return _abrir

    def _antes_do_flush(sessao, _ctx, _inst):
        if sessao.get_bind().get_execution_options().get("constela_so_leitura") and (
                sessao.new or sessao.dirty or sessao.deleted):
            escritas.append(f"flush {len(sessao.new)}/{len(sessao.dirty)}/{len(sessao.deleted)}")
            raise _Recusa("flush numa rota de leitura")

    def _antes_do_commit(sessao):
        if sessao.get_bind().get_execution_options().get("constela_so_leitura"):
            escritas.append("commit")
            raise _Recusa("commit numa rota de leitura")

    def _antes_do_sql(conexao, _cursor, sql, _params, _ctx, _many):
        if conexao.get_execution_options().get("constela_so_leitura") and _ESCRITA.search(sql):
            escritas.append(sql.split("\n")[0][:80])
            raise _Recusa(f"escrita numa rota de leitura: {sql[:80]}")

    def _trava_recusada(original):
        def _trava(sessao, *args, **kwargs):
            if _so_leitura(sessao):
                escritas.append(f"trava {original.__name__}")
                raise _Recusa(f"trava advisory numa rota de leitura: {original.__name__}")
            return original(sessao, *args, **kwargs)
        return _trava

    app.dependency_overrides.pop(get_db, None)          # o get_db de verdade
    monkeypatch.setattr(database, "SessionLocal", _fabrica("local", False))
    monkeypatch.setattr(database, "SessionLeitura", _fabrica("leitura", True))
    # Cada trava, em ``app.core.database`` e em TODO módulo do app que a importou pelo nome
    # (academico, importacoes, alunos_dedup, turma_arquivada, scoring...): quem a chama
    # numa sessão de leitura é recusado. Módulo importado depois a pega já trocada.
    for nome in TRAVAS:
        original = getattr(database, nome)
        involucro = _trava_recusada(original)
        for modulo in list(sys.modules.values()):
            if (getattr(modulo, "__name__", "").startswith("app.")
                    and getattr(modulo, nome, None) is original):
                monkeypatch.setattr(modulo, nome, involucro)
    event.listen(Session, "before_flush", _antes_do_flush)
    event.listen(Session, "before_commit", _antes_do_commit)
    event.listen(motor, "before_cursor_execute", _antes_do_sql)
    clientes = {}
    for perfil, email in (("secretaria", "sec@leitura.local"), ("global", "glob@leitura.local")):
        c = TestClient(app)
        r = c.post(f"{PREFIXO}/auth/login", data={"username": email, "password": "s3nh4-leitura"})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        clientes[perfil] = c
    try:
        yield {"base": base, "c": clientes, "abertas": abertas, "escritas": escritas}
    finally:
        event.remove(Session, "before_flush", _antes_do_flush)
        event.remove(Session, "before_commit", _antes_do_commit)
        event.remove(motor, "before_cursor_execute", _antes_do_sql)


def _pedidos(base) -> list[tuple[str, dict]]:
    rid = base["rede"].id
    alfa = base["escolas"]["alfa"].id
    beta = base["escolas"]["beta"].id
    r = f"/redes/{rid}"
    return [
        ("/auth/me", {}), ("/escolas", {}), ("/redes", {}), (f"{r}/dashboard", {}),
        (f"{r}/destaques", {}), (f"{r}/ranking/frescor", {}), (f"{r}/publico", {}),
        (f"{r}/analise/indicadores", {}), (f"{r}/analise/indicadores/saresp", {}),
        (f"{r}/analise/indicadores/saresp", {"visao": "escolas", "edicao": 2025}),
        (f"{r}/analise/indicadores/ideb", {"escola_id": beta}),
        (f"{r}/analise/plataformas", {}), (f"{r}/analise/plataformas", {"serie": 5}),
        (f"{r}/analise/plataformas", {"periodo": "mes"}),
        (f"{r}/analise/plataformas/evolucao", {}),
        (f"{r}/analise/plataformas/evolucao", {"escola_id": alfa, "so_escola": True}),
        (f"{r}/analise/diagnostico", {}), (f"{r}/analise/relacao", {"indicador": "saresp"}),
        (f"{r}/analise/relacao", {"indicador": "ideb", "metrica": "estrelas_por_aluno"}),
        (f"/escolas/{alfa}/analise", {}), (f"/escolas/{alfa}/analise", {"so_avaliacoes": True}),
        (f"/escolas/{beta}/analise", {}), ("/notificacoes/contador", {}),
    ]


def _casa(modelo: str, caminho: str) -> bool:
    return re.fullmatch(re.sub(r"\\\{[^}]+\\\}", r"[^/]+", re.escape(modelo)), caminho) is not None


def test_todas_as_rotas_marcadas_rodam_numa_sessao_que_recusa_escrita(varredura):
    pedidos = _pedidos(varredura["base"])
    cobertas = {m for m in MARCADAS for caminho, _ in pedidos if _casa(m, caminho)}
    assert cobertas == MARCADAS                        # a varredura passa por TODAS
    for perfil, cliente in varredura["c"].items():
        for caminho, params in pedidos:
            antes = dict(varredura["abertas"])
            r = cliente.get(f"{PREFIXO}{caminho}", params=params)
            assert r.status_code == 200, (perfil, caminho, params, r.status_code, r.text[:300])
            # Só a sessão de leitura (a rota e as dependências dividem a mesma).
            assert varredura["abertas"]["local"] == antes["local"], (perfil, caminho)
            assert varredura["abertas"]["leitura"] == antes["leitura"] + 1, (perfil, caminho)
    assert varredura["escritas"] == []


def test_a_sessao_que_recusa_escrita_recusa_mesmo(varredura):
    """O controle da varredura: a sessão de leitura recusa o flush, o commit e o SQL de
    escrita; uma rota NÃO marcada que grava (a presença) usa a sessão de sempre."""
    leitura = database.SessionLeitura()
    try:
        leitura.add(Usuario(nome="X", email="x@leitura.local", senha_hash="x", cargo="professor"))
        with pytest.raises(_Recusa):
            leitura.flush()
        leitura.rollback()
        with pytest.raises(_Recusa):
            leitura.execute(text("UPDATE usuarios SET nome = nome WHERE 1 = 0"))
        leitura.rollback()
        with pytest.raises(_Recusa):
            leitura.commit()
    finally:
        leitura.close()
    antes = dict(varredura["abertas"])
    r = varredura["c"]["secretaria"].post(f"{PREFIXO}/presenca/heartbeat")
    assert r.status_code in (200, 204), r.text
    assert varredura["abertas"]["local"] > antes["local"]
    assert varredura["abertas"]["leitura"] == antes["leitura"]


@pytest.mark.parametrize("modulo,trava", [
    ("app.core.database", "bloquear_escola_para_importacao"),   # a da fusão e da importação
    ("app.routers.academico", "bloquear_escola_para_importacao"),  # importada pelo nome
    ("app.services.scoring", "bloquear_escola_para_recalculo"),
    ("app.core.database", "bloquear_fonte_para_coleta"),
])
def test_a_varredura_recusa_trava_advisory_numa_rota_marcada(varredura, monkeypatch,
                                                              modulo, trava):
    """No SQLite as travas ``bloquear_*`` não emitem SQL: o filtro de ``pg_advisory`` nunca
    as via, e uma rota marcada que tomasse a trava da escola passava verde. Em produção, na
    sessão em AUTOCOMMIT, ``pg_advisory_xact_lock`` cai no fim do próprio comando e não
    serializa nada. A varredura tem de recusá-la como recusa a escrita."""
    import importlib

    from app.services import notificacoes as svc_notif
    real = svc_notif.contar_nao_lidas
    alvo = importlib.import_module(modulo)
    escola_id = varredura["base"]["escolas"]["alfa"].id

    def _com_trava(db, usuario):
        getattr(alvo, trava)(db, escola_id)
        return real(db, usuario)

    monkeypatch.setattr(svc_notif, "contar_nao_lidas", _com_trava)
    r = varredura["c"]["secretaria"].get(f"{PREFIXO}/notificacoes/contador")
    # A recusa vira 500 pelo tratador geral do app: a varredura (que exige 200) reprova.
    assert r.status_code == 500, (r.status_code, r.text[:200])
    assert varredura["escritas"] == [f"trava {trava}"]


# --- PostgreSQL de verdade ---------------------------------------------------------------------

URL_PG = os.environ.get("TEST_DATABASE_URL_PG", "")
_pg = pytest.mark.skipif(not URL_PG or "test" not in (make_url(URL_PG).database or ""),
                         reason="defina TEST_DATABASE_URL_PG (banco com 'test' no nome)")


@pytest.mark.postgres
@_pg
def test_pg_leitura_sem_begin_e_a_conexao_volta_com_transacao():
    import psycopg

    opcoes = {**database.opcoes_do_engine(URL_PG), "pool_size": 1, "max_overflow": 0}
    motor = create_engine(URL_PG, **opcoes)
    database.desligar_prepared_statements(motor)
    leitura, comum = database.sessao_de_leitura(motor), sessionmaker(bind=motor)
    ociosa, em_transacao = psycopg.pq.TransactionStatus.IDLE, psycopg.pq.TransactionStatus.INTRANS

    with leitura() as s:
        for _ in range(8):                               # mais que o limite padrão de prepare (5)
            assert s.execute(text("SELECT 1")).scalar() == 1
        dbapi = s.connection().connection.dbapi_connection
        assert dbapi.autocommit is True
        assert dbapi.info.transaction_status == ociosa   # nenhuma transação aberta
        assert dbapi.prepare_threshold is None
        assert not dbapi._prepared._names                 # nada preparado no servidor
    # A MESMA conexão (pool de 1) volta para quem grava com transação, como sempre.
    with comum() as s:
        s.execute(text("SELECT 1"))
        dbapi2 = s.connection().connection.dbapi_connection
        assert dbapi2 is dbapi
        assert dbapi2.autocommit is False
        assert dbapi2.info.transaction_status == em_transacao
        s.rollback()
    motor.dispose()
