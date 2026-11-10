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
                           entre retratos e exigem retrato na janela. O período
                           PEDIDO é a referência; o que as coletas cobrem sai
                           ao lado, em ``cobertura_questoes`` / ``cobertura``:
                           sem coleta antes do início, a conta começa na
                           primeira coleta do período e o número NÃO é do
                           período inteiro (``status = "parcial"``) — o que veio
                           antes dessa coleta não é reconstruível, porque o
                           contador não tem data por questão.
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
from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.tempo import hoje_br, para_br
from app.models import (Aluno, Escola, EventoAluno, Importacao, Leitura, Matricula,
                        SnapshotElefante, SnapshotMatific, Turma)
from app.models.plataformas import IMPORTACAO_SEM_QUESTOES
from app.services import matific_destaque, periodos
# A faixa de anos aceita é UMA só para o relatório e para a análise (que mede com as
# funções deste módulo): o pacote ``analise`` só a declara — o ``__init__`` dele não
# importa nada daqui, então não há ciclo.
from app.services.analise import AnaliseInvalida, validar_anos

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
    cobertura_questoes: dict | None = None
    suporte: dict = field(default_factory=dict)


@dataclass
class BlocoMatific:
    atividades: int = 0
    estrelas: int = 0
    alunos_com_atividade: int = 0
    alunos_sem_retrato: int = 0
    questoes: None = None
    janela_efetiva: dict | None = None
    cobertura: dict | None = None
    suporte: dict = field(default_factory=dict)


def resolver_janela(preset: str, ano_letivo: int, *,
                    inicio: date | None = None, fim: date | None = None,
                    hoje: date | None = None) -> Janela:
    """Converte o pedido em (inicio, fim) usando o serviço OFICIAL de períodos.

    Não existe aritmética de data aqui de propósito: ``periodos.resolver`` já
    conhece "mes", "mes_anterior", "bimestre", "bimestre_1..4", "ano_letivo" e
    "personalizado", já normaliza para o começo e o fim do dia (intervalo
    INCLUSIVO, até 23:59:59.999999 — equivale ao limite exclusivo da 0h do dia
    seguinte) e devolve datetimes naive EM DIAS DE BRASÍLIA. Criar um segundo
    sistema de datas aqui era o jeito mais fácil de o relatório e o pódio
    discordarem sobre o que é "setembro".

    Atenção: o instante da COLETA (``data_referencia`` dos retratos) é gravado
    em UTC. Quem compara retrato com a janela converte o retrato para Brasília
    (``_br``) — sem isso, uma coleta de 30/09 às 22h (01/10 01h UTC) cairia
    fora de setembro.

    As datas informadas passam pela MESMA faixa da análise (``validar_anos``,
    anos 2000–2100) antes de qualquer conta, em qualquer preset: fora dela o
    pedido não tem sentido e a aritmética nem existe — a borda do início menos
    ``TOLERANCIA_BORDA`` estoura no ano 1 e o fim mais 1 µs estoura em
    31/12/9999. Antes, isso virava 500 no meio da medição (com a coorte já
    lida); agora é ``RelatorioInvalido`` (422 na rota, no JSON e no PDF).
    """
    if preset not in periodos.PRESETS:
        raise RelatorioInvalido(
            f"Período {preset!r} não existe. Os aceitos são: "
            + ", ".join(periodos.PRESETS) + ".")
    try:
        validar_anos(inicio=inicio, fim=fim)
    except AnaliseInvalida as exc:
        raise RelatorioInvalido(str(exc)) from exc
    if preset == "personalizado":
        if inicio is None or fim is None:
            raise RelatorioInvalido(
                "Período personalizado exige data inicial E data final.")
        if inicio > fim:
            raise RelatorioInvalido(
                f"A data inicial ({inicio.strftime('%d/%m/%Y')}) é posterior à "
                f"final ({fim.strftime('%d/%m/%Y')}) — inverta as duas.")
    # Dia de BRASÍLIA (não o relógio do servidor, em UTC): depois das 21h do último
    # dia do mês, `date.today()` já virava o mês e "mês anterior" pulava um mês.
    ini, fi, rotulo = periodos.resolver(
        preset, hoje or hoje_br(), ano_letivo, inicio, fim)
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


