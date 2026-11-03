"""Tira dos papéis da API do Supabase (anon, authenticated) todo privilégio no schema do app

Revision ID: 0038_revogar_papeis_da_api
Revises: 0037_quest_codigo_hash_limites
Create Date: 2026-10-21 00:00:00.000000

Por quê (leitura só-consulta de produção, 21/10/2026): ``anon`` e ``authenticated``
têm SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES e TRIGGER nas 51 tabelas do
``public`` e USAGE/UPDATE nas 50 sequências — e os privilégios padrão do dono
(``postgres``) concedem tudo a eles em TODA tabela nova. O RLS sem política
(0034/0036/0037) fecha SELECT/INSERT/UPDATE/DELETE, mas não TRUNCATE nem
REFERENCES/TRIGGER/MAINTAIN, e basta o RLS ser desligado numa tabela (pelo painel, por
engano) para ela reabrir pela API. O app não usa a API do Supabase: o web não tem
cliente Supabase e o backend conecta direto como dono das tabelas. Não há view,
função nem política no ``public`` (mesma leitura).

O quê, num bloco ``DO`` (o mesmo SQL online e no modo offline ``--sql``), para cada
um de ``anon``/``authenticated`` que EXISTIR no cluster:

* ``REVOKE ALL`` objeto a objeto — tabelas, views, sequências, funções e
  procedimentos do schema corrente — SÓ nos objetos cujo dono é o papel da migração
  (ou um papel de que ele é membro). Num objeto alheio o REVOKE daria ERRO e
  desfaria a 0036/0037 da mesma execução; esses ficam para a conferência abaixo;
* ``ALTER DEFAULT PRIVILEGES FOR ROLE <papel da migração>`` no schema corrente E
  global, revogando tabelas, sequências e funções: tabelas criadas depois (pelas
  próximas migrações, com o mesmo papel) já nascem sem acesso pela API.

Fica como está: o USAGE no schema; o ``service_role`` (chave secreta, com
BYPASSRLS — decisão à parte); o ``postgres`` (o app); o ``backup_leitor`` (SELECT por
nome e nos privilégios padrão do postgres); os privilégios padrão do
``supabase_admin`` (o papel da migração não pode mudá-los, e ele não cria tabelas do
app). O RLS continua ligado: as duas defesas se somam.

Sem esses papéis (CI sem Supabase, instalação própria): o bloco não faz nada. SQLite:
nada a fazer.

Conferência (só online): o que sobrar — privilégio concedido por outro papel (que só
ele pode revogar), objeto de outro dono, privilégio padrão que o papel da migração não
alcança — vira WARNING listando cada item, sem travar o deploy; a conferência
pós-deploy é a ``e86/audit_db_ro7.py``. Conta todos os privilégios de tabela do
servidor (inclui MAINTAIN no PostgreSQL 17), USAGE/SELECT/UPDATE de sequência,
EXECUTE de função e as entradas de ``pg_default_acl`` do papel da migração.

DOWNGRADE: não devolve nada — devolver reabriria as tabelas à API.
"""
import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = '0038_revogar_papeis_da_api'
down_revision: Union[str, None] = '0037_quest_codigo_hash_limites'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PAPEIS_DA_API = ("anon", "authenticated")
LOCK_TIMEOUT = "5s"
PRIVILEGIOS_DE_TABELA = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")

_log = logging.getLogger("alembic.runtime.migration")


def _bloco_revogar(papeis: Sequence[str]) -> str:
    lista = ", ".join("'" + p.replace("'", "''") + "'" for p in papeis)
    return f"""
DO $revogar$
DECLARE
  papel text;
  obj record;
  esquema text := current_schema();
BEGIN
  FOREACH papel IN ARRAY ARRAY[{lista}]::text[] LOOP
    CONTINUE WHEN NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = papel);
    FOR obj IN
      SELECT c.relname, c.relkind FROM pg_catalog.pg_class c
      JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = esquema AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
        AND pg_catalog.pg_has_role(current_user, c.relowner, 'USAGE')
    LOOP
      IF obj.relkind = 'S' THEN
        EXECUTE format('REVOKE ALL ON SEQUENCE %I.%I FROM %I', esquema, obj.relname, papel);
      ELSE
        EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM %I', esquema, obj.relname, papel);
      END IF;
    END LOOP;
    FOR obj IN
      SELECT p.proname, pg_catalog.pg_get_function_identity_arguments(p.oid) AS args
      FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
      WHERE n.nspname = esquema AND pg_catalog.pg_has_role(current_user, p.proowner, 'USAGE')
    LOOP
      EXECUTE format('REVOKE ALL ON ROUTINE %I.%I(%s) FROM %I', esquema, obj.proname, obj.args, papel);
    END LOOP;
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL ON TABLES FROM %I', current_user, esquema, papel);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL ON SEQUENCES FROM %I', current_user, esquema, papel);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL ON FUNCTIONS FROM %I', current_user, esquema, papel);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I REVOKE ALL ON TABLES FROM %I', current_user, papel);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I REVOKE ALL ON SEQUENCES FROM %I', current_user, papel);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I REVOKE ALL ON FUNCTIONS FROM %I', current_user, papel);
  END LOOP;
END
$revogar$"""


