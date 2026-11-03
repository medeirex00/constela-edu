"""Observabilidade do SaaS: logs estruturados, IDs de correlação, métricas e Sentry.

Peças:
  * `FormatadorJson` — cada log vira UMA linha JSON, já enriquecida com o
    contexto da requisição (request_id, correlation_id, usuario_id, escola_id,
    rota) via `contextvars`. Assim "logs por usuário/escola/rota" saem de graça:
    é só filtrar o campo no agregador (Loki, CloudWatch, Datadog…).
  * `ObservabilidadeMiddleware` — ASGI puro (não BaseHTTPMiddleware, para o
    contexto propagar até o handler mesmo em endpoints síncronos no threadpool).
    Gera request_id, aceita/gera correlation_id, mede a latência, emite o log de
    acesso, alimenta as métricas Prometheus e é a rede de segurança de 500.
  * Métricas Prometheus (`/metrics`): contagem, latência e requisições em curso
    por método/rota/status.
  * Sentry (opcional, ligado por `SENTRY_DSN`): erros e tracing de performance,
    com o usuário e a escola anexados ao evento.

Tudo é degradável: sem `sentry-sdk`/`prometheus-client` instalados, ou sem DSN,
as funções viram no-ops — nada quebra.
"""
from __future__ import annotations

import builtins
import copy
import json
import logging
import re
import sys
import textwrap
import threading
import time
import traceback
import uuid
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import datetime, timezone
from itertools import accumulate
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.exc import DBAPIError

# --- Dependências opcionais (degradam para no-op se ausentes) -----------------
try:  # métricas
    import prometheus_client as _prom
except ImportError:  # pragma: no cover
    _prom = None

try:  # erros + tracing
    import sentry_sdk as _sentry
except ImportError:  # pragma: no cover
    _sentry = None


# --- Contexto da requisição (propaga por toda a stack via contextvars) --------
ctx_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
ctx_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
ctx_usuario_id: ContextVar[int | None] = ContextVar("usuario_id", default=None)
ctx_escola_id: ContextVar[int | None] = ContextVar("escola_id", default=None)
ctx_rota: ContextVar[str | None] = ContextVar("rota", default=None)

_CAMPOS_CONTEXTO = (
    ("request_id", ctx_request_id),
    ("correlation_id", ctx_correlation_id),
    ("usuario_id", ctx_usuario_id),
    ("escola_id", ctx_escola_id),
    ("rota", ctx_rota),
)


# --- Log estruturado em JSON --------------------------------------------------
# Atributos padrão do LogRecord — tudo que estiver ALÉM disso veio de
# `logger.info(..., extra={...})` e entra no JSON como campo próprio.
_ATRIBUTOS_PADRAO = frozenset(logging.LogRecord(
    "", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}


# Nível no vocabulário do agregador (Railway: "lowercased and matched to the
# closest of debug, info, warn, error"). CRITICAL vira "error": não há nível acima.
_NIVEL_PADRAO = {"DEBUG": "debug", "INFO": "info", "WARNING": "warn",
                 "ERROR": "error", "CRITICAL": "error"}


class FormatadorJson(logging.Formatter):
    """Uma linha JSON por evento, com o contexto da requisição embutido.

    ``level`` e ``message`` são os campos que o Railway lê para a severidade e o
    texto da linha (sem eles, a severidade sai do canal: stderr = erro). ``nivel``
    e ``msg`` continuam iguais aos de antes, para filtros e buscas já existentes.

    O DETAIL de um erro do banco (veja ``redigir_detalhe_do_banco``): a mensagem e o
    ``extra`` falham fechado; no traceback, cada exceção usa o DETAIL dela.

    O texto de uma EXCEÇÃO — no traceback (``excecao``), como argumento da mensagem ou
    no ``extra`` — sai também sem dado pessoal (veja ``redigir_dados_pessoais``): ficam o
    tipo e o arquivo, a linha e a função de cada frame.
    """

    def format(self, record: logging.LogRecord) -> str:
        try:
            return _escrevivel(self._formatar(record))
        except Exception as erro:  # noqa: BLE001
            # Nunca deixar o logging cair no ``handleError``: ele imprime no stderr a
            # mensagem e os ARGUMENTOS crus (o DETAIL de um erro do banco junto).
            evento = {
                "ts": datetime.now(timezone.utc).isoformat(), "level": "error",
                "message": _FALHA_DE_FORMATACAO, "nivel": "ERROR",
                "logger": str(record.name), "msg": _FALHA_DE_FORMATACAO,
                "erro_de_formatacao": type(erro).__name__}
            for nome, var in _CAMPOS_CONTEXTO:        # ids e o modelo da rota: sem valor
                if var.get() is not None:
                    evento[nome] = var.get()
            return json.dumps(evento, ensure_ascii=False, default=str)

    def _formatar(self, record: logging.LogRecord) -> str:
        mensagem = redigir_detalhe_do_banco(_mensagem_do_registro(record))
        evento: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": _NIVEL_PADRAO.get(record.levelname, record.levelname.lower()),
            "message": mensagem,
            "nivel": record.levelname,
            "logger": record.name,
            "msg": mensagem,
        }
        for nome, var in _CAMPOS_CONTEXTO:
            valor = var.get()
            if valor is not None:
                evento[nome] = valor
        for chave, valor in record.__dict__.items():
            if chave not in _ATRIBUTOS_PADRAO and not chave.startswith("_"):
                # ``extra`` também: um texto (ou objeto que o json converte com
                # str()) com o DETAIL de um erro do banco não sai com o valor.
                evento[redigir_detalhe_do_banco(chave)] = _redigido(valor)
        if record.exc_info:
            evento["excecao"] = _traceback_do_registro(self, record.exc_info)
        return json.dumps(evento, ensure_ascii=False, default=_texto_para_o_json)


def _escrevivel(texto: str) -> str:
    """Um surrogate isolado (texto vindo de um JSON com "\\ud800") faria a escrita no
    stdout falhar — e o handleError padrão imprimiria a mensagem e os argumentos crus."""
    try:
        texto.encode("utf-8")
        return texto
    except UnicodeEncodeError:
        return texto.encode("utf-8", "backslashreplace").decode("utf-8")


class SaidaDoLog(logging.StreamHandler):
    """O handler do app. Se escrever a linha falhar, o ``handleError`` padrão do logging
    imprime no stderr a mensagem e os ARGUMENTOS crus do registro (o DETAIL de um erro
    do banco junto); este escreve só o logger e o tipo do erro."""

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 — API do logging
        if not logging.raiseExceptions:
            return
        try:
            erro = sys.exc_info()[1]
            sys.stderr.write(f"<falha ao escrever o log de {record.name}: "
                             f"{type(erro).__name__}>\n")
        except Exception:  # noqa: BLE001
            pass


