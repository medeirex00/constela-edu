"""aluno.da_lista_piloto (membro da lista piloto, para reconciliação incremental)

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-12 00:00:00.000000

Coluna booleana que marca os alunos que vieram (ou foram casados) por uma
importação da Lista Piloto. A reconciliação incremental só afeta estes: quem
some de uma nova lista vira status="fora_lista_piloto" (reversível, nunca
apagado). Alunos criados à mão ou por upload (Matific/Elefante) ficam False e
NUNCA são tocados pela reconciliação.

Linhas existentes recebem server_default FALSE: a primeira importação após o
deploy marca a associação; a reconciliação passa a valer da 2ª em diante — sem
sinalizar ninguém em massa por engano no primeiro envio. O default usa
``sa.false()`` (portátil: `false` no Postgres, `0` no SQLite) — `DEFAULT 0`
literal quebraria no Postgres (boolean ≠ integer).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('alunos', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'da_lista_piloto', sa.Boolean(), nullable=False,
            server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('alunos', schema=None) as batch_op:
        batch_op.drop_column('da_lista_piloto')
