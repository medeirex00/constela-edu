"""Certificados em LOTE: a requisição não segura transação aberta enquanto o Chromium
desenha cada certificado.

As guardas de cada aluno (SELECTs) abriam a transação da sessão da requisição, e o
commit só vinha depois de gerar TODOS os PDFs (~1,5 s cada, até 50 = ~75 s): uma
conexão "idle in transaction" durante o lote inteiro — que, num pooler em transaction
mode, prende uma conexão do servidor. Agora a transação das leituras é fechada antes
de cada renderização, e a auditoria vai numa transação curta no fim. Achado
DESEMPENHO-5 (só o lote; o "ao vivo" não). Dados INVENTADOS.
"""
import pytest
from sqlalchemy import select

from app.core.database import get_db
from app.main import app
from app.models import LogAuditoria
from tests.test_certificados_lote import _aluno, _lote, _pdf


@pytest.fixture()
def sessoes_da_requisicao():
    """As sessões que o ``get_db`` (o da fixture ``db``) entrega às rotas."""
    original = app.dependency_overrides[get_db]
    vistas: list = []

    def _get_db():
        for sessao in original():
            vistas.append(sessao)
            yield sessao

    app.dependency_overrides[get_db] = _get_db
    yield vistas
    app.dependency_overrides[get_db] = original


@pytest.fixture()
def renderizador_que_olha_a_transacao(monkeypatch, sessoes_da_requisicao):
    """Troca as duas funções que desenham UM certificado; cada chamada anota se a
    sessão da requisição estava numa transação naquele instante."""
    from app.services import relatorios as svc

    estado = {"durante": [], "falhar": set()}

    def _olhar(qual, nome):
        estado["durante"].append((qual, nome, sessoes_da_requisicao[-1].in_transaction()))

    def _arte(escola_nome, aluno_nome, modelo, *, bimestre=None):
        _olhar("arte", aluno_nome)
        if aluno_nome in estado["falhar"]:
            raise RuntimeError("sem Chromium (simulado)")
        return _pdf(f"ARTE {modelo} {aluno_nome}")

    def _geral(**kw):
        _olhar("geral", kw["aluno_nome"])
        return _pdf(f"GERAL {kw['aluno_nome']}")

    monkeypatch.setattr(svc, "gerar_certificado_plataforma", _arte)
    monkeypatch.setattr(svc, "gerar_certificado", _geral)
    return estado


def _emitidos(db) -> list[int]:
    db.rollback()
    return sorted(db.execute(select(LogAuditoria.entidade_id).where(
        LogAuditoria.acao == "certificado.emitido")).scalars())


@pytest.mark.parametrize("modelo", [None, "elefante"])
def test_lote_nao_desenha_com_transacao_aberta(cliente, db, escola_completa, modelo,
                                               renderizador_que_olha_a_transacao):
    escola = escola_completa["escola"]
    ids = [_aluno(db, escola, f"CRIANCA FICTICIA LOTE {i}").id for i in range(4)]
    r = _lote(cliente, escola.id, ids, modelo)
    assert r.status_code == 200, r.text
    durante = renderizador_que_olha_a_transacao["durante"]
    assert len(durante) == 4
    abertas = [d for d in durante if d[2]]
    assert not abertas, f"transação aberta durante a renderização: {abertas}"
    assert _emitidos(db) == sorted(ids)          # a auditoria continua gravada


def test_fallback_da_arte_para_o_geral_tambem_desenha_sem_transacao(
        cliente, db, escola_completa, renderizador_que_olha_a_transacao):
    """A arte que falha cai no Geral, que relê o mérito no banco: a transação dessa
    releitura também é fechada antes de desenhar o Geral."""
    escola = escola_completa["escola"]
    ok = _aluno(db, escola, "ARTE FICTICIA OK")
    cai = _aluno(db, escola, "ARTE FICTICIA FALHA")
    renderizador_que_olha_a_transacao["falhar"].add(cai.nome)
    r = _lote(cliente, escola.id, [cai.id, ok.id], "matific")
    assert r.status_code == 200, r.text
    durante = renderizador_que_olha_a_transacao["durante"]
    assert [(q, n) for q, n, _ in durante] == [
        ("arte", cai.nome), ("geral", cai.nome), ("arte", ok.nome)]
    assert not [d for d in durante if d[2]], durante
    assert _emitidos(db) == sorted([ok.id, cai.id])
