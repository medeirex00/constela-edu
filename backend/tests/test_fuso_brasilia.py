"""Fuso de Brasília (auditoria A3/M11): 'hoje', janelas de período e a data do
certificado seguem America/Sao_Paulo, não a data UTC do contêiner."""
from datetime import date, datetime, timezone

from app.core import tempo


def test_para_br_atravessa_a_meia_noite():
    # 01:30 UTC de 01/08 = 22:30 (BRT) de 31/07 → em Brasília ainda é 31 de julho
    # (mês 7, bimestre 4). Sem a correção, 'hoje'/mês/bimestre seriam de agosto.
    utc = datetime(2026, 8, 1, 1, 30, tzinfo=timezone.utc)
    br = tempo.para_br(utc)
    assert br.date() == date(2026, 7, 31)
    assert br.month == 7          # define mês e bimestre do certificado

    # Um instante naive é assumido como UTC (padrão dos timestamps gravados).
    assert tempo.para_br(datetime(2026, 8, 1, 1, 30)).date() == date(2026, 7, 31)


def test_hoje_e_agora_br_consistentes():
    assert tempo.hoje_br() == tempo.agora_br().date()
    # O offset é o de Brasília (UTC-3), não UTC.
    assert tempo.agora_br().utcoffset().total_seconds() == -3 * 3600
