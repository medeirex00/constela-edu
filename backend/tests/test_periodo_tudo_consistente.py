"""P4 — "Todo o histórico" (ranking de leitura, premiação, histórico itemizado) usa a
MESMA reconciliação da nota anual: aluno só-snapshot pontua, aluno com snapshot e
leituras não conta o mesmo livro duas vezes; a soma do histórico é exata (P7)."""
import pytest

from app.services import dificuldade_livro as dl
from app.services import premiacoes, scoring


def _base(escola_id):
    return f"/api/v1/escolas/{escola_id}"


def _leituras(cliente, escola_id, aluno, titulos, nivel="D"):
    r = cliente.post(f"{_base(escola_id)}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "leituras", "tipo": "texto",
        "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id,
                    "dados": {"livro": t, "nivel": nivel, "data": f"2026-03-0{i + 1}T09:00:00",
                              "tempo_livro_min": 10}}
                   for i, t in enumerate(titulos)]})
    assert r.status_code == 200, r.text


def _resumo(cliente, escola_id, aluno, por_faixa, livros=None):
    dados = {"livros_por_nivel": por_faixa}
    if livros is not None:
        dados["livros_unicos"] = livros
    r = cliente.post(f"{_base(escola_id)}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "resumo", "tipo": "texto",
        "data_referencia": "2026-04-01T12:00:00",
        "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id, "dados": dados}]})
    assert r.status_code == 200, r.text


def test_tudo_bate_com_a_nota_anual_para_snapshot_leituras_e_ambos(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    _resumo(cliente, escola.id, ana, {"nivel_2": 3})                       # só snapshot
    _leituras(cliente, escola.id, joao, ["Livro J1", "Livro J2"])          # só leituras
    _leituras(cliente, escola.id, sofia, ["Livro S1"])                     # ambos (1 item)
    _resumo(cliente, escola.id, sofia, {"nivel_2": 1})                     # cobre o mesmo livro

    anual = scoring._carregar_contexto(db, escola.id)[5]
    regra = dl.regra_da_escola(db, escola.id)
    assert anual[ana.id] == pytest.approx(regra.pontos_aluno({"nivel_2": 3}, "3º Ano"), abs=0.01)
    assert anual[ana.id] > 0
    valor_d = regra.valor_livro("D", "Livro S1", "3º Ano")
    assert anual[sofia.id] == pytest.approx(valor_d, abs=0.01)             # sem dobrar
    assert anual[joao.id] == pytest.approx(2 * regra.valor_livro("D", "Livro J1", "3º Ano"), abs=0.01)

    rk = {i["aluno_id"]: i for i in cliente.get(
        f"{_base(escola.id)}/ranking/leitura?periodo=tudo").json()}
    _, prem, _ = premiacoes._leitura_no_periodo(
        db, escola.id, premiacoes._alunos_ativos(db, escola.id, 2026, None), None, None)
    for a in (ana, joao, sofia):
        assert rk[a.id]["pontos"] == pytest.approx(anual[a.id], abs=0.01), a.nome
        assert prem[a.id] == pytest.approx(anual[a.id], abs=0.01), a.nome
    assert rk[ana.id]["livros"] == 3 and rk[sofia.id]["livros"] == 1 and rk[joao.id]["livros"] == 2

    # Histórico itemizado (P7: soma sem arredondar por item) = anual quando o
    # aluno só tem leituras.
    hist = cliente.get(f"{_base(escola.id)}/alunos/{joao.id}/leituras?periodo=tudo").json()
    assert hist["resumo"]["pontos"] == pytest.approx(anual[joao.id], abs=0.01)
    assert hist["resumo"]["pontos"] == round(sum(
        regra.valor_livro("D", t, "3º Ano") for t in ("Livro J1", "Livro J2")), 2)
