# Runbook de Recuperação de Desastre (DR) — Constela Edu

Como o banco de produção é **guardado, conferido e restaurado**.

> **Dados de crianças (LGPD).** O backup é a base inteira, com dados pessoais.
> Ele só existe **cifrado** e só no repositório **privado**
> `medeirex00/constela-backups`. A senha fica **separada**: no secret desse
> repositório e numa cópia no gerenciador de senhas do dono. Senhas e URLs de banco
> são **digitadas no terminal** (`read -rsp`), nunca coladas num comando, chat,
> e-mail ou arquivo. A senha do banco vai por `PGPASSWORD`, nunca dentro de uma URL
> passada como argumento: o argumento aparece na lista de processos.

---

## 1. Onde o backup roda (e onde NÃO roda)

| | Repositório | Situação |
|---|---|---|
| **Backup em uso** | `medeirex00/constela-backups` (**privado**) | diário, com ensaio de restauração a cada execução (§2) |
| Legado | `medeirex00/constela-edu` (este) | **não usar** (barreiras abaixo) |

As barreiras contra backup neste repositório:

1. **Variável.** `BACKUP_ENABLED` fica `false`.
2. **Workflow desativado** (Actions › "Backup do banco (produção)" › ··· › *Disable workflow*).
   É a única barreira que vale para qualquer ramo. O ramo `recuperacao/senha-backups`
   tem um `backup.yml` cujo modo "transferir" **não olha a variável**.
3. **Trava no código.** O `backup.yml` **deste ramo** recusa rodar em repositório público.
   Ela só vale depois que este ramo estiver no `main`. **Até lá, o `main` não a tem.** Ela
   também deixa de valer se este repositório virar privado, e por isso as barreiras 1 e 2
   são obrigatórias.
4. **Secrets legados.** `BACKUP_PASSPHRASE`, `BACKUP_PASSPHRASE_TRANSFERENCIA` e
   `DATABASE_URL_RO` ainda estão cadastrados aqui. Com eles, o workflow ativo volta a gerar
   dump. Retire-os quando possível, sabendo que apagar o `BACKUP_PASSPHRASE` torna
   irrecuperáveis os dumps antigos guardados aqui. A credencial de banco do
   `DATABASE_URL_RO` daqui é anterior ao papel `backup_leitor`: troque-a no banco, com plano.

> **Atenção ao nome.** Os dois repositórios têm um workflow chamado
> "Backup do banco (produção)". Para um backup manual, abra **sempre** pela URL do
> privado: `https://github.com/medeirex00/constela-backups/actions/workflows/backup.yml`.
> Em 22/10/2026 um disparo no repositório errado publicou um dump novo como artefato
> público, apagado em seguida.
>
> **Nunca** ligue `BACKUP_ENABLED=true` **neste** repositório. (No privado, ela fica
> `true`: ver §2.)

## 2. O backup diário (repositório privado)

O workflow `backup.yml` do privado só roda com a variável `BACKUP_ENABLED=true` **lá**.
Sem ela, o job é pulado em silêncio. O agendamento é 06:17 UTC, mas o GitHub costuma
começar horas depois. A cada execução, ele:

1. confere que o repositório é **privado** antes de ler qualquer segredo;
2. conta as linhas de cada tabela na produção (transação somente leitura; só números);
3. gera o dump com `pg_dump --schema=public --no-owner --no-privileges`, comprime com
   `gzip -9` e cifra com `openssl enc -aes-256-cbc -pbkdf2` usando o secret
   `BACKUP_PASSPHRASE_COFRE` (ASCII visível, 32 ou mais caracteres);
4. grava o `SHA256SUMS` e guarda o artefato `backup-postgres-<execução>`, privado, por 14 dias;
5. faz um **ensaio de restauração** num PostgreSQL 17 descartável do próprio job, com
   `scripts/verificar_restauracao.sh`: rodapé, aplicação sem erro, `alembic_version` e pelo
   menos 98% das linhas contadas na origem.

**Alertas.** O workflow tem passos de "sinal de vida" e de "aviso de falha", mas eles só
funcionam com os secrets `BACKUP_HEARTBEAT_URL` e `BACKUP_ALERT_WEBHOOK` cadastrados no
privado. **Hoje não estão.** Um backup que falha ou deixa de rodar não avisa ninguém. Até
configurar um monitor de sinal de vida, que alarma quando o ping não chega, a única detecção
é a conferência abaixo.

Os pontos históricos de setembro e outubro de 2026 ficam num artefato de **cofre**
(`backups-cofre-*`), com vários dumps dentro e retenção longa. Detalhes no `OPERACAO.md` e
no `RECUPERACAO.md` do privado.

**Conferência do dia, sem baixar nada:** na execução mais recente do privado, "Gerar backup
cifrado", "Guardar o backup" e "Ensaio de restauração" estão verdes, e ela tem menos de 36 h.

## 3. Restauração verificada FORA do GitHub (com a sua cópia da senha)

