# Histórico dos rankings — o que se perde a cada recálculo e como reconstruir

Investigação de 20/10/2026 (rodada de correção da auditoria), feita sobre o código da
base `5527983`. Só leitura de código e testes locais; nenhuma migração criada, nenhum
dado de produção lido além dos fatos agregados já registrados na auditoria.

## Resumo

| | O que acontece | Consequência |
|---|---|---|
| **Notas** | Cada recálculo regrava a MESMA linha `notas` (uma por aluno e ano letivo) — nota, posição, detalhes e `calculada_em`. Nada é versionado. | Um ranking divulgado (cartaz, certificado, pódio, telão) **não pode ser reconstruído pelo banco** depois do recálculo seguinte. |
| **Retratos** | `snapshots_*` não têm unicidade no banco. Reimportar no MESMO dia **atualiza no lugar** o retrato do dia (troca até o `importacao_id`). | Os valores anteriores do dia somem; a "fotografia imutável" do modelo não é imutável no mesmo dia. |
| **O que já permite reconstruir** | Retratos dos outros dias, leituras datadas com nível congelado, eventos do Elefante, importações, auditoria de configuração, backup diário privado (14 dias). | Reconstrução **exata** só dentro dos 14 dias do backup; fora disso, **aproximada**. |

## 1. Notas sobrescritas a cada recálculo

### Causa

`services/scoring.py::recalcular_escola` (linhas ~1640–1675 na base):

* carrega as notas do ano (`notas_existentes`) e, para cada aluno do conjunto pontuado,
  **reaproveita a linha** (`uq_nota_aluno_ano` = uma por aluno × ano letivo) e regrava
  `nota_*`, `nota_*_institucional`, `posicao`, `posicao_leitura`, `posicao_matematica`,
  `aferido_*`, `detalhes` e `calculada_em = instante`;
* não existe tabela de histórico nem cópia da linha anterior. O conteúdo é determinístico
  (recalcular duas vezes com os mesmos insumos dá o mesmo número), mas qualquer insumo
  novo — uma coleta, um aluno arquivado, uma mudança de peso — muda a nota e a posição de
  muita gente, e o valor antigo se perde.

O recálculo é disparado com frequência: toda importação e sincronização
(`routers/importacoes.py`, `routers/plataformas.py`), mudança de configuração
(`routers/configuracoes.py`, 10 chamadas), operações de cadastro e identidade
(`routers/academico.py`, 8 chamadas: arquivar, fundir, mover de turma…), módulos da rede,
`POST /recalcular` e os scripts de recálculo em lote.

A linha de quem SAI do conjunto pontuado (arquivado, transferido, fora da Lista Piloto,
criança de Fase) **não é apagada nem atualizada**: fica com a posição congelada do último
cálculo em que entrou. Em produção (20/10/2026) são 7 alunos não ativos com
`notas.posicao` preenchida no ano ativo. Os rankings filtram na leitura (travado em
`tests/test_ranking_status_ativo.py`), mas a posição congelada ainda aparece no perfil do
aluno e no comparador (ver § 4).

### Impacto

* **Certificado de mérito**: imprime a posição e a nota do momento da emissão
  (`routers/relatorios.py::certificado` → `posicao=nota.posicao`). O PDF não é guardado e
  a auditoria (`certificado.emitido`) registra só o modelo — **não** a posição nem a nota.
  Não há como conferir, depois, se "3º lugar" era verdade no dia da emissão.
* **Cartaz / exportação do ranking / telão / pódios de premiação**: são gerados na hora a
  partir das notas vigentes; nada fica registrado do que foi exibido.
* **Auditoria do recálculo**: `notas.recalculadas` guarda só a contagem de alunos.
* **Explicação da nota** (`Nota.detalhes`): é sempre a do ÚLTIMO cálculo.

## 2. Retratos sem unicidade e sobrescritos no mesmo dia

### Causa

