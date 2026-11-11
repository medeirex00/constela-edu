"""'Pontuação por turma' depois da virada do ano letivo (G_VIRADA-5).

As turmas de um ano letivo novo são linhas novas, e a pontuação por turma é guardada por
``turma_id``: o motor aplica às Notas do ano ativo só a configuração das turmas desse ano.
Antes, o seletor listava as turmas ATIVAS de todos os anos com o mesmo rótulo
('3º Ano A · 3º Ano' duas vezes) — a de 2026 continuava editável e o "salva. Notas
recalculadas." não mudava nada no ranking.

O que estes testes sustentam:

* a tela recebe só as turmas do ano letivo ATIVO da escola, cada uma com ``ano_letivo``, e o
  ano letivo da lista (``ano_letivo``), para o rótulo dizer de que ano são;
* antes da virada, as turmas do ano em curso continuam lá com a configuração salva.

Dados INVENTADOS (fixture ``escola_completa``).
"""

URL = "/api/v1/escolas/{eid}/configuracoes/pontuacao-turma"


def _patch_ano(cliente, eid, ano):
    return cliente.patch(f"/api/v1/escolas/{eid}", json={"ano_letivo_ativo": ano})


def test_antes_da_virada_a_turma_do_ano_aparece_com_a_configuracao(cliente_global,
                                                                     escola_completa):
    eid, t26 = escola_completa["escola"].id, escola_completa["turma"]
    r = cliente_global.put(URL.format(eid=eid), json={"turma_id": t26.id, "pontos": {"D": 9}})
    assert r.status_code == 200, r.text
    dados = cliente_global.get(URL.format(eid=eid)).json()
    assert dados["ano_letivo"] == 2026
    assert [(t["turma_id"], t["ano_letivo"], t["pontos"]) for t in dados["turmas"]] == [
        (t26.id, 2026, {"D": 9.0})]


def test_depois_da_virada_so_as_turmas_do_ano_ativo(cliente_global, escola_completa):
    eid, t26 = escola_completa["escola"].id, escola_completa["turma"]
    r = cliente_global.put(URL.format(eid=eid), json={"turma_id": t26.id, "pontos": {"D": 9}})
    assert r.status_code == 200, r.text
    assert _patch_ano(cliente_global, eid, 2027).status_code == 200
    novo = cliente_global.post(f"/api/v1/escolas/{eid}/turmas", json={
        "nome": "3º Ano A", "ano_escolar": "3º Ano", "ano_letivo": 2027})
    assert novo.status_code == 201, novo.text
    dados = cliente_global.get(URL.format(eid=eid)).json()
    # A turma de 2026 (ainda ativa, não arquivada) não aparece: a configuração dela não
    # pesa nas Notas de 2027 e o seletor teria duas opções '3º Ano A · 3º Ano'.
    assert [(t["turma_id"], t["nome"], t.get("ano_letivo"), t["pontos"])
            for t in dados["turmas"]] == [(novo.json()["id"], "3º Ano A", 2027, {})]
    assert dados["ano_letivo"] == 2027
