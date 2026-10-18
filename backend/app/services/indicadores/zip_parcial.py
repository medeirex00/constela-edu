"""Leitura de ENTRADAS de um ZIP sem abrir o resto — de um arquivo local ou de uma
URL lida por HTTP Range (só os bytes da entrada pedida).

Por quê: o zip dos microdados da avaliação da alfabetização do INEP tem dezenas de
MB e traz o ``TS_ALUNO`` (dado por aluno, centenas de MB descomprimido). O Constela
só precisa das tabelas agregadas ``TS_MUNICIPIO`` e ``TS_ESTADO`` (cerca de 1 MB nos
três anos). Então:

1. lê só o FIM do arquivo — os 22 bytes do registro de fim do diretório central
   (a busca cresce de trás para a frente só se o zip tiver comentário) e, no ZIP64,
   o localizador e o registro de fim do ZIP64, cada um na faixa exata — e o
   DIRETÓRIO CENTRAL na faixa exata (a lista das entradas, poucos KB). Nenhum byte
   de entrada não pedida é buscado, nem o final do TS_ALUNO que antecede o diretório;
2. para cada entrada PEDIDA, lê só o cabeçalho local e os bytes comprimidos dela;
3. descomprime com teto de tamanho e CONFERE o CRC32 e o tamanho declarados no
   diretório central — CRC diferente = recusa (nada é usado);
4. NUNCA lê uma entrada de aluno (``TS_ALUNO``): o pedido é recusado antes de
   qualquer byte dela ser buscado. As outras entradas não pedidas também não são
   lidas.

O servidor que ignora o Range (responde 200 com o arquivo inteiro) é recusado na
hora, sem ler o corpo: nunca se baixa o zip inteiro. Se o arquivo muda no meio da
leitura (ETag/Last-Modified diferentes), recusa.

Suporta ZIP64 (o registro e o localizador de fim do ZIP64 e o campo extra 0x0001
nas entradas) e os métodos 0 (sem compressão) e 8 (deflate). Puro: o acesso aos
bytes é uma ``FonteBytes`` (arquivo local ou HTTP); o HTTP é injetável, e os testes
o substituem — nenhum teste sai para a internet.
"""
from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from app.services.avaliacoes import ImportacaoRecusada

_SIG_EOCD = b"PK\x05\x06"
_SIG_ZIP64_LOCALIZADOR = b"PK\x06\x07"
_SIG_ZIP64_EOCD = b"PK\x06\x06"
_SIG_CENTRAL = b"PK\x01\x02"
_SIG_LOCAL = b"PK\x03\x04"
_EOCD_FIXO = 22
_COMENTARIO_MAX = 0xFFFF
# Busca do registro de fim, de trás para a frente: 22 bytes bastam no zip sem
# comentário (o do INEP); com comentário, cresce até o máximo (22 + 65535). Ler
# mais que isso de uma vez traria bytes da última entrada (o TS_ALUNO, se for ela).
_PASSOS_CAUDA = (_EOCD_FIXO, 1024, 8192, _EOCD_FIXO + _COMENTARIO_MAX)
_MAX_DIRETORIO = 16 * 1024 * 1024
# Teto da entrada descomprimida: as tabelas agregadas têm ~1,6 MB.
MAX_ENTRADA = 30 * 1024 * 1024
# Teto do que se busca pela rede numa leitura inteira (cauda + diretório + as
# entradas agregadas). Muito abaixo do zip (17 a 44 MB) e do TS_ALUNO.
MAX_BYTES_REDE = 12 * 1024 * 1024
_TIMEOUT = 60.0


class FonteBytes(Protocol):
    """De onde vêm os bytes do zip (arquivo local ou HTTP Range)."""

    tamanho: int
    bytes_lidos: int

    def ler(self, inicio: int, quantidade: int) -> bytes: ...


@dataclass(frozen=True)
class Entrada:
    """Uma entrada do diretório central (o que o zip DECLARA sobre ela)."""

    nome: str
    metodo: int
    flags: int
    crc32: int
    bytes_comprimidos: int
    bytes: int
    offset_local: int
    data_interna: datetime | None

    @property
    def base(self) -> str:
        return re.split(r"[\\/]", self.nome)[-1]

    @property
    def crc32_hex(self) -> str:
        return f"{self.crc32:08x}"


