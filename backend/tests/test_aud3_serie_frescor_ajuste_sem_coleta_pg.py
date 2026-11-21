"""REV3-SERIE-1 no PostgreSQL: com a coleta parada, o ajuste manual da criança que a coleta não
trouxe não vira a data do dado da escola (``frescor_ranking._datas_por_escola``: a última coleta
da escola decide), como no SQLite (``test_aud3_serie_frescor_ajuste_sem_coleta.py``).

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud3_serie_frescor_ajuste_sem_coleta_pg.py -m postgres

Dados fictícios.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models import Aluno, Escola, Importacao, Matricula, SnapshotMatific, Turma
from app.services import frescor_ranking
from tests.test_fusao_trava_escola_pg import motor_pg, pytestmark  # noqa: F401


def _retrato(db, escola_id, aluno_id, quando, tipo):
    imp = Importacao(escola_id=escola_id, plataforma="matific", tipo=tipo, qtd_alunos=1)
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                           data_referencia=quando, atividades=50, estrelas=200,
                           pontuacao_media=4.0))


def test_ajuste_da_crianca_sem_coleta_nao_renova_a_escola_no_postgres(motor_pg):  # noqa: F811
    with Session(motor_pg) as db:
        escola = Escola(nome="ESCOLA FICTICIA FRESCOR SEM COLETA PG", ano_letivo_ativo=2026)
        db.add(escola)
        db.flush()
        turma = Turma(escola_id=escola.id, nome="3º Ano A", ano_escolar="3º Ano",
                      ano_letivo=2026)
        db.add(turma)
        db.flush()
        alunos = []
        for nome in ("Ana Ficticia Sem Coleta PG", "Bia Ficticia Sem Coleta PG",
                     "Caio Ficticio Sem Coleta PG"):
            aluno = Aluno(escola_id=escola.id, nome=nome)
            db.add(aluno)
            db.flush()
            db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                             ano_letivo=2026))
            alunos.append(aluno)
        for aluno in alunos[1:]:
            _retrato(db, escola.id, aluno.id, datetime(2026, 10, 22, 12), "api")
        # A Ana não veio na coleta: só o ajuste manual de hoje.
        _retrato(db, escola.id, alunos[0].id, datetime(2026, 11, 11, 12), "manual")
        db.commit()
        bloco = frescor_ranking.frescor_da_escola(
            db, escola, date(2026, 11, 11))["dimensoes"]["matematica"]
        assert (bloco["estado"], bloco["dado_mais_recente_em"], bloco["dado_mais_antigo_em"],
                bloco["dias_desde_dado"], bloco["alunos_com_dado"],
                bloco["alunos_com_dado_antigo"]) == \
            ("desatualizado", "2026-10-22", "2026-10-22", 20, 3, 2)
        assert bloco["ajuste_manual_mais_recente_em"] == "2026-11-11"
