"""Calendário oficial dos bimestres — fonte ÚNICA das datas.

Por que este módulo existe: até aqui o bimestre do certificado saía de
``_bimestre_por_mes(mês do relógio)``, um mapa de MESES inteiros. Isso erra na
virada, que é o único momento em que a pergunta importa: pelo calendário real da
Rede Estadual de SP, o 3º bimestre de 2026 vai até **04/10**, mas o mapa por mês
já dava 4 no dia 01/10. Quem entregasse certificados na primeira semana de
outubro imprimiria "4º bimestre" num documento sobre o trabalho do 3º.

As datas são do calendário 2026 e estão aqui como CONSTANTE, não no banco: a
tabela de calendário que existiria para isso (``cur_bimestre_periodos``) ainda
não está publicada. Quando estiver, este módulo vira a camada que a lê — os
chamadores não mudam.

Fuso: tudo aqui é ``date``, nunca ``datetime``. A conversão de "agora" para data
local é feita UMA vez, por quem chama, com ``agora_br().date()``. Comparar datas
puras remove a classe inteira de erro de borda em 22/04→23/04 e 04/10→05/10 —
não existe instante ambíguo quando não há hora.
"""
from __future__ import annotations

from datetime import date

# Rede Estadual de SP, 2026. Início e fim INCLUSIVOS.
PERIODOS: dict[int, dict[int, tuple[date, date]]] = {
    2026: {
        1: (date(2026, 2, 2), date(2026, 4, 22)),
        2: (date(2026, 4, 23), date(2026, 7, 23)),
        3: (date(2026, 7, 24), date(2026, 10, 4)),
        4: (date(2026, 10, 5), date(2026, 12, 31)),
    },
}

BIMESTRES = (1, 2, 3, 4)


def ano_com_calendario(ano: int) -> bool:
    """O ano tem calendário oficial cadastrado?"""
    return ano in PERIODOS


def intervalo(bimestre: int, ano: int = 2026) -> tuple[date, date]:
    """Datas de início e fim (inclusivas) do bimestre.

    >>> intervalo(3)
    (datetime.date(2026, 7, 24), datetime.date(2026, 10, 4))
    """
    if bimestre not in BIMESTRES:
        raise ValueError(f"bimestre fora da faixa 1–4: {bimestre!r}")
    if ano not in PERIODOS:
        raise ValueError(f"não há calendário oficial cadastrado para {ano}")
    return PERIODOS[ano][bimestre]


def bimestre_da_data(dia: date) -> int | None:
    """Em qual bimestre esta data cai — ``None`` se cair FORA dos quatro.

    O recesso de janeiro (01/01 a 01/02 de 2026) não pertence a bimestre nenhum,
    e este módulo não finge que pertence: quem precisa de um número sempre usa
    :func:`bimestre_sugerido`, que trata o recesso explicitamente.
    """
    calendario = PERIODOS.get(dia.year)
    if not calendario:
        return None
    for numero in BIMESTRES:
        inicio, fim = calendario[numero]
        if inicio <= dia <= fim:
            return numero
    return None


def bimestre_sugerido(dia: date) -> int:
    """O número que a tela abre selecionado. SEMPRE devolve 1–4.

    É só uma SUGESTÃO: quem emite pode escolher qualquer um dos quatro, e a
    escolha dele manda. Regras das bordas, explícitas para não virarem surpresa:

    * dentro de um bimestre → ele mesmo;
    * recesso ANTES do início do ano letivo (janeiro) → 1º, porque o próximo
      período a ser avaliado é o 1º — e não o 4º do ano anterior, que já foi
      entregue;
    * ano sem calendário cadastrado → cai no mapa por mês legado
      (:func:`por_mes_legado`), que é aproximado mas nunca levanta erro. Cadastrar o
      calendário do ano novo em :data:`PERIODOS` resolve.
    """
    exato = bimestre_da_data(dia)
    if exato is not None:
        return exato
    calendario = PERIODOS.get(dia.year)
    if not calendario:
        return por_mes_legado(dia.month)
    if dia < calendario[1][0]:
        return 1
    return 4


def por_mes_legado(mes: int) -> int:
    """Mapa por MÊS — só para ano sem calendário oficial. Aproximado por
    construção: é exatamente o comportamento que este módulo veio substituir,
    mantido como rede de segurança para não quebrar a emissão em 2027 caso
    ninguém tenha cadastrado as datas."""
    return {1: 1, 2: 1, 3: 1, 4: 1, 5: 2, 6: 2, 7: 2,
            8: 3, 9: 3, 10: 4, 11: 4, 12: 4}[mes]


def rotulo(bimestre: int) -> str:
    """``3`` → ``"3º bimestre"``. Um só lugar monta o texto."""
    if bimestre not in BIMESTRES:
        raise ValueError(f"bimestre fora da faixa 1–4: {bimestre!r}")
    return f"{bimestre}º bimestre"
