"""Gamificação (PRD §64, §79–§84): conquistas, XP/níveis, sequência e destaques.

Nada é armazenado: tudo é derivado dos snapshots imutáveis e recalculado a
cada consulta — assim uma correção de dados nunca deixa medalha órfã.
As regras (XP por indicador, limiares de conquistas) vivem na tabela
`configuracoes` e são editáveis por escola, como todo o resto do sistema.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Aluno,
    Escola,
    Importacao,
    Matricula,
    Nota,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.services import evolucao, scoring

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


def listar_conquistas(db: Session, escola_id: int,
                      incluir_inativas: bool = False) -> list[dict]:
    """Definições da escola (ou o padrão), normalizadas e ordenadas."""
    brutas = scoring.obter_config(db, escola_id, "gamificacao.conquistas",
                                  "lista", CONQUISTAS_PADRAO)
    normalizadas = [_normalizar_conquista(regra, indice)
                    for indice, regra in enumerate(brutas)]
    normalizadas.sort(key=lambda c: (c["ordem"], c["nome"].casefold()))
    if incluir_inativas:
        return normalizadas
    return [c for c in normalizadas if c["ativa"]]


def _regras(db: Session, escola_id: int):
    xp = scoring.obter_config(db, escola_id, "gamificacao.xp", "valores", XP_PADRAO)
    base = scoring.obter_config(db, escola_id, "gamificacao.niveis", "base_xp", NIVEL_BASE_XP_PADRAO)
    conquistas = listar_conquistas(db, escola_id)
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


def gamificacao_do_aluno(db: Session, escola_id: int, aluno_id: int) -> dict:
    pesos_xp, base, conquistas_cfg = _regras(db, escola_id)
    serie_m = db.execute(
        select(SnapshotMatific).where(SnapshotMatific.aluno_id == aluno_id)
        .order_by(SnapshotMatific.id)
    ).scalars().all()
    serie_e = db.execute(
        select(SnapshotElefante).where(SnapshotElefante.aluno_id == aluno_id)
        .order_by(SnapshotElefante.id)
    ).scalars().all()
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

    # XP = indicadores (contínuo) + bônus das conquistas desbloqueadas
    xp = xp_do_aluno(snap_m, snap_e, pesos_xp) + xp_conquistas
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


def ranking_xp(db: Session, escola_id: int) -> list[dict]:
    escola = db.get(Escola, escola_id)
    if escola is None:
        return []
    pesos_xp, base, conquistas_cfg = _regras(db, escola_id)
    matific = scoring._snapshots_atuais(db, escola_id, SnapshotMatific)
    elefante = scoring._snapshots_atuais(db, escola_id, SnapshotElefante)

    matriculas = db.execute(
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .where(Matricula.escola_id == escola_id,
               Matricula.ano_letivo == escola.ano_letivo_ativo,
               Aluno.status == "ativo")
    ).all()

    itens = []
    for matricula, turma in matriculas:
        snap_m = matific.get(matricula.aluno_id)
        snap_e = elefante.get(matricula.aluno_id)
        desbloqueadas = [
            regra for regra in conquistas_cfg
            if _valor_indicador(snap_m, snap_e, regra["indicador"]) >= float(regra["limite"])
        ]
        xp = xp_do_aluno(snap_m, snap_e, pesos_xp) \
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
    definicoes = listar_conquistas(db, escola_id, incluir_inativas=True)

    matific = scoring._snapshots_atuais(db, escola_id, SnapshotMatific)
    elefante = scoring._snapshots_atuais(db, escola_id, SnapshotElefante)
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
                            for chave, info in INDICADORES.items()}}


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

def _destaque(db: Session, escola_id: int, dias: int) -> dict | None:
    itens = evolucao.ranking_evolucao(db, escola_id, dias=dias)
    melhor = itens[0] if itens else None
    if melhor is None or melhor.nota_evolucao <= 0:
        return None
    return {
        "aluno_id": melhor.aluno_id,
        "nome": melhor.nome,
        "turma": melhor.turma,
        "nota_evolucao": melhor.nota_evolucao,
        "ganhos": melhor.ganhos,
    }


def mural(db: Session, escola_id: int) -> dict:
    """Mural da escola: destaques do dia/semana/mês + eventos recentes."""
    eventos: list[dict] = []

    importacoes = db.execute(
        select(Importacao, Usuario.nome)
        .outerjoin(Usuario, Importacao.usuario_id == Usuario.id)
        .where(Importacao.escola_id == escola_id, Importacao.tipo != "manual")
        .order_by(Importacao.id.desc()).limit(5)
    ).all()
    for importacao, usuario_nome in importacoes:
        plataforma = "Matific" if importacao.plataforma == "matific" else "Elefante Letrado"
        eventos.append({
            "tipo": "importacao",
            "icone": "📥",
            "texto": f"Dados de {importacao.qtd_alunos} alunos atualizados na {plataforma}",
            "data": importacao.created_at,
        })

    # Conquistas recentes (últimos 30 dias) — derivadas, sem tabela própria
    corte = datetime.now(timezone.utc) - timedelta(days=30)
    for item in ranking_xp(db, escola_id):
        detalhe = gamificacao_do_aluno(db, escola_id, item["aluno_id"])
        for conquista in detalhe["conquistas"]:
            data = conquista["data"]
            if data is None:
                continue
            data_cmp = data.replace(tzinfo=timezone.utc) if data.tzinfo is None else data
            if data_cmp >= corte:
                eventos.append({
                    "tipo": "conquista",
                    "icone": conquista["icone"],
                    "texto": f"{item['nome']} desbloqueou “{conquista['nome']}”",
                    "data": data,
                })

    eventos.sort(key=lambda evento: str(evento["data"]), reverse=True)
    return {
        "destaques": {
            "dia": _destaque(db, escola_id, 1),
            "semana": _destaque(db, escola_id, 7),
            "mes": _destaque(db, escola_id, 30),
        },
        "eventos": eventos[:20],
    }
