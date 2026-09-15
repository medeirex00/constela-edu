"""Filtro de TURNO nos rankings (itens 7/8): ``?turno=`` em GET /ranking,
/nao-aferidos, /ranking/leitura e /ranking/matematica.

Semântica ÚNICA (a mesma de /ranking-evolucao e das premiações por turno):
  * ausente = todos (nada muda: posição carimbada da escola inteira);
  * ``''`` = turmas SEM turno cadastrado ("Sem turno");
  * senão o turno exato de ``Turma.turno`` (valor do banco, nunca hardcoded).

O turno define QUEM compete, nunca a nota (régua única da escola). Em /ranking
o recorte é RENUMERADO 1..N (como para o professor) e `n_aferidos` passa a ser
o do conjunto filtrado. Turno inexistente → lista vazia, sem erro.
"""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno,
    Importacao,
    Matricula,
    Professor,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.services import scoring

API = "/api/v1"
QUANDO = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)


def _turma(db, escola_id, nome, ano_escolar, turno):
    t = Turma(escola_id=escola_id, nome=nome, ano_escolar=ano_escolar,
              ano_letivo=2026, turno=turno, status="ativa")
    db.add(t)
    db.flush()
    return t


def _aluno(db, escola_id, turma, nome):
    a = Aluno(escola_id=escola_id, nome=nome, status="ativo")
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=escola_id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
    return a


def _cenario(db, escola_completa):
    """Manhã: M1 (forte), M2 (fraco), M3 (SEM dado). Tarde: T1, T2. Sem turno
    (turma da fixture, turno=None): Ana, João e Sofia (SEM dado).

    Os perfis são escalonados em TODOS os indicadores (livros, dificuldade,
    tempo, questões; atividades, estrelas, média) para a ordem na escola ser
    M1 > T1 > Ana > M2 > … sem depender de detalhe da fórmula."""
    esc = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    t_m = _turma(db, esc.id, "2º Ano M", "2º Ano", "manha")
    t_t = _turma(db, esc.id, "4º Ano T", "4º Ano", "tarde")
    m1 = _aluno(db, esc.id, t_m, "M1 Forte")
    m2 = _aluno(db, esc.id, t_m, "M2 Fraco")
    m3 = _aluno(db, esc.id, t_m, "M3 Sem Dado")
    t1 = _aluno(db, esc.id, t_t, "T1 Medio Alto")
    t2 = _aluno(db, esc.id, t_t, "T2 Fraco")
    # (livros por nível, tempo, tentativas, acertos, atividades, estrelas)
    dados = {
        m1: ({"H": 20}, 300, 40, 30, 50, 150),
        t1: ({"J": 15}, 250, 30, 20, 40, 100),
        ana: ({"E": 10}, 150, 15, 10, 30, 70),
        m2: ({"D": 5}, 60, 6, 3, 8, 16),
        t2: ({"C": 4}, 50, 5, 2, 10, 15),
        joao: ({"AA": 2}, 20, 2, 1, 5, 8),
    }
    for aluno, (pn, tempo, tent, acert, ativ, estrelas) in dados.items():
        db.add(SnapshotElefante(
            escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
            data_referencia=QUANDO, livros_unicos=sum(pn.values()),
            livros_por_nivel=dict(pn), tempo_leitura_min=tempo,
            questoes_tentativas=tent, questoes_acertos=acert))
        db.add(SnapshotMatific(
            escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
            data_referencia=QUANDO, atividades=ativ, estrelas=estrelas,
            pontuacao_media=round(estrelas / ativ, 2)))
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    return {
        "escola": esc, "manha": t_m, "tarde": t_t,
        "m1": m1, "m2": m2, "m3": m3, "t1": t1, "t2": t2,
        "ana": ana, "joao": joao, "sofia": sofia,
        "nomes_manha": {m1.nome, m2.nome},
        "nomes_tarde": {t1.nome, t2.nome},
        "nomes_sem_turno": {ana.nome, joao.nome},
    }


