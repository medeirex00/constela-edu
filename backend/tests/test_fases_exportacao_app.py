"""AS FASES NÃO CONCORREM também na EXPORTAÇÃO do Ranking Geral, no CARTAZ
geral e no pacote do APP (evolução e mural).

`services.relatorios.linhas_ranking` (CSV/XLSX/PDF e o cartaz geral) só cortava
o status; a Nota congelada da criança da Fase (que o recálculo não apaga) saía
no arquivo com a posição antiga. O pacote do app (`/sincronizacao`) montava a
evolução e o mural sem o recorte que o telão e a web já fazem.
"""
import csv
import io

from tests.test_ranking_fases_cobertura import cenario  # noqa: F401 (fixture)

API = "/api/v1"


def test_exportacao_do_ranking_geral_sem_a_fase(cliente, cenario):  # noqa: F811
    escola_id = cenario["escola"].id
    r = cliente.get(f"{API}/escolas/{escola_id}/relatorios/ranking", params={"formato": "csv"})
    assert r.status_code == 200, r.text
    texto = r.content.decode("utf-8-sig")
    assert "Fase Teste" not in texto
    linhas = list(csv.reader(io.StringIO(texto), delimiter=";" if ";" in texto else ","))
    assert len(linhas) - 1 == 3        # os 3 do 4º Ano; os 3 do fixture-base não têm retrato nenhum (DEC-19)


def test_cartaz_geral_gera_sem_a_fase(cliente, cenario):  # noqa: F811
    """As LINHAS do cartaz geral saem de `linhas_ranking` (o corte acima). Os
    cartões de estatística (cobertura da escola) ficam como estão — travados em
    `test_cartaz_materia.test_cartoes_do_ranking_geral_nao_mudam`."""
    escola_id = cenario["escola"].id
    r = cliente.get(f"{API}/escolas/{escola_id}/ranking/cartaz")
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"%PDF"


def test_pacote_do_app_sem_a_fase_na_evolucao(cliente, cenario):  # noqa: F811
    escola_id = cenario["escola"].id
    pacote = cliente.get(f"{API}/escolas/{escola_id}/sincronizacao")
    assert pacote.status_code == 200, pacote.text
    ids = {i["aluno_id"] for i in pacote.json()["evolucao"]}
    assert ids and not ids & cenario["fases"]
    assert [i["posicao"] for i in pacote.json()["evolucao"]] == list(range(1, len(ids) + 1))
    assert not {i["aluno_id"] for i in pacote.json()["ranking"]} & cenario["fases"]
