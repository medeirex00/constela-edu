# Status da escola e da rede (`ativa` / `inativa`): o que faz hoje e o que falta decidir

Revisão de prontidão e97, dimensão autorização, achado 3. O documento registra o
comportamento do código e a decisão que ainda é do dono. **Nenhuma revogação de acesso
foi implementada.**

## 1. Como é hoje

`Escola.status` e `Rede.status` funcionam como **bandeira de listagem e de vitrine**.
Não revogam acesso.

| Onde o status é olhado | Efeito de `inativa` |
|---|---|
| `GET /escolas` (seletor de escola) | a escola some da lista; o admin global pode pedir `incluir_inativas` |
| `GET /redes` | a rede some da lista |
| painel público da escola (`/publico/{token}/...`) | 404 |
| vitrine pública da rede (`services/rede.py`) | a escola inativa não entra |

O status **não** é olhado nestes pontos:

- `deps.escola_autorizada` e `deps.exigir_rede`;
- o login.

Por isso, quem já é usuário de uma escola ou rede inativa continua lendo e gravando os
dados dela pelas rotas `/escolas/{id}/...` e `/redes/{id}/...`.

O interruptor de acesso que **funciona** é o do usuário: `Usuario.status != "ativo"`
leva a 401 em `get_usuario_atual`, inclusive para sessões já abertas.

## 2. O que mudou na e97

- `PATCH /escolas/{id}` só aceita **mudança** de `status` do Admin Global. Para os
  demais, a resposta é 403 "Só o administrador global ativa ou inativa escolas", a mesma
  régua do `ano_letivo_ativo`. Mandar o status que a escola já tem continua aceito,
  porque alguns clientes reenviam o objeto inteiro. Antes, o admin local desfazia pela
  API a inativação feita pelo global e conseguia inativar a própria escola, embora a
  tela de (des)ativar (Escolas) seja só do global.
- No mesmo PATCH, `nome` passa por `strip` e precisa ter de 2 a 200 caracteres, o mesmo
  limite do cadastro. Fora disso, a resposta é 422. Antes, o PATCH gravava nome vazio
  ou só com espaços, e um `null` estourava a coluna. **Unicidade de nome não é exigida
  na edição.** Só o cadastro (`POST /escolas`) tem essa regra, com 409 sem diferenciar
  maiúsculas. Estender a regra ao rename é decisão do dono.

## 3. Decisão pendente do dono

Pergunta: "inativa" deve significar **desligar o acesso**, por exemplo no fim de
contrato?

Se **sim**, a implementação sugerida é esta:

1. Em `escola_autorizada`: com `Escola.status == "inativa"`, responder 403 "escola
   desativada" a todos, menos o Admin Global. Para escola com `rede_id`, fazer o mesmo
   com `Rede.status == "inativa"`.
2. Em `exigir_rede`: aplicar a mesma regra com `Rede.status`.
3. No login, opcionalmente, recusar o usuário cuja escola ou rede esteja inativa, com
   uma mensagem própria.
4. Regressões: com escola ou rede inativa, `GET /escolas/{id}/alunos` e
   `GET /redes/{id}/dashboard` respondem 403 ao usuário não global e 200 ao global.

Impacto a pesar: telas que hoje abrem para quem está numa escola inativa passam a
responder 403. O Quest dos alunos e o app móvel também precisam de uma mensagem para
esse caso.

Se **não**, o significado atual (listagem e vitrine) fica documentado aqui e no modelo.

## 4. Procedimento de fim de contrato até a decisão

**Inativar os usuários** da escola ou da rede (`Usuario.status`). Esse interruptor já é
aplicado a cada requisição. Inativar só a escola ou a rede **não** corta o acesso de
quem já tem conta.
