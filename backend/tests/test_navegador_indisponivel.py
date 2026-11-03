"""O NOSSO navegador que não abre não pode pôr a culpa na plataforma.

Antes: ``abrir_playwright`` só tratava o pacote ausente (``ImportError``). Se o driver
do Playwright não subia ou o Chromium não abria (executável ausente, sandbox, falta de
memória), o erro do Playwright saía cru de dentro da coleta: o diagnóstico do Elefante
e o placar ao vivo do Matific respondiam 502 "a conexão com o site … falhou ou ele não
respondeu" — culpa da plataforma por um problema da nossa infraestrutura —, e o
driver que já tinha subido ficava vivo. Agora a falha ao subir o navegador vira
``ErroConector`` ``navegador_indisponivel`` (503, mensagem honesta, sem detalhe
interno), o detalhe vai para o log ERROR de ``constela.sync`` e o que já tinha subido
é fechado. O diagnóstico, o placar ao vivo e a sincronização herdam.

Também aqui: a classificação ÚNICA de quem é a falha no meio de uma coleta
(``classificar_falha_da_coleta``), usada pelo diagnóstico e pelo placar ao vivo.

Resíduos (01/11): o NOSSO navegador que cai NO MEIO da coleta (``TargetClosedError``,
"Target crashed", "Page crashed", "Browser has been closed", o driver do Playwright
morto) saía 502 culpando a plataforma — ou 500, no caso do driver —, e agora é 503
``navegador_indisponivel`` com mensagem honesta; o JS e o seletor que NÓS mandamos ao
navegador, quando quebram, saíam 502 e agora são defeito nosso (500); o
``sqlalchemy.exc.TimeoutError`` saía 504 e o ``FileNotFoundError`` nosso, 502 (agora os
dois são nossos), e os timeouts do httpx saíam 502 (agora 504). A falha ao subir o
Chromium passa a ser recuperável (falta de memória passa).

Resíduos da revisão (01/11): as marcas de texto (navegador caído, seletor, ``net::ERR_``)
eram procuradas no texto INTEIRO, que inclui o "Call log" do Playwright com o HTML da
página da PLATAFORMA — um botão "Page crashed" fazia o tempo esgotado do clique (504)
virar 503 —, e em exceção de qualquer tipo (``KeyError('page crashed')`` virava 503).
Agora só na primeira linha e só para o erro do Playwright, o ``Exception`` do driver
morto e o ``RuntimeError`` de ``erro_sem_o_valor``. E o ``OSError`` genérico só culpa
a plataforma com errno de rede (lista branca) ou sem errno: ENOMEM, EIO, EBADF… saíam
502 culpando o Elefante/Matific e agora são nossos (500).

Sem navegador real nem rede: o ``playwright.async_api`` é trocado por um falso.
"""
from __future__ import annotations

import asyncio
import errno
import logging
import socket
import ssl
import sys
import types

import httpx
import pytest
import sqlalchemy.exc
from sqlalchemy import select

from app.models.sincronizacao import SincronizacaoAlerta
from app.sync import aovivo, connectors, service, vault
from app.sync.connectors import navegador
from app.sync.connectors.elefante import ConectorElefante
from app.sync.connectors.matific import ConectorMatific
from app.sync.interfaces import Credenciais, ErroConector

# O que o Playwright de verdade põe no erro de um Chromium ausente (fictício aqui):
# caminho do servidor e instrução de instalação — nada disso pode chegar à tela.
DETALHE_INTERNO = ("BrowserType.launch: Executable doesn't exist at "
                   "/ms-playwright/chromium-0000/chrome-linux/chrome")


class ErroDoPlaywright(Exception):
    """A forma do ``playwright.async_api.Error`` (o pacote dele)."""
    __module__ = "playwright._impl._errors"


ErroDoPlaywright.__name__ = ErroDoPlaywright.__qualname__ = "Error"


class _Registro:
    def __init__(self):
        self.passos: list[str] = []


class _Pagina:
    def __init__(self, reg):
        self._reg = reg

    def set_default_timeout(self, ms):
        self._reg.passos.append(f"timeout:{ms}")


class _Contexto:
    def __init__(self, reg, falha_aba=None):
        self._reg, self._falha_aba = reg, falha_aba

    async def add_init_script(self, script):
        self._reg.passos.append("init_script")

    async def new_page(self):
        if self._falha_aba is not None:
            raise self._falha_aba
        self._reg.passos.append("new_page")
        return _Pagina(self._reg)