# Uma coleta a até ``TOLERANCIA_BORDA`` de uma borda do período é a MEDIDA dessa
# borda. A agenda diária roda à 0h de Brasília (03:00 UTC) e grava o instante em
# que a importação termina — medido em produção (backup de 05/10): 25.764
# retratos do Elefante entre 00:05 e 00:50 —, e esse retrato mede o dia
# ANTERIOR. Sem a tolerância, a coleta de 01/09 00:10 seria "depois do início"
# e a de 01/10 00:10 "depois do fim": setembro sairia com um dia trocado (31/08
# dentro, 30/09 fora).
TOLERANCIA_BORDA = timedelta(hours=1)
# Primeira coleta "zerada" só prova contador zero se a conta for de fato nova:
# os importadores gravam 0 nas questões quando o relatório não traz a coluna
# (``importacoes._importar_elefante_resumo``) — com livros ou tempo já
# contados, esse 0 é "desconhecido", não medição.
_CONTA_NOVA_EXIGE_ZERO = ("livros_unicos", "tempo_leitura_min")
# Linhas da MESMA execução: a sync grava o resumo da turma e, segundos depois,
# as leituras (dois caminhos do importador, duas linhas). Contam como UMA
# coleta — sem isso, uma coleta só passava por "intervalo medido" (de 16:53:12
# a 16:53:40). E vale a PRIMEIRA: só o resumo traz as questões da plataforma; a
# linha de leituras COPIA as do retrato mais recente
# (``importacoes._importar_elefante_leituras``) — que, numa revisão reaplicada
# com a data congelada, é de OUTRO dia. Desde a correção A2 §3.18 as leituras do
# MESMO dia reescrevem o retrato do resumo no lugar (uma linha só); a regra
# continua valendo para as linhas gravadas antes dela.
_MESMA_COLETA = timedelta(minutes=15)


@dataclass
class _Ponto:
    """Uma COLETA (a primeira linha da execução) e o instante dela."""
    retrato: object
    utc: datetime   # UTC sem fuso — o que se devolve (a tela e o PDF convertem)
    br: datetime    # o mesmo instante em Brasília sem fuso — o que se compara


def _pontos(serie: list) -> list[_Ponto]:
    """Coletas em ordem, uma por execução.

    O instante é a ``data_referencia``. Limitação CONHECIDA dos retratos gravados
    antes da revisão e93: reimportar no mesmo dia reescrevia os valores no lugar
    sem atualizar a data (``importacoes._importar_elefante_resumo``) — nesses
    retratos o valor é mais novo que a data. Hoje o "mesmo dia" do importador é o
    dia de BRASÍLIA (``importacoes._mesmo_dia``; até a e97 era o dia UTC) e a data
    acompanha o valor novo (``importacoes._avancar_data``). Não há como distinguir
    aquele caso antigo, pelo dado gravado, da reaplicação de uma revisão de
    identidade (linha nova, data congelada e valores da coleta original, que estão
    certos)."""
    ordem = sorted(serie, key=lambda s: (_sem_tz(s.data_referencia), s.id))
    pontos: list[_Ponto] = []
    for s in ordem:
        utc = _sem_tz(s.data_referencia)
        ponto = _Ponto(s, utc, _br(utc))
        if pontos and utc - pontos[-1].utc <= _MESMA_COLETA:
            continue             # mesma execução: fica a primeira linha (o resumo)
        pontos.append(ponto)
    return pontos


def _periodo_aberto(janela: Janela, hoje: date | None) -> bool:
    """O período ainda não acabou (inclui hoje, ou não tem fim)."""
    return janela.fim is None or (hoje or hoje_br()) <= janela.fim.date()


def _zerado(retrato, campos: tuple[str, ...]) -> bool:
    return not any(int(getattr(retrato, c, 0) or 0)
                   for c in (*campos, *_CONTA_NOVA_EXIGE_ZERO))


