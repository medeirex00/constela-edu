"""minimizar ficha do aluno (LGPD) — purgar campos sensíveis já gravados

Revision ID: 0014_lgpd
Revises: 0013
Create Date: 2026-07-22 00:00:00.000000

Decisão do responsável (minimização, LGPD Art. 5º/6º/11): o produto guarda do
aluno apenas nome, nº de chamada (colunas próprias) e RA (na ``ficha``). Esta
migração REMOVE de ``alunos.ficha`` toda chave fora da allowlist — incluindo
categorias SENSÍVEIS (raça/cor, SUS) e documentos (CPF, RG, endereço, telefone,
responsável, etc.) que possam ter sido importados antes da minimização.

Idempotente e portável (SQLite + Postgres): lê cada ficha, mantém só as chaves
permitidas e regrava. O ``downgrade`` é NO-OP de propósito — dado sensível
apagado NÃO deve ser "restaurado" (o objetivo é justamente esquecê-lo).

NOTA de encadeamento: a branch feat/perfis-acesso também tem um 0014; ao
mergear aquela feature, resolver o duplo-head com um ``alembic merge`` (ou
renumerar) — são lineages independentes até lá.
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0014_lgpd'
down_revision: Union[str, None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Única chave que permanece na ficha (identidade do aluno). Mantida em sincronia
# com app/services/lista_piloto.py::ROTULOS_FICHA.
CHAVES_PERMITIDAS = {"ra"}


def _limpar(ficha) -> dict:
    if isinstance(ficha, str):          # alguns bancos guardam JSON como texto
        try:
            ficha = json.loads(ficha)
        except (ValueError, TypeError):
            return {}
    if not isinstance(ficha, dict):
        return {}
    return {k: v for k, v in ficha.items() if k in CHAVES_PERMITIDAS}


def upgrade() -> None:
    conn = op.get_bind()
    linhas = conn.execute(sa.text("SELECT id, ficha FROM alunos")).fetchall()
    for aluno_id, ficha in linhas:
        limpa = _limpar(ficha)
        # Regrava só se algo mudou (evita escrita desnecessária).
        original = ficha if isinstance(ficha, dict) else _limpar(ficha)
        if limpa != (original if isinstance(original, dict) else {}):
            conn.execute(
                sa.text("UPDATE alunos SET ficha = :f WHERE id = :i"),
                {"f": json.dumps(limpa), "i": aluno_id},
            )


def downgrade() -> None:
    # NO-OP intencional: dados sensíveis apagados não são restaurados (LGPD).
    pass
