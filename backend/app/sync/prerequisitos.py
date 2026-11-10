"""Pré-requisitos para RELIGAR o agendador de sincronização (P3) — sem ligá-lo.

O agendador está desligado em produção desde 17/09 (``SYNC_SCHEDULER_ENABLED``)
e continua desligado por padrão. O diagnóstico de 22/10 (S1) mostrou por que
religá-lo "só pela variável" amplia os outros defeitos: sem teto de tempo a
coleta fica presa (S7); sem status honesto, "concluída" sai com 0 aluno (S2/S3);
credencial ilegível depois da rotação de chaves parece válida (S16); recálculo
que falhou deixa o ranking velho (S4).

``prerequisitos_agendador(db, settings)`` diz, de forma objetiva, se ESTA versão
e ESTE banco estão prontos: devolve a lista de verificações, cada uma com ``ok``,
``critico`` e ``motivo``. O agendador (``scheduler.iniciar``) RECUSA subir quando
uma verificação crítica falha — a menos que ``SYNC_SCHEDULER_FORCAR=true`` — e o
painel global (``GET /sync/dashboard``, só admin global) mostra o resultado.

Regras deste módulo:

* SÓ LEITURA: nenhuma verificação grava, enfileira, cria agenda ou fecha alerta;
* credencial: decifrada só para saber SE decifra, pelo mesmo caminho da execução
  (``vault.credencial_legivel``, a decifra de ``vault.obter_credencial``); o
  resultado é descartado na hora, nunca sai daqui;
* mensagens sem nome de escola, de aluno ou segredo: só ids, horários e contagens;
* uma verificação que estoura vira ``ok=False`` ("não verificável") e nunca
  derruba quem chamou (o boot do app ou o painel).

Ganchos que dependem de outras frentes da correção de 22–23/10 (lidos com
tolerância — ausentes, a verificação falha, que é o lado seguro):
``settings.SYNC_TETO_EXECUCAO_S``; ``service.ESTADOS_FINAIS`` (opcional — sem ele,
procura os estados do contrato no código do serviço); as colunas da migração
0039 em ``sincronizacao_execucoes``; o alerta ``recalculo_pendente``.

Checklist da reativação autorizada: ``docs/sync/REATIVAR-AGENDADOR.md``.
"""
from __future__ import annotations

import inspect
import logging
import math
import os
import re
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

from pydantic import BaseModel
from sqlalchemy import exists, inspect as sa_inspect, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.sincronizacao import (
    PlataformaCredencial,
    SincronizacaoAlerta,
    SincronizacaoConfig,
    SincronizacaoExecucao,
)
from app.sync import fuso, service, vault

logger = logging.getLogger("constela.sync")

#: Estados finais de ``sincronizacao_execucoes.status`` do contrato de 22–23/10.
ESTADOS_CONTRATO = ("concluida", "parcial", "sem_atualizacao", "sem_dados", "erro")
#: Colunas aditivas da migração 0039 (contadores honestos e recálculo pendente).
COLUNAS_CONTRATO = ("qtd_linhas", "qtd_em_revisao", "qtd_falhas",
                    "recalculo_pendente", "motivo")
TIPO_ALERTA_RECALCULO = "recalculo_pendente"
#: Janela do backup PRIVADO diário, em UTC, como OBSERVADA nos logs (execuções
#: de 21/10 11:44 e 22/10 11:47 UTC, com folga). Nenhuma coleta agendada pode
#: começar nem terminar (no pior caso, o teto) dentro dela. Se o backup mudar
#: de horário, atualizar aqui e no docs/sync/REATIVAR-AGENDADOR.md.
JANELA_BACKUP_UTC = (time(10, 30), time(13, 30))
#: Horário da agenda que ``service.garantir_agendas_diarias`` cria sozinha para
#: quem tem credencial e nenhuma agenda (o mesmo literal de lá).
HORA_AGENDA_AUTOMATICA = "03:00"
NOME_FUSO_ESPERADO = "America/Sao_Paulo"
_VERDADEIRO = frozenset({"1", "true", "sim", "yes", "on"})
_MAX_ROTULOS = 10


@dataclass(frozen=True)
class Verificacao:
    """Uma verificação: ``critico`` = bloqueia o início do agendador se falhar."""
    id: str
    ok: bool
    critico: bool
    motivo: str

    def como_dict(self) -> dict:
        return asdict(self)


class VerificacaoOut(BaseModel):
    id: str
    ok: bool
    critico: bool
    motivo: str


