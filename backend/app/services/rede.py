"""Agregação por REDE / Secretaria de Educação (o tier acima da escola).

Roda SOBRE os dados por escola já existentes — não reimplementa scoring nem toca
em pesos/fórmulas (o motor de pontuação é a fonte única). Cada indicador
municipal é uma soma/média dos indicadores por escola. O isolamento continua por
escola; aqui só se AGREGAM as escolas que pertencem à rede, e NUNCA se expõe PII
de criança nem ranking individual entre escolas (privacidade).

Desempenho: os KPIs de TODAS as escolas da rede saem em 3 consultas agregadas
(GROUP BY escola_id), não em N×3 — uma rede municipal grande tem centenas de
escolas. O filtro de ano correlaciona a coluna por-escola ``Escola.ano_letivo_ativo``
(cada escola tem o seu), nunca uma constante.
"""
from __future__ import annotations

import secrets

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    Aluno,
    Escola,
    Matricula,
    MetaRede,
    Nota,
    Professor,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import scoring

# Regras de "escola que precisa de atenção" (transparentes e auditáveis).
ADOCAO_BAIXA = 40.0      # % de alunos ativos com nota abaixo disto = pouca adoção
MEDIA_BAIXA = 30.0       # média geral da escola abaixo disto = desempenho baixo


def escolas_da_rede(db: Session, rede_id: int) -> list[Escola]:
    return list(db.execute(
        select(Escola).where(Escola.rede_id == rede_id).order_by(Escola.nome)
    ).scalars().all())


def _motivo_atencao(total_alunos: int, com_dados: int, adocao: float,
                    media_geral: float) -> str | None:
    """Por que a escola precisa de atenção — ou None se está saudável."""
    if total_alunos == 0:
        return "Sem alunos matriculados no ano letivo."
    if com_dados == 0:
        return "Nenhum aluno com dados das plataformas ainda."
    if adocao < ADOCAO_BAIXA:
        return f"Baixa adoção: só {adocao:.0f}% dos alunos têm dados."
    if 0 < media_geral < MEDIA_BAIXA:
        return f"Desempenho baixo: média geral {media_geral:.0f}."
    return None


def _totais_plataforma_por_escola(db: Session, ids: list[int], modelo,
                                  campos: list[str]) -> dict[int, dict]:
    """Soma, por escola, os campos do snapshot ATUAL de cada aluno (o último por
    data_referencia,id — mesma régua do scoring) e conta os alunos ATIVOS na
    plataforma. UMA window query para a rede inteira (não N por escola). Só
    números BRUTOS agregados: nenhum dado individual de criança.

    RESTRINGE ao MESMO conjunto das contagens de ``_kpis_da_rede`` (aluno ativo
    E matriculado no ano letivo ATIVO da escola). Sem isso, o snapshot 'preso' de
    um aluno transferido/arquivado (que persiste — o scoring já o filtra de
    propósito) inflava os totais e o ``ativos_*`` frente ao total de alunos,
    chegando a ``ativos_elefante > total_alunos`` no painel da rede/global. O
    JOIN em Matrícula pode multiplicar a linha do snapshot (aluno em >1 turma),
    mas a janela por (escola_id, aluno_id) + ``pos == 1`` deduplica: um aluno
    conta uma vez, sempre pelo snapshot mais recente."""
    if not ids:
        return {}
    numerado = (
        select(
            modelo.escola_id.label("escola_id"),
            *[getattr(modelo, c).label(c) for c in campos],
            func.row_number().over(
                partition_by=(modelo.escola_id, modelo.aluno_id),
                order_by=(modelo.data_referencia.desc(), modelo.id.desc()),
            ).label("pos"),
        )
        .join(Aluno, Aluno.id == modelo.aluno_id)
        .join(Escola, Escola.id == modelo.escola_id)
        .join(Matricula, (Matricula.aluno_id == modelo.aluno_id)
              & (Matricula.escola_id == modelo.escola_id)
              & (Matricula.ano_letivo == Escola.ano_letivo_ativo))
        .where(modelo.escola_id.in_(ids), Aluno.status == "ativo")
        .subquery()
    )
    colunas = [numerado.c.escola_id, func.count().label("ativos")]
    colunas += [func.coalesce(func.sum(getattr(numerado.c, c)), 0).label(c) for c in campos]
    linhas = db.execute(
        select(*colunas).where(numerado.c.pos == 1).group_by(numerado.c.escola_id)
    ).all()
    return {linha.escola_id: dict(linha._mapping) for linha in linhas}


