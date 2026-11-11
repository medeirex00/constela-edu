"""G_AJUSTE-1 (Análise) no PostgreSQL: o corte do ajuste manual desmentido
(``analise.plataformas._ajuste_desmentido``, EXISTS correlacionado com EXTRACT(year))
lê os mesmos retratos que no SQLite (``test_aud2_costura_analise_ajuste_manual.py``).

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud2_costura_analise_ajuste_manual_pg.py -m postgres

Dados fictícios.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Aluno, Escola, Importacao, SnapshotMatific
from app.services.analise import plataformas as ap
from tests.test_fusao_trava_escola_pg import motor_pg, pytestmark  # noqa: F401

INICIO = datetime(2026, 6, 11)
FIM = datetime(2026, 6, 11, 23, 59, 59, 999999)


def _retrato(db, escola_id, aluno_id, quando, atividades, tipo):
    imp = Importacao(escola_id=escola_id, plataforma="matific", tipo=tipo, qtd_alunos=1)
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                           data_referencia=quando, atividades=atividades,
                           estrelas=atividades * 4, pontuacao_media=4.0))


def test_ajuste_desmentido_fica_fora_no_postgres(motor_pg):  # noqa: F811
    with Session(motor_pg) as db:
        escola = Escola(nome="ESCOLA FICTICIA ANALISE AJUSTE PG", ano_letivo_ativo=2026)
        db.add(escola)
        db.flush()
        ana = Aluno(escola_id=escola.id, nome="Ana Ficticia Ajuste PG")
        bia = Aluno(escola_id=escola.id, nome="Bia Ficticia Ajuste PG")
        db.add_all([ana, bia])
        db.flush()
        _retrato(db, escola.id, ana.id, datetime(2026, 6, 8, 12), 100, "api")
        _retrato(db, escola.id, ana.id, datetime(2026, 6, 10, 12), 50, "manual")
        _retrato(db, escola.id, ana.id, datetime(2026, 6, 11, 12), 105, "api")
        # Bia: o ajuste sem coleta depois (no ano) continua valendo.
        _retrato(db, escola.id, bia.id, datetime(2026, 6, 8, 12), 100, "api")
        _retrato(db, escola.id, bia.id, datetime(2026, 6, 10, 12), 50, "manual")
        _retrato(db, escola.id, bia.id, datetime(2027, 1, 5, 12), 3, "api")
        db.commit()
        lidos = ap._retratos_essenciais(db, SnapshotMatific, escola.id, ap._CAMPOS_MATIFIC,
                                        INICIO, FIM)
        assert [r.atividades for r in lidos[ana.id]] == [100, 105]
        assert [r.atividades for r in lidos[bia.id]] == [50]
