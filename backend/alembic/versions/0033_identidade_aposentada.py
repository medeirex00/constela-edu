"""identidade externa aposentada (conta duplicada da mesma criança)

Revision ID: 0033_identidade_aposentada
Revises: 0032_revisoes_identidade
Create Date: 2026-09-25 00:00:00.000000

Uma criança pode ter DUAS contas na mesma plataforma (o caso real: duas contas
Matific da mesma aluna, criadas por caminhos diferentes). Sem acesso
administrativo à plataforma, a escola não consegue apagar a duplicada lá — e
apagar a identidade AQUI seria pior: perderia-se a prova de que aquele id
externo era daquela criança, e o histórico ficaria órfão.

Esta migração dá à identidade externa um ESTADO. A identidade aposentada
continua existindo, com todo o histórico, mas deixa de ser a identidade EFETIVA
do aluno: não casa mais na importação, não alimenta retrato nem pontuação e não
volta a se associar sozinha.

É decisão INTERNA do Constela — a conta segue existindo na plataforma externa.
Por isso a coluna guarda quem decidiu, quando e por quê.

ADITIVA E REVERSÍVEL: só acrescenta colunas com default seguro (`efetiva`), de
modo que toda identidade já gravada continua valendo exatamente como antes.
O downgrade remove as colunas; nenhuma linha é lida, alterada ou apagada.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0033_identidade_aposentada'
down_revision: Union[str, None] = '0032_revisoes_identidade'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABELA = "identidades_externas"


def upgrade() -> None:
    # batch_alter_table: no Postgres vira ALTER normal; no SQLite (usado pelos
    # testes de migração) recria a tabela, que é o único jeito de acrescentar
    # uma FOREIGN KEY lá.
    # ADD COLUMN é suportado nos dois bancos e não recria a tabela.
    # server_default garante que as linhas EXISTENTES nasçam "efetiva" sem
    # precisar de UPDATE — o comportamento de hoje fica idêntico.
    op.add_column(_TABELA, sa.Column("status", sa.String(length=20),
                                     nullable=False, server_default="efetiva"))
    op.add_column(_TABELA, sa.Column("aposentada_em", sa.DateTime(), nullable=True))
    op.add_column(_TABELA, sa.Column("aposentada_por_id", sa.Integer(), nullable=True))
    op.add_column(_TABELA, sa.Column("motivo_aposentadoria", sa.String(length=300),
                                     nullable=True))
    # A FK exige recriar a tabela no SQLite (batch); no Postgres é ALTER normal.
    # Sozinha no lote, sem add_column junto, para o batch não precisar reordenar
    # colunas — reordenar com 4 colunas novas quebra o ordenador do Alembic.
    with op.batch_alter_table(_TABELA) as lote:
        lote.create_foreign_key("fk_identidade_aposentada_por", "usuarios",
                                ["aposentada_por_id"], ["id"], ondelete="SET NULL")
    # A pergunta quente do importador é "quais identidades EFETIVAS este aluno
    # tem nesta plataforma" — uma vez por importação, por escola.
    op.create_index("ix_identidade_externa_status", _TABELA,
                    ["escola_id", "aluno_id", "plataforma", "status"])


def downgrade() -> None:
    op.drop_index("ix_identidade_externa_status", table_name=_TABELA)
    with op.batch_alter_table(_TABELA) as lote:
        lote.drop_constraint("fk_identidade_aposentada_por", type_="foreignkey")
        lote.drop_column("motivo_aposentadoria")
        lote.drop_column("aposentada_por_id")
        lote.drop_column("aposentada_em")
        lote.drop_column("status")
