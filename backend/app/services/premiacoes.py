"""Premiações por PERÍODO (PRD — premiações da escola).

Calcula os vencedores de cada categoria usando EXCLUSIVAMENTE os dados do
intervalo escolhido — leituras (com data real, Fase 1) e ganho no Matific
(comparação de snapshots dentro do período). Premiações justas: quem só
importou dados fora do intervalo não pontua.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Aluno, Escola, Leitura, Livro, Matricula, SnapshotMatific, Turma
from app.services import scoring
from app.services.evolucao import _delta, _janela, _series_por_aluno


def _podio(valores: dict[int, float], alunos: dict[int, dict], limite: int = 5) -> list[dict]:
    """Top N (só quem tem valor > 0), ordenado por valor e depois por nome
    (determinístico para desempatar de forma justa e estável)."""
    itens = [
        {"aluno_id": aid, "nome": alunos[aid]["nome"], "turma": alunos[aid]["turma"],
         "valor": round(float(valor), 2)}
        for aid, valor in valores.items()
        if aid in alunos and valor and valor > 0
    ]
    itens.sort(key=lambda x: (-x["valor"], x["nome"].casefold()))
    for posicao, item in enumerate(itens[:limite], start=1):
        item["posicao"] = posicao
    return itens[:limite]


def _alunos_ativos(db: Session, escola_id: int, ano: int,
                   turma_id: int | None,
                   turma_ids: list[int] | None = None) -> dict[int, dict]:
    consulta = (
        select(Aluno.id, Aluno.nome, Turma.nome)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Aluno.escola_id == escola_id, Aluno.status == "ativo",
               Matricula.ano_letivo == ano)
    )
    if turma_id:
        consulta = consulta.where(Turma.id == turma_id)
    if turma_ids is not None:  # professor: só as turmas designadas a ele
        consulta = consulta.where(Turma.id.in_(turma_ids))
    return {aid: {"nome": nome, "turma": turma}
            for aid, nome, turma in db.execute(consulta).all()}


def premiacoes(db: Session, escola_id: int, inicio: datetime | None,
               fim: datetime | None, turma_id: int | None = None,
               turma_ids: list[int] | None = None) -> dict:
    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo
    alunos = _alunos_ativos(db, escola_id, ano, turma_id, turma_ids)

    # --- Leitura no período (livros, pontos de dificuldade, tempo) ----------
    pontos_map = scoring.pontos_por_codigo(db, escola_id)
    livros: dict[int, float] = {}
    pontos: dict[int, float] = {}
    tempo: dict[int, float] = {}
    if alunos:
        consulta = (
            select(Leitura.aluno_id, Livro.nivel_codigo, Leitura.tempo_leitura_min)
            .join(Livro, Leitura.livro_id == Livro.id)
            .where(Leitura.aluno_id.in_(alunos.keys()))
        )
        if inicio is not None:
            consulta = consulta.where(Leitura.data >= inicio)
        if fim is not None:
            consulta = consulta.where(Leitura.data <= fim)
        for aid, codigo, minutos in db.execute(consulta).all():
            livros[aid] = livros.get(aid, 0) + 1
            pontos[aid] = pontos.get(aid, 0.0) + pontos_map.get((codigo or "").upper(), 0.0)
            tempo[aid] = tempo.get(aid, 0) + (minutos or 0)

    # --- Ganho no Matific dentro do período (snapshot final − linha de base) -
    series_m = _series_por_aluno(db, escola_id, SnapshotMatific)
    matific: dict[int, float] = {}
    for aid in alunos:
        # Ganho de atividades estritamente DENTRO do período (base_no_periodo:
        # o acumulado anterior ao intervalo nunca conta como ganho — premiação
        # justa, diferente da evolução/mural que contam "a partir do zero").
        atual, base = _janela(series_m.get(aid, []), inicio, fim, base_no_periodo=True)
        matific[aid] = _delta(atual, base, "atividades")

    categorias = [
        {"chave": "melhor_leitor", "titulo": "Melhor Leitor", "icone": "🏆",
         "descricao": "Mais pontos de dificuldade no período", "unidade": "pontos",
         "podio": _podio(pontos, alunos)},
        {"chave": "mais_livros", "titulo": "Mais Livros Lidos", "icone": "📚",
         "descricao": "Maior quantidade de livros no período", "unidade": "livros",
         "podio": _podio(livros, alunos)},
        {"chave": "mais_tempo", "titulo": "Mais Tempo de Leitura", "icone": "⏱️",
         "descricao": "Maior tempo dedicado à leitura", "unidade": "min",
         "podio": _podio(tempo, alunos)},
        {"chave": "destaque_matific", "titulo": "Destaque no Matific", "icone": "🧮",
         "descricao": "Mais atividades concluídas no Matific no período",
         "unidade": "atividades", "podio": _podio(matific, alunos)},
    ]
    return {"categorias": categorias}
