"""Sentry com a MESMA redação de dado pessoal do log (revisão de 30/10, achado B).

``higienizar_evento_sentry`` só tirava o DETAIL do banco. Com ``SENTRY_DSN`` ligado, a
LoggingIntegration do sentry-sdk 2.x monta o evento do registro CRU — ``logentry`` com a
mensagem e os argumentos (a exceção vira o repr dela), breadcrumbs com o ``getMessage()``
e o ``extra``, o ``value`` de cada exceção com o texto dela —, e o nome, o documento e o
e-mail iam inteiros para o Sentry (processador externo). Agora todo texto livre do evento
passa por ``redigir_dados_pessoais`` (com o teto do texto de uma exceção); o fim de um
texto que o SDK cortou recua até um ponto em que nenhum dado foi partido; a query de uma
chamada HTTP de saída sai inteira.

O hook roda síncrono, com o event loop parado (revisão de 31/10): a redação de um evento
tem orçamento (``_TETO_DA_REDACAO`` caracteres, contados com os recuos), a description de
um span (que o SDK não corta) é cortada como os outros textos e um texto repetido sai do
que já foi redigido. O que passa do orçamento sai como ``<omitido>``, nunca cru.

Os eventos são os do SDK de verdade (transporte em memória: nada vai para a rede) ou
montados como ele os monta. Dados FICTÍCIOS, definidos só aqui em cima: o SDK manda as
linhas de código em volta de cada frame, e as funções que levantam ficam longe destas.
"""
from __future__ import annotations

import logging
import re

import pytest

from app.core import observabilidade as obs

NOME = "Zuleica Testelli"
NOME_2 = "Quelia Martuscelli"
CPF = "123.456.789-00"
RA = "123456789"
EMAIL = "responsavel.ficticio@exemplo.test"
TOKEN = "f3a9c1d7e5b2a8c4d6e0f1a3b5c7d9e2"
_PARTES = (*NOME.split(), *NOME_2.split(), CPF, RA, EMAIL, TOKEN)
_MENSAGEM = f"aluno {NOME}, RA {RA}, responsável {EMAIL}, chave {TOKEN}"
_REFERER = "https://app.exemplo.test/publico/painelsecreto9?busca=" + NOME.split()[0]
_RE_MARCAS = re.compile(r"<(?:redigido|nome|email|numero|token)>")
_LIMITE_DO_SDK = 1024                    # max_value_length padrão do sentry-sdk 2.x
_VISIVEL = _LIMITE_DO_SDK - 3            # o que sobra antes do "..." do corte


def _sem_parte(texto: str, contexto: str = "") -> None:
    # Sem "assert parte not in texto": na falha, o pytest montaria um diff do texto
    # inteiro (dezenas de MB numa transação de 1000 spans) e não terminaria.
    for parte in _PARTES:
        onde = texto.find(parte)
        assert onde == -1, f"{contexto}: {parte!r} em …{texto[max(onde - 60, 0):onde + 60]}…"


def _pedacos(valor: str) -> set[str]:
    return {valor[i:j] for i in range(len(valor)) for j in range(i + 3, len(valor) + 1)
            if sum(map(str.isalnum, valor[i:j])) >= 3}


def _meta_cortado(tamanho: int) -> dict:
    return {"": {"len": tamanho, "rem": [["!limit", "x", _VISIVEL, _LIMITE_DO_SDK]]}}


# --- SDK de verdade -----------------------------------------------------------------


