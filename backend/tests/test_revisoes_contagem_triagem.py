"""A14 (lado da API): a tela de Revisões passa a usar a triagem — e paga só o
necessário por ela — e ganha o total real de pendências (a lista para em 500).
Dados fictícios."""
from app.models import RevisaoIdentidade
from app.routers import importacoes
from app.services import identidade_aluno as ida


def _rev(escola_id, i, *, status="pendente", motivo="correspondencia_insegura"):
    return RevisaoIdentidade(escola_id=escola_id, chave=f"k{i}", chave_identidade=f"matific|id:c{i}",
                             plataforma="matific", formato="resumo", id_externo=f"c{i}",
                             nome_recebido=f"Crianca Ficticia {i}", motivo=motivo,
                             candidatos=[], linhas=[], contexto={}, origem="sincronizacao",
                             status=status)


def test_contagem_e_o_total_real_por_motivo(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    db.add_all([_rev(eid, 1), _rev(eid, 2, motivo="nome_incompleto"),
                _rev(eid, 3, motivo="nome_incompleto"), _rev(eid, 4, status="resolvida")])
    db.commit()
    r = cliente.get(f"/api/v1/escolas/{eid}/importacoes/contagem-revisoes")
    assert r.status_code == 200, r.text
    assert r.json() == {"pendentes": 3, "limite_da_lista": 500,
                        "por_motivo": {"correspondencia_insegura": 1, "nome_incompleto": 2}}


def test_contagem_nao_satura_no_limite_da_lista(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    db.add_all([_rev(eid, i) for i in range(503)])
    db.commit()
    lista = cliente.get(f"/api/v1/escolas/{eid}/importacoes/revisoes").json()
    assert len(lista) == 500
    assert cliente.get(f"/api/v1/escolas/{eid}/importacoes/contagem-revisoes"
                       ).json()["pendentes"] == 503


def test_lista_de_encerradas_nao_carrega_o_contexto_da_escola(cliente, db, escola_completa,
                                                               monkeypatch):
    eid = escola_completa["escola"].id
    db.add_all([_rev(eid, 1, status="resolvida"), _rev(eid, 2, status="descartada"),
                _rev(eid, 3)])
    db.commit()
    cargas = []
    real = ida.carregar_contexto

    def _espiao(*a, **k):
        cargas.append(1)
        return real(*a, **k)

    monkeypatch.setattr(importacoes.ida, "carregar_contexto", _espiao)
    r = cliente.get(f"/api/v1/escolas/{eid}/importacoes/revisoes?situacao=resolvida")
    assert r.status_code == 200 and [x["triagem"] for x in r.json()] == [None]
    assert cargas == [], "carregou a escola inteira para uma lista sem pendência"

    r = cliente.get(f"/api/v1/escolas/{eid}/importacoes/revisoes")
    assert r.status_code == 200
    assert r.json()[0]["triagem"]["classificacao"] in ("segura", "decisao_humana")
    assert cargas == [1]
