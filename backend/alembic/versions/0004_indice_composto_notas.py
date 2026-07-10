"""índice composto em notas para o caminho de leitura mais quente

O ranking (WHERE escola_id AND ano_letivo ORDER BY posicao), o top10 do
dashboard, o painel público, a média e a exportação filtram sempre por
(escola_id, ano_letivo) e ordenam por posicao. Antes existia só o índice de
coluna única ix_notas_escola_id — que não distingue o ano nem evita a
ordenação. Este índice composto cobre o filtro e o ORDER BY de uma vez.

Puramente aditivo (só cria um índice); seguro para bancos existentes.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-10
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOME = "ix_notas_escola_ano_posicao"


def upgrade() -> None:
    op.create_index(_NOME, "notas", ["escola_id", "ano_letivo", "posicao"])


def downgrade() -> None:
    op.drop_index(_NOME, table_name="notas")
