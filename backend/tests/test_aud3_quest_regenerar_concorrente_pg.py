"""Regenerar DUAS turmas ao mesmo tempo, com troca cruzada de crianças desde a última
folha, num PostgreSQL REAL — local e descartável (``TEST_DATABASE_URL_PG``; o nome do
banco precisa conter 'test'). S_G_QUEST-2.

``gerar_cartoes`` (quest/routers/professor.py) revoga em três passos, cada um na sua
ordem: inativos da turma, quem SAIU dela desde a última folha e os matriculados. Com a
troca cruzada (x foi de A para B e y de B para A), a revogação de A travava x (quem
saiu) e depois y (matriculada); a de B travava y e depois x. O PostgreSQL abortava uma
das duas com ``DeadlockDetected``: 500, sem PDF. Agora as revogações de turma da mesma
escola passam por uma trava da escola (``bloquear_escola_para_cartoes_quest``): a 2ª
espera a 1ª terminar e as duas respondem 200.

Sobrescreve a fixture ``db`` só neste módulo (padrão de
test_quest_regenerar_turma_quem_saiu_pg.py). Dados 100% fictícios.
"""
import os
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.models import Aluno, Matricula, Turma
from app.quest.models import QuestCredencialAluno
from app.quest.services import credenciais as svc_cred

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]

ENTRAR = "/api/v1/quest/auth/entrar"


@pytest.fixture()
def db():
    engine = create_engine(URL, pool_size=10, max_overflow=10)
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


def _cenario(db, cliente, escola, rodada: int, por_turma: int = 3):
    """Turmas A e B do ano ativo, folha impressa das duas e, depois, a troca cruzada
    (a Lista Piloto e a troca manual reescrevem a matrícula). Devolve
    ``(turma_a_id, turma_b_id, x_id, y_id)``: x foi de A para B, y de B para A."""
    turmas = []
    for letra in ("A", "B"):
        turma = Turma(escola_id=escola.id, nome=f"R{rodada} 4º Ano {letra}",
                      ano_escolar="4º Ano", ano_letivo=escola.ano_letivo_ativo)
        db.add(turma)
        db.flush()
        for i in range(por_turma):
            aluno = Aluno(escola_id=escola.id, nome=f"Crianca Ficticia R{rodada}{letra}{i:02d}")
            db.add(aluno)
            db.flush()
            db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                             ano_letivo=escola.ano_letivo_ativo))
        turmas.append(turma)
    db.commit()
    turma_a, turma_b = turmas
    for turma in (turma_a, turma_b):
        r = cliente.post(f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/cartoes")
        assert r.status_code == 200, r.text
    db.expire_all()
    mat_x = db.execute(select(Matricula).where(Matricula.turma_id == turma_a.id)
                       .order_by(Matricula.aluno_id)).scalars().first()
    mat_y = db.execute(select(Matricula).where(Matricula.turma_id == turma_b.id)
                       .order_by(Matricula.aluno_id)).scalars().first()
    mat_x.turma_id, mat_y.turma_id = turma_b.id, turma_a.id
    db.commit()
    return turma_a.id, turma_b.id, mat_x.aluno_id, mat_y.aluno_id


def _corrida(cliente, escola_id: int, turma_a: int, turma_b: int) -> dict:
    """As duas regenerações largam juntas; devolve ``{rótulo: (status, erro)}``."""
    cabecalhos = dict(cliente.headers)
    largada = threading.Barrier(2, timeout=30)
    saida: dict = {}

    def _uma(rotulo: str, turma_id: int) -> None:
        c = TestClient(app)
        c.headers.update(cabecalhos)
        largada.wait()
        try:
            r = c.post(f"/api/v1/escolas/{escola_id}/quest/turmas/{turma_id}/cartoes"
                       "?regenerar=true")
            saida[rotulo] = (r.status_code, "")
        except Exception as erro:  # noqa: BLE001 — o teste mostra o erro do servidor
            causa = getattr(erro, "orig", None) or erro
            saida[rotulo] = (500, f"{type(causa).__name__}: "
                                  f"{str(causa).splitlines()[0][:120]}")

    fios = [threading.Thread(target=_uma, args=(rotulo, turma_id))
            for rotulo, turma_id in (("turma_A", turma_a), ("turma_B", turma_b))]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join(90)
    assert not any(fio.is_alive() for fio in fios), "uma regeneração ficou presa"
    return saida


def _codigo(db, aluno_id: int) -> str:
    db.expire_all()
    return db.execute(select(QuestCredencialAluno.codigo_login)
                      .where(QuestCredencialAluno.aluno_id == aluno_id)).scalar_one()


def test_pg_troca_cruzada_com_as_duas_ja_tendo_revogado_quem_saiu(
        cliente, db, escola_completa, monkeypatch):
    """Intercalação forçada: cada regeneração espera a outra (até 5 s) logo depois de
    revogar "quem saiu" e antes dos matriculados. Sem a trava da escola as duas chegam
    ali juntas e o ciclo de travas fecha; com ela, a 2ª nem começa antes da 1ª terminar
    (a espera expira e cada uma segue sozinha)."""
    escola = escola_completa["escola"]
    turma_a, turma_b, x, y = _cenario(db, cliente, escola, rodada=0)
    as_duas_revogaram = threading.Barrier(2, timeout=5)
    original = svc_cred.revogar_cartoes_que_sairam_da_turma

    def _com_gancho(db_, escola_id, turma):
        revogados = original(db_, escola_id, turma)
        try:
            as_duas_revogaram.wait()
        except threading.BrokenBarrierError:
            pass
        return revogados

    antes = {aluno_id: _codigo(db, aluno_id) for aluno_id in (x, y)}
    monkeypatch.setattr(svc_cred, "revogar_cartoes_que_sairam_da_turma", _com_gancho)
    saida = _corrida(cliente, escola.id, turma_a, turma_b)
    print(f"\n[pg-gancho] respostas: {saida}")
    assert all(status == 200 for status, _ in saida.values()), (
        f"regenerar A e B ao mesmo tempo, com troca cruzada: {saida}")
    # x e y foram revogados (as duas folhas os alcançam): o código de antes não entra
    # mais, e o que ficou no banco (o da folha que terminou por último) entra.
    for aluno_id, codigo_antigo in antes.items():
        assert TestClient(app).post(ENTRAR, json={"codigo": codigo_antigo}).status_code == 401
        assert TestClient(app).post(ENTRAR, json={"codigo": _codigo(db, aluno_id)}).status_code == 200


def test_pg_troca_cruzada_sem_gancho_em_varias_rodadas(cliente, db, escola_completa):
    """Sem gancho: as duas regenerações só largam juntas. Antes, 5 de 6 rodadas
    terminavam com uma das duas em 500 (``DeadlockDetected``)."""
    escola = escola_completa["escola"]
    rodadas = []
    for rodada in range(1, 7):
        turma_a, turma_b, _x, _y = _cenario(db, cliente, escola, rodada=rodada, por_turma=15)
        rodadas.append(_corrida(cliente, escola.id, turma_a, turma_b))
    falhas = [r for r in rodadas if any(status != 200 for status, _ in r.values())]
    print(f"\n[pg-sem-gancho] rodadas com alguma resposta != 200: {len(falhas)} de {len(rodadas)}")
    for r in rodadas:
        print(f"[pg-sem-gancho]   {r}")
    assert not falhas, f"{len(falhas)} de {len(rodadas)} rodadas com erro: {falhas[:2]}"