def _diferenca_de_retratos(serie: list, janela: Janela, campos: tuple[str, ...], *,
                           hoje: date | None = None) -> dict | None:
    """Ganho de contadores ACUMULADOS no período PEDIDO, e o que ele cobre.

    O contador do Elefante é acumulado (vitalício: a sync pede LIFETIME) e não
    tem data por questão. O do período é ``acumulado no fim − acumulado no
    início``, e cada borda só é conhecida onde houve COLETA. Instantes em
    BRASÍLIA (a janela vem em dias de Brasília; a coleta é gravada em UTC).

    BORDA DO INÍCIO (``_inicio``):
      * ``exato``    — coleta a até ``TOLERANCIA_BORDA`` do início: a medida dele;
      * ``antes``    — só há coleta bem antes: o número INCLUI o que veio entre
        ela e o início (``_antecedencia``) — período AMPLIADO, nunca "completo";
      * ``contador`` — o contador parte do zero (``todo o histórico``, ou conta
        nova provadamente zerada na primeira coleta);
      * ``depois``   — sem coleta no início nem antes: a conta começa na
        primeira coleta do período, e o que veio antes dela NÃO ENTRA (não é
        reconstruível). Nunca se zera a base às cegas: num contador vitalício,
        a vida inteira viraria "ganho do período".
    BORDA DO FIM (``_fim``):
      * ``exato``        — coleta a até ``TOLERANCIA_BORDA`` do fim: a medida dele;
      * ``em_andamento`` — período que inclui hoje: vale a coleta mais recente,
        se ela é de hoje;
      * ``antes``        — a última coleta é anterior ao fim: o que veio depois
        dela NÃO ENTRA.

    ``None`` quando não há retrato no período — ausência não é zero. Com uma
    coleta só e nenhuma base, não há diferença a medir: ``_medido = False`` (o
    chamador não soma isso como zero).
    """
    pontos = _pontos(serie)
    if not pontos:
        return None
    tol = TOLERANCIA_BORDA
    ini = janela.inicio
    dentro = [p for p in pontos if janela.contem(p.br)]
    aberto = _periodo_aberto(janela, hoje)
    medida_fim = None
    if not aberto:
        fim_excl = janela.fim + timedelta(microseconds=1)
        perto = [p for p in pontos if abs(p.br - fim_excl) <= tol]
        if perto:
            medida_fim = min(perto, key=lambda p: (abs(p.br - fim_excl), p.br))
    if not dentro and medida_fim is None:
        return None

    if medida_fim is not None:
        atual, fim_estado = medida_fim, "exato"
    else:
        atual = dentro[-1]
        hoje_ = hoje or hoje_br()
        fim_estado = "em_andamento" if aberto and atual.br.date() >= hoje_ else "antes"

    antecedencia = None
    if ini is None:
        base, ini_estado = None, "contador"      # todo o histórico: o acumulado inteiro
    else:
        perto = [p for p in pontos if abs(p.br - ini) <= tol and p.br <= atual.br]
        antes = [p for p in pontos if p.br < ini - tol]
        primeiro = dentro[0] if dentro else atual
        if perto:
            base = min(perto, key=lambda p: (abs(p.br - ini), p.br))
            ini_estado = "exato"
        elif antes:
            base, ini_estado = antes[-1], "antes"
            antecedencia = ini - base.br
        elif _zerado(primeiro.retrato, campos):
            base, ini_estado = None, "contador"  # conta nova: era zero no início
        else:
            base, ini_estado = primeiro, "depois"

    saida: dict = {}
    regrediu = False
    for campo in campos:
        fim_v = int(getattr(atual.retrato, campo, 0) or 0)
        ini_v = int(getattr(base.retrato, campo, 0) or 0) if base is not None else 0
        regrediu = regrediu or fim_v < ini_v
        saida[campo] = max(0, fim_v - ini_v)
    # Acumulado não diminui: se diminuiu, a série mistura contas (fusão,
    # colisão de identidade) ou foi recontada. Zerar e somar o outro campo
    # inventaria número — o chamador tira o aluno da conta e declara.
    saida["_regrediu"] = regrediu
    saida["_data_base"] = base.utc if base is not None else None
    saida["_data_atual"] = atual.utc
    saida["_inicio"] = ini_estado
    saida["_fim"] = fim_estado
    saida["_antecedencia"] = antecedencia
    # O que a base já acumulava (de TODAS as épocas): numa base "depois", é o
    # histórico que a primeira coleta do período trouxe sem dizer quando.
    saida["_base_tentativas"] = (int(getattr(base.retrato, campos[0], 0) or 0)
                                 if base is not None else 0)
    saida["_medido"] = base is not atual
    return saida