def _kpis_da_rede(db: Session, rede_id: int) -> list[dict]:
    """Cartão resumido de CADA escola da rede (contagens + médias + totais brutos
    das plataformas do ano letivo ativo da própria escola), agregado no banco.
    ``adocao`` = % de alunos ativos com nota (proxy de engajamento). Escolas sem
    dados entram com zeros. NUNCA expõe PII: só agregados por escola."""
    escolas = escolas_da_rede(db, rede_id)
    if not escolas:
        return []
    ids = [e.id for e in escolas]

    # (1) turmas ativas por escola — cada escola pelo seu ano_letivo_ativo.
    turmas = dict(db.execute(
        select(Turma.escola_id, func.count(Turma.id))
        .join(Escola, Escola.id == Turma.escola_id)
        .where(Turma.escola_id.in_(ids),
               Turma.ano_letivo == Escola.ano_letivo_ativo,
               Turma.status == "ativa")
        .group_by(Turma.escola_id)
    ).all())

    # (2) alunos ativos distintos por escola.
    alunos = dict(db.execute(
        select(Matricula.escola_id, func.count(func.distinct(Matricula.aluno_id)))
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .join(Escola, Escola.id == Matricula.escola_id)
        .where(Matricula.escola_id.in_(ids),
               Matricula.ano_letivo == Escola.ano_letivo_ativo,
               Aluno.status == "ativo")
        .group_by(Matricula.escola_id)
    ).all())

    # (3) contagem + médias das notas por escola (agregado no banco).
    notas = {r[0]: r for r in db.execute(
        select(Nota.escola_id, func.count(Nota.id), func.avg(Nota.nota_geral),
               func.avg(Nota.nota_matific), func.avg(Nota.nota_elefante))
        .join(Aluno, Aluno.id == Nota.aluno_id)
        .join(Escola, Escola.id == Nota.escola_id)
        .where(Nota.escola_id.in_(ids),
               Nota.ano_letivo == Escola.ano_letivo_ativo,
               Aluno.status == "ativo")
        .group_by(Nota.escola_id)
    ).all()}

    # (4) professores por escola (mesma contagem do painel da escola).
    professores = dict(db.execute(
        select(Professor.escola_id, func.count(Professor.id))
        .where(Professor.escola_id.in_(ids))
        .group_by(Professor.escola_id)
    ).all())

    # (5) totais BRUTOS das plataformas por escola (snapshot atual de cada aluno):
    # livros/tempo do Elefante e atividades/estrelas do Matific + alunos ativos.
    mat = _totais_plataforma_por_escola(db, ids, SnapshotMatific, ["atividades", "estrelas"])
    ele = _totais_plataforma_por_escola(db, ids, SnapshotElefante,
                                        ["livros_unicos", "tempo_leitura_min"])

    cartoes = []
    for escola in escolas:
        agg = notas.get(escola.id)
        com_nota = int((agg[1] if agg else 0) or 0)
        val = ((lambda i: round(float(agg[i]), 1)) if (agg and com_nota)
               else (lambda i: 0.0))
        total_alunos = int(alunos.get(escola.id, 0))
        adocao = round(com_nota / total_alunos * 100, 1) if total_alunos else 0.0
        media_geral = val(2)
        motivo = _motivo_atencao(total_alunos, com_nota, adocao, media_geral)
        m, e = mat.get(escola.id), ele.get(escola.id)
        livros = int(e["livros_unicos"]) if e else 0
        ativos_ele = int(e["ativos"]) if e else 0
        estrelas = int(m["estrelas"]) if m else 0
        atividades = int(m["atividades"]) if m else 0
        tempo_min = int(e["tempo_leitura_min"]) if e else 0
        cartoes.append({
            "escola_id": escola.id, "nome": escola.nome, "cidade": escola.cidade,
            "status": escola.status,
            "latitude": escola.latitude, "longitude": escola.longitude,
            "total_turmas": int(turmas.get(escola.id, 0)),
            "total_professores": int(professores.get(escola.id, 0)),
            "total_alunos": total_alunos,
            "alunos_com_dados": com_nota,
            "adocao": adocao,
            "media_geral": media_geral, "media_matific": val(3), "media_elefante": val(4),
            # Totais brutos das plataformas (para as seções Elefante/Matific da rede).
            "livros": livros,
            "tempo_leitura_min": tempo_min,
            "atividades": atividades,
            "estrelas": estrelas,
            "ativos_matific": int(m["ativos"]) if m else 0,
            "ativos_elefante": ativos_ele,
            "livros_por_aluno": round(livros / ativos_ele, 1) if ativos_ele else 0.0,
            # Per capita por MATRÍCULA (÷ total de alunos da escola) — critério de
            # ranking JUSTO entre escolas de tamanhos diferentes: combina adoção e
            # intensidade e NÃO favorece a escola grande pelo volume bruto (item 1).
            # É a conta do dono: 19.122÷200≈95,6 supera 24.000÷600=40.
            "livros_por_matricula": round(livros / total_alunos, 1) if total_alunos else 0.0,
            "estrelas_por_matricula": round(estrelas / total_alunos, 1) if total_alunos else 0.0,
            "atividades_por_matricula": round(atividades / total_alunos, 1) if total_alunos else 0.0,
            "tempo_por_matricula_min": round(tempo_min / total_alunos, 1) if total_alunos else 0.0,
            "precisa_atencao": motivo is not None,
            "motivo_atencao": motivo,
        })
    _pontuar_escolas(cartoes)
    return cartoes


