"""Consolidação das fichas-sombra num PostgreSQL REAL.

O SQLite da suíte não tem ``FOR UPDATE``, advisory lock nem transação
``READ ONLY``: as três defesas da consolidação só existem de verdade aqui.
Este módulo prova, contra o banco de produção (Postgres):

  1. ``planejar`` + ``aplicar`` ponta a ponta — o padrão consolida, os gêmeos
     ficam para revisão, os dados vão para a oficial, a nota é recalculada e a
     segunda execução não acha nada;
  2. duas aplicações CONCORRENTES do mesmo plano fundem o par UMA vez: a trava
     de importação da escola serializa, e a segunda reconfere o par no banco
     atual (compare-and-set) e o pula — sem erro, sem fundir duas vezes;
  3. a simulação do script roda numa transação que o próprio banco confirma ser
     somente leitura, e não grava nada.

Como rodar::

    set TEST_DATABASE_URL_PG=postgresql+psycopg://constela_teste@127.0.0.1:5433/constela_teste
    pytest tests/test_consolidacao_sombras_pg.py -m postgres

Sem ``TEST_DATABASE_URL_PG`` o módulo inteiro é pulado. Nomes FICTÍCIOS.
"""
from __future__ import annotations

import os
import sys
import threading

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models import (Aluno, Configuracao, Escola, IdentidadeExterna, Importacao,
                        LogAuditoria, Matricula, NivelDificuldade, Nota,
                        ReferenciaNormalizacao, SnapshotElefante, SnapshotMatific,
                        Turma, Usuario)
from app.services import consolidacao_sombras as cs
from app.services import scoring

pytestmark = pytest.mark.postgres

URL_PG = os.environ.get("TEST_DATABASE_URL_PG", "")
if not URL_PG:
    pytest.skip("defina TEST_DATABASE_URL_PG para rodar no PostgreSQL real",
                allow_module_level=True)

OFICIAL = "ZULEICA RAMONA TEODORO DA CUNHA"
SOMBRA = "ZULEICA R"


@pytest.fixture(scope="module")
def motor_pg():
    motor = create_engine(URL_PG, pool_size=8, max_overflow=8, pool_pre_ping=True)
    import app.quest.models  # noqa: F401 — registra o schema completo

    Base.metadata.create_all(motor)
    yield motor
    motor.dispose()


def _semear(motor, sufixo: str) -> dict:
    """Escola NOVA (isolada das outras execuções) com o padrão real e os gêmeos."""
    with Session(motor) as db:
        escola = Escola(nome=f"ESCOLA SOMBRAS PG {sufixo}", ano_letivo_ativo=2026)
        db.add(escola)
        db.flush()
        admin = Usuario(escola_id=escola.id, nome="Admin PG",
                        email=f"sombras-{escola.id}-{sufixo}@teste.local",
                        senha_hash="x", cargo="admin")
        db.add(admin)
        for ns, valores in scoring.PESOS_PADRAO.items():
            db.add(Configuracao(escola_id=escola.id, namespace=ns,
                                chave="valores", valor=valores))
        db.add(NivelDificuldade(escola_id=escola.id, nome="Nivel 2", codigo="nivel_2",
                                codigos=["D"], pontos_padrao=4.0, ordem=0))
        db.add(ReferenciaNormalizacao(escola_id=escola.id, modo="auto"))
        db.flush()
        imp = Importacao(escola_id=escola.id, usuario_id=admin.id,
                         plataforma="matific", tipo="seed")
        turma = Turma(escola_id=escola.id, nome="2o Ano B", ano_escolar="2o Ano",
                      ano_letivo=2026)
        db.add_all([imp, turma])
        db.flush()

        def aluno(nome, lp):
            a = Aluno(escola_id=escola.id, nome=nome, da_lista_piloto=lp)
            db.add(a)
            db.flush()
            db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                             ano_letivo=2026))
            return a

        oficial = aluno(OFICIAL, True)
        sombra = aluno(SOMBRA, False)
        aluno("MARIA ALICE ALVES PEREIRA", True)
        aluno("MARIA ALINE ALVES PEREIRA", True)
        gemea = aluno("MARIA A", False)
        db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=sombra.id,
                                 plataforma="matific", id_externo=f"u-{sufixo}"))
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=sombra.id,
                               importacao_id=imp.id, atividades=40, estrelas=150,
                               pontuacao_media=3.75))
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=oficial.id,
                                importacao_id=imp.id, livros_unicos=12,
                                tempo_leitura_min=300, livros_por_nivel={"D": 2}))
        db.commit()
        return {"escola_id": escola.id, "oficial": oficial.id, "sombra": sombra.id,
                "gemea": gemea.id}


