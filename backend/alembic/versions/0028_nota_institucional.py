"""nota institucional (régua fixa da rede) separada da nota local da escola

Revision ID: 0028_nota_institucional
Revises: 0027_desempenho_por_dimensao
Create Date: 2026-08-28 00:00:00.000000

Separa o SCORING INSTITUCIONAL (a régua oficial da rede — dificuldade A3 fixa +
pesos padrão + normalização linear P90) do SCORING INTERNO da escola (a config
que o coordenador pode personalizar).

Duas colunas NOVAS em ``notas``:

  * ``nota_elefante_institucional``
  * ``nota_matific_institucional``

São calculadas SEMPRE com o perfil institucional fixo, independentemente de
qualquer configuração local. O ranking/dashboard/KPI/relatório DA REDE passam a
ler EXCLUSIVAMENTE estas colunas; ``nota_elefante``/``nota_matific`` (locais)
continuam servindo o contexto INTERNO da escola. Assim, nenhuma alteração de
pesos/dificuldade feita por um coordenador consegue mover a posição da escola no
ranking da rede.

ADITIVA: default 0.0 (server_default), sem backfill. No deploy, toda linha
existente nasce com 0.0 nas colunas novas; o primeiro recálculo por escola as
preenche. Enquanto não recalculado, a rede vê 0 (estado "ainda não aferido pelo
perfil institucional"), nunca um número contaminado.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0028_nota_institucional'
down_revision: Union[str, None] = '0027_desempenho_por_dimensao'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notas",
        sa.Column("nota_elefante_institucional", sa.Float(), nullable=False,
                  server_default="0.0"),
    )
    op.add_column(
        "notas",
        sa.Column("nota_matific_institucional", sa.Float(), nullable=False,
                  server_default="0.0"),
    )


def downgrade() -> None:
    op.drop_column("notas", "nota_matific_institucional")
    op.drop_column("notas", "nota_elefante_institucional")
