"""O texto de uma exceção não leva dado pessoal ao log; o tipo, o frame e a linha ficam.

Revisão integrada de 28/10 (R4): o ``logger.exception("Falha inesperada na sync …")`` (e,
em geral, todo log com ``exc_info``) escrevia no campo ``excecao`` do JSON o traceback
com o TEXTO da exceção inteiro — uma URL com o token na query, o nome da criança da
linha que não casou, um e-mail, um CPF. A redação do formatador só tirava o DETAIL do
banco. Agora o texto de cada exceção (no traceback, como argumento da mensagem e no
``extra``) passa por ``redigir_dados_pessoais``; o tipo de cada exceção e o arquivo, a
linha e a função de cada frame continuam no log, e texto técnico sem dado pessoal sai
byte a byte como antes.

Dados FICTÍCIOS: nomes inventados (os da fixture ``escola_completa`` e sobrenomes que não
existem), domínios reservados (``.exemplo``/``.test``), CPF com dígito verificador
inválido. Sem rede.
"""
from __future__ import annotations

import gc
import io
import json
import logging
import os
import sys
import time
import traceback

import pytest
from fastapi.testclient import TestClient

from app.core import observabilidade as obs
from app.core.config import settings
from app.sync import service
from tests._sync_nucleo_fakes import PlacarFake, credencial, instalar, rodar

TOKEN = "TOK-SECRETO-LOGEXC-4821"
NOME = "Zuleica Testelli Sintetico"
NOME_CAIXA_ALTA = "QUELIA MARTUSCELLI DOS ANJOS"
EMAIL = "responsavel.ficticio@exemplo.test"
CPF = "123.456.789-00"                     # DV inválido: não é de ninguém
SENHA = "valor-ficticio-local"
USUARIO = "robo-ficticio"
MSG = (f"Falhou em https://plataforma.exemplo/api/turmas?token={TOKEN}&pagina=2 para "
       f"{NOME} ({NOME_CAIXA_ALTA}); responsável {EMAIL}, CPF {CPF}; "
       f"credencial usuario={USUARIO} senha={SENHA}")
PROIBIDOS = (TOKEN, *NOME.split(), "QUELIA", "MARTUSCELLI", "ANJOS", EMAIL,
             EMAIL.split("@")[0], CPF, "123.456", SENHA, USUARIO, "pagina=2")


def _sem_proibidos(texto: str, extras=()) -> None:
    for proibido in (*PROIBIDOS, *extras):
        assert proibido not in texto, f"dado pessoal no log: {proibido[:8]}…"


def _frames(tb) -> list[str]:
    """Como cada frame aparece no traceback: arquivo, linha e função."""
    return [f'File "{f.filename}", line {f.lineno}, in {f.name}'
            for f in traceback.extract_tb(tb)]


def _registro(msg="erro_nao_tratado", args=None, exc_info=None, nivel=logging.ERROR):
    return logging.LogRecord("constela", nivel, __file__, 1, msg, args, exc_info)


def _capturado(erro: BaseException):
    try:
        raise erro
    except BaseException as capturada:  # noqa: BLE001
        return type(capturada), capturada, capturada.__traceback__


# --- O caso da revisão: a exceção inesperada da sync -----------------------------------

def test_excecao_inesperada_da_sync_vai_ao_json_sem_dado_pessoal_e_com_tipo_e_linha(
        db, escola_completa, monkeypatch, caplog):
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "matific")
    instalar(monkeypatch, placar=PlacarFake())

    def _quebra(*_a, **_k):
        raise RuntimeError(MSG)

    monkeypatch.setattr(service, "_coletar", _quebra)
    with caplog.at_level(logging.INFO, logger="constela.sync"):
        ex, erro = rodar(db, eid, "matific")
    assert erro is None and ex.status == "erro"
    [r] = [r for r in caplog.records if r.getMessage().startswith("Falha inesperada")]
    linha = obs.FormatadorJson().format(r)
    evento = json.loads(linha)

    _sem_proibidos(linha, (ec["escola"].nome, *(a.nome for a in ec["alunos"])))
    excecao = evento["excecao"]
    # O diagnóstico fica: o tipo, cada frame (arquivo, linha, função) e o que não é dado.
    assert excecao.startswith("Traceback (most recent call last):\n")
    assert "\nRuntimeError: Falhou em https://plataforma.exemplo/api/turmas?<redigido> para " \
           "<nome> (<nome>); responsável <email>, CPF <numero>; credencial " \
           "usuario=<redigido> senha=<redigido>" in excecao
    frames = _frames(r.exc_info[2])
    assert len(frames) >= 2 and frames[-1].endswith(
        f"line {_quebra.__code__.co_firstlineno + 1}, in _quebra")
    for frame in frames:
        assert frame in excecao, frame
    assert 'service.py", line ' in excecao
    # Nível e formato do JSON como antes.
    assert (evento["level"], evento["nivel"], evento["logger"]) == ("error", "ERROR",
                                                                    "constela.sync")
    assert evento["message"] == evento["msg"] == (
        f"Falha inesperada na sync (escola {eid}, plataforma matific)")


# --- Cadeia, notas, grupos e SyntaxError -----------------------------------------------

def test_cadeia_notas_e_grupo_saem_sem_dado_pessoal_com_cada_tipo_e_frame():
    class ErroDaPlataforma(Exception):
        pass

    def _raiz():
        raise KeyError(f"aluno {NOME}")

    try:
        try:
            _raiz()
        except KeyError as causa:
            erro = ErroDaPlataforma(MSG)
            erro.add_note(f"contato: {EMAIL}")
            raise erro from causa
    except ErroDaPlataforma as e:
        try:
            raise ExceptionGroup("lote", [ValueError(f"linha de {NOME_CAIXA_ALTA}"), e])
        except ExceptionGroup as grupo:
            info = (ExceptionGroup, grupo, grupo.__traceback__)

    for formatador in (obs.FormatadorJson(), obs.FormatadorTexto("%(message)s")):
        texto = formatador.format(_registro(exc_info=info))
        _sem_proibidos(texto)
        for tipo in ("ExceptionGroup: lote (2 sub-exceptions)", "ValueError: linha de <nome>",
                     "ErroDaPlataforma: Falhou em https://plataforma.exemplo/api/turmas?",
                     "contato: <email>", "KeyError: 'aluno <nome>'",
                     "The above exception was the direct cause of the following exception:"):
            assert tipo in texto, tipo
        assert f"line {_raiz.__code__.co_firstlineno + 1}, in _raiz" in texto


