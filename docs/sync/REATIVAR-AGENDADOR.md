# Reativar o agendador de sincronização: checklist

O agendador automático (Elefante Letrado e Matific) está **desligado em produção desde 17/09/2026**. Ele continua desligado por padrão: `SYNC_SCHEDULER_ENABLED=false`.

Este documento lista o que precisa estar pronto para religá-lo, com autorização do dono. O código não executa nenhum passo daqui: cada passo é uma ação humana. A mudança de variável de ambiente e o reinício do serviço são feitos pelo dono.

Por que não basta ligar a variável: o diagnóstico de 22/10 mostrou que, sem as correções, o agendador amplia os defeitos que hoje ficam escondidos.
- **S7:** sem teto de tempo, uma execução pode ficar presa.
- **S2/S3:** "concluída" sai com 0 aluno aplicado.
- **S16:** depois da rotação de chaves, a credencial fica ilegível mas aparece como válida.
- **S4:** se o recálculo falha, o ranking fica velho.

---

## 1. Como o código protege

| Situação | O que acontece |
|---|---|
| `SYNC_SCHEDULER_ENABLED=false` (padrão) | O agendador não sobe e nem chega a verificar nada. |
| `SYNC_SCHEDULER_ENABLED=true` | No boot, cada processo roda `prerequisitos_agendador` (`backend/app/sync/prerequisitos.py`). Se **um pré-requisito crítico falha**, o agendador **não sobe**. |
| Recusa no boot | O log registra em nível ERROR: `Agendador de sincronização NÃO iniciado: pré-requisito crítico falho — <id>: <motivo> \| ...`. A API segue normal e a coleta manual ("Sincronizar agora") continua funcionando. |
| `SYNC_SCHEDULER_FORCAR=true` | O agendador sobe mesmo com falha. O log registra em WARNING: `INICIADO À FORÇA`. A variável **nunca liga o agendador sozinha** e **não fura a trava do schema errado** no boot. |
| A própria verificação quebra (ex.: banco fora) | Conta como falha crítica: o agendador recusa subir, sem derrubar o app. |

**Quando a decisão é tomada:** uma vez por processo, no boot. Cada processo uvicorn (`WEB_CONCURRENCY`) decide por si. Mudou alguma coisa? É preciso reiniciar.

**Onde ver o resultado:** `GET /api/v1/sync/dashboard`, só para o admin global. O bloco `prerequisitos_agendador` traz:
- `habilitado`, `forcar` e `pode_iniciar`;
- `decisao_no_boot`, que pode ser `desligado`, `recusado`, `iniciado` ou `forcado`. `null` quer dizer que o `iniciar` não rodou neste processo (ex.: schema errado no boot);
- `criticos_falhos`;
- `verificacoes[]`, cada uma com `id`, `ok`, `critico` e `motivo`. O motivo traz só ids de escola, horários e contagens, sem nome nem segredo.

A verificação é **só leitura**: não cria agenda, não cancela execução, não fecha alerta e não chama as plataformas.

## 2. As verificações

