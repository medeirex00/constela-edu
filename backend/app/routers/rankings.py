from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import exigir_modulo_da_escola
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.core.tempo import hoje_br
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
from app.services import periodos, permissoes, premiacoes as svc_premiacoes, scoring
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Ranking e Dashboard"])


def _ranking(db: Session, escola_id: int, ano: int, turma_id=None, ano_escolar=None,
             limite=None, turma_ids: list[int] | None = None):
    consulta = (
        select(Nota, Aluno, Turma)
        .join(Aluno, Nota.aluno_id == Aluno.id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id) & (Matricula.ano_letivo == ano))
        .join(Turma, Matricula.turma_id == Turma.id)
        # Aluno.status: nunca exibir aluno arquivado/excluído no ranking (a Nota
        # órfã dele não é apagada no recálculo — filtra-se na leitura).
        .where(Nota.escola_id == escola_id, Nota.ano_letivo == ano,
               Aluno.status == "ativo")
        .order_by(Nota.posicao)
    )
    if turma_id:
        consulta = consulta.where(Turma.id == turma_id)
    if ano_escolar:
        consulta = consulta.where(Turma.ano_escolar == ano_escolar)
    if turma_ids is not None:  # professor: só as turmas dele (posição segue geral)
        consulta = consulta.where(Turma.id.in_(turma_ids))
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
    """Ranking Geral com filtros por turma e série (PRD §63). O PROFESSOR vê o
    ranking na perspectiva DELE: só os alunos das turmas dele, renumerados 1..N
    (a posição global 109/111/… não fazia sentido para uma turma só)."""
    escola = db.get(Escola, escola_id)
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    itens = _ranking(db, escola_id, escola.ano_letivo_ativo, turma_id, ano_escolar,
                     turma_ids=permitidas)
    if permitidas is not None:  # professor: posição RELATIVA aos alunos dele
        for posicao, item in enumerate(itens, start=1):
            item.posicao = posicao
    return itens


