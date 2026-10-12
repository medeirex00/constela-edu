"""TETO DE ESTRELAS no Ranking de Matemática por período (decisão do dono,
2026-10-12: "aplicar ao ranking de Matemática o teto de estrelas já
documentado").

O teto mora em ``matific_destaque.limitar_estrelas`` (no máximo 5 estrelas por
atividade do período) e a premiação "Melhor Matemática" já o aplicava em
``ganho_no_periodo``. ``GET /escolas/{id}/ranking/matematica`` ordenava pelas
estrelas BRUTAS: a mesma criança, no mesmo período, contava 50 estrelas aqui e
10 na premiação. Estes testes travam:

  (1) com excesso, a ORDEM muda — conta o que o teto deixa contar;
  (2) sem excesso, o ranking sai IDÊNTICO ao da regra antiga (o teto é no-op);
  (3) estrela sem atividade não conta, e quem não fez atividade sai do período;
  (4) ranking e premiação contam as MESMAS estrelas para os mesmos dados.

O excesso nasce pelo caminho real (importação por período), que não valida
``estrelas ≤ 5 × atividades`` — é exatamente o dado que o teto neutraliza.
"""
from __future__ import annotations

API = "/api/v1/escolas"
MARCO = "?periodo=personalizado&inicio=2026-03-01&fim=2026-03-31"
ABRIL = "?periodo=personalizado&inicio=2026-04-01&fim=2026-04-30"


def _importar(cliente, escola_id, aluno, inicio, fim, ativ, estrelas, media=4.0):
    r = cliente.post(f"{API}/{escola_id}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
        "periodo_inicio": inicio, "periodo_fim": fim,
        "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id,
                    "dados": {"atividades": ativ, "pontuacao_media": media,
                              "estrelas": estrelas}}]})
    assert r.status_code == 200, r.text


def _ranking(cliente, escola_id, query) -> list[dict]:
    r = cliente.get(f"{API}/{escola_id}/ranking/matematica{query}")
    assert r.status_code == 200, r.text
    return r.json()


def _podio_matematica(cliente, escola_id, query) -> list[dict]:
    r = cliente.get(f"{API}/{escola_id}/premiacoes{query}&limite=50")
    assert r.status_code == 200, r.text
    return {c["chave"]: c["podio"] for c in r.json()["categorias"]}["melhor_matematica"]


def test_excesso_de_estrelas_por_atividade_muda_a_ordem(cliente, db, escola_completa):
    """2 atividades com 50 estrelas no período → contam 10 (5 × 2). Pela regra
    antiga a Ana (50 brutas) ficava à frente do João (40); agora o João, que
    tem 40 estrelas legítimas em 10 atividades, é o 1º."""
    esc = escola_completa["escola"]
    ana, joao, _ = escola_completa["alunos"]
    _importar(cliente, esc.id, ana, "2026-03-01", "2026-04-01", 2, 50)
    _importar(cliente, esc.id, joao, "2026-03-01", "2026-04-01", 10, 40)

    linhas = _ranking(cliente, esc.id, MARCO)

    assert [i["aluno_id"] for i in linhas] == [joao.id, ana.id]
    assert [i["posicao"] for i in linhas] == [1, 2]
    por_id = {i["aluno_id"]: i for i in linhas}
    assert (por_id[ana.id]["estrelas"], por_id[ana.id]["estrelas_brutas"],
            por_id[ana.id]["teto_estrelas_aplicado"]) == (10, 50, True)
    assert (por_id[joao.id]["estrelas"], por_id[joao.id]["estrelas_brutas"],
            por_id[joao.id]["teto_estrelas_aplicado"]) == (40, 40, False)
    # As atividades não são tocadas pelo teto.
    assert (por_id[ana.id]["atividades"], por_id[joao.id]["atividades"]) == (2, 10)


def test_excesso_vindo_de_correcao_entre_snapshots_no_meio_do_ano(
        cliente, db, escola_completa):
    """O caso que o teto foi feito para conter: uma correção entre dois
    snapshots. Fevereiro fecha em 40 atividades/100 estrelas; março soma 2
    atividades e 50 estrelas. O ganho de março (base = fevereiro) é 2/50 —
    contam 10, e a Sofia (8 atividades, 30 estrelas) passa à frente."""
    esc = escola_completa["escola"]
    ana, _, sofia = escola_completa["alunos"]
    _importar(cliente, esc.id, ana, "2026-02-01", "2026-03-01", 40, 100)
    _importar(cliente, esc.id, ana, "2026-03-01", "2026-04-01", 2, 50)
    _importar(cliente, esc.id, sofia, "2026-03-01", "2026-04-01", 8, 30)

    linhas = _ranking(cliente, esc.id, MARCO)

    assert [i["aluno_id"] for i in linhas] == [sofia.id, ana.id]
    ana_linha = next(i for i in linhas if i["aluno_id"] == ana.id)
    assert (ana_linha["atividades"], ana_linha["estrelas"],
            ana_linha["estrelas_brutas"]) == (2, 10, 50)