def entrada_de_aluno(nome: str) -> bool:
    """Entrada com dado POR ALUNO (``TS_ALUNO`` e afins): nunca é lida."""
    return "ALUNO" in re.split(r"[\\/]", nome or "")[-1].upper()


# --- Fontes de bytes -------------------------------------------------------------

class FonteArquivoLocal:
    """Zip num arquivo local: lê só as faixas pedidas (seek + read)."""

    def __init__(self, caminho: str | Path):
        self.caminho = Path(caminho)
        self.tamanho = self.caminho.stat().st_size
        self.bytes_lidos = 0
        self.faixas: list[tuple[int, int]] = []

    def ler(self, inicio: int, quantidade: int) -> bytes:
        _conferir_faixa(inicio, quantidade, self.tamanho)
        with self.caminho.open("rb") as f:
            f.seek(inicio)
            dados = f.read(quantidade)
        if len(dados) != quantidade:
            raise ImportacaoRecusada("O arquivo zip terminou antes do esperado (cortado).")
        self.bytes_lidos += quantidade
        self.faixas.append((inicio, inicio + quantidade))
        return dados


@dataclass
class RespostaFaixa:
    """Resposta de UMA requisição com Range (o corpo já lido, com teto)."""

    status: int
    cabecalhos: dict[str, str]
    corpo: bytes


# (url, valor do cabeçalho Range, máximo de bytes do corpo) → RespostaFaixa
BuscarFaixa = Callable[[str, str, int], RespostaFaixa]


def buscar_faixa_https(url: str, faixa: str, maximo: int, *,
                       transporte=None) -> RespostaFaixa:
    """Uma requisição GET com ``Range`` (só https para host público — a mesma guarda
    anti-SSRF do robô de coleta, revalidada a cada redirecionamento). Resposta que
    não é 206 é devolvida SEM ler o corpo: quem chama recusa (nunca se baixa o zip
    inteiro). O corpo é lido com teto. ``transporte`` (httpx) é só para os testes."""
    import httpx

    from app.services import avaliacoes as svc

    cabecalhos = {"User-Agent": svc._UA_NAVEGADOR, "Accept": "*/*", "Range": faixa,
                  "Accept-Encoding": "identity"}
    opcoes = {"timeout": _TIMEOUT, "follow_redirects": False, "headers": cabecalhos}
    if transporte is not None:
        opcoes["transport"] = transporte
    with httpx.Client(**opcoes) as cli:
        for _ in range(svc._MAX_REDIRECTS + 1):
            svc._exigir_destino_publico(url)
            with cli.stream("GET", url) as r:
                if r.is_redirect:
                    destino = r.headers.get("location")
                    if not destino:
                        raise ImportacaoRecusada("O servidor redirecionou sem destino.")
                    url = str(r.url.join(destino))
                    continue
                saida = {k.lower(): v for k, v in r.headers.items()}
                if r.status_code != 206:
                    return RespostaFaixa(r.status_code, saida, b"")   # corpo NÃO lido
                buf = bytearray()
                for pedaco in r.iter_bytes():
                    buf += pedaco
                    if len(buf) > maximo:
                        raise ImportacaoRecusada(
                            "O servidor mandou mais bytes que a faixa pedida; leitura "
                            "interrompida (nunca se baixa o zip inteiro).")
                return RespostaFaixa(r.status_code, saida, bytes(buf))
    raise ImportacaoRecusada("Excesso de redirecionamentos na leitura por faixa.")


_RE_CONTENT_RANGE = re.compile(r"^\s*bytes\s+(\d+)-(\d+)/(\d+|\*)\s*$", re.IGNORECASE)


