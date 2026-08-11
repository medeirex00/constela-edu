"""módulos contratados por rede (SaaS: Leitura / Matemática)

Revision ID: 0026_modulos_rede
Revises: 0025_notificacoes
Create Date: 2026-08-09 00:00:00.000000

Cria a tabela `modulos_rede`, que registra quais MÓDULOS cada rede municipal
contratou (hoje: "leitura" = Elefante Letrado e "matematica" = Matific; o
vocabulário vive no catálogo em código, app/services/modulos.py, então módulos
futuros não exigem migração).

ADITIVA e SEM BACKFILL de propósito: a tabela é ESPARSA e a regra de leitura é
**ausência de linha = módulo LIGADO**. Assim, no deploy, toda rede já existente
continua com todos os módulos ativos e nenhum comportamento muda — desligar um
módulo passa a ser um registro explícito feito pelo Admin Global.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0026_modulos_rede'
down_revision: Union[str, None] = '0025_notificacoes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "modulos_rede",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rede_id", sa.Integer(),
                  sa.ForeignKey("redes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("modulo", sa.String(length=30), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_modulos_rede_rede_id", "modulos_rede", ["rede_id"])
    # Uma linha por (rede, módulo): reconfigurar é UPDATE, nunca duplicata.
    op.create_index("uq_modulo_rede", "modulos_rede", ["rede_id", "modulo"],
                    unique=True)


def downgrade() -> None:
    op.drop_index("uq_modulo_rede", table_name="modulos_rede")
    op.drop_index("ix_modulos_rede_rede_id", table_name="modulos_rede")
    op.drop_table("modulos_rede")
