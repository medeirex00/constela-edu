"""PEND-11 (RANKINGS-1 / RANKINGS-5, causa raiz no motor): a Nota de quem deixou
de ser pontuado não guarda a posição de um cálculo antigo.

O recálculo só regrava as linhas de quem concorre (aluno ativo, matriculado no ano
numa turma premiável). A Nota de quem saiu — transferido, arquivado, sem matrícula
no ano, Fase — ficava com a posição carimbada antes, e cada leitor precisava
filtrá-la; um leitor novo que esquecesse o filtro mostrava duas crianças "em 1º".
Agora o recálculo limpa as POSIÇÕES dessas linhas (a Nota continua existindo: o
recálculo não a apaga — ``test_ranking_fases_cobertura``). Dados fictícios.
"""
from datetime import datetime

from sqlalchemy import select

from app.models import Importacao, Matricula, Nota, SnapshotMatific, Turma
from app.services import scoring


def _coleta(db, escola_id, valores):
    imp = Importacao(escola_id=escola_id, usuario_id=None, plataforma="matific",
                     tipo="api", qtd_alunos=len(valores))
    db.add(imp)
    db.flush()
    for aid, ativ in valores.items():
        db.add(SnapshotMatific(escola_id=escola_id, aluno_id=aid, importacao_id=imp.id,
                               data_referencia=datetime(2026, 6, 8, 12, 0),
                               atividades=ativ, estrelas=ativ * 4, pontuacao_media=4.0))
    db.commit()


def _notas(db, escola_id):
    db.expire_all()
    return {n.aluno_id: n for n in db.execute(
        select(Nota).where(Nota.escola_id == escola_id, Nota.ano_letivo == 2026)
    ).scalars()}


def _escola(db, escola_completa):
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    # Sofia é a que mais fez: está em 1º antes de sair.
    _coleta(db, escola.id, {ana.id: 20, joao.id: 10, sofia.id: 90})
    scoring.recalcular_escola(db, escola.id)
    notas = _notas(db, escola.id)
    assert (notas[sofia.id].posicao, notas[sofia.id].posicao_matematica) == (1, 1)
    return escola, ana, joao, sofia


def _sem_posicao(nota):
    return (nota.posicao, nota.posicao_leitura, nota.posicao_matematica) == \
        (None, None, None)


def test_transferido_perde_a_posicao_antiga(db, escola_completa):
    escola, ana, joao, sofia = _escola(db, escola_completa)
    sofia.status = "transferido"
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    notas = _notas(db, escola.id)
    assert sofia.id in notas, "o recálculo não apaga a Nota de quem saiu"
    assert _sem_posicao(notas[sofia.id]), \
        "a Nota de quem saiu guardou a posição de um cálculo antigo"
    assert (notas[ana.id].posicao, notas[joao.id].posicao) == (1, 2)
    assert (notas[ana.id].posicao_matematica, notas[joao.id].posicao_matematica) == (1, 2)


def test_quem_perde_a_matricula_do_ano_perde_a_posicao(db, escola_completa):
    escola, _, _, sofia = _escola(db, escola_completa)
    for m in db.execute(select(Matricula).where(Matricula.aluno_id == sofia.id)).scalars():
        db.delete(m)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    assert _sem_posicao(_notas(db, escola.id)[sofia.id])


def test_quem_vai_para_uma_fase_perde_a_posicao(db, escola_completa):
    escola, _, _, sofia = _escola(db, escola_completa)
    fase = Turma(escola_id=escola.id, nome="1ª Fase Teste", ano_escolar="1ª Fase",
                 ano_letivo=2026)
    db.add(fase)
    db.flush()
    matricula = db.execute(select(Matricula).where(Matricula.aluno_id == sofia.id)
                           ).scalars().one()
    matricula.turma_id = fase.id
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    assert _sem_posicao(_notas(db, escola.id)[sofia.id])


def test_quem_volta_recebe_posicao_de_novo(db, escola_completa):
    escola, _, _, sofia = _escola(db, escola_completa)
    sofia.status = "transferido"
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    sofia.status = "ativo"
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    nota = _notas(db, escola.id)[sofia.id]
    assert (nota.posicao, nota.posicao_matematica) == (1, 1)
