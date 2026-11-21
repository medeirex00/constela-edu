"""S_G_VIRADA-2/evolucao (costura da fase D) — a "Melhor Evolução" de um período de ano
letivo ENCERRADO, consultada depois da virada, usa as crianças e as turmas daquele ano.

Os pódios das Premiações, o Ranking de Leitura e o Relatório por Período já tiram a
população do período (``periodos.populacao_do_periodo``, 26e4becf). A "Melhor Evolução",
logo abaixo dos pódios na mesma tela e com o mesmo período, vinha de
``evolucao.ranking_evolucao`` com as matrículas do ano ATIVO e o contador do Matific do
ano ativo: depois da virada, a formanda que mais cresceu sumia, as demais apareciam na
turma de 2027, e a Matemática de out–dez/2026 ficava vazia (o contador de 2026 é de
"outro ano").

Agora a rota resolve a população como as premiações: período inteiro num ano encerrado →
as crianças daquele ano, com a turma e a série dele, e o contador do Matific daquele ano;
o recorte de turma (o filtro da tela e as turmas do professor) continua escolhendo QUEM
aparece pelas turmas de agora. Cada linha diz de que ano é (``ano_letivo``,
``populacao``), como as do Ranking de Leitura.

O cenário (ANA, BETO e a formanda DORA) é o de ``test_aud3_periodo_ano_fechado``. Datas
fixas; mundo fictício.
"""
from tests.test_aud3_periodo_ano_fechado import (  # noqa: F401 — fixtures
    ANA, ANO_FECHADO, BETO, DORA, PERIODO, _get, cliente_professor, virada)

ROTA = "ranking-evolucao"


def _lista(resp, dimensao):
    return [(i["nome"], i["turma"]) for i in resp
            if i["dimensoes"][dimensao]["aferido"] and (i["nota"] or 0) > 0]


def test_melhor_evolucao_do_ano_fechado_nao_muda_com_a_virada(cliente_global, virada):
    antes = {d: _get(cliente_global, virada, ROTA, {**PERIODO, "dimensao": d})
             for d in ("leitura", "matematica")}
    virada["virar"]()
    depois = {d: _get(cliente_global, virada, ROTA, {**PERIODO, "dimensao": d})
              for d in ("leitura", "matematica")}

    # Antes do conserto, depois da virada: leitura [ANA e BETO no "5º Ano A" de 2027],
    # sem DORA; matemática vazia (o contador de 2026 era "de outro ano").
    assert _lista(depois["leitura"], "leitura") == [
        (DORA, "5º Ano A"), (ANA, "4º Ano A"), (BETO, "4º Ano A")]
    assert [n for n, _t in _lista(depois["matematica"], "matematica")] == [DORA, ANA, BETO]
    for d in ("leitura", "matematica"):
        assert ([(i["aluno_id"], i["nota"], i["turma"]) for i in depois[d]]
                == [(i["aluno_id"], i["nota"], i["turma"]) for i in antes[d]]), d
        assert {(i["ano_letivo"], i["populacao"]) for i in depois[d]} == {
            (ANO_FECHADO, "ano_do_periodo")}
        assert {(i["ano_letivo"], i["populacao"]) for i in antes[d]} == {
            (ANO_FECHADO, "ano_ativo")}


def test_recorte_de_turma_no_ano_fechado_escolhe_as_criancas_de_agora(
        cliente_global, cliente_professor, virada):
    """O filtro da tela e as turmas do professor são as de 2027 (o 5º Ano A de ANA e
    BETO): escolhem quem aparece, e cada criança sai com a turma de 2026."""
    virada["virar"]()
    turma_nova = {"turma_id": virada["t5_novo"].id}
    esperado = [(ANA, "4º Ano A"), (BETO, "4º Ano A")]
    gestao = _get(cliente_global, virada, ROTA, {**PERIODO, **turma_nova, "dimensao": "leitura"})
    assert _lista(gestao, "leitura") == esperado
    prof = _get(cliente_professor, virada, ROTA, {**PERIODO, "dimensao": "leitura"})
    assert _lista(prof, "leitura") == esperado
    # A régua continua a da escola inteira daquele ano: a nota de ANA é a mesma.
    todos = _get(cliente_global, virada, ROTA, {**PERIODO, "dimensao": "leitura"})
    nota = {i["nome"]: i["nota"] for i in todos}
    assert {i["nome"]: i["nota"] for i in prof} == {ANA: nota[ANA], BETO: nota[BETO]}


def test_ultimos_dias_e_periodo_do_ano_ativo_seguem_com_as_criancas_de_agora(
        cliente_global, virada):
    """Controle: sem período de ano encerrado (os últimos N dias, o padrão), a lista é a
    de sempre — as crianças do ano ativo, com a origem declarada."""
    virada["virar"]()
    resp = _get(cliente_global, virada, ROTA, {"dimensao": "leitura", "dias": 30})
    assert {i["nome"] for i in resp} <= {ANA, BETO}
    assert {(i["ano_letivo"], i["populacao"]) for i in resp} <= {(2027, "ano_ativo")}
