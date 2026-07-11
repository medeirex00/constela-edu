"""reparo: cria tabelas do baseline 0001 ausentes em bancos carimbados

Revision ID: 0002a
Revises: 0002
Create Date: 2026-07-11

Contexto (incidente de produção)
--------------------------------
Bancos ANTERIORES à adoção do Alembic são detectados por ``app.core.migracoes``
(têm a tabela-âncora ``usuarios`` mas não têm ``alembic_version``) e
CARIMBADOS na revisão 0001 SEM executá-la — assume-se que o schema já é o 0001
completo. O banco de produção nasceu ANTES das features "Constela Quest" e
"responsáveis": tinha as 20 tabelas de então, mas NÃO as 10 tabelas que a 0001
também define. O carimbo passou a AFIRMAR que essas 10 existem, quando não
existiam. A 0003 (integridade referencial) então roda
``ALTER TABLE quest_perfis ADD CONSTRAINT ...`` e quebra com
``UndefinedTable: relation "quest_perfis" does not exist``, abortando o boot.

O que esta migração faz
-----------------------
Recria, pelo fluxo OFICIAL do Alembic, EXATAMENTE as 10 tabelas do 0001 que
estiverem faltando — de forma IDEMPOTENTE (só cria o que não existe) e ANTES da
0003 (que adiciona as FKs a essas tabelas). O DDL abaixo é copiado VERBATIM da
0001, em ordem de dependência. Em bancos que aplicaram a 0001 de fato
(novos/CI/dev), é um NO-OP.

Por que é a correção mais segura
--------------------------------
* Não usa ``metadata.create_all`` nem qualquer DDL fora do Alembic.
* O histórico permanece LINEAR (0001 → 0002 → 0002a → 0003 → 0004 → 0005) e
  todo o schema passa a ser aplicado por migração — o banco fica 100%
  consistente com o histórico.
* Não toca em NENHUMA tabela existente nem em dado algum (só CREATE de tabelas
  ausentes e vazias).
* Idempotente e re-executável: seguro rodar em qualquer estado do banco.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002a"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existentes = set(sa.inspect(op.get_bind()).get_table_names())

    # Ordem de dependência (cada FK aponta para tabela já existente ou já criada
    # acima). Blocos idênticos aos da revisão 0001.

    if "quest_mundos" not in existentes:
        op.create_table('quest_mundos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=40), nullable=False),
        sa.Column('nome', sa.String(length=80), nullable=False),
        sa.Column('descricao', sa.String(length=500), nullable=True),
        sa.Column('ordem', sa.Integer(), nullable=False),
        sa.Column('tema', sa.JSON(), nullable=False),
        sa.Column('icone', sa.String(length=16), nullable=False),
        sa.Column('ativo', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('quest_mundos', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_quest_mundos_slug'), ['slug'], unique=True)

    if "quest_jornadas" not in existentes:
        op.create_table('quest_jornadas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mundo_id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=120), nullable=False),
        sa.Column('descricao', sa.String(length=500), nullable=True),
        sa.Column('ano_escolar', sa.String(length=30), nullable=False),
        sa.Column('ordem', sa.Integer(), nullable=False),
        sa.Column('bncc', sa.JSON(), nullable=False),
        sa.Column('estrelas_chefao', sa.Integer(), nullable=False),
        sa.Column('ativo', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['mundo_id'], ['quest_mundos.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('quest_jornadas', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_quest_jornadas_ano_escolar'), ['ano_escolar'], unique=False)
            batch_op.create_index(batch_op.f('ix_quest_jornadas_mundo_id'), ['mundo_id'], unique=False)

    if "quest_missoes" not in existentes:
        op.create_table('quest_missoes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('jornada_id', sa.Integer(), nullable=False),
        sa.Column('ordem', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=120), nullable=False),
        sa.Column('tipo', sa.String(length=20), nullable=False),
        sa.Column('icone', sa.String(length=16), nullable=True),
        sa.Column('descricao_crianca', sa.String(length=300), nullable=True),
        sa.Column('xp_base', sa.Integer(), nullable=False),
        sa.Column('moedas_base', sa.Integer(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('versao', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['jornada_id'], ['quest_jornadas.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('quest_missoes', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_quest_missoes_jornada_id'), ['jornada_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_quest_missoes_status'), ['status'], unique=False)

    if "quest_desafios" not in existentes:
        op.create_table('quest_desafios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('missao_id', sa.Integer(), nullable=False),
        sa.Column('ordem', sa.Integer(), nullable=False),
        sa.Column('mecanica', sa.String(length=30), nullable=False),
        sa.Column('dificuldade', sa.Integer(), nullable=False),
        sa.Column('bncc_codigo', sa.String(length=12), nullable=True),
        sa.Column('corpo', sa.JSON(), nullable=False),
        sa.Column('gabarito', sa.JSON(), nullable=False),
        sa.Column('dica', sa.JSON(), nullable=False),
        sa.Column('explicacao', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['missao_id'], ['quest_missoes.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('quest_desafios', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_quest_desafios_bncc_codigo'), ['bncc_codigo'], unique=False)
            batch_op.create_index(batch_op.f('ix_quest_desafios_missao_id'), ['missao_id'], unique=False)

    if "quest_perfis" not in existentes:
        op.create_table('quest_perfis',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('escola_id', sa.Integer(), nullable=False),
        sa.Column('aluno_id', sa.Integer(), nullable=False),
        sa.Column('nome_exibicao', sa.String(length=40), nullable=True),
        sa.Column('apelido', sa.String(length=60), nullable=False),
        sa.Column('codigo_amigo', sa.String(length=16), nullable=False),
        sa.Column('nivel', sa.Integer(), nullable=False),
        sa.Column('xp_total', sa.Integer(), nullable=False),
        sa.Column('moedas', sa.Integer(), nullable=False),
        sa.Column('estrelas_total', sa.Integer(), nullable=False),
        sa.Column('sequencia_dias', sa.Integer(), nullable=False),
        sa.Column('escudo_sequencia', sa.Boolean(), nullable=False),
        sa.Column('ultimo_dia_ativo', sa.Date(), nullable=True),
        sa.Column('avatar', sa.JSON(), nullable=False),
        sa.Column('preferencias', sa.JSON(), nullable=False),
        sa.Column('dificuldade', sa.JSON(), nullable=False),
        sa.Column('social_ativo', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['aluno_id'], ['alunos.id'], ),
        sa.ForeignKeyConstraint(['escola_id'], ['escolas.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('aluno_id')
        )
        with op.batch_alter_table('quest_perfis', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_quest_perfis_codigo_amigo'), ['codigo_amigo'], unique=True)
            batch_op.create_index(batch_op.f('ix_quest_perfis_escola_id'), ['escola_id'], unique=False)

    if "quest_credenciais_aluno" not in existentes:
        op.create_table('quest_credenciais_aluno',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('escola_id', sa.Integer(), nullable=False),
        sa.Column('aluno_id', sa.Integer(), nullable=False),
        sa.Column('codigo_login', sa.String(length=20), nullable=False),
        sa.Column('qr_token', sa.String(length=64), nullable=False),
        sa.Column('token_version', sa.Integer(), nullable=False),
        sa.Column('ultimo_acesso', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['aluno_id'], ['alunos.id'], ),
        sa.ForeignKeyConstraint(['escola_id'], ['escolas.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('aluno_id')
        )
        with op.batch_alter_table('quest_credenciais_aluno', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_quest_credenciais_aluno_codigo_login'), ['codigo_login'], unique=True)
            batch_op.create_index(batch_op.f('ix_quest_credenciais_aluno_escola_id'), ['escola_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_quest_credenciais_aluno_qr_token'), ['qr_token'], unique=True)

    if "responsaveis_alunos" not in existentes:
        op.create_table('responsaveis_alunos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('escola_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('aluno_id', sa.Integer(), nullable=False),
        sa.Column('parentesco', sa.String(length=40), nullable=True),
        sa.Column('autorizado_por', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['aluno_id'], ['alunos.id'], ),
        sa.ForeignKeyConstraint(['autorizado_por'], ['usuarios.id'], ),
        sa.ForeignKeyConstraint(['escola_id'], ['escolas.id'], ),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('usuario_id', 'aluno_id', name='uq_responsavel_aluno')
        )
        with op.batch_alter_table('responsaveis_alunos', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_responsaveis_alunos_aluno_id'), ['aluno_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_responsaveis_alunos_escola_id'), ['escola_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_responsaveis_alunos_usuario_id'), ['usuario_id'], unique=False)

    if "quest_habilidades" not in existentes:
        op.create_table('quest_habilidades',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('perfil_id', sa.Integer(), nullable=False),
        sa.Column('bncc_codigo', sa.String(length=12), nullable=False),
        sa.Column('tentativas', sa.Integer(), nullable=False),
        sa.Column('acertos', sa.Integer(), nullable=False),
        sa.Column('dominio', sa.Float(), nullable=False),
        sa.Column('ultima_atividade_em', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['perfil_id'], ['quest_perfis.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('perfil_id', 'bncc_codigo', name='uq_habilidade_perfil_bncc')
        )
        with op.batch_alter_table('quest_habilidades', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_quest_habilidades_bncc_codigo'), ['bncc_codigo'], unique=False)
            batch_op.create_index(batch_op.f('ix_quest_habilidades_perfil_id'), ['perfil_id'], unique=False)

    if "quest_progresso" not in existentes:
        op.create_table('quest_progresso',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('perfil_id', sa.Integer(), nullable=False),
        sa.Column('missao_id', sa.Integer(), nullable=False),
        sa.Column('estrelas', sa.Integer(), nullable=False),
        sa.Column('melhor_pct', sa.Float(), nullable=False),
        sa.Column('tentativas', sa.Integer(), nullable=False),
        sa.Column('primeira_conclusao_em', sa.DateTime(), nullable=True),
        sa.Column('ultima_tentativa_em', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['missao_id'], ['quest_missoes.id'], ),
        sa.ForeignKeyConstraint(['perfil_id'], ['quest_perfis.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('perfil_id', 'missao_id', name='uq_progresso_perfil_missao')
        )
        with op.batch_alter_table('quest_progresso', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_quest_progresso_missao_id'), ['missao_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_quest_progresso_perfil_id'), ['perfil_id'], unique=False)

    if "quest_tentativas" not in existentes:
        op.create_table('quest_tentativas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('escola_id', sa.Integer(), nullable=False),
        sa.Column('perfil_id', sa.Integer(), nullable=False),
        sa.Column('missao_id', sa.Integer(), nullable=False),
        sa.Column('missao_versao', sa.Integer(), nullable=False),
        sa.Column('modo', sa.String(length=20), nullable=False),
        sa.Column('sala_id', sa.Integer(), nullable=True),
        sa.Column('iniciada_em', sa.DateTime(), nullable=False),
        sa.Column('finalizada_em', sa.DateTime(), nullable=True),
        sa.Column('total_desafios', sa.Integer(), nullable=False),
        sa.Column('acertos', sa.Integer(), nullable=False),
        sa.Column('tempo_seg', sa.Integer(), nullable=False),
        sa.Column('xp_ganho', sa.Integer(), nullable=False),
        sa.Column('moedas_ganhas', sa.Integer(), nullable=False),
        sa.Column('estrelas', sa.Integer(), nullable=False),
        sa.Column('respostas', sa.JSON(), nullable=False),
        sa.Column('origem', sa.String(length=12), nullable=False),
        sa.ForeignKeyConstraint(['escola_id'], ['escolas.id'], ),
        sa.ForeignKeyConstraint(['missao_id'], ['quest_missoes.id'], ),
        sa.ForeignKeyConstraint(['perfil_id'], ['quest_perfis.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('quest_tentativas', schema=None) as batch_op:
            batch_op.create_index('ix_quest_tent_escola_fim', ['escola_id', 'finalizada_em'], unique=False)
            batch_op.create_index('ix_quest_tent_perfil_fim', ['perfil_id', 'finalizada_em'], unique=False)
            batch_op.create_index(batch_op.f('ix_quest_tentativas_escola_id'), ['escola_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_quest_tentativas_missao_id'), ['missao_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_quest_tentativas_perfil_id'), ['perfil_id'], unique=False)


def downgrade() -> None:
    # Reparo FORWARD-ONLY: estas tabelas pertencem à revisão 0001 (é ela quem as
    # cria e as remove). Reverter o reparo não deve derrubá-las — no-op.
    pass