class FonteHTTPRange:
    """Zip numa URL: cada leitura é uma requisição com ``Range``. A 1ª lê os últimos
    22 bytes (o registro de fim, num zip sem comentário) e descobre o tamanho pelo
    ``Content-Range``; a ETag e o Last-Modified dela valem para todas as outras — se
    mudarem, o arquivo mudou no meio: recusa."""

    def __init__(self, url: str, buscar: BuscarFaixa | None = None, *,
                 max_bytes: int = MAX_BYTES_REDE):
        self.url = url
        self.buscar = buscar or buscar_faixa_https
        self.max_bytes = max_bytes
        self.bytes_lidos = 0
        self.faixas: list[tuple[int, int]] = []
        self.requisicoes = 0
        resposta = self._pedir(f"bytes=-{_EOCD_FIXO}", _EOCD_FIXO)
        inicio, fim, total = self._content_range(resposta)
        if fim - inicio + 1 != len(resposta.corpo) or fim != total - 1:
            raise ImportacaoRecusada(
                "O servidor respondeu ao Range com uma faixa que não é o fim do arquivo.")
        self.tamanho = total
        self.last_modified = resposta.cabecalhos.get("last-modified")
        self.etag = resposta.cabecalhos.get("etag")
        self._cauda_inicio = inicio
        self._cauda = resposta.corpo
        self.faixas.append((inicio, fim + 1))

    def _pedir(self, faixa: str, maximo: int) -> RespostaFaixa:
        if self.bytes_lidos + maximo > self.max_bytes:
            raise ImportacaoRecusada(
                f"A leitura por faixa passaria de {self.max_bytes // (1024 * 1024)} MB — "
                "muito mais que as tabelas agregadas. Interrompida (o zip inteiro nunca é "
                "baixado).")
        self.requisicoes += 1
        resposta = self.buscar(self.url, faixa, maximo)
        if resposta.status != 206:
            raise ImportacaoRecusada(
                f"O servidor não aceitou a leitura por faixa (HTTP Range): respondeu "
                f"{resposta.status} em vez de 206. Para não baixar o zip inteiro (que traz o "
                "TS_ALUNO, dado de aluno), a leitura foi interrompida. Nada foi gerado.")
        self.bytes_lidos += len(resposta.corpo)
        return resposta

    @staticmethod
    def _content_range(resposta: RespostaFaixa) -> tuple[int, int, int]:
        casou = _RE_CONTENT_RANGE.match(resposta.cabecalhos.get("content-range", ""))
        if not casou or casou.group(3) == "*":
            raise ImportacaoRecusada(
                "A resposta ao Range não tem um Content-Range válido (bytes início-fim/total).")
        return int(casou.group(1)), int(casou.group(2)), int(casou.group(3))

    def ler(self, inicio: int, quantidade: int) -> bytes:
        _conferir_faixa(inicio, quantidade, self.tamanho)
        if quantidade == 0:
            return b""
        fim = inicio + quantidade
        if inicio >= self._cauda_inicio:              # já está no fim lido
            return self._cauda[inicio - self._cauda_inicio:fim - self._cauda_inicio]
        resposta = self._pedir(f"bytes={inicio}-{fim - 1}", quantidade)
        r_ini, r_fim, total = self._content_range(resposta)
        if (r_ini, r_fim, total) != (inicio, fim - 1, self.tamanho) or len(resposta.corpo) != quantidade:
            raise ImportacaoRecusada(
                f"O servidor devolveu outra faixa (pedido {inicio}-{fim - 1}, veio "
                f"{r_ini}-{r_fim}/{total}). Leitura interrompida.")
        for campo, inicial in (("etag", self.etag), ("last-modified", self.last_modified)):
            atual = resposta.cabecalhos.get(campo)
            if inicial and atual and atual != inicial:
                raise ImportacaoRecusada(
                    f"O arquivo mudou durante a leitura ({campo}: {inicial} → {atual}). "
                    "Rode de novo. Nada foi gerado.")
        self.faixas.append((inicio, fim))
        return resposta.corpo


def _conferir_faixa(inicio: int, quantidade: int, tamanho: int) -> None:
    if inicio < 0 or quantidade < 0 or inicio + quantidade > tamanho:
        raise ImportacaoRecusada(
            f"O zip aponta para fora do próprio arquivo ({inicio}+{quantidade} > {tamanho}): "
            "arquivo corrompido ou cortado.")


# --- Diretório central -------------------------------------------------------------

def _data_dos(data: int, hora: int) -> datetime | None:
    try:
        return datetime(1980 + (data >> 9), (data >> 5) & 0xF, data & 0x1F,
                        hora >> 11, (hora >> 5) & 0x3F, (hora & 0x1F) * 2)
    except ValueError:
        return None


