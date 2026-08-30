"""desempenho por dimensão: aferido/posição de Leitura e de Matemática na nota

Revision ID: 0027_desempenho_por_dimensao
Revises: 0026_modulos_rede
Create Date: 2026-08-24 00:00:00.000000

Arquitetura 2 (`docs/spec-arquitetura-2.md` §1.3 e Aprovação 1, opção 1A): o
desempenho do aluno passa a ser ordenado POR DIMENSÃO, e cada dimensão precisa
de duas informações que hoje não existem em lugar nenhum do banco:

  * ``aferido_leitura`` / ``aferido_matematica`` — existe snapshot ATUAL da
    plataforma daquela dimensão para o aluno. É o que separa "sem snapshot"
    (ausência: fora da ordenação, `—` na tela) de "snapshot zerado" (zero
    LEGÍTIMO, entra em último). O corte NUNCA é ``nota > 0``.
  * ``posicao_leitura`` / ``posicao_matematica`` — a posição CARIMBADA dentro
    da dimensão, contada só entre os aferidos dela.

Por que coluna e não derivar na leitura (`ORDER BY nota_d` + `EXISTS`): posição
vai para certificado, cartaz, telão e app offline. Posição recomputada a cada
leitura MUDA SOZINHA quando outro aluno é importado, sem recálculo — e isso é o
"o sistema mudou a nota do meu filho" garantido.

ADITIVA e NÃO DESTRUTIVA: nada é apagado nem alterado. ``nota_geral`` e
``posicao`` (legado) continuam onde estão, com os valores que já tinham.

BACKFILL: as colunas nascem preenchidas com um estado de transição COERENTE com
as notas já gravadas — ``aferido_d`` pela EXISTÊNCIA de snapshot da plataforma
(a mesma régua de ``rede._medias_por_plataforma``) e ``posicao_d`` ordenando os
aferidos por ``nota_d`` decrescente. Assim nenhuma tela nasce vazia esperando o
recálculo. A fonte AUTORITATIVA continua sendo o motor: o próximo
``recalcular_escola`` restampa as quatro colunas com o desempate LOCAL completo
da dimensão (spec §2.2), que não cabe em SQL porque depende de indicadores que
não são colunas de ``notas``.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0027_desempenho_por_dimensao'
down_revision: Union[str, None] = '0026_modulos_rede'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (coluna aferido, coluna posição, tabela de snapshot, coluna da nota)
_DIMENSOES = (
    ("aferido_leitura", "posicao_leitura", "snapshots_elefante", "nota_elefante"),
    ("aferido_matematica", "posicao_matematica", "snapshots_matific", "nota_matific"),
)


def _backfill(conexao) -> None:
    """Preenche as quatro colunas a partir do que JÁ está no banco.

    Feito em Python (e não num UPDATE ... FROM com window function) para rodar
    igual em SQLite e PostgreSQL: `UPDATE ... FROM` só existe no SQLite ≥ 3.33 e
    a sintaxe do Postgres é outra. O volume é uma linha de `notas` por aluno/ano.
    """
    for col_aferido, col_posicao, tabela_snap, col_nota in _DIMENSOES:
        # 1) aferido = EXISTE snapshot daquela plataforma para o aluno (mesma
        #    régua do EXISTS de rede._medias_por_plataforma). Portável.
        conexao.execute(sa.text(
            f"UPDATE notas SET {col_aferido} = 1 WHERE EXISTS ("
            f"  SELECT 1 FROM {tabela_snap} s"
            f"  WHERE s.aluno_id = notas.aluno_id AND s.escola_id = notas.escola_id)"
        ))
        # 2) posição = ordem por nota decrescente DENTRO de (escola, ano), só
        #    entre os aferidos. Desempate por aluno_id: determinístico e
        #    estável; o recálculo aplica o desempate local completo depois.
        linhas = conexao.execute(sa.text(
            f"SELECT id, escola_id, ano_letivo, {col_nota} AS nota FROM notas "
            f"WHERE {col_aferido} = 1 "
            f"ORDER BY escola_id, ano_letivo, {col_nota} DESC, aluno_id"
        )).all()
        atual, posicao = None, 0
        for linha in linhas:
            chave = (linha.escola_id, linha.ano_letivo)
            if chave != atual:
                atual, posicao = chave, 0
            posicao += 1
            conexao.execute(
                sa.text(f"UPDATE notas SET {col_posicao} = :p WHERE id = :i"),
                {"p": posicao, "i": linha.id},
            )


def upgrade() -> None:
    # `server_default` só para a coluna nascer preenchida nas linhas que já
    # existem (ADD COLUMN NOT NULL exige um valor); o default de aplicação vive
    # no modelo. Falso = "não aferido" é o estado seguro: quem não tem snapshot
    # fica FORA da ordenação em vez de entrar com zero.
    op.add_column("notas", sa.Column("aferido_leitura", sa.Boolean(),
                                     nullable=False, server_default=sa.false()))
    op.add_column("notas", sa.Column("aferido_matematica", sa.Boolean(),
                                     nullable=False, server_default=sa.false()))
    op.add_column("notas", sa.Column("posicao_leitura", sa.Integer(), nullable=True))
    op.add_column("notas", sa.Column("posicao_matematica", sa.Integer(), nullable=True))

    _backfill(op.get_bind())

    op.create_index("ix_notas_escola_ano_pos_leitura", "notas",
                    ["escola_id", "ano_letivo", "posicao_leitura"])
    op.create_index("ix_notas_escola_ano_pos_matematica", "notas",
                    ["escola_id", "ano_letivo", "posicao_matematica"])


def downgrade() -> None:
    op.drop_index("ix_notas_escola_ano_pos_matematica", table_name="notas")
    op.drop_index("ix_notas_escola_ano_pos_leitura", table_name="notas")
    op.drop_column("notas", "posicao_matematica")
    op.drop_column("notas", "posicao_leitura")
    op.drop_column("notas", "aferido_matematica")
    op.drop_column("notas", "aferido_leitura")