# ---------------------------------------------------------------------------
# ÍNDICE DA REDE (0–1000) — pontuação COMPARÁVEL ENTRE escolas
# ---------------------------------------------------------------------------
# Por que NÃO reusar media_elefante/media_matific aqui: aquelas notas (0–100) são
# normalizadas contra a régua da PRÓPRIA escola (P90 dos alunos dela, ver
# scoring._referencias) — um "60" numa escola não equivale a um "60" noutra. Elas
# servem ao ranking INTERNO (competição entre colegas), não à comparação entre
# escolas. O índice da rede usa a MESMA primitiva de normalização do motor
# (``scoring.normalizar``), mudando só duas coisas: a COORTE passa a ser a REDE
# (a régua é a melhor escola, não a própria escola) e o indicador é PER CAPITA —
# que é o que torna escolas de tamanhos diferentes comparáveis. Nenhuma segunda
# lógica de pontuação: é o mesmo motor com outro escopo.
#
# Régua = MELHOR ESCOLA DA REDE (não o P90): entre poucas dezenas de escolas o
# P90 empataria o pódio inteiro no teto (10% das escolas), e o pódio é justamente
# o que a Secretaria lê. Com o máximo, o índice é estritamente monotônico —
# a ordem do ranking e a pontuação nunca se contradizem — e a leitura é direta:
# "1000 = melhor da rede; 500 = metade do desempenho da melhor".
ESCALA_INDICE = 10.0          # 0–100 do motor → 0–1000 exibido na rede


def _indice_da_rede(valor: float, melhor: float) -> float:
    """Indicador per capita → índice 0–1000 na régua da REDE (melhor escola=1000).
    Reusa ``scoring.normalizar`` (linear, teto 100) e só reescala para 0–1000."""
    return round(scoring.normalizar(valor, melhor) * ESCALA_INDICE, 1)


