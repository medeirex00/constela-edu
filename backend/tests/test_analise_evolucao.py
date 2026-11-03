"""Análise educacional — a EVOLUÇÃO das plataformas por bimestre
(``GET /redes/{id}/analise/plataformas/evolucao``).

O que estes testes sustentam:

* só os bimestres que JÁ COMEÇARAM (calendário oficial de 2026), com o que contém hoje
  marcado ``em_andamento``;
* cada bimestre é EXATAMENTE a rota de plataformas com aquele bimestre (rede e escolas):
  nada recalculado;
* escolas em ordem alfabética; ausência ≠ zero (sem coleta = nulo com motivo); módulo não
  contratado = nulo;
* k = 5: escola suprimida fica sem número em todos os bimestres (motivo único);
* filtros de série e de escola (série inválida 400; escola de outra rede 404);
* permissões (``exigir_rede``), nenhum dado pessoal, banco igual antes e depois — as duas
  últimas também em ``test_analise_diagnostico`` (as duas rotas novas juntas).

Dados INVENTADOS (``test_analise_base``; decisão D13).
"""
import json
from datetime import date, datetime

import pytest

from app.models import Aluno, Turma
from app.services.analise import evolucao as svc
from tests.test_analise_base import (HOJE, NOMES, PREFIXO_CRIANCA, mundo_plataformas,
                                     nova_escola, nova_rede, retrato_matific, turma_com_alunos)

URL = "/api/v1/redes/{rede}/analise/plataformas/evolucao"
URL_PLAT = "/api/v1/redes/{rede}/analise/plataformas"


@pytest.fixture()
def mundo(db, cliente_global, monkeypatch):
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: HOJE)
    return {**mundo_plataformas(db), "c": cliente_global, "monkeypatch": monkeypatch}


