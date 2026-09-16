# Dificuldade por livro do Elefante Letrado — `elefante_dificuldade_v2`

Versão **vigente** (2026-09-15) da régua de dificuldade por livro. É a mesma **regra global**
(rede inteira) da v1, com a mesma fórmula e os mesmos parâmetros congelados; a versão nova
existe para ficar **identificável** nas notas a mudança de **resolução do livro** (id oficial),
do **fallback de wordCount** e das **guardas numéricas**.

* Fonte única no código: [`backend/app/services/dificuldade_livro.py`](../backend/app/services/dificuldade_livro.py).
* Normalização (P90 + mínimo de 8 alunos, inalterada; só guardas): [`backend/app/services/scoring.py`](../backend/app/services/scoring.py).
* Calibração, dataset e modelos comparados: [`elefante-dificuldade-v1.md`](elefante-dificuldade-v1.md).

## 1. Fórmula (definida pelo dono)

```
pontos_base      = dificuldade oficial do nível
                   BaseDoNível A3 = exp(0,103 · posição)   AA=0 … Z=29, Z+=30, A+=4,5
fator_word_count = clamp(1 + 0,35 · ln(wordCount / medianaWordCountDoNível) / ln 3, 0,80, 1,35)
pontos_livro     = pontos_base × fator_word_count × FatorSérie
FatorSérie       = 1º 1,40 · 2º 1,30 · 3º 1,20 · 4º 1,10 · 5º 1,00 · desconhecida 1,00
```

Regras que acompanham a fórmula:

* a **hierarquia oficial** de dificuldade (A3) é a base; nível desconhecido vale **0**, nunca negativo;
* mediana **por nível** = as medianas **congeladas** da calibração de 752 livros (2026-09-14);
* **não** usa tempo real do aluno e **não** usa `pageCount`;
* mesmo livro + mesmo nível + mesmo catálogo = mesmo valor (determinístico);
* nada de NaN, infinito, divisão por zero ou valor negativo.

### Decisão registrada: "Fórmula B"

O texto do dono chama esta régua de **"Fórmula B"**, mas a fórmula escrita é exatamente a da
v1 (A3 × ajuste por `ln(wc/mediana)/ln 3` com clamp 0,80–1,35 × fator de série). **Foi
implementada exatamente a fórmula escrita.** Consequência: nenhuma leitura com metadados
válidos muda de valor entre v1 e v2 (há teste que compara `versao=v1` e `versao=v2` livro a
livro). Se "Fórmula B" pretendia outra conta, isso é uma **v3** explícita, não uma edição da v2.

## 2. Parâmetros (`PARAMS_V2`)

`PARAMS_V2` é uma cópia profunda de `PARAMS_V1` com `versao = "elefante_dificuldade_v2"` e a
lista `mudancas_desde_v1`. Números:

| parâmetro | valor |
|---|---|
| `alpha` | 0,35 |
| `razao_log` | 3 (3× a mediana ⇒ +α) |
| `piso` / `teto` | 0,80 / 1,35 |
| `posicoes_extra` | `Z+` = 30 · `A+` = 4,5 (provisório, 1 livro) |
| `posicoes_faixa` | `pre_leitor` 1,5 · `nivel_1` 5 · `nivel_2` 10 · `nivel_3` 17,5 · `nivel_4` 24,5 · `nivel_5` 28,5 |
| `medianas_wordcount` | as 32 medianas da calibração (AA 12 … Z 7.380, Z+ 23.549, A+ 965) |
| `fator_serie` | 1: 1,40 · 2: 1,30 · 3: 1,20 · 4: 1,10 · 5: 1,00; `fator_serie_padrao` 1,0 |

`calcular_dificuldade_livro(..., versao=...)` aceita `elefante_dificuldade_v1` e
`elefante_dificuldade_v2` (mesma conta) e **recusa** qualquer outra versão (`ValueError`).
`parametros_publicos()` devolve a cópia da v2 (é o que `GET …/configuracoes/dificuldade-livro` expõe).

## 3. Fallback auditável de wordCount

`resolver_word_count(nivel, word_count) → (wordCount | None, status)`:

| status | quando | wordCount devolvido | fator usado |
|---|---|---|---|
| `catalogo` | número finito > 0 e nível com mediana | o número | fórmula |
| `ausente` | `None` ou texto vazio (livro fora do catálogo) | `None` | **1,0** |
| `invalido` | não numérico, ≤ 0, NaN, ±infinito (inclui `bool`) | `None` | **1,0** |
| `sem_mediana` | número válido, mas o nível não tem mediana (faixa, código sujo) | o número | **1,0** |

