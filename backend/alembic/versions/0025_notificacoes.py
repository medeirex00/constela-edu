"""notificações acionáveis por perfil (Fase 2a)

Revision ID: 0025_notificacoes
Revises: 0024_turma_codigo_externo
Create Date: 2026-08-03 00:00:00.000000

Cria a tabela `notificacoes` (aviso acionável por perfil, roteado por escopo
escola|rede|global, com portão de PII em aluno_id) e a coluna por-usuário
`usuarios.notificacoes_lidas_ate_id` (maior id já visto → contador de não-lidas).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0025_notificacoes'
down_revision: Union[str, None] = '0024_turma_codigo_externo'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notificacoes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("escopo", sa.String(length=10), nullable=False),
        sa.Column("escola_id", sa.Integer(),
                  sa.ForeignKey("escolas.id", ondelete="CASCADE"), nullable=True),
        sa.Column("rede_id", sa.Integer(),
                  sa.ForeignKey("redes.id", ondelete="CASCADE"), nullable=True),
        sa.Column("tipo", sa.String(length=40), nullable=False),
        sa.Column("severidade", sa.String(length=8), nullable=False, server_default="info"),
        sa.Column("titulo", sa.String(length=200), nullable=False),
        sa.Column("rota", sa.String(length=200), nullable=True),
        sa.Column("entidade", sa.String(length=40), nullable=True),
        sa.Column("entidade_id", sa.Integer(), nullable=True),
        sa.Column("aluno_id", sa.Integer(), nullable=True),
        sa.Column("autor_id", sa.Integer(),
                  sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_notificacoes_escopo", "notificacoes", ["escopo"])
    op.create_index("ix_notificacoes_escola_id", "notificacoes", ["escola_id"])
    op.create_index("ix_notificacoes_rede_id", "notificacoes", ["rede_id"])
    op.create_index("ix_notificacoes_tipo", "notificacoes", ["tipo"])
    op.create_index("ix_notificacoes_created_at", "notificacoes", ["created_at"])
    op.create_index("ix_notificacoes_escopo_escola", "notificacoes", ["escopo", "escola_id"])
    op.create_index("ix_notificacoes_escopo_rede", "notificacoes", ["escopo", "rede_id"])

    op.add_column("usuarios", sa.Column(
        "notificacoes_lidas_ate_id", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("usuarios", "notificacoes_lidas_ate_id")
    op.drop_index("ix_notificacoes_escopo_rede", table_name="notificacoes")
    op.drop_index("ix_notificacoes_escopo_escola", table_name="notificacoes")
    op.drop_index("ix_notificacoes_created_at", table_name="notificacoes")
    op.drop_index("ix_notificacoes_tipo", table_name="notificacoes")
    op.drop_index("ix_notificacoes_rede_id", table_name="notificacoes")
    op.drop_index("ix_notificacoes_escola_id", table_name="notificacoes")
    op.drop_index("ix_notificacoes_escopo", table_name="notificacoes")
    op.drop_table("notificacoes")
