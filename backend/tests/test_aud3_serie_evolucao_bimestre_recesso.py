"""REG_NUMEROS-5 — Perfil do Aluno › Evolução "por bimestre": a leitura feita no RECESSO
não entra no balde de um bimestre cuja janela oficial não a conta.

``evolucao._bucket_leitura`` classificava cada leitura JÁ FEITA pela SUGESTÃO do que a
tela abre marcado (``bimestres.bimestre_sugerido``), que no recesso devolve o próximo
bimestre (e janeiro, o 1º). O Ranking de Leitura, as Premiações, o Relatório por Período
e o certificado usam as janelas oficiais (``bimestres.intervalo``), que não incluem o
recesso: o Perfil dizia 2 livros no "1º bim 2026" e o Ranking do 1º bimestre, 1.

Agora a leitura é classificada pela DATA (``bimestre_da_data``); fora dos quatro
bimestres ela vai para um balde "Recesso <mês>/<ano>" (o mês em que o recesso começa),
na ordem do tempo. Ano sem calendário cadastrado continua no mapa por mês.

Dados e calendário de 2027 fictícios.
"""
import json
from datetime import date, datetime

import pytest

from app.models import Leitura, Livro
from app.services import bimestres, periodos
from app.services import evolucao as svc_evolucao

API = "/api/v1"

CAL_2027 = {"2027": [["2027-02-01", "2027-04-23"], ["2027-04-26", "2027-07-09"],
                     ["2027-07-26", "2027-10-01"], ["2027-10-04", "2027-12-17"]]}


@pytest.fixture()
def calendario_2027(monkeypatch):
    monkeypatch.setenv(bimestres.VARIAVEL_CALENDARIO, json.dumps(CAL_2027))
    assert bimestres.ano_com_calendario(2027)


def _ler(db, esc, aluno, quando, titulo):
    livro = Livro(escola_id=esc.id, titulo=titulo, nivel_codigo="D")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=esc.id, aluno_id=aluno.id, livro_id=livro.id, data=quando,
                   tempo_leitura_min=10))


def test_janeiro_nao_entra_no_1o_bimestre_do_perfil(cliente, db, escola_completa):
    esc = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _ler(db, esc, ana, datetime(2026, 1, 20, 10, 0), "Livro Fictício do Recesso")
    _ler(db, esc, ana, datetime(2026, 2, 10, 10, 0), "Livro Fictício de Fevereiro")
    db.commit()
    base = f"{API}/escolas/{esc.id}"
    perfil = cliente.get(f"{base}/alunos/{ana.id}/evolucao-leitura",
                         params={"granularidade": "bimestre"})
    assert perfil.status_code == 200, perfil.text
    series = [(b["rotulo"], b["livros"]) for b in perfil.json()["series"]]
    assert series == [("Recesso jan/2026", 1), ("1º bim 2026", 1)], series
    # O 1º bimestre do Perfil bate com o do Ranking de Leitura e o das Premiações.
    ranking = cliente.get(f"{base}/ranking/leitura", params={"periodo": "bimestre_1"}).json()
    premio = cliente.get(f"{base}/premiacoes", params={"periodo": "bimestre_1"}).json()
    mais_livros = next(c for c in premio["categorias"] if c["chave"] == "mais_livros")
    assert ranking[0]["livros"] == 1
    assert mais_livros["podio"][0]["valor"] == 1


@pytest.mark.parametrize("dia,rotulo", [
    (datetime(2027, 1, 20, 10, 0), "Recesso jan/2027"),    # antes do 1º
    (datetime(2027, 4, 24, 10, 0), "Recesso abr/2027"),    # entre o 1º e o 2º
    (datetime(2027, 7, 15, 10, 0), "Recesso jul/2027"),    # entre o 2º e o 3º
    (datetime(2027, 10, 2, 10, 0), "Recesso out/2027"),    # entre o 3º e o 4º
    (datetime(2027, 12, 20, 10, 0), "Recesso dez/2027"),   # depois do 4º
])
def test_leitura_do_recesso_vai_para_o_balde_do_recesso(calendario_2027, dia, rotulo):
    assert bimestres.bimestre_da_data(dia.date()) is None
    _, obtido = svc_evolucao._bucket_leitura(dia, "bimestre")
    assert obtido == rotulo


@pytest.mark.parametrize("dia", [datetime(2027, 2, 1, 8), datetime(2027, 4, 23, 23),
                                 datetime(2027, 7, 26, 8), datetime(2027, 12, 17, 23)])
def test_leitura_dentro_do_bimestre_cai_na_janela_oficial(calendario_2027, dia):
    chave, rotulo = svc_evolucao._bucket_leitura(dia, "bimestre")
    numero = chave[1]
    assert rotulo == f"{numero}º bim 2027"
    ini, fim, _ = periodos.resolver(f"bimestre_{numero}", dia.date(), 2027)
    assert ini <= dia <= fim


def test_baldes_em_ordem_do_tempo(calendario_2027):
    dias = [datetime(2027, 12, 20), datetime(2027, 1, 5), datetime(2027, 7, 15),
            datetime(2027, 3, 1), datetime(2027, 8, 1), datetime(2027, 4, 24),
            datetime(2027, 5, 2), datetime(2027, 10, 2), datetime(2027, 11, 3)]
    baldes = {}
    for dia in dias:
        chave, rotulo = svc_evolucao._bucket_leitura(dia, "bimestre")
        baldes[chave] = rotulo
    assert [baldes[c] for c in sorted(baldes)] == [
        "Recesso jan/2027", "1º bim 2027", "Recesso abr/2027", "2º bim 2027",
        "Recesso jul/2027", "3º bim 2027", "Recesso out/2027", "4º bim 2027",
        "Recesso dez/2027"]


def test_ano_sem_calendario_continua_no_mapa_por_mes(monkeypatch):
    monkeypatch.delenv(bimestres.VARIAVEL_CALENDARIO, raising=False)
    assert not bimestres.ano_com_calendario(2031)
    _, rotulo = svc_evolucao._bucket_leitura(datetime(2031, 1, 20, 10), "bimestre")
    assert rotulo == f"{bimestres.bimestre_sugerido(date(2031, 1, 20))}º bim 2031"
