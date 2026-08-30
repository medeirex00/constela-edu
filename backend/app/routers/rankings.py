from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, false, func, or_, select
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
from app.schemas import (
    AlunoNaoAferidoOut,
    DashboardOut,
    DimensaoNaoAferidaOut,
    EscolaOut,
    NaoAferidosOut,
    RankingItemOut,
    RankingTurnoOut,
)
from app.services import modulos as svc_modulos
from app.services import periodos, permissoes, premiacoes as svc_premiacoes, scoring
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Ranking e Dashboard"])

# Colunas de `notas` por DIMENSÃO. A nota, a marca de aferido e a posição
# carimbada dentro da dimensão — as três gravadas pelo motor no mesmo recálculo.
_COLUNAS_DIMENSAO = {
    "leitura": (Nota.nota_elefante, Nota.aferido_leitura, Nota.posicao_leitura,
                SnapshotElefante),
    "matematica": (Nota.nota_matific, Nota.aferido_matematica,
                   Nota.posicao_matematica, SnapshotMatific),
}


# Rótulo e ordem de APRESENTAÇÃO dos turnos. NÃO define QUAIS turnos existem —
# isso vem sempre do banco (`Turma.turno`). Só formata e ordena os que
# aparecerem; turno desconhecido cai no title-case do valor cru e `None` (turma
# sem turno cadastrado) vai por último. Nada de turma/série hardcoded aqui.
_ROTULO_TURNO = {"manha": "Manhã", "tarde": "Tarde", "noite": "Noite",
                 "integral": "Integral"}
_ORDEM_TURNO = {"manha": 0, "tarde": 1, "noite": 2, "integral": 3}


def _rotulo_turno(turno: str | None) -> str:
    if turno is None:
        return "Sem turno"
    return _ROTULO_TURNO.get(turno, turno.replace("_", " ").strip().title() or turno)


def _ordem_turno(turno: str | None) -> tuple:
    """Chave de ordenação estável dos turnos na apresentação (conhecidos na ordem
    pedagógica, desconhecidos em ordem alfabética, `None` por último)."""
    if turno is None:
        return (2, 0, "")
    return (0, _ORDEM_TURNO.get(turno, 99), turno)


def _exigir_dimensao(db: Session, escola_id: int, dimensao: str) -> None:
    """Valida a dimensão pedida e o CONTRATO da rede (cascata contrato → dado).

    403 e não 404 para módulo não contratado: some a informação de que o
    recurso existe, mas o produto não foi assinado (mesma régua de
    `deps.exigir_modulo_da_escola`, que as rotas de plataforma já usam)."""
    if dimensao not in _COLUNAS_DIMENSAO:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Dimensão inválida. Use uma de: {', '.join(_COLUNAS_DIMENSAO)}.")
    escola = db.get(Escola, escola_id)
    svc_modulos.exigir(svc_modulos.modulos_da_escola(db, escola), dimensao)