class PrerequisitosAgendadorOut(BaseModel):
    """Bloco mínimo do painel global: dá para decidir sem abrir o servidor."""
    habilitado: bool                 # SYNC_SCHEDULER_ENABLED (configuração)
    forcar: bool                     # SYNC_SCHEDULER_FORCAR interpretado
    pode_iniciar: bool               # nenhuma verificação crítica falhou
    decisao_no_boot: str | None = None   # o que ESTE processo decidiu ao subir
    criticos_falhos: list[str]
    verificacoes: list[VerificacaoOut]


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(valor: datetime | None) -> datetime | None:
    if valor is not None and valor.tzinfo is not None:
        return valor.astimezone(timezone.utc).replace(tzinfo=None)
    return valor


def _inteiro(valor) -> int | None:
    if isinstance(valor, bool):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _hora(texto: str | None) -> tuple[int, int] | None:
    try:
        hh, mm = str(texto or "").split(":")
        hh, mm = int(hh), int(mm)
    except ValueError:
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh, mm


def _hhmm(minutos: int) -> str:
    minutos %= 24 * 60
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def _rotulos(itens: list[str]) -> str:
    mostrados = ", ".join(itens[:_MAX_ROTULOS])
    resto = len(itens) - _MAX_ROTULOS
    return mostrados + (f" e mais {resto}" if resto > 0 else "")


def _desfazer(db: Session) -> None:
    """Depois de uma consulta que falhou (no PostgreSQL a transação fica
    abortada): desfaz para a próxima verificação poder ler. Só leitura aqui —
    não há trabalho pendente a perder."""
    try:
        db.rollback()
    except Exception:  # noqa: BLE001
        logger.debug("rollback dos pré-requisitos falhou", exc_info=True)


def forcar_habilitado(cfg=None) -> bool:
    """``SYNC_SCHEDULER_FORCAR`` interpretado (texto): só os valores de "ligado"
    forçam; qualquer outro (vazio, "talvez", erro de digitação) NÃO força."""
    cfg = settings if cfg is None else cfg
    return str(getattr(cfg, "SYNC_SCHEDULER_FORCAR", "") or "").strip().lower() in _VERDADEIRO


def teto_execucao_s(cfg=None) -> int | None:
    """O teto total por execução (``SYNC_TETO_EXECUCAO_S``) se configurado e > 0."""
    cfg = settings if cfg is None else cfg
    teto = _inteiro(getattr(cfg, "SYNC_TETO_EXECUCAO_S", None))
    return teto if teto is not None and teto > 0 else None


def _travada_s(cfg) -> int:
    return max(1, _inteiro(getattr(cfg, "SYNC_TRAVADA_S", None)) or 1800)


def _colunas_no_modelo() -> set[str]:
    """Colunas que o MODELO desta versão declara para a tabela de execuções."""
    return set(SincronizacaoExecucao.__table__.columns.keys())


# A avaliação em curso (``prerequisitos_agendador``) neste contexto de execução —
# cada requisição/thread tem o seu. O que ela já leu do banco vale para as
# verificações seguintes da MESMA avaliação.
_AVALIACAO: ContextVar[_Ctx | None] = ContextVar("prerequisitos_avaliacao", default=None)


def _colunas_no_banco(db: Session) -> set[str]:
    """Colunas REAIS da tabela de execuções neste banco (não só no modelo).

    Dentro de UMA avaliação, lidas uma vez só: o status honesto e o recálculo
    pendente perguntam o mesmo, e no PostgreSQL a leitura do catálogo são 3
    consultas (~0,6 s em produção a cada leitura do painel)."""
    ctx = _AVALIACAO.get()
    if ctx is not None and ctx.db is db and ctx._colunas is not None:
        return set(ctx._colunas)
    colunas = {c["name"] for c in sa_inspect(db.connection()).get_columns(
        SincronizacaoExecucao.__tablename__)}
    if ctx is not None and ctx.db is db:
        ctx._colunas = frozenset(colunas)
    return colunas


def _plataformas_automaticas() -> tuple[str, ...]:
    """As plataformas em que ``garantir_agendas_diarias`` cria agenda sozinha
    (o padrão do próprio parâmetro, para as duas listas não divergirem)."""
    try:
        padrao = inspect.signature(service.garantir_agendas_diarias).parameters[
            "plataformas"].default
        return tuple(padrao)
    except Exception:  # noqa: BLE001
        return ("matific", "elefante")


@dataclass(frozen=True)
class _Agenda:
    escola_id: int
    plataforma: str
    cadencia: str
    hora_local: str
    dia_semana: int | None
    proxima_execucao: datetime | None
    automatica: bool          # não existe ainda: nasce ao ligar o agendador

    @property
    def rotulo(self) -> str:
        return f"escola {self.escola_id}/{self.plataforma}"


