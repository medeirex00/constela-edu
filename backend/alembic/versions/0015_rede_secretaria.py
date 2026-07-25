"""rede / secretaria de educação — agrupador acima da escola

Revision ID: 0015_rede
Revises: 0014_lgpd
Create Date: 2026-07-25 00:00:00.000000

Cria a tabela ``redes`` (rede de ensino / Secretaria) e liga escolas e usuários
a ela: ``escolas.rede_id`` (quais escolas a rede agrega) + ``escolas.latitude``/
``longitude`` (mapa), e ``usuarios.rede_id`` (o perfil Secretaria — enxerga a
rede agregada, sem ser global). Tudo NULO por padrão: nada muda para as escolas/
usuários existentes até uma rede ser criada e vinculada. Portável (SQLite +
Postgres) via ``batch_alter_table``.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0015_rede'
down_revision: Union[str, None] = '0014_lgpd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "redes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(length=200), nullable=False),
        sa.Column("uf", sa.String(length=2), nullable=True),
        sa.Column("codigo_ibge", sa.String(length=7), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="ativa"),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_redes_nome", "redes", ["nome"])
    op.create_index("ix_redes_codigo_ibge", "redes", ["codigo_ibge"])

    # batch_alter_table: no SQLite recria a tabela (única forma de ADICIONAR uma
    # FK); no Postgres vira ALTER direto. Adiciona as colunas e a FK NOMEADA num
    # passo só — assim o schema da migração bate com o do create_all (test_alembic).
    with op.batch_alter_table("escolas") as b:
        b.add_column(sa.Column("rede_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("latitude", sa.Float(), nullable=True))
        b.add_column(sa.Column("longitude", sa.Float(), nullable=True))
        b.create_foreign_key("fk_escolas_rede", "redes", ["rede_id"], ["id"],
                             ondelete="SET NULL")
    op.create_index("ix_escolas_rede_id", "escolas", ["rede_id"])

    with op.batch_alter_table("usuarios") as b:
        b.add_column(sa.Column("rede_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_usuarios_rede", "redes", ["rede_id"], ["id"],
                             ondelete="SET NULL")
    op.create_index("ix_usuarios_rede_id", "usuarios", ["rede_id"])


def downgrade() -> None:
    op.drop_index("ix_usuarios_rede_id", table_name="usuarios")
    with op.batch_alter_table("usuarios") as b:
        b.drop_constraint("fk_usuarios_rede", type_="foreignkey")
        b.drop_column("rede_id")
    op.drop_index("ix_escolas_rede_id", table_name="escolas")
    with op.batch_alter_table("escolas") as b:
        b.drop_constraint("fk_escolas_rede", type_="foreignkey")
        b.drop_column("longitude")
        b.drop_column("latitude")
        b.drop_column("rede_id")
    op.drop_index("ix_redes_codigo_ibge", table_name="redes")
    op.drop_index("ix_redes_nome", table_name="redes")
    op.drop_table("redes")
