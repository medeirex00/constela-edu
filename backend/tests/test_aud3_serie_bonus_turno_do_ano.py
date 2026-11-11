"""S_G_MODULOS-1 — bônus "livro lido na escola" (perfil personalizado): cada leitura é
julgada pelo turno da turma do ANO LETIVO dela, não pelo turno da turma atual.

``pontos_dif_com_bonus`` montava o turno de cada criança só com as matrículas do ano
ativo, e ``_bonus_leitura_na_escola`` soma as leituras de TODOS os anos (o contador do
Elefante é vitalício): a leitura feita em casa de manhã, num ano em que a criança
estudava à tarde, ganhava o bônus pelo turno de hoje — e a feita na escola à tarde o
perdia. A Matrícula guarda o histórico por ano; agora o turno vem dela.

Ano sem matrícula conhecida na escola: continua valendo o turno atual (o comportamento
de antes — decisão do dono pendente).

Dados fictícios.
"""
from datetime import date, datetime, time

import pytest
from sqlalchemy import select

from app.models import (Configuracao, Importacao, Leitura, Livro, Matricula, Nota,
                        SnapshotElefante, Turma)
from app.services import scoring

SEG_2024 = date(2024, 6, 3)
SEG_2025 = date(2025, 6, 2)
TER_2025 = date(2025, 6, 3)
SEG_2026 = date(2026, 7, 6)


def _ler(db, escola, aluno, quando, i):
    livro = Livro(escola_id=escola.id, titulo=f"Livro Fictício do Turno {aluno.id}-{i}",
                  nivel_codigo="D")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id, data=quando))


def _turma(db, escola, nome, ano, turno):
    turma = Turma(escola_id=escola.id, nome=nome, ano_escolar="2º Ano", ano_letivo=ano,
                  turno=turno)
    db.add(turma)
    db.flush()
    return turma


@pytest.fixture()
def cenario(db, escola_completa):
    assert all(d.weekday() == 0 for d in (SEG_2024, SEG_2025, SEG_2026))
    assert TER_2025.weekday() == 1
    escola = escola_completa["escola"]
    escola_completa["turma"].turno = "manha"                 # 2026: todos de manhã
    ana, joao, sofia = escola_completa["alunos"]
    # 2025: Ana estudava À TARDE; Sofia, de MANHÃ. João não tem matrícula de 2025.
    tarde_2025 = _turma(db, escola, "2º Ano B Fictício", 2025, "tarde")
    manha_2025 = _turma(db, escola, "2º Ano A Fictício", 2025, "manha")
    db.add(Matricula(escola_id=escola.id, aluno_id=ana.id, turma_id=tarde_2025.id,
                     ano_letivo=2025))
    db.add(Matricula(escola_id=escola.id, aluno_id=sofia.id, turma_id=manha_2025.id,
                     ano_letivo=2025))
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    for a in escola_completa["alunos"]:
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                                data_referencia=datetime(2026, 7, 10), livros_unicos=10,
                                tempo_leitura_min=100, questoes_tentativas=10,
                                questoes_acertos=8, livros_por_nivel={"D": 10}))
    leituras = {
        ana.id: [datetime.combine(SEG_2025, time(9, 0)),     # 2025 manhã: em CASA
                 datetime.combine(SEG_2025, time(9, 30)),    # idem
                 datetime.combine(SEG_2025, time(10, 0)),    # idem
                 datetime.combine(TER_2025, time(14, 30)),   # 2025 tarde: NA ESCOLA
                 datetime.combine(SEG_2026, time(9, 0))],    # 2026 manhã: NA ESCOLA
        # João: 2024 sem matrícula conhecida → o turno atual (manhã) julga, como antes.
        joao.id: [datetime.combine(SEG_2024, time(9, 0)),
                  datetime.combine(SEG_2024, time(14, 0))],
        sofia.id: [datetime.combine(SEG_2025, time(8, 0))],   # 2025 manhã: NA ESCOLA
    }
    alunos = {a.id: a for a in escola_completa["alunos"]}
    for aluno_id, momentos in leituras.items():
        for i, quando in enumerate(momentos):
            _ler(db, escola, alunos[aluno_id], quando, i)
    db.add(Configuracao(escola_id=escola.id, namespace=scoring.PERFIL_SCORING_NS,
                        chave="modo", valor="personalizado"))
    db.add(Configuracao(escola_id=escola.id, namespace="pesos.elefante_extra",
                        chave="valores", valor={"ativo": True, "pontos_por_livro": 10.0}))
    db.commit()
    return {"escola": escola, "ana": ana, "joao": joao, "sofia": sofia}


def _bonus(db, aluno):
    nota = db.execute(select(Nota).where(Nota.aluno_id == aluno.id,
                                         Nota.ano_letivo == 2026)).scalar_one()
    return ((nota.detalhes or {}).get("elefante") or {}).get("bonus_leitura_escola")


def test_motor_julga_cada_leitura_pelo_turno_do_ano_dela(db, cenario):
    scoring.recalcular_escola(db, cenario["escola"].id)
    db.expire_all()
    # Ana: 2025 às 14h30 (tarde, o turno dela em 2025) + 2026 às 9h (manhã) = 2 × 10.
    assert _bonus(db, cenario["ana"]) == 20.0
    # Sofia: 2025 às 8h, quando estudava de manhã (o turno de 2026 também é manhã).
    assert _bonus(db, cenario["sofia"]) == 10.0
    # João: 2024 sem matrícula na escola → o turno atual (manhã), como antes: só as 9h.
    assert _bonus(db, cenario["joao"]) == 10.0


def test_simulador_usa_o_mesmo_turno_do_ano(db, cenario):
    """O motor e o simulador somam o bônus pela MESMA função."""
    escola = cenario["escola"]
    contexto = scoring._carregar_contexto(db, escola.id)
    _, _, matriculas, _matific, _elefante, pontos_dif = contexto
    _, bonus = scoring.pontos_dif_com_bonus(db, escola.id, matriculas, pontos_dif)
    assert bonus == {cenario["ana"].id: 20.0, cenario["sofia"].id: 10.0,
                     cenario["joao"].id: 10.0}


def test_turno_atual_sem_janela_nao_apaga_o_bonus_do_ano_em_que_tinha(db, cenario):
    """Turma atual integral (sem janela): a leitura de 2025, quando a criança estudava
    de manhã, continua sendo da escola; a de hoje não tem janela."""
    escola, sofia = cenario["escola"], cenario["sofia"]
    integral = _turma(db, escola, "3º Ano Integral Fictício", 2026, "integral")
    mat = db.execute(select(Matricula).where(Matricula.aluno_id == sofia.id,
                                             Matricula.ano_letivo == 2026)).scalar_one()
    mat.turma_id = integral.id
    _ler(db, escola, sofia, datetime.combine(SEG_2026, time(9, 0)), 99)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    db.expire_all()
    assert _bonus(db, sofia) == 10.0