def test_syntax_error_mantem_arquivo_e_linha_e_redige_o_texto_avaliado():
    try:
        compile(f"{NOME} +", "<entrada-ficticia>", "eval")
    except SyntaxError as erro:
        info = (SyntaxError, erro, erro.__traceback__)
    excecao = json.loads(obs.FormatadorJson().format(_registro(exc_info=info)))["excecao"]
    _sem_proibidos(excecao)
    assert '  File "<entrada-ficticia>", line 1\n' in excecao
    assert "\nSyntaxError: " in excecao


# --- A exceção como argumento da mensagem e no extra ------------------------------------

def test_excecao_como_argumento_e_no_extra_sai_sem_dado_pessoal():
    erro = RuntimeError(MSG)
    registro = _registro("Falha inesperada ao validar %s (escola %s): %s: %s",
                         ("matific", 7, type(erro).__name__, erro), exc_info=_capturado(erro))
    registro.erro = erro                                  # extra={"erro": erro}
    evento = json.loads(obs.FormatadorJson().format(registro))
    _sem_proibidos(json.dumps(evento, ensure_ascii=False))
    assert evento["message"].startswith(
        "Falha inesperada ao validar matific (escola 7): RuntimeError: Falhou em "
        "https://plataforma.exemplo/api/turmas?<redigido> para <nome>")
    assert evento["erro"].startswith("Falhou em https://plataforma.exemplo/api/turmas?")
    assert "RuntimeError: Falhou em" in evento["excecao"]

    repr_ = json.loads(obs.FormatadorJson().format(_registro("falhou: %r", (erro,))))
    _sem_proibidos(repr_["message"])
    assert repr_["message"].startswith("falhou: RuntimeError('Falhou em https://")
    por_nome = json.loads(obs.FormatadorJson().format(
        _registro("falhou: %(erro)s", ({"erro": erro},))))
    _sem_proibidos(por_nome["message"])

    texto = obs.FormatadorTexto("%(levelname)s %(name)s: %(message)s").format(
        _registro("falhou: %s", (erro,), _capturado(erro)))
    _sem_proibidos(texto)
    assert texto.startswith("ERROR constela: falhou: Falhou em https://plataforma.exemplo/")
    assert "\nTraceback (most recent call last):\n" in texto


def _formas_de_logar(erro: BaseException) -> list[logging.LogRecord]:
    """Revisão do logexc: a exceção como a PRÓPRIA mensagem e dentro de uma lista, de uma
    tupla ou de um dict passados como argumento (ainda vazavam na de9f62e)."""
    return [_registro(erro),                                      # logger.error(erro)
            _registro("falhas: %s", ([erro, 3],)),
            _registro("falha: %s", ((erro,),)),
            _registro("falhas: %s em %s", ({"matific": [erro]}, "escola 7")),
            _registro("falhas: %(lote)s", ({"lote": {"a": (erro,)}},)),
            _registro("falhas: %r", ([erro],))]


def test_excecao_como_mensagem_ou_dentro_de_lista_tupla_ou_dict_sai_sem_dado_pessoal():
    for registro in _formas_de_logar(RuntimeError(MSG)):
        evento = json.loads(obs.FormatadorJson().format(registro))
        _sem_proibidos(evento["message"])
        assert "Falhou em https://plataforma.exemplo/api/turmas?<redigido>" in evento["message"]
        _sem_proibidos(obs.FormatadorTexto("%(message)s").format(registro))


def test_excecao_sem_dado_pessoal_como_mensagem_ou_aninhada_sai_como_antes():
    """Sem dado pessoal, a mensagem é a do ``getMessage()`` (a de antes); um argumento
    com ciclo não trava a formatação."""
    ciclo: list = [1]
    ciclo.append(ciclo)
    registros = [*_formas_de_logar(KeyError("escola_id")),
                 *_formas_de_logar(ValueError("a", 2)),
                 _registro("lote %s de %s", ([1, (2, {"x": "y"})], ciclo))]
    for registro in registros:
        esperado = registro.getMessage()
        assert json.loads(obs.FormatadorJson().format(registro))["message"] == esperado
        assert obs.FormatadorTexto("%(message)s").format(registro) == esperado


def test_argumento_com_dois_ciclos_nao_dobra_o_percurso_a_cada_nivel(monkeypatch):
    """Revisão do logexc: uma lista com dois auto-ciclos dobrava as visitas a cada nível
    (2^32 com o limite de profundidade, minutos por linha de log com o lock do handler
    preso). Agora cada ciclo para onde o ``repr()`` para, e a mensagem é a de antes."""
    original, visitas = obs._sem_excecoes, []

    def _contado(*a, **k):
        visitas.append(1)
        if len(visitas) > 200:
            raise RecursionError("percurso exponencial")
        return original(*a, **k)

    monkeypatch.setattr(obs, "_sem_excecoes", _contado)
    ciclos: list = []
    ciclos.extend((ciclos, ciclos))
    tupla: tuple = ([],)
    tupla[0].append(tupla)
    proprio: dict = {"x": 1}
    proprio["a"] = proprio
    for registro in (_registro("lote %s", (ciclos,)), _registro("lote %s e %s", (tupla, 3)),
                     _registro("lote %(a)s", (proprio,))):
        visitas.clear()
        esperado = registro.getMessage()            # "lote [[...], [...]]", "([(...)],)"…
        assert json.loads(obs.FormatadorJson().format(registro))["message"] == esperado
        assert obs.FormatadorTexto("%(message)s").format(registro) == esperado
        assert len(visitas) < 20, len(visitas)


def test_excecao_dentro_de_um_ciclo_sai_sem_dado_pessoal():
    """O ponto em que a lista volta a si mesma não leva a lista ORIGINAL (com a exceção
    crua dentro) para a mensagem: vira o "[...]" do ``repr()``."""
    erro = RuntimeError(MSG)
    ciclo: list = [erro]
    ciclo.append(ciclo)
    for registro in (_registro("lote %s", (ciclo,)), _registro("lote %r", (ciclo,))):
        mensagem = json.loads(obs.FormatadorJson().format(registro))["message"]
        _sem_proibidos(mensagem)
        assert mensagem.startswith("lote [") and mensagem.endswith(", [...]]")
        assert "RuntimeError('Falhou em https://plataforma.exemplo/api/turmas?<redigido>" in (
            mensagem)


