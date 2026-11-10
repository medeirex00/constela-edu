"""N2: lote de livros do Elefante com pool e prazo contado da saída do pedido.

Antes, ``_JS_FETCH_LOTE`` criava TODOS os pedidos de uma turma de uma vez, cada um
com o AbortController de 20 s já correndo. Em HTTP/1.1 o navegador abre ~6
conexões por host: os demais esperavam na fila do navegador gastando o prazo, e os
últimos eram abortados sem ter saído. Agora são 6 de cada vez e o prazo nasce
quando o pedido sai.

Prova com o navegador DE VERDADE (Chromium do Playwright) contra um servidor local
com latência — nunca contra a plataforma. Em escala reduzida para a suíte: 40 alunos,
0,5 s por resposta e prazo de 2,5 s (a mesma proporção de 40 × 4 s com o prazo de
20 s, a medida pedida). Sem Chromium, pula (igual ao job da CI).
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.sync.connectors import elefante


class _Servidor:
    """HTTP/1.1 local: GET / → página vazia (mesma origem); POST /livros → espera
    ``latencia`` e devolve []; conta os pedidos simultâneos."""

    def __init__(self, latencia: float):
        self.latencia = latencia
        self.ao_mesmo_tempo = 0
        self.pico = 0
        self.recebidos = 0
        self._trava = threading.Lock()
        servidor = self

        class _H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_a):
                pass

            def _responder(self, corpo: bytes, tipo: str):
                self.send_response(200)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)

            def do_GET(self):  # noqa: N802
                self._responder(b"<!doctype html><title>t</title>", "text/html")

            def do_POST(self):  # noqa: N802
                tamanho = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(tamanho)
                with servidor._trava:
                    servidor.recebidos += 1
                    servidor.ao_mesmo_tempo += 1
                    servidor.pico = max(servidor.pico, servidor.ao_mesmo_tempo)
                try:
                    time.sleep(servidor.latencia)
                    self._responder(json.dumps([]).encode(), "application/json")
                finally:
                    with servidor._trava:
                        servidor.ao_mesmo_tempo -= 1

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self._http.daemon_threads = True
        self.base = f"http://127.0.0.1:{self._http.server_address[1]}"
        self._thread = threading.Thread(target=self._http.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_a):
        self._http.shutdown()
        self._http.server_close()


def _rodar_lote(js_lote: str, latencia: float):
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        pytest.skip("sem Playwright")
    with _Servidor(latencia) as srv, sync_playwright() as p:
        try:
            nav = p.chromium.launch()
        except Exception:  # noqa: BLE001
            pytest.skip("sem Chromium (igual ao job da CI)")
        try:
            pagina = nav.new_page()
            pagina.goto(srv.base + "/")
            inicio = time.monotonic()
            js = js_lote.replace("__URL_LOTE__", json.dumps(srv.base + "/livros"))
            saida = pagina.evaluate(js)
            return saida, time.monotonic() - inicio, srv
        finally:
            nav.close()


def _js(ids):
    return elefante.ConectorElefante._js_fetch_lote(
        "__URL_LOTE__", {}, "same-origin", {"courseId": 1}, ids).replace(
        json.dumps("__URL_LOTE__"), "__URL_LOTE__")


def test_lote_de_40_com_latencia_nao_aborta_nenhum_e_respeita_o_pool(monkeypatch):
    monkeypatch.setattr(elefante, "_LOTE_PRAZO_MS", 2500)
    ids = list(range(9400001, 9400041))
    saida, duracao, srv = _rodar_lote(_js(ids), latencia=0.5)

    erros = [i for i in saida if "books" not in i]
    assert erros == [], f"{len(erros)} pedido(s) abortado(s): {erros[:3]}"
    assert sorted(i["studentId"] for i in saida) == ids
    assert srv.recebidos == 40
    assert srv.pico <= elefante._LOTE_CONEXOES
    # 40 / 6 = 7 rodadas de 0,5 s: passou do prazo de 2,5 s sem abortar ninguém.
    assert duracao > 2.5


def test_aluno_travado_ainda_e_abortado_pelo_prazo(monkeypatch):
    """O prazo continua valendo para o pedido que SAIU e não volta."""
    monkeypatch.setattr(elefante, "_LOTE_PRAZO_MS", 300)
    saida, _duracao, _srv = _rodar_lote(_js([9400001, 9400002]), latencia=2.0)
    assert len(saida) == 2 and all("erro" in i for i in saida)
