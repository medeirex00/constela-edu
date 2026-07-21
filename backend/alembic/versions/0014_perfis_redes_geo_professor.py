"""perfis de acesso: redes (secretaria) + geo na escola + professor_id/rede_id no usuario

Tudo ADITIVO e nullable — bancos existentes migram sem recriar (padrão do projeto).
Não inclui nenhuma alteração de tabelas não relacionadas (o autogenerate detectou
duas divergências pré-existentes em `alunos.da_lista_piloto` e
`identidades_externas.created_at` que foram DELIBERADAMENTE removidas desta
migração — não são parte desta feature).

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rede de ensino / Secretaria — o agrupador acima da escola.
    op.create_table(
        "redes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=200), nullable=False),
        sa.Column("uf", sa.String(length=2), nullable=True),
        sa.Column("codigo_ibge", sa.String(length=7), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="ativa"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("redes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_redes_codigo_ibge"), ["codigo_ibge"], unique=False)
        batch_op.create_index(batch_op.f("ix_redes_nome"), ["nome"], unique=False)

    # Escola: rede + geolocalização/endereço (habilita mapa e agregação municipal).
    with op.batch_alter_table("escolas", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rede_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("latitude", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("longitude", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("endereco", sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column("bairro", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("cep", sa.String(length=9), nullable=True))
        batch_op.add_column(sa.Column("codigo_ibge", sa.String(length=7), nullable=True))
        batch_op.create_index(batch_op.f("ix_escolas_codigo_ibge"), ["codigo_ibge"], unique=False)
        batch_op.create_index(batch_op.f("ix_escolas_rede_id"), ["rede_id"], unique=False)
        batch_op.create_foreign_key("fk_escolas_rede", "redes", ["rede_id"], ["id"],
                                    ondelete="SET NULL")

    # Usuário: escopo de rede (secretaria) + vínculo forte professor↔cadastro.
    with op.batch_alter_table("usuarios", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rede_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("professor_id", sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f("ix_usuarios_professor_id"), ["professor_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_usuarios_rede_id"), ["rede_id"], unique=False)
        batch_op.create_foreign_key("fk_usuarios_rede", "redes", ["rede_id"], ["id"],
                                    ondelete="SET NULL")
        batch_op.create_foreign_key("fk_usuarios_professor", "professores",
                                    ["professor_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("usuarios", schema=None) as batch_op:
        batch_op.drop_constraint("fk_usuarios_professor", type_="foreignkey")
        batch_op.drop_constraint("fk_usuarios_rede", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_usuarios_rede_id"))
        batch_op.drop_index(batch_op.f("ix_usuarios_professor_id"))
        batch_op.drop_column("professor_id")
        batch_op.drop_column("rede_id")

    with op.batch_alter_table("escolas", schema=None) as batch_op:
        batch_op.drop_constraint("fk_escolas_rede", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_escolas_rede_id"))
        batch_op.drop_index(batch_op.f("ix_escolas_codigo_ibge"))
        batch_op.drop_column("codigo_ibge")
        batch_op.drop_column("cep")
        batch_op.drop_column("bairro")
        batch_op.drop_column("endereco")
        batch_op.drop_column("longitude")
        batch_op.drop_column("latitude")
        batch_op.drop_column("rede_id")

    with op.batch_alter_table("redes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_redes_nome"))
        batch_op.drop_index(batch_op.f("ix_redes_codigo_ibge"))
    op.drop_table("redes")