def _sem_coleta_no_periodo(serie: list, janela: Janela, hoje: date | None) -> bool:
    """O aluno era coletado antes E depois do período, mas não DENTRO dele —
    lacuna, não "aluno sem dado". Só em período fechado com início."""
    if janela.inicio is None or _periodo_aberto(janela, hoje):
        return False
    instantes = [p.br for p in _pontos(serie)]
    return (any(b < janela.inicio for b in instantes)
            and any(b > janela.fim for b in instantes))


def _coleta_interrompida(serie: list, janela: Janela) -> bool:
    """O aluno ERA coletado antes do período e não tem nenhuma coleta que entre
    na conta dele (nem dentro, nem medindo o fim) — e não é a lacuna de
    :func:`_sem_coleta_no_periodo` (que exige coleta depois, em período
    fechado). É a coleta que PAROU ou falhou para ele: a turma que o relatório
    do Elefante não trouxe, a agenda que parou antes do bimestre, o "este mês"
    sem coleta desde o dia 1º. Sem isto, o número da escola saía "completo"
    somando só quem foi coletado — subcontagem sem aviso. A sync grava retrato
    de todo aluno do relatório a cada coleta (com ou sem atividade), então não
    ter retrato é falta de COLETA, não falta de leitura."""
    if janela.inicio is None:
        return False
    return any(p.br < janela.inicio for p in _pontos(serie))


def _sem_tz(momento: datetime) -> datetime:
    return momento.replace(tzinfo=None) if momento.tzinfo is not None else momento


def _br(momento: datetime) -> datetime:
    """Instante de coleta (gravado em UTC; naive = UTC) no relógio de
    Brasília, sem fuso — a mesma régua da janela pedida."""
    return para_br(momento).replace(tzinfo=None)


def _fim_efetivo(janela: Janela, hoje: date | None) -> date | None:
    """Último dia que o período PODE ter: o fim pedido, ou hoje num período em
    andamento ("este mês" até hoje; "todo o histórico" até hoje)."""
    hoje_ = hoje or hoje_br()
    return hoje_ if janela.fim is None else min(janela.fim.date(), hoje_)