def _ranking(db: Session, escola_id: int, ano: int, turma_id=None, ano_escolar=None,
             limite=None, turma_ids: list[int] | None = None,
             dimensao: str | None = None):
    """Lista de ranking de alunos.

    ``dimensao`` ausente = Ranking Geral LEGADO (ordem única por `Nota.posicao`,
    derivada de `nota_geral`), preservado bit a bit enquanto as vitrines e os
    clientes não migrarem.

    ``dimensao`` = ``leitura`` | ``matematica`` = a ordenação OFICIAL da
    Arquitetura 2: **somente os alunos AFERIDOS naquela dimensão** (existe
    snapshot atual da plataforma dela), ordenados pela posição carimbada dentro
    da dimensão. Quem não tem snapshot NÃO entra com zero — sai da lista e
    aparece em `GET /nao-aferidos`.
    """
    coluna_nota = aferido = posicao_dim = None
    if dimensao:
        coluna_nota, aferido, posicao_dim, _ = _COLUNAS_DIMENSAO[dimensao]

    consulta = (
        select(Nota, Aluno, Turma)
        .join(Aluno, Nota.aluno_id == Aluno.id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id) & (Matricula.ano_letivo == ano))
        .join(Turma, Matricula.turma_id == Turma.id)
        # Aluno.status: nunca exibir aluno arquivado/excluído no ranking (a Nota
        # órfã dele não é apagada no recálculo — filtra-se na leitura).
        .where(Nota.escola_id == escola_id, Nota.ano_letivo == ano,
               Aluno.status == "ativo")
    )
    if dimensao:
        # O corte é a marca de AFERIDO (existência de snapshot), nunca `nota > 0`:
        # é o que separa "sem snapshot" (fora) de "snapshot zerado" (dentro, em
        # último, com 0,00).
        consulta = consulta.where(aferido.is_(True)).order_by(
            posicao_dim.asc().nullslast(), coluna_nota.desc(), Aluno.id)
    else:
        consulta = consulta.order_by(Nota.posicao)
    if turma_id:
        consulta = consulta.where(Turma.id == turma_id)
    if ano_escolar:
        consulta = consulta.where(Turma.ano_escolar == ano_escolar)
    if turma_ids is not None:  # professor: só as turmas dele (posição segue geral)
        consulta = consulta.where(Turma.id.in_(turma_ids))
    if limite:
        consulta = consulta.limit(limite)

    itens = []
    for nota, aluno, turma in db.execute(consulta).all():
        item = RankingItemOut(
            posicao=nota.posicao or 0,
            aluno_id=aluno.id,
            nome=aluno.nome,
            turma=turma.nome,
            ano_escolar=turma.ano_escolar,
            nota_matific=nota.nota_matific,
            nota_elefante=nota.nota_elefante,
            nota_geral=nota.nota_geral,
            # Carimbo de AFERIÇÃO, sempre — também na rota legada. As duas
            # colunas de nota acima chegam `0.0` tanto para quem NÃO USA a
            # plataforma quanto para quem usa e ainda não produziu; sem este
            # discriminante o Top 5 do painel (web e app) exibe `0,0` nos dois
            # casos, afirmando desempenho onde só há ausência de dado. O corte
            # é a EXISTÊNCIA do snapshot (`Nota.aferido_*`), nunca `nota > 0`.
            aferido_leitura=bool(nota.aferido_leitura),
            aferido_matematica=bool(nota.aferido_matematica),
        )
        if dimensao:
            # Detalhe gravado pelo motor. Uma nota ainda não recalculada nesta
            # arquitetura não tem o bloco — a lista continua correta (a coluna
            # da nota e a posição vêm do banco), só sem os dados brutos.
            detalhe = (nota.detalhes or {}).get("dimensoes", {}).get(dimensao, {})
            item.dimensao = dimensao
            item.aferido = True
            item.posicao = getattr(nota, posicao_dim.key) or 0
            item.nota = getattr(nota, coluna_nota.key)
            item.dados = detalhe.get("dados") or {}
            item.snapshot_em = detalhe.get("snapshot_em")
            item.adocao = ((nota.detalhes or {}).get("adocao") or {}).get("pct")
        itens.append(item)
    return itens


def _contar_aferidos(db: Session, escola_id: int, ano: int, dimensao: str) -> int:
    """Quantos alunos ATIVOS da escola entraram na ordenação daquela dimensão —
    o denominador da posição ("8º de 21 aferidos em Leitura").

    Mesmos filtros de `_ranking` (ativo + matriculado no ano), para o
    denominador não poder contar alguém que a lista não mostra."""
    _, aferido, _, _ = _COLUNAS_DIMENSAO[dimensao]
    return int(db.execute(
        select(func.count(func.distinct(Nota.id)))
        .join(Aluno, Nota.aluno_id == Aluno.id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id)
              & (Matricula.ano_letivo == ano))
        .where(Nota.escola_id == escola_id, Nota.ano_letivo == ano,
               Aluno.status == "ativo", aferido.is_(True))
    ).scalar_one() or 0)


