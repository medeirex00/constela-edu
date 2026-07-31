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

from datetime import date, datetime, timedelta, timezone

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
from app.services import evolucao, scoring

DIAS_SEM_ATIVIDADE = 30
QUEDA_ACERTOS_PONTOS = 15.0
FRACAO_ABAIXO_TURMA = 0.5
# Persistência SEMANAL: janela de referência do "ritmo próprio" do aluno (o
# ganho da semana atual é comparado à média das últimas N semanas dele mesmo).
SEMANAS_BASE_PERSISTENCIA = 8


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


def indices_da_escola(db: Session, escola_id: int,
                      serie_m: dict[int, list] | None = None,
                      serie_e: dict[int, list] | None = None,
                      mapa_dif: dict[tuple[str, str], float] | None = None,
                      alunos_com_leituras: set[int] | None = None) -> list[dict]:
    """Engajamento, evolução e persistência de cada aluno ativo.

    Engajamento/Evolução partem da nota de evolução (régua justa do ranking),
    mas o ÍNDICE exibido é a posição percentilar — leitura pedagógica de
    distribuição ("onde o aluno está na escola"), não nota competitiva.

    `serie_m`/`serie_e`/`mapa_dif`/`alunos_com_leituras` são varreduras CARAS e
    independentes da janela; a rota /insights as carrega UMA vez e injeta aqui e
    em `alertas_da_escola`, evitando reler snapshots/leitura duas vezes."""
    escola = db.get(Escola, escola_id)
    # Varreduras CARAS e independentes da janela: carrega UMA vez (ou reusa as
    # injetadas pela rota) e injeta nas 4 chamadas de ranking_evolucao abaixo.
    # Sem isto, cada chamada relê os snapshots (Matific + Elefante), remonta o
    # mapa de dificuldade e refaz o DISTINCT de leituras — ~16 varreduras
    # pesadas por requisição, o que fazia /insights estourar o timeout de 15 s
    # do cliente (a origem do "Não foi possível conectar").
    if serie_m is None:
        serie_m = evolucao._series_por_aluno(db, escola_id, SnapshotMatific)
    if serie_e is None:
        serie_e = evolucao._series_por_aluno(db, escola_id, SnapshotElefante)
    if mapa_dif is None:
        mapa_dif = scoring._mapa_dificuldade(db, escola_id)
    if alunos_com_leituras is None:
        alunos_com_leituras = evolucao._alunos_com_leituras(db, escola_id)

    engajamento_bruto = {
        item.aluno_id: item.nota_evolucao
        for item in evolucao.ranking_evolucao(
            db, escola_id, dias=30, serie_m=serie_m, serie_e=serie_e, mapa_dif=mapa_dif,
            alunos_com_leituras=alunos_com_leituras)
    }
    crescimento_bruto = {
        item.aluno_id: item.nota_evolucao
        for item in evolucao.ranking_evolucao(
            db, escola_id, dias=90, serie_m=serie_m, serie_e=serie_e, mapa_dif=mapa_dif,
            alunos_com_leituras=alunos_com_leituras)
    }
    # Só quem avançou (>0) entra na régua percentilar; quem não avançou fica 0.
    ativos_30 = sorted(v for v in engajamento_bruto.values() if v > 0)
    ativos_90 = sorted(v for v in crescimento_bruto.values() if v > 0)

    def _indice(bruto: dict[int, float], ativos: list[float], aluno_id: int) -> float:
        valor = bruto.get(aluno_id, 0.0)
        return _percentil_rank(ativos, valor) if valor > 0 else 0.0

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

    # PERSISTÊNCIA SEMANAL pelo ritmo do PRÓPRIO aluno (decisão de produto):
    # compara o crescimento da SEMANA ATUAL (segunda→agora) com o ritmo semanal
    # recente dele mesmo (média das últimas N semanas). Não compara com colegas —
    # turma fraca não penaliza. Reusa o motor de evolução (que já normaliza as
    # plataformas numa nota) nas séries já carregadas; as duas janelas usam os
    # MESMOS parâmetros, então a razão semana/ritmo é consistente.
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    iso_hoje = agora.isocalendar()
    inicio_semana = datetime.combine(
        date.fromisocalendar(iso_hoje[0], iso_hoje[1], 1), datetime.min.time())
    inicio_base = agora - timedelta(weeks=SEMANAS_BASE_PERSISTENCIA)
    cresc_semana = {
        i.aluno_id: i.nota_evolucao
        for i in evolucao.ranking_evolucao(db, escola_id, inicio=inicio_semana, fim=agora,
                                           serie_m=serie_m, serie_e=serie_e, mapa_dif=mapa_dif,
                                           alunos_com_leituras=alunos_com_leituras)
    }
    cresc_base = {
        i.aluno_id: i.nota_evolucao
        for i in evolucao.ranking_evolucao(db, escola_id, inicio=inicio_base, fim=agora,
                                           serie_m=serie_m, serie_e=serie_e, mapa_dif=mapa_dif,
                                           alunos_com_leituras=alunos_com_leituras)
    }

    def _persistencia_semanal(aluno_id: int) -> float:
        semana = cresc_semana.get(aluno_id, 0.0)
        ritmo = cresc_base.get(aluno_id, 0.0) / SEMANAS_BASE_PERSISTENCIA
        if ritmo <= 0:
            return 100.0 if semana > 0 else 0.0   # sem histórico: começou a se mexer
        return round(min(100.0, 100.0 * semana / ritmo), 1)  # 100 = manteve/superou o próprio ritmo

    itens = []
    for matricula, turma in matriculas:
        aluno_id = matricula.aluno_id
        itens.append({
            "aluno_id": aluno_id,
            "nome": matricula.aluno.nome,
            "turma": turma.nome,
            "engajamento": _indice(engajamento_bruto, ativos_30, aluno_id),
            "evolucao": _indice(crescimento_bruto, ativos_90, aluno_id),
            "persistencia": _persistencia_semanal(aluno_id),
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
