from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, case, false, func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import exigir_modulo_da_escola
from app.core.deps import (escola_autorizada, exigir_papeis,
                           get_usuario_atual, negar_secretaria)
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
from app.services import elegibilidade, frescor_ranking, modulos as svc_modulos
from app.services import grupo_pequeno as svc_grupo
from app.services import (dificuldade_livro, matific_destaque, periodos, permissoes,
                          premiacoes as svc_premiacoes,
                          relatorios as svc_relatorios,
                          relatorios_periodo as svc_relatorio_periodo,
                          relatorios_periodo_pdf as svc_relatorio_pdf,
                          scoring, turnos)
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


# Rótulo e ordem de APRESENTAÇÃO dos turnos vêm da fonte ÚNICA compartilhada
# (`services.turnos`), reusada pelas premiações por turno. Aliases internos para
# não mexer nos call-sites deste módulo.
_rotulo_turno = turnos.rotulo_turno
_ordem_turno = turnos.ordem_turno


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


def _turno_param(turno) -> str | None:
    """Normaliza o parâmetro ``turno``: só uma STRING filtra. Quem chama a
    função da rota DIRETAMENTE em Python (testes, consumidores internos) sem
    passar ``turno`` recebe o sentinela ``Query(None)`` do FastAPI no lugar do
    default — que jamais pode virar um parâmetro SQL. Qualquer coisa que não
    seja ``str`` significa "todos"."""
    return turno if isinstance(turno, str) else None


def _aplicar_turno(consulta, turno: str | None):
    """Filtro de TURNO (eixo ortogonal a turma/série/período) — a MESMA semântica
    de ``services.evolucao.ranking_evolucao`` e das premiações por turno:
    ``None`` = não filtra (todos); ``""`` = turmas SEM turno cadastrado
    ("Sem turno"); senão o turno exato de ``Turma.turno`` (valores do banco,
    nunca hardcoded). A consulta precisa já ter ``Turma`` no FROM/JOIN."""
    turno = _turno_param(turno)
    if turno is None:
        return consulta
    return consulta.where(Turma.turno.is_(None) if turno == "" else Turma.turno == turno)


def _apenas_premiaveis(consulta, db: Session, escola_id: int, ano: int):
    """Corte de ELEGIBILIDADE (1º–5º ano; as Fases não concorrem) — o MESMO para
    a lista (`_ranking`) e para o denominador dela (`_contar_aferidos`). Num
    lugar só para os dois não poderem divergir: "1º de 4" numa lista de 2 nomes.
    A regra em si mora em ``services.elegibilidade``. A consulta precisa já ter
    ``Turma`` no FROM/JOIN."""
    return consulta.where(
        Turma.id.in_(elegibilidade.turmas_premiaveis(db, escola_id, ano)))


