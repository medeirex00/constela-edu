"""G_MODULOS-4 — o Painel do app e o Comparador não mostram o módulo fora do plano.

Rede só com Leitura e um retrato do Matific gravado (contrato mudado no meio do
ano, ou escola vinda de outra rede):
  * o pacote do app (`/sincronizacao`) não soma as atividades do Matific e diz
    quais módulos valem, para o Painel esconder o cartão (nem zerado);
  * o Comparador devolve a nota e os indicadores do Matific NULOS, e a matéria
    não é "aferida" num produto que a rede não comprou.

Dados 100% fictícios. Datas FIXAS dentro do ano letivo 2026 da fixture
(REV2-MOTOR-2): o Matific é contador do ANO, e um retrato datado pelo relógio de
quem roda a suíte cairia fora de 2026 a partir de 01/01/2027.
"""
from datetime import datetime, timedelta

import pytest

from app.models import Importacao, ModuloRede, Rede, SnapshotElefante, SnapshotMatific
from app.services import modulos as svc_modulos, scoring

API = "/api/v1"
INDICADORES_MATIFIC = ("atividades", "estrelas", "pontuacao_media")
INDICADORES_ELEFANTE = ("livros_unicos", "tempo_leitura_min", "questoes_tentativas",
                        "questoes_acertos")
# Dia de uma coleta inventada, dentro do ano letivo 2026 (nunca o relógio).
QUANDO = datetime(2026, 10, 10, 12, 0)


def _cenario(db, escola_completa, ativos):
    """Ana e João leem (4 livros cada); Ana também tem Matific do ano (30
    atividades) e Sofia, 5 atividades. ``ativos`` = módulos da rede (None = sem rede)."""
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    if ativos is not None:
        rede = Rede(nome="Rede Inventada Painel", status="ativa")
        db.add(rede)
        db.flush()
        escola.rede_id = rede.id
        for modulo in svc_modulos.TODOS:
            db.add(ModuloRede(rede_id=rede.id, modulo=modulo, ativo=(modulo in ativos)))
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    for aluno in (ana, joao):
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                                livros_unicos=4, tempo_leitura_min=50,
                                questoes_tentativas=10, questoes_acertos=8,
                                data_referencia=QUANDO - timedelta(days=2)))
    for aluno, atividades in ((ana, 30), (sofia, 5)):
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                               atividades=atividades, estrelas=600, pontuacao_media=3.5,
                               data_referencia=QUANDO - timedelta(days=1)))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola, ana, joao, escola_completa["turma"]


@pytest.fixture()
def so_leitura(db, escola_completa):
    return _cenario(db, escola_completa, {"leitura"})


# --- Pacote do app (Painel) --------------------------------------------------------

def test_pacote_do_app_sem_atividades_do_matific_e_com_os_modulos(so_leitura, cliente):
    escola, *_ = so_leitura
    pacote = cliente.get(f"{API}/escolas/{escola.id}/sincronizacao").json()
    assert pacote["modulos"] == ["leitura"]
    assert pacote["dashboard"]["total_atividades"] == 0
    assert pacote["dashboard"]["total_livros"] == 8


def test_pacote_do_app_rede_so_matematica_sem_livros_nem_tempo(db, escola_completa, cliente):
    escola, *_ = _cenario(db, escola_completa, {"matematica"})
    pacote = cliente.get(f"{API}/escolas/{escola.id}/sincronizacao").json()
    assert pacote["modulos"] == ["matematica"]
    d = pacote["dashboard"]
    assert (d["total_livros"], d["tempo_leitura_min"]) == (0, 0)
    assert d["total_atividades"] == 35


def test_controle_pacote_escola_sem_rede_soma_tudo(db, escola_completa, cliente):
    escola, *_ = _cenario(db, escola_completa, None)
    pacote = cliente.get(f"{API}/escolas/{escola.id}/sincronizacao").json()
    assert pacote["modulos"] == ["leitura", "matematica"]
    assert pacote["dashboard"]["total_atividades"] == 35
    assert pacote["dashboard"]["total_livros"] == 8


# --- Comparador ---------------------------------------------------------------------

def _comparar(cliente, escola, tipo_a, id_a, tipo_b, id_b):
    r = cliente.get(f"{API}/escolas/{escola.id}/comparar",
                    params={"tipo_a": tipo_a, "id_a": id_a, "tipo_b": tipo_b, "id_b": id_b})
    assert r.status_code == 200, r.text
    return r.json()


def _sem_matematica(lado):
    assert lado["notas"]["matific"] is None, lado["notas"]
    assert all(lado["indicadores"][c] is None for c in INDICADORES_MATIFIC), lado["indicadores"]
    assert lado["dimensoes"]["matematica"]["aferido"] is False
    assert lado["dimensoes"]["matematica"]["nota"] is None
    # A Leitura (contratada) segue com os números.
    assert lado["notas"]["elefante"] is not None
    assert lado["indicadores"]["livros_unicos"] > 0


def test_comparador_aluno_sem_matematica_fora_do_plano(so_leitura, cliente):
    escola, ana, joao, _turma = so_leitura
    corpo = _comparar(cliente, escola, "aluno", ana.id, "aluno", joao.id)
    _sem_matematica(corpo["a"])
    _sem_matematica(corpo["b"])


def test_comparador_turma_sem_matematica_fora_do_plano(so_leitura, cliente):
    escola, ana, _joao, turma = so_leitura
    corpo = _comparar(cliente, escola, "aluno", ana.id, "turma", turma.id)
    _sem_matematica(corpo["b"])


def test_comparador_escola_sem_matematica_fora_do_plano(so_leitura, cliente_global):
    escola, ana, _joao, _turma = so_leitura
    corpo = _comparar(cliente_global, escola, "aluno", ana.id, "escola", escola.id)
    _sem_matematica(corpo["b"])


def test_comparador_rede_so_matematica_sem_leitura(db, escola_completa, cliente):
    escola, ana, joao, _turma = _cenario(db, escola_completa, {"matematica"})
    corpo = _comparar(cliente, escola, "aluno", ana.id, "aluno", joao.id)
    lado = corpo["a"]
    assert lado["notas"]["elefante"] is None
    assert all(lado["indicadores"][c] is None for c in INDICADORES_ELEFANTE)
    assert lado["dimensoes"]["leitura"]["aferido"] is False
    assert lado["notas"]["matific"] is not None and lado["indicadores"]["atividades"] == 30


def test_controle_comparador_escola_sem_rede_mostra_as_duas(db, escola_completa, cliente):
    escola, ana, joao, _turma = _cenario(db, escola_completa, None)
    corpo = _comparar(cliente, escola, "aluno", ana.id, "aluno", joao.id)
    assert corpo["a"]["notas"]["matific"] > 0
    assert corpo["a"]["indicadores"]["atividades"] == 30
    assert corpo["a"]["dimensoes"]["matematica"]["aferido"] is True