def _cobertura(janela: Janela, hoje: date | None, intervalos: list[dict],
               sem_intervalo: int, *, regra: str = "diferenca_de_coletas",
               so_inicio: int = 0, regrediu: int = 0,
               sem_coleta_no_periodo: int = 0,
               coleta_interrompida: int = 0,
               turmas_sem_coleta: list[dict] | None = None,
               acumulado_na_primeira_coleta: int | None = None,
               questoes_nao_vieram: int = 0) -> dict | None:
    """PERÍODO PEDIDO × COBERTURA DAS COLETAS de um número que vem de diferença
    entre retratos. ``None`` quando ninguém tem retrato no período.

    ``intervalos``: um por aluno MEDIDO, com ``base``/``atual`` (UTC) e os
    estados das bordas (``inicio``: exato|antes|contador|depois|ano_letivo|
    regra_oficial; ``fim``: exato|em_andamento|antes|regra_oficial) e, no
    Elefante, ``fim_sem_questoes`` (S9: o fim falta porque a coleta que o mediria
    veio sem as questões — conta em ``questoes_nao_vieram``, não em
    ``alunos_sem_fim``).

    ``status``:
      * ``completa``      — todo aluno medido nas duas bordas;
      * ``ampliada``      — cobre o período, mas a base de algum aluno é bem
        anterior ao início: o número INCLUI atividade de antes dele;
      * ``parcial``       — falta parte do período para algum aluno (sem
        medida no início, ou última coleta antes do fim), ou há alunos sem
        intervalo medido, ou há aluno cuja coleta PAROU antes do período
        (``coleta_interrompida``), ou há turma já coletada sem nenhuma coleta na
        janela (``turmas_sem_coleta``) — nunca "completa" somando só quem foi
        coletado; também quando a coleta de algum aluno no período veio SEM as
        questões (``questoes_nao_vieram``, S9): ela não mede a borda, e a conta
        dele vai só até a coleta anterior (ou fica sem número);
      * ``regra_oficial`` — (Matific) o número é o da regra oficial e as bordas
        não são verificadas aqui: nunca se afirma "completo";
      * ``sem_intervalo`` — ninguém tem duas pontas: não há número.
    Datas do PERÍODO em dias de Brasília; instantes de COLETA em UTC.
    """
    if not (intervalos or sem_intervalo or regrediu or sem_coleta_no_periodo
            or coleta_interrompida or questoes_nao_vieram):
        return None
    sem_inicio = [i for i in intervalos if i["inicio"] in ("depois", "ano_letivo")]
    sem_fim = [i for i in intervalos if i["fim"] == "antes"]
    # "A última coleta é de X" (``alunos_sem_fim``, ``coleta_fim_mais_cedo``): só quem
    # NÃO tem coleta depois de X no período. O fim que falta porque a coleta seguinte
    # veio sem as questões (S9, ``fim_sem_questoes``) já é dito por
    # ``alunos_questoes_nao_vieram`` — cada aluno numa causa só.
    ultima_antes = [i for i in sem_fim if not i.get("fim_sem_questoes")]
    ampliados = [i for i in intervalos if i["inicio"] == "antes"]
    oficiais = [i for i in intervalos if "regra_oficial" in (i["inicio"], i["fim"])]
    completos = [i for i in intervalos
                 if i["inicio"] in ("exato", "contador")
                 and i["fim"] in ("exato", "em_andamento")]
    bases = [i["base"] for i in intervalos if i["base"] is not None]
    atuais = [i["atual"] for i in intervalos]
    if not intervalos:
        status = "sem_intervalo"
    elif (sem_inicio or sem_fim or sem_intervalo or regrediu or sem_coleta_no_periodo
          or coleta_interrompida or turmas_sem_coleta or questoes_nao_vieram):
        status = "parcial"
    elif oficiais:
        status = "regra_oficial"
    elif ampliados:
        status = "ampliada"
    else:
        status = "completa"
    antecedencias = [i["antecedencia"] for i in ampliados if i.get("antecedencia")]
    fim_efetivo = _fim_efetivo(janela, hoje)
    return {
        "regra": regra,
        "periodo_inicio": janela.inicio.date().isoformat() if janela.inicio else None,
        "periodo_fim": janela.fim.date().isoformat() if janela.fim else None,
        "periodo_fim_efetivo": fim_efetivo.isoformat() if fim_efetivo else None,
        "em_andamento": _periodo_aberto(janela, hoje),
        "coleta_inicio": min(bases).isoformat() if bases else None,
        "coleta_inicio_mais_tardio": (max(i["base"] for i in sem_inicio
                                          if i["base"] is not None).isoformat()
                                      if any(i["base"] for i in sem_inicio) else None),
        "coleta_fim": max(atuais).isoformat() if atuais else None,
        "coleta_fim_mais_cedo": (min(i["atual"] for i in ultima_antes).isoformat()
                                 if ultima_antes else
                                 (min(atuais).isoformat() if atuais else None)),
        "inicio_coberto": bool(intervalos) and not sem_inicio,
        "fim_coberto": bool(intervalos) and not sem_fim,
        "inclui_antes_do_inicio": bool(ampliados),
        # (Matific) base nula numa janela que começa antes de 01/01: o contador é
        # do ano, então o que veio antes da virada não entra.
        "inicio_do_contador_anual": any(i["inicio"] == "ano_letivo" for i in intervalos),
        "antecedencia_max_horas": (round(max(antecedencias).total_seconds() / 3600)
                                   if antecedencias else None),
        "status": status,
        "completa": status == "completa",
        "alunos_cobertura_completa": len(completos),
        "alunos_cobertura_parcial": len({id(i) for i in (*sem_inicio, *sem_fim)}),
        "alunos_sem_inicio": len(sem_inicio),
        "alunos_sem_fim": len(ultima_antes),
        "alunos_ampliados": len(ampliados),
        "alunos_sem_intervalo": sem_intervalo,
        # dos "sem intervalo": a única coleta do período é a que mede o INÍCIO
        # (ex.: dia 1º, antes da coleta seguinte) — "nenhuma antes" seria falso
        "alunos_sem_intervalo_so_inicio": so_inicio,
        "alunos_contador_regrediu": regrediu,
        "alunos_sem_coleta_no_periodo": sem_coleta_no_periodo,
        # coletados ANTES do período e sem nenhuma coleta que entre na conta:
        # a coleta parou/falhou para eles (fora da conta, e o número é parcial)
        "alunos_coleta_interrompida": coleta_interrompida,
        # turmas do recorte sem NENHUMA coleta na janela (nenhum aluno com
        # retrato no período): o número da escola não as inclui
        "turmas_sem_coleta": list(turmas_sem_coleta or []),
        # o denominador de "para N aluno(s)": quem tem intervalo medido
        "alunos_medidos": len(intervalos),
        # (Elefante) soma do contador vitalício na primeira coleta de quem NÃO
        # tem coleta no início: o histórico existe na plataforma, mas o
        # contador não diz quando foi feito — por isso fica fora da conta.
        "acumulado_na_primeira_coleta": acumulado_na_primeira_coleta,
        # (Elefante, S9) alunos cuja coleta no período veio SEM as questões (a
        # plataforma deixou de mandá-las): ela não serve de borda, e a conta deles
        # vai só até a coleta anterior — ou fica sem número
        "alunos_questoes_nao_vieram": questoes_nao_vieram,
    }


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


