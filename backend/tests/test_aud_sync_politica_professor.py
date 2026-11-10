"""Política "bloquear" e a conta do professor que a coleta do Elefante informa.

Com "bloquear" a escola declara que a plataforma NÃO é fonte de cadastro: a
coleta não cria ficha de criança nem move matrícula — e também não pode criar
conta de login de professor a partir do texto ``teachers`` do relatório, nem pôr
esse nome como TITULAR da turma (o vínculo que dá ao professor acesso às crianças
pelo RBAC). Só avisa no registro da coleta, sem o nome da pessoa.

Com "permitir" (o padrão) a coleta continua criando a conta e o titular, como em
``test_sync_conta_professor``. Dados fictícios; nada sai para a internet.
"""
import json

from sqlalchemy import select

from app.models import Professor, Usuario
from app.services import politica_sync, professores
from app.sync import orchestrator
from app.sync.interfaces import ArquivoObtido, Contexto


def _sincronizar(db, escola, professor_txt, monkeypatch) -> list[tuple[str, str, str]]:
    """Roda o orquestrador REAL com um relatório de turma do Elefante (JSON da API)
    e devolve o registro técnico da coleta como (etapa, nível, mensagem)."""
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)
    registro: list[tuple[str, str, str]] = []
    payload = {"courseSchoolDescriptors": {"courseName": "3º Ano A",
                                           "teachers": professor_txt},
               "students": [{"studentId": 1, "studentName": "Ana Beatriz Souza",
                             "totalBooksRead": 42}]}
    orchestrator.aplicar_arquivo(
        db, escola,
        ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                      nome_arquivo="e.json", plataforma="elefante",
                      content_type=orchestrator.CT_ELEFANTE_API, formato_hint="resumo"),
        usuario_id=None, recalcular=False,
        contexto=Contexto(escola_id=escola.id, execucao_id=None,
                          log=lambda etapa, nivel, msg: registro.append((etapa, nivel, msg))))
    db.expire_all()
    return registro


def _bloquear(db, escola_id):
    politica_sync.definir(db, escola_id, politica_sync.BLOQUEAR)
    db.commit()
    assert politica_sync.pode_criar_aluno(db, escola_id) is False


def test_bloquear_nao_cria_conta_de_professor_nem_titular(db, escola_completa, monkeypatch):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    _bloquear(db, escola.id)
    contas_antes = db.query(Usuario).count()
    profs_antes = db.query(Professor).count()

    registro = _sincronizar(db, escola, "Nome Vindo Da Plataforma", monkeypatch)

    assert db.execute(select(Usuario).where(
        Usuario.username == "NomePlataforma")).scalars().all() == [], (
        "com 'bloquear' a coleta criou conta de professor a partir do texto da plataforma")
    assert db.query(Usuario).count() == contas_antes
    assert db.query(Professor).count() == profs_antes
    db.refresh(turma)
    assert turma.professor_id is None, (
        "com 'bloquear' a coleta pôs o nome da plataforma como titular da turma")

    # Avisa no registro (sem o nome da pessoa) e diz o que fazer.
    avisos = [m for etapa, nivel, m in registro if etapa == "professores"]
    assert len(avisos) == 1, registro
    [(_, nivel, aviso)] = [r for r in registro if r[0] == "professores"]
    assert nivel == "warn"
    assert "Usuários" in aviso and "3º Ano A" in aviso
    assert "Nome Vindo" not in aviso and "NomePlataforma" not in aviso
    assert "criada(s) automaticamente" not in aviso


def test_bloquear_nao_poe_professor_ja_cadastrado_como_titular(db, escola_completa,
                                                                monkeypatch):
    """A plataforma não matricula: nem o professor que JÁ existe (casado pelo nome)
    vira titular pela coleta — o vínculo é feito pela gestão."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    prof, _ = professores.garantir_professor(db, escola.id, "Iolanda Sint Barreto")
    db.commit()
    _bloquear(db, escola.id)

    registro = _sincronizar(db, escola, "IOLANDA SINT BARRETO", monkeypatch)

    db.refresh(turma)
    assert turma.professor_id is None
    assert any(etapa == "professores" and nivel == "warn" for etapa, nivel, _ in registro)


def test_permitir_continua_criando_a_conta_e_o_titular(db, escola_completa, monkeypatch):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    assert politica_sync.pode_criar_aluno(db, escola.id) is True     # padrão

    registro = _sincronizar(db, escola, "Marisa Sint Quintela", monkeypatch)

    conta = db.execute(select(Usuario).where(
        Usuario.username == "MarisaQuintela")).scalar_one()
    assert (conta.status, conta.cargo) == ("ativo", "professor")
    db.refresh(turma)
    prof = db.execute(select(Professor).where(Professor.email == conta.email)).scalar_one()
    assert turma.professor_id == prof.id
    assert any(etapa == "professores" and nivel == "info" for etapa, nivel, _ in registro)