class _Chromium:
    def __init__(self, reg, falha_launch=None, falha_aba=None):
        self._reg, self._falha_launch, self._falha_aba = reg, falha_launch, falha_aba

    async def launch(self, **kw):
        if self._falha_launch is not None:
            raise self._falha_launch
        self._reg.passos.append("launch")
        reg, falha_aba = self._reg, self._falha_aba

        class _Navegador:
            async def new_context(self, **kw):
                reg.passos.append("new_context")
                return _Contexto(reg, falha_aba)

            async def close(self):
                reg.passos.append("browser.close")

        return _Navegador()


def _playwright_falso(monkeypatch, *, falha_start=None, falha_launch=None,
                      falha_aba=None) -> _Registro:
    """Troca o ``playwright.async_api`` (import tardio de ``abrir_playwright``) por um
    falso que falha onde o teste pedir. Devolve o registro dos passos."""
    reg = _Registro()

    class _Pw:
        chromium = _Chromium(reg, falha_launch, falha_aba)

        async def stop(self):
            reg.passos.append("pw.stop")

    class _Gerente:
        async def start(self):
            if falha_start is not None:
                raise falha_start
            reg.passos.append("start")
            return _Pw()

    modulo = types.ModuleType("playwright.async_api")
    modulo.async_playwright = lambda: _Gerente()
    monkeypatch.setitem(sys.modules, "playwright.async_api", modulo)
    return reg


def _logs_do_navegador(caplog):
    return [r for r in caplog.records if r.name == "constela.sync"
            and r.getMessage().startswith("O navegador do robô não abriu")]


def _sem_detalhe_interno(texto: str):
    for cru in ("Executable", "ms-playwright", "chrome-linux", "BrowserType",
                "Erro interno", "Traceback", "Error"):
        assert cru not in texto, cru


# --- abrir_playwright -----------------------------------------------------------

def test_driver_que_nao_sobe_vira_navegador_indisponivel_com_log_error(monkeypatch,
                                                                       caplog):
    caplog.set_level(logging.DEBUG, logger="constela.sync")
    erro = ErroDoPlaywright(DETALHE_INTERNO)
    reg = _playwright_falso(monkeypatch, falha_start=erro)

    with pytest.raises(ErroConector) as exc:
        asyncio.run(navegador.abrir_playwright())
    assert exc.value.codigo == "navegador_indisponivel"
    assert str(exc.value) == navegador.NAVEGADOR_NAO_ABRIU
    assert "Constela" in str(exc.value) and "não da plataforma" in str(exc.value)
    _sem_detalhe_interno(str(exc.value))
    # O erro original não fica pendurado na exceção que a rota e a sync exibem.
    assert exc.value.__cause__ is None and exc.value.__suppress_context__ is True
    # Falta de memória ou /dev/shm cheio passam: a sincronização pode tentar de novo
    # (antes: recuperavel=False, sem nova tentativa).
    assert exc.value.recuperavel is True
    # O detalhe ficou no log ERROR (o Sentry vê), com a exceção original.
    logs = _logs_do_navegador(caplog)
    assert len(logs) == 1 and logs[0].levelno == logging.ERROR
    assert logs[0].exc_info and logs[0].exc_info[1] is erro
    assert reg.passos == []                    # nada subiu, nada a fechar


def test_chromium_que_nao_abre_para_o_driver_que_ja_subiu(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="constela.sync")
    reg = _playwright_falso(monkeypatch, falha_launch=ErroDoPlaywright(DETALHE_INTERNO))

    with pytest.raises(ErroConector) as exc:
        asyncio.run(navegador.abrir_playwright())
    assert exc.value.codigo == "navegador_indisponivel"
    assert reg.passos == ["start", "pw.stop"]  # antes: o driver ficava vivo
    assert len(_logs_do_navegador(caplog)) == 1


def test_aba_que_nao_abre_fecha_o_chromium_e_o_driver(monkeypatch):
    reg = _playwright_falso(monkeypatch, falha_aba=ErroDoPlaywright("Target closed"))
    with pytest.raises(ErroConector) as exc:
        asyncio.run(navegador.abrir_playwright())
    assert exc.value.codigo == "navegador_indisponivel"
    assert reg.passos == ["start", "launch", "new_context", "init_script",
                          "browser.close", "pw.stop"]


def test_navegador_que_abre_segue_igual(monkeypatch):
    reg = _playwright_falso(monkeypatch)
    nav = asyncio.run(navegador.abrir_playwright(timeout_s=7))
    assert isinstance(nav, navegador._NavegadorPlaywright)
    assert reg.passos == ["start", "launch", "new_context", "init_script", "new_page",
                          "timeout:7000"]


