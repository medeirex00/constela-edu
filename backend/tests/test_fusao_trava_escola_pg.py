"""Fusão × coleta em andamento — só o PostgreSQL prova.

O SQLite tem um escritor só e a trava lá é no-op. Aqui rodam transações de
verdade, em paralelo, contra o banco de produção (Postgres), no ponto exato do
defeito: a coleta segura a trava da escola e grava na ficha que a fusão quer
apagar. Sem a trava (ou com ela depois das escritas) a fusão apaga a ficha e o
``ON DELETE CASCADE`` leva junto o retrato e o vínculo que a coleta acabou de
gravar, ou as duas se matam em deadlock (40P01).

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_fusao_trava_escola_pg.py -m postgres

Dados fictícios.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.database import (Base, _NS_IMPORTACAO, _NS_RECALCULO,
                               bloquear_escola_para_importacao)
from app.models import (Aluno, Configuracao, Escola, IdentidadeExterna, Importacao, Matricula,
                        NivelDificuldade, ReferenciaNormalizacao, SnapshotMatific, Turma, Usuario)
from app.routers import academico
from app.schemas.comum import CorrigirDuplicadosAlunos, FusaoAlunos
from app.services import alunos_dedup, alunos_fusao, scoring

URL_PG = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL_PG, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL_PG) and "test" not in (make_url(URL_PG).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]


@pytest.fixture(scope="module")
def motor_pg():
    motor = create_engine(URL_PG, pool_size=8, max_overflow=8, pool_pre_ping=True)
    import app.quest.models  # noqa: F401 — registra o schema completo

    Base.metadata.create_all(motor)
    yield motor
    motor.dispose()


@pytest.fixture()
def cena(motor_pg, request):
    """Escola isolada: a ficha oficial e o stub dela, na mesma turma."""
    sufixo = request.node.name[-24:]
    with Session(motor_pg) as db:
        escola = Escola(nome=f"ESCOLA FUSAO PG {sufixo}", ano_letivo_ativo=2026)
        db.add(escola)
        db.flush()
        admin = Usuario(escola_id=escola.id, nome="Admin PG",
                        email=f"fusao-{escola.id}-{sufixo}@teste.local",
                        senha_hash="x", cargo="admin")
        db.add(admin)
        for ns, valores in scoring.PESOS_PADRAO.items():
            db.add(Configuracao(escola_id=escola.id, namespace=ns, chave="valores", valor=valores))
        db.add(NivelDificuldade(escola_id=escola.id, nome="Nivel", codigo="nivel",
                                codigos=["AA"], pontos_padrao=1.0, ordem=0))
        db.add(ReferenciaNormalizacao(escola_id=escola.id, modo="auto"))
        turma = Turma(escola_id=escola.id, nome="3º Ano A", ano_escolar="3º Ano",
                      ano_letivo=2026, turno="manha")
        imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
        db.add_all([turma, imp])
        db.flush()
        oficial = Aluno(escola_id=escola.id, nome="Zefa Quaresma Lima", da_lista_piloto=True)
        stub = Aluno(escola_id=escola.id, nome="Zefa Quaresma")
        db.add_all([oficial, stub])
        db.flush()
        for a in (oficial, stub):
            db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                             ano_letivo=2026))
        db.commit()
        return {"escola": escola.id, "admin": admin.id, "oficial": oficial.id,
                "stub": stub.id, "importacao": imp.id}


def _fundir_rota(motor, c, erros, *, nome="FUSAO"):
    def _alvo():
        try:
            with Session(motor) as db:
                academico.fundir_alunos(
                    dados=FusaoAlunos(manter_id=c["oficial"], remover_id=c["stub"],
                                      confirmacao="FUNDIR"),
                    escola_id=c["escola"], usuario=db.get(Usuario, c["admin"]), db=db)
        except Exception as erro:  # noqa: BLE001 — é o que o teste mede
            erros.append(erro)

    t = threading.Thread(target=_alvo, name=nome)
    t.start()
    return t


def _fundir_lote_rota(motor, c, erros):
    def _alvo():
        try:
            with Session(motor) as db:
                r = academico.corrigir_alunos_duplicados(
                    dados=CorrigirDuplicadosAlunos(loser_ids=[c["stub"]], confirmacao="FUNDIR"),
                    escola_id=c["escola"], usuario=db.get(Usuario, c["admin"]), db=db)
                assert r["fundidos"] == 1, r
        except Exception as erro:  # noqa: BLE001
            erros.append(erro)

    t = threading.Thread(target=_alvo, name="LOTE")
    t.start()
    return t


def _fundir_lote_servico(motor, c, erros):
    def _alvo():
        try:
            with Session(motor) as db:
                r = alunos_dedup.aplicar_deduplicacao(db, c["escola"], [c["stub"]], c["admin"])
                db.commit()
                assert r["fundidos"] == 1, r
        except Exception as erro:  # noqa: BLE001
            erros.append(erro)

    t = threading.Thread(target=_alvo, name="SERVICO")
    t.start()
    return t


def _esperando_a_trava(motor, escola_id: int) -> bool:
    """Alguma conexão está PARADA na trava da escola (e não correndo por fora)?"""
    with motor.connect() as espia:
        return espia.execute(text(
            "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted "
            "AND classid=:c AND objid=:o"), {"c": _NS_IMPORTACAO, "o": escola_id}).scalar_one() > 0


def _ate_esperar(motor, escola_id: int, prazo: float = 10.0) -> bool:
    limite = time.monotonic() + prazo
    while time.monotonic() < limite:
        if _esperando_a_trava(motor, escola_id):
            return True
        time.sleep(0.02)
    return False


@pytest.mark.parametrize("disparar", [_fundir_rota, _fundir_lote_rota, _fundir_lote_servico],
                         ids=["fundir", "corrigir", "aplicar_deduplicacao"])
def test_fusao_espera_a_coleta_e_nao_perde_o_que_ela_gravou(motor_pg, cena, disparar):
    """A coleta segura a trava; a fusão chega e ESPERA; a coleta grava retrato e
    vínculo na ficha que vai sumir e comita; a fusão então move tudo para a oficial.

    A ordem das etapas é a que fecha o deadlock se a fusão travasse depois de
    escrever: quem espera a trava não pode estar segurando linha nenhuma, senão o
    INSERT da coleta (que confere a FK do stub) pararia atrás dela."""
    erros: list[Exception] = []
    coleta = Session(motor_pg)
    try:
        bloquear_escola_para_importacao(coleta, cena["escola"])

        t = disparar(motor_pg, cena, erros)
        assert _ate_esperar(motor_pg, cena["escola"]), (
            f"a fusão não esperou a coleta (erros: {erros}): sem exclusão mútua")

        # Com a fusão já na fila, a coleta escreve no stub (a FK pede a linha dele).
        coleta.add(SnapshotMatific(escola_id=cena["escola"], aluno_id=cena["stub"],
                                   importacao_id=cena["importacao"],
                                   data_referencia=datetime(2026, 9, 1),
                                   atividades=42, estrelas=99, pontuacao_media=2.3))
        coleta.add(IdentidadeExterna(escola_id=cena["escola"], aluno_id=cena["stub"],
                                     plataforma="matific", id_externo="conta-do-stub"))
        coleta.commit()
        t.join(60)
        assert not t.is_alive(), "a fusão não terminou depois da coleta soltar a trava"
    finally:
        coleta.close()

    assert erros == [], f"fusão falhou na corrida: {erros}"
    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["stub"]) is None, "o stub devia ter sido absorvido"
        retratos = db.execute(select(SnapshotMatific.aluno_id, SnapshotMatific.atividades).where(
            SnapshotMatific.escola_id == cena["escola"])).all()
        assert retratos == [(cena["oficial"], 42)], "o retrato da coleta se perdeu no CASCADE"
        vinculo = db.execute(select(IdentidadeExterna.aluno_id).where(
            IdentidadeExterna.escola_id == cena["escola"],
            IdentidadeExterna.id_externo == "conta-do-stub")).scalars().all()
        assert vinculo == [cena["oficial"]], "o vínculo da coleta se perdeu no CASCADE"


def test_duas_fusoes_do_mesmo_stub_uma_espera_e_a_outra_recebe_404(motor_pg, cena, monkeypatch):
    """Duplo clique: a 2ª fusão relê o estado depois da 1ª e diz que a ficha não
    existe mais, em vez de estourar FK, NoResultFound ou apagar duas vezes."""
    entrou, soltar = threading.Event(), threading.Event()
    real = alunos_fusao.fundir_par

    def _lento(db, escola_id, manter, remover, usuario_id):
        r = real(db, escola_id, manter, remover, usuario_id)
        if threading.current_thread().name == "F1":
            entrou.set()
            assert soltar.wait(30)
        return r

    monkeypatch.setattr(alunos_fusao, "fundir_par", _lento)

    erros: list[Exception] = []
    t1 = _fundir_rota(motor_pg, cena, erros, nome="F1")
    assert entrou.wait(30), "a 1ª fusão nem chegou a fundir"
    t2 = _fundir_rota(motor_pg, cena, erros, nome="F2")
    assert _ate_esperar(motor_pg, cena["escola"]), "a 2ª fusão atravessou a 1ª"
    soltar.set()
    t1.join(60)
    t2.join(60)

    assert len(erros) == 1, erros
    assert isinstance(erros[0], HTTPException) and erros[0].status_code == 404, erros
    with Session(motor_pg) as db:
        assert db.get(Aluno, cena["oficial"]) is not None
        assert db.execute(select(func.count()).select_from(Aluno).where(
            Aluno.escola_id == cena["escola"])).scalar_one() == 1


def test_a_trava_cai_no_commit_e_o_recalculo_nao_a_segura(motor_pg, cena, monkeypatch):
    """Hierarquia contra deadlock ENTRE travas: o recálculo (4713) nunca é pedido
    por quem ainda segura a de importação (4711), e a fusão não vaza a trava."""
    segurados: list[list[int]] = []
    contexto_real = scoring._carregar_contexto

    def _contexto(db, eid):
        segurados.append(sorted(db.execute(text(
            "SELECT DISTINCT classid FROM pg_locks WHERE locktype='advisory' "
            "AND pid = pg_backend_pid()")).scalars()))
        return contexto_real(db, eid)

    monkeypatch.setattr(scoring, "_carregar_contexto", _contexto)
    erros: list[Exception] = []
    t = _fundir_rota(motor_pg, cena, erros)
    t.join(60)
    assert erros == [], erros
    assert segurados, "o recálculo da fusão nem rodou"
    for travas in segurados:
        assert _NS_RECALCULO in travas
        assert _NS_IMPORTACAO not in travas, "4713 pedida ainda segurando 4711"
    with motor_pg.connect() as espia:
        assert espia.execute(text(
            "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND classid=:c AND objid=:o"),
            {"c": _NS_IMPORTACAO, "o": cena["escola"]}).scalar_one() == 0, "a trava vazou"