def _pontuar_escolas(cartoes: list[dict]) -> None:
    """Acrescenta a cada cartão o índice da rede por DIMENSÃO (leitura/matemática)
    e o geral, IN PLACE. As dimensões são conceitos distintos e cada uma tem o seu
    indicador per capita como base:

      * leitura     → livros por aluno   (o critério principal do ranking de leitura)
      * matemática  → estrelas por aluno

    ``pontuacao_geral`` é a média das dimensões em que a escola TEM dados: uma
    escola que só usa o Elefante não é punida com um zero de Matific que não
    reflete desempenho, e ``dimensoes_pontuadas`` diz quais entraram na conta
    (a interface mostra isso, para a Secretaria saber o que está comparando).

    ESCOPO: o índice é relativo À REDE recebida. Comparar índices de escolas de
    REDES diferentes não é válido (cada uma foi normalizada contra a melhor da
    sua rede) — por isso o painel global ranqueia escolas por ``media_geral``,
    não por este índice."""
    if not cartoes:
        return
    melhor_leitura = max((c["livros_por_matricula"] for c in cartoes), default=0.0)
    melhor_matematica = max((c["estrelas_por_matricula"] for c in cartoes), default=0.0)
    for c in cartoes:
        # "Tem dados" = a escola tem algum aluno com snapshot daquela plataforma.
        # Sem isso, um zero de "não usa a plataforma" viraria nota de desempenho.
        tem_leitura = c["ativos_elefante"] > 0
        tem_matematica = c["ativos_matific"] > 0
        c["pontuacao_leitura"] = (
            _indice_da_rede(c["livros_por_matricula"], melhor_leitura) if tem_leitura else 0.0)
        c["pontuacao_matematica"] = (
            _indice_da_rede(c["estrelas_por_matricula"], melhor_matematica) if tem_matematica else 0.0)
        disponiveis = [p for p, tem in ((c["pontuacao_leitura"], tem_leitura),
                                        (c["pontuacao_matematica"], tem_matematica)) if tem]
        c["pontuacao_geral"] = round(sum(disponiveis) / len(disponiveis), 1) if disponiveis else 0.0
        c["dimensoes_pontuadas"] = [nome for nome, tem in (("leitura", tem_leitura),
                                                           ("matematica", tem_matematica)) if tem]


