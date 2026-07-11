"""Módulo de Sincronização Automática de Plataformas Educacionais.

Automatiza a OBTENÇÃO dos relatórios das plataformas externas e os entrega ao
pipeline de importação já existente. NÃO substitui o upload manual — ele
permanece como fallback (``ConectorManual``).

Camadas (desacopladas por interface):
    interfaces.py   — contrato ``Conector`` + DTOs (agnóstico de plataforma)
    vault.py        — cofre de credenciais cifradas (Fernet)
    connectors/     — implementações plugáveis (manual, matific, elefante, …)
    orchestrator.py — cola: conector → pipeline de importação existente
    scheduler.py    — fila/worker com retry, backoff, idempotência
    router.py       — API do painel administrativo

Adicionar uma plataforma nova = criar um conector em ``connectors/`` e
registrá-lo. Nada mais no sistema muda (Requisito de arquitetura).
"""
