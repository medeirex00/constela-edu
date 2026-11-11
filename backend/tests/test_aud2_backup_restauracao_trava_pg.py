"""G_LGPD-6 — restauração do backup × coleta da MESMA escola ao mesmo tempo, num
PostgreSQL REAL (o SQLite tem um escritor só e a trava lá é no-op).

``backup.restaurar`` não tomava ``bloquear_escola_para_importacao`` (4711), que a
importação, a coleta, a fusão e a exclusão tomam. Duas ordens:

  A) a coleta já começou (segura a 4711 e gravou na ficha) e a restauração chega: a
     restauração não esperava a trava, parava só no lock de linha e, depois do commit
     da coleta, sobrava o registro da importação dela sem dado nenhum;
  B) a restauração já apagou e recriou as fichas (sem commit) e a coleta chega: a
     coleta lia as fichas antigas, gravava nelas e caía com ``ForeignKeyViolation``
     quando a restauração comitava (a sincronização em "falha"; o envio manual, 500).

Com a trava, a 2ª ESPERA a 1ª na 4711 e relê o estado: a coleta grava na ficha
recriada; a restauração apaga a importação da coleta junto com o resto.

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud2_backup_restauracao_trava_pg.py -m postgres

Dados fictícios.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.database import Base, _NS_IMPORTACAO
from app.models import (Aluno, Configuracao, Escola, IdentidadeExterna, Importacao, Matricula,
                        NivelDificuldade, ReferenciaNormalizacao, SnapshotMatific, Turma, Usuario)
from app.routers.importacoes import _confirmar_sem_commit
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import backup as svc_backup
from app.services import scoring

URL_PG = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL_PG, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL_PG) and "test" not in (make_url(URL_PG).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]

UUID = "uuid-ficticio-aud2-trava"
NOME = "Zefa Quaresma Aud2"


@pytest.fixture(scope="module")
def motor_pg():
    motor = create_engine(URL_PG, pool_size=8, max_overflow=8, pool_pre_ping=True)
    import app.quest.models  # noqa: F401 — registra o schema completo

    Base.metadata.create_all(motor)
    yield motor
    motor.dispose()


@pytest.fixture()
def cena(motor_pg, request):
    """Escola isolada com uma ficha (conta da plataforma e um retrato) e o arquivo dela."""
    sufixo = request.node.name[-20:]
    with Session(motor_pg) as db:
        escola = Escola(nome=f"ESCOLA FICTICIA AUD2 TRAVA {sufixo}", ano_letivo_ativo=2026)
        db.add(escola)
        db.flush()
        admin = Usuario(escola_id=escola.id, nome="Admin PG",
                        email=f"aud2-trava-{escola.id}-{sufixo}@teste.local", senha_hash="x",
                        cargo="admin")
        db.add(admin)
        for ns, valores in scoring.PESOS_PADRAO.items():
            db.add(Configuracao(escola_id=escola.id, namespace=ns, chave="valores", valor=valores))
        db.add(NivelDificuldade(escola_id=escola.id, nome="Nivel", codigo="nivel",
                                codigos=["AA"], pontos_padrao=1.0, ordem=0))
        db.add(ReferenciaNormalizacao(escola_id=escola.id, modo="auto"))
        turma = Turma(escola_id=escola.id, nome="3º Ano A", ano_escolar="3º Ano", ano_letivo=2026)
        imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
        db.add_all([turma, imp])
        db.flush()
        ficha = Aluno(escola_id=escola.id, nome=NOME)
        db.add(ficha)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=ficha.id, turma_id=turma.id,
                         ano_letivo=2026))
        db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=ficha.id, plataforma="matific",
                                 id_externo=UUID))
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=ficha.id, importacao_id=imp.id,
                               data_referencia=datetime(2026, 8, 1), atividades=10,
                               estrelas=10, pontuacao_media=50))
        db.commit()
        dados = json.loads(json.dumps(svc_backup.exportar(db, escola.id), default=str))
        return {"escola": escola.id, "admin": admin.id, "ficha": ficha.id,
                "turma": turma.nome, "dados": dados}


def _coleta_sem_commit(db, c):
    corpo = ImportacaoConfirm(
        plataforma="matific", formato="resumo", tipo="texto",
        linhas=[LinhaConfirmacao(nome=NOME, criar_em_turma_nome=c["turma"], dados={
            "matific_uuid": UUID, "turma_relatorio": c["turma"],
            "atividades": 77, "estrelas": 77, "pontuacao_media": 90})],
        recalcular=False, sincronizar_turma=True, permitir_criar_turma=False,
        permitir_criar_aluno=True)
    return _confirmar_sem_commit(dados=corpo, escola_id=c["escola"],
                                 usuario=db.get(Usuario, c["admin"]), db=db)


def _restaurar_sem_commit(db, c):
    return svc_backup.restaurar(db, c["escola"], c["dados"], avisos=[])


def _esperando_a_trava(motor, escola_id: int) -> bool:
    """Alguma conexão está PARADA na trava da escola (e não correndo por fora)?"""
    with motor.connect() as espia:
        return espia.execute(text(
            "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted "
            "AND classid=:c AND objid=:o"), {"c": _NS_IMPORTACAO, "o": escola_id}).scalar_one() > 0


def _ate_esperar(motor, escola_id: int, fio: threading.Thread, prazo: float = 15.0) -> bool:
    limite = time.monotonic() + prazo
    while time.monotonic() < limite and fio.is_alive():
        if _esperando_a_trava(motor, escola_id):
            return True
        time.sleep(0.05)
    return False


def _estado(motor, eid):
    with Session(motor) as db:
        alunos = db.execute(select(Aluno.id).where(Aluno.escola_id == eid)).scalars().all()
        snaps = db.execute(select(SnapshotMatific.aluno_id, SnapshotMatific.estrelas).where(
            SnapshotMatific.escola_id == eid)).all()
        imps = db.execute(select(Importacao.id).where(Importacao.escola_id == eid)).scalars().all()
        sem_dado = [i for i in imps if not db.execute(
            select(func.count()).select_from(SnapshotMatific)
            .where(SnapshotMatific.importacao_id == i)).scalar_one()]
        return {"alunos": alunos, "snapshots": snaps, "importacoes_sem_dado": sem_dado}


def test_ordem_b_a_coleta_espera_a_restauracao_e_grava_na_ficha_recriada(motor_pg, cena):
    erros, feitos = [], []
    restauracao = Session(motor_pg)
    try:
        _restaurar_sem_commit(restauracao, cena)

        def _alvo():
            with Session(motor_pg) as db:
                try:
                    feitos.append(_coleta_sem_commit(db, cena))
                    db.commit()
                except Exception as erro:  # noqa: BLE001 — é o que o teste mede
                    db.rollback()
                    erros.append(erro)

        fio = threading.Thread(target=_alvo, name="COLETA")
        fio.start()
        esperou = _ate_esperar(motor_pg, cena["escola"], fio)
        restauracao.commit()
        fio.join(60)
    finally:
        restauracao.close()
    assert not erros, f"a coleta que chegou durante a restauração caiu: {erros[0]!r}"[:400]
    assert esperou, "a coleta não esperou a trava da escola: leu as fichas de antes"
    estado = _estado(motor_pg, cena["escola"])
    [ficha] = estado["alunos"]
    assert ficha != cena["ficha"]                    # a ficha recriada pela restauração
    assert (ficha, 77) in estado["snapshots"], estado
    assert estado["importacoes_sem_dado"] == [], estado


def test_ordem_a_a_restauracao_espera_a_coleta_e_nao_sobra_importacao_vazia(motor_pg, cena):
    erros = []
    coleta = Session(motor_pg)
    try:
        _coleta_sem_commit(coleta, cena)

        def _alvo():
            with Session(motor_pg) as db:
                try:
                    _restaurar_sem_commit(db, cena)
                    db.commit()
                except Exception as erro:  # noqa: BLE001
                    db.rollback()
                    erros.append(erro)

        fio = threading.Thread(target=_alvo, name="RESTAURA")
        fio.start()
        esperou = _ate_esperar(motor_pg, cena["escola"], fio)
        coleta.commit()
        fio.join(60)
    finally:
        coleta.close()
    assert not erros, f"a restauração caiu: {erros[0]!r}"[:400]
    assert esperou, "a restauração não esperou a trava da escola"
    estado = _estado(motor_pg, cena["escola"])
    assert estado["importacoes_sem_dado"] == [], (
        f"sobrou o registro da importação da coleta sem nenhum dado: {estado}")
    [ficha] = estado["alunos"]
    assert estado["snapshots"] == [(ficha, 10)]      # o arquivo, por inteiro
