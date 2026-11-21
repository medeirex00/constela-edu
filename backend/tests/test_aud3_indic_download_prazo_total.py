"""Prazo TOTAL do download do robô de avaliações (auditoria S_G_INDICADORES-3, REV3-INDIC-1).

O ``timeout`` do httpx vale POR OPERAÇÃO de rede: cada pedaço que chega recomeça a
contagem. Um servidor que manda o arquivo pouco a pouco (1 byte a cada 29 s, até o teto
de 150 MB) segurava o "Coletar agora" — a thread, a conexão do banco e a trava da fonte —
por tempo sem limite. Agora o download inteiro tem um prazo (``AVALIACOES_DOWNLOAD_PRAZO_S``,
10 min por padrão): passou dele, a coleta termina em erro, com a causa, e nada é gravado.
Aqui o prazo cai para 1 s e o servidor goteja o arquivo ao longo de ~4 s.

REV3-INDIC-1: o prazo era conferido só antes de cada pedido e a cada pedaço do CORPO. O
cabeçalho HTTP (o httpcore aceita até 100 KB dele, com o timeout valendo por leitura) e a
conexão segura (TLS) ficavam de fora: um servidor que gotejava o CABEÇALHO segurava a
coleta por semanas. Agora o prazo vale em cada leitura e escrita da conexão.

Servidor só em 127.0.0.1 (porta livre escolhida pelo sistema), dentro do teste; a guarda
anti-SSRF (https e IP público) é trocada só aqui, para o teste não precisar de TLS: o que
se mede é o prazo, não a guarda. Dados fictícios."""
import socket
import threading
import time

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import FonteAvaliacao, ResultadoAvaliacao
from app.services import avaliacoes as svc

PRAZO_TOTAL_TESTE_S = 1.0
FOLGA_S = 1.5        # acima do prazo total (e de uma leitura), bem abaixo dos ~4 s
GOTEJAMENTO_S = 4.0  # quanto o servidor leva para mandar a parte gotejada
GOTAS = 40           # o corpo: 40 bytes, um a cada 0,1 s

CORPO_GOTEJADO = b"x" * GOTAS
CABECALHO_DO_CORPO_GOTEJADO = (b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n"
                               b"Connection: close\r\n\r\n" % GOTAS)
# REV3-INDIC-1: a linha de status e o cabeçalho, 1 byte por vez (~80 bytes em ~4 s).
CABECALHO_GOTEJADO = (b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nX-Enchimento: "
                      + b"a" * 10 + b"\r\nConnection: close\r\n\r\n")


