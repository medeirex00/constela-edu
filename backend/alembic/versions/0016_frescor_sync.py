"""índice de frescor da sincronização (obsolescência barata em escala)

Revision ID: 0016_frescor
Revises: 0015_rede
Create Date: 2026-07-25 00:00:00.000000

A blindagem por OBSOLESCÊNCIA varre, a cada rodada do scheduler, o último
``finalizada_em`` das execuções ``concluida`` por (escola, plataforma) —
GROUP BY MAX(finalizada_em). Como ``sincronizacao_execucoes`` é histórico
PERMANENTE (cresce ~1/dia por integração), sem um índice dedicado essa varredura
degradaria com o tempo. Este índice torna a consulta um lookup barato. Aditivo e
portável (SQLite + Postgres) — nada muda para os dados existentes.
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0016_frescor'
down_revision: Union[str, None] = '0015_rede'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDICE = "ix_sync_exec_frescor"
_TABELA = "sincronizacao_execucoes"
_COLUNAS = ["status", "escola_id", "plataforma", "finalizada_em"]


def upgrade() -> None:
    op.create_index(_INDICE, _TABELA, _COLUNAS)


def downgrade() -> None:
    op.drop_index(_INDICE, table_name=_TABELA)