def test_sem_excesso_o_ranking_e_identico_ao_da_regra_antiga(cliente, db, escola_completa):
    """Ninguém acima de 5 estrelas por atividade (a Sofia está EXATAMENTE no
    limite: 8 atividades, 40 estrelas): o teto não corta nada, e ordem, posições
    e números saem iguais aos da ordenação antiga pelas estrelas brutas."""
    esc = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    _importar(cliente, esc.id, ana, "2026-03-01", "2026-04-01", 10, 45)
    _importar(cliente, esc.id, joao, "2026-03-01", "2026-04-01", 10, 40)
    _importar(cliente, esc.id, sofia, "2026-03-01", "2026-04-01", 8, 40)

    linhas = _ranking(cliente, esc.id, MARCO)

    assert all(i["estrelas"] == i["estrelas_brutas"] for i in linhas)
    assert not any(i["teto_estrelas_aplicado"] for i in linhas)
    # A ordenação ANTIGA, refeita aqui sobre as brutas: tem de dar o mesmo.
    antiga = sorted(linhas, key=lambda x: (-x["estrelas_brutas"], -x["atividades"],
                                           -x["pontuacao_media"], x["nome"].casefold(),
                                           x["aluno_id"]))
    assert [i["aluno_id"] for i in linhas] == [i["aluno_id"] for i in antiga]
    assert [(i["aluno_id"], i["estrelas"], i["atividades"]) for i in linhas] == [
        (ana.id, 45, 10), (joao.id, 40, 10), (sofia.id, 40, 8)]


def test_estrela_sem_atividade_nao_conta_e_tira_do_periodo(cliente, db, escola_completa):
    """Abril soma 30 estrelas e NENHUMA atividade ao acumulado da Ana (uma
    correção de relatório). Pelo teto, 0 atividade → 0 estrela que conta: sem
    atividade no período, ela sai do ranking de abril — como já fica fora da
    premiação de abril. O João, com atividade legítima, segue."""
    esc = escola_completa["escola"]
    ana, joao, _ = escola_completa["alunos"]
    _importar(cliente, esc.id, ana, "2026-03-01", "2026-04-01", 10, 40)
    _importar(cliente, esc.id, ana, "2026-04-01", "2026-05-01", 0, 30)
    _importar(cliente, esc.id, joao, "2026-04-01", "2026-05-01", 6, 20)

    linhas = _ranking(cliente, esc.id, ABRIL)

    assert [i["aluno_id"] for i in linhas] == [joao.id]
    assert ana.id not in {i["aluno_id"] for i in _podio_matematica(cliente, esc.id, ABRIL)}


def test_ranking_e_premiacao_contam_as_mesmas_estrelas(cliente, db, escola_completa):
    """Para os MESMOS dados, a linha do ranking e a linha do pódio da "Melhor
    Matemática" trazem as MESMAS estrelas e atividades — com e sem excesso, no
    período personalizado e em "todo o histórico". (A ORDEM das duas telas é
    diferente por definição: o ranking é volume, a premiação é média por
    atividade. O que tem de bater é o que cada uma CONTA.)"""
    esc = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    _importar(cliente, esc.id, ana, "2026-03-01", "2026-04-01", 2, 50)     # excesso
    _importar(cliente, esc.id, joao, "2026-03-01", "2026-04-01", 10, 40)   # normal
    _importar(cliente, esc.id, sofia, "2026-03-01", "2026-04-01", 8, 40)   # no limite

    for query in (MARCO, "?periodo=tudo"):
        ranking = {i["aluno_id"]: (i["estrelas"], i["atividades"])
                   for i in _ranking(cliente, esc.id, query)}
        podio = {i["aluno_id"]: (i["estrelas"], i["atividades"])
                 for i in _podio_matematica(cliente, esc.id, query)}
        assert set(ranking) == set(podio) == {ana.id, joao.id, sofia.id}, query
        assert ranking == podio, (
            f"[{query}] o ranking e a premiação contaram estrelas diferentes "
            f"para os mesmos dados: ranking={ranking} premiação={podio}")
        assert ranking[ana.id] == (10, 2), query
