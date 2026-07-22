# Guia passo a passo: testar a restauração do backup (para quem nunca fez)

Objetivo: provar, uma vez, que **conseguimos recuperar o banco a partir de um
backup** — o item que o encarregado de dados (DPO) da Secretaria vai perguntar.
Você **não precisa saber programar**. É copiar, colar e ler o resultado.

> ⏱️ ~30 minutos. Feito no **staging** (ou num banco de teste descartável),
> **nunca** na produção. Nada aqui apaga ou altera dados reais.

---

## Antes de começar — o que você vai precisar

1. Acesso ao **Supabase** (onde fica o banco).
2. O **Git Bash** já instalado neste computador (é onde você digita os comandos).
3. A senha de cifra do backup (a `BACKUP_PASSPHRASE` que você definir).

Se ainda não instalou o cliente do Postgres, faça uma vez:
- Baixe o **PostgreSQL** em <https://www.postgresql.org/download/windows/> e, no
  instalador, deixe marcado **"Command Line Tools"** (é o que traz `pg_dump` e
  `psql`). Não precisa instalar o servidor; só as ferramentas de linha de comando.

---

## Passo 1 — Criar um banco de teste "descartável" (dr_scratch)

Um banco vazio, separado, só para o teste. No **Supabase**:

1. Entre no projeto → menu **Database** → **… (mais opções)** ou o SQL Editor.
2. Rode este comando no **SQL Editor** para criar o banco de teste:
   ```sql
   CREATE DATABASE dr_scratch;
   ```
   (Se o seu plano não deixar criar outro banco, crie um **projeto Supabase
   novo e gratuito** chamado `constela-dr-teste` e use o banco dele.)
3. Guarde a **connection string** desse banco de teste. No Supabase:
   **Project Settings → Database → Connection string → URI**. Vai parecer:
   ```
   postgresql://postgres:SUA_SENHA@db.xxxx.supabase.co:5432/postgres
   ```

## Passo 2 — Pegar a connection string do banco de ORIGEM

O de origem é o **staging** (ou, na falta dele, o próprio banco de produção —
o teste **só lê**, não altera). Pegue a URI do mesmo jeito (Passo 1.2), do
projeto certo.

## Passo 3 — Rodar o teste (um comando só)

Abra o **Git Bash** na pasta do projeto (clique direito na pasta → *Git Bash
Here*) e cole isto, **trocando os três valores** pelas suas strings/senha:

```bash
SRC_DATABASE_URL="postgresql://postgres:SENHA@db.ORIGEM.supabase.co:5432/postgres" \
DR_SCRATCH_URL="postgresql://postgres:SENHA@db.TESTE.supabase.co:5432/dr_scratch" \
BACKUP_PASSPHRASE="a-senha-de-cifra-que-voce-escolher" \
  bash backend/scripts/dr_drill.sh
```

Aperte **Enter**. O script vai, sozinho:
1. fazer um backup do banco de origem;
2. cifrar e decifrar (prova que a cifra funciona);
3. restaurar no banco de teste `dr_scratch`;
4. comparar quantas escolas, alunos, notas etc. existem nos dois;
5. mostrar o resultado.

## Passo 4 — Ler o resultado

No final aparece uma tabela e uma dessas linhas:

- ✅ **`VEREDITO: PASSOU`** → o backup restaura **íntegro e completo**. É isso que
  queremos. Anote no `docs/DR-RUNBOOK.md` (seção 6) a **data de hoje** e quanto
  tempo levou (esse tempo é o seu **RTO**).
- ❌ **`VEREDITO: FALHOU`** → algo divergiu. **Me mande o texto que apareceu** que
  eu diagnostico. Não confie no backup até resolvermos.

## Passo 5 — Limpar (opcional)

O banco `dr_scratch` era só para o teste. Pode apagá-lo no Supabase:
```sql
DROP DATABASE dr_scratch;
```
(Ou deixe lá para o próximo teste — ele é sobrescrito a cada execução.)

---

## Perguntas comuns

**"Deu erro `pg_dump: command not found`."** → As ferramentas do Postgres não
estão instaladas. Faça a instalação do "Antes de começar".

**"Posso rodar na produção?"** → A origem pode ser produção (o script só LÊ dela).
Mas o **destino** (`DR_SCRATCH_URL`) tem de ser o banco de teste, nunca a
produção — o script se recusa a rodar se os dois forem iguais.

**"Preciso repetir?"** → Sim: uma vez agora, e de novo sempre que houver uma
mudança grande de banco. É rápido depois da primeira vez.
