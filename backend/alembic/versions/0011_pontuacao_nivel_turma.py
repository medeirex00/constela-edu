"""pontuacao_nivel_turma (pontos por nível configuráveis por TURMA)

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-13 00:00:00.000000

Torna a pontuação por nível de livro (AA..Z) configurável LIVREMENTE por TURMA,
sem faixas fixas (PRD §39). Tabela ESPARSA: só turmas customizadas têm linha; as
demais herdam o padrão da escola (``niveis_dificuldade.pontos_padrao``) — logo o
upgrade preserva 100% o comportamento atual (nenhuma turma customizada no início).

Aditivo: NÃO toca em niveis_dificuldade/dificuldade_turma/notas/leituras. Portável
SQLite+Postgres. Cadeia linear (0010 → 0011).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0011'
down_revision: Union[str, None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pontuacao_nivel_turma',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('escola_id', sa.Integer(), nullable=False),
        sa.Column('turma_id', sa.Integer(), nullable=False),
        sa.Column('pontos_por_codigo', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['escola_id'], ['escolas.id']),
        sa.ForeignKeyConstraint(['turma_id'], ['turmas.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('escola_id', 'turma_id', name='uq_pontos_nivel_turma'),
    )
    op.create_index(op.f('ix_pontuacao_nivel_turma_escola_id'),
                    'pontuacao_nivel_turma', ['escola_id'], unique=False)
    op.create_index(op.f('ix_pontuacao_nivel_turma_turma_id'),
                    'pontuacao_nivel_turma', ['turma_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_pontuacao_nivel_turma_turma_id'),
                  table_name='pontuacao_nivel_turma')
    op.drop_index(op.f('ix_pontuacao_nivel_turma_escola_id'),
                  table_name='pontuacao_nivel_turma')
    op.drop_table('pontuacao_nivel_turma')
