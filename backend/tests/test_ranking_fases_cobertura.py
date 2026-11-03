"""AS FASES NÃO CONCORREM — em TODO ranking, não só nos que já tinham o corte.

Regra (``services.elegibilidade``): ranking e premiação são do 1º ao 5º ano. As
turmas de Educação Infantil (1ª/2ª Fase) que a Lista Piloto traz junto não
concorrem. O motor já tira a Fase da população, mas a Nota ANTIGA dela continua
no banco (o recálculo não apaga linha de quem saiu) e os retratos dela também —
cada leitor precisa cortar na LEITURA.

O PR #36 fechou os rankings por período, as médias e o telão. Este arquivo
cobre, num cenário só, as superfícies de ranking de ALUNO da escola — inclusive
a que ainda vazava (a Evolução da gestão e do professor) — e o recorte por série.
O ranking de turmas tem o seu teste em ``test_ranking_turmas.py``. A criança da Fase tem o MAIOR volume de tudo: se o corte
falhar em qualquer rota, ela aparece em 1º.
"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno,
    Importacao,
    Leitura,
    Livro,
    Matricula,
    Nota,
    Professor,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.services import scoring

API = "/api/v1"


def _turma(db, escola, nome, ano_escolar, turno="manha"):
    t = Turma(escola_id=escola.id, nome=nome, ano_escolar=ano_escolar,
              ano_letivo=escola.ano_letivo_ativo, turno=turno, status="ativa")
    db.add(t)
    db.flush()
    return t


def _aluno(db, escola, turma, nome):
    a = Aluno(escola_id=escola.id, nome=nome, status="ativo", da_lista_piloto=True)
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                     ano_letivo=turma.ano_letivo))
    db.flush()
    return a


def _dados(db, escola, imp, aluno, livros_catalogo, escala):
    """Dois retratos de cada plataforma DENTRO da janela da evolução (crescimento
    real), mais leituras datadas — volume proporcional a ``escala``."""
    agora = datetime.now().replace(microsecond=0)
    for dias, fator in ((20, 1), (2, 2)):
        quando = agora - timedelta(days=dias)
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=imp.id, data_referencia=quando,
                               atividades=5 * escala * fator,
                               estrelas=12 * escala * fator, pontuacao_media=2.4))
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                                importacao_id=imp.id, data_referencia=quando,
                                livros_unicos=escala * fator,
                                tempo_leitura_min=15 * escala * fator,
                                livros_por_nivel={"D": escala * fator}))
    for i in range(min(escala, len(livros_catalogo))):
        db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id,
                       livro_id=livros_catalogo[i].id,
                       data=agora - timedelta(days=5, hours=i),
                       tempo_leitura_min=20, nivel_codigo="D"))


@pytest.fixture()
def cenario(db, escola_completa):
    escola = escola_completa["escola"]
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    livros = [Livro(escola_id=escola.id, titulo=f"Livro Teste {i}", nivel_codigo="D")
              for i in range(12)]
    db.add_all(livros)
    db.flush()

    fund = _turma(db, escola, "4º Ano Teste", "4º Ano")
    fase = _turma(db, escola, "1ª Fase Teste", "1ª Fase")
    fase2 = _turma(db, escola, "2ª Fase Teste", "2ª Fase", turno="tarde")
    do_fund = [_aluno(db, escola, fund, f"Aluna Teste {letra}") for letra in "ABC"]
    da_fase = _aluno(db, escola, fase, "Crianca Fase Teste")
    da_fase2 = _aluno(db, escola, fase2, "Crianca Segunda Fase Teste")
    for i, aluno in enumerate(do_fund, start=1):
        _dados(db, escola, imp, aluno, livros, escala=i)
    # A Fase com o MAIOR volume de tudo: se algum corte faltar, ela é a 1ª.
    _dados(db, escola, imp, da_fase, livros, escala=10)
    _dados(db, escola, imp, da_fase2, livros, escala=9)
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    # A Nota CONGELADA da Fase (de antes da regra), carimbada em 1º em tudo —
    # o recálculo não a apaga, só deixa de atualizá-la.
    for crianca in (da_fase, da_fase2):
        nota = db.query(Nota).filter_by(aluno_id=crianca.id).one_or_none()
        if nota is None:
            nota = Nota(escola_id=escola.id, aluno_id=crianca.id, ano_letivo=2026)
            db.add(nota)
        nota.nota_geral = nota.nota_elefante = nota.nota_matific = 99.0
        nota.posicao = nota.posicao_leitura = nota.posicao_matematica = 1
        nota.aferido_leitura = nota.aferido_matematica = True
    db.commit()
    return {"escola": escola, "fund": fund, "fase": fase, "fase2": fase2,
            "do_fund": {a.id for a in do_fund},
            "fases": {da_fase.id, da_fase2.id}}


def _ids(resposta, chave="aluno_id"):
    assert resposta.status_code == 200, resposta.text
    return [item[chave] for item in resposta.json()]


def _sem_fase_e_sem_buraco(itens, cenario, campo_posicao="posicao"):
    ids = [i["aluno_id"] for i in itens]
    assert not set(ids) & cenario["fases"], "uma criança da Fase entrou no ranking"
    # Posição sem buraco: quem concorre é numerado 1..N, sem a vaga da Fase.
    posicoes = [i[campo_posicao] for i in itens]
    assert posicoes == list(range(1, len(itens) + 1)), posicoes


@pytest.mark.parametrize("params", [
    {}, {"dimensao": "leitura"}, {"dimensao": "matematica"},
    {"turno": "manha"}, {"dimensao": "leitura", "turno": "manha"},
])
def test_ranking_da_escola_geral_e_por_dimensao_sem_a_fase(cliente, cenario, params):
    escola = cenario["escola"]
    r = cliente.get(f"{API}/escolas/{escola.id}/ranking", params=params)
    assert r.status_code == 200, r.text
    itens = r.json()
    assert cenario["do_fund"] <= {i["aluno_id"] for i in itens}
    _sem_fase_e_sem_buraco(itens, cenario)
    if params.get("dimensao"):
        # O denominador também: "1º de N" não pode contar a Fase.
        assert {i["n_aferidos"] for i in itens} == {len(itens)}


@pytest.mark.parametrize("serie,esperado", [("1ª Fase", 0), ("2ª Fase", 0), ("4º Ano", 3)])
def test_ranking_por_serie_nao_abre_a_fase(cliente, cenario, serie, esperado):
    """Pedir a série da Fase explicitamente devolve lista VAZIA (ela não
    concorre); a série do Fundamental continua com os seus alunos."""
    escola = cenario["escola"]
    for params in ({"ano_escolar": serie}, {"ano_escolar": serie, "dimensao": "leitura"}):
        ids = _ids(cliente.get(f"{API}/escolas/{escola.id}/ranking", params=params))
        assert len(ids) == esperado, (params, ids)
        assert not set(ids) & cenario["fases"]
    for rota in ("ranking/leitura", "ranking/matematica"):
        ids = _ids(cliente.get(f"{API}/escolas/{escola.id}/{rota}",
                               params={"ano_escolar": serie}))
        assert not set(ids) & cenario["fases"], rota


def test_ranking_por_turma_da_fase_e_vazio(cliente, cenario):
    escola = cenario["escola"]
    for rota in ("ranking", "ranking/leitura", "ranking/matematica"):
        r = cliente.get(f"{API}/escolas/{escola.id}/{rota}",
                        params={"turma_id": cenario["fase"].id})
        assert _ids(r) == [], rota


@pytest.mark.parametrize("rota,params", [
    ("ranking/leitura", {}),
    ("ranking/leitura", {"periodo": "mes"}),
    ("ranking/matematica", {}),
    ("ranking/matematica", {"periodo": "mes"}),
])
def test_rankings_por_periodo_sem_a_fase(cliente, cenario, rota, params):
    escola = cenario["escola"]
    r = cliente.get(f"{API}/escolas/{escola.id}/{rota}", params=params)
    assert r.status_code == 200, r.text
    _sem_fase_e_sem_buraco(r.json(), cenario)


def test_competicao_de_leitura_por_turno_sem_a_fase(cliente, cenario):
    escola = cenario["escola"]
    r = cliente.get(f"{API}/escolas/{escola.id}/ranking/leitura/turnos")
    assert r.status_code == 200, r.text
    for grupo in r.json():
        _sem_fase_e_sem_buraco(grupo["alunos"], cenario)
    # O turno da tarde só tem a 2ª Fase: não vira um grupo vazio nem um grupo dela.
    assert "tarde" not in {g["turno"] for g in r.json()}


@pytest.mark.parametrize("params", [
    {}, {"dimensao": "leitura"}, {"dimensao": "matematica"},
    {"periodo": "mes"}, {"periodo": "mes", "dimensao": "leitura"},
    {"turno": "tarde"}, {"ano_escolar": "1ª Fase"},
])
def test_ranking_de_evolucao_sem_a_fase(cliente, cenario, params):
    """Era o furo: a Evolução da gestão listava a Fase (o telão já cortava)."""
    escola = cenario["escola"]
    r = cliente.get(f"{API}/escolas/{escola.id}/ranking-evolucao", params=params)
    assert r.status_code == 200, r.text
    itens = r.json()
    _sem_fase_e_sem_buraco(itens, cenario)
    if params.get("dimensao"):
        assert {i["n_aferidos"] for i in itens} <= {len(itens)}
    if params.get("turno") == "tarde" or params.get("ano_escolar") == "1ª Fase":
        assert itens == []
    elif not params.get("dimensao"):
        assert cenario["do_fund"] <= {i["aluno_id"] for i in itens}


def test_evolucao_mantem_a_regua_da_escola_inteira(cliente, db, cenario):
    """O corte é de quem APARECE: a nota de evolução de cada criança do
    Fundamental é a mesma que o serviço calcula sem recorte (a régua continua a
    da escola inteira — a mesma decisão do telão)."""
    from app.services import evolucao as svc_evolucao

    escola = cenario["escola"]
    r = cliente.get(f"{API}/escolas/{escola.id}/ranking-evolucao")
    pela_rota = {i["aluno_id"]: i["nota_evolucao"] for i in r.json()}
    sem_recorte = {i.aluno_id: i.nota_evolucao for i in svc_evolucao.ranking_evolucao(
        db, escola.id, dias=30, base_no_periodo=True)}
    for aluno_id, nota in pela_rota.items():
        assert nota == sem_recorte[aluno_id]


def test_professor_da_fase_e_do_fundamental_ve_so_o_fundamental(db, cenario):
    """Escopo de acesso INALTERADO: a professora das duas turmas continua vendo
    as duas no resto do sistema; no ranking de evolução só concorre o Fundamental."""
    escola = cenario["escola"]
    prof = Professor(escola_id=escola.id, nome="Professora Teste", email="prof@fase.local")
    db.add(prof)
    db.flush()
    cenario["fund"].professor_id = prof.id
    cenario["fase"].professor_id = prof.id
    db.add(Usuario(escola_id=escola.id, nome="Professora Teste", email="prof@fase.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()
    cli = TestClient(app)
    r = cli.post(f"{API}/auth/login", data={"username": "prof@fase.local", "password": "s3nh4"})
    assert r.status_code == 200, r.text
    cli.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    itens = cli.get(f"{API}/escolas/{escola.id}/ranking-evolucao").json()
    assert {i["aluno_id"] for i in itens} == cenario["do_fund"]
    assert [i["posicao"] for i in itens] == [1, 2, 3]
    # A turma da Fase continua sendo DELA (o escopo não mudou): a lista da turma abre.
    r = cli.get(f"{API}/escolas/{escola.id}/turmas/{cenario['fase'].id}/alunos")
    assert r.status_code == 200, r.text


def test_premiacoes_e_top10_sem_a_fase(cliente, cenario):
    escola = cenario["escola"]
    r = cliente.get(f"{API}/escolas/{escola.id}/premiacoes",
                    params={"periodo": "ano_letivo", "limite": 50})
    assert r.status_code == 200, r.text
    for categoria in r.json()["categorias"]:
        assert not {i["aluno_id"] for i in categoria["podio"]} & cenario["fases"], \
            categoria["chave"]
        assert categoria["total"] <= len(cenario["do_fund"]), categoria["chave"]
    top10 = cliente.get(f"{API}/escolas/{escola.id}/dashboard").json()["top10"]
    assert not {i["aluno_id"] for i in top10} & cenario["fases"]
