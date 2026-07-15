"""Motor de Pontuação genérico do Constela.

O motor NUNCA conhece plataforma (Elefante/Matific/Quest): trabalha apenas com
INDICADORES. Adicionar uma plataforma no futuro = escrever o coletor + cadastrar
os indicadores no catálogo. A lógica do motor não muda.

Camadas (todas plugáveis, independentes):
  * catalogo    — o que é POSSÍVEL medir (indicadores declarativos, em código).
  * normalizacao — COMO comparar (registro de métodos: percentil, meta, média…).
  * (motor)     — costura tudo: valor bruto → normaliza → pondera → soma.

Esta é a base definitiva: método/indicador novo entra por dado, não por `if`.
"""
