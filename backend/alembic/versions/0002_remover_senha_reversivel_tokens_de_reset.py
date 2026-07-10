"""remover senha reversivel; tokens de reset

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-10 00:40:24.628394

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores da revisão, usados pelo Alembic.
revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tokens_reset_senha',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expira_em', sa.DateTime(), nullable=False),
        sa.Column('usado_em', sa.DateTime(), nullable=True),
        sa.Column('criado_por', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['criado_por'], ['usuarios.id'], ),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_tokens_reset_senha_token_hash', 'tokens_reset_senha',
                    ['token_hash'], unique=True)
    op.create_index('ix_tokens_reset_senha_usuario_id', 'tokens_reset_senha',
                    ['usuario_id'], unique=False)
    # DROP COLUMN nativo: SQLite >= 3.35 e PostgreSQL suportam sem recriar a
    # tabela — evita o rebuild em lote (que quebraria as FKs que apontam para
    # `usuarios` no SQLite) e preserva os dados.
    op.drop_column('usuarios', 'senha_visivel')


def downgrade() -> None:
    op.add_column('usuarios',
                  sa.Column('senha_visivel', sa.VARCHAR(length=500), nullable=True))
    op.drop_index('ix_tokens_reset_senha_usuario_id', table_name='tokens_reset_senha')
    op.drop_index('ix_tokens_reset_senha_token_hash', table_name='tokens_reset_senha')
    op.drop_table('tokens_reset_senha')
