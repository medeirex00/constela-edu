"""PEND-30 (API_SEGURANCA-5/6) — o push aos aparelhos sai DEPOIS da resposta.

``_pos_commit_importacao`` (usado pelo /confirmar com recálculo, pelo /recalcular
do lote e pelo /revisoes/{id}/resolver) chamava ``push.notificar_escola`` dentro da
requisição: mesmo com a transação fechada antes da rede, quem importava esperava a
chamada ao Expo — até 15 s por lote de 100 aparelhos — para ver o resultado.

Agora o push é uma tarefa depois da resposta, com SESSÃO PRÓPRIA (a da requisição
já está fechada quando a tarefa roda), no mesmo banco. A ordem é conferida no nível
do ASGI: a mensagem final da resposta sai antes do push. A sincronização automática,
que não é uma requisição, continua notificando na hora. Dados fictícios; o Expo é
trocado por um falso (sem rede).
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import DispositivoMovel, RevisaoIdentidade
from app.services import push

API = "/api/v1"
VIVO = "ExponentPushToken[ficticio-depois-0001]"
MORTO = "ExponentPushToken[ficticio-depois-0002]"


def _com_registro(eventos: list):
    """O app, anotando quando a resposta termina de ser enviada."""
    async def asgi(scope, receive, send):
        async def enviar(mensagem):
            if mensagem["type"] == "http.response.body" and not mensagem.get("more_body"):
                eventos.append("resposta")
            await send(mensagem)
        await app(scope, receive, enviar)
    return asgi


def _cliente_registrando(cliente, eventos):
    c = TestClient(_com_registro(eventos))
    c.headers.update(cliente.headers)
    return c


def _push_registrando(monkeypatch, eventos):
    sessoes = []

    def falso(db, escola_id, titulo, corpo, dados=None, **kw):
        eventos.append("push")
        sessoes.append(db)
        return 0
    monkeypatch.setattr(push, "notificar_escola", falso)
    return sessoes


def _corpo_matific(escola_completa, recalcular=True):
    return {"plataforma": "matific", "formato": "resumo", "tipo": "texto",
            "recalcular": recalcular,
            "linhas": [{"nome": a.nome, "aluno_id": a.id,
                        "dados": {"atividades": 10 + i, "pontuacao_media": 3.0,
                                  "estrelas": 30 + i}}
                       for i, a in enumerate(escola_completa["alunos"])]}


def test_confirmar_responde_antes_do_push(cliente, db, escola_completa, monkeypatch):
    eventos: list = []
    _push_registrando(monkeypatch, eventos)
    eid = escola_completa["escola"].id

    r = _cliente_registrando(cliente, eventos).post(
        f"{API}/escolas/{eid}/importacoes/confirmar", json=_corpo_matific(escola_completa))

    assert r.status_code == 200, r.text
    assert eventos == ["resposta", "push"]


def test_recalcular_do_lote_responde_antes_do_push(cliente, db, escola_completa,
                                                   monkeypatch):
    eventos: list = []
    _push_registrando(monkeypatch, eventos)
    eid = escola_completa["escola"].id

    r = _cliente_registrando(cliente, eventos).post(f"{API}/escolas/{eid}/importacoes/recalcular")

    assert r.status_code == 200, r.text
    assert eventos == ["resposta", "push"]


def test_resolver_revisao_responde_antes_do_push(cliente, db, escola_completa,
                                                 monkeypatch):
    eid = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    placar = json.dumps({"fonte": "matific-placar", "turma": "3º Ano A", "alunos": [
        {"nome": ana.nome, "uuid": "uuid-fict-ana", "estrelas": 9, "atividades": 2}]})
    analise = cliente.post(f"{API}/escolas/{eid}/importacoes/analisar",
                           data={"texto": placar}).json()
    linha = analise["linhas"][0]
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": analise["plataforma"], "formato": analise["formato"],
        "tipo": analise["tipo"], "recalcular": False, "data_referencia": "2026-08-14T12:00:00",
        "linhas": [{"nome": linha["nome"], "dados": linha["dados"],
                    "criar_em_turma_nome": "3º Ano A", "deixar_para_revisao": True}]})
    assert r.status_code == 200, r.text
    rev = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).scalars().one()
    eventos: list = []
    _push_registrando(monkeypatch, eventos)

    r = _cliente_registrando(cliente, eventos).post(
        f"{API}/escolas/{eid}/importacoes/revisoes/{rev.id}/resolver",
        json={"aluno_id": ana.id})

    assert r.status_code == 200, r.text
    assert eventos == ["resposta", "push"]


def test_push_depois_da_resposta_usa_sessao_propria_e_limpa_token_morto(
        cliente, db, escola_completa, monkeypatch):
    """O push de verdade (Expo falso): o aparelho vivo recebe e o token morto sai do
    banco — a limpeza é gravada pela sessão própria da tarefa."""
    eid = escola_completa["escola"].id
    admin = escola_completa["admin"]
    db.add_all([DispositivoMovel(escola_id=eid, usuario_id=admin.id, token_push=VIVO,
                                 plataforma="android"),
                DispositivoMovel(escola_id=eid, usuario_id=admin.id, token_push=MORTO,
                                 plataforma="android")])
    db.commit()
    lotes = []
    monkeypatch.setattr(push, "_enviar_lotes", lambda ls: lotes.extend(ls) or [MORTO])

    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar",
                     json=_corpo_matific(escola_completa))

    assert r.status_code == 200, r.text
    assert sorted(m["to"] for lote in lotes for m in lote) == [VIVO, MORTO]
    db.expire_all()
    assert [d.token_push for d in db.query(DispositivoMovel).all()] == [VIVO]


def test_falha_inesperada_no_push_nao_derruba_a_resposta(cliente, db, escola_completa,
                                                         monkeypatch, caplog):
    def explode(*a, **k):
        raise RuntimeError("falha de teste no push")
    monkeypatch.setattr(push, "notificar_escola", explode)
    eid = escola_completa["escola"].id

    with caplog.at_level("ERROR", logger="constela.importacao"):
        r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar",
                         json=_corpo_matific(escola_completa))

    assert r.status_code == 200, r.text
    assert any("push" in rec.getMessage().lower() for rec in caplog.records), caplog.records


@pytest.mark.parametrize("recalcular", [False])
def test_sem_recalculo_nao_ha_push(cliente, db, escola_completa, monkeypatch, recalcular):
    eventos: list = []
    _push_registrando(monkeypatch, eventos)
    eid = escola_completa["escola"].id
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar",
                     json=_corpo_matific(escola_completa, recalcular=recalcular))
    assert r.status_code == 200, r.text
    assert eventos == []
