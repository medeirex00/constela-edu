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
from sqlalchemy.orm import Session

from app.core.tempo import para_br
from app.models import (
    Escola,
    Nota,
    SnapshotElefante,
    SnapshotMatific,
)
from app.services import dificuldade_livro, evolucao, scoring
from app.services import dimensoes as svc_dimensoes

DIAS_SEM_ATIVIDADE = 30
QUEDA_ACERTOS_PONTOS = 15.0
FRACAO_ABAIXO_TURMA = 0.5
# Persistência SEMANAL: janela de referência do "ritmo próprio" do aluno (o
# ganho da semana atual é comparado à média das últimas N semanas dele mesmo).
SEMANAS_BASE_PERSISTENCIA = 8


def _num_br(valor: float, casas: int = 1) -> str:
    """Número com vírgula decimal (pt-BR) para o TEXTO dos alertas.

    O texto vai pronto para a tela ("Precisa de atenção", Insights), que no
    resto mostra as notas como "72,8"; o "23.2" destoava. Só a escrita muda:
    o valor comparado e o critério do alerta continuam os mesmos.
    """
    return f"{valor:.{casas}f}".replace(".", ",")


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


@scoring.com_leituras_da_requisicao
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
    if mapa_dif is None:   # a REGRA de dificuldade (fonte única)
        mapa_dif = dificuldade_livro.regra_da_escola(db, escola_id)
    if alunos_com_leituras is None:
        alunos_com_leituras = evolucao._alunos_com_leituras(db, escola_id)

    # RÉGUA JUSTA (`base_no_periodo=True`) nas 4 janelas, a mesma do Ranking de
    # Evolução, do app e do telão: sem retrato ANTERIOR à janela, o acumulado de
    # vida não vira avanço. Com o padrão antigo, a criança cujo 1º retrato caía
    # dentro dos 30 dias tinha o MAIOR engajamento sem ter avançado nada nele.
    engajamento_bruto = {
        item.aluno_id: item.nota_evolucao
        for item in evolucao.ranking_evolucao(
            db, escola_id, dias=30, serie_m=serie_m, serie_e=serie_e, mapa_dif=mapa_dif,
            alunos_com_leituras=alunos_com_leituras,
            base_no_periodo=True)
    }
    crescimento_bruto = {
        item.aluno_id: item.nota_evolucao
        for item in evolucao.ranking_evolucao(
            db, escola_id, dias=90, serie_m=serie_m, serie_e=serie_e, mapa_dif=mapa_dif,
            alunos_com_leituras=alunos_com_leituras,
            base_no_periodo=True)
    }
    # Só quem avançou (>0) entra na régua percentilar; quem não avançou fica 0.
    ativos_30 = sorted(v for v in engajamento_bruto.values() if v > 0)
    ativos_90 = sorted(v for v in crescimento_bruto.values() if v > 0)

    def _indice(bruto: dict[int, float], ativos: list[float], aluno_id: int) -> float:
        valor = bruto.get(aluno_id, 0.0)
        return _percentil_rank(ativos, valor) if valor > 0 else 0.0

    # O laço lê matricula.aluno.nome: a coorte vem com o aluno carregado (sem um
    # SELECT por aluno) e é a MESMA das quatro janelas acima (uma ida no bloco).
    matriculas = evolucao.matriculas_ativas(db, escola_id, escola.ano_letivo_ativo)

    # PERSISTÊNCIA SEMANAL pelo ritmo do PRÓPRIO aluno (decisão de produto):
    # compara o crescimento da SEMANA ATUAL (segunda→agora) com o ritmo semanal
    # recente dele mesmo (média das últimas N semanas). Não compara com colegas —
    # turma fraca não penaliza. Reusa o motor de evolução (que já normaliza as
    # plataformas numa nota) nas séries já carregadas; as duas janelas usam os
    # MESMOS parâmetros, então a razão semana/ritmo é consistente.
    agora_utc = datetime.now(timezone.utc)
    agora = agora_utc.replace(tzinfo=None)   # UTC naive: cobre retratos e leituras
    # A SEMANA ATUAL é a de BRASÍLIA (segunda 00h, horário de parede), a mesma do
    # preset "Esta semana" (`periodos.resolver` com `hoje_br`): `Leitura.data` é
    # horário de parede de Brasília. Pela semana do relógio UTC, no domingo depois
    # das 21h (BRT) o UTC já era segunda, a "semana atual" começava amanhã e a
    # persistência de todos caía a 0. Como nas demais janelas por período, o
    # retrato (UTC naive) é comparado com esse mesmo limite.
    hoje = para_br(agora_utc).date()
    inicio_semana = datetime.combine(hoje - timedelta(days=hoje.weekday()),
                                     datetime.min.time())
    inicio_base = agora - timedelta(weeks=SEMANAS_BASE_PERSISTENCIA)
    cresc_semana = {
        i.aluno_id: i.nota_evolucao
        for i in evolucao.ranking_evolucao(db, escola_id, inicio=inicio_semana, fim=agora,
                                           serie_m=serie_m, serie_e=serie_e, mapa_dif=mapa_dif,
                                           alunos_com_leituras=alunos_com_leituras,
                                           base_no_periodo=True)
    }
    cresc_base = {
        i.aluno_id: i.nota_evolucao
        for i in evolucao.ranking_evolucao(db, escola_id, inicio=inicio_base, fim=agora,
                                           serie_m=serie_m, serie_e=serie_e, mapa_dif=mapa_dif,
                                           alunos_com_leituras=alunos_com_leituras,
                                           base_no_periodo=True)
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


@scoring.com_leituras_da_requisicao
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

    # Idem indices_da_escola — o laço lê matricula.aluno.nome; a coorte vem com
    # o aluno carregado. Rota também usada pela sincronização mobile e pelo
    # contexto do Assistente (no pacote do app, a mesma coorte do mural).
    matriculas = evolucao.matriculas_ativas(db, escola_id, ano)

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
    #
    # POR DIMENSÃO (Arquitetura 2, docs/spec-arquitetura-2.md, "ausência nunca
    # vira zero ... nem no alerta 'abaixo da turma'"): a mediana é só entre os
    # AFERIDOS daquela dimensão, e o aluno só é comparado nas dimensões em que
    # ele próprio foi aferido. Antes era a mediana de `nota_geral` (legado) da
    # turma inteira: os zeros de quem nunca teve dado puxavam a referência para
    # baixo e o próprio aluno sem dado disparava "está com nota 0,0".
    contratadas = scoring.dimensoes_contratadas(db, escola)
    mediana_turma: dict[int, dict[str, float]] = {}
    alunos_por_turma: dict[int, list[int]] = {}
    for matricula, turma in matriculas:
        alunos_por_turma.setdefault(turma.id, []).append(matricula.aluno_id)
    for turma_id, ids in alunos_por_turma.items():
        mediana_turma[turma_id] = {}
        for dimensao in contratadas:
            coluna, marca, _ = svc_dimensoes.COLUNAS[dimensao]
            com_nota = sorted(getattr(notas[i], coluna) or 0.0 for i in ids
                              if i in notas and getattr(notas[i], marca))
            if not com_nota:
                continue
            meio = len(com_nota) // 2
            mediana_turma[turma_id][dimensao] = (
                com_nota[meio] if len(com_nota) % 2
                else (com_nota[meio - 1] + com_nota[meio]) / 2
            )

    # CONTRATO (o mesmo corte do motor, `scoring._carregar_contexto`): retrato da
    # plataforma de um módulo que a rede NÃO contratou não é dado do aluno. Sem
    # isto, um retrato recente do Matific numa rede só com Leitura escondia o
    # "sem novos dados" de quem parou de ler, e quem só tinha Matific aparecia
    # "sem novos dados há N dias" em vez de "ainda não tem nenhum dado".
    fora = {plataforma for dimensao, plataforma in scoring.DIMENSOES.items()
            if dimensao not in contratadas}

    alertas: list[dict] = []
    for matricula, turma in matriculas:
        aluno_id = matricula.aluno_id
        nome = matricula.aluno.nome
        m = [] if "matific" in fora else serie_m.get(aluno_id, [])
        e = [] if "elefante" in fora else serie_e.get(aluno_id, [])

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
                    "texto": (f"{nome} caiu de {_num_br(anterior)}% para "
                              f"{_num_br(atual)}% de acertos nas questões."),
                })

        # Um alerta POR DIMENSÃO, só nas que o aluno foi aferido: "abaixo da
        # turma em Leitura" é acionável; sem dizer em quê, não era.
        nota = notas.get(aluno_id)
        for dimensao, mediana in mediana_turma.get(turma.id, {}).items():
            coluna, marca, _ = svc_dimensoes.COLUNAS[dimensao]
            if not nota or not getattr(nota, marca) or mediana <= 0:
                continue
            valor = getattr(nota, coluna) or 0.0
            if valor < mediana * FRACAO_ABAIXO_TURMA:
                alertas.append({
                    "tipo": "abaixo_da_turma", "gravidade": "media",
                    "aluno_id": aluno_id, "nome": nome, "turma": turma.nome,
                    "dimensao": dimensao,
                    "texto": (f"{nome} está com nota {_num_br(valor)} em "
                              f"{svc_dimensoes.ROTULOS[dimensao]}, menos da metade "
                              f"da mediana da turma ({_num_br(mediana)})."),
                })

    ordem = {"alta": 0, "media": 1, "baixa": 2}
    alertas.sort(key=lambda alerta: (ordem.get(alerta["gravidade"], 9), alerta["nome"]))
    return alertas
