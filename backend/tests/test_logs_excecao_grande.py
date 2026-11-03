"""Exceção com texto ENORME: o custo e o tamanho da linha do log não crescem com o texto.

Revisão adversarial do candidato de 30/10 (achado A): a redação do texto de uma exceção
(``redigir_dados_pessoais``) custa ~0,4 s por MB, linear, e o formatador é síncrono — o
``logger.exception("erro_nao_tratado")`` do middleware formata dentro da corrotina, com o
event loop parado (~37 ms a cada 100 KB), e esse tempo entra no ``dur_ms`` do
``http_acesso``. O caso real: um IntegrityError de INSERT com milhares de linhas de VALUES,
com centenas de KB de "[SQL: …]". Agora, acima do limite, o texto de cada exceção sai só
com a cabeça e a cauda; o meio não é redigido nem escrito.

O corte não pode deixar um PEDAÇO de dado que escape das regras (meio nome, um token com
menos de 32 caracteres, um número com menos de 6 dígitos, o valor de uma chave que ficou
do outro lado): os testes põem cada dado fictício com o corte em cada posição dele.

Dados FICTÍCIOS (os nomes inventados dos outros testes de log, domínio reservado, CPF com
dígito verificador inválido). Sem rede. Tempo medido só pela ESCALA (1 MB × 4 MB).
"""
from __future__ import annotations

import gc
import io
import json
import logging
import re
import time
import traceback

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import observabilidade as obs

MEIO = "SENTINELA_DO_MEIO_7731"          # sem cara de dado: só some se não for escrita
NOME = "Zuleica Testelli"
EMAIL = "responsavel.ficticio@exemplo.test"
NOME_DA_CAUDA = "Quelia Martuscelli"
_RE_OMITIDOS = re.compile(r"\[\.\.\. (\d+) caracteres omitidos\]")
_RE_MARCAS = re.compile(r"<(?:redigido|nome|email|numero|token)>")


def _capturado(erro: BaseException):
    try:
        raise erro
    except BaseException as capturada:  # noqa: BLE001
        return type(capturada), capturada, capturada.__traceback__


def _registro(exc_info=None, msg="erro_nao_tratado", args=None):
    return logging.LogRecord("constela.http", logging.ERROR, __file__, 1, msg, args, exc_info)


def _excecao_do_log(exc_info) -> str:
    return json.loads(obs.FormatadorJson().format(_registro(exc_info)))["excecao"]


def _frames(tb) -> list[str]:
    return [f'File "{f.filename}", line {f.lineno}, in {f.name}'
            for f in traceback.extract_tb(tb)]


def _sql(n: int) -> str:
    """O texto de um erro do SQLAlchemy num INSERT de muitas linhas."""
    linha = "(%(aluno_id_m{i})s, %(escola_id_m{i})s, %(valor_m{i})s, %(periodo_m{i})s), "
    partes = ["(psycopg.errors.DeadlockDetected) deadlock detected\n"
              "[SQL: INSERT INTO notas (aluno_id, escola_id, valor, periodo) VALUES "]
    total, i = 0, 0
    while total < n:
        partes.append(linha.format(i=i))
        total += len(partes[-1])
        i += 1
    partes.append("]\n(Background on this error at: https://sqlalche.me/e/20/e3q8)")
    return "".join(partes)