def dashboard_rede(db: Session, rede_id: int) -> dict:
    """Painel municipal: totais da rede + cartão de cada escola (para cards e o
    mapa), ordenado por média geral e já numerado (``posicao``). Inclui um resumo
    de EQUIDADE (dispersão entre escolas) e a lista de escolas em ATENÇÃO."""
    cartoes = _kpis_da_rede(db, rede_id)

    total_alunos = sum(c["total_alunos"] for c in cartoes)
    total_turmas = sum(c["total_turmas"] for c in cartoes)
    total_professores = sum(c["total_professores"] for c in cartoes)
    com_dados = sum(c["alunos_com_dados"] for c in cartoes)

    # Média da rede PONDERADA por alunos-com-nota (não média de médias, que daria
    # peso igual a uma escola de 10 e uma de 500 alunos).
    def _ponderada(chave: str) -> float:
        if not com_dados:
            return 0.0
        return round(sum(c[chave] * c["alunos_com_dados"] for c in cartoes) / com_dados, 1)

    media_rede = _ponderada("media_geral")
    com_nota = [c for c in cartoes if c["alunos_com_dados"] > 0]
    medias = [c["media_geral"] for c in com_nota]
    equidade = {
        # Diferença entre a melhor e a pior escola COM dados (quanto maior, mais
        # desigual a rede) — o número que a secretaria usa para direcionar apoio.
        "gap_media": round(max(medias) - min(medias), 1) if len(medias) >= 2 else 0.0,
        "escola_maior_media": round(max(medias), 1) if medias else 0.0,
        "escola_menor_media": round(min(medias), 1) if medias else 0.0,
        "escolas_abaixo_da_media": sum(1 for m in medias if m < media_rede),
    }

    cartoes.sort(key=lambda c: (-c["media_geral"], c["nome"].casefold()))
    for posicao, cartao in enumerate(cartoes, start=1):
        cartao["posicao"] = posicao

    # Totais brutos das plataformas na rede + alunos ativos (soma dos cartões).
    total_livros = sum(c["livros"] for c in cartoes)
    total_atividades = sum(c["atividades"] for c in cartoes)
    ativos_elefante = sum(c["ativos_elefante"] for c in cartoes)
    # A melhor escola COM dados (o pódio do ranking geral) — atalho para o KPI.
    melhor = next((c for c in cartoes if c["alunos_com_dados"] > 0), None)

    return {
        "rede_id": rede_id,
        "totais": {
            "escolas": len(cartoes),
            "escolas_ativas": sum(1 for c in cartoes if c["status"] == "ativa"),
            "alunos": total_alunos,
            "turmas": total_turmas,
            "professores": total_professores,
            "alunos_com_dados": com_dados,
            "adocao": round(com_dados / total_alunos * 100, 1) if total_alunos else 0.0,
            "media_geral": media_rede,
            "media_matific": _ponderada("media_matific"),
            "media_elefante": _ponderada("media_elefante"),
            "escolas_em_atencao": sum(1 for c in cartoes if c["precisa_atencao"]),
            # Totais das plataformas na rede inteira (seções Elefante/Matific).
            "livros": total_livros,
            "tempo_leitura_min": sum(c["tempo_leitura_min"] for c in cartoes),
            "atividades": total_atividades,
            "estrelas": sum(c["estrelas"] for c in cartoes),
            "ativos_matific": sum(c["ativos_matific"] for c in cartoes),
            "ativos_elefante": ativos_elefante,
            "livros_por_aluno": round(total_livros / ativos_elefante, 1) if ativos_elefante else 0.0,
            "melhor_escola": {"nome": melhor["nome"], "media_geral": melhor["media_geral"]}
            if melhor else None,
        },
        "equidade": equidade,
        "escolas": cartoes,
        # Atalho: só as escolas que precisam de atenção (a lista de ação da rede).
        "atencao": [c for c in cartoes if c["precisa_atencao"]],
    }


# Métricas de ordenação do ranking de escolas (SEDUC escolhe o critério). Só
# agregados por escola — nunca ranking individual entre escolas (privacidade).
METRICAS_RANKING = {
    "geral": "media_geral",
    "leitura": "media_elefante",
    "elefante": "media_elefante",
    "matematica": "media_matific",
    "matific": "media_matific",
    "engajamento": "adocao",
    "livros": "livros",
    "estrelas": "estrelas",
    # Critérios PER CAPITA (÷ matrícula) — comparação JUSTA entre escolas de
    # tamanhos diferentes (item 1): não favorecem a escola grande pelo volume bruto.
    # "livros_aluno" é o critério PRINCIPAL do ranking de LEITURA da rede.
    "livros_aluno": "livros_por_matricula",
    "estrelas_aluno": "estrelas_por_matricula",
    "atividades_aluno": "atividades_por_matricula",
    # ÍNDICES da rede (0–1000, régua = melhor escola sobre o indicador per capita).
    # As chaves legadas acima (geral/leitura/matematica = médias 0–100 do motor)
    # continuam válidas para não quebrar consumidores antigos, mas NÃO são
    # comparáveis entre escolas (cada escola é normalizada na própria curva).
    "indice_geral": "pontuacao_geral",
    "indice_leitura": "pontuacao_leitura",
    "indice_matematica": "pontuacao_matematica",
}


