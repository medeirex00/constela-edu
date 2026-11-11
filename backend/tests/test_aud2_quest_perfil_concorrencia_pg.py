"""Vestiário e preferências: toques rápidos não perdem troca (G_QUEST-3), num PostgreSQL
REAL, local e descartável (``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test').

``trocar_avatar`` e ``trocar_preferencias`` mesclavam a troca no perfil lido pela
dependência ``get_aluno_atual``, sem trava, e regravavam o dicionário JSON INTEIRO. Em
READ COMMITTED, duas requisições que leram a mesma versão gravavam uma por cima da
outra: as duas respondiam 200 e uma troca sumia do banco (a criança troca pele, cabelo
e chapéu em sequência e algum item "volta" sozinho). Agora as duas rotas relêem o perfil
com ``SELECT ... FOR UPDATE`` antes de mesclar: a segunda espera a primeira gravar e
mescla sobre a versão nova.

Sobrescreve a fixture ``db`` só neste módulo (padrão de
test_quest_regenerar_turma_quem_saiu_pg.py). Dados fictícios.
"""
import os
import threading

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base, get_db
from app.core.deps import oauth2_scheme
from app.main import app
from app.quest.deps import get_aluno_atual
from app.quest.models import QuestCredencialAluno
from app.quest.routers import auth as quest_auth_router
from app.quest.services import perfis as svc_perfis

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]

ENTRAR = "/api/v1/quest/auth/entrar"
PERFIL = "/api/v1/quest/perfil"


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


@pytest.fixture(autouse=True)
def _limitadores_limpos():
    for lim in (quest_auth_router.limitador_codigo, quest_auth_router.limitador_ip,
                quest_auth_router.limitador_codigo_conta,
                quest_auth_router.limitador_ip_falha,
                quest_auth_router.limitador_global_falha):
        lim._eventos.clear()
    yield


def _cabecalho_da_crianca(cliente, db, escola, turma, aluno_id) -> dict:
    r = cliente.post(f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/cartoes")
    assert r.status_code == 200, r.text
    db.expire_all()
    codigo = db.execute(select(QuestCredencialAluno.codigo_login)
                        .where(QuestCredencialAluno.aluno_id == aluno_id)).scalar_one()
    r = TestClient(app).post(ENTRAR, json={"codigo": codigo})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _dois_ao_mesmo_tempo(rota: str, cab: dict, corpos: list[dict]) -> list[int]:
    """Os dois PATCH já leram o perfil (get_aluno_atual) antes de qualquer um gravar:
    a intercalação que o toque rápido produz. A barreira fica DEPOIS da leitura da
    dependência e ANTES da rota — vale com ou sem a trava."""
    barreira = threading.Barrier(len(corpos), timeout=15)

    def _lento(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
        ctx = get_aluno_atual(token=token, db=db)
        barreira.wait()
        return ctx

    app.dependency_overrides[get_aluno_atual] = _lento
    status: list[int] = []
    try:
        def _patch(corpo):
            status.append(TestClient(app).patch(rota, headers=cab, json=corpo).status_code)

        fios = [threading.Thread(target=_patch, args=(c,)) for c in corpos]
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join(60)
    finally:
        app.dependency_overrides.pop(get_aluno_atual, None)
    return status


def test_dois_patch_de_avatar_simultaneos_guardam_as_duas_trocas(cliente, db,
                                                                 escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    cab = _cabecalho_da_crianca(cliente, db, escola, turma, escola_completa["alunos"][0].id)

    status = _dois_ao_mesmo_tempo(f"{PERFIL}/avatar", cab,
                                  [{"pele": "#8D5524"}, {"cabelo": "afro"}])

    assert sorted(status) == [200, 200]
    final = TestClient(app).get(PERFIL, headers=cab).json()["avatar"]
    assert (final["pele"], final["cabelo"]) == ("#8D5524", "afro"), (
        f"troca perdida depois de dois 200: pele={final['pele']} cabelo={final['cabelo']}")


def test_dois_patch_de_preferencias_simultaneos_guardam_as_duas(cliente, db,
                                                               escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    cab = _cabecalho_da_crianca(cliente, db, escola, turma, escola_completa["alunos"][1].id)

    status = _dois_ao_mesmo_tempo(f"{PERFIL}/preferencias", cab,
                                  [{"som": False}, {"musica": False}])

    assert sorted(status) == [200, 200]
    final = TestClient(app).get(PERFIL, headers=cab).json()["preferencias"]
    assert (final["som"], final["musica"]) == (False, False), final


def test_oito_toques_simultaneos_em_slots_diferentes_nao_perdem_nenhum(cliente, db,
                                                                      escola_completa):
    """Sem gancho: 8 PATCH ao mesmo tempo, cada um num slot, três rodadas."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    cab = _cabecalho_da_crianca(cliente, db, escola, turma, escola_completa["alunos"][0].id)
    pedidos = {"pele": "#4A3020", "cabelo": "moicano", "cor_cabelo": "#C9302C",
               "top": "jaqueta", "chapeu": "coroa", "costas": "asas", "pet": "dino",
               "veiculo": "patins"}
    perdidos_por_rodada = []
    for _ in range(3):
        r = TestClient(app).patch(f"{PERFIL}/avatar", headers=cab,
                                  json=dict(svc_perfis.AVATAR_PADRAO))
        assert r.status_code == 200, r.text
        inicio = threading.Barrier(len(pedidos), timeout=15)

        def _um(slot, valor):
            inicio.wait()
            TestClient(app).patch(f"{PERFIL}/avatar", headers=cab, json={slot: valor})

        fios = [threading.Thread(target=_um, args=kv) for kv in pedidos.items()]
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join(60)
        final = TestClient(app).get(PERFIL, headers=cab).json()["avatar"]
        perdidos_por_rodada.append(sorted(s for s, v in pedidos.items() if final[s] != v))
    assert perdidos_por_rodada == [[], [], []]
