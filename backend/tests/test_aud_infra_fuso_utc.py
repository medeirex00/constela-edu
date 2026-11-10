"""Datas gravadas em UTC, seja qual for o fuso da sessão do PostgreSQL.

As colunas de data e hora são ``timestamp`` SEM fuso e guardam UTC — é assim que o app as lê
(``auth._expirado``, ``sync.service._agora``, ``sync.fuso``). Mas o padrão ``models.base.agora()``
devolve o instante COM fuso: o psycopg o envia como ``timestamptz`` e o PostgreSQL o converte
para a hora local da SESSÃO antes de gravar. Com o banco (ou o papel) em America/Sao_Paulo —
``ALTER DATABASE ... SET timezone``, um banco de recuperação criado num servidor brasileiro —
tudo saía 3 h atrasado: o link de redefinição de senha nascia vencido (AUTH-7), uma coleta
viva era dada como travada (SYNC-5), os recortes por período e o frescor deslocavam (BANCO-4).

Agora:

* toda coluna ``Mapped[datetime]`` usa ``database.DataHoraUTC``, que converte o instante com
  fuso para UTC sem fuso ANTES de enviá-lo — vale em qualquer engine, pooler ou script, e o
  SQLite (desenvolvimento e testes) passa a gravar o mesmo que o PostgreSQL;
* o engine do app põe a sessão em UTC quando o servidor informa outro fuso
  (``database.fixar_fuso_utc``), para o ``now()`` do próprio banco e o SQL escrito à mão.

Os cenários de PostgreSQL abrem a sessão em America/Sao_Paulo (``options -c TimeZone``) num
engine de teste SEM o ajuste do app: a gravação certa vem do tipo da coluna. O link de
redefinição pela API está em ``test_aud_infra_fuso_utc_link_pg.py``.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import DateTime, create_engine, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — registra as tabelas do Constela Edu
import app.quest.models  # noqa: F401 — e as do Constela Quest
from app.core import database
from app.core.database import Base

URL_PG = os.environ.get("TEST_DATABASE_URL_PG", "")
FUSO_SP = timezone(timedelta(hours=-3))
BACKEND = Path(database.__file__).parents[2]


def _so_no_pg(teste):
    for marca in (pytest.mark.postgres,
                  pytest.mark.skipif(not URL_PG, reason="defina TEST_DATABASE_URL_PG"),
                  pytest.mark.skipif(bool(URL_PG) and "test" not in (make_url(URL_PG).database or ""),
                                     reason="o nome do banco PG de teste precisa conter 'test'")):
        teste = marca(teste)
    return teste


def _agora_utc_sem_fuso() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- sem banco de rede -------------------------------------------------------------------------

def test_o_tipo_converte_o_instante_com_fuso_para_utc_sem_fuso():
    tipo = getattr(database, "DataHoraUTC", None)
    assert tipo is not None, "app.core.database não tem o tipo DataHoraUTC"
    converter = tipo().process_bind_param
    dialeto = postgresql.dialect()
    assert converter(datetime(2026, 11, 10, 19, 0, tzinfo=FUSO_SP), dialeto) == datetime(2026, 11, 10, 22, 0)
    assert converter(datetime(2026, 11, 10, 22, 0, tzinfo=timezone.utc), dialeto) == datetime(2026, 11, 10, 22, 0)
    # o que já vem sem fuso é UTC pela convenção do app: passa intacto
    assert converter(datetime(2026, 11, 10, 22, 0), dialeto) == datetime(2026, 11, 10, 22, 0)
    assert converter(None, dialeto) is None


def test_toda_coluna_de_data_e_hora_dos_modelos_grava_em_utc():
    """Catraca: coluna de data e hora declarada com ``DateTime`` explícito escaparia da conversão."""
    tipo = getattr(database, "DataHoraUTC", None)
    assert tipo is not None, "app.core.database não tem o tipo DataHoraUTC"
    sem_conversao = [f"{t.name}.{c.name}" for t in Base.metadata.sorted_tables for c in t.columns
                     if isinstance(getattr(c.type, "impl", c.type), DateTime)
                     and not isinstance(c.type, tipo)]
    assert not sem_conversao, f"colunas de data e hora fora do DataHoraUTC: {sem_conversao}"


def test_comparar_e_somar_com_a_coluna_mantem_os_tipos_de_antes():
    """O instante comparado com a coluna também passa pela conversão; o intervalo somado à
    coluna continua um intervalo (e não uma data, que o SQLite recusaria)."""
    from app.models import TokenResetSenha

    coluna = TokenResetSenha.__table__.c.expira_em
    comparado = (coluna >= datetime(2026, 1, 1, tzinfo=timezone.utc)).right
    assert type(comparado.type).__name__ == "DataHoraUTC"
    somado = (coluna + timedelta(minutes=5)).right
    assert type(somado.type).__name__ == "Interval"


def test_instante_com_outro_fuso_e_gravado_em_utc_tambem_no_sqlite(db):
    """No SQLite o instante com fuso era gravado com o relógio do PRÓPRIO fuso (o fuso era
    descartado): 19h de Brasília viravam 19h "UTC". Agora o SQLite grava o mesmo que o
    PostgreSQL: 22h."""
    from app.models import Escola

    e = Escola(nome="ESCOLA FICTICIA FUSO", ano_letivo_ativo=2026,
               created_at=datetime(2026, 11, 10, 19, 0, tzinfo=FUSO_SP))
    db.add(e)
    db.commit()
    gravado = db.execute(select(Escola.created_at).where(Escola.id == e.id)).scalar_one()
    assert gravado == datetime(2026, 11, 10, 22, 0), f"gravado {gravado} (esperado 22:00 UTC)"


class _ConexaoFalsa:
    """Conexão do driver que informa um fuso e anota o que foi executado."""

    def __init__(self, fuso: str | None):
        self.executados: list[str] = []
        self.commits = 0
        self.info = type("Info", (), {"parameter_status": staticmethod(
            lambda nome: fuso if nome == "TimeZone" else None)})()

    def cursor(self):
        conexao = self

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, sql):
                conexao.executados.append(sql)

        return _Cursor()

    def commit(self):
        self.commits += 1


def _ouvintes_de_conexao_nova(motor):
    return list(motor.pool.dispatch.connect)


@pytest.mark.parametrize("fuso,ajusta", [("UTC", False), ("Etc/UTC", False), ("GMT", False),
                                         ("America/Sao_Paulo", True), (None, True)])
def test_a_sessao_so_e_ajustada_quando_o_servidor_informa_outro_fuso(fuso, ajusta):
    """O ouvinte da conexão nova (``database._sessao_em_utc``) sobre uma conexão falsa do driver.
    A ligação ao engine do app está em ``test_o_engine_do_app_em_postgresql_poe_a_sessao_em_utc``."""
    ouvinte = getattr(database, "_sessao_em_utc", None)
    assert ouvinte is not None, "app.core.database não tem o ajuste do fuso da sessão"
    falsa = _ConexaoFalsa(fuso)
    ouvinte(falsa, None)
    if ajusta:   # gravado de vez (o ROLLBACK da devolução ao pool desfaria um SET sem COMMIT)
        assert falsa.executados == ["SET TIME ZONE 'UTC'"] and falsa.commits == 1
    else:        # o fuso já é UTC: nenhuma ida a mais ao banco
        assert falsa.executados == [] and falsa.commits == 0


def test_fixar_fuso_utc_nao_mexe_no_sqlite():
    fixar = getattr(database, "fixar_fuso_utc", None)
    assert fixar is not None, "app.core.database não tem fixar_fuso_utc"
    motor = create_engine("sqlite://")
    antes = _ouvintes_de_conexao_nova(motor)
    fixar(motor)
    assert _ouvintes_de_conexao_nova(motor) == antes
    motor.dispose()


def test_o_autogenerate_do_alembic_escreve_o_tipo_como_sa_datetime():
    """Sem o gancho, uma migração gerada por ``alembic revision --autogenerate`` importaria
    ``app.core.database.DataHoraUTC`` (código do app dentro do histórico de migrações)."""
    from alembic.autogenerate import render_python_code
    from alembic.operations import ops
    from sqlalchemy import Column

    from app.core import migracoes

    renderizar = getattr(migracoes, "renderizar_item_do_alembic", None)
    assert renderizar is not None, "app.core.migracoes não tem renderizar_item_do_alembic"
    tipo = database.DataHoraUTC
    codigo = render_python_code(
        ops.UpgradeOps(ops=[ops.AddColumnOp("escolas", Column("visto_em", tipo(), nullable=True))]),
        render_item=renderizar)
    assert "sa.DateTime()" in codigo and "app.core" not in codigo, codigo
    # e o env.py liga o gancho nos dois modos (online e offline)
    arvore = ast.parse((BACKEND / "alembic" / "env.py").read_text(encoding="utf-8"))
    configuracoes = [n for n in ast.walk(arvore) if isinstance(n, ast.Call)
                     and getattr(n.func, "attr", None) == "configure"]
    assert len(configuracoes) == 2
    assert all(any(k.arg == "render_item" for k in c.keywords) for c in configuracoes)


_SONDA_DO_ENGINE_DO_APP = """
from app.core import database as d
class Info:
    @staticmethod
    def parameter_status(nome):
        return "America/Sao_Paulo"
