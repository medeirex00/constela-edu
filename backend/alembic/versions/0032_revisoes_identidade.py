"""fila de revisão de identidade (linha ambígua não é descartada)

Revision ID: 0032_revisoes_identidade
Revises: 0031_leitura_nivel_congelado
Create Date: 2026-09-21 00:00:00.000000

Cria ``revisoes_identidade``: a linha de importação/sincronização cuja
identidade não pôde ser decidida com segurança (dois candidatos, nome parcial
não estrutural, identidade externa de ficha inativa, homônimo em outra sala,
turma ambígua…) deixa de ser só um aviso/log — fica PRESERVADA com nome
recebido, identidade externa, turma informada, candidatos, motivo e os dados
da linha, até um gestor escolher explicitamente o aluno ou descartar.

ADITIVA: só cria a tabela e seus índices. Nenhum dado existente é lido nem
alterado; o downgrade apenas remove a tabela.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0032_revisoes_identidade'
down_revision: Union[str, None] = '0031_leitura_nivel_congelado'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "revisoes_identidade",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("escola_id", sa.Integer(), sa.ForeignKey("escolas.id"), nullable=False),
        sa.Column("chave", sa.String(length=400), nullable=False),
        sa.Column("chave_identidade", sa.String(length=400), nullable=False),
        sa.Column("plataforma", sa.String(length=30), nullable=False),
        sa.Column("formato", sa.String(length=20), nullable=False),
        sa.Column("id_externo", sa.String(length=80), nullable=True),
        sa.Column("nome_recebido", sa.String(length=200), nullable=False),
        sa.Column("turma_informada", sa.String(length=200), nullable=True),
        sa.Column("turma_id", sa.Integer(),
                  sa.ForeignKey("turmas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("motivo", sa.String(length=60), nullable=False),
        sa.Column("candidatos", sa.JSON(), nullable=False),
        sa.Column("linhas", sa.JSON(), nullable=False),
        sa.Column("contexto", sa.JSON(), nullable=False),
        sa.Column("origem", sa.String(length=20), nullable=False),
        sa.Column("importacao_id", sa.Integer(),
                  sa.ForeignKey("importacoes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ocorrencias", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("aluno_escolhido_id", sa.Integer(),
                  sa.ForeignKey("alunos.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolvida_por_id", sa.Integer(),
                  sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolvida_em", sa.DateTime(), nullable=True),
        sa.Column("resolucao", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("atualizada_em", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_revisoes_identidade_escola_id", "revisoes_identidade", ["escola_id"])
    op.create_index("ix_revisoes_identidade_escola_status", "revisoes_identidade",
                    ["escola_id", "status"])
    op.create_index("ix_revisoes_identidade_escola_chave", "revisoes_identidade",
                    ["escola_id", "chave"])


def downgrade() -> None:
    op.drop_index("ix_revisoes_identidade_escola_chave", table_name="revisoes_identidade")
    op.drop_index("ix_revisoes_identidade_escola_status", table_name="revisoes_identidade")
    op.drop_index("ix_revisoes_identidade_escola_id", table_name="revisoes_identidade")
    op.drop_table("revisoes_identidade")
