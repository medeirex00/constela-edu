"""Conquistas (web) e Insights usam a régua JUSTA da evolução — a mesma do
Ranking de Evolução, do app e do telão.

`GET /gamificacao/mural` (página Conquistas) e `insights.indices_da_escola`
chamavam `evolucao.ranking_evolucao` com o padrão `base_no_periodo=False`: a
criança cujo PRIMEIRO retrato cai dentro da janela recebia o acumulado inteiro
como "evolução". Ela virava o "Aluno do Mês/Semana" da web e tinha o MAIOR
engajamento no /insights (e no Assistente), enquanto o Ranking de Evolução, o
app (`/sincronizacao`) e o telão punham em 1º quem cresceu de verdade.

Achado RANKINGS-2. Cenário de `tests/test_mobile_evolucao_regua_justa.py`;
dados fictícios.
"""
from tests.test_mobile_evolucao_regua_justa import _cenario
from tests._ano_letivo import escola_no_ano_de_hoje  # noqa: F401 — fixture

API = "/api/v1"


def test_destaques_da_web_sao_o_1o_do_ranking_de_evolucao(cliente, db, escola_completa):
    escola, _primeira, segunda = _cenario(db, escola_completa)
    base = f"{API}/escolas/{escola.id}"
    mural = cliente.get(f"{base}/gamificacao/mural")
    app = cliente.get(f"{base}/sincronizacao")
    assert mural.status_code == 200, mural.text
    assert app.status_code == 200, app.text
    destaques = mural.json()["destaques"]

    for janela, dias in (("semana", 7), ("mes", 30)):
        ranking = cliente.get(f"{base}/ranking-evolucao", params={"dias": dias})
        assert ranking.status_code == 200, ranking.text
        topo = ranking.json()[0]
        assert topo["aluno_id"] == segunda.id, "quem cresceu de verdade lidera"
        destaque = destaques[janela]
        assert destaque is not None, janela
        assert (destaque["aluno_id"], destaque["nota_evolucao"]) == (
            topo["aluno_id"], topo["nota_evolucao"]), (
            f"a página Conquistas coroa outra criança no destaque '{janela}': "
            f"{destaque['aluno_id']} ({destaque['nota_evolucao']}) × "
            f"Ranking de Evolução {topo['aluno_id']} ({topo['nota_evolucao']})")

    # O app (aba Evolução 30d) concorda com o "Aluno do Mês" da web.
    assert app.json()["evolucao"][0]["aluno_id"] == destaques["mes"]["aluno_id"]


def test_insights_nao_premia_o_acumulado_de_quem_nao_cresceu(cliente, db, escola_completa):
    escola, primeira, segunda = _cenario(db, escola_completa)
    r = cliente.get(f"{API}/escolas/{escola.id}/insights")
    assert r.status_code == 200, r.text
    idx = {i["aluno_id"]: i for i in r.json()["indices"]}
    # Quem só tem o acumulado (1º retrato dentro da janela) não avançou na janela:
    # índice 0. Quem cresceu é o único ativo da régua percentilar: 100.
    assert (idx[primeira.id]["engajamento"], idx[primeira.id]["evolucao"]) == (0.0, 0.0), (
        f"acumulado premiado como engajamento/evolução: {idx[primeira.id]}")
    assert (idx[segunda.id]["engajamento"], idx[segunda.id]["evolucao"]) == (100.0, 100.0)
