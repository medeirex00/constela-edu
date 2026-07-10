"""integridade referencial: ON DELETE nas FKs de filhos

Define o comportamento de deleção no BANCO (antes tudo era NO ACTION, tratado
só no código): filhos que pertencem a um pai vão junto (CASCADE); referências
"de autoria" que podem sobreviver perdem o vínculo (SET NULL). Ficam como estão
(RESTRICT/NO ACTION): escola_id (trava de tenant), importacao_id (snapshot
imutável), matriculas.turma_id e leituras.livro_id (travas de UX) e
missão←progresso/tentativas (telemetria imutável).

Autogenerate NÃO detecta mudança de ON DELETE — esta migração é escrita à mão.
Dois caminhos por dialeto:
  * PostgreSQL (produção): DROP/ADD CONSTRAINT nativo, sem recriar tabela.
  * SQLite (dev/testes): recria a tabela em lote (não há ALTER de constraint).
    O env/aplicar_migracoes desliga PRAGMA foreign_keys durante a migração.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (tabela, coluna, tabela_referida, ondelete_no_upgrade)
# A coluna referida é sempre "id". No downgrade volta tudo a NO ACTION (None).
_FKS = [
    # Filhos de ALUNO — somem com o aluno (LGPD: apagar aluno apaga seus dados)
    ("leituras", "aluno_id", "alunos", "CASCADE"),
    ("snapshots_matific", "aluno_id", "alunos", "CASCADE"),
    ("snapshots_elefante", "aluno_id", "alunos", "CASCADE"),
    ("notas", "aluno_id", "alunos", "CASCADE"),
    ("matriculas", "aluno_id", "alunos", "CASCADE"),
    ("quest_perfis", "aluno_id", "alunos", "CASCADE"),
    ("quest_credenciais_aluno", "aluno_id", "alunos", "CASCADE"),
    ("responsaveis_alunos", "aluno_id", "alunos", "CASCADE"),
    # Filhos de USUÁRIO — dados pessoais somem; autoria vira NULL
    ("responsaveis_alunos", "usuario_id", "usuarios", "CASCADE"),
    ("responsaveis_alunos", "autorizado_por", "usuarios", "SET NULL"),
    ("conversas_ia", "usuario_id", "usuarios", "CASCADE"),
    ("dispositivos_moveis", "usuario_id", "usuarios", "CASCADE"),
    ("tokens_reset_senha", "usuario_id", "usuarios", "CASCADE"),
    ("tokens_reset_senha", "criado_por", "usuarios", "SET NULL"),
    ("importacoes", "usuario_id", "usuarios", "SET NULL"),
    ("logs_auditoria", "usuario_id", "usuarios", "SET NULL"),
    # Filho de CONVERSA
    ("mensagens_ia", "conversa_id", "conversas_ia", "CASCADE"),
    # Filho de NÍVEL de dificuldade
    ("dificuldade_turma", "nivel_id", "niveis_dificuldade", "CASCADE"),
    # Catálogo Quest (mundo→jornada→missão→desafio)
    ("quest_jornadas", "mundo_id", "quest_mundos", "CASCADE"),
    ("quest_missoes", "jornada_id", "quest_jornadas", "CASCADE"),
    ("quest_desafios", "missao_id", "quest_missoes", "CASCADE"),
    # Filhos de PERFIL Quest (astronauta)
    ("quest_progresso", "perfil_id", "quest_perfis", "CASCADE"),
    ("quest_habilidades", "perfil_id", "quest_perfis", "CASCADE"),
    ("quest_tentativas", "perfil_id", "quest_perfis", "CASCADE"),
    # Turma perde o professor deletado, mas continua existindo
    ("turmas", "professor_id", "professores", "SET NULL"),
]

# Nomeia as FKs anônimas refletidas no batch do SQLite (para poder dropá-las).
_NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def _nome_fk_pg(bind, tabela: str, coluna: str) -> str | None:
    """Nome real da constraint de FK no PostgreSQL (gerada pelo create_all)."""
    return bind.execute(sa.text(
        """
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_attribute att
             ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)
        WHERE con.contype = 'f' AND rel.relname = :t AND att.attname = :c
        LIMIT 1
        """
    ), {"t": tabela, "c": coluna}).scalar()


def _por_tabela():
    """Agrupa as FKs por tabela (um rebuild em lote por tabela no SQLite)."""
    grupos: dict[str, list] = {}
    for tabela, coluna, ref, od in _FKS:
        grupos.setdefault(tabela, []).append((coluna, ref, od))
    return grupos


def _aplicar(ondelete_por_linha) -> None:
    """ondelete_por_linha: função (od_upgrade) -> od a usar (None = NO ACTION)."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for tabela, coluna, ref, od in _FKS:
            nome = _nome_fk_pg(bind, tabela, coluna)
            if nome:
                op.drop_constraint(nome, tabela, type_="foreignkey")
            op.create_foreign_key(
                f"{tabela}_{coluna}_fkey", tabela, ref, [coluna], ["id"],
                ondelete=ondelete_por_linha(od))
    else:
        for tabela, fks in _por_tabela().items():
            with op.batch_alter_table(tabela, naming_convention=_NAMING) as b:
                for coluna, ref, od in fks:
                    nome = f"fk_{tabela}_{coluna}_{ref}"
                    b.drop_constraint(nome, type_="foreignkey")
                    b.create_foreign_key(
                        nome, ref, [coluna], ["id"],
                        ondelete=ondelete_por_linha(od))


def upgrade() -> None:
    _aplicar(lambda od: od)          # aplica o ON DELETE desejado


def downgrade() -> None:
    _aplicar(lambda od: None)        # volta tudo a NO ACTION
