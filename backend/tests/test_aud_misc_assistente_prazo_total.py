"""Prazo TOTAL das chamadas aos provedores externos de IA (REV-MISC-2, API_SEGURANCA-3).

O prazo do httpx vale POR OPERAÇÃO de rede: cada pedaço que chega recomeça a contagem.
Uma resposta que chega gotejando (um proxy/CDN no caminho) nunca estourava os 60 s e
segurava a thread do worker pelo tempo que o gotejamento durasse; e a pausa do SDK da
Anthropic antes da nova tentativa (o que o provedor pedir, até 60 s) também ficava fora
da conta. Aqui o prazo total cai para 1 s (escala dos 60 s) e um servidor HTTP local
goteja a resposta ao longo de ~4 s: a chamada tem de desistir perto de 1 s, com
``ErroProvedorIA`` (o assistente então responde no modo local).

Servidor só em 127.0.0.1 (porta livre escolhida pelo sistema), dentro do teste; nada
sai da máquina. Dados fictícios."""
import json
import socket
import threading
import time

import anthropic
import httpcore
import pytest

from app.services.ia import ErroProvedorIA, provedores
from app.services.ia.provedores import AnthropicProvedor, OpenAIProvedor

CONVERSA = [{"papel": "usuario", "conteudo": "Como está a escola?"}]
_ANTHROPIC = anthropic.Anthropic  # a classe do SDK, antes de qualquer troca
PRAZO_TOTAL_TESTE_S = 1.0
FOLGA_S = 1.5        # acima do prazo total, ainda bem abaixo dos ~4 s do gotejamento
GOTA_S = 0.1
GOTAS = 40           # 40 bytes, um a cada 0,1 s: ~4 s até a resposta completar

