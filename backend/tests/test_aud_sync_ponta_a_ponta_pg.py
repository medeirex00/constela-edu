"""O PONTA A PONTA da sincronização (``test_aud_sync_ponta_a_ponta``) e as
regressões da auditoria da sync no PostgreSQL REAL — local e descartável
(``TEST_DATABASE_URL_PG``; o nome do banco precisa conter 'test') — e mais DUAS
COLETAS AO MESMO TEMPO (Elefante e Matific da mesma escola, em threads e sessões
separadas, como dois workers). Sobrescreve a fixture ``db`` só neste módulo e
reusa os testes dos módulos SQLite, para as duas execuções afirmarem a mesma
coisa. Dados fictícios; conectores reais com navegador falso."""
import os
import threading

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.models import Nota
from app.models.plataformas import Leitura, SnapshotElefante, SnapshotMatific
from app.models.sincronizacao import SincronizacaoExecucao
from app.sync import service
from tests._sync_nucleo_fakes import NavElefante, alertas_abertos, contagens, credencial, instalar
from tests.test_aud_sync_ponta_a_ponta import escola_ficticia, origem_elefante, placar_matific

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]

_FABRICA: dict = {}


@pytest.fixture()
def db():
    engine = create_engine(URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    _FABRICA["sessao"] = TestSession
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
    _FABRICA.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


from tests.test_aud_sync_cursor_formato_leituras import (  # noqa: E402,F401
    test_data_renomeada_e_formato_que_mudou_e_nao_conta_em_dia as test_pg_formato_nao_em_dia,
    test_data_renomeada_nao_avanca_o_cursor_nem_perde_o_livro as test_pg_cursor_formato)
from tests.test_aud_sync_credenciais_fora_do_loop import (  # noqa: E402,F401
    test_salvar_e_validar_nao_consulta_o_banco_no_event_loop as test_pg_salvar_fora_do_loop,
    test_testar_conexao_nao_consulta_o_banco_no_event_loop as test_pg_testar_fora_do_loop)
from tests.test_aud_sync_matific_numero_ilegivel import (  # noqa: E402,F401
    test_numero_ilegivel_nao_grava_retrato_zero_no_acumulado as test_pg_numero_ilegivel)
from tests.test_aud_sync_ponta_a_ponta import (  # noqa: E402,F401
    test_coleta_completa_das_duas_plataformas_e_repetir_nao_duplica as test_pg_ponta_a_ponta,
    test_sincronizar_agora_duplo_reaproveita_a_execucao as test_pg_agora_duplo)
from tests.test_aud_sync_politica_professor import (  # noqa: E402,F401
    test_bloquear_nao_cria_conta_de_professor_nem_titular as test_pg_bloquear_professor)


def test_pg_elefante_e_matific_ao_mesmo_tempo_nao_corrompem(db, escola_completa, monkeypatch):
    eid, alunos = escola_ficticia(db, escola_completa)
    credencial(db, eid, "elefante")
    credencial(db, eid, "matific")
    instalar(monkeypatch, nav_elefante=NavElefante(origem_elefante(alunos)),
             placar=placar_matific(alunos))
    ids = {plat: service.enfileirar(db, eid, plat, origem="manual").id
           for plat in ("elefante", "matific")}
    db.commit()

    erros, barreira = [], threading.Barrier(2)

    def _rodar(plat):
        s = _FABRICA["sessao"]()
        try:
            barreira.wait(10)
            service.executar(s, s.get(SincronizacaoExecucao, ids[plat]))
        except BaseException as exc:  # noqa: BLE001 — o teste decide
            erros.append((plat, repr(exc)))
        finally:
            s.close()

    threads = [threading.Thread(target=_rodar, args=(p,)) for p in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    db.expire_all()
    estados = {p: (db.get(SincronizacaoExecucao, i).status, db.get(SincronizacaoExecucao, i).motivo)
               for p, i in ids.items()}
    assert not erros, erros
    assert estados == {"elefante": ("concluida", None), "matific": ("concluida", None)}, (
        estados, alertas_abertos(db, eid), contagens(db, eid))
    assert db.scalar(select(func.count()).select_from(Leitura).where(
        Leitura.escola_id == eid)) == 5
    assert db.scalar(select(func.count()).select_from(SnapshotMatific).where(
        SnapshotMatific.escola_id == eid)) == 4
    assert db.scalar(select(func.count()).select_from(SnapshotElefante).where(
        SnapshotElefante.escola_id == eid)) == 4
    # As notas refletem as DUAS plataformas (o último recálculo leu os dois dados).
    notas = db.execute(select(Nota).where(Nota.escola_id == eid)).scalars().all()
    assert len(notas) == 4
    assert sum(n.nota_elefante or 0 for n in notas) > 0 and sum(
        n.nota_matific or 0 for n in notas) > 0, [
        (n.aluno_id, n.nota_elefante, n.nota_matific) for n in notas]
    assert alertas_abertos(db, eid) == []
