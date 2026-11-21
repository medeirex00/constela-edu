"""A coluna de data e hora dos modelos responde o tipo Python (``datetime``) — o backup depende disso.

``database.DataHoraUTC`` (TypeDecorator de ``DateTime`` no ``type_annotation_map`` do Base)
não repassava ``python_type``: o ``TypeDecorator`` herda o do ``TypeEngine``, que levanta
``NotImplementedError``. O ``services.backup._desserializar`` pergunta o tipo da coluna para
voltar as datas do arquivo a ``datetime``; com toda coluna ``Mapped[datetime]`` virando
DataHoraUTC, a RESTAURAÇÃO de backup caía com 500 na primeira data
(tests/test_backup_restauracao_sem_perda.py: 9 falhas).
"""
from __future__ import annotations

from datetime import datetime

import app.models  # noqa: F401 — registra as tabelas em Base.metadata
import app.quest.models  # noqa: F401
from app.core.database import Base, DataHoraUTC
from app.models.academico import Aluno, IdentidadeExterna
from app.services.backup import _desserializar


def test_toda_coluna_de_data_e_hora_responde_datetime():
    colunas = [c for t in Base.metadata.tables.values() for c in t.columns
               if isinstance(c.type, DataHoraUTC)]
    assert colunas, "nenhuma coluna DataHoraUTC: o type_annotation_map mudou?"
    sem_tipo = []
    for coluna in colunas:
        try:
            tipo = coluna.type.python_type
        except NotImplementedError:
            tipo = None
        if tipo is not datetime:
            sem_tipo.append(f"{coluna.table.name}.{coluna.name}: {tipo}")
    assert not sem_tipo, sem_tipo


def test_backup_volta_a_data_do_arquivo_para_datetime():
    assert _desserializar(Aluno, "created_at", "2026-03-04T05:06:07") == datetime(
        2026, 3, 4, 5, 6, 7)
    assert _desserializar(IdentidadeExterna, "created_at", None) is None
