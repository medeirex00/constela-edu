"""Evolução, páginas de turma/escola e comparadores (PRD §67–§78).

Endpoints somente-leitura: toda a informação vem dos snapshots imutáveis.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, get_usuario_atual
from app.core.tempo import hoje_br
from app.models import Aluno, Escola, Usuario
from app.services import evolucao as svc
from app.services import grupo_pequeno as svc_grupo
from app.services import modulos as svc_modulos
from app.services import elegibilidade, periodos, permissoes, timeline

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Evolução"])


def _intervalo_pedido(escola: Escola | None, periodo: str | None, inicio: str | None,
                      fim: str | None, dia: str | None):
    """(início, fim) do período pedido, no MESMO contrato de
    ``/alunos/{id}/leituras`` — o que o ``SeletorPeriodo`` da web manda
    (``periodoParaQuery``): ``?periodo=<preset>`` ("bimestre_3", "semana"...,
    "tudo"), ``?periodo=personalizado&inicio=&fim=`` ou ``?dia=``.

    Antes as rotas do Perfil do Aluno só declaravam ``inicio``/``fim``: o
    ``periodo`` era descartado em silêncio e "3º bimestre" no seletor trazia o
    histórico todo. Sem ``periodo``, ``inicio``/``fim`` continuam valendo como
    intervalo personalizado (quem já chamava assim não muda); sem nada, é o
    histórico todo. Data inválida → 400."""
    hoje = hoje_br()
    ano = escola.ano_letivo_ativo if escola else hoje.year
    try:
        if dia:
            d = periodos._parse_data(dia)
            ini, fim_dt, _ = periodos.resolver("personalizado", hoje, ano, d, d)
        else:
            preset = periodo or ("personalizado" if (inicio or fim) else "tudo")
            ini, fim_dt, _ = periodos.resolver(
                preset, hoje, ano, periodos._parse_data(inicio), periodos._parse_data(fim))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Data inválida (use AAAA-MM-DD).") from exc
    return ini, fim_dt


@router.get("/alunos/{aluno_id}/evolucao")
def evolucao_do_aluno(
    aluno_id: int,
    dias: int = Query(default=30, ge=1, le=366),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Linha do tempo completa + variação no período (PRD §67–§71).
    Coordenador/admin veem qualquer aluno da escola; o PROFESSOR vê a evolução
    dos alunos das TURMAS DELE (404 fora do escopo); a Secretaria não vê dado
    individual (404).

    Leitura MISTA (as duas plataformas): a do módulo que a rede não contratou
    sai da resposta — série vazia na linha do tempo e nenhum indicador dela no
    resumo —, em vez de 403 na rota inteira."""
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    escola = db.get(Escola, escola_id)
    permissoes.exigir_aluno_permitido(
        db, escola_id, escola.ano_letivo_ativo if escola else 0, usuario, aluno_id)
    fora = svc_modulos.plataformas_fora_do_plano(svc_modulos.modulos_da_escola(db, escola))
    return {
        "aluno_id": aluno_id,
        "nome": aluno.nome,
        "linha_do_tempo": svc.linha_do_tempo(db, escola_id, aluno_id, dias,
                                             plataformas_fora=fora),
        "resumo": svc.resumo_evolucao(db, escola_id, aluno_id, dias,
                                      plataformas_fora=fora),
    }


