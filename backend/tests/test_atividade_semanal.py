"""GET /escolas/{id}/atividade-semanal — % da coorte ativa por semana e plataforma.

O que este arquivo trava:
* semanas de segunda a domingo, em ordem cronológica, a última é a corrente;
* "ativo" = a mesma regra da Visão Geral (Leitura: leu ou releu; Matific: GANHO > 0);
* semana sem coleta = ``null`` (lacuna), nunca 0 — e semana COM coleta e sem ganho = 0;
* semana fechada vista só em parte (Elefante) e ganho com base antiga (Matific, a
  atividade de uma semana sem coleta) também são lacuna;
* módulo fora do plano: ``*_contratado=false`` e tudo nulo;
* professor recortado (denominador das turmas dele), Secretaria negada;
* o recorte da série do Matific dá o MESMO ganho da regra oficial sobre a série toda.

Hoje fixo: quarta, 14/10/2026. Nomes fictícios.
"""
import random
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (Aluno, Matricula, ModuloRede, Professor, Rede, Turma,
                        Usuario)
from app.services import matific_destaque
from app.services import visao_geral as svc
from tests.test_visao_geral import (_coleta_elefante, _evento, _leitura, _login,
                                    _matific)

API = "/api/v1"
HOJE = date(2026, 10, 14)


@pytest.fixture(autouse=True)
def _hoje(monkeypatch):
    from app.routers import visao_geral as rota
    monkeypatch.setattr(rota, "hoje_br", lambda: HOJE)


def _get(cliente, eid, **params):
    return cliente.get(f"{API}/escolas/{eid}/atividade-semanal", params=params)


def _cenario(db, escola_completa, *, coleta_elefante=datetime(2026, 10, 14, 3, 10)):
    """Semanas: 28/09–04/10, 05/10–11/10 e 12/10–18/10 (a corrente)."""
    eid = escola_completa["escola"].id
    a, b, c = (x.id for x in escola_completa["alunos"])
    _leitura(db, eid, a, "Livro Ficticio S1", datetime(2026, 9, 29, 10, 0), 5)
    _leitura(db, eid, c, "Livro Ficticio S2", datetime(2026, 10, 7, 10, 0), 5)
    relido = _leitura(db, eid, b, "Livro Ficticio Relido", datetime(2026, 8, 1, 10, 0), 5)
    _evento(db, eid, b, relido, datetime(2026, 10, 13, 10, 0))   # releitura na S3
    if coleta_elefante is not None:
        _coleta_elefante(db, eid, a, coleta_elefante)
    for quando, va, vb in ((datetime(2026, 9, 27, 3, 10), 1, 5),
                           (datetime(2026, 10, 4, 3, 10), 10, 5),
                           (datetime(2026, 10, 11, 3, 10), 10, 8)):
        _matific(db, eid, a, quando, va)
        _matific(db, eid, b, quando, vb)
    db.commit()
    return eid


def test_contrato_e_as_tres_semanas(cliente, db, escola_completa):
    eid = _cenario(db, escola_completa)
    r = _get(cliente, eid, semanas=3)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["denominador"] == 3
    assert corpo["leitura_contratado"] is True and corpo["matematica_contratado"] is True
    assert "lacuna" in corpo["observacao"] and "3 alunos" in corpo["observacao"]
    assert corpo["semanas"] == [
        # S1: A leu; no Matific A ganhou 9 e B ficou em 5 (ganho 0 não conta).
        {"inicio": "2026-09-28", "fim": "2026-10-04", "leitura_alunos": 1,
         "leitura_pct": 33.3, "matematica_alunos": 1, "matematica_pct": 33.3},
        # S2: C leu; no Matific só B ganhou (A ficou em 10).
        {"inicio": "2026-10-05", "fim": "2026-10-11", "leitura_alunos": 1,
         "leitura_pct": 33.3, "matematica_alunos": 1, "matematica_pct": 33.3},
        # S3 (corrente): B releu; nenhuma coleta do Matific ainda → lacuna.
        {"inicio": "2026-10-12", "fim": "2026-10-18", "leitura_alunos": 1,
         "leitura_pct": 33.3, "matematica_alunos": None, "matematica_pct": None},
    ]