@router.get("/ranking/leitura", response_model=list[dict],
            dependencies=[Depends(exigir_modulo_da_escola("leitura"))])
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
            periodo, hoje_br(), ano,
            periodos._parse_data(inicio), periodos._parse_data(fim))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Data inválida (use AAAA-MM-DD).") from exc

    consulta = (
        select(Leitura.aluno_id, Livro.nivel_codigo, Leitura.tempo_leitura_min,
               Aluno.nome, Turma.nome, Turma.ano_escolar, Turma.id)
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
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None:  # professor: só as turmas dele
        consulta = consulta.where(Turma.id.in_(permitidas))

    # Pontuação por CÓDIGO resolvida pela TURMA do aluno (config LIVRE por turma):
    # {turma_id|None: {CODIGO_UPPER: pontos}}. Sem override, cai no padrão (None).
    mapa_turmas = scoring.mapa_pontos_turmas(db, escola_id)
    padrao_pontos = mapa_turmas[None]
    agg: dict[int, dict] = {}
    for aluno_id, codigo, tempo, nome, turma_nome, serie, turma_id in db.execute(consulta).all():
        item = agg.setdefault(aluno_id, {
            "aluno_id": aluno_id, "nome": nome, "turma": turma_nome,
            "ano_escolar": serie, "livros": 0, "pontos": 0.0, "tempo_leitura_min": 0,
        })
        item["livros"] += 1
        pontos_map = mapa_turmas.get(turma_id, padrao_pontos)
        item["pontos"] += pontos_map.get((codigo or "").upper(), 0.0)
        item["tempo_leitura_min"] += tempo or 0

    # No "Todo o histórico" (sem recorte de datas), inclui o TOTAL acumulado do
    # Elefante (SnapshotElefante) — que a sincronização por API popula de forma
    # AGREGADA (livros/tempo por aluno, sem uma linha por livro com data). Sem
    # isso, a aba Leitura ficava vazia para escolas que só têm o import por turma.
    if periodo == "tudo":
        # Snapshot ATUAL por (data_referencia, id) — não por max(id): um import
        # de período antigo (backfill) grava id maior com data menor e NÃO pode
        # virar o estado atual. Mesma régua do ranking/scoring (fonte única).
        ids_atuais_e = scoring.ids_snapshots_atuais(SnapshotElefante, escola_id)
        q_snap = (
            select(SnapshotElefante.aluno_id, SnapshotElefante.livros_unicos,
                   SnapshotElefante.tempo_leitura_min,
                   Aluno.nome, Turma.nome, Turma.ano_escolar)
            .where(SnapshotElefante.id.in_(ids_atuais_e))
            .join(Aluno, Aluno.id == SnapshotElefante.aluno_id)
            .join(Matricula, (Matricula.aluno_id == Aluno.id)
                  & (Matricula.ano_letivo == ano))
            .join(Turma, Matricula.turma_id == Turma.id)
            .where(Aluno.escola_id == escola_id, Aluno.status == "ativo"))
        if turma_id:
            q_snap = q_snap.where(Turma.id == turma_id)
        if ano_escolar:
            q_snap = q_snap.where(Turma.ano_escolar == ano_escolar)
        if permitidas is not None:
            q_snap = q_snap.where(Turma.id.in_(permitidas))
        for aluno_id, livros, tempo, nome, turma_nome, serie in db.execute(q_snap).all():
            item = agg.setdefault(aluno_id, {
                "aluno_id": aluno_id, "nome": nome, "turma": turma_nome,
                "ano_escolar": serie, "livros": 0, "pontos": 0.0,
                "tempo_leitura_min": 0})
            # O snapshot é o TOTAL autoritativo; o ranking por livro (com data) pode
            # ter menos (só livros datados). Fica o MAIOR — sem dupla contagem.
            item["livros"] = max(item["livros"], int(livros or 0))
            item["tempo_leitura_min"] = max(item["tempo_leitura_min"], int(tempo or 0))

    itens = sorted(agg.values(),
                   key=lambda x: (-x["pontos"], -x["livros"],
                                  -x["tempo_leitura_min"], x["nome"].casefold()))
    for posicao, item in enumerate(itens, start=1):
        item["posicao"] = posicao
        item["pontos"] = round(item["pontos"], 2)
    return itens


@router.get("/ranking/matematica", response_model=list[dict],
            dependencies=[Depends(exigir_modulo_da_escola("matematica"))])
def ranking_matematica(
    escola_id: int = Depends(escola_autorizada),
    periodo: str = Query(default="tudo"),
    inicio: str | None = Query(default=None),
    fim: str | None = Query(default=None),
    turma_id: int | None = Query(default=None),
    ano_escolar: str | None = Query(default=None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Ranking de MATEMÁTICA por PERÍODO: estrelas e atividades do Matific
    conquistadas apenas no intervalo escolhido — o espelho do Ranking de
    Leitura para os melhores da matemática. Como o Matific não tem eventos
    individuais datados, o ganho vem dos snapshots (os imports mensais com
    "Intervalo de datas" criam exatamente um ponto por período)."""
    from app.services.evolucao import _delta, _janela, _series_por_aluno

    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo
    try:
        ini, fim_dt, _ = periodos.resolver(
            periodo, hoje_br(), ano,
            periodos._parse_data(inicio), periodos._parse_data(fim))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Data inválida (use AAAA-MM-DD).") from exc

    consulta = (
        select(Aluno.id, Aluno.nome, Turma.nome, Turma.ano_escolar)
        .join(Matricula, (Matricula.aluno_id == Aluno.id) & (Matricula.ano_letivo == ano))
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Aluno.escola_id == escola_id, Aluno.status == "ativo")
    )
    if turma_id:
        consulta = consulta.where(Turma.id == turma_id)
    if ano_escolar:
        consulta = consulta.where(Turma.ano_escolar == ano_escolar)
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None:  # professor: só as turmas dele
        consulta = consulta.where(Turma.id.in_(permitidas))

    series = _series_por_aluno(db, escola_id, SnapshotMatific)
    itens: list[dict] = []
    for aluno_id, nome, turma_nome, serie_escolar in db.execute(consulta).all():
        serie = series.get(aluno_id)
        if not serie:
            continue
        # base_no_periodo=True: o acumulado anterior ao período nunca é
        # atribuído a ele — mesma regra justa das premiações.
        atual, base = _janela(serie, ini, fim_dt, base_no_periodo=True)
        if atual is None:
            continue
        estrelas = _delta(atual, base, "estrelas")
        atividades = _delta(atual, base, "atividades")
        if estrelas == 0 and atividades == 0:
            continue  # sem atividade no período: fora do pódio do período
        # Média DO PERÍODO, derivada dos snapshots (o import acumula a média
        # ponderada por atividades): a acumulada de outra época não pode
        # aparecer num ranking que promete só o intervalo escolhido.
        media_periodo = 0.0
        if atividades > 0:
            base_ativ = base.atividades if base else 0
            base_media = base.pontuacao_media if base else 0.0
            bruta = ((atual.pontuacao_media or 0.0) * atual.atividades
                     - base_media * base_ativ) / atividades
            media_periodo = round(max(0.0, min(5.0, bruta)), 2)
        itens.append({
            "aluno_id": aluno_id, "nome": nome, "turma": turma_nome,
            "ano_escolar": serie_escolar,
            "estrelas": int(estrelas), "atividades": int(atividades),
            "pontuacao_media": media_periodo,
        })

    # Desempate determinístico por nome — a convenção das premiações (_podio).
    itens.sort(key=lambda x: (-x["estrelas"], -x["atividades"],
                              -x["pontuacao_media"], x["nome"].casefold()))
    for posicao, item in enumerate(itens, start=1):
        item["posicao"] = posicao
    return itens


@router.get("/premiacoes", response_model=dict)
def premiacoes(
    escola_id: int = Depends(escola_autorizada),
    periodo: str = Query(default="mes"),
    inicio: str | None = Query(default=None),
    fim: str | None = Query(default=None),
    turma_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Vencedores de cada categoria de premiação, calculados EXCLUSIVAMENTE com
    os dados do período escolhido (melhor leitor, mais livros, mais tempo,
    destaque no Matific)."""
    escola = db.get(Escola, escola_id)
    try:
        ini, fim_dt, rotulo = periodos.resolver(
            periodo, hoje_br(), escola.ano_letivo_ativo,
            periodos._parse_data(inicio), periodos._parse_data(fim))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Data inválida (use AAAA-MM-DD).") from exc
    dados = svc_premiacoes.premiacoes(
        db, escola_id, ini, fim_dt, turma_id,
        turma_ids=permissoes.turmas_permitidas(db, escola_id, usuario))
    dados["periodo"] = {"chave": periodo, "rotulo": rotulo,
                        "inicio": ini.isoformat() if ini else None,
                        "fim": fim_dt.isoformat() if fim_dt else None}
    return dados


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


def montar_dashboard(db: Session, escola_id: int,
                     turma_ids: list[int] | None = None) -> DashboardOut:
    """Indicadores do painel inicial (PRD §19, §48).

    Extraído do endpoint para ser reutilizado pela sincronização mobile.
    `turma_ids` restringe TODOS os números às turmas informadas (professor vê
    o dashboard apenas das turmas designadas a ele)."""
    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo

    consulta_alunos = (
        select(func.count(func.distinct(Matricula.aluno_id)))
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .where(Matricula.escola_id == escola_id, Matricula.ano_letivo == ano, Aluno.status == "ativo")
    )
    consulta_turmas = select(func.count(Turma.id)).where(
        Turma.escola_id == escola_id, Turma.ano_letivo == ano)
    if turma_ids is not None:
        consulta_alunos = consulta_alunos.where(Matricula.turma_id.in_(turma_ids))
        consulta_turmas = consulta_turmas.where(Turma.id.in_(turma_ids))
    total_alunos = db.execute(consulta_alunos).scalar_one()
    total_turmas = db.execute(consulta_turmas).scalar_one()
    total_professores = db.execute(
        select(func.count(Professor.id)).where(Professor.escola_id == escola_id)
    ).scalar_one()

    # Subconjunto de alunos das turmas permitidas (None = escola inteira)
    alunos_sub = None
    if turma_ids is not None:
        alunos_sub = (
            select(Matricula.aluno_id)
            .where(Matricula.escola_id == escola_id,
                   Matricula.ano_letivo == ano,
                   Matricula.turma_id.in_(turma_ids))
        )

    # Estado atual = snapshot mais recente de cada aluno POR (data_referencia,
    # id) — não por max(id). Um import de período antigo (backfill mensal do
    # Matific) grava id maior com data menor; usar max(id) faria os totais do
    # painel divergirem do ranking, que usa esta mesma régua (fonte única).
    ids_atuais_m = scoring.ids_snapshots_atuais(SnapshotMatific, escola_id)
    consulta_atividades = (
        select(func.coalesce(func.sum(SnapshotMatific.atividades), 0))
        .where(SnapshotMatific.id.in_(ids_atuais_m))
    )
    if alunos_sub is not None:
        consulta_atividades = consulta_atividades.where(SnapshotMatific.aluno_id.in_(alunos_sub))
    total_atividades = db.execute(consulta_atividades).scalar_one()

    ids_atuais_e = scoring.ids_snapshots_atuais(SnapshotElefante, escola_id)
    consulta_elefante = (
        select(
            func.coalesce(func.sum(SnapshotElefante.livros_unicos), 0),
            func.coalesce(func.sum(SnapshotElefante.tempo_leitura_min), 0),
        ).where(SnapshotElefante.id.in_(ids_atuais_e))
    )
    if alunos_sub is not None:
        consulta_elefante = consulta_elefante.where(SnapshotElefante.aluno_id.in_(alunos_sub))
    total_livros, tempo_total = db.execute(consulta_elefante).one()

    # Média só dos alunos ATIVOS (JOIN em Aluno): Notas órfãs de arquivados não
    # distorcem a média geral da escola.
    consulta_media = (
        select(func.coalesce(func.avg(Nota.nota_geral), 0.0))
        .join(Aluno, Nota.aluno_id == Aluno.id)
        .where(Nota.escola_id == escola_id, Nota.ano_letivo == ano,
               Aluno.status == "ativo"))
    if alunos_sub is not None:
        consulta_media = consulta_media.where(Nota.aluno_id.in_(alunos_sub))
    media_geral = db.execute(consulta_media).scalar_one()

    top10 = _ranking(db, escola_id, ano, limite=10, turma_ids=turma_ids)
    # Professor: posição RELATIVA às turmas dele (1..N), igual ao Ranking Geral —
    # o Top 10 e a tela de ranking não podem mostrar posições diferentes.
    if turma_ids is not None:
        for posicao, item in enumerate(top10, start=1):
            item.posicao = posicao

    return DashboardOut(
        escola=EscolaOut.model_validate(escola),
        total_alunos=total_alunos,
        total_turmas=total_turmas,
        total_professores=total_professores,
        total_atividades=int(total_atividades),
        total_livros=int(total_livros),
        tempo_leitura_min=int(tempo_total),
        media_geral=round(float(media_geral), 2),
        top10=top10,
    )


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    return montar_dashboard(
        db, escola_id, turma_ids=permissoes.turmas_permitidas(db, escola_id, usuario))