Qualquer status diferente de `catalogo` vale o **livro típico do nível** (fator 1,0). A
explicação (`RegraGlobal.explicar` / `explicar_dificuldade`) expõe `word_count_status`,
`resolvido_por` (`elefante_id` | `titulo_nivel` | `None`) e `elefante_id`; um `word_count`
não finito aparece como `null` (a resposta é sempre JSON válido).

## 4. Identidade oficial do livro (`elefante_id`)

* `RegraGlobal` (alias histórico `RegraV1`): `valor_livro`, `explicar` e `metadados` aceitam o
  parâmetro **nomeado** `elefante_id`. Com id **presente no catálogo oficial**, o wordCount vem
  do livro por id (vence um título renomeado na escola); sem id — ou com id fora do catálogo —
  a busca é por título + nível, como na v1; sem nenhum dos dois, o típico do nível.
* O **nível que pontua** continua sendo o registrado na leitura (nível efetivo), nunca o do catálogo.
* `RegraEscolaLegada` (perfil `personalizado`) aceita e **ignora** `elefante_id` (régua por faixa).
* `LeituraItem` ganhou o 4º campo opcional `elefante_id` (usos com 2 ou 3 campos continuam
  válidos); `leituras_por_aluno` seleciona `Livro.elefante_id` (migração `0030`) e
  `pontos_por_chave` passa o id ao valorar cada item.

### 4.1 Nível congelado na leitura (o passado não é reescrito)

A migração `0031_leitura_nivel_congelado` acrescenta duas colunas em `leituras`:

| coluna | o que guarda |
|---|---|
| `nivel_codigo` | o nível **efetivo** do livro quando a leitura foi registrada — é o que **vale** para pontuar aquela leitura |
| `catalogo_versao` | a versão do catálogo que resolveu esse nível (auditoria: com que extrato o número nasceu) |

Quem pontua uma leitura usa o nível **congelado** e, quando ele é nulo (leitura
anterior a esta versão), cai no nível **atual** do livro — em SQL,
`func.coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)`. Consequências:

* corrigir o nível de um livro no catálogo **não** muda nenhum período já
  fechado, em nenhuma tela, nem a nota gravada: vale das **próximas** leituras em
  diante. Antes, todos os consumidores liam `livros.nivel_codigo` ao vivo — a tela
  mudava na hora e a nota gravada só no recálculo: dois números para o mesmo fato;
* as colunas nascem **nulas, sem backfill**: no deploy, nenhuma leitura muda de
  valor (o fallback devolve exatamente o número de antes);
* o preenchimento das linhas antigas é **opcional** e explícito, pelo script
  `python -m scripts.vincular_livros_catalogo --congelar-niveis` (dry-run por
  padrão; `--aplicar` grava). Ele escreve nas leituras sem nível congelado
  exatamente o nível **atual** do livro — o valor que elas já valem hoje —, então
  **nenhum número muda** e nenhuma nota é recalculada. É **idempotente** (o
  `UPDATE` repete `nivel_codigo IS NULL`, e o que já está congelado nunca é
  sobrescrito), registra **uma** auditoria agregada por escola
  (`leitura.nivel_congelado`, com a contagem por nível) e deixa nula a leitura
  cujo livro está sem nível (congelar vazio não guarda informação);
* o corte de "ainda não congelada" é **`IS NULL`**, não "sem texto" — exatamente
  o do `coalesce`, que em SQL só cai no nível do livro quando a coluna é **nula**.
  Nível congelado **vazio** é congelamento válido ("desconhecido", 0 ponto: a
  régua ignora item sem letra) e o backfill não o toca; regravá-lo com o nível do
  livro faria a leitura pular de 0 para o valor do nível — o backfill mudaria um
  número, que é o que ele promete nunca fazer. O caso existe: `aplicar_ao_historico`
  num livro legado sem nível grava `""` no congelado das leituras dele;
* `catalogo_versao` no backfill recebe a versão do catálogo **vigente no
  congelamento** — é ela que testemunha o valor congelado. Não é uma reconstrução
  do passado: o extrato que resolveu aquele nível na época não é recuperável, e
  inventá-lo falsearia a auditoria.

## 5. Guardas numéricas

**Régua (`dificuldade_livro`)**