def _get(mundo, url=URL, **params):
    r = mundo["c"].get(url.format(rede=mundo["rede"].id), params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_so_os_bimestres_que_ja_comecaram(mundo):
    dados = _get(mundo)
    assert dados["ano_letivo"] == 2026 and dados["k_minimo"] == 5
    assert dados["calendario_oficial"] is True
    bims = dados["bimestres"]
    # Hoje = 05/10/2026: o 4º bimestre (05/10–31/12) começou hoje e está em andamento.
    assert [b["numero"] for b in bims] == [1, 2, 3, 4]
    assert [(b["inicio"], b["fim"]) for b in bims] == [
        ("2026-02-02", "2026-04-22"), ("2026-04-23", "2026-07-23"),
        ("2026-07-24", "2026-10-04"), ("2026-10-05", "2026-12-31")]
    assert [b["em_andamento"] for b in bims] == [False, False, False, True]
    assert bims[0]["rotulo"].startswith("1º bimestre")
    # Em 01/05/2026, só o 1º e o 2º (este em andamento).
    mundo["monkeypatch"].setattr("app.routers.analise.hoje_br", lambda: date(2026, 5, 1))
    cedo = _get(mundo)
    assert [(b["numero"], b["em_andamento"]) for b in cedo["bimestres"]] == [(1, False),
                                                                             (2, True)]


def test_cada_bimestre_e_a_rota_de_plataformas_daquele_bimestre(mundo):
    dados = _get(mundo)
    for b in dados["bimestres"]:
        plat = _get(mundo, URL_PLAT, periodo=f"bimestre_{b['numero']}")
        assert plat["janela"]["inicio"] == b["inicio"] and plat["janela"]["fim"] == b["fim"]
        for p, campos in svc.CAMPOS_REDE.items():
            for c in campos:
                assert b["rede"][p][c] == plat["rede"][p][c], (b["numero"], p, c)
        assert b["rede"]["escolas_com_dado"] == plat["rede"]["escolas_com_dado"]
        assert b["rede"]["escolas_parciais"] == {
            p: len(v) for p, v in plat["cobertura"]["escolas_coleta_parcial"].items()}
        assert [e["id"] for e in b["escolas"]] == [e["escola_id"] for e in plat["escolas"]]
        for ev, ep in zip(b["escolas"], plat["escolas"]):
            assert ev["cobertura"] == ep["cobertura"]
            for p, campos in svc.CAMPOS_ESCOLA.items():
                for c in campos:
                    assert ev[p][c] == ep[p][c], (b["numero"], ev["nome"], p, c)
    # Os livros de maio (2º bimestre) aparecem no 2º e não no 1º.
    alfa = mundo["escolas"]["alfa"].id
    por_bim = {b["numero"]: next(e for e in b["escolas"] if e["id"] == alfa)
               for b in dados["bimestres"]}
    assert por_bim[2]["elefante"]["livros_por_aluno"] > 0
    assert por_bim[1]["elefante"]["livros_por_aluno"] == 0.0
    # 4º bimestre: a última coleta do Elefante (30/09) é de antes dele — sem dado, não zero.
    assert por_bim[4]["elefante"]["livros_por_aluno"] is None
    assert por_bim[4]["elefante"]["motivo_sem_dado"] == "sem_coleta_no_periodo"


def test_ordem_alfabetica_e_ausencia_nao_e_zero(mundo):
    dados = _get(mundo)
    for b in dados["bimestres"]:
        assert [e["nome"] for e in b["escolas"]] == [
            NOMES["ebano"], NOMES["alfa"], NOMES["beta"], NOMES["delta"], NOMES["gama"]]
        beta = next(e for e in b["escolas"] if e["id"] == mundo["escolas"]["beta"].id)
        assert beta["elefante"]["participacao_pct"] is None
        assert beta["elefante"]["motivo_sem_dado"] == "sem_coleta"
        assert beta["elefante"]["texto_sem_dado"]
    assert dados["limitacoes"] and any("bimestre" in t for t in dados["limitacoes"])
    # A "aba de plataformas" não existe mais (virou a tela Elefante e Matific): o texto não a cita.
    assert not any("aba de plataformas" in t for t in dados["limitacoes"])


def test_filtros_de_serie_e_escola(db, mundo):
    alfa = mundo["escolas"]["alfa"]
    so3 = _get(mundo, serie=3)
    assert so3["filtros"] == {"serie": 3, "escola_id": None}
    plat3 = _get(mundo, URL_PLAT, periodo="bimestre_2", serie=3)
    b2 = next(b for b in so3["bimestres"] if b["numero"] == 2)
    a2 = next(e for e in b2["escolas"] if e["id"] == alfa.id)
    assert a2["elefante"]["livros_por_aluno"] == next(
        e for e in plat3["escolas"] if e["escola_id"] == alfa.id)["elefante"]["livros_por_aluno"]
    so_alfa = _get(mundo, escola_id=alfa.id)
    assert all([e["id"] for e in b["escolas"]] == [alfa.id] for b in so_alfa["bimestres"])
    c, rede = mundo["c"], mundo["rede"].id
    assert c.get(URL.format(rede=rede), params={"serie": 6}).status_code == 400
    assert c.get(URL.format(rede=rede), params={"escola_id": 999999}).status_code == 404
    vizinha = nova_rede(db, nome="Rede Fictícia Vizinha", codigo="3599908", codmun="9998")
    de_fora = nova_escola(db, vizinha, "EMEF Fictícia da Vizinha", "35990801")
    db.commit()
    r = c.get(URL.format(rede=rede), params={"escola_id": de_fora.id})
    assert r.status_code == 404 and "Vizinha" not in r.text


def test_so_escola_mede_so_a_escola_com_a_supressao_da_rede(db, mundo):
    """A ficha (``so_escola``): a escola com os MESMOS números da evolução da rede, a rede
    nula (não foi medida) e a supressão decidida pela rede INTEIRA — a escola pequena e a
    Beta (em complemento) continuam escondidas. Sem escola: 422; escola de fora: 404."""
    pequena = nova_escola(db, mundo["rede"], "EMEF Fictícia Pequena", "35990198")
    for a in turma_com_alunos(db, pequena, "4º Ano", 3):
        retrato_matific(db, pequena, a, datetime(2026, 9, 30, 3, 20), atividades=9373,
                        estrelas=9791)
    db.commit()
    da_rede = _get(mundo)
    for escola in (mundo["escolas"]["alfa"], pequena, mundo["escolas"]["beta"]):
        so = _get(mundo, escola_id=escola.id, so_escola=True)
        assert so["filtros"] == {"serie": None, "escola_id": escola.id, "so_escola": True}
        assert len(so["bimestres"]) == len(da_rede["bimestres"])
        for b, b_rede in zip(so["bimestres"], da_rede["bimestres"]):
            assert b["rede"] is None
            assert b["escolas"] == [next(e for e in b_rede["escolas"] if e["id"] == escola.id)]
    for escondida in (pequena, mundo["escolas"]["beta"]):
        so = _get(mundo, escola_id=escondida.id, so_escola=True)
        assert all(b["escolas"][0]["suprimido"] for b in so["bimestres"])
    c, rede = mundo["c"], mundo["rede"].id
    r = c.get(URL.format(rede=rede), params={"so_escola": True})
    assert r.status_code == 422 and "escola_id" in r.text
    vizinha = nova_rede(db, nome="Rede Fictícia Vizinha", codigo="3599908", codmun="9998")
    de_fora = nova_escola(db, vizinha, "EMEF Fictícia da Vizinha", "35990801")
    db.commit()
    r = c.get(URL.format(rede=rede), params={"escola_id": de_fora.id, "so_escola": True})
    assert r.status_code == 404 and "Vizinha" not in r.text


def test_k_escola_suprimida_fica_sem_numero_em_todo_bimestre(db, mundo):
    pequena = nova_escola(db, mundo["rede"], "EMEF Fictícia Pequena", "35990198")
    for a in turma_com_alunos(db, pequena, "4º Ano", 3):
        retrato_matific(db, pequena, a, datetime(2026, 9, 30, 3, 20), atividades=9373,
                        estrelas=9791)
    db.commit()
    r = mundo["c"].get(URL.format(rede=mundo["rede"].id))
    assert r.status_code == 200, r.text
    for b in r.json()["bimestres"]:
        for escola in (pequena, mundo["escolas"]["beta"]):      # a Beta junto, em complemento
            e = next(x for x in b["escolas"] if x["id"] == escola.id)
            assert e["suprimido"] is True and e["cobertura"] is None
            for p in ("elefante", "matific"):
                assert e[p]["participacao_pct"] is None and e[p]["motivo_sem_dado"] == "suprimido"
    assert "9373" not in r.text and "9791" not in r.text


def test_modulo_nao_contratado_fica_nulo(db, mundo):
    from app.services import modulos
    modulos.definir(db, mundo["rede"].id, "matematica", False)
    db.commit()
    dados = _get(mundo)
    assert dados["modulos"] == {"elefante": True, "matific": False}
    for b in dados["bimestres"]:
        assert b["rede"]["matific"] is None and b["rede"]["escolas_com_dado"]["matific"] is None
        assert all(e["matific"] is None for e in b["escolas"])


def test_nenhum_dado_pessoal(db, mundo):
    texto = json.dumps(_get(mundo), ensure_ascii=False)
    texto += json.dumps(_get(mundo, serie=3), ensure_ascii=False)
    assert "aluno_id" not in texto and PREFIXO_CRIANCA not in texto
    for nome in (a.nome for a in db.query(Aluno).all()):
        assert nome not in texto
    assert '"turma"' not in texto and "turma_id" not in texto
    turmas = [t.nome for t in db.query(Turma).all()]            # nem o nome da turma
    assert turmas and not [t for t in turmas if t in texto]


def test_ano_letivo_diferente_do_calendario_de_hoje(db, mundo):
    """Em janeiro de 2027, com as escolas ainda no ano letivo de 2026: os bimestres são os
    de 2026 (todos já começaram), pelas datas do calendário de 2026."""
    mundo["monkeypatch"].setattr("app.routers.analise.hoje_br", lambda: date(2027, 1, 10))
    dados = _get(mundo)
    assert dados["ano_letivo"] == 2026
    assert [b["inicio"] for b in dados["bimestres"]] == ["2026-02-02", "2026-04-23",
                                                         "2026-07-24", "2026-10-05"]
    assert not any(b["em_andamento"] for b in dados["bimestres"])
