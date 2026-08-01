"""código externo (nº SED/Censo) da turma, fora do nome visível

Revision ID: 0024_turma_codigo_externo
Revises: 0023_metas_rede
Create Date: 2026-08-01 00:00:00.000000

A turma passa a guardar o código da sala na fonte externa (o "(300303525)" que
vinha COLADO no nome do relatório) numa coluna própria, indexada. É a chave de
dedup/idempotência mais forte no import: reimportar casa por este código antes
de qualquer heurística de nome, e o nome visível fica curto ("4ºC").
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0024_turma_codigo_externo'
down_revision: Union[str, None] = '0023_metas_rede'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("turmas", sa.Column("codigo_externo", sa.String(length=40),
                                      nullable=True))
    op.create_index("ix_turmas_codigo_externo", "turmas", ["codigo_externo"])


def downgrade() -> None:
    op.drop_index("ix_turmas_codigo_externo", table_name="turmas")
    op.drop_column("turmas", "codigo_externo")
