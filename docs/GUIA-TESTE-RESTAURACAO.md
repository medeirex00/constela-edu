# Guia passo a passo: testar a restauração do backup (para quem nunca fez)

Objetivo: provar que **conseguimos recuperar o banco a partir do backup guardado**.
É o item que o encarregado de dados (DPO) da Secretaria vai perguntar. Você **não
precisa saber programar**: é copiar, colar e ler o resultado.

> ⏱️ Cerca de 20 minutos, no seu computador. Nada aqui lê nem altera a produção. O
> banco de teste é um banco **descartável e local**, apagado no fim. A senha é
> digitada só no seu terminal, **sem aparecer na tela**. Nunca cole a senha em
> chat, e-mail ou documento, nem no próprio comando.

Este guia é a versão "para iniciantes" do §3 do [`DR-RUNBOOK.md`](DR-RUNBOOK.md).
Cada bloco abaixo começa redefinindo as pastas: se você fechar e reabrir o Git Bash
no meio, é só colar o próximo bloco.

---

## Antes de começar — o que você vai precisar

1. Acesso ao repositório **privado** de backups: `github.com/medeirex00/constela-backups`.
   O backup fica **só** lá. Neste repositório (`constela-edu`) não há backup em uso,
   e não se dispara backup aqui.
2. Um clone desse repositório privado no computador (é onde estão os scripts de conferência).
3. O **Git Bash**.
4. O **PostgreSQL 17** (cliente e servidor). Baixe em
   <https://www.postgresql.org/download/windows/>. O teste cria um banco próprio e
   descartável; ele **não usa** nenhum PostgreSQL que já esteja rodando na máquina.
5. A senha do backup, do seu gerenciador de senhas.

---

## Passo 1 — Baixar o backup do dia

No repositório **privado**: **Actions** › "Backup do banco (produção)". Abra a execução
**verde** mais recente e baixe o artefato `backup-postgres-…`. Salve-o na pasta
`restauracao-teste`, dentro da sua pasta de usuário (crie a pasta se precisar).

> O arquivo é cifrado, mas é a base inteira. A pasta é apagada no Passo 5.

## Passo 2 — Conferir que o arquivo chegou inteiro e que a SUA senha abre o backup

Abra o **Git Bash** na pasta do clone do repositório privado e cole:

```bash
T="$HOME/restauracao-teste"
unzip -q "$T"/backup-postgres-*.zip -d "$T" && (cd "$T" && sha256sum -c SHA256SUMS)
ARQ="$(ls "$T"/constela_*.sql.gz.enc | head -1)"
bash scripts/conferir_senha_local.sh "$ARQ" "$T/SHA256SUMS"
```

O script pede a senha **sem mostrar o que você digita**. O resultado esperado é:
`OK: a senha do cofre abre …, o gzip está íntegro e o dump está completo.`

## Passo 3 — Criar o banco de teste descartável

```bash
T="$HOME/restauracao-teste"; PG17="/c/Program Files/PostgreSQL/17/bin"
"$PG17/initdb" -D "$T/cluster" -U restauracao --auth=trust -E UTF8
"$PG17/pg_ctl" -D "$T/cluster" -o "-p 55433 -c listen_addresses=127.0.0.1" -l "$T/pg.log" -w start
"$PG17/createdb" -h 127.0.0.1 -p 55433 -U restauracao restauracao_teste
```

## Passo 4 — Restaurar e conferir

```bash
T="$HOME/restauracao-teste"; PG17="/c/Program Files/PostgreSQL/17/bin"; ARQ="$(ls "$T"/constela_*.sql.gz.enc | head -1)"
read -rsp "Senha do backup: " BACKUP_PASSPHRASE; echo; export BACKUP_PASSPHRASE
PATH="$PG17:$PATH" RESTORE_DATABASE_URL="postgresql://restauracao@127.0.0.1:55433/restauracao_teste" \
  bash scripts/verificar_restauracao.sh "$ARQ"
unset BACKUP_PASSPHRASE
```

- ✅ Termina com **`OK: o backup decifra, aplica sem erro e traz o schema com a versão de
  migração.`** e mostra quantas tabelas e linhas voltaram. Compare esses dois números com
  os que aparecem no passo "Ensaio de restauração" da mesma execução no Actions. Anote no
  `DR-RUNBOOK.md` (§7) a **data** e quanto tempo levou: esse é o seu **RTO**.
- ❌ Aparece **`FALHOU`**: não confie no backup até resolver. O script mostra só um código
  de erro, nunca o conteúdo; repasse esse código.

## Passo 5 — Limpar (obrigatório)

```bash
T="$HOME/restauracao-teste"; PG17="/c/Program Files/PostgreSQL/17/bin"
"$PG17/pg_ctl" -D "$T/cluster" stop -m fast; rm -rf "$T"; ls "$T" 2>/dev/null || echo "limpo"
```

A última linha tem de dizer **`limpo`**. Se aparecer algum arquivo, rode o bloco de novo.

---

## Perguntas comuns

**"Deu `command not found` em `initdb`, `pg_ctl` ou `psql`."** → O PostgreSQL 17 não está
instalado, ou está em outra pasta: ajuste o `PG17`. Veja "Antes de começar".

**"Posso usar a produção ou o Supabase como banco de teste?"** → Não. O teste restaura
num banco **local, vazio e com 'restaura' ou 'test' no nome**. O próprio script recusa
qualquer outro.

**"E o `dr_drill.sh`?"** → Não use: ele está quebrado e não testa o backup guardado. Ver o
`DR-RUNBOOK.md` (§6).

**"Preciso repetir?"** → Sim: a cada mudança grande de banco, e pelo menos uma vez por
mês durante o piloto.
