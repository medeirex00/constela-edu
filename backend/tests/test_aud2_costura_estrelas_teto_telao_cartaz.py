"""G_AJUSTE-2 (telão e cartaz): o total de estrelas segue o teto do motor — no máximo 5
por atividade (``scoring.estrelas_que_contam``, a fonte única do teto).

O motor, os rankings, a Evolução, o XP e as conquistas já contam só as estrelas que
cabem no teto. O telão público (``publico._dados_publicos``, faixa de indicadores) e os
cartões do cartaz de Matemática (``relatorios.estatisticas_cartaz_materia``) somavam o
número BRUTO do retrato: um retrato antigo (ou de relatório importado) com 10
atividades e 5000 estrelas punha 5000 no telão, enquanto a nota dela contava 50.
Dados fictícios.
"""
from datetime import datetime

from app.models import Importacao, SnapshotMatific
from app.routers import publico
from app.services import relatorios, scoring


def _retrato(db, escola, aluno, atividades, estrelas):
    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=datetime(2026, 9, 1), atividades=atividades,
                           estrelas=estrelas, pontuacao_media=4))


def _cenario(db, escola_completa):
    escola = escola_completa["escola"]
    ana, joao, _sofia = escola_completa["alunos"]
    _retrato(db, escola, ana, 10, 5000)     # acima do teto: contam 50
    _retrato(db, escola, joao, 4, 12)       # dentro do teto: contam 12
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    db.commit()
    return escola, [ana.id, joao.id]


def test_telao_soma_as_estrelas_que_contam(db, escola_completa):
    escola, _ids = _cenario(db, escola_completa)
    dados = publico._dados_publicos(db, escola, publico._config(db, escola.id))
    assert dados["estatisticas"]["estrelas"] == 50 + 12      # antes 5012
    assert dados["estatisticas"]["atividades"] == 14


def test_cartaz_de_matematica_soma_as_estrelas_que_contam(db, escola_completa):
    escola, ids = _cenario(db, escola_completa)
    cartoes = relatorios.estatisticas_cartaz_materia(db, escola.id, "matematica", ids)
    assert cartoes == {"atividades": 14, "estrelas": 62}    # antes 5012
