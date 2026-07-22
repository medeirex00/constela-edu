"""Regressão do dashboard após importação RETROATIVA (backfill).

Bug corrigido: o dashboard escolhia o "snapshot atual" por max(id), enquanto o
resto do sistema usa (data_referencia, id). Um import de período ANTIGO grava
id MAIOR com data MENOR — e o painel passava a mostrar os totais do snapshot
errado (o antigo), divergindo do ranking. Agora o dashboard usa a mesma régua
autoritativa (scoring.ids_snapshots_atuais).
"""
from datetime import datetime, timezone

from app.models import Importacao, SnapshotMatific


def _base(escola_id: int) -> str:
    return f"/api/v1/escolas/{escola_id}"


def test_dashboard_usa_snapshot_por_data_nao_por_id(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    aluno = escola_completa["alunos"][0]

    imp = Importacao(escola_id=escola_id, plataforma="matific", tipo="texto")
    db.add(imp)
    db.flush()

    # ORDEM DE INSERÇÃO simula o backfill: primeiro o snapshot ATUAL (junho,
    # 120 atividades) e DEPOIS um import retroativo de janeiro (id maior, mas
    # data menor, 10 atividades). Por max(id), o painel pegaria os 10 (errado).
    db.add(SnapshotMatific(
        escola_id=escola_id, aluno_id=aluno.id, importacao_id=imp.id,
        data_referencia=datetime(2026, 6, 1, tzinfo=timezone.utc), atividades=120))
    db.flush()
    db.add(SnapshotMatific(
        escola_id=escola_id, aluno_id=aluno.id, importacao_id=imp.id,
        data_referencia=datetime(2026, 1, 1, tzinfo=timezone.utc), atividades=10))
    db.commit()

    r = cliente.get(f"{_base(escola_id)}/dashboard")
    assert r.status_code == 200, r.text
    # Reflete o snapshot ATUAL (junho=120), não o retroativo de id maior (10).
    assert r.json()["total_atividades"] == 120


def test_perfil_aluno_usa_snapshot_elefante_por_data_nao_por_id(cliente, db, escola_completa):
    """A ficha individual do aluno (distribuição de leitura) também deve usar o
    snapshot atual por data_referencia — não max(id). Sem isto, um import
    retroativo mostraria a distribuição de leitura ERRADA de uma criança."""
    from app.models import Importacao, SnapshotElefante

    escola_id = escola_completa["escola"].id
    aluno = escola_completa["alunos"][0]
    imp = Importacao(escola_id=escola_id, plataforma="elefante", tipo="texto")
    db.add(imp)
    db.flush()

    # ATUAL (junho, 8 livros AA) inserido primeiro; retroativo (janeiro, 1 livro)
    # depois com id MAIOR. Por max(id) o perfil pegaria o de janeiro (errado).
    db.add(SnapshotElefante(
        escola_id=escola_id, aluno_id=aluno.id, importacao_id=imp.id,
        data_referencia=datetime(2026, 6, 1, tzinfo=timezone.utc),
        livros_unicos=8, livros_por_nivel={"AA": 8}))
    db.flush()
    db.add(SnapshotElefante(
        escola_id=escola_id, aluno_id=aluno.id, importacao_id=imp.id,
        data_referencia=datetime(2026, 1, 1, tzinfo=timezone.utc),
        livros_unicos=1, livros_por_nivel={"AA": 1}))
    db.commit()

    r = cliente.get(f"{_base(escola_id)}/alunos/{aluno.id}/perfil")
    assert r.status_code == 200, r.text
    leitura = r.json().get("leitura_niveis") or {}
    assert leitura.get("total_livros") == 8   # snapshot ATUAL (junho), não o de janeiro (1)
