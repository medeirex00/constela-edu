"""metas da rede (cadastro de objetivos por indicador consolidado)

Revision ID: 0023_metas_rede
Revises: 0022_resultado_unico
Create Date: 2026-07-31 00:00:00.000000

A Secretaria/SEDUC passa a CADASTRAR metas da rede (ex.: média geral 70, 10.000
livros lidos). É o único dado 'cadastrado' — o progresso é sempre calculado
sobre os totais REAIS da rede. Uma meta por (rede, métrica): o índice único
garante o upsert. ON DELETE CASCADE: apagar a rede leva as metas junto.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0023_metas_rede'
down_revision: Union[str, None] = '0022_resultado_unico'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "metas_rede",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rede_id", sa.Integer(),
                  sa.ForeignKey("redes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metrica", sa.String(length=30), nullable=False),
        sa.Column("alvo", sa.Float(), nullable=False),
        sa.Column("descricao", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_metas_rede_rede_id", "metas_rede", ["rede_id"])
    op.create_index("uq_meta_rede_metrica", "metas_rede",
                    ["rede_id", "metrica"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_meta_rede_metrica", table_name="metas_rede")
    op.drop_index("ix_metas_rede_rede_id", table_name="metas_rede")
    op.drop_table("metas_rede")