def _ranking(cliente, escola_id, **params):
    r = cliente.get(f"{API}/escolas/{escola_id}/ranking", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _nomes(itens):
    return [i["nome"] for i in itens]


def _posicoes(itens):
    return [i["posicao"] for i in itens]


# --------------------------------------------------------------------------
# GET /ranking
# --------------------------------------------------------------------------

def test_sem_turno_mantem_a_posicao_carimbada_da_escola(cliente, db, escola_completa):
    c = _cenario(db, escola_completa)
    itens = _ranking(cliente, c["escola"].id, dimensao="leitura")
    # 6 aferidos (M3 e Sofia não têm snapshot): posições da escola inteira.
    assert _posicoes(itens) == list(range(1, 7))
    assert {i["n_aferidos"] for i in itens} == {6}
    assert itens[0]["nome"] == "M1 Forte"
    por_nome = {i["nome"]: i["posicao"] for i in itens}
    # M2 é batido por M1, T1 e Ana em todos os indicadores: nunca é 1º nem 2º.
    assert por_nome["M2 Fraco"] >= 3
    assert por_nome["T2 Fraco"] >= 3


def test_turno_manha_recorta_e_renumera(cliente, db, escola_completa):
    c = _cenario(db, escola_completa)
    todos = _ranking(cliente, c["escola"].id, dimensao="leitura")
    manha = _ranking(cliente, c["escola"].id, dimensao="leitura", turno="manha")
    assert set(_nomes(manha)) == c["nomes_manha"]
    assert _posicoes(manha) == [1, 2]                      # renumerado no recorte
    assert {i["n_aferidos"] for i in manha} == {2}         # denominador do recorte
    # A ordem relativa é a da escola (a nota não muda; só quem compete).
    ordem_escola = [n for n in _nomes(todos) if n in c["nomes_manha"]]
    assert _nomes(manha) == ordem_escola == ["M1 Forte", "M2 Fraco"]
    notas_todos = {i["nome"]: i["nota"] for i in todos}
    assert all(i["nota"] == notas_todos[i["nome"]] for i in manha)


def test_turno_tarde_recorta_e_renumera(cliente, db, escola_completa):
    c = _cenario(db, escola_completa)
    tarde = _ranking(cliente, c["escola"].id, dimensao="matematica", turno="tarde")
    assert set(_nomes(tarde)) == c["nomes_tarde"]
    assert _posicoes(tarde) == [1, 2]
    assert {i["n_aferidos"] for i in tarde} == {2}
    assert _nomes(tarde) == ["T1 Medio Alto", "T2 Fraco"]


def test_turno_vazio_isola_as_turmas_sem_turno(cliente, db, escola_completa):
    c = _cenario(db, escola_completa)
    sem = _ranking(cliente, c["escola"].id, dimensao="leitura", turno="")
    assert set(_nomes(sem)) == c["nomes_sem_turno"]
    assert _posicoes(sem) == [1, 2]
    assert {i["n_aferidos"] for i in sem} == {2}


def test_turno_inexistente_devolve_lista_vazia(cliente, db, escola_completa):
    c = _cenario(db, escola_completa)
    assert _ranking(cliente, c["escola"].id, dimensao="leitura", turno="noite") == []
    assert _ranking(cliente, c["escola"].id, turno="integral") == []


def test_ranking_legado_sem_dimensao_tambem_filtra_por_turno(cliente, db, escola_completa):
    """O LEGADO ordena por `Nota.posicao` sobre quem TEM Nota no ano — e o motor
    grava Nota para TODA matrícula ativa, inclusive a de quem não foi aferido em
    nenhuma dimensão (nota_geral 0, no fim). Por isso M3 (sem dado) ENTRA no
    legado, ao contrário do ranking por dimensão."""
    c = _cenario(db, escola_completa)
    legado = _ranking(cliente, c["escola"].id, turno="manha")
    assert _nomes(legado) == ["M1 Forte", "M2 Fraco", "M3 Sem Dado"]
    assert _posicoes(legado) == [1, 2, 3]                  # renumerado no recorte
    # Recortado → denominador do recorte carimbado também no legado.
    assert [i["n_aferidos"] for i in legado] == [len(legado)] * len(legado)
    assert all(i["dimensao"] is None for i in legado)

    sem = _ranking(cliente, c["escola"].id, turno="")
    assert set(_nomes(sem)) == c["nomes_sem_turno"] | {"Sofia Almeida Duarte"}
    assert _posicoes(sem) == [1, 2, 3]
    assert {i["n_aferidos"] for i in sem} == {3}


def test_ranking_legado_sem_turno_mantem_contrato_antigo(cliente, db, escola_completa):
    """Sem recorte o legado não muda: posição carimbada da escola inteira e
    `n_aferidos` ausente (None) — contrato dos clientes antigos."""
    c = _cenario(db, escola_completa)
    todos = _ranking(cliente, c["escola"].id)
    assert set(_nomes(todos)) == (c["nomes_manha"] | c["nomes_tarde"] | c["nomes_sem_turno"]
                                  | {"M3 Sem Dado", "Sofia Almeida Duarte"})
    assert _posicoes(todos) == list(range(1, 9))
    assert {i["n_aferidos"] for i in todos} == {None}


def test_turno_combina_com_turma_e_serie(cliente, db, escola_completa):
    c = _cenario(db, escola_completa)
    # turno certo + turma certa: recorte normal; turno errado para a turma: vazio.
    ok = _ranking(cliente, c["escola"].id, dimensao="leitura", turno="manha",
                  turma_id=c["manha"].id)
    assert set(_nomes(ok)) == c["nomes_manha"]
    assert _ranking(cliente, c["escola"].id, dimensao="leitura", turno="tarde",
                    turma_id=c["manha"].id) == []
    assert _ranking(cliente, c["escola"].id, dimensao="leitura", turno="tarde",
                    ano_escolar="2º Ano") == []


# --------------------------------------------------------------------------
# GET /nao-aferidos
# --------------------------------------------------------------------------

def _nao_aferidos(cliente, escola_id, **params):
    r = cliente.get(f"{API}/escolas/{escola_id}/nao-aferidos", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_nao_aferidos_filtra_por_turno(cliente, db, escola_completa):
    c = _cenario(db, escola_completa)
    eid = c["escola"].id
    todos = _nao_aferidos(cliente, eid)
    assert todos["total_alunos"] == 8
    assert {a["nome"] for a in todos["sem_nenhuma"]} == {"M3 Sem Dado", "Sofia Almeida Duarte"}

    manha = _nao_aferidos(cliente, eid, turno="manha")
    assert manha["total_alunos"] == 3
    assert [a["nome"] for a in manha["sem_nenhuma"]] == ["M3 Sem Dado"]
    for dim in manha["dimensoes"]:
        assert [a["nome"] for a in dim["alunos"]] == ["M3 Sem Dado"]
        assert dim["n_aferidos"] == 2 and dim["total"] == 3

    tarde = _nao_aferidos(cliente, eid, turno="tarde")
    assert tarde["total_alunos"] == 2 and tarde["sem_nenhuma"] == []
    assert all(dim["alunos"] == [] and dim["n_aferidos"] == 2 for dim in tarde["dimensoes"])

    sem = _nao_aferidos(cliente, eid, turno="")
    assert sem["total_alunos"] == 3
    assert [a["nome"] for a in sem["sem_nenhuma"]] == ["Sofia Almeida Duarte"]

    assert _nao_aferidos(cliente, eid, turno="noite")["total_alunos"] == 0


# --------------------------------------------------------------------------
# GET /ranking/leitura e /ranking/matematica (volume no período)
# --------------------------------------------------------------------------

def _leitura(cliente, escola_id, **params):
    r = cliente.get(f"{API}/escolas/{escola_id}/ranking/leitura",
                    params={"periodo": "tudo", **params})
    assert r.status_code == 200, r.text
    return r.json()


def _matematica(cliente, escola_id, **params):
    r = cliente.get(f"{API}/escolas/{escola_id}/ranking/matematica",
                    params={"periodo": "tudo", **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_ranking_leitura_periodo_filtra_por_turno(cliente, db, escola_completa):
    c = _cenario(db, escola_completa)
    eid = c["escola"].id
    assert set(_nomes(_leitura(cliente, eid))) == (
        c["nomes_manha"] | c["nomes_tarde"] | c["nomes_sem_turno"])
    manha = _leitura(cliente, eid, turno="manha")
    assert set(_nomes(manha)) == c["nomes_manha"]
    assert _posicoes(manha) == [1, 2]
    assert set(_nomes(_leitura(cliente, eid, turno=""))) == c["nomes_sem_turno"]
    assert _leitura(cliente, eid, turno="noite") == []

    # Leituras ITEMIZADAS (com data) importadas para um aluno de cada turno:
    # o recorte por turno vale também para a consulta por livro.
    for aluno, titulo in ((c["m1"], "Livro da Manhã"), (c["t1"], "Livro da Tarde")):
        r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
            "plataforma": "elefante", "formato": "leituras", "tipo": "texto",
            "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id,
                        "dados": {"livro": titulo, "nivel": "H",
                                  "data": "2026-03-05T09:00:00"}}]})
        assert r.status_code == 200, r.text
    manha = _leitura(cliente, eid, turno="manha")
    assert set(_nomes(manha)) == c["nomes_manha"]
    assert next(i for i in manha if i["nome"] == "M1 Forte")["livros"] >= 1
    assert "T1 Medio Alto" not in _nomes(manha)
    assert "M1 Forte" not in _nomes(_leitura(cliente, eid, turno="tarde"))