def test_excecao_com_str_que_falha_ainda_sai_no_repr():
    """Revisão do logexc: o texto da exceção era calculado na criação, mesmo quando a
    mensagem só pedia "%r"; um ``__str__`` que falha derrubava a linha inteira
    ("<falha ao formatar o log>"). O "%r" sai como antes; o "%s" sai com o marcador do
    traceback do Python (antes do logexc, a linha também se perdia)."""
    class ErroDeStrQuebrado(Exception):
        def __str__(self):
            raise ValueError("sem texto")

    erro = ErroDeStrQuebrado("escola_id")
    registro = _registro("falhou: %r", (erro,))
    assert json.loads(obs.FormatadorJson().format(registro))["message"] == (
        "falhou: ErroDeStrQuebrado('escola_id')") == registro.getMessage()
    assert json.loads(obs.FormatadorJson().format(_registro("falhou: %s", (erro,))))[
        "message"] == "falhou: <exception str() failed>"


def test_texto_comum_nos_argumentos_continua_como_o_codigo_escreveu():
    """Só a EXCEÇÃO passada como argumento é redigida: a mensagem que o código monta
    com os próprios valores continua igual (a regra do DETAIL do banco já valia)."""
    evento = json.loads(obs.FormatadorJson().format(_registro(
        "sync_execucao_finalizada execucao=%s escola=%s plataforma=%s status=%s motivo=%s",
        (12, 3, "matific", "concluida", "-"), nivel=logging.INFO)))
    assert evento["message"] == ("sync_execucao_finalizada execucao=12 escola=3 "
                                 "plataforma=matific status=concluida motivo=-")


def _excecoes_sem_dado_pessoal() -> list[BaseException]:
    import sqlite3

    erros: list[BaseException] = [
        KeyError("escola_id"), RuntimeError(), ValueError("a", 2), RuntimeError(None),
        OSError(10054, "An existing connection was forcibly closed by the remote host"),
        FileNotFoundError(2, "No such file or directory", "/tmp/lista.csv"),
        sqlite3.OperationalError("database is locked"), TimeoutError("Timeout 30000ms exceeded."),
        ExceptionGroup("lote", [ValueError("linha 3"), KeyError("ra")]), StopIteration(3)]
    for codigo in (lambda: b"\xff".decode("utf-8"), lambda: compile("x = = 1", "<e>", "exec"),
                   lambda: int("abc")):
        try:
            codigo()
        except Exception as erro:  # noqa: BLE001
            erros.append(erro)
    return erros


@pytest.mark.parametrize("erro", _excecoes_sem_dado_pessoal(), ids=lambda e: type(e).__name__)
def test_repr_de_excecao_sem_dado_pessoal_sai_como_o_python_escreve(erro):
    """Revisão do logexc: o ``%r`` saía do ``str()`` da exceção, e uma sem dado pessoal
    mudava de forma: KeyError("'escola_id'"), RuntimeError(''), ValueError("('a', 2)")."""
    esperado = f"falhou: {erro!r}"
    assert json.loads(obs.FormatadorJson().format(
        _registro("falhou: %r", (erro,))))["message"] == esperado
    assert obs.FormatadorTexto("%(message)s").format(_registro("falhou: %r", (erro,))) == esperado
    assert json.loads(obs.FormatadorJson().format(
        _registro("falhou: %(e)r", ({"e": erro},))))["message"] == esperado


def test_repr_de_excecao_com_dado_pessoal_tem_a_forma_do_python_sem_o_dado():
    erro = ValueError(f"aluno {NOME}", 3, (EMAIL,))
    mensagem = json.loads(obs.FormatadorJson().format(_registro("falhou: %r", (erro,))))["message"]
    assert mensagem == "falhou: ValueError('aluno <nome>', 3, ('<email>',))"


# --- O diagnóstico de login do conector (app/sync/connectors/base.py) ------------------

class _NavegadorQueFalha:
    def __init__(self, erro: BaseException):
        self.erro = erro

    async def ir_para(self, _url):
        raise self.erro

    async def fechar(self):
        pass


def _diagnostico_de_login(erro: BaseException, caplog) -> tuple[dict, logging.LogRecord]:
    import asyncio

    from app.sync import connectors
    from app.sync.interfaces import Contexto

    async def _fabrica(**_k):
        return _NavegadorQueFalha(erro)

    classe = type(connectors.obter("matific"))
    contexto = Contexto(escola_id=0, execucao_id=None, log=lambda *_a: None, timeout_s=30)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="constela.sync"):
        resposta = asyncio.run(classe(_fabrica).diagnosticar_login(contexto))
    [registro] = [r for r in caplog.records if r.getMessage().startswith("Diagnóstico de")]
    return resposta, registro


def test_diagnostico_de_login_loga_a_excecao_sem_dado_pessoal_e_a_resposta_nao_muda(caplog):
    """Revisão do logexc: o diagnóstico de login logava o texto da exceção já montado
    (f"{tipo}: {str(exc)[:140]}"), um texto comum que a redação não alcança."""
    resposta, registro = _diagnostico_de_login(RuntimeError(MSG), caplog)
    assert resposta["erro"] == f"RuntimeError: {MSG[:140]}"         # a resposta, como antes
    linha = obs.FormatadorJson().format(registro)
    _sem_proibidos(linha)
    assert json.loads(linha)["message"] == (
        "Diagnóstico de login matific: RuntimeError: "
        + obs.redigir_dados_pessoais(MSG)[:140])

    tecnico = TimeoutError("Page.goto: Timeout 20000ms exceeded.\nCall log:\n  - navigating "
                           "to \"https://plataforma.exemplo/login\", waiting until \"load\"" * 3)
    resposta, registro = _diagnostico_de_login(tecnico, caplog)
    esperado = f"Diagnóstico de login matific: {resposta['erro']}"     # a linha de antes
    assert registro.getMessage() == esperado
    assert json.loads(obs.FormatadorJson().format(registro))["message"] == esperado


# --- O valor que o Playwright digitou, no "Call log" do erro ---------------------------
# Revisão adversarial do logexc: com o campo achado mas readonly ou disabled, o
# Locator.fill estoura o tempo e o texto do erro traz o USUÁRIO e a SENHA no call log
# (fill("…")) — e a redação não reconhecia essa forma (sem ":" nem "=", entre aspas).