* `SnapshotMatific` / `SnapshotElefante` (`models/plataformas.py`) não têm restrição de
  unicidade; o "retrato atual" é escolhido na leitura por `(data_referencia, id)`
  (`scoring.ids_snapshots_atuais`).
* A idempotência da reimportação é **só de aplicação**, e por **atualização no lugar**:
  `routers/importacoes.py::_importar_matific` (~linha 1236),
  `_importar_elefante_resumo` (~1399) e `_importar_matific_periodo` (o ponto do mesmo
  fim de período) testam `_mesmo_dia(anterior.data_referencia, data_referencia)` e, se o
  retrato ATUAL do aluno é do mesmo dia, **sobrescrevem** atividades/estrelas/média (ou
  livros/tempo/questões/níveis) **e o `importacao_id`**. O docstring do modelo diz
  "Nunca é sobrescrita (PRD §68)"; no mesmo dia, é.
* O teste só compara com o retrato ATUAL: um retrato do mesmo dia que não seja o atual
  (backfill fora de ordem) não é detectado, e duas importações concorrentes podem
  empilhar dois retratos com a mesma data. O caminho do relatório individual do Elefante
  (`_importar_elefante_leituras`, ~linha 1915) sempre empilha um retrato novo, sem o
  teste do mesmo dia.
* O retrato não tem `criado_em`: quando ele entrou no banco só se sabe pela
  `Importacao.created_at` — e a atualização no lugar troca o `importacao_id`, apagando
  também esse rastro.

### Impacto

* Os valores anteriores do dia se perdem (uma coleta parcial de manhã corrigida à tarde
  não deixa vestígio).
* Não dá para afirmar "com que dados o ranking das 10h foi calculado".
* Sem unicidade no banco, a regra "um retrato por aluno por dia" depende de todo
  caminho de escrita lembrar dela.

## 3. O que já existe e permite reconstruir

| Fonte | O que guarda | Limite |
|---|---|---|
| `snapshots_matific` / `snapshots_elefante` | Um ponto por aluno por dia de coleta, com `data_referencia` e `importacao_id`. | Mesmo dia sobrescrito; sem `criado_em`. |
| `leituras` | Cada livro com a data real e o **nível congelado** (`nivel_codigo`, `catalogo_versao`) — renivelar o catálogo não muda o passado. | Uma linha por (aluno, livro): releitura não pontua; fusão de alunos pode perder a data (ver memória "fusão perde a data"). |
| `eventos_aluno` | Espelho evento a evento do relatório individual do Elefante (inclui releituras), idempotente por `chave_natural`. | Só Elefante individual; o Matific não tem evento datado. |
| `importacoes`, `sincronizacao_execucoes` | Quando cada importação/coleta ocorreu (`created_at`, `finalizada_em`). | Em produção, `importacao_id` das execuções está vazio (0 de 409). |
| `logs_auditoria` | `pesos.alterados`, `referencias.alteradas`, `dificuldade.alterada`, `elefante_extra.alterado`, `certificado.emitido`, `notas.recalculadas`, mudanças de cadastro. | Sem posição/nota nos eventos de emissão e de recálculo. |
| `notas.detalhes` | Referências (P90/k), pesos, versão da régua, `snapshot_em` de cada dimensão — do ÚLTIMO cálculo. | Sobrescrito. |
| Backup diário PRIVADO | O banco inteiro, com ensaio de restauração a cada execução. | Retenção de **14 dias** (decisão do dono de 13/10). |
| Git (commit publicado) | O código do motor e da elegibilidade vigentes em cada data. | Precisa do registro de qual commit estava no ar. |

### Procedimento de reconstrução (com o que existe hoje)

1. **Data D nos últimos 14 dias**: restaurar o backup do dia D num banco descartável
   (`docs/DR-RUNBOOK.md`, `docs/GUIA-TESTE-RESTAURACAO.md`) e ler `notas` daquela
   escola/ano. É a única reconstrução **exata** — ela reflete o último recálculo antes do
   horário do backup, não necessariamente o instante da divulgação.