* `math.isfinite` em todas as etapas; valor final sempre finito e ≥ 0 (`valor_livro`,
  `valor_tipico`, `pontos_por_chave`, `pontos_aluno`, também na régua legada).
* Contagem **negativa ou não finita** em `livros_por_nivel` vale **0**. Motivo: um snapshot
  manual não subtrai pontos, e a evolução só passa ganhos positivos (`evolucao._delta_niveis`
  descarta ganho ≤ 0) — nenhum consumidor dependia de contagem negativa. Uma leitura
  itemizada continua valendo o seu valor mesmo que a contagem do snapshot seja negativa.
* WordCount subnormal (razão que estoura para 0) usa `ln(wc) − ln(mediana)`: mesmo número,
  sem erro de domínio. Catálogo com `wordCount` sujo carrega com 0 (→ `invalido`).

**Normalização (`scoring`)** — P90 + mínimo de 8 alunos por dimensão **inalterados**

* `normalizar` e `normalizar_saturado` devolvem 0 para valor ou referência não finitos, valor
  ≤ 0 ou referência ≤ 0; resultado sempre em [0, 100]. `k` não finito ou ≤ 0 cai no linear.
  Em magnitudes astronômicas (soma que estoura) a curva saturada é recalculada com os termos
  reescalados; valores normais dão exatamente o mesmo número de antes (teste bit a bit).
* `_percentil` ignora não finitos.
* `referencias_robustas` e `_referencias_auto`: ativos = só finitos > 0; no fallback do
  máximo, só finitos ≥ 0 (padrão 0). O tamanho da amostra que liga o modo robusto não muda.
* `calcular_matific` / `calcular_elefante` convertem as entradas para números finitos ≥ 0
  (preservando o tipo quando válido), leem `refs.get(chave, 0.0)` (referência inexistente = 0,
  nunca `KeyError`) e a nota final é finita em [0, 100]. Coorte vazia → nota 0, nunca erro.
* `nota_geral` passa pela MESMA guarda (`_nota_0_100`): nota finita em [0, 100] mesmo com um
  peso negativo gravado por engano em `pesos.geral` (valores válidos não mudam).
* Inteiro **fora do alcance do float** (`10**400`, que o JSON aceita) não levanta
  `OverflowError`: a contagem de `livros_por_nivel` satura em `dificuldade_livro.TETO_CONTAGEM`
  (mais livros nunca vale MENOS, e a multiplicação pelo típico nunca vira infinito) e
  `scoring._entrada_nao_negativa` trata o valor como entrada suja (0). O mesmo vale para o
  `wordCount`: um inteiro gigante satura no maior float finito e recebe a MESMA leitura que
  `1e308` (status `catalogo`, ajuste no teto 1,35), em vez de cair em `invalido` — não há
  degrau entre `1e308` e `10**400`.

## 6. Série

`serie_numero` compara sem acento e sem caixa. Além do que a v1 reconhecia ("1º Ano",
"4º ANO B", "3ª série", "2° ano", "5º", "5", "5B", "Ano 3"), reconhece:
"Primeiro/Segundo/Terceiro/Quarto/Quinto Ano" e "Primeira…Quinta Série", "3.º ano",
"EF1 - 3º", "3º B". Continua **sem** série: "Turma 12345", "Turma 3", "EJA 2", "EF1",
"Segundo Semestre" (a série tem de estar marcada: ordinal, "ano"/"série" ou o rótulo inteiro).

O ordinal **solto no meio** do rótulo (o caso "EF1 - 3º") é o **último recurso**: `serie_numero`
faz duas passadas e só o aceita quando **nenhum** padrão marcado ("5º Ano", "Ano 5", rótulo
inteiro, por extenso) casa no rótulo. Por isso rótulos compostos continuam valendo a série
marcada, como na v1 — "Multisseriada 1º ao 5º Ano" e "EF - 1º ao 5º ano" = 5, "Turma 1º A - 4º
Ano" e "Integral 2º - 4º Ano" = 4, "Multi 1º/2º ano" = 2.

O ordinal solto também **não** vale quando vem seguido de
etapa/segmento/semestre/bimestre/trimestre/período/módulo/fase/ciclo ("EJA 1ª Etapa",
"Turma A - 3º Período"), em rótulo que contém "EJA" ("EJA 3º") — as etapas da EJA não são
séries do 1º–5º — nem quando há **mais de um** ordinal solto no rótulo ("EF1 - 1º ao 5º": é um
intervalo, não há série única → sem série, fator 1,0). Rótulos que **começam** pelo ordinal
("2º Semestre") e "EJA 3º Ano" seguem exatamente como na v1 (não houve mudança para eles).