| id | Crítico | O que confere | Como resolver |
|---|---|---|---|
| `teto_execucao` | sim | `SYNC_TETO_EXECUCAO_S` existe e é maior que 0. O padrão do contrato é 2700 s; a #407 levou ~17 min. | Implantar a versão com o teto. |
| `teto_coerente` | sim | `SYNC_TRAVADA_S` é maior que o teto, e o teto é maior ou igual a `SYNC_TIMEOUT_S`. | Com o teto de 2700 s, um `SYNC_TRAVADA_S` de 1800 s **não serve**: a limpeza de órfãs mataria uma coleta viva entre 30 e 45 min. O padrão da integração (fix/sync-integridade) já é 3600; confira se o ambiente não o sobrescreve com um valor menor. |
| `status_honesto` | sim | O serviço conhece os estados `concluida`, `parcial`, `sem_atualizacao`, `sem_dados` e `erro`. Lê de `service.ESTADOS_FINAIS` ou, na falta dele, do código. Também confere as colunas da migração 0039 no modelo **e no banco**: `qtd_linhas`, `qtd_em_revisao`, `qtd_falhas`, `recalculo_pendente` e `motivo`. | Implantar a versão e aplicar a 0039. |
| `selo_frescor` | sim | Existem `/ranking/frescor` e `frescor_ranking.frescor_da_escola`. | Já estão no c5e78d3. |
| `execucoes_presas` | sim | Nenhuma execução em `executando` além de min(teto, `SYNC_TRAVADA_S`). Nenhuma em `fila` sem sinal de vida além de `SYNC_TRAVADA_S`. | O reinício libera as órfãs antigas. Uma manual presa sai com um novo "Sincronizar agora". |
| `credenciais_legiveis` | sim | Toda integração que o agendador rodaria tem credencial que **decifra**. Isso inclui as agendas ativas não manuais e as credenciais sem agenda, que ganham agenda diária ao ligar. | Recadastrar pela tela Integrações depois da rotação de chaves. |
| `recalculo_sem_pendencia` | sim | Nenhum alerta `recalculo_pendente` aberto. Nenhuma execução com `recalculo_pendente=true` sem uma execução **posterior** da mesma integração em `concluida`/`parcial` com recálculo feito. Sem a coluna, a verificação não tem como conferir e **falha**. | Recalcular as notas da escola: "Recalcular agora" no aviso da tela Integrações (`POST /importacoes/recalcular`) ou uma nova coleta que aplique dado. O recálculo que dá certo fecha o alerta **e** zera a marca das execuções. Resolver o alerta à mão, sem recalcular, não solta. |
| `fuso_da_agenda` | sim | O fuso é `America/Sao_Paulo`. O cálculo real da agenda põe "03:00" em 06:00 UTC. A `proxima_execucao` de cada agenda ativa bate com o `hora_local` em Brasília. | Re-salvar a agenda desalinhada. Se aparecer a nota "UTC-3 fixo", instalar `tzdata`. |
| `horario_fora_do_backup` | sim | Cada agenda, do início até início + teto (pior caso), fica fora da janela do backup privado: **10:30–13:30 UTC = 07:30–10:30 em Brasília**. | Mudar o horário da agenda. |
| `workers_semaforo` | sim | `SYNC_WORKERS` ≥ 1 e `SYNC_POLL_S` ≥ 1. O semáforo das manuais é max(1, `SYNC_WORKERS`). O motivo informa o pior caso de coletas simultâneas: `WEB_CONCURRENCY` × (1 + `SYNC_WORKERS`). | Corrigir a variável e reiniciar. |
| `fila_da_agenda` | não (aviso) | No pior caso em série (uma coleta por vez, cada uma no teto), a fila não alcança o backup. | Espalhar os horários ao ampliar. Com teto de 45 min, cabem ~6 coletas em série entre 03:00 e 07:30 de Brasília. |
| `alcance_ao_ligar` | não (aviso) | Lista as agendas que rodariam. Avisa quem ganha **agenda diária às 03:00 automaticamente** (credencial sem agenda, via `garantir_agendas_diarias`). | Para um piloto de 1 escola, salvar antes a agenda das outras como manual/desligada. |

## 3. Checklist, na ordem

Não pule passos. Cada passo depende do anterior.

### Passo 1. Corrigir e implantar esta versão
- [ ] Os ramos de correção da sincronização (frentes A a E) estão integrados e revisados.
- [ ] O CI está verde: a suíte inteira coleta sem erro, e também em PostgreSQL.
- [ ] A migração 0039 foi aplicada (`alembic upgrade heads`), com upgrade e downgrade ensaiados antes em PG local.
- [ ] A produção está no commit novo, **provado pelo hash** do deploy/bundle. Não dizer "no ar" sem o hash.
- [ ] `SYNC_SCHEDULER_ENABLED` **continua `false`** neste passo.
- [ ] `SYNC_TETO_EXECUCAO_S` está definido (padrão 2700) e `SYNC_TRAVADA_S` é maior que o teto (ex.: 3600).
- [ ] No `/sync/dashboard`, estão ok: `teto_execucao`, `teto_coerente`, `status_honesto`, `selo_frescor` e `workers_semaforo`.

### Passo 2. Rotação de credenciais do incidente concluída e recadastro feito
- [ ] A rotação do incidente de 21/10 está encerrada pelo dono, com chaves e segredos trocados.
- [ ] As credenciais do Elefante e do Matific foram recadastradas em cada escola que tem credencial, e o "Testar" da tela passou.
- [ ] No painel, `credenciais_legiveis` está ok.

Atenção: credencial **legível** não é credencial **válida**. A validade é provada pelo "Testar" e pela primeira coleta.

### Passo 3. Uma semana de coletas manuais com status honesto (≥ 5 dias úteis)
- [ ] Em todo dia útil, houve coleta manual ("Sincronizar agora") nas escolas com credencial, acompanhada.
- [ ] Toda execução terminou num estado do contrato, e nenhuma ficou em `executando` (`execucoes_presas` ok).
- [ ] `concluida` só aparece com alunos aplicados > 0.
- [ ] `parcial` vem com o alerta `coleta_parcial`.
- [ ] Nenhum `erro` ficou sem explicação.
- [ ] Nenhum `recalculo_pendente` (`recalculo_sem_pendencia` ok).
- [ ] `qtd_alunos` é igual aos alunos distintos e bate com a plataforma, em contagens por turma conferidas pelo dono.
- [ ] A duração máxima observada ficou abaixo de 50% do teto. Se não ficou, rever o teto antes de seguir.
- [ ] O selo `/ranking/frescor` mostra dado de hoje ou de ontem.
- [ ] A semana está registrada: data, escola, plataforma, status, alunos e duração.

