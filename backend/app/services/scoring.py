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
from datetime import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import bloquear_escola_para_recalculo
from app.models import (
    Aluno,
    Configuracao,
    DificuldadeTurma,
    Escola,
    Leitura,
    Matricula,
    NivelDificuldade,
    Nota,
    ReferenciaNormalizacao,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)

# Pontos extras "por livro lido NA ESCOLA": a janela de horário é definida pelo
# TURNO da turma (horário de Brasília, como já vem no relatório individual do
# Elefante). Manhã 07:00–13:00 e Tarde 13:00–18:00, só de segunda a sexta. O
# limite das 13h vai para a TARDE. Integral/Noite não têm janela (sem bônus).
_JANELAS_TURNO: dict[str, tuple[time, time]] = {
    "manha": (time(7, 0), time(13, 0)),
    "tarde": (time(13, 0), time(18, 0)),
}


def _bonus_leitura_na_escola(
    db: Session, escola_id: int, turno_por_aluno: dict[int, str | None],
    pontos_por_livro: float,
) -> dict[int, float]:
    """Pontos extras de cada aluno = `pontos_por_livro` × (livros lidos DENTRO da
    janela do turno da turma dele, seg–sex). Usa a data+hora real de cada leitura
    (Leitura.data, do relatório individual do Elefante). Livro sem hora conhecida
    ou fora da janela não gera extra."""
    alvos = {aid: _JANELAS_TURNO[t] for aid, t in turno_por_aluno.items()
             if t in _JANELAS_TURNO}
    if not alvos or pontos_por_livro <= 0:
        return {}
    bonus: dict[int, float] = {}
    for aluno_id, data in db.execute(
        select(Leitura.aluno_id, Leitura.data)
        .where(Leitura.escola_id == escola_id, Leitura.aluno_id.in_(alvos.keys()))
    ):
        if data is None:
            continue
        quando = data.replace(tzinfo=None) if data.tzinfo is not None else data
        if quando.weekday() >= 5:                       # só segunda a sexta
            continue
        ini, fim = alvos[aluno_id]
        if ini <= quando.time() < fim:                  # dentro da janela do turno
            bonus[aluno_id] = bonus.get(aluno_id, 0.0) + pontos_por_livro
    return {aid: round(b, 2) for aid, b in bonus.items()}

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
# Normalização robusta (auto): saturação de VOLUME + referência por percentil
# ---------------------------------------------------------------------------
# Indicadores de VOLUME (contagens acumuladas) recebem RETORNOS DECRESCENTES:
# dobrar a quantidade não dobra a nota. Indicadores de QUALIDADE (média de
# desempenho, dificuldade, acertos) permanecem LINEARES. A referência do modo
# auto passa a ser o P90 (robusto) em vez do MÁXIMO, para que um único outlier
# não defina a régua e "esmague" os demais. Corrige a distorção de o ranking
# medir volume acumulado sem punir excesso — sem regra específica por aluno.
INDICADORES_VOLUME = {"atividades", "estrelas", "livros", "tempo", "tentativas"}
# Estatística robusta (P90/mediana) só é confiável com amostra suficiente;
# abaixo disso a escola cai na escala simples por máximo (comportamento antigo).
MIN_ALUNOS_ROBUSTO = 8


def normalizar_saturado(valor: float, referencia: float, k: float) -> float:
    """Normalização CÔNCAVA (retornos decrescentes) reescalada p/ referência→100.

    Curva de saturação hiperbólica ``x/(x+k)``: cresce rápido no começo e satura
    depois. ``k`` é a meia-saturação (mediana da escola) — no valor ``k`` a curva
    entrega metade do teto. ``k<=0`` ou referência inválida recai no linear.
    Preserva ordem (monótona) e teto 100; comprime distâncias entre volumes altos.
    """
    if not referencia or referencia <= 0:
        return 0.0
    if not k or k <= 0:
        return normalizar(valor, referencia)
    f_ref = referencia / (referencia + k)
    if f_ref <= 0:
        return 0.0
    return round(min(100.0, (float(valor) / (float(valor) + k)) / f_ref * 100.0), 2)


