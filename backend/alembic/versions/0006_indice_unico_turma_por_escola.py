"""índice único de turma por (escola, ano letivo, nome) — anti-duplicação

Defesa cross-DB contra importações concorrentes que criavam turmas duplicadas
(SELECT-then-INSERT sem lock; a corrida some sob pg_advisory_xact_lock no
Postgres, mas o índice único protege qualquer caminho e todo ambiente).

O nome do índice (uq_turma_escola_ano_nome) casa com o Index(unique=True)
declarado no modelo Turma, preservando a paridade create_all ≡ Alembic.

De-dup defensivo ANTES do índice: em bancos que já acumularam turmas idênticas
(pela corrida), junta cada grupo na turma de menor id (repontando as matrículas)
e apaga as sobras. Em bancos limpos (todo install novo) é no-op.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDICE = "uq_turma_escola_ano_nome"


def _dedup_turmas(bind) -> None:
    """Junta turmas idênticas (mesma escola+ano+nome) na de menor id, repontando
    as matrículas, e apaga as duplicadas. No-op quando não há duplicatas."""
    grupos = bind.execute(sa.text(
        "SELECT escola_id, ano_letivo, nome, MIN(id) AS manter "
        "FROM turmas GROUP BY escola_id, ano_letivo, nome HAVING COUNT(*) > 1"
    )).mappings().all()
    for g in grupos:
        sobras = [row[0] for row in bind.execute(sa.text(
            "SELECT id FROM turmas WHERE escola_id = :e AND ano_letivo = :a "
            "AND nome = :n AND id <> :m"),
            {"e": g["escola_id"], "a": g["ano_letivo"],
             "n": g["nome"], "m": g["manter"]}).all()]
        for extra in sobras:
            bind.execute(sa.text(
                "UPDATE matriculas SET turma_id = :m WHERE turma_id = :x"),
                {"m": g["manter"], "x": extra})
            bind.execute(sa.text("DELETE FROM turmas WHERE id = :x"),
                         {"x": extra})


def upgrade() -> None:
    _dedup_turmas(op.get_bind())
    op.create_index(_INDICE, "turmas", ["escola_id", "ano_letivo", "nome"],
                    unique=True)


def downgrade() -> None:
    op.drop_index(_INDICE, table_name="turmas")