@pytest.fixture
def sentry_real(monkeypatch, request):
    """O ``configurar_sentry`` de verdade, só com o ENVIO trocado por um transporte em
    memória (nada vai para a rede); a troca do ``get_error_message`` é desfeita no fim.
    Parametrizado (``indirect``), o valor é a taxa de amostragem do tracing."""
    sentry_sdk = pytest.importorskip("sentry_sdk")
    import sentry_sdk.utils as utilitarios
    from sentry_sdk.transport import Transport

    from app.core.config import settings
    dsn = "https://chaveficticia@sentry.exemplo.test/1"

    class _Transporte(Transport):
        def __init__(self):
            super().__init__({"dsn": dsn})
            self.envelopes = []

        def capture_envelope(self, envelope):
            self.envelopes.append(envelope)

    transporte = _Transporte()
    init_real = sentry_sdk.init

    class _SentryComTransporte:
        def __getattr__(self, nome):
            return getattr(sentry_sdk, nome)

        def init(self, **opcoes):
            return init_real(transport=transporte, **opcoes)

    monkeypatch.setattr(utilitarios, "get_error_message", utilitarios.get_error_message)
    monkeypatch.setattr(obs, "_sentry", _SentryComTransporte())
    monkeypatch.setattr(obs, "_sentry_ativo", False)
    monkeypatch.setattr(settings, "SENTRY_DSN", dsn)
    if getattr(request, "param", None) is not None:
        monkeypatch.setattr(settings, "SENTRY_TRACES_SAMPLE_RATE", request.param)
    obs.configurar_sentry(settings)
    try:
        yield transporte
    finally:
        sentry_sdk.get_client().close()
        sentry_sdk.get_global_scope().set_client(None)


def _corpo(transporte) -> str:
    return b"".join(envelope.serialize() for envelope in transporte.envelopes).decode(
        "utf-8", "replace")


def _eventos(transporte) -> list[dict]:
    return [e for e in (env.get_event() for env in transporte.envelopes) if e]


def _levantar(mensagem: str) -> None:
    raise RuntimeError(mensagem)


@pytest.fixture
def logger_de_teste():
    lg = logging.getLogger("constela.teste_sentry_pii")
    lg.setLevel(logging.INFO)
    try:
        yield lg
    finally:
        lg.setLevel(logging.NOTSET)


def test_log_de_excecao_real_chega_ao_sentry_sem_dado_pessoal(sentry_real, logger_de_teste):
    import sentry_sdk

    logger_de_teste.info("importando aluno %s (%s)", NOME, EMAIL,
                         extra={"responsavel": NOME_2, "documento": CPF})
    try:
        _levantar(_MENSAGEM)
    except RuntimeError as erro:
        logger_de_teste.exception("falhou: %s", erro,
                                  extra={"aluno": NOME, "lista": [NOME_2, {"doc": CPF}]})
    sentry_sdk.flush()

    _sem_parte(_corpo(sentry_real), "envelope")
    [evento] = [e for e in _eventos(sentry_real) if e.get("logger") == logger_de_teste.name]
    [excecao] = evento["exception"]["values"]
    assert excecao["type"] == "RuntimeError"
    assert excecao["value"] == "aluno <nome>, RA <numero>, responsável <email>, chave <token>"
    assert excecao["stacktrace"]["frames"][-1]["function"] == "_levantar"
    assert evento["logentry"]["message"] == "falhou: %s"
    assert evento["logentry"]["params"] == [
        "RuntimeError('aluno <nome>, RA <numero>, responsável <email>, chave <token>')"]
    assert evento["extra"]["aluno"] == "<nome>"
    assert evento["extra"]["lista"] == ["<nome>", {"doc": "<numero>"}]
    [migalha] = [b for b in evento["breadcrumbs"]["values"]
                 if b.get("category") == logger_de_teste.name]
    assert migalha["message"] == "importando aluno <nome> (<email>)"
    assert migalha["data"] == {"responsavel": "<nome>", "documento": "<numero>"}
    assert migalha["level"] == "info" and migalha["type"] == "log" and migalha["timestamp"]


def test_valor_cortado_pelo_sdk_real_nao_deixa_o_primeiro_nome(sentry_real):
    """O SDK corta o texto em 1021 caracteres + "...": cortado logo depois da inicial do
    sobrenome, a inicial sozinha não forma nome, e o primeiro nome ia inteiro. O fim
    recua para antes dele."""
    import sentry_sdk

    antes = ("wz " * 400)[:_VISIVEL - len(NOME.split()[0]) - 3] + " "
    try:
        _levantar(antes + NOME + " wz" * 100)
    except RuntimeError as erro:
        sentry_sdk.capture_exception(erro)
    sentry_sdk.flush()
    _sem_parte(_corpo(sentry_real), "envelope")
    [evento] = _eventos(sentry_real)
    valor = evento["exception"]["values"][0]["value"]
    assert valor.endswith("...") and valor.startswith("wz wz")
    assert len(valor) <= _VISIVEL - obs._MARGEM + 3


