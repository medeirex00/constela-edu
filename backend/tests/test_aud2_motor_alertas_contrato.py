"""G_MODULOS-5 — os alertas automáticos não contam a plataforma fora do plano.

Numa rede de um módulo só, um retrato da plataforma que a rede NÃO contratou
(o contrato mudou no meio do ano, ou a escola veio de outra rede) não é "dado
do aluno": não esconde o "sem novos dados" de quem parou na plataforma
contratada, e quem só tem dado da outra plataforma "ainda não tem nenhum dado".
Os alertas vão para Insights, para o pacote do app e para o contexto da IA.

Dados 100% fictícios.
"""
from datetime import datetime, timedelta, timezone

from app.models import Importacao, ModuloRede, Rede, SnapshotElefante, SnapshotMatific
from app.services import insights

API = "/api/v1"


def _agora():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _rede(db, escola, desligado):
    rede = Rede(nome=f"Rede Inventada Alertas {desligado}", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(ModuloRede(rede_id=rede.id, modulo=desligado, ativo=False))
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    return imp


def _do(alertas, aluno):
    return [(a["tipo"], a["texto"]) for a in alertas if a["aluno_id"] == aluno.id]


def test_rede_so_leitura_matific_recente_nao_esconde_leitura_parada(db, escola_completa):
    escola = escola_completa["escola"]
    joao = escola_completa["alunos"][1]
    imp = _rede(db, escola, "matematica")
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=joao.id, importacao_id=imp.id,
                            livros_unicos=3, data_referencia=_agora() - timedelta(days=45)))
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=joao.id, importacao_id=imp.id,
                           atividades=9, data_referencia=_agora() - timedelta(days=1)))
    db.commit()
    alertas = _do(insights.alertas_da_escola(db, escola.id), joao)
    assert [t for t, _ in alertas] == ["sem_atividade"], alertas
    assert "45 dias" in alertas[0][1]


def test_rede_so_leitura_quem_so_tem_matific_nao_tem_nenhum_dado(db, escola_completa, cliente):
    escola = escola_completa["escola"]
    sofia = escola_completa["alunos"][2]
    imp = _rede(db, escola, "matematica")
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=sofia.id, importacao_id=imp.id,
                           atividades=5, estrelas=10, pontuacao_media=2.0,
                           data_referencia=_agora() - timedelta(days=40)))
    db.commit()
    alertas = _do(insights.alertas_da_escola(db, escola.id), sofia)
    assert alertas == [("sem_dados", "Sofia Almeida Duarte ainda não tem nenhum dado importado.")]
    # O pacote do app recebe o mesmo alerta (as séries que ele injeta são as mesmas).
    pacote = cliente.get(f"{API}/escolas/{escola.id}/sincronizacao").json()
    assert [a["tipo"] for a in pacote["alertas"] if a["aluno_id"] == sofia.id] == ["sem_dados"]


def test_rede_so_matematica_elefante_nao_esconde_matific_parado_nem_derruba_acertos(
        db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    imp = _rede(db, escola, "leitura")
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=ana.id, importacao_id=imp.id,
                           atividades=9, data_referencia=_agora() - timedelta(days=50)))
    # Leitura (fora do plano) recente e com queda de acertos: não é alerta desta rede.
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=ana.id, importacao_id=imp.id,
                            livros_unicos=3, questoes_tentativas=20, questoes_acertos=18,
                            data_referencia=_agora() - timedelta(days=3)))
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=ana.id, importacao_id=imp.id,
                            livros_unicos=4, questoes_tentativas=40, questoes_acertos=20,
                            data_referencia=_agora() - timedelta(days=1)))
    db.commit()
    alertas = _do(insights.alertas_da_escola(db, escola.id), ana)
    assert [t for t, _ in alertas] == ["sem_atividade"], alertas
    assert "50 dias" in alertas[0][1]


def test_controle_escola_sem_rede_o_matific_conta_como_dado(db, escola_completa):
    """Com os dois módulos, o retrato recente do Matific é dado do aluno (desenho)."""
    escola = escola_completa["escola"]
    joao = escola_completa["alunos"][1]
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=joao.id, importacao_id=imp.id,
                            livros_unicos=3, data_referencia=_agora() - timedelta(days=45)))
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=joao.id, importacao_id=imp.id,
                           atividades=9, data_referencia=_agora() - timedelta(days=1)))
    db.commit()
    assert _do(insights.alertas_da_escola(db, escola.id), joao) == []