class FormatadorTexto(logging.Formatter):
    """O formato legível (``LOG_JSON=false``), com a mesma redação do JSON."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            record.message = redigir_detalhe_do_banco(_mensagem_do_registro(record))
            if self.usesTime():
                record.asctime = self.formatTime(record, self.datefmt)
            texto = self.formatMessage(record)
            if record.exc_info:
                texto += "\n" + _traceback_do_registro(self, record.exc_info)
            if record.stack_info:
                texto += "\n" + self.formatStack(record.stack_info)
            return _escrevivel(texto)
        except Exception as erro:  # noqa: BLE001 — veja FormatadorJson.format
            return f"{_FALHA_DE_FORMATACAO} ({record.name}: {type(erro).__name__})"


_FALHA_DE_FORMATACAO = "<falha ao formatar o log>"


def silenciar_log_de_acesso_do_uvicorn() -> None:
    """Desliga a linha de acesso do PRÓPRIO uvicorn (logger ``uvicorn.access``).

    Ela grava a URL CRUA, com a query string: o token do painel público e da
    vitrine da rede, o token do link de redefinição de senha e o ``?busca=`` com
    nome de criança iam inteiros para o stdout (log do Railway, EUA). O log de
    acesso do app (``http_acesso``, no ObservabilidadeMiddleware) continua e grava
    só o MODELO da rota.

    Por que funciona sem depender do comando de partida: o uvicorn configura o
    logging no ``Config`` e só DEPOIS importa o app (``Config.load``); cada conexão
    decide se grava o acesso por ``getLogger("uvicorn.access").hasHandlers()``
    (``protocols/http/h11_impl.py`` e ``httptools_impl.py``, uvicorn 0.34). Sem
    handler e sem propagar, ``hasHandlers()`` é falso e a linha nem é montada — o
    mesmo efeito do ``--no-access-log`` (``uvicorn/config.py``, ``access_log=False``).
    ``propagate=True`` NÃO serviria: a linha subiria para o nosso handler da raiz,
    com a URL crua no ``message``. A flag no comando de partida fica como reforço
    (cobre quem importe o app ANTES de criar o ``Config`` do uvicorn)."""
    acesso = logging.getLogger("uvicorn.access")
    acesso.handlers = []
    acesso.propagate = False


def _logar_excecao_nao_tratada(tipo, valor, tb, thread: str | None = None) -> None:
    try:
        # CRITICAL: nem um LOG_LEVEL alto silencia a exceção que derrubou a thread
        # ou o processo (o scripts.migrate sairia com 1 sem dizer por quê).
        logging.getLogger("constela").critical(
            "excecao_nao_tratada", exc_info=(tipo, valor, tb),
            extra={"nome_da_thread": thread} if thread else None)
    except Exception:  # noqa: BLE001 — nunca o traceback cru no stderr
        try:
            sys.stderr.write(f"<excecao_nao_tratada: {getattr(tipo, '__name__', tipo)}>\n")
        except Exception:  # noqa: BLE001
            pass


def instalar_ganchos_de_excecao() -> None:
    """Exceção que ninguém tratou — numa thread ("Sincronizar agora", a verificação da
    automação) ou no processo (``scripts.migrate`` no pre-deploy) — ia para o
    excepthook PADRÃO, que imprime o traceback cru no stderr (o DETAIL de um erro do
    banco junto, no log do Railway) sem passar pelo formatador. Agora vai para o log,
    redigida. O Sentry, ligado depois, embrulha estes ganchos e continua capturando."""
    def no_processo(tipo, valor, tb) -> None:
        if issubclass(tipo, KeyboardInterrupt):
            sys.__excepthook__(tipo, valor, tb)
            return
        _logar_excecao_nao_tratada(tipo, valor, tb)

    def na_thread(args) -> None:
        if args.exc_type is SystemExit:
            return
        _logar_excecao_nao_tratada(args.exc_type, args.exc_value, args.exc_traceback,
                                   getattr(args.thread, "name", None))

    sys.excepthook = no_processo
    threading.excepthook = na_thread


def configurar_logging(settings) -> None:
    """Instala o handler único (JSON em produção, texto legível em dev).

    Saída em STDOUT: o Railway marca como ERRO toda linha que chega pelo stderr
    (o padrão do ``StreamHandler()``), e o log de acesso de um 200 aparecia em
    vermelho. A severidade real vai no campo ``level`` do JSON."""
    raiz = logging.getLogger()
    nivel = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    raiz.setLevel(nivel)
    for handler in list(raiz.handlers):
        raiz.removeHandler(handler)
    handler = SaidaDoLog(sys.stdout)
    if settings.LOG_JSON:
        handler.setFormatter(FormatadorJson())
    else:
        handler.setFormatter(FormatadorTexto(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    raiz.addHandler(handler)
    instalar_ganchos_de_excecao()
    # Uvicorn: manda o log de erro para a nossa formatação.
    for nome in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(nome)
        lg.handlers = []
        lg.propagate = True
    silenciar_log_de_acesso_do_uvicorn()
    # SQLAlchemy loga TODA consulta, com os parâmetros (nomes de criança), quando
    # o logger dele está habilitado para INFO — e com a raiz em INFO ele herdaria
    # isso. Até aqui quem segurava era o fileConfig do alembic.ini (que, de quebra,
    # trocava o nosso handler); agora a trava é explícita. O httpx, pelo mesmo
    # caminho, logaria em INFO cada chamada de SAÍDA com a URL inteira (Nominatim
    # com o endereço da escola, Matific, Expo, IA): ruído sem uso no diagnóstico.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # O Alembic fica em INFO para o "Running upgrade" aparecer no log da migração,
    # mas respeita um LOG_LEVEL mais alto (WARNING/ERROR): quem pediu silêncio não
    # recebe as linhas INFO dele.
    logging.getLogger("alembic").setLevel(max(logging.INFO, nivel))


# --- Métricas (Prometheus) ----------------------------------------------------
if _prom is not None:
    _M_REQS = _prom.Counter(
        "http_requisicoes_total", "Total de requisições HTTP concluídas",
        ["metodo", "rota", "status"])
    _M_DUR = _prom.Histogram(
        "http_duracao_segundos", "Duração das requisições HTTP (s)",
        ["metodo", "rota"],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
    _M_ANDAMENTO = _prom.Gauge(
        "http_em_andamento", "Requisições HTTP em andamento", ["metodo"])
else:  # pragma: no cover
    _M_REQS = _M_DUR = _M_ANDAMENTO = None


def metricas_ativas() -> bool:
    return _prom is not None


def render_metricas() -> tuple[bytes, str]:
    """Corpo e content-type para o endpoint /metrics (formato Prometheus)."""
    if _prom is None:  # pragma: no cover
        return b"# prometheus-client nao instalado\n", "text/plain"
    return _prom.generate_latest(), _prom.CONTENT_TYPE_LATEST


# --- Sentry (opcional) --------------------------------------------------------
_sentry_ativo = False


def higienizar_evento_sentry(event, _hint=None):
    """Redige segredos da URL/query ANTES do evento sair para o Sentry
    (processador externo). A integração Starlette anexa a URL crua da
    requisição ao evento — e ``send_default_pii=False`` não cobre isso —, então
    um 500 em /publico/{token} ou /auth/redefinir-senha/{token} vazaria o token.
    Espelha a redação dos logs internos (redigir_caminho) e zera a query string,
    onde nomes/códigos de criança poderiam aparecer (?busca=, ?qr=). O nome da
    transação, quando não é um modelo de rota, também (veja ``_nome_sem_segredo``).

    Depois, o texto livre do evento passa pela MESMA redação de dado pessoal do log,
    com um orçamento por evento (veja ``_sem_dado_pessoal_no_sentry``). Se ela falhar
    (não deveria), o evento NÃO sai: devolve None, que o SDK trata como descartado —
    sem a redação, iria cru."""
    req = event.get("request") if isinstance(event, dict) else None
    if isinstance(req, dict):
        if isinstance(req.get("url"), str):
            req["url"] = redigir_caminho(req["url"])
        if req.get("query_string"):
            req["query_string"] = "<redigido>"
    if isinstance(event, dict) and isinstance(event.get("transaction"), str):
        info = event.get("transaction_info")
        if not (isinstance(info, dict) and info.get("source") in _NOMES_DO_CODIGO):
            event["transaction"] = _nome_sem_segredo(event["transaction"])
    if isinstance(event, dict):
        # Valores da linha recusada que o PostgreSQL põe no DETAIL do erro, em
        # QUALQUER texto do evento. O valor de uma exceção usa o DETAIL exato do erro
        # da cadeia (hint) cujo texto ele reproduz INTEIRO; cortado pelo SDK (ou
        # qualquer outro texto), falha fechado.
        exc_info = (_hint or {}).get("exc_info") if isinstance(_hint, dict) else None
        excecao = exc_info[1] if exc_info and len(exc_info) > 1 else None
        exatos: dict[int, str] = {}
        excecoes = event.get("exception")
        valores = excecoes.get("values") if isinstance(excecoes, dict) else None
        for valor in valores if isinstance(valores, list) else ():
            if (isinstance(valor, dict) and "value" in valor and valor["value"] is not None
                    and not isinstance(valor["value"], str)):
                # O SDK pode entregar uma LISTA (veja _sem_mutar_o_erro_no_sentry): um
                # texto só, sem dono.
                bruto = valor["value"]
                exatos[id(valor)] = redigir_detalhe_do_banco(
                    "".join(str(x) for x in bruto) if isinstance(bruto, (list, tuple))
                    else str(bruto))
        if isinstance(excecao, BaseException) and isinstance(valores, list):
            # (texto inteiro, mensagem, exceção) de cada erro da cadeia
            textos = [(par[0], par[1], no) for no in _nos_da_cadeia(excecao)
                      if (par := _texto_no_sentry(no)) is not None]
            for valor in valores:
                if isinstance(valor, dict) and isinstance(valor.get("value"), str):
                    texto = valor["value"]
                    achado = next(((mensagem, no) for completo, mensagem, no in textos
                                   if completo == texto), None)
                    if achado is None:
                        continue
                    mensagem, dono = achado
                    if isinstance(mensagem, str) and texto.startswith(mensagem):
                        # Só a mensagem é o texto do dono; as notas falham fechado.
                        exatos[id(valor)] = (redigir_detalhe_do_banco(mensagem, dono) +
                                             redigir_detalhe_do_banco(texto[len(mensagem):]))
        event = _redigido(event, exatos)
        try:
            event = _sem_dado_pessoal_no_sentry(event)
        except Exception:  # noqa: BLE001 — sem a redação, o evento iria cru: não sai
            return None
    return event


# O nome de uma transação de rota CASADA é o modelo dela ("/api/v1/publico/{token}",
# source "route"); o de uma NÃO casada (um 404) é a URL crua da requisição, com o host e
# o token ("http://host/api/v1/publico/<o token>/x", source "url": o SentryAsgiMiddleware
# usa _get_url quando não há rota). As fontes abaixo são nomes do código.
_NOMES_DO_CODIGO = frozenset({"route", "component", "view", "task"})


def _nome_sem_segredo(nome: str) -> str:
    """O nome de uma transação que não é nome do código: só o caminho — sem esquema, host,
    query e fragmento — e sem o token de rota (``redigir_caminho``)."""
    try:
        partes = urlsplit(nome)
    except ValueError:                   # um "[" sem par no host: fica o texto inteiro
        partes = None
    if partes is not None and partes.scheme and partes.netloc:
        nome = partes.path or "/"
    return redigir_caminho(nome.split("?", 1)[0].split("#", 1)[0])


# A LoggingIntegration do sentry-sdk 2.x monta o evento do registro CRU
# (integrations/logging.py): ``logentry = {"message": record.msg, "params": record.args}``
# (uma exceção nos argumentos vira o repr dela), o ``extra`` do evento e o ``data`` de cada
# breadcrumb com o ``extra`` do registro, o ``message`` do breadcrumb com o
# ``getMessage()`` (o texto da exceção junto) e o ``value`` de cada exceção com o texto
# dela. As integrações de HTTP de saída (httpx, http.client) põem a query e o fragmento da
# URL em ``data["http.query"]``/``data["http.fragment"]`` do breadcrumb e do span; a do
# SQLAlchemy, o SQL no ``message`` do breadcrumb e na ``description`` do span; a do
# Starlette, os cabeçalhos da requisição que o SDK não considera sensíveis (Referer,
# User-Agent, X-Correlation-Id…) em ``request.headers``. Todo esse texto passa pela redação
# de dado pessoal do log (``redigir_dados_pessoais``, com o teto do texto de uma exceção),
# depois da do DETAIL do banco; a query e o fragmento saem inteiros, como os de uma URL no
# log. As chaves de texto dos dicts também passam pela redação: um
# ``extra={"por_aluno": {"Zuleica Testelli": 3}}`` levaria o nome na chave. Duas chaves que
# viram a mesma ficam as duas ("<nome>", "<nome> #2"…), e as do ``_meta`` (o caminho até
# cada texto que o SDK cortou passa pelas chaves do evento) seguem a mesma troca. Ficam os
# campos técnicos: o tipo e o módulo da exceção, os frames (arquivo, função, linha e o
# código do repositório; sem variáveis locais: ``include_local_variables=False``), as
# tags, os contextos, os carimbos de tempo e as anotações do ``_meta``.
#
# O SDK corta cada texto em ``max_value_length`` (1024) ANTES do ``before_send`` e anota o
# corte no ``_meta`` ("!limit"): o fim de um texto cortado pode ser o PEDAÇO de um dado
# ("Zuleica T..."). Ali o texto recua como a cabeça de uma exceção grande
# (``_inicio_redigido``: até um espaço a mais de ``_MARGEM`` caracteres do corte em que
# nenhum dado foi partido) e termina em "...".
#
# O CUSTO TEM TETO POR EVENTO. Este hook roda síncrono, com o event loop parado: o
# ``before_send_transaction`` sai do fim da transação da requisição, e um erro não tratado
# gera dois eventos (o ``logger.exception`` e o ``capturar_excecao``). A redação custa
# ~0,4 s por MB, uma transação leva até 1000 spans e o SDK NÃO corta a ``description`` de
# um span (um INSERT de 1400 linhas tem 52 KB): sem teto, uma requisição com muitas
# consultas e o tracing ligado parava o worker por centenas de ms. Por evento:
#   * a ``description`` de um span mais longa que ``_LIMITE_DO_SDK`` é cortada aqui como
#     o SDK corta os outros textos (e recua do mesmo jeito);
#   * um texto repetido (a mesma consulta em 1000 spans) sai do que já foi redigido no
#     evento, sem custo;
#   * a redação vê no máximo ``_TETO_DA_REDACAO`` caracteres (o do texto de UMA exceção
#     no log: ~66 mil, ~26 ms), contados com os recuos. Antes de cada texto, o custo
#     MÁXIMO dele (``_custo_da_redacao``) tem de caber no que resta; se não cabe, o texto
#     vira ``_FORA_DO_ORCAMENTO`` — nunca sai cru. Ordem: as chaves do ``_meta`` (curtas:
#     o caminho até cada texto cortado), os valores das exceções (da de cima, a última da
#     lista, à mais antiga), ``logentry``, ``message``, ``extra``, os cabeçalhos da
#     requisição (poucos e curtos), os breadcrumbs (do mais recente ao mais antigo) e os
#     spans, na ordem. O ``op`` e os tempos de cada span ficam: a cascata da transação
#     continua legível.
_CAMPOS_LIVRES_DO_SENTRY = ("logentry", "message", "extra")
_CAMPOS_LIVRES_DO_ITEM = ("message", "description", "data")     # breadcrumb e span
_SEM_QUERY_NO_SENTRY = frozenset({"http.query", "http.fragment"})
_CORTE_DO_SDK = "..."
_LIMITE_DO_SDK = 1024                    # max_value_length padrão do sentry-sdk 2.x
_META_DO_CORTE = {"": {"rem": [["!limit", "x"]]}}   # o corte da description, feito aqui
_FORA_DO_ORCAMENTO = "<omitido>"


class _Orcamento:
    """Quanto texto a redação de dado pessoal ainda pode ver (``restante``, em caracteres)
    e os textos já redigidos sob este orçamento (``feitos``: (texto, cortado) → saída)."""
    __slots__ = ("restante", "feitos")

    def __init__(self, total: int) -> None:
        self.restante = total
        self.feitos: dict[tuple[str, bool], str] = {}

    def redigir(self, texto: str) -> str:
        self.restante -= len(texto)
        return redigir_dados_pessoais(texto)


def _sem_dado_pessoal_no_sentry(evento):
    """O evento (a cópia que ``_redigido`` acabou de fazer) com o texto livre sem dado
    pessoal, sob o orçamento do evento (veja o comentário acima). Campo com tipo
    inesperado fica como está."""
    if not isinstance(evento, dict):
        return evento
    orcamento = _Orcamento(_TETO_DA_REDACAO)
    meta = evento.get("_meta")                # o original: os caminhos do evento recebido
    if isinstance(meta, dict):
        evento["_meta"] = _meta_sem_dado_pessoal(meta, orcamento)
    excecoes = evento.get("exception")
    valores = excecoes.get("values") if isinstance(excecoes, dict) else None
    meta_valores = _no_do_meta(_no_do_meta(meta, "exception"), "values")
    for i in reversed(range(len(valores))) if isinstance(valores, list) else ():
        valor = valores[i]
        if isinstance(valor, dict) and isinstance(valor.get("value"), str):
            valor["value"] = _texto_do_sentry(
                valor["value"], _no_do_meta(_no_do_meta(meta_valores, i), "value"), orcamento)
    for campo in _CAMPOS_LIVRES_DO_SENTRY:
        if campo in evento:
            evento[campo] = _textos_do_sentry(evento[campo], _no_do_meta(meta, campo),
                                              orcamento)
    req = evento.get("request")
    if isinstance(req, dict) and "headers" in req:
        req["headers"] = _textos_do_sentry(
            req["headers"], _no_do_meta(_no_do_meta(meta, "request"), "headers"), orcamento)
    for campo in ("breadcrumbs", "spans"):
        itens, meta_itens = evento.get(campo), _no_do_meta(meta, campo)
        if isinstance(itens, dict):                      # {"values": [...]}
            itens, meta_itens = itens.get("values"), _no_do_meta(meta_itens, "values")
        if not isinstance(itens, list):
            continue
        ordem = reversed(range(len(itens))) if campo == "breadcrumbs" else range(len(itens))
        for i in ordem:
            item = itens[i]
            if not isinstance(item, dict):
                continue
            meta_item = _no_do_meta(meta_itens, i)
            for chave in _CAMPOS_LIVRES_DO_ITEM:
                if chave not in item:
                    continue
                valor, meta_valor = item[chave], _no_do_meta(meta_item, chave)
                if (campo == "spans" and chave == "description" and isinstance(valor, str)
                        and len(valor) > _LIMITE_DO_SDK):
                    valor = valor[:_LIMITE_DO_SDK - len(_CORTE_DO_SDK)] + _CORTE_DO_SDK
                    meta_valor = _META_DO_CORTE
                item[chave] = _textos_do_sentry(valor, meta_valor, orcamento)
    return evento


def _meta_sem_dado_pessoal(meta: dict, orcamento: _Orcamento, _nivel: int = 0) -> dict:
    """O ``_meta`` com as chaves de texto trocadas como as do evento (a mesma redação: uma
    chave já vista sai do que foi feito). A anotação de cada nó (a chave "") fica. Uma
    chave fora do orçamento leva o nó junto: só a anotação do corte se perde."""
    saida: dict = {}
    if _nivel >= _PROFUNDIDADE_MAX:
        return saida
    for chave, no in meta.items():
        if isinstance(chave, str) and chave:
            chave = _chave_redigida(chave, orcamento)
            if chave == _FORA_DO_ORCAMENTO:
                continue
        saida[chave] = (_meta_sem_dado_pessoal(no, orcamento, _nivel + 1)
                        if chave != "" and isinstance(no, dict) else no)
    return saida


def _chave_redigida(chave: str, orcamento: _Orcamento) -> str:
    """Uma chave de texto de dict sem dado pessoal. Só dígitos, e menos que um documento
    (o índice de uma lista no ``_meta``, um id curto): a redação a deixaria igual, e ela
    sai sem gastar orçamento — senão o custo do ``_meta`` cresceria com os breadcrumbs."""
    if len(chave) < _MIN_DIGITOS_DOCUMENTO and chave.isascii() and chave.isdigit():
        return chave
    return _texto_do_sentry(chave, None, orcamento)


def _chave_sem_repetir(chave: str, saida: dict, repetidas: dict[str, int]) -> str:
    """``chave`` ou, se outra chave do mesmo dict já virou ela, "chave #2", "chave #3"…
    (``repetidas``: o último número usado para cada chave, para não recontar)."""
    if chave not in saida:
        return chave
    n = repetidas.get(chave, 1)
    while True:
        n += 1
        candidata = f"{chave} #{n}"
        if candidata not in saida:
            repetidas[chave] = n
            return candidata


def _no_do_meta(meta, chave):
    """O nó do ``_meta`` do SDK no caminho ``chave`` (o índice de uma lista vira texto)."""
    return meta.get(str(chave)) if isinstance(meta, dict) else None


def _cortado_pelo_sdk(meta) -> bool:
    """Se o ``_meta`` diz que o SDK cortou este texto ("rem": [["!limit", …]])."""
    anotacao = meta.get("") if isinstance(meta, dict) else None
    remocoes = anotacao.get("rem") if isinstance(anotacao, dict) else None
    return isinstance(remocoes, list) and any(
        isinstance(r, (list, tuple)) and r and r[0] == "!limit" for r in remocoes)


def _custo_da_redacao(texto: str, cortado: bool) -> int:
    """O MÁXIMO de caracteres que ``_texto_do_sentry`` entrega a ``redigir_dados_pessoais``
    para este texto: a janela e os recuos de ``_inicio_redigido`` (cortado), o texto
    inteiro (até ``_LIMITE_DO_TEXTO``) ou o teto do texto de uma exceção."""
    if cortado:
        visivel = len(texto) - len(_CORTE_DO_SDK)
        return visivel + _TENTATIVAS_DE_CORTE * max(visivel - _MARGEM - 1, 0)
    return len(texto) if len(texto) <= _LIMITE_DO_TEXTO else _TETO_DA_REDACAO


def _texto_do_sentry(texto: str, meta, orcamento: _Orcamento) -> str:
    """Um texto do evento sem dado pessoal, sob o ``orcamento`` do evento. Cortado pelo
    SDK e ainda terminado no "..." do corte (a redação do DETAIL não levou o fim junto),
    o fim pode ser o pedaço de um dado: o texto recua até um ponto em que nenhum dado foi
    partido. Um texto já redigido neste evento sai do que foi feito; um que não cabe no
    que resta do orçamento vira ``_FORA_DO_ORCAMENTO``."""
    cortado = _cortado_pelo_sdk(meta) and texto.endswith(_CORTE_DO_SDK)
    feito = orcamento.feitos.get((texto, cortado))
    if feito is not None:
        return feito
    if _custo_da_redacao(texto, cortado) > orcamento.restante:
        return _FORA_DO_ORCAMENTO
    if cortado:
        visivel = len(texto) - len(_CORTE_DO_SDK)
        feito = (_inicio_redigido(texto[:visivel], visivel, orcamento.redigir)[1] +
                 _CORTE_DO_SDK)
    else:
        feito = _sem_dado_pessoal_com_teto(texto, orcamento.redigir)
    orcamento.feitos[(texto, cortado)] = feito
    return feito


def _textos_do_sentry(valor, meta, orcamento: _Orcamento, _nivel: int = 0):
    """``valor`` com cada texto (também dentro de dicts, listas e tuplas, e as chaves de
    texto dos dicts) sem dado pessoal; a query e o fragmento de uma URL de saída,
    inteiros."""
    if isinstance(valor, str):
        return _texto_do_sentry(valor, meta, orcamento)
    if not isinstance(valor, (dict, list, tuple)):
        return valor
    if _nivel >= _PROFUNDIDADE_MAX:
        return _OMITIDO
    if isinstance(valor, dict):
        saida: dict = {}
        repetidas: dict[str, int] = {}
        for chave, item in valor.items():
            if chave in _SEM_QUERY_NO_SENTRY and isinstance(item, str) and item:
                item = _REDIGIDO
            else:
                item = _textos_do_sentry(item, _no_do_meta(meta, chave), orcamento, _nivel + 1)
            if isinstance(chave, str):
                chave = _chave_sem_repetir(_chave_redigida(chave, orcamento), saida,
                                           repetidas)
            saida[chave] = item
        return saida
    itens = [_textos_do_sentry(item, _no_do_meta(meta, i), orcamento, _nivel + 1)
              for i, item in enumerate(valor)]
    return itens if isinstance(valor, list) else tuple(itens)


def _mensagem_para_o_sentry(exc_value) -> str:
    if exc_value is None:
        return ""
    par = _texto_no_sentry(exc_value)
    return par[0] if par is not None else _REDIGIDO


def _sem_mutar_o_erro_no_sentry() -> None:
    """O ``utils.get_error_message`` do sentry-sdk 2.x faz ``mensagem += notas``: com o
    ``.detail`` em LISTA de um erro do SQLAlchemy (autoflush), isso ESTENDE a lista do
    próprio erro com as notas, letra por letra — o ``value`` do evento vira uma lista
    de caracteres que nenhuma redação reconhece, e o ``str()`` do erro muda também no
    log. Troca pela cópia (``_texto_no_sentry``) que não muda nada e sempre devolve
    texto; o SDK a usa como global do próprio módulo."""
    try:
        import sentry_sdk.utils as utilitarios
    except ImportError:  # pragma: no cover
        return
    if hasattr(utilitarios, "get_error_message"):
        utilitarios.get_error_message = _mensagem_para_o_sentry


def configurar_sentry(settings) -> None:
    global _sentry_ativo
    if _sentry is None or not settings.SENTRY_DSN:
        return
    _sem_mutar_o_erro_no_sentry()
    _sentry.init(
        dsn=settings.SENTRY_DSN,
        environment=(settings.SENTRY_ENVIRONMENT or settings.ENV),
        release=settings.APP_VERSION,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        # As integrações de FastAPI/Starlette/SQLAlchemy ligam sozinhas.
        send_default_pii=False,   # LGPD: sem dados pessoais por padrão
        # NÃO anexar variáveis locais dos frames às exceções: elas podem conter
        # PII de menor (bytes do arquivo, filename, linhas já parseadas com
        # nomes de alunos). send_default_pii=False não cobre frame-locals.
        include_local_variables=False,
        # NUNCA anexar o CORPO da requisição: POST /auth/redefinir-senha carrega o
        # token de reset E a nova senha em texto puro no corpo; imports carregam
        # nomes de alunos. send_default_pii=False não cobre o corpo (o SDK captura
        # corpos "medium" por padrão).
        max_request_body_size="never",
        # Redige o token de rota e a query string da URL crua em erros E em
        # transações de performance antes do envio externo.
        before_send=higienizar_evento_sentry,
        before_send_transaction=higienizar_evento_sentry,
    )
    _sentry_ativo = True
    logging.getLogger("constela").info("Sentry ativado", extra={"componente": "sentry"})


def sentry_ativo() -> bool:
    return _sentry_ativo


def _marcar_sentry(request_id, correlation_id, usuario_id, escola_id) -> None:
    if not _sentry_ativo:
        return
    escopo = _sentry.get_current_scope()
    escopo.set_tag("request_id", request_id)
    escopo.set_tag("correlation_id", correlation_id)
    if escola_id is not None:
        escopo.set_tag("escola_id", escola_id)
    if usuario_id is not None:
        escopo.set_user({"id": usuario_id})


def capturar_excecao(erro: BaseException) -> None:
    if _sentry_ativo:
        _sentry.capture_exception(erro)


# --- Extração de contexto da requisição --------------------------------------
_RE_ESCOLA = re.compile(r"/escolas/(\d+)")


def _escola_id_do_caminho(caminho: str) -> int | None:
    m = _RE_ESCOLA.search(caminho)
    return int(m.group(1)) if m else None


def redigir_caminho(caminho: str) -> str:
    """Remove segredos de URL antes de logar/telemetrar. Os tokens de rota
    NÃO podem aparecer no log de erro nem no Sentry:
      * painel público da escola (/publico/{token}/...) — quem lê o log abriria o
        painel (nomes e notas das crianças);
      * vitrine da rede (/publico/rede/{token}) — o segmento logo após /publico/ é
        a palavra "rede"; redigir só ele deixava o token inteiro no log;
      * redefinição de senha (/redefinir-senha/{token}) — quem lê poderia
        trocar a senha da conta antes de a pessoa usar o link.
    O log de ACESSO não passa por aqui: grava o modelo da rota (ver _rota_de)."""
    caminho = re.sub(r"(/publico/(?:rede/)?)[^/?#]+", r"\1<token>", caminho)
    caminho = re.sub(r"(/redefinir-senha/)[^/?#]+", r"\1<token>", caminho)
    return caminho


# O PostgreSQL escreve no texto do erro os VALORES da linha recusada — e o
# hide_parameters do SQLAlchemy (core/database.py) não alcança esse texto, que vem
# do servidor: "DETAIL:  Failing row contains (12, NOME DA CRIANÇA, 2017-…)." numa
# violação de NOT NULL/CHECK; "DETAIL:  Key (coluna)=(valor) already exists." numa de
# UNIQUE; "… is not present in table …"/"… is still referenced from table …" numa de
# FK; "Key (c)=(v1) conflicts with existing key (c)=(v2)." numa de EXCLUDE; um
# 'Token "…" is invalid.' num JSON inválido. Valores também vêm no CONTEXT ("unnamed
# portal with parameters: $1 = '…'" com log_parameter_max_length_on_error ligado, o
# comando de um EXECUTE com os literais, o trecho de um JSON), no QUERY de uma função
# e na linha "LINE n: …" com que o libpq mostra a posição do erro na consulta (a de
# um EXECUTE traz os literais).
# Os nomes das colunas e das tabelas ficam (servem ao diagnóstico); os VALORES saem.
#
# O FIM DO VALOR NÃO SE ACHA PELO CONTEÚDO: ele pode conter qualquer coisa — quebra
# de linha, parágrafo, ")", ").", "[SQL: ", "HINT:", o separador de exceções do
# traceback, o rabo de uma chave, o DETAIL inteiro de outro erro. A regra:
#   1. Os campos exatos do erro (``diag.message_detail``, ``context`` e
#      ``internal_query`` do psycopg) só valem no texto do erro DONO deles: a
#      mensagem daquela exceção, em que o PostgreSQL escreveu cada campo uma vez. Ali
#      o DETAIL vira a forma montada pela ESTRUTURA (prefixo, nomes das colunas, rabo
#      conhecido sem valor); o CONTEXT, o QUERY e a linha LINE saem inteiros. No
#      traceback, cada exceção da cadeia é redigida com os campos dela; no Sentry, um valor de exceção
#      só usa os campos do erro cujo texto ele reproduz INTEIRO.
#   2. Todo o resto — a mensagem do log, ``extra``, breadcrumbs, um erro sem ``diag``
#      que copia o texto de outro (PendingRollbackError), um valor cortado pelo SDK
#      do Sentry, um repr — falha fechado: o primeiro rótulo "DETAIL:"/"CONTEXT:"/
#      "QUERY:"/"LINE n:" (ou começo de linha/chave recusada) corta aquele texto, e
#      tudo dali até o fim dele sai. Perde-se diagnóstico nesses casos; o valor, nunca.
# Por que o dono: aplicado ao texto inteiro, o DETAIL exato de um erro casava também
# com o começo do DETAIL de OUTRO erro (um valor forjado com o rabo do PostgreSQL), e
# o resto desse outro DETAIL saía como se fosse estrutura. Sem regex sobre o valor e
# com custo linear no tamanho do texto (uma regex ambígua aqui custava tempo
# quadrático com o GIL preso). Em produção (21/10/2026) o servidor fala inglês
# (lc_messages = en_US) e log_parameter_max_length_on_error = 0.
_INICIO_LINHA = "Failing row contains ("
_INICIO_PARTICAO = "Partition key of the failing row contains ("
_INICIO_CHAVE = "Key ("
_SEPARADOR = ")=("
_ROTULOS = ("DETAIL:  ", "CONTEXT:  ", "QUERY:  ")     # como o libpq escreve cada campo
_REDIGIDO = "<redigido>"
_RABOS_FIXOS = (") already exists.", ") is duplicated.")
_RABOS_TABELA = (") is not present in table \"", ") is still referenced from table \"")
_CONFLITOS = (") conflicts with existing key (", ") conflicts with key (")
_ROTULO_POSICAO = "LINE "                               # "LINE 12: " (posição do erro)
_RE_INICIOS = re.compile("|".join([re.escape(m) for m in (
    _INICIO_LINHA, _INICIO_PARTICAO, _INICIO_CHAVE, _SEPARADOR) + _ROTULOS]
    + [re.escape(_ROTULO_POSICAO) + r"\d+: "]))
# O bloco da posição: "LINE n: <janela da consulta>" e a linha do "^" embaixo. O libpq
# o escreve em linha própria e a janela não tem quebra de linha; ancorar no começo da
# linha mantém o custo linear (só uma tentativa por linha).
_RE_BLOCO_POSICAO = re.compile(r"(?m)^LINE (\d+): [^\n]*\n *\^")


def _diag_do_erro(erro) -> bool:
    """Se o erro (ou o ``orig`` de um DBAPIError) veio do driver do banco."""
    return any(getattr(alvo, "diag", None) is not None for alvo in (
        erro, getattr(erro, "orig", None) if isinstance(erro, DBAPIError) else None))


def _campos_do_erro(erro) -> list[tuple[str, str]]:
    """Os campos com valor do PRÓPRIO erro, cada um com a sua forma redigida: o
    ``diag`` do psycopg e, num erro do SQLAlchemy que embrulha o do driver (e copia a
    mensagem dele), o do ``orig``. Os erros da cadeia (``__cause__``/``__context__``)
    são outros textos, cada um com os seus campos."""
    campos = []
    for alvo in (erro, getattr(erro, "orig", None) if isinstance(erro, DBAPIError) else None):
        diag = getattr(alvo, "diag", None)
        for nome in ("message_detail", "context", "internal_query"):
            try:
                valor = getattr(diag, nome, None)
            except Exception:  # noqa: BLE001 — um diag quebrado não derruba o log
                valor = None
            if isinstance(valor, str) and valor.strip():
                campos.append((valor, _forma_redigida(valor) if nome == "message_detail"
                               else _REDIGIDO))
    return campos


# Nome de tabela no PostgreSQL tem no máximo 63 bytes: o rabo de uma FK cabe aqui.
_JANELA_DO_RABO = 200


def _rabo_da_chave(texto: str, corpo: int, fim: int) -> str | None:
    """O que vem depois do valor em ``texto[corpo:fim]``, se for um rabo CONHECIDO e
    sem valor (a tabela de uma FK é nome de tabela: fica). Só olha o fim do trecho,
    numa janela de tamanho fixo: custo constante."""
    for rabo in _RABOS_FIXOS:
        if texto.endswith(rabo, corpo, fim):
            return rabo
    if not texto.endswith("\".", corpo, fim):
        return None
    for rabo in _RABOS_TABELA:
        pos = texto.rfind(rabo, max(corpo, fim - _JANELA_DO_RABO), fim)
        if pos != -1:
            tabela = texto[pos + len(rabo):fim - 2]
            if "\"" not in tabela and "\n" not in tabela:
                return texto[pos:fim]
    return None


def _forma_redigida(detalhe: str) -> str:
    """O DETAIL exato, sem os valores. Formato desconhecido = redigido inteiro."""
    if detalhe.startswith(_INICIO_LINHA):
        return _INICIO_LINHA + _REDIGIDO + ")."
    separador = detalhe.find(_SEPARADOR) if detalhe.startswith(_INICIO_CHAVE) else -1
    if separador == -1:
        return _REDIGIDO
    colunas = detalhe[len(_INICIO_CHAVE):separador]                       # "a, b"
    corpo = detalhe[:separador + len(_SEPARADOR)] + _REDIGIDO
    for conflito in _CONFLITOS:                     # EXCLUDE: os DOIS valores saem
        if conflito + colunas + _SEPARADOR in detalhe:
            return corpo + conflito + colunas + _SEPARADOR + _REDIGIDO + ")."
    rabo = _rabo_da_chave(detalhe, separador + len(_SEPARADOR), len(detalhe))
    return corpo + (rabo if rabo is not None else ")")


def _trechos_exatos(texto: str, campos: list[tuple[str, str]],
                    do_banco: bool = False) -> tuple[list[tuple[int, int, str]], int]:
    """Cada ocorrência de um campo do dono — (início, fim, forma redigida) —, em ordem
    e sem sobreposição, e a posição a partir da qual o texto tem de ser cortado
    (``len(texto)``: em nenhuma). ``do_banco``: o dono é um erro do driver, e o bloco
    "LINE n:" do texto dele também é um trecho (redigido inteiro). Uma ocorrência
    contida noutra some com ela; duas que se CRUZAM não dão fronteira confiável: o
    texto é cortado no começo da primeira."""
    n = len(texto)
    achados = []
    for exato, forma in set(campos):
        pos = texto.find(exato)
        while pos != -1:
            achados.append((pos, pos + len(exato), forma))
            pos = texto.find(exato, pos + len(exato))
    if do_banco and _ROTULO_POSICAO in texto:
        achados.extend((m.start(), m.end(), f"LINE {m.group(1)}: {_REDIGIDO}")
                       for m in _RE_BLOCO_POSICAO.finditer(texto))
    achados.sort(key=lambda t: (t[0], -t[1]))
    trechos: list[tuple[int, int, str]] = []
    for trecho in achados:
        if trechos and trecho[0] < trechos[-1][1]:   # começa dentro do anterior...
            if trecho[1] > trechos[-1][1]:            # ...e passa dele: cruzam
                return trechos[:-1], trechos[-1][0]
            continue
        trechos.append(trecho)
    return trechos, n


def _inicios_de_detalhe(texto: str) -> list[int]:
    """Onde, em ordem, começa um valor que o PostgreSQL escreveu: logo depois de um
    rótulo ("DETAIL:  ", "CONTEXT:  ", "QUERY:  ", "LINE n: ") ou no começo de uma linha ou chave
    recusada, também sem o rótulo. "Key (" só conta com um ")=(" adiante: sem ele não
    há valor depois (e não há teto para a distância — a expressão de um índice,
    escrita entre os dois, não tem tamanho máximo). Uma varredura."""
    if (_INICIO_LINHA not in texto and _INICIO_CHAVE not in texto
            and _INICIO_PARTICAO not in texto and _ROTULO_POSICAO not in texto
            and not any(rotulo in texto for rotulo in _ROTULOS)):
        return []
    inicios, chaves, ultimo_separador = [], [], -1
    for m in _RE_INICIOS.finditer(texto):
        alvo = m.group()
        if alvo == _SEPARADOR:
            ultimo_separador = m.start()
        elif alvo == _INICIO_CHAVE:
            chaves.append(m.start())
        elif alvo in _ROTULOS or alvo.startswith(_ROTULO_POSICAO):
            inicios.append(m.end())                  # o rótulo fica; o valor, não
        else:
            inicios.append(m.start())
    inicios.extend(ini for ini in chaves if ini < ultimo_separador)
    return sorted(inicios)


def redigir_detalhe_do_banco(texto: str, dono=None) -> str:
    """Tira de um texto os valores que o PostgreSQL copia no erro (veja o comentário
    acima). ``dono``: a exceção cujo PRÓPRIO texto é este (a mensagem dela); só os
    campos dela valem aqui. Sem dono, tudo a partir do primeiro valor sai."""
    if not texto:
        return texto
    trechos, corte = (_trechos_exatos(texto, _campos_do_erro(dono), _diag_do_erro(dono))
                      if dono is not None else ([], len(texto)))
    inicios = _inicios_de_detalhe(texto)
    partes, i, p = [], 0, 0
    for ini, fim, forma in trechos:
        while p < len(inicios) and inicios[p] < i:
            p += 1
        if p < len(inicios) and inicios[p] < ini:    # valor sem forma exata antes
            corte = inicios[p]
            break
        partes.append(texto[i:ini] + forma)
        i = fim
    else:
        while p < len(inicios) and inicios[p] < i:
            p += 1
        if p < len(inicios) and inicios[p] < corte:
            corte = inicios[p]
    if corte < len(texto):
        return "".join(partes) + texto[i:corte] + _REDIGIDO
    return "".join(partes) + texto[i:]


# --- Dado pessoal no texto de uma exceção --------------------------------------------
# O texto de uma exceção é livre e vem de qualquer lugar: o conector escreve nele o
# endereço em que parou (com o token na query), uma biblioteca o valor que recebeu (o
# ``input_value=`` do pydantic, o ``[parameters: …]`` de um engine sem
# ``hide_parameters``), um parser a linha que não entendeu (com o nome da criança). O
# ``logger.exception`` da sync e o ``erro_nao_tratado`` levavam esse texto INTEIRO ao
# campo ``excecao`` do JSON (revisão integrada de 28/10, R4): a redação acima só tira os
# valores que o PostgreSQL copia no erro.
#
# No traceback fica o que serve ao diagnóstico e não identifica ninguém: o TIPO de cada
# exceção, o arquivo, a linha e a função de cada frame (e a linha de CÓDIGO dele, que é
# do repositório, não dado), a cadeia e os grupos. Do texto de cada exceção — e de uma
# exceção passada como ARGUMENTO da mensagem ("falhou: %s", erro) ou no ``extra`` — saem:
#   * URL: a query, o fragmento e o usuário/senha (``usuario:senha@``); o esquema, o
#     host e o caminho ficam, com os tokens de rota tirados por ``redigir_caminho``;
#   * o valor que o Playwright digitou, escrito no "Call log" do erro (``fill("…")``,
#     ``elementHandle.type("…")``, ``elementHandle.press("…")``), e o ``value`` do campo
#     na prévia do elemento que ele achou (veja ``redigir_valor_digitado``);
#   * credencial: o valor de uma chave ``senha=``, ``token:``, ``cookie=``,
#     ``Authorization:``, ``usuario=``, ``nome=``… (também entre aspas, como num dict),
#     o de "senha valor-x" sem separador quando ele tem cara de credencial, o
#     ``Bearer …`` e um JWT; o bloco ``[parameters: …]`` do SQLAlchemy;
#   * token opaco: 32+ letras, dígitos, "_" ou "-" com letra e 4+ dígitos (hash,
#     ``token_urlsafe``, UUID);
#   * e-mail;
#   * número de documento: 6+ dígitos, com ". - /" no meio (CPF, RA, RG, telefone, CEP),
#     exceto data e IPv4 — a régua do assistente (services/assistente.py);
#   * nome: palavras Capitalizadas ("Ana Beatriz Souza") ou em CAIXA ALTA ("ANA BEATRIZ
#     SOUZA") seguidas, separadas só por espaço, com partículas ("de", "dos", "e") no
#     meio, com duas ou mais FORA do vocabulário técnico (SQL, HTTP, os nomes das
#     plataformas): "FOREIGN KEY", "INSERT INTO", "Not Found", "Placar do Matific" ficam.
# Falha para o lado da privacidade: uma frase capitalizada fora do vocabulário também
# vira "<nome>" (o tipo, o frame e a linha continuam lá). Um primeiro nome SOZINHO não é
# reconhecível por padrão e fica. Custo linear no tamanho do texto: cada regex só começa
# no início de uma sequência (lookbehind) e não tem quantificador ambíguo.
#
# Risco residual: é uma heurística por FORMA, não uma garantia. Ficam, por exemplo, um
# nome sozinho ou todo em minúsculas fora de uma chave ("aluno zuleica testelli"), nomes
# invertidos ("Testelli, Zuleica") ou ligados por algo que não é espaço ("%20", "_",
# ";", quebra de linha), um nome com escape \u de JSON, um sobrenome que é palavra do
# vocabulário técnico ("Real", "Rede"), CPF ou telefone com espaços, um caminho sem
# esquema ("/api/v1/publico/…"), um token curto (o do painel tem 12 caracteres) ou com
# menos de 4 dígitos e "x-api-key abc…". Numa chave de nome, a palavra seguida de ":"
# ou "=" é tomada pela chave seguinte e fica ("nome=Ana Souza: duplicado" deixa
# "Souza"). "Sem dado pessoal" vale para as formas acima:
# o que o código escreve no texto da exceção continua sendo escolha de quem o escreve.
_MARCA_NOME = "<nome>"
_MARCA_EMAIL = "<email>"
_MARCA_NUMERO = "<numero>"
_MARCA_TOKEN = "<token>"

# O Playwright escreve no "Call log" do erro o VALOR que digitou (lib/server/dom.js da
# 1.48, a do requirements.txt: ``progress.log(`  fill("${value}")`)``, e o mesmo em
# ``elementHandle.type("…")`` e ``elementHandle.press("…")``), sem escapar nada, e a
# prévia do elemento que achou com os atributos dele ("locator resolved to <input …
# value="…"/>": o valor que a página pôs no campo). O cliente Python junta o call log ao
# texto do erro, uma entrada por linha, separadas por "\n  - " (_impl/_connection.py,
# ``format_call_log``): é assim que a senha e o usuário iam para o log. O valor digitado
# sai até o fim da ENTRADA (a próxima "\n  - " ou o fim do texto): uma aspa, um ")" ou
# uma quebra de linha no valor não o encerram. O ``value`` da prévia (uma linha só: o
# Playwright troca a quebra por "↵") sai até a última aspa da linha, ou até o fim dela.
_COMANDOS_QUE_DIGITAM = ("fill", "type", "press", "pressSequentially", "insertText")
_RE_VALOR_DIGITADO = re.compile(
    r"(\b(?:" + "|".join(_COMANDOS_QUE_DIGITAM) + r")\(\")[\s\S]*?(?=\n  - |\n?\Z)")
_RE_PREVIA_DO_ELEMENTO = re.compile(r"resolved to <[^\n]*")
_RE_VALOR_DA_PREVIA = re.compile(r"(\svalue=\")([^\n]*)")
_MIN_VALOR_EXATO = 3        # um valor menor, trocado onde aparecer, desfiguraria o texto

_RE_URL = re.compile(r"(?<![\w+.\-])[A-Za-z][\w+.\-]{0,30}://[^\s'\"<>`]+")
_PONTUACAO_FINAL_DA_URL = ".,;:!?)]}"
_RE_PARAMETROS_SQL = re.compile(r"\[parameters: [^\n]*")
# A chave: uma palavra inteira seguida (talvez depois de aspas) de ":" ou "=".
_RE_CHAVE = re.compile(r"(?<![\w.\-])[\w.\-]+(?=['\"]?[ \t]*[:=])")
_RE_VALOR_DA_CHAVE = re.compile(
    r"['\"]?[ \t]*[:=][ \t]*(?:(?:[Bb]earer|[Bb]asic|[Tt]oken)[ \t]+)?"
    r"(\"[^\"\n]*\"?|'[^'\n]*'?|[^\s,;&)\]}'\"<>]+)")
_RE_CHAVE_SECRETA = re.compile(
    r"senha|passw|pwd|secret|segredo|token|api_?key|apikey|chave|credencia|credential|"
    r"cookie|session|sessao|sessão|csrf|jwt|auth|bearer|usuario|usuário|username|login|"
    r"input_value|cpf|e_?mail|telefone|celular|nome|name|respons[aá]vel")
_CHAVES_SECRETAS_CURTAS = frozenset({"ra", "rm", "rg", "user", "pass", "key"})
# A chave cujo valor é um NOME ("nome: Ana Souza", "matific|nome:zuleica testelli|…",
# "responsavel: Maria da Silva,"): o valor sem aspas vai além da primeira palavra, pelas
# palavras só de letras que vêm depois, separadas por espaço, até uma palavra do
# vocabulário técnico ("nome = abc AND x" para no AND), a chave seguinte ("nome:a
# sala:3") ou qualquer outra coisa. A partícula ("do", "da", "de"…) é olhada antes do
# vocabulário — "DO" também é SQL — e só entra se um nome vier depois dela: "nome: Maria
# do Carmo" sai inteiro; "nome = abc DO NOTHING" fica com o "DO NOTHING".
_RE_CHAVE_DE_NOME = re.compile(r"nome|name|respons[aá]vel|usu[aá]rio|user|login")
_RE_PROXIMA_PALAVRA_DO_NOME = re.compile(
    r"[ \t]+((?>[^\W\d_]+(?:['’\-][^\W\d_]+)*+))(?![\w'’\-])(?!['\"]?[ \t]*[:=])")
# O marcador de parâmetro do SQL depois de "coluna =" ("alunos.nome = ?", "nome =
# %(nome_1)s", "= %s", "= $1") não é valor: fica. É assim que o "[SQL: …]" de um erro do
# SQLAlchemy mostra cada coluna comparada. Só a forma inteira, seguida de fim de palavra.
_RE_MARCADOR_DO_SQL = re.compile(r"(?:\?|%s|%\([\w.\-]{1,64}\)s|\$\d{1,4})(?![\w(])")
# "senha valor-x", "usuario robo.1", "senha 'Abc12345'": sem ":"/"=", o valor é a palavra
# seguinte (ou o que está entre as aspas que vêm logo depois) — se tiver cara de
# credencial (dígito, ". - _ @ / +" ou maiúscula no meio); "senha inválida" fica.
_RE_CREDENCIAL_SOLTA = re.compile(
    r"(?<![\w.\-])((?i:senha|password|passwd|token|usu[aá]rio|username|user|login|"
    r"cookie|secret|segredo)[ \t]+)(\"[^\"\n]*\"?|'[^'\n]*'?|[^\s,;)\]}'\"<>]+)")
_RE_CARA_DE_CREDENCIAL = re.compile(r"[\d.\-_@/+]|.[A-Z]")
_RE_BEARER = re.compile(r"(?<![\w\-])([Bb]earer[ \t]+)[\w~+/.\-]{8,}=*"
                        r"|(?<![\w\-])([Bb]asic[ \t]+)[A-Za-z0-9+/]{8,}=*")
_RE_JWT = re.compile(r"(?<![\w\-])eyJ[\w\-]{4,}\.[\w\-]{4,}\.[\w\-]*")
_RE_EMAIL_NA_EXCECAO = re.compile(r"(?<![\w.+\-])[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_RE_TOKEN_OPACO = re.compile(r"(?<![\w\-])[\w\-]{32,}")
_RE_NUMERO_NA_EXCECAO = re.compile(r"(?<!\d)\d(?:[.\-/]?\d)*(?:-?[xX](?![^\W\d_]))?")
_RE_DATA_NA_EXCECAO = re.compile(r"\d{1,2}[./\-]\d{1,2}(?:[./\-]\d{2,4})?"
                                 r"|\d{4}[./\-]\d{1,2}[./\-]\d{1,2}")
_RE_IPV4 = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")
_MIN_DIGITOS_DOCUMENTO = 6           # RA (9+), CPF (11), RG (8+), telefone (8+), CEP (8)
# Só dígitos e logo depois uma unidade ("Timeout 180000ms", "1048576 bytes", "20000 ms"):
# é medida, não documento. "s" só colado ("RA 123456789 s/ turma" continua documento).
_RE_UNIDADE_DO_NUMERO = re.compile(
    r"(?:ms|s|[KMG]i?B|B|bytes|[ \t](?:ms|bytes?|[KMG]i?B|B|segundos?|milissegundos?))"
    r"(?![\w/])")
_MIN_DIGITOS_TOKEN = 4
_RE_PALAVRA_DO_NOME = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*")
_RE_JUNTA_DO_NOME = re.compile(r"['’\-]")
_PARTICULAS_DO_NOME = frozenset({
    "de", "da", "do", "das", "dos", "e", "di", "du", "del", "della", "der", "van", "von",
    "la", "le", "y"})
# Palavras que não contam como pedaço de nome (comparadas em caixa alta). Sem as que
# também são nome de gente ("MAX", "MIN", "EDU"): "MAX SILVA" é nome.
_VOCABULARIO_TECNICO = frozenset("""
    SQL INSERT INTO VALUES UPDATE SET DELETE FROM SELECT WHERE AND OR NOT NULL IS IN AS ON
    BY DO NOTHING CONFLICT EXCLUDED RETURNING JOIN LEFT RIGHT INNER OUTER FULL CROSS
    NATURAL LATERAL USING ORDER GROUP HAVING LIMIT OFFSET FETCH NEXT ONLY ASC DESC NULLS
    FIRST LAST DISTINCT ALL ANY SOME EXISTS BETWEEN LIKE ILIKE SIMILAR ESCAPE COLLATE
    NOCASE CASE WHEN THEN ELSE END CAST COALESCE COUNT SUM AVG LOWER UPPER TRIM
    EXTRACT EPOCH DATE TIME TIMESTAMP ZONE AT INTERVAL INTEGER BIGINT SMALLINT TEXT
    VARCHAR CHAR CHARACTER VARYING BOOLEAN NUMERIC DECIMAL FLOAT REAL DOUBLE PRECISION
    JSON JSONB UUID BYTEA SERIAL DEFAULT PRIMARY FOREIGN KEY UNIQUE CHECK CONSTRAINT
    REFERENCES INDEX TABLE VIEW CREATE DROP ALTER ADD COLUMN RENAME TO IF CASCADE
    RESTRICT TRIGGER FUNCTION RETURNS LANGUAGE BEGIN COMMIT ROLLBACK SAVEPOINT RELEASE
    TRANSACTION ISOLATION LEVEL SERIALIZABLE REPEATABLE READ COMMITTED UNCOMMITTED WRITE
    UNION INTERSECT EXCEPT WITH RECURSIVE OVER PARTITION WINDOW ROWS ROW RANGE FILTER
    ARRAY FOR SHARE SKIP LOCKED NOWAIT LOCK MODE EXCLUSIVE ACCESS NO ACTION DEFERRABLE
    INITIALLY DEFERRED IMMEDIATE PRAGMA VACUUM ANALYZE EXPLAIN TRUE FALSE UNKNOWN
    SEQUENCE TEMP TEMPORARY GENERATED ALWAYS IDENTITY STORED OF WITHOUT
    DETAIL CONTEXT QUERY LINE HINT ERROR FATAL PANIC WARNING NOTICE INFO DEBUG LOG
    STATEMENT HTTP HTTPS GET POST PUT PATCH HEAD OPTIONS URL URI API ID UTC BRT CSV PDF
    XLSX XLSM ODS XML HTML TLS SSL TCP DNS OK CORS JWT SSO CAPTCHA
    BAD REQUEST REQUESTS FOUND INTERNAL SERVER SERVICE UNAVAILABLE GATEWAY TIMEOUT TOO
    MANY FORBIDDEN UNAUTHORIZED METHOD ALLOWED GONE UNPROCESSABLE ENTITY CONTENT PAYLOAD
    LARGE PRECONDITION FAILED REQUIRED UNSUPPORTED MEDIA TYPE MOVED PERMANENTLY TEMPORARY
    REDIRECT PERMANENT SEE OTHER MODIFIED PROXY AUTHENTICATION CREATED ACCEPTED PARTIAL
    RESET LENGTH EXPECTATION UPGRADE DEPENDENCY HEADER FIELDS NETWORK VERSION SUPPORTED
    INSUFFICIENT STORAGE IMPLEMENTED CONNECTION REFUSED ABORTED
    MATIFIC ELEFANTE LETRADO CONSTELA QUEST PLACAR LISTA PILOTO LOGIN GOOGLE
    RAILWAY SUPABASE SENTRY PLAYWRIGHT CHROMIUM EXPO ZIP
    ADMIN GLOBAL REDE MUNICIPAL ESTADUAL FEDERAL PRIVADA INEP SARESP SAEB IDEB IBGE SEDUC
    CODMUN
