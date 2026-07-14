"""identidade externa do aluno (UUID do Matific / id do Elefante)

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-14 00:00:00.000000

Cria ``identidades_externas``: vínculo estável aluno ↔ id do aluno numa
plataforma (UUID do Matific). É a identificação CONFIÁVEL entre sincronizações —
base da mudança automática de turma (o UUID não muda quando o aluno troca de
sala). Genérico por ``plataforma`` para o Elefante reusar depois.

Aditivo: tabela nova, nada existente muda. Portável SQLite+Postgres. Cadeia
linear (0012 → 0013).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0013'
down_revision: Union[str, None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'identidades_externas',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('escola_id', sa.Integer(),
                  sa.ForeignKey('escolas.id'), nullable=False),
        sa.Column('aluno_id', sa.Integer(),
                  sa.ForeignKey('alunos.id', ondelete='CASCADE'), nullable=False),
        sa.Column('plataforma', sa.String(length=30), nullable=False),
        sa.Column('id_externo', sa.String(length=80), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('escola_id', 'plataforma', 'id_externo',
                            name='uq_identidade_externa'),
    )
    op.create_index('ix_identidades_externas_escola_id',
                    'identidades_externas', ['escola_id'])
    op.create_index('ix_identidades_externas_aluno_id',
                    'identidades_externas', ['aluno_id'])


def downgrade() -> None:
    op.drop_index('ix_identidades_externas_aluno_id', 'identidades_externas')
    op.drop_index('ix_identidades_externas_escola_id', 'identidades_externas')
    op.drop_table('identidades_externas')
