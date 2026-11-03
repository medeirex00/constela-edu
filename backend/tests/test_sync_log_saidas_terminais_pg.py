"""A linha ``sync_execucao_finalizada`` de cada saída para estado final num
PostgreSQL REAL — local e descartável (``TEST_DATABASE_URL_PG``; o nome do banco
precisa conter 'test').

Reusa os cenários de ``test_sync_log_saidas_terminais.py`` (UPDATE condicional,
savepoint, rollback, commit da rota) e acrescenta o que só o banco de verdade mostra:
CORRIDAS entre sessões. No PostgreSQL o segundo UPDATE condicional espera o lock da
linha e, quando o primeiro commita, reavalia o WHERE e não pega nada — quem perdeu
não encerrou a execução e não escreve. E a transição desfeita (rollback) de quem
segurava o lock não deixa linha; quem estava esperando segue e escreve a sua.
"""
from __future__ import annotations

import os
import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.models.sincronizacao import SincronizacaoExecucao
from app.sync import service
from tests.test_sync_log_saidas_terminais import (_captura, _contagem, _execucao,  # noqa: F401
                                                  _no_banco, _travada, _uma_linha)

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]

SEGURA_S = 0.6          # quanto o vencedor segura o lock da linha antes de decidir


@pytest.fixture()
def db():
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


from tests.test_sync_log_saidas_terminais import (  # noqa: E402,F401
    test_aborto_antes_do_estado_final_nao_escreve_e_a_orfa_escreve_uma as test_pg_aborto,
    test_boot_escreve_uma_linha_por_orfa_e_por_fila_liberada as test_pg_boot,
    test_cancelamento_em_savepoint_revertido_nao_escreve_e_liberado_escreve
    as test_pg_savepoint,
    test_estado_final_gravado_e_saida_por_excecao_escreve_uma_linha as test_pg_interrompida,
    test_executar_com_claim_perdido_nao_escreve as test_pg_claim_perdido,
    test_executar_fora_do_plano_cancela_com_uma_linha as test_pg_fora_do_plano,
    test_fim_normal_tem_origem_executar_e_a_segunda_chamada_nao_duplica
    as test_pg_fim_normal,
    test_pedido_manual_que_substitui_a_da_fila_escreve_no_commit as test_pg_substitui,
    test_quem_perde_a_travada_ou_o_cancelamento_nao_escreve as test_pg_quem_perde,
    test_reaper_do_agendador_escreve_uma_linha_e_a_nova_tentativa_nenhuma as test_pg_reaper,
    test_sincronizar_agora_que_substitui_a_da_fila_escreve_uma_linha as test_pg_agora,
    test_status_libera_a_fila_com_uma_linha_por_execucao as test_pg_status_fila,
    test_substituicao_em_sessao_fechada_sem_commit_nao_escreve as test_pg_sessao_fechada,
    test_substituicao_revertida_nao_escreve as test_pg_revertida,
    test_travada_achada_pelo_pedido_escreve_uma_linha as test_pg_travada_pedido)


# --------------------------------------------------------------------------
# Corridas de verdade entre sessões
# --------------------------------------------------------------------------
class _Corrida:
    """O VENCEDOR faz a transição, avisa e segura o lock da linha por ``SEGURA_S``
    antes de commitar (ou desfazer); o PERDEDOR, com o objeto lido ANTES, tenta a
    sua transição nesse meio-tempo — o UPDATE dele espera o lock."""

    def __init__(self, db):
        self.bind = db.get_bind()
        self.fez = threading.Event()
        self.erros: list[BaseException] = []
        self.espera_s = 0.0
        self.resultado = None

    def _em_thread(self, alvo) -> threading.Thread:
        def rodar():
            try:
                alvo()
            except BaseException as exc:  # noqa: BLE001 — o teste reporta
                self.erros.append(exc)
        t = threading.Thread(target=rodar, daemon=True)
        t.start()
        return t

    def rodar(self, execucao_id, vencedor, perdedor, *, desfaz=False):
        s_venc, s_perd = Session(bind=self.bind), Session(bind=self.bind)
        ex_perd = s_perd.get(SincronizacaoExecucao, execucao_id)   # o objeto velho
        s_perd.commit()

        def venc():
            assert vencedor(s_venc, s_venc.get(SincronizacaoExecucao, execucao_id))
            self.fez.set()
            time.sleep(SEGURA_S)
            s_venc.rollback() if desfaz else s_venc.commit()

        def perd():
            assert self.fez.wait(5)
            inicio = time.monotonic()
            self.resultado = perdedor(s_perd, ex_perd)
            self.espera_s = time.monotonic() - inicio
            s_perd.commit()

        try:
            threads = [self._em_thread(venc), self._em_thread(perd)]
            for t in threads:
                t.join(30)
        finally:
            s_venc.close()       # nenhuma sessão fica com a transação aberta (o
            s_perd.close()       # drop_all do fim esperaria o lock para sempre)
        assert not self.erros, self.erros
        return self


