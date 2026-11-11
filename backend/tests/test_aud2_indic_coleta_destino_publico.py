"""Regressão G_INDICADORES-2: a guarda anti-SSRF da coleta de avaliação externa
(``POST /avaliacoes/fontes/{id}/coletar`` e o robô).

1. Só IP PÚBLICO (``is_global``): a faixa 100.64.0.0/10 (CGNAT, onde ficam metadados
   de nuvem como 100.100.100.200) passava, porque não é ``is_private``.
2. DNS rebinding: a guarda resolvia o nome e o httpx resolvia DE NOVO ao conectar; a
   2ª resposta podia ser um IP interno. Agora a conexão abre no IP conferido, na mesma
   resolução que a guarda viu.
3. O erro gravado em ``fonte.ultimo_erro`` (mostrado no painel) não diferencia porta
   aberta de porta fechada: falha de conexão vira uma mensagem única; o detalhe vai
   só para o log do servidor.

Rede FALSIFICADA: ``socket.getaddrinfo`` é trocado por um resolvedor falso que só
conhece hosts ``*.sonda.invalid``; a conexão "de verdade" do httpcore é interceptada
(nenhum pacote sai da máquina). O único ouvinte é local, em 127.0.0.1 (porta da faixa
reservada a esta frente).
"""
import logging
import socket
import threading

import httpcore
import httpx
import pytest

from app.services import avaliacoes as svc
from tests.test_avaliacoes_fontes import _fonte

_REAL = socket.getaddrinfo
PORTA_OUVINTE = 7121
IP_PUBLICO = "93.184.215.14"           # só a guarda o vê: a conexão é interceptada


def _info(ip: str, port: int):
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(fam, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))]


class ResolvedorFalso:
    """Responde aos nomes ``*.sonda.invalid`` com a fila dada (o último se repete);
    IPs literais locais vão ao resolvedor real (sem DNS)."""

    def __init__(self, respostas: dict[str, list[str]]):
        self.respostas = respostas
        self.chamadas: list[tuple[str, str]] = []

    def __call__(self, host, port, *a, **kw):
        if isinstance(host, bytes):
            host = host.decode()
        if host in ("127.0.0.1", "localhost"):
            return _REAL(host, port, *a, **kw)
        if host not in self.respostas:
            raise socket.gaierror(f"sonda: host desconhecido {host}")
        fila = self.respostas[host]
        ip = fila.pop(0) if len(fila) > 1 else fila[0]
        self.chamadas.append((host, ip))
        return _info(ip, int(port or 443))


class Ouvinte:
    """Ouvinte TCP local: registra quem conectou."""

    def __init__(self, porta: int):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", porta))
        self.sock.listen(5)
        self.sock.settimeout(5)
        self.conexoes: list[tuple] = []
        self.t = threading.Thread(target=self._rodar, daemon=True)
        self.t.start()

    def _rodar(self):
        try:
            while True:
                c, addr = self.sock.accept()
                self.conexoes.append(addr)
                c.close()
        except OSError:
            return

    def fechar(self):
        try:
            self.sock.close()
        except OSError:
            pass
        self.t.join(timeout=6)


@pytest.mark.parametrize("ip", ["100.64.0.1", "100.100.100.200", "100.127.255.254",
                                "::ffff:100.100.100.200"])
def test_faixa_cgnat_e_ipv4_mapeado_nao_passam_na_guarda(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", ResolvedorFalso({"nuvem.sonda.invalid": [ip]}))
    with pytest.raises(ValueError, match="não-pública"):
        svc._exigir_destino_publico("https://nuvem.sonda.invalid/arquivo.csv")


def test_ip_publico_literal_continua_aceito():
    svc._exigir_destino_publico("https://200.0.0.1/x")       # não levanta (nem resolve DNS)


def test_dns_rebinding_nao_leva_a_conexao_a_um_ip_interno(monkeypatch):
    # 1ª resolução: IP público; as seguintes: o loopback (onde há um ouvinte).
    falso = ResolvedorFalso({"rebind.sonda.invalid": [IP_PUBLICO, "127.0.0.1"]})
    monkeypatch.setattr(socket, "getaddrinfo", falso)
    ouvinte = Ouvinte(PORTA_OUVINTE)
    try:
        with pytest.raises(Exception):  # noqa: B017 — o que importa é a conexão
            svc.baixar_url(f"https://rebind.sonda.invalid:{PORTA_OUVINTE}/ideb.csv", timeout=4)
    finally:
        ouvinte.fechar()
    assert not ouvinte.conexoes, (
        f"a guarda validou {IP_PUBLICO} e a conexão foi ao loopback (DNS rebinding): "
        f"{ouvinte.conexoes}")


def test_a_conexao_abre_no_ip_que_a_guarda_conferiu(monkeypatch):
    falso = ResolvedorFalso({"fixo.sonda.invalid": [IP_PUBLICO]})
    monkeypatch.setattr(socket, "getaddrinfo", falso)
    conexoes = []

    def conectar(self, host, port, timeout=None, local_address=None, socket_options=None):
        conexoes.append((host, port))
        raise httpcore.ConnectError("sonda: sem rede")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", conectar)
    with pytest.raises(httpx.ConnectError):
        svc.baixar_url("https://fixo.sonda.invalid/ideb.csv", timeout=4)
    # O socket abriria no IP conferido (o TLS segue verificando o certificado pelo nome).
    assert conexoes == [(IP_PUBLICO, 443)]


@pytest.mark.parametrize("erro", [
    httpx.ConnectError("[WinError 10061] Nenhuma conexão pôde ser feita (recusou)"),
    httpx.ConnectError("[WinError 10054] Foi forçado o cancelamento de uma conexão"),
    httpx.ConnectTimeout("timed out"),
    httpx.ReadTimeout("timed out"),
    httpx.RemoteProtocolError("Server disconnected without sending a response."),
    ConnectionResetError(10054, "reset"),
])
def test_falha_de_conexao_vira_mensagem_unica_e_o_detalhe_so_no_log(db, caplog, erro):
    f = _fonte(db)

    def baixador(url):
        raise erro

    with caplog.at_level(logging.WARNING, logger="app.services.avaliacoes"):
        resumo = svc.coletar_fonte(db, f, baixador=baixador)
    assert resumo["status"] == "erro" and f.ultimo_status == "erro"
    assert str(erro) not in f.ultimo_erro and type(erro).__name__ not in f.ultimo_erro, (
        f"o erro gravado (o painel mostra) revela o detalhe da conexão: {f.ultimo_erro!r}")
    assert f.ultimo_erro == svc.ERRO_CONEXAO_FONTE
    assert f.ultimo_resumo == {"erro": svc.ERRO_CONEXAO_FONTE}
    assert str(erro) in caplog.text                    # o detalhe fica no log do servidor


def test_recusa_da_guarda_continua_dizendo_o_motivo(db, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        ResolvedorFalso({"interno.sonda.invalid": ["10.0.0.5"]}))
    f = _fonte(db)
    f.url = "https://interno.sonda.invalid/x.csv"
    db.commit()
    svc.coletar_fonte(db, f)
    assert f.ultimo_status == "erro" and "não-pública" in f.ultimo_erro
