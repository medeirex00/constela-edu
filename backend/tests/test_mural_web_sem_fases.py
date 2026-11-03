"""AS FASES NÃO CONCORREM também no MURAL da web (página Conquistas).

O pacote do app (`/sincronizacao`) e o telão já recortavam o mural pelas turmas
premiáveis; a rota da web (`/gamificacao/mural`) chamava o serviço sem recorte e
punha a criança da Educação Infantil no "Aluno do Dia/Semana/Mês" e nos eventos.
O mesmo gestor via uma vitrine no app e outra na web.

O cenário dá à criança da Fase o MAIOR volume de tudo: sem o corte, ela é a
primeira de cada destaque.
"""
from tests.test_ranking_fases_cobertura import cenario  # noqa: F401 (fixture)

API = "/api/v1"


def test_mural_da_web_sem_a_fase(cliente, cenario):  # noqa: F811
    escola_id = cenario["escola"].id
    r = cliente.get(f"{API}/escolas/{escola_id}/gamificacao/mural")
    assert r.status_code == 200, r.text
    corpo = r.json()
    destaques = [d for d in corpo["destaques"].values() if d]
    # Não é um mural vazio: quem concorre continua em destaque.
    assert destaques
    assert {d["aluno_id"] for d in destaques} <= cenario["do_fund"]
    assert corpo["eventos"]
    assert not any("Crianca" in e["texto"] for e in corpo["eventos"])


def test_mural_da_web_e_o_do_app_mostram_os_mesmos_eventos(cliente, cenario):  # noqa: F811
    escola_id = cenario["escola"].id
    web = cliente.get(f"{API}/escolas/{escola_id}/gamificacao/mural").json()["eventos"]
    app = cliente.get(f"{API}/escolas/{escola_id}/sincronizacao").json()["mural"]
    assert [e["texto"] for e in web] == [e["texto"] for e in app]
