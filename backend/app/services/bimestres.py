"""Calendário oficial dos bimestres — fonte ÚNICA das datas.

Por que este módulo existe: até aqui o bimestre do certificado saía de
``_bimestre_por_mes(mês do relógio)``, um mapa de MESES inteiros. Isso erra na
virada, que é o único momento em que a pergunta importa: pelo calendário real da
Rede Estadual de SP, o 3º bimestre de 2026 vai até **04/10**, mas o mapa por mês
já dava 4 no dia 01/10. Quem entregasse certificados na primeira semana de
outubro imprimiria "4º bimestre" num documento sobre o trabalho do 3º.

As datas de 2026 estão aqui como CONSTANTE, não no banco: a tabela de
calendário que existiria para isso (``cur_bimestre_periodos``) ainda não está
publicada. Quando estiver, este módulo vira a camada que a lê — os chamadores não
mudam.

ANO SEM CALENDÁRIO (2027 em diante, enquanto ninguém cadastrar): nada de datas
silenciosamente erradas. :func:`intervalo` RECUSA com :class:`CalendarioNaoDefinido`
(mensagem que diz como configurar); :func:`bimestre_sugerido`, que precisa sempre
devolver um número para a tela abrir, cai no mapa por mês legado mas AVISA no log
(uma vez por ano) e :func:`aviso_sem_calendario` dá o texto para quem exibe datas.

COMO CONFIGURAR um ano novo, sem mexer no código: a variável de ambiente
``BIMESTRES_CALENDARIO`` com um JSON ``{"2027": [["2027-02-01", "2027-04-23"],
["2027-04-26", "2027-07-09"], ["2027-07-26", "2027-10-01"], ["2027-10-04",
"2027-12-17"]]}`` (datas de EXEMPLO) — quatro pares início/fim INCLUSIVOS, em
ordem, sem sobreposição, dentro do ano. Calendário inválido é IGNORADO por
inteiro (com erro no log): antes "sem calendário" (explícito) do que datas
erradas. Também dá para acrescentar o ano em :data:`PERIODOS` (exige deploy). As
datas são as da Secretaria — não invente.

Fuso: tudo aqui é ``date``, nunca ``datetime``. A conversão de "agora" para data
local é feita UMA vez, por quem chama, com ``agora_br().date()``. Comparar datas
puras remove a classe inteira de erro de borda em 22/04→23/04 e 04/10→05/10 —
não existe instante ambíguo quando não há hora.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date

logger = logging.getLogger(__name__)

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
VARIAVEL_CALENDARIO = "BIMESTRES_CALENDARIO"


class CalendarioNaoDefinido(ValueError):
    """O ano pedido não tem calendário oficial cadastrado. ``ValueError`` para
    quem já tratava o erro antigo continuar tratando."""


def _validar_ano(ano: int, pares) -> dict[int, tuple[date, date]]:
    """Quatro pares (início, fim) inclusivos, em ordem, sem sobreposição e dentro
    do ano. LEVANTA ``ValueError`` com o motivo."""
    if not isinstance(pares, list) or len(pares) != 4:
        raise ValueError("precisa de exatamente 4 bimestres")
    saida: dict[int, tuple[date, date]] = {}
    fim_anterior: date | None = None
    for numero, par in zip(BIMESTRES, pares):
        if not isinstance(par, (list, tuple)) or len(par) != 2:
            raise ValueError(f"{numero}º bimestre: use [início, fim]")
        inicio, fim = (date.fromisoformat(str(x)) for x in par)
        if inicio.year != ano or fim.year != ano:
            raise ValueError(f"{numero}º bimestre fora de {ano}")
        if fim < inicio:
            raise ValueError(f"{numero}º bimestre termina antes de começar")
        if fim_anterior is not None and inicio <= fim_anterior:
            raise ValueError(f"{numero}º bimestre começa antes do fim do anterior")
        saida[numero] = (inicio, fim)
        fim_anterior = fim
    return saida


def _calendario_configurado() -> dict[int, dict[int, tuple[date, date]]]:
    """Anos cadastrados pela variável de ambiente (ver o topo do módulo). Lido a
    cada chamada (é barato, e vale sem reiniciar nos testes); ano inválido é
    descartado inteiro, com erro no log."""
    bruto = os.environ.get(VARIAVEL_CALENDARIO, "").strip()
    if not bruto:
        return {}
    try:
        dados = json.loads(bruto)
        if not isinstance(dados, dict):
            raise ValueError("o JSON precisa ser um objeto {ano: [...]}")
    except ValueError as exc:
        logger.error("%s ilegível (%s): ignorado.", VARIAVEL_CALENDARIO, exc)
        return {}
    saida: dict[int, dict[int, tuple[date, date]]] = {}
    for chave, pares in dados.items():
        try:
            ano = int(chave)
            saida[ano] = _validar_ano(ano, pares)
        except (TypeError, ValueError) as exc:
            logger.error("%s: calendário de %s inválido (%s): ignorado.",
                         VARIAVEL_CALENDARIO, chave, exc)
    return saida


def calendario(ano: int) -> dict[int, tuple[date, date]] | None:
    """Os quatro bimestres do ano (constante, senão a configuração), ou None."""
    if ano in PERIODOS:
        return PERIODOS[ano]
    return _calendario_configurado().get(ano)


def ano_com_calendario(ano: int) -> bool:
    """O ano tem calendário oficial cadastrado?"""
    return calendario(ano) is not None


def aviso_sem_calendario(ano: int) -> str:
    """O texto para quem EXIBE datas de bimestre de um ano sem calendário."""
    return (f"Calendário oficial de {ano} não cadastrado: as datas do bimestre são "
            "aproximadas (meses do calendário civil). Cadastre o calendário da rede "
            f"em {VARIAVEL_CALENDARIO}.")


_avisados: set[int] = set()


def _avisar_uma_vez(ano: int) -> None:
    if ano not in _avisados:
        _avisados.add(ano)
        logger.warning(aviso_sem_calendario(ano))


def intervalo(bimestre: int, ano: int = 2026) -> tuple[date, date]:
    """Datas de início e fim (inclusivas) do bimestre.

    >>> intervalo(3)
    (datetime.date(2026, 7, 24), datetime.date(2026, 10, 4))

    Ano sem calendário: LEVANTA ``CalendarioNaoDefinido`` — nunca chuta datas.
    """
    if bimestre not in BIMESTRES:
        raise ValueError(f"bimestre fora da faixa 1–4: {bimestre!r}")
    cal = calendario(ano)
    if cal is None:
        raise CalendarioNaoDefinido(
            f"não há calendário oficial cadastrado para {ano}. Cadastre os quatro "
            f"bimestres da rede em {VARIAVEL_CALENDARIO} (ver app/services/bimestres.py).")
    return cal[bimestre]


def bimestre_da_data(dia: date) -> int | None:
    """Em qual bimestre esta data cai — ``None`` se cair FORA dos quatro.

    O recesso (01/01 a 01/02 de 2026, ou entre dois bimestres num ano que tenha
    folga entre eles) não pertence a bimestre nenhum, e este módulo não finge que
    pertence: quem precisa de um número sempre usa :func:`bimestre_sugerido`, que
    trata o recesso explicitamente.
    """
    cal = calendario(dia.year)
    if not cal:
        return None
    for numero in BIMESTRES:
        inicio, fim = cal[numero]
        if inicio <= dia <= fim:
            return numero
    return None


def bimestre_sugerido(dia: date) -> int:
    """O número que a tela abre selecionado. SEMPRE devolve 1–4.

    É só uma SUGESTÃO: quem emite pode escolher qualquer um dos quatro, e a
    escolha dele manda. Regras das bordas, explícitas para não virarem surpresa:

    * dentro de um bimestre → ele mesmo;
    * recesso → o PRÓXIMO bimestre do ano, porque é o próximo período a ser
      avaliado. Vale para janeiro (antes do 1º → 1º, e não o 4º do ano anterior,
      que já foi entregue) e para o recesso ENTRE dois bimestres (em julho, entre
      o 2º e o 3º → 3º; o 2º, que acabou, é o "bimestre anterior"). É o mesmo
      número que a tela abre marcado (``bimestreDeHoje`` na web);
    * depois do fim do 4º (fim de dezembro) não há próximo no ano → 4º;
    * ano sem calendário cadastrado → cai no mapa por mês legado
      (:func:`por_mes_legado`), que é aproximado mas nunca levanta erro — e AVISA
      no log (uma vez por ano), para não ser silencioso. Cadastrar o calendário do
      ano novo (``BIMESTRES_CALENDARIO`` ou :data:`PERIODOS`) resolve.
    """
    exato = bimestre_da_data(dia)
    if exato is not None:
        return exato
    cal = calendario(dia.year)
    if not cal:
        _avisar_uma_vez(dia.year)
        return por_mes_legado(dia.month)
    # Antes, todo dia fora de um bimestre depois do início do 1º virava 4: no
    # recesso de julho, "este bimestre" era o 4º e o "anterior", o 3º (futuro).
    return next((numero for numero in BIMESTRES if dia < cal[numero][0]), 4)


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