def _retratos_das_questoes(db: Session, escola_id: int, coorte: dict[int, dict]
                           ) -> tuple[dict[int, list], dict[int, list]]:
    """(retratos que MEDEM as questões, retratos que não medem) do Elefante, por
    aluno. UMA query.

    Não medem: os gravados por uma sincronização em que as questões não vieram da
    plataforma (S9; ``Importacao.status == IMPORTACAO_SEM_QUESTOES``). Quem leu um
    livro novo ganhou ali um retrato com as questões da coleta ANTERIOR e a data de
    agora: usado como borda, ele dava "0 no período" com cobertura completa."""
    if not coorte:
        return {}, {}
    validos: dict[int, list] = {}
    sem_questoes: dict[int, list] = {}
    for snap, status in db.execute(
            select(SnapshotElefante, Importacao.status)
            .outerjoin(Importacao, Importacao.id == SnapshotElefante.importacao_id)
            .where(SnapshotElefante.escola_id == escola_id,
                   SnapshotElefante.aluno_id.in_(coorte.keys()))
            .order_by(SnapshotElefante.aluno_id, SnapshotElefante.data_referencia,
                      SnapshotElefante.id)).all():
        alvo = sem_questoes if status == IMPORTACAO_SEM_QUESTOES else validos
        alvo.setdefault(snap.aluno_id, []).append(snap)
    return validos, sem_questoes


def _bordas(ganho: dict | None) -> tuple | None:
    """O que decide a conta de um aluno: as duas coletas e o estado das bordas."""
    if ganho is None:
        return None
    return (ganho["_data_base"], ganho["_data_atual"], ganho["_inicio"], ganho["_fim"],
            ganho["_medido"])


def _matific(db: Session, escola_id: int, coorte: dict[int, dict], janela: Janela,
             ano_letivo: int, hoje: date | None = None
             ) -> tuple[BlocoMatific, dict[int, dict]]:
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
    intervalos: list[dict] = []
    zero_oficial = 0
    ini_ano = matific_destaque.janela_ano_letivo(ano_letivo)[0]
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
            intervalo = _intervalo_matific(janela, ini_ano, ganho)
            if intervalo is None:
                zero_oficial += 1        # uma coleta só: a regra oficial dá 0
            else:
                intervalos.append(intervalo)
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
    bloco.cobertura = _cobertura(janela, hoje, intervalos, zero_oficial,
                                 regra="oficial_matific")
    return bloco, por_aluno


