"""A7 — a fusão continua mantendo a data de quem fica (decisão C2), mas deixa de
fazer isso às cegas: a data descartada vai para o log, e a prévia (só leitura)
mostra antes do FUNDIR quantos livros repetidos têm data diferente e quantos
deixam de contar no bimestre da premiação. Dados fictícios."""
import json
from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from app.models import Escola, LogAuditoria
from app.models.plataformas import Leitura, Livro
from app.services import alunos_fusao
from tests.sync_integridade_comum import aluno

# Dia "de hoje" fixo no 3º bimestre de 2026 (24/07 a 04/10).
HOJE = datetime(2026, 8, 20, 10, 0)


@pytest.fixture(autouse=True)
def _hoje_fixo(monkeypatch):
    monkeypatch.setattr(alunos_fusao, "agora_br", lambda: HOJE)


def _livro(db, escola_id, titulo):
    livro = Livro(escola_id=escola_id, titulo=titulo, nivel_codigo="D", nivel_fonte="D",
                  origem_nivel="legado")
    db.add(livro)
    db.flush()
    return livro


def _ler(db, escola_id, a, livro, quando):
    db.add(Leitura(escola_id=escola_id, aluno_id=a.id, livro_id=livro.id, data=quando))


@pytest.fixture()
def par(db, escola_completa):
    """Oficial e stub com quatro livros em comum (e um só do stub):
      A: oficial 25/03 (1º bim.)  × stub 06/08 (3º) → com a oficial, sai do 3º;
      B: mesma data nas duas      → nada muda;
      C: 01/08 × 10/08, ambos 3º  → data diferente, mesmo bimestre;
      D: só no stub               → é movido, não é repetido."""
    esc, t = escola_completa["escola"], escola_completa["turma"]
    oficial = aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    stub = aluno(db, esc.id, t, "Zefa Quaresma")
    a, b, c, d = (_livro(db, esc.id, f"Livro Ficticio {x}") for x in "ABCD")
    _ler(db, esc.id, oficial, a, datetime(2026, 3, 25, 14, 0))
    _ler(db, esc.id, stub, a, datetime(2026, 8, 6, 9, 30))
    _ler(db, esc.id, oficial, b, datetime(2026, 5, 2, 8, 0))
    _ler(db, esc.id, stub, b, datetime(2026, 5, 2, 15, 0))
    _ler(db, esc.id, oficial, c, datetime(2026, 8, 1, 8, 0))
    _ler(db, esc.id, stub, c, datetime(2026, 8, 10, 8, 0))
    _ler(db, esc.id, stub, d, datetime(2026, 8, 12, 8, 0))
    db.commit()
    return {"escola": esc.id, "oficial": oficial.id, "stub": stub.id,
            "livros": {x: lv.id for x, lv in zip("ABCD", (a, b, c, d))}}


def _url(eid):
    return f"/api/v1/escolas/{eid}/alunos/fundir"


def test_log_da_fusao_guarda_cada_livro_descartado_com_as_duas_datas(cliente, db, par):
    r = cliente.post(_url(par["escola"]), json={"manter_id": par["oficial"],
                                                "remover_id": par["stub"],
                                                "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    assert r.json()["leituras_descartadas"] == 3
    log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "aluno.fundido")
                     ).scalars().one()
    detalhe = {d["livro"]: d for d in log.detalhes["leituras_descartadas_detalhe"]}
    assert sorted(detalhe) == ["Livro Ficticio A", "Livro Ficticio B", "Livro Ficticio C"]
    assert detalhe["Livro Ficticio A"]["data_manter"].startswith("2026-03-25")
    assert detalhe["Livro Ficticio A"]["data_remover"].startswith("2026-08-06")
    assert detalhe["Livro Ficticio A"]["livro_id"] == par["livros"]["A"]
    # A REGRA não mudou (C2): fica a data de quem fica.
    fica = db.execute(select(Leitura.data).where(Leitura.aluno_id == par["oficial"],
                                                 Leitura.livro_id == par["livros"]["A"])
                      ).scalar_one()
    assert fica.date() == date(2026, 3, 25)