_CORPO = {
    "openai": json.dumps({"choices": [{"message": {"content": "Resposta gotejada."}}]}),
    "anthropic": json.dumps({
        "id": "msg_ficticia", "type": "message", "role": "assistant",
        "model": "modelo-ficticio", "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "content": [{"type": "text", "text": "Resposta gotejada."}]}),
}


def _ler_pedido(conexao: socket.socket) -> None:
    dados = b""
    while b"\r\n\r\n" not in dados:
        pedaco = conexao.recv(65536)
        if not pedaco:
            return
        dados += pedaco
    cabecalho, resto = dados.split(b"\r\n\r\n", 1)
    tamanho = 0
    for linha in cabecalho.split(b"\r\n"):
        if linha.lower().startswith(b"content-length:"):
            tamanho = int(linha.split(b":", 1)[1])
    while len(resto) < tamanho:
        pedaco = conexao.recv(65536)
        if not pedaco:
            return
        resto += pedaco


class _Servidor:
    """HTTP/1.1 mínimo em 127.0.0.1. ``modo``:

    * ``"normal"``    — responde de uma vez;
    * ``"corpo"``     — cabeçalho de uma vez, os primeiros bytes do corpo gotejando;
    * ``"cabecalho"`` — os primeiros bytes do PRÓPRIO cabeçalho gotejando;
    * ``"ocupado"``   — 529 na hora, pedindo para tentar de novo em 3 s; na nova
                        tentativa, responde normal."""

    def __init__(self, corpo: str, modo: str):
        self.corpo, self.modo = corpo.encode(), modo
        self.pedidos = 0
        self._parar = threading.Event()
        self._escuta = socket.socket()
        self._escuta.bind(("127.0.0.1", 0))
        self._escuta.listen(8)
        self._escuta.settimeout(0.1)
        self.porta = self._escuta.getsockname()[1]
        self._threads: list[threading.Thread] = []
        self._aceitar = threading.Thread(target=self._laco, daemon=True)
        self._aceitar.start()

    def _laco(self) -> None:
        while not self._parar.is_set():
            try:
                conexao, _ = self._escuta.accept()
            except (socket.timeout, OSError):
                continue
            t = threading.Thread(target=self._atender, args=(conexao,), daemon=True)
            self._threads.append(t)
            t.start()

    def _resposta(self) -> bytes:
        self.pedidos += 1
        if self.modo == "ocupado" and self.pedidos == 1:
            erro = json.dumps({"type": "error", "error": {
                "type": "overloaded_error", "message": "Ocupado (fictício)."}}).encode()
            return (b"HTTP/1.1 529 Overloaded\r\nContent-Type: application/json\r\n"
                    b"Retry-After: 3\r\nx-should-retry: true\r\n"
                    + f"Content-Length: {len(erro)}\r\nConnection: close\r\n\r\n".encode()
                    + erro)
        return (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(self.corpo)}\r\nConnection: close\r\n\r\n".encode()
                + self.corpo)

    def _atender(self, conexao: socket.socket) -> None:
        try:
            conexao.settimeout(10)
            _ler_pedido(conexao)
            resposta = self._resposta()
            inicio_gotas = {"corpo": resposta.index(b"\r\n\r\n") + 4, "cabecalho": 0}.get(
                self.modo)
            if inicio_gotas is None or self.pedidos > 1:
                conexao.sendall(resposta)
                return
            conexao.sendall(resposta[:inicio_gotas])
            for i in range(inicio_gotas, inicio_gotas + GOTAS):
                if self._parar.is_set():
                    return
                conexao.sendall(resposta[i:i + 1])
                time.sleep(GOTA_S)
            conexao.sendall(resposta[inicio_gotas + GOTAS:])
        except OSError:
            pass  # o cliente desistiu no meio: é o que se espera dele
        finally:
            conexao.close()

    def fechar(self) -> None:
        self._parar.set()
        self._aceitar.join(5)
        for t in self._threads:
            t.join(5)
        self._escuta.close()


@pytest.fixture()
def servidor():
    criados: list[_Servidor] = []

    def criar(provedor: str, modo: str) -> _Servidor:
        s = _Servidor(_CORPO[provedor], modo)
        criados.append(s)
        return s
    yield criar
    for s in criados:
        s.fechar()


def _chamar(monkeypatch, provedor: str, srv: _Servidor):
    """Aponta o provedor para o servidor local, com o prazo total de 1 s."""
    monkeypatch.setattr(provedores, "PRAZO_TOTAL_S", PRAZO_TOTAL_TESTE_S)
    base = f"http://127.0.0.1:{srv.porta}"
    if provedor == "openai":
        monkeypatch.setattr(provedores, "URL_OPENAI", f"{base}/v1/chat/completions")
        return lambda: OpenAIProvedor("sk-ficticia").responder("sistema", CONVERSA)

    class Local(_ANTHROPIC):
        def __init__(self, *args, **kwargs):
            kwargs["base_url"] = base   # o cliente HTTP continua o do provedor
            super().__init__(*args, **kwargs)
    monkeypatch.setattr(anthropic, "Anthropic", Local)
    return lambda: AnthropicProvedor("sk-ant-ficticia").responder("sistema", CONVERSA)


@pytest.mark.parametrize("provedor", ["openai", "anthropic"])
def test_resposta_normal_continua_chegando(monkeypatch, servidor, provedor):
    """O cliente com prazo total fala HTTP de verdade (sem transporte falso)."""
    srv = servidor(provedor, "normal")
    assert _chamar(monkeypatch, provedor, srv)() == "Resposta gotejada."


@pytest.mark.parametrize("modo", ["corpo", "cabecalho"])
@pytest.mark.parametrize("provedor", ["openai", "anthropic"])
def test_resposta_gotejando_estoura_o_prazo_total(monkeypatch, servidor, provedor, modo):
    srv = servidor(provedor, modo)
    chamar = _chamar(monkeypatch, provedor, srv)

    inicio = time.monotonic()
    with pytest.raises(ErroProvedorIA):
        chamar()
    duracao = time.monotonic() - inicio

    assert duracao < PRAZO_TOTAL_TESTE_S + FOLGA_S, (
        f"{provedor}/{modo}: a chamada durou {duracao:.2f} s com prazo total de "
        f"{PRAZO_TOTAL_TESTE_S} s")


def test_anthropic_ocupada_nao_espera_alem_do_prazo_total(monkeypatch, servidor):
    """529 pedindo 3 s de espera: a pausa antes da nova tentativa ficaria fora do
    prazo total. Responde na hora com ``ErroProvedorIA`` (o modo local assume)."""
    srv = servidor("anthropic", "ocupado")
    chamar = _chamar(monkeypatch, "anthropic", srv)

    inicio = time.monotonic()
    with pytest.raises(ErroProvedorIA):
        chamar()
    duracao = time.monotonic() - inicio

    assert duracao < PRAZO_TOTAL_TESTE_S + FOLGA_S, f"durou {duracao:.2f} s"


# --- A rede com prazo total, peça por peça (inclui o TLS, que o servidor local não usa)

class _FluxoFalso(httpcore.NetworkStream):
    def __init__(self):
        self.esperas: list = []

    def read(self, max_bytes, timeout=None):
        self.esperas.append(("read", timeout))
        return b""

    def write(self, buffer, timeout=None):
        self.esperas.append(("write", timeout))

    def close(self):
        self.esperas.append(("close", None))

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.esperas.append(("start_tls", timeout))
        return self

    def get_extra_info(self, info):
        return f"info:{info}"


def test_cada_operacao_espera_no_maximo_o_que_resta_do_prazo(monkeypatch):
    agora = [100.0]
    monkeypatch.setattr(provedores.time, "monotonic", lambda: agora[0])
    falso = _FluxoFalso()
    rede = provedores._RedeComPrazoTotal(limite=110.0)
    fluxo = provedores._FluxoComPrazoTotal(falso, rede)

    tls = fluxo.start_tls(ssl_context=None, server_hostname="exemplo.invalid", timeout=5.0)
    assert isinstance(tls, provedores._FluxoComPrazoTotal)   # o TLS segue com o prazo
    agora[0] = 107.0
    tls.read(10, timeout=60.0)
    tls.write(b"x", timeout=60.0)
    assert tls.get_extra_info("ssl_object") == "info:ssl_object"
    assert falso.esperas == [("start_tls", 5.0), ("read", 3.0), ("write", 3.0)]

    agora[0] = 110.0
    with pytest.raises(httpcore.ReadTimeout):
        tls.read(10, timeout=60.0)
    with pytest.raises(httpcore.WriteTimeout):
        tls.write(b"x", timeout=60.0)
    with pytest.raises(httpcore.ConnectTimeout):
        fluxo.start_tls(ssl_context=None, timeout=5.0)
    assert len(falso.esperas) == 3      # nenhuma operação começou depois do limite