O ensaio do workflow usa a senha guardada no GitHub. Só este teste prova que a **sua** cópia
da senha abre o backup e que ele restaura longe do GitHub. Faça a cada mudança grande de
schema e anote a data e o tempo (o RTO) no §7.

**Pré-requisitos.**
- PostgreSQL **17**: cliente e servidor, usados só para um cluster descartável local. Não use
  um serviço PostgreSQL já instalado na máquina.
- Git Bash (`openssl`, `gzip`, `sha256sum`, `unzip`).
- Um clone do repositório privado. Os comandos rodam na pasta dele, porque os `scripts/` são de lá.
- Uma pasta temporária, apagada no fim: o artefato e o banco restaurado contêm dados pessoais.

**Passos.** Cada bloco redefine `T` e `PG17`, então pode ser colado num terminal novo.

```bash
# 1) Baixe o artefato da execução verde mais recente do PRIVADO (Actions › execução ›
#    Artifacts) para a pasta T. Confira o sha256 do zip com o digest que o GitHub mostra.
T="$HOME/restauracao-teste"; mkdir -p "$T"
sha256sum "$T"/backup-postgres-*.zip
unzip -q "$T"/backup-postgres-*.zip -d "$T" && (cd "$T" && sha256sum -c SHA256SUMS)
ls "$T"/constela_*.sql.gz.enc        # o diário traz UM arquivo
#    Ponto do COFRE: unzip -q "$T"/backups-cofre-*.zip -d "$T"; o cofre traz VÁRIOS
#    constela_*.sql.gz.enc (ver MANIFESTO.txt); escolha um e use o nome completo no ARQ.

# 2) A SUA cópia da senha abre o arquivo? (decifra, gzip íntegro, rodapé do pg_dump)
T="$HOME/restauracao-teste"; ARQ="$(ls "$T"/constela_*.sql.gz.enc | head -1)"   # ou o nome escolhido
bash scripts/conferir_senha_local.sh "$ARQ" "$T/SHA256SUMS"

# 3) Cluster PostgreSQL 17 descartável, só em 127.0.0.1, numa porta livre (ex.: 55433)
T="$HOME/restauracao-teste"; PG17="/c/Program Files/PostgreSQL/17/bin"
"$PG17/initdb" -D "$T/cluster" -U restauracao --auth=trust -E UTF8
"$PG17/pg_ctl" -D "$T/cluster" -o "-p 55433 -c listen_addresses=127.0.0.1" -l "$T/pg.log" -w start
"$PG17/createdb" -h 127.0.0.1 -p 55433 -U restauracao restauracao_teste

# 4) Ensaio de restauração. O script RECUSA um destino que não seja local, não esteja vazio
#    ou não tenha "restaura"/"test" no nome. Sem senha de banco: o cluster local é --auth=trust.
T="$HOME/restauracao-teste"; PG17="/c/Program Files/PostgreSQL/17/bin"; ARQ="$(ls "$T"/constela_*.sql.gz.enc | head -1)"
read -rsp "Senha do backup: " BACKUP_PASSPHRASE; echo; export BACKUP_PASSPHRASE
PATH="$PG17:$PATH" RESTORE_DATABASE_URL="postgresql://restauracao@127.0.0.1:55433/restauracao_teste" \
  bash scripts/verificar_restauracao.sh "$ARQ"
unset BACKUP_PASSPHRASE

# 5) Limpeza OBRIGATÓRIA: parar o cluster e apagar a pasta inteira (artefato e banco restaurado)
T="$HOME/restauracao-teste"; PG17="/c/Program Files/PostgreSQL/17/bin"
"$PG17/pg_ctl" -D "$T/cluster" stop -m fast; rm -rf "$T"; ls "$T" 2>/dev/null || echo "limpo"
```

**Critério.** O script termina em `OK`. As tabelas e linhas restauradas batem com os números
que o ensaio da mesma execução imprimiu no log do Actions (só números). Se algo falhar, não
confie no backup até resolver.

## 4. Restauração de emergência (produção perdida)

Sempre num banco **novo e vazio** (um projeto Supabase novo, por exemplo), nunca por cima da
produção.

1. Escolha o ponto: o diário mais recente do privado, ou um ponto do cofre.
2. Siga os passos 1 e 2 do §3 para baixar, conferir e testar a senha. Deixe `ARQ` apontando
   para o arquivo escolhido.
3. Aplique o dump no banco novo. A senha do banco vai por `PGPASSWORD`, e a URL passada ao
   `psql` **não leva senha**. Com `pipefail`, qualquer etapa que falhar aborta. Erros saem só
   com o código, sem a linha de dados.
   ```bash
   T="$HOME/restauracao-teste"; ARQ="$T/constela_AAAAMMDD_HHMMSSZ.sql.gz.enc"   # nome EXATO
   read -rp  "Host do banco NOVO (ex.: db.xxxx.supabase.co): " PGHOST
   read -rsp "Senha do banco NOVO: " PGPASSWORD; echo
   read -rsp "Senha do backup: " BACKUP_PASSPHRASE; echo
   export PGHOST PGPASSWORD BACKUP_PASSPHRASE PGUSER=postgres PGDATABASE=postgres PGPORT=5432 PGSSLMODE=require
   ( set -o pipefail
     openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$ARQ" \
       | gunzip | sed '/^CREATE SCHEMA public;$/d' \
       | psql -X -q -v ON_ERROR_STOP=1 -v VERBOSITY=sqlstate -v SHOW_CONTEXT=never -o /dev/null 2> "$T/erros.txt" \
   ) && echo "dump aplicado" || { echo "FALHOU: veja só os códigos em $T/erros.txt"; }
   ```
