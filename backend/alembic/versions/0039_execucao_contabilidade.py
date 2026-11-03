"""contabilidade honesta da execução de sincronização

Revision ID: 0039_execucao_contabilidade
Revises: 0038_revogar_papeis_da_api
Create Date: 2026-10-22 00:00:00.000000

A execução dizia "concluída" sempre que chegava algum arquivo: com 0 alunos
aplicados, com uma turma inteira falhando, com tudo na fila de revisão. Os
estados finais passam a ser concluida | parcial | sem_atualizacao | sem_dados |
erro (``status`` é String(16) sem CHECK: nada a migrar nele), e a execução guarda
o que os explica:

* ``qtd_linhas``      linhas recebidas da plataforma;
* ``qtd_em_revisao``  linhas/contas enviadas à fila de revisão;
* ``qtd_falhas``      unidades que falharam (turma, lote de livros, aluno,
                      endpoint, arquivo);
* ``recalculo_pendente``  houve dado gravado e o recálculo das notas falhou;
* ``motivo``          o porquê do status ('nada_mudou', 'falha_apos_gravacao'…).

ADITIVA E REVERSÍVEL: as contagens são ANULÁVEIS — uma execução anterior a esta
migração não as mediu, e NULL ("não medido") não pode ser confundido com 0. O
``recalculo_pendente`` nasce ``false`` por ``server_default`` (sem UPDATE). O
downgrade só remove as colunas; nenhuma linha é lida, alterada ou apagada.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0039_execucao_contabilidade'
down_revision: Union[str, None] = '0038_revogar_papeis_da_api'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABELA = "sincronizacao_execucoes"
COLUNAS = ("qtd_linhas", "qtd_em_revisao", "qtd_falhas", "recalculo_pendente", "motivo")


def upgrade() -> None:
    # ADD COLUMN simples nos dois bancos (sem recriar a tabela no SQLite).
    op.add_column(_TABELA, sa.Column("qtd_linhas", sa.Integer(), nullable=True))
    op.add_column(_TABELA, sa.Column("qtd_em_revisao", sa.Integer(), nullable=True))
    op.add_column(_TABELA, sa.Column("qtd_falhas", sa.Integer(), nullable=True))
    op.add_column(_TABELA, sa.Column("recalculo_pendente", sa.Boolean(), nullable=False,
                                     server_default=sa.false()))
    op.add_column(_TABELA, sa.Column("motivo", sa.String(length=40), nullable=True))


def downgrade() -> None:
    # batch: no SQLite, DROP COLUMN de tabela com índice parcial exige recriar.
    with op.batch_alter_table(_TABELA) as lote:
        for coluna in reversed(COLUNAS):
            lote.drop_column(coluna)
