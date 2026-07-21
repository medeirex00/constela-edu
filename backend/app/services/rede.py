"""Agregação por REDE / Secretaria de Educação (o tier acima da escola).

Roda SOBRE os dados por escola já existentes — não reimplementa scoring nem toca
em pesos/fórmulas (essas vivem no motor de pontuação, congelado). Cada indicador
municipal é uma soma/média dos indicadores por escola. O isolamento continua por
escola; aqui só se AGREGAM as escolas que pertencem à rede.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Aluno, Escola, Matricula, Nota, Turma


def escolas_da_rede(db: Session, rede_id: int) -> list[Escola]:
    return list(db.execute(
        select(Escola).where(Escola.rede_id == rede_id).order_by(Escola.nome)
    ).scalars().all())


def _kpi_escola(db: Session, escola: Escola) -> dict:
    """Cartão resumido de UMA escola: contagens + médias do ano letivo ativo.

    `participacao` = % de alunos ativos que já têm nota (proxy de engajamento:
    quem tem dado de plataforma consolidado). Tudo derivado das mesmas tabelas
    que o dashboard da escola usa — nenhuma métrica nova é inventada aqui.
    """
    ano = escola.ano_letivo_ativo
    total_turmas = db.scalar(
        select(func.count(Turma.id)).where(
            Turma.escola_id == escola.id,
            Turma.ano_letivo == ano,
            Turma.status == "ativa",
        )
    ) or 0
    total_alunos = db.scalar(
        select(func.count(func.distinct(Matricula.aluno_id)))
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .where(Matricula.escola_id == escola.id,
               Matricula.ano_letivo == ano,
               Aluno.status == "ativo")
    ) or 0
    notas = db.execute(
        select(Nota.nota_geral, Nota.nota_matific, Nota.nota_elefante)
        .join(Aluno, Aluno.id == Nota.aluno_id)
        .where(Nota.escola_id == escola.id,
               Nota.ano_letivo == ano,
               Aluno.status == "ativo")
    ).all()
    com_nota = len(notas)
    media = (lambda i: round(sum(x[i] for x in notas) / com_nota, 1)) if com_nota else (lambda i: 0.0)
    return {
        "escola_id": escola.id,
        "nome": escola.nome,
        "cidade": escola.cidade,
        "status": escola.status,
        "latitude": escola.latitude,
        "longitude": escola.longitude,
        "total_turmas": int(total_turmas),
        "total_alunos": int(total_alunos),
        "alunos_com_dados": com_nota,
        "participacao": round(com_nota / total_alunos * 100, 1) if total_alunos else 0.0,
        "media_geral": media(0),
        "media_matific": media(1),
        "media_elefante": media(2),
    }


def dashboard_rede(db: Session, rede_id: int) -> dict:
    """Painel municipal: totais da rede + cartão de cada escola (para cards e
    para o mapa). Ordena as escolas por média geral (desc)."""
    escolas = escolas_da_rede(db, rede_id)
    cartoes = [_kpi_escola(db, escola) for escola in escolas]

    total_escolas = len(cartoes)
    total_alunos = sum(c["total_alunos"] for c in cartoes)
    total_turmas = sum(c["total_turmas"] for c in cartoes)
    com_dados = sum(c["alunos_com_dados"] for c in cartoes)
    # Média da rede PONDERADA por alunos-com-nota (não média de médias, que daria
    # peso igual a uma escola de 10 e uma de 500 alunos).
    def _ponderada(chave: str) -> float:
        peso = sum(c["alunos_com_dados"] for c in cartoes)
        if not peso:
            return 0.0
        return round(sum(c[chave] * c["alunos_com_dados"] for c in cartoes) / peso, 1)

    cartoes.sort(key=lambda c: (-c["media_geral"], c["nome"].casefold()))
    return {
        "rede_id": rede_id,
        "totais": {
            "escolas": total_escolas,
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
    por participação e nome."""
    cartoes = [c for c in (_kpi_escola(db, e) for e in escolas_da_rede(db, rede_id))
               if c["alunos_com_dados"] > 0]
    cartoes.sort(key=lambda c: (-c["media_geral"], -c["participacao"], c["nome"].casefold()))
    for posicao, cartao in enumerate(cartoes[:limite], start=1):
        cartao["posicao"] = posicao
    return cartoes[:limite]
