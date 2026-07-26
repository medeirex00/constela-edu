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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Aluno, Escola, Matricula, Nota, Rede, Turma

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


def _kpis_da_rede(db: Session, rede_id: int) -> list[dict]:
    """Cartão resumido de CADA escola da rede (contagens + médias do ano letivo
    ativo da própria escola), em 3 consultas agregadas. ``adocao`` = % de alunos
    ativos com nota (proxy de engajamento). Escolas sem dados entram com zeros."""
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
        cartoes.append({
            "escola_id": escola.id, "nome": escola.nome, "cidade": escola.cidade,
            "status": escola.status,
            "latitude": escola.latitude, "longitude": escola.longitude,
            "total_turmas": int(turmas.get(escola.id, 0)),
            "total_alunos": total_alunos,
            "alunos_com_dados": com_nota,
            "adocao": adocao,
            "media_geral": media_geral, "media_matific": val(3), "media_elefante": val(4),
            "precisa_atencao": motivo is not None,
            "motivo_atencao": motivo,
        })
    return cartoes


def dashboard_rede(db: Session, rede_id: int) -> dict:
    """Painel municipal: totais da rede + cartão de cada escola (para cards e o
    mapa), ordenado por média geral e já numerado (``posicao``). Inclui um resumo
    de EQUIDADE (dispersão entre escolas) e a lista de escolas em ATENÇÃO."""
    cartoes = _kpis_da_rede(db, rede_id)

    total_alunos = sum(c["total_alunos"] for c in cartoes)
    total_turmas = sum(c["total_turmas"] for c in cartoes)
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

    return {
        "rede_id": rede_id,
        "totais": {
            "escolas": len(cartoes),
            "escolas_ativas": sum(1 for c in cartoes if c["status"] == "ativa"),
            "alunos": total_alunos,
            "turmas": total_turmas,
            "alunos_com_dados": com_dados,
            "adocao": round(com_dados / total_alunos * 100, 1) if total_alunos else 0.0,
            "media_geral": media_rede,
            "media_matific": _ponderada("media_matific"),
            "media_elefante": _ponderada("media_elefante"),
            "escolas_em_atencao": sum(1 for c in cartoes if c["precisa_atencao"]),
        },
        "equidade": equidade,
        "escolas": cartoes,
        # Atalho: só as escolas que precisam de atenção (a lista de ação da rede).
        "atencao": [c for c in cartoes if c["precisa_atencao"]],
    }


def ranking_escolas(db: Session, rede_id: int, limite: int = 50) -> list[dict]:
    """Ranking MUNICIPAL por escola (não expõe ranking individual de crianças
    entre escolas — decisão de privacidade). Ordena por média geral, desempata
    por adoção e nome; só escolas com dados entram."""
    cartoes = [c for c in _kpis_da_rede(db, rede_id) if c["alunos_com_dados"] > 0]
    cartoes.sort(key=lambda c: (-c["media_geral"], -c["adocao"], c["nome"].casefold()))
    for posicao, cartao in enumerate(cartoes[:limite], start=1):
        cartao["posicao"] = posicao
    return cartoes[:limite]


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
