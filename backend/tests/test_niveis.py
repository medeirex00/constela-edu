"""Cadastro dos níveis de dificuldade (faixas) e provisionamento da escola.

Cobre o conserto do beco "Cadastre os níveis de dificuldade": criar/editar/
excluir níveis pela interface, o atalho de níveis padrão e o fato de uma escola
nova nascer provisionada (antes, escola criada pela tela ficava sem níveis).
"""
from sqlalchemy import select

from app.models import Escola, NivelDificuldade, ReferenciaNormalizacao
from app.services import provisionamento

API = "/api/v1"


def _niveis(cliente, escola_id=1):
    r = cliente.get(f"{API}/escolas/{escola_id}/configuracoes/dificuldade")
    assert r.status_code == 200, r.text
    return r.json()["niveis"]


def test_criar_editar_e_excluir_nivel(cliente):
    # cria — códigos são normalizados (maiúsculo, sem espaço, sem repetido)
    r = cliente.post(f"{API}/escolas/1/configuracoes/niveis",
                     json={"nome": "Nível 9", "codigos": ["y", "z ", "Z"], "pontos_padrao": 20})
    assert r.status_code == 201, r.text
    novo = r.json()
    assert novo["codigos"] == ["Y", "Z"]
    assert novo["codigo"] == "nivel_9"
    nivel_id = novo["id"]

    assert "Nível 9" in [n["nome"] for n in _niveis(cliente)]

    # edita nome e pontos
    r = cliente.put(f"{API}/escolas/1/configuracoes/niveis/{nivel_id}",
                    json={"pontos_padrao": 25, "nome": "Nível X"})
    assert r.status_code == 200, r.text
    assert r.json()["pontos_padrao"] == 25
    assert r.json()["nome"] == "Nível X"

    # exclui
    r = cliente.delete(f"{API}/escolas/1/configuracoes/niveis/{nivel_id}")
    assert r.status_code == 200, r.text
    assert "Nível X" not in [n["nome"] for n in _niveis(cliente)]


def test_niveis_padrao_desbloqueiam_a_pontuacao_por_turma(cliente, db):
    # esvazia os níveis desta escola -> beco: catálogo de pontuação vazio
    for n in db.execute(
        select(NivelDificuldade).where(NivelDificuldade.escola_id == 1)
    ).scalars().all():
        db.delete(n)
    db.commit()
    r = cliente.get(f"{API}/escolas/1/configuracoes/pontuacao-turma")
    assert r.status_code == 200
    assert r.json()["catalogo"] == []

    # 1 clique: níveis padrão do Elefante
    r = cliente.post(f"{API}/escolas/1/configuracoes/niveis/padrao")
    assert r.status_code == 200, r.text
    assert r.json()["criados"] == len(provisionamento.NIVEIS_PADRAO)

    # agora o catálogo tem códigos -> pontuação por turma liberada
    r = cliente.get(f"{API}/escolas/1/configuracoes/pontuacao-turma")
    codigos = [c["codigo"] for c in r.json()["catalogo"]]
    assert "AA" in codigos and "Z" in codigos


def test_niveis_padrao_nao_duplica_se_ja_existem(cliente):
    antes = len(_niveis(cliente))
    r = cliente.post(f"{API}/escolas/1/configuracoes/niveis/padrao")
    assert r.status_code == 200
    assert r.json()["criados"] == 0
    assert len(_niveis(cliente)) == antes


def test_semear_config_inicial_provisiona_escola_nova(db):
    escola = Escola(nome="ESCOLA NOVA", ano_letivo_ativo=2026)
    db.add(escola)
    db.flush()
    provisionamento.semear_config_inicial(db, escola.id)
    db.commit()

    niveis = db.execute(
        select(NivelDificuldade).where(NivelDificuldade.escola_id == escola.id)
    ).scalars().all()
    assert len(niveis) == len(provisionamento.NIVEIS_PADRAO)
    ref = db.execute(
        select(ReferenciaNormalizacao).where(ReferenciaNormalizacao.escola_id == escola.id)
    ).scalar_one_or_none()
    assert ref is not None and ref.modo == "auto"