class Falsa:
    info = Info()
    prepare_threshold = 5
    def __init__(self):
        self.executados, self.commits = [], 0
    def cursor(self):
        dono = self
        class C:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, sql): dono.executados.append(sql)
        return C()
    def commit(self):
        self.commits += 1
falsa = Falsa()
from types import SimpleNamespace
for ouvinte in list(d.engine.pool.dispatch.connect):
    try:
        ouvinte(falsa, SimpleNamespace(info={}))
    except Exception:
        pass
print(falsa.executados == ["SET TIME ZONE 'UTC'"], falsa.commits == 1)
"""


@pytest.mark.postgres
def test_o_engine_do_app_em_postgresql_poe_a_sessao_em_utc():
    """O ``engine`` do próprio app, montado com uma URL PostgreSQL (processo à parte, sem
    conectar): a conexão nova que chega com outro fuso sai em UTC."""
    pytest.importorskip("psycopg", reason="sem o driver psycopg (instalado só no job postgres do CI)")
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg://usuario@127.0.0.1:1/constela_teste",
           "AUTOMACAO_VERIFICAR_NO_BOOT": "false"}
    r = subprocess.run([sys.executable, "-c", _SONDA_DO_ENGINE_DO_APP], cwd=str(BACKEND),
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.split() == ["True", "True"]


# --- PostgreSQL de verdade, sessão em America/Sao_Paulo -------------------------------------

FUSOS = ["UTC", "America/Sao_Paulo"]


def _motor_no_fuso(fuso: str):
    return create_engine(URL_PG, connect_args={"options": f"-c TimeZone={fuso}"})


@pytest.fixture
def motor_pg(request):
    motor = _motor_no_fuso(request.param)
    Base.metadata.drop_all(motor)
    Base.metadata.create_all(motor)
    yield motor
    Base.metadata.drop_all(motor)
    motor.dispose()


@_so_no_pg
@pytest.mark.parametrize("motor_pg", FUSOS, indirect=True)
def test_coleta_viva_nao_e_dada_como_travada_com_a_sessao_fora_de_utc(motor_pg):
    """SYNC-5: o log de agora era lido 3 h no passado e a execução viva virava 'travada'."""
    from app.models import Escola
    from app.models.sincronizacao import SincronizacaoExecucao, SincronizacaoLog
    from app.sync import service

    with sessionmaker(bind=motor_pg)() as s:
        fuso = s.execute(text("SHOW TimeZone")).scalar()
        e = Escola(nome="ESCOLA FICTICIA FUSO", ano_letivo_ativo=2026)
        s.add(e)
        s.flush()
        ex = SincronizacaoExecucao(escola_id=e.id, plataforma="elefante", origem="manual",
                                   status="executando", parametros={},
                                   iniciada_em=service._agora() - timedelta(minutes=20))
        s.add(ex)
        s.flush()
        s.add(SincronizacaoLog(execucao_id=ex.id, escola_id=e.id, etapa="download",
                               nivel="info", mensagem="progresso"))
        s.commit()
        ultimo = s.scalar(select(func.max(SincronizacaoLog.created_at)))
        assert abs((ultimo - service._agora()).total_seconds()) < 60, (
            f"sessão em {fuso}: último log {ultimo}, agora {service._agora()}")
        assert service._esta_travada(s.get(SincronizacaoExecucao, ex.id)) is False, (
            f"sessão em {fuso}: execução viva (log de agora) dada como travada")


@_so_no_pg
@pytest.mark.parametrize("motor_pg", FUSOS, indirect=True)
def test_padrao_agora_grava_utc_e_o_filtro_com_fuso_acha_a_linha(motor_pg):
    """BANCO-4: o ``created_at`` de ``agora()`` saía no relógio da sessão (3 h atrás)."""
    from app.models import Escola

    with sessionmaker(bind=motor_pg)() as s:
        fuso = s.execute(text("SHOW TimeZone")).scalar()
        antes = _agora_utc_sem_fuso()
        e = Escola(nome="ESCOLA FICTICIA FUSO", ano_letivo_ativo=2026)
        s.add(e)
        s.commit()
        cru = s.execute(text("SELECT created_at FROM escolas WHERE id = :i"), {"i": e.id}).scalar()
        assert abs((cru - antes).total_seconds()) < 60, (
            f"sessão em {fuso}: gravado {cru}, UTC de agora {antes}")
        desde = datetime.now(FUSO_SP) - timedelta(minutes=1)   # o instante com outro fuso
        achou = s.scalars(select(Escola.id).where(Escola.created_at >= desde)).all()
        assert achou == [e.id]


@_so_no_pg
def test_o_ajuste_do_app_poe_a_sessao_em_utc_e_dura_alem_do_rollback():
    fixar = getattr(database, "fixar_fuso_utc", None)
    assert fixar is not None, "app.core.database não tem fixar_fuso_utc"
    motor = create_engine(URL_PG, pool_size=1, max_overflow=0,
                          connect_args={"options": "-c TimeZone=America/Sao_Paulo"})
    fixar(motor)
    try:
        for _ in range(2):   # a 2ª retirada pega a MESMA conexão, depois do ROLLBACK da devolução
            with motor.connect() as c:
                assert c.execute(text("SHOW TimeZone")).scalar() == "UTC"
                local = c.execute(text("SELECT LOCALTIMESTAMP")).scalar()
                assert abs((local - _agora_utc_sem_fuso()).total_seconds()) < 60
                c.rollback()
    finally:
        motor.dispose()