def _carregar_agendas(db: Session) -> list[_Agenda]:
    """O que o agendador RODARIA se fosse ligado agora: as agendas ativas (o
    mesmo filtro de ``service.enfileirar_agendados``) e as que ele CRIA sozinho
    na primeira rodada (``garantir_agendas_diarias``: credencial sem agenda).
    Duas consultas, qualquer que seja o número de plataformas automáticas (antes,
    uma por plataforma)."""
    ativas = db.execute(select(SincronizacaoConfig).where(
        SincronizacaoConfig.ativo.is_(True),
        SincronizacaoConfig.cadencia != "manual")).scalars().all()
    agendas = [_Agenda(c.escola_id, c.plataforma, c.cadencia,
                       c.hora_local or HORA_AGENDA_AUTOMATICA, c.dia_semana,
                       _naive(c.proxima_execucao), False) for c in ativas]
    plataformas = _plataformas_automaticas()
    PC, SC = PlataformaCredencial, SincronizacaoConfig
    sem_agenda: dict[str, list[int]] = {}
    for escola_id, plat in db.execute(select(PC.escola_id, PC.plataforma).where(
            PC.plataforma.in_(plataformas),
            ~exists().where(SC.escola_id == PC.escola_id,
                            SC.plataforma == PC.plataforma))).all():
        sem_agenda.setdefault(plat, []).append(escola_id)
    for plat in plataformas:
        for escola_id in sem_agenda.get(plat, ()):
            agendas.append(_Agenda(escola_id, plat, "diaria", HORA_AGENDA_AUTOMATICA,
                                   None, None, True))
    return sorted(agendas, key=lambda a: (a.escola_id, a.plataforma))


class _Ctx:
    """Contexto de UMA avaliação (as agendas são lidas uma vez só)."""

    def __init__(self, db: Session, cfg, agora: datetime):
        self.db, self.cfg, self.agora = db, cfg, agora
        self.hoje_local: date = fuso.hoje_local(agora)
        self._agendas: list[_Agenda] | None = None
        self._colunas: frozenset[str] | None = None   # ``_colunas_no_banco``

    def agendas(self) -> list[_Agenda]:
        if self._agendas is None:
            self._agendas = _carregar_agendas(self.db)
        return self._agendas

    def duracao_pior_caso_min(self) -> int:
        """Quanto uma coleta pode durar no pior caso: o teto; sem teto, o limite
        a partir do qual a limpeza de órfãs a interrompe."""
        segundos = teto_execucao_s(self.cfg) or _travada_s(self.cfg)
        return max(1, math.ceil(segundos / 60))

    def minuto_utc(self, hora_local: str) -> int | None:
        """Minuto do dia, em UTC, do horário de PAREDE de Brasília ``hora_local``
        (convertido pela regra única de ``sync/fuso.py``)."""
        hm = _hora(hora_local)
        if hm is None:
            return None
        utc = fuso.local_para_utc_naive(datetime.combine(self.hoje_local, time(*hm)))
        return utc.hour * 60 + utc.minute

    def janela_backup_min(self) -> tuple[int, int]:
        ini, fim = JANELA_BACKUP_UTC
        return ini.hour * 60 + ini.minute, fim.hour * 60 + fim.minute

    def janela_backup_texto(self) -> str:
        ini, fim = JANELA_BACKUP_UTC
        dia = datetime.combine(self.hoje_local, time(0, 0))
        local_ini = fuso.para_local(dia.replace(hour=ini.hour, minute=ini.minute))
        local_fim = fuso.para_local(dia.replace(hour=fim.hour, minute=fim.minute))
        return (f"{ini:%H:%M}–{fim:%H:%M} UTC = {local_ini:%H:%M}–{local_fim:%H:%M} "
                "em Brasília")


def _sobrepoe(inicio: int, fim: int, janela: tuple[int, int]) -> bool:
    """[inicio, fim) cruza a janela diária? Minutos; ``fim`` pode passar de 24 h."""
    j_ini, j_fim = janela
    dia = 24 * 60
    return any(inicio < j_fim + d and j_ini + d < fim for d in (-dia, 0, dia, 2 * dia))


# --------------------------------------------------------------------------
# Verificações — cada uma devolve (ok, motivo)
# --------------------------------------------------------------------------
def _v_teto_execucao(ctx: _Ctx) -> tuple[bool, str]:
    bruto = getattr(ctx.cfg, "SYNC_TETO_EXECUCAO_S", None)
    if bruto is None:
        return False, ("SYNC_TETO_EXECUCAO_S não existe nesta versão: a coleta não tem "
                       "teto total de tempo e uma execução pode ficar 'executando' (S7).")
    teto = teto_execucao_s(ctx.cfg)
    if teto is None:
        return False, (f"SYNC_TETO_EXECUCAO_S = {bruto!r}: precisa ser um número de "
                       "segundos maior que zero.")
    return True, f"Teto total por execução: {teto} s ({teto // 60} min)."


