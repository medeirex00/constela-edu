"""eventos_aluno + sync_marcadores (espelho evento a evento + linha do tempo)

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-12 00:00:00.000000

Camada ADITIVA de histórico fino, para as DUAS plataformas:
- ``eventos_aluno``: 1 linha por evento real (uma leitura, uma atividade) com
  data/HORA, desempenho, tempo, nível — a base da linha do tempo cronológica.
  Idempotente por ``uq_evento_natural (aluno_id, plataforma, chave_natural)``:
  reimportar o mesmo relatório é no-op (nunca duplica, nunca perde histórico).
- ``sync_marcadores``: marca-d'água do incremental por (escola, plataforma,
  tipo) — até onde já capturamos; 1ª sync = histórico total, seguintes = só o
  novo.

NÃO toca em snapshots_matific/snapshots_elefante/leituras/notas — zero regressão
no scoring/evolução/ranking. Tudo portável SQLite+Postgres (op.create_table +
batch). Segue a cadeia linear (0009 → 0010).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0010'
down_revision: Union[str, None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sync_marcadores',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('escola_id', sa.Integer(), nullable=False),
        sa.Column('plataforma', sa.String(length=30), nullable=False),
        sa.Column('tipo_evento', sa.String(length=40), nullable=False),
        sa.Column('primeira_sync_em', sa.DateTime(), nullable=True),
        sa.Column('historico_completo', sa.Boolean(), nullable=False),
        sa.Column('ultimo_evento_em', sa.DateTime(), nullable=True),
        sa.Column('ultima_chave_natural', sa.String(length=64), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['escola_id'], ['escolas.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('escola_id', 'plataforma', 'tipo_evento',
                            name='uq_sync_marcador'),
    )
    with op.batch_alter_table('sync_marcadores', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sync_marcadores_escola_id'),
                              ['escola_id'], unique=False)

    op.create_table(
        'eventos_aluno',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('escola_id', sa.Integer(), nullable=False),
        sa.Column('aluno_id', sa.Integer(), nullable=False),
        sa.Column('importacao_id', sa.Integer(), nullable=True),
        sa.Column('plataforma', sa.String(length=30), nullable=False),
        sa.Column('tipo_evento', sa.String(length=40), nullable=False),
        sa.Column('ocorrido_em', sa.DateTime(), nullable=False),
        sa.Column('chave_natural', sa.String(length=64), nullable=False),
        sa.Column('conteudo_titulo', sa.String(length=300), nullable=True),
        sa.Column('habilidade', sa.String(length=200), nullable=True),
        sa.Column('nivel_codigo', sa.String(length=10), nullable=True),
        sa.Column('acertos', sa.Integer(), nullable=True),
        sa.Column('erros', sa.Integer(), nullable=True),
        sa.Column('tentativas', sa.Integer(), nullable=True),
        sa.Column('pontuacao', sa.Float(), nullable=True),
        sa.Column('tempo_segundos', sa.Integer(), nullable=True),
        sa.Column('livro_id', sa.Integer(), nullable=True),
        sa.Column('dados', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['aluno_id'], ['alunos.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['escola_id'], ['escolas.id']),
        sa.ForeignKeyConstraint(['importacao_id'], ['importacoes.id']),
        sa.ForeignKeyConstraint(['livro_id'], ['livros.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('aluno_id', 'plataforma', 'chave_natural',
                            name='uq_evento_natural'),
    )
    with op.batch_alter_table('eventos_aluno', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_eventos_aluno_aluno_id'),
                              ['aluno_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_eventos_aluno_chave_natural'),
                              ['chave_natural'], unique=False)
        batch_op.create_index(batch_op.f('ix_eventos_aluno_escola_id'),
                              ['escola_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_eventos_aluno_importacao_id'),
                              ['importacao_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_eventos_aluno_livro_id'),
                              ['livro_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_eventos_aluno_ocorrido_em'),
                              ['ocorrido_em'], unique=False)
        batch_op.create_index('ix_eventos_aluno_ocorrido',
                              ['escola_id', 'aluno_id', 'ocorrido_em'], unique=False)
        batch_op.create_index('ix_eventos_tipo',
                              ['escola_id', 'aluno_id', 'tipo_evento'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('eventos_aluno', schema=None) as batch_op:
        batch_op.drop_index('ix_eventos_tipo')
        batch_op.drop_index('ix_eventos_aluno_ocorrido')
        batch_op.drop_index(batch_op.f('ix_eventos_aluno_ocorrido_em'))
        batch_op.drop_index(batch_op.f('ix_eventos_aluno_livro_id'))
        batch_op.drop_index(batch_op.f('ix_eventos_aluno_importacao_id'))
        batch_op.drop_index(batch_op.f('ix_eventos_aluno_escola_id'))
        batch_op.drop_index(batch_op.f('ix_eventos_aluno_chave_natural'))
        batch_op.drop_index(batch_op.f('ix_eventos_aluno_aluno_id'))
    op.drop_table('eventos_aluno')

    with op.batch_alter_table('sync_marcadores', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sync_marcadores_escola_id'))
    op.drop_table('sync_marcadores')
