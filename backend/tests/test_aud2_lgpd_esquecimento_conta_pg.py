"""Exclusão permanente (LGPD) × a coleta seguinte, num PostgreSQL REAL — local e
descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').

Reusa os testes SQLite de ``test_aud2_lgpd_esquecimento_conta`` (o PostgreSQL não
reaproveita id de linha apagada) e acrescenta o caso que só o PostgreSQL prova: a
exclusão chega DURANTE uma coleta da mesma escola que acabou de mandar a segunda
conta da criança para a fila. A exclusão espera a trava da escola (4711), varre o
que a coleta gravou e marca as duas contas; a coleta seguinte não traz a criança de
volta por nenhuma delas.

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud2_lgpd_esquecimento_conta_pg.py -m postgres

Dados fictícios.
"""
from __future__ import annotations

import json
import os
import threading
import time

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.models import (Aluno, Configuracao, Escola, IdentidadeExterna, Matricula,
                        NivelDificuldade, ReferenciaNormalizacao, RevisaoIdentidade, Turma,
                        Usuario)
from app.models.nota import LogAuditoria
from app.routers import academico
from app.routers.importacoes import _confirmar_sem_commit
from app.schemas.comum import ExclusaoPermanenteAlunos
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import scoring

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]

NOME = "Quiteria Concorrente Ficticia"


@pytest.fixture()
def db():
    from app.quest import models as _quest  # noqa: F401
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


from tests.test_aud2_lgpd_esquecimento_conta import (  # noqa: E402,F401
    test_a_coleta_seguinte_nao_traz_de_volta_a_crianca_esquecida as test_pg_coleta_seguinte,
    test_a_marca_nao_guarda_nome_nem_id_em_claro as test_pg_marca_sem_nome_nem_id,
    test_a_segunda_conta_que_estava_na_fila_tambem_e_esquecida as test_pg_segunda_conta,
    test_conta_de_quem_continua_na_escola_nunca_e_marcada as test_pg_conta_de_quem_fica,
    test_a_marca_vale_so_na_escola_que_excluiu as test_pg_so_na_escola,
    test_exclusao_de_turma_com_alunos_nao_marca_contas as test_pg_turma_nao_marca)


@pytest.fixture()
def motor_pg():
    from app.quest import models as _quest  # noqa: F401
    motor = create_engine(URL, pool_size=8, max_overflow=8, pool_pre_ping=True)
    Base.metadata.drop_all(motor)
    Base.metadata.create_all(motor)
    yield motor
    Base.metadata.drop_all(motor)
    motor.dispose()


def _cena(motor):
    with Session(motor) as db:
        escola = Escola(nome="ESCOLA FICTICIA ESQUECIMENTO PG", ano_letivo_ativo=2026)
        db.add(escola)
        db.flush()
        admin = Usuario(escola_id=escola.id, nome="Admin PG",
                        email=f"esq-{escola.id}@teste.local", senha_hash="x", cargo="admin")
        glob = Usuario(escola_id=escola.id, nome="Global PG",
                       email=f"esq-glob-{escola.id}@teste.local", senha_hash="x",
                       cargo="admin", is_global=True)
        db.add_all([admin, glob])
        for ns, valores in scoring.PESOS_PADRAO.items():
            db.add(Configuracao(escola_id=escola.id, namespace=ns, chave="valores",
                                valor=valores))
        db.add(NivelDificuldade(escola_id=escola.id, nome="Nivel", codigo="nivel",
                                codigos=["AA"], pontos_padrao=1.0, ordem=0))
        db.add(ReferenciaNormalizacao(escola_id=escola.id, modo="auto"))
        turma = Turma(escola_id=escola.id, nome="3º Ano A", ano_escolar="3º Ano",
                      ano_letivo=2026)
        db.add(turma)
        db.flush()
        x = Aluno(escola_id=escola.id, nome=NOME)
        db.add(x)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=x.id, turma_id=turma.id,
                         ano_letivo=2026))
        db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=x.id, plataforma="matific",
                                 id_externo="uuid-ficticio-conta-1"))
        db.commit()
        return {"escola": escola.id, "admin": admin.id, "global": glob.id, "x": x.id,
                "turma": turma.nome}


