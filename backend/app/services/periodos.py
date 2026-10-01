"""Resolução de PERÍODOS de análise.

Converte um preset ("hoje", "este bimestre"...) ou um intervalo personalizado
em (inicio, fim) — datetimes naive — para filtrar leituras, rankings e
estatísticas por qualquer janela de tempo (base das premiações por período).

`None` em qualquer extremo significa "sem limite" (todo o histórico).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from app.services import bimestres

# Presets aceitos pela API (o frontend usa exatamente estas chaves).
PRESETS = (
    "hoje", "semana", "semana_anterior", "ontem", "7dias", "30dias", "mes",
    "mes_anterior", "bimestre", "bimestre_anterior", "semestre", "ano_letivo",
    "tudo", "personalizado",
    # Bimestre NOMEADO do calendário oficial. Premiar "o 3º bimestre" não pode
    # depender de que dia é hoje: "bimestre" vira o 4º em 05/10 e o pódio troca
    # de criança sozinho. Quem entrega um prêmio escolhe o número.
    "bimestre_1", "bimestre_2", "bimestre_3", "bimestre_4",
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


def _bimestre_legado(numero_par: int, ano: int, rotulo: str):
    """Bimestre de CALENDÁRIO (jan/fev, mar/abr, ...) — a conta antiga, usada só
    em ano sem calendário oficial cadastrado em :mod:`app.services.bimestres`.
    Aproximada por construção; existe para 2027 não quebrar antes de alguém
    cadastrar as datas."""
    m1 = numero_par * 2 + 1
    return _ini(_primeiro(ano, m1)), _fim(_ultimo(ano, m1 + 1)), rotulo


def _bimestre(preset: str, hoje: date):
    """Os presets de bimestre, pelo calendário OFICIAL da rede.

    Antes daqui, "este bimestre" era ``(mês-1)//2`` — o bimestre do CALENDÁRIO,
    não o da escola. Em 01/10/2026 isso devolvia 01/09–31/10 enquanto o 3º
    bimestre oficial é 24/07–04/10: 61 dias contra 73, com só 34 em comum. Medido
    na rede no dia em que isto foi escrito, o pódio de "Mais Livros Lidos"
    coroava uma criança DIFERENTE em 4 das 5 escolas da Lista Piloto. É por isso
    que a janela passa a vir de uma fonte só.

    ``bimestre_1``…``bimestre_4`` são o jeito certo de premiar: o número é
    explícito e não muda quando o dia virar. ``bimestre`` ("este") continua
    existindo para as telas de acompanhamento, e em 05/10 ele passa a ser o 4º
    porque é isso que o calendário diz — quem vai entregar um prêmio do 3º
    escolhe ``bimestre_3``.
    """
    pedido = preset.rsplit("_", 1)[-1]
    if pedido.isdigit():
        numero, ano = int(pedido), hoje.year
        if not (1 <= numero <= 4):
            return None, None, "Todo o histórico"
        if not bimestres.ano_com_calendario(ano):
            # Inverso do mapa legado por mês (1–4→1º, 5–7→2º, 8–9→3º, 10–12→4º).
            meses = [m for m in range(1, 13) if bimestres.por_mes_legado(m) == numero]
            return (_ini(_primeiro(ano, meses[0])), _fim(_ultimo(ano, meses[-1])),
                    bimestres.rotulo(numero))
    else:
        ano = hoje.year
        if not bimestres.ano_com_calendario(ano):
            # Sem calendário oficial: a conta antiga, com o rótulo antigo.
            bim = (hoje.month - 1) // 2
            if preset == "bimestre_anterior":
                if bim == 0:
                    return _bimestre_legado(5, ano - 1, "Bimestre anterior")
                bim -= 1
            return _bimestre_legado(
                bim, ano,
                "Bimestre anterior" if preset == "bimestre_anterior" else "Este bimestre")
        numero = bimestres.bimestre_sugerido(hoje)
        if preset == "bimestre_anterior":
            if numero == 1:
                # O 4º do ano passado. Sem calendário dele, cai no legado.
                if bimestres.ano_com_calendario(ano - 1):
                    ano, numero = ano - 1, 4
                else:
                    return _bimestre_legado(5, ano - 1, "Bimestre anterior")
            else:
                numero -= 1
    inicio, fim = bimestres.intervalo(numero, ano)
    return _ini(inicio), _fim(fim), (f"{bimestres.rotulo(numero)} "
                                    f"({inicio:%d/%m} a {fim:%d/%m})")


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

    if preset == "semana":
        # Semana atual: segunda-feira até hoje (weekday(): 0 = segunda).
        return _ini(hoje - timedelta(days=hoje.weekday())), _fim(hoje), "Esta semana"

    if preset in ("semana_anterior", "semana_passada"):
        # Semana passada COMPLETA: segunda a domingo anteriores à semana atual.
        domingo = hoje - timedelta(days=hoje.weekday() + 1)
        return _ini(domingo - timedelta(days=6)), _fim(domingo), "Semana passada"

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

    if preset.startswith("bimestre"):
        return _bimestre(preset, hoje)

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
