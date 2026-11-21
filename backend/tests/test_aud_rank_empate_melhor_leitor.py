"""O pódio "Melhor Leitor" das Premiações desempata como o Ranking de Leitura.

`/ranking/leitura` ordena por pontos → livros → tempo → nome → id. O "Melhor
Leitor" de `premiacoes._categorias` chamava `_categoria` sem `desempate`, ou
seja, pontos → nome → id: com pontos iguais (mesmos livros, mesmo nível, mesma
série — o caso típico de "Hoje"/"Semana") o vencedor mudava de tela no MESMO
período, e o "Gerar certificados" de cada tela premiava uma criança diferente.
Achado RANKINGS-3. Dados fictícios.
"""
from datetime import datetime

import pytest

from app.models import Leitura, Livro

API = "/api/v1"
Q = "periodo=personalizado&inicio=2026-09-01&fim=2026-09-30"


def _cenario(db, escola_completa, turno=None):
    esc = escola_completa["escola"]
    if turno is not None:
        escola_completa["turma"].turno = turno
    ana, joao, _sofia = escola_completa["alunos"]   # "Ana Beatriz…" < "João Pedro…"
    livros = []
    for titulo in ("Livro Empate Um", "Livro Empate Dois"):
        lv = Livro(escola_id=esc.id, titulo=titulo, nivel_codigo="D")
        db.add(lv)
        db.flush()
        livros.append(lv)
    # Mesmos 2 livros, mesmo nível, mesmo mês: pontos e livros IGUAIS. O tempo é
    # que desempata: Ana 10 min no total, João 40 min.
    for aluno, minutos in ((ana, 5), (joao, 20)):
        for dia, lv in zip((10, 11), livros):
            db.add(Leitura(escola_id=esc.id, aluno_id=aluno.id, livro_id=lv.id,
                           data=datetime(2026, 9, dia, 10, 0), tempo_leitura_min=minutos))
    db.commit()
    return esc, ana, joao


def _posicoes_do_ranking(cliente, esc, extra=""):
    r = cliente.get(f"{API}/escolas/{esc.id}/ranking/leitura?{Q}{extra}")
    assert r.status_code == 200, r.text
    return [(i["aluno_id"], i["posicao"], i["pontos"]) for i in r.json()]


def _podio(categorias):
    cat = next(c for c in categorias if c["chave"] == "melhor_leitor")
    return [(i["aluno_id"], i["posicao"], i["valor"]) for i in cat["podio"]]


@pytest.mark.parametrize("limite", [5, 50])
def test_melhor_leitor_desempata_por_livros_e_tempo_como_o_ranking(
        cliente, db, escola_completa, limite):
    esc, ana, joao = _cenario(db, escola_completa)
    ranking = _posicoes_do_ranking(cliente, esc)
    r = cliente.get(f"{API}/escolas/{esc.id}/premiacoes?{Q}&limite={limite}")
    assert r.status_code == 200, r.text
    podio = _podio(r.json()["categorias"])
    # Os pontos empatam (é o cenário) e são os mesmos nas duas telas...
    assert ranking[0][2] == ranking[1][2]
    assert {a: p for a, _, p in ranking} == {a: v for a, _, v in podio}
    # ...e o desempate é o MESMO: João leu mais tempo, é o 1º nas duas.
    assert [a for a, _, _ in ranking] == [joao.id, ana.id]
    assert podio == ranking, (
        f"Ranking de Leitura dá {ranking}, Premiações (Melhor Leitor) dá {podio}")


def test_melhor_leitor_por_turno_desempata_como_o_ranking_do_turno(
        cliente, db, escola_completa):
    esc, ana, joao = _cenario(db, escola_completa, turno="manha")
    ranking = _posicoes_do_ranking(cliente, esc, "&turno=manha")
    r = cliente.get(f"{API}/escolas/{esc.id}/premiacoes?{Q}&turnos=true")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert _podio(corpo["categorias"]) == ranking
    (bloco,) = [t for t in corpo["turnos"] if t["turno"] == "manha"]
    podio_turno = _podio(bloco["categorias"])
    assert [a for a, _, _ in ranking] == [joao.id, ana.id]
    assert podio_turno == ranking, (
        f"Ranking de Leitura do turno dá {ranking}, pódio do turno dá {podio_turno}")