# --- Eventos montados como o SDK os monta ------------------------------------------


def test_breadcrumbs_logentry_message_extra_e_cabecalhos_saem_sem_dado_pessoal():
    evento = {
        "level": "error", "timestamp": "2026-10-30T12:00:00.123456Z",
        "tags": {"request_id": "a1b2c3"}, "logger": "constela.sync",
        "message": f"aviso sobre {NOME}",
        "logentry": {"message": "aluno %s", "params": [NOME, 42, {"doc": CPF}],
                     "formatted": f"aluno {NOME}"},
        "breadcrumbs": {"values": [
            {"type": "log", "category": "constela.sync", "level": "info",
             "timestamp": "2026-10-30T11:59:59.000001Z", "message": f"lendo {NOME}",
             "data": {"aluno": NOME, "ids": [1, 2], "aninhado": {"email": EMAIL}}},
            {"type": "http", "category": "httplib",
             "data": {"url": "https://nominatim.exemplo/search", "http.method": "GET",
                      "http.query": "q=Rua+" + NOME.replace(" ", "+") + "&format=json",
                      "http.fragment": "ancora", "http.response.status_code": 200}},
            {"category": "query",
             "message": "SELECT alunos.nome FROM alunos WHERE alunos.nome = %(nome_1)s"},
            # sem o "!limit" no _meta, um texto que termina em "..." é só um texto
            {"category": "constela.sync", "message": "carregando a turma 3B..."},
        ]},
        "extra": {"responsavel": NOME_2, "tentativas": 3},
        "request": {"url": "https://api.exemplo/api/v1/alunos", "method": "GET",
                    "headers": {"Referer": _REFERER, "User-Agent": "pytest"}},
    }
    saida = obs.higienizar_evento_sentry(evento, None)
    _sem_parte(str(saida), "evento")
    assert "painelsecreto9" not in str(saida)
    assert saida["message"] == "aviso sobre <nome>"
    assert saida["logentry"] == {"message": "aluno %s", "params": ["<nome>", 42,
                                                                   {"doc": "<numero>"}],
                                 "formatted": "aluno <nome>"}
    log, http, sql, reticencias = saida["breadcrumbs"]["values"]
    assert reticencias["message"] == "carregando a turma 3B..."
    assert log["message"] == "lendo <nome>"
    assert log["data"] == {"aluno": "<nome>", "ids": [1, 2], "aninhado": {"email": "<email>"}}
    assert log["timestamp"] == "2026-10-30T11:59:59.000001Z"
    assert http["data"] == {"url": "https://nominatim.exemplo/search", "http.method": "GET",
                            "http.query": "<redigido>", "http.fragment": "<redigido>",
                            "http.response.status_code": 200}
    assert sql["message"] == evento["breadcrumbs"]["values"][2]["message"]
    assert saida["extra"] == {"responsavel": "<nome>", "tentativas": 3}
    assert saida["request"]["headers"] == {
        "Referer": "https://app.exemplo.test/publico/<token>?<redigido>",
        "User-Agent": "pytest"}
    for campo in ("level", "timestamp", "tags", "logger"):
        assert saida[campo] == evento[campo], campo
    assert NOME in evento["message"]                    # o evento recebido fica intacto


def test_spans_da_transacao_saem_sem_a_query_e_sem_dado_pessoal():
    evento = {"type": "transaction", "transaction": "/api/v1/alunos", "spans": [
        {"op": "http.client", "description": "GET https://nominatim.exemplo/search",
         "data": {"http.query": "q=" + NOME.replace(" ", "+"), "http.method": "GET"}},
        {"op": "db", "description": "SELECT 1 /* " + NOME + " */", "data": {}},
    ]}
    saida = obs.higienizar_evento_sentry(evento, None)
    _sem_parte(str(saida), "transação")
    http, db = saida["spans"]
    assert http["data"] == {"http.query": "<redigido>", "http.method": "GET"}
    assert http["description"] == "GET https://nominatim.exemplo/search"
    assert db["description"] == "SELECT 1 /* <nome> */"
    assert saida["transaction"] == "/api/v1/alunos"


