# Assistente de IA — fluxo de dados, quem liga e o que sai

Lacuna A1 do crítico de completude do e97: o assistente nunca tinha passado por revisão. Este
documento descreve o que o código faz depois da correção (ramo `prontidao/e97m-ia`). Não é
parecer jurídico. Validação: local (SQLite e PostgreSQL 16 descartável, provedor externo
**falso**). Nada foi aplicado em produção, e o estado de produção não foi conferido aqui.

**Decisão técnica P9** (análoga ao D7, levada ao dono): ligar o provedor externo é exclusivo do
**Admin Global**. O admin da escola vê o estado e pode **desligar**. A pergunta ao dono é se a
IA externa entra no piloto. O padrão do código continua `local`, sem rede.

---

## 1. Onde está

| Peça | Arquivo |
|---|---|
| Rotas (perguntar, conversas, status, configuração, testar) | `backend/app/routers/ia.py` |
| Contexto, limpeza do que sai, conversa, retenção | `backend/app/services/assistente.py` |
| Provedores (`local`, `anthropic`, `openai`) | `backend/app/services/ia/` |
| Tela de configuração | `apps/web/src/components/ConfigAssistenteIA.tsx` (em Configurações) |
| Chat | `apps/web/src/pages/Assistente.tsx` |

## 2. Uma pergunta, passo a passo

1. **`POST /escolas/{id}/assistente`**: perguntam o admin, a coordenação e o Admin Global. O
   professor e a Secretaria levam 403 (`negar_dado_individual`), porque o contexto tem dado
   individual de criança.
2. **Contexto**: montado no backend por `montar_contexto`, só com a escola do caminho e só com
   alunos `ativo`. Leva:
   - o nome da escola e o ano letivo;
   - o ranking (15 primeiros) e os pódios do Matific e do Elefante (10 cada);
   - a evolução de 30 dias (10 primeiros);
   - os índices (engajamento, evolução, persistência) e os alertas;
   - as turmas (total, média, livros lidos);
   - a lista de todos os alunos com nota: nome, turma, posição e notas.
3. **Conversa**: as últimas 12 mensagens gravadas e a pergunta nova.
4. **Provedor**: o da configuração da escola (`configuracoes`, namespace `assistente`). Sem
   configuração própria, vale o do ambiente (`AI_PROVIDER`, `AI_API_KEY`, `AI_MODEL`).
   - `local` responde por regras no próprio backend. **Nada sai.**
   - `anthropic` usa o SDK oficial (Messages API).
   - `openai` faz `POST https://api.openai.com/v1/chat/completions`.
5. **O que sai no externo**: o corpo leva só `model`, `max_tokens`, as instruções com o contexto
   limpo (`system`; na OpenAI, a 1ª mensagem) e a conversa limpa (`messages`). A chave vai no
   cliente ou no cabeçalho `Authorization`. Não vai identificador de usuário nem nome ou e-mail
   de professor.
6. **Limpeza** (`_Pseudonimizador`), aplicada ao contexto e a toda a conversa, histórico
   incluído:

   | Dado | Vira | Onde |
   |---|---|---|
   | Nome completo de qualquer aluno da escola, de qualquer status, em qualquer caixa e com ou sem acento | `Aluno NNN` (token fixo) | contexto e conversa |
   | Pedaço de nome de aluno (só o primeiro nome, só um sobrenome) | `[nome omitido]` | conversa |
   | E-mail | `[e-mail omitido]` | contexto e conversa |
   | Número com 6 ou mais dígitos (RA, CPF, RG, telefone, CEP), inclusive colado a letra (`RA123456789`, `nº123456789-0`, `ra_123456789`, `123456789SP`). Datas ficam | `[identificador omitido]` | contexto e conversa |
   | RA/RM gravado na ficha do aluno (inclusive curto, a partir de 4 caracteres, e colado a letra: `RA4321`; com ou sem o DV `X`). RA/RM gravado com letra (`A1234`) é casado também pelos dígitos seguidos, a partir de 4 | `[identificador omitido]` | conversa |

   O número é delimitado por **dígito**, não por palavra: a letra, o `_` ou o `º` de `nº` encostados
   nele não impedem a troca. As letras em volta ficam (`RA[identificador omitido]`).

   No contexto, que o backend monta, o nome só aparece inteiro e não há ficha. Por isso ali não
   se troca pedaço de nome nem RA curto: estragaria os textos fixos ("há 12 dias", com um aluno
   de sobrenome Dias), as turmas e as contagens. O mapa de nomes inclui também quem tem nota ou
   matrícula na escola mas está com a ficha em outra.
7. **Resposta**: o token volta a ser o nome no backend (`_reidentificar`). A conversa fica
   gravada com os nomes reais em `conversas_ia` e `mensagens_ia`.