2. **Data D anterior**: reconstrução **aproximada**, rodando o motor do commit vigente em
   D sobre os insumos "como eram em D": retratos com `data_referencia ≤ D` cuja
   `Importacao.created_at ≤ D` (os do mesmo dia podem ter sido sobrescritos depois),
   leituras com `data ≤ D`, configuração reconstituída pela auditoria. Matrícula e status
   de aluno NÃO são versionados (só o que a auditoria registrou), e o retrato substituído
   no mesmo dia não volta. O resultado deve ser apresentado como aproximação.

## 4. Proposta (sem migração nesta rodada)

Em ordem de custo. As P2–P4 exigem migração Alembic — ficam para uma rodada autorizada.

* **P1 — Registro do que foi DIVULGADO, já sem migração** (`logs_auditoria.detalhes` é
  JSON): ao emitir certificado, gravar `posicao`, `posicao_*` da dimensão, a nota
  impressa, `calculada_em` da Nota e o SHA-256 do PDF; ao gerar cartaz/exportação do
  ranking, gravar dimensão, `calculada_em` e o SHA-256 + a lista `(aluno_id, posição,
  nota)` (sem nome). Arquivos: `routers/relatorios.py` (fora da posse desta frente).
* **P2 — Ranking publicado imutável** (tabela nova, migração): `publicacoes_ranking`
  (escola, ano, tipo — cartaz/certificado/premiação/telão —, dimensão, período, versão da
  régua, commit, `calculada_em`, hash) + itens `(aluno_id, posição, nota)`. Sem nome de
  criança: o nome sai do cadastro enquanto ele existir.
* **P3 — Histórico de notas append-only** (migração): `notas_historico` recebendo, a cada
  recálculo, só as linhas que MUDARAM (nota/posição/aferido + `calculada_em` + versão).
  Estimativa: ~5.000 alunos, ~30% de mudança por recálculo diário ≈ 1.500 linhas/dia ≈
  0,5 milhão/ano — trivial. Permite "o ranking como estava em D" por consulta.
* **P4 — Retratos append-only de verdade** (migração): parar de atualizar no lugar —
  inserir o retrato novo e marcar o anterior (`substituido_em`, `substituido_por`), com
  `criado_em` e um índice ÚNICO parcial `(escola_id, aluno_id, dia) WHERE vigente`. O
  "atual" continua único por dia e o substituído fica rastreável. Versão leve, sem
  migração: antes de sobrescrever, registrar os valores antigos e o `importacao_id`
  antigo na auditoria (`snapshot.substituido`). Arquivos: `routers/importacoes.py`
  (frente de sincronização/importação).
* **P5 — Posição congelada de quem saiu**: hoje os rankings filtram na leitura; o perfil
  do aluno (`routers/academico.py::perfil_aluno`) e o comparador
  (`services/evolucao.py::_lado_aluno`) ainda mostram a posição congelada de transferido,
  fora da Lista Piloto, arquivado e criança de Fase. Proposta: não exibir posição para
  quem não concorre (na leitura, sem apagar o dado).

### Privacidade e retenção

P1–P3 guardam `aluno_id` + posição + nota (dado pessoal de criança, finalidade de
auditoria de premiação). Precisa de prazo de retenção definido pelo dono/jurídico —
sugestão técnica: ano letivo corrente + 1 ano, depois agregar (sem `aluno_id`) ou apagar.
O hash do documento permite provar o que foi emitido sem guardar o PDF.

## 5. Perguntas para o dono

1. Quais superfícies contam como "ranking divulgado" e precisam ser reconstruíveis:
   certificado, cartaz, pódio de premiação, telão (que é ao vivo)?
2. Prazo de retenção do registro de publicação e do histórico de notas.
3. O certificado deve ser verificável depois (hash/QR que confira posição e data)?
4. Autoriza, numa próxima rodada, as migrações de P2–P4?