@pytest.mark.parametrize("campo", ["excecao", "breadcrumb", "param"])
def test_texto_cortado_pelo_sdk_nao_deixa_pedaco_de_dado_no_fim(campo):
    """O ``_meta`` diz onde o SDK cortou (``"!limit"``): com o corte em CADA posição de um
    dado, nenhum pedaço dele sobra no fim (a redação do pedaço sozinho não o reconhece:
    "Zuleica T", "123.45", um token de 20 caracteres)."""
    for dado in (NOME, CPF, TOKEN, EMAIL, "senha 'abc d3f ghi'"):
        for desvio in range(len(dado) + 2):
            antes = ("wz " * 400)[:_VISIVEL - desvio - 1] + " "
            bruto = antes + dado + " wz" * 100
            cortado = bruto[:_VISIVEL] + "..."
            meta = _meta_cortado(len(bruto))
            if campo == "excecao":
                evento = {"exception": {"values": [{"type": "RuntimeError", "value": cortado}]},
                          "_meta": {"exception": {"values": {"0": {"value": meta}}}}}
            elif campo == "breadcrumb":
                evento = {"breadcrumbs": {"values": [{"message": "x"}, {"message": cortado}]},
                          "_meta": {"breadcrumbs": {"values": {"1": {"message": meta}}}}}
            else:
                evento = {"logentry": {"message": "%s", "params": [cortado]},
                          "_meta": {"logentry": {"params": {"0": meta}}}}
            saida = obs.higienizar_evento_sentry(evento, None)
            texto = _RE_MARCAS.sub("", str(saida))
            for pedaco in _pedacos(dado.removeprefix("senha ")):
                assert pedaco not in texto, f"{campo}, {dado!r} cortado em {desvio}: {pedaco!r}"
            assert "wz wz" in texto and "..." in texto


def test_tipo_inesperado_nao_derruba_o_envio():
    evento = {
        "exception": {"values": [{"type": "X", "value": 123}, "solto", None,
                                 {"type": "Y", "value": NOME}]},
        "logentry": "texto solto de " + NOME,
        "message": {"message": NOME, "params": (NOME_2, None, 1.5)},
        "breadcrumbs": [{"message": None, "data": None}, "solto",
                        {"data": {1: NOME, (2, 3): [NOME_2], "http.query": None}}],
        "spans": {"values": "não é lista"},
        "extra": None,
        "request": {"headers": ["Referer", _REFERER]},
        "_meta": "lixo",
    }
    saida = obs.higienizar_evento_sentry(evento, None)
    assert isinstance(saida, dict)
    _sem_parte(str(saida), "tipos inesperados")
    assert saida["exception"]["values"][0] == {"type": "X", "value": "123"}   # vira texto
    assert saida["exception"]["values"][1:3] == ["solto", None]
    assert saida["message"]["params"] == ("<nome>", None, 1.5)
    assert saida["breadcrumbs"][2]["data"][1] == "<nome>"
    assert saida["breadcrumbs"][2]["data"]["http.query"] is None
    assert saida["spans"] == {"values": "não é lista"} and saida["extra"] is None


def test_falha_na_redacao_descarta_o_evento_em_vez_de_mandar_cru(monkeypatch):
    def _quebrada(texto):
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(obs, "redigir_dados_pessoais", _quebrada)
    assert obs.higienizar_evento_sentry({"logentry": {"message": NOME}}, None) is None


# --- Orçamento da redação por evento (revisão de 31/10) -----------------------------
# Sem relógio: a redação (a parte cara) vê a MESMA quantidade de texto com 100 e com 1000
# spans distintos (e com 10 e com 100 breadcrumbs longos), até ``_TETO_DA_REDACAO``, e
# nenhum dado fictício sai cru.