try:
    from playwright.async_api import TimeoutError as TimeoutDoPlaywright
except ImportError:  # pragma: no cover — o pacote é do requirements.txt
    TimeoutDoPlaywright = type("TimeoutError", (Exception,), {})


def _erro_ao_preencher(seletor: str, previa: str, valor: str, motivo: str) -> str:
    """O texto LITERAL do erro do Playwright 1.48 (o do requirements.txt) quando o campo
    achado não aceita o valor: o driver escreve o valor no call log (lib/server/dom.js,
    ``progress.log(`  fill("${value}")`)``) e a prévia do campo com os atributos dele; o
    cliente Python junta o call log ao texto (_impl/_connection.py, ``format_call_log``).
    Capturado do Chromium headless, sem rede, com valores fictícios (as 2 primeiras
    tentativas; o real segue igual até o tempo acabar)."""
    return ("Locator.fill: Timeout 30000ms exceeded.\nCall log:\n"
            f'waiting for locator("{seletor}:visible").first\n'
            f"  -   locator resolved to {previa}\n"
            f'  -   fill("{valor}")\n'
            "  - attempting fill action\n"
            "  -   waiting for element to be visible, enabled and editable\n"
            f"  -   element is not {motivo}\n"
            "  - retrying fill action, attempt #1\n"
            "  -   waiting for element to be visible, enabled and editable\n"
            f"  -   element is not {motivo}\n"
            "  - retrying fill action, attempt #2\n"
            "  -   waiting 20ms\n")


def _erro_no_usuario(valor: str = USUARIO) -> str:
    # A página escreveu o usuário no value do campo (o ASP.NET o devolve assim).
    return _erro_ao_preencher("#u", f'<input id="u" readonly value="{valor}"/>', valor,
                              "editable")


def _erro_na_senha(valor: str = SENHA) -> str:
    return _erro_ao_preencher("#entrada", '<input disabled id="entrada" type="password"/>',
                              valor, "enabled")


def _sem_o_valor_e_com_o_diagnostico(texto: str, motivo: str) -> None:
    _sem_proibidos(texto)
    assert 'fill("<redigido>")' in texto
    for diagnostico in ("Locator.fill: Timeout 30000ms exceeded.\nCall log:\n",
                        "  - attempting fill action\n",
                        f"  -   element is not {motivo}\n",
                        "  - retrying fill action, attempt #2\n"):
        assert diagnostico in texto, diagnostico


class _NavegadorQueRecusaOValor:
    """O formulário de login aparece; o preenchimento de número ``falha_no`` (1: o
    usuário, 2: a senha) falha como o do Playwright, com o valor no call log."""

    def __init__(self, falha_no: int):
        self.falha_no, self.preenchidos = falha_no, 0

    async def ir_para(self, _url):
        pass

    async def url_atual(self):
        return "https://plataforma.exemplo/login"

    async def esperar(self, _seletor, timeout_s=20):
        return True

    async def visivel(self, seletor):
        return "password" in seletor.lower()

    async def clicar(self, _seletor):
        pass

    async def preencher(self, _seletor, valor):
        self.preenchidos += 1
        if self.preenchidos == self.falha_no:
            raise TimeoutDoPlaywright(_erro_no_usuario(valor) if self.falha_no == 1
                                      else _erro_na_senha(valor))

    async def fechar(self):
        pass


@pytest.mark.parametrize("plataforma", ["matific", "elefante"])
@pytest.mark.parametrize("falha_no, motivo", [(1, "editable"), (2, "enabled")],
                         ids=["usuario", "senha"])
def test_erro_do_playwright_ao_validar_credencial_sai_sem_usuario_e_senha(
        plataforma, falha_no, motivo, caplog):
    """testar_credenciais (base.py) loga "%s: %s" com a exceção e ``exc_info=True``: o
    valor que o Playwright digitou não vai nem para o ``message`` nem para o
    ``excecao``; o tipo, o call log sem o valor e a linha do frame ficam."""
    import asyncio

    from app.sync import connectors
    from app.sync.interfaces import Contexto, Credenciais

    async def _fabrica(**_k):
        return _NavegadorQueRecusaOValor(falha_no)

    classe = type(connectors.obter(plataforma))
    contexto = Contexto(escola_id=7, execucao_id=None, log=lambda *_a: None, timeout_s=30)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="constela.sync"):
        resultado = asyncio.run(classe(_fabrica).testar_credenciais(
            Credenciais(usuario=USUARIO, senha=SENHA), contexto))
    assert resultado.ok is False and resultado.codigo == "erro_navegador"
    [registro] = [r for r in caplog.records if r.getMessage().startswith("Falha inesperada")]

    evento = json.loads(obs.FormatadorJson().format(registro))
    _sem_o_valor_e_com_o_diagnostico(evento["message"], motivo)
    assert evento["message"].startswith(
        f"Falha inesperada ao validar {plataforma} (escola 7): TimeoutError: Locator.fill: ")
    _sem_o_valor_e_com_o_diagnostico(evento["excecao"], motivo)
    assert evento["excecao"].startswith("Traceback (most recent call last):\n")
    assert "TimeoutError: Locator.fill: Timeout 30000ms exceeded." in evento["excecao"]
    assert "in preencher\n" in evento["excecao"]
    _sem_proibidos(obs.FormatadorTexto("%(message)s").format(registro))


def test_erro_do_playwright_na_sync_sai_sem_a_senha_no_logger_exception(
        db, escola_completa, monkeypatch, caplog):
    """O ``logger.exception("Falha inesperada na sync …")`` (service.py) com o erro do
    Playwright: o ``excecao`` do JSON sai sem o usuário e a senha."""
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    instalar(monkeypatch, placar=PlacarFake())
    erros = iter([_erro_no_usuario(), _erro_na_senha()])

    def _quebra(*_a, **_k):
        raise TimeoutDoPlaywright(next(erros))

    monkeypatch.setattr(service, "_coletar", _quebra)
    for motivo in ("editable", "enabled"):
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="constela.sync"):
            ex, erro = rodar(db, eid, "matific")
        assert erro is None and ex.status == "erro"
        [r] = [r for r in caplog.records if r.getMessage().startswith("Falha inesperada")]
        evento = json.loads(obs.FormatadorJson().format(r))
        _sem_o_valor_e_com_o_diagnostico(evento["excecao"], motivo)
        assert f"line {_quebra.__code__.co_firstlineno + 1}, in _quebra" in evento["excecao"]
        assert evento["message"] == f"Falha inesperada na sync (escola {eid}, plataforma matific)"


