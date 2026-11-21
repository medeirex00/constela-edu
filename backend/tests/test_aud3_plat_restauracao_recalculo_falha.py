"""Restauração histórica com falha no recálculo: a falha não fica escondida (REV3-PLAT-3).

Desde S_G_AJUSTE-4 a restauração aplicada entra na fila da escola (4711), grava a
data e o tempo com a auditoria e comita (o commit solta a trava) ANTES de recalcular
a escola — a hierarquia das travas: nunca pedir a do recálculo segurando a 4711. O
preço é que dado e notas não caem mais juntos. Se o recálculo falhava (queda de
conexão, tempo esgotado), a resposta era 500 "Erro interno" com a restauração já
gravada e auditada e as notas e posições velhas; a retentativa recusava com 422
"Nada foi perdido neste livro" e não recalculava — as notas ficavam velhas até a
próxima importação, sem nada que avisasse.

Agora a falha no recálculo é dita: 200 com ``recalculo_pendente`` e o aviso de usar
"Recalcular"; a pendência fica aberta para a escola (o alerta ``recalculo_pendente``
do Elefante, o mesmo que a sincronização usa, e que o próximo Recalcular fecha); a
retentativa diz que a leitura JÁ FOI restaurada e que falta recalcular, em vez de
"Nada foi perdido". Dados fictícios.
"""
from sqlalchemy import select

from app.models import Leitura, LogAuditoria, Nota
from app.services import scoring
from app.sync import service as sync_service
from tests.test_leituras_restauracao import (DATA_REAL, MOTIVO, ORIGEM, _evento,
                                             _leitura, _livro)

API = "/api/v1"


def _notas(db, escola_id: int) -> dict:
    db.expire_all()
    return {n.aluno_id: (round(n.nota_elefante or 0, 4), n.posicao)
            for n in db.execute(select(Nota).where(Nota.escola_id == escola_id)).scalars()}


def _cena(db, escola_completa) -> dict:
    """Uma leitura de nível D que a fusão deixou com a data velha e 1 minuto; o evento
    prova 06/08/2026 e 40 minutos. Os colegas leram o mesmo livro com 20 e 30 minutos:
    o tempo de leitura é relativo à turma, então restaurar muda a nota do aluno."""
    escola = escola_completa["escola"]
    aluno, *colegas = escola_completa["alunos"]
    livro = _livro(db, escola.id, nivel="D")
    leitura = _leitura(db, escola.id, aluno.id, livro.id)
    for colega, minutos in zip(colegas, (20, 30)):
        _leitura(db, escola.id, colega.id, livro.id, data=DATA_REAL, tempo=minutos)
    evento = _evento(db, escola.id, aluno.id, livro, minutos=40)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    corpo = {"itens": [{
        "aluno_id": aluno.id, "aluno_origem_id": ORIGEM, "livro_id": livro.id,
        "data_original": DATA_REAL.isoformat(), "tempo_original": 40,
        "evidencia_evento_id": evento.id, "evidencia_chave_natural": evento.chave_natural,
        "motivo": MOTIVO}], "dry_run": False, "confirmacao": "RESTAURAR HISTORICO"}
    return {"escola": escola.id, "leitura": leitura.id, "corpo": corpo,
            "url": f"{API}/escolas/{escola.id}/leituras/restaurar-historico"}


def _falhar_uma_vez(monkeypatch) -> dict:
    real = scoring.recalcular_escola
    chamadas = {"n": 0, "real": real}

    def _falha(*a, **k):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise RuntimeError("falha simulada no recálculo (queda de conexão)")
        return real(*a, **k)

    monkeypatch.setattr(scoring, "recalcular_escola", _falha)
    return chamadas


def _post(cliente, url: str, corpo: dict):
    try:
        return cliente.post(url, json=corpo)
    except RuntimeError as erro:           # o TestClient relança o erro não tratado
        return erro


