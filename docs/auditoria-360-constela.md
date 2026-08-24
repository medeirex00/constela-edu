# Auditoria 360° — Constela Edu

**Data:** 24/08/2026 · **Base:** consolidação de 6 auditorias independentes e somente-leitura (arquitetura, segurança, dados/performance, observabilidade/testes/LGPD, UX/telas, visão de Secretaria/pedagógico/IA/automação).
**Método:** leitura direta do código-fonte, com provas de conceito executadas contra a aplicação real (SQLite em memória) nas frentes de segurança, dados e observabilidade. **Nenhum arquivo do produto foi alterado.**
**Escopo excluído por instrução:** duplicatas de aluno (P0 fechado no commit `7f6fe4e`), corrida do recálculo (trava 4713, commit `c4551a2`) e as 3 falhas pré-existentes conhecidas da suíte (`test_perfis_pdf` ×2, `test_auditoria_fixes`) — nada disso é achado novo.

**Placar dos achados:** 🔴 7 críticos · 🟠 23 altos · 🟡 41 médios · 🟢 25 baixos — **96 no total**.

---

## 1. RESUMO EXECUTIVO

*(escrito para ser lido por um Secretário de Educação, não por um desenvolvedor)*

### Em uma frase

O Constela Edu é um produto **maduro, bem construído e honesto** — muito acima da média do que se vê num sistema neste estágio —, mas hoje ele **classifica crianças e escolas com contas que estão erradas em três pontos específicos**, e tem **três portas de segurança abertas** que precisam ser fechadas antes de o município crescer.

### Estado atual

O sistema faz o que promete: importa dados do Elefante Letrado (leitura) e do Matific (matemática), calcula uma nota de 0 a 100 por criança, monta rankings, emite certificados e dá à Secretaria uma visão do município inteiro. Está em piloto real, com crianças reais, em Caraguatatuba. A engenharia por trás é séria: quase um arquivo de teste para cada arquivo de código, decisões documentadas dentro do próprio código (várias vezes explicando *o bug que motivou aquela linha*), e uma proteção de dados de criança que é, disparado, o melhor argumento comercial do produto.

### As qualidades (o que já é diferencial de mercado)

1. **A Secretaria não consegue ver o nome de nenhuma criança — por construção, não por tela.** Uma varredura de 45 rotas com uma criança-isca no banco não encontrou **um único vazamento** (com uma exceção, o botão de backup — item 🔴 C-04). Isso é o que ganha o jurídico de uma prefeitura.
2. **A conta de cada nota é auditável.** O sistema guarda o passo a passo do cálculo de cada criança, e o próprio código afirma que **nenhuma inteligência artificial participa dos números** — eles são reproduzíveis. Em compra pública isso vale mais do que número esperto.
3. **A comparação entre escolas de tamanhos diferentes já foi resolvida certo** (livros por aluno, e não livros no total), com um índice de 0 a 1000 correto — só que ele ainda não é o que aparece na tela principal (item 🔴 C-02).
4. **A estatística pedagógica é correta:** o sistema compara cada criança com a mediana e o percentil da própria turma, e mede persistência contra o ritmo dela mesma — turma fraca não penaliza ninguém.

### Os problemas (o que está errado hoje)

**Três contas erradas, que já afetam criança real:**

- Uma criança que lê 30 livros e não usa o Matific **fica atrás** de uma criança que lê 10 livros e usa as duas plataformas. O sistema trata "não tem o dado" como "tirou zero", e isso tem teto de 50 pontos. Foi medido: nas simulações, quem lia 3× mais ficou em **último lugar**. Isso alimenta ranking, premiação, certificado e o painel público com o nome da criança no telão.
- A nota com que a Secretaria compara escolas **não compara escolas**. Cada escola é medida contra ela mesma, então uma escola onde todos leem pouco e igual pontua **melhor** do que uma escola que lê muito mas tem crianças paradas. O próprio código escreve, em outro arquivo, que essa comparação é inválida — e a tela principal, o alerta de "escola em atenção", as metas do município, o boletim em PDF e a **vitrine pública** continuam usando ela.
- A mesma escola, no mesmo dia, tem **três "Média geral" diferentes** dependendo da tela (foi medido: 38,6 no painel do coordenador e 77,3 no painel da Secretaria).

**Três portas de segurança abertas** (todas com prova de conceito executada):

- O gestor de **uma** escola consegue trocar a senha da conta da Secretaria e, com ela, ler o dashboard, o ranking e o boletim de **todas as outras escolas do município**.
- Existe um botão de "baixar backup" que devolve nome, data de nascimento e o campo livre de observações (onde entram laudos) de qualquer escola da rede, e é a única rota de dados de criança que não passa pelo bloqueio da Secretaria.
- Um endereço de e-mail pessoal está **escrito dentro do código** e é promovido automaticamente a "dono da plataforma" a cada reinício do sistema. Na produção atual a conta já existe e isso bloqueia o ataque por acidente; em **um município novo, no ambiente de homologação ou numa restauração de desastre**, qualquer gestor de escola vira dono da plataforma inteira.

**Duas coisas que apagam dados sem avisar:**

- O botão "restaurar backup" **apaga permanentemente** dados que o backup nunca guardou: o mapeamento que liga a criança ao Matific (justamente a defesa contra o problema de alunos duplicados que acabou de ser corrigido), a linha do tempo inteira da criança e a conta dela no Quest. A tela responde "Backup restaurado com sucesso".
- Quando um gestor exclui permanentemente uma criança, o **nome civil dela continua no registro de auditoria** em 4 de 5 formatos que o sistema realmente grava. O teste que "prova" o esquecimento usa o mesmo filtro defeituoso do código — ele não pode falhar.

### Os riscos (o que ainda não doeu)

- **Ninguém descobre quando quebra.** Se a tela da professora der branco amanhã de manhã, **ninguém fica sabendo, nunca**. Não existe telemetria de erro no navegador; o identificador que amarraria "deu erro às 10h" a uma linha de log é gerado, enviado ao navegador — e jogado fora.
- **O produto envelhece mal.** As telas de leitura carregam **todo o histórico desde sempre**, sem recorte de data. Foi medido: uma escola de 400 alunos leva 2,5 s no 1º ano e 5 s no 2º ano — na rota **pública**, sem login e sem limite de requisições. No 3º ano letivo ela estoura o tempo limite do navegador só por envelhecer.
- **O produto não escala comercialmente.** A tela inicial do dono faz 7 consultas por rede, sem cache; mudar o contrato de módulos de uma rede de 60 escolas recalcula tudo **dentro do clique**, o que levaria de 8 a 25 minutos e seria cortado pelo servidor muito antes.
- **Não existe prazo de descarte para dado de criança.** Uma criança que saiu da rede permanece no banco indefinidamente. Existe expurgo apenas para conversas de IA e cópias de relatório — as duas coisas menos sensíveis.

### As oportunidades (o que dá retorno rápido)

1. **Inverter uma linha** faz a lista "Escolas que precisam de atenção" parar de mostrar a melhor escola primeiro.
2. **Trocar uma métrica que já existe e já está certa** (o índice per capita 0–1000) no painel, no alerta, nas metas e na vitrine pública corrige a régua com que o Secretário decide.
3. **Contagens de risco por escola sem nome nenhum** ("140 crianças da Escola X sem atividade há 30 dias") são calculáveis com o que já está no banco e dariam à Secretaria a resposta que ela não tem hoje — sem tocar em LGPD.
4. **Fazer o sistema procurar o Secretário** em vez de esperar: o sino de notificação da Secretaria é estruturalmente vazio (nenhum código emite alerta no escopo de rede), e o robô que detecta escola parada já roda — só não avisa ninguém.
5. **Um botão "emitir certificado" no pódio de premiações** liga dois fluxos que hoje são duas telas desconectadas — e premiação é o nome do produto.

### O que este relatório NÃO diz

Nenhuma frente conseguiu validar: comportamento sob PostgreSQL real (os testes de carga rodaram em SQLite e representam o **piso otimista**), se as variáveis de ambiente de monitoramento estão de fato ligadas no Railway, acessibilidade real (contraste, teclado, leitor de tela) e o tempo real de recuperação de desastre em escala municipal.

---

### 1.1 Onde as frentes divergiram

Consolidar 6 auditorias independentes produziu **duas divergências reais** e **uma corroboração cruzada** que vale registrar:

| # | Tema | Frente A | Frente B | Resolução proposta |
|---|---|---|---|---|
| D1 | **Claim atômico da fila de sync** | *Arquitetura* afirma que existe e é correto (`sync/service.py:355-361`), citando-o como ponto forte | *Observabilidade* (R2) diz que `proximas_da_fila` (`sync/service.py:274-283`) é um `SELECT` puro, sem `FOR UPDATE SKIP LOCKED`, e que **não localizou** o claim que o comentário de `main.py:158-160` alega | **Divergência não resolvida.** As duas leram pontos diferentes do mesmo arquivo. Item 🟡 M-41: ler `service.py` de ponta a ponta e ou corrigir o código, ou corrigir o comentário. Existe `uq_sync_exec_ativa` como rede de proteção em ambas as leituras. |
| D2 | **E-mail hardcoded promovido a admin global** | *Arquitetura* (D1) classifica como **RISCO POTENCIAL**: o `UNIQUE` em `usuarios.email` bloqueia hoje, "não é exploração confirmada" | *Segurança* (#2) executou **PoC com sucesso** e classifica como **ALTA** | **Não é contradição factual, é janela temporal.** Ambas concordam que em produção a conta já existe e bloqueia. Consolidado como 🔴 C-05, com a ressalva explícita: **inexplorável hoje na produção atual, explorável em município novo, staging, homologação e restauração de desastre.** |
| D3 | **Rate limit e caches por processo** | *Arquitetura* (F9) registra que o próprio código documenta a limitação e recomenda "não re-flagar" | *Segurança* (#5, #7) e *Dados* (B2) tratam como achado ativo (amplificação sem cache negativo, estampida no painel público, teto de tentativas do Quest multiplicado por worker) | **Consolidado como achado ativo.** Documentar uma limitação não a mitiga. Os itens 🟠 A-13, 🟡 M-03 e 🟡 M-04 seguem abertos; o crédito de honestidade do código fica registrado na §2. |
| C1 | **Backup/restore destrutivo** (corroboração) | *Dados* (C1) chegou por leitura de `MODELOS` + migrações de cascade | *Observabilidade* (C2) chegou por execução de `exportar`/`restaurar` reais | **Mesmo achado, dois caminhos independentes, prova executada.** Consolidado como 🔴 C-06 com confiança máxima. |

---

## 2. O QUE O SISTEMA JÁ FAZ MUITO BEM

Isto não é cortesia: cada item abaixo foi verificado no código por pelo menos uma frente, e **não deve ser mexido** numa refatoração. Onde há comentário explicando o porquê, o comentário deve viajar junto com o código.

**1. Bloqueio de PII da Secretaria por construção, não por tela** — `services/permissoes.py:44-49`, `core/deps.py:154-174`.
*Por quê é bom:* `turmas_permitidas` devolve `[]` **antes** de `acesso_total`, e **todos** os consumidores testam `is not None` (nunca truthiness), então lista vazia nunca vira "sem filtro". `escola_autorizada` nega todo POST/PUT/PATCH/DELETE da Secretaria num único ponto — o código diz literalmente que assim é "impossível abrir escrita por engano em alguma rota específica". A varredura de 45 rotas GET com criança-isca confirmou: **zero vazamentos**. É o argumento de venda para o jurídico de uma prefeitura, e a maioria dos concorrentes não tem.

**2. O motor de pontuação não tem número mágico** — `services/scoring.py`.
*Por quê é bom:* zero pesos no código (tudo em `configuracoes`), normalização plugável com P90 robusto a outlier, **saturação côncava** (`x/(x+k)`) aplicada só aos indicadores de VOLUME e nunca aos de QUALIDADE — a diferença entre premiar quem lê e premiar quem clica —, desempate determinístico por `aluno.id` (`:684-688`) e filtro que impede snapshot de aluno arquivado de entrar na régua (`:715-724`).

**3. As três travas de concorrência com hierarquia anti-deadlock escrita** — `core/database.py:130-134`.
*Por quê é bom:* 4711 importação / 4712 coleta / 4713 recálculo, com ordem de aquisição documentada e teste que guarda a ordem. O comentário de `bloquear_escola_para_recalculo` enumera as três consequências da corrida, incluindo a pior: *"corrupção silenciosa: é o dano real, o 500 é só o sintoma"*. Isso é engenharia de verdade, não cerimônia.

**4. Higiene de PII no log, repetida e consistente** — `routers/importacoes.py:203-207`, `:1316-1322`, `sync/orchestrator.py:91-93`.
*Por quê é bom:* o sistema **não loga o nome do arquivo** de relatório individual porque ele traz nome de criança; grava só a contagem de avisos no log permanente. Uma varredura por `logger.*` com nome de aluno voltou limpa. É raro ver essa disciplina aplicada em todos os pontos.

**5. Pseudonimização real antes de mandar dado para LLM externo** — `services/assistente.py:20-26, 229-236`.
*Por quê é bom:* cobre **todos** os alunos, inclusive arquivados ("rede de segurança" explícita), com tokens de largura fixa para reidentificação exata, opt-in por escola e chave cifrada. E a limitação (fragmento de nome digitado pelo usuário não é trocado) está **documentada no próprio código**, não escondida. Raríssimo.

**6. IA não calcula número** — `services/insights.py:1-6`.
*Por quê é bom:* o docstring afirma que nenhum modelo participa dos cálculos, "então os números são reproduzíveis e auditáveis". Num produto com criança real e dinheiro público, número auditável vale mais que número esperto. **Manter essa fronteira.**

**7. Estatística pedagógica robusta a outlier** — `services/insights.py:44-60, 120-165`.
*Por quê é bom:* percentil em vez de máximo, mediana em vez de média, e persistência comparada ao **próprio ritmo do aluno** — com a justificativa escrita ao lado ("turma fraca não penaliza"). É estatística correta, não dashboard bonito.

**8. Separar desempenho de cobertura** — `services/rede.py:102-137`.
*Por quê é bom:* o corte é pela **existência do snapshot**, não por `nota > 0`, "porque um aluno que usa a plataforma e ainda leu 0 livros é um zero LEGÍTIMO". Resolve o caso real "42/54" (escola boa com metade dos alunos fora parecia ruim). É sutileza de quem apanhou de dado real. **O defeito 🔴 C-01 é exatamente esta regra não tendo sido aplicada no nível do aluno.**

**9. Comparação per capita com índice 0–1000 reusando o mesmo motor** — `services/rede.py:302-357`.
*Por quê é bom:* `livros_por_matricula`, `estrelas_por_matricula` e índice com escopo REDE — "nenhuma segunda lógica de pontuação: é o mesmo motor com outro escopo". Está **correto**. Só precisa ser promovido ao painel (🔴 C-02).

**10. `core/deps.py` — o modelo de permissões** (202 linhas).
*Por quê é bom:* `exigir_rede` fecha IDOR entre redes; `exigir_modulo_da_escola` resolve o módulo pela escola da rota justamente porque o admin global passaria no guard genérico (`:119-125`); 404 em vez de 403 para não revelar existência de aluno (`permissoes.py:98-99`). É a peça mais bem desenhada do backend.

**11. Autenticação endurecida de verdade** — `core/security.py`, `routers/auth.py`.
*Por quê é bom:* bcrypt com limite de 72 bytes, `dummy_verify` anti-timing, mesma mensagem para conta inexistente e senha errada, limitador duplo somando e-mail e `@username` na mesma chave, `token_version` derrubando sessões na troca de senha, token de reset de 256 bits guardado só como SHA-256, JWT preso a HS256 com rejeição cruzada do claim `papel` entre Edu e Quest.

**12. Painel público nasce protegido** — `PainelPublicoConfig.tsx:206-235`, `routers/publico.py:184-189, 275, 405-439`.
*Por quê é bom:* anonimização por padrão, `window.confirm` com texto explícito antes de expor nome de criança, `confirmar_exposicao` obrigatório **no servidor**, k-anonimato (turma omitida no modo anônimo), `_ids_visiveis` bloqueando enumeração por `aluno_id`, `compare_digest` com guarda `isascii()`, `Cache-Control: no-store`. A preocupação antiga de PII no telão está endereçada.

**13. Fila de sincronização com backoff, recuperação de órfãs e alerta sem spam** — `sync/`, `main.py:69-80`.
*Por quê é bom:* recuperação no boot e por timeout, backoff exponencial, e o módulo já está estruturado para virar worker separado sem mudar código (`scheduler.py:8-10`). *(Ver divergência D1 quanto ao claim atômico.)*

**14. `core/config.py` fail-closed real** — `:68-93`, `main.py:247-250`.
*Por quê é bom:* recusa subir em produção com `SECRET_KEY` padrão ou SQLite; `/metrics` fail-closed sem token; chave de dados separada da de JWT com `MultiFernet` para rotação. Config exemplar — **é o padrão que o e-mail hardcoded (🔴 C-05) deveria seguir.**

**15. `hooks/useApi.ts` (219 linhas)** — o cliente HTTP do frontend.
*Por quê é bom:* cancelamento por `AbortController`, timeout por tentativa, retry **só** em falha transitória, backoff, cache opt-in. Substitui de fato o antipadrão `api().then().catch(()=>[])` que engolia erro. Não tocar. *(Duas telas ainda estão fora do padrão — 🟡 M-23.)*

**16. Avaliações externas com casamento por código INEP, nunca por nome** — `services/avaliacoes.py:28-31, 440-486`.
*Por quê é bom:* propostas para conferência humana, defesas contra zip-bomb, decompression-bomb e SSRF (resolve com `getaddrinfo` e valida IP público **a cada salto**, com `follow_redirects=False` manual). Maturidade acima do esperado.

**17. Correlação SAEB × engajamento com Pearson e ressalva explícita de não-causalidade** — `services/avaliacoes.py:353`, `rede.py:487`.
*Por quê é bom:* numa SEDUC, isso é o que separa uma ferramenta séria de um gráfico bonito. *(A métrica de entrada precisa ser corrigida — 🔴 C-02.)*

**18. Módulos contratados propagando até o índice** — `services/modulos.py`, `rede.py:341-345`.
*Por quê é bom:* duas regras de ouro explícitas (ausência = ligado; escola sem rede = tudo ligado), upsert com `SAVEPOINT` para a corrida de dois admins, e o índice distingue "módulo fora do plano" de "módulo contratado sem importação". SaaS de verdade, não flag de UI.

**19. Observabilidade de request bem instrumentada** — `main.py:100-113`, `core/observabilidade.py`.
*Por quê é bom:* middleware ASGI puro **antes** do CORS, para que o 500 volte com cabeçalhos CORS; `/health/live` × `/health/ready` distinguindo reinício de tirar-de-rota; Sentry com `send_default_pii=False`, `include_local_variables=False`, `max_request_body_size="never"` e redação de token na rota — tudo coberto por teste. *O que falta é o caminho do sinal até uma pessoa (🟠 A-14, A-15).*

**20. Minimização de ficha cadastral testada** — `ROTULOS_FICHA == {"ra"}`, `test_lgpd_minimizacao.py:17-20` + migração 0014; IP mascarado no log permanente (`rate_limit.py:116-128`).

**21. Os comentários explicam o porquê, não o quê** — e várias vezes registram o bug que motivou a linha.
*Por quê é bom:* é o que torna esta base auditável. Sem esses comentários, nenhuma das 6 frentes teria conseguido separar decisão consciente de defeito. **Qualquer refatoração deve preservá-los.**

**22. Volume de teste e migrações** — 88 arquivos de teste / ~21,5k linhas (razão 0,81:1 sobre o código), 90% de cobertura no backend, 28 migrações Alembic, `packages/core` compartilhado com mobile e desktop, code-splitting por rota.

**23. Detalhes de UX raros e certos** — `Premiacoes.tsx:166-177` muda a mensagem de erro **conforme o cargo** (gestor recebe link para Sincronização, professor recebe "peça ao coordenador"); `Alunos.tsx:63-68` tem "Salvar e adicionar outro" mantendo a turma; `Turmas.tsx:306-420` cria várias turmas numa grade Ano × Letra com as existentes desabilitadas; `Rankings.tsx:62-76` usa a URL como fonte da verdade, então deep-link funciona.

---

## 3. O QUE PRECISA SER CORRIGIDO

Legenda de confiança preservada das frentes originais: **CONFIRMADO** (código lido e provado) · **RISCO POTENCIAL** · **HIPÓTESE** · **SUGESTÃO**.
Prioridade: **P1** = agora · **P2** = 30 dias · **P3** = 30–90 dias · **P4** = 3–6 meses. Esforço: **P** (≤1 dia) · **M** (dias) · **G** (semanas).

---

### 🔴 CRÍTICOS (7)

#### 🔴 C-01 — A nota geral tem teto de 50 para quem usa só uma plataforma; o Ranking Geral ordena por adesão, não por desempenho
**Confiança:** CONFIRMADO (frente *dados*, com execução real do motor)

- **Problema:** `calcular_matific(snapshot=None, ...)` devolve **0,0** quando o aluno não tem snapshot — ausência de dado tratada como desempenho zero — e a nota geral é a média ponderada fixa das duas plataformas. Quem só lê fica com teto de 50.
- **Evidência:** `backend/app/services/scoring.py:811` (nota_geral = nota_m × peso_matific + nota_e × peso_elefante) e `scoring.py:590-611` (o zero). Execução com 12 alunos, escola 50/50: os 6 alunos **sem** Matific leram 30 livros e tiraram nota_elefante 100 → **geral 50,0, posições 7 a 12**; os 6 **com** Matific leram 10 livros → **geral 72,11, posições 1 a 6**. Quem lê 3× mais fica em último.
- **Impacto técnico:** contamina `Nota.posicao` na escrita — o dado está errado **no banco**, não só na tela. O código já corrigiu o caso irmão ("a REDE não contratou o módulo", `scoring.py:192`) e a versão da escola ("ausência ≠ zero", `rede.py:102-115`); o caso mais comum — módulo contratado, aluno sem dado — ficou aberto.
- **Impacto para o usuário:** a criança leitora perde ranking, premiação e certificado para uma criança que fez menos. A professora não consegue explicar o resultado, e a tela de explicação do cálculo mostra a conta certa de um resultado injusto.
- **Impacto para a Secretaria:** o Ranking Geral apresentado e o painel público do município medem **adesão às duas plataformas**, não aprendizagem. Com `ADOCAO_BAIXA = 40.0` (`rede.py:36`) o próprio produto assume que boa parte dos alunos não tem dado de uma das plataformas — não é caso de borda, é a regra.
- **Solução recomendada:** renormalizar os pesos sobre as plataformas em que o aluno **tem** dado, reusando a regra de `rede.py:102-115`; registrar em `Nota.detalhes` quais dimensões entraram, para a explicação da nota seguir honesta.
- **Solução rápida:** exibir selo "só leitura" / "só matemática" e **excluir do Ranking Geral** quem tem uma só dimensão, mantendo a criança nos rankings específicos — para o dano imediato sem mexer no motor.
- **Esforço:** M · **Prioridade:** **P1** (único achado que já afeta criança real, hoje, no piloto)

#### 🔴 C-02 — A métrica que governa o painel da Secretaria não compara escolas (e o próprio código diz isso, em outro arquivo)
**Confiança:** CONFIRMADO (frentes *dados* e *secretaria*, independentes, com execução real da normalização)

- **Problema:** `nota_elefante`/`nota_matific`/`nota_geral` são normalizadas contra o **P90 da própria escola**. A `media_geral` mede a **forma da distribuição interna** — homogeneidade —, não o nível. Escola em que todos leem pouco e igual pontua melhor do que escola que lê muito com uma cauda parada.
- **Evidência:** régua por escola em `services/scoring.py:506-556` (P90 dos alunos da escola na linha 542; `ReferenciaNormalizacao.escola_id == escola_id` em `:548-552`). O reconhecimento está em `services/rede.py:293-300`: *um 60 numa escola não equivale a um 60 noutra… servem ao ranking INTERNO, não à comparação entre escolas*. Execução com as funções reais: escola com 30 alunos × 2 livros → `media_elefante = 100,0`; escola com 40 alunos, 40,8 livros por aluno e distribuição real → **25,8**. **A escola que lê 13,6× mais por aluno cai abaixo de `MEDIA_BAIXA=30` e entra na lista de atenção; a que lê 3 livros aparece como melhor escola.**
- **Consumidores dessa métrica inválida:** ordem e posição das escolas (`rede.py:389`), KPI "Melhor escola" (`:427`), **equidade / `gap_media`** (`:383`), gatilho de atenção `MEDIA_BAIXA=30` (`:37, 55`), metas da Secretaria (`:563-566`), ranking global de redes (`:528-546`), **boletim PDF da rede** (`routers/rede.py:522`), **vitrine PÚBLICA sem login** (`rede.py:656-657`) e a **correlação contra SAEB/IDEB** (default `metrica="media_geral"` em `routers/rede.py:465`, rotulada "Média geral (engajamento)" em `RedeAvaliacoes.tsx:68`).
- **Impacto técnico:** o antídoto **já existe e está correto** — `_indice_da_rede`/`_pontuar_escolas` (`rede.py:314-357`), índice 0–1000 per capita com escopo REDE — mas só alimenta as abas do Ranking da Rede.
- **Impacto para o usuário:** a escola que mais lê é rotulada como escola em atenção; a direção é cobrada por um número que pune dispersão interna.
- **Impacto para a Secretaria:** ela **premia homogeneidade e chama isso de desempenho**, num painel público e num boletim de reunião. A correlação com SAEB/IDEB — o gráfico mais defensável do produto — está calculada sobre esse número.
- **Solução recomendada:** trocar `media_geral` por `pontuacao_geral` (índice per capita já existente) em `dashboard_rede:389`, `_motivo_atencao:46`, `dashboard_global:528`, nas metas, no boletim PDF e na vitrine pública; ajustar o default de `avaliacoes/correlacao`.
- **Solução rápida:** manter a média na tela, mas **rotulá-la corretamente** ("distribuição interna — não comparável entre escolas") e **ordenar a lista e disparar o alerta de atenção pelo índice**. Duas linhas de ordenação e um rótulo param a decisão errada hoje.
- **Esforço:** M · **Prioridade:** **P1**

#### 🔴 C-03 — Admin de UMA escola toma a conta da Secretaria e passa a ler a REDE inteira
**Confiança:** CONFIRMADO (frente *segurança*, PoC executado)

- **Problema:** `_usuario_alvo` só protege contas **globais** (`alvo.is_global and not ator.is_global`). Não há nenhuma referência a `rede_id` em `admin.py`. E `PUT /redes/{rede_id}/usuarios` promove a Secretaria a partir de um usuário **já existente de escola**, que mantém o `escola_id` — o próprio teste documenta isso como "pior caso" (`test_rbac_secretaria.py:36`).
- **Evidência:** `backend/app/routers/admin.py:157-166`, `:291-299` (troca de senha), `:330-386` (link de reset), `backend/app/routers/rede.py:283-312` (`definir_usuarios`). PoC: antes, o admin local recebe **403** em `/redes/{id}/dashboard` e em `/escolas/{B}/alunos`; após `PATCH /escolas/{A}/usuarios/{sec_id}` com senha → **200**; logando como Secretaria: dashboard **200**, ranking **200**, boletim **200**, lista de escolas devolve as duas escolas do município. Dois vetores independentes (PATCH de senha e `POST .../redefinir-senha`).
- **Impacto técnico:** rompe o isolamento entre escolas dentro da rede — exatamente o que `exigir_rede` foi escrito para impedir.
- **Impacto para o usuário:** o gestor da Escola Alpha lê dashboard, ranking e boletim de todas as outras escolas do município.
- **Impacto para a Secretaria:** a conta institucional do município é sequestrável por qualquer gestor de escola. É incidente reportável, não inconveniência.
- **Solução recomendada:** em `_usuario_alvo`, negar quando `alvo.rede_id is not None and not ator.is_global` (mesma régua já usada para `is_global`); e fazer `definir_usuarios` **zerar o `escola_id`** ao promover, tornando a conta puramente de rede.
- **Solução rápida:** só a condição em `_usuario_alvo` — uma linha, fecha os dois vetores.
- **Esforço:** P · **Prioridade:** **P1**

#### 🔴 C-04 — `GET /escolas/{id}/backup` fura a regra "Secretaria não vê PII"
**Confiança:** CONFIRMADO (frente *segurança*, PoC executado)

- **Problema:** a rota é protegida só por `escola_autorizada` + `exigir_papeis("admin")`. `escola_autorizada` libera **GET em qualquer escola da rede** para a Secretaria, e `exigir_papeis` só olha o cargo — mas `PUT /redes/{id}/usuarios` aceita **qualquer** `usuario_id`, inclusive um com `cargo="admin"`. Toda a proteção da regra depende de um detalhe de cadastro.
- **Evidência:** `backend/app/routers/admin.py:631-647`; `deps.py:143-166`; `rede.py:283-312`. PoC (mesma varredura de 45 rotas, só trocando o cargo): com `cargo="coordenador"` → **403**, `VAZAMENTOS: nenhum`; com `cargo="admin"` → **200 com NOME, OBS e NASC**. Devolve o JSON completo de `alunos` (nome civil, `data_nascimento`, `observacoes` — campo livre onde entram laudos), `matriculas`, `leituras` e `notas` de **qualquer escola da rede**.
- **Impacto técnico:** é a única rota de PII de escola que não passa por `negar_secretaria` (como `relatorios`/`importacoes`/`sync` em `main.py:147-152`) nem por `permissoes.negar_dado_individual`.
- **Impacto para o usuário:** dado clínico e cadastral de criança sai da escola sem consentimento e sem trilha visível no produto.
- **Impacto para a Secretaria:** LGPD e ECA. Destrói o argumento comercial nº 1 do produto — que é verdadeiro nas outras 44 das 45 rotas verificadas.
- **Solução recomendada:** registrar `admin.router` com `dependencies=[Depends(negar_secretaria)]` em `main.py`; e `definir_usuarios` recusar contas com `cargo="admin"` como Secretaria.
- **Solução rápida:** chamar `permissoes.negar_dado_individual` dentro de `baixar_backup` e `restaurar_backup` — duas linhas.
- **Esforço:** P · **Prioridade:** **P1**

#### 🔴 C-05 — E-mail pessoal cravado no código é auto-promovido a `is_global` a cada boot
**Confiança:** CONFIRMADO por *segurança* (PoC executado) · classificado como RISCO POTENCIAL por *arquitetura* — ver divergência **D2**

- **Problema:** `_EMAIL_ADMIN_GLOBAL = "edumedeiros1405@gmail.com"` dispara `UPDATE usuarios SET is_global = true WHERE lower(email) = :email` em **todo boot de todo worker**. E `admin.py:211-231` permite que um admin **de escola** crie usuário com e-mail arbitrário.
- **Evidência:** `backend/app/core/database.py:156-170`, chamado por `garantir_dados_base` em `backend/app/main.py:64`; criação livre em `admin.py:211-231`. PoC: admin local cria usuário com o e-mail (201, `is_global=False`); após reinício, `is_global=True`; login do atacante 200; em seguida `GET /redes/panorama-global` 200, `GET /presenca/sessoes` 200, `GET escola B /backup` 200 (**PII completa de outra escola**).
- **Ressalva honesta (divergência entre frentes):** na produção atual a conta **já existe** e `criar_usuario` devolve 409 por e-mail duplicado — inclusive com `status="excluido"`. **Não é exploração aberta hoje.** O vetor vale para toda instância onde a conta não exista: **município novo, staging, homologação, restauração de desastre**. A proteção atual é acidental, não desenhada.
- **Impacto técnico:** configuração de tenant dentro do código-fonte de um SaaS multi-tenant, aplicada por escrita idempotente a cada boot.
- **Impacto para o usuário:** nenhum hoje; total no dia da expansão (admin de escola → dono da plataforma).
- **Impacto para a Secretaria:** no primeiro município novo, qualquer gestor de escola pode virar Admin Global de **todas as redes** e baixar backup com PII de todas as escolas de todos os municípios.
- **Solução recomendada:** `ADMIN_GLOBAL_EMAIL` como variável de ambiente lida **uma vez no provisionamento** (ou em `scripts/`), nunca num UPDATE a cada boot — o padrão que `core/config.py` já aplica ao resto; e barrar a criação de usuários com o e-mail do owner por rotas de escola.
- **Solução rápida:** ler o e-mail de `settings` com default vazio e **não fazer nada** quando vazio. Uma linha, e nenhum ambiente novo nasce com a bomba.
- **Esforço:** P · **Prioridade:** **P1** (antes do próximo município, do próximo staging e do próximo teste de restauração)

#### 🔴 C-06 — "Restaurar backup" destrói permanentemente dados que o backup nunca capturou
**Confiança:** CONFIRMADO por duas frentes independentes (*dados* por leitura, *observabilidade* por execução) — corroboração **C1**

- **Problema:** `MODELOS` exporta 15 tabelas e **não inclui** `identidades_externas`, `eventos_aluno`, `sync_marcadores`, `resultados_avaliacao`, `notificacoes`, `quest_perfis`, `quest_credenciais_aluno`, `responsaveis_alunos`, `dispositivos_moveis`. A restauração **apaga `Aluno` da escola**, e `alunos.id` tem `ON DELETE CASCADE` para várias dessas tabelas.
- **Evidência:** `backend/app/services/backup.py:41-57` (`MODELOS`), `:131-132` (o delete); cascades em `alembic/versions/0013_identidade_externa_aluno.py:34`, `0010_eventos_aluno.py:74`, `0003_on_delete_integridade_referencial.py:44-47`; cascade ativado em `core/database.py:33-36`. Execução real de `exportar`/`restaurar`: Aluno 1→1 ok, Matricula 1→1 ok, **IdentidadeExterna 1→0 PERDIDO, EventoAluno 1→0 PERDIDO, QuestPerfil 1→0 PERDIDO (XP 4200, nível 7), QuestCredencialAluno 1→0 PERDIDO**. A resposta é "Backup restaurado: N registros. Notas recalculadas." (`admin.py:684`), **sem aviso**.
- **Impacto técnico:** perder `IdentidadeExterna` (o mapa UUID Matific ↔ aluno) faz a próxima sincronização voltar a casar **por nome** — exatamente o mecanismo do P0 de duplicatas fechado em `7f6fe4e`. **Restaurar um backup pode reabrir o P0.** O roundtrip existente (`test_fase4.py:339-372`) só cria alunos/leituras/livros e não enxerga nada disso.
- **Impacto para o usuário:** a criança perde o login do Quest, o XP e o nível; a linha do tempo inteira dela desaparece. Nada volta, porque nunca esteve no arquivo.
- **Impacto para a Secretaria:** o recurso vendido como rede de segurança é hoje um destruidor silencioso de dado de criança — com mensagem de sucesso na tela.
- **Distinção importante:** o `pg_dump` de `.github/workflows/backup.yml` **é** completo. O perigoso é a *funcionalidade* de backup/restauração dentro do aplicativo.
- **Solução recomendada:** falhar de saída se houver linha em tabela fora de `MODELOS` que o cascade apagaria; ou completar `MODELOS` com `IdentidadeExterna`, `EventoAluno` e as tabelas do Quest.
- **Solução rápida:** **desabilitar o botão de restauração na interface**, trocando por aviso ("restauração indisponível — use o backup do banco"), até a correção. Uma linha no frontend.
- **Esforço:** M (correção) / P (bloqueio) · **Prioridade:** **P1**

#### 🔴 C-07 — Nome civil de menor sobrevive à exclusão "irreversível" (LGPD)
**Confiança:** CONFIRMADO (frente *observabilidade*, prova executada com as funções reais)

- **Problema:** `_anonimizar_logs_do_aluno` filtra `entidade == "aluno" AND entidade_id.in_(aluno_ids)`, e `_redigir` só apaga a chave literal `"nome"` ou strings **exatamente iguais** a `Aluno.nome`. Escapam os formatos que a produção realmente grava.
- **Evidência:** `backend/app/routers/academico.py:493-509`. Escapam: `aluno.criacao_recusada` (`academico.py:174-180`, `entidade_id=None` — `IN` nunca casa NULL), `aluno.revisao_necessaria` (`importacoes.py:624-628`, idem), **`aluno.criado_auto` (`importacoes.py:634-638`, idem — caminho de importação normal)**, `aluno.vinculado_auto` (`:611-616`, chave `origem`, e o nome cru da planilha **difere** do da base — é por isso que houve fuzzy match), `aluno.identidade_vinculada` (`:1686-1692`, chave `nome_antigo`). Prova após a exclusão permanente: **4 de 5 linhas ainda contêm o nome do menor**.
- **Agravante:** `logs_auditoria` é **permanente por design** (`models/nota.py:47`), e `academico.py:542-544` declara por escrito a intenção que a implementação não cumpre.
- **O teste que "prova" o esquecimento é tautológico:** `test_alunos_gestao.py:171-198` consulta (`:193-195`) com **o mesmo filtro do código com defeito** — só inspeciona linhas que o anonimizador garantidamente tocou. Não pode falhar no caso real.
- **Impacto técnico:** o direito ao esquecimento não é entregue, e a suíte dá confiança falsa de que é.
- **Impacto para o usuário:** o nome da criança fica no banco para sempre depois de a família pedir exclusão.
- **Impacto para a Secretaria:** o município é o controlador dos dados. Responder a um pedido de titular com "excluído" quando o nome permanece é falha de conformidade documentada.
- **Solução recomendada:** redigir por **chave semântica** (`nome`, `origem`, `nome_antigo`, `nome_novo`, `aluno`, `origem_linha`) **e** remover o filtro `entidade_id`, varrendo por `escola_id` + conjunto de nomes normalizado; reescrever o teste consultando **sem** o filtro do código.
- **Solução rápida:** acrescentar as chaves semânticas ao `_redigir` e trocar `entidade_id.in_(...)` por `or_(entidade_id.in_(...), entidade_id.is_(None))` — pega 4 dos 5 casos.
- **Esforço:** M · **Prioridade:** **P1**

---

### 🟠 ALTOS (23)

#### 🟠 A-01 — `recalcular_escola` nunca apaga `Nota` órfã: posições duplicadas e contagem da Secretaria maior que a matrícula
**CONFIRMADO** (*dados*, execução real)
- **Problema:** o recálculo carrega as notas existentes, atualiza as do resultado e **nunca deleta o resto**. Aluno que continua ativo mas perde a matrícula do ano mantém a linha de `notas` com a posição antiga.
- **Evidência:** `services/scoring.py:850-866`; caminho real de perda de matrícula em `routers/academico.py:964`. Execução: após remover a matrícula dos 3 melhores e recalcular, `posicoes = [1,1,2,2,3,3,4,5,6,7]` — **dois alunos distintos em 1º lugar** — e o cartão da Secretaria reporta `alunos_com_nota_elefante = 10` com `total_alunos = 7`.
- **Impacto técnico:** `_medias_por_plataforma` (`rede.py:120-134`) não faz join em `Matricula`; média (78,4) e volume (`ativos_elefante=7`) discordam sobre qual é a coorte. O ranking da tela esconde no read (`rankings.py:32-38` faz inner join), mas o banco está inconsistente.
- **Impacto para o usuário:** dois primeiros lugares no mesmo ranking; certificado e premiação podem sair para quem não está mais matriculado.
- **Impacto para a Secretaria:** o painel reporta mais crianças com dado do que crianças matriculadas — número indefensável numa reunião.
- **Solução recomendada:** apagar (ou marcar) as `Nota` sem matrícula ao fim de `recalcular_escola` e fazer `_medias_por_plataforma` juntar `Matricula`.
- **Solução rápida:** só o join em `_medias_por_plataforma`, que remove o número impossível do painel da Secretaria enquanto a limpeza é feita.
- **Esforço:** M · **Prioridade:** **P1**

#### 🟠 A-02 — A mesma escola, no mesmo dia, tem três "Média geral" diferentes
**CONFIRMADO** (*dados*, execução real)
- **Problema:** três implementações independentes da mesma métrica: `avg(Nota.nota_geral)` incluindo os zeros de quem não usa a plataforma e as linhas órfãs; a média por plataforma só sobre quem tem snapshot (a correta); e a soma/len sem join em `Matricula` do Comparador.
- **Evidência:** `routers/rankings.py:379-386` (`montar_dashboard`), `services/rede.py:102-134` (`_medias_por_plataforma`), `services/evolucao.py:669-700` (`_lado_escola`). Execução com 10 alunos só de Elefante: **dashboard da escola = 38,64 · Secretaria = 77,29**. Divergência menor no mesmo par: `rankings.py:332` conta turmas sem `status == "ativa"`, `rede.py:172-178` conta com.
- **Impacto técnico:** três donos para uma invariante; qualquer correção em um lugar aumenta a divergência.
- **Impacto para o usuário:** o coordenador e a Secretaria olham "Média geral" da mesma escola e veem números diferentes — o produto perde credibilidade na primeira reunião conjunta.
- **Impacto para a Secretaria:** impossível responder "qual é a média da escola?" sem perguntar de qual tela.
- **Solução recomendada:** uma função única de média de escola (a de `_medias_por_plataforma`), consumida pelas três telas; padronizar o filtro de turma ativa.
- **Solução rápida:** rotular cada tela com a definição usada ("média sobre alunos com dado" × "média sobre todos os matriculados") até a unificação.
- **Esforço:** M · **Prioridade:** **P1**

#### 🟠 A-03 — O escopo do professor pende de uma igualdade de string de e-mail
**CONFIRMADO** (*arquitetura*)
- **Problema:** `turmas_permitidas` junta `Usuario` e `Professor` por `func.lower(Professor.email) == email`. `Usuario` **não tem** `professor_id`; `Professor.email` é anulável, sem `unique`, sem índice e sem FK. Chave natural mutável carregando decisão de autorização.
- **Evidência:** `services/permissoes.py:51-59`; `models/usuario.py`; `models/academico.py:10-18`.
- **Impacto técnico:** todos os modos de falha são **silenciosos** — retorna `[]`, HTTP 200, tela vazia, nunca erro: e-mail nulo, admin corrigindo o e-mail do usuário, typo no cadastro, professor duplicado (o produto tem ferramenta de dedup **porque isso acontece**, `admin.py:488-522`).
- **Impacto para o usuário:** a professora abre o sistema e não vê aluno nenhum, sem nenhuma mensagem. Suporte não tem como diagnosticar pela tela.
- **Impacto para a Secretaria:** perfil inteiro desligado sem sinal, com professoras reais no piloto; vira "o sistema não funciona".
- **Solução recomendada:** `Usuario.professor_id` (FK) + migração de backfill por e-mail, mantendo o e-mail como fallback.
- **Solução rápida:** exibir aviso explícito na tela quando `turmas_permitidas` devolver `[]` para cargo professor ("sua conta não está vinculada a nenhuma turma — peça ao coordenador"), transformando falha silenciosa em falha visível.
- **Esforço:** M · **Prioridade:** **P1**

#### 🟠 A-04 — 80 dos 151 endpoints não declaram `response_model`; `routers/rede.py` tem 20 endpoints e ZERO
**CONFIRMADO** (*arquitetura*)
- **Problema:** sem schema de saída, nada além de convenção e teste impede um campo `nome` de escapar num dict montado em Python.
- **Evidência:** contagem sobre os 151 endpoints; `routers/rede.py` (20 endpoints, 0 `response_model`, incluindo `/{rede_id}/dashboard`, `/{rede_id}/ranking`, `/panorama-global`, `/avaliacoes/correlacao`), `routers/evolucao.py` (8, todos sem), `routers/gamificacao.py` (6, todos sem). Os cartões são montados como dicionários em `rede.py:160-330`.
- **Impacto técnico:** OpenAPI vazio; os tipos de `packages/core/src/tipos.ts` são escritos à mão e derivam sem que nada acuse.
- **Impacto para o usuário:** nenhum hoje; o risco é a regressão futura.
- **Impacto para a Secretaria:** é exatamente a superfície onde a invariante nº 1 (Secretaria nunca vê PII) precisa valer — e onde ela não é garantida por tipo, apenas por costume.
- **Solução recomendada:** `response_model` em todo `routers/rede.py`, depois `evolucao.py` e `gamificacao.py`.
- **Solução rápida:** um teste de contrato que varra as respostas das rotas de rede procurando chaves proibidas (`nome`, `data_nascimento`, `observacoes`, `ra`) — pega o vazamento sem esperar a tipagem completa.
- **Esforço:** M · **Prioridade:** **P2**

#### 🟠 A-05 — A regra mais central do produto ("qual é o estado atual do aluno") está escrita 7 vezes, e já diverge
**CONFIRMADO** (*arquitetura*)
- **Problema:** "último snapshot por `(data_referencia DESC, id DESC)`" tem 7 implementações independentes — e as três de `plataformas.py` filtram só `aluno_id`, enquanto as de `importacoes.py` filtram `escola_id AND aluno_id`.
- **Evidência:** `services/scoring.py:259-273`, `services/rede.py:77-93` (window `row_number()`); `routers/importacoes.py:122-131` e `:138-153`; `routers/plataformas.py:121-125`, `:194-198`, `:266-270`. Cada arquivo repete no comentário o mesmo aviso ("não use `max(id)`, backfill grava id maior com data menor") — invariante sem dono.
- **Impacto técnico:** se um dos sete perder o desempate por `id`, ranking e painel passam a discordar **em silêncio**.
- **Impacto para o usuário:** risco de o aluno aparecer com dado antigo numa tela e novo em outra.
- **Impacto para a Secretaria:** mesma classe de incoerência de A-02, com origem diferente.
- **Solução recomendada:** `services/snapshots.py` com `ultimo_por_aluno()` única, consumida pelos sete pontos.
- **Solução rápida:** alinhar os três de `plataformas.py` para filtrar também por `escola_id` (a divergência já existente).
- **Esforço:** M · **Prioridade:** **P2**

#### 🟠 A-06 — O motor de identidade de aluno mora num router, e a sincronização chama um route handler do FastAPI diretamente
**CONFIRMADO** (*arquitetura*)
- **Problema:** `routers/importacoes.py` tem 1685 linhas e ~40 funções privadas que são regra de negócio pura (`_resolver_aluno:542`, `_casar_no_roster:506`, `_aluno_existente_na_turma:422`, `_roster_identidades:469`, `_sincronizar_turma_matific:699`). São consumidas de fora **por nome privado** por `routers/academico.py:155` (router→router), `sync/orchestrator.py:23` (sync→router) e 10 arquivos de teste. E `sync/orchestrator.py:158` chama `imp.confirmar(...)`, que é um `@router.post` com 3 dos 4 parâmetros em `Depends(...)` (`importacoes.py:1136-1140`).
- **Evidência:** os arquivos e linhas acima. A escolha do orchestrator está **documentada** ("DECISÃO ARQUITETURAL", `orchestrator.py:9-13`) e de fato evitou regressão.
- **Impacto técnico:** **RISCO POTENCIAL derivado e concreto:** no dia em que alguém acrescentar um 5º parâmetro `Depends()` a `confirmar` (um guard, um `Request`, um `background_tasks`), o caminho HTTP continua correto e **a sincronização passa a receber o objeto `Depends` como valor** — falha silenciosa ou `AttributeError` só no robô, que roda sem ninguém olhando. Não há teste que trave esse contrato.
- **Impacto para o usuário:** a coleta automática pode parar ou gravar errado sem que ninguém perceba.
- **Impacto para a Secretaria:** o motor que decide "é a mesma criança?" — a coisa mais crítica do produto — não tem fronteira testável independente do HTTP.
- **Solução recomendada:** extrair `services/identidade_aluno.py` e uma `services/importacao_pipeline.aplicar()` que `confirmar` **e** o orchestrator chamem.
- **Solução rápida:** um teste que falhe se `inspect.signature(imp.confirmar)` mudar de aridade — trava o contrato hoje, por ~10 linhas.
- **Esforço:** G (extração) / P (teste de contrato) · **Prioridade:** **P2**

#### 🟠 A-07 — As telas de leitura carregam todo o histórico desde sempre: o produto fica mais lento a cada ano letivo
**CONFIRMADO** (*dados*, benchmark executado)
- **Problema:** `_series_por_aluno` seleciona todos os snapshots da escola como objetos ORM, **sem filtro de data e sem ano letivo**, enquanto a janela pedida é quase sempre 30 dias.
- **Evidência:** `services/evolucao.py:44-56`. Benchmark (1 escola, SQLite em memória = **piso otimista**; Postgres em rede é 3–10× pior): 400 alunos × 180 dias → `mural` (rota **pública**) 2,57 s, `insights` 2,29 s, `ranking_evolucao` 2,03 s; 400 alunos × 360 dias → mural **5,08 s**, insights **4,38 s**. Chamadores: `publico.py:296` e `:434` (**sem login, sem rate limit**), `insights.py:84-86`, `gamificacao.py:490-491`, `mobile.py:116`, `rankings.py:234`, `premiacoes.py:85`, `ia.py:30`.
- **Impacto técnico:** escala **linear no tempo de vida do produto**: ano 2 dobra, ano 3 triplica, sem nada mudar na escola. O timeout do cliente é 15 s (`hooks/useApi.ts`). `recalcular_escola` é a exceção saudável (window function no banco) — **o caminho de escrita escala, o de leitura não**.
- **Impacto para o usuário:** telão da escola travando e Inteligência Pedagógica lenta, piorando sozinho a cada bimestre.
- **Impacto para a Secretaria:** o produto que funciona no piloto para de funcionar no 3º ano só por envelhecer — e a rota mais lenta é a pública, que qualquer pessoa pode chamar.
- **Solução recomendada:** recortar `_series_por_aluno` por janela de data (a que o chamador já informa) e por ano letivo.
- **Solução rápida:** a mesma cláusula `WHERE data_referencia >= ...` — é uma linha que devolve ~90% do tempo das rotas mais lentas.
- **Esforço:** P · **Prioridade:** **P1**

#### 🟠 A-08 — Mudar o contrato de módulos de uma rede recalcula tudo dentro do clique
**CONFIRMADO** (*arquitetura* F4 e *dados* B3, independentes)
- **Problema:** `PUT /redes/{id}/modulos` itera **todas as escolas da rede** chamando `scoring.recalcular_escola` na thread do request HTTP, cada uma pegando advisory lock e carregando matrículas e snapshots em memória.
- **Evidência:** `routers/rede.py:159, :194` → `services/modulos.py:243` → `recalcular_rede` (`:172-209`) → `services/scoring.py:695-734`. Estimativa das frentes: 500 escolas × 1–3 s = **8 a 25 minutos** num único request; 60 escolas × 500 alunos = 30 mil alunos recalculados numa requisição.
- **Impacto técnico:** qualquer edge (Railway/Vercel) corta em 30–60 s. A docstring propõe "reenviar o mesmo PUT" como recuperação — mas o reenvio estoura pelo mesmo motivo, sempre.
- **Impacto para o usuário:** o gestor clica em salvar, espera, recebe erro, e não sabe se salvou.
- **Impacto para a Secretaria:** o ato comercial central do SaaS (contratar/descontratar módulo) é o único endpoint que **não tem como terminar** numa rede grande.
- **Solução recomendada:** transformar em tarefa de fila com status consultável (a infraestrutura de fila já existe em `sync/`).
- **Solução rápida:** processar em lotes com resposta 202 e uma tela de progresso, mantendo a idempotência já documentada.
- **Esforço:** M · **Prioridade:** **P2**

#### 🟠 A-09 — O painel global do dono é O(redes × escolas), com a rede inteira materializada em memória
**CONFIRMADO** (*arquitetura* F1/F2 e *dados* B4)
- **Problema:** laço por rede chamando `_kpis_da_rede` (≈7 consultas agregadas cada), sem cache, acumulando **todo cartão de toda escola** para no fim usar `top[:10]`; e `_alunos_com_qualquer_dado` traz **todos** os pares `(escola_id, aluno_id)` para conjuntos Python só para contar distintos.
- **Evidência:** `services/rede.py:486-497`, `:137-158`, `:160-330`; rota `GET /panorama-global` em `routers/rede.py:395-403`; reuso em `ranking_escolas` (`:474`) e no boletim PDF (`routers/rede.py:522`).
- **Impacto técnico:** 20 redes / 200 escolas ⇒ 140+ queries por carregamento; 100 redes / 250k alunos ⇒ ~600 consultas e 500k tuplas em memória. É um `COUNT(DISTINCT)` que o Postgres faria sozinho.
- **Impacto para o usuário:** a tela inicial do Admin Global degrada com o **crescimento comercial**, não com o uso.
- **Impacto para a Secretaria:** indireto — é o gargalo que impede vender o 10º município.
- **Solução recomendada:** `_alunos_com_qualquer_dado` vira `COUNT(DISTINCT)` em SQL; cache curto (TTL) em `dashboard_global` e `_kpis_da_rede`.
- **Solução rápida:** só o cache com TTL de 60 s no `panorama-global`.
- **Esforço:** M · **Prioridade:** **P2**

#### 🟠 A-10 — Chromium é aberto dentro do request, num contêiner de 768 MB com 2 workers, sem nenhum semáforo
**CONFIRMADO** (*arquitetura*)
- **Problema:** cada geração de PDF faz `p.chromium.launch()` dentro de handlers síncronos, que rodam no threadpool do FastAPI (padrão 40 threads). Nada serializa isso.
- **Evidência:** `services/relatorios.py:438-441, :512-515, :833-836, :930-933`; chamadores em `routers/relatorios.py:118, :123, :127, :162, :225, :238`; `backend/entrypoint.sh` (`--workers ${WEB_CONCURRENCY:-2}`); `docker-compose.yml` (`mem_limit: 768m`). Some-se `core/automacao.py`, que **também** abre Chromium no boot de cada worker (`main.py:168`).
- **Impacto técnico:** um professor emitindo 30 certificados, ou dois gestores gerando cartaz ao mesmo tempo, dispara vários Chromium concorrentes no teto de 768 MB — OOM derruba a API inteira, não só o PDF.
- **Impacto para o usuário:** o sistema cai justamente no dia de festa/premiação, quando todo mundo emite certificado.
- **Impacto para a Secretaria:** indisponibilidade do produto no momento de maior visibilidade.
- **Solução recomendada:** semáforo global de 1–2 renderizações simultâneas + fila com resposta assíncrona para lotes.
- **Solução rápida:** o semáforo (um `threading.Semaphore` no módulo de relatórios) — poucas linhas, elimina o pior caso.
- **Esforço:** P · **Prioridade:** **P2**

#### 🟠 A-11 — Alunos além do 100º em ordem alfabética não podem receber certificado por esta tela
**CONFIRMADO** (*UX*)
- **Problema:** o dropdown de alunos do certificado busca `?por_pagina=100` e o backend limita `por_pagina` a `le=100`. A tela lê **só a página 1**, sem busca, sem paginação e **sem qualquer aviso de que a lista está truncada**.
- **Evidência:** `apps/web/src/pages/Relatorios.tsx:33-35`; `backend/app/routers/academico.py:81`.
- **Impacto técnico:** defeito funcional silencioso.
- **Impacto para o usuário:** a criança cujo nome começa com letra tardia simplesmente **não recebe certificado**, e ninguém entende por quê. Escolas do piloto têm centenas de alunos.
- **Impacto para a Secretaria:** entrega quebrada num município real, em cerimônia pública.
- **Solução recomendada:** trocar o dropdown por campo de busca com autocompletar paginado.
- **Solução rápida:** ordenar por turma + paginação simples, ou no mínimo exibir "mostrando os primeiros 100 alunos — use a busca" (aviso hoje inexistente).
- **Esforço:** P · **Prioridade:** **P1**

#### 🟠 A-12 — Arquivar um aluno é um beco sem saída de 1 clique
**CONFIRMADO** (*UX*)
- **Problema:** a lista de alunos filtra `status == "ativo"`, a tela não tem filtro "mostrar arquivados", mas o menu oferece **"Arquivar"**. Arquivado, o aluno **desaparece desta tela para sempre**: "Reativar" só aparece quando `status != "ativo"`, condição que esta lista nunca devolve.
- **Evidência:** `backend/app/routers/academico.py:94`; `apps/web/src/components/AcoesAluno.tsx:113-120` usado em `Alunos.tsx:266`; parâmetro `incluir_inativos` já existe no backend para turma (`academico.py:821`).
- **Impacto técnico:** nenhum; é puramente de fluxo.
- **Impacto para o usuário:** ação destrutiva-por-omissão de 1 clique, com reversão de 4+ cliques e conhecimento prévio (lembrar a turma, ir em `/turmas/:id`, marcar "Mostrar arquivados").
- **Impacto para a Secretaria:** crianças "somem" do sistema e a escola conclui que houve perda de dados.
- **Solução recomendada:** filtro "Arquivados" na própria tela de Alunos, reusando `incluir_inativos`.
- **Solução rápida:** o mesmo filtro só como checkbox, sem redesenho.
- **Esforço:** P · **Prioridade:** **P2**

#### 🟠 A-13 — Quest: espaço de código de ~17 bits permite colher contas e nomes de crianças sem autenticação
**CONFIRMADO** (*segurança*, números calculados a partir do próprio código)
- **Problema:** o código de login é a credencial (decisão de produto documentada), e o espaço é pequeno demais para resistir a força bruta.
- **Evidência:** `backend/app/quest/services/credenciais.py:34-83` (147 palavras × 900 = **132.300 combinações, ~2^17**); `quest/routers/auth.py:41` (`limitador_ip_falha` = 50 falhas/300 s → **14.400 tentativas/dia por IP**) e `:105-128` (`/quest/auth/quem` devolve **o nome real da criança**). Com 2000 alunos: densidade 1,51%, ~66 palpites por acerto, **~218 contas por dia de um único IP**. Agravantes: o limitador é **por processo** (`core/rate_limit.py:7-13`) e o próprio código reconhece (`quest/routers/auth.py:35-37`) que *na topologia real (API no Railway, sem nginx na frente) não há limite de borda* — o `limit_req` de `quest_login` só existe no `nginx.conf` do docker-compose, que não é o deploy de produção.
- **Impacto técnico:** `POST /quest/auth/entrar` cria sessão de 30 dias.
- **Impacto para o usuário:** sequestro de contas de menores e colheita de nomes, sem login, de um único IP; com rotação de IP, sem teto prático.
- **Impacto para a Secretaria:** incidente com dados de menores em plataforma municipal.
- **Solução recomendada:** ampliar o código (o formato "2 palavras + 4 dígitos" já existe como legado e `formatar_codigo_exibicao` já o trata) e mover o limitador para armazenamento compartilhado + limite de borda.
- **Solução rápida:** exigir turma/escola junto do código em `/quem` — corta a enumeração cega sem mudar o formato do cartão já impresso.
- **Esforço:** M · **Prioridade:** **P2** (exige decisão de produto do dono)

#### 🟠 A-14 — Se a tela da professora der branco, ninguém descobre — e o identificador de correlação é jogado fora
**CONFIRMADO** (*observabilidade*)
- **Problema:** o `ErrorBoundary` só faz `console.error`, não há nenhuma dependência de telemetria no frontend, e o `X-Request-ID` que o backend expõe de propósito **não é lido por ninguém no cliente**.
- **Evidência:** `apps/web/src/components/LimiteErro.tsx:26-27` (o comentário admite: *o backend não recebe stack do cliente*); `apps/web/package.json` sem telemetria; `main.py:112-113` expõe o header via CORS; grep por `request-id` em `apps/web/src` = **0 ocorrências**; `packages/core/src/cliente.ts:12-18` carrega só `status` e `mensagem`.
- **Impacto técnico:** o id de correlação é gerado, logado, exposto — e descartado. Não há como amarrar "deu erro às 10h" a uma linha de log.
- **Impacto para o usuário:** a professora vê tela branca, ninguém fica sabendo, nunca.
- **Impacto para a Secretaria:** o suporte do município não tem procedimento nem evidência; a falha vira "o sistema é ruim".
- **Solução recomendada:** telemetria de erro no frontend (o Sentry já está integrado no backend) + ler o `X-Request-ID` em `cliente.ts`, guardar em `ApiError` e mostrar na tela de erro.
- **Solução rápida:** só a leitura do header e a exibição do código na tela de erro — converte "deu erro às 10h" numa busca de log.
- **Esforço:** M · **Prioridade:** **P2**

#### 🟠 A-15 — O alerta de sincronização não sai do banco, e o sino da Secretaria é estruturalmente vazio
**CONFIRMADO** (*observabilidade* C5 e *secretaria* P3)
- **Problema:** os alertas de sync são gravados em tabela e só têm um consumidor: a tela. E as notificações são criadas **sempre com escopo "escola"**, enquanto o feed da Secretaria filtra **apenas** escopo "rede" — que nenhum código emite.
- **Evidência:** `sync/service.py:51-67` (grava) e `sync/router.py:445-448` (único consumidor); `services/notificacoes.py:56-57` (`escopo="escola"` fixo) × `:70` (`_condicao_feed` exige `escopo == "rede"`); a única ocorrência de escopo "rede" no repositório é o teste `test_notificacoes.py:79`. Não há e-mail, webhook, push nem métrica de negócio (só RED de HTTP em `observabilidade.py:111-119`). Uma integração parada com `severidade="critico"` (`service.py:185`) é descoberta só por inspeção manual.
- **Impacto técnico:** os 11 eventos de `NOTIFICAVEIS` (`notificacoes.py:27-40`) são **todos operacionais** — nenhum é pedagógico.
- **Impacto para o usuário:** o coordenador descobre a integração parada quando abre a tela por acaso.
- **Impacto para a Secretaria:** **o sino nunca acende.** O produto espera o Secretário em vez de procurá-lo — e é exatamente isso que faria alguém abrir o sistema toda manhã.
- **Solução recomendada:** emissor de notificação com escopo "rede"/"global" + digest semanal (e-mail/push) com escolas que caíram, escolas que subiram e metas fora de rota.
- **Solução rápida:** ligar `verificar_obsolescencia` (que **já roda** no scheduler, `sync/scheduler.py:40`) a uma notificação de escopo rede — a detecção já existe, falta só o aviso.
- **Esforço:** M · **Prioridade:** **P2**

#### 🟠 A-16 — Os testes de concorrência em Postgres nunca rodam no CI — inclusive o que guarda a trava 4713 recém-entregue
**CONFIRMADO** (*observabilidade*)
- **Problema:** o `pytest` do CI roda sem `TEST_DATABASE_URL_PG`, e o job que sobe Postgres executa **só** as migrações. Os testes marcados se auto-pulam.
- **Evidência:** `.github/workflows/ci.yml:61`; job `migracoes-postgres` em `ci.yml:77-134`; `test_recalculo_concorrencia_pg.py:45` (auto-skip). Fica sem rede de proteção justamente `test_hierarquia_nunca_pega_4713_segurando_4711` (`:351`), que guarda contra **deadlock entre a trava de importação (4711) e a de recálculo (4713)**.
- **Impacto técnico:** um refactor que inverta a ordem de aquisição **passa verde no CI e trava em produção**.
- **Impacto para o usuário:** importação e recálculo travados sem erro compreensível.
- **Impacto para a Secretaria:** o P0 que acabou de ser fechado pode voltar sem que a esteira acuse.
- **Solução recomendada:** rodar `pytest -m postgres` no job que **já tem** Postgres no CI.
- **Solução rápida:** é literalmente uma linha no workflow.
- **Esforço:** P · **Prioridade:** **P1**

#### 🟠 A-17 — Não existe dimensão TEMPO acima do aluno: "quais escolas estão piorando?" não tem resposta no produto
**CONFIRMADO** (*secretaria*)
- **Problema:** `Nota` tem `UniqueConstraint("aluno_id","ano_letivo")` — uma linha por aluno/ano, **sobrescrita a cada recálculo** —, e `dashboard_rede`/`_kpis_da_rede` não têm parâmetro de janela nem campo de variação.
- **Evidência:** `backend/app/models/nota.py:24`; `services/rede.py:359`. A capacidade existe um nível abaixo: snapshots são imutáveis e datados (`models/plataformas.py:44, 66`) e `evolucao.ranking_evolucao(db, escola_id, inicio=, fim=)` (`services/evolucao.py:345`) já mede crescimento em janela arbitrária — mas só por aluno, dentro de uma escola.
- **Impacto técnico:** a matéria-prima existe; falta a agregação.
- **Impacto para o usuário:** o diretor não sabe se a escola melhorou; compara prints de bimestres anteriores.
- **Impacto para a Secretaria:** nenhuma tela distingue "escola que subiu de 20 para 35" de "escola que caiu de 60 para 35" — as duas aparecem como 35. É a pergunta nº 1 de um Secretário, e o produto não responde.
- **Solução recomendada:** delta de 30/90 dias por escola somando `ranking_evolucao` por escola e comparando com a janela anterior.
- **Solução rápida:** guardar um retrato mensal dos KPIs por escola (uma tabela pequena, gravada pelo scheduler) — habilita a comparação sem tocar no motor.
- **Esforço:** M · **Prioridade:** **P2**

#### 🟠 A-18 — A lista "Escolas que precisam de atenção" está ordenada da MELHOR para a PIOR
**CONFIRMADO** (*secretaria*)
- **Problema:** a lista de ação herda a ordenação por média **decrescente** do ranking.
- **Evidência:** `services/rede.py:389` (`cartoes.sort(key=lambda c: (-c["media_geral"], ...))`) e `:431` (`"atencao": [c for c in cartoes if c["precisa_atencao"]]`); o frontend renderiza na ordem recebida (`apps/web/src/pages/rede/RedeDashboard.tsx:686`). Com 100 escolas, a escola **com zero dado** (`media_geral = 0.0`) fica no **fim** da lista. Agrava: `_motivo_atencao` (`rede.py:46-57`) devolve **um** motivo, sem severidade, sem "desde quando" e sem quantas crianças são afetadas — "Sem alunos matriculados" e "Baixa adoção: só 38%" chegam com o mesmo peso.
- **Impacto técnico:** uma linha.
- **Impacto para o usuário:** a lista de ação está literalmente de trás para frente.
- **Impacto para a Secretaria:** a escola mais crítica do município é a última que ele lê — e provavelmente não lê.
- **Solução recomendada:** ordenar `atencao` por severidade (e por nº de crianças afetadas) e enriquecer `_motivo_atencao`.
- **Solução rápida:** inverter a chave de ordenação da lista `atencao`. Uma linha.
- **Esforço:** P · **Prioridade:** **P1**

#### 🟠 A-19 — A Secretaria não enxerga risco pedagógico nem em número agregado
**CONFIRMADO** (*secretaria*)
- **Problema:** o bloqueio de PII está **correto**, mas não há substituto agregado: a Secretaria recebe `{"indices": [], "alertas": []}`.
- **Evidência:** `backend/app/routers/ia.py:19-49` filtra por `alunos_permitidos`, e `turmas_permitidas` devolve `[]` para Secretaria (`services/permissoes.py:47-48`) — que é `not None`, logo o filtro esvazia tudo. `dashboard_rede` não expõe `alunos_sem_atividade_30d`, `alunos_com_queda_de_acertos` nem `alunos_abaixo_da_mediana` por escola — **números que são contagens, não PII**.
- **Impacto técnico:** os 4 gatilhos já existem e são transparentes em `services/insights.py:35-37, 176-278`; falta só agregar por escola e por tipo.
- **Impacto para o usuário:** nenhum (é perfil de Secretaria).
- **Impacto para a Secretaria:** ela sabe que 62% das crianças usam o Elefante; **não sabe que 140 delas pararam há um mês**. Direcionar recurso vira palpite.
- **Solução recomendada:** contagens de risco por escola derivadas de `alertas_da_escola`, agregadas por tipo, expostas em `dashboard_rede`.
- **Solução rápida:** um único número por escola — "crianças sem atividade há 30 dias" — já muda a conversa.
- **Esforço:** M · **Prioridade:** **P2**

#### 🟠 A-20 — Não existe "Esqueci minha senha"
**CONFIRMADO** (*UX*)
- **Problema:** a tela de login não tem link de recuperação; a única via é um token gerado **por um gestor**.
- **Evidência:** `apps/web/src/pages/Login.tsx` (sem link); `RedefinirSenha.tsx:26-37` (só abre com `?token=`); `backend/app/routers/admin.py:341` (o token só nasce em `POST /usuarios/{id}/redefinir-senha`); `MinhaConta.tsx:66-70` confirma por escrito: *peça ao administrador da escola um link de redefinição*.
- **Impacto técnico:** nenhum; o fluxo de token de uso único já existe e é seguro.
- **Impacto para o usuário:** professora que esquece a senha num domingo fica fora do sistema até alguém da coordenação atender.
- **Impacto para a Secretaria:** custo de suporte recorrente e evitável, e adoção prejudicada logo na primeira semana.
- **Solução recomendada:** autoatendimento de "Esqueci minha senha" reusando o token existente, com envio por e-mail.
- **Solução rápida:** se não houver serviço de e-mail configurado, ao menos um texto no login dizendo exatamente a quem pedir e como.
- **Esforço:** M · **Prioridade:** **P2**

#### 🟠 A-21 — Importação de matrículas: o arquivo sobe e é reprocessado duas vezes, sem barra de progresso e sem desfazer
**CONFIRMADO** (*UX*)
- **Problema:** o fluxo de Lista Piloto envia **o arquivo inteiro duas vezes** (analisar e confirmar) e o backend **reparseia a planilha duas vezes**. O fluxo irmão já resolveu isso com `arquivo_token`.
- **Evidência:** `apps/web/src/pages/ImportacaoMatriculas.tsx:62-94`; `backend/app/routers/importacoes.py:1385-1396` e `:1737-1752`; solução existente em `Importacoes.tsx:327`. Sem barra de progresso em `ImportacaoMatriculas.tsx:244-246`.
- **Impacto técnico:** duplica banda e CPU no momento mais crítico do produto.
- **Impacto para o usuário:** com Excel de 5–10 MB na internet de escola pública, o "Importando..." repete todo o upload sem nenhum sinal de vida — e **depois de confirmar não existe desfazer**: numa importação errada de 200 alunos, a correção é manual, um a um.
- **Impacto para a Secretaria:** é a porta de entrada de todos os dados e onde nasceu o P0 de duplicatas.
- **Solução recomendada:** usar `arquivo_token` também aqui + barra de progresso + operação de desfazer por lote de importação.
- **Solução rápida:** só o `arquivo_token` (o mecanismo já existe e é testado) e um indicador de progresso.
- **Esforço:** M · **Prioridade:** **P2**

#### 🟠 A-22 — Não existe retenção para dado de criança, e a única purga que existe roda só no boot
**CONFIRMADO** (*observabilidade*)
- **Problema:** há retenção apenas para as duas classes **menos** sensíveis — conversas de IA (90 d) e cópias de relatório em disco (7 d). **Nenhuma** para `Aluno`, `Matricula`, `Leitura`, `SnapshotMatific`, `SnapshotElefante`, `EventoAluno`, `Nota`.
- **Evidência:** `core/config.py:145` e `:100`; grep por `retenc|expurg|purgar` em `services/` e `routers/` só retorna esses dois casos. A purga de IA roda **só no boot** (`database.py:219` via `garantir_dados_base`); `backend/scripts/purgar_ia.py` existe mas **nenhum workflow o agenda** (só `backup.yml` e `security.yml` têm `schedule:`). Também não existe exclusão de escola/rede: grep por `delete(Escola)` retorna zero.
- **Impacto técnico:** num processo que fica semanas no ar, a retenção de 90 dias **não é aplicada**.
- **Impacto para o usuário:** criança que saiu da rede permanece indefinidamente no banco.
- **Impacto para a Secretaria:** o município é o controlador; não ter política de descarte nem caminho de fim de contrato é achado direto numa fiscalização.
- **Solução recomendada:** política de retenção por classe de dado + rotina agendada; caminho de encerramento de escola/rede.
- **Solução rápida:** agendar `purgar_ia.py` num workflow com `schedule:` (o script já existe) e documentar a política.
- **Esforço:** M · **Prioridade:** **P3**

#### 🟠 A-23 — A parte destrutiva e irreversível da fusão de alunos é justamente a não testada
**CONFIRMADO** (*observabilidade*)
- **Problema:** em `services/alunos_fusao.py` (75% de cobertura), as linhas descobertas (245-252, 266-271, 280-284) são exatamente o ramo em que **ambos** os alunos têm perfil Quest — onde o código **deleta** perfil, progresso, habilidades e tentativas do perdedor, deleta a credencial e reatribui responsáveis.
- **Evidência:** medição de cobertura da frente de observabilidade; **zero testes e2e** (verificado por grep nos 7 specs) para backup, restauração, exclusão permanente, fusão de alunos e sincronização — os cinco fluxos que destroem ou movem dado de criança.
- **Impacto técnico:** operação irreversível de 1 clique sem rede de proteção automatizada.
- **Impacto para o usuário:** a criança pode perder progresso do Quest numa fusão feita de boa-fé.
- **Impacto para a Secretaria:** perda de dado de menor sem trilha de reversão.
- **Solução recomendada:** testes do ramo "ambos têm Quest" + e2e para os cinco fluxos destrutivos.
- **Solução rápida:** só o teste unitário do ramo Quest, que é onde está o dano irreversível.
- **Esforço:** M · **Prioridade:** **P2**

---

### 🟡 MÉDIOS (41)

*(formato compacto: os mesmos campos, condensados)*

**🟡 M-01 · Restauração de backup aceita a chave primária ditada pelo arquivo** — CONFIRMADO (*segurança*, PoC)
**Problema:** a exportação ignora `id`/`escola_id`/`usuario_id`, mas a restauração não reaplica esse filtro. **Evidência:** `services/backup.py:143-147, :159` (`IGNORADAS` aplicado só na linha 72); PoC: `id=4242` → HTTP 200 e gravado com id 4242; `escola_id` de outra escola → 400 (bloqueado por acidente feliz, colisão de kwarg vira `TypeError`). **Impacto:** técnico — em Postgres, `INSERT` com id explícito **não avança a sequence**, então inserções futuras de qualquer escola colidem em cadeia (não validado em Postgres a partir daqui); usuário — erros de integridade inexplicáveis; Secretaria — DoS multi-tenant a partir de uma conta de escola. **Solução:** aplicar `IGNORADAS` também no `restaurar` | **rápida:** a mesma condição, uma linha. **Esforço:** P · **Prioridade:** **P2**

**🟡 M-02 · `/api/health` anônimo expõe infraestrutura e o IP de saída real** — CONFIRMADO (*segurança* #6, *observabilidade* R1)
**Problema:** devolve sem auth nem rate limit: versão, estado do Sentry, `automacao_navegador`, `login_paginas` (diagnóstico das páginas de login de Matific/Elefante), `scheduler_sync`, `uptime_s` e `egress` = `{ip, org/ASN, cidade, região, país}` do backend. **Evidência:** `backend/app/main.py:207-232`; `core/automacao.py:44-49`. **Impacto:** técnico — mapeamento de infraestrutura e revelação do IP de origem (útil para contornar proxy/WAF); incoerente com `/metrics`, que é fail-closed (`main.py:233-249`); usuário — nenhum; Secretaria — exposição desnecessária de superfície. **Solução:** proteger o health detalhado com `METRICS_TOKEN`, mantendo `/live` e `/ready` públicos | **rápida:** remover `egress` e `login_paginas` da resposta pública. **Esforço:** P · **Prioridade:** **P2**

**🟡 M-03 · Painel público: varredura completa do banco a cada token inválido, sem rate limit** — CONFIRMADO (*segurança*)
**Problema:** o cache só guarda tokens **válidos**; token inválido nunca é cacheado, então toda requisição errada roda o SELECT de todas as configs e compara linha a linha. `rede_pelo_token_publico` é pior: carrega **todas** as redes com token em toda chamada, sem cache. **Evidência:** `routers/publico.py:94-123` (`if valores.get("ativo") and tok`, linha 119); `services/rede.py:661-675`. **Impacto:** técnico — amplificação barata que escala com o número de escolas do SaaS; usuário — lentidão do telão; Secretaria — disponibilidade, não vazamento. **Solução:** cache negativo curto (LRU com TTL) + `LimitadorTentativas` por IP nas rotas `/publico/*` | **rápida:** só o cache negativo. **Esforço:** P · **Prioridade:** **P2**

**🟡 M-04 · Cache do painel público é por processo, TTL 60 s, sem proteção de estampida** — CONFIRMADO (*dados*)
**Problema:** com N workers há N caches independentes; no miss, cada requisição concorrente dispara a varredura pesada de A-07 sem single-flight, numa rota sem autenticação e com polling contínuo do telão. **Evidência:** `routers/publico.py:362-363` (`TTL_PAINEL_S = 60`, `_cache_painel: dict`). **Impacto:** técnico — até N recomputações por minuto por escola; usuário — telão travando; Secretaria — a vitrine do município é a rota mais frágil. **Solução:** cache compartilhado + single-flight | **rápida:** lock por chave no processo, evitando a estampida local. **Esforço:** M · **Prioridade:** **P3**

**🟡 M-05 · `/metrics` mente com 2 workers** — CONFIRMADO (*observabilidade*)
**Problema:** não existe `PROMETHEUS_MULTIPROC_DIR` (grep no repo inteiro) e cada worker tem seu registry; o scrape cai num worker arbitrário. **Evidência:** `backend/entrypoint.sh:13` (`--workers ${WEB_CONCURRENCY:-2}`). **Impacto:** técnico — contadores e histogramas parciais e oscilantes; um pico de erro em um worker pode não aparecer; usuário — nenhum; Secretaria — o painel de saúde não é confiável. **Solução:** modo multiprocesso do client Prometheus | **rápida:** documentar que a métrica é por worker e não alarmar sobre ela. **Esforço:** M · **Prioridade:** **P3**

**🟡 M-06 · Trilha de auditoria sem ferramenta de consulta** — CONFIRMADO (*observabilidade*)
**Problema:** 91 ações são auditadas, a tela reconhece **13**, e o único endpoint devolve os **últimos 15** eventos, sem filtro, sem paginação e sem exportação. **Evidência:** `routers/sistema.py:91-105` (`_TEXTOS`) e `:108-132`. Ficam invisíveis: `aluno.excluido_permanente`, `usuario.excluido_permanente`, `login.falhou`, `login.bloqueado`, `aluno.fundido`, `rede.boletim_exportado`, `painel_publico.token_trocado`, `sync.credencial_salva`, `quest.cartoes_gerados`. **Impacto:** técnico — a trilha existe e não é consultável; usuário — nenhum; Secretaria — responder "quem apagou esta criança?" exige console do Postgres. **Solução:** tela de auditoria com filtro por usuário/período/entidade + exportação | **rápida:** completar `_TEXTOS` e permitir filtro por entidade. **Esforço:** M · **Prioridade:** **P3**

**🟡 M-07 · Backend sem catraca de cobertura** — CONFIRMADO (*observabilidade*)
**Problema:** o CI não usa `--cov-fail-under` no backend, enquanto o web tem catraca honesta. **Evidência:** `.github/workflows/ci.yml:61`; `apps/web/vitest.config.ts:48-53` (lines 26, branches 60). Estado medido: **90%** (13.446 statements, 1.337 sem cobertura). **Impacto:** técnico — a camada com scoring, permissões e LGPD é a única sem trava contra erosão; usuário/Secretaria — indireto. **Solução:** `--cov-fail-under=88` | **rápida:** idem, é uma flag. **Esforço:** P · **Prioridade:** **P2**

**🟡 M-08 · Importar `app.main` faz chamadas de rede externas** — CONFIRMADO (*observabilidade*)
**Problema:** `automacao.iniciar_verificacao()` é chamado sem guard e dispara dois GETs a serviços de geolocalização de IP, launch do Chromium e abertura das **páginas de login reais** de Matific e Elefante. **Evidência:** `main.py:168`; `core/automacao.py:39-49, :56-80`; `tests/conftest.py:9` importa `app.main` → acontece em **toda execução da suíte** (deixou a suíte I/O-bound: 5 s de CPU em 5,5 min) e em **cada worker a cada deploy**. **Impacto:** técnico — CI e boot dependem de terceiros; expõe o IP do runner às plataformas; usuário — boot mais lento; Secretaria — nenhuma. **Solução:** guard de ambiente | **rápida:** desligar em `TESTING`/CI. **Esforço:** P · **Prioridade:** **P2**

**🟡 M-09 · Campo `rota` ausente nos logs da aplicação** — CONFIRMADO (*observabilidade*)
**Problema:** `ctx_rota.set(rota)` só ocorre no `finally`, depois do handler; qualquer `logger.*` emitido **dentro** de um handler sai sem `rota`. **Evidência:** `core/observabilidade.py:318`, promessa em `:6-7`. **Impacto:** técnico — só a linha `http_acesso` tem o campo; usuário/Secretaria — indireto (diagnóstico mais lento). **Solução:** setar o contexto antes de chamar o handler | **rápida:** idem, é o mesmo `set` movido. **Esforço:** P · **Prioridade:** **P3**

**🟡 M-10 · Fallbacks sem log: o documento de vitrine degrada em silêncio** — CONFIRMADO (*arquitetura* E1/E2) + RISCO POTENCIAL (E3)
**Problema:** cinco `except Exception` caem em fallback **sem nenhum log**, e o sexto faz o oposto e **explica por quê** — o problema foi diagnosticado e corrigido em um único lugar. **Evidência:** `services/relatorios.py:248, :662` (devolve `{atividades: 0, livros: 0}`), `:797`, `:961`, `:1013`, contra `:1137-1141` (*loga com traceback para uma falha que NÃO seja "sem navegador" ficar observável*); `routers/relatorios.py:239` repete o padrão. RISCO: `sync/connectors/matific.py:257, 267, 335, 343, 411, 419, 443, 452, 480` engolem sem log, devolvendo `""`/`{}`/`False`. **Impacto:** técnico — se o Matific mudar de formato, a sync produz nomes vazios e segue "com sucesso"; usuário — recebe cartaz com "0 atividades / 0 livros"; Secretaria — documento público errado sem ninguém saber. **Solução:** copiar o padrão de `elefante.py` (que loga quase todos: `:888, :948, :991`) | **rápida:** um `logger.exception` em cada um dos 6 fallbacks. **Esforço:** P · **Prioridade:** **P2**
*Ressalva justa: praticamente todo `except` deste código é tipado e todo `except Exception` carrega `# noqa: BLE001` com justificativa escrita — são ~9 pontos num universo de 74.*

**🟡 M-11 · 28 endpoints com `response_model=dict` / `list[dict]`** — CONFIRMADO (*arquitetura*)
**Problema:** contrato vazio no OpenAPI. **Evidência:** `academico.py:74` (`/alunos`, paginado), `:647` (`/alunos/duplicados`), `admin.py:411`, `rankings.py:86` e `:191`. **Impacto:** técnico — os tipos de `packages/core/src/tipos.ts` são escritos à mão e derivam sem que nada acuse; usuário — quebra silenciosa de tela após mudança de backend; Secretaria — nenhuma. **Solução:** schemas Pydantic nas rotas de maior tráfego | **rápida:** começar pelas duas de ranking. **Esforço:** M · **Prioridade:** **P3**

**🟡 M-12 · O índice não cobre a ordenação usada para "estado atual"** — CONFIRMADO (*arquitetura*)
**Problema:** o índice é `(escola_id, aluno_id, id)`, mas a window ordena por `(data_referencia DESC, id DESC)` — agrupa a partição e não serve à ordenação, causando sort por partição em toda leitura. **Evidência:** `models/plataformas.py:38` e `:59`; consumo em `scoring.py:265-267` e `rede.py:81-83`. **Impacto:** técnico — snapshots são append-only e só crescem; usuário — lentidão crescente; Secretaria — idem A-07. **Solução:** índice `(escola_id, aluno_id, data_referencia DESC, id DESC)` | **rápida:** a mesma migração, é aditiva. **Esforço:** P · **Prioridade:** **P2**

**🟡 M-13 · Scheduler replicado por worker e coleta de avaliações inline na mesma thread** — CONFIRMADO (*arquitetura*)
**Problema:** `sync_scheduler.iniciar()` é chamado no import, então com 2 workers há 2 threads de scheduler; `SYNC_WORKERS=1` limita por worker, não globalmente. E `_coletar_avaliacoes_pendentes()` roda **inline**, travando a fila quando é lento. **Evidência:** `main.py:161`; `sync/scheduler.py:57`; paliativo `AVALIACOES_COLETA_POR_RODADA=3` em `config.py:161`. **Impacto:** técnico — duas execuções Playwright simultâneas no mesmo teto de 768 MB (soma-se a A-10); usuário — sync lenta; Secretaria — coleta atrasada. **Solução:** worker de sync separado (o módulo já está pronto para isso, `scheduler.py:8-10`) | **rápida:** eleger o scheduler por advisory lock, garantindo um por instância. **Esforço:** M · **Prioridade:** **P3**

**🟡 M-14 · 136 URLs de tenant montadas à mão no frontend** — CONFIRMADO (*arquitetura*)
**Problema:** não existe camada de recursos; cada página concatena o caminho multi-tenant. **Evidência:** grep `escolas/${escolaId}` em `apps/web/src` (excluindo testes) = **136 ocorrências**; `packages/core` já existe e seria o lugar natural. **Impacto:** técnico — mudar o esquema de URL é uma varredura de 136 pontos; usuário/Secretaria — indireto. **Solução:** módulo de recursos em `packages/core` | **rápida:** começar pelas rotas mais tocadas. **Esforço:** G · **Prioridade:** **P4**

**🟡 M-15 · `Layout.tsx` concentra 12 responsabilidades em 1150 linhas** — CONFIRMADO (*arquitetura*)
**Problema:** catálogo de menu, sidebar por perfil, filtro por módulo SaaS, pesquisa global, notificações, breadcrumb, menu do usuário, barra recolhida, indicador de importação e persistência em `localStorage` no mesmo arquivo. **Evidência:** `apps/web/src/components/Layout.tsx:110-150, 188-241, 262, 339, 518, 844, 889, 917, 972, 1044`. **Impacto:** técnico — é o arquivo mais tocado da aplicação e concentra o risco de merge de toda mudança de navegação; usuário/Secretaria — indireto. **Solução:** extrair o catálogo e `gruposDoPerfil` para `lib/navegacao.ts` (dados puros, testáveis) | **rápida:** só a extração do catálogo. **Esforço:** M · **Prioridade:** **P3**

**🟡 M-16 · A sidebar da Secretaria tem dois itens indistinguíveis** — CONFIRMADO (*UX*)
**Problema:** "Panorama da Rede" (`/`) e "Painel da Rede" (`/rede`) são o **mesmo componente** alternando por `modo`, com nomes quase idênticos, ícones parecidos e zero explicação. **Evidência:** `Layout.tsx:218-221`; `rede/RedeDashboard.tsx:617-620`. **Impacto:** técnico — nenhum; usuário — o perfil mais importante do produto tem os dois únicos itens do menu indistinguíveis; Secretaria — atrito logo na primeira sessão do cliente que decide a compra. **Solução:** renomear para "Panorama" e "Administração da Rede", com uma linha de descrição em cada item | **rápida:** só o rename. **Esforço:** P · **Prioridade:** **P2**

**🟡 M-17 · `/insights` é recalculado duas vezes porque o cache não foi ativado** — CONFIRMADO (*UX*)
**Problema:** o endpoint mais pesado do sistema (timeout de 45 s por decisão própria) é chamado no Dashboard e de novo na tela Insights, **sem `cacheMs`** — e `useApi` só cacheia quando a opção é passada. **Evidência:** `Insights.tsx:186-191`; `Dashboard.tsx:416-417`; `hooks/useApi.ts:39, 124-130`. **Impacto:** técnico — trabalho duplicado no caminho mais caro; usuário — espera duas vezes pelo mesmo cálculo; Secretaria — indireto. **Solução:** `cacheMs` no consumo de insights | **rápida:** idem, é um parâmetro. **Esforço:** P · **Prioridade:** **P2**

**🟡 M-18 · Gestão por exceção invertida nas telas: os melhores primeiro, os alertas escondidos** — CONFIRMADO (*UX* e *secretaria* P6)
**Problema:** `indices_da_escola` ordena **melhores primeiro** e devolve a escola inteira sem corte; o bloco de Alertas **nasce fechado**; no Dashboard, destaques e alertas têm o mesmo peso. **Evidência:** `services/insights.py:166`; `apps/web/src/pages/Insights.tsx:47` (`useState(false)`); `Dashboard.tsx:188-191`. **Impacto:** técnico — nenhum; usuário — a tela chamada "Inteligência Pedagógica" abre mostrando quem vai bem; Secretaria — o produto ensina a olhar para o lugar errado. **Solução:** abrir os alertas por padrão e ordenar por menor engajamento quando o acesso vem da Central de Atenção | **rápida:** trocar o `useState(false)` por `true`. **Esforço:** P · **Prioridade:** **P2**

**🟡 M-19 · Jargão do motor entregue cru ao usuário** — CONFIRMADO (*UX*)
**Problema:** colunas **Valor / Referência / Normalizado / Peso / Contribuição** sem uma linha de explicação, ao lado do nome da criança; badge "Normalização: automática" no topo do perfil; aba "Referências de Normalização"; enum cru do backend virando texto de alerta ("credencial invalida", "sem dados"); badge "colunas por posição — confira" e "Bloqueado por conflito de identidade" na importação. **Evidência:** `PerfilAluno.tsx:117-124, 262-264`; `configuracoes/Metricas.tsx:251`; `Sincronizacao.tsx:283-286`; `Importacoes.tsx:573, 450`. **Impacto:** técnico — nenhum; usuário — a professora recebe vocabulário de motor de scoring; Secretaria — o produto parece feito para engenheiros. **Solução:** frase em português ("A nota vem 70% da leitura e 30% da matemática...") com a tabela atrás de "ver o cálculo detalhado"; tabela de rótulos humanos para os enums | **rápida:** renomear a aba para "O que vale nota 100" e mapear os 6 enums de alerta. **Esforço:** M · **Prioridade:** **P3**

**🟡 M-20 · Perfil do Aluno mostra as mesmas 3 conquistas duas vezes** — CONFIRMADO (*UX*)
**Problema:** a seção renderiza as 3 próximas em destaque **e depois a grade inteira**, com barra de progresso duplicada. **Evidência:** `PerfilAluno.tsx:373-405` e `:407-439`. **Impacto:** usuário — poluição na tela mais consultada pela professora; técnico/Secretaria — nenhum. **Solução:** excluir as 3 destacadas da grade | **rápida:** um filtro. **Esforço:** P · **Prioridade:** **P3**

**🟡 M-21 · Dashboard da escola: média geral dentro do card de Matemática, números repetidos e dois seletores de escola** — CONFIRMADO (*UX*)
**Problema:** (a) dentro do card "Matemática", o segundo número é a média geral da escola, rotulada de forma que induz a leitura "média de matemática" — e o card "Leitura" ao lado não tem número equivalente; (b) "Livros lidos" e "Tempo de leitura" aparecem em Engajamento e de novo no card Leitura — a tela repete 3 dos 6 números; (c) dois seletores de escola concorrentes, um na página e outro fixo na barra superior. **Evidência:** `Dashboard.tsx:320-322`, `:177-179` × `:295-301`, `:130-144` × `Layout.tsx:1160-1186`. **Impacto:** usuário — leitura errada do indicador principal; técnico — nenhum; Secretaria — o número mais citado do produto é o mais fácil de interpretar errado. **Solução:** mover a média geral para o topo, remover a duplicação e manter um único seletor | **rápida:** só remover o número do card de Matemática. **Esforço:** P · **Prioridade:** **P2**

**🟡 M-22 · Telas do Matific e do Elefante sem busca, filtro ou paginação** — CONFIRMADO (*UX*)
**Problema:** carregam e renderizam **todos** os alunos ativos numa tabela única, enquanto `Alunos.tsx` e `Livros.tsx` têm busca, filtro e paginação. **Evidência:** `Matific.tsx:121`; `Elefante.tsx` (aba alunos). **Impacto:** usuário — para editar o Matific de uma criança numa escola de centenas, é rolar até achar; técnico — render pesado; Secretaria — nenhuma. **Solução:** reusar o padrão de `Alunos.tsx` | **rápida:** só o campo de busca no cliente. **Esforço:** P · **Prioridade:** **P3**

**🟡 M-23 · A listagem de Usuários está fora do padrão de consumo de API, e seu estado vazio é ambíguo** — CONFIRMADO (*UX*)
**Problema:** usa `api().then().catch()` cru — sem timeout, sem retry em falha transitória, sem cancelamento — exatamente o antipadrão que `useApi` foi criado para eliminar; e o estado vazio é "Sem acesso ou nenhum usuário", que junta erro de permissão com lista vazia. **Evidência:** `Usuarios.tsx:731-741` e `:854`; padrão documentado em `hooks/useApi.ts:1-18`. **Impacto:** técnico — erro engolido na tela que cria contas; usuário — não sabe se errou ou se não tem direito; Secretaria — suporte cego. **Solução:** migrar para `useApi` e separar as duas mensagens | **rápida:** separar as mensagens. **Esforço:** P · **Prioridade:** **P3**

**🟡 M-24 · Relatórios: um download congela a tela inteira, sem filtros e sem lote** — CONFIRMADO (*UX*)
**Problema:** `disabled={ocupado !== ""}` desabilita **todos** os botões enquanto um único arquivo é gerado; não há filtro por turma ou bimestre (que existem em Ranking e Premiações); não há emissão em lote. **Evidência:** `Relatorios.tsx:72, 113, 119, 125`. **Impacto:** usuário — gerar um PDF impede gerar qualquer outro; emitir 30 certificados é repetir o fluxo 30 vezes; técnico — relacionado a A-10; Secretaria — trabalho manual em cerimônia de premiação. **Solução:** desabilitar só o botão em uso + filtros + emissão por turma | **rápida:** desabilitar só o botão clicado. **Esforço:** M · **Prioridade:** **P2**

**🟡 M-25 · Nome de cliente chumbado no código do produto** — CONFIRMADO (*UX*)
**Problema:** constante `REDE_CARAGUA`, botão "Adicionar rede de Caraguatatuba (N)" no cabeçalho e modal homônimo, com a lista de escolas do município no frontend. **Evidência:** `apps/web/src/pages/Escolas.tsx:31, 189, 293`. **Impacto:** técnico — dado de tenant no código de um SaaS multi-rede (mesma classe de C-05); usuário — nenhum; Secretaria — o próximo município vê o nome do concorrente-vizinho na tela. **Solução:** importação de rede por arquivo/config | **rápida:** esconder o botão atrás de flag do Admin Global. **Esforço:** M · **Prioridade:** **P3**

**🟡 M-26 · Metas da rede sem prazo, responsável, linha de base e desdobramento por escola** — CONFIRMADO (*secretaria*)
**Problema:** `MetaRede` tem só `rede_id`, `metrica`, `alvo`, `descricao`, `created_at`, e o progresso compara o alvo com o valor de **hoje**. **Evidência:** `backend/app/models/rede.py` (classe `MetaRede`); `services/rede.py:601-632`. **Impacto:** técnico — herda C-02 em `escolas_atingiram`; usuário — nenhum; Secretaria — sem linha de base, "progresso 72%" não distingue "andamos 22 pontos" de "já estávamos em 72% quando a meta foi criada". Meta sem prazo e sem responsável não é instrumento de gestão. **Solução:** acrescentar `prazo`, `responsavel_usuario_id`, `valor_base` (congelado na criação) e `escola_id` opcional | **rápida:** só `valor_base` e `prazo`. **Esforço:** M · **Prioridade:** **P3**

**🟡 M-27 · O Assistente de IA é inacessível justamente a quem mais precisaria dele** — CONFIRMADO (*secretaria*)
**Problema:** a rota chama `negar_dado_individual`, que barra a Secretaria por construção — e a justificativa é **correta**, porque `montar_contexto` injeta a lista nominal de **todos** os alunos com nota, sem limite, mais pódios e alertas nominais. Não existe `montar_contexto_rede`. **Evidência:** `routers/ia.py:66`; `services/permissoes.py:88-92`; `services/assistente.py:159`. **Impacto:** técnico — o bloqueio não é decisão de produto, é consequência de o contexto ter sido montado com PII; usuário — nenhum; Secretaria — é o **maior valor de IA não realizado do produto**. **Solução:** `montar_contexto_rede` agregado (sem uma linha nominal) sobre `dashboard_rede` + contagens de risco, liberando o assistente sem tocar em `negar_dado_individual` | **rápida:** nenhuma; exige o contexto novo. **Esforço:** M · **Prioridade:** **P3**

**🟡 M-28 · `Nota.detalhes` replica a mesma tabela de referências em toda linha** — RISCO POTENCIAL (*dados*, medido)
**Problema:** ~1,5 KB por aluno, com `referencias`/`saturacao` **idênticas para todos os alunos da escola**, reescritas por inteiro a cada importação e a cada mudança de peso. **Evidência:** medição no banco real; `services/scoring.py:830-835`. **Impacto:** técnico — a 250 mil alunos são ~375 MB de JSON quase todo duplicado; usuário — nenhum; Secretaria — custo de banco. **Solução:** guardar as referências uma vez por escola/versão e referenciá-las | **rápida:** nenhuma barata; monitorar o tamanho. **Esforço:** M · **Prioridade:** **P4**

**🟡 M-29 · `logs_auditoria` sem retenção nem particionamento** — RISCO POTENCIAL (*dados*)
**Problema:** o modelo declara "logs nunca são apagados" e não há purga (existe só para IA e para `/exports`); `registrar` é chamado em toda ação relevante, grava `detalhes` JSON e ainda dispara `notificacoes.emitir_da_auditoria` na mesma sessão. **Evidência:** `models/nota.py:47-59`; `database.py:194`; `services/relatorios.py:29`; `services/audit.py`. **Impacto:** técnico — crescimento monotônico; usuário — nenhum; Secretaria — junta-se a C-07 (o log permanente é onde o nome sobrevive). **Solução:** política de arquivamento/particionamento | **rápida:** medir e alarmar o tamanho da tabela. **Esforço:** M · **Prioridade:** **P3**

**🟡 M-30 · Escola grande não consegue mais gerar backup restaurável** — RISCO POTENCIAL (*dados*)
**Problema:** `exportar` serializa todos os snapshots históricos num único JSON em memória e o restore tem teto de 25 MB — a 144k snapshots o arquivo já passa do teto: **o backup gera e o restore recusa**. Além disso, o restore faz `db.flush()` **por linha**. **Evidência:** `services/backup.py:89-103`, `:161`; `routers/admin.py:658`. **Impacto:** técnico — uma ida ao banco por registro; usuário — o recurso falha justamente na escola que mais precisa; Secretaria — falsa sensação de proteção (soma-se a C-06). **Solução:** exportar por streaming e restaurar em lote | **rápida:** avisar o limite na tela ao gerar. **Esforço:** M · **Prioridade:** **P3**

**🟡 M-31 · "Comece aqui": o botão Concluir aparece morto sem dizer por quê** — CONFIRMADO (*UX*)
**Problema:** no passo 3, "Configurar depois" e "Concluir" ficam lado a lado, e "Concluir" tem `disabled={!s.integracao_configurada}` sem explicação. Também falta dizer **onde conseguir a credencial** do Matific/Elefante e uma verificação de sanidade final. **Evidência:** `Comecar.tsx:182-185`, `:159-163`. **Impacto:** usuário — lê o botão desabilitado como bug logo no onboarding; técnico — nenhum; Secretaria — primeira impressão da escola nova. **Solução:** rotular o motivo ("Conecte ao menos uma plataforma para concluir") e transformar "Configurar depois" em link secundário | **rápida:** só o rótulo. **Esforço:** P · **Prioridade:** **P3**

**🟡 M-32 · Sincronização pinta estado normal como falha vermelha** — CONFIRMADO (*UX*)
**Problema:** escola nova, sem Lista Piloto, recebe mensagem de **erro** "Nenhuma turma cadastrada ainda". **Evidência:** `Sincronizacao.tsx:200-204`. **Impacto:** usuário — quem acabou de entrar acha que já quebrou algo; técnico — nenhum; Secretaria — atrito no onboarding. **Solução:** estado vazio informativo com CTA para "Comece aqui" | **rápida:** trocar o tipo da mensagem. **Esforço:** P · **Prioridade:** **P3**

**🟡 M-33 · "Excluir" e "Excluir permanentemente" lado a lado, ambos vermelhos** — CONFIRMADO (*UX*)
**Problema:** na barra de seleção em massa, um é reversível e o outro apaga dados de criança, com rótulos quase idênticos e mesma cor. **Evidência:** `TurmaDetalhe.tsx:328-335`. **Impacto:** usuário — risco real de clique errado em massa; técnico — a operação é irreversível (ver C-07 e A-23); Secretaria — perda de dado de menor por erro de interface. **Solução:** tirar a exclusão permanente da barra de massa e exigir confirmação por digitação (padrão que `Usuarios.tsx:1155-1163` já usa) | **rápida:** só mudar cor/rótulo e mover para um submenu. **Esforço:** P · **Prioridade:** **P2**

**🟡 M-34 · Premiações não leva ao certificado** — CONFIRMADO (*UX*)
**Problema:** o gestor vê o campeão e precisa ir a Relatórios, achar o nome num dropdown (que trunca em 100 — A-11) e emitir. **Evidência:** `Premiacoes.tsx:42-78`; `Relatorios.tsx:90-95`. Também: o card ao vivo pode ficar até 180 s mostrando só "Consultando o Matific…", sem barra e sem cancelar (`:121, :165`). **Impacto:** usuário — 5 cliques e duas telas para o que deveria ser 1; técnico — nenhum; Secretaria — **premiação é o nome do produto** e o fluxo termina fora dele. **Solução:** botão "Emitir certificado" no próprio pódio + "gerar os 4 certificados deste período" | **rápida:** só o botão no card do campeão. **Esforço:** P · **Prioridade:** **P2**

**🟡 M-35 · Métricas recalcula a escola inteira sem prévia, sem histórico e sem reversão** — CONFIRMADO (*UX*)
**Problema:** salvar pesos altera o ranking de todo mundo sem "ver o efeito antes de aplicar", apesar de existir um **Simulador** que faz exatamente essa conta — em outra tela, desconectado. **Evidência:** `configuracoes/Metricas.tsx`; `pages/Simulador.tsx`. **Impacto:** usuário — mudança irreversível às cegas; técnico — recálculo caro disparado por engano; Secretaria — ranking do município muda sem trilha de "voltar ao anterior". **Solução:** embutir o Simulador como painel de prévia ao lado dos sliders + histórico de versões de configuração | **rápida:** exibir "com estes pesos, N alunos mudam de posição" antes de confirmar. **Esforço:** M · **Prioridade:** **P3**

**🟡 M-36 · Barra relativa sem rótulo na Visão da Escola** — CONFIRMADO (*UX*)
**Problema:** a barra é normalizada pelo **maior valor da escola**, não por 100, e nada na tela avisa. Turmas com média 40 e 42 aparecem como "metade" e "cheia". **Evidência:** `VisaoEscola.tsx:326`. **Impacto:** usuário — leitura visual completamente errada da diferença entre turmas; técnico — nenhum; Secretaria — decisão sobre turma baseada em ilusão gráfica. **Solução:** escala fixa 0–100 ou rótulo explícito da escala | **rápida:** o rótulo. **Esforço:** P · **Prioridade:** **P2**

**🟡 M-37 · Sem portabilidade por titular e sem caminho de encerramento de escola/rede (LGPD art. 18)** — CONFIRMADO (*observabilidade*)
**Problema:** não há endpoint de acesso/portabilidade por titular; o único export é backup por escola (admin) e PDFs. O modelo `ResponsavelAluno` existe, mas **nenhum router o utiliza** — o produto modela o responsável e não lhe oferece caminho. Também não existe exclusão de escola/rede (`delete(Escola)` = zero ocorrências). **Evidência:** `services/relatorios.py:65, 150, 184`; grep citado. **Impacto:** técnico — funcionalidade ausente; usuário — a família não tem como pedir os dados da criança; Secretaria — obrigação legal do controlador sem ferramenta, e fim de contrato sem procedimento. **Solução:** relatório de titular (dados + origem) e rotina de encerramento | **rápida:** documentar o procedimento manual no DPO/runbook. **Esforço:** G · **Prioridade:** **P3**

**🟡 M-38 · Teto de 1024 tokens de resposta no assistente** — RISCO POTENCIAL (*secretaria*)
**Problema:** `AI_MAX_TOKENS = 1024` corta respostas do tipo "liste os 12 alunos que concentram as notas baixas e o porquê". **Evidência:** `core/config.py:141`, usado em `services/ia/provedores.py:35, 70`. **Não foi possível validar em execução** (sem chave configurada no ambiente auditado). **Impacto:** usuário — resposta truncada no meio; técnico — configuração; Secretaria — percepção de produto incompleto. **Solução:** elevar o teto e paginar | **rápida:** elevar o teto. **Esforço:** P · **Prioridade:** **P3**

**🟡 M-39 · Custo do assistente cresce linearmente com o tamanho da escola, e o cache está no lugar errado** — RISCO POTENCIAL (*secretaria*)
**Problema:** `montar_contexto` monta a cada pergunta: ranking completo, 2 pódios, `ranking_evolucao(30d)`, `indices_da_escola` (que roda `ranking_evolucao` **4 vezes**), `alertas_da_escola`, `resumo_escola` e uma linha por aluno — milhares de tokens por pergunta numa escola de 600 alunos, recomputados do banco. O `cache_control` `ephemeral` top-level posiciona o breakpoint no **último bloco cacheável** (a pergunta do usuário, que muda sempre), então a **primeira** pergunta de cada conversa paga escrita integral e nunca lê. **Evidência:** `services/assistente.py:159`; `services/ia/provedores.py:38`. **Não foi possível validar** sem métricas de leitura de cache em produção. **Impacto:** técnico — custo e latência; usuário — resposta lenta; Secretaria — custo por pergunta imprevisível. **Solução:** breakpoint explícito no bloco `system` para que todas as conversas da escola compartilhem o prefixo | **rápida:** limitar `linhas_alunos` ao top-N relevante. **Esforço:** M · **Prioridade:** **P3**

**🟡 M-40 · O provedor padrão de fábrica não é um modelo de linguagem** — RISCO POTENCIAL (*secretaria*)
**Problema:** `LocalProvedor` é casamento de palavra-chave contra seções fixas do contexto — honesto e nunca alucina, mas o padrão do sistema é `AI_PROVIDER = "local"`. **Evidência:** `services/ia/provedores.py:100-140`; `core/config.py:138`. **Impacto:** usuário — o "Assistente Pedagógico" que o gestor vê é um buscador de seções; técnico — nenhum; Secretaria — expectativa versus entrega no item mais vendável do pitch. **Solução:** decisão de produto (configurar provedor ou renomear a funcionalidade no modo local) | **rápida:** rotular a tela como "Busca no contexto da escola" quando o provedor for local. **Esforço:** P · **Prioridade:** **P3**

**🟡 M-41 · Divergência não resolvida: o claim atômico da fila de sync existe ou não?** — DIVERGÊNCIA ENTRE FRENTES (ver **D1**)
**Problema:** *arquitetura* cita `sync/service.py:355-361` como claim atômico correto e ponto forte; *observabilidade* aponta que `proximas_da_fila` (`sync/service.py:274-283`) é `SELECT` puro sem `FOR UPDATE SKIP LOCKED` e que `executar_por_id` (`:499-508`) não faz transição de status guardada — **não localizou** o claim que `main.py:158-160` alega. **Evidência:** as linhas citadas pelas duas frentes. **Impacto:** técnico — com `WEB_CONCURRENCY:-2` há dois schedulers varrendo a mesma fila (ver M-13); existe `uq_sync_exec_ativa` como rede em ambas as leituras; usuário — risco de coleta duplicada; Secretaria — dado de plataforma importado duas vezes. **Solução:** ler `service.py` de ponta a ponta e ou corrigir o código, ou corrigir o comentário de `main.py` | **rápida:** um teste de concorrência sobre a fila que decida a questão empiricamente. **Esforço:** P · **Prioridade:** **P2**

---

### 🟢 BAIXOS (25)

*(formato compacto: Problema · Evidência · Impacto técnico / usuário / Secretaria · Solução ideal | rápida · Esforço · Prioridade)*

**🟢 B-01 · Rotas de escrita da rede sem checagem de cargo** — CONFIRMADO (*segurança* #8)
`PUT /redes/{id}/metas`, `DELETE .../metas/{metrica}` e `PUT /redes/{id}/publico` usam só `exigir_rede` + `get_usuario_atual`. · `routers/rede.py:416-431, :432-444, :494-508`; `/redes/gerenciar` (`:75-77`) oferece **todos os usuários ativos** como candidatos a Secretaria. · Técnico: contradiz o tier "Secretaria = só leitura" descrito em `deps.py:57-60` · Usuário: um professor vinculado por engano liga/desliga a vitrine pública · Secretaria: metas municipais alteráveis por conta indevida. · **Ideal:** `exigir_papeis("admin","coordenador")` nas três rotas | **rápida:** idem, três linhas. · P · **P2**

**🟢 B-02 · `.gitignore` não cobre `backend/*.db`** — CONFIRMADO (*segurança* #9)
Cobre `backend/e2e.db` e `database/*.db`, mas `backend/demo-rc.db` (696 KB, presente no working tree) não é ignorado. · `.gitignore:28, :40`. Conteúdo verificado: 15 alunos e 1 usuário **sintéticos** — hoje **não** há PII real. · Técnico: um `git add -A` commitaria qualquer `backend/*.db` futuro · Usuário: nenhum · Secretaria: risco de vazamento de base em repositório. · **Ideal/rápida:** trocar por `backend/*.db` e `backend/*.db-*`. · P · **P2**

**🟢 B-03 · Reset de senha não aplica a regra "senha ≠ e-mail"** — CONFIRMADO (*segurança* #10)
`validar_forca_senha(valor)` é chamada **sem** o argumento `email` no fluxo de link, enquanto o cadastro passa. · `routers/auth.py:157-163` × `admin.py:100-106`; regra existe em `core/security.py:170-173`. · Técnico: regra existente que não roda · Usuário: senha fraca aceita · Secretaria: baixo. · **Ideal/rápida:** passar o e-mail. · P · **P2**

**🟢 B-04 · Mensagem de erro do restore vaza caminho interno** — CONFIRMADO (*segurança*, colateral do #4)
Devolve ao cliente o texto da exceção com o caminho do módulo Python. · `routers/admin.py:671-673` repassa `str(erro)`. · Técnico: fingerprinting · Usuário: mensagem incompreensível · Secretaria: nenhuma. · **Ideal:** mensagem genérica + log completo | **rápida:** idem. · P · **P3**

**🟢 B-05 · SSRF: janela de DNS rebinding no coletor de avaliações** — RISCO POTENCIAL (*segurança*)
`_exigir_destino_publico` resolve com `getaddrinfo` e valida IP público a cada salto (defesa **acima da média**), mas o `httpx` resolve de novo ao conectar (TOCTOU). · `services/avaliacoes.py:440-486`; alcançável só por **admin global** (`:301-333`). · Técnico: TTL 0 poderia devolver IP interno na segunda resolução · Usuário: nenhum · Secretaria: baixo (exige a conta mais privilegiada). · **Ideal:** conectar ao IP validado com `Host` header fixo | **rápida:** aceitar o risco documentado. · M · **P4**

**🟢 B-06 · `TRUSTED_PROXY_HOPS=1` depende do comportamento do edge** — **Não foi possível validar com as informações disponíveis** (*segurança*)
O anti-spoofing de XFF está implementado corretamente (Nª entrada da direita). Se o edge do Railway não appendar exatamente 1 hop, o limitador por IP chaveia no valor errado. · `core/rate_limit.py:92-113`. · Técnico: limitador ineficaz · Usuário: nenhum · Secretaria: baixo. · **Ideal:** medir o header real em produção | **rápida:** logar o XFF bruto uma vez. · P · **P3**

**🟢 B-07 · Sem cabeçalhos de segurança nas respostas da API** — RISCO POTENCIAL (*segurança*)
CSP/nosniff/HSTS existem só no `vercel.json` e no `nginx.conf`; o FastAPI no Railway não adiciona nenhum. · `main.py` (só observabilidade + CORS). · Técnico: baixo impacto direto (JSON, token em `Authorization`); o `/escolas/{id}/painel-publico/qr` devolve `image/svg+xml` sem `X-Content-Type-Options`, mitigado por `Content-Disposition: attachment` · Usuário/Secretaria: baixo. · **Ideal/rápida:** middleware de headers. · P · **P3**

**🟢 B-08 · `routers/mobile.py` importa funções privadas de `rankings.py`** — CONFIRMADO (*arquitetura*)
`from app.routers.rankings import _ranking, montar_dashboard`; `montar_dashboard` já tem docstring dizendo que foi "extraído do endpoint para ser reutilizado" — reconheceu-se que é service e ficou no router. · `routers/mobile.py:21`; `rankings.py:317-322`. · Técnico: mesmo padrão de A-06 · Usuário/Secretaria: nenhum. · **Ideal:** mover para `services/` | **rápida:** nenhuma necessária. · P · **P4**

**🟢 B-09 · Três expressões paralelas da mesma autorização** — RISCO POTENCIAL (*arquitetura*)
`core/deps.py` (portão real) + guards de rota + grupos do menu; coerentes hoje, e o código diz claramente que o backend é a trava real. · `App.tsx:92-125`; `Layout.tsx:200-241`. · Técnico: cada rota nova exige três edições e nada detecta o esquecimento · Usuário: item de menu que redireciona, ou tela sem entrada no menu · Secretaria: nenhuma. · **Ideal:** derivar menu e guards de uma fonte única | **rápida:** teste que compare as três listas. · M · **P4**

**🟢 B-10 · E-mail de contato no `USER_AGENT` da geocodificação** — SUGESTÃO (*arquitetura*)
`contato: suporte@constelaedu.com` no código. · `services/geocodificacao.py:27`. · Técnico: valor que pertence a config · Usuário/Secretaria: nenhum. · **Ideal/rápida:** mover para `core/config.py`. · P · **P4**

**🟢 B-11 · Pasta `frontend/` vazia na raiz** — CONFIRMADO (*arquitetura*)
0 arquivos `.js/.ts/.tsx/.html/.json`; resquício do layout anterior a `apps/web`. · Técnico: ruído · Usuário/Secretaria: nenhum. · **Ideal/rápida:** remover. · P · **P4**

**🟢 B-12 · Duplicação nas 5 páginas de ranking** — SUGESTÃO (*arquitetura*)
Mesmo preâmbulo (`escolaId`, `useApi` de turmas com `cacheMs`, estado `periodo`/`alvo`, tradução do filtro) repetido cinco vezes — e **já divergindo**: `RankingGeral.tsx:53-56` usa `URLSearchParams`, `RankingLeitura.tsx:31-35` usa template string com ternário aninhado. · Técnico: divergência silenciosa de filtro · Usuário: comportamento sutilmente diferente entre abas · Secretaria: nenhuma. · **Ideal/rápida:** um hook `useFiltroRanking()`. · P · **P4**

**🟢 B-13 · Código órfão e aba permanentemente vazia** — CONFIRMADO (*UX*)
`pages/EmBreve.tsx` existe e **não está roteado**; a aba "Escolar" do Ranking abre "Em construção" ocupando espaço permanente. · `App.tsx`; `RankingEscolar.tsx:18-22`. · Técnico: código morto · Usuário: clica e não encontra nada · Secretaria: parece produto inacabado numa demonstração. · **Ideal:** implementar ou remover a aba | **rápida:** esconder a aba. · P · **P3**

**🟢 B-14 · Turma pede nome e série digitados à mão, sendo um derivável do outro** — CONFIRMADO (*UX*)
"Nome da turma *" (ex.: 4º Ano A) e "Série / Ano escolar *" (ex.: 4º Ano) são dois campos obrigatórios, embora o próprio arquivo já derive `ano_escolar` do nome na criação em massa. Também: campo "Escola" desabilitado só para exibir o nome, num formulário de 7 campos. · `Turmas.tsx:175-197, ~340, :200-207`. · Técnico: nenhum · Usuário: digitação duplicada em toda turma criada individualmente · Secretaria: nenhuma. · **Ideal/rápida:** pré-preencher a série a partir do nome, editável. · P · **P3**

**🟢 B-15 · Ferramentas de manutenção em destaque permanente** — RISCO POTENCIAL (*UX*)
"Corrigir duplicadas", "Fundir duplicatas", "Padronizar @" e "Professores duplicados" ocupam o lugar mais nobre, com o mesmo peso de "Adicionar aluno"/"Adicionar Turma". · `Turmas.tsx:775-788`; `Alunos.tsx:194-196`; `Usuarios.tsx:799-808`. · Técnico: nenhum · Usuário novo não distingue rotina de cirurgia · Secretaria: risco de operação destrutiva por curiosidade. · **Ideal:** menu "Manutenção de dados" | **rápida:** rebaixar a botão secundário. · P · **P3**

**🟢 B-16 · Largura fixa espreme todas as tabelas largas** — CONFIRMADO (*UX*)
`max-w-6xl` no `<main>`: prévia de importação (4 colunas + selects), comparativo da rede e rankings rolam horizontalmente mesmo num monitor de 27". · `Layout.tsx:1216`. · Técnico: nenhum · Usuário: rolagem horizontal desnecessária nas telas de decisão · Secretaria: nenhuma. · **Ideal:** largura por tipo de tela | **rápida:** liberar a largura nas telas de tabela. · P · **P3**

**🟢 B-17 · Botão "Baixar cartaz" desabilitado com o motivo só no `title`** — CONFIRMADO (*UX*)
Fora de "Ano letivo" o botão fica morto e a explicação vive num atributo `title`, invisível no celular/tablet — que é onde a coordenação usa. · `RankingGeral.tsx:123-127`. · Técnico: nenhum · Usuário: botão morto sem motivo visível · Secretaria: nenhuma. · **Ideal/rápida:** texto visível abaixo do botão. · P · **P3**

**🟢 B-18 · `livros` sem unicidade em `(escola_id, titulo)`** — SUGESTÃO / **Não foi possível validar com as informações disponíveis** (*dados*)
A dedup é aplicacional por `titulo.strip().casefold()` e `uq_leitura_unica` é `(aluno_id, livro_id)`; duas linhas para o mesmo título fariam a mesma releitura pontuar duas vezes em `livros_unicos`. · `models/plataformas.py:152-162`; `routers/importacoes.py:940-948`. Não foi possível confirmar se algum caminho real cria a segunda linha — o lock por escola e o catálogo compartilhado cobrem os caminhos lidos. · **Ideal:** constraint | **rápida:** consulta de verificação periódica. · P · **P4**

**🟢 B-19 · `APP_VERSION` com default fixo "1.0.0"** — RISCO POTENCIAL (*observabilidade*)
`.env.example` não a menciona; se o deploy não a define, todo log e todo release do Sentry dizem "1.0.0". · `core/config.py:180`. · Técnico: impossível saber qual build gerou o erro · Usuário/Secretaria: indireto. · **Ideal/rápida:** injetar o hash do commit no deploy. · P · **P2**

**🟢 B-20 · Backups off-site vivem como artefato do GitHub com 30 dias** — RISCO POTENCIAL (*observabilidade*)
Histórico máximo recuperável = 30 dias, sem camada mensal/anual, e no mesmo raio de confiança da conta do repositório. · `.github/workflows/backup.yml`. · Técnico: ponto único de confiança · Usuário: nenhum · Secretaria: perda além de 30 dias é irrecuperável. · **Ideal:** cópia mensal em armazenamento independente | **rápida:** aumentar a retenção. · P · **P3**

**🟢 B-21 · `.env.example` não documenta `SENTRY_DSN`, `LOG_LEVEL` nem `SYNC_SCHEDULER_ENABLED`** — RISCO POTENCIAL (*observabilidade*)
Quem provisiona um ambiente novo pelo exemplo sobe **sem observabilidade e sem scheduler**. · Técnico: ambiente novo nasce cego · Usuário: nenhum · Secretaria: o próximo município começa sem monitoramento. · **Ideal/rápida:** documentar as três. · P · **P2**

**🟢 B-22 · Indicadores de baixo valor ocupando a linha nobre** — SUGESTÃO (*UX*)
"Professores" como indicador principal do Dashboard (número que muda 2×/ano) e "Professores — na rede" num painel estratégico; 8 `StatCard` em bloco único, todos com o mesmo peso, incluindo "Melhor escola" (nome dentro de card de número) e "Adoção" (jargão que ninguém na secretaria usa espontaneamente). · `Dashboard.tsx:170`; `RedeDashboard.tsx:648-673`. · Técnico: nenhum · Usuário: hierarquia visual desperdiçada · Secretaria: o painel não destaca o que exige decisão. · **Ideal:** trocar por frescor do dado e por "escolas sem nenhum dado" | **rápida:** rebaixar os dois cards. · P · **P3**

**🟢 B-23 · Sincronização: quatro ações parecidas no cabeçalho e um "Resolver" que não resolve** — CONFIRMADO (*UX*)
"Atualizar" (recarrega a tela) e "Sincronizar agora" (dispara coleta) lado a lado; "Resolver" apenas marca o alerta como resolvido. Falta "próxima sincronização às HH:MM" — o usuário vê a última, nunca a próxima. · `Sincronizacao.tsx:168-186, :289-290`. · Técnico: nenhum · Usuário: efeitos muito diferentes com nomes parecidos · Secretaria: nenhuma. · **Ideal:** renomear para "Marcar como resolvido" e levar à correção + exibir a próxima execução | **rápida:** o rename. · P · **P3**

**🟢 B-24 · Criar usuário exige que o gestor invente e transmita uma senha em texto** — CONFIRMADO (*UX*)
O mesmo arquivo já sabe gerar link de redefinição de uso único. · `Usuarios.tsx:942-944` × `:220-254`. · Técnico: nenhum · Usuário: senha trafega por WhatsApp/papel · Secretaria: prática fraca de credencial, evitável com código existente. · **Ideal:** "criar e enviar link" como padrão | **rápida:** oferecer as duas opções com o link em destaque. · P · **P2**

**🟢 B-25 · Contagem de turmas diverge entre a escola e a Secretaria** — CONFIRMADO (*dados*, achado menor de A-02)
`rankings.py:332` conta turmas **sem** `status == "ativa"`; `rede.py:172-178` conta **com**. · Técnico: duas definições · Usuário: o total do painel da escola inclui arquivadas · Secretaria: número diferente do da escola. · **Ideal/rápida:** padronizar o filtro. · P · **P2**

---

## 4. VULNERABILIDADES

Todas as vulnerabilidades abaixo foram levantadas pela frente de segurança (com PoC executado contra a aplicação real, salvo indicação) e pelas frentes de dados e observabilidade nos itens de LGPD. **Nenhum ataque foi executado contra produção** — os PoCs rodaram em SQLite em memória, fora do repositório.

---

**V1 — Escalada de privilégio: admin de escola assume a conta da Secretaria**
- **Local:** `backend/app/routers/admin.py:157-166` (`_usuario_alvo`), `:291-299`, `:330-386`; `backend/app/routers/rede.py:283-312`
- **Como explorar:** com conta de admin da Escola A, chamar `PATCH /escolas/{A}/usuarios/{sec_id}` com `{"senha": "..."}` — ou `POST /escolas/{A}/usuarios/{sec_id}/redefinir-senha` — porque `_usuario_alvo` só protege contas `is_global` e a conta da Secretaria mantém o `escola_id` da escola de origem. Depois, logar como Secretaria.
- **Impacto:** leitura de dashboard, ranking, boletim PDF e todos os GET por escola de **todas as escolas do município**. Rompe o isolamento que `exigir_rede` foi escrito para garantir.
- **Severidade:** 🔴 **CRÍTICA** (PoC executado com sucesso; sequência completa: 403 antes → 200 depois)
- **Correção:** negar em `_usuario_alvo` quando `alvo.rede_id is not None and not ator.is_global`; e zerar `escola_id` ao promover a Secretaria em `definir_usuarios`.

**V2 — Vazamento de PII de menores: `GET /escolas/{id}/backup` acessível à Secretaria**
- **Local:** `backend/app/routers/admin.py:631-647`; `core/deps.py:143-166`; `routers/rede.py:283-312`
- **Como explorar:** promover (ou já ter promovido) a Secretaria a partir de um usuário com `cargo="admin"` — `definir_usuarios` aceita qualquer `usuario_id`. `escola_autorizada` libera GET em qualquer escola da rede e `exigir_papeis("admin")` passa. Baixar o backup de qualquer escola.
- **Impacto:** JSON completo com nome civil, `data_nascimento` e `observacoes` (campo livre onde entram laudos), além de matrículas, leituras e notas de **qualquer escola da rede**. É a única rota de PII de escola fora de `negar_secretaria`.
- **Severidade:** 🔴 **CRÍTICA** (LGPD/ECA; PoC: `cargo="coordenador"` → 403 sem vazamentos; `cargo="admin"` → 200 com NOME, OBS e NASC)
- **Correção:** `admin.router` com `dependencies=[Depends(negar_secretaria)]`; ou `permissoes.negar_dado_individual` dentro de `baixar_backup`/`restaurar_backup`; e recusar `cargo="admin"` como Secretaria.

**V3 — Backdoor reivindicável: e-mail hardcoded promovido a `is_global` a cada boot**
- **Local:** `backend/app/core/database.py:156-170`; chamado por `backend/app/main.py:64`; criação livre em `admin.py:211-231`
- **Como explorar:** com conta de admin de escola, criar um usuário com o e-mail do owner e senha à escolha (`POST /escolas/{id}/usuarios`, cargo `professor`). No próximo restart/redeploy, `_promover_admin_global` faz `UPDATE usuarios SET is_global = true`. Logar.
- **Impacto:** admin de escola → **Admin Global** (todas as redes, todas as escolas, `panorama-global`, `/presenca/sessoes`, backup com PII de todas).
- **Severidade:** 🔴 **CRÍTICA em ambiente novo** / 🟡 contida na produção atual. **Pré-condição honesta:** na produção atual a conta já existe e o `UNIQUE` em `usuarios.email` devolve 409 (inclusive com `status="excluido"`). Vale para **município novo, staging, homologação e restauração de desastre**. *(Aqui as frentes divergiram — ver D2.)*
- **Correção:** `ADMIN_GLOBAL_EMAIL` por variável de ambiente, aplicada **uma vez no provisionamento**, nunca num UPDATE a cada boot; barrar a criação de usuários com o e-mail do owner por rotas de escola.

**V4 — Enumeração de contas de menores no Quest (sem autenticação)**
- **Local:** `backend/app/quest/services/credenciais.py:34-83`; `backend/app/quest/routers/auth.py:41, :105-128`
- **Como explorar:** força bruta em `POST /quest/auth/quem`. Espaço = 147 palavras × 900 = **132.300 (~2^17)**; com 2000 alunos a densidade é 1,51% (~66 palpites por acerto) e o teto por IP (50 falhas/300 s) permite 14.400 tentativas/dia → **~218 contas por dia de um único IP**. O limitador é **por processo** e, na topologia real (Railway, sem nginx na frente), **não há limite de borda** — o próprio código reconhece isso em `auth.py:35-37`.
- **Impacto:** colheita de **nomes reais de crianças** (`/quem` devolve `nome_para_falas`) e sequestro de contas (`/entrar` cria sessão de 30 dias).
- **Severidade:** 🟠 **ALTA**
- **Correção:** ampliar o código (formato "2 palavras + 4 dígitos" já suportado por `formatar_codigo_exibicao`), limitador em armazenamento compartilhado + limite de borda; alternativa barata: exigir turma/escola junto do código em `/quem`.

**V5 — Direito ao esquecimento não cumprido: nome de menor sobrevive à exclusão permanente**
- **Local:** `backend/app/routers/academico.py:493-509`
- **Como explorar:** não é ataque — é falha de conformidade. Basta importar normalmente (gera `aluno.criado_auto` com `entidade_id=None`) e depois excluir permanentemente o aluno; o nome permanece em `logs_auditoria`, que é permanente por design.
- **Impacto:** LGPD art. 18; prova executada mostra **4 de 5 linhas ainda com o nome do menor**. O teste que valida o esquecimento usa o mesmo filtro defeituoso do código e não pode falhar.
- **Severidade:** 🔴 **CRÍTICA** (conformidade)
- **Correção:** redigir por chave semântica (`nome`, `origem`, `nome_antigo`, `nome_novo`, `aluno`, `origem_linha`) e remover o filtro `entidade_id`, varrendo por `escola_id` + conjunto de nomes; reescrever o teste sem o filtro do código.

**V6 — Destruição de dados por restauração de backup**
- **Local:** `backend/app/services/backup.py:41-57, :131-132`; cascades em `alembic/versions/0013`, `0010`, `0003`
- **Como explorar:** não é ataque — é o botão funcionando como implementado. Restaurar qualquer backup apaga `Aluno` e, por cascade, `identidades_externas`, `eventos_aluno`, `quest_perfis`, `quest_credenciais_aluno`, `responsaveis_alunos` — nenhum deles está no arquivo.
- **Impacto:** perda irreversível do mapa UUID↔aluno (**reabre o P0 de duplicatas**, porque a sync volta a casar por nome), da linha do tempo e das contas Quest das crianças. A resposta é "Backup restaurado com sucesso".
- **Severidade:** 🔴 **CRÍTICA**
- **Correção:** falhar de saída se houver linha fora de `MODELOS` que o cascade apagaria, ou completar `MODELOS`; enquanto isso, desabilitar o botão.

**V7 — Fixação de chave primária via arquivo de backup**
- **Local:** `backend/app/services/backup.py:143-147, :159`
- **Como explorar:** admin de escola edita o JSON de backup incluindo `id` arbitrário; a restauração não reaplica o filtro `IGNORADAS` usado na exportação.
- **Impacto:** PKs arbitrárias ocupadas em tabelas compartilhadas. **Não validado em PostgreSQL a partir daqui**, mas em Postgres um `INSERT` com id explícito não avança a sequence — inserções futuras de **qualquer escola** colidiriam em cadeia (DoS multi-tenant). Cross-tenant por `escola_id` está barrado por acidente feliz (colisão de kwarg → `TypeError` → 400).
- **Severidade:** 🟡 **MÉDIA**
- **Correção:** aplicar `IGNORADAS` também no `restaurar`.

**V8 — Exposição de infraestrutura em `/api/health` anônimo**
- **Local:** `backend/app/main.py:207-232`; `core/automacao.py:44-49`
- **Como explorar:** um `GET` sem autenticação e sem rate limit.
- **Impacto:** versão, estado do Sentry, diagnóstico das páginas de login de Matific/Elefante, estado do scheduler, uptime e **IP/ASN/cidade de saída real do backend** — útil para contornar proxy/WAF. Incoerente com `/metrics`, que é fail-closed.
- **Severidade:** 🟡 **MÉDIA**
- **Correção:** proteger o health detalhado com `METRICS_TOKEN`, mantendo `/live` e `/ready` públicos; ou remover `egress` e `login_paginas`.

**V9 — Amplificação de carga no painel público (sem autenticação, sem limitador)**
- **Local:** `backend/app/routers/publico.py:94-123`; `backend/app/services/rede.py:661-675`
- **Como explorar:** requisições repetidas com token inválido. Tokens inválidos nunca são cacheados, então cada uma executa o SELECT de todas as configs `painel_publico` e compara linha a linha; `rede_pelo_token_publico` carrega **todas** as redes com token, sem cache nenhum.
- **Impacto:** amplificação barata que escala com o número de escolas do SaaS. Disponibilidade, não vazamento. Combina-se com A-07 (a mesma rota faz varredura de histórico completo).
- **Severidade:** 🟡 **MÉDIA**
- **Correção:** cache negativo curto (LRU com TTL) + `LimitadorTentativas` por IP nas rotas `/publico/*`.

**V10 — Rotas de escrita da rede sem checagem de cargo**
- **Local:** `backend/app/routers/rede.py:416-431, :432-444, :494-508`
- **Como explorar:** qualquer conta com `rede_id` (e `/redes/gerenciar` oferece **todos** os usuários ativos como candidatos) altera metas municipais e liga/desliga a vitrine pública da rede.
- **Impacto:** contradiz o tier "Secretaria = só leitura"; exposição pública ligada por conta indevida.
- **Severidade:** 🟢 **BAIXA** (exige conta já vinculada à rede)
- **Correção:** `exigir_papeis("admin", "coordenador")` nas três rotas.

**V11 — Regra de senha não aplicada no fluxo de redefinição por link**
- **Local:** `backend/app/routers/auth.py:157-163` (× `admin.py:100-106`)
- **Como explorar:** usar o link de redefinição e escolher a própria conta de e-mail como senha; `validar_forca_senha` é chamada sem o argumento `email`, então a regra de `core/security.py:170-173` não roda.
- **Impacto:** senha trivialmente adivinhável aceita no fluxo mais usado de recuperação.
- **Severidade:** 🟢 **BAIXA**
- **Correção:** passar o e-mail para a validação.

**V12 — Base SQLite fora do `.gitignore`**
- **Local:** `.gitignore:28, :40`; arquivo `backend/demo-rc.db` (696 KB) no working tree
- **Como explorar:** um `git add -A` (o histórico registra um processo DevOps paralelo que varre o index) commitaria qualquer `backend/*.db`.
- **Impacto:** hoje **não** há PII real no arquivo (15 alunos e 1 usuário sintéticos, verificado). O risco é o padrão, não o conteúdo atual.
- **Severidade:** 🟢 **BAIXA**
- **Correção:** `backend/*.db` e `backend/*.db-*` no `.gitignore`.

**V13 — SSRF com janela de DNS rebinding no coletor de avaliações externas**
- **Local:** `backend/app/services/avaliacoes.py:440-486` (alcançável só por admin global, `:301-333`)
- **Como explorar:** hospedar um domínio com TTL 0 que resolva primeiro para IP público (passando `_exigir_destino_publico`) e depois para `169.254.169.254` quando o `httpx` resolver de novo ao conectar.
- **Impacto:** acesso a metadados internos. A defesa existente é **acima da média** (valida IP público a cada salto, com `follow_redirects=False` manual); resta o TOCTOU clássico. Exige a conta mais privilegiada do sistema, o que reduz muito o valor do ataque.
- **Severidade:** 🟢 **BAIXA** (RISCO POTENCIAL)
- **Correção:** conectar ao IP já validado, fixando o `Host` header.

---

### 4.1 O que foi verificado e está CORRETO (não re-auditar)

- **Secretaria × PII individual:** varredura de **45 rotas GET** com aluno-canário (nome, observações e data de nascimento marcados) — `alunos` 200 mas vazio; `perfil` 404; `leituras`, `linha-do-tempo`, `espelho`, `mural`, `comparar-aluno`, `assistente` 403; `ranking*`, `dashboard`, `matific`, `elefante`, `insights`, `sincronizacao`, `pesquisa` 200 **sem uma linha de PII**. Resultado: `VAZAMENTOS: nenhum`. Única exceção: V2.
- **Painel público:** anonimização por padrão com gate de confirmação **no servidor**, k-anonimato, `Aluno.status == "ativo"` no ranking, `_ids_visiveis` bloqueando enumeração por `aluno_id`, `compare_digest` com guarda `isascii()` contra 500, `Cache-Control: no-store`. Verificado também que desativar o painel ou rotacionar o token **não** fica preso no cache, porque `_escola_pelo_token` valida contra o banco antes de ler o cache (`publico.py:371-382`).
- **IDOR entre escolas:** tudo sob `/escolas/{id}` passa por `escola_autorizada`; `_lado_aluno`/`_lado_turma`/`resumo_turma` re-checam `escola_id`; `comparar` bloqueia lado "escola" alheio para não-global; `sync` re-checa `ex.escola_id`/`al.escola_id`.
- **Upload / path traversal:** regex de token, `is_relative_to` na origem e no destino, basename saneado, extensão restrita; imagem re-codificada para PNG via Pillow, matando polyglot.
- **Autenticação:** bcrypt com limite de 72 bytes, `dummy_verify` anti-timing, mensagem única para conta inexistente e senha errada, limitador duplo, `token_version`, token de reset de 256 bits guardado só como SHA-256, JWT preso a HS256 com rejeição cruzada do claim `papel` entre Edu e Quest.
- **CORS:** lista fixa, sem wildcard, `allow_credentials` com origens explícitas.
- **Cofre de credenciais:** Fernet com `DATA_ENCRYPTION_KEY` separada da `SECRET_KEY`, `MultiFernet` para rotação, unicidade `(escola_id, plataforma)`, nada devolvido ao navegador.
- **Sentry:** `send_default_pii=False`, `include_local_variables=False`, `max_request_body_size="never"`, redação de token em rota e query — coberto por teste.

---

## 5. TOP 10

### 5.1 Top 10 pontos positivos

| # | Ponto | Por quê |
|---|---|---|
| 1 | PII da Secretaria bloqueada **por construção** (`permissoes.py:44-49`, `deps.py:154-174`) | 45 rotas varridas, zero vazamentos; a escrita é negada num único ponto |
| 2 | Motor de pontuação sem número mágico, com saturação de volume (`scoring.py:117-125, 543-544`) | Diferença entre premiar quem lê e premiar quem clica |
| 3 | Três advisory locks com hierarquia anti-deadlock **escrita** (`database.py:130-134`) | O comentário nomeia a pior consequência: "corrupção silenciosa é o dano real" |
| 4 | Transparência do cálculo em `Nota.detalhes` + "nenhuma IA participa dos números" (`insights.py:1-6`) | Auditabilidade é vantagem competitiva em compra pública |
| 5 | Pseudonimização real antes de mandar dado a LLM externo, com a limitação documentada (`assistente.py:12-26`) | Raríssimo; e a honestidade sobre o limite vale tanto quanto o mecanismo |
| 6 | Separar desempenho de cobertura: o corte é pela existência do snapshot (`rede.py:102-137`) | Sutileza de quem apanhou de dado real (o caso "42/54") |
| 7 | Comparação per capita + índice 0–1000 reusando o mesmo motor (`rede.py:302-357`) | Nenhuma segunda lógica de pontuação; correto e bem argumentado |
| 8 | Higiene de PII no log, aplicada em todos os pontos (`importacoes.py:203-207, :1316-1322`) | Não loga nome de arquivo de relatório individual porque traz nome de criança |
| 9 | `useApi` com cancelamento, timeout, retry só em falha transitória e cache (`hooks/useApi.ts`) | Substituiu de fato o antipadrão que engolia erro |
| 10 | Comentários que explicam o **porquê** e registram o bug que motivou a linha | É o que tornou esta auditoria possível: separam decisão consciente de defeito |

### 5.2 Top 10 problemas

| # | Problema | ID | Severidade |
|---|---|---|---|
| 1 | Nota geral com teto de 50 para quem usa uma só plataforma — ranking por adesão | C-01 | 🔴 |
| 2 | A métrica que governa o painel da Secretaria não compara escolas | C-02 | 🔴 |
| 3 | Admin de escola toma a conta da Secretaria e lê a rede inteira | C-03 | 🔴 |
| 4 | `GET /backup` entrega PII de criança à Secretaria | C-04 | 🔴 |
| 5 | Restaurar backup destrói dados que o backup não contém (reabre o P0) | C-06 | 🔴 |
| 6 | Nome de menor sobrevive à exclusão permanente | C-07 | 🔴 |
| 7 | E-mail hardcoded auto-promovido a Admin Global | C-05 | 🔴 |
| 8 | Notas órfãs: posições duplicadas e contagem maior que a matrícula | A-01 | 🟠 |
| 9 | Três "Média geral" diferentes para a mesma escola | A-02 | 🟠 |
| 10 | Leitura sem janela de data: o produto fica mais lento a cada ano letivo | A-07 | 🟠 |

### 5.3 Top 10 melhorias técnicas

| # | Melhoria | Resolve |
|---|---|---|
| 1 | `WHERE data_referencia >=` em `_series_por_aluno` | A-07 (≈90% do tempo das rotas mais lentas, inclusive a pública) |
| 2 | `services/snapshots.py` com `ultimo_por_aluno()` única + índice `(escola_id, aluno_id, data_referencia DESC, id DESC)` | A-05, M-12 |
| 3 | Extrair `services/identidade_aluno.py` e `importacao_pipeline.aplicar()` do router | A-06 |
| 4 | `response_model` em `rede.py`, `evolucao.py`, `gamificacao.py` | A-04, M-11 |
| 5 | `Usuario.professor_id` (FK) com backfill por e-mail | A-03 |
| 6 | `recalcular_rede` como tarefa de fila com status consultável | A-08 |
| 7 | `COUNT(DISTINCT)` em SQL + cache TTL no `panorama-global` | A-09 |
| 8 | Semáforo global para Chromium + logar os 6 fallbacks silenciosos | A-10, M-10 |
| 9 | `pytest -m postgres` no job que já sobe Postgres + `--cov-fail-under` | A-16, M-07 |
| 10 | Ler `X-Request-ID` no cliente e telemetria de erro no frontend | A-14 |

### 5.4 Top 10 melhorias para a Secretaria

| # | Melhoria | Por quê |
|---|---|---|
| 1 | Trocar `media_geral` pelo índice per capita no painel, atenção, metas, boletim e vitrine | Corrige a régua com que ela decide (C-02) |
| 2 | Inverter a ordem da lista "Escolas que precisam de atenção" | Hoje a lista de ação está de trás para frente (A-18) |
| 3 | Contagens de risco por escola, sem PII (`sem_atividade_30d`, `queda_acertos`, `abaixo_da_mediana`, `sem_dados`) | Responde "quais crianças precisam de intervenção" sem tocar em LGPD (A-19) |
| 4 | Delta de 30/90 dias por escola | Responde "quem está piorando", hoje sem resposta (A-17) |
| 5 | Digest semanal por e-mail/push com quem caiu, quem subiu e metas fora de rota | Faz o produto procurar o Secretário (A-15) |
| 6 | Total de escolas **sem nenhum dado**, em destaque | A escola que não usa some do ranking em vez de aparecer como problema |
| 7 | Metas com prazo, responsável, linha de base e desdobramento por escola | Vira instrumento de gestão, não número na tela (M-26) |
| 8 | Assistente de rede sobre contexto agregado | Maior valor de IA não realizado (M-27) |
| 9 | Renomear "Panorama"/"Painel" e descrever cada item do menu | O perfil que decide a compra tem dois itens indistinguíveis (M-16) |
| 10 | Boletim mensal agendado e arquivado | Reusa `gerar_boletim_rede` inteiro; hoje é sob demanda |

### 5.5 Top 10 melhorias de inteligência pedagógica

| # | Melhoria | Fonte já existente | Complexidade |
|---|---|---|---|
| 1 | Renormalizar a nota sobre as plataformas em que o aluno tem dado | `rede.py:102-115` (regra já escrita) | M |
| 2 | Delta de **turma** em duas janelas: "3ºB caiu 14% em dois meses" | `evolucao._monta_resumo_turma:532` | M |
| 3 | Alerta de **nível de leitura estagnado** ("8 alunos do 4º ano lêem há 3 meses só no nível AA") | `SnapshotElefante.livros_por_nivel` + `evolucao._delta_niveis:77` — **hoje não vira alerta nenhum** | M |
| 4 | Curva de concentração: "12 alunos concentram 63% das notas baixas" | `Nota` com `ix_notas_escola_ano_posicao` | B |
| 5 | Qualidade × volume: separar "leu muito e errou muito" de "leu pouco e acertou" | `insights._pct_acertos:41` | B |
| 6 | Turmas paradas: % de alunos sem snapshot novo em 30 dias, agregado por `turma_id` | `alertas_da_escola` + `Matricula.turma_id` — dá o alvo real (o professor) | B |
| 7 | Score de risco composto por aluno (hoje um aluno com 3 alertas aparece 3 vezes, sem peso) | `insights.alertas_da_escola:176-278` | M |
| 8 | Persistência do risco ("em risco há 6 semanas") | histórico de alertas | M |
| 9 | Ponto cego declarado: `abaixo_da_turma` compara com a mediana da própria turma — numa turma inteira fraca **ninguém** dispara | escolha defensável, mas a Secretaria deveria enxergar de cima | B |
| 10 | Bônus de horário como sinal pedagógico: "esta turma só lê em casa" × "só lê na escola" | já calculado, hoje só alimenta pontuação | M |

### 5.6 Top 10 automações

| # | Automação | Base já existente | Impacto / Esforço |
|---|---|---|---|
| 1 | Alerta de **silêncio de dados** por escola virando notificação de rede | `sync/service.verificar_obsolescencia` **já roda** no scheduler (`scheduler.py:40`) e não avisa ninguém | A / B |
| 2 | Digest semanal para a Secretaria | `push.py` e `Notificacao` existem; falta emitir escopo "rede" | A / M |
| 3 | Alertas pedagógicos materializados como notificação com rota acionável | os 4 tipos já têm `aluno_id` e gravidade | A / M |
| 4 | Detecção de duplicatas **após cada importação**, como aviso passivo | motor de dedup maduro; hoje só roda quando alguém suspeita e clica | M / B |
| 5 | Certificados em lote por turma/escola | arte e coordenadas já calibradas por plataforma | M / M |
| 6 | Boletim mensal da rede agendado | `gerar_boletim_rede` completo | M / B |
| 7 | Selo de frescor do dado no Dashboard da escola + aviso após N dias | `RedeDashboard` já calcula `escolas_desatualizadas` | A / B |
| 8 | Purga de retenção agendada (hoje só no boot) | `backend/scripts/purgar_ia.py` existe, nenhum workflow o agenda | M / B |
| 9 | Geocodificação em laço no servidor | paginação por cursor já implementada | B / B |
| 10 | Coleta de avaliações externas e sync diária **ligadas em produção** | robô pronto com anti-SSRF; `SYNC_SCHEDULER_ENABLED` é fail-safe consciente — ligar é decisão do dono, não código | A / B |

### 5.7 Top 10 aplicações de IA

| # | Aplicação | Por quê funciona aqui |
|---|---|---|
| 1 | **Narrativa sobre número já calculado** ("a Escola X caiu 14%; a queda está no 3ºB, onde 12 de 28 alunos pararam em março") | O cálculo segue determinístico; a IA só redige. Zero risco de alucinação numérica |
| 2 | **Assistente de REDE agregado** (`montar_contexto_rede` sem uma linha nominal) | Libera a IA para a Secretaria sem tocar em `negar_dado_individual` — maior valor não realizado |
| 3 | **Explicar a nota em linguagem natural** a partir de `Nota.detalhes` | Fonte é dado, saída é texto; resolve M-19 (o jargão "Normalizado") |
| 4 | **Minuta de ofício/comunicado à escola** a partir do alerta | Humano edita e assina; encurta o ciclo detectar→agir |
| 5 | **Resumo semanal por turma para a professora** | Reusa `alertas_da_escola`, que já é por aluno |
| 6 | **Tradução dos motivos de atenção** em plano de 3 passos | `_motivo_atencao` já entrega o gatilho |
| 7 | **Assistência na revisão de importação** ("estes 6 casos precisam de você; os outros 182 são seguros") | O motor já classifica confiança; falta a redação |
| 8 | **Perguntas em linguagem natural sobre o painel da rede** (após o item 2) | Contexto agregado, sem PII |
| 9 | **Detecção de anomalia narrada** ("esta escola importou 3× mais leituras que a média — confira") | Cálculo estatístico + texto |
| 10 | **Onde a IA NÃO deve entrar: calcular índice.** Manter `insights.py:1-6` como está | Número auditável vale mais que número esperto em dinheiro público |

---

## 6. QUICK WINS E MELHORIAS ESTRUTURAIS

### 6.1 Quick wins (baixo esforço, alto impacto) — todos ≤ 1 dia

| # | Ação | Arquivo | Resolve | Ganho |
|---|---|---|---|---|
| 1 | Negar `alvo.rede_id is not None` em `_usuario_alvo` | `routers/admin.py:157-166` | C-03 / V1 | Fecha escalada entre escolas com **uma condição** |
| 2 | `negar_secretaria` no `admin.router` | `main.py:147-152` | C-04 / V2 | Fecha o único furo de PII em **uma linha** |
| 3 | E-mail do admin global vindo de `settings`, sem default | `core/database.py:156` | C-05 / V3 | Nenhum ambiente novo nasce com backdoor |
| 4 | Desabilitar o botão de restauração na interface | frontend de backup | C-06 / V6 | Impede destruição irreversível até a correção |
| 5 | `WHERE data_referencia >=` em `_series_por_aluno` | `services/evolucao.py:44-56` | A-07 | Devolve ~90% do tempo das rotas mais lentas |
| 6 | Inverter a ordenação da lista `atencao` | `services/rede.py:431` | A-18 | A lista de ação passa a começar pela pior escola |
| 7 | `pytest -m postgres` no job que já tem Postgres | `.github/workflows/ci.yml` | A-16 | Protege a trava 4713 recém-entregue |
| 8 | `IGNORADAS` também no `restaurar` | `services/backup.py:143` | M-01 / V7 | Fecha a fixação de PK |
| 9 | Aviso "mostrando os primeiros 100 alunos" + busca no certificado | `Relatorios.tsx:33-35` | A-11 | Destrava a emissão em escola grande |
| 10 | `cacheMs` no consumo de `/insights` | `Dashboard.tsx:416` | M-17 | Elimina o cálculo mais caro feito duas vezes |
| 11 | Abrir o bloco de Alertas por padrão | `Insights.tsx:47` | M-18 | A tela pedagógica passa a mostrar quem precisa de ajuda |
| 12 | `logger.exception` nos 6 fallbacks silenciosos | `services/relatorios.py` | M-10 | Documento de vitrine para de degradar em silêncio |
| 13 | Semáforo global para `chromium.launch()` | `services/relatorios.py` | A-10 | Elimina o pior caso de OOM em 768 MB |
| 14 | `exigir_papeis` nas três rotas de escrita da rede | `routers/rede.py:416, 432, 494` | B-01 / V10 | Restaura o tier "só leitura" |
| 15 | `backend/*.db` no `.gitignore` + `APP_VERSION` do commit | `.gitignore`, deploy | B-02, B-19 | Higiene de repositório e de diagnóstico |

### 6.2 Melhorias estruturais (semanas, mas mudam o teto do produto)

1. **Renormalização da nota por dimensões disponíveis** (C-01) — corrige a justiça do produto no nível do aluno, que é onde a criança sente.
2. **Promover o índice per capita a métrica oficial da rede** (C-02) — o código já existe e está certo; é uma troca de consumidor, não uma construção.
3. **Camada de identidade de aluno como serviço** (A-06) — tirar `_resolver_aluno`/`_casar_no_roster` do router e dar a eles fronteira testável; é o motor mais crítico do produto.
4. **Dimensão temporal acima do aluno** (A-17) — retrato periódico dos KPIs por escola; destrava tendência, digest, meta com linha de base e "quem está piorando".
5. **Contagens de risco agregadas por escola** (A-19) — a ponte entre a blindagem de PII (que está certa) e a utilidade para a Secretaria (que falta).
6. **Trabalho pesado fora do request** (A-08, A-10, M-13) — fila para recálculo de rede, semáforo/fila para PDF, worker de sync separado. A infraestrutura de fila já existe em `sync/`.
7. **Contrato de API tipado nas rotas de rede** (A-04) — transforma a invariante de PII de convenção em garantia.
8. **Caminho do sinal até uma pessoa** (A-14, A-15) — telemetria de frontend, request-id visível, notificação que sai do banco.
9. **Ciclo de gestão fechado** (M-26 + plano de ação) — uma entidade `AcaoRede(rede_id, escola_id?, origem_alerta, responsavel, prazo, status, resultado_medido)` reusando `LogAuditoria`, `Notificacao` e o padrão de `MetaRede`. Hoje o sistema **detecta** bem, **investiga** razoavelmente e **não faz nada** de agir/responsável/prazo/medir.
10. **Política de retenção e portabilidade** (A-22, M-37) — retenção por classe de dado, relatório de titular e caminho de encerramento de escola/rede.

---

## 7. AUDITORIA DAS TELAS

**Inventário real:** 51 arquivos em `apps/web/src/pages` · 5 rotas públicas (Login, Redefinir senha, Painel Público do telão, Perfil público do aluno, Vitrine pública da rede) · ~46 rotas autenticadas com 5 guards de perfil em `App.tsx:92-125`. `pages/EmBreve.tsx` existe e **não está roteado**.
**Ressalva de escopo:** foi avaliado o código-fonte, não a interface em execução. Contraste real, foco por teclado, leitura por leitor de tela e desempenho percebido **não foi possível validar com as informações disponíveis**.

### 7.1 As 14 telas principais

| Tela (arquivo) | Objetivo · Usuário | O que está bom | O que está ruim (ID) | O que falta | Prior. |
|---|---|---|---|---|---|
| **Dashboard da escola** `Dashboard.tsx:410-500` | Retrato da escola em 5 s · coordenador (diário), professor (semanal) | Média geral com anel, 4xl e barra 0–100 (`156-167`); skeletons por seção; `/insights` em paralelo sem travar; **cada alerta é um `<Link>` acionável** (`252-268`); erro mostra `erro.message` | Média geral dentro do card "Matemática" (`320-322`); "Livros lidos"/"Tempo" repetidos em Engajamento e em Leitura; dois seletores de escola (M-21); "Professores" na linha nobre (B-22); destaques ordenados por engajamento cru, sempre os mesmos (M-18) | **Tendência** (nenhum "+3 desde a semana passada"); **data da última atualização do dado**; contagem total de alertas e "ver todos" | **ALTA** |
| **Panorama / Painel da Rede** `rede/RedeDashboard.tsx:596-812` | Retrato do município e prioridades · Secretaria | "Escolas que precisam de atenção" **antes** do ranking, com motivo; equidade em português; módulos não contratados somem; zero PII | Dois itens de menu indistinguíveis (M-16); 8 StatCard com o mesmo peso, incluindo "Melhor escola" e "Adoção" (B-22); lista de atenção **ordenada da melhor para a pior** (A-18); métrica não comparável (C-02) | Comparação temporal (A-17); total de escolas **sem nenhum dado**; "top 3 do que fazer esta semana" | **ALTA** |
| **Importações** `Importacoes.tsx` (874 l.) | Trazer dados sem estragar o cadastro · coordenador | Prévia obrigatória com "nada é gravado antes da sua confirmação"; agrupamento por aluno (centenas de linhas viram um card); vínculo automático só em alta confiança; troca de escola descarta a análise; histórico com autor/erros | Um `<select>` por linha + um segundo de turma quando é aluno novo — até 400 dropdowns numa lista de 200 (item 8.4); 3 modos sem explicação da diferença; jargão cru ("colunas por posição", "Bloqueado por conflito de identidade") (M-19); reenvio duplo do arquivo (A-21) | **Desfazer** (não existe rollback depois de confirmar); o que acontece com quem **não** está no arquivo | **CRÍTICA** |
| **Comece aqui** `Comecar.tsx` | Escola do zero ao funcionando | Stepper com estado real de `/sync/status` e **retomada** no passo certo; reusa os componentes reais; termina com 3 destinos concretos | "Concluir" desabilitado sem dizer por quê, ao lado de "Configurar depois" (M-31) | Onde conseguir a credencial das plataformas; verificação de sanidade final ("47 alunos, 3 turmas sem professor") | MÉDIA |
| **Alunos** `Alunos.tsx` | Cadastro e busca · todos | Busca com debounce 300 ms; filtro por turma; paginação de 25 com total; **"Salvar e adicionar outro" mantendo a turma** | **Beco do arquivamento** (A-12); "Fundir duplicatas" com o mesmo peso de "Adicionar aluno" (B-15) | Filtro por série (o backend já aceita `ano_escolar` e a coluna já é exibida); exportar a lista filtrada; nota/situação na lista | **ALTA** |
| **Perfil do Aluno** `PerfilAluno.tsx` | O que esta criança fez · professora | Transparência total do cálculo; abas por perfil; "Faltam apenas 7 livros..."; ficha minimizada a RA com allowlist; pesos que o motor **realmente usou** | Colunas Valor/Referência/Normalizado/Peso/Contribuição sem explicação + badge "Normalização: automática" ao lado do nome da criança (M-19); conquistas renderizadas duas vezes (M-20); Linha do tempo escondida atrás de um clique e negada ao professor | Comparação com a turma ("média da turma: 71"); evolução da nota na tela principal | **ALTA** |
| **Turmas** `Turmas.tsx` (1181 l.) | Estrutura da escola · gestão | Validação em tempo real com exemplo; **grade Ano × Letra** para criar várias marcando células, com as existentes desabilitadas; 409 tratado como "pulada"; mensagem de sucesso que diz o efeito | Nome + Série digitados à mão, sendo um derivável do outro (B-14); campo "Escola" desabilitado só para exibir; "Corrigir duplicadas" com o mesmo peso de "Adicionar Turma" (B-15) | Sinalizar turmas **sem professor** (a coluna mostra "—" e nada agrega); aviso passivo de duplicadas | MÉDIA |
| **Detalhe da Turma** `TurmaDetalhe.tsx` | Operar uma turma · gestão | 4 StatCards + busca/ordenação/"Mostrar arquivados" numa barra só; seleção em massa com barra contextual; reversíveis diretas, destrutivas com modal; cartões do Quest com QR | **"Excluir" e "Excluir permanentemente" lado a lado, ambos vermelhos** (M-33) | Distribuição ("5 alunos abaixo de 40"), não só médias | MÉDIA |
| **Rankings** `Rankings.tsx` + 5 filhas | Reconhecimento · todos | Aba única com 5 visões e **URL como fonte da verdade** (deep-link funciona); abas somem quando o módulo não é contratado; a Secretaria recebe o ranking de escolas automaticamente; "Ano letivo" × período com badge explicando; coluna "Feito no período" | "Baixar cartaz" desabilitado com o motivo só no `title` (B-17); nomes de três naturezas ("Geral", "Elefante Letrado", "Matific", "Evolução", "Escolar"); aba "Escolar" permanentemente em construção (B-13); ordenação injusta por C-01 | Exportação direta; paginação/virtualização (renderiza a escola inteira) | MÉDIA-ALTA |
| **Premiações** `Premiacoes.tsx` | Premiar · gestão | Pódio com campeão em destaque clicável; Matific ao vivo por período; **mensagem de erro que muda com o cargo** — o melhor tratamento de erro do sistema | Card ao vivo pode ficar 180 s mostrando só "Consultando o Matific…", sem barra e sem cancelar; nada leva ao certificado (M-34) | "Emitir certificado" no pódio; "gerar os 4 certificados deste período" | MÉDIA-ALTA |
| **Sincronização** `Sincronizacao.tsx` | Saúde da integração · escola-op | Badge de estado; Alertas e Histórico recolhíveis; aviso correto quando o agendador está desligado no servidor; erro do último sync exibido | Estado normal pintado como erro vermelho (M-32); enum cru do backend como texto (M-19); "Atualizar" × "Sincronizar agora" lado a lado; "Resolver" que não resolve (B-23) | "Próxima sincronização às HH:MM" | MÉDIA |
| **Usuários** `Usuarios.tsx` (1185 l.) | Contas e acesso · gestão | Matriz de permissão espelhando o backend; exclusão permanente exigindo digitar o e-mail exato; dedup de professores com checkbox e confiança; link de redefinição com copiar; folha de senhas para entrega presencial | Fora do padrão `useApi` e estado vazio ambíguo (M-23); 3 botões no cabeçalho, dois de manutenção (B-15); senha em texto no cadastro (B-24) | Busca e filtro por cargo/situação (rede com dezenas de contas não tem nem campo de busca) | MÉDIA |
| **Relatórios** `Relatorios.tsx` | Documentos · gestão e professor | 3 relatórios × 3 formatos em cards limpos; professor só vê os dois que pode; o texto explica que o certificado se preenche sozinho | **Alunos além do 100º não podem receber certificado** (A-11); um download congela a tela inteira (M-24) | Filtros por turma/bimestre (existem em Ranking e Premiações); emissão em lote | **ALTA** |
| **Métricas** `configuracoes/Metricas.tsx` | Pesos e referências · gestão | Slider + campo sincronizados; soma travada em 100% com badge; botão que diz o efeito ("Salvando e recalculando..."); Secretaria em leitura com aviso; Elefante agrupado em sub-abas | Aba "Referências de Normalização" (M-19); salva e recalcula sem prévia, com o Simulador desconectado em outra tela (M-35) | Histórico e reversão de configuração | MÉDIA |

### 7.2 Achados transversais de tela

| Achado | Evidência | Classificação |
|---|---|---|
| Não existe "Esqueci minha senha" | `Login.tsx` sem link; token só nasce por ação de gestor (`admin.py:341`) | CONFIRMADO · A-20 |
| Telas do Matific e do Elefante sem busca, filtro ou paginação | `Matific.tsx:121`, `Elefante.tsx` | CONFIRMADO · M-22 |
| Nome de cliente no código do produto | `Escolas.tsx:31, 189, 293` | CONFIRMADO · M-25 |
| `/insights` calculado duas vezes | `Dashboard.tsx:416-417` + `Insights.tsx` sem `cacheMs` | CONFIRMADO · M-17 |
| Prioridade invertida: alertas colapsados, índices sempre abertos | `Insights.tsx:47` | CONFIRMADO · M-18 |
| A legenda que ensina a ler a tela é a menor fonte e o menor contraste da página | `Insights.tsx:249-251` (~230 caracteres em `text-xs text-zinc-400`, à direita do cabeçalho) | CONFIRMADO · M-19 |
| Barra relativa sem rótulo (normaliza pelo maior valor da escola) | `VisaoEscola.tsx:326` | CONFIRMADO · M-36 |
| Largura fixa `max-w-6xl` espremendo tabelas largas | `Layout.tsx:1216` | CONFIRMADO · B-16 |
| Ferramentas de manutenção em destaque permanente em 3 telas | `Turmas.tsx:775-788`, `Alunos.tsx:194-196`, `Usuarios.tsx:799-808` | RISCO POTENCIAL · B-15 |
| **Acerto a registrar:** o Painel Público nasce protegido, com confirmação explícita no cliente **e** no servidor | `PainelPublicoConfig.tsx:206-235`; `confirmar_exposicao` obrigatório | BOM |
| **Acerto a registrar:** `components/ui.tsx:127-133` dá `role="alert"` a erro e `role="status"` a sucesso | — | BOM |

---

## 8. COISAS QUE O SOFTWARE DEVERIA FAZER PELO USUÁRIO

### 8.1 Onde exige 5 cliques e podia exigir 2

1. **Emitir certificado de quem acabou de ser premiado.** Hoje: ver o pódio → ir a Relatórios → achar o nome num dropdown de 100 → escolher o modelo → baixar. Deveria ser: botão no próprio card do pódio (`Premiacoes.tsx:43-55`). O certificado **já se preenche sozinho**. *(M-34)*
2. **Certificados de uma turma inteira.** Hoje é 30 vezes o fluxo acima — e **impossível** para o aluno de nº 101. Deveria ser "Emitir para a 4º A" → um único arquivo. *(A-11, M-24)*
3. **Desarquivar um aluno.** Hoje: lembrar a turma → `/turmas` → abrir → marcar "Mostrar arquivados" → achar → menu → Reativar. Deveria ser um filtro na própria tela de Alunos — o parâmetro `incluir_inativos` **já existe** no backend. *(A-12)*
4. **Aceitar as sugestões da importação.** Hoje: um `<select>` por aluno, mais um segundo de turma para cada aluno novo. Deveria ser "Aceitar as 182 sugestões automáticas" em 1 clique, revisando só os 6 duvidosos. O motor já classifica confiança. *(A-21)*
5. **Exportar o que está na tela.** Ranking, Alunos e Detalhe da Turma não exportam; é preciso ir a Relatórios e reencontrar o mesmo recorte com outros filtros. Deveria haver "Exportar esta visão" em cada tabela.
6. **Trocar a própria senha.** Hoje: contatar o gestor → gestor gera link → gestor transmite → usuário abre. Deveria ser "Esqueci minha senha" no login. *(A-20)*

### 8.2 Preenchimento manual que podia ser automático

7. **Série da turma** — digitada à mão em todo cadastro individual, embora o próprio arquivo já derive `ano_escolar` do nome na criação em massa. *(B-14)*
8. **Turma dos alunos novos na importação** — o arquivo traz `turma_relatorio` linha a linha e o código já resolve, mas ainda apresenta o dropdown para o humano confirmar um por um.
9. **Senha inicial de usuário novo** — o gestor inventa e digita, sendo que o mesmo arquivo já sabe gerar link de uso único. Criar conta deveria emitir o link. *(B-24)*
10. **Reenvio do arquivo na Lista Piloto** — upload e parse acontecem duas vezes; o `arquivo_token` já existe no fluxo irmão. *(A-21)*

### 8.3 Análise humana que podia ser detecção automática

11. **Duplicatas** — hoje são três botões que alguém precisa suspeitar e clicar (alunos, turmas, professores). Depois de cada importação o sistema **sabe** que criou candidatos duvidosos e deveria avisar: "esta importação gerou 3 possíveis duplicatas — revisar".
12. **Dado envelhecendo** — `RedeDashboard` já calcula `escolas_desatualizadas` e a tela de Sincronização já mostra "Desatualizadas"; no Dashboard da escola não há nada. O coordenador olha números de três semanas atrás sem saber.
13. **Turmas sem professor** — a coluna mostra "—" e mais nada; deveria virar alerta agregado ("3 turmas sem professor responsável").
14. **Tendência** — nenhuma tela mostra variação, embora `ranking-evolucao` já calcule ganhos por janela. O gestor faz essa conta comparando prints. *(A-17)*
15. **Efeito de mudar os pesos** — alterar Métricas recalcula a escola inteira sem prévia, embora o Simulador já faça essa conta em outra tela. Deveria mostrar "com estes pesos, 12 alunos mudam de posição" antes de salvar. *(M-35)*
16. **Quem não está usando** — o painel da rede ranqueia quem usa; a escola que não gerou nenhum dado simplesmente **não aparece**. A não-adoção é o problema mais caro da secretaria e é 100% detectável (`total_alunos > 0 && atividades == 0`).

### 8.4 O que o sistema já sabe e não conta a ninguém

17. **Que a integração parou** — `verificar_obsolescencia` já roda no scheduler e o alerta é gravado no banco, mas só a tela o consome. *(A-15)*
18. **Que uma criança está há 30 dias sem atividade** — o alerta existe por aluno para a escola, e some completamente para a rede. *(A-19)*
19. **Que a criança lê há três meses no mesmo nível** — `livros_por_nivel` e `_delta_niveis` existem e **não viram alerta nenhum**. É o dado pedagógico mais valioso do sistema.
20. **Que a professora não está vendo aluno nenhum** — `turmas_permitidas` devolve `[]` e a tela fica vazia, em silêncio, com HTTP 200. *(A-03)*

---

## 9. MATRIZ DE PRIORIZAÇÃO

*(ordenada por impacto real numa rede municipal com crianças reais — não por elegância técnica)*

| Prioridade | Melhoria | Problema resolvido | Impacto | Esforço | Risco atual | Área |
|---|---|---|---|---|---|---|
| **P1** | Renormalizar a nota sobre as plataformas com dado | C-01 | Muito alto | M | Criança leitora perde prêmio para quem fez menos, **hoje** | Dados / Pedagógico |
| **P1** | Negar `rede_id` em `_usuario_alvo` | C-03 / V1 | Muito alto | P | Gestor de escola lê a rede inteira | Segurança |
| **P1** | `negar_secretaria` no `admin.router` | C-04 / V2 | Muito alto | P | PII de menor sai da escola | Segurança / LGPD |
| **P1** | Desabilitar restauração de backup na interface | C-06 / V6 | Muito alto | P | Destruição irreversível + reabertura do P0 | Dados |
| **P1** | Redigir logs por chave semântica + remover filtro `entidade_id` | C-07 / V5 | Muito alto | M | Direito ao esquecimento não cumprido | LGPD |
| **P1** | `ADMIN_GLOBAL_EMAIL` por variável de ambiente | C-05 / V3 | Alto | P | Bomba-relógio no próximo município/staging/DR | Segurança |
| **P1** | Trocar `media_geral` pelo índice per capita (painel, atenção, metas, boletim, vitrine) | C-02 | Muito alto | M | Secretaria decide e publica com régua inválida | Analytics |
| **P1** | Inverter a ordem da lista de atenção | A-18 | Alto | P | A escola mais crítica é a última lida | Secretaria |
| **P1** | `WHERE data_referencia >=` em `_series_por_aluno` | A-07 | Alto | P | Rota pública em 5 s, piorando por ano | Performance |
| **P1** | Aviso + busca no dropdown de certificados | A-11 | Alto | P | Criança sem certificado em escola grande | UX |
| **P1** | Apagar `Nota` órfã + join em `Matricula` nas médias | A-01 | Alto | M | Dois "1º lugar"; painel com mais crianças que matrículas | Dados |
| **P1** | Unificar a definição de "Média geral" | A-02 | Alto | M | 38,6 × 77,3 para a mesma escola | Dados |
| **P1** | `pytest -m postgres` no CI | A-16 | Alto | P | Deadlock 4711×4713 passaria verde | Testes |
| **P1** | Aviso visível quando o professor não tem turma vinculada | A-03 | Alto | P | Perfil inteiro desligado em silêncio | RBAC / UX |
| **P2** | `Usuario.professor_id` (FK) + backfill | A-03 | Alto | M | Chave natural mutável decidindo autorização | Arquitetura |
| **P2** | Semáforo global para Chromium | A-10 | Alto | P | OOM em 768 MB no dia da premiação | Performance |
| **P2** | `logger.exception` nos 6 fallbacks | M-10 | Médio | P | Cartaz com "0 livros" sem ninguém saber | Observabilidade |
| **P2** | Ler `X-Request-ID` + telemetria de erro no front | A-14 | Alto | M | Tela branca que ninguém descobre | Observabilidade |
| **P2** | Notificação de escopo rede + alerta de silêncio de dados | A-15 | Alto | M | O sino da Secretaria nunca acende | Automação |
| **P2** | `response_model` em `routers/rede.py` | A-04 | Alto | M | PII protegida só por convenção | Segurança / Arquitetura |
| **P2** | `arquivo_token` + progresso na Lista Piloto | A-21 | Médio | M | Upload duplo em internet de escola pública | UX |
| **P2** | Filtro "Arquivados" na tela de Alunos | A-12 | Médio | P | Beco sem saída de 1 clique | UX |
| **P2** | `recalcular_rede` em fila com status | A-08 | Alto | M | Endpoint que não termina em rede grande | Escalabilidade |
| **P2** | `COUNT(DISTINCT)` + cache no `panorama-global` | A-09 | Médio | M | Tela do dono degrada com vendas | Escalabilidade |
| **P2** | Contagens de risco por escola, sem PII | A-19 | Muito alto | M | Secretaria não vê criança em risco nem em número | Secretaria |
| **P2** | Botão "Emitir certificado" no pódio | M-34 | Médio | P | Premiação termina fora do produto | UX |
| **P2** | Índice `(escola_id, aluno_id, data_referencia DESC, id DESC)` | M-12 | Médio | P | Sort por partição em toda leitura | Performance |
| **P2** | `IGNORADAS` no `restaurar` + `exigir_papeis` nas rotas de rede + `.gitignore` | M-01, B-01, B-02 | Médio | P | DoS multi-tenant; vitrine ligada por conta indevida | Segurança |
| **P2** | Resolver a divergência do claim atômico da fila | M-41 / D1 | Médio | P | Coleta possivelmente duplicada | Arquitetura |
| **P3** | Retrato mensal de KPIs por escola (dimensão temporal) | A-17 | Muito alto | M | "Quem está piorando?" sem resposta | Secretaria |
| **P3** | Extrair `services/identidade_aluno.py` + pipeline | A-06 | Alto | G | Motor crítico dentro de um router | Arquitetura |
| **P3** | `services/snapshots.py` com `ultimo_por_aluno()` | A-05 | Médio | M | 7 cópias de uma invariante, já divergindo | Arquitetura |
| **P3** | Metas com prazo, responsável e linha de base | M-26 | Alto | M | Meta não é instrumento de gestão | Secretaria |
| **P3** | `montar_contexto_rede` + assistente de rede | M-27 | Alto | M | Maior valor de IA não realizado | IA |
| **P3** | Alerta de nível de leitura estagnado | 5.5 #3 | Alto | M | O dado pedagógico mais valioso não vira alerta | Pedagógico |
| **P3** | Política de retenção + purga agendada | A-22 | Médio | M | Dado de criança sem prazo de descarte | LGPD |
| **P3** | Testes do ramo destrutivo da fusão + e2e dos 5 fluxos | A-23 | Médio | M | Parte irreversível sem rede de proteção | Testes |
| **P4** | Camada de recursos no `packages/core` (136 URLs) | M-14 | Baixo | G | Refactor de URL é varredura manual | Arquitetura |
| **P4** | Extrair navegação de `Layout.tsx` | M-15 | Baixo | M | Risco de merge concentrado | Arquitetura |
| **P4** | Entidade `AcaoRede` (plano de ação) | §6.2 #9 | Muito alto | G | O ciclo detectar→agir→medir não fecha | Produto |

---

## 10. ROADMAP

### AGORA (esta semana) — parar o dano

*Tudo aqui é ≤ 1 dia de trabalho por item, e cada um interrompe um dano que já está acontecendo ou que acontece no próximo evento.*

1. `_usuario_alvo` protege contas de rede (**C-03**) — uma condição.
2. `negar_secretaria` no `admin.router` (**C-04**) — uma linha.
3. Botão de restauração de backup desabilitado na interface (**C-06**) — uma linha.
4. `ADMIN_GLOBAL_EMAIL` por variável de ambiente, sem default (**C-05**).
5. `WHERE data_referencia >=` em `_series_por_aluno` (**A-07**).
6. Ordem da lista de atenção invertida (**A-18**).
7. `pytest -m postgres` no job que já tem Postgres (**A-16**).
8. Aviso "mostrando os primeiros 100 alunos" no certificado (**A-11**).
9. `IGNORADAS` no `restaurar` (**M-01**), `exigir_papeis` nas 3 rotas de rede (**B-01**), `backend/*.db` no `.gitignore` (**B-02**).
10. `logger.exception` nos 6 fallbacks silenciosos (**M-10**) e semáforo do Chromium (**A-10**).

**Critério de pronto:** os 7 críticos ou estão corrigidos, ou estão **bloqueados na interface** com aviso, e nenhum ambiente novo pode ser provisionado com o e-mail hardcoded.

### 30 DIAS — corrigir a conta e fechar o buraco de LGPD

1. **Renormalizar a nota** por dimensões disponíveis (**C-01**) + recálculo controlado de toda a base do piloto, com comparação antes/depois publicada internamente.
2. **Promover o índice per capita** a métrica oficial no painel, atenção, metas, boletim e vitrine pública (**C-02**); ajustar o default da correlação SAEB.
3. **Redação semântica dos logs** + reescrita do teste tautológico (**C-07**).
4. **Restauração de backup corrigida** (falha de saída ou `MODELOS` completo) e reabilitada (**C-06**).
5. **Notas órfãs** apagadas no recálculo + join em `Matricula` (**A-01**); **definição única de média** (**A-02**); contagem de turmas padronizada (**B-25**).
6. `Usuario.professor_id` com backfill e aviso visível na tela (**A-03**).
7. `response_model` em `routers/rede.py` + teste de contrato anti-PII (**A-04**).
8. Ler `X-Request-ID` no cliente e exibi-lo na tela de erro (**A-14**).
9. Quick wins de UX: filtro "Arquivados" (**A-12**), botão de certificado no pódio (**M-34**), alertas abertos por padrão (**M-18**), `cacheMs` em insights (**M-17**), rename da sidebar da Secretaria (**M-16**).

**Critério de pronto:** nenhuma criança é ordenada por adesão; a Secretaria decide pelo índice comparável; um pedido de exclusão apaga o nome de verdade.

### 30–90 DIAS — parar de quebrar com escala e começar a avisar

1. **Trabalho pesado fora do request:** fila para `recalcular_rede` (**A-08**), semáforo/fila para PDF, worker de sync separado (**M-13**), resolução da divergência do claim atômico (**M-41**).
2. **Consultas que não materializam a rede:** `COUNT(DISTINCT)` + cache no `panorama-global` (**A-09**), índice de ordenação (**M-12**), `services/snapshots.py` (**A-05**).
3. **Contagens de risco por escola, sem PII** (**A-19**) e **retrato mensal de KPIs** (**A-17**) — as duas peças que destravam quase todo o resto da visão de Secretaria.
4. **Notificação que sai do banco:** escopo rede, alerta de silêncio de dados, digest semanal (**A-15**).
5. **Telemetria de erro no frontend** (**A-14**) e guard de ambiente em `automacao` (**M-08**), `--cov-fail-under` (**M-07**).
6. **Extrair `services/identidade_aluno.py`** e o pipeline compartilhado com o orchestrator (**A-06**), com teste de contrato de aridade.
7. **Retenção e portabilidade:** política por classe de dado, purga agendada, relatório de titular (**A-22**, **M-37**).
8. Testes do ramo destrutivo da fusão e e2e dos 5 fluxos que movem dado de criança (**A-23**).

**Critério de pronto:** nenhum endpoint que possa não terminar; o sistema procura o usuário quando algo quebra ou envelhece.

### 3–6 MESES — virar instrumento de gestão

1. **Ciclo detectar→investigar→agir→responsável→prazo→medir** com a entidade `AcaoRede`, reusando `LogAuditoria`, `Notificacao` e o padrão de `MetaRede`.
2. **Metas com prazo, responsável, linha de base e desdobramento por escola** (**M-26**).
3. **Assistente de rede** sobre contexto agregado (**M-27**) + narrativa automática sobre número já calculado (a IA redige, o motor calcula).
4. **Inteligência pedagógica de segunda geração:** delta por turma, curva de concentração, **nível de leitura estagnado**, qualidade × volume, score de risco composto e persistência do risco.
5. **Certificados e boletins em lote e agendados**; detecção de duplicatas automática após cada importação.
6. **Contrato de API tipado** nas rotas restantes e camada de recursos no `packages/core` (**M-14**, **M-11**).
7. **Comparação justa entre escolas com contexto socioeconômico** — `Escola` já tem `codigo_inep` e há `services/casamento_inep.py`; importar INSE permitiria "grupos comparáveis", o padrão que uma SEDUC reconhece.

### VISÃO FUTURA

- **O produto que abre sozinho toda manhã:** a tela inicial do Secretário mostra o **delta desde a última visita** ("3 escolas entraram em atenção, 2 saíram; a meta de leitura está 9% atrás do ritmo; 4 escolas não importam dados há 21 dias") — não o mesmo retrato de ontem.
- **O diretor vê posição e movimento:** "sua escola é a 14ª de 42 em leitura per capita, subiu 3 posições; o 3ºB é a turma que puxa para baixo". A comparação já existe, mas mora só na Secretaria.
- **O coordenador abre nos 8 alunos que precisam dele hoje**, com o botão de registrar o que foi feito — e o sistema mede se funcionou.
- **Multi-município de verdade:** nenhum dado de tenant no código, trabalho pesado em workers, caches compartilhados, e o painel do dono servindo 100 redes sem degradar.
- **Constela Quest integrado ao ciclo pedagógico**, com o código de login endurecido e o progresso da criança protegido contra fusão e restauração.

---

## 11. NOTAS POR CATEGORIA (0 a 10)

| # | Categoria | Nota | Justificativa ancorada em achado |
|---|---|---|---|
| 1 | **Arquitetura** | **7,0** | Camadas nominais boas e `core/deps.py` exemplar, mas o motor de identidade de aluno mora num router (A-06), a sync chama um route handler do FastAPI direto e a invariante de "estado atual" está escrita 7 vezes, já divergindo (A-05). |
| 2 | **Qualidade do código** | **8,0** | Razão teste:código 0,81:1, 90% de cobertura, `except` tipados com `# noqa: BLE001` justificado e comentários que registram o bug que motivou a linha; descontam os 6 fallbacks sem log (M-10) e 80 endpoints sem contrato (A-04). |
| 3 | **Segurança** | **5,0** | Modelo de permissões deliberado e 45 rotas varridas sem vazamento — mas três achados de severidade alta com PoC executado: escalada admin→Secretaria (V1), backup com PII (V2) e e-mail hardcoded (V3). |
| 4 | **Performance** | **5,5** | O caminho de **escrita** escala (window function no banco, advisory locks) e o de **leitura** não: `_series_por_aluno` sem janela leva a rota pública a 5 s (A-07), ranking materializa 25 mil linhas em Python e Chromium abre dentro do request (A-10). |
| 5 | **Escalabilidade** | **4,5** | `panorama-global` é O(redes × escolas) sem cache (A-09), `recalcular_rede` levaria de 8 a 25 minutos dentro de um PUT (A-08), e rate limit, caches e scheduler são por processo com 2 workers. |
| 6 | **UX** | **6,5** | Detalhes raros e certos (erro que muda com o cargo, prévia obrigatória na importação, URL como fonte da verdade) convivem com um beco sem saída no arquivamento (A-12), certificado inacessível acima de 100 alunos (A-11) e ausência de "Esqueci minha senha" (A-20). |
| 7 | **Qualidade dos dados** | **4,0** | Três defeitos que produzem número errado no banco: nota com teto de 50 (C-01), `Nota` órfã com posições duplicadas (A-01) e três definições divergentes de "Média geral" — 38,6 × 77,3 medidos na mesma escola (A-02). |
| 8 | **Analytics** | **5,0** | O índice per capita 0–1000 existe e está **correto**, mas o painel, o alerta de atenção, as metas, o boletim e a vitrine pública continuam na média não comparável (C-02); e não existe nenhuma série temporal acima do aluno (A-17). |
| 9 | **Inteligência pedagógica** | **7,0** | Percentil em vez de máximo, mediana em vez de média, persistência auto-referenciada e saturação de volume são estatística correta e justificada no código; falta narrativa, agregação por turma e o uso de `livros_por_nivel`, que hoje não vira alerta nenhum. |
| 10 | **Utilidade para escolas** | **7,5** | O Dashboard é centro de comando real, com alertas clicáveis e drill-down escola→turma→aluno; falta tendência, frescor do dado e emissão em lote — e o coordenador abre a tela pedagógica vendo os melhores, com os alertas colapsados (M-18). |
| 11 | **Utilidade para Secretaria** | **5,0** | Blindagem de PII e comparação per capita são diferenciais reais, mas a lista de ação está ordenada ao contrário (A-18), o sino nunca acende (A-15) e "quais escolas estão piorando?" não tem resposta no produto (A-17). |
| 12 | **Automação** | **5,5** | A fila de sync tem backoff, recuperação de órfãs e alerta sem spam — e vem **desligada por padrão**; `verificar_obsolescencia` já detecta escola parada e não avisa ninguém; a purga de retenção roda só no boot (A-22). |
| 13 | **IA** | **5,5** | Pseudonimização real com a limitação documentada e a fronteira "IA não calcula número" são acertos de maturidade; descontam o provedor padrão que não é IA (M-40), o teto de 1024 tokens (M-38) e a Secretaria sem acesso por falta de contexto agregado (M-27). |
| 14 | **Diferencial competitivo** | **8,0** | PII bloqueada por construção, transparência auditável do cálculo, per capita com o mesmo motor e correlação SAEB com ressalva explícita de não-causalidade — o conjunto que ganha o jurídico e a área técnica de uma prefeitura. |
| 15 | **Produto como um todo** | **6,5** | Base madura, honesta e auditável, com piloto real rodando — travada por um punhado de defeitos de dado e de segurança que são corrigíveis em semanas, e por lacunas de gestão (tendência, ação, aviso) que são o próximo salto de valor. |

**Média simples das 15 categorias: 6,2.**

---

## 12. VINTE PERGUNTAS INCÔMODAS

*(específicas deste software; o time deveria saber responder e provavelmente não sabe)*

1. **Quantas crianças do piloto estão hoje no Ranking Geral com nota travada em 50 por não terem dado do Matific — e quantas delas já perderam premiação ou certificado para alguém que produziu menos?** (`scoring.py:811`)
2. **Se a Secretaria abrir o Painel da Rede agora, qual escola aparece como "melhor" — e qual seria a melhor pelo índice per capita 0–1000 que já existe no mesmo arquivo?** Alguém já rodou as duas listas lado a lado? (`rede.py:389` × `:320`)
3. **Qual é a "Média geral" verdadeira da Escola X: os 38,6 do Dashboard do coordenador ou os 77,3 do painel da Secretaria?** Qual dos dois números foi para a última reunião? (`rankings.py:379` × `rede.py:102`)
4. **Quem hoje tem conta de admin de escola no piloto e, portanto, pode trocar a senha da conta da Secretaria com um único PATCH?** (`admin.py:291`)
5. **O e-mail `edumedeiros1405@gmail.com` já existe no banco de produção, no staging, no ambiente de homologação e em cada backup já restaurado — ou em algum deles ele ainda está livre?** (`database.py:156`)
6. **Alguém já clicou em "Restaurar backup" em produção?** Se sim, quantas linhas de `identidades_externas` e de `quest_perfis` existiam antes e existem depois? (`backup.py:131`)
7. **Se uma mãe pedir hoje a exclusão dos dados da filha, quem executa, em quanto tempo, e como se prova que o nome saiu de `logs_auditoria` — sabendo que 4 de 5 formatos escapam do anonimizador?** (`academico.py:493`)
8. **Quantas linhas tem `logs_auditoria` hoje e qual é a taxa de crescimento mensal?** Existe algum plano para quando ela dominar o banco? (`models/nota.py:47`)
9. **`SENTRY_DSN` está mesmo definido no Railway?** Quando foi a última vez que alguém abriu o Sentry — e o release lá diz "1.0.0" para todos os deploys? (`config.py:180, 186`)
10. **Se a tela da professora der branco amanhã às 10h, qual é o procedimento?** Onde ela clica, o que a coordenação vê, e como alguém encontra a linha de log correspondente sem o `X-Request-ID` no cliente? (`LimiteErro.tsx:26`)
11. **Qual escola do piloto tem mais de 100 alunos ativos — e as crianças a partir do 101º em ordem alfabética já receberam certificado alguma vez?** (`Relatorios.tsx:33` + `academico.py:81`)
12. **Quantos professores estão hoje com `Professor.email` diferente do `Usuario.email` e, por isso, abrem o sistema e não veem aluno nenhum, sem nenhuma mensagem de erro?** (`permissoes.py:51`)
13. **O que acontece com o robô de sincronização no dia em que alguém acrescentar um parâmetro `Depends()` em `importacoes.confirmar`?** Existe algum teste que trave essa aridade? (`orchestrator.py:158`)
14. **Quantos snapshots existem hoje na maior escola do piloto, e quanto tempo o mural público leva para responder nela — sabendo que a consulta não tem recorte de data e que a rota não tem login nem limite?** (`evolucao.py:44`, `publico.py:296`)
15. **Quem no município olha o painel público, em que dispositivo, e a que taxa essa tela faz polling contra uma rota sem rate limit e com cache de 60 s por worker?** (`publico.py:362`)
16. **Se a Secretaria contratar ou descontratar um módulo numa rede de 60 escolas, quanto tempo o PUT leva antes de o proxy cortar — e o que acontece com as escolas que já foram recalculadas quando ele cortar?** (`modulos.py:243`)
17. **Quantos alunos duplicados existiriam hoje se uma restauração de backup tivesse apagado `identidades_externas` na semana passada — e como o time descobriria que foi isso?** (`backup.py:41` + P0 `7f6fe4e`)
18. **O código de login do Quest já foi distribuído a alguma criança? Em quantas contas?** Alguém monitora a taxa de falhas em `POST /quest/auth/quem`, sabendo que 218 contas por dia são colhíveis de um único IP? (`credenciais.py:34`)
19. **Quando um refactor inverter a ordem de aquisição das travas 4711 e 4713, quem descobre — dado que o teste que guarda essa hierarquia se auto-pula no CI?** (`ci.yml:61`, `test_recalculo_concorrencia_pg.py:351`)
20. **Quanto custa hoje uma pergunta ao Assistente numa escola de 600 alunos, quantos tokens de contexto ela carrega, e qual fração das requisições é escrita de cache em vez de leitura — dado que o breakpoint está na pergunta do usuário?** (`assistente.py:159`, `provedores.py:38`)

---

## Anexo — Rastreabilidade das frentes

| Frente | Método | Provas executadas |
|---|---|---|
| Arquitetura e qualidade de código | Leitura direta (123 arquivos `.py` / ~26,5k linhas em `backend/app`; 108 arquivos em `apps/web/src`) | Contagens de endpoints, `response_model`, ocorrências de URL e implementações duplicadas |
| Segurança, autenticação e permissões | Leitura + **4 PoCs executados** contra a app real (SQLite em memória) | `poc.py`, `poc_global.py`, `poc_backup.py`, `pii_secretaria.py`, `pii_sec_admin.py`, `rotas.py` (scratchpad, reexecutáveis) |
| Banco, dados, performance e escalabilidade | Leitura + **execução do motor** contra bancos sintéticos e benchmarks | Simulações de nota, normalização, notas órfãs; benchmarks de 144k e 288k snapshots |
| Observabilidade, confiabilidade, testes e LGPD | Leitura + **2 provas empíricas** com as funções reais | `prova_lgpd.py`, `prova_restore.py` (scratchpad) |
| UX e telas | Leitura de 51 páginas + `Layout.tsx` + rotas | — (interface em execução não avaliada) |
| Secretaria, pedagógico, IA e automação | Leitura na perspectiva de um município de 100 escolas | Rastreamento de consumidores de métrica e greps de ausência (`plano_acao`, `escopo="rede"`) |

**Nada foi alterado no produto.** Os arquivos de prova vivem fora do repositório, no diretório de trabalho temporário da sessão, e são descartáveis.
