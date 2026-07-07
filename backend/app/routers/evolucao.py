"""Evolução, páginas de turma/escola e comparadores (PRD §67–§78).

Endpoints somente-leitura: toda a informação vem dos snapshots imutáveis.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, get_usuario_atual
from app.models import Aluno, Escola, Usuario
from app.services import evolucao as svc
from app.services import periodos

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Evolução"])


@router.get("/alunos/{aluno_id}/evolucao")
def evolucao_do_aluno(
    aluno_id: int,
    dias: int = Query(default=30, ge=1, le=366),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Linha do tempo completa + variação no período (PRD §67–§71)."""
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    return {
        "aluno_id": aluno_id,
        "nome": aluno.nome,
        "linha_do_tempo": svc.linha_do_tempo(db, escola_id, aluno_id),
        "resumo": svc.resumo_evolucao(db, escola_id, aluno_id, dias),
    }


@router.get("/alunos/{aluno_id}/evolucao-leitura")
def evolucao_leitura_do_aluno(
    aluno_id: int,
    granularidade: str = Query(default="mes", pattern="^(semana|mes|bimestre)$"),
    inicio: str | None = Query(default=None),
    fim: str | None = Query(default=None),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Evolução das LEITURAS no tempo (livros/pontos/tempo/nível médio por
    semana, mês ou bimestre), respeitando o período escolhido."""
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    escola = db.get(Escola, escola_id)
    try:
        preset = "personalizado" if (inicio or fim) else "tudo"
        ini, fim_dt, _ = periodos.resolver(
            preset, date.today(), escola.ano_letivo_ativo,
            periodos._parse_data(inicio), periodos._parse_data(fim))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Data inválida (use AAAA-MM-DD).") from exc
    return svc.evolucao_leitura(db, escola_id, aluno_id, granularidade, ini, fim_dt)


@router.get("/ranking-evolucao")
def ranking_evolucao(
    dias: int = Query(default=30, ge=1, le=366),
    periodo: str | None = Query(default=None),
    inicio: str | None = Query(default=None),
    fim: str | None = Query(default=None),
    turma_id: int | None = Query(default=None),
    ano_escolar: str | None = Query(default=None),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Ranking independente do geral: quem mais cresceu no período (PRD §72).
    Aceita um preset/intervalo (periodo/inicio/fim) ou os últimos N `dias`."""
    escola = db.get(Escola, escola_id)
    ini = None
    fim_dt = None
    if periodo or inicio or fim:
        try:
            ini, fim_dt, _ = periodos.resolver(
                periodo or "personalizado", date.today(), escola.ano_letivo_ativo,
                periodos._parse_data(inicio), periodos._parse_data(fim))
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Data inválida (use AAAA-MM-DD).") from exc
        dados = svc.ranking_evolucao(db, escola_id, ini, fim_dt, turma_id, ano_escolar)
    else:
        dados = svc.ranking_evolucao(db, escola_id, turma_id=turma_id,
                                     ano_escolar=ano_escolar, dias=dias)
    return [
        {
            "posicao": item.posicao,
            "aluno_id": item.aluno_id,
            "nome": item.nome,
            "turma": item.turma,
            "ano_escolar": item.ano_escolar,
            "nota_evolucao": item.nota_evolucao,
            "ganhos": item.ganhos,
        }
        for item in dados
    ]


@router.get("/turmas/{turma_id}/resumo")
def resumo_turma(
    turma_id: int,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Página da turma: médias, totais e indicadores (PRD §76–§77)."""
    resumo = svc.resumo_turma(db, escola_id, turma_id)
    if resumo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Turma não encontrada.")
    return resumo


@router.get("/resumo-escola")
def resumo_escola(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Página da escola: comparação entre turmas (PRD §78)."""
    return svc.resumo_escola(db, escola_id)


@router.get("/comparar")
def comparar(
    tipo_a: str = Query(pattern="^(aluno|turma)$"),
    id_a: int = Query(),
    tipo_b: str = Query(pattern="^(aluno|turma)$"),
    id_b: int = Query(),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Comparador aluno×aluno, aluno×turma e turma×turma (PRD §73–§75)."""
    resultado = svc.comparar(db, escola_id, tipo_a, id_a, tipo_b, id_b)
    if resultado is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Aluno ou turma não encontrado nesta escola.")
    return resultado
