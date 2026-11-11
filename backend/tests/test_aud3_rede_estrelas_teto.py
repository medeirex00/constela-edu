"""G_AJUSTE-2 (a rede, mesma classe de defeito): o painel e o Ranking da Rede somam só as
estrelas que cabem no teto do motor — no máximo 5 por atividade.

``rede._q_totais`` somava ``SnapshotMatific.estrelas`` BRUTO nos cartões das escolas
(``estrelas``) e no PER CAPITA do Ranking da Rede (``estrelas_premiaveis`` ÷ quem
concorre): um retrato antigo ou importado com 10 atividades e 5000 estrelas punha a escola
dele no topo da Matemática da rede, enquanto a nota da criança contava 50. O motor, os
rankings da escola, a Visão da Escola, o telão e o cartaz já seguem o teto
(``scoring.estrelas_que_contam``). Dados fictícios.
"""
from datetime import datetime

from app.models import Aluno, Escola, Importacao, Matricula, Rede, SnapshotMatific, Turma
from app.services import rede as svc_rede
from app.services import scoring


def _retrato(db, escola, aluno, atividades, estrelas):
    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=datetime(escola.ano_letivo_ativo, 9, 1),
                           atividades=atividades, estrelas=estrelas, pontuacao_media=4))


def _rede_com(db, escola_completa) -> Rede:
    rede = Rede(nome="Rede Ficticia Teto")
    db.add(rede)
    db.flush()
    escola_completa["escola"].rede_id = rede.id
    return rede


def test_painel_da_rede_soma_as_estrelas_que_contam(db, escola_completa):
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    rede = _rede_com(db, escola_completa)
    _retrato(db, escola, ana, 10, 5000)     # acima do teto: contam 50
    _retrato(db, escola, joao, 4, 12)       # dentro do teto: contam 12
    _retrato(db, escola, sofia, 0, 7)       # sem atividade: nenhuma conta
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    db.commit()

    painel = svc_rede.dashboard_rede(db, rede.id)
    cartao = next(c for c in painel["escolas"] if c["escola_id"] == escola.id)
    assert cartao["estrelas"] == 62                 # antes 5019
    assert cartao["estrelas_premiaveis"] == 62
    assert cartao["atividades"] == 14
    assert cartao["estrelas_por_matricula"] == 20.7     # 62 ÷ 3 (antes 1673)
    # Quem SOMA nas estrelas (o k da vitrine pública): a Sofia não soma nenhuma.
    (interno,) = [c for c in svc_rede._kpis_da_rede(db, rede.id) if c["escola_id"] == escola.id]
    assert interno["com_estrelas_premiaveis"] == 2
    assert painel["totais"]["estrelas"] == 62


def test_ranking_da_rede_nao_poe_no_topo_a_escola_do_retrato_inflado(db, escola_completa):
    """Duas escolas: a do retrato inflado (10 atividades, 5000 estrelas) e uma com mais
    atividades e estrelas reais. A Matemática da rede ordena pelas estrelas que contam."""
    inflada = escola_completa["escola"]
    rede = _rede_com(db, escola_completa)
    ana, joao, sofia = escola_completa["alunos"]
    _retrato(db, inflada, ana, 10, 5000)
    _retrato(db, inflada, joao, 0, 0)
    _retrato(db, inflada, sofia, 0, 0)
    real = Escola(nome="Escola Ficticia Real", ano_letivo_ativo=inflada.ano_letivo_ativo,
                  rede_id=rede.id)
    db.add(real)
    db.flush()
    turma = Turma(escola_id=real.id, nome="3º Ano A", ano_escolar="3º Ano",
                  ano_letivo=real.ano_letivo_ativo)
    db.add(turma)
    db.flush()
    for i in range(3):
        a = Aluno(escola_id=real.id, nome=f"Crianca Ficticia Real {i}")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=real.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=real.ano_letivo_ativo))
        _retrato(db, real, a, 30, 120)
    db.commit()
    for eid in (inflada.id, real.id):
        scoring.recalcular_escola(db, eid)
    db.commit()

    cartoes = {c["escola_id"]: c for c in svc_rede.cartoes_da_rede(db, rede.id)}
    assert cartoes[inflada.id]["estrelas"] == 50
    assert cartoes[real.id]["estrelas"] == 360
    assert (cartoes[real.id]["estrelas_por_matricula"]
            > cartoes[inflada.id]["estrelas_por_matricula"])
    # A aba Matemática do Ranking da Rede (estrelas por aluno). Antes, a inflada em 1º.
    ranking = svc_rede.ranking_escolas(db, rede.id, metrica="estrelas_aluno")
    assert [c["escola_id"] for c in ranking] == [real.id, inflada.id]