def _percentil(valores: list[float], p: float) -> float:
    """Percentil ``p`` (0–1) por interpolação linear. Lista vazia → 0."""
    v = sorted(float(x) for x in valores)
    if not v:
        return 0.0
    if len(v) == 1:
        return v[0]
    pos = (len(v) - 1) * p
    baixo = int(pos)
    frac = pos - baixo
    if baixo + 1 < len(v):
        return v[baixo] + (v[baixo + 1] - v[baixo]) * frac
    return v[-1]


def referencias_robustas(
    listas: dict[str, list[float]],
) -> tuple[dict[str, float], dict[str, float]]:
    """Régua justa (P90 + k=mediana) a partir de listas de valores por indicador.

    Mesma regra do modo auto do Ranking Geral, em forma PURA e reutilizável —
    o Ranking de EVOLUÇÃO usa esta função sobre os GANHOS do período, para o
    topo ficar disputado lá também (um único gigante não vira a régua de todos).
    Amostra pequena (< ``MIN_ALUNOS_ROBUSTO``) recai no máximo, sem saturação.
    Retorna ``(referencias, k_por_indicador)``.
    """
    n_alunos = max((len(v) for v in listas.values()), default=0)
    usar_robusto = n_alunos >= MIN_ALUNOS_ROBUSTO
    refs: dict[str, float] = {}
    k_vol: dict[str, float] = {}
    for indicador, valores in listas.items():
        chave = "max_" + indicador
        ativos = [x for x in valores if x and x > 0]
        if usar_robusto and len(ativos) >= 2:
            refs[chave] = _percentil(ativos, 0.90)
            if indicador in INDICADORES_VOLUME:
                k_vol[indicador] = _percentil(ativos, 0.50)
        else:
            refs[chave] = max(valores, default=0)
    return refs, k_vol


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


def _pesos_dos_modulos_contratados(db: Session, escola_id: int,
                                   valores: dict) -> dict:
    """Mantém em ``pesos.geral`` só as plataformas dos módulos CONTRATADOS.

    Sem isto, uma rede que assinou apenas a Leitura teria ``nota_geral =
    0,5·elefante + 0,5·0`` — metade da nota, por um produto que ela nem contratou
    (o mesmo "teto de 50" que corrigimos nas médias da escola, agora no ALUNO).
    Como ``obter_pesos`` divide pela soma logo abaixo, remover a chave já
    REDISTRIBUI o peso: só Leitura ⇒ {elefante: 1,0}. Com os dois módulos nada
    muda (50/50), então o comportamento atual é preservado bit a bit.

    Só age em ``pesos.geral`` (a combinação ENTRE plataformas). Os pesos DENTRO
    de cada plataforma (livros/dificuldade/questões, atividades/média/estrelas)
    não têm relação com contratação e ficam intocados."""
    from app.services import modulos as svc_modulos

    escola = db.get(Escola, escola_id)
    contratados = svc_modulos.modulos_da_escola(db, escola)
    permitidas = {p for chave in contratados
                  for p in svc_modulos.CATALOGO[chave]["plataformas"]}
    filtrados = {k: v for k, v in valores.items() if k in permitidas}
    # Nenhuma plataforma contratada (config exótica): mantém o original em vez de
    # zerar a nota de todo mundo — degradação segura.
    return filtrados or valores


