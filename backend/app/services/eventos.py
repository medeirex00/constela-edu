"""Ingestão idempotente de EVENTOS granulares por aluno (EventoAluno).

A camada de "espelho evento a evento" e a base da linha do tempo cronológica.
Genérica de propósito: as duas plataformas emitem dicts de evento e esta função
grava sem duplicar (Elefante hoje; Matific quando o login destravar). A
idempotência vem da chave_natural DETERMINÍSTICA — reimportar o mesmo relatório
é no-op, nunca duplica e nunca perde histórico.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.models import EventoAluno


def chave_evento(plataforma: str, tipo: str, aluno_id: int, titulo: str,
                 quando: datetime, extra: str = "") -> str:
    """Chave de dedup DETERMINÍSTICA de um evento. Como Matific/Elefante não
    expõem um id estável de evento, sintetizamos a partir do que o identifica:
    plataforma, tipo, aluno, título normalizado e o MINUTO do ocorrido — mais um
    ``extra`` opcional (ex.: nº da tentativa) para casos com repetição no mesmo
    minuto. sha256 em hex (64 chars, cabe na coluna)."""
    base = "|".join([
        plataforma, tipo, str(aluno_id),
        (titulo or "").strip().casefold(),
        quando.strftime("%Y-%m-%dT%H:%M"),
        extra,
    ])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def ingerir_eventos(db: Session, aluno_id: int, plataforma: str,
                    eventos: list[dict]) -> int:
    """Grava só os eventos NOVOS (idempotente). ``eventos`` são dicts com as
    colunas de EventoAluno, incluindo ``chave_natural``. Descarta os que já
    existem (por chave_natural, para este aluno+plataforma) e os repetidos no
    próprio lote; grava o resto num único INSERT executemany. Devolve quantos
    foram inseridos. Portável SQLite+Postgres (não usa on-conflict de dialeto)."""
    if not eventos:
        return 0
    existentes: set[str] = set(db.execute(
        select(EventoAluno.chave_natural).where(
            EventoAluno.aluno_id == aluno_id,
            EventoAluno.plataforma == plataforma)
    ).scalars().all())
    novos: list[dict] = []
    vistos: set[str] = set()
    for ev in eventos:
        chave = ev.get("chave_natural")
        if not chave or chave in existentes or chave in vistos:
            continue
        vistos.add(chave)
        novos.append(ev)
    if novos:
        db.execute(insert(EventoAluno), novos)
    return len(novos)