@pytest.mark.parametrize("texto, esperado", [
    # O valor vai até o fim da ENTRADA do call log: aspa, ")" e quebra de linha dentro
    # dele não o encerram; a entrada seguinte fica.
    ('  -   fill("Fic")ticia"9")\n  - attempting fill action',
     '  -   fill("<redigido>")\n  - attempting fill action'),
    ('  -   fill("linha1\nlinha2")\n  - attempting fill action',
     '  -   fill("<redigido>")\n  - attempting fill action'),
    ('Call log:\n  -   fill("valor-sem-fim', 'Call log:\n  -   fill("<redigido>")'),
    ('  -   fill("abc")\n', '  -   fill("<redigido>")\n'),
    ('elementHandle.type("abc123")\n  - x', 'elementHandle.type("<redigido>")\n  - x'),
    ('elementHandle.press("Enter")', 'elementHandle.press("<redigido>")'),
    # O value da prévia do elemento: até a última aspa da linha, ou até o fim dela.
    ('  -   locator resolved to <input id="u" readonly value="abc.def"/>\n  - x',
     '  -   locator resolved to <input id="u" readonly value="<redigido>"/>\n  - x'),
    ('locator resolved to <input value="a"b" id="u"/>',
     'locator resolved to <input value="<redigido>"/>'),
    ('locator resolved to <input id="u" value="cortado-pelo-limite…',
     'locator resolved to <input id="u" value="<redigido>'),
    # Fora da prévia, ``value=`` e uma chamada sem aspas ficam.
    ('<input value="3"> fill(campo) type(x)', '<input value="3"> fill(campo) type(x)'),
])
def test_valor_digitado_pelo_playwright(texto, esperado):
    assert obs.redigir_dados_pessoais(texto) == esperado
    assert obs.redigir_valor_digitado(texto) == esperado


def test_redigir_valor_digitado_tira_o_valor_exato_onde_estiver():
    texto = f"falhou com {USUARIO} (de novo: {USUARIO}); ab"
    assert obs.redigir_valor_digitado(texto, USUARIO) == (
        "falhou com <redigido> (de novo: <redigido>); ab")
    assert obs.redigir_valor_digitado(texto, "ab") == texto     # curto demais: desfiguraria
    assert obs.redigir_valor_digitado(texto, "") == texto
    assert obs.redigir_valor_digitado("", USUARIO) == ""


# --- O navegador real relança o erro do preenchimento sem o valor ----------------------

class _CampoQueRecusa:
    def __init__(self, texto: str):
        self.texto = texto

    @property
    def first(self):
        return self

    async def fill(self, _valor):
        raise TimeoutDoPlaywright(self.texto)


class _PaginaQueRecusa:
    def __init__(self, texto: str):
        self.texto = texto

    def locator(self, _seletor):
        return _CampoQueRecusa(self.texto)


def _preencher_no_playwright(texto: str, valor: str) -> BaseException:
    import asyncio

    from app.sync.connectors.navegador import _NavegadorPlaywright

    nav = _NavegadorPlaywright(None, None, _PaginaQueRecusa(texto))
    with pytest.raises(BaseException) as capturado:
        asyncio.run(nav.preencher("#entrada", valor))
    return capturado.value


def test_preencher_do_playwright_relanca_o_erro_sem_o_valor():
    """Defesa na origem: o erro sai de ``preencher`` sem o valor (para o log, o Sentry e
    quem mais ler a exceção), do MESMO tipo, com o call log e a pilha de onde nasceu, e
    sem o original (com o valor) pendurado como ``__context__``."""
    for texto, valor, motivo in ((_erro_no_usuario(), USUARIO, "editable"),
                                 (_erro_na_senha(), SENHA, "enabled")):
        erro = _preencher_no_playwright(texto, valor)
        assert type(erro) is TimeoutDoPlaywright
        _sem_o_valor_e_com_o_diagnostico(str(erro), motivo)
        assert str(erro) == obs.redigir_valor_digitado(texto)
        assert erro.__context__ is None and erro.__cause__ is None
        funcoes = [f.name for f in traceback.extract_tb(erro.__traceback__)]
        assert funcoes.count("preencher") == 1 and funcoes[-1] == "fill", funcoes

    # O valor que aparece em outro lugar do texto também sai (o valor exato).
    erro = _preencher_no_playwright(f"Locator.fill: campo recusou {SENHA}", SENHA)
    assert str(erro) == "Locator.fill: campo recusou <redigido>"


def test_preencher_do_playwright_sem_o_valor_no_erro_relanca_o_mesmo_erro():
    texto = 'Locator.fill: Timeout 30000ms exceeded.\nCall log:\nwaiting for locator("#x")\n'
    erro = _preencher_no_playwright(texto, SENHA)
    assert type(erro) is TimeoutDoPlaywright and str(erro) == texto


def test_erro_sem_o_valor_com_tipo_que_nao_se_cria_so_com_a_mensagem():
    from app.sync.connectors.navegador import erro_sem_o_valor

    class ErroDeDoisArgumentos(Exception):
        def __init__(self, codigo, texto):
            super().__init__(f"{codigo}: {texto}")

    erro = erro_sem_o_valor(ErroDeDoisArgumentos(7, f'fill("{SENHA}")'), SENHA)
    assert type(erro) is RuntimeError and str(erro) == '7: fill("<redigido>")'


# --- Pela rota de verdade: erro_nao_tratado do middleware -------------------------------

@pytest.fixture
def log_do_processo(monkeypatch):
    raiz = logging.getLogger()
    nomes = ("sqlalchemy.engine", "alembic", "httpx", "uvicorn", "uvicorn.error",
             "uvicorn.access")
    salvo = (list(raiz.handlers), raiz.level,
             {n: (logging.getLogger(n).level, list(logging.getLogger(n).handlers),
                  logging.getLogger(n).propagate) for n in nomes})
    saida = io.StringIO()
    monkeypatch.setattr(sys, "stdout", saida)
    obs.configurar_logging(settings)
    yield lambda: [json.loads(x) for x in saida.getvalue().splitlines() if x.startswith("{")]
    handlers, nivel, outros = salvo
    raiz.handlers[:] = handlers
    raiz.setLevel(nivel)
    for nome, (lvl, hs, prop) in outros.items():
        lg = logging.getLogger(nome)
        lg.setLevel(lvl)
        lg.handlers[:] = hs
        lg.propagate = prop


