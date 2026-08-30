# Recálculo institucional — procedimento pós-deploy

Contexto: a migração `0028_nota_institucional` acrescenta as colunas
`nota_elefante_institucional` e `nota_matific_institucional` em `notas`, com
**default 0.0 e sem backfill** (aditiva, deploy sem efeito colateral). Enquanto
uma escola não é recalculada, a rede lê `0` para ela — nunca um número
contaminado, mas também ainda não a nota institucional real.

Este procedimento roda **uma vez, depois do deploy e da migração**, e preenche
as colunas institucionais de todas as escolas.

## Pré-requisitos

1. Deploy do código já concluído (o novo `scoring.recalcular_escola` grava as
   colunas institucionais).
2. Migração aplicada até `0028_nota_institucional` (o entrypoint do container já
   roda `python -m scripts.migrate`; confirmar com `alembic current`).
3. Janela de baixo tráfego recomendada (cada escola pega um lock transacional
   curto; importações concorrentes apenas esperam, não corrompem).

## Passo a passo

```bash
# 1. (opcional) conferir quantas escolas serão recalculadas, sem gravar nada
python -m scripts.recalcular_institucional --dry-run

# 2. recalcular TODAS as escolas (preenche nota_*_institucional + regrava locais)
python -m scripts.recalcular_institucional

# variações, se precisar fatiar a carga:
python -m scripts.recalcular_institucional --rede 3     # só a rede 3
python -m scripts.recalcular_institucional --escola 42  # só a escola 42
```

O script imprime o progresso escola a escola e um resumo final
(`escolas processadas`, `alunos recalculados`, `falhas`). Sai com código `1` se
houve qualquer falha — reexecutar é seguro (idempotente).

## Garantias

- **Idempotente**: `recalcular_escola` é determinístico e sobrescreve as linhas
  de `notas`. Rodar duas vezes dá o mesmo resultado.
- **Isolado por escola**: cada escola tem seu próprio commit. Uma escola com
  dado corrompido vira uma linha de "falha" no resumo e **não** impede as demais.
- **Sem passo de rede**: a nota institucional é derivada por escola; a rede só
  agrega o que já está gravado. Não há recálculo "de rede" a fazer.

## Efeito colateral esperado (comunicar às escolas)

Como *Padrão Constela = régua institucional*, toda escola que ainda **não**
escolheu "Personalizado" passa a pontuar internamente pela régua **A3** neste
recálculo (deixa de usar a régua histórica de 6 faixas semeada). Escolas que
querem manter uma régua própria devem ativar **Personalizado** em
Configurações → Métricas → *Régua de pontuação da escola* **antes** do recálculo
(ou depois — o recálculo é reexecutável).

## Verificação pós-recálculo

```sql
-- Nenhuma escola com dado de Elefante deve ficar com institucional zerado:
SELECT escola_id, COUNT(*) AS notas_zeradas
FROM notas n
WHERE n.nota_elefante > 0 AND n.nota_elefante_institucional = 0
GROUP BY escola_id;   -- esperado: 0 linhas
```
