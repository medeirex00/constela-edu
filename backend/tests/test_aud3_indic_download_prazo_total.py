"""Prazo TOTAL do download do robô de avaliações (auditoria S_G_INDICADORES-3).

O ``timeout`` do httpx vale POR OPERAÇÃO de rede: cada pedaço que chega recomeça a
contagem. Um servidor que manda o arquivo pouco a pouco (1 byte a cada 29 s, até o teto
de 150 MB) segurava o "Coletar agora" — a thread, a conexão do banco e a trava da fonte —
por tempo sem limite. Agora o download inteiro tem um prazo (``AVALIACOES_DOWNLOAD_PRAZO_S``,
10 min por padrão): passou dele, a coleta termina em erro, com a causa, e nada é gravado.
Aqui o prazo cai para 1 s e o servidor goteja o arquivo ao longo de ~4 s.

Servidor só em 127.0.0.1 (porta livre escolhida pelo sistema), dentro do teste; a guarda
anti-SSRF (https e IP público) é trocada só aqui, para o teste não precisar de TLS: o que
se mede é o prazo, não a guarda. Dados fictícios."""
import socket
import threading
import time

from sqlalchemy import func, select

from app.core.config import settings
from app.models import FonteAvaliacao, ResultadoAvaliacao
from app.services import avaliacoes as svc

PRAZO_TOTAL_TESTE_S = 1.0
FOLGA_S = 1.5        # acima do prazo total (e de uma leitura), bem abaixo dos ~4 s
GOTA_S = 0.1
GOTAS = 40           # 40 bytes, um a cada 0,1 s: ~4 s até o arquivo completar


class _Servidor:
    """HTTP/1.1 mínimo em 127.0.0.1 que manda o cabeçalho na hora e o corpo gotejando."""

    def __init__(self):
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
                    conexao.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n"
                                    b"Connection: close\r\n\r\n" % GOTAS)
                    for _ in range(GOTAS):
                        if self._parar.wait(GOTA_S):
                            return
                        conexao.sendall(b"x")
                except OSError:
                    pass                       # o cliente desistiu (o prazo)


def _sem_guarda(monkeypatch):
    monkeypatch.setattr(svc, "_exigir_destino_publico", lambda url: ["127.0.0.1"])
    monkeypatch.setattr(svc, "_resolver_publico", lambda host, porta: ["127.0.0.1"])
    monkeypatch.setattr(settings, "AVALIACOES_DOWNLOAD_PRAZO_S", PRAZO_TOTAL_TESTE_S)


def test_download_que_goteja_para_no_prazo_total(monkeypatch):
    _sem_guarda(monkeypatch)
    with _Servidor() as servidor:
        comeco = time.monotonic()
        try:
            svc.baixar_url(f"http://127.0.0.1:{servidor.porta}/arquivo.zip", timeout=1.0)
            erro = None
        except ValueError as exc:
            erro = str(exc)
        gasto = time.monotonic() - comeco
    assert erro is not None, f"o download terminou sem erro em {gasto:.1f} s"
    assert "prazo total" in erro
    assert gasto < PRAZO_TOTAL_TESTE_S + FOLGA_S, f"o download durou {gasto:.1f} s"


def test_coletar_agora_com_download_lento_termina_em_erro_sem_gravar(db, monkeypatch):
    _sem_guarda(monkeypatch)
    av = svc.obter_avaliacao(db, "ideb")
    with _Servidor() as servidor:
        fonte = FonteAvaliacao(
            avaliacao_id=av.id, nome="IDEB inventado", edicao=2023, indicador="ideb",
            url=f"http://127.0.0.1:{servidor.porta}/ideb.csv", unidade="indice",
            cadencia="manual", mapeamento={"linha_dados": 0, "col_inep": 0, "col_valor": 1})
        db.add(fonte)
        db.commit()
        comeco = time.monotonic()
        saida = svc.coletar_fonte(db, fonte)
        gasto = time.monotonic() - comeco
    db.commit()
    assert saida["status"] == "erro"
    assert "prazo total" in fonte.ultimo_erro
    assert gasto < PRAZO_TOTAL_TESTE_S + FOLGA_S, f"a coleta durou {gasto:.1f} s"
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0