def ranking_escolas(db: Session, rede_id: int, limite: int = 50,
                    metrica: str = "geral") -> list[dict]:
    """Ranking MUNICIPAL por escola (não expõe ranking individual de crianças
    entre escolas — decisão de privacidade). A SEDUC escolhe o CRITÉRIO em
    ``metrica`` (ver ``METRICAS_RANKING``); desempata por adoção e nome. Só
    escolas com dados entram.

    As abas do Ranking da Rede usam: ``indice_geral`` (Geral), ``livros_aluno``
    (Leitura — livros ÷ alunos, o critério principal), ``estrelas_aluno``
    (Matemática) e ``engajamento`` (participação). Todas per capita ou índice, de
    modo que a escola GRANDE não sobe só por ter mais alunos."""
    chave = METRICAS_RANKING.get(metrica, "media_geral")
    cartoes = [c for c in _kpis_da_rede(db, rede_id) if c["alunos_com_dados"] > 0]
    cartoes.sort(key=lambda c: (-c[chave], -c["adocao"], c["nome"].casefold()))
    for posicao, cartao in enumerate(cartoes[:limite], start=1):
        cartao["posicao"] = posicao
    return cartoes[:limite]


# ---------------------------------------------------------------------------
# Visão GLOBAL do Admin Global — consolida TODAS as redes (uma camada acima da
# Secretaria, que vê só a própria rede). Só agregados por escola/rede, sem PII.
# ---------------------------------------------------------------------------

def dashboard_global(db: Session) -> dict:
    """Panorama consolidado de TODAS as redes (Admin Global): totais globais,
    cartão por REDE (para comparar/ranquear redes) e as melhores escolas de toda
    a base com o nome da rede. Reusa ``_kpis_da_rede`` por rede — só agregado."""
    redes = db.execute(select(Rede).order_by(Rede.nome)).scalars().all()
    cartoes_rede: list[dict] = []
    todas_escolas: list[dict] = []
    for rede in redes:
        cartoes = _kpis_da_rede(db, rede.id)
        alunos = sum(c["total_alunos"] for c in cartoes)
        com_dados = sum(c["alunos_com_dados"] for c in cartoes)

        def _pond(chave: str, _cartoes=cartoes, _com=com_dados) -> float:
            if not _com:
                return 0.0
            return round(sum(c[chave] * c["alunos_com_dados"] for c in _cartoes) / _com, 1)

        cartoes_rede.append({
            "rede_id": rede.id, "nome": rede.nome, "uf": rede.uf, "status": rede.status,
            "escolas": len(cartoes),
            "alunos": alunos, "turmas": sum(c["total_turmas"] for c in cartoes),
            "professores": sum(c["total_professores"] for c in cartoes),
            "alunos_com_dados": com_dados,
            "adocao": round(com_dados / alunos * 100, 1) if alunos else 0.0,
            "media_geral": _pond("media_geral"),
            "media_matific": _pond("media_matific"),
            "media_elefante": _pond("media_elefante"),
            "livros": sum(c["livros"] for c in cartoes),
            "atividades": sum(c["atividades"] for c in cartoes),
            "estrelas": sum(c["estrelas"] for c in cartoes),
            "escolas_em_atencao": sum(1 for c in cartoes if c["precisa_atencao"]),
        })
        for c in cartoes:
            todas_escolas.append({**c, "rede_id": rede.id, "rede_nome": rede.nome})

    total_com_dados = sum(r["alunos_com_dados"] for r in cartoes_rede)

    def _pond_global(chave: str) -> float:
        if not total_com_dados:
            return 0.0
        return round(sum(r[chave] * r["alunos_com_dados"] for r in cartoes_rede) / total_com_dados, 1)

    cartoes_rede.sort(key=lambda r: (-r["media_geral"], r["nome"].casefold()))
    for posicao, cartao in enumerate(cartoes_rede, start=1):
        cartao["posicao"] = posicao
    top = [e for e in todas_escolas if e["alunos_com_dados"] > 0]
    top.sort(key=lambda e: (-e["media_geral"], e["nome"].casefold()))

    return {
        "totais": {
            "redes": len(cartoes_rede),
            "escolas": sum(r["escolas"] for r in cartoes_rede),
            "alunos": sum(r["alunos"] for r in cartoes_rede),
            "turmas": sum(r["turmas"] for r in cartoes_rede),
            "professores": sum(r["professores"] for r in cartoes_rede),
            "livros": sum(r["livros"] for r in cartoes_rede),
            "atividades": sum(r["atividades"] for r in cartoes_rede),
            "estrelas": sum(r["estrelas"] for r in cartoes_rede),
            "alunos_com_dados": total_com_dados,
            "media_geral": _pond_global("media_geral"),
            "media_matific": _pond_global("media_matific"),
            "media_elefante": _pond_global("media_elefante"),
            "escolas_em_atencao": sum(r["escolas_em_atencao"] for r in cartoes_rede),
        },
        "redes": cartoes_rede,
        "top_escolas": top[:10],
    }


