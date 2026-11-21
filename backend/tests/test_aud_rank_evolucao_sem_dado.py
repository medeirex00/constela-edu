"""AUSÊNCIA NÃO É ZERO também nas listas legadas: a criança sem dado de nenhuma
plataforma não ganha posição (nem medalha) no Ranking de Evolução nem no
Top 10 do painel.

* `evolucao.ranking_evolucao` criava um item para a coorte inteira e dava a
  posição legada (-nota_evolucao, nome, id) a todos: num período sem
  importação (coleta automática desligada), a aba Evolução da web montava um
  pódio em ORDEM ALFABÉTICA com "0,0 de evolução", e o "Gerar certificados"
  pegava esses nomes. O app (`/sincronizacao`) herdava a mesma lista.
* `montar_dashboard` montava o Top 10 com o `_ranking` legado, que inclui quem
  tem Nota sem nenhum `aferido_*`: o Top 5 do Painel (web e app) dava medalha
  e "0,0" a quem nunca abriu plataforma.

O telão já cortava as duas coisas (`publico._com_algum_dado`). Quem TEM dado e
não cresceu continua (zero legítimo); as listas por dimensão não mudam.
Achado RANKINGS-4. Dados fictícios.
"""
from datetime import datetime

from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Importacao, Professor, SnapshotMatific, Turma, Usuario
from app.services import scoring

API = "/api/v1"
OUTUBRO = {"periodo": "personalizado", "inicio": "2026-10-01", "fim": "2026-10-31"}


def _matific(db, esc, aluno, data, atividades, estrelas):
    imp = Importacao(escola_id=esc.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=data, atividades=atividades,
                           estrelas=estrelas, pontuacao_media=3.0))


def test_evolucao_sem_dado_nenhum_nao_tem_posicao(cliente, escola_completa):
    """Escola sem retrato nenhum: ninguém sobe ao pódio em ordem alfabética."""
    esc = escola_completa["escola"]
    r = cliente.get(f"{API}/escolas/{esc.id}/ranking-evolucao", params=OUTUBRO)
    assert r.status_code == 200, r.text
    assert r.json() == [], [(i["posicao"], i["nome"], i["nota_evolucao"]) for i in r.json()]


def test_evolucao_mantem_zero_legitimo_e_renumera_sem_buraco(cliente, db, escola_completa):
    """Ana e Sofia têm Matific (retrato de setembro, não cresceram em outubro);
    João não tem plataforma nenhuma. Ficam Ana e Sofia, 1º e 2º, com 0,0."""
    esc = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    for aluno in (ana, sofia):
        _matific(db, esc, aluno, datetime(2026, 9, 15), 10, 20)
    db.commit()
    r = cliente.get(f"{API}/escolas/{esc.id}/ranking-evolucao", params=OUTUBRO)
    assert r.status_code == 200, r.text
    itens = r.json()
    assert [(i["posicao"], i["aluno_id"], i["nota_evolucao"]) for i in itens] == [
        (1, ana.id, 0.0), (2, sofia.id, 0.0)]
    assert joao.id not in {i["aluno_id"] for i in itens}
    # A lista da dimensão não muda: os mesmos dois, com o mesmo denominador.
    rd = cliente.get(f"{API}/escolas/{esc.id}/ranking-evolucao",
                     params={**OUTUBRO, "dimensao": "matematica"})
    assert [(i["posicao"], i["aluno_id"], i["n_aferidos"]) for i in rd.json()] == [
        (1, ana.id, 2), (2, sofia.id, 2)]


def test_top10_do_painel_sem_crianca_sem_dado(cliente, db, escola_completa):
    esc = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    _matific(db, esc, ana, datetime(2026, 10, 1), 10, 20)
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    top = cliente.get(f"{API}/escolas/{esc.id}/dashboard").json()["top10"]
    assert [(i["posicao"], i["aluno_id"]) for i in top] == [(1, ana.id)], [
        (i["posicao"], i["nome"], i["nota_geral"], i["aferido_leitura"],
         i["aferido_matematica"]) for i in top]


def test_top10_do_painel_mantem_o_zero_legitimo(cliente, db, escola_completa):
    """Doze crianças sem plataforma nenhuma (mais que o limite de 10) e uma com
    retrato ZERADO: só esta fica no Top 10 — o corte é a existência do retrato
    (`aferido_*`), nunca `nota > 0`."""
    esc = escola_completa["escola"]
    turma = escola_completa["turma"]
    from app.models import Aluno, Matricula

    extras = []
    for i in range(10):
        aluno = Aluno(escola_id=esc.id, nome=f"Aaa Sem Dado {i:02d}")
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=aluno.id, turma_id=turma.id,
                         ano_letivo=2026))
        extras.append(aluno)
    ana, joao, sofia = escola_completa["alunos"]
    # Sofia tem retrato ZERADO: abriu a plataforma e não produziu (zero legítimo).
    _matific(db, esc, sofia, datetime(2026, 10, 1), 0, 0)
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    top = cliente.get(f"{API}/escolas/{esc.id}/dashboard").json()["top10"]
    assert [i["aluno_id"] for i in top] == [sofia.id], [
        (i["posicao"], i["nome"], i["aferido_matematica"]) for i in top]
    assert top[0]["aferido_matematica"] is True


def test_painel_e_evolucao_do_app_sem_crianca_sem_dado(db, escola_completa):
    """O pacote do app (`/sincronizacao`) herda as duas listas, também para a
    professora (posição relativa às turmas dela)."""
    esc = escola_completa["escola"]
    turma = escola_completa["turma"]
    ana, joao, sofia = escola_completa["alunos"]
    _matific(db, esc, sofia, datetime(2026, 10, 1), 10, 20)
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    prof = Professor(escola_id=esc.id, nome="Profa Teste", email="profa@teste.local")
    db.add(prof)
    db.flush()
    db.get(Turma, turma.id).professor_id = prof.id
    db.add(Usuario(escola_id=esc.id, nome="Profa Teste", email="profa@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()
    c = TestClient(app)
    tok = c.post(f"{API}/auth/login",
                 data={"username": "profa@teste.local", "password": "s3nh4"})
    assert tok.status_code == 200, tok.text
    c.headers["Authorization"] = f"Bearer {tok.json()['access_token']}"
    pacote = c.get(f"{API}/escolas/{esc.id}/sincronizacao")
    assert pacote.status_code == 200, pacote.text
    corpo = pacote.json()
    assert [(i["posicao"], i["aluno_id"]) for i in corpo["dashboard"]["top10"]] == [
        (1, sofia.id)]
    evolucao = corpo["evolucao"]
    assert not {ana.id, joao.id} & {i["aluno_id"] for i in evolucao}, evolucao
    assert [i["posicao"] for i in evolucao] == list(range(1, len(evolucao) + 1))