def obter_pesos(db: Session, escola_id: int, namespace: str) -> dict[str, float]:
    """Retorna os pesos como frações (0–1), já normalizados defensivamente.

    A interface impede salvar pesos cuja soma difere de 100 (PRD §33),
    mas o motor ainda divide pela soma para nunca produzir notas > 100.

    Em ``pesos.geral``, as plataformas de módulos NÃO contratados saem da conta e
    o peso é redistribuído entre as contratadas (ver
    ``_pesos_dos_modulos_contratados``) — a fórmula, as referências (P90/mediana)
    e a saturação seguem exatamente as mesmas.
    """
    valores = obter_config(db, escola_id, namespace, "valores", PESOS_PADRAO[namespace])
    if namespace == "pesos.geral":
        valores = _pesos_dos_modulos_contratados(db, escola_id, valores)
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


def _overrides_serie(db: Session, escola_id: int) -> dict[tuple[str, str], float]:
    """Override de pontos por SÉRIE (legado): ``{(ano_escolar, CODIGO_UPPER):
    pontos}`` a partir de DificuldadeTurma. Sobrepõe o padrão da escola; é
    sobreposto pela config LIVRE por turma. Resolução: TURMA > SÉRIE > padrão."""
    niveis = {n.id: n for n in db.execute(
        select(NivelDificuldade).where(NivelDificuldade.escola_id == escola_id)
    ).scalars()}
    saida: dict[tuple[str, str], float] = {}
    for ov in db.execute(
        select(DificuldadeTurma).where(DificuldadeTurma.escola_id == escola_id)
    ).scalars():
        nivel = niveis.get(ov.nivel_id)
        if nivel is None:
            continue
        for codigo in (nivel.codigos or []):
            if codigo:
                saida[(ov.ano_escolar, str(codigo).strip().upper())] = float(ov.pontos)
    return saida


def pontos_por_codigo(db: Session, escola_id: int, turma_id: int | None = None,
                      ano_escolar: str | None = None) -> dict[str, float]:
    """Pontos de dificuldade por CÓDIGO de letra do livro (ex.: {"AA": 1.0,
    "D": 4.0}). Base do ranking de leitura por período. Com ``ano_escolar`` e/ou
    ``turma_id``, resolve **TURMA > SÉRIE > padrão** — a MESMA régua do ranking
    anual, para as telas de PERÍODO (premiações, aba Leitura, evolução, histórico)
    não divergirem do Geral."""
    mapa: dict[str, float] = {}
    for nivel in db.execute(
        select(NivelDificuldade).where(NivelDificuldade.escola_id == escola_id)
    ).scalars():
        for codigo in (nivel.codigos or []):
            if codigo:
                mapa[str(codigo).upper()] = float(nivel.pontos_padrao)
    if ano_escolar:                       # 2) override por SÉRIE
        for (serie, cod_up), pontos in _overrides_serie(db, escola_id).items():
            if serie == ano_escolar and cod_up in mapa:
                mapa[cod_up] = pontos
    if turma_id:                          # 1) config LIVRE por TURMA (mais forte)
        mapa.update(_overrides_turma(db, escola_id).get(turma_id, {}))
    return mapa


