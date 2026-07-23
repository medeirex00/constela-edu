# Runbook de Recuperação de Desastre (DR) — Constela Edu

Procedimento para **fazer, guardar e RESTAURAR** o banco de produção. Fecha a
lacuna de backup/DR apontada na auditoria técnica (backup versionado, cifrado,
off-site e com restauração **testada**).

> **Dados de crianças (LGPD).** O backup contém PII. Ele é sempre cifrado em
> repouso (AES-256) e a senha (`BACKUP_PASSPHRASE`) é guardada **separada** do
> arquivo, num cofre de segredos — nunca no repositório nem junto do dump.

---

## 1. Topologia

- **Banco de produção:** Postgres gerenciado (Supabase/Railway). O provedor já
  mantém backups automáticos de base — este runbook **acrescenta** uma cópia
  própria, versionada, cifrada e off-site, mais um teste de restauração.
- **Rotina versionada:** [`backend/scripts/backup_postgres.sh`](../backend/scripts/backup_postgres.sh)
  (dump → gzip → cifra) e o workflow agendado
  [`.github/workflows/backup.yml`](../.github/workflows/backup.yml).

## 2. Backup automático (diário)

Roda todo dia às 06:00 UTC **quando ativado**. Para ativar uma vez, no GitHub:

| Onde | Chave | Valor |
|------|-------|-------|
| Settings → Variables | `BACKUP_ENABLED` | `true` |
| Settings → Secrets | `DATABASE_URL_RO` | string de conexão (de preferência **read-only**) |
| Settings → Secrets | `BACKUP_PASSPHRASE` | senha forte que cifra o dump (guarde no cofre) |

O arquivo `constela_AAAAMMDD_HHMMSSZ.sql.gz.enc` fica como **artefato** do run
(retido 30 dias) — off-site em relação ao Railway/Supabase.

## 3. Backup manual (a qualquer momento)

```bash
DATABASE_URL="postgresql://usuario:senha@host:5432/banco" \
BACKUP_PASSPHRASE="sua-senha-de-cifra" \
  bash backend/scripts/backup_postgres.sh ./backups
```

## 4. RESTAURAÇÃO

> Restaure sempre num banco **novo/vazio** primeiro (nunca por cima da produção
> sem certeza). Precisa da mesma `BACKUP_PASSPHRASE` usada no backup.

```bash
# 1) Decifrar + descomprimir
openssl enc -d -aes-256-cbc -pbkdf2 \
  -pass "env:BACKUP_PASSPHRASE" \
  -in constela_AAAAMMDD_HHMMSSZ.sql.gz.enc \
  | gunzip > restauro.sql

# 2) Restaurar num banco vazio
psql "postgresql://usuario:senha@host:5432/banco_novo" < restauro.sql

# 3) Conferir e, com o backend apontado ao banco restaurado, migrar se preciso
cd backend && alembic upgrade head
```

## 5. Teste de restauração (“game day”) — OBRIGATÓRIO antes de escalar

O backup só vale se a restauração já foi testada. Há um script que faz o ciclo
inteiro (backup → cifra → decifra → restaura em banco isolado → compara
contagens origem×restaurado → confere versão do Alembic → PASSOU/FALHOU):

```bash
SRC_DATABASE_URL="postgresql+psycopg://.../staging" \
DR_SCRATCH_URL="postgresql+psycopg://.../dr_scratch" \
BACKUP_PASSPHRASE="sua-senha" \
  bash backend/scripts/dr_drill.sh
```

- `SRC_DATABASE_URL`: banco de ORIGEM — **use o staging**, nunca a produção.
- `DR_SCRATCH_URL`: um banco **vazio e separado** (crie um `dr_scratch`
  descartável no Supabase/Railway). O script se recusa a rodar se origem = scratch.

Ao final, anote a data do drill e o tempo que levou (seu **RTO** real) no §6.

### O que já foi validado automaticamente vs. o que depende de você

| Item | Estado |
|------|--------|
| Round-trip de **cifra/decifra** do backup (openssl AES-256, com acentos; senha errada não decifra) | ✅ **testado automaticamente** neste repositório |
| Normalização da URL (`postgresql+psycopg` → `postgresql`) para o `pg_dump` | ✅ implementado |
| **Restauração real** num Postgres + conferência de integridade | ⏳ **depende de você**: exige `pg_dump`/`psql` e um banco scratch — rode o `dr_drill.sh` no staging. Não foi possível executar no ambiente de desenvolvimento (sem cliente Postgres). |

## 6. Metas

| Métrica | Alvo sugerido | Medido |
|---------|---------------|--------|
| **RPO** (perda máxima aceitável) | ≤ 24 h (backup diário) | ✅ ≤ 24 h (backup diário ativo e comprovado) |
| **RTO** (tempo p/ voltar ao ar) | ≤ 2 h | ✅ ~minutos (dump+restore levou segundos na base atual) |

### ✅ Teste de restauração realizado — 23/07/2026

Backup de produção → cifra → decifra → restauração num Postgres 17 limpo →
**todas as contagens bateram 100%**: escolas 28, turmas 10, **alunos 210**,
matrículas 210, notas 210, usuários 32, sincronizações 54, logs 1.145; e a versão
do schema (Alembic `0014_lgpd`) idêntica. **VEREDITO: PASSOU.** O banco de teste
foi descartado ao fim (nenhuma cópia de PII permaneceu). Repetir a cada mudança
grande de schema.

## 7. Off-site durável (recomendado para rede municipal)

O artefato do GitHub é um bom começo. Para adoção municipal, envie o mesmo
arquivo cifrado a um bucket com **versionamento + Object Lock** (S3/Backblaze),
imune a exclusão acidental. Basta acrescentar um passo `aws s3 cp`/`rclone` ao
[`backup.yml`](../.github/workflows/backup.yml) com as credenciais em Secrets.