def _v_teto_coerente(ctx: _Ctx) -> tuple[bool, str]:
    teto = teto_execucao_s(ctx.cfg)
    if teto is None:
        return False, ("Sem teto total configurado: não há com o que comparar "
                       "SYNC_TRAVADA_S e SYNC_TIMEOUT_S.")
    travada = _travada_s(ctx.cfg)
    etapa = _inteiro(getattr(ctx.cfg, "SYNC_TIMEOUT_S", None)) or 0
    problemas = []
    if travada <= teto:
        # A órfã em 'executando' é decidida pelo log (SYNC_SEM_SINAL_S), não por
        # SYNC_TRAVADA_S: a limpeza não interrompe mais a coleta viva. O que ainda
        # depende dele é a verificação 'execucoes_presas' (min(teto, SYNC_TRAVADA_S))
        # e o teto do sinal de vida (2 × SYNC_TRAVADA_S).
        problemas.append(
            f"SYNC_TRAVADA_S ({travada} s) não passa do teto ({teto} s): a verificação "
            "'execucoes_presas' acusaria como presa uma coleta ainda VIVA entre "
            f"{travada} s e {teto} s, e o sinal de vida de uma execução viva, que para em "
            f"2 × SYNC_TRAVADA_S ({2 * travada} s), deixaria só {2 * travada - teto} s "
            "depois do teto da coleta para a aplicação e o recálculo")
    if etapa > teto:
        problemas.append(f"SYNC_TIMEOUT_S ({etapa} s, por etapa) maior que o teto total "
                         f"({teto} s)")
    if problemas:
        return False, "; ".join(problemas) + "."
    return True, (f"SYNC_TRAVADA_S ({travada} s) > teto ({teto} s) >= SYNC_TIMEOUT_S "
                  f"({etapa} s).")


def _estados_declarados() -> tuple[set[str], str]:
    """Os estados do contrato que ESTA versão do serviço conhece. Preferência:
    a constante ``service.ESTADOS_FINAIS``; sem ela, o código do serviço."""
    constante = getattr(service, "ESTADOS_FINAIS", None)
    if constante:
        return {str(e) for e in constante}, "service.ESTADOS_FINAIS"
    try:
        fonte = inspect.getsource(service)
    except (OSError, TypeError):
        return set(), "código de app/sync/service.py indisponível"
    achados = {e for e in ESTADOS_CONTRATO if re.search(rf"[\"']{e}[\"']", fonte)}
    return achados, "código de app/sync/service.py"


def _v_status_honesto(ctx: _Ctx) -> tuple[bool, str]:
    declarados, origem = _estados_declarados()
    faltam_estados = [e for e in ESTADOS_CONTRATO if e not in declarados]
    modelo = _colunas_no_modelo()
    faltam_modelo = [c for c in COLUNAS_CONTRATO if c not in modelo]
    banco = _colunas_no_banco(ctx.db)
    faltam_banco = [c for c in COLUNAS_CONTRATO if c not in banco]
    problemas = []
    if faltam_estados:
        problemas.append(f"estados ausentes ({origem}): {', '.join(faltam_estados)}")
    if faltam_modelo:
        problemas.append(f"colunas ausentes no modelo: {', '.join(faltam_modelo)}")
    if faltam_banco:
        problemas.append("colunas ausentes no banco (migração 0039 não aplicada): "
                         + ", ".join(faltam_banco))
    if problemas:
        return False, ("Esta versão ainda não tem o status honesto do contrato — "
                       + "; ".join(problemas) + ".")
    return True, ("Estados " + ", ".join(ESTADOS_CONTRATO) + " presentes; colunas "
                  "da 0039 no modelo e no banco.")


def _v_selo_frescor(ctx: _Ctx) -> tuple[bool, str]:
    from app.routers import rankings
    from app.services import frescor_ranking

    faltam = []
    if not callable(getattr(frescor_ranking, "frescor_da_escola", None)):
        faltam.append("frescor_ranking.frescor_da_escola")
    rotas = {getattr(r, "path", "") for r in rankings.router.routes}
    if not any(p.endswith("/ranking/frescor") for p in rotas):
        faltam.append("rota /ranking/frescor")
    if faltam:
        return False, ("Selo de frescor indisponível: sem " + ", ".join(faltam)
                       + ". O ranking mostraria dado velho como atual.")
    return True, "Selo de frescor (/ranking/frescor) disponível."