def mapa_pontos_turmas(db: Session, escola_id: int) -> dict:
    """``{turma_id | None: {CODIGO_UPPER: pontos}}`` resolvido **TURMA > SÉRIE >
    padrão**. ``None`` = padrão da escola; cada turma já traz a SÉRIE e a config
    LIVRE aplicadas. Para o ranking/premiação por período resolver a pontuação
    pela turma do aluno numa passada só (sem N+1)."""
    base = pontos_por_codigo(db, escola_id)
    overrides_serie = _overrides_serie(db, escola_id)
    overrides_turma = _overrides_turma(db, escola_id)
    turmas = db.execute(
        select(Turma.id, Turma.ano_escolar).where(Turma.escola_id == escola_id)
    ).all()
    saida: dict = {None: base}
    for turma_id, serie in turmas:
        combinado = dict(base)
        for (s, cod_up), pontos in overrides_serie.items():   # SÉRIE
            if s == serie and cod_up in combinado:
                combinado[cod_up] = pontos
        combinado.update(overrides_turma.get(turma_id, {}))   # TURMA-livre (mais forte)
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
) -> tuple[dict[str, float], str, dict[str, float]]:
    """Resolve as referências e o k de saturação de cada indicador.

    Modo AUTO (robusto): referência = **P90** dos alunos ATIVOS (>0) — não o
    máximo — para um único outlier não definir a régua; e ``k`` (meia-saturação)
    = mediana dos ativos, só para os indicadores de VOLUME. Escola pequena
    (< ``MIN_ALUNOS_ROBUSTO``) ou indicador com poucos ativos recai no máximo
    (escala simples, sem saturação). Modo MANUAL: valores do admin, LINEARES
    (sem saturação — previsível), com chaves ausentes caindo no auto.
    Retorna ``(referencias, modo, k_por_indicador)``; ``k`` vazio = sem saturação.
    """
    listas = {
        "atividades": [s.atividades for s in matific.values()],
        "media": [s.pontuacao_media for s in matific.values()],
        "estrelas": [s.estrelas for s in matific.values()],
        "livros": [s.livros_unicos for s in elefante.values()],
        "pontos_dificuldade": list(pontos_dificuldade.values()),
        "tentativas": [s.questoes_tentativas for s in elefante.values()],
        "acertos": [s.questoes_acertos for s in elefante.values()],
        "tempo": [s.tempo_leitura_min for s in elefante.values()],
    }
    n_alunos = max(len(matific), len(elefante))
    usar_robusto = n_alunos >= MIN_ALUNOS_ROBUSTO

    auto: dict[str, float] = {}
    k_vol: dict[str, float] = {}
    for indicador, valores in listas.items():
        chave = "max_" + indicador
        ativos = [x for x in valores if x and x > 0]
        if usar_robusto and len(ativos) >= 2:
            auto[chave] = _percentil(ativos, 0.90)        # régua robusta (top 10%)
            if indicador in INDICADORES_VOLUME:
                k_vol[indicador] = _percentil(ativos, 0.50)  # meia-saturação = mediana
        else:
            auto[chave] = max(valores, default=0)          # poucos dados → escala simples

    ref_row = db.execute(
        select(ReferenciaNormalizacao).where(
            ReferenciaNormalizacao.escola_id == escola_id
        )
    ).scalar_one_or_none()

    if ref_row is None or ref_row.modo == "auto":
        return auto, "auto", k_vol

    # MANUAL: o admin define a régua → linear e previsível (sem saturação).
    manuais = ref_row.valores_manuais or {}
    resolvidas = {
        chave: float(manuais.get(chave) or auto[chave]) for chave in CHAVES_REFERENCIA
    }
    return resolvidas, "manual", {}


# ---------------------------------------------------------------------------
# Cálculo por módulo
# ---------------------------------------------------------------------------

def _norm(indicador: str, valor: float, referencia: float,
          k_vol: dict[str, float] | None) -> float:
    """Normaliza um indicador: saturado se ``k_vol`` tiver o k dele (volume no
    modo auto), senão linear (qualidade, modo manual, evolução)."""
    k = (k_vol or {}).get(indicador)
    return normalizar_saturado(valor, referencia, k) if k else normalizar(valor, referencia)