def test_chromium_que_nao_abre_e_recuperavel_mas_o_pacote_ausente_nao(monkeypatch):
    """Falha ao SUBIR o Chromium pode passar (memória, /dev/shm): recuperável. O pacote
    do Playwright ausente não volta sozinho: continua não recuperável."""
    _playwright_falso(monkeypatch, falha_launch=ErroDoPlaywright(DETALHE_INTERNO))
    with pytest.raises(ErroConector) as subida:
        asyncio.run(navegador.abrir_playwright())
    assert subida.value.codigo == "navegador_indisponivel"
    assert subida.value.recuperavel is True

    monkeypatch.setitem(sys.modules, "playwright.async_api", None)   # → ImportError
    with pytest.raises(ErroConector) as pacote:
        asyncio.run(navegador.abrir_playwright())
    assert pacote.value.codigo == "navegador_indisponivel"
    assert pacote.value.recuperavel is False


# --- quem usa o navegador herda: diagnóstico, placar ao vivo e sincronização ---------

def test_diagnostico_do_elefante_responde_503_sem_culpar_o_elefante(
        cliente, db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    vault.salvar_credencial(db, eid, "elefante", Credenciais(usuario="u", senha="p"))
    db.commit()
    _playwright_falso(monkeypatch, falha_launch=ErroDoPlaywright(DETALHE_INTERNO))
    con = ConectorElefante()                       # a fábrica REAL (abrir_playwright)
    monkeypatch.setattr(connectors, "obter", lambda p: con if p == "elefante" else None)

    r = cliente.post(f"/api/v1/escolas/{eid}/sync/elefante/diagnostico")
    assert r.status_code == 503, r.text            # antes: 502 "…o Elefante não respondeu"
    assert r.json()["detail"] == navegador.NAVEGADOR_NAO_ABRIU
    assert "Elefante" not in r.json()["detail"]
    _sem_detalhe_interno(r.text)


def test_placar_ao_vivo_do_matific_responde_503_sem_culpar_o_matific(
        cliente, db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    aovivo._cache.clear()
    vault.salvar_credencial(db, eid, "matific", Credenciais(usuario="u", senha="p"))
    db.commit()
    _playwright_falso(monkeypatch, falha_start=ErroDoPlaywright(DETALHE_INTERNO))
    con = ConectorMatific()
    monkeypatch.setattr(connectors, "obter", lambda p: con if p == "matific" else None)

    r = cliente.get(f"/api/v1/escolas/{eid}/sync/matific/placar-ao-vivo",
                    params={"periodo": "semana", "forcar": "true"})
    assert r.status_code == 503, r.text            # antes: 502 "…o Matific não respondeu"
    assert r.json()["detail"] == navegador.NAVEGADOR_NAO_ABRIU
    _sem_detalhe_interno(r.text)


def test_sincronizacao_herda_o_codigo_e_alerta_que_e_o_servidor(db, escola_completa,
                                                                 monkeypatch):
    eid = escola_completa["escola"].id
    vault.salvar_credencial(db, eid, "matific", Credenciais(usuario="u", senha="p"))
    db.commit()
    _playwright_falso(monkeypatch, falha_launch=ErroDoPlaywright(DETALHE_INTERNO))
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorMatific())

    ex = service.enfileirar(db, eid, "matific", origem="manual")
    service.executar(db, ex)
    assert ex.status == "erro"
    alertas = db.execute(select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == eid,
        SincronizacaoAlerta.resolvido.is_(False))).scalars().all()
    # ``navegador_indisponivel`` → "plataforma_indisponivel" crítico (este servidor
    # não consegue coletar), não a falha de download da plataforma.
    assert [(a.tipo, a.severidade) for a in alertas] == [("plataforma_indisponivel",
                                                          "critico")]
    _sem_detalhe_interno(alertas[0].mensagem + (ex.erro_resumo or ""))


# --- o NOSSO navegador que cai NO MEIO da coleta ------------------------------------

def _do_playwright(nome: str, texto: str) -> Exception:
    """Um erro com a forma de um tipo do Playwright (``playwright._impl._errors``)."""
    tipo = type(nome, (ErroDoPlaywright,), {"__module__": "playwright._impl._errors"})
    return tipo(texto)


def _target_closed() -> Exception:
    """O ``TargetClosedError`` do Playwright (o de verdade, quando instalado): aba,
    contexto ou Chromium fechados por baixo da coleta."""
    try:
        from playwright._impl._errors import TargetClosedError
    except ImportError:  # pragma: no cover — sem o pacote: a mesma forma
        return _do_playwright("TargetClosedError",
                              "Target page, context or browser has been closed")
    return TargetClosedError()


# Como o navegador que caiu chega à coleta (textos do Playwright 1.48; o do driver morto
# é um ``Exception`` embutido; o último passou por ``erro_sem_o_valor``).
_NAVEGADOR_QUE_CAIU = [
    _target_closed,
    lambda: _do_playwright("TargetClosedError",
                           "Page.goto: Target page, context or browser has been closed"),
    lambda: ErroDoPlaywright("Page.evaluate: Target crashed"),
    lambda: ErroDoPlaywright("Page.goto: Page crashed"),
    lambda: ErroDoPlaywright("BrowserContext.new_page: Browser has been closed"),
    lambda: Exception("Page.goto: Connection closed while reading from the driver"),
    lambda: RuntimeError("Locator.fill: Target page, context or browser has been closed"),
]


