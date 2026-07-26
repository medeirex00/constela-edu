"""painel público da rede (Secretaria) — token da vitrine sem login

Revision ID: 0018_publico_rede
Revises: 0017_avaliacoes
Create Date: 2026-07-25 00:00:00.000000

Adiciona ``redes.token_publico``: quando definido, habilita a vitrine pública da
Secretaria (/publico/rede/{token}) com as MELHORES ESCOLAS da rede em leitura e
matemática — sem PII de criança. Nulo por padrão (desligado). Aditivo e portável.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0018_publico_rede'
down_revision: Union[str, None] = '0017_avaliacoes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("redes") as b:
        b.add_column(sa.Column("token_publico", sa.String(length=64), nullable=True))
        b.create_index("ix_redes_token_publico", ["token_publico"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("redes") as b:
        b.drop_index("ix_redes_token_publico")
        b.drop_column("token_publico")
