from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.models import (
    Aluno,
    Escola,
    Leitura,
    Livro,
    Matricula,
    Nota,
    Professor,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.schemas import DashboardOut, EscolaOut, RankingItemOut
from app.services import periodos, scoring
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Ranking e Dashboard"])


def _ranking(db: Session, escola_id: int, ano: int, turma_id=None, ano_escolar=None, limite=None):
    consulta = (
        select(Nota, Aluno, Turma)
        .join(Aluno, Nota.aluno_id == Aluno.id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id) & (Matricula.ano_letivo == ano))
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Nota.escola_id == escola_id, Nota.ano_letivo == ano)
        .order_by(Nota.posicao)
    )
    if turma_id:
        consulta = consulta.where(Turma.id == turma_id)
    if ano_escolar:
        consulta = consulta.where(Turma.ano_escolar == ano_escolar)
    if limite:
        consulta = consulta.limit(limite)
    return [
        RankingItemOut(
            posicao=nota.posicao or 0,
            aluno_id=aluno.id,
            nome=aluno.nome,
            turma=turma.nome,
            ano_escolar=turma.ano_escolar,
            nota_matific=nota.nota_matific,
            nota_elefante=nota.nota_elefante,
            nota_geral=nota.nota_geral,
        )
        for nota, aluno, turma in db.execute(consulta).all()
    ]


@router.get("/ranking", response_model=list[RankingItemOut])
def ranking_geral(
    escola_id: int = Depends(escola_autorizada),
    turma_id: int | None = Query(default=None),
    ano_escolar: str | None = Query(default=None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Ranking Geral com filtros por turma e série (PRD §63)."""
    escola = db.get(Escola, escola_id)
    return _ranking(db, escola_id, escola.ano_letivo_ativo, turma_id, ano_escolar)


@router.get("/ranking/leitura", response_model=list[dict])
def ranking_leitura(
    escola_id: int = Depends(escola_autorizada),
    periodo: str = Query(default="tudo"),
    inicio: str | None = Query(default=None),
    fim: str | None = Query(default=None),
    turma_id: int | None = Query(default=None),
    ano_escolar: str | None = Query(default=None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Ranking de LEITURA por PERÍODO: livros lidos, pontos de dificuldade e
    tempo somados apenas no intervalo escolhido — base do "melhor leitor da
    semana/mês/bimestre" e de premiações por maior quantidade/dificuldade."""
    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo
    try:
        ini, fim_dt, _ = periodos.resolver(
            periodo, date.today(), ano,
            periodos._parse_data(inicio), periodos._parse_data(fim))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Data inválida (use AAAA-MM-DD).") from exc

    consulta = (
        select(Leitura.aluno_id, Livro.nivel_codigo, Leitura.tempo_leitura_min,
               Aluno.nome, Turma.nome, Turma.ano_escolar)
        .join(Livro, Leitura.livro_id == Livro.id)
        .join(Aluno, Aluno.id == Leitura.aluno_id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id) & (Matricula.ano_letivo == ano))
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Aluno.escola_id == escola_id, Aluno.status == "ativo")
    )
    if ini is not None:
        consulta = consulta.where(Leitura.data >= ini)
    if fim_dt is not None:
        consulta = consulta.where(Leitura.data <= fim_dt)
    if turma_id:
        consulta = consulta.where(Turma.id == turma_id)
    if ano_escolar:
        consulta = consulta.where(Turma.ano_escolar == ano_escolar)

    pontos_map = scoring.pontos_por_codigo(db, escola_id)
    agg: dict[int, dict] = {}
    for aluno_id, codigo, tempo, nome, turma_nome, serie in db.execute(consulta).all():
        item = agg.setdefault(aluno_id, {
            "aluno_id": aluno_id, "nome": nome, "turma": turma_nome,
            "ano_escolar": serie, "livros": 0, "pontos": 0.0, "tempo_leitura_min": 0,
        })
        item["livros"] += 1
        item["pontos"] += pontos_map.get((codigo or "").upper(), 0.0)
        item["tempo_leitura_min"] += tempo or 0

    itens = sorted(agg.values(),
                   key=lambda x: (x["pontos"], x["livros"], x["tempo_leitura_min"]),
                   reverse=True)
    for posicao, item in enumerate(itens, start=1):
        item["posicao"] = posicao
        item["pontos"] = round(item["pontos"], 2)
    return itens


@router.post("/recalcular")
def recalcular(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    total = scoring.recalcular_escola(db, escola_id)
    registrar(db, "notas.recalculadas", escola_id=escola_id, usuario_id=usuario.id,
              detalhes={"alunos": total})
    db.commit()
    return {"mensagem": f"Notas recalculadas para {total} alunos."}


def montar_dashboard(db: Session, escola_id: int) -> DashboardOut:
    """Indicadores do painel inicial (PRD §19, §48).

    Extraído do endpoint para ser reutilizado pela sincronização mobile.
    """
    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo

    total_alunos = db.execute(
        select(func.count(func.distinct(Matricula.aluno_id)))
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .where(Matricula.escola_id == escola_id, Matricula.ano_letivo == ano, Aluno.status == "ativo")
    ).scalar_one()
    total_turmas = db.execute(
        select(func.count(Turma.id)).where(Turma.escola_id == escola_id, Turma.ano_letivo == ano)
    ).scalar_one()
    total_professores = db.execute(
        select(func.count(Professor.id)).where(Professor.escola_id == escola_id)
    ).scalar_one()

    # Estado atual = snapshot mais recente de cada aluno
    sub_m = (
        select(SnapshotMatific.aluno_id, func.max(SnapshotMatific.id).label("max_id"))
        .where(SnapshotMatific.escola_id == escola_id)
        .group_by(SnapshotMatific.aluno_id)
        .subquery()
    )
    total_atividades = db.execute(
        select(func.coalesce(func.sum(SnapshotMatific.atividades), 0))
        .join(sub_m, SnapshotMatific.id == sub_m.c.max_id)
    ).scalar_one()

    sub_e = (
        select(SnapshotElefante.aluno_id, func.max(SnapshotElefante.id).label("max_id"))
        .where(SnapshotElefante.escola_id == escola_id)
        .group_by(SnapshotElefante.aluno_id)
        .subquery()
    )
    total_livros, tempo_total = db.execute(
        select(
            func.coalesce(func.sum(SnapshotElefante.livros_unicos), 0),
            func.coalesce(func.sum(SnapshotElefante.tempo_leitura_min), 0),
        ).join(sub_e, SnapshotElefante.id == sub_e.c.max_id)
    ).one()

    media_geral = db.execute(
        select(func.coalesce(func.avg(Nota.nota_geral), 0.0)).where(
            Nota.escola_id == escola_id, Nota.ano_letivo == ano
        )
    ).scalar_one()

    return DashboardOut(
        escola=EscolaOut.model_validate(escola),
        total_alunos=total_alunos,
        total_turmas=total_turmas,
        total_professores=total_professores,
        total_atividades=int(total_atividades),
        total_livros=int(total_livros),
        tempo_leitura_min=int(tempo_total),
        media_geral=round(float(media_geral), 2),
        top10=_ranking(db, escola_id, ano, limite=10),
    )


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    return montar_dashboard(db, escola_id)