def test_previa_conta_repetidos_data_diferente_e_o_bimestre_que_perde_o_livro(cliente, db, par):
    antes = db.execute(select(func.count()).select_from(Leitura)).scalar_one()
    r = cliente.get(f"{_url(par['escola'])}/previa",
                    params={"manter_id": par["oficial"], "remover_id": par["stub"]})
    assert r.status_code == 200, r.text
    lei = r.json()["leituras"]
    assert lei["livros_repetidos"] == 3
    assert lei["com_data_diferente"] == 2            # A e C (B é o mesmo dia)
    assert lei["bimestre"]["numero"] == 3
    assert lei["no_bimestre"] == 1                   # só A sai do 3º; C fica nele
    assert lei["por_bimestre"] == [{"numero": 3, "rotulo": "3º bimestre", "livros": 1}]
    primeiro = lei["exemplos"][0]
    assert (primeiro["livro"], primeiro["data_manter"], primeiro["data_remover"],
            primeiro["deixa_de_contar_em"]) == ("Livro Ficticio A", "2026-03-25",
                                                "2026-08-06", 3)
    # Só leitura: nada mudou.
    db.expire_all()
    assert db.execute(select(func.count()).select_from(Leitura)).scalar_one() == antes


def test_previa_depende_da_direcao(cliente, par):
    """Trocar a ficha principal troca a data que fica — a prévia acompanha."""
    r = cliente.get(f"{_url(par['escola'])}/previa",
                    params={"manter_id": par["stub"], "remover_id": par["oficial"]})
    lei = r.json()["leituras"]
    assert lei["com_data_diferente"] == 2
    assert lei["no_bimestre"] == 0                   # agora quem fica é agosto
    assert lei["por_bimestre"] == [{"numero": 1, "rotulo": "1º bimestre", "livros": 1}]


def test_previa_sem_calendario_nao_inventa_bimestre(cliente, db, par):
    db.get(Escola, par["escola"]).ano_letivo_ativo = 2031
    db.commit()
    r = cliente.get(f"{_url(par['escola'])}/previa",
                    params={"manter_id": par["oficial"], "remover_id": par["stub"]})
    lei = r.json()["leituras"]
    assert lei["com_data_diferente"] == 2
    assert lei["bimestre"] is None and lei["no_bimestre"] is None
    assert lei["por_bimestre"] == []


def test_previa_recusa_o_mesmo_aluno_e_aluno_de_fora(cliente, par):
    url = f"{_url(par['escola'])}/previa"
    assert cliente.get(url, params={"manter_id": par["oficial"],
                                    "remover_id": par["oficial"]}).status_code == 400
    assert cliente.get(url, params={"manter_id": par["oficial"],
                                    "remover_id": 987654}).status_code == 404


def test_previa_do_lote_traz_as_leituras_de_cada_par(cliente, par):
    r = cliente.get(f"/api/v1/escolas/{par['escola']}/alunos/duplicados")
    assert r.status_code == 200, r.text
    [cand] = [c for c in r.json()["candidatos"] if c["loser_id"] == par["stub"]]
    assert cand["manter_id"] == par["oficial"]
    lei = cand["leituras"]
    assert (lei["livros_repetidos"], lei["com_data_diferente"], lei["no_bimestre"]) == (3, 2, 1)
    assert lei["exemplos"] == []                     # o lote só conta; o detalhe é na ficha


def test_previa_e_barrada_para_a_secretaria(db, escola_completa, par):
    """Mesmo portão de /alunos/duplicados: nome de criança e livros dela."""
    from fastapi import HTTPException

    from app.models import Usuario
    from app.routers import academico

    sec = Usuario(nome="Secretaria Ficticia", email="sec-previa@teste.local",
                  senha_hash="x", cargo="admin", rede_id=1, escola_id=None)
    with pytest.raises(HTTPException) as erro:
        academico.previa_fundir_alunos(manter_id=par["oficial"], remover_id=par["stub"],
                                       escola_id=par["escola"], usuario=sec, db=db)
    assert erro.value.status_code == 403


def test_detalhe_do_log_e_json_serializavel_sem_conversao(db, escola_completa, par):
    """O detalhe vai para o LogAuditoria (JSON): nada de datetime cru."""
    oficial = db.get(type(escola_completa["alunos"][0]), par["oficial"])
    stub = db.get(type(escola_completa["alunos"][0]), par["stub"])
    r = alunos_fusao.fundir_par(db, par["escola"], oficial, stub, escola_completa["admin"].id)
    db.commit()
    assert r["leituras_descartadas"] == 3
    log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "aluno.fundido")
                     ).scalars().one()
    json.dumps(log.detalhes)
