# 20 — Migração de Dados & Importação / Data Migration & Import

- **Status:** 🟢 aprovado / approved
- **Padrão / Standard:** [ADR-0002](decisoes/ADR-0002-padrao-de-capitulo.md) (16 partes)
- **Fontes / Sources:** `INDICE.md` (bloco 20, subseções 20.1–20.41), `_estado-atual/RELATORIO-2026-07-09.md`, e o **código Q0 já implementado**: `backend/app/services/importacao.py` (pipeline de 4 estratégias que competem: TABELA/VERTICAL/RÓTULOS/POSICIONAL; `normalizar_nome`, `casar_nomes`, `casa_abreviado_posicional`), `backend/app/services/perfis_pdf.py` (`PerfilElefanteTurma`, `PerfilElefanteEstudante`, `PerfilMatific` — leitura posicional via pdfplumber), `backend/app/services/planilhas.py` (XLSX **só Matific**; `ValueError` se ≠ matific), `backend/app/services/lista_piloto.py` (matrículas `.xls`/`.xlsx`, `ra_util`, `_canonizar_turma`), `backend/app/services/matriculas.py` (núcleo **puro** do casamento: RA → nome+turma → abreviação posicional, unicidade bipartida, vetos), `backend/app/routers/importacoes.py` (2 etapas `analisar`→`confirmar`; `/uploads/temporarios` TTL 24h; auditoria `aluno.identidade_vinculada`), `backend/app/routers/academico.py` (`POST /alunos/fundir`, confirmação `"FUNDIR"`), `backend/app/quest/services/credenciais.py` (`garantir_credencial_aluno`; `codigo_login` falável + `qr_token`), `backend/app/services/backup.py` (export/restore JSON por escola, `VERSAO_BACKUP=1`), `backend/scripts/seed.py`, Seções [10](10-professor-familia.md)/[11](11-arquitetura.md)/[12](12-seguranca-privacidade.md)/[14](14-infra-deploy-dr.md)/[21](21-suporte-operacao.md), Apêndice B
- **Depende de / Depends on:** princípios (P13 servidor é autoridade · P14 ledger imutável · P15 isolamento por escola · P16 identidade da criança vive no Edu · P6 erro nunca pune) → [01](01-principios-imutaveis.md); **modelo de dados / schema / desenho do Alembic / tenancy** → [11](11-arquitetura.md); **execução** da migração de **schema** no deploy + **backup/restore/DR** como operação → [14](14-infra-deploy-dr.md); **política** LGPD (coleta mínima, consentimento, retenção, anonimização, erasure) → [12](12-seguranca-privacidade.md); **papéis** de quem importa + vínculo responsável↔aluno → [10](10-professor-familia.md); **quais operações geram `logs_auditoria`** → [12](12-seguranca-privacidade.md) e o **schema/entrega** de `logs_auditoria` → [11](11-arquitetura.md); **comunicação/agenda** do cutover à escola → [21](21-suporte-operacao.md); **contratos formais** de formato de arquivo e de API de import → Apêndice B.

> **Convenção / Convention:** "§N" = uma das 16 **partes deste capítulo** / one of the 16 **parts of this
> chapter**; "Seção NN" / "Section NN" = outro capítulo da Bible; "20.NN" = uma subseção do plano do `INDICE.md`.
> **Escopo / Scope:** este capítulo decide a **estratégia e as regras de migração e importação de DADOS** do
> Constela — o **pipeline** de import (upload→parse→normalizar→casar→pré-visualizar→aplicar→auditar→relatar), a **regra de
> ouro** *casar automático × fundir manual*, a **precedência de casamento**, o **provisionamento** do lado Quest a
> partir do roster, e a **portabilidade** por escola. Ele **decide a mecânica e o critério do ETL de dados**;
> **não** decide o **modelo/schema** de dados nem o desenho do Alembic (Seção [11](11-arquitetura.md)), a
> **execução** da migração de **schema** no deploy nem o backup/DR operacional (Seção [14](14-infra-deploy-dr.md)),
> a **política** LGPD (Seção [12](12-seguranca-privacidade.md)), os **papéis** (Seção [10](10-professor-familia.md))
> nem a **comunicação/agenda** do cutover (Seção [21](21-suporte-operacao.md)) — apenas os **aplica** e **referencia**. Os
> **contratos formais** de arquivo/API descem para o **Apêndice B**.

---

## 🇧🇷 Migração de Dados & Importação

### 1. Objetivo
Ser a **referência definitiva de como os dados entram, se reconhecem e se preservam** no Constela: importar
matrículas/turmas/alunos e os relatórios das plataformas externas (Matific, Elefante Letrado) **sem nunca renomear
a criança errada, sem perder histórico e sem gravar nada antes da confirmação**. Decide a **estratégia e as regras
do ETL**; **não** decide o **schema** (Seção [11](11-arquitetura.md)), a **execução** da migração de schema/backup
(Seção [14](14-infra-deploy-dr.md)), a **política** LGPD (Seção [12](12-seguranca-privacidade.md)) nem os **papéis**
(Seção [10](10-professor-familia.md)) — apenas os **aplica**. Os contratos formais ficam no **Apêndice B**.

### 2. Contexto
Constela é **Hub → Edu → Quest**. A identidade da criança **vive no núcleo Edu** (P16): o Quest **deriva** dela
(`quest_perfis`/`quest_credenciais_aluno`), nunca o contrário. **Estado atual (Q0) — grande parte do pipeline já
existe e funciona:**
- **4 caminhos de entrada** — (1) **PDF** de relatório; (2) **XLSX** de relatório (**só Matific**); (3) **texto
  colado/`.csv`/`.txt`**; (4) planilha de **matrículas "Lista Piloto"** (`.xls`/`.xlsx`).
- **Parsers reais** — `perfis_pdf.py` (leitura **posicional** via pdfplumber: Elefante turma, Elefante individual,
  Matific estrelas); `importacao.py` (4 estratégias genéricas que **competem** e vence a que reconhece mais alunos);
  `planilhas.py` (Matific XLSX; **levanta `ValueError` se ≠ matific** — Elefante XLSX **não** é suportado);
  `lista_piloto.py` (matrículas, uma aba por turma, `.xls` via xlrd e `.xlsx` via openpyxl).
- **Detecção automática** — o usuário **não** informa o formato: a plataforma é detectada por palavras-chave; as
  colunas casam por **semelhança difusa** (acento/caixa ignorados, `SequenceMatcher ≥ 0,82`), nunca por nome exato.
- **Casamento** — relatório: `exato`/`provável`/`não-encontrado` (provável **exige** confirmação humana; homônimo
  desempata pela turma, senão vira `não-encontrado` para **nunca pontuar aluno errado**). Matrículas: núcleo **puro**
  `matriculas.py` — precedência **RA → nome+turma exato → abreviação posicional**, com **unicidade bipartida** e
  **vetos** (overlap de turma série+letra; nascimento divergente); ambíguo → **cria aluno novo + aviso** para usar
  *Fundir alunos*.
- **CASAR × FUNDIR** — **CASAR** (trocar o nome abreviado antigo pelo completo mantendo o **mesmo `aluno_id`**) é
  **automático** e reversível; **FUNDIR** (unir dois `aluno_id`) é **sempre manual** (`POST /alunos/fundir`,
  confirmação textual `"FUNDIR"`, irreversível).
- **2 etapas** — `analisar` (prévia, **nada grava**) → `confirmar` (grava **só o aprovado**).
- **Snapshots imutáveis e complementares** — `SnapshotMatific`/`SnapshotElefante` nunca sobrescritos; `Leitura` com
  `UNIQUE(aluno_id, livro_id)` (releitura **não** repontua); import por período **soma** ao acumulado com piso
  anti-regressão.
- **Arquivo-fonte guardado (só relatório PDF/XLSX)** — o relatório vai para `/uploads/temporarios` (TTL **24 h**) →
  movido para `/uploads/{plataforma}/` na confirmação (saneado contra path traversal). A **Lista Piloto** é
  **re-enviada** na confirmação e **não** é arquivada; o **texto colado** não gera arquivo.
- **Portabilidade** — `backup.py` export/restore JSON **por escola** (`VERSAO_BACKUP=1`, restore **destrutivo** em
  uma transação); o **backup não contém** usuários nem o lado Quest, **porém** o restore **apaga o aluno e, por
  cascata, destrói todo o Quest da escola** — perfis, credenciais e o **ledger imutável** de progresso/tentativas —
  sem repor nada. É um **risco de invariante** (P14/P16/P6), tratado em §12/§15, não uma mera decisão futura.
