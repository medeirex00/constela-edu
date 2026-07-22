# Análise de Escala da Sincronização — Constela Edu

Resposta à pergunta: **a arquitetura de sincronização aguenta uma rede municipal
(dezenas de escolas) sem reescrever nada?** Conclusão curta: **sim, a FILA já é
escalável por design; o que precisa de atenção é operacional (pool de conexões e
alta disponibilidade), não o modelo de sincronização.** Nenhum Redis ou fila nova
é necessário no momento.

---

## 1. Como funciona hoje (fatos do código)

- **Fila em banco.** Cada sincronização é uma linha em `sincronizacao_execucoes`
  com `status` (`fila` → `executando` → `concluida`/`erro`). A fonte da verdade é
  o Postgres, não a memória.
- **Worker embutido.** Uma thread de fundo no processo da API
  ([`scheduler.py`](../backend/app/sync/scheduler.py)) varre a fila a cada
  `SYNC_POLL_S` (30s) e processa até `SYNC_WORKERS` execuções por rodada.
- **`SYNC_WORKERS=1`** por processo, `WEB_CONCURRENCY=2` uvicorn workers → até
  **2 sincronizações simultâneas** no deploy atual. É deliberado: o login usa
  Chromium (Playwright), que é pesado em memória; limitar a concorrência protege a
  RAM da instância.
- **HTTP-first.** Após o login (sessão cacheada ~6h), a coleta é por HTTP
  (`httpx`), leve. O navegador só aparece na autenticação/renovação — o pico de
  memória é raro e curto.

## 2. Por que a fila é segura para escala horizontal (com evidência)

Três mecanismos garantem correção mesmo com **vários workers/réplicas** no mesmo
banco:

1. **Claim atômico (compare-and-swap).** Antes de executar, o worker roda
   `UPDATE ... SET status='executando' WHERE id=? AND status='fila'`
   ([`service.py:249`](../backend/app/sync/service.py)). Só **um** obtém
   `rowcount=1`; os outros veem `0` e desistem. **Nunca há sync duplicada**,
   mesmo que dois workers leiam a mesma linha.
2. **Anti-duplicação de tarefa no banco.** `enfileirar` é idempotente e há um
   **índice único parcial** `uq_sync_exec_ativa`: é impossível existir duas
   execuções ativas para a mesma (escola, plataforma). Clique duplo, scheduler +
   manual, ou múltiplas réplicas enfileirando ao mesmo tempo → uma só tarefa.
3. **Recuperação pós-crash.** Um redeploy no meio de uma sync deixa a linha em
   `executando`; o *reaper* ([`recuperar_execucoes_travadas`](../backend/app/sync/service.py))
   a devolve para a fila (com backoff/limite de tentativas) no próximo boot —
   também via UPDATE atômico, seguro entre réplicas.

**Consequência prática:** para escalar, basta rodar o mesmo código como um
serviço separado (ou mais réplicas) apontando para o mesmo Postgres. Nada muda no
código. O "worker separado" é uma decisão de *deploy*, não de reescrita.

## 3. Evidência de teste

- **Testes de concorrência** (determinísticos):
  [`tests/test_sync_concorrencia.py`](../backend/tests/test_sync_concorrencia.py)
  — claim de vencedor único, anti-duplicação, distribuição sem sobreposição.
  Mais o já existente `test_finalizar_orfas_no_boot` (crash recovery).
- **Harness de carga:**
  [`scripts/carga_sync.py`](../backend/scripts/carga_sync.py) — simula N escolas e
  K workers, mede vazão e **duplicação (tem de ser 0)**.
  Resultado local (SQLite, lógica) para 1/10/50/100 escolas: **0 duplicadas, 0
  perdidas** em todos os casos.

> **Limite de fidelidade (honestidade):** o SQLite serializa escritas, então o
> teste local valida a **lógica** do claim, não a **contenção real** do Postgres
> sob paralelismo. Os números de latência/throughput reais devem ser medidos no
> **staging Postgres** (§5).

## 4. Onde estão os limites REAIS (para uma rede municipal)

Não é a fila. São estes, por ordem de importância:

| Limite | Aos ~10 escolas | Aos ~50–100 escolas | Ação |
|--------|-----------------|---------------------|------|
| **Conexões do Postgres** | ok | **atenção** | Usar o *pooler* do Supabase (PgBouncer, porta 6543) na `DATABASE_URL`; hoje `DB_POOL_SIZE=10` × 2 workers = ~20 conexões diretas, e o plano gerenciado tem teto. |
| **Alta disponibilidade** | 1 instância basta | **ponto único** | 1 réplica no Railway = se cair às 3h, a janela de sync é perdida (o reaper reprocessa no boot). Para município, considerar 2 réplicas (a fila já suporta) + região com SLA. |
| **Janela noturna** | trivial | ok | Sync diária escalonada por `hora_local`. Mesmo 100 escolas a 2 simultâneas × ~30s ≈ 25 min — cabe folgado na madrugada. Evitar todas no mesmo minuto. |
| **Ranking ao vivo (Matific)** | ok | depende do Matific | Consulta em tempo real por request, com cache por worker. Muitos professores simultâneos → limite da API do Matific, não nosso. |
| **Memória (Chromium)** | ok | ok | `SYNC_WORKERS=1` mantém 1 navegador por processo. Só sobe na autenticação. |

## 5. Como medir com números reais (você, no staging)

Depois que o staging existir (ver [STAGING.md](STAGING.md)):

```bash
# Aponte para o Postgres do STAGING (banco descartável, NUNCA produção)
DATABASE_URL="postgresql+psycopg://.../staging" \
  python backend/scripts/carga_sync.py --escolas 100 --workers 8 --go
```

O script cria escolas de teste (prefixo `CARGA_TESTE_`), mede e **apaga tudo** no
fim. Ele se recusa a rodar se houver escolas reais no banco (proteção contra
apontar para produção por engano).

## 6. Recomendação

- **Piloto (1 escola) e rede pequena (até ~10 escolas):** a arquitetura atual
  atende **sem nenhuma mudança**.
- **Antes de crescer para dezenas de escolas:** (1) trocar a `DATABASE_URL` para o
  *pooler* do Supabase; (2) medir com o harness no staging; (3) avaliar 2 réplicas
  no Railway (a fila já é segura para isso).
- **NÃO implementar** Redis, Celery ou fila externa agora: adicionaria
  complexidade operacional sem ganho — o Postgres já entrega fila com exclusão
  mútua, dedup e recuperação. Reavaliar só se o harness no staging mostrar
  contenção real (o que não é esperado nessa faixa).