def test_falha_no_recalculo_e_dita_e_a_pendencia_fica_aberta(cliente_global, db,
                                                             escola_completa, monkeypatch):
    c = _cena(db, escola_completa)
    antes = _notas(db, c["escola"])
    chamadas = _falhar_uma_vez(monkeypatch)

    r = _post(cliente_global, c["url"], c["corpo"])
    assert not isinstance(r, Exception), f"a falha no recálculo virou erro interno: {r!r}"
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["dry_run"] is False and corpo["leituras_restauradas"] == 1, corpo
    assert corpo.get("recalculo_pendente") is True, corpo
    assert "não foram recalculadas" in corpo["aviso"], corpo["aviso"]
    assert "Recalcular" in corpo["aviso"], corpo["aviso"]

    # A restauração ficou gravada e auditada; as notas, como estavam — e isso fica
    # visível para a escola até um recálculo dar certo.
    db.expire_all()
    lida = db.get(Leitura, c["leitura"])
    assert (lida.data, lida.tempo_leitura_min) == (DATA_REAL, 40)
    acoes = sorted(db.execute(select(LogAuditoria.acao).where(
        LogAuditoria.acao.like("leitura%"))).scalars().all())
    assert acoes == ["leitura.data_restaurada", "leituras.restauracao_historica"], acoes
    assert _notas(db, c["escola"]) == antes
    assert sync_service.recalculo_pendente_aberto(db, c["escola"], "elefante"), (
        "a pendência do recálculo não ficou registrada para a escola")

    # A retentativa não diz "Nada foi perdido": diz que já foi restaurada e o que falta.
    r2 = cliente_global.post(c["url"], json=c["corpo"])
    assert r2.status_code == 422, r2.text
    detalhe = r2.json()["detail"]
    assert "Nada foi perdido" not in detalhe, detalhe
    assert "já foi restaurada" in detalhe and "Recalcular" in detalhe, detalhe

    # "Recalcular" deixa as notas iguais às de um recálculo de verdade e fecha a pendência.
    rec = cliente_global.post(f"{API}/escolas/{c['escola']}/importacoes/recalcular")
    assert rec.status_code == 200, rec.text
    depois = _notas(db, c["escola"])
    assert not sync_service.recalculo_pendente_aberto(db, c["escola"], "elefante")
    chamadas["real"](db, c["escola"])
    verdade = _notas(db, c["escola"])
    assert verdade != antes, "cenário inválido: a restauração não mexe na nota"
    assert depois == verdade


def test_sem_falha_recalcula_na_mesma_resposta_e_nao_deixa_pendencia(cliente_global, db,
                                                                     escola_completa):
    c = _cena(db, escola_completa)
    antes = _notas(db, c["escola"])
    r = cliente_global.post(c["url"], json=c["corpo"])
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["leituras_restauradas"] == 1
    assert not corpo.get("recalculo_pendente"), corpo
    assert "aviso" not in corpo, corpo
    assert _notas(db, c["escola"]) != antes
    assert not sync_service.recalculo_pendente_aberto(db, c["escola"], "elefante")


def test_leitura_que_ja_tinha_a_data_continua_nada_foi_perdido(cliente_global, db,
                                                               escola_completa):
    """A regra 10 sem restauração anterior não muda: o livro em que as duas fichas
    tinham a mesma data segue recusado com "Nada foi perdido"."""
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id, nivel="D")
    _leitura(db, escola.id, aluno.id, livro.id, data=DATA_REAL, tempo=40)
    evento = _evento(db, escola.id, aluno.id, livro, minutos=40)
    db.commit()
    r = cliente_global.post(
        f"{API}/escolas/{escola.id}/leituras/restaurar-historico",
        json={"itens": [{
            "aluno_id": aluno.id, "aluno_origem_id": ORIGEM, "livro_id": livro.id,
            "data_original": DATA_REAL.isoformat(), "tempo_original": 40,
            "evidencia_evento_id": evento.id,
            "evidencia_chave_natural": evento.chave_natural, "motivo": MOTIVO}],
            "dry_run": False, "confirmacao": "RESTAURAR HISTORICO"})
    assert r.status_code == 422, r.text
    detalhe = r.json()["detail"]
    assert "Nada foi perdido" in detalhe and "já foi restaurada" not in detalhe, detalhe