@router.get("/ranking", response_model=list[RankingItemOut])
def ranking_geral(
    escola_id: int = Depends(escola_autorizada),
    turma_id: int | None = Query(default=None),
    ano_escolar: str | None = Query(default=None),
    dimensao: str | None = Query(
        default=None,
        description="leitura | matematica. Ausente = Ranking Geral (legado)."),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Ranking de desempenho do aluno, com filtros por turma e série (PRD §63).

    Com ``?dimensao=leitura`` ou ``?dimensao=matematica`` devolve o ranking POR
    DIMENSÃO — a ordenação oficial da Arquitetura 2 —, com **somente os alunos
    aferidos naquela dimensão**, ordenados pela nota dela. Cada item traz
    `n_aferidos` (o denominador da posição), os dados brutos da dimensão e a
    adoção do aluno.

    A rota é PARAMETRIZADA em vez de ganhar endpoints novos porque
    `/ranking/leitura` e `/ranking/matematica` já existem e significam **outra
    coisa**: são os rankings de VOLUME NO PERÍODO (pontos de dificuldade e
    estrelas ganhas no intervalo), base das premiações por período. Eles
    continuam intactos.

    Sem ``dimensao``, devolve o Ranking Geral LEGADO (ordem única por
    `nota_geral`), preservado enquanto vitrines e clientes não migram.

    O PROFESSOR vê o ranking na perspectiva DELE: só os alunos das turmas dele,
    renumerados 1..N (a posição global 109/111/… não fazia sentido para uma
    turma só) — e, por consequência, com o `n_aferidos` do escopo dele."""
    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo
    if dimensao:
        _exigir_dimensao(db, escola_id, dimensao)
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    itens = _ranking(db, escola_id, ano, turma_id, ano_escolar,
                     turma_ids=permitidas, dimensao=dimensao)
    if permitidas is not None:  # professor: posição RELATIVA aos alunos dele
        for posicao, item in enumerate(itens, start=1):
            item.posicao = posicao
    if dimensao:
        # Denominador coerente com a posição exibida: global para a gestão
        # (posição carimbada da escola), do escopo para o professor (renumerado).
        total = (len(itens) if permitidas is not None
                 else _contar_aferidos(db, escola_id, ano, dimensao))
        for item in itens:
            item.n_aferidos = total
    return itens


@router.get("/ranking/leitura/turnos", response_model=list[RankingTurnoOut],
            dependencies=[Depends(exigir_modulo_da_escola("leitura"))])
def ranking_leitura_por_turno(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Ranking OFICIAL da competição escolar de leitura, dividido por TURNO.

    Dentro de cada turno (`Turma.turno`, descoberto do banco — nunca hardcoded)
    competem TODOS os alunos ativos do 1º ao 5º ano JUNTOS, ordenados pela MESMA
    ``nota_elefante``: a régua ÚNICA da escola (P90 da escola inteira, A3, sem
    nenhum fator de série). O turno só define QUEM compete; a nota é idêntica
    entre séries, turmas e turnos. A posição REINICIA em 1 a cada turno.

    NÃO confundir com ``/ranking/leitura`` (ranking temporal por pontos brutos do
    período), que continua intacto: ESTE é a competição escolar 0–100 oficial,
    ordenada pela `posicao_leitura` (a ordenação determinística da Arquitetura 2).
    O professor vê só as turmas dele, renumeradas dentro do turno."""
    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo
    coluna_nota, aferido, posicao_dim, _ = _COLUNAS_DIMENSAO["leitura"]

    consulta = (
        select(Nota, Aluno, Turma)
        .join(Aluno, Nota.aluno_id == Aluno.id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id) & (Matricula.ano_letivo == ano))
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Nota.escola_id == escola_id, Nota.ano_letivo == ano,
               Aluno.status == "ativo", aferido.is_(True))
        # A MESMA ordenação determinística da dimensão Leitura (posicao_leitura):
        # nota desc + desempate estável. Filtrar por turno e renumerar preserva a
        # ordem correta DENTRO do turno.
        .order_by(posicao_dim.asc().nullslast(), coluna_nota.desc(), Aluno.id)
    )
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None:  # professor: só as turmas dele
        consulta = consulta.where(Turma.id.in_(permitidas))

    grupos: dict = {}
    vistos: dict = {}
    for nota, aluno, turma in db.execute(consulta).all():
        turno = turma.turno
        vistos.setdefault(turno, set())
        if aluno.id in vistos[turno]:
            continue  # aluno em 2 turmas do MESMO turno entra uma vez só
        vistos[turno].add(aluno.id)
        grupos.setdefault(turno, []).append((nota, aluno, turma))

    saida: list[RankingTurnoOut] = []
    for turno in sorted(grupos, key=_ordem_turno):
        alunos = [
            RankingItemOut(
                posicao=pos, aluno_id=aluno.id, nome=aluno.nome, turma=turma.nome,
                ano_escolar=turma.ano_escolar, turno=turno,
                nota_matific=nota.nota_matific, nota_elefante=nota.nota_elefante,
                nota_geral=nota.nota_geral,
                aferido_leitura=nota.aferido_leitura,
                aferido_matematica=nota.aferido_matematica,
                dimensao="leitura", nota=nota.nota_elefante, aferido=True,
            )
            for pos, (nota, aluno, turma) in enumerate(grupos[turno], start=1)
        ]
        saida.append(RankingTurnoOut(turno=turno, turno_rotulo=_rotulo_turno(turno),
                                     total=len(alunos), alunos=alunos))
    return saida


