"""Análise por PERÍODO: gravação de data+hora nas leituras, histórico filtrado
por intervalo/dia e ranking de leitura por período (base das premiações)."""
from datetime import date, datetime

from sqlalchemy import select

from app.models import Leitura
from app.services import periodos
from app.services.premiacoes import _podio


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
    # "semana": segunda-feira até hoje (2026-07-17 é sexta → semana começa 13).
    i, f, rot = periodos.resolver("semana", h, 2026)
    assert i.date() == date(2026, 7, 13) and f.date() == date(2026, 7, 17)
    assert rot == "Esta semana"
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


# --- Evolução de leitura por semana/mês/bimestre ----------------------------

def test_evolucao_leitura_por_mes_e_bimestre(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    _importar_leitura(cliente, escola_id, ana, "M1", "AA", "2026-07-05T09:00:00", 10)
    _importar_leitura(cliente, escola_id, ana, "M2", "D", "2026-07-20T09:00:00", 20)
    _importar_leitura(cliente, escola_id, ana, "M3", "AA", "2026-08-02T09:00:00", 5)
    base = f"{_base(escola_id)}/alunos/{ana.id}/evolucao-leitura"

    por_mes = cliente.get(base + "?granularidade=mes").json()
    assert por_mes["granularidade"] == "mes"
    assert len(por_mes["series"]) == 2  # julho e agosto
    jul, ago = por_mes["series"]
    assert jul["rotulo"] == "jul/2026"
    assert jul["livros"] == 2
    assert jul["pontos"] == 5.0          # AA(1) + D(4)
    assert jul["tempo_min"] == 30
    assert jul["nivel_medio"] == 2.5     # 5 pontos / 2 livros
    assert ago["rotulo"] == "ago/2026" and ago["livros"] == 1

    # julho e agosto caem no mesmo 4º bimestre → um único balde de 3 livros
    por_bim = cliente.get(base + "?granularidade=bimestre").json()
    assert len(por_bim["series"]) == 1
    assert por_bim["series"][0]["livros"] == 3
    assert "bim" in por_bim["series"][0]["rotulo"]


# --- Premiações por período -------------------------------------------------

def test_premiacoes_usam_so_o_periodo(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    ana, joao, sofia = escola_completa["alunos"]
    _importar_leitura(cliente, escola_id, ana, "A1", "AA", "2026-07-05T09:00:00", 10)
    _importar_leitura(cliente, escola_id, ana, "A2", "D", "2026-07-06T09:00:00", 20)
    _importar_leitura(cliente, escola_id, joao, "J1", "D", "2026-07-07T09:00:00", 40)
    _importar_leitura(cliente, escola_id, sofia, "S1", "D", "2026-08-01T09:00:00", 99)  # fora

    r = cliente.get(f"{_base(escola_id)}/premiacoes"
                    "?periodo=personalizado&inicio=2026-07-01&fim=2026-07-31").json()
    cats = {c["chave"]: c["podio"] for c in r["categorias"]}

    # Melhor leitor (pontos): Ana AA(1)+D(4)=5 > João D(4)=4; Sofia (agosto) fora.
    ml = cats["melhor_leitor"]
    assert ml[0]["nome"] == ana.nome and ml[0]["valor"] == 5.0 and ml[0]["posicao"] == 1
    assert ml[1]["nome"] == joao.nome and ml[1]["valor"] == 4.0
    assert all(p["nome"] != sofia.nome for p in ml)  # dados de agosto não contam

    assert cats["mais_livros"][0]["nome"] == ana.nome and cats["mais_livros"][0]["valor"] == 2
    assert cats["mais_tempo"][0]["nome"] == joao.nome and cats["mais_tempo"][0]["valor"] == 40


def _importar_matific(cliente, escola_id, aluno, atividades, data_ref):
    r = cliente.post(f"{_base(escola_id)}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "texto",
        "data_referencia": data_ref,
        "linhas": [{"nome": aluno.nome,
                    "dados": {"atividades": atividades, "pontuacao_media": 3.0, "estrelas": 10},
                    "aluno_id": aluno.id}]})
    assert r.status_code == 200, r.text


def test_destaque_matific_conta_so_o_ganho_no_periodo(cliente, escola_completa):
    """O acumulado histórico do Matific não pode ser atribuído ao período: só o
    GANHO dentro do intervalo pontua (achado da auditoria adversarial)."""
    escola_id = escola_completa["escola"].id
    ana, joao, sofia = escola_completa["alunos"]
    # Ana: 100 antes de julho, 130 em julho → ganho real = 30.
    _importar_matific(cliente, escola_id, ana, 100, "2026-06-20T00:00:00")
    _importar_matific(cliente, escola_id, ana, 130, "2026-07-25T00:00:00")
    # João: único snapshot EM CIMA do início (2026-07-01 00:00) com 200 acumuladas
    # de antes → ganho no período deve ser 0 (fronteira vira base).
    _importar_matific(cliente, escola_id, joao, 200, "2026-07-01T00:00:00")
    # Sofia: único snapshot no meio de julho com 350 acumuladas (sem baseline) → 0.
    _importar_matific(cliente, escola_id, sofia, 350, "2026-07-15T00:00:00")

    r = cliente.get(f"{_base(escola_id)}/premiacoes"
                    "?periodo=personalizado&inicio=2026-07-01&fim=2026-07-31").json()
    dm = {c["chave"]: c["podio"] for c in r["categorias"]}["destaque_matific"]
    # Só Ana pontua (ganho 30); João e Sofia com 0 ficam fora do pódio.
    assert len(dm) == 1
    assert dm[0]["nome"] == ana.nome and dm[0]["valor"] == 30.0


def test_ranking_evolucao_respeita_o_periodo(cliente, escola_completa):
    """O ranking de evolução mede o ganho DENTRO do intervalo: um snapshot
    depois do fim não infla o ganho (fix do 'atual = serie[-1]')."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    _importar_matific(cliente, escola_id, ana, 100, "2026-06-20T00:00:00")  # base
    _importar_matific(cliente, escola_id, ana, 130, "2026-07-25T00:00:00")  # dentro
    _importar_matific(cliente, escola_id, ana, 160, "2026-08-10T00:00:00")  # depois do fim

    r = cliente.get(f"{_base(escola_id)}/ranking-evolucao"
                    "?periodo=personalizado&inicio=2026-07-01&fim=2026-07-31").json()
    ana_item = next(i for i in r if i["aluno_id"] == ana.id)
    assert ana_item["ganhos"]["atividades"] == 30  # 130−100; agosto (160) fora não conta


def test_ranking_evolucao_usa_datas_reais_das_leituras(cliente, escola_completa):
    """CRUCIAL: importar HOJE um relatório que cobre meses NÃO atribui tudo a
    hoje. Para quem tem leituras individuais, o ganho do período conta apenas
    os livros cuja DATA REAL cai no intervalo (o delta de snapshot diria 3)."""
    escola_id = escola_completa["escola"].id
    ana, joao, _ = escola_completa["alunos"]
    # Importadas AGORA (snapshot de hoje), mas com datas reais espalhadas:
    _importar_leitura(cliente, escola_id, ana, "R1", "D", "2026-07-05T09:00:00", 30)
    _importar_leitura(cliente, escola_id, ana, "R2", "D", "2026-07-06T09:00:00", 20)
    _importar_leitura(cliente, escola_id, ana, "R3", "D", "2026-06-01T09:00:00", 40)  # fora

    r = cliente.get(f"{_base(escola_id)}/ranking-evolucao"
                    "?periodo=personalizado&inicio=2026-07-04&fim=2026-07-07").json()
    ana_item = next(i for i in r if i["aluno_id"] == ana.id)
    assert ana_item["ganhos"]["livros"] == 2                # só as do intervalo
    assert ana_item["ganhos"]["tempo_leitura_min"] == 50    # 30 + 20 (não 90)

    # Aluno SEM leituras individuais (só relatório-resumo da turma): o ganho vem
    # do DELTA entre snapshots. Com baseline ANTES da janela, mede-se o
    # crescimento REAL do período — não o acumulado (regra justa; um snapshot
    # único sem baseline daria 0). Ver test_ranking_justo.py.
    for data_ref, livros in (("2026-07-01T12:00:00", 2),   # baseline (antes)
                             ("2026-07-05T12:00:00", 5)):  # dentro da janela
        resp = cliente.post(f"{_base(escola_id)}/importacoes/confirmar", json={
            "plataforma": "elefante", "formato": "resumo", "tipo": "texto",
            "data_referencia": data_ref,
            "linhas": [{"nome": joao.nome,
                        "dados": {"livros_unicos": livros, "tempo_leitura_min": 100,
                                  "questoes_tentativas": 10, "questoes_acertos": 8},
                        "aluno_id": joao.id}]})
        assert resp.status_code == 200
    r2 = cliente.get(f"{_base(escola_id)}/ranking-evolucao"
                     "?periodo=personalizado&inicio=2026-07-04&fim=2026-07-07").json()
    joao_item = next(i for i in r2 if i["aluno_id"] == joao.id)
    assert joao_item["ganhos"]["livros"] == 3               # 5 − 2 (delta com baseline)


def test_podio_desempata_por_nome_normalizado():
    """Empate no valor → ordem alfabética ignorando caixa (senão minúsculas
    caem para fora do top-5 e premiam o aluno errado)."""
    alunos = {i: {"nome": nome, "turma": "A"} for i, nome in
              enumerate(["Ana", "ary", "Bia", "bic", "Caio", "Duda"], start=1)}
    valores = {i: 4.0 for i in alunos}  # todos empatados
    podio = _podio(valores, alunos, limite=5)
    assert [p["nome"] for p in podio] == ["Ana", "ary", "Bia", "bic", "Caio"]
