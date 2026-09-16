"""Destaque de MATEMÁTICA por período — a régua da "Melhor Matemática".

Módulo PURO (sem banco, sem configuração): recebe séries de snapshots do
Matific já carregadas e devolve números determinísticos. Quem consulta o banco é
``services.premiacoes``; aqui só mora a regra, num lugar só, para ela não ser
duplicada em outra camada (nem no frontend).

DECISÃO DO DONO (2026-09-15), que substitui a de 2026-09-01:

1. SÓ O PERÍODO decide. O ganho do período sai de snapshots do ANO LETIVO:
   um acumulado de dez/2025 nunca vale como "setembro/2026". Período sem
   atividade = sem dado e sem vencedor; nenhum número é inventado.
2. A RÉGUA É A DA ESCOLA INTEIRA. A mediana ``k`` vem da coorte completa de
   alunos ativos matriculados no ano letivo. Turma, série, professor e turno só
   decidem QUEM APARECE; a mesma criança com os mesmos dados tem a mesma nota
   em qualquer filtro.
3. A FÓRMULA é a média de estrelas por atividade, com um amortecedor para
   amostras pequenas: soma-se ao denominador um número de atividades "extras"
   com ZERO estrela igual a 20% da mediana de atividades da coorte::

       zeros  = 0,2 × k
       índice = estrelas_do_período ÷ (atividades_do_período + zeros)

   O amortecedor é RELATIVO À COORTE DO PERÍODO, então o equilíbrio entre
   "poucas atividades perfeitas" e "muitas quase perfeitas" DEPENDE DE ``k`` —
   não é propriedade absoluta da fórmula. Quanto MAIOR a mediana do período,
   mais o volume pesa; quanto MENOR (período curto, coorte pouco ativa), mais a
   média por atividade pesa. Com a mediana da escola em torno de 80 atividades
   (os casos de referência do dono), quem fez 10 atividades com 5 estrelas não
   passa à frente de quem fez 150 com 4,5 (1,92 × 4,07), e volume sozinho também
   não vence: 200 atividades com 4,0 ficam atrás de 60 com 4,8 (3,70 × 3,79).
   Numa coorte de mediana baixa (k = 4,5) a primeira comparação se inverte
   (4,59 × 4,47) e numa de mediana alta (k = 180) a segunda também
   (3,39 × 3,00) — ao explicar a premiação, cite sempre a mediana DO PERÍODO.
   Escala de 0 a 5, sempre finita.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

# Fração da mediana de atividades da coorte somada como atividades com 0 estrela.
FRACAO_ZEROS_EXTRAS = 0.2
# Teto de estrelas por atividade no Matific (a escala do índice é 0 a 5).
ESTRELAS_MAX_POR_ATIVIDADE = 5.0


def _sem_fuso(momento: datetime) -> datetime:
    """SQLite devolve datetimes ingênuos; normaliza para comparar com segurança."""
    return momento.replace(tzinfo=None) if momento.tzinfo else momento


def _data(snap) -> datetime:
    return _sem_fuso(snap.data_referencia)


def _valor(snap, campo: str) -> float:
    if snap is None:
        return 0.0
    bruto = getattr(snap, campo, 0) or 0
    valor = float(bruto)
    return valor if math.isfinite(valor) else 0.0


def janela_ano_letivo(ano_letivo: int) -> tuple[datetime, datetime]:
    """[ano-01-01 00:00, ano-12-31 23:59:59.999999] — a mesma janela do preset
    ``"ano_letivo"`` de ``services.periodos``."""
    return (datetime(ano_letivo, 1, 1, 0, 0, 0),
            datetime(ano_letivo, 12, 31, 23, 59, 59, 999999))


def janela_efetiva(inicio: datetime | None, fim: datetime | None,
                   ano_letivo: int) -> tuple[datetime, datetime] | None:
    """Interseção de [inicio, fim] com o ano letivo. Extremo nulo vira a borda do
    ano. ``None`` quando o período não toca o ano letivo (nada a medir)."""
    ini_ano, fim_ano = janela_ano_letivo(ano_letivo)
    ini = ini_ano if inicio is None else max(_sem_fuso(inicio), ini_ano)
    fim_ef = fim_ano if fim is None else min(_sem_fuso(fim), fim_ano)
    if ini > fim_ef:
        return None
    return ini, fim_ef


@dataclass(frozen=True)
class GanhoMatific:
    """O que o aluno fez DENTRO do período (nunca o acumulado anterior)."""
    atividades: float
    estrelas: float
    data_base: datetime | None    # snapshot usado como ponto de partida (None = zero)
    data_atual: datetime          # snapshot usado como ponto de chegada
    # O contador do Matific CAIU entre `data_base` e `data_atual` (atual < base).
    # O ganho fica em 0 — nenhum número é inventado —, mas o fato não é
    # silenciado: quem exibe o pódio pode dizer "o contador do Matific regrediu
    # entre <data_base> e <data_atual>" em vez de mostrar um zero inexplicável.
    regressao_detectada: bool = False


def ganho_no_periodo(serie: Iterable, inicio: datetime | None,
                     fim: datetime | None, ano_letivo: int) -> GanhoMatific | None:
    """Atividades e estrelas conquistadas no período, só com snapshots do ano letivo.

    Regras (decisão do dono, 2026-09-15):

    * Snapshots com ``data_referencia`` fora do ano letivo são descartados
      ANTES de tudo: os contadores do Matific são do ano, e um snapshot de
      dez/2025 não diz nada sobre 2026 — nem como estado, nem como base.
    * Janela efetiva = [inicio, fim] ∩ ano letivo (extremo nulo = borda do ano).
    * ``atual`` = último snapshot DENTRO da janela efetiva. Sem snapshot na janela
      → ``None``: o aluno não é elegível (ausência, não zero).
    * ``base`` = último snapshot do ano letivo ANTES do início efetivo. Sem ele:
      - janela que COMEÇA NO INÍCIO DO ANO LETIVO (``ini == ini_ano``, o único
        caso possível já que ``janela_efetiva`` faz ``max``): ``base = None`` —
        o contador do Matific é DO ANO e parte de zero ali, então o primeiro
        snapshot do ano já É ganho do período. Usá-lo como base jogaria fora
        tudo o que a criança fez antes da primeira coleta e faria "ano letivo"
        divergir de "todo o histórico" na MESMA janela;
      - janela que começa NO MEIO DO ANO: ``base`` = PRIMEIRO snapshot dentro da
        janela, porque o acumulado até ali é de ANTES do período e não pode
        virar mérito dele (um único snapshot na janela dá ganho 0).
    * atividades = max(0, atual − base); estrelas = max(0, atual − base),
      limitadas a 5 × atividades (uma correção de relatório não cria estrela
      sem atividade).

    RESET/REGRESSÃO DO CONTADOR: quando ``atual < base`` o ganho fica em 0 (o
    piso é deliberado: uma correção para baixo — aluno fundido, relatório
    recontado, aluno recriado — não pode virar ganho do valor cheio, que seria
    inventar número), mas a queda é REGISTRADA em ``regressao_detectada`` em vez
    de silenciada. HIPÓTESE ASSUMIDA, ainda não confirmada com a plataforma: a
    virada do contador é a do ANO CIVIL (01/01), e por isso a janela do ano vai
    de 01/01 a 31/12. A coleta usa ``duration=this-year`` ("ano acadêmico
    atual"), cuja data de virada não está documentada (docs/MATIFIC_API.md, item
    do ``this-year``). Se ela NÃO for 01/01, o mês da virada aparece como
    ``regressao_detectada`` com ganho 0 — é esse sinal que deve disparar a
    revisão da janela do ano, nunca um remendo cego de ``base = 0``.

    O QUE ESSA HIPÓTESE CUSTA na regra de ``base = None`` acima (a outra face da
    mesma moeda, dita aqui para ninguém ser surpreendido): partir de zero em
    01/01 só é verdade se o contador TIVER zerado ali. Se a virada do
    ``this-year`` for depois (p. ex. em fevereiro), um snapshot de janeiro ainda
    carrega o acumulado do ano anterior e a janela que abre o ano o atribuiria
    inteiro ao período — e esse caso NÃO acende ``regressao_detectada`` (a queda
    só aparece no mês da virada, depois). Enquanto a data real não for
    confirmada, o sinal a vigiar é uma ``regressao_detectada`` logo após a
    abertura do ano: ela indica que o zero de 01/01 é fictício e que a janela do
    ano precisa ser derivada da virada observada na série.

    TODO O HISTÓRICO (``inicio`` e ``fim`` nulos): não existe período para
    recortar, e fingir um seria inventar número. Vale a SITUAÇÃO DO ÚLTIMO
    SNAPSHOT do ano letivo, tomada a partir do zero (``data_base = None``): os
    contadores do ano como a plataforma os informou. Sem snapshot no ano → ``None``.
    """
    ini_ano, fim_ano = janela_ano_letivo(ano_letivo)
    # sorted é estável: empate de data preserva a ordem recebida (id).
    do_ano = sorted((s for s in serie if ini_ano <= _data(s) <= fim_ano), key=_data)
    if not do_ano:
        return None

    if inicio is None and fim is None:
        atual, base = do_ano[-1], None
    else:
        janela = janela_efetiva(inicio, fim, ano_letivo)
        if janela is None:
            return None
        ini, fim_ef = janela
        dentro = [s for s in do_ano if ini <= _data(s) <= fim_ef]
        if not dentro:
            return None
        atual = dentro[-1]
        anteriores = [s for s in do_ano if _data(s) < ini]
        if anteriores:
            base = anteriores[-1]
        elif ini <= ini_ano:
            # A janela começa no início do ano letivo: o contador do ano parte
            # de zero (mesma premissa do caminho "todo o histórico", acima).
            base = None
        else:
            base = dentro[0]

    ativ_atual, ativ_base = _valor(atual, "atividades"), _valor(base, "atividades")
    est_atual, est_base = _valor(atual, "estrelas"), _valor(base, "estrelas")
    # Queda do contador: fica explícita na resposta em vez de virar um zero mudo.
    regrediu = base is not None and (ativ_atual < ativ_base or est_atual < est_base)
    atividades = max(0.0, ativ_atual - ativ_base)
    estrelas = min(max(0.0, est_atual - est_base),
                   ESTRELAS_MAX_POR_ATIVIDADE * atividades)
    return GanhoMatific(
        atividades=atividades, estrelas=estrelas,
        data_base=_data(base) if base is not None else None,
        data_atual=_data(atual), regressao_detectada=regrediu)


def mediana_atividades(atividades: Iterable[float]) -> float | None:
    """``k`` = mediana das atividades do período entre os alunos da COORTE com
    pelo menos 1 atividade (contadores inteiros: valor > 0). Ninguém → ``None``."""
    ativos = [float(a) for a in atividades
              if a is not None and math.isfinite(float(a)) and float(a) > 0]
    if not ativos:
        return None
    return float(statistics.median(ativos))


def indice(atividades: float | None, estrelas: float | None,
           k: float | None) -> float | None:
    """Média ajustada de estrelas por atividade (0 a 5).

    ``None`` quando não há o que medir: atividades ≤ 0 ou régua ``k`` ausente.
    ``zeros = 0,2 × k``; ``índice = estrelas ÷ (atividades + zeros)``. O
    denominador é sempre ≥ atividades > 0, então nunca há divisão por zero; o
    resultado é limitado a [0, 5] e sempre finito."""
    if k is None or atividades is None:
        return None
    atividades = float(atividades)
    k = float(k)
    if not math.isfinite(atividades) or not math.isfinite(k) or atividades <= 0:
        return None
    estrelas = float(estrelas or 0.0)
    if not math.isfinite(estrelas):
        return None
    zeros = FRACAO_ZEROS_EXTRAS * max(0.0, k)
    valor = max(0.0, estrelas) / (atividades + zeros)
    return min(ESTRELAS_MAX_POR_ATIVIDADE, max(0.0, valor))


@dataclass(frozen=True)
class ReguaMatematica:
    """A régua única da escola no período (a mesma para qualquer recorte)."""
    k_mediana_atividades: float | None
    zeros_extras: float | None
    alunos_com_atividade: int


def indices_da_coorte(
    ganhos: dict[int, GanhoMatific],
) -> tuple[ReguaMatematica, dict[int, float]]:
    """Régua + índice de cada aluno, a partir dos ganhos da COORTE ESCOLAR inteira.

    ``ganhos`` deve conter a escola toda (quem não tem snapshot no período
    simplesmente não está no dicionário). Devolve só os alunos com índice
    definido (atividades > 0); coorte vazia → régua sem ``k`` e nenhum índice."""
    k = mediana_atividades(g.atividades for g in ganhos.values())
    regua = ReguaMatematica(
        k_mediana_atividades=k,
        zeros_extras=FRACAO_ZEROS_EXTRAS * k if k is not None else None,
        alunos_com_atividade=sum(1 for g in ganhos.values() if g.atividades > 0))
    indices: dict[int, float] = {}
    for aluno_id, ganho in ganhos.items():
        valor = indice(ganho.atividades, ganho.estrelas, k)
        if valor is not None:
            indices[aluno_id] = valor
    return regua, indices
