"""Relógio de Brasília (fuso da escola) — fonte ÚNICA do "agora/hoje no Brasil".

O contêiner roda em UTC e os timestamps são GRAVADOS em UTC (models.base.agora).
Mas "hoje", "este mês/bimestre" e a data IMPRESSA no certificado são conceitos
do fuso da escola (America/Sao_Paulo): usar a data UTC desloca a janela em ~3h —
das 21h à meia-noite (BRT) o UTC já virou o dia (e, nas fronteiras, o mês e o
bimestre) seguinte, gerando ranking vazio à noite e premiação/certificado do
período errado.

Brasil sem horário de verão desde 2019 → UTC-3 FIXO (mesmo pressuposto do
aovivo.py). Se o DST voltar, trocar ``FUSO_BR`` por ``ZoneInfo("America/Sao_Paulo")``.

⚠️ Só para EXIBIÇÃO/DECISÃO (janela de período, data do certificado). Para
GRAVAR timestamp continue usando UTC (``models.base.agora``).
"""
from datetime import date, datetime, timedelta, timezone

FUSO_BR = timezone(timedelta(hours=-3))


def para_br(instante_utc: datetime) -> datetime:
    """Converte um instante em Brasília. Naive é assumido como UTC (padrão dos
    timestamps gravados) — testável com um instante fixo."""
    if instante_utc.tzinfo is None:
        instante_utc = instante_utc.replace(tzinfo=timezone.utc)
    return instante_utc.astimezone(FUSO_BR)


def agora_br() -> datetime:
    """Instante atual no fuso de Brasília (aware)."""
    return datetime.now(FUSO_BR)


def hoje_br() -> date:
    """Data de hoje no fuso de Brasília — base dos presets de período."""
    return datetime.now(FUSO_BR).date()
