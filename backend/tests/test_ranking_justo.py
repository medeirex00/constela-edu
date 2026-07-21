"""Justiça do Ranking de Evolução (auditoria da discrepância "Antonella").

Bug de origem: o Ranking de Evolução (que alimenta o mural — Aluno do
Dia/Semana/Mês — e o painel público) media o ganho do período com
`base_no_periodo=False`. Quando um aluno NÃO tinha snapshot ANTES do início da
janela, a `_janela` devolvia base=None e o ganho virava o TOTAL ACUMULADO
inteiro. Com a normalização por MÁXIMO da escola, esse total (histórico de vida
importado num único snapshot recente) virava ~100 e dominava o ranking — sem que
o aluno tivesse, de fato, crescido naquele período.

As premiações já usavam o critério justo (`base_no_periodo=True`, "ganho
estritamente dentro do período"). Estes testes fixam o MESMO critério justo para
o Ranking de Evolução: sem baseline anterior, o ganho do período é medido do 1º
snapshot DENTRO da janela (0 se houver só um) — nunca o acumulado de vida.
"""
from datetime import datetime, timedelta, timezone

from app.models import Importacao, SnapshotMatific
from app.services import evolucao as svc
from app.services import gamificacao as svc_gami


def _imp(db, escola_id):
    importacao = Importacao(escola_id=escola_id, plataforma="matific", tipo="seed")
    db.add(importacao)
    db.flush()
    return importacao


def _snap(db, escola_id, imp, aluno_id, dias_atras, **valores):
    db.add(SnapshotMatific(
        escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
        data_referencia=datetime.now(timezone.utc) - timedelta(days=dias_atras),
        **valores,
    ))


# ---------------------------------------------------------------------------
# Reprodução da discrepância + garantia de que NÃO se repete
# ---------------------------------------------------------------------------

def test_snapshot_unico_recente_nao_conta_acumulado_como_evolucao(db, escola_completa):
    """CENÁRIO ANTONELLA: aluno com UM único snapshot recente e total enorme
    (histórico de vida importado de uma vez) NÃO pode dominar o ranking; sem
    baseline anterior, o ganho do período é 0 — não o acumulado."""
    escola = escola_completa["escola"]
    antonella, joao, sofia = escola_completa["alunos"]
    imp = _imp(db, escola.id)

    # Antonella: um único snapshot 5 dias atrás com números altíssimos.
    _snap(db, escola.id, imp, antonella.id, 5, atividades=500, estrelas=999, pontuacao_media=95)
    # João: crescimento REAL dentro do período (baseline 40d + recente 3d).
    _snap(db, escola.id, imp, joao.id, 40, atividades=10, estrelas=20, pontuacao_media=60)
    _snap(db, escola.id, imp, joao.id, 3, atividades=40, estrelas=70, pontuacao_media=75)
    # Sofia: crescimento real menor.
    _snap(db, escola.id, imp, sofia.id, 40, atividades=5, estrelas=10, pontuacao_media=55)
    _snap(db, escola.id, imp, sofia.id, 3, atividades=15, estrelas=25, pontuacao_media=60)
    db.commit()

    itens = svc.ranking_evolucao(db, escola.id, dias=30)
    por_id = {i.aluno_id: i for i in itens}

    # Antonella não cresceu DENTRO do período → ganho 0, não 500.
    assert por_id[antonella.id].ganhos["atividades"] == 0
    assert por_id[antonella.id].nota_evolucao == 0
    # Quem realmente cresceu lidera.
    assert por_id[joao.id].posicao == 1
    assert por_id[joao.id].ganhos["atividades"] == 30
    assert por_id[antonella.id].posicao > por_id[sofia.id].posicao