def _v_execucoes_presas(ctx: _Ctx) -> tuple[bool, str]:
    db, agora = ctx.db, ctx.agora
    travada = _travada_s(ctx.cfg)
    teto = teto_execucao_s(ctx.cfg)
    limite_exec = min(travada, teto) if teto else travada
    executando = db.execute(
        select(SincronizacaoExecucao.id, SincronizacaoExecucao.escola_id,
               SincronizacaoExecucao.plataforma, SincronizacaoExecucao.iniciada_em)
        .where(SincronizacaoExecucao.status == "executando",
               SincronizacaoExecucao.iniciada_em.isnot(None),
               SincronizacaoExecucao.iniciada_em < agora - timedelta(seconds=limite_exec))
        .order_by(SincronizacaoExecucao.id)).all()
    presas = [f"#{i} escola {e}/{p} 'executando' há "
              f"{int((agora - _naive(ini)).total_seconds() // 60)} min"
              for i, e, p, ini in executando]
    corte_fila = agora - timedelta(seconds=travada)
    # O último log de cada uma vem na mesma consulta (o sinal de vida de
    # ``service.ultimo_sinal_de_vida``): uma ida, não uma por execução na fila.
    na_fila = db.execute(
        select(SincronizacaoExecucao, service.consulta_ultimo_log()).where(
            SincronizacaoExecucao.status == "fila",
            SincronizacaoExecucao.created_at < corte_fila)
        .order_by(SincronizacaoExecucao.id)).all()
    for ex, ultimo_log in na_fila:
        if ex.id in service._vivas_neste_processo:
            continue                      # uma thread deste processo espera por ela
        marcos = [m for m in (_naive(service.sinal_de_vida(ex, ultimo_log)),
                              _naive(ex.disponivel_em)) if m]
        if not marcos or max(marcos) < corte_fila:
            presas.append(f"#{ex.id} escola {ex.escola_id}/{ex.plataforma} na fila sem "
                          f"sinal de vida há mais de {travada // 60} min")
    if presas:
        return False, (f"{len(presas)} execução(ões) presa(s): {_rotulos(presas)}. "
                       "Libere-as (o boot finaliza as órfãs antigas; a manual é "
                       "substituída por um novo 'Sincronizar agora') antes de ligar.")
    return True, (f"Nenhuma execução 'executando' há mais de {limite_exec // 60} min nem "
                  f"na fila sem sinal de vida há mais de {travada // 60} min.")


def _v_credenciais_legiveis(ctx: _Ctx) -> tuple[bool, str]:
    agendas = ctx.agendas()
    if not agendas:
        return True, "Nenhuma integração com agenda ativa: não há credencial a conferir."
    # As credenciais de TODAS as agendas numa consulta (antes, uma ida por agenda:
    # ``vault.obter_credencial``); o "decifra ou não" é o mesmo da execução
    # (``vault.credencial_legivel`` = ``obter_credencial`` não None) e o texto
    # claro é descartado na hora. (escola, plataforma) é única na tabela.
    linhas = {(c.escola_id, c.plataforma): c for c in ctx.db.execute(
        select(PlataformaCredencial).where(
            PlataformaCredencial.escola_id.in_(sorted({a.escola_id for a in agendas})),
            PlataformaCredencial.plataforma.in_(sorted({a.plataforma for a in agendas}))))
        .scalars()}
    ruins = []
    for a in agendas:
        linha = linhas.get((a.escola_id, a.plataforma))
        if linha is None or not vault.credencial_legivel(linha):
            ruins.append(a.rotulo)
    if ruins:
        return False, (f"Credencial ausente ou ilegível em {len(ruins)} de {len(agendas)} "
                       f"integração(ões) que o agendador rodaria: {_rotulos(ruins)}. "
                       "Recadastre pela tela Integrações (depois da rotação de chaves).")
    return True, (f"As {len(agendas)} integração(ões) que o agendador rodaria têm "
                  "credencial legível.")


def _recalculos_pendentes(db: Session) -> list[str] | None:
    """Integrações cuja última marca de recálculo pendente NÃO foi superada por
    uma execução posterior com dado aplicado e recálculo feito. ``None`` = a
    versão não registra o recálculo pendente (coluna da 0039 ausente).

    Uma consulta (NOT EXISTS da execução posterior que a supera), qualquer que
    seja o número de execuções marcadas — antes, um ``count`` por marcada."""
    tabela = SincronizacaoExecucao.__table__
    coluna = tabela.columns.get("recalculo_pendente")
    if coluna is None or "recalculo_pendente" not in _colunas_no_banco(db):
        return None
    posterior = tabela.alias("posterior")
    superada = exists().where(
        posterior.c.escola_id == tabela.c.escola_id,
        posterior.c.plataforma == tabela.c.plataforma,
        posterior.c.id > tabela.c.id,
        posterior.c.status.in_(("concluida", "parcial")),
        or_(posterior.c.recalculo_pendente.is_(False),
            posterior.c.recalculo_pendente.is_(None)))
    pendentes = db.execute(
        select(tabela.c.escola_id, tabela.c.plataforma)
        .where(coluna.is_(True), ~superada)).all()
    return sorted({f"escola {escola_id}/{plataforma}" for escola_id, plataforma in pendentes})