def test_erro_nao_tratado_de_uma_rota_sai_sem_dado_pessoal_e_a_resposta_nao_muda(
        log_do_processo, monkeypatch):
    from app.main import app
    from app.services import rede as svc_rede

    def _quebra(*_a, **_k):
        raise RuntimeError(MSG)
    monkeypatch.setattr(svc_rede, "rede_pelo_token_publico", _quebra)

    r = TestClient(app, raise_server_exceptions=False).get("/api/v1/publico/rede/tokficticio")
    assert r.status_code == 500
    assert r.content == b'{"detail": "Erro interno. Tente novamente em instantes."}'

    erros = [x for x in log_do_processo() if x["message"] == "erro_nao_tratado"]
    assert len(erros) == 1
    _sem_proibidos(json.dumps(erros, ensure_ascii=False))
    assert erros[0]["level"] == "error" and erros[0]["caminho"] == "/api/v1/publico/rede/<token>"
    assert f"line {_quebra.__code__.co_firstlineno + 1}, in _quebra" in erros[0]["excecao"]
    assert "\nRuntimeError: Falhou em https://plataforma.exemplo/api/turmas?" in (
        erros[0]["excecao"])


# --- As regras, uma a uma ----------------------------------------------------------------

@pytest.mark.parametrize("texto, esperado", [
    # URL: query, fragmento, usuário/senha e o token de rota saem; host e caminho ficam.
    (f"GET https://plataforma.exemplo/api?token={TOKEN}.",
     "GET https://plataforma.exemplo/api?<redigido>."),
    ("em https://app.exemplo/login#sid=abc123 (fim)",
     "em https://app.exemplo/login#<redigido> (fim)"),
    (f"postgresql+psycopg://constela:{SENHA}@db.exemplo.test:5432/base",
     "postgresql+psycopg://<redigido>@db.exemplo.test:5432/base"),
    ("https://api.exemplo.test/api/v1/publico/rede/tokficticio/x",
     "https://api.exemplo.test/api/v1/publico/rede/<token>/x"),
    # Credencial com separador, entre aspas (dict) e sem separador com cara de credencial.
    (f"senha={SENHA}&usuario={USUARIO}", "senha=<redigido>&usuario=<redigido>"),
    (f"{{'usuario': '{USUARIO}', 'senha': '{SENHA}', 'escola_id': 3}}",
     "{'usuario': <redigido>, 'senha': <redigido>, 'escola_id': 3}"),
    (f"(usuario {USUARIO} / senha {SENHA})", "(usuario <redigido> / senha <redigido>)"),
    ("Authorization: Bearer abcDEF0123456789xyz", "Authorization: Bearer <redigido>"),
    ("qr_token=tokQrFicticio5Hd1 nome='Zuleica'", "qr_token=<redigido> nome=<redigido>"),
    ("[type=string_type, input_value='zuleica testelli', input_type=str]",
     "[type=string_type, input_value=<redigido>, input_type=str]"),
    ("(Background)\n[parameters: ('Zuleica', 3)]\n(x)",
     "(Background)\n[parameters: <redigido>]\n(x)"),
    # Token opaco e JWT.
    ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJh", "jwt <token>"),
    ("id 1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed", "id <token>"),
    # E-mail e números de documento (CPF, RA com DV, telefone, CEP).
    (f"de {EMAIL}.", "de <email>."),
    (f"CPF {CPF}, RA 000123456789-X, tel (12) 99999-0000, CEP 11660-000",
     "CPF <numero>, RA <numero>, tel (12) <numero>, CEP <numero>"),
    # Nomes: Capitalizados, CAIXA ALTA, partículas, hífen e apóstrofo.
    (f"aluno {NOME} sem turma", "aluno <nome> sem turma"),
    (f"ALUNO {NOME_CAIXA_ALTA} SEM TURMA", "<nome>"),
    ("Maria da Silva e João dos Santos; D'Ávila Testelli, Ana-Clara Sintetico",
     "<nome>; <nome>, <nome>"),
    ("escola ESCOLA FICTICIA TESTE (17)", "escola <nome> (17)"),
    ("aluno MAX TESTELLI no Matific", "aluno <nome> no Matific"),
    # O grupo: só espaço, tab ou nbsp entre as palavras; a partícula da ponta fica fora;
    # palavra do vocabulário no meio de um nome vai junto; um nome por trecho.
    ("Ana\u00a0Souza\tLima e Silva", "<nome>"),
    ("de Ana Souza e", "de <nome> e"),
    ("Ana' Souza Lima", "Ana' <nome>"),
    ("Ana Souza, Lima Testelli; Max", "<nome>, <nome>; Max"),
    ("ANA-\nSOUZA LIMA", "ANA-\n<nome>"),
    ("INSERT INTO Ana Souza", "<nome>"),
    ("Placar do Matific; Lista Piloto", "Placar do Matific; Lista Piloto"),
    # O que a revisão do logexc devolveu ao diagnóstico não abre brecha: valor que só
    # começa como marcador do SQL, número formatado ou sem unidade, "Edu" é nome.
    ("nome = 'Zuleica'; senha=?abc; senha = %(x", "nome = <redigido>; senha=<redigido>; "
     "senha = <redigido>"),
    ("RA 123456789 s/ turma; 1.048.576 bytes", "RA <numero> s/ turma; <numero> bytes"),
    ("aluno Edu Testelli", "aluno <nome>"),
    # Revisão adversarial do logexc: o valor sem aspas de uma chave de NOME vai além da
    # primeira palavra (o sobrenome sozinho escapava das duas regras); para no
    # vocabulário técnico, na chave seguinte ou no que não é palavra.
    ("nome: Zuleica Testelli", "nome: <redigido>"),
    ("matific|nome:zuleica testelli|sala:3a", "matific|nome:<redigido>|sala:3a"),
    ("responsavel: Maria da Silva, CPF 1", "responsavel: <redigido>, CPF 1"),
    ("usuario=Ana Souza; name=Ana Souza; nome_social: Ana Souza",
     "usuario=<redigido>; name=<redigido>; nome_social: <redigido>"),
    ("WHERE nome = abc AND x = 1; nome: Ana 3A", "WHERE nome = <redigido> AND x = 1; "
     "nome: <redigido> 3A"),
    ("nome:a nome:b sala: Zuleica Testelli", "nome:<redigido> nome:<redigido> sala: <nome>"),
    # A partícula "do" também é SQL: olhada antes do vocabulário, e só entra com um nome
    # depois dela (o sobrenome sozinho escapava).
    ("nome: Maria do Carmo; responsavel: Ana do Socorro", "nome: <redigido>; "
     "responsavel: <redigido>"),
    ("matific|nome:joao do nascimento|sala:3a", "matific|nome:<redigido>|sala:3a"),
    ("WHERE nome = abc DO NOTHING; nome: Ana do", "WHERE nome = <redigido> DO NOTHING; "
     "nome: <redigido> do"),
    # Credencial sem separador ENTRE ASPAS (o valor de dentro, com cara de credencial).
    ("senha 'Abc12345' e senha \"Abc12345\"", "senha <redigido> e senha <redigido>"),
    ("usuário 'zuleica.testelli' inválido; token 'x-9", "usuário <redigido> inválido; "
     "token <redigido>"),
])
def test_cada_regra(texto, esperado):
    assert obs.redigir_dados_pessoais(texto) == esperado


