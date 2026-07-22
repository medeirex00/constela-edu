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

O backup só vale se a restauração já foi testada. Uma vez (e a cada mudança
grande de schema), num banco descartável:

1. Baixe o último artefato de backup.
2. Rode a **Restauração** (§4) num Postgres local/temporário.
3. Confirme: nº de escolas, alunos e notas confere; login funciona; ranking
   abre. Anote a data do teste e o tempo que levou (seu **RTO** real).
4. Descarte o banco de teste.

## 6. Metas (preencher após o 1º game day)

| Métrica | Alvo sugerido | Medido |
|---------|---------------|--------|
| **RPO** (perda máxima aceitável) | ≤ 24 h (backup diário) | — |
| **RTO** (tempo p/ voltar ao ar) | ≤ 2 h | — |

## 7. Off-site durável (recomendado para rede municipal)

O artefato do GitHub é um bom começo. Para adoção municipal, envie o mesmo
arquivo cifrado a um bucket com **versionamento + Object Lock** (S3/Backblaze),
imune a exclusão acidental. Basta acrescentar um passo `aws s3 cp`/`rclone` ao
[`backup.yml`](../.github/workflows/backup.yml) com as credenciais em Secrets.
