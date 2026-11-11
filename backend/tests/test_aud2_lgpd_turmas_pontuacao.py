"""G_MODULOS-8: consolidar turmas duplicadas não apaga, em silêncio, a pontuação por
nível que o Admin Global gravou para a turma duplicada.

``turmas_dedup.consolidar`` move as matrículas e faz ``db.delete(dup)``; a
``PontuacaoNivelTurma`` tem ``ondelete=CASCADE`` e sumia junto — sem aviso na
prévia nem na resposta. A rota é da coordenação e do admin da escola, mas a
pontuação por turma é parâmetro oficial do Admin Global (PUT /pontuacao-turma).
Herdar a configuração na turma que fica mudaria os pontos de quem já estava nela
(decisão do dono); então o grupo em que a duplicada tem pontuação própria diferente
da que fica é recusado (409, antes de mover qualquer matrícula) e a prévia avisa.

Dados 100% fictícios; sem rede.
"""
from datetime import datetime

import pytest

from app.models import (
    Aluno,
    Importacao,
    Matricula,
    Nota,
    PontuacaoNivelTurma,
    Professor,
    SnapshotElefante,
    Turma,
)

API = "/api/v1"


@pytest.fixture()
def cena(db, escola_completa, cliente_global):
    """'3º Ano A' (canônica, com titular) e '3 ANO A' (a duplicada vinda do SED),
    onde está a Lia; perfil personalizado."""
    escola = escola_completa["escola"]
    canonica = escola_completa["turma"]
    prof = Professor(escola_id=escola.id, nome="Prof Ficticia Turma",
                     email="prof.turma@teste.local")
    db.add(prof)
    db.flush()
    canonica.professor_id = prof.id
    dup = Turma(escola_id=escola.id, nome="3 ANO A", ano_escolar="3º Ano", ano_letivo=2026)
    db.add(dup)
    db.flush()
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    lia = Aluno(escola_id=escola.id, nome="Lia Ficticia Turma")
    db.add(lia)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=lia.id, turma_id=dup.id, ano_letivo=2026))
    for a in [*escola_completa["alunos"], lia]:
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                                livros_unicos=5, livros_por_nivel={"D": 5},
                                data_referencia=datetime(2026, 3, 10)))
    db.commit()
    base = f"{API}/escolas/{escola.id}/configuracoes"
    r = cliente_global.put(f"{base}/perfil-scoring", json={"modo": "personalizado"})
    assert r.status_code == 200, r.text
    return {"eid": escola.id, "canonica": canonica.id, "dup": dup.id, "lia": lia.id,
            "base": base}


def _pontuar(cliente_global, cena, turma_id, pontos):
    r = cliente_global.put(f"{cena['base']}/pontuacao-turma",
                           json={"turma_id": turma_id, "pontos": pontos, "aplicar_em": []})
    assert r.status_code == 200, r.text


def _pontos_da_lia(db, cena):
    db.expire_all()
    nota = db.query(Nota).filter(Nota.aluno_id == cena["lia"]).one()
    return nota.detalhes["elefante"]["indicadores"][1]["valor"]


def _consolidar(cliente, cena):
    return cliente.post(f"{API}/escolas/{cena['eid']}/turmas/duplicadas/corrigir",
                        json=[{"canonica_id": cena["canonica"], "duplicada_ids": [cena["dup"]]}])


def _configs(db, cena):
    db.expire_all()
    return {p.turma_id: p.pontos_por_codigo for p in db.query(PontuacaoNivelTurma).filter(
        PontuacaoNivelTurma.escola_id == cena["eid"])}


def test_pontuacao_so_na_duplicada_recusa_a_consolidacao(db, cena, cliente, cliente_global):
    _pontuar(cliente_global, cena, cena["dup"], {"D": 10})
    antes = _pontos_da_lia(db, cena)

    r = _consolidar(cliente, cena)
    configs = _configs(db, cena)
    print("CONSOLIDAR:", r.status_code, r.json(), "| configs:", configs)
    assert configs, "a pontuação por turma do Admin Global sumiu"
    assert r.status_code == 409, r.text
    texto = r.json()["detail"]
    assert "“3 ANO A”" in texto and "pontuação por nível" in texto
    assert "Admin Global" in texto
    # Nada mudou: a Lia continua na duplicada, com os mesmos pontos.
    db.expire_all()
    assert db.get(Turma, cena["dup"]) is not None
    assert db.query(Matricula).filter(Matricula.aluno_id == cena["lia"]).one().turma_id == cena["dup"]
    assert _pontos_da_lia(db, cena) == antes


def test_a_previa_avisa_antes(db, cena, cliente, cliente_global):
    _pontuar(cliente_global, cena, cena["dup"], {"D": 10})
    grupos = cliente.get(f"{API}/escolas/{cena['eid']}/turmas/duplicadas").json()
    grupo, = [g for g in grupos if g["canonica"]["id"] == cena["canonica"]]
    assert grupo["recusa"] and "pontuação por nível" in grupo["recusa"]
    assert grupo["recusa"] == _consolidar(cliente, cena).json()["detail"]


def test_pontuacoes_diferentes_nas_duas_tambem_recusa(db, cena, cliente, cliente_global):
    _pontuar(cliente_global, cena, cena["dup"], {"D": 10})
    _pontuar(cliente_global, cena, cena["canonica"], {"D": 6})
    assert _consolidar(cliente, cena).status_code == 409
    assert set(_configs(db, cena)) == {cena["dup"], cena["canonica"]}


def test_a_mesma_pontuacao_nas_duas_consolida_sem_mudar_ponto(db, cena, cliente, cliente_global):
    _pontuar(cliente_global, cena, cena["dup"], {"D": 10})
    _pontuar(cliente_global, cena, cena["canonica"], {"D": 10})
    antes = _pontos_da_lia(db, cena)
    grupos = cliente.get(f"{API}/escolas/{cena['eid']}/turmas/duplicadas").json()
    assert all(g["recusa"] is None for g in grupos)
    r = _consolidar(cliente, cena)
    assert r.status_code == 200, r.text
    assert _configs(db, cena) == {cena["canonica"]: {"D": 10.0}}
    assert _pontos_da_lia(db, cena) == antes


def test_sem_pontuacao_na_duplicada_consolida_como_antes(db, cena, cliente, cliente_global):
    """Controle: pontuação só na turma que fica (ou em nenhuma) — nada se perde."""
    _pontuar(cliente_global, cena, cena["canonica"], {"D": 6})
    r = _consolidar(cliente, cena)
    assert r.status_code == 200, r.text
    assert _configs(db, cena) == {cena["canonica"]: {"D": 6.0}}


def test_um_grupo_recusado_recusa_o_pedido_inteiro_antes_de_mover(
        db, cena, cliente, cliente_global, escola_completa):
    """Como a canônica arquivada e a duplicada de outro ano: 409 para o pedido
    inteiro, sem consolidar nem os grupos que poderiam passar."""
    eid = cena["eid"]
    b = Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    b_dup = Turma(escola_id=eid, nome="4 ANO B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add_all([b, b_dup])
    db.commit()
    b_id, b_dup_id = b.id, b_dup.id
    _pontuar(cliente_global, cena, cena["dup"], {"D": 10})
    r = cliente.post(f"{API}/escolas/{eid}/turmas/duplicadas/corrigir", json=[
        {"canonica_id": b_id, "duplicada_ids": [b_dup_id]},
        {"canonica_id": cena["canonica"], "duplicada_ids": [cena["dup"]]}])
    assert r.status_code == 409, r.text
    db.expire_all()
    assert db.get(Turma, b_dup_id) is not None
