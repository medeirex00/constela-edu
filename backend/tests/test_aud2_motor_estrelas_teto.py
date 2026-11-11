"""G_AJUSTE-2: estrelas acima de 5 por atividade não contam em lugar nenhum do motor.

A regra (decisão do dono 2026-09-15, ``matific_destaque.limitar_estrelas``): uma
correção de relatório não cria estrela sem atividade — 10 atividades valem no
máximo 50 estrelas. Só as premiações aplicavam o teto; o Ranking de Matemática, a
nota oficial (posição e certificado de mérito), o Ranking de Evolução, o XP, as
conquistas e o resumo da turma usavam o número bruto. O mesmo dado saía em ordens
diferentes na mesma tela.

O retrato é gravado direto no banco (como um ajuste antigo, de antes da validação
da edição manual): o motor tem de se defender sozinho. Dados fictícios.
"""
from datetime import datetime

from sqlalchemy import select

from app.models import Aluno, Importacao, Matricula, Nota, SnapshotMatific
from app.services import evolucao, gamificacao, scoring

API = "/api/v1"
QUANDO = datetime(2026, 6, 8, 12, 0)


def _mais_alunos(db, escola_completa, n=4):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    novos = []
    for i in range(n):
        a = Aluno(escola_id=escola.id, nome=f"Aluno Ficticio {i}")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=2026))
        novos.append(a)
    db.commit()
    return escola_completa["alunos"] + novos


def _retrato(db, escola_id, aluno_id, atividades, estrelas, tipo="manual"):
    imp = Importacao(escola_id=escola_id, usuario_id=None, plataforma="matific",
                     tipo=tipo, qtd_alunos=1)
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                           data_referencia=QUANDO, atividades=atividades,
                           estrelas=estrelas, pontuacao_media=4.0))
    db.commit()


def _escola(db, escola_completa, estrelas_ana):
    escola = escola_completa["escola"]
    alunos = _mais_alunos(db, escola_completa)
    ana, outros = alunos[0], alunos[1:]
    for a in outros:
        _retrato(db, escola.id, a.id, 60, 270, tipo="api")
    _retrato(db, escola.id, ana.id, 10, estrelas_ana)
    return escola, ana


def test_ranking_de_matematica_nao_ordena_por_estrela_sem_atividade(cliente, db,
                                                                    escola_completa):
    escola, ana = _escola(db, escola_completa, 5000)
    ranking = cliente.get(f"{API}/escolas/{escola.id}/ranking/matematica",
                          params={"periodo": "ano_letivo"}).json()
    item = next(i for i in ranking if i["aluno_id"] == ana.id)
    assert item["estrelas"] == 50, "estrelas acima de 5 por atividade no ranking"
    assert item["posicao"] == len(ranking), "Ana subiu para o topo com estrelas digitadas"


def _nota_da_ana(db, escola_completa, estrelas):
    escola, ana = _escola(db, escola_completa, estrelas)
    scoring.recalcular_escola(db, escola.id)
    db.expire_all()
    n = db.execute(select(Nota).where(Nota.aluno_id == ana.id)).scalars().one()
    return (round(n.nota_matific, 2), round(n.nota_geral, 2), n.posicao,
            n.posicao_matematica)


def test_nota_oficial_com_5000_estrelas_igual_a_com_50(db, escola_completa):
    com_5000 = _nota_da_ana(db, escola_completa, 5000)
    # A MESMA escola com o número dentro do teto: a nota não pode mudar.
    snap = db.execute(select(SnapshotMatific).where(SnapshotMatific.estrelas == 5000)
                      ).scalars().one()
    snap.estrelas = 50
    db.commit()
    escola_id = escola_completa["escola"].id
    scoring.recalcular_escola(db, escola_id)
    db.expire_all()
    n = db.execute(select(Nota).where(Nota.aluno_id == snap.aluno_id)).scalars().one()
    com_50 = (round(n.nota_matific, 2), round(n.nota_geral, 2), n.posicao,
              n.posicao_matematica)
    assert com_5000 == com_50, "nota oficial usou estrelas acima de 5 por atividade"


def test_regua_da_escola_nao_e_puxada_pela_estrela_sem_atividade(db, escola_completa):
    escola, _ = _escola(db, escola_completa, 5000)
    matific = scoring._snapshots_atuais(db, escola.id, SnapshotMatific)
    refs, _ = scoring._referencias_auto(matific, {}, {})
    assert refs["max_estrelas"] <= 270


def test_ranking_de_evolucao_limita_o_ganho_de_estrelas(db, escola_completa):
    escola, ana = _escola(db, escola_completa, 5000)
    itens = evolucao.ranking_evolucao(db, escola.id, datetime(2026, 1, 1),
                                      datetime(2026, 12, 31, 23, 59, 59),
                                      base_no_periodo=True)
    item = next(i for i in itens if i.aluno_id == ana.id)
    assert (item.ganhos["atividades"], item.ganhos["estrelas"]) == (10, 50)


def test_xp_e_conquista_nao_contam_estrela_sem_atividade(db, escola_completa):
    escola, ana = _escola(db, escola_completa, 5000)
    detalhe = gamificacao.gamificacao_do_aluno(db, escola.id, ana.id)
    estrelas = [c for c in detalhe["conquistas"] if c["indicador"] == "estrelas"]
    assert estrelas, "a configuração padrão tem conquistas de estrelas"
    assert all(not c["atingida"] for c in estrelas), \
        "conquista de estrelas desbloqueada com 10 atividades"
    assert all(c["progresso"] == 50 for c in estrelas)
    pesos = {"atividades": 0.0, "estrelas": 1.0}
    snap = db.execute(select(SnapshotMatific).where(SnapshotMatific.aluno_id == ana.id)
                      ).scalars().one()
    assert gamificacao.xp_do_aluno(snap, None, pesos) == 50


def test_resumo_da_turma_soma_so_as_estrelas_que_contam(db, escola_completa):
    escola, ana = _escola(db, escola_completa, 5000)
    total = evolucao._indicadores_atuais(db, escola.id, [ana.id])
    assert total["estrelas"] == 50