def test_pg_duas_sessoes_finalizam_a_mesma_travada_e_so_uma_escreve(
        db, escola_completa, caplog):
    eid = escola_completa["escola"].id
    exid = _travada(db, eid, "matific")
    c = _Corrida(db).rodar(
        exid,
        lambda s, ex: service._finalizar_travada(s, ex, origem="travada_no_agendador"),
        lambda s, ex: service._finalizar_travada(s, ex, origem="orfa_no_boot"))
    assert c.resultado is False                       # perdeu: o WHERE não pegou nada
    assert c.espera_s >= SEGURA_S * 0.5               # e esperou o lock do vencedor
    _uma_linha(caplog, exid, status="erro", origem="travada_no_agendador")
    assert sum(_contagem(caplog).values()) == 1


def test_pg_cancelamento_e_claim_do_executar_na_mesma_execucao(
        db, escola_completa, caplog):
    """O "Sincronizar agora" cancela a da fila enquanto a thread dela tenta o
    claim: o claim espera, perde e sai sem linha. Só o cancelamento escreve."""
    eid = escola_completa["escola"].id
    exid = _execucao(db, eid, "matific", origem="scheduler")
    c = _Corrida(db).rodar(
        exid,
        lambda s, ex: service._cancelar_na_fila(s, ex, "teste",
                                                origem="cancelada_por_pedido_manual"),
        lambda s, ex: service.executar(s, ex))
    assert c.espera_s >= SEGURA_S * 0.5
    assert _no_banco(db, exid).status == "cancelada"
    _uma_linha(caplog, exid, status="cancelada", origem="cancelada_por_pedido_manual")
    assert sum(_contagem(caplog).values()) == 1


def test_pg_cancelamento_desfeito_nao_escreve_e_o_claim_que_esperava_roda(
        db, escola_completa, caplog):
    """O cancelamento é desfeito (rollback) com o claim esperando o lock: a
    transição não aconteceu e não tem linha; o claim pega a execução, que roda até o
    fim e escreve a única linha (origem 'executar')."""
    eid = escola_completa["escola"].id
    exid = _execucao(db, eid, "matific", origem="manual")
    c = _Corrida(db).rodar(
        exid,
        lambda s, ex: service._cancelar_na_fila(s, ex, "teste",
                                                origem="cancelada_por_pedido_manual"),
        lambda s, ex: service.executar(s, ex),
        desfaz=True)
    assert c.espera_s >= SEGURA_S * 0.5
    assert _no_banco(db, exid).status == "erro"           # sem credencial
    _uma_linha(caplog, exid, status="erro", origem="executar")
    assert sum(_contagem(caplog).values()) == 1


def test_pg_varias_threads_executam_a_mesma_execucao_e_so_uma_escreve(
        db, escola_completa, caplog):
    eid = escola_completa["escola"].id
    exid = _execucao(db, eid, "matific", origem="manual")
    bind = db.get_bind()
    largada = threading.Barrier(4)
    erros: list[BaseException] = []

    def rodar():
        s = Session(bind=bind)
        try:
            ex = s.get(SincronizacaoExecucao, exid)
            s.commit()
            largada.wait(5)
            service.executar(s, ex)
        except BaseException as exc:  # noqa: BLE001
            erros.append(exc)
        finally:
            s.close()

    threads = [threading.Thread(target=rodar, daemon=True) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not erros, erros
    _uma_linha(caplog, exid, status="erro", origem="executar")
    assert sum(_contagem(caplog).values()) == 1
