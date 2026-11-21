"""Perfil do Aluno: as abas "Evolução" e "Linha do tempo" respeitam o período
escolhido no seletor (auditoria PERIODOS-8).

A web manda o período no MESMO contrato de ``/alunos/{id}/leituras``
(``periodoParaQuery``): ``?periodo=<preset>``, ``?periodo=personalizado&inicio=&fim=``
ou ``?dia=``. As rotas ``/evolucao-leitura`` e ``/linha-do-tempo`` só declaravam
``inicio``/``fim``: o FastAPI descartava ``periodo`` em silêncio e a resposta era o
histórico TODO — "3º bimestre" no seletor mostrava a leitura de março.

Dados fictícios.
"""
from datetime import datetime

import pytest

from app.models import EventoAluno, Leitura, Livro


@pytest.fixture()
def cenario(db, escola_completa):
    escola, aluno = escola_completa["escola"], escola_completa["alunos"][0]
    for titulo, quando in (("Livro de Março", datetime(2026, 3, 10, 10)),
                           ("Livro de Setembro", datetime(2026, 9, 10, 10))):
        livro = Livro(escola_id=escola.id, titulo=titulo, nivel_codigo="D")
        db.add(livro)
        db.flush()
        db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id,
                       data=quando, tempo_leitura_min=10))
        db.add(EventoAluno(escola_id=escola.id, aluno_id=aluno.id, plataforma="elefante",
                           tipo_evento="leitura", ocorrido_em=quando,
                           chave_natural=f"aud-per-{titulo}", conteudo_titulo=titulo))
    db.commit()
    return f"/api/v1/escolas/{escola.id}/alunos/{aluno.id}"


def _meses(cliente, base, query):
    r = cliente.get(f"{base}/evolucao-leitura?granularidade=mes&{query}")
    assert r.status_code == 200, r.text
    return [s["rotulo"] for s in r.json()["series"]]


def _titulos(cliente, base, query):
    r = cliente.get(f"{base}/linha-do-tempo?limite=50&{query}")
    assert r.status_code == 200, r.text
    return sorted(i["conteudo_titulo"] for i in r.json()["itens"])


@pytest.mark.parametrize("query, meses", [
    ("periodo=bimestre_3", ["set/2026"]),                 # 24/07–04/10/2026
    ("periodo=bimestre_1", ["mar/2026"]),                 # 02/02–22/04/2026
    ("periodo=tudo", ["mar/2026", "set/2026"]),
    ("", ["mar/2026", "set/2026"]),                       # sem período = histórico todo
    ("periodo=personalizado&inicio=2026-09-01&fim=2026-09-30", ["set/2026"]),
    ("inicio=2026-03-01&fim=2026-03-31", ["mar/2026"]),   # contrato antigo continua valendo
    ("dia=2026-03-10", ["mar/2026"]),
])
def test_evolucao_leitura_respeita_o_periodo_do_seletor(cliente, cenario, query, meses):
    assert _meses(cliente, cenario, query) == meses


@pytest.mark.parametrize("query, titulos", [
    ("periodo=bimestre_3", ["Livro de Setembro"]),
    ("periodo=bimestre_1", ["Livro de Março"]),
    ("periodo=tudo", ["Livro de Março", "Livro de Setembro"]),
    ("", ["Livro de Março", "Livro de Setembro"]),
    ("periodo=personalizado&inicio=2026-09-01&fim=2026-09-30", ["Livro de Setembro"]),
    ("inicio=2026-03-01&fim=2026-03-31", ["Livro de Março"]),
    ("dia=2026-09-10", ["Livro de Setembro"]),
])
def test_linha_do_tempo_respeita_o_periodo_do_seletor(cliente, cenario, query, titulos):
    assert _titulos(cliente, cenario, query) == titulos


@pytest.mark.parametrize("rota", ["evolucao-leitura?granularidade=mes&", "linha-do-tempo?"])
def test_data_invalida_continua_400(cliente, cenario, rota):
    r = cliente.get(f"{cenario}/{rota}periodo=personalizado&inicio=2026-13-40")
    assert r.status_code == 400, r.text
    r = cliente.get(f"{cenario}/{rota}dia=ontem")
    assert r.status_code == 400, r.text