def _capitalizado(n: int) -> str:
    base = "Linha Inválida Na Planilha Turma Tres Ano Coluna Nome Do Aluno Valor 123456 "
    return (base * (n // len(base) + 1))[:n]


def _sem_espaco(n: int) -> str:
    return ("a1b2c3d4/" * (n // 9 + 1))[:n]


def _linhas(n: int) -> str:
    base = "linha da planilha com a turma 3B e o aluno " + NOME + "\n"
    return base * (n // len(base)) + "última linha\n"     # o mesmo fim em todo tamanho


def _parenteses_e_aspas(n: int) -> str:
    """Muitos '("' que não abrem valor digitado, sem entrada do call log: a busca do
    começo da cauda varre o texto inteiro."""
    return '("x", ' * (n // 6) + "\nfim\n"


_GERADORES = {"sql": _sql, "capitalizado": _capitalizado, "sem-espaco": _sem_espaco,
              "linhas": _linhas, "parenteses-e-aspas": _parenteses_e_aspas}


# --- Custo e tamanho constantes -------------------------------------------------------

@pytest.mark.parametrize("caso", sorted(_GERADORES))
def test_redacao_ve_o_mesmo_texto_e_a_linha_tem_o_mesmo_tamanho_com_1_e_4_mb(
        caso, monkeypatch):
    """Sem relógio: a redação (a parte cara) recebe a MESMA quantidade de texto com 1 MB
    e com 4 MB, limitada pelas constantes do teto, e a linha tem o mesmo tamanho (só os
    dígitos da contagem do que foi omitido mudam)."""
    redigir = obs.redigir_dados_pessoais
    vistos: list[int] = []

    def _contando(texto):
        vistos.append(len(texto))
        return redigir(texto)

    monkeypatch.setattr(obs, "redigir_dados_pessoais", _contando)
    linhas, redigidos = [], []
    for tamanho in (1_000_000, 4_000_000):
        vistos.clear()
        linhas.append(obs.FormatadorJson().format(
            _registro(_capturado(RuntimeError(_GERADORES[caso](tamanho))))))
        redigidos.append(sum(vistos))
    teto = (obs._TENTATIVAS_DE_CORTE + 1) * (obs._CABECA + obs._MARGEM) + obs._CAUDA
    assert redigidos[0] == redigidos[1] <= teto, redigidos
    assert abs(len(linhas[0]) - len(linhas[1])) <= 2, [len(x) for x in linhas]
    for linha in linhas:
        assert len(linha) < 3 * obs._LIMITE_DO_TEXTO, len(linha)
        assert _RE_OMITIDOS.search(json.loads(linha)["excecao"])


# O tempo de formatar um texto 4x maior fica perto do de 1x: sobram as varreduras em C do
# texto inteiro (o str() da exceção, o DETAIL do banco, o começo da cauda), ~3 ms/MB nestes
# textos (o DETAIL chega a ~36 ms/MB num texto denso de rótulos "DETAIL:"/"Key (", como na
# base), contra ~10 ms constantes da redação da cabeça e da cauda — razão ~1,8 sem cobertura,
# menos com ela. Linear (435ce00) dá ~4. Como em test_logs_excecao_sem_dado_pessoal.py:
# vale o menor de várias medidas alternadas, sem o coletor de lixo, e uma rodada ruim é
# refeita. Sem teto de relógio: só a razão entre os dois tamanhos.
_RAZAO_MAXIMA = 3.0
_MEDIDAS = 3
_TENTATIVAS = 2


def _tempo_de_formatar(registro) -> float:
    comeco = time.perf_counter()
    obs.FormatadorJson().format(registro)
    return time.perf_counter() - comeco


@pytest.mark.parametrize("caso", ["sql", "capitalizado", "parenteses-e-aspas"])
def test_tempo_de_formatar_nao_cresce_com_o_texto_da_excecao(caso):
    menor = _registro(_capturado(RuntimeError(_GERADORES[caso](1_000_000))))
    maior = _registro(_capturado(RuntimeError(_GERADORES[caso](4_000_000))))
    for _ in range(_TENTATIVAS):
        t_menor = t_maior = float("inf")
        ligado = gc.isenabled()
        gc.disable()
        try:
            for _ in range(_MEDIDAS):
                t_menor = min(t_menor, _tempo_de_formatar(menor))
                t_maior = min(t_maior, _tempo_de_formatar(maior))
        finally:
            if ligado:
                gc.enable()
        if t_maior <= _RAZAO_MAXIMA * t_menor:
            return
    pytest.fail(f"{caso}: {t_menor * 1000:.1f} ms em 1 MB e {t_maior * 1000:.1f} ms em 4 MB "
                f"(razão {t_maior / t_menor:.1f}; constante daria ~1, linear ~4)")


# --- O que fica e o que sai -----------------------------------------------------------

def _texto_grande(miolo: int = 600_000) -> str:
    return (f"Linha 7 da planilha: aluno {NOME}, responsável {EMAIL}\n"
            + "wz " * (miolo // 6) + MEIO + " " + "wz " * (miolo // 6)
            + f"\núltima linha: conferir {NOME_DA_CAUDA} na turma")


def test_cadeia_enorme_mantem_tipo_e_frames_redige_cabeca_e_cauda_e_omite_o_meio():
    def _raiz():
        raise ValueError(_texto_grande())

    def _de_cima():
        try:
            _raiz()
        except ValueError as erro:
            raise RuntimeError(_texto_grande()) from erro

    try:
        _de_cima()
    except RuntimeError as erro:
        info = (type(erro), erro, erro.__traceback__)
    excecao = _excecao_do_log(info)

    assert MEIO not in excecao
    for parte in (*NOME.split(), EMAIL, *NOME_DA_CAUDA.split()):
        assert parte not in excecao, parte
    assert len(_RE_OMITIDOS.findall(excecao)) == 2              # uma por exceção da cadeia
    assert "\nValueError: Linha 7 da planilha: aluno <nome>, responsável <email>\n" in excecao
    assert "\nRuntimeError: Linha 7 da planilha: aluno <nome>, responsável <email>\n" in excecao
    assert excecao.count("\núltima linha: conferir <nome> na turma") == 2
    assert "The above exception was the direct cause of the following exception:" in excecao
    for frame in _frames(info[2]) + _frames(info[1].__cause__.__traceback__):
        assert frame in excecao, frame
    assert len(excecao) < 4 * obs._LIMITE_DO_TEXTO


def test_conta_do_omitido_e_exata_e_cabeca_e_cauda_sao_o_texto_original():
    """Sem nada a redigir, a cabeça é o começo do texto, a cauda é o fim, e o número do
    marcador é o que ficou entre as duas (o espaço do corte e a quebra antes da cauda
    viram a junção)."""
    texto = "wz " * 20_000 + "\n" + "linha zz\n" * 3000
    saida = obs._sem_dado_pessoal_com_teto(texto)
    [omitidos] = _RE_OMITIDOS.findall(saida)
    cabeca, _, cauda = _RE_OMITIDOS.split(saida)
    cabeca, cauda = cabeca[:-1], cauda[1:]                       # as junções
    assert texto.startswith(cabeca) and texto.endswith(cauda) and cauda
    assert int(omitidos) == len(texto) - len(cabeca) - len(cauda) - 2
    assert len(cabeca) <= obs._CABECA and len(cauda) <= obs._CAUDA


def test_excecao_enorme_como_argumento_e_no_extra_sai_cortada_e_redigida():
    erro = RuntimeError(_texto_grande())
    saida = io.StringIO()
    handler = logging.StreamHandler(saida)
    handler.setFormatter(obs.FormatadorJson())
    lg = logging.getLogger("constela.teste_excecao_grande")
    lg.addHandler(handler)
    lg.propagate = False
    try:
        lg.error("falhou: %s / %r", erro, erro, extra={"erro": erro})
    finally:
        lg.removeHandler(handler)
        lg.propagate = True
    linha = saida.getvalue()
    assert len(linha) < 6 * obs._LIMITE_DO_TEXTO
    assert MEIO not in linha
    for parte in (*NOME.split(), EMAIL, *NOME_DA_CAUDA.split()):
        assert parte not in linha, parte
    evento = json.loads(linha)
    assert evento["message"].startswith("falhou: Linha 7 da planilha: aluno <nome>, ")
    assert len(_RE_OMITIDOS.findall(evento["message"])) == 2      # o %s e o %r
    assert _RE_OMITIDOS.search(evento["erro"])
    assert " / RuntimeError('Linha 7 da planilha: aluno <nome>" in evento["message"]


def test_erro_nao_tratado_de_uma_rota_com_texto_enorme_sai_curto(caplog):
    app = FastAPI()

    @app.get("/explode")
    def explode():
        raise RuntimeError(_sql(2_000_000))

    app.add_middleware(obs.ObservabilidadeMiddleware, settings=None)
    with caplog.at_level(logging.INFO, logger="constela.http"):
        with TestClient(app, raise_server_exceptions=False) as cliente:
            resposta = cliente.get("/explode")
    assert resposta.status_code == 500
    [erro] = [r for r in caplog.records if r.getMessage() == "erro_nao_tratado"]
    linha = obs.FormatadorJson().format(erro)
    assert len(linha) < 2 * obs._LIMITE_DO_TEXTO, len(linha)
    excecao = json.loads(linha)["excecao"]
    assert ("\nRuntimeError: (psycopg.errors.DeadlockDetected) deadlock detected\n"
            "[SQL: INSERT INTO notas (aluno_id, escola_id, valor, periodo) VALUES ") in excecao
    assert _RE_OMITIDOS.search(excecao)
    assert excecao.endswith("\n(Background on this error at: https://sqlalche.me/e/20/e3q8)")
    assert f"line {explode.__code__.co_firstlineno + 2}, in explode" in excecao
    [acesso] = [r for r in caplog.records if r.getMessage() == "http_acesso"]
    assert acesso.status == 500


def test_syntaxerror_com_linha_enorme_mantem_arquivo_linha_e_tipo():
    """No SyntaxError, a linha de código mostrada (o texto avaliado) é cortada como
    qualquer texto; a linha 'File "…", line n' e o tipo ficam."""
    fonte = "x = (" + "a + " * 10_000 + NOME
    with pytest.raises(SyntaxError) as pego:
        compile(fonte, "<texto avaliado>", "exec")
    excecao = _excecao_do_log((SyntaxError, pego.value, pego.value.__traceback__))
    assert '  File "<texto avaliado>", line 1\n' in excecao
    assert _RE_OMITIDOS.search(excecao)
    assert excecao.endswith("SyntaxError: '(' was never closed")
    assert "Zuleica" not in excecao and "Testelli" not in excecao
    assert len(excecao) < 2 * obs._LIMITE_DO_TEXTO


# --- Dado na fronteira do corte ---------------------------------------------------------
# (o que vem antes, o dado): na redação do texto inteiro o dado sai todo (o controle de
# cada caso confere, no mesmo texto); o teste põe o corte da cabeça (ou o começo da
# janela da cauda) em CADA posição dele, e nenhum pedaço de 3+ letras ou dígitos dele
# pode sobrar.
_NA_FRONTEIRA = {
    "nome": ("aluno ", NOME),
    "nome-caixa-alta": ("aluno ", "QUELIA MARTUSCELLI"),
    "nome-com-particula": ("aluno ", "Zuleica dos Santos Testelli"),
    "nome-entre-parenteses": ("aluno (", NOME + ")"),
    "nome-depois-da-chave": ("nome: ", "zuleica testelli"),
    "email": ("contato ", EMAIL),
    "cpf": ("CPF ", "123.456.789-00"),
    "ra": ("RA ", "123456789"),
    "token": ("chave ", "f3a9c1d7e5b2a8c4d6e0f1a3b5c7d9e2"),
    "jwt": ("auth ", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI0MiJ9.c2lnbmF0dXJh"),
    "chave-secreta": ("senha=", "Valor-Ficticio-9"),
    "chave-com-espaco": ("senha: ", "Valor-Ficticio-9"),
    "credencial-entre-aspas": ("senha '", "abc d3f ghi'"),
    "bearer": ("Authorization: Bearer ", "abcDEF123456ghi"),
    "url": ("em https://plataforma.exemplo/api?token=", "TOKSECRETO4821x&pagina=2"),
    "previa": ('resolved to <input value="', 'Zuleica Testelli segredo"/>'),
    "valor-digitado": ('fill("', 'Zuleica Testelli segredo1")'),
    "parameters": ("[parameters: ('", "Zuleica Testelli', '123456789')]"),
}


def _pedacos(valor: str) -> set[str]:
    """Os pedaços do dado com 3+ letras ou dígitos."""
    return {valor[i:j] for i in range(len(valor)) for j in range(i + 3, len(valor) + 1)
            if sum(map(str.isalnum, valor[i:j])) >= 3}


def _sem_pedaco(saida: str, valor: str, contexto: str) -> None:
    saida = _RE_MARCAS.sub("", _RE_OMITIDOS.sub("", saida))
    for pedaco in sorted(_pedacos(valor), key=len):
        assert pedaco not in saida, f"{contexto}: pedaço {pedaco!r} no log"


@pytest.mark.parametrize("caso", sorted(_NA_FRONTEIRA))
def test_dado_na_fronteira_da_cabeca_nao_deixa_pedaco(caso):
    prefixo, valor = _NA_FRONTEIRA[caso]
    item = prefixo + valor
    for desvio in range(-1, len(item) + 2):
        inicio = obs._CABECA - desvio                     # o _CABECA cai em item[desvio]
        antes = ("wz " * (inicio // 3 + 1))[:inicio - 1] + " "
        texto = antes + item + " wz" * 4000 + "\nfim\n"
        if desvio == 0:                       # controle: o texto inteiro redige o dado
            _sem_pedaco(obs.redigir_dados_pessoais(texto), valor, f"{caso} (controle)")
        saida = obs._sem_dado_pessoal_com_teto(texto)
        assert _RE_OMITIDOS.search(saida), (caso, desvio)
        _sem_pedaco(saida, valor, f"{caso} (corte em {desvio})")


@pytest.mark.parametrize("caso", sorted(_NA_FRONTEIRA))
def test_dado_na_fronteira_da_cauda_nao_deixa_pedaco(caso):
    prefixo, valor = _NA_FRONTEIRA[caso]
    item = prefixo + valor
    final = f" wz wz\núltima: {NOME_DA_CAUDA} na turma\n"
    for desvio in range(-1, len(item) + 2):
        # a janela da cauda (as últimas _CAUDA letras) começa em item[desvio]
        depois = obs._CAUDA - (len(item) - desvio) - len(final)
        texto = "wz " * 8000 + item + (" wz" * (depois // 3 + 1))[:depois] + final
        if desvio >= 0:
            assert texto[len(texto) - obs._CAUDA:].startswith(item[desvio:])
        if desvio == 0:                       # controle: o texto inteiro redige o dado
            _sem_pedaco(obs.redigir_dados_pessoais(texto), valor, f"{caso} (controle)")
        saida = obs._sem_dado_pessoal_com_teto(texto)
        assert _RE_OMITIDOS.search(saida), (caso, desvio)
        _sem_pedaco(saida, valor, f"{caso} (janela em {desvio})")
        if caso != "valor-digitado":              # este vai até o fim do texto: sem cauda
            assert saida.endswith("\núltima: <nome> na turma\n"), (caso, desvio)


def test_valor_digitado_que_atravessa_linhas_nao_entra_pela_cauda():
    """O único valor que atravessa linhas: o que o Playwright digitou, até a próxima entrada
    do call log. Se a janela da cauda cai dentro dele, a cauda começa na entrada seguinte."""
    segredo = "Valor-Secreto-77"
    valor = "linha zz\n" * 600 + segredo + "\n" + "linha zz\n" * 3
    texto = ("wz " * 6000 + "\nTimeout 30000ms exceeded.\nCall log:\n"
             "  - waiting for locator(\"#senha\")\n"
             '  - fill("' + valor + '")' + "\n  - waiting for element to be visible\n")
    assert len(texto) - obs._CAUDA < texto.index(segredo)       # a janela cai no valor
    saida = obs._sem_dado_pessoal_com_teto(texto)
    assert _RE_OMITIDOS.search(saida)
    _sem_pedaco(saida, segredo, "valor digitado")
    assert "linha zz" not in saida
    assert saida.endswith("\n  - waiting for element to be visible\n")


def test_cauda_fica_com_parentese_e_aspas_que_nao_abrem_valor_digitado():
    """Um '("' que não é ``fill("``/``type("``… (um identificador entre aspas no SQL) ou um
    valor digitado já fechado por uma entrada do call log não tiram a cauda."""
    sql = ('[SQL: INSERT INTO alunos ("user", "order") VALUES ' + "(%s, %s), " * 3000
           + "]\n(Background on this error at: https://sqlalche.me/e/20/gkpj)\n")
    assert obs._sem_dado_pessoal_com_teto(sql).endswith(
        "\n(Background on this error at: https://sqlalche.me/e/20/gkpj)\n")
    log = ('Call log:\n  - fill("' + "x" * 20_000 + '")\n  - waiting for element\n'
           + "linha zz\n" * 1000)
    saida = obs._sem_dado_pessoal_com_teto(log)
    assert "caracteres omitidos]\nlinha zz\n" in saida and saida.endswith("linha zz\n" * 400)


# --- Até o limite, como antes ------------------------------------------------------------

def test_no_limite_sai_inteiro_como_antes_e_um_caractere_acima_sai_cortado():
    base = f"aluno {NOME}, responsável {EMAIL}, CPF 123.456.789-00\n"
    no_limite = (base * (obs._LIMITE_DO_TEXTO // len(base) + 1))[:obs._LIMITE_DO_TEXTO]
    assert obs._sem_dado_pessoal_com_teto(no_limite) == obs.redigir_dados_pessoais(no_limite)
    assert not _RE_OMITIDOS.search(obs._sem_dado_pessoal_com_teto(no_limite))
    acima = no_limite + "x"
    saida = obs._sem_dado_pessoal_com_teto(acima)
    assert _RE_OMITIDOS.search(saida)
    for parte in (*NOME.split(), EMAIL, "123.456"):
        assert parte not in saida, parte


@pytest.mark.parametrize("msg", [
    f"aluno {NOME} ({EMAIL}) sem turma",
    "x" * 15_000 + f" {NOME}",
    "deadlock detected\n[SQL: INSERT INTO notas (aluno_id) VALUES (%(aluno_id)s)]",
], ids=["nome-e-email", "quase-no-limite", "sql"])
def test_excecao_normal_sai_byte_a_byte_como_antes_e_a_enorme_sai_cortada(msg):
    """Até o limite, o texto que o formatador escrevia em 435ce00 — o traceback do Python
    com o que vem depois do tipo redigido por ``redigir_dados_pessoais`` (esta parte é uma
    guarda de não-regressão: vale antes e depois do teto). A mesma mensagem com texto
    além do limite sai cortada."""
    info = _capturado(RuntimeError(msg))
    *pilha, linha_da_excecao = traceback.format_exception(*info)
    assert linha_da_excecao == f"RuntimeError: {msg}\n"
    esperado = ("".join(pilha) + "RuntimeError"
                + obs.redigir_dados_pessoais(f": {msg}\n")).rstrip("\n")
    assert _excecao_do_log(info) == esperado
    enorme = _excecao_do_log(_capturado(RuntimeError(msg + " wz" * obs._LIMITE_DO_TEXTO)))
    assert _RE_OMITIDOS.search(enorme)


# --- Orçamento por traceback (revisão de 31/10) ---------------------------------------

def _cadeia_enorme(quantas: int, tamanho: int = 40_000) -> BaseException:
    """``quantas`` exceções encadeadas por ``__cause__``, cada uma com texto acima do
    limite e um dado fictício no começo e na última linha (a cauda)."""
    erros = [RuntimeError(f"erro {i:02d}: aluno {NOME}, responsável {EMAIL} "
                          + "wz " * (tamanho // 3)
                          + f"\núltima linha: conferir {NOME_DA_CAUDA}")
             for i in range(quantas)]
    for de_cima, causa in zip(erros[1:], erros):
        de_cima.__cause__ = causa
    return erros[-1]


def test_cadeia_de_muitas_excecoes_enormes_ve_o_mesmo_texto_com_16_e_64(monkeypatch):
    """Sem relógio: o teto vale por exceção, e uma cadeia de 64 enormes pagava 64 vezes.
    Com 16 e com 64, a redação vê a MESMA quantidade de texto, até o orçamento do
    traceback (mais o custo de uma exceção); a de cima sai redigida, as mais antigas só
    com o tipo, e nenhum dado fictício sai cru."""
    redigir = obs.redigir_dados_pessoais
    vistos: list[int] = []

    def _contando(texto):
        vistos.append(len(texto))
        return redigir(texto)

    monkeypatch.setattr(obs, "redigir_dados_pessoais", _contando)
    redigidos, textos = [], []
    for quantas in (16, 64):
        erro = _cadeia_enorme(quantas)
        vistos.clear()
        textos.append(_excecao_do_log((type(erro), erro, None)))
        redigidos.append(sum(vistos))
    for texto in textos:
        for parte in (*NOME.split(), EMAIL, *NOME_DA_CAUDA.split()):
            assert texto.find(parte) == -1, parte
    assert redigidos[0] == redigidos[1], redigidos
    teto = (obs._TENTATIVAS_DE_CORTE + 1) * (obs._CABECA + obs._MARGEM) + obs._CAUDA
    assert redigidos[1] <= 3 * teto, redigidos
    for quantas, texto in zip((16, 64), textos):
        assert texto.count("RuntimeError: ") == quantas          # o tipo de cada uma fica
        assert texto.count("The above exception was the direct cause") == quantas - 1
        de_cima = texto.rsplit("\nRuntimeError: ", 1)[1]
        assert de_cima.startswith(f"erro {quantas - 1:02d}: aluno <nome>, responsável <email>")
        assert de_cima.endswith("\núltima linha: conferir <nome>")
        assert _RE_OMITIDOS.search(de_cima)
        assert texto.startswith(f"RuntimeError: {obs._TEXTO_FORA_DO_ORCAMENTO}\n")


def test_grupo_de_excecoes_enormes_tambem_tem_orcamento(monkeypatch):
    """Num grupo, os membros vêm depois da cadeia de cima; os que passam do orçamento saem
    só com o tipo, e os marcadores de membro ficam."""
    vistos: list[int] = []
    redigir = obs.redigir_dados_pessoais
    monkeypatch.setattr(obs, "redigir_dados_pessoais",
                        lambda texto: vistos.append(len(texto)) or redigir(texto))
    grupo = ExceptionGroup("lote", [_cadeia_enorme(1) for _ in range(15)])
    texto = obs.traceback_redigido(grupo)
    teto = (obs._TENTATIVAS_DE_CORTE + 1) * (obs._CABECA + obs._MARGEM) + obs._CAUDA
    assert sum(vistos) <= 3 * teto, sum(vistos)
    for parte in (*NOME.split(), EMAIL, *NOME_DA_CAUDA.split()):
        assert texto.find(parte) == -1, parte
    assert texto.startswith("ExceptionGroup: lote (15 sub-exceptions)\n")
    assert texto.count("+---------------- ") == 15
    assert "| RuntimeError: erro 00: aluno <nome>" in texto
    assert f"| RuntimeError: {obs._TEXTO_FORA_DO_ORCAMENTO}" in texto