def _ranking(db: Session, escola_id: int, ano: int, turma_id=None, ano_escolar=None,
             limite=None, turma_ids: list[int] | None = None,
             dimensao: str | None = None, turno: str | None = None,
             so_com_dado: bool = False):
    """Lista de ranking de alunos.

    ``dimensao`` ausente = Ranking Geral LEGADO (ordem única por `Nota.posicao`,
    derivada de `nota_geral`), preservado bit a bit enquanto as vitrines e os
    clientes não migrarem.

    ``dimensao`` = ``leitura`` | ``matematica`` = a ordenação OFICIAL da
    Arquitetura 2: **somente os alunos AFERIDOS naquela dimensão** (existe
    snapshot atual da plataforma dela), ordenados pela posição carimbada dentro
    da dimensão. Quem não tem snapshot NÃO entra com zero — sai da lista e
    aparece em `GET /nao-aferidos`.

    A nota de PLATAFORMA (`nota_matific` / `nota_elefante`) de módulo que a rede
    não contratou sai nula — vale para todo consumidor (Ranking Geral, Top 10
    do dashboard, pacote do app). A ordenação não muda.

    ``so_com_dado=True`` deixa no LEGADO só quem é aferido em ALGUMA dimensão
    (o corte ``publico._com_algum_dado`` do telão): é o Top 10 do painel, o
    Ranking Geral (``ranking_geral``) e a aba "Ranking Geral" do app — criança
    sem NENHUM dado não ganha posição nem 0,0 (ausência não é zero). O corte vai
    na CONSULTA, antes do ``limite``, para a vaga de quem não tem dado ser
    ocupada por quem tem. A posição exibida segue a carimbada (``Nota.posicao``),
    como no telão (pode pular um número).
    """
    modulos = svc_modulos.modulos_da_escola(db, db.get(Escola, escola_id))
    mostra_matific = "matematica" in modulos
    mostra_elefante = "leitura" in modulos
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
    # AS FASES NÃO CONCORREM. O motor já as tirou da população, então elas não
    # recebem posição nova — mas a Nota ANTIGA delas continua no banco (o
    # recálculo não apaga linha de quem saiu da população, igual ao arquivado
    # logo acima). Sem este corte na LEITURA, aquela linha congelada voltaria a
    # aparecer na lista. O mobile e o painel público herdam de graça: os dois
    # chamam esta mesma função.
    consulta = _apenas_premiaveis(consulta, db, escola_id, ano)
    # `turno` é kwarg NO FIM da assinatura: consumidores externos (app mobile,
    # painel público) chamam posicionalmente e não podem mudar de significado.
    consulta = _aplicar_turno(consulta, turno)
    if so_com_dado:
        # AUSÊNCIA NÃO É ZERO: a EXISTÊNCIA do snapshot (`aferido_*`), nunca
        # `nota > 0` — o retrato zerado (abriu e não produziu) continua.
        consulta = consulta.where(or_(Nota.aferido_leitura.is_(True),
                                      Nota.aferido_matematica.is_(True)))
    if limite:
        consulta = consulta.limit(limite)

    # Dentro de ``scoring.leituras_da_requisicao`` a MESMA lista pedida de novo (o
    # pacote do app do professor: a aba "Ranking Geral" e a posição do Top 10 do
    # painel) sai do banco uma vez. Os itens são refeitos a cada chamada — quem
    # chama os renumera sem mexer na lista de outro.
    memoria = scoring.memoria_da_requisicao(db, "ranking_legado")
    chave = (escola_id, ano, turma_id, ano_escolar, limite,
             None if turma_ids is None else tuple(turma_ids), dimensao, turno,
             so_com_dado)
    if memoria is not None and chave in memoria:
        linhas = memoria[chave]
    else:
        linhas = tuple(db.execute(consulta).all())
        if memoria is not None:
            memoria[chave] = linhas

    itens = []
    for nota, aluno, turma in linhas:
        item = RankingItemOut(
            posicao=nota.posicao or 0,
            aluno_id=aluno.id,
            nome=aluno.nome,
            turma=turma.nome,
            ano_escolar=turma.ano_escolar,
            nota_matific=nota.nota_matific if mostra_matific else None,
            nota_elefante=nota.nota_elefante if mostra_elefante else None,
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

    Mesmos filtros de `_ranking` (ativo + matriculado no ano + turma que
    CONCORRE), para o denominador não poder contar alguém que a lista não
    mostra. Sem o corte de elegibilidade, a Nota antiga de uma criança da
    Educação Infantil (que o recálculo não apaga) entrava no "de N"."""
    _, aferido, _, _ = _COLUNAS_DIMENSAO[dimensao]
    consulta = (
        select(func.count(func.distinct(Nota.id)))
        .join(Aluno, Nota.aluno_id == Aluno.id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id)
              & (Matricula.ano_letivo == ano))
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Nota.escola_id == escola_id, Nota.ano_letivo == ano,
               Aluno.status == "ativo", aferido.is_(True))
    )
    consulta = _apenas_premiaveis(consulta, db, escola_id, ano)
    return int(db.execute(consulta).scalar_one() or 0)


@router.get("/ranking", response_model=list[RankingItemOut])
def ranking_geral(
    escola_id: int = Depends(escola_autorizada),
    turma_id: int | None = Query(default=None),
    ano_escolar: str | None = Query(default=None),
    dimensao: str | None = Query(
        default=None,
        description="leitura | matematica. Ausente = Ranking Geral (legado)."),
    turno: str | None = Query(
        default=None,
        description="Filtra por Turma.turno. Ausente = todos; '' = sem turno; "
                    "senão o turno exato (manha, tarde, noite, integral)."),
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
    turma só) — e, por consequência, com o `n_aferidos` do escopo dele.

    Com ``?turno=`` (manha | tarde | noite | integral | '' = sem turno) a lista
    é recortada pelo turno da turma e, como para o professor, RENUMERADA 1..N
    dentro do recorte, com `n_aferidos` do conjunto filtrado — o turno define
    QUEM compete, nunca a nota (régua única da escola). Sem ``turno`` nada muda:
    a posição continua a carimbada da escola inteira.

    No LEGADO (sem ``dimensao``) recortado (professor e/ou turno), `n_aferidos`
    também vem carimbado com o tamanho do recorte (o denominador da posição
    renumerada); sem recorte segue ``None`` (contrato antigo)."""
    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo
    turno = _turno_param(turno)
    if dimensao:
        _exigir_dimensao(db, escola_id, dimensao)
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    # LEGADO: só quem tem dado de ALGUMA dimensão (o corte do telão e do Top 10).
    # Quem não tem retrato nenhum não ganha posição nem 0,0 — e, no recorte,
    # também não empurra a numeração de quem tem. Por dimensão o corte já é o
    # aferido dela.
    itens = _ranking(db, escola_id, ano, turma_id, ano_escolar,
                     turma_ids=permitidas, dimensao=dimensao, turno=turno,
                     so_com_dado=not dimensao)
    # Posição RELATIVA ao recorte: professor (só as turmas dele) e/ou turno (só
    # as turmas daquele turno). Sem recorte vale a posição carimbada da escola.
    recortado = permitidas is not None or turno is not None
    if recortado:
        for posicao, item in enumerate(itens, start=1):
            item.posicao = posicao
    if dimensao:
        # Denominador coerente com a posição exibida: global para a gestão
        # (posição carimbada da escola), do recorte quando renumerado.
        total = (len(itens) if recortado
                 else _contar_aferidos(db, escola_id, ano, dimensao))
    elif recortado:
        # LEGADO recortado (professor e/ou turno): a posição foi renumerada
        # 1..N dentro do recorte, então o denominador é o tamanho do recorte —
        # sem ele "2º" não diz "de quantos". O legado lista quem tem dado de
        # alguma dimensão (o zero legítimo entra; a ausência, não).
        total = len(itens)
    else:
        # LEGADO sem recorte: contrato antigo preservado (`n_aferidos` ausente).
        total = None
    if total is not None:
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
    # A nota do Matific sai nula com a Matemática fora do plano — a mesma regra
    # de `_ranking` (a rota exige só a Leitura, mas o item leva as duas notas).
    mostra_matific = "matematica" in svc_modulos.modulos_da_escola(db, escola)

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
    # AS FASES NÃO CONCORREM: a mesma régua de `_ranking`. A Nota antiga de uma
    # criança da Educação Infantil (que o recálculo não apaga) não pode voltar
    # a disputar dentro do turno dela.
    consulta = _apenas_premiaveis(consulta, db, escola_id, ano)
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
                nota_matific=nota.nota_matific if mostra_matific else None,
                nota_elefante=nota.nota_elefante,
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


@router.get("/ranking/frescor", response_model=dict)
def ranking_frescor(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """DE QUANDO é o dado por trás dos rankings desta escola, por dimensão.

    O motor ranqueia pelo retrato mais recente de cada aluno sem olhar a idade
    dele; esta rota declara essa idade para a tela pôr um selo com a data e
    avisar quando o dado passou de ``limite_dias``
    (``frescor_ranking.LIMITE_DIAS_DADO_ATUAL``). Ver o módulo para os estados
    (``sem_dados`` / ``desatualizado`` / ``parcial`` / ``em_dia``) — nunca
    "funcionando".

    Rota PRÓPRIA (e não um campo nas listas) porque ``/ranking``,
    ``/ranking/leitura`` e ``/ranking/matematica`` devolvem LISTAS consumidas
    por web, app e telão: um envelope novo quebraria todos. As respostas em
    objeto (``/premiacoes``, ``/ranking/turmas``) trazem o mesmo bloco embutido.

    Só agregados (datas e contagens), nenhum nome. A população é a do ranking
    que o usuário vê: o professor, as turmas dele."""
    escola = db.get(Escola, escola_id)
    return frescor_ranking.frescor_da_escola(
        db, escola, hoje_br(),
        turma_ids=permissoes.turmas_permitidas(db, escola_id, usuario))


def _ordem_turmas(linhas: list[dict]) -> list[dict]:
    """A ORDEM do ranking de turmas — fonte única, aqui no backend.

    Média da matéria (desc) → mais alunos aferidos (desc) → nome (casefold) →
    id da turma. Sem empate na POSIÇÃO: a mesma convenção dos rankings de aluno
    (``premiacoes._ordenar``), em que o último desempate é o id para a ordem não
    variar entre duas requisições iguais. A tela só exibe."""
    linhas.sort(key=lambda t: (-t["media"], -t["n_aferidos"],
                               t["nome"].casefold(), t["turma_id"]))
    for posicao, linha in enumerate(linhas, start=1):
        linha["posicao"] = posicao
    return linhas


@router.get("/ranking/turmas", response_model=dict)
def ranking_turmas(
    escola_id: int = Depends(escola_autorizada),
    dimensao: str = Query(description="leitura | matematica"),
    turno: str | None = Query(default=None,
                              description="Ausente = todos; '' = sem turno; senão o turno exato."),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Ranking de TURMAS por matéria — a ordem e a POSIÇÃO saem daqui.

    Antes a tela pegava ``/resumo-escola`` e ordenava/numerava no navegador
    (com desempate por ``localeCompare``, diferente do backend). Agora a mesma
    média — a do resumo da escola (``services.evolucao.resumo_escola``: só
    sobre os alunos AFERIDOS na matéria, nunca zeros de quem não tem dado) — é
    posta em ordem por :func:`_ordem_turmas`, e a tela só exibe.

    Entram só turmas que CONCORREM (1º–5º ano; as Fases não concorrem) e com
    pelo menos um aluno aferido na matéria. ``turno`` recorta e renumera 1..N,
    como nos rankings de aluno.

    Mesmo acesso do resumo da escola (gestão: ``negar_restrito``) — agregado por
    turma, sem nome de criança. O bloco ``frescor`` diz de quando é o dado.

    SECRETARIA: a turma que o resumo da escola esconde nesta matéria (grupo
    pequeno, ver ``services.grupo_pequeno``) não entra na ordem nem ganha
    posição (a vizinhança no ranking cercaria o número escondido); vai para a
    lista ``ocultas``, sem média, com o motivo. A gestão da escola e o Admin
    Global recebem o ranking de sempre (sem a chave ``ocultas``)."""
    permissoes.negar_restrito(db, escola_id, usuario)
    _exigir_dimensao(db, escola_id, dimensao)
    escola = db.get(Escola, escola_id)
    turno = _turno_param(turno)
    concorrem = set(elegibilidade.turmas_premiaveis(db, escola_id, escola.ano_letivo_ativo))
    secretaria = permissoes.e_secretaria(usuario)
    resumo = svc_grupo.resumo_escola_do_usuario(db, escola_id, usuario)
    turnos_por_id = dict(db.execute(
        select(Turma.id, Turma.turno).where(Turma.escola_id == escola_id,
                                            Turma.ano_letivo == escola.ano_letivo_ativo)
    ).all())
    chave_media, chave_n = (("media_leitura", "n_leitura") if dimensao == "leitura"
                            else ("media_matematica", "n_matematica"))
    linhas = []
    ocultas = []
    for item in resumo["turmas"]:
        turma = item["turma"]
        if turma["id"] not in concorrem or not item.get(chave_n):
            continue
        turno_turma = turnos_por_id.get(turma["id"])
        if turno is not None and (turno_turma is not None if turno == ""
                                  else turno_turma != turno):
            continue
        linha = {
            "turma_id": turma["id"], "nome": turma["nome"],
            "ano_escolar": turma["ano_escolar"], "turno": turno_turma,
            "media": item.get(chave_media) or 0.0, "n_aferidos": item[chave_n],
            "total_alunos": item["total_alunos"],
        }
        oculto = (item.get("oculto") or {}).get(dimensao)
        if oculto:
            ocultas.append({**linha, "media": None, "posicao": None,
                            "grupo_pequeno": oculto["motivo"] == svc_grupo.MOTIVO_GRUPO_PEQUENO,
                            "motivo": oculto["motivo"], "texto": oculto["texto"]})
            continue
        linhas.append(linha)
    resposta = {
        "dimensao": dimensao,
        "itens": _ordem_turmas(linhas),
        # A média é da escola inteira (régua única), então o frescor também.
        "frescor": frescor_ranking.frescor_da_escola(db, escola, hoje_br()),
    }
    if secretaria:
        resposta["ocultas"] = sorted(ocultas, key=lambda t: (t["nome"].casefold(),
                                                             t["turma_id"]))
    return resposta


@router.get("/nao-aferidos", response_model=NaoAferidosOut)
def nao_aferidos(
    escola_id: int = Depends(escola_autorizada),
    turma_id: int | None = Query(default=None),
    ano_escolar: str | None = Query(default=None),
    turno: str | None = Query(default=None,
                              description="Ausente = todos; '' = sem turno; senão o turno exato."),
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
    mesmo mecanismo — `turmas_permitidas` devolve lista vazia para ela. E a
    MESMA população: só as turmas que concorrem (`_apenas_premiaveis`, as Fases
    não entram) — o motor não carimba `aferido_*` para quem não concorre, então
    a Nota congelada de uma Fase contaria como "aferida" (e o "N aferidos" não
    seria o denominador do ranking) e a Fase sem Nota sairia como "sem nenhuma
    dimensão" mesmo usando as duas plataformas.
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
    consulta = _aplicar_turno(consulta, turno)   # mesmo recorte do ranking
    # AS FASES NÃO CONCORREM: a mesma população do ranking e do denominador dele
    # (`_contar_aferidos`).
    consulta = _apenas_premiaveis(consulta, db, escola_id, ano)
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
    turno: str | None = Query(default=None,
                              description="Ausente = todos; '' = sem turno; senão o turno exato."),
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

    # NÍVEL CONGELADO da leitura (``Leitura.nivel_codigo``) e, só quando ele é
    # nulo (leitura anterior a esta versão), o nível ATUAL do livro. Mesma
    # ``coalesce`` do motor (``dificuldade_livro.leituras_por_aluno``): renivelar
    # um livro no catálogo não muda o que o aluno já pontuou nesta tela.
    nivel_efetivo = func.coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)
    consulta = (
        select(Leitura.aluno_id, nivel_efetivo, Leitura.tempo_leitura_min,
               Aluno.nome, Turma.nome, Turma.ano_escolar, Turma.id, Livro.titulo,
               Livro.elefante_id)
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
    consulta = _aplicar_turno(consulta, turno)
    # AS FASES NÃO CONCORREM (base das premiações por período): a mesma régua de
    # `_ranking`, aplicada também ao total do Elefante logo abaixo.
    consulta = _apenas_premiaveis(consulta, db, escola_id, ano)
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None:  # professor: só as turmas dele
        consulta = consulta.where(Turma.id.in_(permitidas))

    # Valor de CADA leitura pela FONTE ÚNICA de dificuldade (v1 global: nível ×
    # ajuste do livro × série do aluno; ou a régua legada da escola personalizada)
    # — a MESMA regra da nota anual e das premiações.
    regra = dificuldade_livro.regra_da_escola(db, escola_id)
    agg: dict[int, dict] = {}
    itens: dict[int, list] = {}          # leituras itemizadas por aluno (p/ reconciliar no "tudo")
    # A turma da LINHA chama-se `turma_da_leitura`, nunca `turma_id`: o laço
    # reusava o nome do PARÂMETRO da rota, e no "Todo o histórico" o filtro do
    # total do Elefante logo abaixo (`if turma_id:`) passava a recortar pela
    # turma da ÚLTIMA leitura do laço — o ranking sem filtro mostrava só uma turma.
    for (aluno_id, codigo, tempo, nome, turma_nome, serie, turma_da_leitura, titulo,
         elefante_id) in db.execute(consulta).all():
        item = agg.setdefault(aluno_id, {
            "aluno_id": aluno_id, "nome": nome, "turma": turma_nome,
            "ano_escolar": serie, "livros": 0, "pontos": 0.0, "tempo_leitura_min": 0,
        })
        item["livros"] += 1
        # Identidade oficial do livro (id do catálogo do Elefante) antes do título.
        item["pontos"] += regra.valor_livro(codigo, titulo, serie, turma_da_leitura,
                                            elefante_id=elefante_id)
        item["tempo_leitura_min"] += tempo or 0
        itens.setdefault(aluno_id, []).append((titulo, codigo, 0, elefante_id))

    # No "Todo o histórico" (sem recorte de datas), inclui o TOTAL acumulado do
    # Elefante (SnapshotElefante) — que a sincronização por API popula de forma
    # AGREGADA (livros/tempo por aluno, sem uma linha por livro com data). Sem
    # isso, a aba Leitura ficava vazia para escolas que só têm o import por turma.
    # Decide pelo INTERVALO resolvido, não pelo texto do preset: "personalizado"
    # ainda sem datas e preset desconhecido também viram "Todo o histórico" em
    # `periodos.resolver` — a mesma condição de `premiacoes._leitura_no_periodo`.
    if ini is None and fim_dt is None:
        # Snapshot ATUAL por (data_referencia, id) — não por max(id): um import
        # de período antigo (backfill) grava id maior com data menor e NÃO pode
        # virar o estado atual. Mesma régua do ranking/scoring (fonte única).
        ids_atuais_e = scoring.ids_snapshots_atuais(SnapshotElefante, escola_id)
        q_snap = (
            select(SnapshotElefante.aluno_id, SnapshotElefante.livros_unicos,
                   SnapshotElefante.tempo_leitura_min,
                   Aluno.nome, Turma.nome, Turma.ano_escolar,
                   SnapshotElefante.livros_por_nivel, Turma.id)
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
        q_snap = _aplicar_turno(q_snap, turno)
        q_snap = _apenas_premiaveis(q_snap, db, escola_id, ano)
        if permitidas is not None:
            q_snap = q_snap.where(Turma.id.in_(permitidas))
        for aluno_id, livros, tempo, nome, turma_nome, serie, por_nivel, tid in db.execute(q_snap).all():
            item = agg.setdefault(aluno_id, {
                "aluno_id": aluno_id, "nome": nome, "turma": turma_nome,
                "ano_escolar": serie, "livros": 0, "pontos": 0.0,
                "tempo_leitura_min": 0})
            # O snapshot é o TOTAL autoritativo; o ranking por livro (com data) pode
            # ter menos (só livros datados). Fica o MAIOR — sem dupla contagem.
            item["livros"] = max(item["livros"], int(livros or 0))
            item["tempo_leitura_min"] = max(item["tempo_leitura_min"], int(tempo or 0))
            # PONTOS pela MESMA reconciliação da nota anual (fonte única): cada
            # leitura itemizada vale a sua; o restante da contagem do snapshot
            # vale o típico do nível. Quem só tem o agregado deixa de valer 0.
            item["pontos"] = regra.pontos_aluno(por_nivel or {}, serie, turma_id=tid,
                                                leituras=itens.get(aluno_id))

    # Último desempate = id do aluno (convenção de ``premiacoes._podio``): dois
    # homônimos empatados não podem trocar de posição entre requisições.
    itens = sorted(agg.values(),
                   key=lambda x: (-x["pontos"], -x["livros"],
                                  -x["tempo_leitura_min"], x["nome"].casefold(),
                                  x["aluno_id"]))
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
    turno: str | None = Query(default=None,
                              description="Ausente = todos; '' = sem turno; senão o turno exato."),
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
    consulta = _aplicar_turno(consulta, turno)
    # AS FASES NÃO CONCORREM: a mesma régua de `_ranking` e das premiações.
    consulta = _apenas_premiaveis(consulta, db, escola_id, ano)
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
        # Contadores do Matific são do ANO: snapshot de outro ano letivo nunca
        # serve de base NEM de estado — SEMPRE, inclusive em "todo o histórico".
        # Antes o filtro só valia com início definido, e o preset padrão
        # (``periodo=tudo``, sem datas) deixava um acumulado de dez/2025 virar o
        # "estado atual" de 2026; agora o preset padrão passa a valer o último
        # snapshot DENTRO do ano letivo, exatamente como o "todo o histórico" das
        # premiações (``matific_destaque.ganho_no_periodo``, que nunca deixou de
        # receber o ano). Quem só tem dado de outro ano sai do ranking (ausência
        # no ano, não zero) — era a divergência entre as duas telas.
        atual, base = _janela(serie, ini, fim_dt, base_no_periodo=True,
                              ano_letivo=ano)
        if atual is None:
            continue
        atividades = _delta(atual, base, "atividades")
        # No máximo 5 estrelas por atividade (o teto das premiações,
        # ``matific_destaque.limitar_estrelas``): estrela digitada sem atividade
        # não ordena o ranking — o mesmo dado sai na mesma ordem nas duas telas.
        estrelas = matific_destaque.limitar_estrelas(
            atividades, _delta(atual, base, "estrelas"))
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
        # Data do retrato que FECHA o ganho deste aluno ("até quando" o número
        # vale). Sem ela, um retrato de três semanas atrás tem a mesma cara de um
        # de ontem. Dia de BRASÍLIA, o mesmo do selo de frescor: a coleta das
        # 22h30 não pode virar "dado de amanhã".
        dia_retrato = frescor_ranking.dia_do_retrato(atual.data_referencia)
        itens.append({
            "aluno_id": aluno_id, "nome": nome, "turma": turma_nome,
            "ano_escolar": serie_escolar,
            "estrelas": int(estrelas), "atividades": int(atividades),
            "pontuacao_media": media_periodo,
            "snapshot_em": dia_retrato.isoformat() if dia_retrato else None,
        })

    # Desempate determinístico por nome e, por último, pelo ID DO ALUNO — a
    # convenção das premiações (``premiacoes._podio``). Sem o id, dois homônimos
    # empatados ficavam à mercê da ordem que o banco devolvesse e podiam trocar
    # de posição entre duas requisições idênticas.
    itens.sort(key=lambda x: (-x["estrelas"], -x["atividades"],
                              -x["pontuacao_media"], x["nome"].casefold(),
                              x["aluno_id"]))
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
    turnos: bool = Query(default=False,
                         description="Quebra os pódios por Turma.turno (só na visão todas as turmas)."),
    limite: int = Query(default=5, ge=1, le=500,
                        description="Quantas linhas por pódio. 5 (padrão) é o cartão da tela; "
                                    "valores maiores servem o ranking completo da MESMA premiação."),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Vencedores de cada categoria de premiação, calculados EXCLUSIVAMENTE com
    os dados do período escolhido (melhor leitor, melhor matemática, mais livros,
    mais tempo). Com ``?turnos=true`` e sem ``turma_id``, devolve também os pódios
    quebrados por TURNO (`turnos: [{turno, turno_rotulo, categorias}]`).

    ``?limite=N`` só aumenta o TAMANHO de cada pódio — mesma coorte, mesma régua,
    mesma ordem, mesmo desempate e as mesmas posições do Top 5, que continua
    sendo o prefixo da lista. Cada categoria traz ``total``, o número de alunos
    premiáveis, para a tela saber se ainda há ranking além do que recebeu.

    Privacidade: com menos de ``MINIMO_ALUNOS_REFERENCIA_MATIFIC`` alunos com
    atividade no período, a régua sai sem ``k`` e as linhas da Melhor Matemática
    saem com ``valor: null`` (o índice, que com estrelas e atividades devolveria
    o ``k``) — em todos os pódios da resposta. A ordem é a mesma."""
    escola = db.get(Escola, escola_id)
    try:
        ini, fim_dt, rotulo = periodos.resolver(
            periodo, hoje_br(), escola.ano_letivo_ativo,
            periodos._parse_data(inicio), periodos._parse_data(fim))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Data inválida (use AAAA-MM-DD).") from exc
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    dados = svc_premiacoes.premiacoes(
        db, escola_id, ini, fim_dt, turma_id,
        turma_ids=permitidas,
        por_turno=turnos, limite=limite,
        # Categoria de módulo não contratado não sai (o módulo não existe p/ a rede).
        modulos=svc_modulos.modulos_da_escola(db, escola))
    dados["periodo"] = {"chave": periodo, "rotulo": rotulo,
                        "inicio": ini.isoformat() if ini else None,
                        "fim": fim_dt.isoformat() if fim_dt else None}
    # DE QUANDO é o dado: um pódio de "outubro" montado com a última coleta de
    # 01/10 parece completo e não é. Mesma população do pódio (o professor, as
    # turmas dele) — ver `frescor_ranking`.
    dados["frescor"] = frescor_ranking.frescor_da_escola(
        db, escola, hoje_br(), turma_ids=permitidas)
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

    O DESEMPENHO (as médias e os ``n_*``) segue mais dois cortes do painel da
    rede, para a identidade acima continuar valendo:

      * MATIFIC É CONTADOR DO ANO: aferido em Matemática é ter snapshot DENTRO do
        ano letivo (``matific_destaque.janela_ano_letivo``) — a definição do
        motor (``scoring.snapshots_matific_do_ano``). Quem só tem coleta do ano
        anterior o motor deixa sem aferição e com 0,0; sem o corte, entrava aqui
        como ZERO na média;
      * AS FASES NÃO CONCORREM: só a matrícula numa turma PREMIÁVEL
        (``services.elegibilidade``) compõe o desempenho. A Nota antiga da
        Educação Infantil (que o motor não atualiza mais) fica fora.

    O ALCANCE (``com_dados``) NÃO recebe esses cortes: é cobertura — quem usa a
    plataforma —, o mesmo conceito de ``rede._alunos_com_qualquer_dado``.
    """
    def _marca(dimensao: str, do_ano: bool = False):
        if dimensao not in contratadas:
            return false()
        _, _, _, modelo = _COLUNAS_DIMENSAO[dimensao]
        consulta = select(modelo.id).where(modelo.escola_id == Nota.escola_id,
                                           modelo.aluno_id == Nota.aluno_id)
        if do_ano and modelo is SnapshotMatific:
            inicio, fim = matific_destaque.janela_ano_letivo(ano)
            consulta = consulta.where(modelo.data_referencia >= inicio,
                                      modelo.data_referencia <= fim)
        return consulta.exists()

    # COBERTURA: tem snapshot da plataforma, de qualquer época.
    marcas = {"leitura": _marca("leitura"), "matematica": _marca("matematica")}
    # DESEMPENHO: aferido (Matific do ano) E matriculado numa turma premiável.
    premiavel = (
        select(Matricula.id)
        .where(Matricula.escola_id == Nota.escola_id,
               Matricula.aluno_id == Nota.aluno_id,
               Matricula.ano_letivo == ano,
               Matricula.turma_id.in_(
                   elegibilidade.turmas_premiaveis(db, escola_id, ano)))
        .exists()
    )
    desempenho = {"leitura": and_(marcas["leitura"], premiavel),
                  "matematica": and_(_marca("matematica", do_ano=True), premiavel)}
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
            func.sum(case((desempenho["leitura"], 1), else_=0)),
            func.avg(case((desempenho["leitura"], Nota.nota_elefante))),
            func.sum(case((desempenho["matematica"], 1), else_=0)),
            func.avg(case((desempenho["matematica"], Nota.nota_matific))),
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


@scoring.com_leituras_da_requisicao
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

    # CONTRATO: o total da plataforma de um módulo que a rede NÃO contratou nem é
    # somado — um retrato antigo dela (contrato mudado, escola vinda de outra
    # rede) virava "Atividades 35" no Painel do app de uma rede só com Leitura.
    # O esquema da resposta pede número, então sai 0; o pacote do app leva os
    # módulos (`routers/mobile.sincronizar`) e o Painel esconde o cartão.
    contratadas = scoring.dimensoes_contratadas(db, escola)

    # MATIFIC É CONTADOR DO ANO: o "atual" é o último retrato DENTRO do ano
    # letivo (a definição de aferido do motor, ``scoring.snapshots_matific_do_ano``).
    # Sem a janela, o acumulado de dez/2025 (ou de jan/2027, antes da virada da
    # escola) entrava no "atividades" do painel de 2026.
    total_atividades = 0
    if "matematica" in contratadas:
        ids_atuais_m = scoring.ids_snapshots_atuais(
            SnapshotMatific, escola_id, janela=matific_destaque.janela_ano_letivo(ano))
        consulta_atividades = (
            select(func.coalesce(func.sum(SnapshotMatific.atividades), 0))
            .where(SnapshotMatific.id.in_(ids_atuais_m), _na_coorte(SnapshotMatific))
        )
        if alunos_sub is not None:
            consulta_atividades = consulta_atividades.where(
                SnapshotMatific.aluno_id.in_(alunos_sub))
        total_atividades = db.execute(consulta_atividades).scalar_one()

    total_livros, tempo_total = 0, 0
    if "leitura" in contratadas:
        ids_atuais_e = scoring.ids_snapshots_atuais(SnapshotElefante, escola_id)
        consulta_elefante = (
            select(
                func.coalesce(func.sum(SnapshotElefante.livros_unicos), 0),
                func.coalesce(func.sum(SnapshotElefante.tempo_leitura_min), 0),
            ).where(SnapshotElefante.id.in_(ids_atuais_e), _na_coorte(SnapshotElefante))
        )
        if alunos_sub is not None:
            consulta_elefante = consulta_elefante.where(
                SnapshotElefante.aluno_id.in_(alunos_sub))
        total_livros, tempo_total = db.execute(consulta_elefante).one()

    # DESEMPENHO POR DIMENSÃO — cada média só sobre quem TEM dado da plataforma
    # (ver `_media_da_dimensao`). Era uma média única de `nota_geral` sobre TODOS
    # os alunos ativos, zeros de quem não tem dado incluídos: media_geral media
    # desempenho × cobertura, e a MESMA escola exibia um número aqui e outro no
    # cartão do painel da rede. Agora as duas telas usam a mesma régua.
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
    # Só quem tem dado de ALGUMA plataforma (`so_com_dado`, o corte do telão):
    # o Top 5 do Painel (web e app) dava medalha e "0,0" a quem nunca abriu
    # plataforma nenhuma — ausência não é zero.
    top10 = _ranking(db, escola_id, ano, limite=10, turma_ids=turma_ids,
                     so_com_dado=True)
    # Professor: posição RELATIVA às turmas dele (1..N), igual ao Ranking Geral —
    # o Top 10 e a tela de ranking não podem mostrar posições diferentes.
    # A posição sai da lista INTEIRA do professor (a mesma que `ranking_geral`
    # e o pacote do app renumeram, também sem quem não tem dado nenhum), e não
    # da ordem do Top 10 já cortado pelo `limite`.
    if turma_ids is not None:
        ordem = {item.aluno_id: n for n, item in enumerate(
            _ranking(db, escola_id, ano, turma_ids=turma_ids, so_com_dado=True),
            start=1)}
        for item in top10:
            item.posicao = ordem.get(item.aluno_id, item.posicao)

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


PAINEL_DA_ESCOLA_SEM_SECRETARIA = (
    "O painel da escola é de quem trabalha nela. A Secretaria acompanha a rede pelo "
    "Panorama da Rede.")


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Painel da escola. A Secretaria leva 403 com a explicação, como no pacote do
    app (``mobile.sincronizar``): ``turmas_permitidas`` é vazia para ela de
    propósito (nunca vê nome de criança), e o painel recortado por ela saía 200
    com 0 alunos, 0 turmas, média 0,0 e 0 livros, como se fossem os números da
    escola. Nenhuma tela usa este painel para ela: a web a leva ao Panorama da
    Rede e à ficha da escola na rede, que têm os números agregados."""
    if permissoes.e_secretaria(usuario):
        raise HTTPException(status.HTTP_403_FORBIDDEN, PAINEL_DA_ESCOLA_SEM_SECRETARIA)
    return montar_dashboard(
        db, escola_id, turma_ids=permissoes.turmas_permitidas(db, escola_id, usuario))


# ---------------------------------------------------------------------------
# Relatório por PERÍODO
# ---------------------------------------------------------------------------
# POR QUE AQUI, e não num router próprio: o lugar natural seria um
# `routers/relatorios_periodo.py` registrado em `main.py` — mas `main.py` e
# `routers/relatorios.py` estão entre as alterações paralelas não commitadas
# deste worktree, e tocá-los publicaria trabalho de terceiro inacabado. Este
# router é LIMPO e já está registrado, e já é a casa das consultas recortadas
# por período (`/premiacoes`, `/ranking/*`). Quando o trabalho paralelo entrar,
# mover este endpoint para um router dedicado é um recorta-e-cola.
#
# A GUARDA DE PII VIAJA COM O ENDPOINT. `relatorios.router` é registrado atrás
# de `negar_secretaria` porque seus PDFs têm NOME de criança; este relatório
# lista nome por aluno, então precisa da MESMA guarda — e aqui ela é declarada
# na própria rota, não na linha de registro, justamente para não depender de
# `main.py`.
@router.get("/relatorios/periodo", response_model=dict)
def relatorio_por_periodo(
    periodo: str = Query(default="mes",
                         description="mes | mes_anterior | bimestre | "
                                     "bimestre_1..4 | ano_letivo | personalizado "
                                     "(e os demais presets de `periodos`)"),
    inicio: str | None = Query(default=None, description="AAAA-MM-DD; "
                                                         "obrigatório em `personalizado`"),
    fim: str | None = Query(default=None, description="AAAA-MM-DD; "
                                                      "obrigatório em `personalizado`"),
    plataformas: list[str] = Query(default=["elefante", "matific"],
                                   description="elefante e/ou matific"),
    escopo: str = Query(default="escola", description="escola | turma | aluno"),
    turma_id: int | None = Query(default=None),
    aluno_id: int | None = Query(default=None),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(negar_secretaria),
):
    """O que aconteceu numa JANELA de datas, por plataforma e por escopo.

    É consulta: não grava nada e não altera scoring, ranking, nota, premiação,
    certificado nem sincronização. O período vem do serviço OFICIAL
    (`periodos.resolver`), então "setembro" aqui é o mesmo "setembro" do pódio.

    A resposta diz, para cada plataforma, QUAL campo sustenta a janela e a
    classificação do que foi calculado (`SUPORTADO` / `SUPORTADO COM RESSALVA` /
    `NÃO SUPORTADO`) — métrica sem dado histórico suficiente volta `None` com o
    motivo em `nao_suportado`, nunca um número inventado.
    """
    return _relatorio_periodo_dados(
        db, escola_id, usuario, periodo=periodo, inicio=inicio, fim=fim,
        plataformas=plataformas, escopo=escopo, turma_id=turma_id,
        aluno_id=aluno_id, acao="relatorio.periodo_consultado")


def _relatorio_periodo_dados(
    db: Session, escola_id: int, usuario: Usuario, *, periodo: str,
    inicio: str | None, fim: str | None, plataformas: list[str], escopo: str,
    turma_id: int | None, aluno_id: int | None, acao: str,
) -> dict:
    """Permissão + geração + auditoria do relatório por período.

    Existe como FUNÇÃO porque duas rotas a usam — o JSON e o PDF — e a
    autorização do PDF precisa ser a mesma, não uma cópia parecida. Cópia
    envelhece: bastaria alguém endurecer uma das duas e a outra viraria a porta
    de trás. Aqui, endurecer uma é endurecer as duas.
    """
    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo
    # CONTRATO antes de permissão: não se emite relatório de um produto que a
    # rede não assinou — a mesma cascata de `routers/relatorios.py` e das rotas
    # por plataforma aqui ao lado. Sem isto, bastava pedir
    # `?plataformas=matific` para receber o que `/ranking/matematica` nega com
    # 403, e com nome de criança no documento.
    #   `.get` e não `[p]`: plataforma desconhecida tem de cair no 422 de
    #   `gerar` (que valida o vocabulário), não num KeyError 500 aqui fora.
    contratados = svc_modulos.modulos_da_escola(db, escola)
    for plataforma in plataformas:
        modulo = svc_modulos.PLATAFORMA_MODULO.get(plataforma)
        if modulo is not None:
            svc_modulos.exigir(contratados, modulo)
    # PERMISSÃO antes de qualquer consulta de dado, em DUAS camadas — e a ordem
    # importa. `exigir_*_permitida` cuida da restrição do PROFESSOR e devolve
    # cedo quando o usuário é de gestão (`ids is None`); ela NÃO confere de que
    # escola a turma/o aluno é. Quem confere é esta primeira camada. Sem ela, um
    # coordenador podia passar o id de uma turma de outra escola e receber 200
    # (relatório vazio, porque a coorte é filtrada por `Aluno.escola_id` — mas
    # 200 mesmo assim). 404, e não 403, para não confirmar que o id existe.
    if escopo == "aluno":
        if aluno_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Escolha o aluno para o relatório individual.")
        alvo = db.get(Aluno, aluno_id)
        if alvo is None or alvo.escola_id != escola_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
        permissoes.exigir_aluno_permitido(db, escola_id, ano, usuario, aluno_id)
    if escopo == "turma":
        if turma_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Escolha a turma para o relatório da turma.")
        alvo = db.get(Turma, turma_id)
        if alvo is None or alvo.escola_id != escola_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Turma não encontrada.")
        permissoes.exigir_turma_permitida(db, escola_id, usuario, turma_id)
    # Professor restrito: o recorte das turmas dele vale TAMBÉM no escopo
    # "escola" — senão bastaria pedir escopo=escola para ver a escola inteira.
    restrito = permissoes.turmas_permitidas(db, escola_id, usuario)

    try:
        dados = svc_relatorio_periodo.gerar(
            db, escola_id, preset=periodo, plataformas=plataformas, escopo=escopo,
            inicio=periodos._parse_data(inicio), fim=periodos._parse_data(fim),
            turma_id=turma_id, aluno_id=aluno_id, turma_ids=restrito,
            hoje=hoje_br())
    except svc_relatorio_periodo.RelatorioInvalido as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except ValueError as exc:            # data em formato inválido
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Data inválida: use o formato AAAA-MM-DD.") from exc

    # AUDITORIA: reusa o mecanismo existente (`logs_auditoria`), igual ao
    # `certificado.emitido`. O relatório NÃO é persistido — nem os dados nem
    # PDF —, então o log guarda só o PEDIDO (período, plataformas, escopo), que
    # é o que permite responder "quem consultou o quê" sem duplicar PII.
    registrar(db, acao, escola_id=escola_id,
              usuario_id=usuario.id, entidade="escola", entidade_id=escola_id,
              detalhes={"periodo": periodo, "rotulo": dados["periodo"]["rotulo"],
                        "plataformas": dados["plataformas"], "escopo": escopo,
                        "turma_id": turma_id, "aluno_id": aluno_id,
                        "alunos_considerados": dados["alunos"]["considerados"]})
    db.commit()
    return dados


# MESMA rota, outro formato. O caminho termina em `.pdf` (e não `?formato=pdf`)
# para o navegador e o histórico do gestor já dizerem o que o arquivo é.
@router.get("/relatorios/periodo.pdf")
def relatorio_por_periodo_pdf(
    periodo: str = Query(default="mes"),
    inicio: str | None = Query(default=None, description="AAAA-MM-DD"),
    fim: str | None = Query(default=None, description="AAAA-MM-DD"),
    plataformas: list[str] = Query(default=["elefante", "matific"]),
    escopo: str = Query(default="escola", description="escola | turma | aluno"),
    turma_id: int | None = Query(default=None),
    aluno_id: int | None = Query(default=None),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(negar_secretaria),
):
    """O MESMO relatório, em PDF.

    Mesma cadeia de permissão, mesmos parâmetros e — o que importa — os MESMOS
    números: o PDF recebe o dicionário que `svc_relatorio_periodo.gerar`
    devolveu e não consulta o banco de novo. Não existe aqui uma segunda
    aritmética que pudesse discordar da tela.
    """
    dados = _relatorio_periodo_dados(
        db, escola_id, usuario, periodo=periodo, inicio=inicio, fim=fim,
        plataformas=plataformas, escopo=escopo, turma_id=turma_id,
        aluno_id=aluno_id, acao="relatorio.periodo_pdf")
    conteudo = svc_relatorio_pdf.gerar(
        dados, cor=svc_relatorios.cor_primaria(db, escola_id),
        logos=svc_relatorios.logos_da_escola(db, escola_id))
    nome = svc_relatorio_pdf.nome_arquivo(dados)
    return Response(
        content=conteudo, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'})