def test_destaques_semana_e_mes_nao_coroam_snapshot_unico(db, escola_completa):
    """O sintoma exato relatado: aluno vira Aluno da Semana E do Mês só por ter
    um snapshot recente com total alto. Após a correção, quem cresce de verdade
    é que ganha os destaques."""
    escola = escola_completa["escola"]
    antonella, joao, _ = escola_completa["alunos"]
    imp = _imp(db, escola.id)

    _snap(db, escola.id, imp, antonella.id, 5, atividades=500, estrelas=999, pontuacao_media=95)
    _snap(db, escola.id, imp, joao.id, 40, atividades=10, estrelas=20, pontuacao_media=60)
    _snap(db, escola.id, imp, joao.id, 3, atividades=40, estrelas=70, pontuacao_media=80)
    db.commit()

    destaques = svc_gami.mural(db, escola.id)["destaques"]
    # Semana e mês vão para quem cresceu no período (João), não para a Antonella.
    assert destaques["semana"] is not None
    assert destaques["semana"]["aluno_id"] == joao.id
    assert destaques["mes"]["aluno_id"] == joao.id


def test_antonella_aparece_quando_cresce_de_verdade(db, escola_completa):
    """A correção NÃO pune quem merece: se a Antonella tiver o MAIOR crescimento
    real no período (medido entre snapshots), ela lidera normalmente."""
    escola = escola_completa["escola"]
    antonella, joao, _ = escola_completa["alunos"]
    imp = _imp(db, escola.id)

    # Antonella: baseline 20d + recente 2d → cresceu 100 de verdade.
    _snap(db, escola.id, imp, antonella.id, 20, atividades=100, estrelas=200, pontuacao_media=70)
    _snap(db, escola.id, imp, antonella.id, 2, atividades=200, estrelas=400, pontuacao_media=85)
    # João: cresceu 20.
    _snap(db, escola.id, imp, joao.id, 20, atividades=100, estrelas=200, pontuacao_media=70)
    _snap(db, escola.id, imp, joao.id, 2, atividades=120, estrelas=230, pontuacao_media=72)
    db.commit()

    itens = svc.ranking_evolucao(db, escola.id, dias=30)
    por_id = {i.aluno_id: i for i in itens}
    assert por_id[antonella.id].posicao == 1
    assert por_id[antonella.id].ganhos["atividades"] == 100


def test_historico_grande_nao_vence_por_ser_veterano(db, escola_completa):
    """Aluno veterano com histórico enorme mas quase parado NÃO vence quem
    cresceu pouco em valor absoluto mas muito no período."""
    escola = escola_completa["escola"]
    veterano, novato, _ = escola_completa["alunos"]
    imp = _imp(db, escola.id)

    # Veterano: 1000 acumulados ANTES do período, cresceu só 5.
    _snap(db, escola.id, imp, veterano.id, 60, atividades=1000, estrelas=2000, pontuacao_media=95)
    _snap(db, escola.id, imp, veterano.id, 2, atividades=1005, estrelas=2005, pontuacao_media=95)
    # Novato: baseline no período, cresceu 50.
    _snap(db, escola.id, imp, novato.id, 20, atividades=10, estrelas=20, pontuacao_media=60)
    _snap(db, escola.id, imp, novato.id, 2, atividades=60, estrelas=120, pontuacao_media=75)
    db.commit()

    itens = svc.ranking_evolucao(db, escola.id, dias=30)
    por_id = {i.aluno_id: i for i in itens}
    assert por_id[novato.id].posicao == 1
    assert por_id[veterano.id].ganhos["atividades"] == 5  # delta real, não 1005


def test_snapshot_only_com_baseline_mede_delta(db, escola_completa):
    """Aluno acompanhado só por snapshots (sem leitura individual), COM baseline
    anterior ao período: o ganho é o delta entre snapshots — comportamento justo
    que continua funcionando."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    imp = _imp(db, escola.id)
    _snap(db, escola.id, imp, ana.id, 40, atividades=20, estrelas=40, pontuacao_media=60)
    _snap(db, escola.id, imp, ana.id, 3, atividades=32, estrelas=60, pontuacao_media=70)
    db.commit()

    itens = svc.ranking_evolucao(db, escola.id, dias=30)
    ana_item = next(i for i in itens if i.aluno_id == ana.id)
    assert ana_item.ganhos["atividades"] == 12  # 32 − 20