def test_padrao_oito_semanas_de_segunda_a_domingo(cliente, db, escola_completa):
    eid = _cenario(db, escola_completa)
    semanas = _get(cliente, eid).json()["semanas"]
    assert len(semanas) == 8
    inicios = [date.fromisoformat(s["inicio"]) for s in semanas]
    assert inicios == sorted(inicios)
    for s in semanas:
        ini, fim = date.fromisoformat(s["inicio"]), date.fromisoformat(s["fim"])
        assert ini.weekday() == 0 and (fim - ini).days == 6
    assert date.fromisoformat(semanas[-1]["inicio"]) <= HOJE <= date.fromisoformat(
        semanas[-1]["fim"])
    assert [s["inicio"] for s in semanas[-3:]] == ["2026-09-28", "2026-10-05",
                                                   "2026-10-12"]
    # Antes de qualquer coleta do Matific: lacuna, nunca 0.
    assert all(s["matematica_alunos"] is None for s in semanas[:5])
    # Na Leitura, semana antiga já VISTA por coleta posterior tem número (0 aqui).
    assert all(s["leitura_alunos"] == 0 for s in semanas[:5])


def test_semana_depois_da_ultima_coleta_do_elefante_e_lacuna(cliente, db,
                                                             escola_completa):
    """A coleta de 06/10 00h10 mede até 05/10: a semana corrente ainda não foi vista.
    A de 05/10 foi vista só na segunda: lacuna, não 0 (coletada só em parte)."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0].id
    _leitura(db, eid, a, "Livro Ficticio Antigo", datetime(2026, 9, 29, 10, 0), 5)
    _coleta_elefante(db, eid, a, datetime(2026, 10, 6, 3, 10))
    db.commit()
    semanas = _get(cliente, eid, semanas=3).json()["semanas"]
    assert [s["leitura_alunos"] for s in semanas] == [1, None, None]
    assert semanas[1]["leitura_pct"] is None
    assert semanas[2]["leitura_pct"] is None


def test_semana_em_que_a_coleta_do_elefante_parou_no_meio_e_lacuna(cliente, db,
                                                                  escola_completa):
    """A coleta de 08/10 00h10 mede até 07/10: a semana de 05/10 só foi vista até a
    quarta — 1 leitor ali não é o número da semana inteira, é lacuna. A semana de 28/09,
    vista por inteiro, segue com número."""
    eid = escola_completa["escola"].id
    a, _b, c = (x.id for x in escola_completa["alunos"])
    _leitura(db, eid, a, "Livro Ficticio S1", datetime(2026, 9, 29, 10, 0), 5)
    _leitura(db, eid, c, "Livro Ficticio S2", datetime(2026, 10, 6, 10, 0), 5)
    _coleta_elefante(db, eid, a, datetime(2026, 10, 8, 3, 10))
    db.commit()
    semanas = _get(cliente, eid, semanas=3).json()["semanas"]
    assert [s["leitura_alunos"] for s in semanas] == [1, None, None]
    assert semanas[1]["leitura_pct"] is None


def test_semana_fechada_vista_ate_o_domingo_tem_numero(cliente, db, escola_completa):
    """A coleta da segunda 0h10 (12/10 03h10 UTC) mede até o domingo 11/10: a semana de
    05/10 está vista por inteiro, e a corrente ainda não foi vista. Com a coleta de
    13/10 (mede até 12/10), a corrente segue com o número "em curso" mesmo sem a terça
    (o rodapé do gráfico diz que ela ainda pode crescer)."""
    eid = escola_completa["escola"].id
    a, b, c = (x.id for x in escola_completa["alunos"])
    _leitura(db, eid, c, "Livro Ficticio S2", datetime(2026, 10, 11, 18, 0), 5)
    _coleta_elefante(db, eid, a, datetime(2026, 10, 12, 3, 10))
    db.commit()
    semanas = _get(cliente, eid, semanas=3).json()["semanas"]
    assert [s["leitura_alunos"] for s in semanas] == [0, 1, None]

    _leitura(db, eid, b, "Livro Ficticio S3", datetime(2026, 10, 12, 9, 0), 5)
    _coleta_elefante(db, eid, a, datetime(2026, 10, 13, 3, 10))
    db.commit()
    semanas = _get(cliente, eid, semanas=3).json()["semanas"]
    assert [s["leitura_alunos"] for s in semanas] == [0, 1, 1]


def test_ganho_de_semana_sem_coleta_nao_migra_para_a_seguinte(cliente, db,
                                                              escola_completa):
    """Retratos 21/09 (5), 28/09 (5) e 12/10 03h10 UTC (9): as 4 atividades foram entre
    28/09 e 11/10, mas sem coleta na semana de 05/10 a base da semana de 12/10 seria a
    de 28/09 — contar o aluno ali atribuía a ela a atividade da lacuna. Também a semana
    de 28/09: a base (21/09) é de uma semana antes da segunda-feira, e o ganho dela
    mede a semana ANTERIOR. Sem base da borda, o aluno não está medido: lacuna."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0].id
    for quando, valor in ((datetime(2026, 9, 21, 3, 10), 5),
                          (datetime(2026, 9, 28, 3, 10), 5),
                          (datetime(2026, 10, 12, 3, 10), 9)):
        _matific(db, eid, a, quando, valor)
    db.commit()
    semanas = _get(cliente, eid, semanas=3).json()["semanas"]
    assert [s["inicio"] for s in semanas] == ["2026-09-28", "2026-10-05", "2026-10-12"]
    assert [s["matematica_alunos"] for s in semanas] == [None, None, None]
    assert all(s["matematica_pct"] is None for s in semanas)