@router.get("/alunos/{aluno_id}/evolucao-leitura")
def evolucao_leitura_do_aluno(
    aluno_id: int,
    granularidade: str = Query(default="mes", pattern="^(semana|mes|bimestre)$"),
    periodo: str | None = Query(default=None, max_length=40),
    inicio: str | None = Query(default=None),
    fim: str | None = Query(default=None),
    dia: str | None = Query(default=None),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Evolução das LEITURAS no tempo (livros/pontos/tempo/nível médio por
    semana, mês ou bimestre), respeitando o período escolhido.
    Coordenador/admin: qualquer aluno da escola; PROFESSOR: os alunos das turmas
    dele (404 fora do escopo); Secretaria: 404 (sem dado individual).
    Rede que não contratou Leitura → 403 (o módulo não existe para ela). A trava
    do módulo vem DEPOIS do escopo: quem não pode ver o aluno recebe 404, com o
    módulo ligado ou não."""
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    escola = db.get(Escola, escola_id)
    permissoes.exigir_aluno_permitido(
        db, escola_id, escola.ano_letivo_ativo if escola else 0, usuario, aluno_id)
    svc_modulos.exigir(svc_modulos.modulos_da_escola(db, escola), "leitura")
    ini, fim_dt = _intervalo_pedido(escola, periodo, inicio, fim, dia)
    return svc.evolucao_leitura(db, escola_id, aluno_id, granularidade, ini, fim_dt)


@router.get("/alunos/{aluno_id}/linha-do-tempo")
def linha_do_tempo_do_aluno(
    aluno_id: int,
    plataforma: str | None = Query(default=None, pattern="^(matific|elefante)$"),
    tipo: str | None = Query(default=None, max_length=40),
    periodo: str | None = Query(default=None, max_length=40),
    inicio: str | None = Query(default=None),
    fim: str | None = Query(default=None),
    dia: str | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=80),
    limite: int = Query(default=50, ge=1, le=200),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Linha do tempo cronológica (evento a evento) do aluno, do mais recente ao
    mais antigo, paginada por cursor, no período do seletor (``periodo``,
    ``inicio``/``fim`` ou ``dia``, como em ``/leituras``). Sem período informado,
    traz o histórico TODO. Dado detalhado: professor restrito não acessa.

    Módulo fora do plano da rede: ``?plataforma=`` dele → 403 (a mesma régua das
    rotas inteiras de um módulo); sem filtro, os eventos dele não entram no feed.
    A trava vem DEPOIS do escopo (perfil e aluno), como nas demais rotas."""
    permissoes.negar_dado_individual(db, escola_id, usuario)
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    escola = db.get(Escola, escola_id)
    modulos = svc_modulos.modulos_da_escola(db, escola)
    if plataforma:
        svc_modulos.exigir_plataforma(modulos, plataforma)
    ini, fim_dt = _intervalo_pedido(escola, periodo, inicio, fim, dia)
    dados = timeline.linha_do_tempo(
        db, escola_id, aluno_id, plataforma=plataforma, tipo_evento=tipo,
        inicio=ini, fim=fim_dt, cursor=cursor, limite=limite,
        plataformas_fora=svc_modulos.plataformas_fora_do_plano(modulos))
    return {"aluno_id": aluno_id, "nome": aluno.nome, **dados}


@router.get("/alunos/{aluno_id}/espelho")
def espelho_do_aluno(
    aluno_id: int,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Resumo do 'espelho' de dados do aluno (contadores por tipo/plataforma,
    primeira/última atividade, tempo total). Dado detalhado: professor não
    acessa. Os eventos da plataforma de módulo fora do plano não são contados."""
    permissoes.negar_dado_individual(db, escola_id, usuario)
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    fora = svc_modulos.plataformas_fora_do_plano(
        svc_modulos.modulos_da_escola(db, db.get(Escola, escola_id)))
    return {"aluno_id": aluno_id, "nome": aluno.nome,
            "espelho": timeline.espelho(db, escola_id, aluno_id, plataformas_fora=fora)}


@router.get("/ranking-evolucao")
def ranking_evolucao(
    dias: int = Query(default=30, ge=1, le=366),
    periodo: str | None = Query(default=None),
    inicio: str | None = Query(default=None),
    fim: str | None = Query(default=None),
    turma_id: int | None = Query(default=None),
    ano_escolar: str | None = Query(default=None),
    turno: str | None = Query(
        default=None,
        description="Filtra por Turma.turno (eixo ORTOGONAL ao período). Ausente = "
                    "todos; vazio (turno=) = 'Sem turno'; senão o turno exato."),
    dimensao: str | None = Query(
        default=None,
        description="leitura | matematica. Ausente = ordem única (legado)."),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Ranking independente do geral: quem mais cresceu no período (PRD §72).
    Aceita um preset/intervalo (periodo/inicio/fim) ou os últimos N `dias`.

    Com ``?dimensao=leitura`` ou ``?dimensao=matematica`` devolve o crescimento
    DENTRO daquela dimensão — a leitura oficial da Arquitetura 2 —, com somente
    os alunos AFERIDOS nela (têm dado da plataforma na janela) e ordenados pela
    nota da própria dimensão. Quem não tem dado não entra com zero: sai da
    lista, e `dimensoes` de cada item continua dizendo o estado dele.

    Sem ``dimensao``, devolve a ordem ÚNICA (legado), que o telão público, o
    mural e o /insights ainda consomem — já com o C-01 aplicado, sem o teto
    de 50 que existia nesta tela.

    AS FASES NÃO CONCORREM (``services.elegibilidade``, 1º–5º ano): só as turmas
    premiáveis aparecem, renumeradas entre quem concorre. É o MESMO recorte que
    o telão público já faz (``publico._dados_publicos``): ``turma_ids`` só
    recorta a lista — a régua continua a da escola inteira, então a nota de cada
    criança é a mesma do sistema.
    """
    escola = db.get(Escola, escola_id)
    if dimensao is not None:
        if dimensao not in svc.DIMENSOES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Dimensão inválida. Use uma de: {', '.join(svc.DIMENSOES)}.")
        # 403 (e não 404) para módulo não contratado: mesma régua das demais
        # rotas por dimensão — some o produto, não a existência da rota.
        svc_modulos.exigir(svc_modulos.modulos_da_escola(db, escola), dimensao)
    # Quem APARECE = turmas permitidas ao usuário (professor; `None` = gestão) ∩
    # turmas que concorrem. A interseção mantém o escopo de acesso exatamente
    # como era — ninguém passa a ver turma que não via — e só tira as Fases.
    premiaveis = elegibilidade.turmas_premiaveis(db, escola_id, escola.ano_letivo_ativo)
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    concorrem = set(premiaveis)
    recorte = (premiaveis if permitidas is None
               else [t for t in permitidas if t in concorrem])
    ini = None
    fim_dt = None
    if periodo or inicio or fim:
        try:
            ini, fim_dt, _ = periodos.resolver(
                periodo or "personalizado", hoje_br(), escola.ano_letivo_ativo,
                periodos._parse_data(inicio), periodos._parse_data(fim))
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Data inválida (use AAAA-MM-DD).") from exc
        dados = svc.ranking_evolucao(db, escola_id, ini, fim_dt, turma_id, ano_escolar,
                                     turno=turno, turma_ids=recorte,
                                     base_no_periodo=True)
    else:
        dados = svc.ranking_evolucao(db, escola_id, turma_id=turma_id,
                                     ano_escolar=ano_escolar, dias=dias, turno=turno,
                                     turma_ids=recorte, base_no_periodo=True)
    if dimensao:
        dados = sorted((i for i in dados if i.aferido.get(dimensao)),
                       key=lambda i: i.posicao_dimensao[dimensao])
    return [
        {
            # Com `?dimensao=`, a posição exibida é a DAQUELA dimensão (o
            # denominador vem em `n_aferidos`); sem ela, a ordem única legada.
            "posicao": item.posicao_dimensao[dimensao] if dimensao else item.posicao,
            "aluno_id": item.aluno_id,
            "nome": item.nome,
            "turma": item.turma,
            "ano_escolar": item.ano_escolar,
            # LEGADO — a nota única de crescimento.
            "nota_evolucao": item.nota_evolucao,
            "ganhos": item.ganhos,
            "dimensao": dimensao,
            "nota": item.notas.get(dimensao) if dimensao else None,
            "n_aferidos": item.n_aferidos.get(dimensao) if dimensao else None,
            # Estado por dimensão SEMPRE presente: `nota: null` (nunca 0,0)
            # quando o aluno não tem dado daquela plataforma na janela.
            "dimensoes": {
                d: {
                    "plataforma": svc.DIMENSOES[d],
                    "contratada": d in item.contratadas,
                    "aferido": bool(item.aferido.get(d)),
                    "nota": item.notas.get(d),
                    "posicao": item.posicao_dimensao.get(d),
                    "n_aferidos": item.n_aferidos.get(d, 0),
                }
                for d in svc.DIMENSOES
            },
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
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None and turma_id not in permitidas:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Turma não encontrada.")
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
    """Página da escola: comparação entre turmas (PRD §78) — gestão apenas.

    Para a Secretaria, a matéria de turma com menos de
    ``grupo_pequeno.K_MINIMO_TURMA`` alunos aferidos sai com média e indicadores
    nulos e a marca ``grupo_pequeno``/``oculto`` (senão o número seria o de uma
    criança); a gestão da escola e o Admin Global recebem o resumo de sempre."""
    permissoes.negar_restrito(db, escola_id, usuario)
    return svc_grupo.resumo_escola_do_usuario(db, escola_id, usuario)


@router.get("/comparar")
def comparar(
    tipo_a: str = Query(pattern="^(aluno|turma|escola)$"),
    id_a: int = Query(),
    tipo_b: str = Query(pattern="^(aluno|turma|escola)$"),
    id_b: int = Query(),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Comparador aluno×aluno, aluno×turma, turma×turma e (ADM da rede)
    escola×escola (PRD §73–§75) — dados detalhados: gestão apenas."""
    # O lado 'aluno' expõe PII individual → bloqueado para a Secretaria (LGPD).
    # turma×turma e escola×escola são AGREGADOS (sem nome de criança): seguem
    # abertos à gestão, inclusive à Secretaria.
    if "aluno" in (tipo_a, tipo_b):
        permissoes.negar_dado_individual(db, escola_id, usuario)
    else:
        permissoes.negar_restrito(db, escola_id, usuario)
    # "Escola" como lado é recurso de ADM SUPREMO (rede/global). Um usuário
    # não-global só pode usar a PRÓPRIA escola como lado "escola".
    for tipo, ident in ((tipo_a, id_a), (tipo_b, id_b)):
        if tipo == "escola" and not usuario.is_global and ident != escola_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Comparar outra escola é exclusivo de administradores da rede.")
    secretaria = permissoes.e_secretaria(usuario)
    resultado = svc.comparar(db, escola_id, tipo_a, id_a, tipo_b, id_b,
                             com_contagem_aferidos=secretaria)
    if resultado is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Aluno, turma ou escola não encontrado.")
    # Secretaria: o lado TURMA com grupo pequeno sai sem os números (a mesma
    # decisão do resumo da escola), e o lado ESCOLA com menos de k alunos com
    # dado numa matéria também (a regra do cartão da rede); os outros perfis
    # recebem tudo.
    return svc_grupo.proteger_comparacao(db, escola_id, usuario, resultado)