def _achar_eocd(cauda: bytes) -> int:
    """Posição do registro de fim cujo comentário termina exatamente no fim, ou -1."""
    pos = cauda.rfind(_SIG_EOCD)
    while pos >= 0:
        if pos + _EOCD_FIXO <= len(cauda):
            comentario = struct.unpack_from("<H", cauda, pos + 20)[0]
            if pos + _EOCD_FIXO + comentario == len(cauda):
                return pos
        pos = cauda.rfind(_SIG_EOCD, 0, pos)
    return -1


def _localizar_diretorio(fonte: FonteBytes) -> tuple[int, int, int]:
    """``(offset, tamanho, entradas)`` do diretório central (com ZIP64)."""
    pos, inicio_cauda, cauda = -1, 0, b""
    for passo in _PASSOS_CAUDA:
        n = min(passo, fonte.tamanho)
        inicio_cauda = fonte.tamanho - n
        cauda = fonte.ler(inicio_cauda, n)
        pos = _achar_eocd(cauda)
        if pos >= 0 or n == fonte.tamanho:
            break
    if pos < 0:
        raise ImportacaoRecusada("O arquivo não é um zip válido (sem o registro de fim do "
                                 "diretório central).")
    eocd = inicio_cauda + pos
    (_, _, _, entradas, tam_dir, off_dir, _) = struct.unpack_from("<HHHHIIH", cauda, pos + 4)
    if entradas == 0xFFFF or tam_dir == 0xFFFFFFFF or off_dir == 0xFFFFFFFF:
        # ZIP64: o localizador (20 bytes) fica logo antes do registro de fim; ele diz
        # onde está o registro de fim do ZIP64 (56 bytes). Cada um na faixa exata.
        if eocd < 20:
            raise ImportacaoRecusada("Zip ZIP64 sem o localizador do fim do ZIP64.")
        localizador = fonte.ler(eocd - 20, 20)
        if localizador[:4] != _SIG_ZIP64_LOCALIZADOR:
            raise ImportacaoRecusada("Zip ZIP64 sem o localizador do fim do ZIP64.")
        off_eocd64 = struct.unpack_from("<Q", localizador, 8)[0]
        if off_eocd64 + 56 > eocd - 20:
            raise ImportacaoRecusada("Zip ZIP64 com o registro de fim do ZIP64 inválido.")
        registro = fonte.ler(off_eocd64, 56)
        if registro[:4] != _SIG_ZIP64_EOCD:
            raise ImportacaoRecusada("Zip ZIP64 com o registro de fim do ZIP64 inválido.")
        entradas, tam_dir, off_dir = struct.unpack_from("<QQQ", registro, 32)
    if off_dir + tam_dir > fonte.tamanho or tam_dir > _MAX_DIRETORIO:
        raise ImportacaoRecusada("O diretório central do zip é inválido ou grande demais.")
    return off_dir, tam_dir, entradas


def listar_entradas(fonte: FonteBytes) -> list[Entrada]:
    """As entradas que o zip declara (só o diretório central é lido)."""
    off_dir, tam_dir, quantas = _localizar_diretorio(fonte)
    if off_dir + tam_dir <= fonte.tamanho and tam_dir:
        diretorio = fonte.ler(off_dir, tam_dir)
    else:
        diretorio = b""
    saida: list[Entrada] = []
    p = 0
    while p + 46 <= len(diretorio) and diretorio[p:p + 4] == _SIG_CENTRAL:
        (_, _, flags, metodo, hora, data, crc, comp, desc, n_nome, n_extra, n_coment,
         _, _, _, off_local) = struct.unpack_from("<HHHHHHIIIHHHHHII", diretorio, p + 4)
        bruto = diretorio[p + 46:p + 46 + n_nome]
        nome = bruto.decode("utf-8" if flags & 0x800 else "cp437", errors="replace")
        extra = diretorio[p + 46 + n_nome:p + 46 + n_nome + n_extra]
        desc, comp, off_local = _zip64_extra(extra, desc, comp, off_local)
        saida.append(Entrada(nome=nome, metodo=metodo, flags=flags, crc32=crc,
                             bytes_comprimidos=comp, bytes=desc, offset_local=off_local,
                             data_interna=_data_dos(data, hora)))
        p += 46 + n_nome + n_extra + n_coment
    if len(saida) != quantas:
        raise ImportacaoRecusada(
            f"O diretório central do zip declara {quantas} entradas e tem {len(saida)} "
            "(arquivo corrompido).")
    return saida