4. **Feche o banco novo à API do Supabase ANTES de qualquer outra coisa.** O dump sai com
   `--no-privileges`: num Supabase novo, os privilégios padrão dão acesso total a `anon` e
   `authenticated` em toda tabela criada. Como o dump já traz a versão de migração no
   `alembic_version`, o deploy **não** reaplica a 0036 nem a 0038. Rode, no mesmo terminal:
   ```bash
   psql -X -q -v ON_ERROR_STOP=1 <<'SQL'
   DO $$ DECLARE t record; BEGIN
     FOR t IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
              WHERE n.nspname = 'public' AND c.relkind IN ('r','p') AND NOT c.relrowsecurity LOOP
       EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.relname);
     END LOOP; END $$;
   REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM anon, authenticated;
   REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
   REVOKE ALL ON ALL ROUTINES  IN SCHEMA public FROM anon, authenticated;
   ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON TABLES    FROM anon, authenticated;
   ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
   ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon, authenticated;
   ALTER DEFAULT PRIVILEGES FOR ROLE postgres REVOKE ALL ON TABLES    FROM anon, authenticated;
   ALTER DEFAULT PRIVILEGES FOR ROLE postgres REVOKE ALL ON SEQUENCES FROM anon, authenticated;
   ALTER DEFAULT PRIVILEGES FOR ROLE postgres REVOKE ALL ON FUNCTIONS FROM anon, authenticated;
   SQL
   ```
   Depois, rode no banco novo as duas conferências do CI (`.github/workflows/ci.yml`, job de
   migrações): "Conferir RLS ligado…" e "Conferir que a API do Supabase (anon/authenticated)
   não alcança nada". As duas têm de passar.
5. **Confira que os dados voltaram**, para não publicar uma produção vazia. Rode
   `bash scripts/contar_tabelas.sh "postgresql://postgres@$PGHOST:5432/postgres?sslmode=require"`
   (o script lê a senha de `PGPASSWORD`). Tabelas e linhas têm de bater com os números do
   ensaio da execução escolhida.
6. Só então troque o `DATABASE_URL` no provedor do backend, publique e confira
   `/api/health/ready`. No fim, `unset PGPASSWORD BACKUP_PASSPHRASE`.

## 5. Backup manual (exceção)

Pelo **repositório privado**:
`https://github.com/medeirex00/constela-backups/actions/workflows/backup.yml` › *Run workflow*.
Essa execução já inclui o ensaio de restauração.

O `backend/scripts/backup_postgres.sh` deste repositório só serve numa máquina do operador,
em último caso:
- a senha do banco vai por `PGPASSWORD` (`read -rsp`), com uma URL **sem senha** em `DATABASE_URL`;
- a senha de cifra vai por `BACKUP_PASSPHRASE` (`read -rsp`);
- o arquivo gerado nunca vai para um lugar público.

## 6. `backend/scripts/dr_drill.sh` — NÃO USAR

Ele gera um dump **novo** de uma origem, em vez de testar o backup guardado, e **hoje não
funciona**: aplica o `CREATE SCHEMA public;` do dump num banco que já tem o schema e aborta.
Ele também não tem as travas de destino local e vazio. Use o §3.

## 7. Metas e histórico

| Métrica | Alvo | Situação |
|---|---|---|
| **RPO** (perda máxima) | ≤ 24 h | diário privado ativo desde 16/10/2026 |
| **RTO** (voltar ao ar) | ≤ 2 h | medir no próximo teste do §3 |

- **23/07/2026:** teste de restauração do backup antigo (deste repositório, hoje desligado): passou.
- **16/10/2026:** cofre de históricos conferido (6 de 6) e primeiro diário privado validado com a
  cópia da senha do dono (decifra, gzip, rodapé). Não houve restauração em banco nesse dia.
- **16 a 21/10/2026:** ensaio de restauração verde em todas as 12 execuções do privado.
- **22/10/2026:** um backup manual foi disparado por engano neste repositório (público). O
  artefato foi apagado e `BACKUP_ENABLED` voltou a `false`.

## 8. Off-site durável (recomendado para rede municipal)

O artefato do GitHub fica na mesma conta do código. Para adoção municipal, envie o mesmo
arquivo cifrado também a um bucket com **versionamento e Object Lock** (S3/Backblaze), fora
da conta do GitHub, imune a exclusão acidental. Faça isso no workflow do **repositório
privado**, com as credenciais em secrets de lá.