def test_base_antiga_de_um_aluno_nao_apaga_a_semana_dos_outros(cliente, db,
                                                               escola_completa):
    """Na semana de 12/10, A (base 28/09) fica fora da conta; B (base 11/10 00h10, a
    borda) é medido e ganhou: 1 aluno, não 2."""
    eid = escola_completa["escola"].id
    a, b, _c = (x.id for x in escola_completa["alunos"])
    _matific(db, eid, a, datetime(2026, 9, 28, 3, 10), 5)
    _matific(db, eid, a, datetime(2026, 10, 12, 3, 10), 9)
    _matific(db, eid, b, datetime(2026, 10, 11, 3, 10), 3)
    _matific(db, eid, b, datetime(2026, 10, 13, 3, 10), 5)
    db.commit()
    s3 = _get(cliente, eid, semanas=3).json()["semanas"][2]
    assert s3["inicio"] == "2026-10-12"
    assert s3["matematica_alunos"] == 1 and s3["matematica_pct"] == 33.3


def test_base_nula_na_abertura_do_ano_letivo_segue_medida():
    """Semana de 29/12/2025 a 04/01/2026 no ano letivo 2026: sem retrato do ano antes,
    a base é o zero do contador (01/01) — medida, não base antiga."""
    serie = [SimpleNamespace(id=1, data_referencia=datetime(2026, 1, 2, 3, 10),
                             atividades=3, estrelas=6)]
    dados = svc._SeriesMatific(series={1: serie},
                               chaves={1: [matific_destaque._data(s) for s in serie]},
                               ultima_coleta=None)
    janela = svc.rp.Janela(preset="semana", inicio=datetime(2025, 12, 29),
                           fim=datetime(2026, 1, 4, 23, 59, 59, 999999),
                           rotulo="semana")
    assert svc._ativos_matific_semana(dados, {1: {}, 2: {}}, janela, 2026) == 1


def test_escola_sem_nenhum_dado_e_toda_lacuna(cliente, db, escola_completa):
    corpo = _get(cliente, escola_completa["escola"].id, semanas=4).json()
    assert corpo["denominador"] == 3
    for s in corpo["semanas"]:
        assert s["leitura_alunos"] is None and s["matematica_alunos"] is None
        assert s["leitura_pct"] is None and s["matematica_pct"] is None


