"""Linha do tempo cronológica e espelho por aluno (EventoAluno)."""
from datetime import datetime

from app.models import EventoAluno, Importacao


def _seed_eventos(db, escola_id, aluno_id):
    imp = Importacao(escola_id=escola_id, plataforma="elefante", tipo="seed")
    db.add(imp)
    db.flush()

    def ev(quando, chave, titulo, nivel=None, seg=None):
        db.add(EventoAluno(
            escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
            plataforma="elefante", tipo_evento="leitura", ocorrido_em=quando,
            chave_natural=chave, conteudo_titulo=titulo, nivel_codigo=nivel,
            tempo_segundos=seg, dados={}))

    ev(datetime(2026, 3, 1, 10, 0), "k1", "Livro A", "C", 300)
    ev(datetime(2026, 3, 2, 9, 0), "k2", "Livro B", "D", 600)
    ev(datetime(2026, 3, 3, 8, 0), "k3", "Livro C", None, 120)
    db.commit()


def _url(escola_id, aluno_id, sufixo):
    return f"/api/v1/escolas/{escola_id}/alunos/{aluno_id}/{sufixo}"


def test_linha_do_tempo_ordena_e_pagina_por_cursor(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    _seed_eventos(db, escola.id, aluno.id)

    r = cliente.get(_url(escola.id, aluno.id, "linha-do-tempo"),
                    params={"limite": 2})
    assert r.status_code == 200, r.text
    corpo = r.json()
    # mais recente primeiro
    assert [i["conteudo_titulo"] for i in corpo["itens"]] == ["Livro C", "Livro B"]
    assert corpo["proximo_cursor"]

    r2 = cliente.get(_url(escola.id, aluno.id, "linha-do-tempo"),
                     params={"limite": 2, "cursor": corpo["proximo_cursor"]})
    corpo2 = r2.json()
    assert [i["conteudo_titulo"] for i in corpo2["itens"]] == ["Livro A"]
    assert corpo2["proximo_cursor"] is None


def test_espelho_consolida_contadores_e_tempo(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    _seed_eventos(db, escola.id, aluno.id)

    r = cliente.get(_url(escola.id, aluno.id, "espelho"))
    assert r.status_code == 200, r.text
    esp = r.json()["espelho"]
    assert esp["total_eventos"] == 3
    assert esp["por_tipo"] == {"leitura": 3}
    assert esp["por_plataforma"] == {"elefante": 3}
    assert esp["tempo_total_segundos"] == 1020
    assert esp["primeira_atividade"].startswith("2026-03-01")
    assert esp["ultima_atividade"].startswith("2026-03-03")


def test_linha_do_tempo_404_aluno_de_outra_escola(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    r = cliente.get(_url(escola.id, 999999, "linha-do-tempo"))
    assert r.status_code == 404