@pytest.mark.parametrize("texto", [
    "(sqlite3.IntegrityError) FOREIGN KEY constraint failed\n[SQL: INSERT INTO alunos "
    "(escola_id, nome) VALUES (?, ?)]\n[SQL parameters hidden due to hide_parameters=True]\n"
    "(Background on this error at: https://sqlalche.me/e/20/gkpj)",
    "duplicate key value violates unique constraint \"uq_x\"\nDETAIL:  Key (escola_id, "
    "nome)=(<redigido>) already exists.",
    "null value in column \"nome\" of relation \"alunos\" violates not-null constraint\n"
    "DETAIL:  Failing row contains (<redigido>).",
    "SELECT alunos.id FROM alunos LEFT OUTER JOIN turmas ON turmas.id = alunos.turma_id "
    "WHERE alunos.escola_id = %(escola_id)s ORDER BY alunos.nome FOR UPDATE SKIP LOCKED",
    "INSERT INTO x (a) VALUES (1) ON CONFLICT DO NOTHING RETURNING x.id",
    "Client error '404 Not Found' for url 'https://api.exemplo.test/v1/escolas/17'",
    "Server error '503 Service Unavailable' for url 'https://api.exemplo.test/v1/x'",
    "connection to server at \"127.0.0.1\", port 55433 failed: FATAL:  password "
    "authentication failed for user \"constela\"",
    "Page.goto: Timeout 30000ms exceeded.\nCall log:\n  - navigating to \"https://app."
    "exemplo/login\", waiting until \"load\"",
    "Placar do Matific falhou na API (HTTP 503).",
    "A Lista Piloto da escola 17 não tem a turma 3 ANO A.",
    "name 'variavel_que_nao_existe_qz' is not defined. Did you mean: 'variavel'?",
    "'NoneType' object has no attribute 'escola_id'",
    "Object of type Decimal is not JSON serializable",
    "período 2026-09-01 a 2026-10-27 (bimestre_4), execução 4821, escola 17",
    "senha inválida para a conta da escola; token expirado; login recusado",
    "As credenciais do Elefante não estão configuradas. Configure em Sincronização.",
    "Conector do Elefante indisponível. Download do Matific veio vazio.",
    "codigo=senha_invalida recuperavel=False",
    "",
    # Da revisão do logexc (mudavam na de9f62e): o marcador de parâmetro do SQL depois
    # de "coluna =", o número só de dígitos com unidade, termos do app.
    "(sqlite3.OperationalError) no such column: x\n[SQL: UPDATE alunos SET nome = ? "
    "WHERE alunos.nome = ? AND x = 1]\n[SQL parameters hidden due to hide_parameters=True]",
    "[SQL: UPDATE alunos SET nome=%(nome)s WHERE alunos.nome = %(nome_1)s AND "
    "alunos.escola_id = %(escola_id_1)s]",
    "[SQL: SELECT alunos.id FROM alunos WHERE alunos.nome = $1 AND alunos.nome_social = %s]",
    "Page.goto: Timeout 180000ms exceeded.",
    "download veio com 1048576 bytes em 120000 ms",
    "Apenas o Admin Global pode alterar o contrato da Rede Municipal.",
    "esperado Municipal, Estadual, Federal, Privada ou um dos Totais do INEP",
    "O Constela Edu importa o Excel exportado pelo Matific.",
    # Valor entre aspas sem cara de credencial.
    "o campo senha 'obrigatório' está vazio; token \"expirado\"; login 'recusado'",
])
def test_texto_tecnico_sem_dado_pessoal_volta_igual(texto):
    assert obs.redigir_dados_pessoais(texto) == texto


def _exc_tecnicas():
    """Exceções sem dado pessoal: o traceback sai byte a byte como o do Python (o mesmo
    texto que o formatador escrevia antes da redação de dado pessoal)."""
    import sqlite3

    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError, OperationalError

    engine = create_engine("sqlite://", hide_parameters=True)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE t (id integer primary key, nome text NOT NULL)"))
    casos = []
    try:
        with engine.begin() as c:
            c.execute(text("INSERT INTO t (nome) VALUES (:n)"), {"n": None})
    except IntegrityError as erro:
        casos.append(erro)
    try:                                   # o [SQL: …] com "nome = ?" (revisão do logexc)
        with engine.begin() as c:
            c.execute(text("UPDATE t SET nome = :nome WHERE t.nome = :nome_1 AND x = 1"),
                      {"nome": "a", "nome_1": "b"})
    except OperationalError as erro:
        casos.append(erro)
    engine.dispose()
    for erro in (KeyError("escola_id"), ValueError("valor"),
                 sqlite3.OperationalError("database is locked"),
                 TimeoutError("Timeout 30000ms exceeded."),
                 TimeoutError("Page.goto: Timeout 180000ms exceeded."),
                 RuntimeError("Apenas o Admin Global pode alterar o contrato da Rede Municipal"),
                 RuntimeError("Placar do Matific falhou na API (HTTP 503).")):
        casos.append(_capturado(erro)[1])
    try:
        try:
            {}["chave_canonica"]
        except KeyError as causa:
            raise LookupError("turma 3 ANO A sem titular") from causa
    except LookupError as erro:
        erro.add_note("execução 4821, escola 17")
        casos.append(erro)
    return casos


