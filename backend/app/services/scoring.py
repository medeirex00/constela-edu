"""Motor de cálculo de notas e rankings.

Princípios (PRD Parte 3):
  * Nenhum peso vive no código — tudo é lido da tabela `configuracoes`.
  * Todo indicador é normalizado para a escala 0–100 antes de ser ponderado.
  * Cada nota carrega um `detalhes` com o passo a passo completo do cálculo,
    permitindo auditoria total ("Como esta nota foi calculada", PRD §45).
  * O recálculo é integral e automático (PRD §43): qualquer importação ou
    mudança de configuração dispara `recalcular_escola`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Aluno,
    Configuracao,
    DificuldadeTurma,
    Escola,
    Matricula,
    NivelDificuldade,
    Nota,
    ReferenciaNormalizacao,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)

# Valores usados apenas na primeira execução, antes do seed gravar os
# padrões no banco. Depois disso, a fonte é sempre a tabela `configuracoes`.
PESOS_PADRAO = {
    "pesos.matific": {"atividades": 40.0, "media": 35.0, "estrelas": 25.0},
    "pesos.elefante": {"livros": 35.0, "dificuldade": 30.0, "questoes": 30.0, "tempo": 5.0},
    "pesos.questoes": {"tentativas": 30.0, "acertos": 70.0},
    "pesos.geral": {"matific": 50.0, "elefante": 50.0},
}

CRITERIOS_DESEMPATE_PADRAO = [
    "nota_elefante",
    "nota_matific",
    "livros_unicos",
    "atividades",
    "pct_acertos",
    "nome",
]


def normalizar(valor: float, referencia: float) -> float:
    """Converte um valor bruto para a escala 0–100 usando a referência.

    Referência ausente ou zero resulta em 0 (nada a comparar ainda).
    O teto é 100 mesmo que um aluno ultrapasse a referência manual.
    """
    if not referencia or referencia <= 0:
        return 0.0
    return round(min(100.0, (float(valor) / float(referencia)) * 100.0), 2)


# ---------------------------------------------------------------------------
# Leitura de configurações
# ---------------------------------------------------------------------------

def obter_config(db: Session, escola_id: int, namespace: str, chave: str, padrao):
    row = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == namespace,
            Configuracao.chave == chave,
        )
    ).scalar_one_or_none()
    return row.valor if row is not None else padrao


def obter_pesos(db: Session, escola_id: int, namespace: str) -> dict[str, float]:
    """Retorna os pesos como frações (0–1), já normalizados defensivamente.

    A interface impede salvar pesos cuja soma difere de 100 (PRD §33),
    mas o motor ainda divide pela soma para nunca produzir notas > 100.
    """
    valores = obter_config(db, escola_id, namespace, "valores", PESOS_PADRAO[namespace])
    total = sum(float(v) for v in valores.values())
    if total <= 0:
        return {k: 0.0 for k in valores}
    return {k: float(v) / total for k, v in valores.items()}


def obter_pesos_brutos(db: Session, escola_id: int, namespace: str) -> dict[str, float]:
    return dict(obter_config(db, escola_id, namespace, "valores", PESOS_PADRAO[namespace]))


# ---------------------------------------------------------------------------
# Estado atual dos alunos (snapshots mais recentes)
# ---------------------------------------------------------------------------

def _snapshots_atuais(db: Session, escola_id: int, modelo):
    """Último snapshot de cada aluno para a plataforma indicada.

    "Último" pela DATA DE REFERÊNCIA (id desempata), não pelo id: importar um
    relatório de um período antigo (backfill mensal do Matific) registra o
    histórico sem rebaixar o estado atual dos rankings. A seleção acontece no
    banco (window function) — snapshots são imutáveis e só crescem; varrer
    todos como objetos ORM a cada recálculo não escala."""
    ids = ids_snapshots_atuais(modelo, escola_id)
    rows = db.execute(select(modelo).where(modelo.id.in_(ids))).scalars().all()
    return {row.aluno_id: row for row in rows}


def ids_snapshots_atuais(modelo, escola_id: int):
    """Subquery com o id do snapshot mais recente (data_referencia, id) de
    cada aluno da escola."""
    numerado = (
        select(
            modelo.id.label("snap_id"),
            func.row_number().over(
                partition_by=modelo.aluno_id,
                order_by=(modelo.data_referencia.desc(), modelo.id.desc()),
            ).label("posicao"),
        )
        .where(modelo.escola_id == escola_id)
        .subquery()
    )
    return select(numerado.c.snap_id).where(numerado.c.posicao == 1).scalar_subquery()


def _chaves_do_nivel(nivel: NivelDificuldade) -> list[str]:
    """Todas as chaves que representam a faixa em livros_por_nivel: os códigos
    de letra dos livros E o código estável da faixa (ex.: "pre_leitor"), que é
    usado quando os livros são informados/importados diretamente por faixa."""
    from app.models.configuracao import slug_nivel

    chaves = list(nivel.codigos or [])
    chaves.append(nivel.codigo or slug_nivel(nivel.nome))
    return chaves


def _overrides_turma(db: Session, escola_id: int) -> dict[int, dict[str, float]]:
    """Config LIVRE de pontos por TURMA: ``{turma_id: {CODIGO_UPPER: pontos}}``
    (esparso — só turmas customizadas). Sobrepõe o padrão da escola por código."""
    from app.models.configuracao import PontuacaoNivelTurma

    saida: dict[int, dict[str, float]] = {}
    for row in db.execute(
        select(PontuacaoNivelTurma).where(PontuacaoNivelTurma.escola_id == escola_id)
    ).scalars():
        m: dict[str, float] = {}
        for k, v in (row.pontos_por_codigo or {}).items():
            try:
                m[str(k).strip().upper()] = float(v)
            except (TypeError, ValueError):
                continue
        if m:
            saida[row.turma_id] = m
    return saida


def _mapa_dificuldade(db: Session, escola_id: int) -> dict:
    """Mapa de resolução de pontos. Chaves:
      ``"__padrao__"``     -> {codigo: pontos_padrao da faixa} (case preservado)
      ``(ano_escolar, codigo)`` -> override por SÉRIE (DificuldadeTurma, legado)
      ``"__turma__"``      -> {turma_id: {CODIGO_UPPER: pontos}} livre por TURMA
    Resolução (em ``_pontos_dificuldade``): TURMA > SÉRIE > padrão."""
    niveis = db.execute(
        select(NivelDificuldade).where(NivelDificuldade.escola_id == escola_id)
    ).scalars().all()
    mapa: dict = {}
    padrao_por_codigo: dict[str, float] = {}
    for nivel in niveis:
        for codigo in _chaves_do_nivel(nivel):
            padrao_por_codigo[codigo] = float(nivel.pontos_padrao)

    niveis_por_id = {n.id: n for n in niveis}
    for override in db.execute(
        select(DificuldadeTurma).where(DificuldadeTurma.escola_id == escola_id)
    ).scalars():
        nivel = niveis_por_id.get(override.nivel_id)
        if nivel is None:
            continue
        for codigo in _chaves_do_nivel(nivel):
            mapa[(override.ano_escolar, codigo)] = float(override.pontos)

    mapa["__padrao__"] = padrao_por_codigo
    mapa["__turma__"] = _overrides_turma(db, escola_id)
    return mapa


def _pontos_dificuldade(
    livros_por_nivel: dict, ano_escolar: str, mapa: dict,
    turma_id: int | None = None,
) -> float:
    padrao: dict[str, float] = mapa.get("__padrao__", {})
    por_turma: dict[str, float] = (
        mapa.get("__turma__", {}).get(turma_id, {}) if turma_id else {})
    total = 0.0
    for codigo, quantidade in (livros_por_nivel or {}).items():
        cod_up = str(codigo).strip().upper()
        if cod_up in por_turma:                       # 1) livre por TURMA
            pontos = por_turma[cod_up]
        elif (ano_escolar, codigo) in mapa:           # 2) por SÉRIE (legado)
            pontos = mapa[(ano_escolar, codigo)]
        else:                                          # 3) padrão da faixa
            pontos = padrao.get(codigo, 0.0)
        total += float(pontos) * int(quantidade)
    return round(total, 2)


def pontos_por_codigo(db: Session, escola_id: int,
                      turma_id: int | None = None) -> dict[str, float]:
    """Pontos de dificuldade por CÓDIGO de letra do livro (ex.: {"AA": 1.0,
    "D": 4.0}). Base do ranking de leitura por período. Com ``turma_id``, aplica a
    config LIVRE daquela turma sobre o padrão da escola."""
    mapa: dict[str, float] = {}
    for nivel in db.execute(
        select(NivelDificuldade).where(NivelDificuldade.escola_id == escola_id)
    ).scalars():
        for codigo in (nivel.codigos or []):
            if codigo:
                mapa[str(codigo).upper()] = float(nivel.pontos_padrao)
    if turma_id:
        mapa.update(_overrides_turma(db, escola_id).get(turma_id, {}))
    return mapa


def mapa_pontos_turmas(db: Session, escola_id: int) -> dict:
    """``{turma_id | None: {CODIGO_UPPER: pontos}}`` — ``None`` = padrão da escola;
    cada turma customizada tem o seu (padrão + override). Para o ranking por
    período resolver a pontuação pela turma do aluno numa passada só."""
    base = pontos_por_codigo(db, escola_id)
    saida: dict = {None: base}
    for turma_id, override in _overrides_turma(db, escola_id).items():
        combinado = dict(base)
        combinado.update(override)
        saida[turma_id] = combinado
    return saida


def distribuicao_niveis(
    db: Session, escola_id: int, livros_por_nivel: dict, ano_escolar: str = "",
    turma_id: int | None = None,
) -> dict:
    """Distribuição dos livros de um aluno pelas FAIXAS de dificuldade.

    Para relatórios/gráficos: por faixa devolve quantidade, pontos por livro
    (respeitando a config LIVRE da turma, senão o override da série, senão o
    padrão), pontos ganhos e percentual; além do total de livros, dos pontos de
    dificuldade e da faixa predominante. Funciona com livros por faixa ou por
    código de letra.
    """
    from app.models.configuracao import slug_nivel

    niveis = db.execute(
        select(NivelDificuldade)
        .where(NivelDificuldade.escola_id == escola_id)
        .order_by(NivelDificuldade.ordem)
    ).scalars().all()
    mapa = _mapa_dificuldade(db, escola_id)
    padrao: dict[str, float] = mapa.get("__padrao__", {})  # type: ignore[assignment]
    por_turma: dict[str, float] = (
        mapa.get("__turma__", {}).get(turma_id, {}) if turma_id else {})
    dados = livros_por_nivel or {}

    faixas = []
    total_livros = 0
    pontos_total = 0.0
    for nivel in niveis:
        slug = nivel.codigo or slug_nivel(nivel.nome)
        chaves = _chaves_do_nivel(nivel)
        quantidade = sum(int(dados.get(c, 0) or 0) for c in chaves)
        # Config LIVRE da turma (representada pela 1ª letra da faixa com override)
        # tem prioridade sobre a série e o padrão.
        override_turma = next(
            (por_turma[str(c).upper()] for c in chaves if str(c).upper() in por_turma),
            None)
        pontos_unidade = float(
            override_turma if override_turma is not None
            else mapa.get((ano_escolar, slug), padrao.get(slug, nivel.pontos_padrao)))
        pontos = round(quantidade * pontos_unidade, 2)
        faixas.append({
            "codigo": slug,
            "nome": nivel.nome,
            "quantidade": quantidade,
            "pontos_por_livro": pontos_unidade,
            "pontos": pontos,
            "percentual": 0.0,
        })
        total_livros += quantidade
        pontos_total += pontos

    for faixa in faixas:
        faixa["percentual"] = (round(faixa["quantidade"] / total_livros * 100, 1)
                               if total_livros else 0.0)

    com_livros = [f for f in faixas if f["quantidade"] > 0]
    predominante = max(com_livros, key=lambda f: f["quantidade"])["nome"] \
        if com_livros else None

    return {
        "faixas": faixas,
        "total_livros": total_livros,
        "pontos_dificuldade": round(pontos_total, 2),
        "faixa_predominante": predominante,
    }


# ---------------------------------------------------------------------------
# Referências de normalização (PRD §31, §62)
# ---------------------------------------------------------------------------

CHAVES_REFERENCIA = [
    "max_atividades",
    "max_media",
    "max_estrelas",
    "max_livros",
    "max_pontos_dificuldade",
    "max_tentativas",
    "max_acertos",
    "max_tempo",
]


def _referencias(
    db: Session,
    escola_id: int,
    matific: dict[int, SnapshotMatific],
    elefante: dict[int, SnapshotElefante],
    pontos_dificuldade: dict[int, float],
) -> tuple[dict[str, float], str]:
    """Resolve as referências no modo auto (máximos da base) ou manual.

    No modo manual, chaves não preenchidas caem no valor automático,
    para que uma configuração parcial nunca zere as notas.
    """
    auto = {
        "max_atividades": max((s.atividades for s in matific.values()), default=0),
        "max_media": max((s.pontuacao_media for s in matific.values()), default=0),
        "max_estrelas": max((s.estrelas for s in matific.values()), default=0),
        "max_livros": max((s.livros_unicos for s in elefante.values()), default=0),
        "max_pontos_dificuldade": max(pontos_dificuldade.values(), default=0),
        "max_tentativas": max((s.questoes_tentativas for s in elefante.values()), default=0),
        "max_acertos": max((s.questoes_acertos for s in elefante.values()), default=0),
        "max_tempo": max((s.tempo_leitura_min for s in elefante.values()), default=0),
    }

    ref_row = db.execute(
        select(ReferenciaNormalizacao).where(
            ReferenciaNormalizacao.escola_id == escola_id
        )
    ).scalar_one_or_none()

    if ref_row is None or ref_row.modo == "auto":
        return auto, "auto"

    manuais = ref_row.valores_manuais or {}
    resolvidas = {
        chave: float(manuais.get(chave) or auto[chave]) for chave in CHAVES_REFERENCIA
    }
    return resolvidas, "manual"


# ---------------------------------------------------------------------------
# Cálculo por módulo
# ---------------------------------------------------------------------------

def _linha(nome: str, valor: float, referencia: float, peso_pct: float) -> dict:
    norm = normalizar(valor, referencia)
    return {
        "indicador": nome,
        "valor": valor,
        "referencia": referencia,
        "normalizado": norm,
        "peso": peso_pct,
        "contribuicao": round(norm * peso_pct / 100.0, 2),
    }


def calcular_matific(
    snapshot: SnapshotMatific | None,
    refs: dict[str, float],
    pesos: dict[str, float],
    pesos_pct: dict[str, float],
) -> tuple[float, list[dict]]:
    atividades = snapshot.atividades if snapshot else 0
    media = snapshot.pontuacao_media if snapshot else 0.0
    estrelas = snapshot.estrelas if snapshot else 0

    linhas = [
        _linha("Atividades finalizadas", atividades, refs["max_atividades"], pesos_pct.get("atividades", 0)),
        _linha("Pontuação média", media, refs["max_media"], pesos_pct.get("media", 0)),
        _linha("Estrelas", estrelas, refs["max_estrelas"], pesos_pct.get("estrelas", 0)),
    ]
    nota = (
        normalizar(atividades, refs["max_atividades"]) * pesos.get("atividades", 0)
        + normalizar(media, refs["max_media"]) * pesos.get("media", 0)
        + normalizar(estrelas, refs["max_estrelas"]) * pesos.get("estrelas", 0)
    )
    return round(nota, 2), linhas


def calcular_elefante(
    snapshot: SnapshotElefante | None,
    pontos_dificuldade: float,
    refs: dict[str, float],
    pesos: dict[str, float],
    pesos_pct: dict[str, float],
    pesos_questoes: dict[str, float],
    pesos_questoes_pct: dict[str, float],
) -> tuple[float, list[dict], dict]:
    livros = snapshot.livros_unicos if snapshot else 0
    tempo = snapshot.tempo_leitura_min if snapshot else 0
    tentativas = snapshot.questoes_tentativas if snapshot else 0
    acertos = snapshot.questoes_acertos if snapshot else 0

    # Sub-nota de questões: tentativa + aprendizado (PRD §36)
    n_tentativas = normalizar(tentativas, refs["max_tentativas"])
    n_acertos = normalizar(acertos, refs["max_acertos"])
    nota_questoes = round(
        n_tentativas * pesos_questoes.get("tentativas", 0)
        + n_acertos * pesos_questoes.get("acertos", 0),
        2,
    )
    detalhe_questoes = {
        "tentativas": {"valor": tentativas, "referencia": refs["max_tentativas"], "normalizado": n_tentativas, "peso": pesos_questoes_pct.get("tentativas", 0)},
        "acertos": {"valor": acertos, "referencia": refs["max_acertos"], "normalizado": n_acertos, "peso": pesos_questoes_pct.get("acertos", 0)},
        "sub_nota": nota_questoes,
    }

    linhas = [
        _linha("Livros únicos concluídos", livros, refs["max_livros"], pesos_pct.get("livros", 0)),
        _linha("Pontos de dificuldade", pontos_dificuldade, refs["max_pontos_dificuldade"], pesos_pct.get("dificuldade", 0)),
        _linha("Questões (tentativas + acertos)", nota_questoes, 100.0, pesos_pct.get("questoes", 0)),
        _linha("Tempo de leitura (min)", tempo, refs["max_tempo"], pesos_pct.get("tempo", 0)),
    ]
    nota = (
        normalizar(livros, refs["max_livros"]) * pesos.get("livros", 0)
        + normalizar(pontos_dificuldade, refs["max_pontos_dificuldade"]) * pesos.get("dificuldade", 0)
        + nota_questoes * pesos.get("questoes", 0)
        + normalizar(tempo, refs["max_tempo"]) * pesos.get("tempo", 0)
    )
    return round(nota, 2), linhas, detalhe_questoes


# ---------------------------------------------------------------------------
# Desempate (PRD §42) — critérios configuráveis
# ---------------------------------------------------------------------------

@dataclass
class ResultadoAluno:
    aluno: Aluno
    ano_escolar: str
    turma_nome: str
    nota_matific: float = 0.0
    nota_elefante: float = 0.0
    nota_geral: float = 0.0
    livros_unicos: int = 0
    atividades: int = 0
    pct_acertos: float = 0.0
    detalhes: dict = field(default_factory=dict)


def _chave_ordenacao(resultado: ResultadoAluno, criterios: list[str]):
    chave: list = [-resultado.nota_geral]
    for criterio in criterios:
        if criterio == "nome":
            chave.append(resultado.aluno.nome.casefold())
        else:
            chave.append(-float(getattr(resultado, criterio, 0) or 0))
    # Desempate final DETERMINÍSTICO: dois alunos DISTINTOS homônimos e com todas
    # as métricas iguais não podem trocar de posição entre recálculos sucessivos
    # (aluno.id é único e estável).
    chave.append(resultado.aluno.id)
    return tuple(chave)


# ---------------------------------------------------------------------------
# Recalculo integral (PRD §43)
# ---------------------------------------------------------------------------

def _carregar_contexto(db: Session, escola_id: int):
    """Carrega tudo que o cálculo precisa: matrículas do ano ativo,
    snapshots mais recentes por aluno e pontos de dificuldade por série."""
    escola = db.get(Escola, escola_id)
    if escola is None:
        return None
    ano = escola.ano_letivo_ativo

    matriculas = db.execute(
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .where(
            Matricula.escola_id == escola_id,
            Matricula.ano_letivo == ano,
            Aluno.status == "ativo",
        )
        .options(selectinload(Matricula.aluno))  # evita N+1 em matricula.aluno
    ).all()

    matific = _snapshots_atuais(db, escola_id, SnapshotMatific)
    elefante = _snapshots_atuais(db, escola_id, SnapshotElefante)
    mapa_dif = _mapa_dificuldade(db, escola_id)

    pontos_dif: dict[int, float] = {}
    for matricula, turma in matriculas:
        snap = elefante.get(matricula.aluno_id)
        pontos_dif[matricula.aluno_id] = _pontos_dificuldade(
            snap.livros_por_nivel if snap else {}, turma.ano_escolar, mapa_dif,
            turma_id=turma.id,
        )
    return escola, ano, matriculas, matific, elefante, pontos_dif


def referencias_em_uso(db: Session, escola_id: int) -> tuple[dict, str]:
    """Referências efetivas (tela REFERÊNCIAS DE NORMALIZAÇÃO, PRD §62)."""
    contexto = _carregar_contexto(db, escola_id)
    if contexto is None:
        return {}, "auto"
    _, _, _, matific, elefante, pontos_dif = contexto
    return _referencias(db, escola_id, matific, elefante, pontos_dif)


def recalcular_escola(db: Session, escola_id: int) -> int:
    """Recalcula todas as notas e o ranking da escola. Retorna nº de alunos."""
    contexto = _carregar_contexto(db, escola_id)
    if contexto is None:
        return 0
    escola, ano, matriculas, matific, elefante, pontos_dif = contexto

    refs, modo = _referencias(db, escola_id, matific, elefante, pontos_dif)

    p_matific = obter_pesos(db, escola_id, "pesos.matific")
    p_elefante = obter_pesos(db, escola_id, "pesos.elefante")
    p_questoes = obter_pesos(db, escola_id, "pesos.questoes")
    p_geral = obter_pesos(db, escola_id, "pesos.geral")
    pct_matific = obter_pesos_brutos(db, escola_id, "pesos.matific")
    pct_elefante = obter_pesos_brutos(db, escola_id, "pesos.elefante")
    pct_questoes = obter_pesos_brutos(db, escola_id, "pesos.questoes")
    pct_geral = obter_pesos_brutos(db, escola_id, "pesos.geral")

    resultados: list[ResultadoAluno] = []
    for matricula, turma in matriculas:
        aluno = matricula.aluno
        snap_m = matific.get(aluno.id)
        snap_e = elefante.get(aluno.id)

        nota_m, linhas_m = calcular_matific(snap_m, refs, p_matific, pct_matific)
        nota_e, linhas_e, det_q = calcular_elefante(
            snap_e, pontos_dif[aluno.id], refs, p_elefante, pct_elefante,
            p_questoes, pct_questoes,
        )
        nota_geral = round(
            nota_m * p_geral.get("matific", 0) + nota_e * p_geral.get("elefante", 0), 2
        )

        tentativas = snap_e.questoes_tentativas if snap_e else 0
        acertos = snap_e.questoes_acertos if snap_e else 0
        resultados.append(
            ResultadoAluno(
                aluno=aluno,
                ano_escolar=turma.ano_escolar,
                turma_nome=turma.nome,
                nota_matific=nota_m,
                nota_elefante=nota_e,
                nota_geral=nota_geral,
                livros_unicos=snap_e.livros_unicos if snap_e else 0,
                atividades=snap_m.atividades if snap_m else 0,
                pct_acertos=round(acertos / tentativas * 100, 2) if tentativas else 0.0,
                detalhes={
                    "modo_normalizacao": modo,
                    "referencias": refs,
                    "matific": {"indicadores": linhas_m, "nota": nota_m},
                    "elefante": {"indicadores": linhas_e, "questoes": det_q, "nota": nota_e},
                    "geral": {"pesos": pct_geral, "nota": nota_geral},
                },
            )
        )

    criterios = obter_config(
        db, escola_id, "desempate", "criterios", CRITERIOS_DESEMPATE_PADRAO
    )
    resultados.sort(key=lambda r: _chave_ordenacao(r, criterios))

    # Carrega TODAS as notas do ano numa query só (era 1 SELECT por aluno).
    notas_existentes = {
        n.aluno_id: n for n in db.execute(
            select(Nota).where(Nota.escola_id == escola_id, Nota.ano_letivo == ano)
        ).scalars()
    }
    for posicao, resultado in enumerate(resultados, start=1):
        nota_row = notas_existentes.get(resultado.aluno.id)
        if nota_row is None:
            nota_row = Nota(escola_id=escola_id, aluno_id=resultado.aluno.id, ano_letivo=ano)
            db.add(nota_row)
        nota_row.nota_matific = resultado.nota_matific
        nota_row.nota_elefante = resultado.nota_elefante
        nota_row.nota_geral = resultado.nota_geral
        nota_row.posicao = posicao
        nota_row.detalhes = resultado.detalhes

    db.commit()
    return len(resultados)
