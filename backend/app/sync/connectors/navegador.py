"""Abstração de navegador para conectores que dependem de automação (Playwright).

Por que uma abstração e não Playwright direto nos conectores:
  * TESTABILIDADE — os testes injetam um ``NavegadorFake`` e exercitam TODO o
    fluxo do conector (login → localizar → baixar) sem browser real nem contas.
  * TROCABILIDADE — quando uma plataforma liberar API oficial, o conector migra
    de ``Estrategia.NAVEGADOR`` para ``API_OFICIAL`` sem que orquestrador/
    scheduler/painel percebam.
  * ISOLAMENTO DE DEPENDÊNCIA — o Playwright é import TARDIO: o app sobe e os
    testes rodam sem o pacote instalado; só ``abrir()`` real o exige.

Regra: nenhum método loga a senha. O conector passa o valor a ``preencher`` e
pronto — o valor nunca vai para ``SincronizacaoLog``. O erro do Playwright ao
preencher traz o valor no "Call log" (``fill("…")``): ``preencher`` o relança
sem ele (``erro_sem_o_valor``).
"""
from __future__ import annotations

import errno
import logging
import re
import socket
import ssl
from collections.abc import Awaitable, Callable, Iterator
from typing import Protocol, runtime_checkable

from app.core.observabilidade import redigir_valor_digitado
from app.sync.interfaces import ErroConector

logger = logging.getLogger("constela.sync")

# O NOSSO navegador não abriu (Chromium ausente, sandbox, falta de memória): a
# plataforma nem foi procurada. Sem detalhe interno — ele vai para o log ERROR.
NAVEGADOR_NAO_ABRIU = (
    "O navegador do robô não abriu neste servidor, então a plataforma nem chegou a ser "
    "consultada. O problema é do Constela, não da plataforma: avise o suporte.")
# O NOSSO navegador caiu NO MEIO da consulta (Chromium que fechou ou travou, falta de
# memória no container, driver do Playwright que morreu): também é do servidor.
NAVEGADOR_CAIU = (
    "O navegador do robô caiu no meio da consulta, antes de a plataforma terminar de "
    "responder. O problema é do Constela, não da plataforma: tente de novo em alguns "
    "minutos e, se repetir, avise o suporte.")


@runtime_checkable
class Navegador(Protocol):
    """Superfície mínima de navegador usada pelos conectores."""

    async def ir_para(self, url: str) -> None: ...
    async def preencher(self, seletor: str, valor: str) -> None: ...
    async def clicar(self, seletor: str) -> None: ...
    async def esperar(self, seletor: str, timeout_s: int = 20) -> bool: ...
    async def visivel(self, seletor: str) -> bool: ...
    async def texto(self, seletor: str) -> str: ...
    async def url_atual(self) -> str: ...
    # Avalia uma expressão JS na página e devolve o resultado (JSON-serializável).
    # É como lemos ESTRUTURA (ids de turma/aluno, links) de forma robusta — sem
    # depender de clicar em componentes de UI frágeis.
    async def avaliar(self, expressao: str): ...
    # Navega e captura os corpos JSON das respostas XHR/fetch — revela a API
    # interna do SPA (ex.: lista de turmas/alunos do Elefante Angular) quando os
    # ids não estão no HTML. Devolve [{"url", "json", "method", "status",
    # "req_auth"}] — o Authorization da requisição permite reusar a mesma sessão
    # para chamar a API interna direto (in-page fetch).
    async def coletar_respostas(self, url: str, timeout_s: int = 25) -> list: ...
    # Como coletar_respostas, mas em torno de uma AÇÃO (ex.: clicar "Pesquisar")
    # em vez de navegar — captura os XHR/fetch que a ação dispara (o SPA só
    # renderiza o relatório do aluno DEPOIS de submeter a busca).
    async def coletar_apos_acao(self, acao, timeout_s: int = 20) -> list: ...
    async def baixar(self, seletor: str,
                     timeout_s: int = 60) -> tuple[bytes, str]: ...
    async def baixar_acao(self, acao,
                          timeout_s: int = 60) -> tuple[bytes, str]: ...
    # Estado da sessão (cookies + localStorage) para REUSO: guardado cifrado e
    # reinjetado numa próxima consulta ao vivo, evitando um novo login por clique.
    async def estado_sessao(self) -> dict: ...
    async def fechar(self) -> None: ...


