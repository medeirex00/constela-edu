"""Análise educacional — a visão de UMA escola (``GET /escolas/{id}/analise``).

* os indicadores oficiais DELA (SARESP, IEE, Ideb e Saeb, todas as etapas × componentes),
  com a rede municipal como referência e o ICA só como indicador da rede;
* as plataformas por série, com a MESMA conta e a MESMA supressão da rota da rede;
* o que não dá para comparar, e por quê (ICA por escola, relação sem sobreposição de ano,
  cadastro, sem rede).

Dados INVENTADOS (decisão D13).
"""
import pytest

from tests.test_analise_base import HOJE, mundo_plataformas, nova_escola, turma_com_alunos


@pytest.fixture()
def mundo(db, cliente_global, monkeypatch):
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: HOJE)
    return {**mundo_plataformas(db), "c": cliente_global}


def _get(mundo, escola, **params):
    r = mundo["c"].get(f"/api/v1/escolas/{escola.id}/analise", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_escola_ve_os_proprios_indicadores_com_a_rede_de_referencia(mundo):
    alfa = mundo["escolas"]["alfa"]
    dados = _get(mundo, alfa)
    assert dados["escola"] == {"id": alfa.id, "nome": alfa.nome, "codigo_inep": "35990101",
                               "status": "ativa", "pendencia": None, "ano_letivo": 2026}
    assert dados["rede"] == {"id": mundo["rede"].id, "nome": mundo["rede"].nome}
    itens = {i["chave"]: i for i in dados["indicadores"]}
    assert list(itens) == ["ica", "saresp", "iee", "ideb", "saeb"]
    # SARESP: as 4 séries da escola (etapa × componente) + a rede onde ela tem número.
    saresp = itens["saresp"]["series"]
    da_escola = [s for s in saresp if s["abrangencia"] == "escola"]
    assert {(s["etapa"], s["componente"]) for s in da_escola} == {
        ("5_ano", "lp"), ("5_ano", "mt"), ("2_ano", "lp"), ("2_ano", "mt")}
    lp5 = next(s for s in da_escola if (s["etapa"], s["componente"]) == ("5_ano", "lp"))
    assert [(p["edicao"], p["valor"]) for p in lp5["pontos"]] == [(2025, 210.3)]
    assert all(s["papel"] == "referencia" for s in saresp if s["abrangencia"] == "rede")
    # O ICA só como referência da rede (nunca "o ICA da escola").
    ica = itens["ica"]
    assert ica["por_escola"] is False
    assert [s["id"] for s in ica["series"]] == ["rede_municipal"]
    assert ica["series"][0]["papel"] == "referencia"
    # Ideb da escola com a meta e a comparação; IEE com o ICM oficial.
    ideb = next(s for s in itens["ideb"]["series"] if s["abrangencia"] == "escola")
    p = {x["edicao"]: x for x in ideb["pontos"]}
    assert p[2019]["situacao_meta"] == "atingiu" and p[2023]["meta"] is None
    iee = next(s for s in itens["iee"]["series"] if s["abrangencia"] == "escola")
    assert iee["pontos"][0]["situacao_meta"] == "nao_atingiu"
    # Cada fonte citada está em `fontes`.
    ids = {x["fonte_id"] for i in dados["indicadores"] for s in i["series"] for x in s["pontos"]
           if x["fonte_id"]}
    assert ids and {str(i) for i in ids} <= set(dados["fontes"])


def test_comparacoes_indisponiveis_dizem_o_porque(mundo):
    dados = _get(mundo, mundo["escolas"]["alfa"])
    temas = {c["tema"]: c["texto"] for c in dados["comparacoes_indisponiveis"]}
    assert temas["ica"] == "O ICA é da rede: não existe por escola."
    assert "período sem sobreposição" in temas["relacao"] and "2026" in temas["relacao"]
    assert "ranking" in temas
    gama = _get(mundo, mundo["escolas"]["gama"])
    assert gama["escola"]["pendencia"] == "sem_codigo_inep"
    assert any(c["tema"] == "cadastro" for c in gama["comparacoes_indisponiveis"])
    # Sem número da escola, os pontos dizem o motivo (nunca 0).
    saresp = next(i for i in gama["indicadores"] if i["chave"] == "saresp")
    pontos = [p for s in saresp["series"] if s["abrangencia"] == "escola" for p in s["pontos"]]
    assert pontos and all(p["valor"] is None and p["motivo_ausencia"] == "sem_codigo_inep"
                          for p in pontos)


def test_plataformas_da_escola_iguais_as_da_rede(mundo):
    alfa = mundo["escolas"]["alfa"]
    escola = _get(mundo, alfa)["plataformas"]
    rede = mundo["c"].get(f"/api/v1/redes/{mundo['rede'].id}/analise/plataformas").json()
    da_rede = next(e for e in rede["escolas"] if e["escola_id"] == alfa.id)
    assert escola["alunos"] == da_rede["alunos"] == 17
    assert escola["series"] == da_rede["series"]
    assert escola["elefante"] == da_rede["elefante"] and escola["matific"] == da_rede["matific"]
    assert {s["serie"]: s["suprimido"] for s in escola["series"]} == {2: True, 3: False, 5: True}
    assert escola["janela"]["rotulo"] == "Ano letivo 2026" and escola["k_minimo"] == 5


def test_escola_sem_rede_nao_inventa_referencia(db, mundo):
    avulsa = nova_escola(db, None, "Escola Fictícia Avulsa", "35991001")
    turma_com_alunos(db, avulsa, "4º Ano", 6)
    db.commit()
    dados = _get(mundo, avulsa)
    assert dados["rede"] is None and dados["indicadores"] == [] and dados["fontes"] == {}
    assert any(c["tema"] == "sem_rede" for c in dados["comparacoes_indisponiveis"])
    plat = dados["plataformas"]
    assert plat["alunos"] == 6 and plat["modulos"] == {"elefante": True, "matific": True}
    assert plat["elefante"]["motivo_sem_dado"] == "sem_coleta"