def _v_recalculo(ctx: _Ctx) -> tuple[bool, str]:
    alertas = ctx.db.execute(
        select(SincronizacaoAlerta.escola_id, SincronizacaoAlerta.plataforma).where(
            SincronizacaoAlerta.tipo == TIPO_ALERTA_RECALCULO,
            SincronizacaoAlerta.resolvido.is_(False))).all()
    pendentes = _recalculos_pendentes(ctx.db)
    problemas = []
    if alertas:
        rot = sorted({f"escola {e}/{p or '-'}" for e, p in alertas})
        problemas.append(f"{len(alertas)} alerta(s) '{TIPO_ALERTA_RECALCULO}' aberto(s): "
                         + _rotulos(rot))
    if pendentes is None:
        problemas.append("não verificável nesta versão: a coluna "
                         "sincronizacao_execucoes.recalculo_pendente (migração 0039) não "
                         "existe — um recálculo que falhou não deixaria rastro")
    elif pendentes:
        problemas.append("execução com recálculo pendente ainda não superada: "
                         + _rotulos(pendentes))
    if problemas:
        texto = "; ".join(problemas) + "."
        return False, texto[0].upper() + texto[1:]
    return True, "Nenhum recálculo pendente."


def _v_fuso_da_agenda(ctx: _Ctx) -> tuple[bool, str]:
    problemas, notas = [], []
    if fuso.NOME_FUSO_LOCAL != NOME_FUSO_ESPERADO:
        problemas.append(f"fuso da agenda = {fuso.NOME_FUSO_LOCAL}, esperado "
                         f"{NOME_FUSO_ESPERADO}")
    # Prova pelo MESMO cálculo do agendador: "todo dia às 03:00" pedido às 09:00
    # de Brasília (12:00 UTC) tem de cair às 03:00 de Brasília do dia seguinte,
    # 06:00 UTC — e não às 03:00 UTC (meia-noite em Brasília).
    amostra = SimpleNamespace(ativo=True, cadencia="diaria", hora_local="03:00",
                              dia_semana=None)
    obtido = service.calcular_proxima(amostra, datetime(2026, 1, 15, 12, 0))
    esperado = datetime(2026, 1, 16, 6, 0)
    if obtido != esperado:
        problemas.append("a agenda das 03:00 calculou "
                         + (f"{obtido:%d/%m %H:%M} UTC" if obtido else "nada")
                         + f"; em {NOME_FUSO_ESPERADO} seria 16/01 06:00 UTC")
    if getattr(fuso.FUSO_LOCAL, "key", None) != NOME_FUSO_ESPERADO:
        notas.append("base de fusos ausente: UTC-3 fixo (mesmo resultado hoje; instale "
                     "tzdata)")
    desalinhadas, sem_proxima = [], []
    for a in ctx.agendas():
        if a.automatica:
            continue
        hm = _hora(a.hora_local)
        if hm is None:
            desalinhadas.append(f"{a.rotulo} com horário inválido {a.hora_local!r}")
            continue
        if a.proxima_execucao is None:
            sem_proxima.append(a.rotulo)
            continue
        local = fuso.para_local(a.proxima_execucao)
        dia_ok = a.cadencia != "semanal" or local.weekday() == (a.dia_semana or 0)
        if (local.hour, local.minute) != hm or not dia_ok:
            desalinhadas.append(f"{a.rotulo} marcada para {a.hora_local} e com próxima "
                                f"execução às {local:%H:%M} de Brasília")
    if desalinhadas:
        problemas.append("agenda(s) com a próxima execução fora do horário de Brasília "
                         f"(re-salve a agenda): {_rotulos(desalinhadas)}")
    if sem_proxima:
        notas.append(f"agenda(s) ativa(s) sem próxima execução (não rodariam): "
                     f"{_rotulos(sem_proxima)}")
    sufixo = (" Observação: " + "; ".join(notas) + ".") if notas else ""
    if problemas:
        return False, "; ".join(problemas) + "." + sufixo
    return True, (f"Horários calculados em {NOME_FUSO_ESPERADO} (03:00 de Brasília = "
                  "06:00 UTC)." + sufixo)


