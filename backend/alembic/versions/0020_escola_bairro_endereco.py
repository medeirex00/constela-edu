"""bairro e endereço da escola (geocodificação mais precisa no mapa da rede)

Revision ID: 0020_endereco
Revises: 0019_fontes
Create Date: 2026-07-26 00:00:00.000000

O mapa da Secretaria geocodificava pelo NOME da escola no OpenStreetMap — mas o
OSM raramente tem escolas municipais pequenas, então elas ficavam sem coordenada
e sumiam do mapa. Com o BAIRRO (que o OSM conhece), toda escola localiza. Aditivo.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0020_endereco'
down_revision: Union[str, None] = '0019_fontes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("escolas") as b:
        b.add_column(sa.Column("bairro", sa.String(length=120), nullable=True))
        b.add_column(sa.Column("endereco", sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("escolas") as b:
        b.drop_column("endereco")
        b.drop_column("bairro")
