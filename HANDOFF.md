# Handoff do Constela

Retrato do checkout local em **19/11/2026**, no PC, com as referências Git já disponíveis nesta pasta. Os registros de operação abaixo trazem a data da última evidência encontrada. A versão servida e as configurações atuais dos provedores ainda precisam de conferência nos painéis.

## Estado do checkout

| Área | Situação |
| --- | --- |
| **Constela Edu** | O web de gestão fica em `apps/web`, o mobile Expo em `apps/mobile` e o desktop Tauri em `apps/desktop`. A API FastAPI fica em `backend` e os contratos compartilhados em `packages/core`. Há trabalho local em andamento na interface, no cálculo por dimensão, nos rankings, nos relatórios e na integração com o Elefante. Consulte [README.md](README.md), [Arquitetura](docs/ARQUITETURA.md) e [Arquitetura 2](docs/spec-arquitetura-2.md). |
| **Constela Quest** | O PWA fica em `apps/quest`, com cliente e tipos em `packages/quest-core` e módulo da API em `backend/app/quest`. A árvore de trabalho inclui o loop de missões, progresso e currículo da Fase 1, com código ainda fora do histórico da branch atual. O congelamento de 20/07 é da **documentação** 1.0 RC. Consulte a [arquitetura do Quest](docs/quest/README.md), o [release documental](docs/production/RELEASE-1.0-RC.md) e o [plano de produção](docs/production-roadmap/START_HERE.md). |
| **Constela Hub** | A arquitetura do Quest define o Hub como portal de entrada para Edu e Quest. O checkout não contém um workspace do Hub, um manifesto próprio ou uma configuração de deploy identificável para ele. A localização do código e seu estado de publicação estão por confirmar. [Ecossistema](docs/quest/README.md#ecossistema) |
| **Branch corrente** | `feat/elefante-dificuldade-livro-v1` em `3e3c512d`, sem upstream configurado, com alterações preexistentes rastreadas e arquivos ainda fora do Git no Edu web, mobile, Quest, backend, pacotes, documentação e configuração do Claude. Bancos SQLite locais e exportações também estão na pasta. Preserve esse trabalho antes de trocar de base. |
| **Bases Git locais** | `main` local em `f69c5acb`, quatro commits atrás da referência local `origin/main` em `dd5f2ef9` (03/11). Em relação a essa referência, o HEAD corrente tem 31 commits exclusivos e fica atrás em 13. O registro de 10/11 descreve a publicação da identidade v2 e navegação da Secretaria, com reconstrução do web em 03/11. [Pendências do responsável (10/11)](exports/constela-pendencias-do-dono-2026-11/O-QUE-DEPENDE-DE-VOCE.md) |

O checkout atual tem a migração local `0029_curriculo_fase1.py` ainda fora do Git. Ela e a revisão rastreada `0030_livro_identidade_oficial` declaram `0028_nota_institucional` como pai. Pela leitura dos arquivos, os terminais locais são `0029_curriculo_fase1` e `0033_identidade_aposentada`. A referência `origin/main` registra revisões até `0039_execucao_contabilidade`. O [migrador da aplicação](backend/app/core/migracoes.py) já aplica `heads` no plural, enquanto a verificação PostgreSQL no [CI](.github/workflows/ci.yml) chama `get_current_head()`. Confira `alembic heads` a partir de `backend/` e valide o CI antes de integrar as linhas. [Plano de cadastro, nota sobre migrações](docs/cadastro/PLANO-automacao-cadastro-municipios-escolas.md)

## Branches

| Branch ou referência | Para que serve |
| --- | --- |
| `feat/elefante-dificuldade-livro-v1` · `3e3c512d` | Checkout em uso. Dificuldade por livro e cobertura das questões do Elefante nos relatórios. A árvore de trabalho também carrega frentes do Edu e do Quest. |
| `fix/pos-publicacao` · `e7ff3ee1` | Integração local pós-publicação, com correções em sincronização, identidade, relatórios, telas e desempenho da Secretaria. O registro de 10/11 se refere ao marco anterior `6de28b5c`. A ponta atual está 555 commits à frente de `origin/main`, sem diferença em `backend/alembic/versions` entre essas duas referências. Revalide o candidato efetivo. |
| `feat/navegacao-inteligencia` · `5d7ab778` | Navegação, identidade v2 e desempenho da Secretaria. A referência de produção registrada localmente recebeu a entrega condensada em `1766ab33`, seguida da reconstrução `dd5f2ef9`. |
| `feat/indicadores-oficiais` · `34f1a23c` | Indicadores oficiais e importação com prévia e reversão. A ponta já é ancestral de `origin/main`. |
| `prontidao/demo-jacarei` · `a518ff4e` | Preparação da demonstração com cenários da Secretaria, rede e varredura em celular. |
| `prontidao/e97`, `prontidao/e97y`, `prontidao/e97z` | Linhas de revisão e integração de segurança, sincronização e operação. Os ramos `ci/prontidao-*`, `arquivo/e97y-*` e `rc/*` guardam candidatos, ensaios ou pontos de retorno. |
| `publicacao/rollback-34f1a23-pos-web` · `ac3d5fdc` | Referência de retorno citada no roteiro de 10/11 para a publicação web. O procedimento de troca de credenciais tem instruções próprias de reversão. |
| `recuperacao/senha-backups` · `2d1bee0e` | Diagnóstico e transferência de backups históricos, reservado à recuperação. |

O inventário reúne 171 branches locais e 32 referências locais de acompanhamento de `origin` que ficaram fora da ancestralidade direta de `origin/main`. Uma entrega por squash ou cherry-pick pode já conter o trabalho correspondente. O estado de PRs no GitHub ficou por verificar. Para refazer o inventário local, use `git branch -avv`, `git branch -a --no-merged origin/main` e `git worktree list`.

## Deploy e operação

| Serviço | Configuração registrada e checagem necessária |
| --- | --- |
| **Vercel** | O projeto Edu `constela-edu-web` serve `www.constelaedu.com`. O [manifesto raiz](vercel.json) instala as dependências com `npm install --legacy-peer-deps`, roda `npm run build --workspace=@constela/web`, publica `apps/web/dist` e faz fallback de rotas SPA. `VITE_API_URL` deve apontar para `https://api.constelaedu.com/api/v1`. Em 03/11, a atribuição automática de domínios de produção foi desativada. O push na `main` gerava um build, com promoção manual para o domínio. O backend usa `quest.constelaedu.com` como URL pública do Quest e o Quest tem build próprio em `apps/quest`. Confirme no painel o projeto, vínculo e destino de build do Quest. [Pendências do responsável (10/11)](exports/constela-pendencias-do-dono-2026-11/O-QUE-DEPENDE-DE-VOCE.md) |
| **Railway** | Serviço `@constela/backend`, a partir da `main`, com [Dockerfile em backend](backend/Dockerfile). A inspeção de 18/10 registrou `api.constelaedu.com` na porta 8080, start command próprio e migração na partida do app no modo então configurado. O registro de 03/11 lista seis serviços duplicados com auto-deploy desativado e o backend como único serviço com auto-deploy na `main`, com `Wait for CI` desligado naquela data. Confira o comando efetivo, `PORT`, `ENV`, healthcheck `/api/health/ready` e pre-deploy antes de mudança de ambiente. Ative o modo de produção somente com o caminho de migração já ensaiado para o deploy efetivo. [Inspeção de 18/10](docs/indicadores/RELATORIO-P4-inspecao-railway.md) · [Sequência operacional](docs/indicadores/SEQUENCIA-operacional.md) · [Pendências de 10/11](exports/constela-pendencias-do-dono-2026-11/O-QUE-DEPENDE-DE-VOCE.md) |
| **Supabase** | PostgreSQL gerenciado compartilhado por Edu e Quest. O Railway usa `DATABASE_URL`. A inspeção de 18/10 registrou o session pooler na porta 5432. Schema via Alembic. Antes da próxima publicação, confira conexões do pool, réplicas/processos da API, backups nativos, retenção/PITR e restauração de backup privado. O plano de staging prevê banco, chaves e dados fictícios próprios. [Inspeção de 18/10](docs/indicadores/RELATORIO-P4-inspecao-railway.md) · [Runbook de recuperação](docs/DR-RUNBOOK.md) · [Staging](docs/STAGING.md) |
| **DNS na Hostinger** | A Hostinger é a referência informada para administrar o DNS de `constelaedu.com`. O checkout identifica `www` para o Edu, `api` para a Railway e `quest` como URL pública do Quest. Os nameservers, o destino do domínio raiz e os tipos, valores e TTLs dos registros precisam ser conferidos no hPanel e comparados com os domínios configurados na Vercel e na Railway. |
| **CI/CD** | [CI](.github/workflows/ci.yml), [segurança](.github/workflows/security.yml), [backup](.github/workflows/backup.yml) e [deploy](.github/workflows/deploy.yml) estão versionados. O workflow de deploy exige `DEPLOY_ENABLED=true`. Os rótulos de ambiente são `staging` e `producao`. O fluxo pelas integrações Git dos provedores é o documentado para produção. A ativação do workflow e a proteção da `main` dependem de verificação nas configurações do GitHub. [CI/CD](docs/CI-CD.md) · [Pendências de 10/11](exports/constela-pendencias-do-dono-2026-11/O-QUE-DEPENDE-DE-VOCE.md) |

## Pendências e prazos

| Ordem | Pendência e condição de conclusão | Prazo ou janela registrada |
| --- | --- | --- |
| 1 | **Responsável pela infraestrutura**. Conferir os serviços duplicados antes de rotacionar credenciais. Executar o roteiro de novembro e, na sequência, verificar login de Admin Global, Secretaria e Coordenação e recadastrar/testar as integrações de cada escola. [Roteiro da troca](exports/constela-troca-de-credenciais-2026-11/ROTEIRO-TROCA-DE-CREDENCIAIS.md) | Prioridade mais urgente no registro de 10/11. Sem data marcada. Janela sugerida domingo a quinta, 21h30–23h30, com a coordenação disponível na manhã seguinte. Estimativa de 1h15 à noite e cerca de dez minutos por escola na manhã seguinte. |
| 2 | **Publicação pós-correções do Edu**. Validar a ponta atual de `fix/pos-publicacao`, confirmar capacidade do pool na Supabase e processos na Railway, conferir CI e autorização para publicar. A ordem do roteiro é API, promoção do web na Vercel e testes de login. [Pendências de 10/11](exports/constela-pendencias-do-dono-2026-11/O-QUE-DEPENDE-DE-VOCE.md) | Após a rotação, o teste de login e um dia de uso normal. A troca e a publicação têm janelas separadas. |
| 3 | **Ajustes operacionais do Edu**. Depois da publicação, tratar série de turma, Lista Piloto e fila de revisões de identidade pelas telas. Conferir a política de criação de fichas nas escolas com Lista Piloto antes de nova coleta. O arquivo de pendências contém os casos para o responsável autorizado. [Pendências de 10/11](exports/constela-pendencias-do-dono-2026-11/O-QUE-DEPENDE-DE-VOCE.md) | Após a publicação da rodada. Sem data de calendário. |
| 4 | **Sincronização automática**. Segue desligada no último registro. Depende da rotação, validação de credenciais, publicação das correções, coletas manuais e escolha de uma escola piloto. O guia mais recente está em `fix/pos-publicacao:docs/sync/REATIVAR-AGENDADOR.md`. | Coletas manuais fora da janela de backup de 07h30–10h30 em Brasília. Ainda cabe ao responsável escolher o critério de reativação entre cinco dias úteis e 14 dias consecutivos com pelo menos 95% de sucesso. |
| 5 | **Continuidade da operação**. Conferir segunda cópia externa e ensaio de restauração, acesso ao cofre, monitoração, proteção da `main` e staging isolado. O registro de 10/11 também deixa a cifra do disco deste PC e a promoção automática na Vercel como decisões do responsável. [Continuidade](docs/CONTINUIDADE.md) · [Staging](docs/STAGING.md) · [Monitoramento](docs/MONITORAMENTO-ATIVACAO.md) · [Pendências de 10/11](exports/constela-pendencias-do-dono-2026-11/O-QUE-DEPENDE-DE-VOCE.md) | Sem datas confirmadas. |
| 6 | **Quest**. Reconciliar as migrações antes de integrar currículo e jogo. Na produção do jogo, ratificar o ADR do rig-base, validar Blender → GLB → runtime e preservar o ledger em backup/restauração. A vertical de sistemas pode avançar com o avatar procedural. [Promoção da RC](docs/production/RELEASE-1.0-RC.md) · [Marcos e sprints sugeridos](docs/production-roadmap/02-dependencias-milestones-sprints.md) | O plano sugere S0–S5 em seis quinzenas, da assinatura inicial à primeira versão jogável. Sem início ou lançamento confirmado. |
| 7 | **Hub**. Identificar checkout, projeto de deploy e domínio, depois registrar o estado do portal. [Ecossistema](docs/quest/README.md#ecossistema) | Sem prazo localizado. |

## Inventário de referências locais

A ponta indica o assunto do commit mais recente na referência. A coluna de origem mostra se o nome existe na cópia local ou na referência local de acompanhamento de `origin`. Quando as duas pontas coincidem, a mesma linha representa ambas.

<details>
<summary>Funcionalidades, operação e outros ramos (63)</summary>

| Branch | Ponta | Origem | Assunto do commit |
| --- | --- | --- | --- |
| `arquivo/e97y-ci-1a710c5` | `08c5eea4` | local | validação do candidato 1a710c5 no CI real — árvore única, sem histórico |
| `arquivo/e97y-rollback-1a710c5` | `3b707cea` | local | volta a árvore do main para 34f1a23 (rollback do candidato) |
| `arquivo/e97y-squash-1a710c5` | `ecd4863c` | local | correções da sincronização, P15, P18 e painel global (candidato 1a710c5) |
| `bkp/pre-split-branch` | `aca61c7b` | local | "Conquistas de aprendizado" do aluno na Carreira |
| `ci/ensaio-restauracao` | `b32bb940` | local + origin | contagem à prova de nome de tabela e de contagem incompleta |
| `ci/prontidao-e97` | `b3633890` | local | prontidao/e97 @6fed992 no ramo de CI (só validação; revisão independente + integração de 26/10) |
| `ci/prontidao-e97y` | `d243bdd3` | local | validação do candidato a508768 no CI real — árvore única, sem histórico |
| `docs/backup-so-no-privado` | `1500ff50` | local | restauração de emergência não publica banco vazio nem aberto à API; senha do banco fora do argv |
| `entrega/identidade-visual-v2` | `4c76c538` | local | identidade visual v2 do Constela Edu (app web inteiro) |
| `feat/analise-educacional` | `a3a813ce` | local | análise educacional integrada e painel público responsivo |
| `feat/decisoes-dono-2026-10-12` | `77f7ff75` | local + origin | a rodada do agendador é testada isolada e na ordem, sem depender do banco |
| `feat/elefante-dificuldade-livro-v1` | `3e3c512d` | local | legenda das Questões diz "intervalo medido pelas coletas", não "cobertura disponível" |
| `feat/identidade-automatica` | `547d0d80` | local + origin | erro de uma letra só liga em sobrenome do meio; sem corpus de prenomes |
| `feat/identidade-consolidacao` | `44ca8ae9` | local + origin | hierarquia das travas diz o que o código faz e o vigia cobre a consolidação e o /resolver |
| `feat/identidade-visual-v2` | `c2f83c83` | local | v2 — efeitos colaterais vistos na conferência das capturas finais |
| `feat/navegacao-inteligencia` | `5d7ab778` | local | painel da rede, destaques e análise da escola em menos consultas |
| `feat/perfis-acesso` | `07849236` | local + origin | correções da revisão final (isolamento, UX, performance, CSP) |
| `feat/suporte-coordenacao` | `529f6f83` | local + origin | declara os usos de nota_geral que o Suporte introduz |
| `fix/ci-verde` | `a77925ed` | local + origin | a reconferência da auditoria roda sem DATABASE_URL no ambiente |
| `fix/pontuacao-consistencia` | `7b20234f` | local + origin | Fases fora dos rankings por período e das médias; Matific contado no ano |
| `fix/pos-publicacao` | `e7ff3ee1` | local | Placar ao vivo de um ano letivo encerrado liga a linha da formanda à ficha dela |
| `fix/ranking-evolucao-justo` | `99e85340` | local | evolução mede crescimento no período, não acumulado de vida |
| `fix/secretaria-permissoes-main` | `59f0afa8` | local | evolução individual dá 404 à Secretaria desde 73f9499 |
| `fix/seguranca-contas-professor` | `f0239113` | local | professor mantém a evolução só dos alunos das próprias turmas (decisão de 03/08) e testes que travam o escopo |
| `fix/sync-a-nucleo` | `ae1f8cf0` | local | devolve o espaço de _RODAPES que a ddc07f7 tirou sem querer |
| `fix/sync-b-identidade` | `4938759d` | local | integridade de identidade e turma também em PostgreSQL local |
| `fix/sync-c-resultados` | `a7725f0c` | local | Questões por período saem da diferença entre coletas; coleta datada fica pendente |
| `fix/sync-d-web` | `9708dea1` | local | lote manual mostra quando o recálculo final falha |
| `fix/sync-e-agendador` | `46d4effd` | local | checklist objetiva para reativar o agendador |
| `fix/sync-integridade` | `5e388b60` | local | a linha do teste do motivo 'turma_nao_cadastrada' traz o campo essencial |
| `hotfix/rls-todas-as-tabelas` | `bd777595` | local | o workflow de backup recusa rodar em repositório público |
| `marco/pos-publicacao-0fa697ce` | `0fa697ce` | local | catraca do DADOS_DIR dos E2E confere a linha do próprio DADOS_DIR, não o arquivo inteiro |
| `marco/pos-publicacao-6de28b5c` | `6de28b5c` | local | a mesma conta em duas turmas do Placar é uma linha da prévia, como no backend |
| `marco/pos-publicacao-9082e298` | `9082e298` | local | o teste do certificado com nome longo usa escola inventada |
| `prontidao/demo-jacarei` | `a518ff4e` | local | fluxos da demo, rede da Secretaria e varredura com celular |
| `publicacao/navegacao-rollback-34f1a23` | `bd52e031` | local | volta a árvore de 34f1a23 (desfaz o candidato 5d7ab77) |
| `publicacao/rollback-34f1a23-pos-web` | `ac3d5fdc` | local | volta a árvore de 34f1a23 (desfaz a publicação do 1766ab3) |
| `rc/auditoria-2026-10-20` | `adeccbf0` | local | web em job separado do backend; EXIGIR_CI_VERDE falha fechado; emergência sem Rollback/Redeploy |
| `rc/base-agentes` | `55279837` | local | espelho das rotas guardadas com a trava da Secretaria (RotaSemSecretaria) |
| `rc/dependencias-upload-cicd` | `c5e78d34` | local | pypdf 6.20.1 → 6.21.2 (GHSA-5hx5-vpf9-5wcv publicado depois do 6.20.1) |
| `rc/docs` | `9ba77a05` | local | pendências por responsável e índice do pacote |
| `rc/exportacao-e-backup` | `6ece2713` | local | relatório com a validação final em adeccbf, a segurança do CI e as vulnerabilidades por alcance |
| `rc/infra` | `007a55de` | local | log de acesso volta a aparecer; --no-access-log opcional |
| `rc/ponto-retorno-f0d2963` | `f0d2963e` | local | exportação inexistente vira SKIP, não falha falsa |
| `rc/quest` | `c56f4f10` | local | avaliação do token no localStorage e de MFA para perfis privilegiados |
| `rc/rankings` | `99847cb2` | local | histórico dos rankings — notas sobrescritas e retratos do mesmo dia |
| `rc/sync` | `1648800e` | local | coleta das plataformas — limites reais, estados, alternativas e critérios |
| `rc/ui` | `35041212` | local | no celular o nome do aluno não quebra no meio da palavra |
| `recuperacao/senha-backups` | `2d1bee0e` | local + origin | diagnostico e transferencia dos backups historicos (NAO FAZER MERGE) |
| `rev/em-dia-c` | `4369d8cc` | local | fila de revisão vazia não diz "0 contas aguardam" |
| `rev/escola-cruzada` | `b5ad6502` | local | escola externa — revisão e95, riscos para decisão e suposições |
| `rev/etapa3` | `1de3d314` | local | no rev/etapa3, o sinal da forma C nas métricas é o do banco |
| `rev/metricas-sync` | `8b809806` | local | prazo, vários workers, regras sugeridas e METRICS_PUBLICO |
| `wip/ci-pg` | `d0d818c4` | local | testes PostgreSQL rodam de verdade num banco descartável do próprio job |
| `wip/d1-back` | `26b4e1f3` | local | pódio do modo local é a lista oficial, sem quem não concorre |
| `wip/d1-mobile` | `69a0505f` | local | aba da matéria lista "Ainda não aferidos" — a criança sem dado não some do app |
| `wip/d1-web` | `918926da` | local | matérias pelo contrato da escola, sem nota congelada de quem saiu da classificação |
| `wip/d2-teto` | `ce8fd2c2` | local | Ranking de Matemática conta as estrelas do teto, como a premiação |
| `wip/d3-matias` | `dce167de` | local | gêmeas na mesma Lista Piloto e a triagem não resolvem sozinhas uma letra no prenome (decisão 3) |
| `wip/d4-ideb` | `69267eb9` | local | importar e excluir IDEB/SAEB só pelo admin global e pela Secretaria da rede |
| `wip/d5-promocao` | `3c361fac` | local | promoção a Secretaria invalida a senha e exige link de redefinição |
| `fix/seguranca-contas-professor` | `e1956d43` | origin | promoção a Secretaria derruba sessões e links pendentes |
| `validacao/integracao-2026-10-11` | `5963f5fd` | origin | integração local: fix/ci-verde (teste da auditoria sem DATABASE_URL) |

</details>

<details>
<summary>Auditoria e correções pós-publicação (44)</summary>

| Branch | Ponta | Origem | Assunto do commit |
| --- | --- | --- | --- |
| `fix/aud-alunos` | `4d0833db` | local | nome de turma ou de escola colado com caractere invisível entra limpo e não derruba mais a exportação Excel |
| `fix/aud-auth` | `0e796f9a` | local | o "Aguarde N minuto(s)" do bloqueio arredonda para cima |
| `fix/aud-imp` | `91f0e277` | local | "Criar novo aluno" recusado por letra ilegível mostra o motivo no painel, sem dizer que a lista mudou |
| `fix/aud-impweb` | `9daecb75` | local | o aviso de turmas que não carregaram no lote diz só o efeito real |
| `fix/aud-infra` | `980ba223` | local | o erro de validação não devolve mais a chave longa que o cliente mandou |
| `fix/aud-misc` | `6c2fc35b` | local | prazo total de verdade nas chamadas do assistente ao provedor externo |
| `fix/aud-mobile` | `6e7e0dce` | local | Scanner diz que não reconhece o endereço, sem afirmar que não é do Constela |
| `fix/aud-per` | `5c19486a` | local | certificados da web não quebram a CI a partir de 2027 (relógio fixo em 2026) |
| `fix/aud-rank` | `679d42bc` | local | registra que o bônus das conquistas ainda põe em 1º quem não tem dado do ano |
| `fix/aud-rel` | `0b9d8c24` | local | arte do certificado com a fila de PDFs cheia pede "tente de novo", não vira o Geral de mérito |
| `fix/aud-sync` | `d00b48c4` | local | com a política "bloquear", o aviso do professor sai uma vez por turma e só quando a turma está sem titular |
| `fix/aud2-analise` | `0a522c6f` | local | ano letivo da Secretaria volta a abrir em ~2 s — os blocos do calendário que não mudaram não são medidos de novo |
| `fix/aud2-assist` | `461bae14` | local | rede só com Matemática não leva o alerta de queda de acertos da Leitura à IA |
| `fix/aud2-auth2` | `cb29ab41` | local | registro do 1c5f1d8c corrigido: Quest sem portão de logins é decisão PENDENTE do dono |
| `fix/aud2-backup` | `9a6f6280` | local | restaurar arquivo de outro banco não passa a decisão da fila de revisões para outra criança |
| `fix/aud2-indic` | `8a90ef65` | local | a falha de conexão da coleta também diz que pode ser o certificado HTTPS |
| `fix/aud2-lgpd` | `3e48beda` | local | exclusão permanente apaga do log também o RA do vínculo da Lista Piloto |
| `fix/aud2-motor` | `0cd253e0` | local | devolve o espaço que faltava em "chaves = {" (estilo, sem efeito) |
| `fix/aud2-ops` | `e9f71f01` | local | o expurgo de fundo só apaga os arquivos que o próprio app grava |
| `fix/aud2-plat` | `1f08ad68` | local | recusa do ajuste manual não diz que dado chegou quando a integração só foi configurada |
| `fix/aud2-quest` | `7a7f0c23` | local | teste prova que o campo do nome da cerimônia não deixa entrar "letra invisível" |
| `fix/aud2-rede` | `251e41d2` | local | para a Secretaria, escola com matéria escondida pesa na média geral só por quem a média visível mede |
| `fix/aud2-sync2` | `315f2ff0` | local | diagnóstico já em andamento não promete mostrar um resultado que a tela não tem |
| `fix/aud2-virada` | `e5c2e659` | local | coleta do Elefante não grava de novo a leitura do livro homônimo quando o tempo de leitura não veio |
| `fix/aud3-indic` | `da35b8d8` | local | o teste da 1ª coleta sem referência cobre também a coluna do código fora de ID_ESCOLA |
| `fix/aud3-lgpd` | `477d3016` | local | conta da criança excluída tem como sair do cursor depois da coleta e da restauração |
| `fix/aud3-ops` | `97574534` | local | textos do PWA não prometem "nada recarrega sem o clique" à página que veio da rede |
| `fix/aud3-periodo` | `15ee71af` | local | num período de ano encerrado, a professora lê em Premiações e no Ranking de Leitura que as turmas dela são as de agora |
| `fix/aud3-plat` | `de150bad` | local | no "Quer ver um exemplo?" a Secretaria escolhe só o nível, sem a busca no acervo que dava erro de importação |
| `fix/aud3-quest` | `b9603bb4` | local | recusa dos cartões da turma de outro ano não afirma mais onde a criança está |
| `fix/aud3-rede` | `1f1175e9` | local | o diagnóstico da matrícula em turma de outro ano diz onde a criança ainda aparece (o Painel da escola a conta) |
| `fix/aud3-seg` | `0fe5f3c0` | local | os textos do login dizem o limite que sobra, o par e-mail + @ da mesma conta |
| `fix/aud3-serie` | `7f243dd1` | local | ajuste do suporte numa criança que a coleta não trouxe não faz a escola com a coleta parada parecer em dia |
| `fix/aud3-virada` | `e3704d1d` | local | recusa do Mérito de quem só tem matrícula no ano encerrado não diz que a posição daquele ano "não vale mais" |
| `fix/auditoria-alto-medio` | `1cd11574` | local + origin | corrige 2 altos + 7 médios da auditoria técnica |
| `fix/pp-desempenho` | `2e0b2f3b` | local | datas das suprimidas e equivalência da leitura única também no PostgreSQL |
| `fix/pp-identidade` | `75ca1ef3` | local | sufixo de outra sala não disfarça nome de uma palavra só (A2) |
| `fix/pp-sync` | `55f39a1d` | local | registra o custo do pool de livros do Elefante no pior caso |
| `fix/pp-textos` | `7afb1c91` | local | "Como ler estes números" diz a data que de fato conta nos livros novos |
| `fix/pp2-dados` | `34c950f4` | local | transferir toma a trava antes de ler e dá 409 se a ficha foi fundida |
| `fix/pp2-pool` | `4d3cecc3` | local | testes do mantenedor sem teto de tempo fixo e sem parar o agendador da sync |
| `fix/pp2-telas` | `322eabfe` | local | cartão "Questões" do Elefante sem número diz por quê |
| `fix/pp3-relatorios` | `ade20af2` | local | alertas e log da coleta sem "conector" e com a verdade de cada status |
| `fix/pp3-telas` | `891b4ea8` | local | avisos do resultado sem chave repetida e com a 2ª linha alinhada |

</details>

<details>
<summary>Prontidão E97 (66)</summary>

| Branch | Ponta | Origem | Assunto do commit |
| --- | --- | --- | --- |
| `prontidao/e97` | `6fed9920` | local | prontidao/e97w-final (linhagem global, cópia em outra escola, push do /confirmar, senha do compose) |
| `prontidao/e97-cifra` | `af2002ad` | local | chaveiro só de decifra e recifragem para a rotação planejada |
| `prontidao/e97-seg-auth` | `3ddfab6e` | local | teto de 160 MB não aceita token de aluno do Quest |
| `prontidao/e97-seg-dados` | `8c0efdd3` | local | sentinela de CPF não varre a raiz do sistema de arquivos |
| `prontidao/e97-seg-escopo` | `7dcc2155` | local | varredura das rotas que citam o Matific exige a trava de módulo |
| `prontidao/e97-seg-quest` | `9b1b0f3c` | local | limites do login do Quest após a revisão e97 e o portão recomendado |
| `prontidao/e97-sync-identidade` | `c06e3bb2` | local | upload manual de relatório de plataforma segue a política "bloquear" |
| `prontidao/e97-sync-outros` | `d4e192cd` | local | leituras do Elefante não empilham retrato no mesmo dia |
| `prontidao/e97b-config-prod` | `8db5374d` | local | chaves de exemplo, .env.example vazio, ENV normalizado e CORS sem null |
| `prontidao/e97b-escola-externa` | `7a34ea4f` | local | critério de nome do D9 testado só com nomes de escola inventados |
| `prontidao/e97b-turmas` | `fee6bb6d` | local | excluir turma junto com os alunos só pelo Admin Global (D19) |
| `prontidao/e97c-quest-auth-residuos` | `7a2788ea` | local | senhas_derivadas --contagens para o checklist pré-deploy |
| `prontidao/e97c-sync-residuos` | `ffd04f9c` | local | trava do D10 também na importação manual e na volta de conta aposentada |
| `prontidao/e97e-auth-quest-docs` | `e99ee010` | local | roteiro do staging traz a DATA_ENCRYPTION_KEY obrigatória |
| `prontidao/e97e-identidade-travas` | `8ef23835` | local | painel da turma não apaga o aviso do D10 com o temporizador anterior |
| `prontidao/e97f-residuos` | `769fe7ae` | local | cursor, busca de livros e sonda do Elefante usam a regra única do studentId |
| `prontidao/e97g-contas-turmas` | `2929e692` | local | conta desativada, excluída ou promovida a Secretaria não recebe o push da escola |
| `prontidao/e97g-docs-esquemas` | `0938ec76` | local | DATA_ENCRYPTION_KEY no inventário do cofre e SECRET_KEY só com o chaveiro |
| `prontidao/e97g-restauracao-identidade` | `59a2d215` | local | Revisões de identidade mostra a origem da decisão do Admin Global fora da fila |
| `prontidao/e97i-docs-cifra` | `5847c632` | local | regressão da chave do cofre e do texto do "Testar conexão" |
| `prontidao/e97i-turmas-d17` | `3415aac7` | local | painel de turma de outro ano não oferece "Transferir"; Turmas orienta arquivar |
| `prontidao/e97k-auth-listapiloto` | `b5ec4f20` | local | Lista Piloto respeita o tamanho das colunas e avisa em vez de 500 no PostgreSQL |
| `prontidao/e97k-identidade-backup` | `13b38063` | local | restauração anula quem aposentou a conta quando o usuário não existe mais |
| `prontidao/e97l-d10-motivos` | `147ed7b9` | local | trava do D10 na importação manual vale para pendência de qualquer motivo |
| `prontidao/e97m-ci` | `90e4b69c` | local | sonda da fumaça confere a troca da BASE sem depender do número da porta |
| `prontidao/e97m-ia` | `f75ebcd3` | local | limpeza do assistente pega número colado a letra; formas que ainda passam |
| `prontidao/e97m-seed` | `0f11b976` | local | escola de demonstração com nome fictício e catraca de nome real |
| `prontidao/e97n-analise` | `22a22d58` | local | zero das estrelas numa série sem número não sai pela diferença do total |
| `prontidao/e97n-pii-nomes` | `bdb3383d` | local | catraca de nome real de pessoa por SHA-256, sem o nome em claro |
| `prontidao/e97n-quest` | `c09f6065` | local | Seção 12, INDICE e docs/quest dizem que regenerar troca código e QR |
| `prontidao/e97n-scripts-politica` | `3f53e8f9` | local | Integrações mostra a política de criação de aluno e o Admin Global a muda |
| `prontidao/e97p-catracas-quest` | `b2190b3a` | local | um NUL solto ou um byte cp1252 não cegam mais as três catracas |
| `prontidao/e97p-mobile-push-cartaz` | `1f60a620` | local | lote com erro no Expo não cala os lotes seguintes nem a limpeza |
| `prontidao/e97p-painel-publico` | `ac9b4163` | local | fixture do noindex no perfil público sem o campo da nota única |
| `prontidao/e97q-higiene` | `8ef70d7b` | local | sessão de dentro do teste de fim de sessão migra em banco em memória |
| `prontidao/e97q-logsaidas` | `9b2b6116` | local | toda saída para estado final deixa UMA linha sync_execucao_finalizada, com a origem |
| `prontidao/e97r-catracas-git` | `e4afc265` | local | extensão de texto vale em qualquer caixa nas três catracas de LGPD |
| `prontidao/e97r-mobile-quest` | `ee1d0936` | local | regenerar a turma revoga o cartão de quem saiu dela depois da folha |
| `prontidao/e97r-obs` | `9df8228f` | local | a redação do Sentry reduz o risco, não promete "nenhum dado" |
| `prontidao/e97r-testes` | `7bff06e7` | local | campos do log que o PLANO monitora saem iguais ao enviado no JSON |
| `prontidao/e97s-nginx-vitrine` | `d88cb363` | local | vitrine da rede não mostra o cartão do módulo fora do plano |
| `prontidao/e97s-rp-conexao` | `a9261b00` | local | testes do connect_timeout que exigem o psycopg pulam sem o driver e rodam no job postgres |
| `prontidao/e97t-acesso` | `cd2f82da` | local | professor não lista fichas inativas da turma com incluir_inativos |
| `prontidao/e97t-cifra-rotacao` | `ce4187b6` | local | teste PG do '%' na senha migra com papel próprio e não troca a credencial do serviço |
| `prontidao/e97t-dados-lgpd` | `9d26652f` | local | vitrine pública da rede não publica escola com menos de 5 crianças |
| `prontidao/e97t-matriz-mutacao` | `1edd463c` | local | nome fictício da escola 17 com a mesma contagem de caracteres do oficial |
| `prontidao/e97t-pos-snapshot` | `edffac89` | local | METRICAS-SYNC.md não diz mais que a conexão nova não tem connect_timeout |
| `prontidao/e97t-sync` | `b9f4a4b7` | local | 'parcial' sem aluno aplicado não é referência do alerta 'plataforma_sem_dados' |
| `prontidao/e97u-pg-senha` | `63d71f29` | local | papel de migração do teste da 0038 conecta com senha, como exige o PG do CI |
| `prontidao/e97v-contratos-front` | `7125a633` | local | sem ENV as recusas viram aviso, exceto a DATABASE_URL malformada |
| `prontidao/e97v-interacoes` | `f551682a` | local | recálculo pela marca, sem aluno aplicado, não anuncia "0 alunos atualizados" |
| `prontidao/e97v-seguranca-correcao` | `86ff799f` | local | _excluidos_depois_do_backup mantém escola_id na assinatura |
| `prontidao/e97w-final` | `f3f1badd` | local | o "depois" do backup é medido no log inteiro, como as exclusões e a linhagem |
| `prontidao/e97x-dashboard` | `a68eab66` | local | /status e /agora de escola de rede com as mesmas idas da escola avulsa |
| `prontidao/e97x-logexc` | `67e721a6` | local | partícula "do" não corta o nome na chave de nome |
| `prontidao/e97y` | `a5087686` | local | prontidao/e97r-testes (varredura de tetos de tempo endurecida; campos do log que o PLANO monitora, 31/10) |
| `prontidao/e97y-p15` | `09bdeeb1` | local | P15 é recomendação aplicada pela regra do "bloquear", não decisão do dono |
| `prontidao/e97y-p18` | `15bc129f` | local | painel global só conta como sincronizada a execução que aplicou dado |
| `prontidao/e97y-p6` | `6c58438a` | local | conta de aluno transferido vira descarte com motivo próprio, sem pendência que reabre |
| `prontidao/e97y-rollback-34f1a23` | `5faa4f66` | local | volta a árvore do main para 34f1a23 (rollback do candidato) |
| `prontidao/e97y-squash` | `4b67ec9a` | local | correções da sincronização, P15, P18, painel global e logs (candidato a508768) |
| `prontidao/e97z` | `7440226b` | local | prontidao/e97z-agora (causa-raiz da sync, 27/10) |
| `prontidao/e97z-agora` | `d14573ac` | local | "Sincronizar agora" não dispara thread para execução já em andamento |
| `prontidao/e97z-logsync` | `0d5cf5ee` | local | HEAD em /api/health/ready e /api/health/live não dá mais 405 |
| `prontidao/e97z-status` | `b738eaa9` | local | barra lateral lê o onboarding leve, não o /sync/status |
| `prontidao/e97z-web` | `d63c4071` | local | polling das Integrações não cancela o /status em voo |

</details>

<details>
<summary>Dependências (Dependabot) (20)</summary>

| Branch | Ponta | Origem | Assunto do commit |
| --- | --- | --- | --- |
| `dependabot/github_actions/actions/setup-node-6` | `75b97805` | origin | Bump actions/setup-node from 4 to 6 |
| `dependabot/github_actions/actions/setup-python-6` | `63123eba` | origin | Bump actions/setup-python from 5 to 6 |
| `dependabot/github_actions/actions/upload-artifact-7` | `95e77871` | origin | Bump actions/upload-artifact from 4 to 7 |
| `dependabot/github_actions/codecov/codecov-action-7` | `8610d78f` | origin | Bump codecov/codecov-action from 4 to 7 |
| `dependabot/github_actions/tauri-apps/tauri-action-1` | `ac903a21` | origin | Bump tauri-apps/tauri-action from 0 to 1 |
| `dependabot/npm_and_yarn/expo-linking-57.0.2` | `f49437df` | origin | Bump expo-linking from 7.0.5 to 57.0.4 |
| `dependabot/npm_and_yarn/expo-notifications-57.0.3` | `fe55b78b` | origin | Bump expo-notifications from 0.29.14 to 57.0.7 |
| `dependabot/npm_and_yarn/jsdom-29.1.1` | `78320d01` | origin | Bump jsdom from 26.1.0 to 29.1.1 |
| `dependabot/npm_and_yarn/node-menores-c5b82ff5ad` | `717f5594` | origin | Bump the node-menores group across 1 directory with 22 updates |
| `dependabot/npm_and_yarn/node-menores-e25a338c9f` | `5cf5c9d2` | origin | Bump the node-menores group across 1 directory with 17 updates |
| `dependabot/npm_and_yarn/react-native-safe-area-context-5.8.0` | `42431467` | origin | Bump react-native-safe-area-context from 4.12.0 to 5.8.0 |
| `dependabot/npm_and_yarn/react-router-dom-7.18.1` | `fd8dfd30` | origin | Bump react-router-dom from 6.30.4 to 7.18.1 |
| `dependabot/npm_and_yarn/react-three/fiber-9.6.1` | `49707ab0` | origin | Bump @react-three/fiber from 8.17.10 to 9.6.1 |
| `dependabot/npm_and_yarn/typescript-7.0.2` | `d888f726` | origin | Bump typescript from 5.9.3 to 7.0.2 |
| `dependabot/npm_and_yarn/vitest/coverage-v8-4.1.10` | `ddd226f2` | origin | Bump @vitest/coverage-v8 from 3.2.7 to 4.1.10 |
| `dependabot/pip/backend/backend-menores-79070d6c1c` | `a6364a5d` | origin | Bump the backend-menores group across 1 directory with 15 updates |
| `dependabot/pip/backend/bcrypt-5.0.0` | `960e455e` | origin | Bump bcrypt from 4.0.1 to 5.0.0 in /backend |
| `dependabot/pip/backend/pytest-9.1.1` | `26936d73` | origin | Bump pytest from 8.3.4 to 9.1.1 in /backend |
| `dependabot/pip/backend/pytest-cov-7.1.0` | `eaa2e42e` | origin | Bump pytest-cov from 6.0.0 to 7.1.0 in /backend |
| `dependabot/pip/backend/starlette-gte-1.3.1` | `e8c15ac1` | origin | Update starlette requirement from &gt;=0.47.2 to &gt;=1.3.1 in /backend |

</details>
