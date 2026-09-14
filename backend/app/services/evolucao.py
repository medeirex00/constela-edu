"""Evolução e histórico (PRD §67–§78).

Toda a base vem dos snapshots imutáveis da Fase 1: a evolução é sempre a
comparação entre o último snapshot anterior ao período (linha de base) e o
snapshot mais recente. Nenhum dado novo é gravado aqui — apenas leitura.

O Ranking de Evolução reaproveita o próprio motor de cálculo aplicado aos
GANHOS do período: os mesmos pesos configuráveis e a mesma normalização 0–100,
com a régua resolvida DENTRO de cada dimensão (P90 dos ativos daquela coorte,
ou o máximo quando ela é pequena). Indicadores não cumulativos (pontuação
média) entram pela variação positiva — quem manteve não perde, quem cresceu
pontua.

ARQUITETURA 2: aqui, como no Ranking Geral, não existe ordem única entre
matérias diferentes. Cada dimensão tem a sua nota de crescimento, a sua régua e
a sua posição; quem não tem dado da plataforma sai da ordenação daquela
dimensão — sem virar zero e sem sumir da tela. Ver `ranking_evolucao`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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
from app.services import dificuldade_livro, scoring

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
        select(Leitura.data, Livro.nivel_codigo, Leitura.tempo_leitura_min, Livro.titulo)
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
    regra = dificuldade_livro.regra_da_escola(db, escola_id)   # fonte única
    baldes: dict[tuple, dict] = {}
    for data, codigo, tempo, titulo in db.execute(consulta.order_by(Leitura.data)).all():
        chave, rotulo = _bucket_leitura(_sem_fuso(data), granularidade)
        balde = baldes.setdefault(chave, {"rotulo": rotulo, "livros": 0,
                                          "pontos": 0.0, "tempo_min": 0})
        balde["livros"] += 1
        balde["pontos"] += regra.valor_livro(codigo, titulo, ano_escolar, turma_id)
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
# ARQUITETURA 2 — a Evolução também é POR DIMENSÃO (spec §7, Aprovação 7A).
#
# Antes, `nota_evolucao` era `nota_m·w_m + nota_e·w_e` com os pesos BRUTOS: o
# corte por DADO DO ALUNO (o C-01) nunca chegou aqui, e por isso o TETO DE 50
# sobrevivia nesta tela — a criança que cresceu só na leitura levava metade do
# ganho por uma dimensão que ela pode nem usar. Agora cada dimensão tem a sua
# nota, a sua régua e a sua ordem, e a composição sobrevive apenas como LEGADO
# (ver `nota_evolucao` em `ItemEvolucao`), já com o C-01 aplicado.

# Dimensão (vocabulário do produto) → plataforma (nome técnico do dado). Reusa
# a FONTE ÚNICA do motor em vez de repetir o mapa aqui.
DIMENSOES = scoring.DIMENSOES

# Desempate LOCAL de cada ranking de evolução (spec §2.2): só GANHOS daquela
# dimensão. O mesmo princípio de `scoring.CRITERIOS_DESEMPATE_DIMENSAO`, aqui
# sobre o crescimento do período — a medalha de "quem mais cresceu na leitura"
# não pode ser decidida por estrelas de matemática.
CRITERIOS_DESEMPATE_EVOLUCAO: dict[str, tuple[str, ...]] = {
    "leitura": ("pontos_dificuldade", "livros", "tempo_leitura_min"),
    "matematica": ("estrelas", "atividades"),
}


@dataclass
class ItemEvolucao:
    aluno_id: int
    nome: str
    turma: str
    ano_escolar: str
    # LEGADO — a ordem ÚNICA de crescimento, composta entre dimensões.
    # Continua sendo calculada porque o telão público, o mural, o /insights, a
    # sincronização mobile, o assistente e três telas web ainda consomem UM
    # número (spec §7.3). O que MORREU foi a regra antiga: os pesos brutos deram
    # lugar a `scoring.pesos_geral_do_aluno` sobre as dimensões AFERIDAS na
    # janela, isto é, o C-01 finalmente chegou à Evolução e o teto de 50 acabou.
    # Critério de saída (o mesmo de `Nota.nota_geral`): quando telão, mural,
    # insights, mobile e web lerem `notas[dimensao]`, este campo para de existir.
    nota_evolucao: float
    ganhos: dict
    posicao: int = 0
    # --- Por DIMENSÃO (a leitura OFICIAL) ------------------------------------
    # Chaves: "leitura" / "matematica".
    # `notas[d]` é `None` — nunca 0,0 — quando o aluno NÃO é aferido em `d`:
    # ausência é ESTADO, e a tela mostra "—". O 0,0 fica reservado a quem tem
    # dado da plataforma e não cresceu no período (zero legítimo).
    notas: dict = field(default_factory=dict)
    aferido: dict = field(default_factory=dict)
    posicao_dimensao: dict = field(default_factory=dict)
    n_aferidos: dict = field(default_factory=dict)
    contratadas: tuple[str, ...] = ()


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
        select(Leitura.aluno_id, Livro.nivel_codigo, Leitura.tempo_leitura_min, Livro.titulo)
        .join(Livro, Leitura.livro_id == Livro.id)
        .where(Leitura.escola_id == escola_id)
    )
    if inicio is not None:
        consulta = consulta.where(Leitura.data >= inicio)
    if fim is not None:
        consulta = consulta.where(Leitura.data <= fim)

    dados: dict[int, dict] = {}
    for aluno_id, codigo, tempo, titulo in db.execute(consulta).all():
        item = dados.setdefault(aluno_id, {"livros": 0, "tempo_min": 0, "por_nivel": {},
                                           "itens": []})
        item["livros"] += 1
        item["tempo_min"] += tempo or 0
        chave = (codigo or "").upper()
        if chave:
            item["por_nivel"][chave] = item["por_nivel"].get(chave, 0) + 1
            item["itens"].append((titulo or "", chave))   # p/ valor por livro
    return alunos_com_leituras, dados


def series_e_dificuldade(
    db: Session, escola_id: int,
) -> tuple[dict[int, list], dict[int, list], object]:
    """Pré-carrega, UMA vez, as varreduras CARAS e independentes de janela —
    séries de Matific/Elefante + mapa de dificuldade. Um chamador que faça
    VÁRIAS leituras derivadas no mesmo request (ex.: /sincronizacao mobile:
    alertas + mural + ranking de evolução) injeta o resultado nessas funções em
    vez de cada uma reler as tabelas de snapshot (mesma estratégia do mural/M4)."""
    serie_m = _series_por_aluno(db, escola_id, SnapshotMatific)
    serie_e = _series_por_aluno(db, escola_id, SnapshotElefante)
    # `mapa_dif` carrega a REGRA de dificuldade da escola (fonte única).
    mapa_dif = dificuldade_livro.regra_da_escola(db, escola_id)
    return serie_m, serie_e, mapa_dif


def _referencias_por_dimensao(
    listas_por_dimensao: dict[str, dict[str, list[float]]],
) -> tuple[dict[str, float], dict[str, float]]:
    """Régua de normalização resolvida DENTRO de cada dimensão.

    `scoring.referencias_robustas` decide "modo robusto (P90 + saturação) ×
    escala simples por máximo" pelo TAMANHO DA AMOSTRA que recebe — e recebia,
    numa chamada só, os indicadores das DUAS dimensões. Como o tamanho era
    ``max(len(...))`` sobre todas as listas, a coorte do Matific ligava a régua
    dos indicadores de LEITURA (e vice-versa): importar matemática mexia na nota
    de evolução em leitura de quem nunca abriu o Matific. É exatamente o canal
    que o motor já fechou em `scoring._referencias` (ver
    `scoring.DIMENSAO_DO_INDICADOR`), e que sobrevivia aqui.

    Correção: UMA chamada por dimensão, cada uma recebendo só os indicadores
    daquela dimensão e só os valores dos alunos AFERIDOS nela. Assim a amostra
    que decide a régua de Leitura é a coorte do Elefante, e a de Matemática, a
    do Matific. Os dicionários voltam fundidos porque `calcular_elefante` e
    `calcular_matific` leem cada um as suas chaves (`max_livros`, `max_estrelas`
    …) — as chaves de dimensões diferentes nunca colidem.
    """
    refs: dict[str, float] = {}
    k_vol: dict[str, float] = {}
    for listas in listas_por_dimensao.values():
        refs_d, k_d = scoring.referencias_robustas(listas)
        refs.update(refs_d)
        k_vol.update(k_d)
    return refs, k_vol


def ranking_evolucao(db: Session, escola_id: int, inicio: datetime | None = None,
                     fim: datetime | None = None, turma_id: int | None = None,
                     ano_escolar: str | None = None,
                     dias: int | None = None,
                     turma_ids: list[int] | None = None,
                     turno: str | None = None,
                     serie_m: dict[int, list] | None = None,
                     serie_e: dict[int, list] | None = None,
                     mapa_dif: dict[tuple[str, str], float] | None = None,
                     alunos_com_leituras: set[int] | None = None,
                     base_no_periodo: bool = False,
                     ) -> list[ItemEvolucao]:
    """Ranking de quem mais cresceu DENTRO da janela [inicio, fim] (o ganho é
    medido pela `_janela`, que ignora o acumulado anterior ao período).

    POR DIMENSÃO (Arquitetura 2, spec §7 / Aprovação 7A). Cada item traz:

      * ``notas["leitura"]`` / ``notas["matematica"]`` — o crescimento medido
        DENTRO da dimensão, e ``None`` quando o aluno não é aferido nela;
      * ``aferido[d]`` — a mesma noção do C-01, aplicada à janela: existe
        snapshot da PLATAFORMA de ``d`` até ``fim`` (para leitura, também conta
        leitura individual datada, que é a fonte fina do próprio Elefante) E o
        módulo é contratado. Ausência é ESTADO, nunca zero;
      * ``posicao_dimensao[d]`` / ``n_aferidos[d]`` — a ordem local de cada
        dimensão e o denominador dela.

    Sub-decisão da spec §7.2 resolvida como **(a) TER SNAPSHOT**, nunca (b) ter
    crescido: quem usa a plataforma e não cresceu entra com 0,00 e fica em
    último (zero LEGÍTIMO, a mesma filosofia do Ranking Geral); quem não tem
    dado sai da lista daquela dimensão. (b) premiaria estagnar — bastava não
    crescer para sumir do denominador — e apagaria a diferença entre "não usa" e
    "usou e não avançou", que é a informação que o professor precisa.

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
    # Filtro de TURNO (eixo ortogonal ao período): `None` = não filtra (todos);
    # `""` = turmas SEM turno cadastrado ("Sem turno"); senão o turno exato. Os
    # valores vêm de Turma.turno (do banco), nunca hardcoded.
    if turno is not None:
        consulta = consulta.where(
            Turma.turno.is_(None) if turno == "" else Turma.turno == turno)
    if turma_ids is not None:  # professor: só as turmas designadas a ele
        consulta = consulta.where(Turma.id.in_(turma_ids))
    consulta = consulta.options(selectinload(Matricula.aluno))  # evita N+1
    matriculas = db.execute(consulta).all()

    # Varreduras independentes da janela: reusa as injetadas (mural) ou carrega.
    if serie_m is None:
        serie_m = _series_por_aluno(db, escola_id, SnapshotMatific)
    if serie_e is None:
        serie_e = _series_por_aluno(db, escola_id, SnapshotElefante)
    if mapa_dif is None:   # a REGRA de dificuldade (fonte única), injetável
        mapa_dif = dificuldade_livro.regra_da_escola(db, escola_id)
    # Leituras com data REAL: para quem tem relatório individual importado, o
    # ganho de leitura do período vem do que foi DE FATO lido no intervalo.
    com_leituras, leituras_periodo = _leituras_no_periodo(
        db, escola_id, inicio, fim, alunos_com_leituras)

    # CONTRATO (1º degrau da cascata contrato → dado): dimensão que a rede não
    # assinou não tem nota, não tem ranking e ninguém é "não aferido" nela.
    contratadas = tuple(scoring.dimensoes_contratadas(db, escola))

    # Ganhos por aluno no período (snapshots sintéticos alimentam o motor)
    ganhos_m: dict[int, SimpleNamespace] = {}
    ganhos_e: dict[int, SimpleNamespace] = {}
    pontos_dif: dict[int, float] = {}
    # AFERIDO na janela, por dimensão — sub-decisão (a) da spec §7.2: existe
    # dado DA PLATAFORMA daquela dimensão até `fim`. Nunca "cresceu > 0".
    aferido: dict[int, dict[str, bool]] = {}
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
        itens_periodo = None
        if aluno_id in com_leituras:
            # Fonte exata: as leituras individuais datadas dentro do período.
            reais = leituras_periodo.get(aluno_id, {"livros": 0, "tempo_min": 0,
                                                    "por_nivel": {}, "itens": []})
            livros = float(reais["livros"])
            tempo = float(reais["tempo_min"])
            niveis_ganho = reais["por_nivel"]
            itens_periodo = reais.get("itens")     # (título, nível) de cada livro
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
        # Fonte única de dificuldade: livro itemizado vale o seu valor; delta de
        # snapshot vale o típico do nível.
        pontos_dif[aluno_id] = mapa_dif.pontos_aluno(
            niveis_ganho, turma.ano_escolar, turma_id=turma.id, leituras=itens_periodo)
        # MATEMÁTICA é aferida por snapshot do Matific até `fim` (`atual_m`).
        # LEITURA, por snapshot do Elefante OU por leitura individual datada —
        # as duas são dado do MESMO produto (o relatório individual é a fonte
        # fina que este ranking já prefere, logo acima). Nenhum dado de uma
        # plataforma marca a dimensão da outra: a garantia estrutural vale aqui
        # tanto quanto no motor.
        aferido[aluno_id] = {
            "matematica": ("matematica" in contratadas) and atual_m is not None,
            "leitura": ("leitura" in contratadas)
            and (atual_e is not None or aluno_id in com_leituras),
        }

    # Referências JUSTAS sobre os ganhos (mesma régua do Geral): P90 dos ativos
    # + saturação de volume (k=mediana). Um único aluno-gigante deixa de ser a
    # régua de todos — o topo fica disputado; quem mais cresceu segue na frente.
    # Coorte pequena recai no máximo (comportamento antigo), via a própria
    # helper — e a coorte é a DA DIMENSÃO (só os aferidos nela), não a escola
    # inteira: sem isso, matricular alunos sem plataforma nenhuma já mudava a
    # régua, e a amostra de uma dimensão decidia a régua da outra
    # (`_referencias_por_dimensao`).
    aferidos_de = {
        d: [aid for aid in ganhos_m if aferido[aid][d]] for d in DIMENSOES
    }
    refs, k_vol = _referencias_por_dimensao({
        "matematica": {
            "atividades": [ganhos_m[a].atividades for a in aferidos_de["matematica"]],
            "media": [ganhos_m[a].pontuacao_media for a in aferidos_de["matematica"]],
            "estrelas": [ganhos_m[a].estrelas for a in aferidos_de["matematica"]],
        },
        "leitura": {
            "livros": [ganhos_e[a].livros_unicos for a in aferidos_de["leitura"]],
            "pontos_dificuldade": [pontos_dif[a] for a in aferidos_de["leitura"]],
            "tentativas": [ganhos_e[a].questoes_tentativas for a in aferidos_de["leitura"]],
            "acertos": [ganhos_e[a].questoes_acertos for a in aferidos_de["leitura"]],
            "tempo": [ganhos_e[a].tempo_leitura_min for a in aferidos_de["leitura"]],
        },
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
        marcas = aferido[aluno_id]
        # LEGADO — a nota única. O que mudou: os pesos deixam de ser BRUTOS.
        # `pesos_geral_do_aluno` renormaliza sobre as dimensões em que ESTE aluno
        # tem dado na janela (o C-01, que nunca havia chegado à Evolução). Quem
        # cresceu só na leitura sai de 0,5·nota_e para nota_e — o teto de 50
        # desta tela acaba aqui. Quem tem as duas continua 50/50, bit a bit.
        pesos_aluno = scoring.pesos_geral_do_aluno(
            p_geral, {DIMENSOES[d] for d, tem in marcas.items() if tem})
        nota = round(nota_m * pesos_aluno.get("matific", 0)
                     + nota_e * pesos_aluno.get("elefante", 0), 2)
        ganhos = {
            "atividades": ganhos_m[aluno_id].atividades,
            "estrelas": ganhos_m[aluno_id].estrelas,
            "livros": ganhos_e[aluno_id].livros_unicos,
            "tempo_leitura_min": ganhos_e[aluno_id].tempo_leitura_min,
            "acertos": ganhos_e[aluno_id].questoes_acertos,
            # Qualidade da leitura no período (nível dos livros lidos): é o
            # primeiro desempate da dimensão Leitura, então precisa viajar junto.
            "pontos_dificuldade": round(pontos_dif[aluno_id], 2),
        }
        itens.append(ItemEvolucao(
            aluno_id=aluno_id, nome=matricula.aluno.nome, turma=turma.nome,
            ano_escolar=turma.ano_escolar, nota_evolucao=nota, ganhos=ganhos,
            # Nota `None` quando não aferido — a tela mostra "—". 0,00 fica
            # reservado a quem tem a plataforma e não cresceu (zero legítimo).
            notas={"leitura": nota_e if marcas["leitura"] else None,
                   "matematica": nota_m if marcas["matematica"] else None},
            aferido=dict(marcas), contratadas=contratadas,
        ))

    _ordenar_evolucao_por_dimensao(itens, contratadas)

    # LEGADO — a ordem ÚNICA de crescimento (a que o telão, o mural e o
    # /insights ainda consomem). `aluno_id` fecha a chave para que dois
    # homônimos empatados em tudo não troquem de posição entre execuções.
    itens.sort(key=lambda item: (-item.nota_evolucao, item.nome.casefold(),
                                 item.aluno_id))
    for posicao, item in enumerate(itens, start=1):
        item.posicao = posicao
    return itens


def _ordenar_evolucao_por_dimensao(itens: list[ItemEvolucao],
                                   contratadas: tuple[str, ...]) -> None:
    """Carimba `posicao_dimensao` e `n_aferidos` de cada dimensão contratada.

    Só entra na ordem de ``d`` quem é AFERIDO em ``d``; o desempate é LOCAL
    (`CRITERIOS_DESEMPATE_EVOLUCAO`) e termina em nome + `aluno_id`, para a
    posição ser estável entre execuções. `n_aferidos` viaja junto porque é o
    DENOMINADOR da posição: sem ele, um "3º em Leitura" e um "3º em Matemática"
    parecem comparáveis, e não são.
    """
    for dimensao in DIMENSOES:
        if dimensao not in contratadas:
            for item in itens:
                item.posicao_dimensao[dimensao] = None
                item.n_aferidos[dimensao] = 0
            continue
        criterios = CRITERIOS_DESEMPATE_EVOLUCAO[dimensao]
        elegiveis = [item for item in itens if item.aferido.get(dimensao)]
        elegiveis.sort(key=lambda item: (
            -(item.notas.get(dimensao) or 0.0),
            *[-float(item.ganhos.get(c, 0) or 0) for c in criterios],
            item.nome.casefold(), item.aluno_id,
        ))
        for posicao, item in enumerate(elegiveis, start=1):
            item.posicao_dimensao[dimensao] = posicao
        for item in itens:
            item.posicao_dimensao.setdefault(dimensao, None)
            item.n_aferidos[dimensao] = len(elegiveis)


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


def _media_da_dimensao(notas: list[Nota], campo: str, aferidos: set[int],
                       casas: int = 2) -> tuple[int, float]:
    """(n, média) de uma dimensão — SOMENTE sobre os alunos aferidos nela.

    O corte é a EXISTÊNCIA do snapshot da plataforma, **nunca** ``nota > 0``:

      * sem snapshot    → ausência: fica FORA (nunca houve o que medir);
      * snapshot zerado → zero LEGÍTIMO: entra e pesa ("usa e não produziu").

    Trocar o corte por ``nota > 0`` juntaria os dois estados e maquiaria a
    turma — é o erro que `rede.py` proíbe com todas as letras.

    ``casas`` existe porque o arredondamento faz parte da régua: números de
    ESCOLA saem com 1 casa em todo o produto (cartão da rede, dashboard), e
    "o mesmo número" só é o mesmo se for arredondado igual.
    """
    valores = [float(getattr(n, campo)) for n in notas if n.aluno_id in aferidos]
    if not valores:
        return 0, 0.0
    return len(valores), round(sum(valores) / len(valores), casas)


def _monta_resumo_turma(turma: Turma, aluno_ids: list[int], notas: list[Nota],
                        indicadores: dict, aferidos: dict[str, set[int]],
                        contratadas: list[str]) -> dict:
    """Monta o dict de resumo de UMA turma a partir de dados já carregados
    (matrículas + notas + quem tem snapshot de cada plataforma). Sem consulta ao
    banco — o chamador decide se carrega por turma (`resumo_turma`) ou em lote
    (`resumo_escola`).

    DESEMPENHO POR DIMENSÃO (Arquitetura 2, spec §4.2). Antes, as três médias
    eram ``sum(...) / len(notas)`` sobre TODAS as linhas de nota da turma — os
    zeros de quem não tem snapshot entravam na conta. Uma turma boa com metade
    dos alunos ainda sem Matific parecia pior do que uma turma fraca com todos
    cadastrados: o número media desempenho × COBERTURA, duas coisas diferentes.
    É o mesmo defeito que `rede._medias_por_plataforma` já corrigira no nível da
    ESCOLA e que nunca havia descido para a turma.

    Agora cada dimensão tem a sua média (só sobre os aferidos dela) e o seu
    denominador `n_*`, e a COBERTURA aparece ao lado, com nome próprio:
    `adocao_*` por dimensão, `adocao` (média das contratadas) e `alcance` (tem
    dado de ALGUMA contratada). Desempenho e cobertura nunca se misturam num
    número só.

    `media_geral` sobrevive como a média das DIMENSÕES COM DADO — a mesma régua
    do cartão da escola no painel da rede e do dashboard da escola. Não é
    composição nova: é o número que as telas de turma já consomem
    (`TurmaDetalhe`, a barra de comparação de `VisaoEscola`), agora calculado
    com a régua certa. Virar "uma barra por dimensão" na tela é decisão de
    produto (§ Aprovação 5), não conversão mecânica.
    """
    n_leitura, media_elefante = _media_da_dimensao(
        notas, "nota_elefante", aferidos["leitura"]) if "leitura" in contratadas else (0, 0.0)
    n_matematica, media_matific = _media_da_dimensao(
        notas, "nota_matific", aferidos["matematica"]) if "matematica" in contratadas else (0, 0.0)
    disponiveis = [m for m, n in ((media_elefante, n_leitura),
                                  (media_matific, n_matematica)) if n]
    media_geral = round(sum(disponiveis) / len(disponiveis), 2) if disponiveis else 0.0

    total = len(aluno_ids)
    com_algum = len({a for a in aluno_ids
                     for d in contratadas if a in aferidos[d]})
    n_por_dimensao = {"leitura": n_leitura, "matematica": n_matematica}
    # COBERTURA sai da COORTE (matriculados ∩ tem snapshot da plataforma) — a
    # mesma população de `alcance` e de `rede.adocao_elefante`, e nunca a
    # população do CACHE de notas. `n_leitura` conta quem tem snapshot **e** já
    # tem linha em `notas`: ele é o denominador da MÉDIA (só se pode promediar
    # nota que existe), mas usá-lo como numerador da ADOÇÃO faz a cobertura
    # depender de o motor já ter rodado. Numa escola importada e ainda não
    # recalculada a turma reportava, na mesma resposta, `alcance = 100 %` com
    # `adocao_leitura = 0 %` e `nao_aferidos = 0` — três números que não podem
    # ser verdade juntos. Depois do recálculo os dois conjuntos coincidem, então
    # em operação normal nenhum número se move.
    cobertura = {d: sum(1 for a in aluno_ids if a in aferidos[d])
                 for d in contratadas}
    adocoes = {d: round(cobertura[d] / total * 100, 1) if total else 0.0
               for d in contratadas}
    return {
        "turma": {"id": turma.id, "nome": turma.nome, "ano_escolar": turma.ano_escolar},
        "total_alunos": total,
        # Derivada das dimensões com dado (não é média de `nota_geral`).
        "media_geral": media_geral,
        # Chaves históricas (o web lê estas) — agora só sobre os aferidos.
        "media_matific": media_matific,
        "media_elefante": media_elefante,
        # Vocabulário da Arquitetura 2, com o denominador ao lado de cada média.
        "media_leitura": media_elefante,
        "n_leitura": n_leitura,
        "media_matematica": media_matific,
        "n_matematica": n_matematica,
        "contratadas": list(contratadas),
        "dimensoes_com_dados": [d for d in contratadas if n_por_dimensao[d]],
        # COBERTURA — ao lado do desempenho, jamais somada a ele.
        "adocao_leitura": adocoes.get("leitura", 0.0),
        "adocao_matematica": adocoes.get("matematica", 0.0),
        "adocao": round(sum(adocoes.values()) / len(adocoes), 1) if adocoes else 0.0,
        "alcance": round(com_algum / total * 100, 1) if total else 0.0,
        "nao_aferidos": total - com_algum,
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
    # Uma carga só dos snapshots, usada pelos indicadores E pelo corte de
    # aferido — o discriminante é a EXISTÊNCIA do snapshot (a definição), não a
    # coluna `Nota.aferido_*` (o cache carimbado pelo recálculo). Enquanto uma
    # escola não é recalculada, o número certo é o do dado.
    if matific is None:
        matific = scoring._snapshots_atuais(db, escola_id, SnapshotMatific)
    if elefante is None:
        elefante = scoring._snapshots_atuais(db, escola_id, SnapshotElefante)
    indicadores = _indicadores_atuais(db, escola_id, aluno_ids, matific, elefante)
    return _monta_resumo_turma(
        turma, aluno_ids, notas, indicadores,
        {"leitura": set(elefante), "matematica": set(matific)},
        scoring.dimensoes_contratadas(db, escola))


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

    aferidos = {"leitura": set(elefante), "matematica": set(matific)}
    contratadas = scoring.dimensoes_contratadas(db, escola)
    resumos = []
    for turma in turmas:
        aluno_ids = alunos_por_turma.get(turma.id, [])
        notas = [notas_por_aluno[a] for a in aluno_ids if a in notas_por_aluno]
        indicadores = _indicadores_atuais(db, escola_id, aluno_ids, matific, elefante)
        resumos.append(_monta_resumo_turma(turma, aluno_ids, notas, indicadores,
                                           aferidos, contratadas))
    return {
        "escola": {"id": escola.id, "nome": escola.nome},
        "turmas": resumos,
    }


# ---------------------------------------------------------------------------
# Comparadores (PRD §73–§75)
# ---------------------------------------------------------------------------

def _bloco_dimensoes(contratadas: list[str], aferido: dict[str, bool],
                     notas: dict[str, float | None],
                     posicoes: dict[str, int | None] | None = None,
                     n_aferidos: dict[str, int] | None = None) -> dict:
    """Bloco `dimensoes` comum aos três lados do comparador.

    Mesmo formato de `scoring._ordenar_por_dimensao`: nota `None` (e não 0,0)
    quando não há dado, `contratada` explícita, e o denominador ao lado. Sem
    isto, comparar um aluno com uma turma poria lado a lado um zero de ausência
    e uma média já cortada por aferido — dois números com a mesma cara e
    significados diferentes.
    """
    return {
        dimensao: {
            "plataforma": DIMENSOES[dimensao],
            "contratada": dimensao in contratadas,
            "aferido": bool(aferido.get(dimensao)),
            "nota": notas.get(dimensao) if aferido.get(dimensao) else None,
            "posicao": (posicoes or {}).get(dimensao),
            "n_aferidos": (n_aferidos or {}).get(dimensao),
        }
        for dimensao in DIMENSOES
    }


def _lado_aluno(db: Session, escola_id: int, aluno_id: int) -> dict | None:
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        return None
    escola = db.get(Escola, escola_id)
    nota = db.execute(
        select(Nota).where(Nota.aluno_id == aluno_id,
                           Nota.ano_letivo == escola.ano_letivo_ativo)
    ).scalar_one_or_none()
    matific = scoring._snapshots_atuais(db, escola_id, SnapshotMatific)
    elefante = scoring._snapshots_atuais(db, escola_id, SnapshotElefante)
    aferido = {"leitura": aluno_id in elefante, "matematica": aluno_id in matific}
    # DENOMINADOR da posição do aluno, na mesma fonte que o perfil dele usa
    # (`dimensoes.bloco` → `detalhes.dimensoes[d].n_aferidos`, carimbado pelo
    # motor). Sem ele o comparador exibia "3º" pelado, e "3º" numa matéria ao
    # lado de "3º" na outra parece comparável — é exatamente o que o
    # denominador existe para impedir (spec §2). Zero consulta a mais: o número
    # já viaja dentro da linha de `notas` que acabou de ser lida. Os lados
    # TURMA e ESCOLA já mandavam o deles.
    detalhes_dim = ((nota.detalhes or {}).get("dimensoes") or {}) if nota else {}
    n_aferidos = {d: (detalhes_dim.get(d) or {}).get("n_aferidos")
                  for d in DIMENSOES}
    return {
        "tipo": "aluno",
        "id": aluno.id,
        "nome": aluno.nome,
        "indicadores": _indicadores_atuais(db, escola_id, [aluno_id], matific, elefante),
        # Estado por dimensão: sem dado é `null`, não 0,0 — é o que impede a
        # tela de mostrar "0,0 em Matemática" para quem nunca abriu o Matific.
        "dimensoes": _bloco_dimensoes(
            scoring.dimensoes_contratadas(db, escola), aferido,
            {"leitura": nota.nota_elefante if nota else None,
             "matematica": nota.nota_matific if nota else None},
            {"leitura": nota.posicao_leitura if nota else None,
             "matematica": nota.posicao_matematica if nota else None},
            n_aferidos=n_aferidos),
        # LEGADO: as chaves antigas, preservadas bit a bit para os clientes que
        # ainda as leem. `geral` e `posicao` são a ordem única (§ Aprovação 2).
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
        "dimensoes": _bloco_dimensoes(
            resumo["contratadas"],
            {d: bool(resumo["n_" + d]) for d in DIMENSOES},
            {"leitura": resumo["media_leitura"],
             "matematica": resumo["media_matematica"]},
            n_aferidos={"leitura": resumo["n_leitura"],
                        "matematica": resumo["n_matematica"]}),
        "adocao": resumo["adocao"],
        "alcance": resumo["alcance"],
        "notas": {
            "matific": resumo["media_matific"],
            "elefante": resumo["media_elefante"],
            "geral": resumo["media_geral"],
            "posicao": None,
        },
    }


def _lado_escola(db: Session, escola_id: int) -> dict | None:
    """A escola inteira como um lado do comparador: desempenho POR DIMENSÃO de
    todos os alunos ativos + soma dos indicadores (mesma regra das turmas). O
    `escola_id` é o da escola A COMPARAR (pode ser outra, para ADM da rede).

    Antes, as três médias eram ``sum(...) / len(notas)`` sobre TODAS as notas —
    os zeros de quem não tem snapshot entravam. A MESMA escola exibia um número
    aqui, outro no dashboard dela e outro no cartão do painel da rede; a
    divergência era defeito, não opção. Agora os três usam a régua única: cada
    dimensão só sobre quem tem dado dela, e a "geral" é a média das dimensões
    COM DADO — nunca a média das notas gerais dos alunos.

    O CONJUNTO é o dos MATRICULADOS no ano ativo (`aluno_ids`) — o mesmo que
    `total_alunos`, `alcance` e o motor usam. `notas` não é apagada quando o
    aluno perde a matrícula, então a nota órfã de quem foi desvinculado entrava
    nas médias e no denominador de cada dimensão, e o lado "escola" do
    comparador divergia do dashboard da mesma escola. Mesma régua de
    `resumo_turma`/`resumo_escola`, que já filtram por matrícula.
    """
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
               Aluno.status == "ativo",
               Nota.aluno_id.in_(aluno_ids or [0]))
    ).scalars().all()
    # Uma carga só: os indicadores e o corte de aferido saem dos MESMOS
    # snapshots (a existência do snapshot é a definição de aferido).
    matific = scoring._snapshots_atuais(db, escola_id, SnapshotMatific)
    elefante = scoring._snapshots_atuais(db, escola_id, SnapshotElefante)
    contratadas = scoring.dimensoes_contratadas(db, escola)
    # 1 casa: é a régua de ESCOLA do produto inteiro (`rede._kpis_da_rede` e
    # `rankings._desempenho_da_escola`). Com 2 casas aqui, a mesma escola voltaria
    # a exibir números que não batem — que é justamente o defeito corrigido.
    n_leitura, media_elefante = (
        _media_da_dimensao(notas, "nota_elefante", set(elefante), casas=1)
        if "leitura" in contratadas else (0, 0.0))
    n_matematica, media_matific = (
        _media_da_dimensao(notas, "nota_matific", set(matific), casas=1)
        if "matematica" in contratadas else (0, 0.0))
    disponiveis = [m for m, q in ((media_elefante, n_leitura),
                                  (media_matific, n_matematica)) if q]
    media_geral = round(sum(disponiveis) / len(disponiveis), 1) if disponiveis else 0.0
    aferidos = {"leitura": set(elefante), "matematica": set(matific)}
    com_algum = len({a for a in aluno_ids
                     for d in contratadas if a in aferidos[d]})
    total = len(aluno_ids)
    return {
        "tipo": "escola",
        "id": escola.id,
        "nome": escola.nome,
        "total_alunos": total,
        "indicadores": _indicadores_atuais(db, escola_id, aluno_ids, matific, elefante),
        "dimensoes": _bloco_dimensoes(
            contratadas,
            {"leitura": bool(n_leitura), "matematica": bool(n_matematica)},
            {"leitura": media_elefante, "matematica": media_matific},
            n_aferidos={"leitura": n_leitura, "matematica": n_matematica}),
        "alcance": round(com_algum / total * 100, 1) if total else 0.0,
        "notas": {
            "matific": media_matific,
            "elefante": media_elefante,
            "geral": media_geral,
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
