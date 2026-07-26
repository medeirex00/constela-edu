"""fontes de coleta automática de avaliação externa (robô coletor)

Revision ID: 0019_fontes
Revises: 0018_publico_rede
Create Date: 2026-07-26 00:00:00.000000

Tabela ``fontes_avaliacao``: a receita para o software baixar sozinho o arquivo
oficial (URL + mapeamento de colunas) e importá-lo em agenda. Aditivo e portável.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0019_fontes'
down_revision: Union[str, None] = '0018_publico_rede'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fontes_avaliacao",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("avaliacao_id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=160), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("edicao", sa.Integer(), nullable=False),
        sa.Column("indicador", sa.String(length=60), nullable=False),
        sa.Column("unidade", sa.String(length=30), nullable=False),
        sa.Column("mapeamento", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("cadencia", sa.String(length=20), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("ultima_coleta", sa.DateTime(), nullable=True),
        sa.Column("proxima_coleta", sa.DateTime(), nullable=True),
        sa.Column("ultimo_status", sa.String(length=12), nullable=False),
        sa.Column("ultimo_erro", sa.String(length=300), nullable=True),
        sa.Column("ultimo_resumo", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["avaliacao_id"], ["avaliacoes_externas.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_fontes_avaliacao_avaliacao_id", "fontes_avaliacao", ["avaliacao_id"])
    op.create_index("ix_fontes_avaliacao_proxima_coleta", "fontes_avaliacao", ["proxima_coleta"])


def downgrade() -> None:
    op.drop_table("fontes_avaliacao")
