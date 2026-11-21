"""Restauração histórica de leituras × fusão em andamento — só o PostgreSQL prova
(S_G_AJUSTE-4).

A fusão segura a trava da escola (4711), descarta a leitura repetida da ficha
absorvida e apaga a ficha. ``POST /leituras/restaurar-historico`` não pedia a trava:

  * fusão primeiro: a restauração conferia tudo no estado ainda sem commit, parava no
    UPDATE da linha que a fusão apagou e, quando a fusão comitava, caía com
    ``StaleDataError`` (500 "Erro interno");
  * restauração primeiro: a fusão lia a leitura no estado antigo e parava no DELETE;
    quando a restauração comitava ("restaurada"), a fusão apagava a leitura e gravava
    no log ``aluno.fundido`` a data VELHA como a descartada.

Agora a restauração aplicada pede a trava ANTES de ler qualquer coisa: as duas ordens
viram uma fila. Fusão primeiro → a restauração espera, relê e recusa (422) dizendo que
a ficha não existe mais. Restauração primeiro → a fusão espera o commit e registra a
data restaurada. O recálculo vem depois do commit que solta a trava (a hierarquia).

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud3_plat_restauracao_fusao_pg.py -m postgres

Dados fictícios.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.database import _NS_IMPORTACAO, _NS_RECALCULO
from app.models import EventoAluno, Leitura, LogAuditoria, Livro, Usuario
from app.routers import plataformas
from app.schemas import RestauracaoLeituras
from app.services import alunos_fusao, leituras_restauracao, scoring
from app.services.eventos import chave_evento
from tests.test_fusao_trava_escola_pg import (_fundir_rota, cena,  # noqa: F401
                                              motor_pg, pytestmark)

ORIGEM = 987654                       # ficha absorvida numa fusão ANTERIOR (só no hash)
DATA_EVENTO = datetime(2026, 8, 6, 0, 1)
TITULO = "Livro Inventado da Restauracao PG"
# Quanto o teste espera para concluir que o outro lado está PARADO. Sem a trava, a
# restauração para no UPDATE da linha (e cai depois); com ela, fica na trava.
ESPERA_S = 1.5
TETO_S = 60


def _montar(motor_pg, cena):
    """A ficha oficial e o stub leram o mesmo livro; o stub guarda o evento que prova a
    data original (ele veio de uma ficha absorvida antes, ``ORIGEM``)."""
    with Session(motor_pg) as db:
        livro = Livro(escola_id=cena["escola"], titulo=TITULO, nivel_codigo="AA")
        db.add(livro)
        db.flush()
        db.add(Leitura(escola_id=cena["escola"], aluno_id=cena["oficial"], livro_id=livro.id,
                       data=datetime(2026, 9, 1, 10), tempo_leitura_min=3, nivel_codigo="AA"))
        leitura_stub = Leitura(escola_id=cena["escola"], aluno_id=cena["stub"],
                               livro_id=livro.id, data=datetime(2026, 9, 20, 10),
                               tempo_leitura_min=1, nivel_codigo="AA")
        db.add(leitura_stub)
        evento = EventoAluno(
            escola_id=cena["escola"], aluno_id=cena["stub"], plataforma="elefante",
            tipo_evento="leitura", ocorrido_em=DATA_EVENTO, conteudo_titulo=TITULO,
            livro_id=livro.id, tempo_segundos=120, nivel_codigo="AA",
            chave_natural=chave_evento("elefante", "leitura", ORIGEM, TITULO, DATA_EVENTO))
        db.add(evento)
        db.commit()
        return {"livro": livro.id, "leitura_stub": leitura_stub.id, "evento": evento.id,
                "chave": evento.chave_natural}


def _pedido(cena, m) -> RestauracaoLeituras:
    return RestauracaoLeituras(
        itens=[{"aluno_id": cena["stub"], "aluno_origem_id": ORIGEM, "livro_id": m["livro"],
                "data_original": DATA_EVENTO, "tempo_original": 2,
                "evidencia_evento_id": m["evento"], "evidencia_chave_natural": m["chave"],
                "motivo": "fusao anterior manteve a data velha; o evento prova a original"}],
        dry_run=False, confirmacao="RESTAURAR HISTORICO")


def _disparar_restauracao(motor_pg, cena, m, respostas, erros) -> threading.Thread:
    def _alvo():
        try:
            with Session(motor_pg) as db:
                respostas.append(plataformas.restaurar_leituras_historicas(
                    dados=_pedido(cena, m), usuario=db.get(Usuario, cena["admin"]),
                    escola_id=cena["escola"], db=db))
        except Exception as erro:  # noqa: BLE001 — é o que o teste mede
            erros.append(erro)

    t = threading.Thread(target=_alvo, name="RESTAURA")
    t.start()
    return t


def test_fusao_primeiro_a_restauracao_espera_e_recusa_explicando(motor_pg, cena,
                                                                 monkeypatch):
    m = _montar(motor_pg, cena)
    entrou, soltar = threading.Event(), threading.Event()
    real = alunos_fusao.fundir_par

    def _lenta(db, escola_id, manter, remover, usuario_id):
        r = real(db, escola_id, manter, remover, usuario_id)   # descartou, sem commit
        if threading.current_thread().name == "FUSAO":
            entrou.set()
            assert soltar.wait(TETO_S)
        return r

    monkeypatch.setattr(alunos_fusao, "fundir_par", _lenta)
    erros_fusao: list[Exception] = []
    erros: list[Exception] = []
    respostas: list = []
    t_fusao = _fundir_rota(motor_pg, cena, erros_fusao)
    t_rest = None
    try:
        assert entrou.wait(TETO_S), f"a fusão não chegou a fundir: {erros_fusao}"
        t_rest = _disparar_restauracao(motor_pg, cena, m, respostas, erros)
        time.sleep(ESPERA_S)
        assert t_rest.is_alive(), f"a restauração não esperou a fusão: {respostas} {erros}"
    finally:
        soltar.set()
        t_fusao.join(TETO_S)
        if t_rest is not None:
            t_rest.join(TETO_S)
    assert erros_fusao == []
    assert respostas == [], respostas
    assert len(erros) == 1 and isinstance(erros[0], HTTPException), (
        f"a restauração caiu com {[f'{type(e).__name__}: {e}' for e in erros]} (500)")
    assert erros[0].status_code == 422
    assert "não existe" in erros[0].detail and "fundida" in erros[0].detail, erros[0].detail
    with Session(motor_pg) as db:
        assert db.execute(select(LogAuditoria.id).where(
            LogAuditoria.escola_id == cena["escola"],
            LogAuditoria.acao == leituras_restauracao.ACAO_ITEM)).first() is None


def test_restauracao_primeiro_a_fusao_espera_e_registra_a_data_restaurada(
        motor_pg, cena, monkeypatch):
    m = _montar(motor_pg, cena)
    gravou, soltar = threading.Event(), threading.Event()
    real = leituras_restauracao.restaurar

    def _lenta(db, *a, **k):
        r = real(db, *a, **k)            # UPDATE já feito (flush), antes do commit
        if threading.current_thread().name == "RESTAURA":
            gravou.set()
            assert soltar.wait(TETO_S)
        return r

    monkeypatch.setattr(leituras_restauracao, "restaurar", _lenta)
    erros_fusao: list[Exception] = []
    erros: list[Exception] = []
    respostas: list = []
    t_rest = _disparar_restauracao(motor_pg, cena, m, respostas, erros)
    t_fusao = None
    try:
        assert gravou.wait(TETO_S), f"a restauração não chegou a gravar: {erros}"
        t_fusao = _fundir_rota(motor_pg, cena, erros_fusao)
        time.sleep(ESPERA_S)
        assert t_fusao.is_alive(), "a fusão não esperou a restauração"
    finally:
        soltar.set()
        t_rest.join(TETO_S)
        if t_fusao is not None:
            t_fusao.join(TETO_S)
    assert erros == [] and erros_fusao == [], (erros, erros_fusao)
    assert respostas and respostas[0]["leituras_restauradas"] == 1
    with Session(motor_pg) as db:
        log = db.execute(select(LogAuditoria.detalhes).where(
            LogAuditoria.escola_id == cena["escola"],
            LogAuditoria.acao == "aluno.fundido")).scalars().all()
    descartes = (log[0] or {}).get("leituras_descartadas_detalhe") if log else None
    assert descartes and descartes[0]["data_remover"].startswith("2026-08-06T00:01"), (
        f"a fusão leu a leitura antes da restauração comitar e registrou a data velha: "
        f"{descartes}")


def test_o_recalculo_da_restauracao_tem_trava_compartilhada(motor_pg, cena, monkeypatch):
    """A restauração comita antes de calcular com a trava compartilhada."""
    m = _montar(motor_pg, cena)
    segurados: list[dict[int, str]] = []
    contexto_real = scoring._carregar_contexto

    def _contexto(db, eid):
        segurados.append(dict(db.execute(text(
            "SELECT classid, mode FROM pg_locks WHERE locktype='advisory' "
            "AND granted AND pid = pg_backend_pid()")).all()))
        return contexto_real(db, eid)

    monkeypatch.setattr(scoring, "_carregar_contexto", _contexto)
    respostas: list = []
    erros: list[Exception] = []
    t = _disparar_restauracao(motor_pg, cena, m, respostas, erros)
    t.join(TETO_S)
    assert erros == [] and respostas and respostas[0]["leituras_restauradas"] == 1, erros
    assert segurados, "o recálculo da restauração nem rodou"
    assert segurados == [{_NS_IMPORTACAO: "ShareLock", _NS_RECALCULO: "ExclusiveLock"}]
    with motor_pg.connect() as espia:
        assert espia.execute(text(
            "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND classid=:c "
            "AND objid=:o"), {"c": _NS_IMPORTACAO, "o": cena["escola"]}).scalar_one() == 0
