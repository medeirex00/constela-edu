"""Perfil PÚBLICO (link do QR do telão): a matéria sem dado não sai "0,0".

`publico.perfil_publico` devolvia `nota_elefante`/`nota_matific` com o 0.0 que
o motor grava para quem NÃO é aferido, sem o discriminante `aferido_*`; a
página pública mostrava "Leitura 0,0" para a criança que só usa o Matific —
afirma desempenho nulo onde não há dado, numa página aberta a qualquer um.
Agora a nota da matéria não aferida sai nula e o `aferido_*` vai junto; o
retrato ZERADO (abriu e não produziu) continua 0,0. Achado RANKINGS-9.
Dados fictícios.
"""
from fastapi.testclient import TestClient

from app.main import app
from app.models import Importacao, Nota, SnapshotMatific
from app.services import scoring
from tests.test_publico import _ativar_painel
from tests._ano_letivo import escola_no_ano_de_hoje  # noqa: F401 — fixture

API = "/api/v1"


def _so_matific(db, escola_completa, atividades):
    escola = escola_completa["escola"]
    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    for aluno, n in zip(escola_completa["alunos"], atividades):
        if n is None:
            continue
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=imp.id, atividades=n,
                               estrelas=2 * n, pontuacao_media=70 if n else 0))
    db.commit()
    scoring.recalcular_escola(db, escola.id)


def test_perfil_publico_nao_afirma_zero_na_materia_sem_dado(cliente, db, escola_completa):
    _so_matific(db, escola_completa, [30, 20, 10])
    token = _ativar_painel(cliente, escola_completa["escola"].id)
    anonimo = TestClient(app)
    alvo = escola_completa["alunos"][0].id
    nota = db.query(Nota).filter_by(aluno_id=alvo).one()
    assert nota.aferido_leitura is False and nota.aferido_matematica is True
    r = anonimo.get(f"{API}/publico/{token}/alunos/{alvo}")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["nota_elefante"] is None, corpo
    assert corpo["aferido_leitura"] is False
    assert corpo["aferido_matematica"] is True
    assert corpo["nota_matific"] == nota.nota_matific and corpo["nota_matific"] > 0


def test_perfil_publico_mantem_o_zero_legitimo(cliente, db, escola_completa):
    """Retrato do Matific ZERADO: a criança abriu a plataforma e ainda não
    produziu — 0,0 é verdade, e o perfil continua dizendo isso."""
    _so_matific(db, escola_completa, [30, None, 0])
    token = _ativar_painel(cliente, escola_completa["escola"].id)
    zerado = escola_completa["alunos"][2].id
    r = TestClient(app).get(f"{API}/publico/{token}/alunos/{zerado}")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["aferido_matematica"] is True
    assert corpo["nota_matific"] == 0.0
    assert corpo["nota_elefante"] is None and corpo["aferido_leitura"] is False