def test_traceback_sem_dado_pessoal_e_identico_ao_do_python():
    for erro in _exc_tecnicas():
        info = (type(erro), erro, erro.__traceback__)
        esperado = "".join(traceback.format_exception(*info)).rstrip("\n")
        assert obs.traceback_redigido(erro) == esperado
        evento = json.loads(obs.FormatadorJson().format(_registro(exc_info=info)))
        assert evento["excecao"] == logging.Formatter().formatException(info)


def _palavras_distintas(n: int) -> str:
    """Palavras Capitalizadas TODAS diferentes ("Naaaa Nbaaa …"): nenhuma se repete."""
    return " ".join("N" + "".join(chr(97 + (i // 26 ** k) % 26) for k in range(4))
                    for i in range(n // 6))


# Cada caso, do tamanho pedido (em caracteres): o pior texto para uma regra.
_ADVERSARIOS = {
    "letras": lambda n: "a" * n,
    "palavras-capitalizadas": lambda n: "Ana " * (n // 4),
    "palavras-distintas": _palavras_distintas,
    "nomes-e-virgulas": lambda n: "Ana Souza, " * (n // 11),
    "particulas": lambda n: "Ana de " * (n // 7),
    "maiusculas-soltas": lambda n: "A " * (n // 2),
    "nomes-por-linha": lambda n: "Ana\n" * (n // 4),
    "caixa-alta-sem-espaco": lambda n: "ANA-" * (n // 4),
    "chaves-sem-valor": lambda n: "senha" + " " * n + "x",
    "tab-depois-da-chave": lambda n: "senha" + "\t" * n + "x",
    "chaves-nao-secretas": lambda n: "a=" * (n // 2),
    "chaves-entre-aspas": lambda n: "'senha': '" * (n // 10),
    "credencial-solta": lambda n: "senha " * (n // 6),
    "bearer": lambda n: "Bearer " * (n // 7),
    "jwt": lambda n: "eyJ" + "a" * n,
    "arrobas": lambda n: "a" * (n // 2) + "@" + "b" * (n // 2),
    "emails": lambda n: "a@b." * (n // 4),
    "ponto-arroba": lambda n: "a.@" * (n // 3),
    "digitos": lambda n: "1." * (n // 2),
    "urls": lambda n: "https://x.exemplo/?" * (n // 19),
    "url-de-barras": lambda n: "a://" + "/" * n,
    "tokens": lambda n: ("a1" * 20 + " ") * (n // 41),
    "valor-digitado": lambda n: 'fill("' * (n // 6),
    "entradas-do-call-log": lambda n: 'fill("a")\n  - ' * (n // 14),
    "previas": lambda n: "resolved to <" * (n // 13),
    "values-da-previa": lambda n: "resolved to <" + ' value="' * (n // 8),
    "nome-depois-da-chave": lambda n: "nome: " + "Ana " * (n // 4),
    "chaves-de-nome": lambda n: "nome:a " * (n // 7),
    "credencial-entre-aspas": lambda n: "senha '" * (n // 7),
}
# O custo é medido pela ESCALA, não por um relógio fixo: o tempo de um texto 4x maior
# tem de ficar perto de 4x (linear), longe de 16x (quadrático). O teto fixo de 2 s por
# 1 MB dependia da máquina e da cobertura (o CI roda com --cov=app, que encarece o
# Python) e falhava sem regressão nenhuma. O ruído da máquina só SOMA tempo: vale o
# menor de duas medidas de cada tamanho, alternadas (os dois veem a mesma carga), e uma
# medida ruim é refeita; um custo quadrático falha em todas. Uma regex com retrocesso
# quadrático já passa do teto no texto menor (e falha nele, sem medir o maior).
_TAMANHO = 50_000
_RAZAO_MAXIMA = 8.0            # linear: ~4; quadrático: ~16
_PISO_S = 0.25                 # abaixo disso, 4x maior é ruído, não escala
# Teto de CUSTO DE CPU (veja test_tetos_de_tempo.py): 2,5x o TETO_S de
# test_planilha_inflada.py — 5 s numa máquina comum, 30 s com CI (--cov=app num runner
# 2–3x mais lento), TESTE_TETO_TEMPO_S por cima. Linear: ~0,05 s com cobertura (pior
# caso medido em 30/10: 0,056 s); quadrático: dezenas.
_TETO_DO_MENOR_S = 2.5 * float(os.environ.get("TESTE_TETO_TEMPO_S")
                               or (12 if os.environ.get("CI") else 2))
_RODADAS = 2
_TENTATIVAS = 3


def _tempo(texto: str) -> float:
    comeco = time.perf_counter()
    obs.redigir_dados_pessoais(texto)
    return time.perf_counter() - comeco


def _melhores_tempos(caso: str, menor: str, maior: str) -> tuple[float, float]:
    """O menor tempo de cada texto em ``_RODADAS`` medidas alternadas, sem o coletor de
    lixo (que roda quando quer e não é custo da redação)."""
    t_menor = t_maior = float("inf")
    ligado = gc.isenabled()
    gc.disable()
    try:
        for _ in range(_RODADAS):
            t_menor = min(t_menor, _tempo(menor))
            assert t_menor < _TETO_DO_MENOR_S, (
                f"{caso}: {t_menor:.2f}s em {len(menor)} caracteres")
            t_maior = min(t_maior, _tempo(maior))
    finally:
        if ligado:
            gc.enable()
    return t_menor, t_maior


@pytest.mark.parametrize("caso", sorted(_ADVERSARIOS))
def test_custo_linear_em_texto_adversarial(caso):
    gerar = _ADVERSARIOS[caso]
    menor, maior = gerar(_TAMANHO), gerar(4 * _TAMANHO)
    for _ in range(_TENTATIVAS):
        t_menor, t_maior = _melhores_tempos(caso, menor, maior)
        if t_maior <= max(_RAZAO_MAXIMA * t_menor, _PISO_S):
            return
    pytest.fail(f"{caso}: {t_menor:.4f}s em {len(menor)} e {t_maior:.4f}s em {len(maior)} "
                f"caracteres (razão {t_maior / max(t_menor, 1e-9):.1f}; linear daria ~4)")