def test_ranking_matematica_periodo_filtra_por_turno(cliente, db, escola_completa):
    c = _cenario(db, escola_completa)
    eid = c["escola"].id
    assert set(_nomes(_matematica(cliente, eid))) == (
        c["nomes_manha"] | c["nomes_tarde"] | c["nomes_sem_turno"])
    tarde = _matematica(cliente, eid, turno="tarde")
    assert set(_nomes(tarde)) == c["nomes_tarde"]
    assert _posicoes(tarde) == [1, 2]
    assert set(_nomes(_matematica(cliente, eid, turno=""))) == c["nomes_sem_turno"]
    assert _matematica(cliente, eid, turno="integral") == []


# --------------------------------------------------------------------------
# Professor: continua renumerado (com e sem turno)
# --------------------------------------------------------------------------

def test_professor_continua_renumerado(cliente, db, escola_completa):
    c = _cenario(db, escola_completa)
    esc = c["escola"]
    prof = Professor(escola_id=esc.id, nome="Prof Manhã", email="prof@turno.local")
    db.add(prof)
    db.flush()
    c["manha"].professor_id = prof.id
    db.add(Usuario(escola_id=esc.id, nome="Prof Manhã", email="prof@turno.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()
    pc = TestClient(app)
    r = pc.post(f"{API}/auth/login", data={"username": "prof@turno.local", "password": "s3nh4"})
    assert r.status_code == 200, r.text
    pc.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    meus = _ranking(pc, esc.id, dimensao="leitura")
    assert set(_nomes(meus)) == c["nomes_manha"]
    assert _posicoes(meus) == [1, 2] and {i["n_aferidos"] for i in meus} == {2}
    # Com o turno dele: idêntico; com outro turno: nada (não vaza turma alheia).
    assert _ranking(pc, esc.id, dimensao="leitura", turno="manha") == meus
    assert _ranking(pc, esc.id, dimensao="leitura", turno="tarde") == []

    # LEGADO do professor (recorte pelas turmas dele, sem turno): renumerado e
    # com o denominador do recorte carimbado (M3 sem dado entra no legado).
    legado = _ranking(pc, esc.id)
    assert _nomes(legado) == ["M1 Forte", "M2 Fraco", "M3 Sem Dado"]
    assert _posicoes(legado) == [1, 2, 3]
    assert {i["n_aferidos"] for i in legado} == {3}


# --------------------------------------------------------------------------
# Chamada DIRETA em Python (sem passar `turno`) = "todos"
# --------------------------------------------------------------------------

def test_chamada_direta_sem_turno_significa_todos(db, escola_completa):
    """Quem chama a função da rota diretamente em Python (testes, consumidores
    internos) sem passar ``turno`` recebe o sentinela ``Query(None)`` do FastAPI
    no lugar do default. Ele tem de significar "todos" — jamais virar parâmetro
    SQL (regressão vista em chamadas diretas a ``nao_aferidos``)."""
    from app.routers import rankings as r_rankings

    c = _cenario(db, escola_completa)
    admin = escola_completa["admin"]
    faltantes = r_rankings.nao_aferidos(escola_id=c["escola"].id, turma_id=None,
                                        ano_escolar=None, db=db, usuario=admin)
    assert faltantes.total_alunos == 8
    itens = r_rankings.ranking_geral(escola_id=c["escola"].id, turma_id=None,
                                     ano_escolar=None, dimensao="leitura",
                                     db=db, usuario=admin)
    assert [i.posicao for i in itens] == list(range(1, 7))   # sem recorte: carimbada
    assert {i.n_aferidos for i in itens} == {6}