# Fábrica de navegador: () -> Navegador (async). Injetável para teste.
FabricaNavegador = Callable[..., Awaitable[Navegador]]


def erro_sem_o_valor(erro: BaseException, valor: str) -> BaseException:
    """O erro de um preenchimento sem o ``valor`` digitado no texto. O Playwright o
    escreve no "Call log" do erro (``fill("…")``) e, na prévia do campo, o ``value``
    que a página pôs nele; o texto ia assim para o log, para o Sentry e para quem mais
    lesse a exceção. Volta o MESMO tipo (quem chama trata igual), com o texto sem o
    valor e a pilha de onde o erro nasceu; sem o valor no texto, o próprio ``erro``."""
    texto = str(erro)
    limpo = redigir_valor_digitado(texto, valor)
    if limpo == texto:
        return erro
    try:
        novo = type(erro)(limpo)
    except Exception:  # noqa: BLE001 — um tipo que não se cria só com a mensagem
        novo = None
    if novo is None or str(novo) != limpo:
        novo = RuntimeError(limpo)
    for atributo in ("_name", "_stack"):     # os do Error do Playwright (rewrite_error)
        if hasattr(erro, atributo) and hasattr(novo, atributo):
            setattr(novo, atributo, getattr(erro, atributo))
    # A pilha começa no frame que capturou o erro (o de ``preencher``), que o raise
    # dele acrescenta de novo: sem ele, cada frame aparece uma vez só.
    tb = erro.__traceback__
    return novo.with_traceback(tb.tb_next if tb is not None else None)


def _proxy_playwright() -> dict | None:
    """Traduz ``settings.SYNC_PROXY_URL`` (ex.: http://user:pass@host:porta)
    para o formato ``proxy=`` do Playwright ({server, username, password}).
    Devolve None se não houver proxy configurado. O proxy sobe o score do
    reCAPTCHA v3 (login recusado a partir de IP de datacenter)."""
    from urllib.parse import urlsplit

    from app.core.config import settings
    url = (settings.SYNC_PROXY_URL or "").strip()
    if not url:
        return None
    p = urlsplit(url)
    if not p.hostname:
        return None
    porta = f":{p.port}" if p.port else ""
    cfg: dict = {"server": f"{p.scheme or 'http'}://{p.hostname}{porta}"}
    if p.username:
        cfg["username"] = p.username
    if p.password:
        cfg["password"] = p.password
    return cfg