def _intervalo_matific(janela: Janela, ini_ano: datetime, ganho) -> dict | None:
    """O que a regra OFICIAL do Matific usou para um aluno — só a declaração.

    O NÚMERO é o de ``ganho_no_periodo`` (o mesmo das premiações) e não muda
    aqui. Só se afirma o que é CERTO: sem coleta antes do período a conta
    começou na primeira coleta dele (``depois``); com a base nula, o contador do
    ano parte de 01/01 e o que veio antes disso não entra (``ano_letivo``); o
    resto fica como ``regra_oficial`` — as bordas não são verificadas aqui, e
    "completo" nunca é afirmado. ``None`` = uma coleta só (a regra dá 0)."""
    base = _sem_tz(ganho.data_base) if ganho.data_base is not None else None
    atual = _sem_tz(ganho.data_atual)
    if base is not None and base == atual:
        return None
    if base is None:
        inicio = ("contador" if janela.inicio is not None and janela.inicio >= ini_ano
                  else "ano_letivo")
    elif janela.inicio is not None and _br(base) > janela.inicio + TOLERANCIA_BORDA:
        # a base oficial é uma coleta bem DENTRO do período (comparado em
        # Brasília): não havia coleta anterior, e o começo ficou de fora
        inicio = "depois"
    else:
        inicio = "regra_oficial"
    return {"base": base, "atual": atual, "inicio": inicio, "fim": "regra_oficial",
            "antecedencia": None}


