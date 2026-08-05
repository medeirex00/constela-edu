"""Item 4 — a sincronização automática NÃO cria turma que não existe no cadastro da
escola (turma-fantasma). Caso EMEF Prof. Jorge Passos: a escola tem 4ºA/4ºB mas o
relatório da plataforma trazia 4ºC/4ºD, e o sistema as criava. Com
permitir_criar_turma=False (sync), a turma desconhecida vira aviso e nenhum aluno é
criado nela. A turma EXISTENTE continua sendo reaproveitada (regressão do b273824), e
a importação manual (permitir_criar_turma=True, default) mantém o opt-in de criar.
"""
from types import SimpleNamespace

from sqlalchemy import func, select

from app.models import Aluno, Escola, Matricula, Turma
from app.routers.importacoes import _resolver_aluno


def _linha(nome, turma_nome):
    return SimpleNamespace(nome=nome, aluno_id=None, criar_em_turma_id=None,
                           criar_em_turma_nome=turma_nome, numero_chamada=None,
                           dados={})


def _escola_jorge_passos(db):
    esc = Escola(nome="EMEF Prof. Jorge Passos", ano_letivo_ativo=2026, status="ativa")
    db.add(esc)
    db.flush()
    for nome, ae in [("4ºA", "4º Ano"), ("4ºB", "4º Ano")]:
        db.add(Turma(escola_id=esc.id, nome=nome, ano_escolar=ae,
                     ano_letivo=2026, status="ativa"))
    db.commit()
    return esc


def _conta_turmas(db, esc_id):
    return db.execute(select(func.count()).select_from(Turma)
                      .where(Turma.escola_id == esc_id)).scalar_one()


def _conta_alunos(db, esc_id):
    return db.execute(select(func.count()).select_from(Aluno)
                      .where(Aluno.escola_id == esc_id)).scalar_one()


def test_sync_nao_cria_turma_inexistente(db):
    """4ºC não existe na Jorge Passos → a sync NÃO cria a turma nem o aluno; avisa."""
    esc = _escola_jorge_passos(db)
    turmas_antes = _conta_turmas(db, esc.id)
    avisos: list[str] = []

    r = _resolver_aluno(db, esc.id, 2026, _linha("JOAO DA SILVA", "4ºC"),
                        avisos, {}, {}, permitir_criar_turma=False)

    assert r is None                                       # aluno NÃO criado
    assert _conta_turmas(db, esc.id) == turmas_antes       # 4ºC NÃO criada
    assert _conta_alunos(db, esc.id) == 0
    assert any("não existe no cadastro" in a for a in avisos)   # aviso p/ análise


def test_sync_matricula_em_turma_existente(db):
    """Turma que EXISTE (4ºA, mesmo no formato longo da plataforma) → reaproveita e
    cria o aluno nela — a sincronização legítima segue funcionando."""
    esc = _escola_jorge_passos(db)
    turmas_antes = _conta_turmas(db, esc.id)

    r = _resolver_aluno(db, esc.id, 2026,
                        _linha("MARIA SOUZA", "4 ANO A INTEGRAL"),
                        [], {}, {}, permitir_criar_turma=False)

    assert r is not None                                   # aluno criado
    assert _conta_turmas(db, esc.id) == turmas_antes       # nenhuma turma nova
    turma_4a = db.execute(select(Turma).where(
        Turma.escola_id == esc.id, Turma.nome == "4ºA")).scalar_one()
    mat = db.execute(select(Matricula).where(
        Matricula.aluno_id == r.id)).scalar_one()
    assert mat.turma_id == turma_4a.id                     # matriculado na 4ºA real


def test_import_manual_cria_turma_com_opt_in(db):
    """Importação MANUAL (permitir_criar_turma=True, o default) ainda cria a turma —
    é o opt-in explícito do gestor, não a criação silenciosa da sync."""
    esc = _escola_jorge_passos(db)
    turmas_antes = _conta_turmas(db, esc.id)

    r = _resolver_aluno(db, esc.id, 2026, _linha("PEDRO LIMA", "4ºD"),
                        [], {}, {})                        # default = True

    assert r is not None
    assert _conta_turmas(db, esc.id) == turmas_antes + 1   # 4ºD criada (opt-in)
