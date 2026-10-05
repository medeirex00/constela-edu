"""Relatório por PERÍODO: o que aconteceu numa janela de datas, por plataforma
e por escopo (escola, turma ou aluno).

POR QUE ISTO EXISTE. A escola pede "o relatório do mês", "de fevereiro até
agora", "de 10 a 25 de setembro". O que existia era o retrato ANUAL (notas,
ranking) e os pódios por período das premiações — nenhum dos dois responde
"quanto esta turma leu em setembro". Este módulo é a camada de CONSULTA que
responde isso. Ele NÃO calcula mérito, NÃO toca scoring, ranking, P90, nota,
premiação, certificado, identidade nem sincronização: só lê e agrega.

================================================================
A SEMÂNTICA DAS DATAS — a decisão central deste módulo
================================================================

ELEFANTE LETRADO → DOIS eixos de data, porque a plataforma entrega dois fatos
diferentes e nenhum deles responde sozinho "o que aconteceu em setembro".

(1) LIVRO NOVO e TEMPO → ``Leitura.data`` + ``Leitura.tempo_leitura_min``.
    É exatamente o par que a premiação oficial usa em "Mais Livros" e "Mais
    Tempo" (``premiacoes._leitura_no_periodo``). Reusar o mesmo campo é
    deliberado: um relatório que discordasse do pódio sobre o MESMO mês seria
    pior do que relatório nenhum.
    O que o campo É: o ``lastReadWhen`` que a plataforma informava na PRIMEIRA
    importação daquele (aluno, livro) — ``uq_leitura_unica`` impede a linha de
    nascer duas vezes e o importador nunca atualiza a data (§35).
    O que ele NÃO é: a data da releitura. Quem releu em setembro um livro
    importado em julho segue datado em julho.

(2) ATIVIDADE REAL, INCLUSIVE RELEITURA → ``EventoAluno.ocorrido_em``
    (``tipo_evento == "leitura"``). O espelho é gravado por um laço SEPARADO
    que percorre TODAS as linhas do relatório, inclusive as que a §35 descarta,
    com o instante que a plataforma informa. É o único campo que vê a
    releitura.

Os dois saem no relatório como números DISTINTOS e rotulados (``livros_novos``
× ``livros_com_atividade``, com ``livros_relidos`` explicando a diferença).
Nunca somados: somar contaria o mesmo livro duas vezes.

TEMPO POR EVENTO: **NÃO SUPORTADO** — medido, não suposto.
``EventoAluno.tempo_segundos`` é ``tempo_livro_min * 60``, que vem do
``totalTimeSpent`` da API; e a API devolve UMA linha por (aluno, LIVRO), com
``lastReadWhen`` — não uma linha por sessão. Medição em produção (5 escolas,
112.877 eventos, 4.547 pares com 2+ eventos): 95,8% das séries são NÃO
DECRESCENTES ao longo do tempo e somar todos os eventos excede o total
autoritativo do retrato em 10,7% (escola 1) e 15,6% (escola 7) — ou seja, o
campo se comporta como contador ACUMULADO por livro, em que somar conta o mesmo
tempo outra vez. Mas 4,2% das séries DECRESCEM, e um acumulado não pode
decrescer — então a diferença ``atual − base`` também não se sustenta. Com as
duas leituras possíveis refutadas pela própria base, o tempo do período por
evento seria palpite: o relatório devolve ``None`` com o motivo. O tempo do
período vem de (1).

  Ressalva registrada: ``uq_evento_natural(aluno_id, plataforma, chave_natural)``
  e ``chave_evento`` hasheiam o MINUTO do ocorrido. Duas leituras do mesmo livro
  no mesmo minuto colapsam num evento só — ``eventos_leitura`` é, por isso, um
  PISO de atividade, não uma contagem de sessões. Livros distintos não são
  afetados.

  Ressalva registrada: o espelho de eventos existe a partir da migração 0010.
  Janela anterior a ela devolve zero por ausência de histórico, não por
  inatividade — por isso o relatório informa ``primeiro_evento_da_escola``.

MATIFIC → diferença entre RETRATOS (``SnapshotMatific``), via
``matific_destaque.ganho_no_periodo``.

O Matific não expõe evento datado: o que chega é um contador ACUMULADO do ano
por aluno, gravado como retrato do dia (``data_referencia``). "Quantas atividades
em setembro" é, por construção, ``acumulado no fim da janela − acumulado antes
dela``. Em vez de reimplementar essa aritmética, este módulo reusa a função
oficial que as premiações já usam, com as mesmas regras (janela ∩ ano letivo,
base = último retrato antes do início, piso em zero quando o contador regride).

  Ressalva registrada: sem retrato DENTRO da janela o aluno não é elegível —
  ausência não é zero. O relatório conta esses alunos em
  ``alunos_sem_retrato`` em vez de somá-los como zero.

================================================================
O QUE É E O QUE NÃO É CALCULÁVEL
================================================================

SUPORTADO                  Elefante: livros novos e tempo (``Leitura.data``, o
                           mesmo par da premiação); livros com atividade,
                           relidos e eventos (``EventoAluno.ocorrido_em``).
SUPORTADO COM RESSALVA     Elefante: tempo — ``tempo_leitura_min`` é NULLABLE
                           ("quando o relatório informa") e nulo entra como 0,
                           então o total do período é um piso em relação ao
                           acumulado do retrato.
SUPORTADO COM RESSALVA     Elefante: questões tentadas/acertadas, e Matific:
                           atividades/estrelas — só existem como contador
                           acumulado no retrato, então valem pela diferença
                           entre retratos e exigem retrato na janela. A janela
                           EFETIVA (``data_base``/``data_atual``) é a das
                           coletas, não a pedida, e sai junto do número.
NÃO SUPORTADO              Elefante: tempo por EVENTO — ver a medição acima.
NÃO SUPORTADO              Matific: "questões". ``SnapshotMatific`` tem
                           ``atividades``, ``estrelas`` e ``pontuacao_media`` —
                           não há campo de questões. O relatório devolve
                           ``None`` e diz o motivo, em vez de um número falso.
NÃO SUPORTADO              Pontos de dificuldade / mérito no período. Existe e é
                           oficial, mas em ``premiacoes`` — reimplementar aqui
                           criaria uma segunda régua que poderia divergir do
                           pódio. Quem quer mérito usa ``/premiacoes``.

A COORTE não é a da premiação. ``premiacoes._alunos_ativos`` filtra pelo recorte
premiável (1º ao 5º ano, ``elegibilidade.participa_de_premiacao``). Um relatório
de gestão precisa da população ATIVA MATRICULADA inteira, Educação Infantil
incluída — senão a diretora pede "o relatório da escola" e recebe parte dela.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (Aluno, Escola, EventoAluno, Leitura, Matricula,
                        SnapshotElefante, SnapshotMatific, Turma)
from app.services import matific_destaque, periodos

ESCOPOS = ("escola", "turma", "aluno")
PLATAFORMAS = ("elefante", "matific")

# Motivos de "não suportado", para o relatório dizer POR QUE em vez de 0.
MOTIVO_MATIFIC_QUESTOES = (
    "O retrato do Matific guarda atividades, estrelas e pontuação média — não "
    "existe contador de questões, então não há como calcular este número para "
    "um período sem inventá-lo.")
MOTIVO_ELEFANTE_TEMPO_EVENTO = (
    "O tempo do evento vem do `totalTimeSpent` da API, e a API devolve uma "
    "linha por (aluno, LIVRO) — não por sessão. Medido em produção: 95,8% das "
    "séries por livro nunca decrescem e somar todos os eventos excede o total "
    "do retrato em até 15,6% (comportamento de contador ACUMULADO, em que a "
    "soma repete o mesmo tempo), mas 4,2% das séries DECRESCEM, o que um "
    "acumulado não pode fazer (então a diferença atual−base também não vale). "
    "As duas leituras possíveis estão refutadas pela própria base: o tempo do "
    "período por evento não é calculável. O tempo do período vem de "
    "`Leitura.tempo_leitura_min`, o mesmo campo da premiação oficial.")
MOTIVO_ELEFANTE_PONTOS = (
    "A régua de mérito é oficial e vive em `premiacoes`; recalculá-la aqui "
    "criaria uma segunda régua que poderia divergir do pódio. Use /premiacoes "
    "para mérito.")


class RelatorioInvalido(Exception):
    """Pedido que não se sustenta (escopo, plataforma ou datas)."""


@dataclass(frozen=True)
class Janela:
    preset: str
    inicio: datetime | None
    fim: datetime | None
    rotulo: str

    def contem(self, momento: datetime | None) -> bool:
        if momento is None:
            return False
        if self.inicio is not None and momento < self.inicio:
            return False
        if self.fim is not None and momento > self.fim:
            return False
        return True


@dataclass
class BlocoElefante:
    # eixo (1) — Leitura.data: o mesmo par que a premiação oficial usa.
    livros_novos: int = 0
    tempo_min: int = 0
    alunos_com_livro_novo: int = 0
    # eixo (2) — EventoAluno.ocorrido_em: atividade real, inclusive releitura.
    livros_com_atividade: int = 0
    livros_relidos: int = 0
    eventos_leitura: int = 0
    alunos_com_atividade: int = 0
    # retrato (acumulado) — exige coleta dentro da janela.
    questoes_tentativas: int | None = None
    questoes_acertos: int | None = None
    alunos_sem_retrato: int = 0
    janela_efetiva_questoes: dict | None = None
    suporte: dict = field(default_factory=dict)


@dataclass
class BlocoMatific:
    atividades: int = 0
    estrelas: int = 0
    alunos_com_atividade: int = 0
    alunos_sem_retrato: int = 0
    questoes: None = None
    janela_efetiva: dict | None = None
    suporte: dict = field(default_factory=dict)


def resolver_janela(preset: str, ano_letivo: int, *,
                    inicio: date | None = None, fim: date | None = None,
                    hoje: date | None = None) -> Janela:
    """Converte o pedido em (inicio, fim) usando o serviço OFICIAL de períodos.

    Não existe aritmética de data aqui de propósito: ``periodos.resolver`` já
    conhece "mes", "mes_anterior", "bimestre", "bimestre_1..4", "ano_letivo" e
    "personalizado", já normaliza para o começo e o fim do dia (intervalo
    INCLUSIVO) e já devolve datetimes naive — então nenhum fuso desloca o dia do
    relatório. Criar um segundo sistema de datas aqui era o jeito mais fácil de
    o relatório e o pódio discordarem sobre o que é "setembro".
    """
    if preset not in periodos.PRESETS:
        raise RelatorioInvalido(
            f"Período {preset!r} não existe. Os aceitos são: "
            + ", ".join(periodos.PRESETS) + ".")
    if preset == "personalizado":
        if inicio is None or fim is None:
            raise RelatorioInvalido(
                "Período personalizado exige data inicial E data final.")
        if inicio > fim:
            raise RelatorioInvalido(
                f"A data inicial ({inicio.strftime('%d/%m/%Y')}) é posterior à "
                f"final ({fim.strftime('%d/%m/%Y')}) — inverta as duas.")
    ini, fi, rotulo = periodos.resolver(
        preset, hoje or date.today(), ano_letivo, inicio, fim)
    return Janela(preset=preset, inicio=ini, fim=fi, rotulo=rotulo)


def _coorte(db: Session, escola_id: int, ano: int, *,
            turma_id: int | None = None,
            aluno_id: int | None = None,
            turma_ids: list[int] | None = None) -> dict[int, dict]:
    """População ATIVA MATRICULADA no ano, já recortada pelo escopo. UMA query.

    ``turma_ids`` é o recorte de PERMISSÃO (professor restrito às turmas dele),
    não de escopo: ele se aplica também ao relatório "da escola", senão um
    professor pediria escopo=escola e receberia a escola inteira.
    """
    consulta = (
        select(Aluno.id, Aluno.nome, Turma.id, Turma.nome, Turma.ano_escolar,
               Turma.turno)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Aluno.escola_id == escola_id, Aluno.status == "ativo",
               Matricula.ano_letivo == ano))
    if turma_id is not None:
        consulta = consulta.where(Turma.id == turma_id)
    if aluno_id is not None:
        consulta = consulta.where(Aluno.id == aluno_id)
    if turma_ids is not None:
        consulta = consulta.where(Turma.id.in_(turma_ids))
    return {aid: {"nome": nome, "turma_id": tid, "turma": tnome,
                  "ano_escolar": serie, "turno": turno}
            for aid, nome, tid, tnome, serie, turno in db.execute(consulta).all()}


def _vazio_elefante() -> dict:
    return {"livros_novos": 0, "tempo_min": 0, "livros_com_atividade": 0,
            "livros_relidos": 0, "eventos_leitura": 0, "tempo_min_por_evento": None}


def _elefante(db: Session, escola_id: int, coorte: dict[int, dict],
              janela: Janela) -> tuple[BlocoElefante, dict[int, dict]]:
    """Agrega o Elefante nos DOIS eixos de data. Três queries agregadas.

    (1) ``Leitura.data`` → livro NOVO e TEMPO, o mesmo par de
        ``premiacoes._leitura_no_periodo``, coberto por ``ix_leituras_aluno_data``.
    (2) ``EventoAluno.ocorrido_em`` → livro COM ATIVIDADE (distinct) e eventos,
        coberto por ``ix_eventos_aluno_ocorrido``.
    (3) o cruzamento dos dois → RELIDO: livro com evento na janela cuja
        ``Leitura`` está datada FORA dela. É o número que explica por que (1) e
        (2) diferem — sem ele a tela parece ter dois totais contraditórios.

    O tempo NÃO vem de ``tempo_segundos``: ver ``MOTIVO_ELEFANTE_TEMPO_EVENTO``.
    """
    por_aluno: dict[int, dict] = {}
    bloco = BlocoElefante()
    bloco.suporte = {
        "livros_novos": {
            "campo": "Leitura.data (COUNT)",
            "classificacao": "SUPORTADO",
            "por_que": "é o MESMO campo e filtro da premiação oficial 'Mais "
                       "Livros' (premiacoes._leitura_no_periodo), então o "
                       "relatório não discorda do pódio",
            "ressalva": "Leitura.data é o lastReadWhen da PRIMEIRA importação "
                        "daquele livro e nunca é atualizada (§35): releitura "
                        "não entra aqui — entra em livros_relidos",
        },
        "tempo_min": {
            "campo": "Leitura.tempo_leitura_min (SUM, filtrado por Leitura.data)",
            "classificacao": "SUPORTADO COM RESSALVA",
            "por_que": "é o MESMO campo da premiação oficial 'Mais Tempo'",
            "ressalva": "o campo é NULLABLE ('quando o relatório informa') e "
                        "nulo entra como 0, então o total do período é um PISO "
                        "em relação ao acumulado do retrato",
        },
        "livros_com_atividade": {
            "campo": "EventoAluno.ocorrido_em (COUNT DISTINCT livro_id)",
            "classificacao": "SUPORTADO",
            "por_que": "o espelho registra TODA linha do relatório, inclusive a "
                       "releitura que a §35 descarta, com o instante da plataforma",
            "ressalva": "duas leituras do mesmo livro no MESMO MINUTO colapsam "
                        "num evento (uq_evento_natural inclui o minuto): "
                        "eventos_leitura é um PISO, não contagem de sessões",
        },
        "tempo_min_por_evento": {
            "classificacao": "NÃO SUPORTADO",
            "por_que": MOTIVO_ELEFANTE_TEMPO_EVENTO,
        },
    }
    if not coorte:
        return bloco, por_aluno

    # (1) Leitura.data — livro novo + tempo (o par da premiação oficial).
    leituras = (
        select(Leitura.aluno_id, func.count(),
               func.coalesce(func.sum(Leitura.tempo_leitura_min), 0))
        .where(Leitura.escola_id == escola_id,
               Leitura.aluno_id.in_(coorte.keys()))
        .group_by(Leitura.aluno_id))
    if janela.inicio is not None:
        leituras = leituras.where(Leitura.data >= janela.inicio)
    if janela.fim is not None:
        leituras = leituras.where(Leitura.data <= janela.fim)
    for aid, livros, minutos in db.execute(leituras).all():
        alvo = por_aluno.setdefault(aid, _vazio_elefante())
        alvo["livros_novos"] = int(livros or 0)
        alvo["tempo_min"] = int(minutos or 0)
        bloco.livros_novos += int(livros or 0)
        bloco.tempo_min += int(minutos or 0)
        if livros:
            bloco.alunos_com_livro_novo += 1

    # (2) EventoAluno.ocorrido_em — atividade real, inclusive releitura.
    eventos = (
        select(EventoAluno.aluno_id,
               func.count(func.distinct(EventoAluno.livro_id)),
               func.count())
        .where(EventoAluno.escola_id == escola_id,
               EventoAluno.plataforma == "elefante",
               EventoAluno.tipo_evento == "leitura",
               EventoAluno.aluno_id.in_(coorte.keys()))
        .group_by(EventoAluno.aluno_id))
    if janela.inicio is not None:
        eventos = eventos.where(EventoAluno.ocorrido_em >= janela.inicio)
    if janela.fim is not None:
        eventos = eventos.where(EventoAluno.ocorrido_em <= janela.fim)
    for aid, livros, quantos in db.execute(eventos).all():
        alvo = por_aluno.setdefault(aid, _vazio_elefante())
        alvo["livros_com_atividade"] = int(livros or 0)
        alvo["eventos_leitura"] = int(quantos or 0)
        bloco.livros_com_atividade += int(livros or 0)
        bloco.eventos_leitura += int(quantos or 0)

    # (3) RELIDO: evento na janela, Leitura datada fora dela.
    for aid, relidos in _relidos(db, escola_id, coorte, janela):
        por_aluno.setdefault(aid, _vazio_elefante())["livros_relidos"] = relidos
        bloco.livros_relidos += relidos

    bloco.alunos_com_atividade = len(por_aluno)
    return bloco, por_aluno


def _relidos(db: Session, escola_id: int, coorte: dict[int, dict],
             janela: Janela) -> list[tuple[int, int]]:
    """(aluno_id, livros com evento NA janela cuja ``Leitura`` está fora dela).

    Janela aberta nas duas pontas (preset "tudo") não tem "fora": devolve vazio.
    Livro com evento mas SEM ``Leitura`` (linha que o importador rejeitou por
    nível fora do vocabulário) não entra — o join é interno de propósito, para
    não afirmar releitura de um livro que o sistema nunca registrou.
    """
    if janela.inicio is None and janela.fim is None:
        return []
    atividade = (
        select(EventoAluno.aluno_id.label("aluno_id"),
               EventoAluno.livro_id.label("livro_id"))
        .where(EventoAluno.escola_id == escola_id,
               EventoAluno.plataforma == "elefante",
               EventoAluno.tipo_evento == "leitura",
               EventoAluno.livro_id.isnot(None),
               EventoAluno.aluno_id.in_(coorte.keys())))
    if janela.inicio is not None:
        atividade = atividade.where(EventoAluno.ocorrido_em >= janela.inicio)
    if janela.fim is not None:
        atividade = atividade.where(EventoAluno.ocorrido_em <= janela.fim)
    sub = atividade.distinct().subquery()
    fora = []
    if janela.inicio is not None:
        fora.append(Leitura.data < janela.inicio)
    if janela.fim is not None:
        fora.append(Leitura.data > janela.fim)
    consulta = (
        select(Leitura.aluno_id, func.count(func.distinct(Leitura.livro_id)))
        .join(sub, (sub.c.aluno_id == Leitura.aluno_id)
              & (sub.c.livro_id == Leitura.livro_id))
        .where(Leitura.escola_id == escola_id, or_(*fora))
        .group_by(Leitura.aluno_id))
    return [(aid, int(n or 0)) for aid, n in db.execute(consulta).all()]


def _diferenca_de_retratos(serie: list, janela: Janela, campos: tuple[str, ...]
                           ) -> dict[str, int] | None:
    """Ganho de contadores ACUMULADOS entre o primeiro e o último retrato da
    janela. ``None`` quando não há retrato na janela — ausência não é zero.

    É a mesma ideia de ``matific_destaque.ganho_no_periodo``, aplicada aos
    contadores do Elefante que só existem como acumulado no retrato.
    """
    dentro = [s for s in serie if janela.contem(_sem_tz(s.data_referencia))]
    if not dentro:
        return None
    dentro.sort(key=lambda s: (_sem_tz(s.data_referencia), s.id))
    antes = [s for s in serie
             if janela.inicio is not None
             and _sem_tz(s.data_referencia) < janela.inicio]
    antes.sort(key=lambda s: (_sem_tz(s.data_referencia), s.id))
    base = antes[-1] if antes else (dentro[0] if janela.inicio is not None else None)
    atual = dentro[-1]
    saida = {}
    for campo in campos:
        fim = int(getattr(atual, campo, 0) or 0)
        ini = int(getattr(base, campo, 0) or 0) if base is not None else 0
        saida[campo] = max(0, fim - ini)
    # A janela EFETIVA é a das COLETAS, não a pedida: sai junto do número para
    # o relatório não mentir sobre o recorte (mesma auditoria que /premiacoes
    # expõe em data_base/data_atual).
    saida["_data_base"] = _sem_tz(base.data_referencia) if base is not None else None
    saida["_data_atual"] = _sem_tz(atual.data_referencia)
    return saida


def _sem_tz(momento: datetime) -> datetime:
    return momento.replace(tzinfo=None) if momento.tzinfo is not None else momento


def _retratos(db: Session, escola_id: int, coorte: dict[int, dict], modelo
              ) -> dict[int, list]:
    """Série de retratos por aluno. UMA query; sem N+1."""
    if not coorte:
        return {}
    series: dict[int, list] = {}
    for snap in db.execute(
            select(modelo).where(modelo.escola_id == escola_id,
                                 modelo.aluno_id.in_(coorte.keys()))
            .order_by(modelo.aluno_id, modelo.data_referencia, modelo.id)).scalars():
        series.setdefault(snap.aluno_id, []).append(snap)
    return series


def _matific(db: Session, escola_id: int, coorte: dict[int, dict], janela: Janela,
             ano_letivo: int) -> tuple[BlocoMatific, dict[int, dict]]:
    """Agrega o Matific pelo GANHO entre retratos, com a função oficial."""
    bloco = BlocoMatific()
    por_aluno: dict[int, dict] = {}
    bloco.suporte = {
        "campo": "SnapshotMatific.data_referencia (diferença de acumulados)",
        "classificacao": "SUPORTADO COM RESSALVA",
        "por_que": "o Matific entrega contador ACUMULADO do ano, não evento "
                   "datado: a atividade do período é o acumulado do fim menos o "
                   "de antes do início (mesma regra de matific_destaque, usada "
                   "pelas premiações)",
        "ressalva": "sem retrato DENTRO da janela o aluno não é elegível — "
                    "ausência não é zero, e esses alunos são contados em "
                    "alunos_sem_retrato",
        "questoes": {"classificacao": "NÃO SUPORTADO",
                     "por_que": MOTIVO_MATIFIC_QUESTOES},
    }
    if not coorte:
        return bloco, por_aluno
    series = _retratos(db, escola_id, coorte, SnapshotMatific)
    bases: list[datetime] = []
    atuais: list[datetime] = []
    for aid in coorte:
        ganho = matific_destaque.ganho_no_periodo(
            series.get(aid, []), janela.inicio, janela.fim, ano_letivo)
        if ganho is None:
            bloco.alunos_sem_retrato += 1
            continue
        if ganho.data_base is not None:
            bases.append(_sem_tz(ganho.data_base))
        if ganho.data_atual is not None:
            atuais.append(_sem_tz(ganho.data_atual))
        atividades = int(ganho.atividades or 0)
        estrelas = int(ganho.estrelas or 0)
        por_aluno[aid] = {"atividades": atividades, "estrelas": estrelas,
                          "data_base": (ganho.data_base.isoformat()
                                        if ganho.data_base else None),
                          "data_atual": (ganho.data_atual.isoformat()
                                         if ganho.data_atual else None)}
        bloco.atividades += atividades
        bloco.estrelas += estrelas
        if atividades or estrelas:
            bloco.alunos_com_atividade += 1
    bloco.janela_efetiva = _janela_efetiva(bases, atuais)
    return bloco, por_aluno


def _elefante_questoes(db: Session, escola_id: int, coorte: dict[int, dict],
                       janela: Janela, bloco: BlocoElefante,
                       por_aluno: dict[int, dict]) -> None:
    """Questões do Elefante: só existem como acumulado no retrato."""
    series = _retratos(db, escola_id, coorte, SnapshotElefante)
    tentativas = acertos = 0
    sem = 0
    bases: list[datetime] = []
    atuais: list[datetime] = []
    for aid in coorte:
        ganho = _diferenca_de_retratos(
            series.get(aid, []), janela,
            ("questoes_tentativas", "questoes_acertos"))
        if ganho is None:
            sem += 1
            continue
        tentativas += ganho["questoes_tentativas"]
        acertos += ganho["questoes_acertos"]
        if ganho["_data_base"] is not None:
            bases.append(ganho["_data_base"])
        atuais.append(ganho["_data_atual"])
        # SÓ entra em `por_aluno` quem teve questão DE VERDADE na janela. Ter
        # retrato não é ter atividade: toda sincronização grava retrato de todo
        # mundo, então contar "tem retrato" como "tem atividade" faria
        # `alunos_com_atividade` empatar com a escola inteira — e a diretora
        # concluiria que ninguém está parado.
        if not (ganho["questoes_tentativas"] or ganho["questoes_acertos"]):
            continue
        alvo = por_aluno.setdefault(aid, _vazio_elefante())
        alvo["questoes_tentativas"] = ganho["questoes_tentativas"]
        alvo["questoes_acertos"] = ganho["questoes_acertos"]
    # Recontado: a coorte com sinal real agora inclui quem só teve questão.
    bloco.alunos_com_atividade = len(por_aluno)
    bloco.questoes_tentativas = tentativas
    bloco.questoes_acertos = acertos
    bloco.alunos_sem_retrato = sem
    bloco.janela_efetiva_questoes = _janela_efetiva(bases, atuais)
    bloco.suporte["questoes"] = {
        "campo": "SnapshotElefante.questoes_* (diferença entre retratos)",
        "classificacao": "SUPORTADO COM RESSALVA",
        "por_que": "questões só existem como contador acumulado no retrato; a "
                   "do período é a diferença entre retratos",
        "ressalva": "exige retrato dentro da janela (sem ele o aluno entra em "
                    "alunos_sem_retrato, não conta zero) e a janela EFETIVA é a "
                    "das coletas — veja janela_efetiva_questoes",
    }


def _janela_efetiva(bases: list[datetime], atuais: list[datetime]) -> dict | None:
    """O intervalo que o número REALMENTE cobre, quando ele vem de retratos.

    A coleta anterior pode ser bem antes do início pedido; nesse caso o ganho
    inclui, em silêncio, o que veio antes. Em vez de esconder isso, o relatório
    publica a ponta mais antiga e a mais recente que entraram na conta.
    """
    if not atuais:
        return None
    return {"data_base_mais_antiga": min(bases).isoformat() if bases else None,
            "data_base_mais_recente": max(bases).isoformat() if bases else None,
            "data_atual_mais_antiga": min(atuais).isoformat(),
            "data_atual_mais_recente": max(atuais).isoformat(),
            "observacao": "o número vem da diferença entre COLETAS; este é o "
                          "intervalo real que ele cobre, que pode ser mais "
                          "largo que o período pedido"}


def gerar(db: Session, escola_id: int, *, preset: str,
          plataformas: tuple[str, ...] | list[str],
          escopo: str = "escola",
          inicio: date | None = None, fim: date | None = None,
          turma_id: int | None = None, aluno_id: int | None = None,
          turma_ids: list[int] | None = None,
          hoje: date | None = None) -> dict:
    """O relatório. Só leitura; nada é gravado e nada do motor é alterado."""
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise RelatorioInvalido(f"Escola {escola_id} não existe.")
    if escopo not in ESCOPOS:
        raise RelatorioInvalido(
            f"Escopo {escopo!r} não existe. Use: " + ", ".join(ESCOPOS) + ".")
    plats = tuple(dict.fromkeys(plataformas or ()))
    if not plats:
        raise RelatorioInvalido(
            "Escolha ao menos uma plataforma: " + " ou ".join(PLATAFORMAS) + ".")
    desconhecidas = [p for p in plats if p not in PLATAFORMAS]
    if desconhecidas:
        raise RelatorioInvalido(
            f"Plataforma(s) {desconhecidas} não existe(m). Use: "
            + ", ".join(PLATAFORMAS) + ".")
    if escopo == "turma" and turma_id is None:
        raise RelatorioInvalido("O escopo 'turma' exige turma_id.")
    if escopo == "aluno" and aluno_id is None:
        raise RelatorioInvalido("O escopo 'aluno' exige aluno_id.")

    ano = escola.ano_letivo_ativo
    janela = resolver_janela(preset, ano, inicio=inicio, fim=fim, hoje=hoje)
    coorte = _coorte(db, escola_id, ano,
                     turma_id=turma_id if escopo in ("turma", "aluno") else None,
                     aluno_id=aluno_id if escopo == "aluno" else None,
                     turma_ids=turma_ids)

    saida: dict = {
        "escola": {"id": escola_id, "nome": escola.nome, "ano_letivo": ano},
        "periodo": {"preset": janela.preset, "rotulo": janela.rotulo,
                    "inicio": janela.inicio.isoformat() if janela.inicio else None,
                    "fim": janela.fim.isoformat() if janela.fim else None,
                    "inclusivo": True},
        "escopo": {"tipo": escopo, "turma_id": turma_id, "aluno_id": aluno_id,
                   "restrito_a_turmas": (sorted(turma_ids)
                                         if turma_ids is not None else None)},
        "plataformas": list(plats),
        "plataformas_rotulo": " + ".join(
            {"elefante": "Elefante Letrado", "matific": "Matific"}[p] for p in plats),
        "alunos": {"considerados": len(coorte)},
        "nao_suportado": [],
    }

    ele_por_aluno: dict[int, dict] = {}
    mat_por_aluno: dict[int, dict] = {}
    if "elefante" in plats:
        bloco_e, ele_por_aluno = _elefante(db, escola_id, coorte, janela)
        _elefante_questoes(db, escola_id, coorte, janela, bloco_e, ele_por_aluno)
        saida["elefante"] = {
            "livros_novos": bloco_e.livros_novos,
            "tempo_min": bloco_e.tempo_min,
            "alunos_com_livro_novo": bloco_e.alunos_com_livro_novo,
            "livros_com_atividade": bloco_e.livros_com_atividade,
            "livros_relidos": bloco_e.livros_relidos,
            "eventos_leitura": bloco_e.eventos_leitura,
            "tempo_min_por_evento": None,
            "alunos_com_atividade": bloco_e.alunos_com_atividade,
            "questoes_tentativas": bloco_e.questoes_tentativas,
            "questoes_acertos": bloco_e.questoes_acertos,
            "alunos_sem_retrato": bloco_e.alunos_sem_retrato,
            "janela_efetiva_questoes": bloco_e.janela_efetiva_questoes,
            "sem_atividade": len(coorte) - bloco_e.alunos_com_atividade,
            "suporte": bloco_e.suporte}
        saida["elefante"]["primeiro_evento_da_escola"] = _primeiro_evento(db, escola_id)
        saida["nao_suportado"].append(
            {"plataforma": "elefante", "metrica": "tempo_min_por_evento",
             "por_que": MOTIVO_ELEFANTE_TEMPO_EVENTO})
    if "matific" in plats:
        bloco_m, mat_por_aluno = _matific(db, escola_id, coorte, janela, ano)
        saida["matific"] = {
            "atividades": bloco_m.atividades, "estrelas": bloco_m.estrelas,
            "alunos_com_atividade": bloco_m.alunos_com_atividade,
            "alunos_sem_retrato": bloco_m.alunos_sem_retrato,
            "questoes": None,
            "janela_efetiva": bloco_m.janela_efetiva,
            "sem_atividade": len(coorte) - bloco_m.alunos_com_atividade,
            "suporte": bloco_m.suporte}
        saida["nao_suportado"].append(
            {"plataforma": "matific", "metrica": "questoes",
             "por_que": MOTIVO_MATIFIC_QUESTOES})
    saida["nao_suportado"].append(
        {"plataforma": "elefante", "metrica": "pontos_de_dificuldade",
         "por_que": MOTIVO_ELEFANTE_PONTOS})

    com_atividade = set(ele_por_aluno) | set(mat_por_aluno)
    saida["alunos"]["com_atividade"] = len(com_atividade)
    saida["alunos"]["sem_atividade"] = len(coorte) - len(com_atividade)

    # Distribuição por turma: derivada do que já está em memória, sem query nova.
    if escopo in ("escola", "turma"):
        turmas: dict[int, dict] = {}
        for aid, info in coorte.items():
            t = turmas.setdefault(info["turma_id"], {
                "turma_id": info["turma_id"], "turma": info["turma"],
                "ano_escolar": info["ano_escolar"], "turno": info["turno"],
                "alunos": 0, "com_atividade": 0,
                "elefante": {"livros_novos": 0, "tempo_min": 0,
                             "livros_com_atividade": 0, "livros_relidos": 0,
                             "eventos_leitura": 0},
                "matific": {"atividades": 0, "estrelas": 0}})
            t["alunos"] += 1
            if aid in com_atividade:
                t["com_atividade"] += 1
            e = ele_por_aluno.get(aid)
            if e:
                for chave in ("livros_novos", "tempo_min", "livros_com_atividade",
                              "livros_relidos", "eventos_leitura"):
                    t["elefante"][chave] += e.get(chave, 0)
            m = mat_por_aluno.get(aid)
            if m:
                t["matific"]["atividades"] += m.get("atividades", 0)
                t["matific"]["estrelas"] += m.get("estrelas", 0)
        saida["por_turma"] = sorted(turmas.values(), key=lambda x: (x["turma"] or ""))

    saida["por_aluno"] = sorted(
        ({"aluno_id": aid, "nome": info["nome"], "turma": info["turma"],
          "turma_id": info["turma_id"], "ano_escolar": info["ano_escolar"],
          "elefante": ele_por_aluno.get(aid) if "elefante" in plats else None,
          "matific": mat_por_aluno.get(aid) if "matific" in plats else None,
          "sem_atividade": aid not in com_atividade}
         for aid, info in coorte.items()),
        key=lambda x: (x["turma"] or "", x["nome"] or ""))
    return saida


def _primeiro_evento(db: Session, escola_id: int) -> str | None:
    """Data do evento mais antigo da escola — o piso do histórico consultável.

    Serve para a tela não confundir "não houve atividade" com "o espelho de
    eventos ainda não existia nesta janela" (a tabela entrou na migração 0010).
    """
    momento = db.execute(
        select(func.min(EventoAluno.ocorrido_em)).where(
            EventoAluno.escola_id == escola_id,
            EventoAluno.plataforma == "elefante")).scalar()
    return momento.isoformat() if momento is not None else None