""".split())


def _url_sem_segredo(achado: re.Match) -> str:
    url = achado.group()
    fim = len(url)
    while fim and url[fim - 1] in _PONTUACAO_FINAL_DA_URL:
        fim -= 1
    url, rabo = url[:fim], url[fim:]
    esquema, _, resto = url.partition("://")
    corte = min((p for p in (resto.find("/"), resto.find("?"), resto.find("#")) if p != -1),
                default=len(resto))
    autoridade, caminho = resto[:corte], resto[corte:]
    if "@" in autoridade:                                  # usuario:senha@host
        autoridade = _REDIGIDO + "@" + autoridade.rpartition("@")[2]
    consulta = min((p for p in (caminho.find("?"), caminho.find("#")) if p != -1), default=-1)
    if consulta != -1:                                     # ?token=… e #…
        caminho = caminho[:consulta + 1] + _REDIGIDO
    return esquema + "://" + autoridade + redigir_caminho(caminho) + rabo


def _chave_secreta(chave: str) -> bool:
    chave = chave.lower()
    return chave in _CHAVES_SECRETAS_CURTAS or _RE_CHAVE_SECRETA.search(chave) is not None


def _sem_credenciais(texto: str) -> str:
    """O valor de cada chave secreta ("senha=…", "'token': '…'", "Authorization: Bearer
    …") vira ``<redigido>``; a chave fica (diz O QUE faltou)."""
    partes, i = [], 0
    for chave in _RE_CHAVE.finditer(texto):
        if chave.start() < i or not _chave_secreta(chave.group()):
            continue
        valor = _RE_VALOR_DA_CHAVE.match(texto, chave.end())
        if valor is None or _marcador_do_sql(texto, valor):
            continue
        partes.append(texto[i:valor.start(1)] + _REDIGIDO)
        i = valor.end(1)
        if (_RE_CHAVE_DE_NOME.search(chave.group().lower())
                and _RE_PALAVRA_DO_NOME.fullmatch(valor.group(1))):
            j = i
            while proxima := _RE_PROXIMA_PALAVRA_DO_NOME.match(texto, j):
                palavra = proxima.group(1)
                j = proxima.end()
                if palavra.lower() in _PARTICULAS_DO_NOME:
                    continue
                if palavra.upper() in _VOCABULARIO_TECNICO:
                    break
                i = j
    partes.append(texto[i:])
    return "".join(partes)


def _marcador_do_sql(texto: str, valor: re.Match) -> bool:
    marcador = _RE_MARCADOR_DO_SQL.match(texto, valor.start(1))
    return marcador is not None and marcador.end() >= valor.end(1)


def _credencial_solta(achado: re.Match) -> str:
    valor = achado.group(2)
    if valor[0] in "'\"":                       # entre aspas: o que está dentro delas
        valor = valor[1:-1] if len(valor) > 1 and valor[-1] == valor[0] else valor[1:]
    if valor.startswith("<") or not _RE_CARA_DE_CREDENCIAL.search(valor):
        return achado.group()
    return achado.group(1) + _REDIGIDO


def _bearer_redigido(achado: re.Match) -> str:
    return (achado.group(1) or achado.group(2)) + _REDIGIDO


def _token_opaco(achado: re.Match) -> str:
    bruto = achado.group()
    digitos = sum(map(str.isdigit, bruto))            # map: a conta corre em C
    if digitos >= _MIN_DIGITOS_TOKEN and any(map(str.isalpha, bruto)):
        return _MARCA_TOKEN
    return bruto


def _numero_de_documento(achado: re.Match) -> str:
    bruto = achado.group()
    if (sum(map(str.isdigit, bruto)) < _MIN_DIGITOS_DOCUMENTO
            or _RE_DATA_NA_EXCECAO.fullmatch(bruto) or _RE_IPV4.fullmatch(bruto)):
        return bruto
    if bruto.isdecimal() and _RE_UNIDADE_DO_NUMERO.match(achado.string, achado.end()):
        return bruto
    return _MARCA_NUMERO


def _forma_da_palavra(palavra: str) -> str | None:
    """"particula" ("de", "DOS", uma letra maiúscula sozinha), "nome" (Capitalizada ou
    em CAIXA ALTA, também com hífen/apóstrofo: "D'Ávila", "ANA-CLARA") ou None."""
    if palavra.lower() in _PARTICULAS_DO_NOME or (len(palavra) == 1 and palavra.isupper()):
        return "particula"
    pedacos = list(filter(None, _RE_JUNTA_DO_NOME.split(palavra)))
    if all(map(str.isupper, pedacos)) and sum(map(len, pedacos)) >= 2:
        return "nome"
    if all(p[0].isupper() and (len(p) == 1 or p[1:].islower()) for p in pedacos):
        return "nome"
    return None


# Um TRECHO: duas ou mais palavras (as de ``_RE_PALAVRA_DO_NOME``) separadas só por
# espaço, tab ou nbsp — o único lugar em que cabe um nome de duas palavras. Começa no
# início de uma palavra (não depois de letra nem de "letra + hífen/apóstrofo", que é o
# meio de uma) e as palavras são atômicas: custo linear, sem retrocesso.
_PALAVRA = r"(?>[^\W\d_]+(?:['’\-][^\W\d_]+)*+)"
_RE_TRECHO_DE_PALAVRAS = re.compile(
    r"(?<![^\W\d_])(?<![^\W\d_]['’\-])" + _PALAVRA + r"(?:[ \t\u00a0]++" + _PALAVRA + r")+")
_RE_ESPACO_DO_TRECHO = re.compile(r"([ \t\u00a0]+)")
# O código de cada palavra do trecho: "x" (não é de nome: fecha o grupo), "p" (partícula),
# "t" (nome do vocabulário técnico) ou "n" (nome fora dele). Um grupo é uma sequência
# sem "x"; o casamento vai do primeiro ao último nome dele.
_RE_NOMES_DO_GRUPO = re.compile(r"[tn](?:[ptn]*[tn])?")


def _codigo_da_palavra(palavra: str) -> str:
    forma = _forma_da_palavra(palavra)
    if forma is None:
        return "x"
    if forma == "particula":
        return "p"
    return "t" if palavra.upper() in _VOCABULARIO_TECNICO else "n"


def _sem_nomes(texto: str) -> str:
    """Cada sequência de palavras de nome (veja ``_forma_da_palavra``), separadas só por
    espaço/tab/nbsp e com partículas no meio, vira ``<nome>`` se duas ou mais estiverem
    fora do vocabulário técnico.

    O trabalho por palavra corre em C (regex, ``split``, ``set``, ``map``, ``join``): o
    Python só classifica cada palavra DISTINTA de um trecho que tem maiúscula (um trecho
    todo em minúsculas não tem nome) e só calcula posições no trecho que tem o que
    redigir."""
    partes, i = [], 0
    codigos_vistos: dict[str, str] = {}
    for trecho in _RE_TRECHO_DE_PALAVRAS.finditer(texto):
        bruto = trecho.group()
        if bruto.islower():
            continue
        pedacos = _RE_ESPACO_DO_TRECHO.split(bruto)     # palavra, espaço, palavra, …
        palavras = pedacos[::2]
        for palavra in set(palavras).difference(codigos_vistos):
            codigos_vistos[palavra] = _codigo_da_palavra(palavra)
        codigos = "".join(map(codigos_vistos.__getitem__, palavras))
        if codigos.count("n") < 2:
            continue
        fins: list[int] | None = None                  # fim de cada pedaço no trecho
        for grupo in _RE_NOMES_DO_GRUPO.finditer(codigos):
            if codigos.count("n", grupo.start(), grupo.end()) < 2:
                continue
            if fins is None:
                fins = list(accumulate(map(len, pedacos)))
            primeira, ultima = grupo.start(), grupo.end() - 1
            inicio = trecho.start() + (fins[2 * primeira - 1] if primeira else 0)
            partes.append(texto[i:inicio] + _MARCA_NOME)
            i = trecho.start() + fins[2 * ultima]
    partes.append(texto[i:])
    return "".join(partes)


def _valor_digitado_redigido(achado: re.Match) -> str:
    return achado.group(1) + _REDIGIDO + '")'


def _previa_sem_valor(achado: re.Match) -> str:
    return _RE_VALOR_DA_PREVIA.sub(_valor_da_previa_redigido, achado.group())


def _valor_da_previa_redigido(achado: re.Match) -> str:
    resto = achado.group(2)
    fecha = resto.rfind('"')
    return achado.group(1) + _REDIGIDO + (resto[fecha:] if fecha != -1 else "")


def redigir_valor_digitado(texto: str, valor: str | None = None) -> str:
    """O texto de um erro do Playwright sem o valor que ele digitou e sem o ``value`` do
    campo na prévia do elemento (veja o comentário de ``_RE_VALOR_DIGITADO``). Com
    ``valor`` (o que foi digitado, quem chama sabe), também sem nenhuma ocorrência EXATA
    dele, onde estiver. Sem nada disso, volta igual."""
    if not texto:
        return texto
    if valor and len(valor) >= _MIN_VALOR_EXATO:
        texto = texto.replace(valor, _REDIGIDO)
    if '("' in texto:
        texto = _RE_VALOR_DIGITADO.sub(_valor_digitado_redigido, texto)
    if "resolved to <" in texto:
        texto = _RE_PREVIA_DO_ELEMENTO.sub(_previa_sem_valor, texto)
    return texto


def redigir_dados_pessoais(texto: str) -> str:
    """Tira de um texto LIVRE (o de uma exceção) URL com query ou usuário, credencial,
    token, e-mail, número de documento e nome (veja o comentário acima). Texto técnico
    sem nada disso volta igual."""
    if not texto:
        return texto
    texto = redigir_valor_digitado(texto)        # antes de tudo: o valor é qualquer coisa
    texto = _RE_URL.sub(_url_sem_segredo, texto)
    texto = _RE_PARAMETROS_SQL.sub("[parameters: " + _REDIGIDO + "]", texto)
    texto = _sem_credenciais(texto)
    texto = _RE_BEARER.sub(_bearer_redigido, texto)
    texto = _RE_CREDENCIAL_SOLTA.sub(_credencial_solta, texto)
    texto = _RE_JWT.sub(_MARCA_TOKEN, texto)
    texto = _RE_EMAIL_NA_EXCECAO.sub(_MARCA_EMAIL, texto)
    texto = _RE_TOKEN_OPACO.sub(_token_opaco, texto)
    texto = _RE_NUMERO_NA_EXCECAO.sub(_numero_de_documento, texto)
    return _sem_nomes(texto)


# --- Teto do texto de uma exceção ----------------------------------------------------
# A redação acima custa ~0,4 s por MB de texto (linear), e o formatador é síncrono: o
# ``logger.exception("erro_nao_tratado")`` do middleware formata DENTRO da corrotina, com o
# event loop parado, e esse tempo entra no ``dur_ms`` do ``http_acesso``. Um IntegrityError
# de um INSERT com milhares de linhas de VALUES traz centenas de KB de "[SQL: …]". Acima de
# ``_LIMITE_DO_TEXTO`` caracteres, o texto de uma exceção (no traceback, como argumento da
# mensagem ou no ``extra``) sai só com a CABEÇA (até ``_CABECA``) e a CAUDA (até
# ``_CAUDA``), e o meio vira "[... N caracteres omitidos]": ele não é redigido nem escrito,
# e o custo e o tamanho da linha deixam de crescer com o texto. O corte vem depois do
# DETAIL do banco (que precisa do texto inteiro: o rótulo pode estar no meio e o valor na
# cauda) e antes da redação acima; o tipo e as linhas 'File "…", line n' de cada frame não
# são esse texto e ficam sempre. Até o limite, o texto sai byte a byte como antes.
#
# O corte não pode partir um dado: o pedaço que sobra escaparia das regras (um token com
# menos de 32 caracteres, um número com menos de 6 dígitos, meio nome).
#   * a CABEÇA termina num espaço, tab ou quebra de linha, e só onde a redação dela é o
#     começo da redação do texto com mais ``_MARGEM`` caracteres à vista: um dado partido
#     ali sai diferente quando o resto aparece ("Zuleica" sozinho × "<nome>", "senha 'ab"
#     × "senha <redigido>"), e o corte recua para o espaço anterior. Vale para qualquer
#     regra, sem enumerá-las. Escaparia só um dado com espaço dentro, mais longo que
#     ``_MARGEM``, reconhecível apenas pelo que vem depois disso; os que vão até o fim do
#     texto (o valor digitado, o "[parameters: …]", o valor entre aspas de uma chave) já
#     saem redigidos até o fim da cabeça;
#   * a CAUDA começa no começo de uma linha. Nenhuma regra atravessa uma quebra de linha,
#     salvo o valor digitado no Playwright, que vai até a próxima entrada do call log
#     ("\n  - "): se um ``fill("``/``type("``… depois da última entrada antes da cauda o
#     abriu, a cauda começa na entrada que o fecha (sem ela, não há cauda). Sem uma linha
#     inteira nas últimas ``_CAUDA`` letras, também não.
# Numa cadeia (ou grupo), o teto vale para cada exceção, sob o orçamento do traceback
# (``_ORCAMENTO_DO_TRACEBACK``). O DETAIL do banco, antes do teto, é linear no texto
# inteiro, como na base: ~3 ms/MB em texto comum e até ~36 ms/MB em texto denso de
# rótulos ("DETAIL:", "Key (", "LINE n:").
_LIMITE_DO_TEXTO = 16_384           # caracteres; até aqui o texto sai inteiro
_CABECA = 12_288
_CAUDA = _LIMITE_DO_TEXTO - _CABECA
_MARGEM = 128
_TENTATIVAS_DE_CORTE = 4
_OMITIDOS = "[... {} caracteres omitidos]"
_ENTRADA_DO_CALL_LOG = "\n  - "
# O máximo que a redação vê no texto de UMA exceção (a janela da cabeça, os recuos e a
# cauda): ~66 mil caracteres, ~26 ms. É também o orçamento de um evento do Sentry.
_TETO_DA_REDACAO = (_TENTATIVAS_DE_CORTE + 1) * (_CABECA + _MARGEM) + _CAUDA


def _inicio_redigido(texto: str, fim: int, redigir=None) -> tuple[int, str]:
    """(k, redação de ``texto[:k]``): o começo de ``texto[:fim]`` que pode sair sem o resto.
    ``texto[k]`` é um espaço, tab ou quebra de linha a mais de ``_MARGEM`` caracteres de
    ``fim``, e a redação de ``texto[:k]`` é o começo da redação de ``texto[:fim]``: nenhum
    dado partido em k (veja o comentário acima). Recua por até ``_TENTATIVAS_DE_CORTE``
    espaços; sem nenhum que sirva, (0, ""). ``redigir``: a redação a usar (a de um
    orçamento, que conta o que vê); sem ela, ``redigir_dados_pessoais``."""
    redigir = redigir or redigir_dados_pessoais
    janela = redigir(texto[:fim])
    limite = max(fim - _MARGEM, 0)
    for _ in range(_TENTATIVAS_DE_CORTE):
        k = max(texto.rfind(" ", 0, limite), texto.rfind("\t", 0, limite),
                texto.rfind("\n", 0, limite))
        if k <= 0:
            break
        cabeca = redigir(texto[:k])
        if janela.startswith(cabeca):
            return k, cabeca
        limite = k
    return 0, ""


def _inicio_da_cauda(texto: str) -> int:
    """Onde começa a cauda: no começo de uma linha entre as últimas ``_CAUDA`` letras, fora
    de um valor digitado no Playwright que possa estar aberto ali; ``len(texto)``: sem
    cauda (veja o comentário acima)."""
    quebra = texto.find("\n", len(texto) - _CAUDA - 1)
    if quebra == -1:
        return len(texto)
    # Um valor aberto antes da última entrada do call log (até a quebra) acabou nela; um
    # aberto depois dela atravessa a quebra e vai até a próxima entrada (ou o fim). Busca
    # em C, sem o \b da regex (na dúvida, sem cauda): custo linear de ~1 ms por MB.
    desde = max(texto.rfind(_ENTRADA_DO_CALL_LOG, 0, quebra + len(_ENTRADA_DO_CALL_LOG)), 0)
    if texto.find('("', desde, quebra) != -1 and any(
            texto.find(comando + '("', desde, quebra) != -1
            for comando in _COMANDOS_QUE_DIGITAM):
        fecha = texto.find(_ENTRADA_DO_CALL_LOG, quebra + 1)
        if fecha == -1:
            return len(texto)
        quebra = fecha
    return quebra + 1


def _sem_dado_pessoal_com_teto(texto: str, redigir=None) -> str:
    """``redigir_dados_pessoais`` do texto de uma exceção; acima de ``_LIMITE_DO_TEXTO``,
    só da cabeça e da cauda, com o meio omitido (veja o comentário acima). ``redigir``:
    como em ``_inicio_redigido``."""
    redigir = redigir or redigir_dados_pessoais
    if len(texto) <= _LIMITE_DO_TEXTO:
        return redigir(texto)
    fim_da_cabeca, cabeca = _inicio_redigido(texto, _CABECA + _MARGEM, redigir)
    inicio_da_cauda = _inicio_da_cauda(texto)
    if inicio_da_cauda == len(texto):                   # sem cauda: o "\n" do fim fica
        final = "\n" if texto.endswith("\n") else ""
        omitido_ate = len(texto) - len(final)
    else:                                               # a quebra antes da cauda fica
        final = "\n" + redigir(texto[inicio_da_cauda:])
        omitido_ate = inicio_da_cauda - 1
    omitido_de = fim_da_cabeca + 1 if cabeca else 0     # o espaço do corte vira a junção
    juncao = "\n" if cabeca and texto[fim_da_cabeca] == "\n" else " "
    return cabeca + juncao + _OMITIDOS.format(omitido_ate - omitido_de) + final


_RE_LINHA_DO_ARQUIVO = re.compile(r'[ \t]*File "[^"\n]*", line \d+\n?')


def _excecao_sem_dado_pessoal(texto: str, rotulo: str | None, redigir=None) -> str:
    """O texto de UMA exceção ("modulo.Tipo: mensagem" e as notas) com a mensagem e as
    notas sem dado pessoal (e com o teto de ``_sem_dado_pessoal_com_teto``). O rótulo do
    tipo fica; num SyntaxError, as linhas 'File "…", line n' que vêm antes dele também (a
    linha de código mostrada ali pode ser o texto avaliado, e é redigida). ``redigir``:
    como em ``_inicio_redigido``."""
    if rotulo and texto.startswith(rotulo):
        return rotulo + _sem_dado_pessoal_com_teto(texto[len(rotulo):], redigir)
    pos = texto.find("\n" + rotulo) + 1 if rotulo else 0
    if pos <= 0:
        return _sem_dado_pessoal_com_teto(texto, redigir)
    cabeca = "".join(linha if _RE_LINHA_DO_ARQUIVO.fullmatch(linha)
                     else _sem_dado_pessoal_com_teto(linha, redigir)
                     for linha in texto[:pos].splitlines(keepends=True))
    return (cabeca + rotulo +
            _sem_dado_pessoal_com_teto(texto[pos + len(rotulo):], redigir))


def _texto_sem_dado_pessoal(texto: str) -> str:
    """Um texto livre (o de uma exceção) sem o DETAIL do banco (sem dono: falha fechada) e
    sem dado pessoal, com o teto de ``_sem_dado_pessoal_com_teto``."""
    return _sem_dado_pessoal_com_teto(redigir_detalhe_do_banco(texto))


def _repr_sem_dado_pessoal(erro: BaseException) -> str:
    """O ``repr()`` da exceção com o texto de cada argumento sem dado pessoal; sem dado,
    o mesmo do Python ("KeyError('escola_id')", "RuntimeError()", "ValueError('a', 2)").
    Refaz o ``BaseException.__repr__`` (o nome do tipo e o repr de cada argumento) sobre
    os argumentos redigidos; um tipo com ``__repr__`` próprio tem o texto dele redigido."""
    if type(erro).__repr__ is not BaseException.__repr__:
        return _texto_sem_dado_pessoal(repr(erro))
    itens = (repr(_texto_sem_dado_pessoal(a)) if type(a) is str
             else _texto_sem_dado_pessoal(repr(a)) for a in erro.args)
    return f"{type(erro).__name__.rpartition('.')[2]}({', '.join(itens)})"


_STR_DA_EXCECAO_FALHOU = "<exception str() failed>"      # o do traceback.py


class _ExcecaoNaMensagem(str):
    """Uma exceção passada como argumento da mensagem do log: o ``%s`` vira o texto
    dela sem o DETAIL do banco e sem dado pessoal; o ``%r``, o ``repr()`` dela com o
    mesmo cuidado (feito só se a mensagem pedir, como o ``%r`` de antes). Um ``__str__``
    que falha não derruba o ``%r``: o texto vira o marcador que o traceback do Python
    escreve nesse caso."""

    def __new__(cls, erro: BaseException):
        try:
            texto = _texto_sem_dado_pessoal(str(erro))
        except Exception:  # noqa: BLE001 — o __str__ é do tipo da exceção, qualquer um
            texto = _STR_DA_EXCECAO_FALHOU
        objeto = super().__new__(cls, texto)
        objeto._erro = erro
        return objeto

    def __repr__(self) -> str:
        return _repr_sem_dado_pessoal(self._erro)


class _Ciclo:
    """O ponto em que uma lista, tupla ou dict volta a si mesmo: escrito como o
    ``repr()`` o escreve ("[...]", "(...)", "{...}"), sem ser percorrido de novo nem
    levar o original (com uma exceção crua dentro) para a mensagem."""
    __slots__ = ("_texto",)

    def __init__(self, valor):
        self._texto = ("[...]" if type(valor) is list else
                       "{...}" if type(valor) is dict else "(...)")

    def __repr__(self) -> str:
        return self._texto

    __str__ = __repr__


def _sem_excecoes(valor, nivel: int = 0, _caminho: frozenset[int] = frozenset()):
    """``valor`` com cada exceção trocada por ``_ExcecaoNaMensagem`` — também dentro de
    uma tupla, lista ou dict (os tipos exatos; no primeiro nível, os argumentos do
    registro, qualquer tupla ou Mapping), até ``_PROFUNDIDADE_MAX`` níveis. Sem exceção
    nem ciclo, volta o MESMO objeto.

    Um objeto que já está no caminho (um ciclo) vira ``_Ciclo``, como no ``repr()``:
    sem isso, dois ciclos na mesma lista dobravam o trabalho a cada nível (2^32
    visitas). Os argumentos do registro (o nível 0) não entram no caminho: cada um é
    escrito por si ("%(a)s" de um dict que se contém escreve o dict inteiro)."""
    if isinstance(valor, BaseException):
        return _ExcecaoNaMensagem(valor)
    if id(valor) in _caminho:
        return _Ciclo(valor)
    if nivel >= _PROFUNDIDADE_MAX:
        return valor
    if type(valor) in (tuple, list) or (nivel == 0 and isinstance(valor, tuple)):
        caminho = _caminho | {id(valor)} if nivel else _caminho
        itens = [_sem_excecoes(item, nivel + 1, caminho) for item in valor]
        if all(novo is item for novo, item in zip(itens, valor)):
            return valor
        return itens if type(valor) is list else tuple(itens)
    if type(valor) is dict or (nivel == 0 and isinstance(valor, Mapping)):
        caminho = _caminho | {id(valor)} if nivel else _caminho
        itens = {chave: _sem_excecoes(item, nivel + 1, caminho)
                 for chave, item in valor.items()}
        if all(itens[chave] is item for chave, item in valor.items()):
            return valor
        return itens
    return valor


def _mensagem_do_registro(record: logging.LogRecord) -> str:
    """O ``getMessage()`` do registro, com cada EXCEÇÃO — a própria mensagem
    (``logger.error(erro)``) ou um argumento ("falhou: %s", erro), também dentro de uma
    lista, tupla ou dict ("%s", [erro]) — trocada pelo texto dela sem dado pessoal. Os
    outros argumentos ficam como estão: o que vai para a mensagem, o código escolhe."""
    args = _sem_excecoes(record.args) if record.args else record.args
    if args is record.args and not isinstance(record.msg, BaseException):
        return record.getMessage()
    msg = record.msg
    texto = str(_ExcecaoNaMensagem(msg)) if isinstance(msg, BaseException) else str(msg)
    return texto % args if record.args else texto


def _texto_para_o_json(objeto) -> str:
    """O ``default`` do ``json.dumps`` do log: um objeto do ``extra`` vira texto
    redigido (uma exceção, também sem dado pessoal)."""
    if isinstance(objeto, BaseException):
        return _texto_sem_dado_pessoal(str(objeto))
    return redigir_detalhe_do_banco(str(objeto))


# --- Traceback e eventos: cada texto com o seu dono ----------------------------------
_ELO_CAUSA = "\nThe above exception was the direct cause of the following exception:\n\n"
_ELO_CONTEXTO = "\nDuring handling of the above exception, another exception occurred:\n\n"
_GRUPO = getattr(builtins, "BaseExceptionGroup", ())
_NOS_MAX = 64            # exceções num traceback (cadeia + grupos)
_GRUPO_MAX = 15          # subexceções mostradas por grupo, como o traceback do Python
_GRUPO_NIVEIS = 10
# O teto do texto vale por exceção (``_TETO_DA_REDACAO``, ~26 ms): uma cadeia ou um grupo
# com ``_NOS_MAX`` exceções enormes pagaria isso 64 vezes (~1,7 s com o event loop
# parado). Por traceback, a redação tem um orçamento: as exceções são redigidas da de cima
# (a mais recente) à mais antiga, e depois os membros dos grupos; acabado o orçamento, as
# seguintes saem só com o tipo e ``_TEXTO_FORA_DO_ORCAMENTO`` (os frames e os elos ficam).
# O que resta é conferido ANTES de cada exceção: o total passa do orçamento em no máximo
# o custo de uma.
_ORCAMENTO_DO_TRACEBACK = 2 * _TETO_DA_REDACAO
_TEXTO_FORA_DO_ORCAMENTO = "[texto omitido: limite da redação do traceback]"


def traceback_redigido(erro: BaseException, tb=None) -> str:
    """O traceback da cadeia, na ordem e no formato do ``traceback.format_exception``,
    com o texto de CADA exceção redigido só com os campos dela (o de outro erro da
    cadeia, copiado no texto dela, falha fechado). ``tb``: o da exceção de cima, se
    não for o ``__traceback__`` dela (``exc_info`` do log).

    Um único ``TracebackException`` com ``compact=True``, como o do
    ``format_exception`` (sem ele, o contexto SUPRIMIDO de uma exceção era montado e
    marcado como visto, e a causa raiz sumia de outro ramo da cadeia), dá a cadeia já
    sem ciclos, as pilhas e o texto de cada exceção; a exceção real ao lado, nó a nó,
    dá o ``diag``. A redação tem o orçamento de ``_ORCAMENTO_DO_TRACEBACK``."""
    te = traceback.TracebackException(
        type(erro), erro, tb if tb is not None else erro.__traceback__, compact=True)
    orcamento = _Orcamento(_ORCAMENTO_DO_TRACEBACK)
    return "".join(_partes_do_traceback(te, erro, [0], 0, orcamento)).rstrip("\n")


def _partes_do_traceback(te, erro, contador: list[int], nivel: int,
                         orcamento: _Orcamento) -> list[str]:
    cadeia, t, e = [], te, erro
    while t is not None and contador[0] < _NOS_MAX:
        contador[0] += 1
        if t.__cause__ is not None:
            elo, proximo = _ELO_CAUSA, (t.__cause__, e.__cause__)
        elif t.__context__ is not None and not t.__suppress_context__:
            elo, proximo = _ELO_CONTEXTO, (t.__context__, e.__context__)
        else:
            elo, proximo = None, (None, None)
        # o texto já aqui: o orçamento vai da exceção de cima à mais antiga
        cadeia.append((elo, t, e, _texto_da_excecao_redigido(t, e, orcamento)))
        t, e = proximo
    # O elo de cada exceção (com a causa dela, impressa logo antes) vem antes dela.
    partes: list[str] = []
    if t is not None:                              # o teto de exceções acabou aqui
        partes.append(f"[exceções mais antigas omitidas: limite de {_NOS_MAX}]\n" if cadeia
                      else f"[exceção omitida: limite de {_NOS_MAX}]\n")
    for elo, t, e, texto in reversed(cadeia):
        if elo is not None:
            partes.append(elo)
        if t.stack:
            partes.append("Traceback (most recent call last):\n")
            partes.extend(t.stack.format())
        partes.append(texto)
        if t.exceptions is not None and nivel >= _GRUPO_NIVEIS:
            partes.append(f"+---------------- ... (limite de {_GRUPO_NIVEIS} níveis de "
                          "grupo) ----------------\n")
        elif t.exceptions is not None:
            # O TracebackException monta TODOS os membros; o teto de largura é aqui.
            membros = list(zip(t.exceptions, e.exceptions))
            for j, (sub_t, sub_e) in enumerate(membros[:_GRUPO_MAX], 1):
                partes.append(f"+---------------- {j} ----------------\n")
                partes.append(textwrap.indent("".join(_partes_do_traceback(
                    sub_t, sub_e, contador, nivel + 1, orcamento)), "| "))
            if len(membros) > _GRUPO_MAX:
                partes.append(f"+---------------- e mais {len(membros) - _GRUPO_MAX} "
                              "exceções ----------------\n")
    return partes


def _texto_da_excecao_redigido(t, e, orcamento: _Orcamento) -> str:
    """O texto de uma exceção ("Tipo: mensagem" e as notas), primeiro sem o DETAIL do
    banco (com os campos do dono) e depois sem dado pessoal; o tipo fica. Sem orçamento,
    só o tipo e ``_TEXTO_FORA_DO_ORCAMENTO`` (nem o DETAIL é procurado)."""
    rotulo = _rotulo_do_tipo(t, e)
    if orcamento.restante <= 0:
        return (f"{rotulo}: " if rotulo else "") + _TEXTO_FORA_DO_ORCAMENTO + "\n"
    return _excecao_sem_dado_pessoal(_texto_da_excecao_sem_detalhe(t, e), rotulo,
                                     orcamento.redigir)


def _rotulo_do_tipo(t, e) -> str | None:
    """O "modulo.Tipo" com que o ``format_exception_only`` começa a linha da exceção."""
    rotulo = getattr(t, "exc_type_str", None)        # Python 3.13
    if isinstance(rotulo, str):
        return rotulo
    tipo = type(e)
    nome, modulo = getattr(tipo, "__qualname__", None), getattr(tipo, "__module__", None)
    if not isinstance(nome, str):
        return None
    return nome if modulo in ("__main__", "builtins") or not isinstance(modulo, str) else (
        f"{modulo}.{nome}")


def _texto_da_excecao_sem_detalhe(t, e) -> str:
    """O texto de uma exceção sem o DETAIL do banco. Só a MENSAGEM é o texto do dono; as
    notas (``add_note``) podem trazer o texto de outro erro e falham fechado."""
    texto = "".join(t.format_exception_only())
    if t.__notes__:
        sem_notas = copy.copy(t)
        sem_notas.__notes__ = None
        base = "".join(sem_notas.format_exception_only())
        if texto.startswith(base):
            return redigir_detalhe_do_banco(base, e) + redigir_detalhe_do_banco(texto[len(base):])
        return redigir_detalhe_do_banco(texto)
    return redigir_detalhe_do_banco(texto, e)


def _traceback_do_registro(formatador: logging.Formatter, exc_info) -> str:
    valor = exc_info[1] if len(exc_info) > 1 else None
    if isinstance(valor, BaseException):
        return traceback_redigido(valor, exc_info[2] if len(exc_info) > 2 else None)
    return redigir_dados_pessoais(redigir_detalhe_do_banco(formatador.formatException(exc_info)))


def _nos_da_cadeia(erro) -> list[BaseException]:
    """As exceções que o Sentry põe em ``exception.values``: a de cima, a cadeia
    (``__cause__`` e ``__context__``) e as de um grupo."""
    nos, vistos, pilha = [], set(), [erro]
    while pilha and len(nos) < _NOS_MAX:
        e = pilha.pop()
        if not isinstance(e, BaseException) or id(e) in vistos:
            continue
        vistos.add(id(e))
        nos.append(e)
        pilha.extend((e.__cause__, e.__context__))
        if isinstance(e, _GRUPO):
            pilha.extend(e.exceptions)
    return nos


def _texto_no_sentry(erro: BaseException) -> tuple[str, str] | None:
    """O ``value`` que o sentry-sdk 2.x escreve para esta exceção, antes de cortar
    (``utils.get_error_message``), e a parte dele que é a MENSAGEM (o SDK acrescenta as
    notas depois dela). Refeito aqui, sem chamar o do SDK: aquele ESTENDE a lista
    ``.detail`` de um erro do SQLAlchemy com as notas, letra por letra — mudaria o
    próprio erro que se está redigindo. Mensagem que não é texto: sem dono (falha
    fechada)."""
    try:
        mensagem = (getattr(erro, "message", "") or getattr(erro, "detail", "")
                    or str(erro))
        if not isinstance(mensagem, str):
            return None
        notas = getattr(erro, "__notes__", None)
        if isinstance(notas, list) and notas:
            return mensagem + "\n" + "\n".join(n for n in notas if isinstance(n, str)), mensagem
        return mensagem, mensagem
    except Exception:  # noqa: BLE001
        return None


_PROFUNDIDADE_MAX = 32
_OMITIDO = "<estrutura omitida>"


def _redigido(valor, exatos: dict[int, str] | None = None,
              _caminho: frozenset[int] = frozenset(), _nivel: int = 0):
    """Cópia de ``valor`` com todo texto redigido SEM dono (falha fechada), chaves de
    dict inclusive. O original fica intacto: o ``extra`` do log pode ser um objeto que
    o app ainda usa. ``exatos``: id de um dict → o texto já redigido pelo dono para a
    chave "value" (o valor de uma exceção no Sentry). Ciclo ou aninhamento fundo
    demais vira um marcador, em vez de estourar a pilha na chamada de log."""
    if isinstance(valor, str):
        return redigir_detalhe_do_banco(valor)
    if not isinstance(valor, (dict, list, tuple)):
        return valor
    if id(valor) in _caminho or _nivel >= _PROFUNDIDADE_MAX:
        return _OMITIDO
    caminho, nivel = _caminho | {id(valor)}, _nivel + 1
    if isinstance(valor, dict):
        exato = (exatos or {}).get(id(valor))
        return {(_redigido(k) if isinstance(k, str) else k):
                (exato if exato is not None and k == "value"
                 else _redigido(item, exatos, caminho, nivel))
                for k, item in valor.items()}
    if valor and all(isinstance(item, str) for item in valor):
        junto = "".join(valor)
        if _inicios_de_detalhe(junto) and not all(_inicios_de_detalhe(item) for item in valor):
            # Os pedaços, juntos, formam um valor do banco (ex.: o DETAIL partido letra
            # por letra): redige o texto inteiro, num item só.
            itens = [redigir_detalhe_do_banco(junto)]
            return itens if isinstance(valor, list) else tuple(itens)
    itens = [_redigido(item, exatos, caminho, nivel) for item in valor]
    return itens if isinstance(valor, list) else tuple(itens)


def _usuario_id_do_token(headers: dict[bytes, bytes]) -> int | None:
    """Best-effort: extrai o `sub` do JWT só para RASTREAR (sem virar autorização)."""
    bruto = headers.get(b"authorization", b"").decode("latin-1")
    if not bruto.lower().startswith("bearer "):
        return None
    from app.core.security import decodificar_token
    payload = decodificar_token(bruto[7:])
    if not payload or payload.get("papel"):
        return None
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None


def _rota_de(scope: dict) -> str:
    """Template da rota para as MÉTRICAS (baixa cardinalidade): usa a rota
    casada do Starlette. SEM rota casada (404/caminho inexistente), devolve um
    rótulo FIXO "<no_match>" — nunca o caminho bruto. Usar o path cru como label
    permitiria a um anônimo criar séries temporais infinitas (GET /aaa, /bbb…),
    estourando a memória do prometheus_client (DoS por cardinalidade)."""
    rota = scope.get("route")
    caminho = getattr(rota, "path", None)
    return caminho if caminho else "<no_match>"


# Rotas de infra não geram log de acesso (evita ruído nos scrapes/probes).
_SEM_LOG = ("/api/health", "/metrics")

logger = logging.getLogger("constela.http")


class ObservabilidadeMiddleware:
    """ASGI puro: contexto + request/correlation id + latência + métricas +
    log de acesso + rede de segurança de 500. Como NÃO é BaseHTTPMiddleware, o
    contexto propaga até o handler (inclusive endpoints síncronos no threadpool)."""

    def __init__(self, app, settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        request_id = uuid.uuid4().hex
        correlation_id = (headers.get(b"x-correlation-id", b"").decode("latin-1")
                          or request_id)
        caminho = scope.get("path", "")
        escola_id = _escola_id_do_caminho(caminho)
        usuario_id = _usuario_id_do_token(headers)

        ctx_request_id.set(request_id)
        ctx_correlation_id.set(correlation_id)
        if escola_id is not None:
            ctx_escola_id.set(escola_id)
        if usuario_id is not None:
            ctx_usuario_id.set(usuario_id)
        _marcar_sentry(request_id, correlation_id, usuario_id, escola_id)

        metodo = scope.get("method", "?")
        inicio = time.perf_counter()
        estado = {"status": 500, "iniciou": False}
        if _M_ANDAMENTO is not None:
            _M_ANDAMENTO.labels(metodo).inc()

        async def enviar(evento):
            if evento["type"] == "http.response.start":
                estado["status"] = evento["status"]
                estado["iniciou"] = True
                cabecalhos = list(evento.get("headers") or [])
                cabecalhos.append((b"x-request-id", request_id.encode()))
                cabecalhos.append((b"x-correlation-id", correlation_id.encode()))
                evento = {**evento, "headers": cabecalhos}
            await send(evento)

        try:
            await self.app(scope, receive, enviar)
        except Exception as erro:  # noqa: BLE001 — rede de segurança de último recurso
            estado["status"] = 500
            logger.exception("erro_nao_tratado", extra={
                "metodo": metodo, "caminho": redigir_caminho(caminho)})
            capturar_excecao(erro)
            if not estado["iniciou"]:
                await self._responder_500(enviar)
            else:  # resposta já começou: não dá para trocar — só registra
                raise
        finally:
            duracao = time.perf_counter() - inicio
            rota = _rota_de(scope)
            ctx_rota.set(rota)
            if _M_ANDAMENTO is not None:
                _M_ANDAMENTO.labels(metodo).dec()
            self._registrar(metodo, rota, caminho, estado["status"], duracao)

    def _registrar(self, metodo, rota, caminho, status, duracao) -> None:
        if _M_REQS is not None:
            _M_REQS.labels(metodo, rota, str(status)).inc()
            _M_DUR.labels(metodo, rota).observe(duracao)
        if any(caminho.startswith(p) for p in _SEM_LOG):
            return
        nivel = logging.ERROR if status >= 500 else (
            logging.WARNING if status >= 400 else logging.INFO)
        logger.log(nivel, "http_acesso", extra={
            "metodo": metodo, "rota": rota, "status": status,
            "dur_ms": round(duracao * 1000, 1)})

    async def _responder_500(self, enviar) -> None:
        corpo = json.dumps(
            {"detail": "Erro interno. Tente novamente em instantes."}).encode()
        await enviar({"type": "http.response.start", "status": 500,
                      "headers": [(b"content-type", b"application/json")]})
        await enviar({"type": "http.response.body", "body": corpo})