- **Papéis** — só `admin`/`coordenador` importam; **professor não**.
- **Ainda NÃO existe** — a **prévia confirmável linha a linha** e o **desfazer import** como etapas formais do
  pipeline (hoje `confirmar` grava direto; a prévia **read-only** do `analisar` existe); **Elefante XLSX**; importador
  **CSV dedicado** (CSV cai no texto genérico); **OCR** de PDF escaneado (é recusado); a **combinação de dois ledgers
  Quest não-vazios** (o *fundir-aluno* do Edu **já** migra o perfil Quest, ou **descarta com contagem auditada** o do
  removido quando ambos têm perfil; **combinar** progresso é o que não existe — P14 impede reescrever o ledger);
  **provisionamento Quest em massa** na matrícula (hoje só no fluxo de cartões da turma).

Este capítulo **formaliza** a estratégia, fixa a regra de ouro e registra o que falta decidir.

### 3. Filosofia da funcionalidade
**"Um dado importado errado vira uma criança com o nome trocado — isso não pode acontecer."** A migração é onde o
produto toca a **identidade real** de milhares de crianças, coletada de escolas que ainda vivem em PDFs e planilhas
imperfeitas. Princípios que guiam a Seção 20: **nada grava sem confirmação** (a prévia é sagrada); **preferir o
falso-negativo ao falso-positivo** (melhor um cadastro duplicado — falso-negativo, que o gestor funde depois — do que
renomear a criança errada — falso-positivo; na dúvida, **cria novo e avisa**); **o Excel é a fonte da verdade da
identidade** (o nome completo da matrícula vence o
abreviado do relatório); **casar é reversível, fundir não** (por isso casar pode ser automático e fundir é sempre
humano); **ausência ≠ exclusão** (uma planilha que não lista um aluno **não** o apaga); e **o histórico é
intocável** (casar preserva snapshots/leituras/notas no mesmo `aluno_id`; o ledger do Quest é imutável — P14).

Conexão com os **Princípios Imutáveis** ([01](01-principios-imutaveis.md)): **P16** (identidade no Edu) — o import
cria `quest_perfis`/credenciais a partir do aluno do Edu, **nunca** cria linha em `usuarios`; **P15** (isolamento) —
todo provisionamento respeita `escola_id`; **P13/P14** (servidor autoridade + ledger imutável) — a fusão de perfil
Quest não pode reescrever o ledger; **P6** (erro nunca pune) — aluno transferido é **"cartão descansando"**, nunca
um "código errado" que culpe a criança.

### 4. Experiência que o jogador deve sentir
A criança **não** vive a migração diretamente — ela vive o **resultado**: o cartão funciona no primeiro dia, o nome
na tela é o **seu nome completo** (não "NINA M"), e o progresso que já existia **continua ali**. **O gestor**
(admin/coordenador) sente **controle e segurança**: sobe o arquivo, **vê a prévia**, entende cada linha (casada,
provável, nova), confirma, e recebe um **relatório** do que entrou. **A escola** confia porque a transição de
Matific/Elefante para o Constela **não perde ninguém** e **não bagunça** os cadastros que ela já mantinha.

### 5. Fluxo completo
O **pipeline canônico** de importação (⭐ = já existe em Q0; ▢ = decisão/implementação a fazer):

1. **Upload/colar** ⭐ — o gestor sobe PDF/XLSX ou cola texto; o **relatório** vai para `/uploads/temporarios`
   (TTL 24 h); a **Lista Piloto** é lida e re-enviada na confirmação (não arquivada); o **texto colado** não vira arquivo.
2. **Detecção + parse** ⭐ — a plataforma é reconhecida por palavras-chave; o parser posicional (ou as 4 estratégias
   genéricas que competem) extrai as linhas; PDF escaneado/imagem é **recusado** com diagnóstico (sem OCR).
3. **Normalizar** ⭐ — nomes sem acento/caixa/espaço colapsado; chave de turma por **série+letra** (ignora "ano"/turno).
4. **Casar** ⭐ — cada linha é classificada: relatório → `exato`/`provável`/`não-encontrado`; matrículas → RA >
   nome+turma > abreviação posicional, com unicidade bipartida e vetos; ambíguo → **novo + aviso**.
5. **Pré-visualizar** — a **prévia read-only** do `analisar` ⭐ mostra o que **vai** acontecer por linha, **sem
   gravar**; falta ▢ a etapa formal de **prévia confirmável linha a linha** (com *diff* + marcação de *provável* que
   exige aprovação, **congelada** até o `confirmar`).
6. **Aplicar (transacional, atômico)** — a confirmação grava **só o aprovado** num **único commit** (entra inteiro
   ou nada) ⭐; o Excel é a fonte da verdade da identidade (`existente.nome = parsed.nome`). *Hoje* o `confirmar` de
   matrículas **re-analisa** o arquivo contra o estado atual (sem prévia congelada) e o de relatórios confia nas
   linhas devolvidas; a **prévia congelada + revalidação server-side** e o **rollback/undo** de um import já aplicado
   são ▢ (M9b).
7. **Auditar** ⭐ — grava `aluno.identidade_vinculada` (quando o nome muda) e `matriculas.importadas` (lote) em
   `logs_auditoria`; o relatório PDF/XLSX é movido para `/uploads/{plataforma}/`.
8. **Relatar** ⭐ — o gestor recebe o resumo (importados, prováveis pendentes, novos, avisos) e o histórico em
   `GET /importacoes`.

**Provisionamento do Quest** (fluxo paralelo): a **geração de perfil+credencial** isolada por `escola_id` ⭐ **já
existe** (`credenciais.py`), hoje **só no fluxo de cartões da turma**; o **provisionamento em massa a partir do
roster** e o **gatilho** (automático na matrícula × só na geração de cartões × só na 1ª entrada) são ▢/⚠️ (decisão
do dono, §15/M11).

### 6. Interface (quando existir)
**A UI de import** (arrastar-e-soltar, tela de prévia, botão *Confirmar*, ferramenta *Fundir alunos*) pertence ao
**fluxo/UX** (Seções [07](07-ux-fluxos-navegacao.md)/[08](08-onboarding-ftue.md)); a Seção 20 define a **regra por
trás** (2 etapas, nada grava sem confirmar, *provável* exige aprovação, ambíguo vira aviso). Superfícies: a **prévia
por linha** (casada/provável/nova + *diff* de nome), o **relatório pós-import** e o **histórico** de importações.

