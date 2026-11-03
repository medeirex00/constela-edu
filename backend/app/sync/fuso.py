"""Fuso da coleta — regra de negócio LOCAL (America/Sao_Paulo), armazenamento em UTC.

Por que existe: a agenda da escola diz "03:00" pensando no relógio de Brasília,
mas o cálculo da próxima execução trabalhava sobre o relógio UTC do servidor — a
coleta das "03:00" rodava às 03:00 UTC, isto é, à MEIA-NOITE em Brasília. O mesmo
deslize aparece em qualquer data de negócio tirada de um instante UTC: das 21h à
meia-noite (BRT) o UTC já está no dia seguinte.

A convenção do módulo de sincronização, daqui em diante:

* instantes GRAVADOS (``proxima_execucao``, ``iniciada_em``, ``finalizada_em``,
  ``data_referencia`` dos retratos) continuam em UTC *naive* — é o padrão de todo
  o banco (``models.base.agora`` / ``service._agora``);
* regras de negócio (horário da agenda, dia da semana, "hoje", dia de uma
  leitura) são decididas no fuso LOCAL abaixo e só então convertidas para UTC.

``ZoneInfo`` trata horário de verão se um dia voltar a existir. Sem a base de
fusos no sistema (imagem mínima sem ``tzdata``), cai no deslocamento fixo de
UTC-3 — o Brasil não tem horário de verão desde 2019, então o resultado é o mesmo
hoje — e avisa no log para a base ser instalada.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone, tzinfo

logger = logging.getLogger("constela.sync")

NOME_FUSO_LOCAL = "America/Sao_Paulo"


def _carregar_fuso() -> tzinfo:
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(NOME_FUSO_LOCAL)
    except Exception:  # noqa: BLE001 — ZoneInfoNotFoundError ou módulo ausente
        logger.warning(
            "Base de fusos indisponível (%s): usando UTC-3 fixo. Instale o pacote "
            "tzdata para o horário local acompanhar mudanças de regra.", NOME_FUSO_LOCAL)
        return timezone(timedelta(hours=-3))


FUSO_LOCAL: tzinfo = _carregar_fuso()


def _como_utc(instante: datetime) -> datetime:
    """Instante aware em UTC. Naive é assumido como UTC (o padrão do banco)."""
    if instante.tzinfo is None:
        return instante.replace(tzinfo=timezone.utc)
    return instante.astimezone(timezone.utc)


def para_local(instante: datetime) -> datetime:
    """Instante (naive = UTC) → aware no fuso local."""
    return _como_utc(instante).astimezone(FUSO_LOCAL)


def local_para_utc_naive(local: datetime) -> datetime:
    """Horário de PAREDE local (naive, ou aware em qualquer fuso) → UTC naive, o
    formato em que o banco guarda instantes."""
    if local.tzinfo is None:
        local = local.replace(tzinfo=FUSO_LOCAL)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def hoje_local(agora: datetime | None = None) -> date:
    """A data de hoje no fuso local (``agora`` naive = UTC; omitido = relógio)."""
    return para_local(agora or datetime.now(timezone.utc)).date()


def instante_para_horario_local(texto) -> tuple[str, bool]:
    """Normaliza a data/hora que uma PLATAFORMA informou para o horário de parede
    local, em ISO sem fuso — a convenção de ``Leitura.data`` (o relatório
    individual do upload manual traz o horário de Brasília, sem fuso).

    Devolve ``(texto_normalizado, tinha_fuso)``. Sem fuso explícito o texto sai
    INTACTO (já é o horário local: o pedido ao Elefante vai com
    ``timezoneOffset=180``). Com fuso (``Z`` / ``+00:00`` / ``-03:00``) o instante
    é convertido para o local — sem isto, ``2026-09-30T01:30:00Z`` (22h30 de 29/09
    em Brasília) entraria como leitura do dia 30. Texto que não é ISO sai intacto
    (o importador tem os formatos brasileiros)."""
    bruto = str(texto if texto is not None else "").strip()
    if not bruto:
        return bruto, False
    try:
        instante = datetime.fromisoformat(bruto.replace("Z", "+00:00"))
    except ValueError:
        return bruto, False
    if instante.tzinfo is None:
        return bruto, False
    local = instante.astimezone(FUSO_LOCAL).replace(tzinfo=None)
    return local.isoformat(), True
