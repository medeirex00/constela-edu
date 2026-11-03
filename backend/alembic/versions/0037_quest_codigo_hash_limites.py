"""Quest: código de login com hash (HMAC) e limite de tentativas persistente

Revision ID: 0037_quest_codigo_hash_limites
Revises: 0036_rls_todas_as_tabelas
Create Date: 2026-10-20 00:00:00.000000

Por quê (auditoria de 20/10/2026): o código de login da criança no Quest — que É a
credencial, sem senha — ficava só em TEXTO CLARO em
``quest_credenciais_aluno.codigo_login``, e o token do QR (a mesma credencial em
figura) em ``qr_token``; quem lesse o banco (dump, backup, réplica) entrava na conta
de qualquer criança por qualquer dos dois. E o limite de tentativas do /quest/auth
vivia só na memória do processo: zerava a cada deploy e não valia entre workers.

O quê:

* ``quest_credenciais_aluno.codigo_login_hash`` (VARCHAR(64), único, nulo permitido):
  HMAC-SHA256 do código normalizado com chave do SERVIDOR (``DATA_ENCRYPTION_KEY``
  se definida, senão ``SECRET_KEY`` — as mesmas que já cifram os segredos em
  repouso), que não fica no banco. BACKFILL a partir do texto, nesta revisão: todo
  cartão já impresso continua entrando. A coluna ``codigo_login`` FICA (o cartão e a
  página do professor ainda mostram o código a partir dela) até o dono confirmar a
  troca; o passo de remoção está em docs/lgpd/RETENCAO-TECNICA.md.
* ``quest_credenciais_aluno.qr_token_hash`` (VARCHAR(64), único, nulo permitido):
  SHA-256 do token do QR (sem chave: o token tem ~192 bits), com BACKFILL — todo QR
  impresso continua entrando. ``qr_token`` FICA pelo mesmo motivo (a URL do QR é
  montada a partir dele) e sai no mesmo passo de remoção que ``codigo_login``:
  enquanto as duas colunas existirem, um dump ainda dá acesso.
* ``quest_limites_acesso``: contador de tentativas por chave (dimensão + HMAC do
  valor — nem IP nem código digitado em texto) com bloqueio temporário. No
  PostgreSQL, RLS ligado (ENABLE, NUNCA FORCE), como a 0034/0036: sem política,
  ``anon``/``authenticated`` do Supabase não leem nem gravam; o dono (o backend) não é
  afetado.

O cálculo do hash está CONGELADO aqui (não importa o serviço do app), como toda
migração de dados: mudar o serviço depois não muda o que esta revisão gravou. Um
teste confere que os dois calculam igual enquanto coexistirem. Se a migração rodar
num processo com outra chave (ex.: ``SECRET_KEY`` efêmera de desenvolvimento), o
hash gravado não confere — o app corrige no primeiro acesso a partir do texto
(fallback de transição) e nenhum cartão deixa de entrar.

Modo offline (``--sql``): o backfill precisa ler o banco e não roda; o log avisa e
o app preenche no primeiro acesso de cada cartão.

LOCK_TIMEOUT (PostgreSQL): o ADD COLUMN e o índice pedem lock na tabela das
credenciais; com um leitor longo aberto (o pg_dump do backup), a migração falha em
segundos e reverte, em vez de travar o login do app antigo.

DOWNGRADE: remove a tabela de limites e as colunas de hash. Nada se perde: o texto
continua em ``codigo_login``/``qr_token`` e o código anterior autentica por ele.
"""
import hashlib
import hmac
import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = '0037_quest_codigo_hash_limites'
down_revision: Union[str, None] = '0036_rls_todas_as_tabelas'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

_log = logging.getLogger("alembic.runtime.migration")


def _segredo_primario() -> str:
    """Mesma regra de app.quest.services.credenciais._segredos_hmac (1º item)."""
    from app.core.config import settings  # a env.py já carrega as configurações

    dedicada = (settings.DATA_ENCRYPTION_KEY or "").strip()
    if dedicada and dedicada != settings.SECRET_KEY:
        return dedicada
    return settings.SECRET_KEY