@router.get("/nao-aferidos", response_model=NaoAferidosOut)
def nao_aferidos(
    escola_id: int = Depends(escola_autorizada),
    turma_id: int | None = Query(default=None),
    ano_escolar: str | None = Query(default=None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Quem AINDA NÃO FOI AFERIDO, por dimensão — visão OPERACIONAL.

    Não é ranking e não é competição: não tem nota, não tem posição e não tem
    ordem de mérito. É a contrapartida obrigatória do corte "ausência não é
    zero": ao sair do ranking, a criança sem dado **não pode sumir da tela** —
    ela é justamente quem o professor e a coordenação precisam ver.

    Três listas: sem Leitura, sem Matemática e sem NENHUMA das dimensões
    contratadas (adoção 0%). Só dimensões contratadas aparecem — ninguém é "não
    aferido" num produto que a rede não comprou.

    Escopo idêntico ao do ranking: o professor vê só as turmas dele; a
    Secretaria (que não enxerga PII de criança) recebe as listas vazias pelo
    mesmo mecanismo — `turmas_permitidas` devolve lista vazia para ela.
    """
    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    contratadas = scoring.dimensoes_contratadas(db, escola)

    # Parte das MATRÍCULAS (o conjunto pontuado), não de `notas`: o aluno que
    # nunca entrou num recálculo não tem linha de nota e é exatamente quem mais
    # precisa aparecer aqui. LEFT JOIN, portanto.
    consulta = (
        select(Aluno.id, Aluno.nome, Turma.nome, Turma.ano_escolar,
               Nota.aferido_leitura, Nota.aferido_matematica)
        .select_from(Matricula)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .join(Turma, Matricula.turma_id == Turma.id)
        .outerjoin(Nota, (Nota.aluno_id == Aluno.id)
                   & (Nota.escola_id == escola_id) & (Nota.ano_letivo == ano))
        .where(Matricula.escola_id == escola_id, Matricula.ano_letivo == ano,
               Aluno.status == "ativo")
        .order_by(Turma.nome, Aluno.nome)
    )
    if turma_id:
        consulta = consulta.where(Turma.id == turma_id)
    if ano_escolar:
        consulta = consulta.where(Turma.ano_escolar == ano_escolar)
    if permitidas is not None:
        consulta = consulta.where(Turma.id.in_(permitidas))

    faltantes: dict[str, list[AlunoNaoAferidoOut]] = {d: [] for d in contratadas}
    aferidos: dict[str, int] = {d: 0 for d in contratadas}
    sem_nenhuma: list[AlunoNaoAferidoOut] = []
    total = 0
    for aluno_id, nome, turma_nome, serie, af_leitura, af_matematica in db.execute(consulta).all():
        total += 1
        marca = {"leitura": bool(af_leitura), "matematica": bool(af_matematica)}
        item = AlunoNaoAferidoOut(aluno_id=aluno_id, nome=nome, turma=turma_nome,
                                  ano_escolar=serie)
        for dimensao in contratadas:
            if marca[dimensao]:
                aferidos[dimensao] += 1
            else:
                faltantes[dimensao].append(item)
        if not any(marca[d] for d in contratadas):
            sem_nenhuma.append(item)

    return NaoAferidosOut(
        contratadas=contratadas,
        total_alunos=total,
        dimensoes=[
            DimensaoNaoAferidaOut(
                dimensao=dimensao,
                plataforma=scoring.DIMENSOES[dimensao],
                n_aferidos=aferidos[dimensao],
                total=total,
                alunos=faltantes[dimensao],
            )
            for dimensao in contratadas
        ],
        sem_nenhuma=sem_nenhuma,
    )


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


def _desempenho_da_escola(db: Session, escola_id: int, ano: int,
                          contratadas: list[str], alunos_sub) -> dict:
    """Desempenho POR DIMENSÃO + cobertura da escola, numa consulta só.

    Cada média é calculada **somente sobre os alunos aferidos naquela
    dimensão** — a mesma régua de `rede._medias_por_plataforma` ("só quem tem
    dado da plataforma entra na média"). O corte é a EXISTÊNCIA do snapshot,
    **nunca** `nota > 0`:

      * sem snapshot    → ausência: fica FORA da média (nunca houve o que medir);
      * snapshot zerado → zero LEGÍTIMO: entra e pesa ("usa e ainda não produziu").

    Os dois valem 0,0 na coluna da nota e são estados diferentes; trocar o corte
    por `nota > 0` juntaria os dois e maquiaria a escola — é o erro que
    `rede.py:123-125` proíbe com todas as letras.

    O discriminante é o `EXISTS` sobre o snapshot — a DEFINIÇÃO de aferido —, e
    não a coluna `aferido_d`, que é o CACHE dela carimbado pelo recálculo. Os
    dois só divergem enquanto uma escola não foi recalculada, e nesse caso o
    número certo é o do dado, não o do cache. É também o que mantém este painel
    idêntico, número a número, ao cartão da mesma escola no painel da rede
    (`rede._medias_por_plataforma`), que usa exatamente este `EXISTS`.

    As três marcas cabem numa CONSULTA SÓ (agregados condicionais) de propósito:
    uma consulta por dimensão multiplicaria os acessos às tabelas de snapshot
    num endpoint que já é o mais quente do sistema.
    """
    def _marca(dimensao: str):
        if dimensao not in contratadas:
            return false()
        _, _, _, modelo = _COLUNAS_DIMENSAO[dimensao]
        return (select(modelo.id)
                .where(modelo.escola_id == Nota.escola_id,
                       modelo.aluno_id == Nota.aluno_id)
                .exists())

    marcas = {"leitura": _marca("leitura"), "matematica": _marca("matematica")}
    # CONJUNTO = os MATRICULADOS no ano letivo, o mesmo de `total_alunos` (o
    # denominador do Alcance) e o mesmo que o motor pontua. `notas` não é apagada
    # quando o aluno perde a matrícula (o recálculo só grava por cima das linhas
    # do conjunto pontuado): sem este corte, a nota órfã de quem foi desvinculado
    # — ao excluir uma turma antiga, ao sair da escola — seguia pesando na média
    # da dimensão e no `com_dados`, e o Alcance passava de 100% (`com_dados`
    # contava gente que `total_alunos` já não conta). EXISTS, não JOIN: o aluno
    # pode estar em mais de uma turma e o JOIN duplicaria a linha da nota.
    matriculado = (
        select(Matricula.id)
        .where(Matricula.escola_id == Nota.escola_id,
               Matricula.aluno_id == Nota.aluno_id,
               Matricula.ano_letivo == ano)
        .exists()
    )
    consulta = (
        select(
            func.sum(case((marcas["leitura"], 1), else_=0)),
            func.avg(case((marcas["leitura"], Nota.nota_elefante))),
            func.sum(case((marcas["matematica"], 1), else_=0)),
            func.avg(case((marcas["matematica"], Nota.nota_matific))),
            # ALCANCE: tem dado de ALGUMA dimensão CONTRATADA — cascata contrato
            # → dado. Uma rede que desligou a Matemática não pode ser cobrada
            # por snapshots de um produto que ela não assinou.
            # (`rede._alunos_com_qualquer_dado` ainda varre as duas plataformas
            # sem olhar o contrato: achado pré-existente da camada da rede,
            # § Aprovação 10 da spec — não é deste bloco.)
            func.sum(case((or_(marcas["leitura"], marcas["matematica"]), 1),
                          else_=0)),
        )
        .join(Aluno, Nota.aluno_id == Aluno.id)
        .where(Nota.escola_id == escola_id, Nota.ano_letivo == ano,
               Aluno.status == "ativo", matriculado)
    )
    if alunos_sub is not None:
        consulta = consulta.where(Nota.aluno_id.in_(alunos_sub))
    n_l, media_l, n_m, media_m, com_dados = db.execute(consulta).one()
    return {
        "n_leitura": int(n_l or 0),
        "media_leitura": round(float(media_l or 0.0), 1),
        "n_matematica": int(n_m or 0),
        "media_matematica": round(float(media_m or 0.0), 1),
        "com_dados": int(com_dados or 0),
    }


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
    #
    # …e a POPULAÇÃO é a mesma de `total_alunos`: aluno ATIVO e matriculado no
    # ano letivo. O snapshot NÃO é apagado quando a criança é arquivada ou perde
    # a matrícula (ele é imutável, é o histórico) e `ids_snapshots_atuais` varre
    # a escola inteira — sem este corte, os livros/atividades de quem já saiu
    # somavam num cartão ao lado de um total de alunos que já não os contava, e
    # a MESMA escola exibia dois números para "livros lidos" (este e o do cartão
    # da rede / do pôster, que já recortam a coorte). É o mesmo furo que
    # `rede._totais_plataforma_por_escola` fechou com o sintoma
    # `ativos_elefante > total_alunos`. EXISTS (e não JOIN) para não multiplicar
    # a linha do snapshot.
    def _na_coorte(modelo):
        return (
            select(Matricula.id)
            .join(Aluno, Aluno.id == Matricula.aluno_id)
            .where(Matricula.escola_id == escola_id,
                   Matricula.aluno_id == modelo.aluno_id,
                   Matricula.ano_letivo == ano,
                   Aluno.status == "ativo")
            .exists()
        )

    ids_atuais_m = scoring.ids_snapshots_atuais(SnapshotMatific, escola_id)
    consulta_atividades = (
        select(func.coalesce(func.sum(SnapshotMatific.atividades), 0))
        .where(SnapshotMatific.id.in_(ids_atuais_m), _na_coorte(SnapshotMatific))
    )
    if alunos_sub is not None:
        consulta_atividades = consulta_atividades.where(SnapshotMatific.aluno_id.in_(alunos_sub))
    total_atividades = db.execute(consulta_atividades).scalar_one()

    ids_atuais_e = scoring.ids_snapshots_atuais(SnapshotElefante, escola_id)
    consulta_elefante = (
        select(
            func.coalesce(func.sum(SnapshotElefante.livros_unicos), 0),
            func.coalesce(func.sum(SnapshotElefante.tempo_leitura_min), 0),
        ).where(SnapshotElefante.id.in_(ids_atuais_e), _na_coorte(SnapshotElefante))
    )
    if alunos_sub is not None:
        consulta_elefante = consulta_elefante.where(SnapshotElefante.aluno_id.in_(alunos_sub))
    total_livros, tempo_total = db.execute(consulta_elefante).one()

    # DESEMPENHO POR DIMENSÃO — cada média só sobre quem TEM dado da plataforma
    # (ver `_media_da_dimensao`). Era uma média única de `nota_geral` sobre TODOS
    # os alunos ativos, zeros de quem não tem dado incluídos: media_geral media
    # desempenho × cobertura, e a MESMA escola exibia um número aqui e outro no
    # cartão do painel da rede. Agora as duas telas usam a mesma régua.
    contratadas = scoring.dimensoes_contratadas(db, escola)
    desempenho = _desempenho_da_escola(db, escola_id, ano, contratadas, alunos_sub)
    n_leitura, media_leitura = desempenho["n_leitura"], desempenho["media_leitura"]
    n_matematica = desempenho["n_matematica"]
    media_matematica = desempenho["media_matematica"]
    # A "geral" é a média das DIMENSÕES DISPONÍVEIS — não a média das notas
    # gerais dos alunos. Idêntica, número a número, à do cartão da escola no
    # painel da rede (`rede._kpis_da_rede`), inclusive no arredondamento.
    disponiveis = [m for m, n in ((media_leitura, n_leitura),
                                  (media_matematica, n_matematica)) if n]
    media_geral = round(sum(disponiveis) / len(disponiveis), 1) if disponiveis else 0.0

    com_dados = desempenho["com_dados"]
    alcance = round(com_dados / total_alunos * 100, 1) if total_alunos else 0.0

    # LEGADO: o Top 10 continua saindo da ordem única (`Nota.posicao`). Virar
    # "Top 3/10 por dimensão" é DECISÃO DE PRODUTO (vitrine), não conversão
    # mecânica — muda quem sobe ao pódio em toda escola mista.
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
        media_leitura=media_leitura,
        alunos_com_dado_leitura=n_leitura,
        media_matematica=media_matematica,
        alunos_com_dado_matematica=n_matematica,
        media_geral=media_geral,
        alcance=alcance,
        nao_aferidos=max(0, total_alunos - com_dados),
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
