"""Auxiliares dos testes ``test_sync_integridade_identidade*`` (frente B, 22/10/2026).

Dados 100% FICTÍCIOS, sem rede e sem navegador: os arquivos que os conectores
entregariam (JSON da API interna do Matific e do Elefante) entram pelo MESMO
caminho da sincronização — ``orchestrator.aplicar_arquivo`` → parser da API →
``/confirmar`` (porta única de identidade) — com a política da escola e os
parâmetros da sync (não cria turma, pode mover matrícula pelo uuid).

Os testes afirmam sobre o BANCO (fichas, matrículas, retratos, identidades,
pendências), não sobre o status da execução — esse é de outra frente.
"""
from __future__ import annotations

import json

from sqlalchemy import func, select

from app.models import (Aluno, IdentidadeExterna, Matricula, RevisaoIdentidade,
                        SnapshotElefante, SnapshotMatific, Turma)
from app.models.plataformas import Leitura
from app.sync import orchestrator
from app.sync.interfaces import ArquivoObtido, Contexto

ANO = 2026


def contexto(escola_id: int) -> Contexto:
    return Contexto(escola_id=escola_id, execucao_id=None, log=lambda *a: None)


def sem_disco(monkeypatch) -> None:
    """A sync arquiva a fonte em disco; nos testes, não."""
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)


def matific(turma: str, alunos: list[dict]) -> ArquivoObtido:
    """UM arquivo do Placar (uma turma), como o ``ConectorMatific`` emite.
    ``alunos`` = [{nome, nome_abrev, uuid, estrelas, atividades}]."""
    payload = {"turma": turma, "periodo_inicio": "", "periodo_fim": "",
               "alunos": [{"turma": turma, **a} for a in alunos]}
    return ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                         nome_arquivo="matific_ficticio.json", plataforma="matific",
                         content_type=orchestrator.CT_MATIFIC_API, formato_hint="resumo")


def elefante_resumo(turma: str, alunos: list[dict], course_id: int = 700001) -> ArquivoObtido:
    """overall-course-report de UMA turma. ``alunos`` = [{studentId, studentName,
    totalBooksRead, ...}]."""
    payload = {"courseId": course_id,
               "courseSchoolDescriptors": {"courseName": turma,
                                           "schoolName": "ESCOLA FICTICIA"},
               "students": [{"totalReadTime": 600, "responses": 4,
                             "approvedResponses": 2, **a} for a in alunos]}
    return ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                         nome_arquivo="elefante_ficticio.json", plataforma="elefante",
                         content_type=orchestrator.CT_ELEFANTE_API, formato_hint="resumo")


def elefante_leituras(turma: str, leituras: list[dict],
                      course_id: int = 700001) -> ArquivoObtido:
    """Histórico de leituras de UMA turma. ``leituras`` = [{nome, studentId,
    bookTitle, lastReadWhen}]."""
    payload = {"courseId": course_id,
               "courseSchoolDescriptors": {"courseName": turma,
                                           "schoolName": "ESCOLA FICTICIA"},
               "leituras": [{"levelName": "D", "totalTimeSpent": 300, **l}
                            for l in leituras]}
    return ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                         nome_arquivo="elefante_leituras_ficticio.json",
                         plataforma="elefante", content_type=orchestrator.CT_ELEFANTE_API,
                         formato_hint="leituras")


def aplicar(db, escola, arquivo: ArquivoObtido) -> dict:
    """Um arquivo pelo caminho da sincronização (o mesmo do ``service.executar``)."""
    resultado = orchestrator.aplicar_arquivo(db, escola, arquivo, usuario_id=None,
                                             recalcular=False,
                                             contexto=contexto(escola.id))
    db.expire_all()
    return resultado


def turma(db, escola_id: int, nome: str, ano_escolar: str, *, status: str = "ativa",
          ano_letivo: int = ANO) -> Turma:
    t = Turma(escola_id=escola_id, nome=nome, ano_escolar=ano_escolar,
              ano_letivo=ano_letivo, status=status)
    db.add(t)
    db.flush()
    return t


def aluno(db, escola_id: int, t: Turma | None, nome: str, *, status: str = "ativo",
          ano_letivo: int = ANO, **campos) -> Aluno:
    a = Aluno(escola_id=escola_id, nome=nome, status=status, **campos)
    db.add(a)
    db.flush()
    if t is not None:
        db.add(Matricula(escola_id=escola_id, aluno_id=a.id, turma_id=t.id,
                         ano_letivo=ano_letivo))
        db.flush()
    return a


def vincular(db, escola_id: int, aluno_id: int, plataforma: str, id_externo: str) -> None:
    db.add(IdentidadeExterna(escola_id=escola_id, aluno_id=aluno_id,
                             plataforma=plataforma, id_externo=str(id_externo)))
    db.flush()


def contar(db, modelo, *condicoes) -> int:
    return db.scalar(select(func.count()).select_from(modelo).where(*condicoes)) or 0


def fichas(db, escola_id: int) -> int:
    return contar(db, Aluno, Aluno.escola_id == escola_id)


def com_nome(db, escola_id: int, nome: str) -> list[Aluno]:
    return list(db.execute(select(Aluno).where(Aluno.escola_id == escola_id,
                                               Aluno.nome == nome)).scalars())


def turmas_de(db, aluno_id: int) -> list[int]:
    return [tid for (tid,) in db.execute(
        select(Matricula.turma_id).where(Matricula.aluno_id == aluno_id)).all()]


def pendentes(db, escola_id: int, motivo: str | None = None) -> list[RevisaoIdentidade]:
    q = select(RevisaoIdentidade).where(RevisaoIdentidade.escola_id == escola_id,
                                        RevisaoIdentidade.status == "pendente")
    if motivo is not None:
        q = q.where(RevisaoIdentidade.motivo == motivo)
    return list(db.execute(q.order_by(RevisaoIdentidade.id)).scalars())


def dono(db, escola_id: int, plataforma: str, id_externo: str) -> int | None:
    return db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.escola_id == escola_id,
        IdentidadeExterna.plataforma == plataforma,
        IdentidadeExterna.id_externo == str(id_externo))).scalars().first()


def snap_matific(db, aluno_id: int) -> SnapshotMatific | None:
    return db.execute(select(SnapshotMatific).where(SnapshotMatific.aluno_id == aluno_id)
                      .order_by(SnapshotMatific.id.desc())).scalars().first()


def snap_elefante(db, aluno_id: int) -> SnapshotElefante | None:
    return db.execute(select(SnapshotElefante).where(SnapshotElefante.aluno_id == aluno_id)
                      .order_by(SnapshotElefante.id.desc())).scalars().first()


def leituras(db, aluno_id: int) -> int:
    return contar(db, Leitura, Leitura.aluno_id == aluno_id)
