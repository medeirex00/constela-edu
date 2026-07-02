# Arquitetura e Decisões Técnicas

## Visão geral

```
frontend (React/TS)  ──HTTP──▶  backend (FastAPI)  ──SQLAlchemy──▶  SQLite/PostgreSQL
                                     │
                                     ├─ app/core      config, banco, segurança, permissões
                                     ├─ app/models    entidades (tudo pertence a uma escola)
                                     ├─ app/schemas   contrato Pydantic da API
                                     ├─ app/routers   endpoints finos (validação + orquestração)
                                     └─ app/services  regra de negócio (scoring, auditoria)
```

Toda regra de negócio vive no backend; o frontend só apresenta e conversa com
a API (PRD §12). Rotas são finas; o motor de cálculo é um serviço puro e
testável isoladamente.

## Multi-tenant por `escola_id`

Cada tabela de dados carrega `escola_id` com chave estrangeira. Não existe
dado "do sistema": alunos, pesos, níveis, referências, notas e logs pertencem
a uma escola (PRD §10). A dependência `escola_autorizada` bloqueia acesso
cruzado; `is_global` marca o administrador que enxerga todas as escolas (§136).

## Nada hardcoded: tabela `configuracoes`

Pesos e critérios ficam em uma tabela chave-valor com coluna JSON
(`escola_id + namespace + chave`). O motor lê `pesos.matific`,
`pesos.elefante`, `pesos.questoes`, `pesos.geral` e `desempate.criterios`.
Os valores do PRD são apenas o seed inicial. A API rejeita pesos cuja soma
difere de 100% (§33) e, defensivamente, o motor ainda normaliza pela soma —
uma configuração corrompida jamais gera nota acima de 100.

## Histórico imutável via snapshots

`snapshots_matific` e `snapshots_elefante` nunca são sobrescritos (§68). O
"estado atual" é o snapshot mais recente por aluno; a evolução (Fase 3) será
a comparação entre snapshots — sem nenhuma mudança de schema. A tabela
`notas` é apenas cache do último cálculo, com `detalhes` JSON contendo o
passo a passo completo (§45).

## Dificuldade por série

`niveis_dificuldade` define os grupos (Pré-Leitor…Nível 5) e seus códigos
(AA…Z) com pontuação padrão; `dificuldade_turma` guarda apenas as exceções
por série. O motor resolve exceção → padrão → 0, então uma escola nova
funciona sem configurar nada e refina depois (§38–§39).

## Fonte dos pontos de dificuldade

O motor lê `livros_por_nivel` do snapshot do Elefante (contagem de livros
únicos por código). As tabelas `livros`/`leituras` alimentam o catálogo e a
restrição de leitura única (§35); na Fase 2 o importador registrará leituras
e derivará `livros_por_nivel` delas — como o seed já faz.

## Decisões que merecem registro

- **"Acertos" das questões** = quantidade de acertos normalizada pela
  referência (não o percentual). O percentual de acertos é usado no
  desempate, como pede o §42. Se os relatórios reais só trouxerem
  percentual, o importador da Fase 2 adapta sem tocar no motor.
- **Pesos do Ranking Geral (§41)** ficam em Configurações, não em Métricas —
  o §58 fixa Métricas em exatamente 4 módulos e proíbe adicionar outros.
- **Migração SQLite → PostgreSQL**: SQLAlchemy 2.0, tipos portáveis (JSON,
  DateTime, constraints nomeadas) e nenhuma query com SQL cru. Próximo passo
  na Fase 2: introduzir Alembic para versionar o schema.
- **Correção do toque no iPhone (§9)**: todos os elementos clicáveis são
  `<button>`/`<a>` reais (nunca `div` com onClick), com
  `touch-action: manipulation`, `-webkit-tap-highlight-color: transparent`
  e viewport correto. Nenhuma interação depende de `:hover`.
- **Datas em UTC** no banco; formatação pt-BR só na interface.

## Segurança (§24)

Senhas com bcrypt; JWT com expiração; ORM parametrizado (sem SQL injection);
CORS restrito às origens do frontend; validação Pydantic em toda entrada;
permissões conferidas por dependência em cada rota de escrita.