def test_semana_com_coleta_e_sem_ganho_e_zero_nao_lacuna(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    a, b, _c = (x.id for x in escola_completa["alunos"])
    for aluno, valor in ((a, 10), (b, 5)):
        _matific(db, eid, aluno, datetime(2026, 10, 4, 3, 10), valor)
        _matific(db, eid, aluno, datetime(2026, 10, 11, 3, 10), valor)
    db.commit()
    s2 = _get(cliente, eid, semanas=2).json()["semanas"][0]
    assert s2["inicio"] == "2026-10-05"
    assert s2["matematica_alunos"] == 0 and s2["matematica_pct"] == 0.0


def test_uma_coleta_so_na_semana_e_lacuna(cliente, db, escola_completa):
    """Primeira coleta do aluno caindo na semana, sem nada antes: não mede ganho."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0].id
    _matific(db, eid, a, datetime(2026, 10, 7, 3, 10), 30)
    db.commit()
    s2 = _get(cliente, eid, semanas=2).json()["semanas"][0]
    assert s2["matematica_alunos"] is None


def test_mesma_regra_da_visao_geral(cliente, db, escola_completa):
    """A semana corrente do gráfico e a Visão Geral de "esta semana" contam os mesmos
    leitores."""
    eid = _cenario(db, escola_completa)
    semanal = _get(cliente, eid, semanas=1).json()["semanas"][0]
    visao = cliente.get(f"{API}/escolas/{eid}/visao-geral",
                        params={"periodo": "semana"}).json()
    assert visao["periodo"]["inicio"] == semanal["inicio"]
    assert semanal["leitura_alunos"] == visao["alunos"]["ativos_leitura"] == 1


def test_modulo_fora_do_plano(cliente, db, escola_completa):
    eid = _cenario(db, escola_completa)
    escola = escola_completa["escola"]
    rede = Rede(nome="REDE FICTICIA SO LEITURA")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(ModuloRede(rede_id=rede.id, modulo="matematica", ativo=False))
    db.commit()
    corpo = _get(cliente, eid, semanas=3).json()
    assert corpo["matematica_contratado"] is False and corpo["leitura_contratado"] is True
    assert all(s["matematica_alunos"] is None and s["matematica_pct"] is None
               for s in corpo["semanas"])
    assert [s["leitura_alunos"] for s in corpo["semanas"]] == [1, 1, 1]


@pytest.mark.parametrize("semanas", [0, 27, -1])
def test_semanas_fora_da_faixa_e_422(cliente, db, escola_completa, semanas):
    assert _get(cliente, escola_completa["escola"].id, semanas=semanas).status_code == 422


def test_vinte_e_seis_semanas_cabem(cliente, db, escola_completa):
    eid = _cenario(db, escola_completa)
    semanas = _get(cliente, eid, semanas=26).json()["semanas"]
    assert len(semanas) == 26 and semanas[-1]["inicio"] == "2026-10-12"


def test_professor_ve_o_denominador_das_turmas_dele(db, escola_completa):
    eid = _cenario(db, escola_completa)
    outra = Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(outra)
    db.flush()
    d = Aluno(escola_id=eid, nome="Crianca Ficticia da Outra Turma")
    db.add(d)
    db.flush()
    db.add(Matricula(escola_id=eid, aluno_id=d.id, turma_id=outra.id, ano_letivo=2026))
    prof = Professor(escola_id=eid, nome="Prof Ficticio", email="prof.sem@teste.local")
    db.add(prof)
    db.flush()
    outra.professor_id = prof.id
    db.add(Usuario(escola_id=eid, nome="Prof Ficticio", email="prof.sem@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()
    corpo = _get(_login("prof.sem@teste.local"), eid, semanas=3).json()
    assert corpo["denominador"] == 1
    assert "das suas turmas" in corpo["observacao"]
    # A turma dela nunca teve dado: lacuna em tudo (o dado das outras turmas não entra).
    assert all(s["leitura_alunos"] is None and s["matematica_alunos"] is None
               for s in corpo["semanas"])


def test_secretaria_e_outra_escola_sao_negadas(db, escola_completa, cliente):
    from app.models import Escola

    eid = escola_completa["escola"].id
    rede = Rede(nome="REDE FICTICIA")
    db.add(rede)
    db.flush()
    escola_completa["escola"].rede_id = rede.id
    db.add(Usuario(escola_id=eid, rede_id=rede.id, nome="Secretaria",
                   email="sec.sem@teste.local", senha_hash=hash_senha("s3nh4"),
                   cargo="coordenador"))
    outra = Escola(nome="OUTRA ESCOLA FICTICIA", ano_letivo_ativo=2026)
    db.add(outra)
    db.commit()
    r = _get(_login("sec.sem@teste.local"), eid)
    assert r.status_code == 403 and "Secretaria" in r.json()["detail"]
    assert _get(cliente, outra.id).status_code == 403
    assert TestClient(app).get(
        f"{API}/escolas/{eid}/atividade-semanal").status_code == 401


# ---------------------------------------------------------------------------
# O recorte da série dá o MESMO ganho da regra oficial (a otimização é segura)
# ---------------------------------------------------------------------------
def test_recorte_da_serie_e_identico_a_regra_oficial_sobre_a_serie_toda():
    sorteio = random.Random(20261014)
    ano = 2026
    for _ in range(60):
        momento = datetime(2025, 12, 1, 3, 10)
        acumulado, serie = 0, []
        for i in range(sorteio.randint(0, 40)):
            momento += timedelta(hours=sorteio.choice([0, 6, 24, 24, 48, 24 * 9]))
            acumulado = max(0, acumulado + sorteio.choice([0, 0, 1, 3, 7, -2]))
            if momento.month == 1 and momento.day == 1:
                acumulado = 0
            serie.append(SimpleNamespace(id=i, data_referencia=momento,
                                         atividades=acumulado,
                                         estrelas=acumulado * sorteio.randint(0, 6)))
        chaves = [matific_destaque._data(s) for s in serie]
        for _janela in range(25):
            dia = date(2025, 12, 20) + timedelta(days=sorteio.randint(0, 120))
            ini = datetime.combine(dia, datetime.min.time())
            fim = ini + timedelta(days=sorteio.choice([0, 6, 13, 40]),
                                  hours=23, minutes=59, seconds=59, microseconds=999999)
            esperado = matific_destaque.ganho_no_periodo(serie, ini, fim, ano)
            obtido = svc._ganho(serie, chaves, ini, fim, ano)
            assert obtido == esperado, (ini, fim, [(s.data_referencia, s.atividades)
                                                   for s in serie])