8. **Falha do externo** (chave errada, sem rede): responde o `local`, e a conversa registra
   `local (contingência)`.
9. **Auditoria**: `assistente.pergunta` (com o provedor) e `assistente.configurado` (provedor e
   `chave_alterada`; a chave nunca).

## 3. Quem faz o quê (P9)

| Ação | Admin Global | Admin da escola | Coordenação | Secretaria |
|---|---|---|---|---|
| Ver a configuração (`GET /config`, sem a chave) | sim | sim | não | não |
| Ver o provedor (`GET /status`) | sim | sim | sim | não |
| Desligar: salvar `local` sem chave (`PUT /config`) | sim | **sim** | não | não |
| Ligar ou reconfigurar `anthropic`/`openai`, modelo, chave (`PUT /config`) | sim | **não (403, nada gravado)** | não | não |
| Testar (`POST /config/testar`: texto fixo, sem dado de aluno) | sim | sim | não | não |

Outras regras:

- **Desligar descarta a chave** gravada. Religar exige o Admin Global com uma chave nova.
- **Ambiente**: `AI_PROVIDER` vale para a escola sem configuração própria e é decisão de quem
  opera o servidor. O admin da escola vê esse provedor e pode desligar o da escola dele.
- **Backup**: o export não leva a chave. A restauração não repõe a configuração do assistente
  (`PRESERVADAS_NA_RESTAURACAO` em `services/backup.py`), então um arquivo antigo não religa a IA.

## 4. Retenção

- **No Constela**: as conversas são apagadas depois de `IA_RETENCAO_DIAS` (padrão 90 dias), no
  boot e por `python -m scripts.purgar_ia` (`RETENCAO-TECNICA.md`). A exclusão permanente de um
  aluno apaga as conversas que citam o nome completo dele.
- **No provedor externo**: o prazo é o do contrato e dos termos da Anthropic ou da OpenAI, fora
  do controle do código. Precisa entrar no J2 (suboperadores, hoje sem esses dois) e no J6
  (termos).

## 5. O que a limpeza não pega

- **Sem NER**: o nome de quem não é aluno da escola (responsável, aluno de outra escola) não é
  reconhecido. Apelido e grafia errada também não.
- **Texto livre sensível** (situação de saúde ou familiar descrita na pergunta) sai como foi
  escrito.
- **Número partido por outro separador**: só `.`, `-` e `/` juntam os grupos de um número. Com
  espaço, vírgula ou outro sinal (`123 456 789`, `99876 5432`), cada grupo é avaliado sozinho e
  sai como foi escrito quando tem menos de 6 dígitos e não é RA/RM da ficha. Número com forma
  de data (`12/03/2026`, `12.34.5678`) também sai como foi escrito, mesmo que seja documento.
- **RA/RM da ficha** com menos de 4 caracteres, ou com letra e menos de 4 dígitos seguidos
  (`AB123`), não é reconhecido na conversa. O RA curto digitado com um DV numérico que a ficha
  não tem (`4321-5` para a ficha `4321`) também não.
- **Quase-identificadores**: o nome da escola, a turma, a posição e as notas saem. Quem conhece
  a escola pode reconhecer uma criança por eles. O provedor não tem a lista de alunos.
- **Precisão**: na conversa, um pedaço de nome que coincide com palavra comum ("dias", "Rosa")
  também é omitido. Para perguntar de um aluno, use o nome completo. O modo local tem o mesmo
  requisito.

## 6. Conferência em produção (OP-0, só contagem)

Quantas escolas têm provedor externo gravado (sem ler chave nem dado):

```sql
SELECT count(*) FROM configuracoes
 WHERE namespace = 'assistente' AND valor->>'provedor' IN ('anthropic', 'openai');
```

Confira também se `AI_PROVIDER` no ambiente é `local` ou está vazio.

## 7. Testes

| Teste | Cobre |
|---|---|
| `backend/tests/test_ia_provedor_externo_admin_global.py` (e `_pg`) | 403 ao admin da escola para ligar, reconfigurar ou gravar chave; desligar; herança do ambiente; coordenação |
| `backend/tests/test_ia_payload_externo.py` | provedor falso (Anthropic e OpenAI) capturando o corpo real, ponta a ponta e na 2ª pergunta com histórico (inclusive RA colado a letra: `RA000111222333-4`, `RA nº…`, `RA4321`); o limpador peça por peça |
| `backend/tests/test_ia.py` | contexto, cifra da chave, troca de provedor, contingência, retenção |
| `apps/web/src/test/ConfigAssistenteIA.test.tsx` | admin da escola vê, desliga e testa; Admin Global configura |
