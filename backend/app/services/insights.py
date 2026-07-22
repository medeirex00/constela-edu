"""Inteligência Pedagógica (PRD §129–§153): índices e alertas automáticos.

Tudo é derivado dos dados existentes por regras transparentes — nenhum
modelo de IA participa destes cálculos, então os números são reproduzíveis
e auditáveis. O Assistente de IA (services/ia) usa estes mesmos índices
como contexto, nunca o contrário.

Índices (0–100) — leitura PEDAGÓGICA, robusta a outlier (rebalanceamento
aprovado: percentil/mediana/auto-referência no lugar de máximo/média):
  * Engajamento  — POSIÇÃO PERCENTILAR do avanço em 30 dias: "superou X% dos
                   colegas ativos". 50 = aluno mediano; o melhor vira 100 sem
                   comprimir o número de ninguém.
  * Evolução     — idem, na janela de 90 dias (crescimento sustentado).
  * Persistência — CONSTÂNCIA pura: semanas consecutivas com avanço. Não usa
                   volume acumulado nem o máximo da escola.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Aluno,
    Escola,
    Matricula,
    Nota,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import evolucao, gamificacao

DIAS_SEM_ATIVIDADE = 30
QUEDA_ACERTOS_PONTOS = 15.0
FRACAO_ABAIXO_TURMA = 0.5
# Constância: 8 semanas consecutivas com avanço = nota máxima (escala gradual).
PONTOS_POR_SEMANA_CONSTANCIA = 12.5


def _pct_acertos(snap) -> float | None:
    if snap is None or not snap.questoes_tentativas:
        return None
    return round(snap.questoes_acertos / snap.questoes_tentativas * 100, 1)


def _percentil_rank(ordenados_ativos: list[float], valor: float) -> float:
    """Posição percentilar: % dos alunos ATIVOS com valor <= o do aluno.

    Imune a outlier POR CONSTRUÇÃO: um aluno excepcional vira 100 sem alterar
    o percentil de nenhum colega (diferente de normalizar pelo máximo, em que
    o outlier comprime todo mundo). 50 = aluno mediano da escola.
    """
    if not ordenados_ativos:
        return 0.0
    abaixo = sum(1 for x in ordenados_ativos if x <= valor)
    return round(100.0 * abaixo / len(ordenados_ativos), 1)


def indices_da_escola(db: Session, escola_id: int) -> list[dict]:
    """Engajamento, evolução e persistência de cada aluno ativo.

    Engajamento/Evolução partem da nota de evolução (régua justa do ranking),
    mas o ÍNDICE exibido é a posição percentilar — leitura pedagógica de
    distribuição ("onde o aluno está na escola"), não nota competitiva.
    """
    engajamento_bruto = {
        item.aluno_id: item.nota_evolucao
        for item in evolucao.ranking_evolucao(db, escola_id, dias=30)
    }
    crescimento_bruto = {
        item.aluno_id: item.nota_evolucao
        for item in evolucao.ranking_evolucao(db, escola_id, dias=90)
    }
    # Só quem avançou (>0) entra na régua percentilar; quem não avançou fica 0.
    ativos_30 = sorted(v for v in engajamento_bruto.values() if v > 0)
    ativos_90 = sorted(v for v in crescimento_bruto.values() if v > 0)

    def _indice(bruto: dict[int, float], ativos: list[float], aluno_id: int) -> float:
        valor = bruto.get(aluno_id, 0.0)
        return _percentil_rank(ativos, valor) if valor > 0 else 0.0

    escola = db.get(Escola, escola_id)
    # selectinload(Matricula.aluno): o laço lê matricula.aluno.nome; sem isto,
    # cada aluno dispararia um SELECT lazy (N+1). Carrega todos em 1 consulta.
    matriculas = db.execute(
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .options(selectinload(Matricula.aluno))
        .where(Matricula.escola_id == escola_id,
               Matricula.ano_letivo == escola.ano_letivo_ativo,
               Aluno.status == "ativo")
    ).all()

    serie_m = evolucao._series_por_aluno(db, escola_id, SnapshotMatific)
    serie_e = evolucao._series_por_aluno(db, escola_id, SnapshotElefante)

    itens = []
    for matricula, turma in matriculas:
        aluno_id = matricula.aluno_id
        sequencia = gamificacao.sequencia_semanas(
            serie_m.get(aluno_id, []), serie_e.get(aluno_id, [])
        )
        # Persistência = CONSTÂNCIA pura: semanas consecutivas com avanço.
        # (O antigo componente "volume de tentativas ÷ máximo da escola" foi
        # removido: era acumulado de vida normalizado pelo melhor aluno — um
        # outlier zerava a persistência de alunos perfeitamente constantes.)
        persistencia = min(100.0, sequencia * PONTOS_POR_SEMANA_CONSTANCIA)
        itens.append({
            "aluno_id": aluno_id,
            "nome": matricula.aluno.nome,
            "turma": turma.nome,
            "engajamento": _indice(engajamento_bruto, ativos_30, aluno_id),
            "evolucao": _indice(crescimento_bruto, ativos_90, aluno_id),
            "persistencia": round(persistencia, 1),
        })
    itens.sort(key=lambda item: -item["engajamento"])
    return itens


def alertas_da_escola(db: Session, escola_id: int,
                      serie_m: dict[int, list] | None = None,
                      serie_e: dict[int, list] | None = None) -> list[dict]:
    """Alertas automáticos (PRD §139): situações que pedem atenção do professor.

    `serie_m`/`serie_e` podem ser injetados por um chamador que já os carregou
    (ex.: /sincronizacao mobile), evitando reler as tabelas de snapshot."""
    escola = db.get(Escola, escola_id)
    if escola is None:
        return []
    ano = escola.ano_letivo_ativo
    agora = datetime.now(timezone.utc)
    corte_atividade = agora - timedelta(days=DIAS_SEM_ATIVIDADE)

    # selectinload(Matricula.aluno): idem indices_da_escola — o laço lê
    # matricula.aluno.nome; evita N+1. Rota também usada pela sincronização
    # mobile e pelo contexto do Assistente.
    matriculas = db.execute(
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .options(selectinload(Matricula.aluno))
        .where(Matricula.escola_id == escola_id,
               Matricula.ano_letivo == ano,
               Aluno.status == "ativo")
    ).all()

    if serie_m is None:
        serie_m = evolucao._series_por_aluno(db, escola_id, SnapshotMatific)
    if serie_e is None:
        serie_e = evolucao._series_por_aluno(db, escola_id, SnapshotElefante)
    notas = {
        nota.aluno_id: nota
        for nota in db.execute(
            select(Nota).where(Nota.escola_id == escola_id, Nota.ano_letivo == ano)
        ).scalars()
    }

    # MEDIANA da turma para o alerta "muito abaixo da turma" — robusta a
    # outlier: um aluno excepcional não infla a referência nem empurra colegas
    # normais para o alerta (a média aritmética fazia exatamente isso).
    mediana_turma: dict[int, float] = {}
    alunos_por_turma: dict[int, list[int]] = {}
    for matricula, turma in matriculas:
        alunos_por_turma.setdefault(turma.id, []).append(matricula.aluno_id)
    for turma_id, ids in alunos_por_turma.items():
        com_nota = sorted(notas[i].nota_geral for i in ids if i in notas)
        if not com_nota:
            mediana_turma[turma_id] = 0.0
        else:
            meio = len(com_nota) // 2
            mediana_turma[turma_id] = (
                com_nota[meio] if len(com_nota) % 2
                else (com_nota[meio - 1] + com_nota[meio]) / 2
            )

    alertas: list[dict] = []
    for matricula, turma in matriculas:
        aluno_id = matricula.aluno_id
        nome = matricula.aluno.nome
        m = serie_m.get(aluno_id, [])
        e = serie_e.get(aluno_id, [])

        if not m and not e:
            alertas.append({
                "tipo": "sem_dados", "gravidade": "alta",
                "aluno_id": aluno_id, "nome": nome, "turma": turma.nome,
                "texto": f"{nome} ainda não tem nenhum dado importado.",
            })
            continue

        ultima = max(
            (s[-1].data_referencia for s in (m, e) if s),
        )
        ultima_cmp = ultima.replace(tzinfo=timezone.utc) if ultima.tzinfo is None else ultima
        if ultima_cmp < corte_atividade:
            dias = (agora - ultima_cmp).days
            alertas.append({
                "tipo": "sem_atividade", "gravidade": "alta",
                "aluno_id": aluno_id, "nome": nome, "turma": turma.nome,
                "texto": f"{nome} está sem novos dados há {dias} dias.",
            })

        # Queda no percentual de acertos entre os dois últimos snapshots
        if len(e) >= 2:
            atual, anterior = _pct_acertos(e[-1]), _pct_acertos(e[-2])
            if atual is not None and anterior is not None \
                    and anterior - atual >= QUEDA_ACERTOS_PONTOS:
                alertas.append({
                    "tipo": "queda_acertos", "gravidade": "media",
                    "aluno_id": aluno_id, "nome": nome, "turma": turma.nome,
                    "texto": f"{nome} caiu de {anterior}% para {atual}% de acertos nas questões.",
                })

        nota = notas.get(aluno_id)
        mediana = mediana_turma.get(turma.id, 0.0)
        if nota and mediana > 0 and nota.nota_geral < mediana * FRACAO_ABAIXO_TURMA:
            alertas.append({
                "tipo": "abaixo_da_turma", "gravidade": "media",
                "aluno_id": aluno_id, "nome": nome, "turma": turma.nome,
                "texto": (f"{nome} está com nota {nota.nota_geral:.1f}, "
                          f"menos da metade da mediana da turma ({mediana:.1f})."),
            })

    ordem = {"alta": 0, "media": 1, "baixa": 2}
    alertas.sort(key=lambda alerta: (ordem.get(alerta["gravidade"], 9), alerta["nome"]))
    return alertas
