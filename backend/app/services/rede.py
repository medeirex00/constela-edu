"""Agregação por REDE / Secretaria de Educação (o tier acima da escola).

Roda SOBRE os dados por escola já existentes — não reimplementa scoring nem toca
em pesos/fórmulas (essas vivem no motor de pontuação, congelado). Cada indicador
municipal é uma soma/média dos indicadores por escola. O isolamento continua por
escola; aqui só se AGREGAM as escolas que pertencem à rede.

Desempenho: os KPIs de TODAS as escolas da rede saem em **3 consultas agregadas**
(GROUP BY escola_id), não em N×3 (uma rede municipal grande pode ter centenas de
escolas). O filtro de ano correlaciona a coluna por-escola `Escola.ano_letivo_ativo`
(cada escola tem o seu), nunca uma constante.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Aluno, Escola, Matricula, Nota, Turma


def escolas_da_rede(db: Session, rede_id: int) -> list[Escola]:
    return list(db.execute(
        select(Escola).where(Escola.rede_id == rede_id).order_by(Escola.nome)
    ).scalars().all())


def _kpis_da_rede(db: Session, rede_id: int) -> list[dict]:
    """Cartão resumido de CADA escola da rede (contagens + médias do ano letivo
    ativo da própria escola), em 3 consultas agregadas. `participacao` = % de
    alunos ativos com nota (proxy de engajamento). Escolas sem turmas/alunos/notas
    entram com zeros (LEFT — reancorado na lista completa de escolas)."""
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

    # (3) contagem + médias das notas por escola (agregado no banco — não traz as
    #     linhas de Nota ao app). func.avg divide por não-NULL; o domínio não tem
    #     nota NULL, então é idêntico a sum/len e mais robusto.
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
        media = ((lambda i: round(float(agg[i]), 1)) if (agg and com_nota)
                 else (lambda i: 0.0))
        total_alunos = int(alunos.get(escola.id, 0))
        cartoes.append({
            "escola_id": escola.id, "nome": escola.nome, "cidade": escola.cidade,
            "status": escola.status, "latitude": escola.latitude, "longitude": escola.longitude,
            "total_turmas": int(turmas.get(escola.id, 0)), "total_alunos": total_alunos,
            "alunos_com_dados": com_nota,
            "participacao": round(com_nota / total_alunos * 100, 1) if total_alunos else 0.0,
            "media_geral": media(2), "media_matific": media(3), "media_elefante": media(4),
        })
    return cartoes


def dashboard_rede(db: Session, rede_id: int) -> dict:
    """Painel municipal: totais da rede + cartão de cada escola (para cards e para
    o mapa), ordenado por média geral (desc) e já numerado (`posicao`)."""
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
            "participacao": round(com_dados / total_alunos * 100, 1) if total_alunos else 0.0,
            "media_geral": _ponderada("media_geral"),
            "media_matific": _ponderada("media_matific"),
            "media_elefante": _ponderada("media_elefante"),
        },
        "escolas": cartoes,
    }


def ranking_escolas(db: Session, rede_id: int, limite: int = 50) -> list[dict]:
    """Ranking MUNICIPAL por escola (não expõe ranking individual de crianças
    entre escolas — decisão de privacidade). Ordena por média geral, desempata
    por participação e nome; só escolas com dados entram."""
    cartoes = [c for c in _kpis_da_rede(db, rede_id) if c["alunos_com_dados"] > 0]
    cartoes.sort(key=lambda c: (-c["media_geral"], -c["participacao"], c["nome"].casefold()))
    for posicao, cartao in enumerate(cartoes[:limite], start=1):
        cartao["posicao"] = posicao
    return cartoes[:limite]