# ---------------------------------------------------------------------------
# METAS da rede (§9) — a Secretaria CADASTRA o alvo de um indicador; o progresso
# é sempre calculado sobre os totais REAIS (nunca número fictício).
# ---------------------------------------------------------------------------

# Indicadores que aceitam meta: rótulo, sufixo e se dá para comparar POR ESCOLA
# (média/adoção sim; totais da rede não — uma escola não bate um total municipal).
METRICAS_META: dict[str, dict] = {
    "media_geral": {"rotulo": "Média geral da rede", "sufixo": "", "por_escola": True},
    "media_elefante": {"rotulo": "Leitura (Elefante Letrado)", "sufixo": "", "por_escola": True},
    "media_matific": {"rotulo": "Matemática (Matific)", "sufixo": "", "por_escola": True},
    "adocao": {"rotulo": "Engajamento (adoção)", "sufixo": "%", "por_escola": True},
    "livros": {"rotulo": "Livros lidos na rede", "sufixo": "", "por_escola": False},
    "atividades": {"rotulo": "Atividades Matific na rede", "sufixo": "", "por_escola": False},
}


def listar_metas(db: Session, rede_id: int) -> list[dict]:
    metas = db.execute(
        select(MetaRede).where(MetaRede.rede_id == rede_id).order_by(MetaRede.metrica)
    ).scalars().all()
    return [{"id": m.id, "metrica": m.metrica, "alvo": m.alvo, "descricao": m.descricao}
            for m in metas]


def definir_meta(db: Session, rede_id: int, metrica: str, alvo: float,
                 descricao: str | None = None) -> MetaRede:
    """Upsert: UMA meta por (rede, métrica) — redefinir sobrescreve o alvo."""
    if metrica not in METRICAS_META:
        raise ValueError("Métrica de meta inválida.")
    meta = db.execute(select(MetaRede).where(
        MetaRede.rede_id == rede_id, MetaRede.metrica == metrica)).scalars().first()
    if meta is None:
        meta = MetaRede(rede_id=rede_id, metrica=metrica, alvo=alvo, descricao=descricao)
        db.add(meta)
    else:
        meta.alvo = alvo
        meta.descricao = descricao
    return meta


def remover_meta(db: Session, rede_id: int, metrica: str) -> None:
    db.execute(delete(MetaRede).where(
        MetaRede.rede_id == rede_id, MetaRede.metrica == metrica))


