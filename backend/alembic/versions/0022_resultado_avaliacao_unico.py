"""chave natural única em resultados_avaliacao (auditoria M6)

Revision ID: 0022_resultado_unico
Revises: 0021_visto_em
Create Date: 2026-07-31 00:00:00.000000

A tabela de fatos das avaliações externas (SAEB/IDEB/SARESP…) não tinha UNIQUE:
a idempotência era 100% no código (SELECT-then-INSERT), que assume coletas NÃO
concorrentes. Mas "coletar agora" e o scheduler podiam coletar a MESMA fonte ao
mesmo tempo → duas linhas para o mesmo fato (série/painel SEDUC inflados,
não auto-curável). Fecha a brecha com um índice ÚNICO na chave natural. O
COALESCE trata os NULOS (etapa/componente/turma que a fonte não fornece) como
'' — senão o UNIQUE os veria como distintos. Só linhas casadas (escola_id) são
gravadas.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0022_resultado_unico'
down_revision: Union[str, None] = '0021_visto_em'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GRUPO = ("avaliacao_id, edicao, indicador, escola_id, "
          "COALESCE(etapa, ''), COALESCE(componente, ''), COALESCE(turma, '')")


def upgrade() -> None:
    # 1) Remove duplicatas pré-existentes (mantém a de MAIOR id por chave natural)
    #    — senão o índice único não pode ser criado.
    op.execute(
        "DELETE FROM resultados_avaliacao WHERE id NOT IN ("
        f"SELECT MAX(id) FROM resultados_avaliacao GROUP BY {_GRUPO})"
    )
    # 2) Índice único na chave natural (NULOS tratados como '').
    op.create_index(
        "uq_resultado_natural", "resultados_avaliacao",
        ["avaliacao_id", "edicao", "indicador", "escola_id",
         sa.text("COALESCE(etapa, '')"), sa.text("COALESCE(componente, '')"),
         sa.text("COALESCE(turma, '')")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_resultado_natural", table_name="resultados_avaliacao")
