"""RLS ligado (ENABLE, nunca FORCE) em TODA tabela do schema do app

Revision ID: 0036_rls_todas_as_tabelas
Revises: 0035_resultados_escolas
Create Date: 2026-10-20 00:00:00.000000

Por quê: o RLS de produção foi ligado FORA do repositório (no painel do Supabase),
tabela a tabela. Tudo o que nasceu depois ficou sem ele. Leitura só de consulta em
20/10/2026: 47 tabelas com RLS e 4 sem — ``metas_rede``, ``modulos_rede``,
``notificacoes`` e ``revisoes_identidade`` (esta guarda o nome do aluno como veio da
plataforma). No Supabase, os papéis ``anon`` e ``authenticated`` têm GRANT em todas as
tabelas de ``public``; sem RLS, quem tiver a chave pública do projeto lê e grava essas
tabelas pela API REST do Supabase, por fora do backend. E um banco recriado do zero
(``upgrade heads``) subia com RLS só nas tabelas da 0034.

O quê: no PostgreSQL, ``ALTER TABLE ... ENABLE ROW LEVEL SECURITY`` em cada tabela
comum ou particionada do schema corrente que ainda não o tem. Sem política: para
``anon``/``authenticated`` a tabela fica vazia e fechada à escrita. ENABLE, NUNCA
FORCE: o dono das tabelas (o papel do backend) não é afetado, nem papel com BYPASSRLS
(em produção, o do backend e o ``backup_leitor`` do backup diário têm). Idempotente:
rodar de novo não faz nada. No SQLite não há RLS: nada a fazer.

Tabelas criadas DEPOIS desta revisão: a migração que as cria liga o RLS nelas (como
a 0034); o teste ``test_rls_todas_as_tabelas`` (PostgreSQL real) e a conferência do
job de migrações do CI falham se alguma tabela do schema ficar sem RLS.

LOCK_TIMEOUT: ``ENABLE ROW LEVEL SECURITY`` pede ACCESS EXCLUSIVE por um instante.
Com um leitor longo aberto (o pg_dump do backup), a migração falha em segundos e
reverte, em vez de esperar sem prazo; o app antigo segue no ar.

DOWNGRADE: não desliga nada. Desligar reabriria as tabelas à API do Supabase, e não
há como separar as 4 que esta revisão ligou das 47 que já estavam ligadas antes dela
(desligar todas seria pior que o estado de antes). Se for preciso desligar numa
tabela, é decisão manual e registrada, fora da migração.
"""
import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0036_rls_todas_as_tabelas'
down_revision: Union[str, None] = '0035_resultados_escolas'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Espera máxima por um lock (PostgreSQL); vale até o fim da transação (SET LOCAL).
LOCK_TIMEOUT = "5s"

# Tabelas comuns ('r') e particionadas ('p') do schema corrente ainda sem RLS.
TABELAS_SEM_RLS = sa.text(
    "SELECT c.relname FROM pg_catalog.pg_class c "
    "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p') "
    "AND NOT c.relrowsecurity ORDER BY c.relname")

_log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(sa.text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    preparador = bind.dialect.identifier_preparer
    tabelas = [linha[0] for linha in bind.execute(TABELAS_SEM_RLS)]
    for tabela in tabelas:
        op.execute(sa.text(
            f"ALTER TABLE {preparador.quote(tabela)} ENABLE ROW LEVEL SECURITY"))
    _log.info("0036: RLS ligado (ENABLE) em %d tabela(s): %s",
              len(tabelas), ", ".join(tabelas) or "nenhuma")


def downgrade() -> None:
    # De propósito, não desliga o RLS (ver o cabeçalho).
    _log.info("0036: descida não desliga o RLS de nenhuma tabela.")