def _corpo(cena, *contas):
    return ImportacaoConfirm(
        plataforma="matific", formato="resumo", tipo="texto",
        linhas=[LinhaConfirmacao(nome=NOME, criar_em_turma_nome=cena["turma"], dados={
            "matific_uuid": conta, "turma_relatorio": cena["turma"],
            "atividades": 9, "estrelas": 9, "pontuacao_media": 70}) for conta in contas],
        recalcular=False, sincronizar_turma=True, permitir_criar_turma=False,
        permitir_criar_aluno=True)


def _esperando_trava(motor, pid):
    with motor.connect() as espia:
        return espia.execute(text(
            "SELECT wait_event_type FROM pg_stat_activity "
            "WHERE pid=:p AND state='active' AND wait_event_type='Lock'"), {"p": pid}).scalar()


def _com_o_nome(db, eid):
    revs = [rv.id for rv in db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).scalars()
        if NOME in json.dumps({"n": rv.nome_recebido, "c": rv.candidatos, "l": rv.linhas},
                              ensure_ascii=False, default=str)]
    logs = [(lg.id, lg.acao) for lg in db.execute(select(LogAuditoria)).scalars()
            if NOME in json.dumps(lg.detalhes or {}, ensure_ascii=False, default=str)]
    return revs, logs


def test_exclusao_durante_a_coleta_esquece_tambem_a_conta_que_ela_mandou_para_a_fila(
        motor_pg):
    cena = _cena(motor_pg)
    coleta = Session(motor_pg)
    erros, pid = [], {}
    try:
        # A coleta segura a trava da escola e grava, sem commit, a pendência da 2ª conta.
        _confirmar_sem_commit(dados=_corpo(cena, "uuid-ficticio-conta-2"),
                              escola_id=cena["escola"],
                              usuario=coleta.get(Usuario, cena["admin"]), db=coleta)
        assert coleta.execute(select(RevisaoIdentidade.motivo).where(
            RevisaoIdentidade.escola_id == cena["escola"])).scalars().all() == [
            "outra_identidade_na_plataforma"]

        def _excluir():
            with Session(motor_pg) as db:
                pid["exc"] = db.execute(text("select pg_backend_pid()")).scalar_one()
                try:
                    academico.excluir_alunos_permanente(
                        dados=ExclusaoPermanenteAlunos(aluno_ids=[cena["x"]],
                                                       confirmacao="EXCLUIR"),
                        escola_id=cena["escola"], usuario=db.get(Usuario, cena["global"]),
                        db=db)
                except Exception as erro:  # noqa: BLE001 — o teste mostra o erro
                    erros.append(erro)

        fio = threading.Thread(target=_excluir, name="EXCLUSAO")
        fio.start()
        esperou = None
        limite = time.monotonic() + 20
        while time.monotonic() < limite and fio.is_alive():
            if "exc" in pid and (esperou := _esperando_trava(motor_pg, pid["exc"])):
                break
            time.sleep(0.05)
        assert fio.is_alive() and esperou == "Lock", (
            "a exclusão não esperou a coleta da mesma escola")
        coleta.commit()
        fio.join(60)
    finally:
        coleta.close()
    assert not erros, erros

    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["x"]) is None
        assert _com_o_nome(db, cena["escola"]) == ([], [])
        exclusao = db.execute(select(LogAuditoria).where(
            LogAuditoria.acao == "aluno.excluido_permanente")).scalars().one()
        assert len(exclusao.detalhes["contas_esquecidas"]) == 2

    # A coleta seguinte manda as duas contas: nenhuma traz a criança de volta.
    with Session(motor_pg) as db:
        _confirmar_sem_commit(dados=_corpo(cena, "uuid-ficticio-conta-2",
                                           "uuid-ficticio-conta-1"),
                              escola_id=cena["escola"],
                              usuario=db.get(Usuario, cena["admin"]), db=db)
        db.commit()
    with Session(motor_pg) as db:
        assert db.execute(select(Aluno.id).where(Aluno.escola_id == cena["escola"],
                                                 Aluno.nome == NOME)).all() == []
        assert db.execute(select(IdentidadeExterna.id).where(
            IdentidadeExterna.escola_id == cena["escola"])).all() == []
        assert _com_o_nome(db, cena["escola"]) == ([], [])
