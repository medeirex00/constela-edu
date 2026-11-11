"""Resolução de PERÍODOS de análise.

Converte um preset ("hoje", "este bimestre"...) ou um intervalo personalizado
em (inicio, fim) — datetimes naive — para filtrar leituras, rankings e
estatísticas por qualquer janela de tempo (base das premiações por período).

`None` em qualquer extremo significa "sem limite" (todo o histórico).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import Select, select

from app.models import Matricula
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


class PeriodoInvalido(Exception):
    """O pedido de período não tem sentido: no personalizado, a data inicial vem depois da
    final. A mensagem é a frase para quem usa; ``app.main`` a devolve como 422 em qualquer
    rota (a mesma do Relatório por Período).

    NÃO é ``ValueError`` de propósito: as rotas que chamam ``resolver`` trocam o
    ``ValueError`` (data em formato errado, de ``_parse_data``) por "Data inválida (use
    AAAA-MM-DD)", que é outro problema e esconderia a frase. Antes desta classe o intervalo
    invertido passava, as consultas ``data >= início AND data <= fim`` davam vazio e as
    telas diziam "nenhuma leitura no período"."""


def mensagem_datas_invertidas(inicio: date, fim: date) -> str:
    """A frase do intervalo com as datas trocadas (fonte única)."""
    return (f"A data inicial ({inicio.strftime('%d/%m/%Y')}) é posterior à "
            f"final ({fim.strftime('%d/%m/%Y')}) — inverta as duas.")


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


def _aproximado(rotulo: str, ano: int) -> str:
    """Rótulo de um bimestre SEM calendário oficial: a janela é a aproximação por
    meses e quem lê o cabeçalho precisa saber disso — antes saía "3º bimestre"
    como se fosse o oficial."""
    return f"{rotulo} (aproximado: sem calendário oficial de {ano})"


def _bimestre_aproximado(numero: int, ano: int, rotulo: str):
    """Janela APROXIMADA do ``numero``º bimestre de um ano SEM calendário oficial
    cadastrado em :mod:`app.services.bimestres`: os meses inteiros do mapa por mês
    da sugestão (:func:`bimestres.por_mes_legado`: 1º jan–abr, 2º mai–jul, 3º
    ago–set, 4º out–dez). É a MESMA para "Nº bimestre", "Este bimestre" e
    "Bimestre anterior" — antes os dois últimos usavam blocos civis de dois meses
    (``(mês-1)//2``), e "este bimestre" não era nenhum dos quatro numerados que o
    seletor e o certificado sugerem. Aproximada por construção (e o rótulo diz
    isso); existe para 2027 não quebrar antes de alguém cadastrar as datas."""
    meses = [m for m in range(1, 13) if bimestres.por_mes_legado(m) == numero]
    return (_ini(_primeiro(ano, meses[0])), _fim(_ultimo(ano, meses[-1])),
            _aproximado(rotulo, ano))


def _bimestre(preset: str, hoje: date, ano_letivo: int | None = None):
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

    O bimestre NUMERADO é do ANO LETIVO da escola (``ano_letivo``), o mesmo ano
    do preset "Ano letivo" da mesma lista — não do relógio. A troca do ano letivo
    é manual: em janeiro de 2027, com a escola ainda em 2026, o "4º bimestre" da
    cerimônia é o de 2026, e não out–dez de 2027 (janela futura, pódio vazio). O
    rótulo diz o ano quando ele não é o do calendário de hoje.
    """
    pedido = preset.rsplit("_", 1)[-1]
    numerado = pedido.isdigit()
    if numerado:
        numero, ano = int(pedido), ano_letivo or hoje.year
        if not (1 <= numero <= 4):
            return None, None, "Todo o histórico"
        rotulo_aproximado = bimestres.rotulo(numero)
    else:
        # "Este" é o número que a sugestão (e a tela) dá para hoje, com ou sem
        # calendário oficial; "anterior" é o número de antes. Sem calendário, a
        # janela é a aproximada DESSE número (a mesma do "Nº bimestre").
        ano = hoje.year
        anterior = preset == "bimestre_anterior"
        numero = bimestres.bimestre_sugerido(hoje)
        rotulo_aproximado = "Bimestre anterior" if anterior else "Este bimestre"
        if anterior and numero > 1:
            numero -= 1
        elif anterior:
            # O anterior do 1º é o 4º do ano PASSADO, pelo calendário DELE — que
            # pode existir mesmo sem o deste ano. Antes, em jan/fev de um ano sem
            # calendário (2027), caía sempre no legado nov/dez com o rótulo "sem
            # calendário oficial de 2026": 27 dias de outubro a menos e um
            # cabeçalho negando o calendário que 2026 tem. Só sem o calendário do
            # ano passado é que a aproximação entra.
            ano, numero = ano - 1, 4
    if not bimestres.ano_com_calendario(ano):
        return _bimestre_aproximado(numero, ano, rotulo_aproximado)
    inicio, fim = bimestres.intervalo(numero, ano)
    # O numerado de um ano letivo que não é o do calendário de hoje diz o ano: em
    # janeiro, "4º bimestre (05/10 a 31/12)" pode ser lido como o do ano novo.
    de_outro_ano = f" de {ano}" if numerado and ano != hoje.year else ""
    return _ini(inicio), _fim(fim), (f"{bimestres.rotulo(numero)}{de_outro_ano} "
                                    f"({inicio:%d/%m} a {fim:%d/%m})")


def resolver(
    preset: str,
    hoje: date,
    ano_letivo: int,
    inicio: date | None = None,
    fim: date | None = None,
) -> tuple[datetime | None, datetime | None, str]:
    """(inicio_dt, fim_dt, rótulo). Datas None viram limite aberto.

    Personalizado com ``inicio`` depois de ``fim`` levanta ``PeriodoInvalido``."""
    preset = (preset or "tudo").lower()

    if preset == "personalizado":
        if inicio and fim and inicio > fim:
            raise PeriodoInvalido(mensagem_datas_invertidas(inicio, fim))
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
        return _bimestre(preset, hoje, ano_letivo)

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


# ---------------------------------------------------------------------------
# A POPULAÇÃO do período: de que ano letivo vêm as crianças
# ---------------------------------------------------------------------------
#: As crianças do ano letivo ATIVO da escola — o período está nele (ou depois dele, antes
#: da virada manual), ou é "Todo o histórico". A regra de sempre, sem aviso.
ORIGEM_ANO_ATIVO = "ano_ativo"
#: O período cai INTEIRO num ano letivo ANTERIOR ao ativo: as crianças matriculadas
#: NAQUELE ano, com a turma e a série dele.
ORIGEM_ANO_DO_PERIODO = "ano_do_periodo"
#: O período passa por mais de um ano letivo (ou não tem uma das pontas): a regra de
#: sempre (o ano ativo), DECLARADA — quem não tem matrícula no ano ativo não aparece.
ORIGEM_ATRAVESSA_ANOS = "atravessa_anos"


@dataclass(frozen=True)
class PopulacaoDoPeriodo:
    """De que ANO LETIVO vêm as crianças de uma consulta por período — a fonte única das
    premiações, do Ranking de Leitura e de Matemática por período e do Relatório por
    Período (tela e PDF).

    ``ano_letivo`` decide as MATRÍCULAS (quem entra, com a turma e a série daquele ano) e
    o ano do contador do Matific, que zera a cada ano. O ano letivo é o ano civil — a
    mesma janela do preset "Ano letivo" e de ``matific_destaque.janela_ano_letivo``.

    Por que existe (S_G_VIRADA-2): depois da virada, a cerimônia de 2026 feita em
    fevereiro pedia out–dez/2026 e recebia as crianças de 2027 — a formanda do 5º ano que
    liderou sumia do pódio e as demais apareciam na turma do ano novo, sem aviso."""
    ano_letivo: int
    origem: str
    ano_letivo_ativo: int

    @property
    def outro_ano(self) -> bool:
        """As crianças são de um ano letivo que não é o ativo da escola?"""
        return self.ano_letivo != self.ano_letivo_ativo

    def como_dict(self) -> dict:
        """O bloco ``populacao`` das respostas: a tela e o PDF dizem de que ano são as
        crianças e as turmas, e por quê."""
        return {"ano_letivo": self.ano_letivo, "origem": self.origem,
                "ano_letivo_ativo": self.ano_letivo_ativo}

    def alunos_das_turmas(self, escola_id: int, turma_ids: Iterable[int]) -> Select:
        """As crianças que um RECORTE DE TURMA escolhe — a turma do filtro da tela ou as
        turmas do professor —, como subconsulta de ``Aluno.id``.

        Os seletores de turma e as permissões só conhecem as turmas de AGORA (as do ano
        ativo). Num período de ano encerrado, a turma escolhida não tem matrícula naquele
        ano: filtrar pela turma da matrícula do período deixaria a lista sempre vazia (o
        professor, depois da virada, não veria nada do bimestre passado). Então o recorte
        escolhe QUEM aparece pela matrícula na turma — no ano ativo ou no ano do período
        (uma turma é de um ano só) — e cada criança continua saindo com a turma e a série
        que tinha no ano do período. A criança tem uma matrícula por ano
        (``uq_matricula_aluno_ano``), então no ano ativo isto é o mesmo que filtrar pela
        turma da matrícula."""
        anos = sorted({self.ano_letivo, self.ano_letivo_ativo})
        return select(Matricula.aluno_id).where(
            Matricula.escola_id == escola_id,
            Matricula.turma_id.in_(list(turma_ids)),
            Matricula.ano_letivo.in_(anos))


def populacao_do_periodo(inicio: datetime | date | None, fim: datetime | date | None,
                         ano_letivo_ativo: int) -> PopulacaoDoPeriodo:
    """A população de um período já resolvido (``resolver``) numa escola cujo ano letivo
    ativo é ``ano_letivo_ativo``.

    * período INTEIRO num ano letivo ANTERIOR ao ativo → as crianças daquele ano
      (``ano_do_periodo``): o pódio de um ano fechado é o mesmo antes e depois da virada;
    * "Todo o histórico", período dentro do ano ativo, ou inteiro num ano posterior (em
      janeiro, antes de alguém virar o ano da escola) → as crianças de agora
      (``ano_ativo``), como sempre;
    * período que passa por mais de um ano letivo, ou com uma ponta só que não fica no ano
      ativo em diante → a regra de sempre, declarada (``atravessa_anos``).
    """
    if inicio is None and fim is None:
        return PopulacaoDoPeriodo(ano_letivo_ativo, ORIGEM_ANO_ATIVO, ano_letivo_ativo)
    if inicio is not None and fim is not None and inicio.year == fim.year:
        if inicio.year < ano_letivo_ativo:
            return PopulacaoDoPeriodo(inicio.year, ORIGEM_ANO_DO_PERIODO, ano_letivo_ativo)
        return PopulacaoDoPeriodo(ano_letivo_ativo, ORIGEM_ANO_ATIVO, ano_letivo_ativo)
    if fim is None and inicio.year >= ano_letivo_ativo:
        # "A partir de 01/03/2027" numa escola em 2027: é o ano ativo daqui em diante.
        return PopulacaoDoPeriodo(ano_letivo_ativo, ORIGEM_ANO_ATIVO, ano_letivo_ativo)
    return PopulacaoDoPeriodo(ano_letivo_ativo, ORIGEM_ATRAVESSA_ANOS, ano_letivo_ativo)