def _zip64_extra(extra: bytes, desc: int, comp: int, off_local: int) -> tuple[int, int, int]:
    """Troca os campos 0xFFFFFFFF pelos de 8 bytes do extra ZIP64 (id 0x0001), na
    ordem da especificação: descomprimido, comprimido, offset do cabeçalho local."""
    q = 0
    while q + 4 <= len(extra):
        tipo, tam = struct.unpack_from("<HH", extra, q)
        if tipo == 0x0001:
            campos = extra[q + 4:q + 4 + tam]
            k = 0
            valores = []
            for atual in (desc, comp, off_local):
                if atual == 0xFFFFFFFF:
                    if k + 8 > len(campos):
                        raise ImportacaoRecusada("Extra ZIP64 da entrada é inválido.")
                    valores.append(struct.unpack_from("<Q", campos, k)[0])
                    k += 8
                else:
                    valores.append(atual)
            return valores[0], valores[1], valores[2]
        q += 4 + tam
    if 0xFFFFFFFF in (desc, comp, off_local):
        raise ImportacaoRecusada("Entrada ZIP64 sem o campo extra ZIP64.")
    return desc, comp, off_local


# --- Uma entrada -------------------------------------------------------------------

def ler_entrada(fonte: FonteBytes, entrada: Entrada, *, maximo: int = MAX_ENTRADA) -> bytes:
    """Os bytes DESCOMPRIMIDOS de uma entrada, com o CRC32 e o tamanho conferidos.
    Entrada de aluno é recusada antes de qualquer leitura."""
    if entrada_de_aluno(entrada.nome):
        raise ImportacaoRecusada(
            f"A entrada “{entrada.nome}” é dado POR ALUNO e nunca é lida pelo Constela. "
            "Só as tabelas agregadas TS_MUNICIPIO e TS_ESTADO.")
    if entrada.flags & 0x1:
        raise ImportacaoRecusada(f"A entrada “{entrada.nome}” está cifrada; não é o arquivo "
                                 "público do INEP.")
    if entrada.bytes > maximo or entrada.bytes_comprimidos > maximo:
        raise ImportacaoRecusada(
            f"A entrada “{entrada.nome}” tem {entrada.bytes // (1024 * 1024)} MB — muito "
            "maior que uma tabela agregada. Não foi lida.")
    if entrada.metodo not in (0, 8):
        raise ImportacaoRecusada(
            f"A entrada “{entrada.nome}” usa um método de compressão não suportado "
            f"({entrada.metodo}); só 0 (sem compressão) e 8 (deflate).")
    cab = fonte.ler(entrada.offset_local, 30)
    if cab[:4] != _SIG_LOCAL:
        raise ImportacaoRecusada(f"Cabeçalho local da entrada “{entrada.nome}” inválido.")
    n_nome, n_extra = struct.unpack_from("<HH", cab, 26)
    dados = fonte.ler(entrada.offset_local + 30 + n_nome + n_extra, entrada.bytes_comprimidos)
    if entrada.metodo == 0:
        conteudo = dados
    else:
        d = zlib.decompressobj(-15)
        try:
            conteudo = d.decompress(dados, entrada.bytes + 1)
        except zlib.error as exc:
            raise ImportacaoRecusada(
                f"A entrada “{entrada.nome}” não descomprime (arquivo corrompido).") from exc
    if len(conteudo) != entrada.bytes:
        raise ImportacaoRecusada(
            f"A entrada “{entrada.nome}” tem {len(conteudo)} bytes descomprimida; o zip "
            f"declara {entrada.bytes} (arquivo corrompido). Nada foi usado.")
    crc = zlib.crc32(conteudo) & 0xFFFFFFFF
    if crc != entrada.crc32:
        raise ImportacaoRecusada(
            f"O CRC32 da entrada “{entrada.nome}” não confere ({crc:08x}; o zip declara "
            f"{entrada.crc32:08x}): arquivo corrompido ou adulterado. Nada foi usado.")
    return conteudo