class _NavQueCai:
    """Navegador FAKE que abriu, mas cai na primeira página (o diagnóstico começa
    abrindo a página de login)."""

    def __init__(self, erro: Exception):
        self._erro = erro

    async def ir_para(self, url):
        raise self._erro

    async def fechar(self):
        pass


def _logs_da_queda(caplog):
    return [r for r in caplog.records if r.name == "constela.sync"
            and r.getMessage().startswith("O navegador do robô caiu no meio da coleta")]


@pytest.mark.parametrize("fabrica", _NAVEGADOR_QUE_CAIU)
def test_navegador_que_cai_no_meio_vira_navegador_indisponivel(fabrica, caplog):
    caplog.set_level(logging.WARNING, logger="constela.sync")
    erro = fabrica()
    assert navegador._classificar_uma(erro) == navegador.FALHA_NAVEGADOR
    # Para quem chama é uma falha CONHECIDA: o ErroConector vem de erro_conector_de_dentro.
    assert navegador.classificar_falha_da_coleta(erro) == navegador.FALHA_CONHECIDA
    caiu = navegador.erro_conector_de_dentro(erro)
    assert isinstance(caiu, ErroConector)
    assert caiu.codigo == "navegador_indisponivel" and caiu.recuperavel is True
    assert str(caiu) == navegador.NAVEGADOR_CAIU
    assert "Constela" in str(caiu) and "não da plataforma" in str(caiu)
    _sem_detalhe_interno(str(caiu))
    logs = _logs_da_queda(caplog)
    assert len(logs) == 1 and logs[0].levelno == logging.ERROR     # o Sentry vê
    assert logs[0].exc_info and logs[0].exc_info[1] is erro


def test_navegador_que_cai_em_grupo_vale_sobre_rede_e_tempo_mas_nao_sobre_o_conector():
    queda = _target_closed()
    grupo = ExceptionGroup("coleta", [ConnectionResetError(), TimeoutError(), queda])
    assert navegador.classificar_falha_da_coleta(grupo) == navegador.FALHA_CONHECIDA
    assert navegador.erro_conector_de_dentro(grupo).codigo == "navegador_indisponivel"
    # O ErroConector que o conector levantou continua valendo (ele sabe o que houve).
    captcha = ErroConector("x", codigo="captcha")
    com_conector = ExceptionGroup("coleta", [queda, captcha])
    assert navegador.erro_conector_de_dentro(com_conector) is captcha
    # Basta uma nossa para o grupo ser nosso.
    assert navegador.classificar_falha_da_coleta(
        ExceptionGroup("coleta", [queda, KeyError("x")])) == navegador.FALHA_NOSSA
    # Sem ErroConector nem navegador caído: nada a devolver.
    assert navegador.erro_conector_de_dentro(ConnectionResetError()) is None


@pytest.mark.parametrize("fabrica", [_target_closed, _NAVEGADOR_QUE_CAIU[5]])
def test_diagnostico_com_navegador_que_cai_no_meio_responde_503(
        cliente, db, escola_completa, monkeypatch, caplog, fabrica):
    """Antes: 502 "a conexão com o site do Elefante falhou" (TargetClosedError) e 500
    "Erro interno" (driver morto)."""
    caplog.set_level(logging.WARNING, logger="constela.sync")
    eid = escola_completa["escola"].id
    vault.salvar_credencial(db, eid, "elefante", Credenciais(usuario="u", senha="p"))
    db.commit()
    erro = fabrica()

    async def fab(**_kw):
        return _NavQueCai(erro)

    con = ConectorElefante(fab)
    monkeypatch.setattr(connectors, "obter", lambda p: con if p == "elefante" else None)

    r = cliente.post(f"/api/v1/escolas/{eid}/sync/elefante/diagnostico")
    assert r.status_code == 503, r.text
    assert r.json()["detail"] == navegador.NAVEGADOR_CAIU
    assert "Elefante" not in r.json()["detail"]
    _sem_detalhe_interno(r.text)
    assert "Target" not in r.text and "driver" not in r.text
    assert [x.levelno for x in _logs_da_queda(caplog)] == [logging.ERROR]