@pytest.fixture()
def cena(motor_pg, request):
    return _semear(motor_pg, request.node.name[-24:])


def test_planejar_e_aplicar_no_postgres(motor_pg, cena):
    with Session(motor_pg) as db:
        plano = cs.planejar(db, cena["escola_id"])
        assert plano.item_da_sombra(cena["sombra"]).classe == cs.CONSOLIDAR
        gemea = plano.item_da_sombra(cena["gemea"])
        assert (gemea.classe, gemea.motivo) == (cs.REVISAR, "varias_oficiais")
        res = cs.aplicar(db, plano, usuario_id=None, origem="teste_pg")
        assert [x["sombra_id"] for x in res["consolidados"]] == [cena["sombra"]]

    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["sombra"]) is None
        assert db.get(Aluno, cena["gemea"]) is not None
        assert db.execute(select(IdentidadeExterna.aluno_id).where(
            IdentidadeExterna.escola_id == cena["escola_id"])).scalars().all() == [
            cena["oficial"]]
        assert db.execute(select(SnapshotMatific.aluno_id).where(
            SnapshotMatific.escola_id == cena["escola_id"])).scalars().all() == [
            cena["oficial"]]
        nota = db.execute(select(Nota).where(Nota.aluno_id == cena["oficial"])).scalar_one()
        assert nota.aferido_matematica and nota.aferido_leitura
        assert db.execute(select(func.count()).select_from(Nota).where(
            Nota.escola_id == cena["escola_id"])).scalar_one() == 4   # sem a sombra
        assert db.execute(select(func.count()).select_from(LogAuditoria).where(
            LogAuditoria.escola_id == cena["escola_id"],
            LogAuditoria.acao == "aluno.consolidado_automatico")).scalar_one() == 1
        # Idempotente: a segunda execução não acha nada.
        assert cs.planejar(db, cena["escola_id"]).consolidar == []


def test_duas_aplicacoes_concorrentes_fundem_o_par_uma_vez(motor_pg, cena):
    with Session(motor_pg) as db:
        plano = cs.planejar(db, cena["escola_id"])
    assert len(plano.consolidar) == 1

    largada = threading.Barrier(2)
    resultados: list[dict] = []
    erros: list[BaseException] = []

    def rodar():
        try:
            with Session(motor_pg) as db:
                largada.wait(timeout=30)
                resultados.append(cs.aplicar(db, plano, usuario_id=None,
                                             origem="corrida_pg"))
        except BaseException as exc:  # noqa: BLE001 — o teste inspeciona
            erros.append(exc)

    threads = [threading.Thread(target=rodar) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert erros == []
    assert sorted(len(r["consolidados"]) for r in resultados) == [0, 1]
    assert sorted(len(r["pulados"]) for r in resultados) == [0, 1]
    [pulado] = [p for r in resultados for p in r["pulados"]]
    assert pulado["motivo_atual"] == "ficha_inexistente"
    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["sombra"]) is None
        acoes = db.execute(select(LogAuditoria.acao).where(
            LogAuditoria.escola_id == cena["escola_id"],
            LogAuditoria.acao.in_(("aluno.consolidado_automatico", "aluno.fundido")))
        ).scalars().all()
        assert sorted(acoes) == ["aluno.consolidado_automatico", "aluno.fundido"]


def test_simulacao_do_script_e_somente_leitura_no_postgres(motor_pg, cena, monkeypatch,
                                                           capsys):
    import scripts.consolidar_sombras as etapa

    Sessao = sessionmaker(bind=motor_pg)
    vistos: list[bool] = []
    original = etapa._abrir_somente_leitura

    def conferir(db):
        ok = original(db)
        vistos.append(ok)
        return ok

    monkeypatch.setattr(etapa, "_abrir_somente_leitura", conferir)
    monkeypatch.setattr(etapa, "SessionLocal", Sessao)
    monkeypatch.setattr(sys, "argv", ["consolidar_sombras", "--escola",
                                      str(cena["escola_id"])])
    assert etapa.main() == 0
    saida = capsys.readouterr().out
    assert vistos == [True]                     # o banco confirmou: READ ONLY
    assert "CONSOLIDAR 1 · REVISAR 1" in saida and "nada foi gravado" in saida
    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["sombra"]) is not None
        assert db.execute(select(func.count()).select_from(LogAuditoria).where(
            LogAuditoria.escola_id == cena["escola_id"])).scalar_one() == 0
