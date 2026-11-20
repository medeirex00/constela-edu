# Decisão de arquitetura — retirada da Nota Geral legada

Registrada em 20/11/2026. A Leitura usa os dados do Elefante Letrado. A Matemática usa os dados do Matific. Cada matéria tem sua nota, sua posição e sua população aferida. Sem retrato da plataforma, a nota aparece como `—`. Um retrato válido com valor zero aparece como `0,0`.

O banco ainda grava `Nota.nota_geral` e `Nota.posicao` para atender consumidores legados. Rankings, premiações e certificados oficiais por matéria seguem o desempenho da própria dimensão. A ordem única de vitrines explicitamente legadas continua catalogada no inventário de testes.

## Sequência da retirada

| Etapa | Condição para avançar |
| --- | --- |
| 1. Proteger a regra oficial | Manter os testes que embaralham o legado e conferem que o desempenho por matéria fica idêntico. |
| 2–3. Migrar web e contratos | Usar `dimensoes[]` nos perfis e os campos da própria dimensão nos rankings. Tratar a retirada visual de uma vitrine como decisão de produto. |
| 4–6. Rever exportações | Conferir as fontes dos certificados, cartazes e arquivos de cada matéria. Manter os consumidores legados restantes explícitos no inventário. |
| 7. Decidir o Top 10 do painel | A vitrine atual usa a ordem única. Aprovar o desenho por matéria e o impacto na classificação antes de trocar o critério. Atualizar o teste de contrato junto com a troca. |
| 8–10. Migrar consumidores de integração | Identificar quem ainda recebe e lê os campos legados. Testar a API com clientes em uso e as exportações com dados sintéticos. |
| 11. Migrar o app instalado | Confirmar por versão de cliente e de API que as versões em uso suportam a retirada do campo. Aceitar a ficha, o painel, o ranking e os dados em cache no app antes de retirar compatibilidade. Essa é a evidência chamada de Sensor 4 no inventário. |
| 12. Parar de gravar e remover | Parar a escrita quando nenhum consumidor funcional restar e a volta para a versão anterior tiver sido ensaiada. Esse é o Gatilho 1 no inventário. A remoção física das colunas fica para uma migração posterior. |

## Ficha do aluno no app

Desde 09/11/2026, a tela delega a apresentação das notas a `apps/mobile/src/notasDoPerfil.ts`. Essa função usa `dimensoes[].aferido` para distinguir ausência de zero, indica quais detalhamentos exibir e mostra `—` na Nota Geral se nenhuma matéria foi aferida. Servidores antigos que ainda omitem `dimensoes` continuam aceitos. A mudança isolou a apresentação. A retirada do campo da ficha depende da etapa 11.

O inventário e as travas estão em [test_legado_nota_geral.py](../backend/tests/test_legado_nota_geral.py). Os casos de apresentação estão em [notasDoPerfil.test.ts](../apps/mobile/src/test/notasDoPerfil.test.ts) e [PerfilAlunoDimensoes.test.tsx](../apps/web/src/test/PerfilAlunoDimensoes.test.tsx).
