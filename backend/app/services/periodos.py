"""Resolução de PERÍODOS de análise.

Converte um preset ("hoje", "este bimestre"...) ou um intervalo personalizado
em (inicio, fim) — datetimes naive — para filtrar leituras, rankings e
estatísticas por qualquer janela de tempo (base das premiações por período).

`None` em qualquer extremo significa "sem limite" (todo o histórico).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

# Presets aceitos pela API (o frontend usa exatamente estas chaves).
PRESETS = (
    "hoje", "ontem", "7dias", "30dias", "mes", "mes_anterior",
    "bimestre", "bimestre_anterior", "semestre", "ano_letivo",
    "tudo", "personalizado",
)


def _ini(d: date) -> datetime:
    return datetime.combine(d, time.min)


def _fim(d: date) -> datetime:
    return datetime.combine(d, time(23, 59, 59, 999999))


def _primeiro(ano: int, mes: int) -> date:
    return date(ano, mes, 1)


def _ultimo(ano: int, mes: int) -> date:
    proximo = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)
    return proximo - timedelta(days=1)


def _rotulo_intervalo(inicio: date | None, fim: date | None) -> str:
    fmt = lambda d: d.strftime("%d/%m/%Y")  # noqa: E731
    if inicio and fim:
        return fmt(inicio) if inicio == fim else f"{fmt(inicio)} a {fmt(fim)}"
    if inicio:
        return f"a partir de {fmt(inicio)}"
    if fim:
        return f"até {fmt(fim)}"
    return "Todo o histórico"


def resolver(
    preset: str,
    hoje: date,
    ano_letivo: int,
    inicio: date | None = None,
    fim: date | None = None,
) -> tuple[datetime | None, datetime | None, str]:
    """(inicio_dt, fim_dt, rótulo). Datas None viram limite aberto."""
    preset = (preset or "tudo").lower()

    if preset == "personalizado":
        i = _ini(inicio) if inicio else None
        f = _fim(fim) if fim else None
        return i, f, _rotulo_intervalo(inicio, fim)

    if preset in ("tudo", ""):
        return None, None, "Todo o histórico"

    if preset == "hoje":
        return _ini(hoje), _fim(hoje), "Hoje"

    if preset == "ontem":
        o = hoje - timedelta(days=1)
        return _ini(o), _fim(o), "Ontem"

    if preset == "7dias":
        return _ini(hoje - timedelta(days=6)), _fim(hoje), "Últimos 7 dias"

    if preset == "30dias":
        return _ini(hoje - timedelta(days=29)), _fim(hoje), "Últimos 30 dias"

    if preset == "mes":
        return (_ini(_primeiro(hoje.year, hoje.month)),
                _fim(_ultimo(hoje.year, hoje.month)), "Este mês")

    if preset == "mes_anterior":
        ano, mes = (hoje.year - 1, 12) if hoje.month == 1 else (hoje.year, hoje.month - 1)
        return _ini(_primeiro(ano, mes)), _fim(_ultimo(ano, mes)), "Mês anterior"

    if preset in ("bimestre", "bimestre_anterior"):
        bim = (hoje.month - 1) // 2  # 0..5 (jan/fev=0, mar/abr=1, ...)
        ano = hoje.year
        if preset == "bimestre_anterior":
            if bim == 0:
                ano, bim = ano - 1, 5
            else:
                bim -= 1
        m1 = bim * 2 + 1
        rotulo = "Bimestre anterior" if preset == "bimestre_anterior" else "Este bimestre"
        return _ini(_primeiro(ano, m1)), _fim(_ultimo(ano, m1 + 1)), rotulo

    if preset == "semestre":
        m1, m2 = (1, 6) if hoje.month <= 6 else (7, 12)
        return (_ini(_primeiro(hoje.year, m1)),
                _fim(_ultimo(hoje.year, m2)), "Este semestre")

    if preset == "ano_letivo":
        return (_ini(date(ano_letivo, 1, 1)),
                _fim(date(ano_letivo, 12, 31)), f"Ano letivo {ano_letivo}")

    return None, None, "Todo o histórico"  # preset desconhecido: não filtra


def _parse_data(texto: str | None) -> date | None:
    if not texto:
        return None
    return date.fromisoformat(texto)  # aceita "AAAA-MM-DD"; ValueError se inválido
