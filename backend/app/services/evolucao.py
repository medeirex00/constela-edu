"""Evolução e histórico (PRD §67–§78).

Toda a base vem dos snapshots imutáveis da Fase 1: a evolução é sempre a
comparação entre o último snapshot anterior ao período (linha de base) e o
snapshot mais recente. Nenhum dado novo é gravado aqui — apenas leitura.

O Ranking de Evolução reaproveita o próprio motor de cálculo aplicado aos
GANHOS do período: os mesmos pesos configuráveis, a mesma normalização
0–100 (referência = maior ganho da escola). Indicadores não cumulativos
(pontuação média) entram pela variação positiva — quem manteve não perde,
quem cresceu pontua.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Aluno,
    Escola,
    Leitura,
    Livro,
    Matricula,
    Nota,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import scoring

CAMPOS_MATIFIC = ("atividades", "estrelas", "pontuacao_media")
CAMPOS_ELEFANTE = ("livros_unicos", "tempo_leitura_min", "questoes_tentativas", "questoes_acertos")


def _sem_fuso(momento: datetime) -> datetime:
    """SQLite devolve datetimes ingênuos; normaliza para comparar com segurança."""
    return momento.replace(tzinfo=None) if momento.tzinfo else momento


def _series_por_aluno(db: Session, escola_id: int, modelo) -> dict[int, list]:
    """Todos os snapshots da escola agrupados por aluno, em ordem cronológica.

    Ordem por data_referencia (id desempata): o import por período do Matific
    pode gravar um mês ANTIGO depois (backfill) — por id, a série ficaria fora
    de ordem e _janela/_baseline elegeriam o passado como "atual"."""
    series: dict[int, list] = {}
    for snap in db.execute(
        select(modelo).where(modelo.escola_id == escola_id)
        .order_by(modelo.data_referencia, modelo.id)
    ).scalars():
        series.setdefault(snap.aluno_id, []).append(snap)
    return series


def _baseline(serie: list, inicio: datetime):
    """Último snapshot ANTERIOR ao início do período (None = começou do zero)."""
    inicio = _sem_fuso(inicio)
    anterior = None
    for snap in serie:
        if _sem_fuso(snap.data_referencia) < inicio:
            anterior = snap
    return anterior


def _delta(atual, anterior, campo: str) -> float:
    """Ganho no período, nunca negativo (dados cumulativos não regridem;
    correções manuais para baixo não podem gerar evolução negativa)."""
    valor_atual = float(getattr(atual, campo, 0) or 0) if atual else 0.0
    valor_anterior = float(getattr(anterior, campo, 0) or 0) if anterior else 0.0
    return max(0.0, round(valor_atual - valor_anterior, 2))


def _delta_niveis(atual, anterior) -> dict[str, int]:
    atuais: dict = (atual.livros_por_nivel or {}) if atual else {}
    anteriores: dict = (anterior.livros_por_nivel or {}) if anterior else {}
    ganhos = {}
    for codigo, quantidade in atuais.items():
        ganho = int(quantidade) - int(anteriores.get(codigo, 0))
        if ganho > 0:
            ganhos[codigo] = ganho
    return ganhos


def _janela(serie: list, inicio: datetime | None, fim: datetime | None,
            base_no_periodo: bool = False):
    """(atual, base) para medir o GANHO dentro de [inicio, fim].

    atual = último snapshot com data_referencia <= fim (respeita o fim do
    período; antes usava-se serie[-1], que podia estar depois do fim).
    base = último snapshot ANTES do início.

    Quando NÃO há estado anterior ao início:
      * base_no_periodo=False (padrão): base = None → o ganho vira o total
        acumulado ("aluno novo evolui a partir do zero"). É o comportamento
        das telas de evolução/mural.
      * base_no_periodo=True: base = 1º snapshot DENTRO do período → só o
        crescimento observado no intervalo conta (o acumulado anterior nunca
        é atribuído ao período). É o exigido pelas PREMIAÇÕES (justas)."""
    atual = None
    for snap in serie:
        if fim is None or _sem_fuso(snap.data_referencia) <= fim:
            atual = snap
    if atual is None:
        return None, None
    base = None
    if inicio is not None:
        for snap in serie:
            if _sem_fuso(snap.data_referencia) < inicio:
                base = snap
        if base is None and base_no_periodo:
            dentro = [s for s in serie
                      if _sem_fuso(s.data_referencia) >= inicio
                      and (fim is None or _sem_fuso(s.data_referencia) <= fim)]
            base = dentro[0] if dentro else atual
    return atual, base


# ---------------------------------------------------------------------------
# Evolução de LEITURA por período (livros/pontos/tempo/nível por bucket) —
# habilitada pela data+hora real de cada leitura (Fase 1). Diferente da
# evolução por snapshots, esta agrega as leituras individuais no tempo.
# ---------------------------------------------------------------------------

_MES_ABREV = {1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
              7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez"}


def _bucket_leitura(dt: datetime, granularidade: str) -> tuple[tuple, str]:
    """(chave ordenável, rótulo) do balde temporal da leitura."""
    if granularidade == "semana":
        ano, semana, _ = dt.isocalendar()
        return (ano, semana), f"Sem {semana:02d}/{ano}"
    if granularidade == "bimestre":
        bimestre = (dt.month - 1) // 2 + 1
        return (dt.year, bimestre), f"{bimestre}º bim {dt.year}"
    return (dt.year, dt.month), f"{_MES_ABREV[dt.month]}/{dt.year}"  # mês (padrão)


def evolucao_leitura(db: Session, escola_id: int, aluno_id: int,
                     granularidade: str = "mes",
                     inicio: datetime | None = None,
                     fim: datetime | None = None) -> dict:
    """Séries cronológicas por semana/mês/bimestre: livros lidos, pontos de
    dificuldade, tempo e nível médio (pontos por livro) do período."""
    consulta = (
        select(Leitura.data, Livro.nivel_codigo, Leitura.tempo_leitura_min)
        .join(Livro, Leitura.livro_id == Livro.id)
        .where(Leitura.aluno_id == aluno_id)
    )
    if inicio is not None:
        consulta = consulta.where(Leitura.data >= inicio)
    if fim is not None:
        consulta = consulta.where(Leitura.data <= fim)

    # Pontos resolvidos pela TURMA do aluno (TURMA>SÉRIE>padrão) — mesma régua do
    # ranking anual; sem isto a evolução usava a pontuação padrão da escola.
    mat = db.execute(
        select(Turma.id, Turma.ano_escolar)
        .join(Matricula, Matricula.turma_id == Turma.id)
        .where(Matricula.aluno_id == aluno_id)
        .order_by(Matricula.ano_letivo.desc())
    ).first()
    turma_id, ano_escolar = (mat[0], mat[1]) if mat else (None, None)
    pontos_map = scoring.pontos_por_codigo(db, escola_id, turma_id, ano_escolar)
    baldes: dict[tuple, dict] = {}
    for data, codigo, tempo in db.execute(consulta.order_by(Leitura.data)).all():
        chave, rotulo = _bucket_leitura(_sem_fuso(data), granularidade)
        balde = baldes.setdefault(chave, {"rotulo": rotulo, "livros": 0,
                                          "pontos": 0.0, "tempo_min": 0})
        balde["livros"] += 1
        balde["pontos"] += pontos_map.get((codigo or "").upper(), 0.0)
        balde["tempo_min"] += tempo or 0

    series = []
    for chave in sorted(baldes):
        b = baldes[chave]
        series.append({
            "rotulo": b["rotulo"],
            "livros": b["livros"],
            "pontos": round(b["pontos"], 2),
            "tempo_min": b["tempo_min"],
            "nivel_medio": round(b["pontos"] / b["livros"], 2) if b["livros"] else 0.0,
        })
    return {"granularidade": granularidade, "series": series}


# ---------------------------------------------------------------------------
# Linha do tempo e resumo de evolução por aluno (PRD §67–§71)
# ---------------------------------------------------------------------------

def linha_do_tempo(db: Session, escola_id: int, aluno_id: int,
                   dias: int | None = None) -> dict:
    """Série temporal dos snapshots do aluno. `dias` recorta a janela (o seletor
    de período da tela: 7/30/90/365); None traz todo o histórico."""
    inicio = None
    if dias is not None:
        inicio = (datetime.now(timezone.utc) - timedelta(days=dias)).replace(tzinfo=None)

    def consultar(modelo):
        consulta = (
            select(modelo)
            .where(modelo.escola_id == escola_id, modelo.aluno_id == aluno_id)
            .order_by(modelo.data_referencia, modelo.id)
        )
        if inicio is not None:
            consulta = consulta.where(modelo.data_referencia >= inicio)
        return db.execute(consulta).scalars().all()

    matific = consultar(SnapshotMatific)
    elefante = consultar(SnapshotElefante)
    return {
        "matific": [
            {
                "data": snap.data_referencia,
                "atividades": snap.atividades,
                "estrelas": snap.estrelas,
                "pontuacao_media": snap.pontuacao_media,
            }
            for snap in matific
        ],
        "elefante": [
            {
                "data": snap.data_referencia,
                "livros_unicos": snap.livros_unicos,
                "tempo_leitura_min": snap.tempo_leitura_min,
                "questoes_tentativas": snap.questoes_tentativas,
                "questoes_acertos": snap.questoes_acertos,
            }
            for snap in elefante
        ],
    }


def resumo_evolucao(db: Session, escola_id: int, aluno_id: int, dias: int) -> dict:
    """Variação de cada indicador no período, com percentual quando possível."""
    inicio = datetime.now(timezone.utc) - timedelta(days=dias)
    indicadores = []
    for modelo, campos in ((SnapshotMatific, CAMPOS_MATIFIC), (SnapshotElefante, CAMPOS_ELEFANTE)):
        serie = [
            snap for snap in db.execute(
                select(modelo)
                .where(modelo.escola_id == escola_id, modelo.aluno_id == aluno_id)
                .order_by(modelo.data_referencia, modelo.id)
            ).scalars()
        ]
        atual = serie[-1] if serie else None
        anterior = _baseline(serie, inicio)
        for campo in campos:
            valor_inicial = float(getattr(anterior, campo, 0) or 0) if anterior else 0.0
            valor_atual = float(getattr(atual, campo, 0) or 0) if atual else 0.0
            variacao = round(valor_atual - valor_inicial, 2)
            indicadores.append({
                "indicador": campo,
                "inicial": valor_inicial,
                "atual": valor_atual,
                "variacao": variacao,
                "percentual": round(variacao / valor_inicial * 100, 1) if valor_inicial else None,
            })
    return {"dias": dias, "indicadores": indicadores}


# ---------------------------------------------------------------------------
# Ranking de Evolução (PRD §72 — independente do Ranking Geral)
# ---------------------------------------------------------------------------

@dataclass
class ItemEvolucao:
    aluno_id: int
    nome: str
    turma: str
    ano_escolar: str
    nota_evolucao: float
    ganhos: dict
    posicao: int = 0


def _alunos_com_leituras(db: Session, escola_id: int) -> set[int]:
    """Quem tem QUALQUER leitura individual registrada. Varredura INDEPENDENTE
    da janela — um chamador que rode várias janelas (o /insights: 30d/90d/semana/
    base) carrega UMA vez e injeta em `_leituras_no_periodo`/`ranking_evolucao`."""
    return set(db.execute(
        select(Leitura.aluno_id).where(Leitura.escola_id == escola_id).distinct()
    ).scalars().all())


def _leituras_no_periodo(db: Session, escola_id: int,
                         inicio: datetime | None,
                         fim: datetime | None,
                         alunos_com_leituras: set[int] | None = None,
                         ) -> tuple[set[int], dict[int, dict]]:
    """Leituras REAIS dentro do período, agregadas por aluno.

    Devolve (alunos_com_leituras, dados_no_periodo):
      * alunos_com_leituras — quem tem QUALQUER leitura individual registrada
        (para esses, a verdade do período vem das datas reais de cada livro);
      * dados_no_periodo — {aluno_id: {livros, tempo_min, por_nivel}} contando
        somente as leituras cuja DATA cai no intervalo. Um PDF importado hoje
        cobrindo meses não atribui tudo a hoje: cada livro conta no dia em que
        foi realmente lido.

    `alunos_com_leituras` (independente da janela) pode ser injetado para não
    repetir o DISTINCT a cada janela."""
    if alunos_com_leituras is None:
        alunos_com_leituras = _alunos_com_leituras(db, escola_id)

    consulta = (
        select(Leitura.aluno_id, Livro.nivel_codigo, Leitura.tempo_leitura_min)
        .join(Livro, Leitura.livro_id == Livro.id)
        .where(Leitura.escola_id == escola_id)
    )
    if inicio is not None:
        consulta = consulta.where(Leitura.data >= inicio)
    if fim is not None:
        consulta = consulta.where(Leitura.data <= fim)

    dados: dict[int, dict] = {}
    for aluno_id, codigo, tempo in db.execute(consulta).all():
        item = dados.setdefault(aluno_id, {"livros": 0, "tempo_min": 0, "por_nivel": {}})
        item["livros"] += 1
        item["tempo_min"] += tempo or 0
        chave = (codigo or "").upper()
        if chave:
            item["por_nivel"][chave] = item["por_nivel"].get(chave, 0) + 1
    return alunos_com_leituras, dados


def series_e_dificuldade(
    db: Session, escola_id: int,
) -> tuple[dict[int, list], dict[int, list], dict[tuple[str, str], float]]:
    """Pré-carrega, UMA vez, as varreduras CARAS e independentes de janela —
    séries de Matific/Elefante + mapa de dificuldade. Um chamador que faça
    VÁRIAS leituras derivadas no mesmo request (ex.: /sincronizacao mobile:
    alertas + mural + ranking de evolução) injeta o resultado nessas funções em
    vez de cada uma reler as tabelas de snapshot (mesma estratégia do mural/M4)."""
    serie_m = _series_por_aluno(db, escola_id, SnapshotMatific)
    serie_e = _series_por_aluno(db, escola_id, SnapshotElefante)
    mapa_dif = scoring._mapa_dificuldade(db, escola_id)
    return serie_m, serie_e, mapa_dif


def ranking_evolucao(db: Session, escola_id: int, inicio: datetime | None = None,
                     fim: datetime | None = None, turma_id: int | None = None,
                     ano_escolar: str | None = None,
                     dias: int | None = None,
                     turma_ids: list[int] | None = None,
                     serie_m: dict[int, list] | None = None,
                     serie_e: dict[int, list] | None = None,
                     mapa_dif: dict[tuple[str, str], float] | None = None,
                     alunos_com_leituras: set[int] | None = None,
                     base_no_periodo: bool = False,
                     ) -> list[ItemEvolucao]:
    """Ranking de quem mais cresceu DENTRO da janela [inicio, fim] (o ganho é
    medido pela `_janela`, que ignora o acumulado anterior ao período).

    `dias` é um atalho retrocompatível: sem `inicio`, usa os últimos N dias.

    `serie_m`/`serie_e`/`mapa_dif` são as varreduras CARAS e INDEPENDENTES da
    janela; um chamador que precise de VÁRIAS janelas (o mural: dia/semana/mês)
    pode carregá-las UMA vez e injetá-las aqui, em vez de o serviço relê-las a
    cada chamada. `alunos_com_leituras` (o DISTINCT de quem tem leitura, também
    independente da janela) idem. Só a AGREGAÇÃO por janela de
    `_leituras_no_periodo` continua por chamada (depende do intervalo)."""
    escola = db.get(Escola, escola_id)
    if escola is None:
        return []
    if inicio is None and dias is not None:
        inicio = (datetime.now(timezone.utc) - timedelta(days=dias)).replace(tzinfo=None)

    consulta = (
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .where(
            Matricula.escola_id == escola_id,
            Matricula.ano_letivo == escola.ano_letivo_ativo,
            Aluno.status == "ativo",
        )
    )
    if turma_id:
        consulta = consulta.where(Turma.id == turma_id)
    if ano_escolar:
        consulta = consulta.where(Turma.ano_escolar == ano_escolar)
    if turma_ids is not None:  # professor: só as turmas designadas a ele
        consulta = consulta.where(Turma.id.in_(turma_ids))
    consulta = consulta.options(selectinload(Matricula.aluno))  # evita N+1
    matriculas = db.execute(consulta).all()

    # Varreduras independentes da janela: reusa as injetadas (mural) ou carrega.
    if serie_m is None:
        serie_m = _series_por_aluno(db, escola_id, SnapshotMatific)
    if serie_e is None:
        serie_e = _series_por_aluno(db, escola_id, SnapshotElefante)
    if mapa_dif is None:
        mapa_dif = scoring._mapa_dificuldade(db, escola_id)
    # Leituras com data REAL: para quem tem relatório individual importado, o
    # ganho de leitura do período vem do que foi DE FATO lido no intervalo.
    com_leituras, leituras_periodo = _leituras_no_periodo(
        db, escola_id, inicio, fim, alunos_com_leituras)

    # Ganhos por aluno no período (snapshots sintéticos alimentam o motor)
    ganhos_m: dict[int, SimpleNamespace] = {}
    ganhos_e: dict[int, SimpleNamespace] = {}
    pontos_dif: dict[int, float] = {}
    for matricula, turma in matriculas:
        aluno_id = matricula.aluno_id
        atual_m, base_m = _janela(serie_m.get(aluno_id, []), inicio, fim,
                                  base_no_periodo=base_no_periodo)
        ganhos_m[aluno_id] = SimpleNamespace(
            atividades=_delta(atual_m, base_m, "atividades"),
            estrelas=_delta(atual_m, base_m, "estrelas"),
            pontuacao_media=_delta(atual_m, base_m, "pontuacao_media"),
        )
        atual_e, base_e = _janela(serie_e.get(aluno_id, []), inicio, fim,
                                  base_no_periodo=base_no_periodo)
        # Questões só existem agregadas (snapshot); leitura tem data real.
        questoes_t = _delta(atual_e, base_e, "questoes_tentativas")
        questoes_a = _delta(atual_e, base_e, "questoes_acertos")
        if aluno_id in com_leituras:
            # Fonte exata: as leituras individuais datadas dentro do período.
            reais = leituras_periodo.get(aluno_id, {"livros": 0, "tempo_min": 0,
                                                    "por_nivel": {}})
            livros = float(reais["livros"])
            tempo = float(reais["tempo_min"])
            niveis_ganho = reais["por_nivel"]
        else:
            # Aluno acompanhado só pelo relatório da turma: delta de snapshot.
            livros = _delta(atual_e, base_e, "livros_unicos")
            tempo = _delta(atual_e, base_e, "tempo_leitura_min")
            niveis_ganho = _delta_niveis(atual_e, base_e)
        ganhos_e[aluno_id] = SimpleNamespace(
            livros_unicos=livros,
            tempo_leitura_min=tempo,
            questoes_tentativas=questoes_t,
            questoes_acertos=questoes_a,
        )
        pontos_dif[aluno_id] = scoring._pontos_dificuldade(
            niveis_ganho, turma.ano_escolar, mapa_dif, turma.id
        )

    # Referências JUSTAS sobre os ganhos (mesma régua do Geral): P90 dos ativos
    # + saturação de volume (k=mediana). Um único aluno-gigante deixa de ser a
    # régua de todos — o topo fica disputado; quem mais cresceu segue na frente.
    # Turma pequena recai no máximo (comportamento antigo), via a própria helper.
    refs, k_vol = scoring.referencias_robustas({
        "atividades": [g.atividades for g in ganhos_m.values()],
        "media": [g.pontuacao_media for g in ganhos_m.values()],
        "estrelas": [g.estrelas for g in ganhos_m.values()],
        "livros": [g.livros_unicos for g in ganhos_e.values()],
        "pontos_dificuldade": list(pontos_dif.values()),
        "tentativas": [g.questoes_tentativas for g in ganhos_e.values()],
        "acertos": [g.questoes_acertos for g in ganhos_e.values()],
        "tempo": [g.tempo_leitura_min for g in ganhos_e.values()],
    })

    p_matific = scoring.obter_pesos(db, escola_id, "pesos.matific")
    p_elefante = scoring.obter_pesos(db, escola_id, "pesos.elefante")
    p_questoes = scoring.obter_pesos(db, escola_id, "pesos.questoes")
    p_geral = scoring.obter_pesos(db, escola_id, "pesos.geral")
    pct_matific = scoring.obter_pesos_brutos(db, escola_id, "pesos.matific")
    pct_elefante = scoring.obter_pesos_brutos(db, escola_id, "pesos.elefante")
    pct_questoes = scoring.obter_pesos_brutos(db, escola_id, "pesos.questoes")

    itens: list[ItemEvolucao] = []
    for matricula, turma in matriculas:
        aluno_id = matricula.aluno_id
        nota_m, _ = scoring.calcular_matific(
            ganhos_m[aluno_id], refs, p_matific, pct_matific, k_vol)
        nota_e, _, _ = scoring.calcular_elefante(
            ganhos_e[aluno_id], pontos_dif[aluno_id], refs,
            p_elefante, pct_elefante, p_questoes, pct_questoes, k_vol,
        )
        nota = round(nota_m * p_geral.get("matific", 0) + nota_e * p_geral.get("elefante", 0), 2)
        ganhos = {
            "atividades": ganhos_m[aluno_id].atividades,
            "estrelas": ganhos_m[aluno_id].estrelas,
            "livros": ganhos_e[aluno_id].livros_unicos,
            "tempo_leitura_min": ganhos_e[aluno_id].tempo_leitura_min,
            "acertos": ganhos_e[aluno_id].questoes_acertos,
        }
        itens.append(ItemEvolucao(
            aluno_id=aluno_id, nome=matricula.aluno.nome, turma=turma.nome,
            ano_escolar=turma.ano_escolar, nota_evolucao=nota, ganhos=ganhos,
        ))

    itens.sort(key=lambda item: (-item.nota_evolucao, item.nome.casefold()))
    for posicao, item in enumerate(itens, start=1):
        item.posicao = posicao
    return itens


# ---------------------------------------------------------------------------
# Agregados de turma e escola (PRD §76–§78)
# ---------------------------------------------------------------------------

def _indicadores_atuais(db: Session, escola_id: int, aluno_ids: list[int],
                        matific=None, elefante=None) -> dict:
    """Soma/média dos snapshots mais recentes dos alunos indicados.

    `matific`/`elefante` pré-carregados evitam varrer a escola inteira a
    cada turma (resumo_escola já carrega uma vez e repassa)."""
    if matific is None:
        matific = scoring._snapshots_atuais(db, escola_id, SnapshotMatific)
    if elefante is None:
        elefante = scoring._snapshots_atuais(db, escola_id, SnapshotElefante)
    total = {
        "atividades": 0, "estrelas": 0, "pontuacao_media": 0.0,
        "livros_unicos": 0, "tempo_leitura_min": 0,
        "questoes_tentativas": 0, "questoes_acertos": 0,
    }
    com_media = 0
    for aluno_id in aluno_ids:
        snap_m = matific.get(aluno_id)
        if snap_m:
            total["atividades"] += snap_m.atividades
            total["estrelas"] += snap_m.estrelas
            total["pontuacao_media"] += snap_m.pontuacao_media
            com_media += 1
        snap_e = elefante.get(aluno_id)
        if snap_e:
            total["livros_unicos"] += snap_e.livros_unicos
            total["tempo_leitura_min"] += snap_e.tempo_leitura_min
            total["questoes_tentativas"] += snap_e.questoes_tentativas
            total["questoes_acertos"] += snap_e.questoes_acertos
    total["pontuacao_media"] = round(total["pontuacao_media"] / com_media, 2) if com_media else 0.0
    return total


def _monta_resumo_turma(turma: Turma, aluno_ids: list[int], notas: list[Nota],
                        indicadores: dict) -> dict:
    """Monta o dict de resumo de UMA turma a partir de dados já carregados
    (matrículas + notas). Sem consulta ao banco — o chamador decide se carrega
    por turma (`resumo_turma`) ou em lote (`resumo_escola`)."""
    media_geral = round(sum(n.nota_geral for n in notas) / len(notas), 2) if notas else 0.0
    media_matific = round(sum(n.nota_matific for n in notas) / len(notas), 2) if notas else 0.0
    media_elefante = round(sum(n.nota_elefante for n in notas) / len(notas), 2) if notas else 0.0
    return {
        "turma": {"id": turma.id, "nome": turma.nome, "ano_escolar": turma.ano_escolar},
        "total_alunos": len(aluno_ids),
        "media_geral": media_geral,
        "media_matific": media_matific,
        "media_elefante": media_elefante,
        "indicadores": indicadores,
    }


def resumo_turma(db: Session, escola_id: int, turma_id: int,
                 matific=None, elefante=None) -> dict | None:
    turma = db.get(Turma, turma_id)
    if turma is None or turma.escola_id != escola_id:
        return None
    escola = db.get(Escola, escola_id)
    matriculas = db.execute(
        select(Matricula)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .where(Matricula.turma_id == turma_id,
               Matricula.ano_letivo == escola.ano_letivo_ativo,
               Aluno.status == "ativo")
    ).scalars().all()
    aluno_ids = [m.aluno_id for m in matriculas]

    notas = db.execute(
        select(Nota).where(Nota.escola_id == escola_id,
                           Nota.ano_letivo == escola.ano_letivo_ativo,
                           Nota.aluno_id.in_(aluno_ids or [0]))
    ).scalars().all()
    indicadores = _indicadores_atuais(db, escola_id, aluno_ids, matific, elefante)
    return _monta_resumo_turma(turma, aluno_ids, notas, indicadores)


def resumo_escola(db: Session, escola_id: int) -> dict:
    """Visão da escola inteira: totais e comparação entre turmas (PRD §78)."""
    escola = db.get(Escola, escola_id)
    turmas = db.execute(
        select(Turma).where(Turma.escola_id == escola_id,
                            Turma.ano_letivo == escola.ano_letivo_ativo)
        .order_by(Turma.ano_escolar, Turma.nome)
    ).scalars().all()
    # Carrega os snapshots da escola UMA vez e repassa a cada turma (antes,
    # cada turma varria a escola inteira duas vezes).
    matific = scoring._snapshots_atuais(db, escola_id, SnapshotMatific)
    elefante = scoring._snapshots_atuais(db, escola_id, SnapshotElefante)

    # Matrículas ativas e notas de TODAS as turmas em DUAS consultas (antes,
    # resumo_turma disparava 2 por turma — N+1 que crescia com a escola).
    turma_ids = [t.id for t in turmas]
    matriculas = db.execute(
        select(Matricula)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .where(Matricula.turma_id.in_(turma_ids or [0]),
               Matricula.ano_letivo == escola.ano_letivo_ativo,
               Aluno.status == "ativo")
    ).scalars().all()
    alunos_por_turma: dict[int, list[int]] = {}
    for m in matriculas:
        alunos_por_turma.setdefault(m.turma_id, []).append(m.aluno_id)

    todos_ids = [aid for ids in alunos_por_turma.values() for aid in ids]
    notas_por_aluno: dict[int, Nota] = {
        n.aluno_id: n
        for n in db.execute(
            select(Nota).where(Nota.escola_id == escola_id,
                               Nota.ano_letivo == escola.ano_letivo_ativo,
                               Nota.aluno_id.in_(todos_ids or [0]))
        ).scalars()
    }

    resumos = []
    for turma in turmas:
        aluno_ids = alunos_por_turma.get(turma.id, [])
        notas = [notas_por_aluno[a] for a in aluno_ids if a in notas_por_aluno]
        indicadores = _indicadores_atuais(db, escola_id, aluno_ids, matific, elefante)
        resumos.append(_monta_resumo_turma(turma, aluno_ids, notas, indicadores))
    return {
        "escola": {"id": escola.id, "nome": escola.nome},
        "turmas": resumos,
    }


# ---------------------------------------------------------------------------
# Comparadores (PRD §73–§75)
# ---------------------------------------------------------------------------

def _lado_aluno(db: Session, escola_id: int, aluno_id: int) -> dict | None:
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        return None
    escola = db.get(Escola, escola_id)
    nota = db.execute(
        select(Nota).where(Nota.aluno_id == aluno_id,
                           Nota.ano_letivo == escola.ano_letivo_ativo)
    ).scalar_one_or_none()
    return {
        "tipo": "aluno",
        "id": aluno.id,
        "nome": aluno.nome,
        "indicadores": _indicadores_atuais(db, escola_id, [aluno_id]),
        "notas": {
            "matific": nota.nota_matific if nota else 0.0,
            "elefante": nota.nota_elefante if nota else 0.0,
            "geral": nota.nota_geral if nota else 0.0,
            "posicao": nota.posicao if nota else None,
        },
    }


def _lado_turma(db: Session, escola_id: int, turma_id: int) -> dict | None:
    resumo = resumo_turma(db, escola_id, turma_id)
    if resumo is None:
        return None
    return {
        "tipo": "turma",
        "id": resumo["turma"]["id"],
        "nome": resumo["turma"]["nome"],
        "total_alunos": resumo["total_alunos"],
        "indicadores": resumo["indicadores"],
        "notas": {
            "matific": resumo["media_matific"],
            "elefante": resumo["media_elefante"],
            "geral": resumo["media_geral"],
            "posicao": None,
        },
    }


def _lado_escola(db: Session, escola_id: int) -> dict | None:
    """A escola inteira como um lado do comparador: médias das notas de todos os
    alunos ativos + soma dos indicadores (mesma regra das turmas). O `escola_id`
    é o da escola A COMPARAR (pode ser outra, para ADM da rede)."""
    escola = db.get(Escola, escola_id)
    if escola is None:
        return None
    aluno_ids = list(db.execute(
        select(Aluno.id)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .where(Matricula.escola_id == escola_id,
               Matricula.ano_letivo == escola.ano_letivo_ativo,
               Aluno.status == "ativo")
    ).scalars())
    notas = db.execute(
        select(Nota).join(Aluno, Nota.aluno_id == Aluno.id)
        .where(Nota.escola_id == escola_id,
               Nota.ano_letivo == escola.ano_letivo_ativo,
               Aluno.status == "ativo")
    ).scalars().all()
    n = len(notas) or 1
    return {
        "tipo": "escola",
        "id": escola.id,
        "nome": escola.nome,
        "total_alunos": len(aluno_ids),
        "indicadores": _indicadores_atuais(db, escola_id, aluno_ids),
        "notas": {
            "matific": round(sum(x.nota_matific for x in notas) / n, 2),
            "elefante": round(sum(x.nota_elefante for x in notas) / n, 2),
            "geral": round(sum(x.nota_geral for x in notas) / n, 2),
            "posicao": None,
        },
    }


def comparar(db: Session, escola_id: int, tipo_a: str, id_a: int,
             tipo_b: str, id_b: int) -> dict | None:
    lados = []
    for tipo, identificador in ((tipo_a, id_a), (tipo_b, id_b)):
        if tipo == "aluno":
            lado = _lado_aluno(db, escola_id, identificador)
        elif tipo == "escola":
            lado = _lado_escola(db, identificador)  # id = escola a comparar
        else:
            lado = _lado_turma(db, escola_id, identificador)
        if lado is None:
            return None
        lados.append(lado)
    return {"a": lados[0], "b": lados[1]}