## 7. Versionamento e carimbos

* `VERSAO_VIGENTE = VERSAO_V2 = "elefante_dificuldade_v2"`; `VERSAO_V1` permanece para ler notas antigas.
* Cada `Nota` carimba a versão em `detalhes.elefante.dificuldade.versao` e
  `detalhes.dimensoes.leitura.dados.versao_dificuldade` (`escola_legada_v0` no perfil
  personalizado) e no carimbo institucional `detalhes.regua_institucional.versao_dificuldade`
  (sempre a vigente — é a régua da rede).
* Novo: `detalhes.elefante.dificuldade.catalogo = {"versao": <12 hex do sha256 de
  dados/catalogo_elefante.json>, "n_livros": N}`, calculado uma vez por processo
  (`dificuldade_livro.versao_catalogo()`). A fórmula muda só por versão; o arquivo do catálogo
  muda por commit — o carimbo diz qual extrato produziu o wordCount. Determinístico (sem
  timestamp), então recalcular duas vezes não gera UPDATE.

## 8. O que mudou desde a v1 (resumo)

1. Identidade por `elefante_id` antes do título.
2. Fallback de wordCount com status auditável.
3. Guardas numéricas na régua e na normalização (nenhum NaN/infinito/negativo; `refs.get`).
4. Contagem negativa ou não finita = 0 (na v1, `{"D": -2}` valia −2 × típico).
5. Série por extenso e rótulos "3.º ano", "EF1 - 3º", "3º B".
6. Carimbo do catálogo (`catalogo.versao` / `n_livros`) em `Nota.detalhes`.

Para toda leitura com nível válido, wordCount válido e série que a v1 reconhecia (sempre por um
padrão **marcado**), **o valor é idêntico** ao da v1: o ordinal solto só entra quando nenhum
padrão marcado casa no rótulo, então rótulos compostos ("Multisseriada 1º ao 5º Ano") mantêm a
série da v1. O que muda de propósito são os rótulos que a v1 dava como **sem** série e a v2
reconhece (por extenso, "3.º ano", "EF1 - 3º", "3º B"): neles o fator sai de 1,0 para o fator
da série — é a mudança de resolução descrita no item 5.

## 9. Como recalcular (explícito — nada é automático)

Trocar a versão **não recalcula nada sozinho**: as notas carimbadas com a v1 continuam
gravadas e **agregadas pela rede** (o carimbo existe) até o recálculo explícito.

```
python -m scripts.recalcular_institucional --pendentes --dry-run   # lista quem falta
python -m scripts.recalcular_institucional --pendentes             # recalcula só essas escolas
python -m scripts.recalcular_institucional --pendentes --dry-run   # de novo: 0 escolas
```

`--pendentes` agora seleciona escolas com alguma Nota do ano ativo (aluno ativo e matriculado)
**sem carimbo institucional** *ou* **carimbada com versão de dificuldade diferente da vigente**
(`escolas_com_versao_desatualizada`). É idempotente: depois do recálculo a escola sai da
seleção. Alternativa por escola: `POST /api/v1/escolas/{id}/recalcular` (admin ou
coordenador da escola). Anos letivos anteriores nunca são reescritos.

O **painel da rede** conta a mesma coisa: `rede._pendentes_recalculo` (bloco operacional
`recalculo_pendente` do dashboard) soma as notas **sem carimbo** *e* as **carimbadas com versão
≠ da vigente**. O que a rede **agrega** não muda com isso — nota carimbada com régua antiga é
número calculado, não ausência, e continua entrando nas médias; ela apenas deixa de ser
invisível na lista do que falta recalcular.

## 10. Pendências conhecidas

* `scripts/auditar_notas_elefante.py` compara `versao != VERSAO_VIGENTE`: notas v1 aparecem
  como divergentes até o recálculo explícito (comportamento esperado, só ciência).
* `A+` segue provisório (1 livro no catálogo).
* O backfill `--congelar-niveis` é **opcional**: enquanto não for rodado, as leituras antigas
  continuam valendo pelo nível atual do livro (mesmo número), mas uma correção de catálogo
  ainda as alcança. Rodá-lo é o que fecha essa porta para o passado.