async def abrir_playwright(*, headless: bool = True,
                           timeout_s: int = 30,
                           storage_state: dict | None = None) -> Navegador:
    """Fábrica REAL — import tardio do Playwright. Só chamada em produção com
    credenciais reais. Levanta ``ErroConector`` (``navegador_indisponivel``) claro se
    o pacote não estiver instalado (o app não depende dele para subir) ou se o
    navegador não abrir neste servidor — a culpa não vai para a plataforma.

    ``storage_state`` (opcional) reidrata cookies/localStorage de uma sessão
    anterior — a consulta ao vivo do Matific reusa a sessão e pula o login."""
    try:
        from playwright.async_api import async_playwright  # import tardio
    except ImportError as exc:  # pragma: no cover — exige o pacote instalado
        raise ErroConector(
            "Playwright não está instalado neste ambiente. Instale "
            "`playwright` e rode `playwright install chromium` para habilitar "
            "a obtenção automática.", codigo="navegador_indisponivel",
            recuperavel=False) from exc

    # Subir o NOSSO navegador (driver do Playwright + Chromium + contexto + aba) é do
    # servidor, não da plataforma: uma falha aqui (executável ausente, sandbox, falta
    # de memória) vira ``navegador_indisponivel`` (503), não "a plataforma não
    # respondeu" (502). O que já subiu é fechado no caminho de erro; o detalhe vai
    # para o log ERROR e a mensagem não leva nada interno. ``recuperavel=True``: falta
    # de memória ou /dev/shm cheio passam, e a próxima tentativa pode abrir (o pacote
    # ausente, acima, é que não volta sozinho).
    pw = navegador = None
    try:
        pw = await async_playwright().start()
        proxy = _proxy_playwright()
        navegador = await pw.chromium.launch(
            headless=headless,
            # Roteia o robô por um IP residencial/móvel reputável quando configurado
            # (SYNC_PROXY_URL) — necessário para passar o reCAPTCHA v3 do Matific a
            # partir de datacenter. Sem proxy, sai direto (comportamento atual).
            proxy=proxy,
            # Flags que reduzem a chance de bloqueio anti-robô em SPAs.
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        # Contexto REALISTA: locale/fuso/idioma do Brasil e um user-agent de Chrome
        # comum. Sem isto, as plataformas (rodando a partir de um IP de datacenter
        # nos EUA) redirecionam para a versão gringa e/ou barram a automação.
        ctx_kwargs: dict = dict(
            accept_downloads=True,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
            viewport={"width": 1366, "height": 768},
            extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
        # Sessão reaproveitada (cookies de um login anterior) → pula o formulário.
        if storage_state is not None:
            ctx_kwargs["storage_state"] = storage_state
        contexto = await navegador.new_context(**ctx_kwargs)
        # Esconde o marcador navigator.webdriver (sinal clássico de automação).
        await contexto.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        pagina = await contexto.new_page()
        pagina.set_default_timeout(timeout_s * 1000)
    except Exception as exc:  # noqa: BLE001 — qualquer falha ao subir o navegador
        logger.error("O navegador do robô não abriu neste servidor (%s).",
                     type(exc).__name__, exc_info=True)
        await _fechar_o_que_abriu(navegador, pw)
        # ``from None``: o erro original (caminhos, argumentos do Chromium) já está no
        # log e não fica pendurado na exceção que a rota e a sincronização exibem.
        raise ErroConector(NAVEGADOR_NAO_ABRIU, codigo="navegador_indisponivel",
                           recuperavel=True) from None
    return _NavegadorPlaywright(pw, navegador, pagina)


async def _fechar_o_que_abriu(navegador, pw) -> None:
    """Fecha o Chromium e para o driver do Playwright que chegaram a subir antes da
    falha (sem isso, cada tentativa deixava um processo vivo). Best-effort: uma falha
    aqui não esconde a falha original."""
    for aberto, fechar in ((navegador, "close"), (pw, "stop")):
        if aberto is None:
            continue
        try:
            await getattr(aberto, fechar)()
        except Exception:  # noqa: BLE001 — fechamento best-effort
            logger.debug("Fechamento do navegador que não abriu falhou.", exc_info=True)


# --- De quem é a falha que interrompeu uma coleta ------------------------------
# Usado pelo diagnóstico do Elefante (``diagnostico_elefante._erro_da_coleta``) e
# pelo placar ao vivo do Matific (``aovivo._erro_da_consulta``), para os dois
# responderem igual.

FALHA_TEMPO = "timeout"           # tempo esgotado esperando a plataforma → 504
FALHA_PLATAFORMA = "plataforma"   # rede no caminho até ela (DNS, conexão, TLS) → 502
# O NOSSO navegador caiu no meio → 503. É a classe de CADA exceção; no resultado de
# ``classificar_falha_da_coleta`` conta como conhecida (ver a docstring dela).
FALHA_NAVEGADOR = "navegador"
FALHA_CONHECIDA = "conhecida"     # um ErroConector (o conector já disse o que houve)
FALHA_NOSSA = "nossa"             # defeito do Constela → log ERROR e 500

# Exceções destes pacotes são da rede ou do navegador no caminho até a plataforma.
_PACOTES_DA_REDE = ("playwright", "httpx", "httpcore")
# As MARCAS DE TEXTO abaixo são procuradas só na PRIMEIRA linha da mensagem: o resto
# é o "Call log" do Playwright, que traz o HTML dos elementos da página da PLATAFORMA
# (um botão com o texto "Page crashed" não derruba o nosso navegador nem transforma o
# tempo esgotado do clique em outra coisa). E só valem para quem pode trazer o texto
# do Playwright: o erro do pacote dele, o ``Exception`` embutido (o driver que morreu)
# e o ``RuntimeError`` (o erro do Playwright que passou por ``erro_sem_o_valor``) — um
# ``KeyError('page crashed')`` é defeito nosso.
# A marca de erro de rede do Chromium (net::ERR_NAME_NOT_RESOLVED…) no texto: o erro
# do Playwright pode chegar com outro tipo (``erro_sem_o_valor`` cai em RuntimeError
# quando o tipo não se recria só com a mensagem).
_MARCA_DE_REDE_DO_CHROMIUM = "net::ERR_"
# O NOSSO navegador caiu no meio da coleta: o Chromium que travou ou caiu ("Target
# crashed", "Page crashed"), o fechado por baixo da coleta ("Browser has been closed";
# o ``TargetClosedError`` diz "Target page, context or browser has been closed") e o
# driver do Playwright que morreu (um ``Exception`` embutido). Pelo texto, e não só
# pelo tipo, pelo mesmo motivo da marca de rede: o tipo pode ter virado RuntimeError.
_MARCAS_DO_NAVEGADOR_QUE_CAIU = (
    "target crashed", "page crashed", "browser has been closed",
    "connection closed while reading from the driver")
# Defeito NOSSO no que mandamos ao navegador: o JS que pedimos para avaliar não roda
# (ReferenceError/SyntaxError/TypeError na página) ou o seletor é inválido. O
# Playwright os levanta com o tipo dele, que pela regra do pacote culparia a plataforma.
_JS_NOSSO_QUEBRADO = re.compile(
    r"^(Page|Frame|Locator|ElementHandle)\.(evaluate|eval_on_selector\w*): "
    r"(ReferenceError|SyntaxError|TypeError)")
_SELETOR_NOSSO_INVALIDO = "while parsing selector"
# ...menos o ``TypeError: Failed to fetch``, que é o erro de REDE do fetch() feito
# dentro da página (o conector lê a API interna assim): esse é da plataforma.
_FETCH_SEM_REDE = "Failed to fetch"
# OSError da REDE até a plataforma (o ``TimeoutError`` já sai antes, como tempo). As
# outras subclasses — arquivo, permissão, processo (``FileNotFoundError``,
# ``PermissionError``, ``IsADirectoryError``, ``NotADirectoryError``…) — são do NOSSO
# servidor: o arquivo baixado que não abre não é culpa da plataforma.
_OSERROR_DA_REDE = (ConnectionError, socket.gaierror, socket.herror, ssl.SSLError,
                    TimeoutError)
# O OSError genérico (sem subclasse própria) só é da rede com estes errno — rede ou
# máquina inalcançável ou fora do ar, conexão recusada, derrubada ou abortada (também
# a que a rede derrubou ao se reiniciar, ENETRESET), tempo esgotado na conexão — ou
# sem errno (o "Multiple exceptions" do asyncio ao tentar cada endereço). LISTA
# BRANCA: qualquer outro errno (ENOMEM, EIO, EBADF, ENOSPC, EMFILE…) é do NOSSO
# servidor, e o errno que ninguém previu não culpa a plataforma.
_ERRNO_DA_REDE = frozenset({
    errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN, errno.EHOSTDOWN,
    errno.ECONNREFUSED, errno.ECONNRESET, errno.ECONNABORTED, errno.ENETRESET,
    errno.ETIMEDOUT})


def _folhas(exc: BaseException) -> Iterator[BaseException]:
    """As exceções de dentro de um grupo (``ExceptionGroup``, de um ``TaskGroup``),
    também de grupos aninhados; fora de grupo, a própria exceção."""
    if isinstance(exc, BaseExceptionGroup):
        for dentro in exc.exceptions:
            yield from _folhas(dentro)
    else:
        yield exc


def _do_pacote(exc: BaseException, pacotes: tuple[str, ...]) -> bool:
    modulo = type(exc).__module__ or ""
    return any(modulo == p or modulo.startswith(p + ".") for p in pacotes)


def _do_pacote_da_rede(exc: BaseException) -> bool:
    return _do_pacote(exc, _PACOTES_DA_REDE)


def _marca_de_texto_vale(exc: BaseException) -> bool:
    """Se a exceção pode trazer o texto do Playwright (ver as marcas de texto acima):
    a do pacote dele, o ``Exception`` embutido do driver que morreu ou o
    ``RuntimeError`` que sai de ``erro_sem_o_valor`` — o tipo exato, não as subclasses
    (``NotImplementedError``, ``RecursionError``… são nossas)."""
    return _do_pacote(exc, ("playwright",)) or type(exc) in (Exception, RuntimeError)


def _texto(exc: BaseException) -> str:
    """O texto da exceção para as marcas; vazio fora de ``Exception`` (o
    ``CancelledError``) ou se o próprio ``str`` falhar — classificar não pode levantar
    no meio do tratamento da falha original."""
    if not isinstance(exc, Exception):
        return ""
    try:
        return str(exc)
    except Exception:  # noqa: BLE001 — um __str__ quebrado não esconde a falha
        return ""


def _navegador_caiu(exc: BaseException, cabeca: str) -> bool:
    if type(exc).__name__ == "TargetClosedError" and _do_pacote(exc, ("playwright",)):
        return True
    baixo = cabeca.lower()
    return any(marca in baixo for marca in _MARCAS_DO_NAVEGADOR_QUE_CAIU)


def _pedido_nosso_invalido(cabeca: str) -> bool:
    if _SELETOR_NOSSO_INVALIDO in cabeca:
        return True
    return bool(_JS_NOSSO_QUEBRADO.match(cabeca)) and _FETCH_SEM_REDE not in cabeca


def _tempo_esgotado(exc: BaseException) -> bool:
    """O ``TimeoutError`` embutido (o do asyncio no 3.11+, ``socket.timeout``) ou, pelo
    nome, o de um pacote da rede: o ``TimeoutError`` do Playwright (não herda do
    embutido) e os do httpx/httpcore (``ConnectTimeout``, ``ReadTimeout``…). Pelo nome
    SÓ nesses pacotes: o ``sqlalchemy.exc.TimeoutError`` (pool do banco esgotado) é nosso."""
    if isinstance(exc, TimeoutError):
        return True
    return _do_pacote_da_rede(exc) and type(exc).__name__.endswith(("TimeoutError",
                                                                     "Timeout"))


def _oserror_da_rede(exc: BaseException) -> bool:
    if isinstance(exc, _OSERROR_DA_REDE):
        return True
    # O OSError genérico, sem subclasse própria, é o da rede que não ganhou tipo (rede
    # ou máquina inalcançável, o "Multiple exceptions" do asyncio) SÓ com errno da
    # lista branca ou sem errno; com qualquer outro, é do nosso servidor.
    return type(exc) is OSError and (exc.errno is None or exc.errno in _ERRNO_DA_REDE)


def _classificar_uma(exc: BaseException) -> str:
    if isinstance(exc, ErroConector):
        return FALHA_CONHECIDA
    # As marcas de texto: só a primeira linha (antes do "Call log", que traz a página
    # da plataforma) e só de quem pode trazer o texto do Playwright; de outro tipo,
    # nenhuma marca vale.
    cabeca = _texto(exc).split("\n", 1)[0] if _marca_de_texto_vale(exc) else ""
    # ANTES da regra por pacote: o Playwright levanta com o tipo dele tanto a queda do
    # NOSSO navegador quanto o defeito no que NÓS mandamos — nenhum é da plataforma.
    if _navegador_caiu(exc, cabeca):
        return FALHA_NAVEGADOR
    if _pedido_nosso_invalido(cabeca):
        return FALHA_NOSSA
    if _tempo_esgotado(exc):
        return FALHA_TEMPO
    if _oserror_da_rede(exc) or _do_pacote_da_rede(exc):
        return FALHA_PLATAFORMA
    if _MARCA_DE_REDE_DO_CHROMIUM in cabeca:
        return FALHA_PLATAFORMA
    # O resto (KeyError, TypeError, AttributeError, FileNotFoundError…) é defeito
    # nosso. Também o ``asyncio.CancelledError`` que sai de DENTRO do conector: o teto
    # da coleta já vira ``TimeoutError`` e ninguém de fora cancelou.
    return FALHA_NOSSA


def classificar_falha_da_coleta(exc: BaseException) -> str:
    """De quem é a falha que interrompeu uma coleta (login + leitura no site da
    plataforma). Só a rede põe a culpa na plataforma:

    * ``FALHA_TEMPO``: o ``TimeoutError`` embutido (o do asyncio, no 3.11+) ou o de um
      pacote da rede pelo nome (o ``TimeoutError`` do Playwright, o ``ReadTimeout`` do
      httpx…) — o ``TimeoutError`` do SQLAlchemy é nosso;
    * ``FALHA_PLATAFORMA``: o ``OSError`` da rede (``ConnectionError``, DNS, TLS, o
      genérico com errno de rede — lista branca — ou sem errno), as exceções dos
      pacotes Playwright, httpx e httpcore e a marca de rede do Chromium;
    * ``FALHA_CONHECIDA``: um ``ErroConector`` (o conector já sabe dizer o que houve) —
      e também o NOSSO navegador que caiu no meio (``FALHA_NAVEGADOR``, por exceção:
      ``TargetClosedError``, "Target crashed", "Page crashed", "Browser has been
      closed", o driver morto), para o qual ``erro_conector_de_dentro`` devolve o
      ``navegador_indisponivel`` (503) — quem chama não precisa de um ramo próprio;
    * ``FALHA_NOSSA``: todo o resto — um defeito do Constela no meio da coleta tem de
      chegar ao Sentry como erro e responder 500, e não "a plataforma não respondeu".
      Inclui o defeito no que NÓS mandamos ao navegador (o JS avaliado que lança
      ReferenceError/SyntaxError/TypeError, o seletor inválido) e o ``OSError`` do
      nosso servidor (arquivo, permissão, memória, disco: qualquer errno fora da
      lista da rede).

    As marcas de texto (navegador caído, JS e seletor nossos, ``net::ERR_``) valem só
    na primeira linha da mensagem — o "Call log" do Playwright, depois dela, traz a
    página da plataforma — e só para o erro do Playwright, o ``Exception`` do driver
    morto e o ``RuntimeError`` de ``erro_sem_o_valor``.

    Grupo de exceções: olha cada uma (``exc.exceptions``, também aninhadas). Basta
    UMA nossa para o grupo ser nosso; só tempo esgotado é tempo; com um
    ``ErroConector`` dentro (e nada nosso), é ele que vale; sem ele, com o navegador
    caído, vale a queda do navegador (ela explica a rede e o tempo que falharam junto)."""
    tipos = {_classificar_uma(e) for e in _folhas(exc)}
    if FALHA_NOSSA in tipos or not tipos:
        return FALHA_NOSSA
    if tipos == {FALHA_TEMPO}:
        return FALHA_TEMPO
    if FALHA_CONHECIDA in tipos or FALHA_NAVEGADOR in tipos:
        return FALHA_CONHECIDA
    return FALHA_PLATAFORMA


def erro_conector_de_dentro(exc: BaseException) -> ErroConector | None:
    """O ``ErroConector`` que veio na falha: ela mesma ou o primeiro de dentro do grupo.

    Sem nenhum, e com o NOSSO navegador caído no meio da coleta (``FALHA_NAVEGADOR``),
    um ``navegador_indisponivel`` (503, ``NAVEGADOR_CAIU``, sem detalhe interno) — o
    detalhe vai para o log ERROR, porque a falha é do servidor e o Sentry tem de vê-la.
    Sem nenhum dos dois, None."""
    folhas = list(_folhas(exc))
    conhecido = next((e for e in folhas if isinstance(e, ErroConector)), None)
    if conhecido is not None:
        return conhecido
    caiu = next((e for e in folhas if _classificar_uma(e) == FALHA_NAVEGADOR), None)
    if caiu is None:
        return None
    logger.error("O navegador do robô caiu no meio da coleta (%s).", type(caiu).__name__,
                 exc_info=exc)
    # Recuperável: falta de memória passa, e a próxima tentativa pode ir até o fim.
    return ErroConector(NAVEGADOR_CAIU, codigo="navegador_indisponivel", recuperavel=True)


class _NavegadorPlaywright:  # pragma: no cover — exercitado só com browser real
    """Adaptador do Playwright para a interface ``Navegador``. Mantido fino de
    propósito: se um seletor mudar, ajusta-se no CONECTOR, não aqui."""

    def __init__(self, pw, navegador, pagina):
        self._pw, self._navegador, self._pagina = pw, navegador, pagina

    async def ir_para(self, url: str) -> None:
        await self._pagina.goto(url, wait_until="domcontentloaded")

    @staticmethod
    def _vis(seletor: str) -> str:
        """Filtra CADA alternativa por ``:visible``. Assim a automação ignora
        campos ESCONDIDOS que casam o mesmo seletor (ex.: o Elefante tem um
        ``input[name='Username']`` type=hidden ANTES do visível — o ``.first``
        pegaria o errado). Também evita o modo estrito do Playwright: seletores
        com alternativas (vírgula) resolvem para o primeiro elemento VISÍVEL."""
        partes = [p.strip() + ":visible" for p in seletor.split(",") if p.strip()]
        return ", ".join(partes) or seletor

    def _loc(self, seletor: str):
        return self._pagina.locator(self._vis(seletor)).first

    async def preencher(self, seletor: str, valor: str) -> None:
        # O erro sai sem o valor (erro_sem_o_valor), levantado FORA do except: o
        # original, com o valor, não fica pendurado nele como __context__.
        sem_o_valor = None
        try:
            await self._loc(seletor).fill(valor)
        except Exception as exc:  # noqa: BLE001
            sem_o_valor = erro_sem_o_valor(exc, valor)
            if sem_o_valor is exc:
                raise
        if sem_o_valor is not None:
            raise sem_o_valor

    async def clicar(self, seletor: str) -> None:
        await self._loc(seletor).click()

    async def esperar(self, seletor: str, timeout_s: int = 20) -> bool:
        try:
            await self._loc(seletor).wait_for(state="visible", timeout=timeout_s * 1000)
            return True
        except Exception:  # noqa: BLE001 — ausência do seletor visível = False
            return False

    async def visivel(self, seletor: str) -> bool:
        try:
            return await self._loc(seletor).is_visible()
        except Exception:  # noqa: BLE001
            return False

    async def texto(self, seletor: str) -> str:
        return (await self._pagina.text_content(seletor)) or ""

    async def url_atual(self) -> str:
        return self._pagina.url

    async def avaliar(self, expressao: str):
        return await self._pagina.evaluate(expressao)

    async def _capturar(self, acao, timeout_s: int) -> list:
        """Executa ``acao`` (navegar OU clicar) com um listener de respostas ligado
        e devolve os corpos JSON das XHR/fetch capturadas. Além do corpo: método,
        status e o Authorization DA REQUISIÇÃO — o conector reusa esse token para
        CHAMAR a API interna direto (in-page fetch) sem clicar em componentes
        Angular frágeis."""
        capturadas = []

        def _on(resp):
            try:
                if resp.request.resource_type in ("xhr", "fetch"):
                    capturadas.append(resp)
            except Exception:  # noqa: BLE001
                pass

        self._pagina.on("response", _on)
        try:
            await acao()
            try:  # espera a rede assentar p/ pegar os XHR pós-ação do SPA
                await self._pagina.wait_for_load_state(
                    "networkidle", timeout=timeout_s * 1000)
            except Exception:  # noqa: BLE001 — segue com o que já capturou
                pass
        finally:
            self._pagina.remove_listener("response", _on)
        saida = []
        for r in capturadas:
            try:
                if "json" in (r.headers or {}).get("content-type", ""):
                    req = r.request
                    saida.append({
                        "url": r.url, "json": await r.json(),
                        "method": getattr(req, "method", "GET"),
                        "status": getattr(r, "status", None),
                        "req_auth": (req.headers or {}).get("authorization", "")})
            except Exception:  # noqa: BLE001
                pass
        return saida

    async def coletar_respostas(self, url: str, timeout_s: int = 25) -> list:
        return await self._capturar(
            lambda: self._pagina.goto(url, wait_until="domcontentloaded",
                                      timeout=timeout_s * 1000),
            timeout_s)

    async def coletar_apos_acao(self, acao, timeout_s: int = 20) -> list:
        return await self._capturar(acao, timeout_s)

    async def baixar(self, seletor: str, timeout_s: int = 60) -> tuple[bytes, str]:
        return await self.baixar_acao(
            lambda: self._loc(seletor).click(), timeout_s=timeout_s)

    async def baixar_acao(self, acao, timeout_s: int = 60) -> tuple[bytes, str]:
        """Captura o download disparado por uma AÇÃO qualquer (ex.: clicar em
        Exportar, que pode abrir um modal e só então baixar). ``acao`` é um
        callable async que executa o gesto; devolvemos (bytes, nome_sugerido)."""
        async with self._pagina.expect_download(timeout=timeout_s * 1000) as info:
            await acao()
        download = await info.value
        caminho = await download.path()
        with open(caminho, "rb") as fh:
            return fh.read(), (download.suggested_filename or "relatorio")

    async def estado_sessao(self) -> dict:
        """Cookies + localStorage atuais (formato ``storage_state`` do Playwright)
        para persistir cifrado e reusar numa próxima consulta ao vivo."""
        return await self._pagina.context.storage_state()

    async def fechar(self) -> None:
        try:
            await self._navegador.close()
        finally:
            await self._pw.stop()
