"""nível congelado na leitura (o passado não é reescrito por correção de catálogo)

Revision ID: 0031_leitura_nivel_congelado
Revises: 0030_livro_identidade_oficial
Create Date: 2026-09-15 00:00:00.000000

Fecha a divergência entre o que a tela mostra e o que a nota gravada vale:

  * ``leituras.nivel_codigo``    — nível EFETIVO do livro quando a leitura foi
    registrada (é o que pontua aquela leitura);
  * ``leituras.catalogo_versao`` — versão do catálogo oficial que resolveu esse
    nível (auditoria: dá para saber com que régua o número nasceu).

Antes, todos os consumidores (ranking por período, premiações, histórico do
aluno, evolução e o próprio motor) liam ``livros.nivel_codigo`` AO VIVO: corrigir
o nível de um livro mudava na hora resultados de períodos já fechados nas telas,
enquanto a nota gravada só mudava no recálculo — dois números para o mesmo fato.
Com o nível congelado, a correção de catálogo vale para as PRÓXIMAS leituras; o
histórico só muda por uma ação EXPLÍCITA e auditada do Admin Global.

ADITIVA: as duas colunas nascem nulas, sem backfill. Leitura com nível nulo
continua valendo pelo nível atual do livro (mesmo número de antes), e o
preenchimento das linhas antigas é feito pelo script
``scripts.vincular_livros_catalogo --congelar-niveis`` (dry-run por padrão),
nunca em silêncio durante o deploy.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0031_leitura_nivel_congelado'
down_revision: Union[str, None] = '0030_livro_identidade_oficial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("leituras", sa.Column("nivel_codigo", sa.String(length=5), nullable=True))
    op.add_column("leituras", sa.Column("catalogo_versao", sa.String(length=12), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("leituras") as lote:
        lote.drop_column("catalogo_versao")
        lote.drop_column("nivel_codigo")