### 7. UX
A "UX de dados" é a do **gestor adulto**: **prévia antes de tudo**, **linguagem clara por linha** (o que casou, o que
é provável, o que é novo, e **por quê**), **avisos acionáveis** ("dois cadastros parecem a mesma criança — use
Fundir alunos"), e, como **alvo**, **zero surpresa** — a confirmação fazer **exatamente** o que a prévia mostrou
depende da **prévia congelada + revalidação server-side**, evolução ▢ do M9b (hoje o `confirmar` de matrículas
re-analisa contra o estado atual). Erro de arquivo (inválido, colunas faltando, encoding, PDF ilegível) →
**mensagem clara + escrita atômica** (o import entra inteiro ou não entra).

### 8. Game Design
**N/A** — a migração é um sistema **do adulto**, fora do laço de jogo da criança. Ponto de contato: o
provisionamento cria a **credencial** com que a criança entra (`codigo_login` falável, `qr_token`) e o **perfil** de
onde o jogo parte; a **preservação de histórico** garante que o progresso pedagógico já coletado não seja destruído
pelo casamento.

### 9. Regras de negócio
As **normas de migração/importação** (a fonte da estratégia; o **schema** é da Seção [11](11-arquitetura.md), a
**execução** da migração de schema/backup é da Seção [14](14-infra-deploy-dr.md), a **política** LGPD da Seção
[12](12-seguranca-privacidade.md)):

| # | Norma | Regra | Fronteira |
|---|-------|-------|-----------|
| M1 | **Duas etapas + atômico** | `analisar` (prévia read-only, **nada grava**) → `confirmar` (grava só o aprovado num **único commit**: entra inteiro ou nada); a prévia é sagrada | 20 |
| M2 | **Sem informar formato** | detecção automática de plataforma (palavras-chave) + parsers posicionais e 4 estratégias que **competem** (vence quem reconhece mais alunos; desempate: resumo antes de leituras, depois tabela→vertical→rótulos→posicional — detalhe no Apêndice B); colunas por semelhança difusa, nunca nome exato | 20; contrato = Apêndice B |
| M3 | **Casar × Fundir** | **CASAR** (mesmo `aluno_id`, nome abreviado→completo) é **automático e reversível**; **FUNDIR** (unir dois `aluno_id`) é **sempre manual** (`"FUNDIR"`, irreversível) e só entre alunos **ativos** (arquivado/transferido: reativar antes) | 20 |
| M4 | **Precedência de casamento** | **RA → nome+turma exato → abreviação posicional**, só quando **inequívoco** (unicidade bipartida); RA reativa **soft-delete** (`status='excluido'`), com **veto** se o nome contradiz — **nunca** ressuscita cadastro sob **erasure LGPD** (cria novo) | 20; erasure = [12](12-seguranca-privacidade.md) |
| M5 | **Regra de ouro** | **custo(falso-positivo) ≫ custo(falso-negativo)** — preferir a duplicata (falso-negativo) ao renomeio errado: na dúvida **cria aluno novo + aviso** (fila de revisão); **nunca** renomeia a criança errada nem pontua o aluno errado | 20 |
| M6 | **POOL × fonte da verdade** | o **POOL** do reconhecimento **abreviado-posicional** = só cadastros de upload (Matific/Elefante/Leitura) **sem RA** e com ≥2 tokens; **separadamente**, **todo** cadastro casado (por RA, nome+turma **ou** abreviação) tem o nome **sobrescrito** pelo nome completo do Excel (fonte da verdade da identidade) | 20 |
| M7 | **Histórico intocável** | casar **preserva** snapshots/leituras/notas/telemetria no mesmo `aluno_id`; `Leitura` é `UNIQUE(aluno_id,livro_id)` (releitura não repontua); o **ledger do Quest é imutável** (P14) | 20; modelo = [11](11-arquitetura.md) + Apêndice B (DDL) |
| M8 | **Snapshots imutáveis** | `SnapshotMatific`/`SnapshotElefante` nunca sobrescritos e **complementares**; import **por período** soma ao acumulado com **piso anti-regressão**; reimportar o mesmo período não soma duas vezes | 20; modelo = [11](11-arquitetura.md) + Apêndice B (DDL) |
| M9a | **Idempotência** ✅ | reimportar **não duplica** (chave natural/RA; `Leitura` `UNIQUE`; período com piso) — **já existe** | 20 |
| M9b | **Prévia confirmável + undo** ▢ | prévia **congelada** confirmável linha a linha (com *diff* + revalidação server-side) e **rollback/undo** de import aplicado — **a implementar**; o undo **nunca** apaga ledger imutável (P14) nem cascateia `aluno→quest_perfis`/credencial/ledger (P6) | 20 ▢ |
| M10 | **Robustez / ausência ≠ exclusão** | campo ilegível vira **aviso** (a linha sobrevive); erro real só sem nome/sem dado; **planilha que não lista um aluno NÃO o apaga**; recusa PDF escaneado (sem OCR) | 20 |
| M11 | **Provisionamento Quest** | criar `quest_perfis` + `quest_credenciais_aluno` a partir do roster, **isolado por `escola_id`** (o mecanismo **já existe** via cartões da turma); o **gatilho** (automático × cartões × 1ª entrada) e o **provisionamento em massa** são decisão do dono | 20 ⚠️ (gatilho — §15); schema = [11](11-arquitetura.md) |
| M12 | **Geração de credencial** | a 20 **gera** `codigo_login`/`qr_token` **únicos** (tratando colisão); o **formato falável** (`PALAVRA+NNNN`) é design de **identidade/onboarding** e a **entropia/anti-enumeração** é da Seção [12](12-seguranca-privacidade.md) — não da 20 | 20 (geração/unicidade); formato = onboarding/identidade; entropia = [12](12-seguranca-privacidade.md) |
| M13 | **LGPD do import** | o **arquivo-fonte com PII** (só o relatório PDF/XLSX é arquivado; matrícula é re-enviada; texto não vira arquivo) tem acesso restrito, **retenção mínima** e **descarte**; a **política** (prazo/base legal) precisa ser fixada na Seção [12](12-seguranca-privacidade.md) | 20 (aplica); política = [12](12-seguranca-privacidade.md) ⚠️ (criar item de retenção — §15) |
| M14 | **Auditoria da migração** | todo vínculo de identidade gera `aluno.identidade_vinculada` e o lote gera `matriculas.importadas`, gravados em `logs_auditoria`; **quais operações** auditar = Seção [12](12-seguranca-privacidade.md), **schema/entrega** de `logs_auditoria` = Seção [11](11-arquitetura.md) | 20 (aplica); operações = [12](12-seguranca-privacidade.md); schema = [11](11-arquitetura.md) |
| M15 | **Papéis** | **só `admin`/`coordenador`** importam/casam; **professor não** (hoje); a **criança nunca** entra em `usuarios` (o import cria `quest_perfis`, não usuário) | 20 (aplica); papéis = [10](10-professor-familia.md) ⚠️ (habilitar professor — §15) |
| M16 | **Portabilidade por escola** | o export/restore JSON **por `escola_id`** (formato/escopo/salvaguarda) é da 20; restore é **destrutivo** e **hoje apaga por cascata todo o Quest** da escola (perfis/credenciais/ledger imutável) — incluir/preservar o Quest é decisão do dono; a **operação de DR do banco** (PITR) é da Seção [14](14-infra-deploy-dr.md) (mecanismo distinto) | 20 (formato/escopo) ⚠️ (Quest — §15); política LGPD = [12](12-seguranca-privacidade.md); DR do banco = [14](14-infra-deploy-dr.md) |
| M17 | **Cutover da escola-piloto** | a **estratégia técnica** (big-bang × por turma × coexistência) e a **validação antes de expor as crianças** são da 20; a **janela/deploy** é da Seção [14](14-infra-deploy-dr.md) e a **comunicação/agenda** da Seção [21](21-suporte-operacao.md) | 20 (estratégia) ⚠️ (§15); janela/deploy = [14](14-infra-deploy-dr.md); comunicação = [21](21-suporte-operacao.md) |

### 10. Arquitetura técnica
Onde a migração **toca** o código (tudo Q0 real, salvo ▢):
- **Parsers** — `perfis_pdf.py` (posicional/pdfplumber), `importacao.py` (estratégias que competem), `planilhas.py`
  (Matific XLSX), `lista_piloto.py` (matrículas). Contratos de extração **ancorados nos arquivos-exemplo reais**
  (verdade de base — nenhum parser muda sem validar contra eles).
- **Casamento** — `matriculas.py` (núcleo **puro**, sem ORM: RA/nome/abreviação posicional, unicidade bipartida,
  vetos) e `importacao.py::casar_nomes` (relatório).
- **Orquestração** — `importacoes.py` (`/analisar`→`/confirmar` para relatórios e matrículas; guarda o arquivo;
  grava auditoria). **▢** falta a etapa formal de **pré-visualização confirmável linha a linha** e o **undo**.
- **Provisionamento** — `quest/services/credenciais.py` (`garantir_credencial_aluno`/`_turma`; `codigo_login`
  falável, `qr_token`); modelos `quest_perfis`/`quest_credenciais_aluno` (schema = Seção [11](11-arquitetura.md)).
- **Portabilidade** — `backup.py` (export/restore JSON por escola) é da **20**; o restore é destrutivo e **hoje
  cascateia sobre alunos, apagando o Quest** (ver §12/§15). A **operação de DR do banco** (snapshot/WAL/PITR) é da
  Seção [14](14-infra-deploy-dr.md) — **mecanismo distinto** do export JSON.
- **Seed** — `scripts/seed.py` (base idempotente + demo); `seed_e2e.py` (determinístico). Migração de **dados**
  (não de schema) idempotente no boot vive em `garantir_dados_base` (backfills), distinta do Alembic (Seção [14](14-infra-deploy-dr.md)).

### 11. Dependências com outros módulos
**Consome / referencia:**
- **Seção [11](11-arquitetura.md)** — o **modelo/schema** de destino (alunos, turmas, matrículas, snapshots,
  `quest_perfis`, `Leitura` com `UNIQUE` — DDL detalhado no Apêndice B), o desenho do Alembic, a **tenancy** por
  `escola_id`, a imutabilidade do ledger e o **schema/entrega de `logs_auditoria`**.
- **Seção [14](14-infra-deploy-dr.md)** — a **execução** da migração de **schema** no deploy e o **backup/DR de infra**
  (snapshot/WAL/PITR) como operação (a 20 é o **ETL de dados** + o export JSON `backup.py`, não opera Alembic nem PITR).
- **Seção [12](12-seguranca-privacidade.md)** — a **política** LGPD (coleta mínima, consentimento, retenção,
  anonimização, erasure, entropia da credencial) e **quais operações geram `logs_auditoria`** (auditoria de acesso a dado de criança).
- **Seção [10](10-professor-familia.md)** — os **papéis** de quem importa e o vínculo responsável↔aluno (o import **não** cria vínculo).
- **Seção [21](21-suporte-operacao.md)** — a **comunicação/agenda** do cutover à escola.
- **Apêndice B** — os **contratos formais** de formato de arquivo (colunas/layout) e dos endpoints de import.

**Alimenta:**
- **Seção [21](21-suporte-operacao.md)** — o onboarding operacional da escola usa o provisionamento/cutover da 20.
- **Apêndice B** — descreve o comportamento cujos contratos o Apêndice B normatiza.

**O que quebra se mudar:** se a Seção [11](11-arquitetura.md) mudar o **schema**, a 20 **reajusta** o ETL; se a
Seção [12](12-seguranca-privacidade.md) fechar a decisão de **erasure** (cascade × anonimização), a 20 **acopla** o
reprocessamento/undo e o backup; se a Seção [10](10-professor-familia.md) **habilitar** professor a importar, a 20
**estende** os papéis.

### 12. Casos extremos (Edge Cases)
- **Homônimos exatos** (dois "João Silva") → desempata pela **turma**; sem desempate vira **não-encontrado/novo** —
  nunca pontua o aluno errado (M5).
- **RA colide mas o nome contradiz** → **veto**: não casa por RA (M4).
- **Aluno em duas turmas sem RA** → **não** deduplica sozinho; **avisa** o gestor (M10).
- **Planilha parcial** (falta metade da turma) → grava só quem está; **não apaga** os ausentes (M10, ausência ≠ exclusão).
- **Mesmo período reimportado** → recalcula **sem** somar duas vezes (M8).
- **Arquivo inválido/PDF escaneado** → **recusa** com diagnóstico, **zero escrita** (M2/M10).
- **Import aplicado por engano** → hoje **não há undo** (▢ M9b): a correção é reprocessar/editar; quando o undo
  existir, ele **nunca** apaga ledger imutável (P14) nem cascateia `aluno→quest_perfis`/credencial/ledger (P6).
- **Aluno transferido/arquivado** → **"cartão descansando"**, nunca "código errado" (P6); para **fundir** uma
  duplicata arquivada, **reative-a antes** (FUNDIR só opera sobre **ativos** — M3).
- **Dado real de criança em teste** → **proibido fora de produção** (Seção [14](14-infra-deploy-dr.md) O18);
  usar fixtures **sintéticas/anonimizadas** — reconciliar com a suíte de nomes reais (§15).
- **Restore de backup destrói o Quest** ⛔ — o restore é **destrutivo** e, como apaga o aluno, **cascateia** e
  **aniquila todo o lado Quest** da escola (perfis, credenciais e o **ledger imutável** de progresso/tentativas), que
  o backup **nem contém** para repor. É **risco de invariante** (P14/P16/P6): antes de expor a operação, exigir guard
  técnico — incluir o Quest no export/restore **ou** o restore preservar/reprovisionar credenciais e **recusar
  cascatear** o ledger (§15).

### 13. Escalabilidade futura
- **Prévia confirmável + undo** (M9b) — a etapa formal de *diff* por linha e o desfazer de import aplicado.
- **Elefante XLSX** e **importador CSV dedicado** (hoje CSV cai no texto genérico) — ⚠️ §15.
- **OCR** de PDF escaneado — ⚠️ §15.
- **Combinação de dois ledgers Quest** (20.29) — hoje o *fundir-aluno* **migra** o perfil ou **descarta com contagem
  auditada** o do removido quando ambos têm perfil (P14 preservado: a duplicata some, o mantido conserva o seu
  ledger); **combinar** dois ledgers não-vazios num só **não existe** e P14 impede reescrever o ledger — **sempre
  manual**, coordenar com a Seção [11](11-arquitetura.md).
- **Provisionamento Quest em massa** com `escola_id` (20.25) — quando o gatilho for decidido.
- **Import de escola grande em lote** (20.33) — estratégia de lote/streaming da 20 sobre a **capacidade** da Seção [14](14-infra-deploy-dr.md).
- **Integração nativa com o software próprio futuro** (matérias+questões) — um `SnapshotEnsino` no padrão dos
  snapshots externos, se houver API — ⚠️ §15.

### 14. Checklist de implementação
**"Pronto quando" (liga ao Apêndice F). Itens ⚠️ dependem de decisão do dono (§15):**
- [x] **Duas etapas** `analisar`→`confirmar`; nada grava sem confirmar (M1).
- [x] **Detecção automática** + parsers posicionais/estratégias que competem; colunas por semelhança difusa (M2).
- [x] **Casar automático × fundir manual** (`"FUNDIR"`, irreversível) (M3).
- [x] **Precedência** RA→nome+turma→abreviação posicional, unicidade bipartida, vetos (M4).
- [x] **Regra de ouro** preferir o falso-negativo ao falso-positivo (novo + aviso na dúvida) (M5).
- [x] **POOL** abreviado-posicional (upload-sem-RA); Excel = fonte da verdade que **sobrescreve** todo casado (M6).
- [x] **Histórico preservado** ao casar; `Leitura` `UNIQUE`; ledger imutável (M7).
- [x] **Snapshots imutáveis/complementares**; período soma com piso anti-regressão (M8).
- [x] **Idempotência** — reimportar não duplica (chave natural/RA; `Leitura` `UNIQUE`; período com piso) (M9a).
- [ ] ▢ **Prévia confirmável linha a linha** + **rollback/undo** com guard P14/P6 (não apaga ledger, não cascateia) (M9b).
- [x] **Robustez / ausência ≠ exclusão**; recusa de PDF escaneado (M10).
- [x] **Provisionamento Quest** (perfil+credencial isolado por `escola_id`) via cartões da turma — ⚠️ **gatilho** em massa a decidir (M11).
- [x] **Credencial** — geração/unicidade `codigo_login`/`qr_token` (formato = identidade/onboarding; entropia = Seção [12](12-seguranca-privacidade.md)) (M12).
- [ ] ⚠️ **LGPD do import** — retenção/descarte do arquivo-fonte com PII (política a fixar na Seção [12](12-seguranca-privacidade.md)) (M13).
- [x] **Auditoria** `aluno.identidade_vinculada`/`matriculas.importadas` em `logs_auditoria` (operações = Seção [12](12-seguranca-privacidade.md); schema = Seção [11](11-arquitetura.md)) (M14).
- [x] **Papéis** só admin/coordenador; criança nunca em `usuarios` — ⚠️ habilitar professor a decidir (M15).
- [ ] ⚠️ **Portabilidade** por escola — o restore destrutivo **hoje apaga o Quest** (perfis/credenciais/ledger); decidir incluir/preservar o Quest + salvaguarda (M16).
- [ ] ⚠️ **Cutover da escola-piloto** — estratégia técnica + validação antes de expor crianças (M17).

### 15. Questões em aberto
Cada item é **decisão do dono** (⚠️); os defaults são **propostas** da 20, não decisões autônomas:

- ⚠️ **M11 — Gatilho do provisionamento Quest (20.25).** `quest_perfil` é criado **automaticamente** para todo aluno
  matriculado, ou **só** quando o professor gera os cartões / a criança entra pela 1ª vez? Hoje o código provisiona
  apenas no fluxo de cartões da turma. Proposta: criar sob demanda no 1º acesso, provisionar em massa opcional.
- ⚠️ **20.29 — Combinação de dois ledgers Quest.** Hoje o *fundir-aluno* já **migra** o perfil ou **descarta com
  contagem auditada** o do removido quando ambos têm perfil (P14 preservado). **Combinar** dois ledgers não-vazios
  num só é o que falta — e P14 **impede reescrever** o ledger. Proposta: **sempre manual**, "na dúvida não funde";
  regra de combinação coordenada com a Seção [11](11-arquitetura.md).
- ⚠️ **20.41 — Import de progresso pedagógico de terceiros.** O desempenho histórico do Matific/Elefante **entra**
  no Quest, ou o Quest **começa do zero** pedagogicamente? (No Edu os snapshots já entram; a questão é o **jogo**.)
- ⚠️ **20.40 — Integração com o software próprio futuro** (matérias+questões). Fonte única × import × espelho? Se
  houver API, cabe um `SnapshotEnsino` no padrão dos snapshots externos — decisão de produto do dono.
- ⚠️ **M17 / 20.39 — Cutover da escola-piloto.** Big-bang × por turma × período de coexistência Edu/Matific/Elefante,
  e como **validar antes** de expor as crianças. Faz ponte com a Seção [14](14-infra-deploy-dr.md) (janela/deploy) e a
  Seção [21](21-suporte-operacao.md) (comunicação).
- ⚠️ **M13 — Retenção do arquivo-fonte.** Por quanto tempo o **relatório** PDF/XLSX com PII de criança pode ficar em
  `/uploads` (hoje prévias expiram em 24 h; o confirmado é movido e persiste)? A Seção [12](12-seguranca-privacidade.md)
  ainda **não** tem esse item — **requer criar** uma política de retenção/descarte do arquivo-fonte de import (a 20 a aplica).
- ⚠️ **Erasure (cascade × anonimização).** A decisão aberta da Seção [12](12-seguranca-privacidade.md) §15 define se o
  reprocessamento/undo (M9b) e o **backup** (Seção [14](14-infra-deploy-dr.md) O19) **excluem** ou **anonimizam**. A 20
  **depende** dela; não a toma.
- ⚠️ **M16 — Restore destrói o Quest (risco de invariante).** O restore atual **não** é neutro ao Quest: ao apagar o
  aluno, **cascateia** e aniquila perfis, credenciais e o **ledger imutável** (P14/P16/P6), e o backup nem o contém
  para repor. Decidir **antes de operar**: (a) incluir o lado Quest no export/restore, **ou** (b) o restore
  preservar/reprovisionar credenciais e **recusar cascatear** o ledger; mais a **salvaguarda de UX** do restore
  destrutivo e o versionamento do formato (`VERSAO_BACKUP`) quando o schema evoluir. Articular com as Seções
  [12](12-seguranca-privacidade.md)/[14](14-infra-deploy-dr.md).
- ⚠️ **Novos formatos** — Elefante XLSX, importador CSV dedicado, OCR de PDF escaneado: expandir ou manter fora de escopo?
- ⚠️ **Papel de quem importa** — habilitar **professor** (ou família) a importar/casar (hoje só admin/coordenador) é
  decisão da Seção [10](10-professor-familia.md).
- ⚠️ **Tensão de teste (20.38).** Suíte com **nomes reais** da Lista Piloto (homônimos, nomes longos) **versus** a
  regra "nada de dado real de criança fora de produção" (Seção [14](14-infra-deploy-dr.md) O18) — fixtures
  sintéticas/anonimizadas ou exceção controlada de dev? Reconciliar.

### 16. ADR (Architecture Decision Record)
- **ADR-20-A — Casar é automático porque é reversível; fundir é manual porque não é.** CASAR troca o nome abreviado
  antigo pelo completo mantendo o **mesmo `aluno_id`**; **"reversível" aqui significa**: `aluno_id` preservado + o
  nome antigo persistido em `aluno.identidade_vinculada` (a reversão hoje é **edição manual**; a **ação** de undo é o
  trabalho ▢ do M9b), e por isso pode ser automático quando **inequívoco**. FUNDIR une dois `aluno_id` (irreversível),
  é **sempre** manual (`"FUNDIR"`) e só entre **ativos** (reative o arquivado antes). Já refletido em
  `matriculas.py`/`academico.py`.
- **ADR-20-B — Regra de ouro: custo(falso-positivo) ≫ custo(falso-negativo).** Na dúvida, o import **cria um
  cadastro novo e avisa** (prefere a duplicata ao renomeio errado), nunca renomeia/pontua a criança errada. Homônimo
  sem desempate por turma vira `não-encontrado`. A segurança da identidade vale mais que a conveniência de zero duplicatas.
- **ADR-20-C — Nada grava sem prévia; a identidade tem uma fonte da verdade.** O `analisar` **não grava** e devolve
  a prévia **read-only**; o **Excel da matrícula é a fonte da verdade da identidade** (o nome completo vence o
  abreviado). A garantia **"confirmar = exatamente a prévia"** (prévia **congelada** + revalidação server-side — hoje
  o `confirmar` de matrículas **re-analisa** contra o estado atual) e o **undo** de import aplicado são a evolução
  pendente (▢ M9b/§15).
- **ADR-20-D — A 20 é o ETL de dados; a 14 opera o schema/backup; a 11 desenha o modelo.** A Seção 20 decide a
  **estratégia e as regras** de importar/casar/provisionar/exportar **dados**; o **mecanismo de schema** (Alembic no
  deploy) e o **backup/DR** são da Seção [14](14-infra-deploy-dr.md); o **modelo/schema** é da Seção [11](11-arquitetura.md);
  a **política** LGPD é da Seção [12](12-seguranca-privacidade.md). A 20 **aplica** e **referencia**, não redefine.

*Decisões cross-módulo não são improvisadas aqui: as pendências acima viram ADR ou item de §15.*

---

## 🇬🇧 Data Migration & Import

### 1. Objective
To be the **definitive reference for how data enters, is recognized and is preserved** in Constela: importing
enrollments/classes/students and the external platform reports (Matific, Elefante Letrado) **without ever renaming
the wrong child, without losing history, and without writing anything before confirmation**. It decides the **ETL
strategy and rules**; it does **not** decide the **schema** (Section [11](11-arquitetura.md)), the **execution** of
schema migration/backup (Section [14](14-infra-deploy-dr.md)), the LGPD **policy** (Section [12](12-seguranca-privacidade.md))
nor the **roles** (Section [10](10-professor-familia.md)) — it only **applies** them. Formal contracts live in **Appendix B**.

### 2. Context
Constela is **Hub → Edu → Quest**. The child's identity **lives in the Edu core** (P16): Quest **derives** from it
(`quest_perfis`/`quest_credenciais_aluno`), never the other way around. **Current state (Q0) — most of the pipeline
already exists and works:**
- **4 entry paths** — (1) report **PDF**; (2) report **XLSX** (**Matific only**); (3) pasted **text/`.csv`/`.txt`**;
  (4) the **"Lista Piloto" enrollment** spreadsheet (`.xls`/`.xlsx`).
- **Real parsers** — `perfis_pdf.py` (**positional** reading via pdfplumber: Elefante class, Elefante individual,
  Matific stars); `importacao.py` (4 generic strategies that **compete**, the one recognizing more students wins);
  `planilhas.py` (Matific XLSX; **raises `ValueError` if ≠ matific** — Elefante XLSX is **not** supported);
  `lista_piloto.py` (enrollments, one tab per class, `.xls` via xlrd and `.xlsx` via openpyxl).
- **Automatic detection** — the user does **not** state the format: the platform is detected by keywords; columns
  match by **fuzzy similarity** (accents/case ignored, `SequenceMatcher ≥ 0.82`), never by exact name.
- **Matching** — report: `exact`/`probable`/`not-found` (probable **requires** human confirmation; a homonym is
  disambiguated by class, otherwise becomes `not-found` to **never score the wrong student**). Enrollments: the
  **pure** core `matriculas.py` — precedence **RA → exact name+class → positional abbreviation**, with **bipartite
  uniqueness** and **vetoes** (class overlap by grade+letter; divergent birth date); ambiguous → **create a new
  student + warning** to use *Merge students*.
- **MATCH × MERGE** — **MATCH** (swap the old abbreviated name for the full one keeping the **same `aluno_id`**) is
  **automatic** and reversible; **MERGE** (join two `aluno_id`) is **always manual** (`POST /alunos/fundir`, textual
  `"FUNDIR"` confirmation, irreversible).
- **2 stages** — `analyze` (preview, **writes nothing**) → `confirm` (writes **only the approved**).
- **Immutable, complementary snapshots** — `SnapshotMatific`/`SnapshotElefante` never overwritten; `Leitura` with
  `UNIQUE(aluno_id, livro_id)` (re-reading does **not** re-score); a per-period import **sums** into the accumulated
  total with an anti-regression floor.
- **Source file kept (report PDF/XLSX only)** — the report goes to `/uploads/temporarios` (TTL **24 h**) → moved to
  `/uploads/{platform}/` on confirmation (sanitized against path traversal). The **Lista Piloto** is **re-uploaded**
  on confirmation and **not** archived; **pasted text** creates no file.
- **Portability** — `backup.py` JSON export/restore **per school** (`VERSAO_BACKUP=1`, **destructive** restore in
  one transaction); the backup **contains no** users nor the Quest side, **but** the restore **deletes the student
  and, by cascade, destroys the school's entire Quest side** — profiles, credentials and the **immutable ledger** of
  progress/attempts — replacing nothing. It is an **invariant risk** (P14/P16/P6), handled in §12/§15, not a mere future decision.
- **Roles** — only `admin`/`coordenador` import; **teacher does not**.
- **Not yet present** — the **line-by-line confirmable preview** and the **undo import** as formal pipeline stages
  (today `confirm` writes directly; the **read-only** preview of `analyze` exists); **Elefante XLSX**; a **dedicated
  CSV** importer (CSV falls into generic text); **OCR** of scanned PDF (refused); **combining two non-empty Quest
  ledgers** (the Edu *merge-student* **already** migrates the Quest profile, or **discards with an audited count** the
  removed one when both have a profile; **combining** progress is what does not exist — P14 forbids rewriting the
  ledger); **mass Quest provisioning** at enrollment (today only in the class-cards flow).

This chapter **formalizes** the strategy, sets the golden rule, and records what remains to be decided.

### 3. Feature philosophy
**"A wrongly imported record becomes a child with a swapped name — that cannot happen."** Migration is where the
product touches the **real identity** of thousands of children, collected from schools still living in imperfect PDFs
and spreadsheets. Guiding principles: **nothing writes without confirmation** (the preview is sacred); **prefer the
false negative to the false positive** (better a duplicate — false negative, the manager merges later — than
renaming the wrong child — false positive; on doubt, **create new and warn**); **the Excel is the source of truth
for identity** (the enrollment's full name beats the
report's abbreviation); **matching is reversible, merging is not** (so matching can be automatic and merging is
always human); **absence ≠ deletion** (a spreadsheet that omits a student does **not** delete them); and **history
is untouchable** (matching preserves snapshots/readings/grades under the same `aluno_id`; Quest's ledger is immutable — P14).

Link to the **Immutable Principles** ([01](01-principios-imutaveis.md)): **P16** (identity in Edu) — the import
creates `quest_perfis`/credentials from the Edu student, **never** a row in `usuarios`; **P15** (isolation) — every
provisioning respects `escola_id`; **P13/P14** (server authority + immutable ledger) — a Quest profile merge cannot
rewrite the ledger; **P6** (error never punishes) — a transferred student is a **"resting card"**, never a "wrong
code" that blames the child.

### 4. The experience the player should feel
The child does **not** live the migration directly — they live the **result**: the card works on day one, the name
on screen is **their full name** (not "NINA M"), and the progress that already existed **is still there**. **The
manager** (admin/coordinator) feels **control and safety**: uploads the file, **sees the preview**, understands each
line (matched, probable, new), confirms, and receives a **report** of what came in. **The school** trusts because the
transition from Matific/Elefante to Constela **loses no one** and **does not scramble** the records it already kept.

### 5. Complete flow
The **canonical import pipeline** (⭐ = already exists in Q0; ▢ = decision/implementation to do):

1. **Upload/paste** ⭐ — the manager uploads PDF/XLSX or pastes text; the **report** goes to `/uploads/temporarios`
   (TTL 24 h); the **Lista Piloto** is read and re-uploaded on confirmation (not archived); **pasted text** creates no file.
2. **Detect + parse** ⭐ — the platform is recognized by keywords; the positional parser (or the 4 competing generic
   strategies) extracts the rows; a scanned/image PDF is **refused** with a diagnosis (no OCR).
3. **Normalize** ⭐ — names without accent/case/collapsed spaces; class key by **grade+letter** (ignoring "ano"/shift).
4. **Match** ⭐ — each row is classified: report → `exact`/`probable`/`not-found`; enrollments → RA > name+class >
   positional abbreviation, with bipartite uniqueness and vetoes; ambiguous → **new + warning**.
5. **Preview** — the **read-only** preview of `analyze` ⭐ shows what **will** happen per line, **without writing**;
   the formal **line-by-line confirmable preview** stage (with a *diff* + the *probable* marking that requires
   approval, **frozen** until `confirm`) is missing ▢.
6. **Apply (transactional, atomic)** — confirmation writes **only the approved** in a **single commit** (all in or
   nothing) ⭐; the Excel is the source of truth for identity (`existente.nome = parsed.nome`). *Today* the enrollment
   `confirm` **re-analyzes** the file against the current state (no frozen preview) and the report one trusts the rows
   returned; the **frozen preview + server-side re-validation** and the **rollback/undo** of an applied import are ▢ (M9b).
7. **Audit** ⭐ — writes `aluno.identidade_vinculada` (when the name changes) and `matriculas.importadas` (batch) to
   `logs_auditoria`; the report PDF/XLSX is moved to `/uploads/{platform}/`.
8. **Report** ⭐ — the manager receives the summary (imported, probable pending, new, warnings) and the history at
   `GET /importacoes`.

**Quest provisioning** (parallel flow): the **profile+credential generation** isolated by `escola_id` ⭐ **already
exists** (`credenciais.py`), today **only in the class-cards flow**; the **mass provisioning from the roster** and
the **trigger** (automatic at enrollment × only at card generation × only on first entry) are ▢/⚠️ (owner decision, §15/M11).

### 6. Interface (when it exists)
**The import UI** (drag-and-drop, preview screen, *Confirm* button, *Merge students* tool) belongs to **flow/UX**
(Sections [07](07-ux-fluxos-navegacao.md)/[08](08-onboarding-ftue.md)); Section 20 defines the **rule behind it**
(2 stages, nothing writes without confirming, *probable* requires approval, ambiguous becomes a warning). Surfaces:
the **per-line preview** (matched/probable/new + name *diff*), the **post-import report** and the import **history**.

### 7. UX
The "data UX" is the **adult manager's**: **preview before anything**, **clear per-line language** (what matched,
what is probable, what is new, and **why**), **actionable warnings** ("two records look like the same child — use
Merge students"), and, as a **target**, **zero surprise** — confirmation doing **exactly** what the preview showed
depends on the **frozen preview + server-side re-validation**, the ▢ evolution of M9b (today the enrollment `confirm`
re-analyzes against the current state). A file error (invalid, missing columns, encoding, unreadable PDF) →
**clear message + atomic write** (the import goes in whole or not at all).

### 8. Game Design
**N/A** — migration is an **adult** system, outside the child's game loop. Point of contact: provisioning creates the
**credential** the child logs in with (spoken `codigo_login`, `qr_token`) and the **profile** the game starts from;
**history preservation** ensures that already-collected pedagogical progress is not destroyed by matching.

### 9. Business rules
The **migration/import norms** (the source of the strategy; the **schema** is Section [11](11-arquitetura.md)'s, the
**execution** of schema migration/backup is Section [14](14-infra-deploy-dr.md)'s, the LGPD **policy** Section
[12](12-seguranca-privacidade.md)'s):

| # | Norm | Rule | Boundary |
|---|------|------|----------|
| M1 | **Two stages + atomic** | `analyze` (read-only preview, **writes nothing**) → `confirm` (writes only the approved in a **single commit**: all in or nothing); the preview is sacred | 20 |
| M2 | **No format declaration** | automatic platform detection (keywords) + positional parsers and 4 **competing** strategies (the one recognizing more students wins; tiebreak: summary before readings, then table→vertical→labels→positional — detail in Appendix B); columns by fuzzy similarity, never exact name | 20; contract = Appendix B |
| M3 | **Match × Merge** | **MATCH** (same `aluno_id`, abbreviated→full name) is **automatic and reversible**; **MERGE** (join two `aluno_id`) is **always manual** (`"FUNDIR"`, irreversible) and only between **active** students (archived/transferred: reactivate first) | 20 |
| M4 | **Matching precedence** | **RA → exact name+class → positional abbreviation**, only when **unambiguous** (bipartite uniqueness); RA reactivates a **soft-delete** (`status='excluido'`), with a **veto** if the name contradicts — **never** resurrects a record under **LGPD erasure** (creates new) | 20; erasure = [12](12-seguranca-privacidade.md) |
| M5 | **Golden rule** | **cost(false positive) ≫ cost(false negative)** — prefer the duplicate (false negative) to the wrong rename: on doubt **create a new student + warning** (review queue); **never** rename the wrong child nor score the wrong student | 20 |
| M6 | **POOL × source of truth** | the **POOL** for **abbreviated-positional** recognition = only upload records (Matific/Elefante/Leitura) **without RA** and with ≥2 tokens; **separately**, **every** matched record (by RA, name+class **or** abbreviation) has its name **overwritten** by the Excel's full name (identity's source of truth) | 20 |
| M7 | **History untouchable** | matching **preserves** snapshots/readings/grades/telemetry under the same `aluno_id`; `Leitura` is `UNIQUE(aluno_id,livro_id)` (re-reading doesn't re-score); the **Quest ledger is immutable** (P14) | 20; model = [11](11-arquitetura.md) + Appendix B (DDL) |
| M8 | **Immutable snapshots** | `SnapshotMatific`/`SnapshotElefante` never overwritten and **complementary**; a **per-period** import sums into the accumulated with an **anti-regression floor**; re-importing the same period does not sum twice | 20; model = [11](11-arquitetura.md) + Appendix B (DDL) |
| M9a | **Idempotence** ✅ | re-importing **does not duplicate** (natural key/RA; `Leitura` `UNIQUE`; period with floor) — **already exists** | 20 |
| M9b | **Confirmable preview + undo** ▢ | a **frozen** line-by-line confirmable preview (with *diff* + server-side re-validation) and **rollback/undo** of an applied import — **to build**; the undo **never** deletes the immutable ledger (P14) nor cascades `aluno→quest_perfis`/credential/ledger (P6) | 20 ▢ |
| M10 | **Robustness / absence ≠ deletion** | an illegible field becomes a **warning** (the line survives); a real error only when there is no name/no data; **a spreadsheet that omits a student does NOT delete them**; refuses scanned PDF (no OCR) | 20 |
| M11 | **Quest provisioning** | create `quest_perfis` + `quest_credenciais_aluno` from the roster, **isolated by `escola_id`** (the mechanism **already exists** via the class cards); the **trigger** (automatic × cards × first entry) and the **mass provisioning** are an owner decision | 20 ⚠️ (trigger — §15); schema = [11](11-arquitetura.md) |
| M12 | **Credential generation** | 20 **generates** unique `codigo_login`/`qr_token` (handling collisions); the **spoken format** (`PALAVRA+NNNN`) is **identity/onboarding** design and the **entropy/anti-enumeration** is Section [12](12-seguranca-privacidade.md)'s — not 20's | 20 (generation/uniqueness); format = onboarding/identity; entropy = [12](12-seguranca-privacidade.md) |
| M13 | **Import LGPD** | the **source file with PII** (only the report PDF/XLSX is archived; enrollment is re-uploaded; text creates no file) has restricted access, **minimal retention** and **disposal**; the **policy** (deadline/legal basis) must be set in Section [12](12-seguranca-privacidade.md) | 20 (applies); policy = [12](12-seguranca-privacidade.md) ⚠️ (create a retention item — §15) |
| M14 | **Migration audit** | every identity binding generates `aluno.identidade_vinculada` and the batch generates `matriculas.importadas`, written to `logs_auditoria`; **which operations** to audit = Section [12](12-seguranca-privacidade.md), **schema/delivery** of `logs_auditoria` = Section [11](11-arquitetura.md) | 20 (applies); operations = [12](12-seguranca-privacidade.md); schema = [11](11-arquitetura.md) |
| M15 | **Roles** | **only `admin`/`coordenador`** import/match; **teacher does not** (today); the **child never** enters `usuarios` (the import creates `quest_perfis`, not a user) | 20 (applies); roles = [10](10-professor-familia.md) ⚠️ (enable teacher — §15) |
| M16 | **Per-school portability** | the JSON export/restore **per `escola_id`** (format/scope/safeguard) is 20's; restore is **destructive** and **today cascade-deletes the school's entire Quest side** (profiles/credentials/immutable ledger) — including/preserving Quest is an owner decision; the **DB DR operation** (PITR) is Section [14](14-infra-deploy-dr.md)'s (distinct mechanism) | 20 (format/scope) ⚠️ (Quest — §15); LGPD policy = [12](12-seguranca-privacidade.md); DB DR = [14](14-infra-deploy-dr.md) |
| M17 | **Pilot-school cutover** | the **technical strategy** (big-bang × per class × coexistence) and the **validation before exposing children** are 20's; the **window/deploy** is Section [14](14-infra-deploy-dr.md)'s and the **communication/schedule** Section [21](21-suporte-operacao.md)'s | 20 (strategy) ⚠️ (§15); window/deploy = [14](14-infra-deploy-dr.md); communication = [21](21-suporte-operacao.md) |

### 10. Technical architecture
Where migration **touches** code (all real Q0, except ▢):
- **Parsers** — `perfis_pdf.py` (positional/pdfplumber), `importacao.py` (competing strategies), `planilhas.py`
  (Matific XLSX), `lista_piloto.py` (enrollments). Extraction contracts **anchored to the real example files** (base
  truth — no parser changes without validating against them).
- **Matching** — `matriculas.py` (**pure** core, no ORM: RA/name/positional abbreviation, bipartite uniqueness,
  vetoes) and `importacao.py::casar_nomes` (report).
- **Orchestration** — `importacoes.py` (`/analyze`→`/confirm` for reports and enrollments; keeps the file; writes the
  audit). **▢** the formal **line-by-line confirmable preview** stage and the **undo** are missing.
- **Provisioning** — `quest/services/credenciais.py` (`garantir_credencial_aluno`/`_turma`; spoken `codigo_login`,
  `qr_token`); `quest_perfis`/`quest_credenciais_aluno` models (schema = Section [11](11-arquitetura.md)).
- **Portability** — `backup.py` (per-school JSON export/restore) is **20's**; the restore is destructive and **today
  cascades over students, deleting Quest** (see §12/§15). The **DB DR operation** (snapshot/WAL/PITR) is Section
  [14](14-infra-deploy-dr.md)'s — a **distinct mechanism** from the JSON export.
- **Seed** — `scripts/seed.py` (idempotent base + demo); `seed_e2e.py` (deterministic). Idempotent **data** migration
  (not schema) at boot lives in `garantir_dados_base` (backfills), distinct from Alembic (Section [14](14-infra-deploy-dr.md)).

### 11. Dependencies on other modules
**Consumes / references:**
- **Section [11](11-arquitetura.md)** — the destination **model/schema** (students, classes, enrollments, snapshots,
  `quest_perfis`, `Leitura` with `UNIQUE` — detailed DDL in Appendix B), the Alembic design, the `escola_id`
  **tenancy**, the ledger's immutability and the **schema/delivery of `logs_auditoria`**.
- **Section [14](14-infra-deploy-dr.md)** — the **execution** of schema migration at deploy and the **infra
  backup/DR** (snapshot/WAL/PITR) as an operation (20 is the **data ETL** + the `backup.py` JSON export, it does not operate Alembic or PITR).
- **Section [12](12-seguranca-privacidade.md)** — the LGPD **policy** (minimal collection, consent, retention,
  anonymization, erasure, credential entropy) and **which operations generate `logs_auditoria`** (audit of access to child data).
- **Section [10](10-professor-familia.md)** — the **roles** of who imports and the guardian↔student binding (the import does **not** create a binding).
- **Section [21](21-suporte-operacao.md)** — the cutover **communication/schedule** to the school.
- **Appendix B** — the **formal contracts** of file format (columns/layout) and import endpoints.

**Feeds:**
- **Section [21](21-suporte-operacao.md)** — the school's operational onboarding uses 20's provisioning/cutover.
- **Appendix B** — describes the behavior whose contracts Appendix B normalizes.

**What breaks if it changes:** if Section [11](11-arquitetura.md) changes the **schema**, 20 **re-tunes** the ETL; if
Section [12](12-seguranca-privacidade.md) closes the **erasure** decision (cascade × anonymization), 20 **couples**
reprocessing/undo and backup; if Section [10](10-professor-familia.md) **enables** teachers to import, 20 **extends** roles.

### 12. Edge cases
- **Exact homonyms** (two "João Silva") → disambiguated by **class**; without a tiebreak becomes **not-found/new** —
  never scores the wrong student (M5).
- **RA collides but the name contradicts** → **veto**: does not match by RA (M4).
- **Student in two classes without RA** → does **not** dedupe alone; **warns** the manager (M10).
- **Partial spreadsheet** (half the class missing) → writes only who is there; does **not** delete the absent (M10, absence ≠ deletion).
- **Same period re-imported** → recomputes **without** summing twice (M8).
- **Invalid file/scanned PDF** → **refused** with a diagnosis, **zero write** (M2/M10).
- **Import applied by mistake** → today there is **no undo** (▢ M9b): the fix is to reprocess/edit; when the undo
  exists, it **never** deletes the immutable ledger (P14) nor cascades `aluno→quest_perfis`/credential/ledger (P6).
- **Transferred/archived student** → **"resting card"**, never a "wrong code" (P6); to **merge** an archived
  duplicate, **reactivate it first** (MERGE only operates on **active** — M3).
- **Real child data in a test** → **forbidden outside production** (Section [14](14-infra-deploy-dr.md) O18); use
  **synthetic/anonymized** fixtures — reconcile with the real-names suite (§15).
- **Backup restore destroys Quest** ⛔ — the restore is **destructive** and, by deleting the student, **cascades** and
  **annihilates the school's entire Quest side** (profiles, credentials and the **immutable ledger** of
  progress/attempts), which the backup **does not even contain** to restore. It is an **invariant risk** (P14/P16/P6):
  before exposing the operation, require a technical guard — include the Quest side in the export/restore **or** make
  the restore preserve/re-provision credentials and **refuse to cascade** the ledger (§15).

### 13. Future scalability
- **Confirmable preview + undo** (M9b) — the formal per-line *diff* stage and undoing an applied import.
- **Elefante XLSX** and a **dedicated CSV** importer (today CSV falls into generic text) — ⚠️ §15.
- **OCR** of scanned PDF — ⚠️ §15.
- **Combining two Quest ledgers** (20.29) — today the *merge-student* **migrates** the profile or **discards with an
  audited count** the removed one when both have a profile (P14 preserved: the duplicate is gone, the kept one keeps
  its ledger); **combining** two non-empty ledgers into one **does not exist** and P14 forbids rewriting the ledger —
  **always manual**, coordinate with Section [11](11-arquitetura.md).
- **Mass Quest provisioning** with `escola_id` (20.25) — once the trigger is decided.
- **Large-school batch import** (20.33) — 20's batch/streaming strategy over Section [14](14-infra-deploy-dr.md)'s **capacity**.
- **Native integration with the future own software** (subjects+questions) — a `SnapshotEnsino` in the external-snapshot pattern, if there is an API — ⚠️ §15.

### 14. Implementation checklist
**"Done when" (links to Appendix F). Items marked ⚠️ depend on an owner decision (§15):**
- [x] **Two stages** `analyze`→`confirm`; nothing writes without confirming (M1).
- [x] **Automatic detection** + positional parsers/competing strategies; columns by fuzzy similarity (M2).
- [x] **Match automatic × merge manual** (`"FUNDIR"`, irreversible) (M3).
- [x] **Precedence** RA→name+class→positional abbreviation, bipartite uniqueness, vetoes (M4).
- [x] **Golden rule** prefer the false negative to the false positive (new + warning on doubt) (M5).
- [x] **POOL** abbreviated-positional (upload-without-RA); Excel = source of truth that **overwrites** every matched (M6).
- [x] **History preserved** on match; `Leitura` `UNIQUE`; immutable ledger (M7).
- [x] **Immutable/complementary snapshots**; per-period sums with an anti-regression floor (M8).
- [x] **Idempotence** — re-importing does not duplicate (natural key/RA; `Leitura` `UNIQUE`; period with floor) (M9a).
- [ ] ▢ **Line-by-line confirmable preview** + **rollback/undo** with a P14/P6 guard (no ledger delete, no cascade) (M9b).
- [x] **Robustness / absence ≠ deletion**; refusal of scanned PDF (M10).
- [x] **Quest provisioning** (profile+credential isolated by `escola_id`) via the class cards — ⚠️ mass **trigger** to decide (M11).
- [x] **Credential** — generation/uniqueness `codigo_login`/`qr_token` (format = identity/onboarding; entropy = Section [12](12-seguranca-privacidade.md)) (M12).
- [ ] ⚠️ **Import LGPD** — retention/disposal of the source file with PII (policy to be set in Section [12](12-seguranca-privacidade.md)) (M13).
- [x] **Audit** `aluno.identidade_vinculada`/`matriculas.importadas` in `logs_auditoria` (operations = Section [12](12-seguranca-privacidade.md); schema = Section [11](11-arquitetura.md)) (M14).
- [x] **Roles** only admin/coordinator; child never in `usuarios` — ⚠️ enable teacher to decide (M15).
- [ ] ⚠️ **Portability** per school — the destructive restore **today deletes Quest** (profiles/credentials/ledger); decide to include/preserve Quest + safeguard (M16).
- [ ] ⚠️ **Pilot-school cutover** — technical strategy + validation before exposing children (M17).

### 15. Open questions
Each item is an **owner decision** (⚠️); the defaults are 20's **proposals**, not autonomous decisions:

- ⚠️ **M11 — Quest provisioning trigger (20.25).** Is `quest_perfil` created **automatically** for every enrolled
  student, or **only** when the teacher generates the cards / the child logs in for the first time? Today the code
  provisions only in the class-cards flow. Proposal: create on demand at first access, optional mass provisioning.
- ⚠️ **20.29 — Combining two Quest ledgers.** Today the *merge-student* already **migrates** the profile or
  **discards with an audited count** the removed one when both have a profile (P14 preserved). **Combining** two
  non-empty ledgers into one is what's missing — and P14 **forbids rewriting** the ledger. Proposal: **always
  manual**, "on doubt do not merge"; the combination rule coordinated with Section [11](11-arquitetura.md).
- ⚠️ **20.41 — Third-party pedagogical progress import.** Does the Matific/Elefante historical performance **enter**
  Quest, or does Quest **start from zero** pedagogically? (In Edu the snapshots already enter; the question is the **game**.)
- ⚠️ **20.40 — Integration with the future own software** (subjects+questions). Single source × import × mirror? If
  there is an API, a `SnapshotEnsino` in the external-snapshot pattern fits — an owner product decision.
- ⚠️ **M17 / 20.39 — Pilot-school cutover.** Big-bang × per class × Edu/Matific/Elefante coexistence period, and how
  to **validate before** exposing children. It bridges Section [14](14-infra-deploy-dr.md) (window/deploy) and Section
  [21](21-suporte-operacao.md) (communication).
- ⚠️ **M13 — Source-file retention.** How long may the **report** PDF/XLSX with child PII stay in `/uploads` (today
  previews expire in 24 h; the confirmed one is moved and persists)? Section [12](12-seguranca-privacidade.md) does
  **not** yet have this item — it **requires creating** a retention/disposal policy for the import source file (20 applies it).
- ⚠️ **Erasure (cascade × anonymization).** Section [12](12-seguranca-privacidade.md) §15's open decision determines
  whether reprocessing/undo (M9b) and the **backup** (Section [14](14-infra-deploy-dr.md) O19) **delete** or
  **anonymize**. 20 **depends** on it; it does not take it.
- ⚠️ **M16 — Restore destroys Quest (invariant risk).** The current restore is **not** neutral to Quest: by deleting
  the student, it **cascades** and annihilates profiles, credentials and the **immutable ledger** (P14/P16/P6), and
  the backup does not even contain them to restore. Decide **before operating**: (a) include the Quest side in the
  export/restore, **or** (b) make the restore preserve/re-provision credentials and **refuse to cascade** the ledger;
  plus the **UX safeguard** of the destructive restore and format versioning (`VERSAO_BACKUP`) as the schema evolves.
  Articulate with Sections [12](12-seguranca-privacidade.md)/[14](14-infra-deploy-dr.md).
- ⚠️ **New formats** — Elefante XLSX, a dedicated CSV importer, OCR of scanned PDF: expand or keep out of scope?
- ⚠️ **Who imports** — enabling the **teacher** (or family) to import/match (today only admin/coordinator) is a
  Section [10](10-professor-familia.md) decision.
- ⚠️ **Test tension (20.38).** A suite with **real names** from the Lista Piloto (homonyms, long names) **versus** the
  "no real child data outside production" rule (Section [14](14-infra-deploy-dr.md) O18) — synthetic/anonymized
  fixtures or a controlled dev exception? Reconcile.

### 16. ADR (Architecture Decision Record)
- **ADR-20-A — Matching is automatic because it is reversible; merging is manual because it is not.** MATCH swaps the
  old abbreviated name for the full one keeping the **same `aluno_id`**; **"reversible" here means**: `aluno_id`
  preserved + the old name persisted in `aluno.identidade_vinculada` (reversal today is a **manual edit**; the undo
  **action** is the ▢ work of M9b), so it can be automatic when **unambiguous**. MERGE joins two `aluno_id`
  (irreversible), is **always** manual (`"FUNDIR"`) and only between **active** students (reactivate an archived one
  first). Already reflected in `matriculas.py`/`academico.py`.
- **ADR-20-B — Golden rule: cost(false positive) ≫ cost(false negative).** On doubt, the import **creates a new
  record and warns** (prefers the duplicate to the wrong rename), never renames/scores the wrong child. A homonym
  without a class tiebreak becomes `not-found`. Identity safety outweighs the convenience of zero duplicates.
- **ADR-20-C — Nothing writes without a preview; identity has a source of truth.** `analyze` **writes nothing** and
  returns the **read-only** preview; the **enrollment Excel is the source of truth for identity** (the full name
  beats the abbreviation). The guarantee **"confirm = exactly the preview"** (a **frozen** preview + server-side
  re-validation — today the enrollment `confirm` **re-analyzes** against the current state) and the **undo** of an
  applied import are the pending evolution (▢ M9b/§15).
- **ADR-20-D — 20 is the data ETL; 14 operates schema/backup; 11 designs the model.** Section 20 decides the
  **strategy and rules** to import/match/provision/export **data**; the **schema mechanism** (Alembic at deploy) and
  **backup/DR** are Section [14](14-infra-deploy-dr.md)'s; the **model/schema** is Section [11](11-arquitetura.md)'s;
  the LGPD **policy** is Section [12](12-seguranca-privacidade.md)'s. 20 **applies** and **references**, it does not redefine.

*Cross-module decisions are not improvised here: the pending items above become an ADR or a §15 entry.*