def _v_horario_fora_do_backup(ctx: _Ctx) -> tuple[bool, str]:
    agendas = ctx.agendas()
    janela = ctx.janela_backup_min()
    duracao = ctx.duracao_pior_caso_min()
    if not agendas:
        return True, (f"Nenhuma agenda ativa; janela do backup privado: "
                      f"{ctx.janela_backup_texto()}.")
    conflitos = []
    for a in agendas:
        inicio = ctx.minuto_utc(a.hora_local)
        if inicio is None:
            conflitos.append(f"{a.rotulo} com horário inválido {a.hora_local!r}")
            continue
        if _sobrepoe(inicio, inicio + duracao, janela):
            conflitos.append(f"{a.rotulo} às {a.hora_local} de Brasília = "
                             f"{_hhmm(inicio)} UTC, até {_hhmm(inicio + duracao)} UTC")
    if conflitos:
        return False, (f"{len(conflitos)} agenda(s) cruzam a janela do backup privado "
                       f"({ctx.janela_backup_texto()}) no pior caso de {duracao} min: "
                       f"{_rotulos(conflitos)}. Mude o horário da agenda.")
    return True, (f"As {len(agendas)} agenda(s) começam e terminam (pior caso de "
                  f"{duracao} min) fora da janela do backup privado "
                  f"({ctx.janela_backup_texto()}).")


def _v_fila_da_agenda(ctx: _Ctx) -> tuple[bool, str]:
    """AVISO: as coletas agendadas, em série (1 por vez), cada uma no pior caso."""
    agendas = ctx.agendas()
    duracao = ctx.duracao_pior_caso_min()
    inicios = sorted(m for m in (ctx.minuto_utc(a.hora_local) for a in agendas)
                     if m is not None)
    if not inicios:
        return True, "Nenhuma coleta agendada."
    janela = ctx.janela_backup_min()
    livre, conflito = None, None
    for inicio in inicios:
        comeco = inicio if livre is None else max(inicio, livre)
        livre = comeco + duracao
        if conflito is None and _sobrepoe(comeco, livre, janela):
            conflito = (comeco, livre)
    if conflito:
        return False, (f"Pior caso em série ({len(inicios)} coleta(s), {duracao} min cada): "
                       f"uma delas correria de {_hhmm(conflito[0])} a {_hhmm(conflito[1])} "
                       f"UTC e cruzaria o backup privado ({ctx.janela_backup_texto()}). "
                       "Espalhe os horários ao ampliar.")
    return True, (f"Pior caso em série ({len(inicios)} coleta(s), {duracao} min cada): a "
                  f"última termina às {_hhmm(livre)} UTC, fora do backup privado.")


def _v_workers_semaforo(ctx: _Ctx) -> tuple[bool, str]:
    cfg = ctx.cfg
    workers = _inteiro(getattr(cfg, "SYNC_WORKERS", None))
    poll = _inteiro(getattr(cfg, "SYNC_POLL_S", None))
    problemas = []
    if workers is None or workers < 1:
        problemas.append(f"SYNC_WORKERS = {getattr(cfg, 'SYNC_WORKERS', None)!r} "
                         "(mínimo 1)")
    if poll is None or poll < 1:
        problemas.append(f"SYNC_POLL_S = {getattr(cfg, 'SYNC_POLL_S', None)!r} "
                         "(mínimo 1 s)")
    vagas = getattr(service._semaforo_manual, "_initial_value", None)
    if vagas is not None and workers is not None and workers >= 1 \
            and vagas != max(1, workers):
        problemas.append(f"o semáforo das coletas manuais tem {vagas} vaga(s) e "
                         f"SYNC_WORKERS = {workers}: o processo roda com uma configuração "
                         "diferente da atual (reinicie)")
    bruto = os.environ.get("WEB_CONCURRENCY")
    processos = _inteiro(bruto)
    if processos is None or processos < 1:
        processos = 2               # o padrão do entrypoint.sh (--workers)
        origem = ("WEB_CONCURRENCY não definido neste processo; o entrypoint usa 2"
                  if bruto is None else f"WEB_CONCURRENCY = {bruto!r} inválido; "
                                        "considerado 2")
    else:
        origem = f"WEB_CONCURRENCY = {processos}"
    if problemas:
        return False, "; ".join(problemas) + "."
    simultaneas = processos * (1 + workers)
    return True, (f"SYNC_WORKERS = {workers} (semáforo coerente), SYNC_POLL_S = {poll} s; "
                  f"{origem}: até {simultaneas} coleta(s) ao mesmo tempo no pior caso "
                  f"({processos} processo(s) × (1 do agendador + {workers} manual(is))).")


