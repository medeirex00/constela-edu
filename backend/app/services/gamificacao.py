"""Gamificação (PRD §64, §79–§84): conquistas, XP/níveis, sequência e destaques.

Nada é armazenado: tudo é derivado dos snapshots imutáveis e recalculado a
cada consulta — assim uma correção de dados nunca deixa medalha órfã.
As regras (XP por indicador, limiares de conquistas) vivem na tabela
`configuracoes` e são editáveis por escola, como todo o resto do sistema.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Aluno,
    Escola,
    Matricula,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import dificuldade_livro, elegibilidade, evolucao, matific_destaque, scoring

# Padrões usados até a escola personalizar (namespace gamificacao.*)
XP_PADRAO = {
    "atividades": 2.0,
    "estrelas": 1.0,
    "livros": 10.0,
    "acertos": 3.0,
    "tempo_leitura_min": 0.2,
}
NIVEL_BASE_XP_PADRAO = 100  # XP necessário por nível (linear)

# --------------------------------------------------------------------------
# Definições de conquistas — 100% configuráveis pelo painel administrativo
# (Configurações → Conquistas). O código abaixo é apenas o PADRÃO inicial;
# novas conquistas cadastradas pela escola são reconhecidas automaticamente.
# --------------------------------------------------------------------------

RARIDADES = ["comum", "rara", "epica", "lendaria"]
NOMES_RARIDADE = {"comum": "Comum", "rara": "Rara",
                  "epica": "Épica", "lendaria": "Lendária"}
XP_POR_RARIDADE = {"comum": 100, "rara": 250, "epica": 500, "lendaria": 750}

# Indicadores que uma conquista pode medir. `criterio` gera a frase exibida
# na Biblioteca; `unidade` alimenta as barras de progresso.
INDICADORES = {
    "livros_unicos": {"rotulo": "Livros concluídos", "plataforma": "elefante",
                      "unidade": "livros", "criterio": "Concluir {n} livro(s) válido(s)"},
    "tempo_leitura_min": {"rotulo": "Tempo de leitura (min)", "plataforma": "elefante",
                          "unidade": "minutos", "criterio": "Acumular {n} minutos de leitura"},
    "questoes_acertos": {"rotulo": "Questões aprovadas", "plataforma": "elefante",
                         "unidade": "questões", "criterio": "Acertar {n} questões de compreensão"},
    "pct_acertos": {"rotulo": "% de acertos (mín. 20 questões)", "plataforma": "elefante",
                    "unidade": "%", "criterio": "Atingir {n}% de acertos com pelo menos 20 questões"},
    "atividades": {"rotulo": "Atividades finalizadas", "plataforma": "matific",
                   "unidade": "atividades", "criterio": "Finalizar {n} atividade(s) na Matific"},
    "estrelas": {"rotulo": "Estrelas", "plataforma": "matific",
                 "unidade": "estrelas", "criterio": "Acumular {n} estrelas na Matific"},
}

DATA_PADRAO_CONQUISTAS = "2026-07-06"

CONQUISTAS_PADRAO = [
    {"codigo": "primeira_leitura", "nome": "Primeira Leitura", "icone": "📖",
     "descricao": "Concluiu seu primeiro livro no Elefante Letrado.",
     "objetivo": "Dar o primeiro passo no hábito da leitura.",
     "indicador": "livros_unicos", "limite": 1, "xp": 50, "raridade": "comum"},
    {"codigo": "leitor_bronze", "nome": "Leitor Bronze", "icone": "🥉",
     "descricao": "Primeiros passos na leitura: 10 livros concluídos.",
     "objetivo": "Transformar a leitura em rotina.",
     "indicador": "livros_unicos", "limite": 10, "xp": 100, "raridade": "comum"},
    {"codigo": "leitor_prata", "nome": "Leitor Prata", "icone": "🥈",
     "descricao": "Leitura constante: 25 livros concluídos.",
     "objetivo": "Consolidar o hábito de ler toda semana.",
     "indicador": "livros_unicos", "limite": 25, "xp": 250, "raridade": "rara"},
    {"codigo": "leitor_ouro", "nome": "Leitor Ouro", "icone": "🥇",
     "descricao": "Grande leitor: 50 livros concluídos.",
     "objetivo": "Alcançar a elite de leitores da escola.",
     "indicador": "livros_unicos", "limite": 50, "xp": 500, "raridade": "epica"},
    {"codigo": "maratonista", "nome": "Maratonista da Leitura", "icone": "⏱️",
     "descricao": "Acumulou 10 horas de leitura na plataforma.",
     "objetivo": "Valorizar o tempo dedicado à leitura, não só a quantidade.",
     "indicador": "tempo_leitura_min", "limite": 600, "xp": 300, "raridade": "rara"},
    {"codigo": "craque_questoes", "nome": "Craque das Questões", "icone": "🎯",
     "descricao": "80% de acertos nas questões, com pelo menos 20 respondidas.",
     "objetivo": "Premiar a compreensão do que foi lido, não só o volume.",
     "indicador": "pct_acertos", "limite": 80, "xp": 400, "raridade": "epica"},
    {"codigo": "primeiro_desafio", "nome": "Primeiro Desafio", "icone": "🧩",
     "descricao": "Finalizou sua primeira atividade na Matific.",
     "objetivo": "Dar o primeiro passo na matemática.",
     "indicador": "atividades", "limite": 1, "xp": 50, "raridade": "comum"},
    {"codigo": "matematico_bronze", "nome": "Matemático Bronze", "icone": "🧮",
     "descricao": "25 atividades de matemática finalizadas.",
     "objetivo": "Praticar matemática com regularidade.",
     "indicador": "atividades", "limite": 25, "xp": 100, "raridade": "comum"},
    {"codigo": "matematico_prata", "nome": "Matemático Prata", "icone": "✖️",
     "descricao": "75 atividades de matemática finalizadas.",
     "objetivo": "Manter o ritmo de estudos ao longo dos meses.",
     "indicador": "atividades", "limite": 75, "xp": 250, "raridade": "rara"},
    {"codigo": "matematico_ouro", "nome": "Matemático Ouro", "icone": "🏆",
     "descricao": "150 atividades de matemática finalizadas.",
     "objetivo": "Alcançar a elite matemática da escola.",
     "indicador": "atividades", "limite": 150, "xp": 500, "raridade": "epica"},
    {"codigo": "chuva_estrelas", "nome": "Chuva de Estrelas", "icone": "⭐",
     "descricao": "500 estrelas acumuladas na Matific.",
     "objetivo": "Recompensar o capricho: estrelas vêm de atividades bem-feitas.",
     "indicador": "estrelas", "limite": 500, "xp": 250, "raridade": "rara"},
    {"codigo": "constelacao", "nome": "Constelação", "icone": "🌌",
     "descricao": "1500 estrelas acumuladas — uma constelação inteira.",
     "objetivo": "A maior honraria da Matific no Constela Edu.",
     "indicador": "estrelas", "limite": 1500, "xp": 750, "raridade": "lendaria"},
]

MINIMO_TENTATIVAS_PCT = 20  # pct_acertos só vale com volume mínimo de questões


def _normalizar_conquista(regra: dict, indice: int) -> dict:
    """Completa campos ausentes — configurações antigas continuam válidas."""
    indicador = regra.get("indicador") if regra.get("indicador") in INDICADORES \
        else "livros_unicos"
    info = INDICADORES[indicador]
    raridade = regra.get("raridade") if regra.get("raridade") in RARIDADES else "comum"
    limite = float(regra.get("limite", 1) or 1)
    limite = limite if limite == int(limite) else round(limite, 1)
    return {
        "codigo": str(regra.get("codigo") or f"conquista_{indice + 1}"),
        "nome": str(regra.get("nome") or "Conquista"),
        "icone": str(regra.get("icone") or "🏅"),
        "descricao": str(regra.get("descricao") or ""),
        "objetivo": str(regra.get("objetivo") or ""),
        "indicador": indicador,
        "limite": limite,
        "plataforma": regra.get("plataforma") or info["plataforma"],
        "xp": int(regra.get("xp", XP_POR_RARIDADE[raridade])),
        "raridade": raridade,
        "ordem": int(regra.get("ordem", indice)),
        "ativa": bool(regra.get("ativa", True)),
        "criada_em": str(regra.get("criada_em") or DATA_PADRAO_CONQUISTAS),
        "unidade": info["unidade"],
        "criterio": info["criterio"].format(
            n=int(limite) if limite == int(limite) else limite),
    }


def plataformas_fora_do_plano(db: Session, escola: Escola | None) -> set[str]:
    """Plataformas de módulo que a rede da escola NÃO contratou — a MESMA régua do
    motor (``scoring.plataformas_fora_do_contrato``): o XP e as conquistas saem
    dos mesmos dados que a nota. Vazio para escola sem rede (tudo contratado)."""
    return scoring.plataformas_fora_do_contrato(db, escola)


def plataforma_da_conquista(conquista: dict) -> set[str]:
    """Plataformas de que uma conquista depende: a do critério (o indicador) e a
    gravada, quando é uma plataforma (``geral`` não é). Uma conquista "geral" que
    mede atividades continua sendo do Matific."""
    return {INDICADORES[conquista["indicador"]]["plataforma"],
            conquista.get("plataforma")} & {"elefante", "matific"}


def listar_conquistas(db: Session, escola_id: int,
                      incluir_inativas: bool = False, *,
                      plataformas_fora: set[str] | frozenset[str] = frozenset()
                      ) -> list[dict]:
    """Definições da escola (ou o padrão), normalizadas e ordenadas.

    ``plataformas_fora``: as conquistas que dependem de plataforma de módulo fora
    do plano somem (não pontuam, não aparecem, não celebram). A configuração
    gravada não muda — religar o módulo as traz de volta. Vazio (padrão) = a lista
    inteira, como a tela de configuração precisa para não perder nenhuma."""
    brutas = scoring.obter_config(db, escola_id, "gamificacao.conquistas",
                                  "lista", CONQUISTAS_PADRAO)
    normalizadas = [_normalizar_conquista(regra, indice)
                    for indice, regra in enumerate(brutas)]
    normalizadas.sort(key=lambda c: (c["ordem"], c["nome"].casefold()))
    if plataformas_fora:
        normalizadas = [c for c in normalizadas
                        if not plataforma_da_conquista(c) & set(plataformas_fora)]
    if incluir_inativas:
        return normalizadas
    return [c for c in normalizadas if c["ativa"]]


def _regras(db: Session, escola_id: int,
            plataformas_fora: set[str] | frozenset[str] = frozenset()):
    xp = scoring.obter_config(db, escola_id, "gamificacao.xp", "valores", XP_PADRAO)
    base = scoring.obter_config(db, escola_id, "gamificacao.niveis", "base_xp", NIVEL_BASE_XP_PADRAO)
    conquistas = listar_conquistas(db, escola_id, plataformas_fora=plataformas_fora)
    return xp, float(base), conquistas


def _valor_indicador(snap_m, snap_e, indicador: str) -> float:
    if indicador == "atividades":
        return float(snap_m.atividades) if snap_m else 0.0
    if indicador == "estrelas":
        return float(snap_m.estrelas) if snap_m else 0.0
    if indicador == "livros_unicos":
        return float(snap_e.livros_unicos) if snap_e else 0.0
    if indicador == "tempo_leitura_min":
        return float(snap_e.tempo_leitura_min) if snap_e else 0.0
    if indicador == "questoes_acertos":
        return float(snap_e.questoes_acertos) if snap_e else 0.0
    if indicador == "pct_acertos":
        if not snap_e or snap_e.questoes_tentativas < MINIMO_TENTATIVAS_PCT:
            return 0.0
        return round(snap_e.questoes_acertos / snap_e.questoes_tentativas * 100, 1)
    return 0.0


def _primeira_conquista(serie_m: list, serie_e: list, indicador: str, limite: float):
    """Data do primeiro snapshot em que o limiar foi atingido (auditável)."""
    if indicador in ("atividades", "estrelas"):
        serie = serie_m
    else:
        serie = serie_e
    ultimo_m, ultimo_e = None, None
    for snap in serie:
        if indicador in ("atividades", "estrelas"):
            ultimo_m = snap
        else:
            ultimo_e = snap
        if _valor_indicador(ultimo_m, ultimo_e, indicador) >= limite:
            return snap.data_referencia
    return None


def _matific_do_ano(serie_m: list, ano_letivo: int | None):
    """Último retrato do Matific DENTRO do ano letivo — o contador que vale para o
    XP dos indicadores (atividades e estrelas).

    MATIFIC É CONTADOR DO ANO (``scoring.snapshots_matific_do_ano``, a regra do
    motor, do dashboard e do telão): o acumulado de dezembro do ano anterior não
    é XP do ano novo. ``serie_m`` vem em ordem cronológica. ``ano_letivo=None`` =
    sem recorte (o último retrato da série)."""
    if ano_letivo is None:
        return serie_m[-1] if serie_m else None
    inicio, fim = matific_destaque.janela_ano_letivo(ano_letivo)
    do_ano = None
    for snap in serie_m:
        if inicio <= evolucao._sem_fuso(snap.data_referencia) <= fim:
            do_ano = snap
    return do_ano


def xp_do_aluno(snap_m, snap_e, pesos_xp: dict) -> int:
    total = 0.0
    if snap_m:
        total += snap_m.atividades * float(pesos_xp.get("atividades", 0))
        total += snap_m.estrelas * float(pesos_xp.get("estrelas", 0))
    if snap_e:
        total += snap_e.livros_unicos * float(pesos_xp.get("livros", 0))
        total += snap_e.questoes_acertos * float(pesos_xp.get("acertos", 0))
        total += snap_e.tempo_leitura_min * float(pesos_xp.get("tempo_leitura_min", 0))
    return int(total)


def nivel_do_xp(xp: int, base: float) -> tuple[int, int]:
    """(nível atual, XP restante para o próximo). Nível 1 começa em 0 XP."""
    if base <= 0:
        return 1, 0
    nivel = int(xp // base) + 1
    faltam = int(nivel * base - xp)
    return nivel, faltam


def sequencia_semanas(serie_m: list, serie_e: list) -> int:
    """Semanas ISO consecutivas (terminando na mais recente com dado) em que
    o aluno registrou algum ganho em qualquer plataforma."""
    semanas: set[tuple[int, int]] = set()
    for serie, campos in ((serie_m, ("atividades", "estrelas")),
                          (serie_e, ("livros_unicos", "questoes_acertos", "tempo_leitura_min"))):
        anterior = None
        for snap in serie:
            ganhou = any(
                float(getattr(snap, campo, 0) or 0) > float(getattr(anterior, campo, 0) or 0)
                for campo in campos
            ) if anterior else any(float(getattr(snap, campo, 0) or 0) > 0 for campo in campos)
            if ganhou:
                iso = snap.data_referencia.isocalendar()
                semanas.add((iso[0], iso[1]))
            anterior = snap
    if not semanas:
        return 0
    atual = max(semanas)
    sequencia = 0
    ano, semana = atual
    while (ano, semana) in semanas:
        sequencia += 1
        # Semana anterior no calendário ISO
        segunda = date.fromisocalendar(ano, semana, 1) - timedelta(weeks=1)
        iso = segunda.isocalendar()
        ano, semana = iso[0], iso[1]
    return sequencia


def _computar_gamificacao(aluno_id: int, serie_m: list, serie_e: list,
                          pesos_xp: dict, base: float, conquistas_cfg: list,
                          ano_letivo: int | None = None) -> dict:
    """Núcleo do cálculo a partir de séries JÁ carregadas — sem tocar o banco.
    Permite processar a escola inteira (mural, ranking) sem N+1.

    ``ano_letivo``: o XP dos indicadores do Matific usa o contador DESSE ano
    (:func:`_matific_do_ano`). As conquistas seguem avaliadas sobre o último
    retrato — se as de matemática valem por ano ou pela vida toda é decisão de
    produto ainda aberta, e este recorte não a toma."""
    snap_m = serie_m[-1] if serie_m else None
    snap_e = serie_e[-1] if serie_e else None

    conquistas = []
    xp_conquistas = 0
    for regra in conquistas_cfg:
        valor = _valor_indicador(snap_m, snap_e, regra["indicador"])
        limite = float(regra["limite"])
        atingida = valor >= limite
        if atingida:
            xp_conquistas += regra["xp"]
        pct = min(100.0, round(valor / limite * 100, 1)) if limite > 0 else 100.0
        conquistas.append({
            **regra,
            "progresso": valor,
            "pct": pct,
            "faltam": max(0.0, round(limite - valor, 1)),
            "atingida": atingida,
            "data": _primeira_conquista(serie_m, serie_e, regra["indicador"], limite)
            if atingida else None,
        })

    # XP = indicadores (contínuo) + bônus das conquistas desbloqueadas. O
    # indicador do Matific é o contador DO ANO letivo: sem retrato no ano, ele
    # não soma XP (antes o acumulado do ano anterior virava XP do ano novo).
    xp = xp_do_aluno(_matific_do_ano(serie_m, ano_letivo), snap_e, pesos_xp) + xp_conquistas
    nivel, faltam = nivel_do_xp(xp, base)

    return {
        "aluno_id": aluno_id,
        "xp": xp,
        "xp_conquistas": xp_conquistas,
        "nivel": nivel,
        "xp_para_proximo": faltam,
        "sequencia_semanas": sequencia_semanas(serie_m, serie_e),
        "conquistas": conquistas,
        "total_conquistas": sum(1 for c in conquistas if c["atingida"]),
    }


def gamificacao_do_aluno(db: Session, escola_id: int, aluno_id: int) -> dict:
    escola = db.get(Escola, escola_id)
    # CONTRATO: plataforma de módulo fora do plano não dá XP, não conta semana de
    # sequência nem desbloqueia conquista — a série dela é tratada como vazia.
    fora = plataformas_fora_do_plano(db, escola)
    pesos_xp, base, conquistas_cfg = _regras(db, escola_id, fora)

    # Ordem cronológica por data_referencia (id desempata): o backfill mensal
    # do Matific insere períodos antigos com id maior.
    def _serie(modelo, plataforma):
        if plataforma in fora:
            return []
        return db.execute(
            select(modelo).where(modelo.aluno_id == aluno_id)
            .order_by(modelo.data_referencia, modelo.id)
        ).scalars().all()

    serie_m = _serie(SnapshotMatific, "matific")
    serie_e = _serie(SnapshotElefante, "elefante")
    return _computar_gamificacao(aluno_id, serie_m, serie_e,
                                 pesos_xp, base, conquistas_cfg,
                                 ano_letivo=escola.ano_letivo_ativo if escola else None)


def ranking_xp(db: Session, escola_id: int) -> list[dict]:
    """Ranking de XP da escola, numerado 1..N entre quem CONCORRE.

    AS FASES NÃO CONCORREM (``services.elegibilidade``: ranking e premiação são
    do 1º ao 5º ano): só entram as turmas premiáveis do ano letivo — o mesmo
    corte do mural da página Conquistas, do Ranking de Evolução e do telão.
    Sem ele, a Educação Infantil aparecia no topo, com medalha, e empurrava as
    posições do Fundamental. O XP de cada criança não muda: é só quem aparece."""
    escola = db.get(Escola, escola_id)
    if escola is None:
        return []
    premiaveis = elegibilidade.turmas_premiaveis(db, escola_id, escola.ano_letivo_ativo)
    if not premiaveis:
        return []
    # CONTRATO: plataforma de módulo fora do plano não dá XP nem conquista.
    fora = plataformas_fora_do_plano(db, escola)
    pesos_xp, base, conquistas_cfg = _regras(db, escola_id, fora)
    # Conquistas: o último retrato (regra de hoje, à espera da decisão do dono).
    matific = ({} if "matific" in fora
               else scoring._snapshots_atuais(db, escola_id, SnapshotMatific))
    # XP dos indicadores do Matific: o contador DO ANO letivo (a regra do motor).
    matific_do_ano = ({} if "matific" in fora
                      else scoring.snapshots_matific_do_ano(db, escola_id,
                                                            escola.ano_letivo_ativo))
    elefante = ({} if "elefante" in fora
                else scoring._snapshots_atuais(db, escola_id, SnapshotElefante))

    matriculas = db.execute(
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .where(Matricula.escola_id == escola_id,
               Matricula.ano_letivo == escola.ano_letivo_ativo,
               Matricula.turma_id.in_(premiaveis),
               Aluno.status == "ativo")
        .options(selectinload(Matricula.aluno))  # evita N+1 em matricula.aluno
    ).all()

    itens = []
    for matricula, turma in matriculas:
        snap_m = matific.get(matricula.aluno_id)
        snap_e = elefante.get(matricula.aluno_id)
        desbloqueadas = [
            regra for regra in conquistas_cfg
            if _valor_indicador(snap_m, snap_e, regra["indicador"]) >= float(regra["limite"])
        ]
        xp = xp_do_aluno(matific_do_ano.get(matricula.aluno_id), snap_e, pesos_xp) \
            + sum(regra["xp"] for regra in desbloqueadas)
        nivel, _ = nivel_do_xp(xp, base)
        conquistas = len(desbloqueadas)
        itens.append({
            "aluno_id": matricula.aluno_id,
            "nome": matricula.aluno.nome,
            "turma": turma.nome,
            "xp": xp,
            "nivel": nivel,
            "conquistas": conquistas,
        })
    itens.sort(key=lambda item: (-item["xp"], item["nome"].casefold()))
    for posicao, item in enumerate(itens, start=1):
        item["posicao"] = posicao
    return itens


# ---------------------------------------------------------------------------
# Biblioteca de Conquistas: catálogo completo + estatísticas da escola
# ---------------------------------------------------------------------------

def biblioteca(db: Session, escola_id: int) -> dict:
    """Todas as conquistas (inclusive inativas e nunca desbloqueadas), com
    quantos alunos já desbloquearam cada uma e o painel de estatísticas."""
    escola = db.get(Escola, escola_id)
    # CONTRATO: as conquistas (e os indicadores do filtro) de módulo fora do
    # plano não existem para esta escola — nem com progresso 0.
    fora = plataformas_fora_do_plano(db, escola)
    definicoes = listar_conquistas(db, escola_id, incluir_inativas=True,
                                   plataformas_fora=fora)

    matific = ({} if "matific" in fora
               else scoring._snapshots_atuais(db, escola_id, SnapshotMatific))
    elefante = ({} if "elefante" in fora
                else scoring._snapshots_atuais(db, escola_id, SnapshotElefante))
    alunos_ids = [
        matricula.aluno_id
        for matricula in db.execute(
            select(Matricula)
            .join(Aluno, Matricula.aluno_id == Aluno.id)
            .where(Matricula.escola_id == escola_id,
                   Matricula.ano_letivo == (escola.ano_letivo_ativo if escola else 0),
                   Aluno.status == "ativo")
        ).scalars().all()
    ]

    conquistas = []
    for regra in definicoes:
        desbloqueios = sum(
            1 for aluno_id in alunos_ids
            if _valor_indicador(matific.get(aluno_id), elefante.get(aluno_id),
                                regra["indicador"]) >= float(regra["limite"])
        )
        pct = round(desbloqueios / len(alunos_ids) * 100, 1) if alunos_ids else 0.0
        conquistas.append({**regra, "desbloqueios": desbloqueios,
                           "pct_desbloqueio": pct})

    ativas = [c for c in conquistas if c["ativa"]]
    def _resumo(conquista):
        return {"codigo": conquista["codigo"], "nome": conquista["nome"],
                "icone": conquista["icone"], "xp": conquista["xp"],
                "desbloqueios": conquista["desbloqueios"],
                "pct_desbloqueio": conquista["pct_desbloqueio"]}

    estatisticas = {
        "total": len(conquistas),
        "ativas": len(ativas),
        "alunos": len(alunos_ids),
        "total_desbloqueios": sum(c["desbloqueios"] for c in ativas),
        "pct_medio_conclusao": round(
            sum(c["pct_desbloqueio"] for c in ativas) / len(ativas), 1
        ) if ativas else 0.0,
        "mais_rara": _resumo(min(
            ativas, key=lambda c: (c["pct_desbloqueio"], -c["xp"]))) if ativas else None,
        "mais_comum": _resumo(max(
            ativas, key=lambda c: (c["pct_desbloqueio"], c["xp"]))) if ativas else None,
        "maior_xp": _resumo(max(ativas, key=lambda c: c["xp"])) if ativas else None,
        "ranking_desbloqueios": [
            _resumo(c) for c in sorted(
                ativas, key=lambda c: -c["desbloqueios"])[:5]
            if c["desbloqueios"] > 0
        ],
    }
    return {"conquistas": conquistas, "estatisticas": estatisticas,
            "raridades": NOMES_RARIDADE,
            "indicadores": {chave: info["rotulo"]
                            for chave, info in INDICADORES.items()
                            if info["plataforma"] not in fora}}


def gerar_codigo(nome: str, existentes: set[str]) -> str:
    """Slug estável a partir do nome — identidade da conquista nos logs."""
    import re
    import unicodedata

    plano = "".join(c for c in unicodedata.normalize("NFD", nome)
                    if unicodedata.category(c) != "Mn").casefold()
    base = re.sub(r"[^a-z0-9]+", "_", plano).strip("_") or "conquista"
    codigo, sufixo = base, 2
    while codigo in existentes:
        codigo = f"{base}_{sufixo}"
        sufixo += 1
    return codigo


# ---------------------------------------------------------------------------
# Destaques e mural (PRD §64, §83)
# ---------------------------------------------------------------------------

def _melhor_do_ranking(itens) -> dict | None:
    melhor = itens[0] if itens else None
    if melhor is None or melhor.nota_evolucao <= 0:
        return None
    return {
        "aluno_id": melhor.aluno_id, "nome": melhor.nome, "turma": melhor.turma,
        "nota_evolucao": melhor.nota_evolucao, "ganhos": melhor.ganhos,
    }


def anonimizar_nome(nome: str | None) -> str:
    """Nome reduzido para telas PÚBLICAS (sem login): primeiro nome + inicial do
    primeiro sobrenome — ex.: "Ana Beatriz Souza" -> "Ana B.".

    Um telão numa rede municipal não deve expor o nome COMPLETO de uma criança
    (LGPD/ECA, melhor interesse do menor); o primeiro nome + inicial ainda deixa
    a criança se reconhecer no ranking, mas não a identifica publicamente.
    """
    if not nome:
        return nome or ""
    partes = nome.split()
    if len(partes) == 1:
        return partes[0]
    return f"{partes[0]} {partes[1][0]}."


def mural(db: Session, escola_id: int,
          serie_m: dict | None = None, serie_e: dict | None = None,
          mapa_dif: dict | None = None, anonimizar: bool = False,
          base_no_periodo: bool = True,
          turma_ids: list[int] | None = None) -> dict:
    """Mural da escola: destaques do dia/semana/mês + eventos recentes.

    ``base_no_periodo`` (padrão ``True``, a régua JUSTA): o destaque é quem mais
    cresceu DENTRO da janela — sem retrato anterior a ela, o acumulado de vida
    da criança não conta como evolução. É a régua do Ranking de Evolução, do app
    e do telão; com ``False`` (a régua antiga), quem tinha o 1º retrato dentro
    do mês virava "Aluno do Mês" com o acumulado do ano inteiro.

    ``anonimizar=True`` (uso no painel PÚBLICO sem login) reduz o nome do aluno
    nos destaques e nos eventos a "primeiro nome + inicial" — ver
    :func:`anonimizar_nome`.

    ``turma_ids`` (opcional) só RECORTA quem pode ser nomeado: os eventos e os
    destaques ficam restritos a crianças matriculadas nessas turmas. O painel
    PÚBLICO passa as turmas que concorrem (as Fases da Educação Infantil não
    disputam o "Aluno do Dia/Semana/Mês"). A régua da evolução continua a da
    escola inteira (`evolucao.ranking_evolucao`), então a nota exibida não muda.
    ``None`` (padrão) = sem recorte — os demais chamadores seguem idênticos.

    Trabalha em LOTE: todos os snapshots da escola são carregados em 2
    consultas e a gamificação de cada aluno é computada em memória — antes
    isto disparava ~2 queries por aluno (milhares numa escola grande).
    """
    # O mural do telão mostra SÓ conquistas de alunos (decisão de produto): os
    # avisos de "dados atualizados na Matific/Elefante" (importação) foram
    # removidos para o painel ficar 100% celebrativo, sem ruído operacional.
    eventos: list[dict] = []

    # Séries de TODOS os alunos em 2 queries + regras uma única vez. As mesmas
    # séries + o mapa de dificuldade alimentam as 3 janelas do ranking abaixo
    # (dia/semana/mês), evitando que cada janela reexecute essas varreduras.
    escola = db.get(Escola, escola_id)
    # CONTRATO: plataforma de módulo fora do plano não celebra nada no mural
    # (web, app e telão sem login) — a série dela é tratada como vazia, e as
    # conquistas dela nem entram nas regras.
    fora = plataformas_fora_do_plano(db, escola)
    pesos_xp, base, conquistas_cfg = _regras(db, escola_id, fora)
    # Reusa as varreduras injetadas (ex.: /sincronizacao mobile) ou carrega.
    if "matific" in fora:
        series_m = {}
    else:
        series_m = serie_m if serie_m is not None else evolucao._series_por_aluno(db, escola_id, SnapshotMatific)
    if "elefante" in fora:
        series_e = {}
    else:
        series_e = serie_e if serie_e is not None else evolucao._series_por_aluno(db, escola_id, SnapshotElefante)
    if mapa_dif is None:   # a REGRA de dificuldade (fonte única)
        mapa_dif = dificuldade_livro.regra_da_escola(db, escola_id)
    # COORTE do mural = a MESMA de todas as outras superfícies: aluno ATIVO e
    # MATRICULADO no ano letivo corrente (o JOIN de `publico._consulta_ranking`).
    #
    # As séries de snapshot cobrem a escola inteira e NÃO são apagadas quando
    # alguém é arquivado, excluído ou perde a matrícula — e este `nomes` não
    # filtrava nada. Uma criança fora da escola cuja conquista caiu nos últimos
    # 30 dias voltava NOMEADA ao mural, inclusive no telão PÚBLICO sem login,
    # no elemento de texto mais explícito da tela ("Fulano desbloqueou ...").
    # Era a única superfície que o A1 (`test_publico.py::test_a1_aluno_
    # arquivado_some_de_todas_as_superficies`) não cobria.
    #
    # O filtro é ESTRITAMENTE RESTRITIVO: ninguém passa a aparecer no mural,
    # apenas deixam de aparecer os que já não deviam. Nenhuma regra de exposição
    # do telão muda (slides, anonimização e top-N seguem idênticos).
    ano = escola.ano_letivo_ativo if escola is not None else 0
    consulta_nomes = (
        select(Aluno.id, Aluno.nome)
        .join(Matricula, (Matricula.aluno_id == Aluno.id)
              & (Matricula.ano_letivo == ano))
        .where(Aluno.escola_id == escola_id, Aluno.status == "ativo")
    )
    if turma_ids is not None:
        # Recorte opcional (ver docstring): também ESTRITAMENTE RESTRITIVO.
        consulta_nomes = consulta_nomes.where(Matricula.turma_id.in_(turma_ids))
    nomes = dict(db.execute(consulta_nomes).all())

    corte = datetime.now(timezone.utc) - timedelta(days=30)
    # `& nomes`: só quem está na coorte acima. Sem isto, o dono do snapshot
    # entrava no laço e era nomeado com o fallback "Aluno".
    for aluno_id in (set(series_m) | set(series_e)) & set(nomes):
        detalhe = _computar_gamificacao(
            aluno_id, series_m.get(aluno_id, []), series_e.get(aluno_id, []),
            pesos_xp, base, conquistas_cfg,
            ano_letivo=escola.ano_letivo_ativo if escola is not None else None)
        for conquista in detalhe["conquistas"]:
            data = conquista["data"]
            if data is None:
                continue
            data_cmp = data.replace(tzinfo=timezone.utc) if data.tzinfo is None else data
            if data_cmp >= corte:
                nome_evt = nomes.get(aluno_id, "Aluno")
                if anonimizar:
                    nome_evt = anonimizar_nome(nome_evt)
                eventos.append({
                    "tipo": "conquista",
                    "icone": conquista["icone"],
                    "texto": f"{nome_evt} desbloqueou “{conquista['nome']}”",
                    "data": data,
                })

    eventos.sort(key=lambda evento: str(evento["data"]), reverse=True)

    # ranking_evolucao é caro: cada janela reusa as séries + mapa de dificuldade
    # já carregados (só a leitura por período varia entre as janelas).
    def _destaque(dias: int):
        melhor = _melhor_do_ranking(evolucao.ranking_evolucao(
            db, escola_id, dias=dias,
            serie_m=series_m, serie_e=series_e, mapa_dif=mapa_dif,
            base_no_periodo=base_no_periodo, turma_ids=turma_ids))
        if melhor and anonimizar:
            # k-anonimato no PÓDIO: além do nome reduzido, a TURMA também some —
            # "Ana B." + turma + destaque reidentificaria a criança no elemento
            # MAIS visível do telão (o "Aluno do Dia/Semana/Mês"), que é público.
            melhor = {**melhor, "nome": anonimizar_nome(melhor["nome"]), "turma": None}
        return melhor

    return {
        "destaques": {
            "dia": _destaque(1),
            "semana": _destaque(7),
            "mes": _destaque(30),
        },
        "eventos": eventos[:20],
    }
