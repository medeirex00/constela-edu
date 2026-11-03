"""Ranking de TURMAS — a ordem e a posição saem do BACKEND.

A tela (``RankingTurmas.tsx``) pegava ``/resumo-escola``, ordenava no navegador
e numerava ``i + 1`` com desempate por ``localeCompare`` — uma segunda ordem,
diferente da convenção do backend (nome ``casefold`` + id), e com a turma da
Fase dentro (a Nota antiga dela tem média). ``GET /ranking/turmas`` usa a MESMA
média do resumo da escola e põe em ordem num lugar só; a tela só exibe.
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno,
    Importacao,
    Matricula,
    ModuloRede,
    Nota,
    Professor,
    Rede,
    SnapshotElefante,
    Turma,
    Usuario,
)

API = "/api/v1"


def _turma_com_notas(db, escola, imp, nome, notas, ano_escolar="3º Ano", turno="manha"):
    """Turma cujos alunos têm Nota de Leitura e retrato do Elefante (aferidos)."""
    turma = Turma(escola_id=escola.id, nome=nome, ano_escolar=ano_escolar,
                  ano_letivo=2026, turno=turno, status="ativa")
    db.add(turma)
    db.flush()
    for i, valor in enumerate(notas):
        a = Aluno(escola_id=escola.id, nome=f"Aluno Teste {nome} {i}", status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=2026))
        db.add(Nota(escola_id=escola.id, aluno_id=a.id, ano_letivo=2026,
                    nota_elefante=valor, aferido_leitura=True))
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                                data_referencia=datetime(2026, 10, 1), livros_unicos=2,
                                livros_por_nivel={"D": 2}))
    return turma


@pytest.fixture()
def turmas(db, escola_completa):
    escola = escola_completa["escola"]
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    t = {
        # média 80, 1 aferido
        "bosque": _turma_com_notas(db, escola, imp, "Bosque", [80.0]),
        # média 80, 2 aferidos → à frente do Bosque (mais aferidos desempata)
        "campo": _turma_com_notas(db, escola, imp, "Campo", [70.0, 90.0], turno="tarde"),
        # média 80, 1 aferido, mesmo critério do Bosque → decide o nome (casefold)
        "arvore": _turma_com_notas(db, escola, imp, "árvore", [80.0]),
        # média maior
        "duna": _turma_com_notas(db, escola, imp, "Duna", [95.0]),
        # a Fase com a maior média de todas (Nota antiga) — não concorre
        "fase": _turma_com_notas(db, escola, imp, "1ª Fase Teste", [99.0],
                                 ano_escolar="1ª Fase"),
    }
    db.commit()
    return {"escola": escola, **t}


def _ranking(cliente, escola_id, **params):
    r = cliente.get(f"{API}/escolas/{escola_id}/ranking/turmas",
                    params={"dimensao": "leitura", **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_ordem_e_posicao_vem_do_backend_com_desempate_deterministico(cliente, turmas):
    corpo = _ranking(cliente, turmas["escola"].id)
    ordem = [(i["posicao"], i["nome"]) for i in corpo["itens"]]
    # Duna (95) → Campo (80, 2 aferidos) → empate Bosque × árvore (80, 1): nome
    # em casefold, a mesma convenção dos rankings de aluno ("bosque" < "árvore"
    # em codepoint — o `localeCompare` do navegador poria "árvore" antes, e era
    # exatamente essa a divergência). A turma do 3º Ano A da fixture não tem
    # ninguém aferido e não entra.
    assert ordem == [(1, "Duna"), (2, "Campo"), (3, "Bosque"), (4, "árvore")]
    assert corpo["dimensao"] == "leitura"
    campo = corpo["itens"][1]
    assert campo["media"] == 80.0 and campo["n_aferidos"] == 2 and campo["total_alunos"] == 2


def test_a_turma_da_fase_nao_concorre(cliente, turmas):
    escola_id = turmas["escola"].id
    # O furo que a tela tinha: o resumo da escola (visão por turma, não ranking)
    # traz a turma da Fase COM média — e a tela a ordenava junto.
    resumo = cliente.get(f"{API}/escolas/{escola_id}/resumo-escola").json()
    fase = next(t for t in resumo["turmas"] if t["turma"]["id"] == turmas["fase"].id)
    assert fase["n_leitura"] == 1 and fase["media_leitura"] == 99.0
    ids = [i["turma_id"] for i in _ranking(cliente, escola_id)["itens"]]
    assert turmas["fase"].id not in ids, "a Fase não concorre, nem com a maior média"


def test_mesma_media_do_resumo_da_escola(cliente, turmas):
    """Nenhum cálculo novo: a média é a do resumo da escola."""
    escola = turmas["escola"]
    resumo = cliente.get(f"{API}/escolas/{escola.id}/resumo-escola").json()
    por_id = {t["turma"]["id"]: t for t in resumo["turmas"]}
    for item in _ranking(cliente, escola.id)["itens"]:
        assert item["media"] == por_id[item["turma_id"]]["media_leitura"]
        assert item["n_aferidos"] == por_id[item["turma_id"]]["n_leitura"]


@pytest.mark.parametrize("turno,esperado", [
    ("manha", [(1, "Duna"), (2, "Bosque"), (3, "árvore")]),
    ("tarde", [(1, "Campo")]),
    ("", []),
])
def test_turno_recorta_e_renumera(cliente, turmas, turno, esperado):
    corpo = _ranking(cliente, turmas["escola"].id, turno=turno)
    assert [(i["posicao"], i["nome"]) for i in corpo["itens"]] == esperado


def test_validacoes_e_contrato(cliente, db, turmas):
    escola = turmas["escola"]
    r = cliente.get(f"{API}/escolas/{escola.id}/ranking/turmas",
                    params={"dimensao": "geral"})
    assert r.status_code == 400
    rede = Rede(nome="Rede Sem Matematica", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(ModuloRede(rede_id=rede.id, modulo="matematica", ativo=False))
    db.commit()
    r = cliente.get(f"{API}/escolas/{escola.id}/ranking/turmas",
                    params={"dimensao": "matematica"})
    assert r.status_code == 403


def test_professor_nao_abre_o_ranking_de_turmas(db, turmas):
    """Mesmo acesso do resumo da escola (gestão): o escopo não muda."""
    escola = turmas["escola"]
    prof = Professor(escola_id=escola.id, nome="Professora Teste", email="prof@turmas.local")
    db.add(prof)
    db.flush()
    turmas["duna"].professor_id = prof.id
    db.add(Usuario(escola_id=escola.id, nome="Professora Teste", email="prof@turmas.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()
    cli = TestClient(app)
    r = cli.post(f"{API}/auth/login",
                 data={"username": "prof@turmas.local", "password": "s3nh4"})
    cli.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    assert cli.get(f"{API}/escolas/{escola.id}/resumo-escola").status_code == 403
    r = cli.get(f"{API}/escolas/{escola.id}/ranking/turmas", params={"dimensao": "leitura"})
    assert r.status_code == 403
