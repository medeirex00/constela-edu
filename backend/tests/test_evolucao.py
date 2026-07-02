"""Testes da Fase 3 — evolução, ranking de evolução e comparadores."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Importacao, SnapshotElefante, SnapshotMatific
from app.services import evolucao as svc
from app.services import scoring


def _importacao(db, escola_id) -> Importacao:
    importacao = Importacao(escola_id=escola_id, plataforma="matific", tipo="seed")
    db.add(importacao)
    db.flush()
    return importacao


def _snap_matific(db, escola_id, importacao, aluno_id, dias_atras, **valores):
    db.add(SnapshotMatific(
        escola_id=escola_id, aluno_id=aluno_id, importacao_id=importacao.id,
        data_referencia=datetime.now(timezone.utc) - timedelta(days=dias_atras),
        **valores,
    ))


def _snap_elefante(db, escola_id, importacao, aluno_id, dias_atras, **valores):
    db.add(SnapshotElefante(
        escola_id=escola_id, aluno_id=aluno_id, importacao_id=importacao.id,
        data_referencia=datetime.now(timezone.utc) - timedelta(days=dias_atras),
        **valores,
    ))


def test_resumo_evolucao_compara_baseline_e_atual(db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    importacao = _importacao(db, escola.id)
    # Snapshot antigo (fora do período de 30 dias) e um recente
    _snap_matific(db, escola.id, importacao, ana.id, 60,
                  atividades=10, estrelas=50, pontuacao_media=70)
    _snap_matific(db, escola.id, importacao, ana.id, 5,
                  atividades=25, estrelas=90, pontuacao_media=80)
    db.commit()

    resumo = svc.resumo_evolucao(db, escola.id, ana.id, dias=30)
    atividades = next(i for i in resumo["indicadores"] if i["indicador"] == "atividades")
    assert atividades["inicial"] == 10
    assert atividades["atual"] == 25
    assert atividades["variacao"] == 15
    assert atividades["percentual"] == 150.0


def test_aluno_novo_evolui_a_partir_do_zero(db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    importacao = _importacao(db, escola.id)
    _snap_matific(db, escola.id, importacao, ana.id, 3,
                  atividades=12, estrelas=30, pontuacao_media=65)
    db.commit()

    resumo = svc.resumo_evolucao(db, escola.id, ana.id, dias=30)
    atividades = next(i for i in resumo["indicadores"] if i["indicador"] == "atividades")
    assert atividades["inicial"] == 0
    assert atividades["variacao"] == 12
    assert atividades["percentual"] is None  # não há base para percentual


def test_ranking_evolucao_premia_quem_mais_cresceu(db, escola_completa):
    """Quem tem nota alta mas estagnou fica atrás de quem cresceu (PRD §72)."""
    escola = escola_completa["escola"]
    ana, joao, _ = escola_completa["alunos"]
    importacao = _importacao(db, escola.id)

    # Ana: veterana com números altos, mas parada há 60 dias
    _snap_matific(db, escola.id, importacao, ana.id, 60,
                  atividades=100, estrelas=500, pontuacao_media=95)
    # João: começou do zero e cresceu dentro do período
    _snap_matific(db, escola.id, importacao, joao.id, 10,
                  atividades=30, estrelas=80, pontuacao_media=75)
    db.commit()

    itens = svc.ranking_evolucao(db, escola.id, dias=30)
    posicoes = {item.aluno_id: item.posicao for item in itens}
    assert posicoes[joao.id] == 1
    assert posicoes[ana.id] > posicoes[joao.id]
    joao_item = next(i for i in itens if i.aluno_id == joao.id)
    assert joao_item.ganhos["atividades"] == 30


def test_correcao_para_baixo_nao_gera_evolucao_negativa(db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    importacao = _importacao(db, escola.id)
    _snap_matific(db, escola.id, importacao, ana.id, 40,
                  atividades=50, estrelas=200, pontuacao_media=90)
    # Correção manual reduziu os números dentro do período
    _snap_matific(db, escola.id, importacao, ana.id, 2,
                  atividades=45, estrelas=180, pontuacao_media=85)
    db.commit()

    itens = svc.ranking_evolucao(db, escola.id, dias=30)
    ana_item = next(i for i in itens if i.aluno_id == ana.id)
    assert ana_item.ganhos["atividades"] == 0.0
    assert ana_item.nota_evolucao == 0.0


def test_linha_do_tempo_ordena_snapshots(db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    importacao = _importacao(db, escola.id)
    _snap_elefante(db, escola.id, importacao, ana.id, 20, livros_unicos=2)
    _snap_elefante(db, escola.id, importacao, ana.id, 5, livros_unicos=6)
    db.commit()

    linha = svc.linha_do_tempo(db, escola.id, ana.id)
    livros = [ponto["livros_unicos"] for ponto in linha["elefante"]]
    assert livros == [2, 6]


def test_comparador_turmas_usa_medias(db, cliente, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    ana, joao, sofia = escola_completa["alunos"]
    importacao = _importacao(db, escola.id)
    _snap_matific(db, escola.id, importacao, ana.id, 1,
                  atividades=10, estrelas=20, pontuacao_media=80)
    _snap_matific(db, escola.id, importacao, joao.id, 1,
                  atividades=30, estrelas=40, pontuacao_media=60)
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    resposta = cliente.get(
        f"/api/v1/escolas/{escola.id}/comparar",
        params={"tipo_a": "aluno", "id_a": ana.id, "tipo_b": "turma", "id_b": turma.id},
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["a"]["tipo"] == "aluno"
    assert corpo["b"]["tipo"] == "turma"
    assert corpo["b"]["total_alunos"] == 3
    # Média da pontuação considera apenas quem tem snapshot (80+60)/2
    assert corpo["b"]["indicadores"]["pontuacao_media"] == pytest.approx(70.0)
    # Somatório de atividades da turma
    assert corpo["b"]["indicadores"]["atividades"] == 40


def test_resumo_escola_lista_todas_as_turmas(cliente, escola_completa):
    escola = escola_completa["escola"]
    resposta = cliente.get(f"/api/v1/escolas/{escola.id}/resumo-escola")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo["turmas"]) == 1
    assert corpo["turmas"][0]["total_alunos"] == 3


def test_evolucao_do_aluno_pela_api(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    importacao = _importacao(db, escola.id)
    _snap_matific(db, escola.id, importacao, ana.id, 3,
                  atividades=5, estrelas=10, pontuacao_media=60)
    db.commit()

    resposta = cliente.get(f"/api/v1/escolas/{escola.id}/alunos/{ana.id}/evolucao")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["nome"] == ana.nome
    assert len(corpo["linha_do_tempo"]["matific"]) == 1
    assert corpo["resumo"]["dias"] == 30