class _Servidor:
    """HTTP/1.1 mínimo em 127.0.0.1: lê o pedido, manda ``de_uma_vez`` na hora, goteja
    ``gotejado`` (1 byte por vez, ao longo de ~GOTEJAMENTO_S) e manda ``depois``. ``mudo``:
    lê o que chegar (o pedido, ou o início da conexão segura) e não responde nada por
    ~GOTEJAMENTO_S."""

    def __init__(self, de_uma_vez=b"", gotejado=b"", depois=b"", mudo=False):
        self._de_uma_vez, self._gotejado, self._depois = de_uma_vez, gotejado, depois
        self._mudo = mudo
        self._parar = threading.Event()
        self._escuta = socket.socket()
        self._escuta.bind(("127.0.0.1", 0))
        self._escuta.listen(4)
        self._escuta.settimeout(0.1)
        self.porta = self._escuta.getsockname()[1]
        self._thread = threading.Thread(target=self._laco, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._parar.set()
        self._thread.join(10)
        self._escuta.close()

    def _laco(self):
        while not self._parar.is_set():
            try:
                conexao, _ = self._escuta.accept()
            except OSError:
                continue
            with conexao:
                try:
                    conexao.recv(65536)
                    if self._mudo:
                        self._parar.wait(GOTEJAMENTO_S)
                        return
                    conexao.sendall(self._de_uma_vez)
                    for i in range(len(self._gotejado)):
                        if self._parar.wait(GOTEJAMENTO_S / len(self._gotejado)):
                            return
                        conexao.sendall(self._gotejado[i:i + 1])
                    conexao.sendall(self._depois)
                except OSError:
                    pass                       # o cliente desistiu (o prazo)


def _corpo_gotejado():
    return _Servidor(de_uma_vez=CABECALHO_DO_CORPO_GOTEJADO, gotejado=CORPO_GOTEJADO)


def _cabecalho_gotejado():
    return _Servidor(gotejado=CABECALHO_GOTEJADO, depois=b"xxxx")


def _sem_guarda(monkeypatch):
    monkeypatch.setattr(svc, "_exigir_destino_publico", lambda url: ["127.0.0.1"])
    monkeypatch.setattr(svc, "_resolver_publico", lambda host, porta: ["127.0.0.1"])
    monkeypatch.setattr(settings, "AVALIACOES_DOWNLOAD_PRAZO_S", PRAZO_TOTAL_TESTE_S)


def _baixar(url, timeout):
    comeco = time.monotonic()
    try:
        svc.baixar_url(url, timeout=timeout)
        erro = None
    except Exception as exc:  # noqa: BLE001 — o teste diz qual erro veio
        erro = f"{type(exc).__name__}: {exc}"
    return erro, time.monotonic() - comeco


def _coletar(db, porta):
    av = svc.obter_avaliacao(db, "ideb")
    fonte = FonteAvaliacao(
        avaliacao_id=av.id, nome="IDEB inventado", edicao=2023, indicador="ideb",
        url=f"http://127.0.0.1:{porta}/ideb.csv", unidade="indice",
        cadencia="manual", mapeamento={"linha_dados": 0, "col_inep": 0, "col_valor": 1})
    db.add(fonte)
    db.commit()
    comeco = time.monotonic()
    saida = svc.coletar_fonte(db, fonte)
    gasto = time.monotonic() - comeco
    db.commit()
    return fonte, saida, gasto


def test_download_que_goteja_para_no_prazo_total(monkeypatch):
    _sem_guarda(monkeypatch)
    with _corpo_gotejado() as servidor:
        erro, gasto = _baixar(f"http://127.0.0.1:{servidor.porta}/arquivo.zip", timeout=1.0)
    assert erro is not None, f"o download terminou sem erro em {gasto:.1f} s"
    assert erro.startswith("ValueError") and "prazo total" in erro, erro
    assert gasto < PRAZO_TOTAL_TESTE_S + FOLGA_S, f"o download durou {gasto:.1f} s"


def test_coletar_agora_com_download_lento_termina_em_erro_sem_gravar(db, monkeypatch):
    _sem_guarda(monkeypatch)
    with _corpo_gotejado() as servidor:
        fonte, saida, gasto = _coletar(db, servidor.porta)
    assert saida["status"] == "erro"
    assert "prazo total" in fonte.ultimo_erro
    assert gasto < PRAZO_TOTAL_TESTE_S + FOLGA_S, f"a coleta durou {gasto:.1f} s"
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0


def test_cabecalho_que_goteja_para_no_prazo_total(monkeypatch):
    """REV3-INDIC-1: o cabeçalho HTTP gotejado (1 byte por vez) também conta no prazo."""
    _sem_guarda(monkeypatch)
    with _cabecalho_gotejado() as servidor:
        erro, gasto = _baixar(f"http://127.0.0.1:{servidor.porta}/arquivo.zip", timeout=1.0)
    assert gasto < PRAZO_TOTAL_TESTE_S + FOLGA_S, (
        f"o download durou {gasto:.1f} s com prazo total de {PRAZO_TOTAL_TESTE_S:g} s: o "
        f"cabeçalho gotejado escapou do prazo (erro={erro!r})")
    assert erro is not None and erro.startswith("ValueError") and "prazo total" in erro, erro


def test_coletar_agora_com_cabecalho_gotejado_diz_que_passou_do_prazo(db, monkeypatch):
    """REV3-INDIC-1: pela coleta, o painel diz o prazo (não a falha de conexão genérica) e
    nada é gravado."""
    _sem_guarda(monkeypatch)
    with _cabecalho_gotejado() as servidor:
        fonte, saida, gasto = _coletar(db, servidor.porta)
    assert gasto < PRAZO_TOTAL_TESTE_S + FOLGA_S, f"a coleta durou {gasto:.1f} s"
    assert saida["status"] == "erro"
    assert "prazo total" in fonte.ultimo_erro, fonte.ultimo_erro
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0


def test_conexao_segura_parada_para_no_prazo_total(monkeypatch):
    """REV3-INDIC-1: a conexão segura (TLS) que não responde conta no prazo total, mesmo
    com a espera por operação maior que ele (3 s contra 1 s)."""
    _sem_guarda(monkeypatch)
    with _Servidor(mudo=True) as servidor:
        erro, gasto = _baixar(f"https://127.0.0.1:{servidor.porta}/arquivo.zip", timeout=3.0)
    assert gasto < PRAZO_TOTAL_TESTE_S + FOLGA_S, (
        f"a conexão segura parada durou {gasto:.1f} s com prazo total de "
        f"{PRAZO_TOTAL_TESTE_S:g} s (erro={erro!r})")
    assert erro is not None and erro.startswith("ValueError") and "prazo total" in erro, erro


def test_espera_por_leitura_dentro_do_prazo_continua_falha_de_conexao(monkeypatch):
    """O servidor que para de responder antes do prazo total estoura a espera POR LEITURA:
    continua uma falha de conexão (a mensagem única do painel), não o prazo total."""
    _sem_guarda(monkeypatch)
    monkeypatch.setattr(settings, "AVALIACOES_DOWNLOAD_PRAZO_S", 30.0)
    with _Servidor(mudo=True) as servidor:
        with pytest.raises(httpx.TimeoutException):
            svc.baixar_url(f"http://127.0.0.1:{servidor.porta}/arquivo.zip", timeout=0.3)
