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

CONQUISTAS_PADRAO = [
    {"codigo": "primeira_leitura", "nome": "Primeira Leitura", "icone": "📖",
     "descricao": "Concluiu o primeiro livro", "indicador": "livros_unicos", "limite": 1},
    {"codigo": "leitor_bronze", "nome": "Leitor Bronze", "icone": "🥉",
     "descricao": "5 livros únicos concluídos", "indicador": "livros_unicos", "limite": 5},
    {"codigo": "leitor_prata", "nome": "Leitor Prata", "icone": "🥈",
     "descricao": "15 livros únicos concluídos", "indicador": "livros_unicos", "limite": 15},
    {"codigo": "leitor_ouro", "nome": "Leitor Ouro", "icone": "🥇",
     "descricao": "30 livros únicos concluídos", "indicador": "livros_unicos", "limite": 30},
    {"codigo": "matematico_bronze", "nome": "Matemático Bronze", "icone": "🧮",
     "descricao": "10 atividades finalizadas na Matific", "indicador": "atividades", "limite": 10},
    {"codigo": "matematico_prata", "nome": "Matemático Prata", "icone": "✖️",
     "descricao": "50 atividades finalizadas na Matific", "indicador": "atividades", "limite": 50},
    {"codigo": "matematico_ouro", "nome": "Matemático Ouro", "icone": "🏆",
     "descricao": "100 atividades finalizadas na Matific", "indicador": "atividades", "limite": 100},
    {"codigo": "chuva_estrelas", "nome": "Chuva de Estrelas", "icone": "⭐",
     "descricao": "200 estrelas acumuladas", "indicador": "estrelas", "limite": 200},
    {"codigo": "craque_questoes", "nome": "Craque das Questões", "icone": "🎯",
     "descricao": "80% de acertos com pelo menos 20 questões", "indicador": "pct_acertos", "limite": 80},
    {"codigo": "maratonista", "nome": "Maratonista da Leitura", "icone": "⏱️",
     "descricao": "300 minutos de leitura", "indicador": "tempo_leitura_min", "limite": 300},
]

MINIMO_TENTATIVAS_PCT = 20  # pct_acertos só vale com volume mínimo de questões


def _regras(db: Session, escola_id: int):
    xp = scoring.obter_config(db, escola_id, "gamificacao.xp", "valores", XP_PADRAO)
    base = scoring.obter_config(db, escola_id, "gamificacao.niveis", "base_xp", NIVEL_BASE_XP_PADRAO)
    conquistas = scoring.obter_config(db, escola_id, "gamificacao.conquistas", "lista", CONQUISTAS_PADRAO)
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

    xp = xp_do_aluno(snap_m, snap_e, pesos_xp)
    nivel, faltam = nivel_do_xp(xp, base)

    conquistas = []
    for regra in conquistas_cfg:
        valor = _valor_indicador(snap_m, snap_e, regra["indicador"])
        atingida = valor >= float(regra["limite"])
        conquistas.append({
            "codigo": regra["codigo"],
            "nome": regra["nome"],
            "icone": regra.get("icone", "🏅"),
            "descricao": regra["descricao"],
            "limite": regra["limite"],
            "progresso": valor,
            "atingida": atingida,
            "data": _primeira_conquista(serie_m, serie_e, regra["indicador"], float(regra["limite"]))
            if atingida else None,
        })

    return {
        "aluno_id": aluno_id,
        "xp": xp,
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
        xp = xp_do_aluno(snap_m, snap_e, pesos_xp)
        nivel, _ = nivel_do_xp(xp, base)
        conquistas = sum(
            1 for regra in conquistas_cfg
            if _valor_indicador(snap_m, snap_e, regra["indicador"]) >= float(regra["limite"])
        )
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
