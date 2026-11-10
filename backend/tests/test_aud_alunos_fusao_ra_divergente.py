"""Fusão recusada por RA divergente diz um caminho que EXISTE.

O 409 de ``POST /alunos/fundir`` terminava sempre com "corrija antes o dado
divergente em Alunos › Editar dados". Nascimento e nº de chamada se corrigem ali;
o RA não — ``AlunoUpdate`` não tem o campo e o modal também não (o PATCH com
``ficha`` responde 400 "Nada para atualizar."). Para RA divergente, a saída real
é a da própria fusão: deixar como principal a ficha com o RA certo e confirmar
com "FUNDIR MESMO COM CONFLITO" — a fusão guarda o RA da ficha principal.

Achado ALUNOS-10 da auditoria. Dados fictícios.
"""
from datetime import date

from sqlalchemy import select

from app.models import Aluno

API = "/api/v1"
CONFIRMA_CONFLITO = "FUNDIR MESMO COM CONFLITO"


def _fundir(cliente, escola_id, manter, remover, **extra):
    return cliente.post(f"{API}/escolas/{escola_id}/alunos/fundir",
                        json={"manter_id": manter, "remover_id": remover,
                              "confirmacao": "FUNDIR", **extra})


def _par(db, escola_completa, *, ra=("111222333", "111222334"), nasc=(None, None)):
    a, b = escola_completa["alunos"][0], escola_completa["alunos"][1]
    a.ficha, b.ficha = {"ra": ra[0]}, {"ra": ra[1]}
    a.data_nascimento, b.data_nascimento = nasc
    db.commit()
    return escola_completa["escola"].id, a.id, b.id


def test_ra_divergente_nao_manda_corrigir_em_editar_dados(cliente, db, escola_completa):
    escola_id, a_id, b_id = _par(db, escola_completa)
    r = _fundir(cliente, escola_id, a_id, b_id)
    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert "RA 111222333 × 111222334" in detalhe
    assert "Editar dados" not in detalhe, \
        f"manda corrigir o RA em “Editar dados”, que não edita o RA: {detalhe}"
    assert "RA certo" in detalhe and CONFIRMA_CONFLITO in detalhe, detalhe
    # O que "Editar dados" faz com o RA continua igual (não é o caminho).
    e = cliente.patch(f"{API}/escolas/{escola_id}/alunos/{b_id}", json={"ficha": {"ra": "1"}})
    assert e.status_code == 400


def test_seguir_a_orientacao_funde_com_o_ra_da_ficha_principal(cliente, db,
                                                               escola_completa):
    """A ficha com o RA certo como principal + a confirmação específica: fica uma
    ficha só, com o RA certo."""
    escola_id, a_id, b_id = _par(db, escola_completa)
    r = _fundir(cliente, escola_id, a_id, b_id, confirmar_conflito=CONFIRMA_CONFLITO)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.execute(select(Aluno.id).where(Aluno.id == b_id)).scalar_one_or_none() is None
    assert db.execute(select(Aluno.ficha).where(Aluno.id == a_id)).scalar_one()["ra"] \
        == "111222333"


def test_nascimento_divergente_continua_indo_para_editar_dados(cliente, db,
                                                               escola_completa):
    escola_id, a_id, b_id = _par(db, escola_completa, ra=("", ""),
                                 nasc=(date(2017, 5, 17), date(2018, 5, 17)))
    r = _fundir(cliente, escola_id, a_id, b_id)
    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert "nascimento 2017-05-17 × 2018-05-17" in detalhe
    assert "corrija antes o dado divergente em Alunos › Editar dados" in detalhe, detalhe
    assert "RA certo" not in detalhe


def test_ra_e_nascimento_divergentes_dizem_os_dois_caminhos(cliente, db, escola_completa):
    escola_id, a_id, b_id = _par(db, escola_completa,
                                 nasc=(date(2017, 5, 17), date(2018, 5, 17)))
    r = _fundir(cliente, escola_id, a_id, b_id)
    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert "RA certo" in detalhe and "Editar dados" in detalhe, detalhe
    # "Editar dados" é citado só para o que ele corrige.
    assert "o nascimento e o nº de chamada" in detalhe, detalhe