def _sobras(bind, papel: str) -> list[str]:
    privilegios = list(PRIVILEGIOS_DE_TABELA)
    if bind.execute(sa.text("SELECT current_setting('server_version_num')::int")).scalar() >= 170000:
        privilegios.append("MAINTAIN")
    sobras = []
    for privilegio in privilegios:
        sobras += [f"{nome}:{privilegio}" for (nome,) in bind.execute(sa.text(
            "SELECT c.relname FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p', 'v', 'm', 'f') "
            "AND has_table_privilege(:papel, c.oid, :privilegio) ORDER BY 1"),
            {"papel": papel, "privilegio": privilegio})]
    for privilegio in ("USAGE", "SELECT", "UPDATE"):
        sobras += [f"{nome}:{privilegio}" for (nome,) in bind.execute(sa.text(
            "SELECT c.relname FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = current_schema() AND c.relkind = 'S' "
            # CASE: o planejador pode avaliar a função antes do filtro de relkind, e
            # has_sequence_privilege falha em relação que não é sequência.
            "AND CASE WHEN c.relkind = 'S' THEN has_sequence_privilege(:papel, c.oid, :privilegio) "
            "ELSE false END ORDER BY 1"), {"papel": papel, "privilegio": privilegio})]
    sobras += [f"{nome}():EXECUTE" for (nome,) in bind.execute(sa.text(
        "SELECT p.proname FROM pg_catalog.pg_proc p "
        "JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = current_schema() AND has_function_privilege(:papel, p.oid, 'EXECUTE') "
        "ORDER BY 1"), {"papel": papel})]
    sobras += [f"padrao:{onde}:{tipo}" for onde, tipo in bind.execute(sa.text(
        "SELECT coalesce(n.nspname, '(global)'), d.defaclobjtype "
        "FROM pg_catalog.pg_default_acl d LEFT JOIN pg_catalog.pg_namespace n ON n.oid = d.defaclnamespace "
        "CROSS JOIN LATERAL aclexplode(d.defaclacl) a "
        "WHERE d.defaclrole = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = current_user) "
        "AND a.grantee = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = :papel) "
        "AND (n.oid IS NULL OR n.nspname = current_schema()) ORDER BY 1, 2"), {"papel": papel})]
    return sobras


def upgrade() -> None:
    if context.is_offline_mode():
        if op.get_context().dialect.name != "postgresql":
            return
        # Sem banco não há catálogo para conferir: o bloco DO faz o REVOKE sozinho
        # (e não faz nada onde os papéis não existem).
        op.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
        op.execute(_bloco_revogar(PAPEIS_DA_API))
        _log.warning("0038 em modo offline (--sql): o SQL do REVOKE foi gerado; a conferência "
                     "das sobras só roda online (e86/audit_db_ro7.py depois do deploy).")
        return
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    existentes = [nome for (nome,) in bind.execute(
        sa.text("SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(:nomes) ORDER BY 1"),
        {"nomes": list(PAPEIS_DA_API)})]
    if not existentes:
        _log.info("0038: sem os papéis da API do Supabase neste cluster; nada a revogar.")
        return
    op.execute(sa.text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    op.execute(sa.text(_bloco_revogar(existentes)))
    for papel in existentes:
        sobras = _sobras(bind, papel)
        if sobras:
            _log.warning("0038: %s ainda tem %d privilégio(s) que esta migração não alcança "
                         "(objeto ou concessão de outro papel): %s",
                         papel, len(sobras), ", ".join(sobras[:30]))
        else:
            _log.info("0038: %s sem nenhum privilégio no schema nem privilégio padrão do papel "
                      "da migração.", papel)


def downgrade() -> None:
    # De propósito, não devolve nada (ver o cabeçalho).
    _log.info("0038: descida não devolve privilégios aos papéis da API.")
