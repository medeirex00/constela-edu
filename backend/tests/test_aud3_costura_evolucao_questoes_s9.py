"""S_G_AJUSTE-1, resíduo S9 (costura da fase D): na Evolução, o retrato de uma coleta em
que as questões NÃO vieram (S9, ``Importacao.status == "sem_questoes"``) não é borda das
questões do período.

O retrato S9 leva as questões do retrato ATUAL de antes dele (``_snapshot_atual``) — que
pode ser um ajuste manual do suporte. A regra do ajuste manual da série da Evolução
(``sem_ajustes_superados_vitalicio``) tira o ajuste que uma coleta depois desmentiu, e o
S9 conta como essa coleta (para livros e tempo, ele MEDE). Mas ele repete o número
digitado nas questões: usado como base, devolvia o degrau entre o número digitado e o
da plataforma como "questões do período" — o defeito do S_G_AJUSTE-1 que o Relatório por
Período já não tem (as Questões do período usam só os retratos que medem as questões, e
o S9 não desmente o ajuste ali).

Cenário (datas fixas, crianças fictícias): coleta em 01/09 com 100 tentativas e 80
acertos; o suporte corrige para 50/40 em 03/09; coleta S9 em 05/09 (livro novo, questões
herdadas: 50/40); coleta em 07/09 com 105/84. Questões de 06/09 a 08/09: 5 tentativas e
4 acertos (de coleta a coleta: 100/80 → 105/84). Antes: 55 e 44.
"""
from datetime import datetime, timezone

import pytest

from app.models import Importacao, SnapshotElefante
from app.models.plataformas import IMPORTACAO_SEM_QUESTOES
from app.services import evolucao, gamificacao
from app.services.evolucao import IMPORTACAO_AJUSTE_MANUAL
from tests._relogio import prender


def _retrato(db, escola_id, aluno_id, quando, *, tentativas, acertos, livros,
             tipo="sync", status="concluida"):
    imp = Importacao(escola_id=escola_id, plataforma="elefante", tipo=tipo, status=status)
    db.add(imp)
    db.flush()
    db.add(SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                            data_referencia=quando, livros_unicos=livros,
                            tempo_leitura_min=10 * livros, questoes_tentativas=tentativas,
                            questoes_acertos=acertos, livros_por_nivel={"D": livros}))
    db.flush()


def _cenario(db, escola_completa, *, com_s9: bool):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    _retrato(db, escola.id, aluno.id, datetime(2026, 9, 1, 15), tentativas=100, acertos=80,
             livros=10)
    _retrato(db, escola.id, aluno.id, datetime(2026, 9, 3, 15), tentativas=50, acertos=40,
             livros=10, tipo=IMPORTACAO_AJUSTE_MANUAL)
    if com_s9:
        _retrato(db, escola.id, aluno.id, datetime(2026, 9, 5, 15), tentativas=50,
                 acertos=40, livros=11, status=IMPORTACAO_SEM_QUESTOES)
    _retrato(db, escola.id, aluno.id, datetime(2026, 9, 7, 15), tentativas=105, acertos=84,
             livros=12)
    db.commit()
    return escola, aluno


def _ganhos(db, escola, aluno):
    itens = evolucao.ranking_evolucao(db, escola.id, datetime(2026, 9, 6),
                                      datetime(2026, 9, 8, 23, 59), base_no_periodo=True)
    (item,) = [i for i in itens if i.aluno_id == aluno.id]
    return item.ganhos


def test_retrato_s9_nao_e_base_das_questoes_do_periodo(db, escola_completa):
    escola, aluno = _cenario(db, escola_completa, com_s9=True)
    ganhos = _ganhos(db, escola, aluno)
    # Antes: 44 acertos (84 − 40, o número digitado repetido pelo S9).
    assert ganhos["acertos"] == 4
    # Livros e tempo continuam medidos pelo S9 (ele MEDE esses dois): 11 → 12.
    assert ganhos["livros"] == 1


def test_controle_sem_s9_o_ajuste_desmentido_sai_da_serie(db, escola_completa):
    escola, aluno = _cenario(db, escola_completa, com_s9=False)
    ganhos = _ganhos(db, escola, aluno)
    assert ganhos["acertos"] == 4
    assert ganhos["livros"] == 2


def test_resumo_de_evolucao_compara_coletas_que_medem_questoes(db, escola_completa, monkeypatch):
    escola, aluno = _cenario(db, escola_completa, com_s9=True)
    prender(monkeypatch, datetime(2026, 9, 8, 15, tzinfo=timezone.utc))
    resumo = evolucao.resumo_evolucao(db, escola.id, aluno.id, dias=2)
    ganhos = {i["indicador"]: i["variacao"] for i in resumo["indicadores"]}
    assert ganhos["questoes_tentativas"] == 5
    assert ganhos["questoes_acertos"] == 4
    assert ganhos["livros_unicos"] == 1


@pytest.mark.parametrize(("acertos", "semanas"), [(80, 1), (84, 2)])
def test_sequencia_so_conta_ganho_real_de_questoes(db, escola_completa, acertos, semanas):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    _retrato(db, escola.id, aluno.id, datetime(2026, 9, 1, 15), tentativas=100, acertos=80, livros=10)
    _retrato(db, escola.id, aluno.id, datetime(2026, 9, 3, 15), tentativas=50, acertos=40,
             livros=10, tipo=IMPORTACAO_AJUSTE_MANUAL)
    _retrato(db, escola.id, aluno.id, datetime(2026, 9, 5, 15), tentativas=50, acertos=40,
             livros=10, status=IMPORTACAO_SEM_QUESTOES)
    _retrato(db, escola.id, aluno.id, datetime(2026, 9, 7, 15), tentativas=105, acertos=acertos,
             livros=10)
    db.commit()
    assert gamificacao.gamificacao_do_aluno(db, escola.id, aluno.id)["sequencia_semanas"] == semanas
