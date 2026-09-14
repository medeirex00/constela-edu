# Dificuldade por livro do Elefante Letrado — `elefante_dificuldade_v1`

Regra **global** (rede inteira) que dá a cada leitura um valor de dificuldade a partir
dos **metadados objetivos do livro** e da **série do aluno**. Substitui a camada
"pontos de dificuldade" do scoring do Elefante; **não** altera `calcular_elefante`,
os pesos (35/30/30/5), a A3 nem a normalização P90.

```
DificuldadeLivro(livro, série) = BaseDoNível × AjusteIntrínseco × FatorSérie
```

| Camada | O que é | v1 |
|---|---|---|
| **BaseDoNível** | régua institucional **A3** já existente: `exp(0,103·pos)`, AA=0 … Z=29 (1,00 → 19,83). Intocada. | + `Z+` = pos 30 (21,98); `A+` = pos 4,5 (1,59, provisório: 1 livro); faixas (`pre_leitor`…`nivel_5`) no centro das letras |
| **AjusteIntrínseco** | quanto o livro é maior/menor que o **típico do nível** | `clamp(1 + 0,35·log₃(wordCount/medianaDoNível), 0,80, 1,35)` |
| **FatorSérie** | o mesmo livro vale mais para quem está no começo | 1º 1,40 · 2º 1,30 · 3º 1,20 · 4º 1,10 · 5º 1,00 (outra/desconhecida 1,00) |

Fonte única no código: [`backend/app/services/dificuldade_livro.py`](../backend/app/services/dificuldade_livro.py).
Catálogo de referência (752 livros): [`backend/app/dados/catalogo_elefante.json`](../backend/app/dados/catalogo_elefante.json).

## 1. O dataset (752 livros)

* 728 do catálogo padrão do Ensino Fundamental **+ 24 do tier avançado** revelado
  pelas flags `hasZPlusEnabled/hasAPlusEnabled` (23 `Z+`, 1 `A+`) = **752 únicos**,
  0 colisões, 0 sem `levelName/wordCount/pageCount`, 0 soft-deleted, 100 % `readAvailable`,
  `languageId=1`. `complexity` e `grade` são 0 em todos (campos mortos).
* `filteredRows=759` da API **não** é número de livros: com `levels:[30,199]` o count diz
  31 e a listagem devolve 24 — os 7 restantes são registros de nível Z+/A+ que o
  contador inclui e a listagem do EF descarta (tag de outro segmento/não legíveis).
  Não foram fabricados. Os 9 livros `languageId=2` são um catálogo em inglês à parte.

### Estatística que decidiu a fórmula

* `wordCount × minimumReadTime` = **1,000** (global e em todos os níveis) → o
  `minimumReadTime` é função do `wordCount`. **Uma variável só**; usar as duas contaria
  a mesma informação duas vezes.
* `wordCount × pageCount` = 0,80 global, mas **fraco ou negativo dentro dos níveis**
  (D −0,31; H −0,24; K −0,21). Páginas não discriminam dentro do nível → fora.
* Dispersão intra-nível é grande e assimétrica: CV 0,3–1,0; em X/Y/Z a média é 2–3× a
  mediana (Z: mediana 7.380, média 17.219, máx 68.915 = 9,3×). A cauda baixa é *quirk*
  de catálogo (capítulos seriados com 100 palavras em Q/W; "Azucrino" R com 15
  palavras) → **piso generoso (0,80) e teto firme (1,35)**.
* Mediana de `wordCount` quebra a monotonia no topo (W 8.788 > X 5.749 > Y 5.156) e no
  Pré-Leitor (dd 100 > A 34) → a base **não pode ser o wordCount cru**; a A3 (ordem
  pedagógica, exponencial, ≈ mediana^0,47) é a âncora certa e já é institucional.
* Níveis com pouca amostra: só `A+` (n=1) — posicionado de forma conservadora.

## 2. Modelos comparados (dados reais, 752 livros)

| | M1 nível puro | **M2 nível + ajuste robusto** | M3 tamanho puro | M4 nível + percentil |
|---|---|---|---|---|
| dispersão intra-nível (P90/P10) | 1,00 | **1,36** | 1,44 | 1,52 |
| livros ≥ típico de 3 níveis acima | 0 % | **0 %** | 90 % (hierarquia destruída) | 0 % |
| outlier Z 68.915 palavras | 19,8 (=típico) | **26,8 (1,35×)** | 22,0 | 26,8 |
| "Azucrino" (R, 15 palavras) | 8,70 | **6,96 (0,80×)** | 1,96 | 6,96 |
| correlação intra-nível com wordCount | 0 | **0,97** | 0,92 | 0,89 |
| livros AA para igualar 1 Z | 20 | **20** | 12 | 24 |
| livro novo fora do catálogo | ok | **ok (vale o típico)** | precisa wordCount | precisa recalcular percentis |