def metas_com_progresso(db: Session, rede_id: int, dados: dict | None = None) -> list[dict]:
    """Metas cadastradas + progresso REAL: valor ATUAL da rede / alvo (limitado a
    100%) + quantas escolas COM dados já atingiram (só para métricas comparáveis
    por escola). Sem meta cadastrada → lista vazia (a UI mostra o convite)."""
    metas = db.execute(
        select(MetaRede).where(MetaRede.rede_id == rede_id).order_by(MetaRede.metrica)
    ).scalars().all()
    if not metas:
        return []
    if dados is None:
        dados = dashboard_rede(db, rede_id)
    totais = dados["totais"]
    com_dados = [c for c in dados["escolas"] if c["alunos_com_dados"] > 0]
    saida = []
    for m in metas:
        cfg = METRICAS_META.get(m.metrica)
        if cfg is None:
            continue
        atual = float(totais.get(m.metrica, 0) or 0)
        progresso = round(min(100.0, atual / m.alvo * 100), 1) if m.alvo else 0.0
        item = {
            "id": m.id, "metrica": m.metrica, "rotulo": cfg["rotulo"],
            "sufixo": cfg["sufixo"], "alvo": round(m.alvo, 1), "atual": round(atual, 1),
            "progresso": progresso, "atingida": atual >= m.alvo, "descricao": m.descricao,
            "escolas_atingiram": None, "escolas_total": None,
        }
        if cfg["por_escola"] and com_dados:
            item["escolas_atingiram"] = sum(1 for c in com_dados if c.get(m.metrica, 0) >= m.alvo)
            item["escolas_total"] = len(com_dados)
        saida.append(item)
    return saida


# ---------------------------------------------------------------------------
# Painel PÚBLICO da Secretaria (vitrine SEM login): as MELHORES ESCOLAS da rede
# em leitura e matemática — decisão de produto do dono. NUNCA nome de criança
# nem ranking individual; só escolas + a métrica. Habilitado por um token na
# rede (nulo = desligado); trocar/limpar o token invalida o link imediatamente.
# ---------------------------------------------------------------------------

def _top_escolas(cartoes: list[dict], chave: str, limite: int = 5) -> list[dict]:
    """Top-N escolas por uma métrica (>0), sem PII — só nome + valor."""
    validos = [c for c in cartoes if c["alunos_com_dados"] > 0 and c.get(chave, 0) > 0]
    validos.sort(key=lambda c: (-c[chave], c["nome"].casefold()))
    return [{"nome": c["nome"], "valor": round(float(c[chave]), 1)}
            for c in validos[:limite]]


def painel_publico_rede(db: Session, rede_id: int) -> dict:
    """Dados da vitrine pública: top 5 escolas em LEITURA (Elefante) e em
    MATEMÁTICA (Matific). Só agregado por escola — sem PII de criança."""
    rede = db.get(Rede, rede_id)
    cartoes = _kpis_da_rede(db, rede_id)
    return {
        "rede_nome": rede.nome if rede else "",
        "top_leitura": _top_escolas(cartoes, "media_elefante"),
        "top_matematica": _top_escolas(cartoes, "media_matific"),
    }


def rede_pelo_token_publico(db: Session, token: str) -> Rede | None:
    """Resolve o token público para a rede (comparação em tempo constante contra
    força bruta de token). Só redes ATIVAS com painel habilitado."""
    # Todo token real é token_urlsafe (ASCII). Rejeita não-ASCII ANTES de comparar:
    # secrets.compare_digest levanta TypeError com não-ASCII — e o endpoint é sem
    # login, então isso viraria um 500 disparável por qualquer anônimo (deve ser 404).
    if not token or not token.isascii():
        return None
    candidatas = db.execute(
        select(Rede).where(Rede.token_publico.isnot(None), Rede.status == "ativa")
    ).scalars().all()
    for rede in candidatas:
        if secrets.compare_digest(str(rede.token_publico), token):
            return rede
    return None


def definir_painel_publico(db: Session, rede_id: int, ativo: bool) -> str | None:
    """Liga (gera token novo) ou desliga (limpa o token) a vitrine pública da
    rede. Devolve o token atual (ou None se desligado)."""
    rede = db.get(Rede, rede_id)
    if rede is None:
        return None
    rede.token_publico = secrets.token_urlsafe(9) if ativo else None
    return rede.token_publico