def _normalizar(codigo: str) -> str:
    """Cópia congelada de credenciais.normalizar_codigo."""
    import unicodedata

    sem_acento = unicodedata.normalize("NFD", codigo or "")
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return "".join(c for c in sem_acento.upper() if c.isascii() and c.isalnum())


def hash_codigo_0037(codigo: str, segredo: str) -> str:
    """Cópia congelada de credenciais.hash_codigo."""
    chave = hashlib.sha256(f"{segredo}|quest-codigo-login".encode()).digest()
    return hmac.new(chave, _normalizar(codigo).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def hash_qr_0037(token: str) -> str:
    """Cópia congelada de credenciais.hash_qr."""
    return hashlib.sha256(f"quest-qr-token|{(token or '').strip()}"
                          .encode("utf-8")).hexdigest()


def _backfill(bind) -> int:
    credenciais = sa.table("quest_credenciais_aluno",
                           sa.column("id", sa.Integer),
                           sa.column("codigo_login", sa.String),
                           sa.column("codigo_login_hash", sa.String),
                           sa.column("qr_token", sa.String),
                           sa.column("qr_token_hash", sa.String))
    segredo = _segredo_primario()
    linhas = bind.execute(sa.select(credenciais.c.id, credenciais.c.codigo_login,
                                    credenciais.c.qr_token)
                          .where(credenciais.c.codigo_login_hash.is_(None)
                                 | credenciais.c.qr_token_hash.is_(None))).all()
    if not linhas:
        return 0
    bind.execute(
        credenciais.update()
        .where(credenciais.c.id == sa.bindparam("alvo"))
        .values(codigo_login_hash=sa.bindparam("hash"),
                qr_token_hash=sa.bindparam("hash_qr")),
        [{"alvo": linha.id, "hash": hash_codigo_0037(linha.codigo_login, segredo),
          "hash_qr": hash_qr_0037(linha.qr_token)}
         for linha in linhas])
    return len(linhas)


def upgrade() -> None:
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute(sa.text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))

    with op.batch_alter_table("quest_credenciais_aluno", schema=None) as batch_op:
        batch_op.add_column(sa.Column("codigo_login_hash", sa.String(length=64),
                                      nullable=True))
        batch_op.add_column(sa.Column("qr_token_hash", sa.String(length=64),
                                      nullable=True))
        batch_op.create_index(batch_op.f("ix_quest_credenciais_aluno_codigo_login_hash"),
                              ["codigo_login_hash"], unique=True)
        batch_op.create_index(batch_op.f("ix_quest_credenciais_aluno_qr_token_hash"),
                              ["qr_token_hash"], unique=True)

    if context.is_offline_mode():
        _log.warning("0037: modo offline — o hash dos códigos e dos QR existentes NÃO "
                     "foi preenchido; o app preenche no primeiro acesso de cada cartão.")
    else:
        _log.info("0037: hashes preenchidos em %d credencial(is) do Quest.",
                  _backfill(bind))

    op.create_table(
        "quest_limites_acesso",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chave", sa.String(length=80), nullable=False),
        sa.Column("falhas", sa.Integer(), nullable=False),
        sa.Column("janela_inicio", sa.DateTime(), nullable=False),
        sa.Column("bloqueado_ate", sa.DateTime(), nullable=True),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("quest_limites_acesso", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_quest_limites_acesso_chave"),
                              ["chave"], unique=True)
        batch_op.create_index(batch_op.f("ix_quest_limites_acesso_atualizado_em"),
                              ["atualizado_em"], unique=False)
    if postgres:
        op.execute(sa.text(
            "ALTER TABLE quest_limites_acesso ENABLE ROW LEVEL SECURITY"))


def downgrade() -> None:
    with op.batch_alter_table("quest_limites_acesso", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_quest_limites_acesso_atualizado_em"))
        batch_op.drop_index(batch_op.f("ix_quest_limites_acesso_chave"))
    op.drop_table("quest_limites_acesso")
    with op.batch_alter_table("quest_credenciais_aluno", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_quest_credenciais_aluno_qr_token_hash"))
        batch_op.drop_index(batch_op.f("ix_quest_credenciais_aluno_codigo_login_hash"))
        batch_op.drop_column("qr_token_hash")
        batch_op.drop_column("codigo_login_hash")