def test_placar_ao_vivo_com_navegador_que_cai_no_meio_responde_503(
        cliente, db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    aovivo._cache.clear()
    vault.salvar_credencial(db, eid, "matific", Credenciais(usuario="u", senha="p"))
    db.commit()
    monkeypatch.setattr(connectors, "obter",
                        lambda p: ConectorMatific() if p == "matific" else None)

    def _coleta_que_cai(*_a, **_k):
        raise ErroDoPlaywright("Page.goto: Page crashed")

    monkeypatch.setattr(aovivo, "_coletar_http_first", _coleta_que_cai)
    r = cliente.get(f"/api/v1/escolas/{eid}/sync/matific/placar-ao-vivo",
                    params={"periodo": "semana", "forcar": "true"})
    assert r.status_code == 503, r.text            # antes: 502 "…o Matific não respondeu"
    assert r.json()["detail"] == navegador.NAVEGADOR_CAIU
    assert "Matific" not in r.json()["detail"]
    _sem_detalhe_interno(r.text)


# --- defeito nosso e tempo esgotado pela rota do diagnóstico -------------------------

class _ConectorQueFalha:
    def __init__(self, erro: BaseException):
        self._erro = erro

    async def diagnosticar_endpoints(self, cred, contexto):
        await asyncio.sleep(0)
        raise self._erro


@pytest.mark.parametrize("erro, status", [
    # Defeito no que NÓS mandamos ao navegador (antes: 502 culpando o Elefante).
    (ErroDoPlaywright("Page.evaluate: ReferenceError: ficticio is not defined"), 500),
    (ErroDoPlaywright('Locator.click: Unexpected token "]" while parsing selector "a]"'),
     500),
    # OSError e "TimeoutError" do NOSSO servidor (antes: 502 e 504).
    (FileNotFoundError("arquivo baixado ficticio"), 500),
    (sqlalchemy.exc.TimeoutError("QueuePool limit ficticio"), 500),
    # O tempo esgotado do httpx é tempo (antes: 502).
    (httpx.ReadTimeout("leitura ficticia"), 504),
    # Rede de verdade continua culpando o Elefante.
    (socket.gaierror(11001, "getaddrinfo failed"), 502),
])
def test_rota_do_diagnostico_por_classe_de_falha(cliente, db, escola_completa,
                                                 monkeypatch, erro, status):
    eid = escola_completa["escola"].id
    vault.salvar_credencial(db, eid, "elefante", Credenciais(usuario="u", senha="p"))
    db.commit()
    con = _ConectorQueFalha(erro)
    monkeypatch.setattr(connectors, "obter", lambda p: con if p == "elefante" else None)

    r = cliente.post(f"/api/v1/escolas/{eid}/sync/elefante/diagnostico")
    assert r.status_code == status, r.text
    if status == 500:
        assert "Elefante" not in r.text and "demorou" not in r.text
    if status == 504:
        assert "demorou demais" in r.json()["detail"]
    if status == 502:
        assert r.json()["detail"].startswith("Não foi possível rodar o diagnóstico agora")


# --- de quem é a falha no meio de uma coleta ------------------------------------

def _timeout_do_playwright():
    """A forma do ``TimeoutError`` do Playwright: não herda do embutido."""
    tipo = type("TimeoutError", (ErroDoPlaywright,),
                {"__module__": "playwright._impl._errors"})
    return tipo("Timeout 30000ms exceeded.")


@pytest.mark.parametrize("erro, esperado", [
    (TimeoutError(), navegador.FALHA_TEMPO),
    (_timeout_do_playwright(), navegador.FALHA_TEMPO),
    (OSError("rede"), navegador.FALHA_PLATAFORMA),
    (ConnectionResetError("rede"), navegador.FALHA_PLATAFORMA),
    (httpx.ConnectError("sem rede"), navegador.FALHA_PLATAFORMA),
    (ErroDoPlaywright("Page.goto: net::ERR_CONNECTION_REFUSED"), navegador.FALHA_PLATAFORMA),
    # O erro do Playwright que passou por ``erro_sem_o_valor`` e virou RuntimeError.
    (RuntimeError("net::ERR_NAME_NOT_RESOLVED at https://exemplo.invalid/"),
     navegador.FALHA_PLATAFORMA),
    (ErroConector("x", codigo="captcha"), navegador.FALHA_CONHECIDA),
    # Defeito nosso: não vira "a plataforma não respondeu".
    (KeyError("turmas"), navegador.FALHA_NOSSA),
    (TypeError("x"), navegador.FALHA_NOSSA),
    (AttributeError("x"), navegador.FALHA_NOSSA),
    (RuntimeError("defeito ficticio"), navegador.FALHA_NOSSA),
    (asyncio.CancelledError(), navegador.FALHA_NOSSA),
    # Grupos: olha cada uma, também aninhadas.
    (ExceptionGroup("g", [TimeoutError(), _timeout_do_playwright()]), navegador.FALHA_TEMPO),
    (ExceptionGroup("g", [TimeoutError(), ConnectionError()]), navegador.FALHA_PLATAFORMA),
    (ExceptionGroup("g", [ConnectionError(), ExceptionGroup("h", [KeyError("x")])]),
     navegador.FALHA_NOSSA),
    (ExceptionGroup("g", [ConnectionError(), ErroConector("x", codigo="captcha")]),
     navegador.FALHA_CONHECIDA),
    # Resíduos de 01/11 — tempo esgotado: o embutido, ou o de um pacote da rede pelo
    # nome; o "TimeoutError" de outro pacote (o pool do SQLAlchemy) é nosso.
    (socket.timeout(), navegador.FALHA_TEMPO),
    (httpx.ReadTimeout("x"), navegador.FALHA_TEMPO),
    (httpx.ConnectTimeout("x"), navegador.FALHA_TEMPO),
    (httpx.PoolTimeout("x"), navegador.FALHA_TEMPO),
    (sqlalchemy.exc.TimeoutError("QueuePool limit ficticio"), navegador.FALHA_NOSSA),
    (type("TimeoutError", (Exception,), {"__module__": "app.ficticio"})("x"),
     navegador.FALHA_NOSSA),
    # OSError: só o da rede culpa a plataforma; arquivo, permissão e recurso do
    # servidor são nossos.
    (socket.gaierror(11001, "getaddrinfo failed"), navegador.FALHA_PLATAFORMA),
    (ssl.SSLCertVerificationError("certificate verify failed"), navegador.FALHA_PLATAFORMA),
    (OSError(errno.ENETUNREACH, "rede inalcançável"), navegador.FALHA_PLATAFORMA),
    (FileNotFoundError("x"), navegador.FALHA_NOSSA),
    (PermissionError("x"), navegador.FALHA_NOSSA),
    (IsADirectoryError("x"), navegador.FALHA_NOSSA),
    (NotADirectoryError("x"), navegador.FALHA_NOSSA),
    (OSError(errno.ENOSPC, "sem espaço"), navegador.FALHA_NOSSA),
    (OSError(errno.EMFILE, "arquivos abertos demais"), navegador.FALHA_NOSSA),
    # O que NÓS mandamos ao navegador e quebra (antes da regra por pacote).
    (ErroDoPlaywright("Page.evaluate: ReferenceError: ficticio is not defined\n"
                      "    at eval (eval at evaluate (:291:30), <anonymous>:1:1)"),
     navegador.FALHA_NOSSA),
    (ErroDoPlaywright("Page.evaluate: SyntaxError: Unexpected token ')'"),
     navegador.FALHA_NOSSA),
    (ErroDoPlaywright("Locator.evaluate: TypeError: Cannot read properties of null"),
     navegador.FALHA_NOSSA),
    (ErroDoPlaywright("Frame.eval_on_selector_all: TypeError: x.map is not a function"),
     navegador.FALHA_NOSSA),
    (ErroDoPlaywright("ElementHandle.evaluate: ReferenceError: y is not defined"),
     navegador.FALHA_NOSSA),
    (ErroDoPlaywright('Locator.click: Unexpected token "]" while parsing selector "a]"'),
     navegador.FALHA_NOSSA),
    # ...menos o erro de REDE do fetch() de dentro da página, que é da plataforma.
    (ErroDoPlaywright("Page.evaluate: TypeError: Failed to fetch"),
     navegador.FALHA_PLATAFORMA),
    # Um erro do Playwright que não é nenhum desses continua da plataforma.
    (ErroDoPlaywright("Page.goto: Execution context was destroyed"),
     navegador.FALHA_PLATAFORMA),
    # O NOSSO navegador que caiu: para quem chama, falha conhecida (vem o ErroConector).
    (_target_closed(), navegador.FALHA_CONHECIDA),
    (Exception("Page.goto: Connection closed while reading from the driver"),
     navegador.FALHA_CONHECIDA),
])
def test_classificar_falha_da_coleta(erro, esperado):
    assert navegador.classificar_falha_da_coleta(erro) == esperado


def test_classificar_nao_levanta_com_str_quebrado():
    """Classificar roda dentro do tratamento da falha: um ``__str__`` que levanta não
    pode esconder a falha original."""
    class _StrQuebrado(Exception):
        def __str__(self):
            raise ValueError("str quebrado")

    assert navegador.classificar_falha_da_coleta(_StrQuebrado()) == navegador.FALHA_NOSSA


def test_erro_conector_de_dentro_do_grupo():
    captcha = ErroConector("x", codigo="captcha")
    grupo = ExceptionGroup("g", [OSError(), ExceptionGroup("h", [captcha])])
    assert navegador.erro_conector_de_dentro(grupo) is captcha
    assert navegador.erro_conector_de_dentro(OSError()) is None


# --- marcas de texto só na 1ª linha; OSError genérico com errno em lista branca -------

def _com_call_log(cabeca: str, html_da_pagina: str) -> str:
    """O texto de um erro do Playwright: a 1ª linha é dele; o "Call log", depois, traz
    o HTML dos elementos da página da PLATAFORMA (aqui, fictício)."""
    return (f"{cabeca}\nCall log:\n"
            "  - waiting for locator(\"#entrar:visible\").first\n"
            f"  -   locator resolved to {html_da_pagina}\n"
            "  - attempting click action\n")


# Um botão da plataforma cujo texto é uma marca do navegador caído (fictício).
_CLIQUE_QUE_ESGOTOU_COM_PAGE_CRASHED = _com_call_log(
    "Locator.click: Timeout 3000ms exceeded.",
    '<button disabled id="entrar">Page crashed</button>')


@pytest.mark.parametrize("erro, esperado", [
    # O tempo esgotado do clique continua tempo, com a marca só no Call log.
    (_do_playwright("TimeoutError", _CLIQUE_QUE_ESGOTOU_COM_PAGE_CRASHED),
     navegador.FALHA_TEMPO),
    (_do_playwright("TimeoutError", _com_call_log(
        "Locator.click: Timeout 3000ms exceeded.",
        "<p>Target crashed. Browser has been closed. Connection closed while reading "
        "from the driver</p>")), navegador.FALHA_TEMPO),
    (_do_playwright("TimeoutError", _com_call_log(
        "Locator.click: Timeout 3000ms exceeded.",
        '<span>Unexpected token while parsing selector "x"</span>')),
     navegador.FALHA_TEMPO),
    # Outro erro do Playwright com a marca só no Call log: segue a regra do pacote.
    (ErroDoPlaywright(_com_call_log("Locator.click: Element is not attached to the DOM",
                                    "<b>Page crashed</b>")), navegador.FALHA_PLATAFORMA),
    # O RuntimeError (de ``erro_sem_o_valor``) com marca só depois da 1ª linha: nosso.
    (RuntimeError(_com_call_log("defeito ficticio", "<b>Page crashed</b>")),
     navegador.FALHA_NOSSA),
    (RuntimeError(_com_call_log("defeito ficticio", "<p>net::ERR_CONNECTION_RESET</p>")),
     navegador.FALHA_NOSSA),
    # O JS nosso que quebra, com "Failed to fetch" só depois da 1ª linha: nosso.
    (ErroDoPlaywright("Page.evaluate: TypeError: Cannot read properties of null\n"
                      "    at eval (<anonymous>:1:1) Failed to fetch"),
     navegador.FALHA_NOSSA),
    # A marca de texto em exceção que não pode trazer o texto do Playwright: não vale.
    (KeyError("page crashed"), navegador.FALHA_NOSSA),
    (ValueError("Page.goto: Browser has been closed"), navegador.FALHA_NOSSA),
    (NotImplementedError("Page.goto: Target crashed"), navegador.FALHA_NOSSA),
    (KeyError("net::ERR_CONNECTION_REFUSED"), navegador.FALHA_NOSSA),
    (ValueError('Unexpected token "]" while parsing selector "a]"'), navegador.FALHA_NOSSA),
    (httpx.ConnectError("page crashed"), navegador.FALHA_PLATAFORMA),
    # Guardas: a marca na 1ª linha, de quem pode trazê-la, continua valendo.
    (ErroDoPlaywright(_com_call_log("Page.goto: Page crashed", "<i>x</i>")),
     navegador.FALHA_CONHECIDA),
    (RuntimeError(_com_call_log("Locator.fill: Target crashed", "<i>x</i>")),
     navegador.FALHA_CONHECIDA),
    (Exception("Page.goto: Connection closed while reading from the driver\n  - x"),
     navegador.FALHA_CONHECIDA),
    (ErroDoPlaywright(_com_call_log(
        'Locator.click: Unexpected token "]" while parsing selector "a]"', "<i>x</i>")),
     navegador.FALHA_NOSSA),
    (RuntimeError(_com_call_log("Page.goto: net::ERR_NAME_NOT_RESOLVED at "
                                "https://exemplo.invalid/", "<i>x</i>")),
     navegador.FALHA_PLATAFORMA),
    # OSError genérico: errno da rede ou sem errno culpa a plataforma...
    (OSError(), navegador.FALHA_PLATAFORMA),
    (OSError("Multiple exceptions: [Errno 111] ficticio, [Errno 101] ficticio"),
     navegador.FALHA_PLATAFORMA),
    (OSError(errno.EHOSTUNREACH, "máquina inalcançável"), navegador.FALHA_PLATAFORMA),
    (OSError(errno.ENETDOWN, "rede fora do ar"), navegador.FALHA_PLATAFORMA),
    (OSError(errno.EHOSTDOWN, "máquina fora do ar"), navegador.FALHA_PLATAFORMA),
    # A conexão que a rede derrubou ao se reiniciar (antes: 500 "Erro interno").
    (OSError(errno.ENETRESET, "rede derrubou a conexão"), navegador.FALHA_PLATAFORMA),
    # ...qualquer outro errno é do NOSSO servidor (antes: 502 culpando a plataforma).
    (OSError(errno.ENOMEM, "sem memória"), navegador.FALHA_NOSSA),
    (OSError(errno.EIO, "erro de E/S"), navegador.FALHA_NOSSA),
    (OSError(errno.EBADF, "descritor inválido"), navegador.FALHA_NOSSA),
    # Socket nosso sem conexão ou endereço local que não serve: também nossos.
    (OSError(errno.ENOTCONN, "socket sem conexão"), navegador.FALHA_NOSSA),
    (OSError(errno.EADDRNOTAVAIL, "endereço indisponível"), navegador.FALHA_NOSSA),
    (ExceptionGroup("g", [ConnectionResetError(), OSError(errno.ENOMEM, "x")]),
     navegador.FALHA_NOSSA),
])
def test_classificar_marcas_so_na_primeira_linha_e_errno_em_lista_branca(erro, esperado):
    assert navegador.classificar_falha_da_coleta(erro) == esperado


@pytest.mark.parametrize("erro, status", [
    # O botão "Page crashed" da plataforma no Call log não vira 503 (antes: 503).
    (_do_playwright("TimeoutError", _CLIQUE_QUE_ESGOTOU_COM_PAGE_CRASHED), 504),
    (KeyError("page crashed"), 500),                                  # antes: 503
    (OSError(errno.ENOMEM, "sem memória (fictício)"), 500),           # antes: 502
    (OSError(errno.EIO, "erro de E/S (fictício)"), 500),              # antes: 502
    (OSError(errno.EHOSTUNREACH, "máquina inalcançável (fictício)"), 502),
])
def test_rota_do_diagnostico_marca_so_na_primeira_linha_e_errno(
        cliente, db, escola_completa, monkeypatch, erro, status):
    eid = escola_completa["escola"].id
    vault.salvar_credencial(db, eid, "elefante", Credenciais(usuario="u", senha="p"))
    db.commit()
    con = _ConectorQueFalha(erro)
    monkeypatch.setattr(connectors, "obter", lambda p: con if p == "elefante" else None)

    r = cliente.post(f"/api/v1/escolas/{eid}/sync/elefante/diagnostico")
    assert r.status_code == status, r.text
    assert navegador.NAVEGADOR_CAIU not in r.text
    if status == 504:
        assert "demorou demais" in r.json()["detail"]
    if status == 500:
        assert "Elefante" not in r.text and "Erro interno" in r.json()["detail"]
    if status == 502:
        assert r.json()["detail"].startswith("Não foi possível rodar o diagnóstico agora")


@pytest.mark.parametrize("erro, status, motivo", [
    (_do_playwright("TimeoutError", _CLIQUE_QUE_ESGOTOU_COM_PAGE_CRASHED), 504,
     "tempo esgotado"),
    (OSError(errno.EHOSTUNREACH, "máquina inalcançável (fictício)"), 502, "rede"),
])
def test_placar_ao_vivo_marca_so_na_primeira_linha_e_log_da_rede(
        cliente, db, escola_completa, monkeypatch, caplog, erro, status, motivo):
    """O placar ao vivo herda: o botão "Page crashed" no Call log é tempo esgotado
    (504, não 503) e o log WARNING da falha de rede diz "rede" (não "rede ou
    navegador": o navegador que caiu tem resposta e log próprios)."""
    caplog.set_level(logging.WARNING, logger="constela.sync")
    eid = escola_completa["escola"].id
    aovivo._cache.clear()
    vault.salvar_credencial(db, eid, "matific", Credenciais(usuario="u", senha="p"))
    db.commit()
    monkeypatch.setattr(connectors, "obter",
                        lambda p: ConectorMatific() if p == "matific" else None)

    def _coleta_que_falha(*_a, **_k):
        raise erro

    monkeypatch.setattr(aovivo, "_coletar_http_first", _coleta_que_falha)
    r = cliente.get(f"/api/v1/escolas/{eid}/sync/matific/placar-ao-vivo",
                    params={"periodo": "semana", "forcar": "true"})
    assert r.status_code == status, r.text
    assert navegador.NAVEGADOR_CAIU not in r.text
    avisos = [x.getMessage() for x in caplog.records if x.name == "constela.sync"
              and x.getMessage().startswith("Consulta ao vivo do Matific falhou (")]
    assert len(avisos) == 1 and f"falhou ({motivo})" in avisos[0], avisos
    assert not _logs_da_queda(caplog)