**Escolhido: M2.** Preserva a hierarquia AA→Z→Z+ (mediana por nível monótona), diferencia
dentro do nível seguindo o wordCount (r = 0,97) sem transformar 20× de tamanho em 20× de
pontos, é resistente a outliers dos dois lados, determinístico para livros novos e
explicável ("um livro 2× maior que o típico do nível vale +22 %; 3× ou mais, +35 %;
nunca menos de −20 %"). M4 (percentil) tem dispersão parecida mas depende da composição
do catálogo (um livro novo muda os percentis dos outros) — não versiona bem. M3 é só
baseline: 90 % dos livros saltam 3 níveis, o nível deixa de mandar.

Sensibilidade de M2: α=0,25/teto 1,25 → dispersão 1,29; α=0,50/teto 1,50 → 1,59 e 1,9 %
dos livros passam do típico de 3 níveis acima. **0,35/0,80/1,35** é o ponto em que o teto
(+35 %) fica **abaixo de 3 degraus da A3** (exp(0,103·3) = 1,362): um livro excepcional se
aproxima da faixa seguinte, mas nunca ultrapassa o típico de 3 letras acima.

## 3. Fator de série

| fator | 1º | 2º | 3º | 4º | 5º | leitor típico 5º/1º* |
|---|---|---|---|---|---|---|
| F0 | 1,00 | 1,00 | 1,00 | 1,00 | 1,00 | 5,2× |
| F1 | 1,15 | 1,11 | 1,08 | 1,04 | 1,00 | 4,5× |
| **F2** | **1,40** | **1,30** | **1,20** | **1,10** | **1,00** | **3,7×** |
| F3 (1,1^k) | 1,46 | 1,33 | 1,21 | 1,10 | 1,00 | 3,5× |

\* 10 livros do nível típico da série (1º F, 2º K, 3º N, 4º T, 5º V), segundo as
faixas de proficiência do próprio Elefante ("Pré-Leitor – 1º ano", "Iniciante – até 2º",
"Em Processo – 2º e 3º", "Fluente – 4º e 5º").

**Escolhido: F2** — "+10 pontos percentuais por série abaixo do 5º". É o mais explicável,
corrige de forma moderada (o gap entre séries cai de 5,2× para 3,7×, sem inverter: um
5º ano lendo no nível dele continua na frente de um 1º ano lendo no nível dele), e a
diferença máxima entre séries (1,40) ≈ 3 degraus da A3 — a mesma ordem de grandeza do
ajuste intrínseco. Equalizar totalmente as séries exigiria ~6× e viraria uma régua por
série (outra decisão institucional, fora do escopo). Parâmetro versionado: mudar é v2.

## 4. Anti-farming (v1, 5º ano; entre parênteses 1º ano)

* 30×AA = 30,0 (42,0) · 30×A = 45,3 · 10×N = 57,6 · 5×S = 48,2 · 1×Z = 19,8 · 1×Z+ = 22,0
* AA para igualar 1 Z: **20** · A para 1 N: 3,8 · D para 1 V: 6,4
* 5º ano lendo 2 livros típicos da série (V) = 26,3 **>** 20×AA = 20,0.
* Cruzado: 1º ano lendo 20×A (42,3) ≈ 5º ano lendo 2×Z (39,7).

A dificuldade continua LINEAR na soma (sem segunda normalização, ver §5); o que impede o
spam de fáceis é a **escada da A3** (1→19,8) somada ao ajuste (um Z gigante vale 26,8) e
ao fato de "livros" (volume) já saturar na nota. Nota honesta: a parte de BAIXO da A3 é
comprimida (AA→D = 2,1× para 12× de palavras) — herança da régua institucional, que não
cabe alterar aqui; entre AA e D, dentro da mesma série, 20 AA ≈ 10 D. Fora da série
(5º ano lendo AA) a distância para o típico dele é de 10–13×.

## 5. Interação com a normalização / P90 — nada duplicado

* **Valor absoluto da leitura** = `DificuldadeLivro` (o que histórico, ranking por
  período e premiações mostram em "pontos").
* **Valor no ranking** = `calcular_elefante` continua fazendo
  `normalizar(Σ pontos, P90 da escola) × 30 %` — LINEAR, como antes (o indicador não está
  em `INDICADORES_VOLUME`). O P90 é recalculado a partir dos próprios valores v1, então a
  régua se recalibra sozinha; **não** foi criada nenhuma segunda normalização nem
  saturação. A escala de "pontos" muda de magnitude (A3 já era a escala institucional;
  a régua-semente 1/2/4/8/12/16 das telas de período deixa de existir), portanto
  referências **manuais** de `max_pontos_dificuldade` e o bônus `pontos_por_livro`
  (escolas personalizadas) devem ser revistos pelo Admin — ver Pendências.

## 6. Arquitetura implementada

```
Leitura → Livro(título, nível) ──┐
SnapshotElefante.livros_por_nivel ┤→ dificuldade_livro.regra_da_escola(db, escola)
Turma.ano_escolar (série) ────────┘        │
                                            ├─ RegraV1 (GLOBAL): catálogo (arquivo) → wordCount
                                            │     valor_livro / valor_tipico / pontos_por_chave (híbrido) / pontos_aluno
                                            └─ RegraEscolaLegada (só perfil personalizado = override autorizado)
Consumidores (todos): nota anual (scoring._carregar_contexto / _insumos_institucionais),
/ranking/leitura, premiações, evolução (ranking + série do aluno), perfil (card de faixas)
e histórico do aluno, catálogo de livros, simulador, mural/insights.
```

* **Híbrido**: cada livro **itemizado** (linha de `Leitura` com título) vale o seu valor;
  o **restante** da contagem do snapshot naquele nível vale o típico do nível. Snapshot
  velho (contagem < itemizados) → só os itemizados. Determinístico.
* **Catálogo = arquivo versionado no repo**, não tabela: é referência de calibração, não
  dado transacional. Auditável (cada atualização é um commit com diff livro a livro),
  reproduzível, **sem migração** — e havia uma razão dura: `app/main.py` roda
  `alembic upgrade head` no import; uma 2ª head ao lado da `0029` (workstream paralelo,
  ainda não commitada) derrubaria toda a suíte e o dev server.
  Regenerar: `python scripts/gerar_catalogo_elefante.py <extrações.json>`.
* **Fallback determinístico**: título fora do catálogo → típico do nível; nível fora da
  escada → 0 (como a A3); série desconhecida → fator 1,0.
* **Custo**: uma query de leituras por recálculo (em lote, nunca por aluno); catálogo em
  memória (`lru_cache`). A catraca de custo por dimensão continua verde.

## 7. Versionamento e histórico

* `VERSAO_VIGENTE = "elefante_dificuldade_v1"` — constante de código. Parâmetros
  (inclusive as **medianas por nível**) congelados na calibração de 2026-09-14/752 livros.
* Cada `Nota` carimba a versão: `detalhes.dimensoes.leitura.dados.versao_dificuldade` e
  `detalhes.elefante.dificuldade.versao` (`escola_legada_v0` no perfil personalizado).
* **Livro novo**: recebe valor pela versão vigente (mesmas medianas) assim que entrar no
  catálogo; até lá vale o típico do nível. Atualizar o catálogo = commit revisável.
* **Leituras antigas**: o recálculo só toca o ano letivo ATIVO (comportamento existente);
  anos anteriores nunca são reescritos. Trocar de versão = nova constante + recálculo
  explícito (`/recalcular`) pelo Admin — **nunca** recálculo histórico silencioso.
* Guarda de calibração em teste: as medianas congeladas batem exatamente com o catálogo
  de 752; um catálogo atualizado só pode desviá-las até 25 % (senão é hora de uma v2
  explícita, não de editar a v1).

## 8. Governança

* A fórmula é global e **nenhum endpoint a edita**. `GET /escolas/{id}/configuracoes/
  dificuldade-livro` expõe versão, parâmetros, catálogo e a decomposição de um exemplo
  (explicação para coordenação/professores).
* A config de dificuldade por escola/série/turma (`NivelDificuldade` / `DificuldadeTurma` /
  `PontuacaoNivelTurma`) **não foi apagada**: virou **override autorizado**, ativo só no
  perfil `personalizado`. Trocar o perfil (`PUT /perfil-scoring`) passou a exigir
  **Admin Global** (antes: coordenador). O ranking da REDE (`*_institucional`) usa
  sempre a v1, mesmo em escola personalizada.

## 9. Impacto antes/depois (catálogo, 5º ano = fator 1,0)

Antigo = A3 por nível (nota anual/institucional). ↑ 362 · ↓ 356 · = 34 · mediana 0,0 % ·
P5 −20 % · P95 +24 % (teto +35 %, piso −20 %). Nas telas de PERÍODO o "antigo" era a
tabela-semente da escola (1/2/4/8/12/16): lá a mudança é de escala (AA 1→1,0; D 4→2,06;
Z 16→19,8) além do ajuste — é a unificação pedida (anual = período = premiações).

| nv | título | wc | A3 | seed | 1º | 2º | 3º | 4º | 5º | var |
|---|---|---|---|---|---|---|---|---|---|---|
| AA | Alfabeto Ilustrado. Letra Q | 12 | 1,00 | 1 | 1,40 | 1,30 | 1,20 | 1,10 | 1,00 | 0 % |
| A | Nino e Bela | 100 | 1,51 | 2 | 2,83 | 2,63 | 2,43 | 2,22 | 2,02 | +34 % |
| D | Cadê Cadê / Mamo tu | 47 | 2,06 | 4 | 2,30 | 2,14 | 1,97 | 1,81 | 1,65 | −20 % |
| H | Pessoas do Mundo – Levi Strauss | 483 | 3,10 | 4 | 4,36 | 4,05 | 3,74 | 3,43 | 3,12 | 0 % |
| N | Formosuras do velho Chico | 1.460 | 5,76 | 8 | 8,06 | 7,49 | 6,91 | 6,34 | 5,76 | 0 % |
| R | Azucrino (15 palavras) | 15 | 8,70 | 8 | 9,74 | 9,05 | 8,35 | 7,65 | 6,96 | −20 % |
| R | A fada que tinha ideias – Peça | 11.224 | 8,70 | 8 | 16,44 | 15,26 | 14,09 | 12,92 | 11,74 | +35 % |
| S | Caderno de mistérios 1 | 7.842 | 9,64 | 12 | 16,19 | 15,03 | 13,87 | 12,72 | 11,56 | +20 % |
| X | Sagatrissuinorana (247 p.) | 247 | 16,14 | 12 | 18,07 | 16,78 | 15,49 | 14,20 | 12,91 | −20 % |
| Z | Coleção Mitologia 10 – Afrodite | 7.380 | 19,83 | 16 | 27,76 | 25,77 | 23,79 | 21,81 | 19,83 | 0 % |
| Z | O Castelo Encantado | 68.915 | 19,83 | 16 | 37,47 | 34,79 | 32,12 | 29,44 | 26,77 | +35 % |
| Z+ | A história do doutor Dolittle | 23.549 | 0 (fora) | — | 30,77 | 28,57 | 26,37 | 24,17 | 21,98 | novo |

Reproduzir: `python scripts/simular_impacto_dificuldade.py [--completo]`.

## 10. Pendências / riscos

1. **Regra de série vs. ranking único da escola**: a nota de leitura deixa de ser idêntica
   entre séries com dados iguais (agora difere só pelo fator global). Decisão de produto
   já tomada no mandato; o teste de turnos foi reescrito para o novo invariante.
2. **Escolas personalizadas**: ficam na régua legada por faixa (sem dificuldade por livro)
   até o Admin Global devolvê-las ao perfil institucional. Referências manuais
   (`max_pontos_dificuldade`) e `pesos.elefante_extra.pontos_por_livro` foram calibrados na
   escala antiga — revisar se alguma escola os usa.
3. **`A+`**: 1 livro no catálogo; posição provisória (entre A e B). Recalibrar quando houver amostra.
4. **Os 7 registros do `filteredRows`**: não são livros do EF; se algum dia aparecerem
   na listagem, entram pelo fluxo normal do catálogo.
5. **Motor V2 (`app/services/pontuacao/`, workstream paralelo, untracked)** ainda chama
   `scoring.mapa_pontos_turmas` para a coletiva — fora deste escopo; a varredura estática
   o ignora de propósito.
6. Front-end: telas que mostram "pontos por livro" (catálogo, histórico) passam a exibir o
   valor v1 (catálogo sem série = 5º ano). Nenhum contrato de API mudou; só a magnitude.
