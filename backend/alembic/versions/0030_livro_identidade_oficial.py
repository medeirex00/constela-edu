"""identidade oficial do livro do Elefante (id do catálogo) e origem do nível

Revision ID: 0030_livro_identidade_oficial
Revises: 0028_nota_institucional
Create Date: 2026-09-15 00:00:00.000000

Governança do catálogo: o id oficial do livro no Elefante passa a ser a
identidade principal na sincronização/importação (o título vira fallback), e o
nível efetivo ganha rastreabilidade.

Colunas NOVAS em ``livros`` (todas aditivas, nenhum dado existente é alterado):

  * ``elefante_id``   — id do livro no catálogo oficial (nulo até ser vinculado);
  * ``nivel_fonte``   — último nível recebido da fonte oficial;
  * ``origem_nivel``  — quem definiu o nível efetivo; linhas existentes nascem
    ``legado`` (server_default), novas gravadas pelo app levam ``fonte`` ou
    ``admin_global``;
  * ``word_count``    — wordCount oficial copiado no vínculo (auditoria);
  * ``atualizado_em`` — última alteração de metadados do livro.

SEM backfill: o vínculo das linhas antigas ao catálogo é feito pela própria
sincronização ou pelo script ``scripts.vincular_livros_catalogo`` (dry-run por
padrão), nunca em silêncio durante o deploy.

DEPENDÊNCIA: encadeia na ``0028`` (a última revisão VERSIONADA no histórico),
não numa revisão de outro workstream que ainda não está no git — um checkout
limpo precisa aplicar esta migração sozinho. Como a ``0029`` daquele workstream
também parte da ``0028``, as duas são RAMOS independentes (tabelas diferentes:
currículo × livros) e convivem: ``app.core.migracoes`` aplica ``heads`` (todos
os ramos), nunca um ``head`` único. Quando os dois ramos estiverem no mesmo
histórico, uma revisão de MERGE pode uni-los sem reescrever nenhuma das duas.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0030_livro_identidade_oficial'
down_revision: Union[str, None] = '0028_nota_institucional'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("livros", sa.Column("elefante_id", sa.Integer(), nullable=True))
    op.add_column("livros", sa.Column("nivel_fonte", sa.String(length=5), nullable=True))
    op.add_column("livros", sa.Column("origem_nivel", sa.String(length=20), nullable=False,
                                      server_default="legado"))
    op.add_column("livros", sa.Column("word_count", sa.Integer(), nullable=True))
    op.add_column("livros", sa.Column("atualizado_em", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_livros_elefante_id"), "livros", ["elefante_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_livros_elefante_id"), table_name="livros")
    with op.batch_alter_table("livros") as lote:
        lote.drop_column("atualizado_em")
        lote.drop_column("word_count")
        lote.drop_column("origem_nivel")
        lote.drop_column("nivel_fonte")
        lote.drop_column("elefante_id")
