"""S_G_AJUSTE-1 (Análise) no PostgreSQL: o corte do ajuste manual do Elefante desmentido
nas questões (``analise.plataformas._ajuste_desmentido_nas_questoes``: EXISTS correlacionado
com as importações manuais e as "sem questões" em subconsulta) lê as mesmas coletas que no
SQLite (``test_aud3_serie_ajuste_manual_elefante.py``).

    set TEST_DATABASE_URL_PG=postgresql+psycopg://.../constela_test_x
    pytest tests/test_aud3_serie_ajuste_manual_elefante_pg.py -m postgres

Dados fictícios.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models import Aluno, Escola, Importacao, SnapshotElefante
from app.models.plataformas import IMPORTACAO_SEM_QUESTOES
from app.services import relatorios_periodo as rp
from app.services.analise import plataformas as ap
from tests.test_fusao_trava_escola_pg import motor_pg, pytestmark  # noqa: F401


def _retrato(db, escola_id, aluno_id, quando, tentativas, tipo, status="concluida"):
    imp = Importacao(escola_id=escola_id, plataforma="elefante", tipo=tipo, qtd_alunos=1,
                     status=status)
    db.add(imp)
    db.flush()
    db.add(SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                            data_referencia=quando, livros_unicos=10, tempo_leitura_min=100,
                            questoes_tentativas=tentativas,
                            questoes_acertos=tentativas * 4 // 5, livros_por_nivel={"AA": 10}))


def test_ajuste_desmentido_fica_fora_das_questoes_no_postgres(motor_pg):  # noqa: F811
    with Session(motor_pg) as db:
        escola = Escola(nome="ESCOLA FICTICIA AJUSTE ELEFANTE PG", ano_letivo_ativo=2026)
        db.add(escola)
        db.flush()
        ana = Aluno(escola_id=escola.id, nome="Ana Ficticia Ajuste Elefante PG")
        bia = Aluno(escola_id=escola.id, nome="Bia Ficticia Ajuste Elefante PG")
        db.add_all([ana, bia])
        db.flush()
        _retrato(db, escola.id, ana.id, datetime(2026, 6, 8, 12), 100, "api")
        _retrato(db, escola.id, ana.id, datetime(2026, 6, 10, 12), 50, "manual")
        _retrato(db, escola.id, ana.id, datetime(2026, 6, 11, 12), 105, "api")
        # Bia: depois do ajuste só veio a coleta SEM as questões (S9) — o ajuste continua.
        _retrato(db, escola.id, bia.id, datetime(2026, 6, 8, 12), 100, "api")
        _retrato(db, escola.id, bia.id, datetime(2026, 6, 10, 12), 50, "manual")
        _retrato(db, escola.id, bia.id, datetime(2026, 6, 11, 12), 50, "api",
                 status=IMPORTACAO_SEM_QUESTOES)
        db.commit()
        janela = rp.resolver_janela("personalizado", 2026, inicio=date(2026, 6, 11),
                                    fim=date(2026, 6, 11), hoje=date(2026, 11, 11))
        lidas = ap._coletas_das_questoes(db, escola.id, janela)
        assert [r.questoes_tentativas for r in lidas[ana.id]] == [100, 105]
        assert [r.questoes_tentativas for r in lidas[bia.id]] == [50]