def _elefante_questoes(db: Session, escola_id: int, coorte: dict[int, dict],
                       janela: Janela, bloco: BlocoElefante,
                       por_aluno: dict[int, dict], hoje: date | None = None) -> None:
    """Questões do Elefante: só existem como acumulado no retrato.

    O retrato gravado por uma sincronização em que as questões não vieram (S9) não
    serve de borda (``_retratos_das_questoes``): a conta do aluno vai até a coleta
    anterior, ou fica sem número. Quem foi afetado por isso — sem ele, as bordas
    seriam outras — entra em ``alunos_questoes_nao_vieram`` e a cobertura não é
    "completa"; não é contado como "sem coleta", lacuna nem "uma coleta só"."""
    campos = ("questoes_tentativas", "questoes_acertos")
    series, sem_questoes = _retratos_das_questoes(db, escola_id, coorte)
    tentativas = acertos = 0
    sem = 0
    sem_intervalo = so_inicio = regrediu = sem_coleta = acumulado_antes = 0
    interrompida = nao_vieram = 0
    bases: list[datetime] = []
    atuais: list[datetime] = []
    intervalos: list[dict] = []
    # Turmas do recorte e quantos alunos de cada uma têm retrato na janela —
    # para dizer QUAIS turmas ficaram sem coleta (o número não as inclui). Só
    # entra turma que JÁ foi coletada alguma vez: a que nunca teve retrato é
    # indistinguível de turma que não usa a plataforma (ex.: Educação Infantil).
    turmas: dict[int, dict] = {}
    for aid in coorte:
        info = coorte[aid]
        turma = turmas.setdefault(info["turma_id"], {
            "turma_id": info["turma_id"], "turma": info["turma"], "alunos": 0,
            "com_coleta": 0, "ja_coletada": False})
        turma["alunos"] += 1
        serie = series.get(aid, [])
        excluidos = sem_questoes.get(aid, [])
        turma["ja_coletada"] = turma["ja_coletada"] or bool(serie) or bool(excluidos)
        ganho = _diferenca_de_retratos(serie, janela, campos, hoje=hoje)
        # A coleta sem questões explica a conta deste aluno? Só quando, lida, ela
        # mediria o FIM que falta (a conta vai só até a coleta anterior) ou daria a
        # única diferença a medir (sem ela, ele fica fora) — é o que o aviso diz. Esse
        # aluno fica só nessa causa: não entra também em "a última coleta é de X"
        # (``fim_sem_questoes``), cuja data passaria a ser a da coleta ANTERIOR, com
        # uma mais recente no período. A que mudaria só o INÍCIO, ou um fim já medido
        # por outra coleta, não é motivo: a borda do início (ampliada, sem coleta no
        # início) é que explica o número, como para qualquer aluno.
        com = (_diferenca_de_retratos(serie + excluidos, janela, campos, hoje=hoje)
               if excluidos else None)
        afetado = com is not None and _bordas(ganho) != _bordas(com) and (
            ganho is None or not ganho["_medido"]
            or (ganho["_fim"] == "antes"
                and (ganho["_data_atual"], ganho["_fim"]) != (com["_data_atual"], com["_fim"])))
        if afetado:
            nao_vieram += 1
            turma["com_coleta"] += 1     # houve coleta no período, só sem as questões
        if ganho is None:
            if afetado:
                continue
            sem += 1
            if _sem_coleta_no_periodo(serie, janela, hoje):
                sem_coleta += 1
            elif _coleta_interrompida(serie, janela):
                interrompida += 1
            continue
        if not afetado:
            turma["com_coleta"] += 1
        if not ganho["_medido"]:
            # Uma coleta só no período e nenhuma antes: não há diferença a
            # medir. Somar 0 diria "não respondeu nada" — é "não dá para medir".
            # (Se a outra coleta veio sem as questões, o motivo é esse, não este.)
            if not afetado:
                sem_intervalo += 1
                if ganho["_inicio"] == "exato":
                    so_inicio += 1
            continue
        if ganho["_regrediu"]:
            regrediu += 1
            continue
        intervalos.append({"base": ganho["_data_base"], "atual": ganho["_data_atual"],
                           "inicio": ganho["_inicio"], "fim": ganho["_fim"],
                           "antecedencia": ganho["_antecedencia"],
                           "fim_sem_questoes": afetado})
        tentativas += ganho["questoes_tentativas"]
        acertos += ganho["questoes_acertos"]
        if ganho["_inicio"] == "depois":
            acumulado_antes += ganho["_base_tentativas"]
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
    # Sem NENHUM intervalo medido não há número — "—", nunca 0/0.
    bloco.questoes_tentativas = tentativas if intervalos else None
    bloco.questoes_acertos = acertos if intervalos else None
    bloco.alunos_sem_retrato = sem
    bloco.janela_efetiva_questoes = _janela_efetiva(bases, atuais)
    turmas_sem_coleta = sorted(
        ({"turma_id": t["turma_id"], "turma": t["turma"], "alunos": t["alunos"]}
         for t in turmas.values() if t["ja_coletada"] and not t["com_coleta"]),
        key=lambda t: ((t["turma"] or "").casefold(), t["turma_id"]))
    bloco.cobertura_questoes = _cobertura(janela, hoje, intervalos, sem_intervalo,
                                          so_inicio=so_inicio, regrediu=regrediu,
                                          sem_coleta_no_periodo=sem_coleta,
                                          coleta_interrompida=interrompida,
                                          turmas_sem_coleta=turmas_sem_coleta,
                                          acumulado_na_primeira_coleta=(
                                              acumulado_antes or None),
                                          questoes_nao_vieram=nao_vieram)
    bloco.suporte["questoes"] = {
        "campo": "SnapshotElefante.questoes_* (diferença entre retratos)",
        "classificacao": "SUPORTADO COM RESSALVA",
        "por_que": "questões só existem como contador acumulado (vitalício) no "
                   "retrato, sem data por questão; a do período é a diferença "
                   "entre a coleta que mede o fim e a que mede o início",
        "ressalva": "exige retrato no período (sem ele o aluno entra em "
                    "alunos_sem_retrato, não conta zero); sem coleta no início "
                    "do período, a conta começa na primeira coleta dele, e sem "
                    "coleta no fim, termina na última — nos dois casos o número "
                    "NÃO é do período inteiro (veja cobertura_questoes)",
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
                          "largo que o período pedido (coleta-base anterior "
                          "ao início) ou mais estreito (sem coleta antes do "
                          "início, ou última coleta antes do fim) — veja a "
                          "cobertura"}


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
        _elefante_questoes(db, escola_id, coorte, janela, bloco_e, ele_por_aluno,
                           hoje=hoje)
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
            "cobertura_questoes": bloco_e.cobertura_questoes,
            "sem_atividade": len(coorte) - bloco_e.alunos_com_atividade,
            "suporte": bloco_e.suporte}
        saida["elefante"]["primeiro_evento_da_escola"] = _primeiro_evento(db, escola_id)
        saida["nao_suportado"].append(
            {"plataforma": "elefante", "metrica": "tempo_min_por_evento",
             "por_que": MOTIVO_ELEFANTE_TEMPO_EVENTO})
    if "matific" in plats:
        bloco_m, mat_por_aluno = _matific(db, escola_id, coorte, janela, ano, hoje=hoje)
        saida["matific"] = {
            "atividades": bloco_m.atividades, "estrelas": bloco_m.estrelas,
            "alunos_com_atividade": bloco_m.alunos_com_atividade,
            "alunos_sem_retrato": bloco_m.alunos_sem_retrato,
            "questoes": None,
            "janela_efetiva": bloco_m.janela_efetiva,
            "cobertura": bloco_m.cobertura,
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
