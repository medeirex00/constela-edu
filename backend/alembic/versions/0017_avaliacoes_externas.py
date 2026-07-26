"""avaliações externas (SAEB/IDEB/SARESP/...) + código INEP na escola

Revision ID: 0017_avaliacoes
Revises: 0016_frescor
Create Date: 2026-07-25 00:00:00.000000

Estrutura genérica de avaliações externas: catálogo (``avaliacoes_externas``) +
tabela de fatos (``resultados_avaliacao``, qualquer granularidade que a fonte
publique). Adiciona ``escolas.codigo_inep`` (identificador OFICIAL para casar com
as bases do INEP/SEDUC sem depender do nome). Tudo aditivo e portável (SQLite +
Postgres) via ``batch_alter_table`` para a coluna nova.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0017_avaliacoes'
down_revision: Union[str, None] = '0016_frescor'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "avaliacoes_externas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chave", sa.String(length=40), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("orgao", sa.String(length=80), nullable=True),
        sa.Column("descricao", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_avaliacoes_externas_chave", "avaliacoes_externas",
                    ["chave"], unique=True)

    op.create_table(
        "resultados_avaliacao",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("avaliacao_id", sa.Integer(), nullable=False),
        sa.Column("edicao", sa.Integer(), nullable=False),
        sa.Column("rede_id", sa.Integer(), nullable=True),
        sa.Column("escola_id", sa.Integer(), nullable=True),
        sa.Column("codigo_inep", sa.String(length=8), nullable=True),
        sa.Column("etapa", sa.String(length=40), nullable=True),
        sa.Column("componente", sa.String(length=40), nullable=True),
        sa.Column("turma", sa.String(length=60), nullable=True),
        sa.Column("indicador", sa.String(length=60), nullable=False),
        sa.Column("valor", sa.Float(), nullable=False),
        sa.Column("unidade", sa.String(length=30), nullable=False),
        sa.Column("fonte", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["avaliacao_id"], ["avaliacoes_externas.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rede_id"], ["redes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["escola_id"], ["escolas.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_resultados_avaliacao_avaliacao_id", "resultados_avaliacao",
                    ["avaliacao_id"])
    op.create_index("ix_resultados_avaliacao_edicao", "resultados_avaliacao", ["edicao"])
    op.create_index("ix_resultados_avaliacao_rede_id", "resultados_avaliacao", ["rede_id"])
    op.create_index("ix_resultados_avaliacao_escola_id", "resultados_avaliacao", ["escola_id"])
    op.create_index("ix_resultados_avaliacao_codigo_inep", "resultados_avaliacao",
                    ["codigo_inep"])
    op.create_index("ix_resultado_escola_avaliacao", "resultados_avaliacao",
                    ["escola_id", "avaliacao_id", "etapa", "componente", "edicao"])

    with op.batch_alter_table("escolas") as b:
        b.add_column(sa.Column("codigo_inep", sa.String(length=8), nullable=True))
        b.create_index("ix_escolas_codigo_inep", ["codigo_inep"])


def downgrade() -> None:
    with op.batch_alter_table("escolas") as b:
        b.drop_index("ix_escolas_codigo_inep")
        b.drop_column("codigo_inep")
    op.drop_table("resultados_avaliacao")
    op.drop_index("ix_avaliacoes_externas_chave", table_name="avaliacoes_externas")
    op.drop_table("avaliacoes_externas")
