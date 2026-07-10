"""índice em conversas_ia.created_at para a purga de retenção (LGPD)

A retenção das conversas do assistente apaga por
``DELETE FROM conversas_ia WHERE created_at < corte`` (90 dias). Este índice
mantém a limpeza eficiente conforme o volume cresce.

Puramente aditivo (só cria um índice); seguro para bancos existentes. O nome
casa com o índice que o create_all gera (index=True no modelo), preservando a
paridade create_all ≡ Alembic.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-10
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOME = "ix_conversas_ia_created_at"


def upgrade() -> None:
    op.create_index(_NOME, "conversas_ia", ["created_at"])


def downgrade() -> None:
    op.drop_index(_NOME, table_name="conversas_ia")
