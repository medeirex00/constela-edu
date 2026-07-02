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
from sqlalchemy.orm import Session

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
    """Último snapshot de cada aluno para a plataforma indicada."""
    sub = (
        select(modelo.aluno_id, func.max(modelo.id).label("max_id"))
        .where(modelo.escola_id == escola_id)
        .group_by(modelo.aluno_id)
        .subquery()
    )
    rows = db.execute(
        select(modelo).join(sub, modelo.id == sub.c.max_id)
    ).scalars().all()
    return {row.aluno_id: row for row in rows}


def _mapa_dificuldade(db: Session, escola_id: int) -> dict[tuple[str, str], float]:
    """Mapa (série, código do livro) -> pontos, com fallback no padrão do nível."""
    niveis = db.execute(
        select(NivelDificuldade).where(NivelDificuldade.escola_id == escola_id)
    ).scalars().all()
    mapa: dict[tuple[str, str], float] = {}
    padrao_por_codigo: dict[str, float] = {}
    for nivel in niveis:
        for codigo in nivel.codigos:
            padrao_por_codigo[codigo] = float(nivel.pontos_padrao)

    overrides = db.execute(
        select(DificuldadeTurma).where(DificuldadeTurma.escola_id == escola_id)
    ).scalars().all()
    niveis_por_id = {n.id: n for n in niveis}
    for override in overrides:
        nivel = niveis_por_id.get(override.nivel_id)
        if nivel is None:
            continue
        for codigo in nivel.codigos:
            mapa[(override.ano_escolar, codigo)] = float(override.pontos)

    mapa["__padrao__"] = padrao_por_codigo  # type: ignore[assignment]
    return mapa


def _pontos_dificuldade(
    livros_por_nivel: dict, ano_escolar: str, mapa: dict
) -> float:
    padrao: dict[str, float] = mapa.get("__padrao__", {})  # type: ignore[assignment]
    total = 0.0
    for codigo, quantidade in (livros_por_nivel or {}).items():
        pontos = mapa.get((ano_escolar, codigo), padrao.get(codigo, 0.0))
        total += float(pontos) * int(quantidade)
    return round(total, 2)


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
    ).all()

    matific = _snapshots_atuais(db, escola_id, SnapshotMatific)
    elefante = _snapshots_atuais(db, escola_id, SnapshotElefante)
    mapa_dif = _mapa_dificuldade(db, escola_id)

    pontos_dif: dict[int, float] = {}
    for matricula, turma in matriculas:
        snap = elefante.get(matricula.aluno_id)
        pontos_dif[matricula.aluno_id] = _pontos_dificuldade(
            snap.livros_por_nivel if snap else {}, turma.ano_escolar, mapa_dif
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

    for posicao, resultado in enumerate(resultados, start=1):
        nota_row = db.execute(
            select(Nota).where(
                Nota.aluno_id == resultado.aluno.id, Nota.ano_letivo == ano
            )
        ).scalar_one_or_none()
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
