"""Análise por PERÍODO: gravação de data+hora nas leituras, histórico filtrado
por intervalo/dia e ranking de leitura por período (base das premiações)."""
from datetime import date, datetime

from sqlalchemy import select

from app.models import Leitura
from app.services import periodos


def _base(escola_id: int) -> str:
    return f"/api/v1/escolas/{escola_id}"


def _importar_leitura(cliente, escola_id, aluno, livro, nivel, data_iso, tempo=None):
    dados = {"livro": livro, "nivel": nivel, "data": data_iso}
    if tempo is not None:
        dados["tempo_livro_min"] = tempo
    r = cliente.post(f"{_base(escola_id)}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "leituras", "tipo": "texto",
        "linhas": [{"nome": aluno.nome, "dados": dados, "aluno_id": aluno.id}]})
    assert r.status_code == 200, r.text


# --- Resolvedor de períodos (unitário) --------------------------------------

def test_resolver_presets():
    h = date(2026, 7, 17)
    i, f, _ = periodos.resolver("bimestre", h, 2026)
    assert i.date() == date(2026, 7, 1) and f.date() == date(2026, 8, 31)
    i, f, _ = periodos.resolver("bimestre_anterior", h, 2026)
    assert i.date() == date(2026, 5, 1) and f.date() == date(2026, 6, 30)
    i, f, _ = periodos.resolver("mes", h, 2026)
    assert i.date() == date(2026, 7, 1) and f.date() == date(2026, 7, 31)
    i, f, _ = periodos.resolver("tudo", h, 2026)
    assert i is None and f is None
    # bimestre anterior em janeiro rola para nov/dez do ano anterior
    i, f, _ = periodos.resolver("bimestre_anterior", date(2026, 1, 10), 2026)
    assert i.date() == date(2025, 11, 1) and f.date() == date(2025, 12, 31)


# --- Gravação de data + HORÁRIO + tempo -------------------------------------

def test_import_grava_data_hora_e_tempo(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    _importar_leitura(cliente, escola_id, ana, "O Gato e a Lua", "AA",
                      "2026-07-12T14:30:15", tempo=8)
    leitura = db.execute(select(Leitura).where(Leitura.aluno_id == ana.id)).scalars().one()
    assert leitura.data == datetime(2026, 7, 12, 14, 30, 15)  # data + horário reais
    assert leitura.tempo_leitura_min == 8


# --- Histórico de leituras por período / dia --------------------------------

def test_historico_por_periodo_e_dia(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    _importar_leitura(cliente, escola_id, ana, "Livro A", "AA", "2026-07-01T09:00:00", 5)
    _importar_leitura(cliente, escola_id, ana, "Livro B", "D", "2026-07-12T10:00:00", 20)
    _importar_leitura(cliente, escola_id, ana, "Livro C", "AA", "2026-08-05T08:00:00", 3)
    base = f"{_base(escola_id)}/alunos/{ana.id}/leituras"

    tudo = cliente.get(base).json()
    assert tudo["resumo"]["total_livros"] == 3
    datas = [i["data"] for i in tudo["itens"]]
    assert datas == sorted(datas, reverse=True)  # cronológico (mais recente 1º)

    julho = cliente.get(base + "?periodo=personalizado&inicio=2026-07-01&fim=2026-07-31").json()
    assert julho["resumo"]["total_livros"] == 2
    assert {i["livro"] for i in julho["itens"]} == {"Livro A", "Livro B"}
    # AA=1 + D=4 = 5 pontos no período
    assert julho["resumo"]["pontos"] == 5.0
    assert julho["resumo"]["tempo_total_min"] == 25

    dia = cliente.get(base + "?dia=2026-07-12").json()
    assert dia["resumo"]["total_livros"] == 1
    item = dia["itens"][0]
    assert item["livro"] == "Livro B" and item["nivel"] == "D"
    assert item["tempo_leitura_min"] == 20
    assert item["plataforma"] == "elefante"
    assert "T10:00" in item["data"]  # horário preservado


def test_historico_data_invalida_da_400(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    r = cliente.get(f"{_base(escola_id)}/alunos/{ana.id}/leituras?dia=17/07/2026")
    assert r.status_code == 400


# --- Ranking de leitura por período -----------------------------------------

def test_ranking_leitura_respeita_periodo(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    ana, joao = escola_completa["alunos"][0], escola_completa["alunos"][1]
    _importar_leitura(cliente, escola_id, ana, "A1", "AA", "2026-07-05T09:00:00", 10)
    _importar_leitura(cliente, escola_id, ana, "A2", "D", "2026-07-06T09:00:00", 20)
    _importar_leitura(cliente, escola_id, joao, "J1", "AA", "2026-07-05T09:00:00", 5)
    _importar_leitura(cliente, escola_id, joao, "J2", "AA", "2026-08-10T09:00:00", 5)  # fora

    r = cliente.get(f"{_base(escola_id)}/ranking/leitura"
                    "?periodo=personalizado&inicio=2026-07-01&fim=2026-07-31").json()
    assert r[0]["nome"] == ana.nome         # mais pontos no período
    assert r[0]["posicao"] == 1
    assert r[0]["livros"] == 2
    assert r[0]["pontos"] == 5.0            # AA(1) + D(4)
    assert r[0]["tempo_leitura_min"] == 30
    joao_row = next(x for x in r if x["nome"] == joao.nome)
    assert joao_row["livros"] == 1          # a leitura de agosto não conta em julho
