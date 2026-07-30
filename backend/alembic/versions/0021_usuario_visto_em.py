"""visto_em do usuário (presença/heartbeat p/ o Monitor de Sessões Ativas)

Revision ID: 0021_visto_em
Revises: 0020_endereco
Create Date: 2026-07-30 00:00:00.000000

Coluna ADITIVA: última vez que o usuário "pingou" (aplicativo aberto). Alimenta o
Monitor de Sessões Ativas (exclusivo do Admin Global) — "online" = visto_em
recente. Nulo até o primeiro heartbeat; não altera o login nem o `ultimo_acesso`
(que continua sendo o último ENTRAR).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0021_visto_em'
down_revision: Union[str, None] = '0020_endereco'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("usuarios") as b:
        b.add_column(sa.Column("visto_em", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("usuarios") as b:
        b.drop_column("visto_em")
