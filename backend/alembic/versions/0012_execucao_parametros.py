"""parametros da execução de sincronização (janela de datas por run)

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-14 00:00:00.000000

Adiciona ``sincronizacao_execucoes.parametros`` (JSON) para carregar parâmetros
específicos de UMA execução — hoje a janela de datas do Matific (start/end) para
a coleta POR PERÍODO (premiação por semana/mês/intervalo). A execução roda numa
thread que relê a linha pelo id, então o parâmetro precisa estar PERSISTIDO.

Aditivo: default vazio ({}) — execuções existentes/normais não mudam de
comportamento. Portável SQLite+Postgres. Cadeia linear (0011 → 0012).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0012'
down_revision: Union[str, None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'sincronizacao_execucoes',
        sa.Column('parametros', sa.JSON(), nullable=False,
                  server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column('sincronizacao_execucoes', 'parametros')