### Passo 4. Ligar em 1 escola
- [ ] A escola piloto foi escolhida (ex.: a 17, que já era coletada à mão).
- [ ] Nas **outras** escolas com credencial, a agenda foi salva como manual/desligada. Sem isso, o agendador cria agenda diária às 03:00 para elas na primeira rodada. Conferir em `alcance_ao_ligar`.
- [ ] A agenda da piloto é diária e fica fora da janela do backup (`horario_fora_do_backup` ok). O padrão é 03:00 de Brasília, que é 06:00 UTC.
- [ ] No `/sync/dashboard`: `pode_iniciar=true`, `criticos_falhos=[]`, e `alcance_ao_ligar` lista só a piloto.
- [ ] O dono definiu `SYNC_SCHEDULER_ENABLED=true` no ambiente, com `SYNC_SCHEDULER_FORCAR` ausente ou `false`, e reiniciou o serviço.
- [ ] O log de boot de **cada processo** diz "todos os pré-requisitos críticos ok".
- [ ] No painel: `decisao_no_boot="iniciado"` e `scheduler_ligado=true`.

Se aparecer "NÃO iniciado": ler o motivo no log ou no painel, corrigir e reiniciar. **Não usar o FORCAR para "passar".**

### Passo 5. Acompanhar (≥ 7 dias)
- [ ] Todo dia nasce uma execução de origem `scheduler` no horário da agenda (06:00 UTC para 03:00 de Brasília), e ela termina antes do teto.
- [ ] Há uma execução por agenda por dia. Com mais de um processo, o claim é atômico: não pode haver duplicata.
- [ ] Nenhuma coleta cruzou o backup privado do dia. Conferir o horário real do backup.
- [ ] O status é honesto, as contagens foram conferidas, o frescor do ranking está em dia e os alertas foram tratados.

### Passo 6. Ampliar
- [ ] Ativar uma escola, ou poucas, por vez, pela agenda na tela. Repetir o passo 5 a cada ampliação.
- [ ] Espalhar os horários (`fila_da_agenda` ok) e manter `horario_fora_do_backup` ok.

## 4. Desligar (reversão)

- O dono define `SYNC_SCHEDULER_ENABLED=false` e reinicia o serviço.
- As execuções que só o agendador rodaria são **canceladas com registro** no boot e na leitura do `/status` (`liberar_fila_sem_agendador`). Isso vale para agendadas, novas tentativas e manuais órfãs. Nenhuma é apagada.
- Uma execução que já está em andamento termina, ou para no teto.

## 5. Sobre o `SYNC_SCHEDULER_FORCAR`

- Só se usa com decisão **escrita** do dono, com motivo e prazo, registrando qual pré-requisito foi ignorado. Depois, remover.
- Nunca usar para contornar `status_honesto`, `teto_execucao`, `teto_coerente` ou `credenciais_legiveis`. Esses são exatamente os defeitos que o agendador amplia.
- O valor é **texto**. Só `true`, `1`, `sim`, `yes` e `on` forçam; qualquer outro valor não força e não derruba o boot.

## 6. Limites conhecidos

- **Janela do backup:** é **observada**, não lida de nenhuma configuração. Vem das execuções do backup privado de 21/10 11:44 e 22/10 11:47 UTC, com folga. Fica na constante `JANELA_BACKUP_UTC` em `prerequisitos.py`. Se o backup mudar de horário, atualize a constante e este documento.
- **Verificação só no boot:** um problema que surja depois (ex.: uma execução presa) não desliga o agendador já ligado. Ele aparece no painel, e a limpeza de órfãs do próprio agendador trata as execuções presas.
- **Marca de recálculo:** a marca é superada por uma execução posterior em `concluida`/`parcial` com recálculo feito, ou zerada por um recálculo que dá certo (`service.resolver_recalculo_pendente`, chamado pela sync e pelo `/importacoes/recalcular`). Resolver só o alerta, sem recalcular, mantém a marca.
- **WEB_CONCURRENCY:** o processo só enxerga essa variável se ela estiver no ambiente. Sem ela, a verificação assume o padrão do `entrypoint.sh`, que é 2.
- **Agendas semanais:** a janela é avaliada como se fossem diárias (pior caso).
- **Ganchos de outras frentes:** `status_honesto`, `teto_*` e `recalculo_sem_pendencia` dependem de partes que vêm de outras frentes da correção de 22–23/10: teto, estados, colunas da 0039 e alerta `recalculo_pendente`. Sem elas, essas verificações **falham**, e esse é o lado seguro.