## 11. Ramos de migração e checkout limpo

A `0030` encadeia na **`0028_nota_institucional`** (a última revisão que está no git), não na
`0029_curriculo_fase1` — que pertence a outro workstream e ainda não foi versionada. As duas
partem da mesma revisão: são **ramos irmãos** (tabelas diferentes — `cur_*` × `livros`) e
convivem. `app.core.migracoes.aplicar_migracoes` aplica **`heads`** (todos os ramos), nunca um
`head` único; `alembic_version` passa a ter uma linha por ramo. Quando os dois estiverem no
mesmo histórico, uma revisão de **merge** pode uni-los sem reescrever nenhuma das duas.

Por que isso importa: no diretório de uma máquina de desenvolvimento a `0029` existe, então
encadear nela "funciona" localmente — e **quebra no clone** ("revision not present"), que é o
que o deploy faz. `backend/tests/test_alembic.py` trava as duas pontas:

* `test_revisao_versionada_nunca_encadeia_em_revisao_fora_do_git` — lê `git ls-files` e falha,
  nomeando o culpado, se alguma revisão que vai para o git apontar `down_revision` para uma
  revisão que só existe na máquina;
* `test_checkout_limpo_aplica_migracoes_versionadas_sozinhas` — monta um `script_location`
  temporário só com as revisões do checkout limpo e roda `upgrade heads` num SQLite novo,
  conferindo tabelas e as colunas desta frente (`livros.elefante_id`, `leituras.nivel_codigo`,
  `notas.nota_*_institucional`) e que as tabelas `cur_*` **não** existem ali;
* `test_a_trava_do_checkout_limpo_realmente_pega_o_encadeamento_proibido` — o **meta-teste**:
  numa cópia temporária do diretório de revisões, comete o erro das duas formas (reencadear a
  `0030` na `0029` e acrescentar uma revisão nova já encadeada nela) e exige que as duas travas
  acusem. Uma trava que nunca falha não protege nada: sem ele, um recorte afrouxado deixaria os
  dois testes acima verdes para sempre.

Enquanto a `0030`/`0031` não entram no git, elas estão numa lista explícita no teste
(`_MIGRACOES_DESTA_FRENTE`) — uma ponte, não uma exceção permanente: assim que forem commitadas,
`git ls-files` já as devolve.

## 12. O que mudou nesta rodada

1. **Nível congelado na leitura** (`0031`): quem pontua usa
   `coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)`; correção de catálogo vale para novos
   cálculos, nunca reescreve o passado (§ 4.1).
2. **Backfill opcional e auditável**: `vincular_livros_catalogo --congelar-niveis` (dry-run por
   padrão, idempotente, auditoria agregada por escola, nenhum número muda).
3. **Auditoria alinhada aos consumidores**: `scripts/auditar_notas_elefante.py` identifica o
   livro pelo **id oficial** (`elefante_id`) antes do título ao valorar cada leitura, usa o
   nível congelado (fallback só no **nulo**, como o `coalesce`) e não conta como "fora do
   catálogo" o livro cujo `elefante_id` está no catálogo (título renomeado na escola deixa de
   gerar divergência falsa).
4. **Pendência por versão de régua no painel da rede**: `rede._pendentes_recalculo` passa a
   contar também a nota carimbada com versão ≠ da vigente — mesma regra do
   `recalcular_institucional --pendentes` —, **sem mudar o que a rede agrega** (§ 9).
5. **Checkout limpo travado por teste** (§ 11).

Nada disto recalcula nota sozinho: o histórico só muda por ação explícita e auditada do
Admin Global.

### Correções da reconferência

6. **O corte do backfill é `IS NULL`, não "sem texto"** (§ 4.1): nível congelado vazio conta
   como congelado. Antes, o backfill o regravaria com o nível do livro e a leitura pularia de
   0 para o valor do nível — o único caso em que o backfill mudaria um número.
   `auditar_notas_elefante._valor_da_leitura` usa o mesmo corte (`is None`), senão valoraria
   acima do motor e acusaria divergência falsa.
7. **O relatório não quebra no console do Windows**: `vincular_livros_catalogo` imprime `→` e
   `≠`, que não existem em `cp1252` — num terminal Windows comum o dry-run estourava
   `UnicodeEncodeError` e morria ANTES do congelamento. `main()` agora tolera o console
   (`errors="replace"`), com teste que roda o script contra um `stdout` cp1252 de verdade.
