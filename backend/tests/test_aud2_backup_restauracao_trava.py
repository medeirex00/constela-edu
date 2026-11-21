"""G_LGPD-6 — a restauração do backup toma a trava da escola (4711) antes de ler.

``backup.restaurar`` apaga e recria as fichas, as turmas e as importações da escola,
mas não tomava ``bloquear_escola_para_importacao`` — a trava que a importação, a
coleta, a fusão e a exclusão tomam. No PostgreSQL, a coleta que chegava no meio
gravava nas fichas antigas e caía com ``ForeignKeyViolation`` quando a restauração
comitava; na outra ordem sobrava o registro de uma importação sem dado nenhum. A
corrida real está em ``test_aud2_backup_restauracao_trava_pg.py``; no SQLite a trava
é no-op, então aqui se prova a ORDEM: a trava vem antes de qualquer leitura da escola,
o serviço se protege sozinho (outro chamador herda a trava) e o recálculo das notas
(4713) só roda depois do commit que solta a 4711 (a hierarquia das travas).

Dados 100% fictícios (fixture escola_completa); sem rede.
"""
import json

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.services import backup as svc_backup
from app.services import scoring

API = "/api/v1"


class _Espiao:
    """Conta os SELECT nas tabelas da escola e fotografa quantos vieram antes da trava."""

    TABELAS = ("from alunos", "from turmas", "from importacoes", "from revisoes_identidade",
               "from logs_auditoria", "from quest_perfis")

    def __init__(self, db):
        self.motor = db.get_bind()
        self.lidas = 0
        self.lidas_antes_da_trava = None
        event.listen(self.motor, "before_cursor_execute", self._ver)

    def _ver(self, conn, cursor, sql, params, contexto, muitos):
        texto = " ".join(str(sql).lower().split())
        if texto.startswith("select") and any(t in texto for t in self.TABELAS):
            self.lidas += 1

    def travou(self):
        if self.lidas_antes_da_trava is None:
            self.lidas_antes_da_trava = self.lidas

    def parar(self):
        event.remove(self.motor, "before_cursor_execute", self._ver)


def _com_espiao(db, monkeypatch):
    espiao = _Espiao(db)
    chamadas = []
    real = svc_backup.bloquear_escola_para_importacao

    def _spy(sessao, eid):
        espiao.travou()
        chamadas.append(eid)
        return real(sessao, eid)

    monkeypatch.setattr(svc_backup, "bloquear_escola_para_importacao", _spy)
    return espiao, chamadas


def _arquivo(db, eid) -> bytes:
    return json.dumps(svc_backup.exportar(db, eid), default=str).encode("utf-8")


def test_restaurar_toma_a_trava_da_escola_antes_de_ler(cliente_global, db, escola_completa,
                                                       monkeypatch):
    eid = escola_completa["escola"].id
    arquivo = _arquivo(db, eid)
    espiao, chamadas = _com_espiao(db, monkeypatch)
    try:
        r = cliente_global.post(f"{API}/escolas/{eid}/restaurar",
                                files={"arquivo": ("b.json", arquivo, "application/json")})
    finally:
        espiao.parar()
    assert r.status_code == 200, r.text
    assert chamadas == [eid], "a restauração não tomou a trava da escola"
    assert espiao.lidas_antes_da_trava == 0, "leu a escola antes da trava: leitura obsoleta"
    assert espiao.lidas > 0, "o espião não viu leitura nenhuma: teste inócuo"


def test_servico_toma_a_trava_sozinho(db, escola_completa, monkeypatch):
    """O serviço não depende da rota para se proteger: um script herda a trava."""
    eid = escola_completa["escola"].id
    dados = json.loads(_arquivo(db, eid))
    espiao, chamadas = _com_espiao(db, monkeypatch)
    try:
        svc_backup.restaurar(db, eid, dados)
        db.commit()
    finally:
        espiao.parar()
    assert chamadas == [eid]
    assert espiao.lidas_antes_da_trava == 0


def test_arquivo_invalido_nao_toma_a_trava(db, escola_completa, monkeypatch):
    """Arquivo recusado antes de tocar no banco não enfileira atrás de uma coleta."""
    eid = escola_completa["escola"].id
    chamadas = []
    monkeypatch.setattr(svc_backup, "bloquear_escola_para_importacao",
                        lambda _sessao, escola: chamadas.append(escola))
    for dados in ({"versao": 99, "tabelas": {}}, {"versao": 2}):
        with pytest.raises(ValueError):
            svc_backup.restaurar(db, eid, dados)
    assert chamadas == []


def test_recalculo_so_depois_do_commit_que_solta_a_trava(cliente_global, db, escola_completa,
                                                         monkeypatch):
    """Hierarquia (``bloquear_escola_para_recalculo``): 4713 nunca com 4711 presa."""
    eid = escola_completa["escola"].id
    arquivo = _arquivo(db, eid)
    estado = {"trava": False, "violacoes": 0, "recalculos": 0}
    real = svc_backup.bloquear_escola_para_importacao

    def _travar(sessao, escola):
        estado["trava"] = True
        return real(sessao, escola)

    monkeypatch.setattr(svc_backup, "bloquear_escola_para_importacao", _travar)
    commit_real, rollback_real = Session.commit, Session.rollback

    def _commit(self):
        resultado = commit_real(self)
        estado["trava"] = False
        return resultado

    def _rollback(self):
        resultado = rollback_real(self)
        estado["trava"] = False
        return resultado

    monkeypatch.setattr(Session, "commit", _commit)
    monkeypatch.setattr(Session, "rollback", _rollback)
    recalcular_real = scoring.recalcular_escola

    def _recalcular(sessao, escola):
        estado["recalculos"] += 1
        estado["violacoes"] += estado["trava"]
        return recalcular_real(sessao, escola)

    monkeypatch.setattr(scoring, "recalcular_escola", _recalcular)
    r = cliente_global.post(f"{API}/escolas/{eid}/restaurar",
                            files={"arquivo": ("b.json", arquivo, "application/json")})
    assert r.status_code == 200, r.text
    assert estado["recalculos"] >= 1
    assert estado["violacoes"] == 0, "recalculou segurando a trava da escola"