def _linha(nome: str, indicador: str, valor: float, referencia: float,
           peso_pct: float, k_vol: dict[str, float] | None) -> dict:
    norm = _norm(indicador, valor, referencia, k_vol)
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
    k_vol: dict[str, float] | None = None,
) -> tuple[float, list[dict]]:
    atividades = snapshot.atividades if snapshot else 0
    media = snapshot.pontuacao_media if snapshot else 0.0
    estrelas = snapshot.estrelas if snapshot else 0

    linhas = [
        _linha("Atividades finalizadas", "atividades", atividades, refs["max_atividades"], pesos_pct.get("atividades", 0), k_vol),
        _linha("Pontuação média", "media", media, refs["max_media"], pesos_pct.get("media", 0), k_vol),
        _linha("Estrelas", "estrelas", estrelas, refs["max_estrelas"], pesos_pct.get("estrelas", 0), k_vol),
    ]
    nota = (
        _norm("atividades", atividades, refs["max_atividades"], k_vol) * pesos.get("atividades", 0)
        + _norm("media", media, refs["max_media"], k_vol) * pesos.get("media", 0)
        + _norm("estrelas", estrelas, refs["max_estrelas"], k_vol) * pesos.get("estrelas", 0)
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
    k_vol: dict[str, float] | None = None,
) -> tuple[float, list[dict], dict]:
    livros = snapshot.livros_unicos if snapshot else 0
    tempo = snapshot.tempo_leitura_min if snapshot else 0
    tentativas = snapshot.questoes_tentativas if snapshot else 0
    acertos = snapshot.questoes_acertos if snapshot else 0

    # Sub-nota de questões: tentativas (volume → satura) + acertos (qualidade →
    # linear), PRD §36. Assim tentar muito não infla; acertar é que conta.
    n_tentativas = _norm("tentativas", tentativas, refs["max_tentativas"], k_vol)
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
        _linha("Livros únicos concluídos", "livros", livros, refs["max_livros"], pesos_pct.get("livros", 0), k_vol),
        _linha("Pontos de dificuldade", "pontos_dificuldade", pontos_dificuldade, refs["max_pontos_dificuldade"], pesos_pct.get("dificuldade", 0), k_vol),
        _linha("Questões (tentativas + acertos)", "questoes", nota_questoes, 100.0, pesos_pct.get("questoes", 0), None),
        _linha("Tempo de leitura (min)", "tempo", tempo, refs["max_tempo"], pesos_pct.get("tempo", 0), k_vol),
    ]
    nota = (
        _norm("livros", livros, refs["max_livros"], k_vol) * pesos.get("livros", 0)
        + normalizar(pontos_dificuldade, refs["max_pontos_dificuldade"]) * pesos.get("dificuldade", 0)
        + nota_questoes * pesos.get("questoes", 0)
        + _norm("tempo", tempo, refs["max_tempo"], k_vol) * pesos.get("tempo", 0)
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

    # Restringe os snapshots ao conjunto PONTUADO (ativos matriculados no ano) —
    # o mesmo dos `pontos_dif` abaixo. Sem isto, o snapshot de um aluno arquivado/
    # excluído/não-matriculado entrava na régua de normalização (P90/mediana) sem
    # ser pontuado: arquivar um aluno (operação rotineira, que dispara recálculo)
    # mudava as notas e as posições de todos os ativos.
    ids_pontuados = {m.aluno_id for m, _t in matriculas}
    matific = {aid: s for aid, s in _snapshots_atuais(db, escola_id, SnapshotMatific).items()
               if aid in ids_pontuados}
    elefante = {aid: s for aid, s in _snapshots_atuais(db, escola_id, SnapshotElefante).items()
                if aid in ids_pontuados}
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
    refs, modo, _ = contexto_normalizacao(db, escola_id)
    return refs, modo


def contexto_normalizacao(
    db: Session, escola_id: int
) -> tuple[dict, str, dict[str, float]]:
    """``(referencias, modo, k_saturacao)`` — para o ranking e o simulador
    (sistema.py) usarem exatamente a mesma normalização."""
    contexto = _carregar_contexto(db, escola_id)
    if contexto is None:
        return {}, "auto", {}
    _, _, _, matific, elefante, pontos_dif = contexto
    return _referencias(db, escola_id, matific, elefante, pontos_dif)


def recalcular_escola(db: Session, escola_id: int) -> int:
    """Recalcula todas as notas e o ranking da escola. Retorna nº de alunos."""
    # PRIMEIRA linha, antes de QUALQUER leitura que entre no cálculo: daqui até
    # o `db.commit()` do fim, esta escola é só desta transação. Sem isso, dois
    # recálculos sobrepostos leem o mesmo estado e gravam um por cima do outro
    # — 500 por uq_nota_aluno_ano quando inserem, e nota errada em silêncio
    # quando atualizam. Transacional: cai sozinha no commit (no-op no SQLite).
    bloquear_escola_para_recalculo(db, escola_id)
    contexto = _carregar_contexto(db, escola_id)
    if contexto is None:
        return 0
    escola, ano, matriculas, matific, elefante, pontos_dif = contexto

    # Pontos extras por livro lido NA ESCOLA (opcional): soma nos pontos de
    # dificuldade os livros lidos dentro da janela do turno da turma. Feito ANTES
    # das referências para a normalização já considerar o bônus. Desligado => 0.
    extra = obter_config(db, escola_id, "pesos.elefante_extra", "valores",
                         {"ativo": False, "pontos_por_livro": 0.0})
    bonus_por_aluno: dict[int, float] = {}
    if extra.get("ativo") and float(extra.get("pontos_por_livro", 0) or 0) > 0:
        turno_por_aluno = {m.aluno_id: t.turno for m, t in matriculas}
        bonus_por_aluno = _bonus_leitura_na_escola(
            db, escola_id, turno_por_aluno, float(extra["pontos_por_livro"]))
        for aid, b in bonus_por_aluno.items():
            pontos_dif[aid] = pontos_dif.get(aid, 0.0) + b

    refs, modo, k_vol = _referencias(db, escola_id, matific, elefante, pontos_dif)

    p_matific = obter_pesos(db, escola_id, "pesos.matific")
    p_elefante = obter_pesos(db, escola_id, "pesos.elefante")
    p_questoes = obter_pesos(db, escola_id, "pesos.questoes")
    p_geral = obter_pesos(db, escola_id, "pesos.geral")
    pct_matific = obter_pesos_brutos(db, escola_id, "pesos.matific")
    pct_elefante = obter_pesos_brutos(db, escola_id, "pesos.elefante")
    pct_questoes = obter_pesos_brutos(db, escola_id, "pesos.questoes")
    # A EXPLICAÇÃO da Nota Geral é DERIVADA dos pesos efetivamente usados
    # (`p_geral`), não lida de novo da configuração. Assim ela não tem como
    # divergir da conta: as parcelas exibidas somam 100% e reproduzem a nota.
    # Sem isto, uma rede que só assinou a Leitura gravaria "Matific 100 × 50% +
    # Elefante 70 × 50% = 70" — equação que não fecha, justamente na tela de
    # auditoria da nota (PRD §45). Com os dois módulos e pesos somando 100 (o
    # estado de toda rede hoje) o valor gravado é idêntico ao de antes.
    pct_geral = {chave: round(fracao * 100, 2) for chave, fracao in p_geral.items()
                 if fracao > 0}

    resultados: list[ResultadoAluno] = []
    for matricula, turma in matriculas:
        aluno = matricula.aluno
        snap_m = matific.get(aluno.id)
        snap_e = elefante.get(aluno.id)

        nota_m, linhas_m = calcular_matific(snap_m, refs, p_matific, pct_matific, k_vol)
        nota_e, linhas_e, det_q = calcular_elefante(
            snap_e, pontos_dif[aluno.id], refs, p_elefante, pct_elefante,
            p_questoes, pct_questoes, k_vol,
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
                    # Registro auditável da correção (PRD §45): referência P90 e a
                    # meia-saturação (k) por indicador de volume, quando aplicadas.
                    "referencia_tipo": ("p90_robusto" if (modo == "auto" and k_vol)
                                        else ("maximo" if modo == "auto" else "manual")),
                    "saturacao": dict(k_vol),
                    "matific": {"indicadores": linhas_m, "nota": nota_m},
                    "elefante": {"indicadores": linhas_e, "questoes": det_q, "nota": nota_e,
                                 "bonus_leitura_escola": round(bonus_por_aluno.get(aluno.id, 0.0), 2)},
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
