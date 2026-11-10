"""A fusão de alunos toma a MESMA trava da importação/coleta, na ordem certa.

No SQLite a trava é no-op, então aqui só se prova a ORDEM (nenhuma ficha é lida
antes da trava) e que a hierarquia com o recálculo é respeitada. A corrida real
entre transações está em ``test_fusao_trava_escola_pg.py``. Dados fictícios.
"""
from sqlalchemy import event

from app.routers import academico
from app.services import alunos_dedup, scoring
from tests.sync_integridade_comum import aluno


def _fichas(db, ec):
    oficial = aluno(db, ec["escola"].id, ec["turma"], "Zefa Quaresma Lima", da_lista_piloto=True)
    stub = aluno(db, ec["escola"].id, ec["turma"], "Zefa Quaresma")
    db.commit()
    return oficial.id, stub.id  # ids já lidos: o espião só deve ver as leituras da rota


class _Espiao:
    """Conta os SELECT em ``alunos`` e fotografa quantos vieram antes da trava."""

    def __init__(self, db):
        self.motor = db.get_bind()
        self.lidas = 0
        self.lidas_antes_da_trava = None
        event.listen(self.motor, "before_cursor_execute", self._ver)

    def _ver(self, conn, cursor, sql, params, contexto, muitos):
        texto = " ".join(str(sql).lower().split())
        if texto.startswith("select") and "from alunos" in texto:
            self.lidas += 1

    def travou(self):
        self.lidas_antes_da_trava = self.lidas

    def parar(self):
        event.remove(self.motor, "before_cursor_execute", self._ver)


def _com_espiao(db, monkeypatch, modulo):
    espiao = _Espiao(db)
    chamadas = []
    real = modulo.bloquear_escola_para_importacao

    def _spy(sessao, eid):
        espiao.travou()
        chamadas.append(eid)
        return real(sessao, eid)

    monkeypatch.setattr(modulo, "bloquear_escola_para_importacao", _spy)
    return espiao, chamadas


def test_fundir_trava_antes_de_ler_as_fichas(cliente, db, escola_completa, monkeypatch):
    oficial_id, stub_id = _fichas(db, escola_completa)
    eid = escola_completa["escola"].id
    espiao, chamadas = _com_espiao(db, monkeypatch, academico)
    try:
        r = cliente.post(f"/api/v1/escolas/{eid}/alunos/fundir",
                         json={"manter_id": oficial_id, "remover_id": stub_id,
                               "confirmacao": "FUNDIR"})
    finally:
        espiao.parar()
    assert r.status_code == 200, r.text
    assert chamadas == [eid], "a fusão manual não tomou a trava da escola"
    assert espiao.lidas_antes_da_trava == 0, "leu ficha antes da trava: leitura obsoleta"
    assert espiao.lidas > 0, "o espião não viu leitura nenhuma: teste inócuo"


def test_confirmacao_invalida_nao_toma_a_trava(cliente, db, escola_completa, monkeypatch):
    """Pedido recusado antes de tocar no banco não enfileira atrás de uma coleta."""
    oficial_id, stub_id = _fichas(db, escola_completa)
    eid = escola_completa["escola"].id
    espiao, chamadas = _com_espiao(db, monkeypatch, academico)
    try:
        r = cliente.post(f"/api/v1/escolas/{eid}/alunos/fundir",
                         json={"manter_id": oficial_id, "remover_id": stub_id,
                               "confirmacao": "talvez"})
    finally:
        espiao.parar()
    assert r.status_code == 400
    assert chamadas == []


def test_lote_trava_antes_de_recomputar_os_candidatos(cliente, db, escola_completa, monkeypatch):
    oficial_id, stub_id = _fichas(db, escola_completa)
    eid = escola_completa["escola"].id
    espiao, chamadas = _com_espiao(db, monkeypatch, alunos_dedup)
    try:
        r = cliente.post(f"/api/v1/escolas/{eid}/alunos/duplicados/corrigir",
                         json={"loser_ids": [stub_id], "confirmacao": "FUNDIR"})
    finally:
        espiao.parar()
    assert r.status_code == 200, r.text
    assert r.json()["fundidos"] == 1
    assert chamadas == [eid], "a fusão em lote não tomou a trava da escola"
    assert espiao.lidas_antes_da_trava == 0
    assert espiao.lidas > 0


def test_servico_do_lote_toma_a_trava_sozinho(db, escola_completa, monkeypatch):
    """O serviço não depende da rota para se proteger: outro chamador herda a trava."""
    oficial_id, stub_id = _fichas(db, escola_completa)
    eid = escola_completa["escola"].id
    admin_id = escola_completa["admin"].id
    espiao, chamadas = _com_espiao(db, monkeypatch, alunos_dedup)
    try:
        alunos_dedup.aplicar_deduplicacao(db, eid, [stub_id], admin_id)
    finally:
        espiao.parar()
    assert chamadas == [eid]
    assert espiao.lidas_antes_da_trava == 0


def test_recalculo_so_depois_do_commit_que_solta_a_trava(cliente, db, escola_completa, monkeypatch):
    """Hierarquia (``bloquear_escola_para_recalculo``): 4713 nunca com 4711 presa."""
    oficial_id, stub_id = _fichas(db, escola_completa)
    eid = escola_completa["escola"].id
    pendencias = []
    real = scoring.recalcular_escola

    def _recalcular(sessao, escola):
        pendencias.append((len(sessao.new), len(sessao.dirty), len(sessao.deleted)))
        return real(sessao, escola)

    monkeypatch.setattr(scoring, "recalcular_escola", _recalcular)
    r = cliente.post(f"/api/v1/escolas/{eid}/alunos/fundir",
                     json={"manter_id": oficial_id, "remover_id": stub_id,
                           "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    assert pendencias == [(0, 0, 0)], "recalculou com a transação da fusão aberta"
