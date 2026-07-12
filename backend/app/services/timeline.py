"""Consultas da LINHA DO TEMPO cronológica e do ESPELHO por aluno (EventoAluno).

Somente-leitura sobre a camada de eventos granulares. O feed é paginado por
CURSOR de keyset (ocorrido_em, id) — aguenta milhares de eventos por aluno sem
OFFSET caro e sem pular/repetir na inserção concorrente.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import EventoAluno

PAGINA_PADRAO = 50
PAGINA_MAX = 200


def _decodificar_cursor(cursor: str | None) -> tuple[datetime, int] | None:
    if not cursor:
        return None
    try:
        iso, sid = cursor.rsplit("|", 1)
        return datetime.fromisoformat(iso), int(sid)
    except (ValueError, TypeError):
        return None


def _serializar(e: EventoAluno) -> dict:
    return {
        "id": e.id,
        "plataforma": e.plataforma,
        "tipo_evento": e.tipo_evento,
        "ocorrido_em": e.ocorrido_em.isoformat(),
        "conteudo_titulo": e.conteudo_titulo,
        "habilidade": e.habilidade,
        "nivel_codigo": e.nivel_codigo,
        "acertos": e.acertos,
        "erros": e.erros,
        "tentativas": e.tentativas,
        "pontuacao": e.pontuacao,
        "tempo_segundos": e.tempo_segundos,
        "dados": e.dados or {},
    }


def linha_do_tempo(db: Session, escola_id: int, aluno_id: int, *,
                   plataforma: str | None = None, tipo_evento: str | None = None,
                   inicio: datetime | None = None, fim: datetime | None = None,
                   cursor: str | None = None,
                   limite: int = PAGINA_PADRAO) -> dict:
    """Feed cronológico (mais recente primeiro) de eventos do aluno, paginado
    por cursor. Filtros opcionais: plataforma, tipo_evento e período."""
    limite = max(1, min(limite, PAGINA_MAX))
    q = select(EventoAluno).where(
        EventoAluno.escola_id == escola_id, EventoAluno.aluno_id == aluno_id)
    if plataforma:
        q = q.where(EventoAluno.plataforma == plataforma)
    if tipo_evento:
        q = q.where(EventoAluno.tipo_evento == tipo_evento)
    if inicio is not None:
        q = q.where(EventoAluno.ocorrido_em >= inicio)
    if fim is not None:
        q = q.where(EventoAluno.ocorrido_em <= fim)
    cur = _decodificar_cursor(cursor)
    if cur is not None:
        oc, cid = cur
        # Keyset DESC (forma expandida, portável SQLite+Postgres):
        # (ocorrido_em, id) ANTERIOR a (oc, cid).
        q = q.where(or_(
            EventoAluno.ocorrido_em < oc,
            and_(EventoAluno.ocorrido_em == oc, EventoAluno.id < cid)))
    q = q.order_by(EventoAluno.ocorrido_em.desc(),
                   EventoAluno.id.desc()).limit(limite + 1)
    linhas = db.execute(q).scalars().all()
    tem_mais = len(linhas) > limite
    itens = linhas[:limite]
    proximo = (f"{itens[-1].ocorrido_em.isoformat()}|{itens[-1].id}"
               if tem_mais and itens else None)
    return {"itens": [_serializar(e) for e in itens], "proximo_cursor": proximo}


def espelho(db: Session, escola_id: int, aluno_id: int) -> dict:
    """Resumo consolidado do 'espelho' do aluno: contadores por tipo e por
    plataforma, primeira/última atividade e tempo total — o topo da aba."""
    onde = (EventoAluno.escola_id == escola_id,
            EventoAluno.aluno_id == aluno_id)
    por_tipo = dict(db.execute(
        select(EventoAluno.tipo_evento, func.count()).where(*onde)
        .group_by(EventoAluno.tipo_evento)).all())
    por_plataforma = dict(db.execute(
        select(EventoAluno.plataforma, func.count()).where(*onde)
        .group_by(EventoAluno.plataforma)).all())
    total, primeira, ultima, tempo = db.execute(
        select(func.count(), func.min(EventoAluno.ocorrido_em),
               func.max(EventoAluno.ocorrido_em),
               func.coalesce(func.sum(EventoAluno.tempo_segundos), 0))
        .where(*onde)).one()
    return {
        "total_eventos": int(total or 0),
        "primeira_atividade": primeira.isoformat() if primeira else None,
        "ultima_atividade": ultima.isoformat() if ultima else None,
        "tempo_total_segundos": int(tempo or 0),
        "por_tipo": por_tipo,
        "por_plataforma": por_plataforma,
    }