def _teto_da_redacao() -> int:
    """O máximo que a redação vê no texto de UMA exceção no log: o orçamento de um evento.
    Montado das constantes do teto (e conferido contra ``obs._TETO_DA_REDACAO`` abaixo)."""
    return (obs._TENTATIVAS_DE_CORTE + 1) * (obs._CABECA + obs._MARGEM) + obs._CAUDA


def test_orcamento_do_evento_e_o_teto_de_uma_excecao_no_log():
    assert obs._TETO_DA_REDACAO == _teto_da_redacao() == 66_176


def _contando_a_redacao(monkeypatch) -> list[int]:
    redigir = obs.redigir_dados_pessoais
    vistos: list[int] = []

    def _contando(texto):
        vistos.append(len(texto))
        return redigir(texto)

    monkeypatch.setattr(obs, "redigir_dados_pessoais", _contando)
    return vistos


def _consulta(i: int, tamanho: int) -> str:
    """Uma consulta DIFERENTE para cada ``i`` (um texto repetido sai do que já foi
    redigido no evento), com os dados fictícios em literais no começo."""
    cabeca = (f"SELECT /* q{i:05d} */ alunos.id FROM alunos WHERE alunos.nome = '{NOME}' "
              f"AND alunos.ra = '{RA}' AND alunos.email = '{EMAIL}' AND alunos.coluna IN (")
    return (cabeca + "alunos.coluna_a, " * (tamanho // 17 + 1))[:tamanho]


def _texto_longo(i: int, rotulo: str) -> str:
    return f"{rotulo} {i:05d}: aluno {NOME}, RA {RA}, responsável {EMAIL}; " + "wz " * 400


def _cortado(texto: str) -> str:
    return texto[:_VISIVEL] + "..."


@pytest.mark.parametrize("tamanho", [700, 1_500, 52_000])
def test_redacao_da_transacao_ve_o_mesmo_texto_com_100_e_1000_spans_distintos(
        tamanho, monkeypatch):
    vistos = _contando_a_redacao(monkeypatch)
    redigidos, saidas = [], []
    for quantos in (100, 1000):
        evento = {"type": "transaction", "transaction": "/api/v1/alunos", "spans": [
            {"op": "db", "description": _consulta(i, tamanho), "start_timestamp": 1.0 + i,
             "data": {"db.system": "postgresql", "aluno": NOME}} for i in range(quantos)]}
        vistos.clear()
        saidas.append(obs.higienizar_evento_sentry(evento, None))
        redigidos.append(sum(vistos))
    for saida in saidas:
        _sem_parte(str(saida), f"spans de {tamanho} caracteres")
    assert redigidos[0] == redigidos[1], redigidos
    assert redigidos[1] <= _teto_da_redacao(), redigidos
    spans = saidas[1]["spans"]
    assert len(spans) == 1000 and all(s["op"] == "db" for s in spans)
    assert [s["start_timestamp"] for s in spans] == [1.0 + i for i in range(1000)]
    primeiro = spans[0]["description"]
    assert primeiro.startswith("SELECT /* q00000 */ alunos.id FROM alunos WHERE ")
    assert _RE_MARCAS.search(primeiro) and len(primeiro) <= obs._LIMITE_DO_SDK
    assert spans[-1]["description"] == obs._FORA_DO_ORCAMENTO       # nunca cru
    for span in (spans[0], spans[-1]):                  # texto repetido: do que já foi feito
        assert span["data"] == {"db.system": "postgresql", "aluno": "<nome>"}


def test_redacao_do_erro_ve_o_mesmo_texto_com_10_e_100_breadcrumbs_longos(monkeypatch):
    """Cada texto longo vem cortado pelo SDK (com o recuo do corte, de 2 a 5 redações).
    O que vem antes dos breadcrumbs (exceção, logentry, cabeçalhos) cabe sempre; os
    breadcrumbs vão do mais recente ao mais antigo, e os que não cabem saem omitidos."""
    vistos = _contando_a_redacao(monkeypatch)
    campos = ("obs", "planilha", "turma", "linha")
    redigidos, saidas = [], []
    for quantos in (10, 100):
        migalhas, meta_migalhas = [], {}
        for i in range(quantos):
            migalhas.append({
                "type": "log", "category": "constela.sync", "level": "info",
                "message": _cortado(_texto_longo(i, "lendo")),
                "data": {"aluno": NOME, **{c: _cortado(_texto_longo(i, c)) for c in campos}}})
            meta_migalhas[str(i)] = {"message": _meta_cortado(2000),
                                     "data": {c: _meta_cortado(2000) for c in campos}}
        evento = {
            "level": "error", "logger": "constela.sync",
            "exception": {"values": [
                {"type": "RuntimeError", "value": _cortado(_texto_longo(0, "falha"))}]},
            "logentry": {"message": "falhou: %s", "params": [_MENSAGEM]},
            "request": {"url": "https://api.exemplo/api/v1/alunos",
                        "headers": {"Referer": _REFERER, "User-Agent": "pytest"}},
            "breadcrumbs": {"values": migalhas},
            "_meta": {"exception": {"values": {"0": {"value": _meta_cortado(2000)}}},
                      "breadcrumbs": {"values": meta_migalhas}},
        }
        vistos.clear()
        saidas.append(obs.higienizar_evento_sentry(evento, None))
        redigidos.append(sum(vistos))
    for saida in saidas:
        _sem_parte(str(saida), "erro com breadcrumbs")
        assert str(saida).find("painelsecreto9") == -1
    assert redigidos[0] == redigidos[1], redigidos
    assert redigidos[1] <= _teto_da_redacao(), redigidos
    for saida in saidas:
        valor = saida["exception"]["values"][0]["value"]
        assert valor.startswith("falha 00000: aluno <nome>, RA <numero>, responsável <email>;")
        assert valor.endswith("...")
        assert saida["logentry"]["params"] == [
            "aluno <nome>, RA <numero>, responsável <email>, chave <token>"]
        assert saida["request"]["headers"] == {
            "Referer": "https://app.exemplo.test/publico/<token>?<redigido>",
            "User-Agent": "pytest"}
        migalhas = saida["breadcrumbs"]["values"]
        assert migalhas[-1]["message"].startswith(
            f"lendo {len(migalhas) - 1:05d}: aluno <nome>, RA <numero>")
        assert migalhas[0]["message"] == obs._FORA_DO_ORCAMENTO
        assert migalhas[0]["data"]["aluno"] == "<nome>"


def test_mesma_consulta_em_1000_spans_sai_redigida_em_todos_e_a_redacao_ve_um_texto(
        monkeypatch):
    """N+1: a mesma consulta em todos os spans é redigida uma vez só, e nenhum span
    perde a description por falta de orçamento."""
    vistos = _contando_a_redacao(monkeypatch)
    evento = {"type": "transaction", "spans": [
        {"op": "db", "description": _consulta(0, 1_500)} for _ in range(1000)]}
    saida = obs.higienizar_evento_sentry(evento, None)
    _sem_parte(str(saida), "N+1")
    [descricao] = {s["description"] for s in saida["spans"]}
    assert descricao.startswith("SELECT /* q00000 */") and descricao.endswith("...")
    assert _RE_MARCAS.search(descricao)
    visivel = obs._LIMITE_DO_SDK - 3
    assert 0 < sum(vistos) <= visivel + obs._TENTATIVAS_DE_CORTE * (visivel - obs._MARGEM - 1)


def test_description_longa_de_span_e_cortada_sem_deixar_pedaco_de_dado():
    """O SDK não corta a description de um span; o hook corta como o SDK corta os outros
    textos: com o corte em CADA posição de um dado, nenhum pedaço dele sobra no fim."""
    for dado in (NOME, CPF, TOKEN, EMAIL, "senha 'abc d3f ghi'"):
        for desvio in range(len(dado) + 2):
            antes = ("wz " * 400)[:_VISIVEL - desvio - 1] + " "
            evento = {"type": "transaction", "spans": [
                {"op": "db", "description": antes + dado + " wz" * 100}]}
            descricao = obs.higienizar_evento_sentry(evento, None)["spans"][0]["description"]
            texto = _RE_MARCAS.sub("", descricao)
            for pedaco in _pedacos(dado.removeprefix("senha ")):
                assert pedaco not in texto, f"{dado!r} cortado em {desvio}: {pedaco!r}"
            assert descricao.startswith("wz wz") and descricao.endswith("...")
            assert len(descricao) <= obs._LIMITE_DO_SDK


@pytest.mark.parametrize("sentry_real", [1.0], indirect=True)
def test_transacao_real_com_spans_distintos_respeita_o_orcamento(sentry_real, monkeypatch):
    """SDK de verdade com o tracing ligado: o ``before_send_transaction`` é o mesmo hook,
    e a description de cada span chega inteira (o SDK não a corta)."""
    import sentry_sdk

    vistos = _contando_a_redacao(monkeypatch)
    with sentry_sdk.start_transaction(name="/api/v1/alunos", op="http.server"):
        for i in range(300):
            with sentry_sdk.start_span(op="db", name=_consulta(i, 1_500)):
                pass
    sentry_sdk.flush()
    assert 0 < sum(vistos) <= _teto_da_redacao(), sum(vistos)
    _sem_parte(_corpo(sentry_real), "envelope")
    [transacao] = [e for e in (env.get_transaction_event() for env in sentry_real.envelopes)
                   if e]
    descricoes = [s["description"] for s in transacao["spans"]]
    assert len(descricoes) == 300
    assert any(d.startswith("SELECT /* q00000 */") and d.endswith("...") for d in descricoes)
    assert obs._FORA_DO_ORCAMENTO in descricoes


# --- Nome da transação e chaves de dict (revisão de 31/10, menores) ----------------


@pytest.mark.parametrize("sentry_real", [1.0], indirect=True)
def test_transacao_de_rota_nao_casada_real_sai_sem_host_e_sem_token(sentry_real):
    """Numa rota NÃO casada (404), o SentryAsgiMiddleware dá à transação o nome da URL
    crua, com o host e o token; a de uma rota casada leva o modelo dela."""
    import sentry_sdk
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/api/v1/publico/{token}")
    def publico(token: str):
        return {}

    with TestClient(app) as cliente:
        assert cliente.get("/api/v1/publico/tokpainel77/inexistente").status_code == 404
        assert cliente.get("/api/v1/publico/tokpainel78").status_code == 200
    sentry_sdk.flush()
    corpo = _corpo(sentry_real)
    assert corpo.find("tokpainel77") == -1 and corpo.find("tokpainel78") == -1
    nomes = sorted(e["transaction"] for e in (env.get_transaction_event()
                                              for env in sentry_real.envelopes) if e)
    assert nomes == ["/api/v1/publico/<token>/inexistente", "/api/v1/publico/{token}"]


@pytest.mark.parametrize(("nome", "fonte", "esperado"), [
    ("http://testserver/api/v1/publico/tokpainel77/x?busca=" + NOME.split()[0] + "#ancora",
     "url", "/api/v1/publico/<token>/x"),
    ("https://api.exemplo/api/v1/auth/redefinir-senha/" + TOKEN, "url",
     "/api/v1/auth/redefinir-senha/<token>"),
    ("/api/v1/publico/rede/painelsecreto9", None, "/api/v1/publico/rede/<token>"),
    ("http://[sem-par/api/v1/publico/painelsecreto9", "url",
     "http://[sem-par/api/v1/publico/<token>"),
    ("/api/v1/publico/{token}", "route", "/api/v1/publico/{token}"),
    ("app.routers.publico.painel", "component", "app.routers.publico.painel"),
])
def test_nome_da_transacao_que_nao_e_modelo_de_rota_sai_sem_segredo(nome, fonte, esperado):
    for tipo in ("transaction", None):                  # também no evento de erro
        evento = {"transaction": nome}
        if tipo:
            evento["type"] = tipo
        if fonte:
            evento["transaction_info"] = {"source": fonte}
        assert obs.higienizar_evento_sentry(evento, None)["transaction"] == esperado


def test_chave_de_dict_com_nome_sai_redigida_no_evento_e_no_meta():
    """O ``extra`` e o ``data`` são do app: uma chave pode ser o nome de uma criança. O
    ``_meta`` do SDK repete essa chave no caminho até o texto que ele cortou."""
    cortado = _cortado("observação " + "wz " * 600)
    evento = {
        "extra": {"por_aluno": {NOME: 3, NOME_2: 4, "turma 3B": 5}, "total": 12},
        "breadcrumbs": {"values": [{"message": "contagem", "data": {
            "por_aluno": {NOME: cortado}, EMAIL: 1}}]},
        "request": {"headers": {"Referer": "https://app.exemplo.test/x", "X-Ra-" + RA: "1"}},
        "_meta": {"extra": {"por_aluno": {NOME: {"": {"len": 9}}}},
                  "breadcrumbs": {"values": {"0": {"data": {"por_aluno": {
                      NOME: _meta_cortado(2000)}}}}}},
    }
    saida = obs.higienizar_evento_sentry(evento, None)
    _sem_parte(str(saida), "chaves")
    assert saida["extra"] == {"por_aluno": {"<nome>": 3, "<nome> #2": 4, "turma 3B": 5},
                              "total": 12}
    [migalha] = saida["breadcrumbs"]["values"]
    assert list(migalha["data"]) == ["por_aluno", "<email>"]
    [(chave, valor)] = migalha["data"]["por_aluno"].items()
    assert chave == "<nome>" and valor.startswith("observação wz") and valor.endswith("...")
    assert saida["request"]["headers"] == {"Referer": "https://app.exemplo.test/x",
                                           "X-Ra-<numero>": "1"}
    assert saida["_meta"] == {
        "extra": {"por_aluno": {"<nome>": {"": {"len": 9}}}},
        "breadcrumbs": {"values": {"0": {"data": {"por_aluno": {
            "<nome>": _meta_cortado(2000)}}}}}}


def test_chave_so_de_digitos_curta_sai_sem_gastar_orcamento_porque_a_redacao_nao_a_muda():
    """O atalho de ``_chave_redigida`` (o índice de uma lista no ``_meta``) só vale se a
    redação deixa igual todo texto de 1 a 5 dígitos ASCII: conferido aqui, um a um."""
    for n in range(1, obs._MIN_DIGITOS_DOCUMENTO):
        for i in range(10 ** n):
            texto = str(i).zfill(n)
            assert obs.redigir_dados_pessoais(texto) == texto, texto
    orcamento = obs._Orcamento(0)
    assert obs._chave_redigida("99999", orcamento) == "99999"
    assert obs._chave_redigida("123456", orcamento) == obs._FORA_DO_ORCAMENTO
    assert obs._chave_redigida("１２", orcamento) == obs._FORA_DO_ORCAMENTO   # não ASCII


def test_log_real_com_nome_na_chave_do_extra_chega_ao_sentry_sem_ele(sentry_real,
                                                                     logger_de_teste):
    import sentry_sdk

    logger_de_teste.info("lendo a turma", extra={"por_aluno": {NOME_2: 1}})
    logger_de_teste.error("contagem por aluno", extra={"por_aluno": {NOME: 3}})
    sentry_sdk.flush()
    _sem_parte(_corpo(sentry_real), "envelope")
    eventos = [e for e in _eventos(sentry_real) if e.get("logger") == logger_de_teste.name]
    assert len(eventos) == 1, [(e.get("logentry"), e.get("extra")) for e in eventos]
    [evento] = eventos
    assert evento["extra"]["por_aluno"] == {"<nome>": 3}
    # (o escopo do SDK guarda os breadcrumbs dos testes anteriores com o mesmo logger)
    [migalha] = [b for b in evento["breadcrumbs"]["values"]
                 if b.get("category") == logger_de_teste.name
                 and b.get("message") == "lendo a turma"]
    assert migalha["data"] == {"por_aluno": {"<nome>": 1}}
