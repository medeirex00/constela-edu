"""Sync NÃO SUPERVISIONADA: o portão `confiante` do orquestrador, ponta a ponta.

Fecha 2 lacunas de cobertura apontadas na verificação do fluxo de importação:
  * LACUNA A — o gate `confiante` (orchestrator.py) era testado só por uma
    REIMPLEMENTAÇÃO inline do predicado; aqui dirigimos `aplicar_arquivo` de
    verdade com uma linha 'provável' e provamos que NÃO auto-vincula.
  * LACUNA B — não havia teste e2e com HOMÔNIMO real provando que a sync cria um
    novo registro (resolvível em "Fundir duplicatas") em vez de atribuir os
    dados à criança errada.

Ambos passam pelo caminho real: `aplicar_arquivo` → `casar_nomes` → `confirmar`.
Uma regressão que afrouxasse o gate (auto-vincular 'provável') quebraria aqui.
"""
import json

from sqlalchemy import select

from app.models import Aluno, Matricula, Turma
from app.models.plataformas import SnapshotElefante
from app.sync import orchestrator
from app.sync.interfaces import ArquivoObtido, Contexto


def _contexto(escola_id=1):
    return Contexto(escola_id=escola_id, execucao_id=None, log=lambda e, n, m: None)


def _arquivo_elefante(course_name: str, student_name: str) -> ArquivoObtido:
    payload = {
        "courseSchoolDescriptors": {"courseName": course_name},
        "students": [{"studentId": 42, "studentName": student_name,
                      "totalBooksRead": 10, "totalReadTime": 600,
                      "responses": 5, "approvedResponses": 4}],
    }
    return ArquivoObtido(
        conteudo=json.dumps(payload).encode("utf-8"),
        nome_arquivo="elefante.json", plataforma="elefante",
        content_type=orchestrator.CT_ELEFANTE_API, formato_hint="resumo")


def test_sync_provavel_nao_autovincula_e_cria_novo(db, escola_completa, monkeypatch):
    """LACUNA A: um match apenas 'provável' (variação fuzzy do nome) NÃO é
    auto-vinculado ao aluno real na sync automática — vira um novo registro."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]  # "Ana Beatriz Souza"
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)

    # "Ana Beatriz de Souza" ≈ "Ana Beatriz Souza": fuzzy ≥0.80 → 'provável' (via=None).
    arq = _arquivo_elefante("3 ANO A", "Ana Beatriz de Souza")
    orchestrator.aplicar_arquivo(db, escola, arq, usuario_id=None,
                                 recalcular=False, contexto=_contexto(escola.id))

    # A Ana REAL não recebeu o snapshot (nada de misattribution silenciosa).
    assert db.execute(select(SnapshotElefante).where(
        SnapshotElefante.aluno_id == ana.id)).scalars().first() is None
    # O dado foi para um registro NOVO (duplicata resolvível em "Fundir").
    snaps = db.execute(select(SnapshotElefante).where(
        SnapshotElefante.escola_id == escola.id)).scalars().all()
    assert len(snaps) == 1 and snaps[0].aluno_id != ana.id
    novo = db.get(Aluno, snaps[0].aluno_id)
    assert novo.nome == "Ana Beatriz de Souza"


def test_sync_homonimo_ambiguo_nao_atribui_a_crianca_errada(db, escola_completa, monkeypatch):
    """LACUNA B: dois homônimos REAIS em turmas diferentes + relatório numa turma
    que não casa com nenhuma → a sync não atribui a nenhum dos dois; cria um
    terceiro registro (resolvível em "Fundir"), sem roubar dados da criança certa."""
    escola = escola_completa["escola"]
    ano = escola.ano_letivo_ativo
    joao_a = escola_completa["alunos"][1]  # "João Pedro Barbosa" em "3º Ano A"

    # Segundo homônimo real, em outra turma.
    turma_b = Turma(escola_id=escola.id, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=ano)
    db.add(turma_b)
    db.flush()
    joao_b = Aluno(escola_id=escola.id, nome="João Pedro Barbosa")
    db.add(joao_b)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=joao_b.id, turma_id=turma_b.id, ano_letivo=ano))
    db.commit()
    originais = {joao_a.id, joao_b.id}
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)

    # Turma "5 ANO C" não casa com "3º Ano A" nem "4º Ano B" → desempate impossível.
    arq = _arquivo_elefante("5 ANO C", "João Pedro Barbosa")
    orchestrator.aplicar_arquivo(db, escola, arq, usuario_id=None,
                                 recalcular=False, contexto=_contexto(escola.id))

    # NENHUM dos dois homônimos existentes recebeu o dado.
    for aid in originais:
        assert db.execute(select(SnapshotElefante).where(
            SnapshotElefante.aluno_id == aid)).scalars().first() is None
    # O dado ficou num TERCEIRO registro, com o snapshot.
    snaps = db.execute(select(SnapshotElefante).where(
        SnapshotElefante.escola_id == escola.id)).scalars().all()
    assert len(snaps) == 1 and snaps[0].aluno_id not in originais