def _v_alcance_ao_ligar(ctx: _Ctx) -> tuple[bool, str]:
    """AVISO: quem o agendador rodaria — e quem ganha agenda SOZINHO ao ligar."""
    agendas = ctx.agendas()
    existentes = [f"{a.rotulo} {a.cadencia} {a.hora_local}" for a in agendas
                  if not a.automatica]
    automaticas = [a.rotulo for a in agendas if a.automatica]
    texto = (f"Rodariam ao ligar: {_rotulos(existentes)}." if existentes
             else "Nenhuma agenda ativa hoje.")
    if automaticas:
        return False, (texto + f" Além disso, {len(automaticas)} integração(ões) com "
                       "credencial e SEM agenda ganham agenda DIÁRIA às "
                       f"{HORA_AGENDA_AUTOMATICA} de Brasília na 1ª rodada: "
                       f"{_rotulos(automaticas)}. Para ligar em 1 escola só, deixe antes "
                       "a agenda das outras salva como manual/desligada.")
    return True, texto + " Nenhuma agenda nasce sozinha ao ligar."


#: (id, crítico, função). A ORDEM é a da checklist do documento de reativação.
_VERIFICACOES = (
    ("teto_execucao", True, _v_teto_execucao),
    ("teto_coerente", True, _v_teto_coerente),
    ("status_honesto", True, _v_status_honesto),
    ("selo_frescor", True, _v_selo_frescor),
    ("execucoes_presas", True, _v_execucoes_presas),
    ("credenciais_legiveis", True, _v_credenciais_legiveis),
    ("recalculo_sem_pendencia", True, _v_recalculo),
    ("fuso_da_agenda", True, _v_fuso_da_agenda),
    ("horario_fora_do_backup", True, _v_horario_fora_do_backup),
    ("workers_semaforo", True, _v_workers_semaforo),
    ("fila_da_agenda", False, _v_fila_da_agenda),
    ("alcance_ao_ligar", False, _v_alcance_ao_ligar),
)
IDS_CRITICOS = tuple(v for v, critico, _ in _VERIFICACOES if critico)


def prerequisitos_agendador(db: Session, cfg=None, *,
                            agora: datetime | None = None) -> list[Verificacao]:
    """Avalia TODOS os pré-requisitos (só leitura). ``cfg`` = as configurações
    (``settings`` por padrão); ``agora`` em UTC naive (testes).

    Idas ao banco FIXAS, qualquer que seja o número de agendas, credenciais,
    execuções na fila ou recálculos pendentes: o painel global relê isto a cada
    ciclo do polling, e cada ida custa ~195 ms em produção."""
    cfg = settings if cfg is None else cfg
    ctx = _Ctx(db, cfg, _naive(agora) or _agora())
    token = _AVALIACAO.set(ctx)
    try:
        resultado = []
        for vid, critico, funcao in _VERIFICACOES:
            try:
                ok, motivo = funcao(ctx)
            except Exception as exc:  # noqa: BLE001 — nunca derruba boot nem painel
                logger.warning("Pré-requisito do agendador '%s' não verificável (%s).",
                               vid, type(exc).__name__)
                _desfazer(db)
                ctx._agendas = None   # a leitura pode ter sido a que falhou
                ctx._colunas = None
                ok, motivo = False, f"Não verificável ({type(exc).__name__})."
            resultado.append(Verificacao(vid, bool(ok), critico, motivo))
        return resultado
    finally:
        _AVALIACAO.reset(token)


def criticos_falhos(verificacoes: list[Verificacao]) -> list[Verificacao]:
    return [v for v in verificacoes if v.critico and not v.ok]


def pode_iniciar(verificacoes: list[Verificacao]) -> bool:
    return not criticos_falhos(verificacoes)


def para_painel(db: Session, cfg=None, *, decisao: str | None = None,
                agora: datetime | None = None) -> PrerequisitosAgendadorOut:
    """O bloco do painel global (admin global): mínimo e sem segredo."""
    cfg = settings if cfg is None else cfg
    verificacoes = prerequisitos_agendador(db, cfg, agora=agora)
    return PrerequisitosAgendadorOut(
        habilitado=bool(getattr(cfg, "SYNC_SCHEDULER_ENABLED", False)),
        forcar=forcar_habilitado(cfg),
        pode_iniciar=pode_iniciar(verificacoes),
        decisao_no_boot=decisao,
        criticos_falhos=[v.id for v in criticos_falhos(verificacoes)],
        verificacoes=[VerificacaoOut(**v.como_dict()) for v in verificacoes])
