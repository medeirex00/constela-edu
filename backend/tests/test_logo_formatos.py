"""O envio do brasão/logo da prefeitura aceita SÓ PNG, JPEG e WEBP e confere as
dimensões pelo cabeçalho antes de decodificar.

Por quê: sem lista, o ``Image.open`` do Pillow tenta todos os decodificadores
(TIFF, EPS, PSD, ICO, GIF, BMP…) — é neles que caem as falhas de segurança do
Pillow. E uma imagem de poucos KB pode descomprimir para gigabytes. Recusado,
nada é gravado: a aparência continua como estava.
"""
import io

import pytest
from PIL import Image

API = "/api/v1"


def _imagem(formato: str, tamanho=(16, 16), modo="RGB") -> bytes:
    buffer = io.BytesIO()
    Image.new(modo, tamanho, 128).save(buffer, format=formato)
    return buffer.getvalue()


def _enviar(cliente, escola_id, conteudo: bytes, nome="logo.png", tipo_mime="image/png"):
    return cliente.post(f"{API}/escolas/{escola_id}/aparencia/logo?tipo=brasao",
                        files={"arquivo": (nome, conteudo, tipo_mime)})


def _brasao(cliente, escola_id) -> str:
    return cliente.get(f"{API}/escolas/{escola_id}/aparencia").json()["brasao_data_uri"]


@pytest.mark.parametrize("formato", ["PNG", "JPEG", "WEBP"])
def test_formatos_aceitos(cliente, escola_completa, formato):
    escola_id = escola_completa["escola"].id
    resposta = _enviar(cliente, escola_id, _imagem(formato))
    assert resposta.status_code == 200, resposta.text
    assert _brasao(cliente, escola_id).startswith("data:image/png;base64,")


@pytest.mark.parametrize("formato", ["TIFF", "GIF", "BMP", "ICO", "PCX", "PPM"])
def test_outros_formatos_sao_recusados_sem_gravar(cliente, escola_completa, formato):
    """O tipo MIME declarado pelo navegador não manda: o conteúdo é TIFF/GIF/…"""
    escola_id = escola_completa["escola"].id
    resposta = _enviar(cliente, escola_id, _imagem(formato))
    assert resposta.status_code == 400
    assert "PNG, JPG ou WEBP" in resposta.json()["detail"]
    assert _brasao(cliente, escola_id) == ""


def test_eps_nao_chega_ao_decodificador(cliente, escola_completa, monkeypatch):
    """EPS chamaria o Ghostscript; com a lista de formatos o plugin nem é consultado.
    O controle (Image.open sem lista) prova que o espião enxerga a consulta."""
    Image.init()
    fabrica, aceita = Image.OPEN["EPS"]
    consultado = []
    monkeypatch.setitem(Image.OPEN, "EPS", (fabrica, lambda prefixo: consultado.append(1)
                                            or aceita(prefixo)))
    eps = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\nshowpage\n"
    resposta = _enviar(cliente, escola_completa["escola"].id, eps, nome="logo.eps")
    assert resposta.status_code == 400
    assert consultado == []

    # Controle: sem a lista, o Image.open consulta o plugin EPS (e o reconhece). Sem
    # .load(): o controle não depende de haver Ghostscript na máquina.
    assert Image.open(io.BytesIO(eps)).format == "EPS"
    assert consultado != []


def test_open_recebe_a_lista_de_formatos(cliente, escola_completa, monkeypatch):
    chamadas = []
    original = Image.open

    def espiao(arquivo, *args, **kwargs):
        chamadas.append(kwargs.get("formats", args[1] if len(args) > 1 else None))
        return original(arquivo, *args, **kwargs)

    monkeypatch.setattr(Image, "open", espiao)
    assert _enviar(cliente, escola_completa["escola"].id, _imagem("PNG")).status_code == 200
    assert chamadas == [("PNG", "JPEG", "WEBP")]


def _espiar_decodificacao(monkeypatch):
    """Anota toda decodificação de pixels (ImageFile.load) e toda abertura (Image.open)."""
    from PIL import ImageFile

    eventos = []
    carregar, abrir = ImageFile.ImageFile.load, Image.open
    monkeypatch.setattr(ImageFile.ImageFile, "load",
                        lambda self, *a, **k: eventos.append("load") or carregar(self, *a, **k))
    monkeypatch.setattr(Image, "open",
                        lambda *a, **k: eventos.append("open") or abrir(*a, **k))
    return eventos


@pytest.mark.parametrize("formato", ["PNG", "JPEG"])
def test_dimensoes_conferidas_antes_de_decodificar(cliente, escola_completa, monkeypatch, formato):
    """4097 px de largura: recusado pelo cabeçalho, sem decodificar os pixels."""
    escola_id = escola_completa["escola"].id
    grande = _imagem(formato, tamanho=(4097, 1), modo="L")
    eventos = _espiar_decodificacao(monkeypatch)
    resposta = _enviar(cliente, escola_id, grande)
    assert resposta.status_code == 400
    assert "4096" in resposta.json()["detail"]
    assert eventos == ["open"]                      # abriu o cabeçalho e parou
    assert _brasao(cliente, escola_id) == ""


def _webp_vp8x(largura: int, altura: int) -> bytes:
    """Só o cabeçalho de um WEBP estendido (VP8X) que DECLARA um canvas enorme — o
    decodificador do Pillow alocaria canvas × 4 bytes (×2 se animado) no open."""
    corpo = (b"WEBP" + b"VP8X" + (10).to_bytes(4, "little") + bytes([0x02]) + b"\0\0\0"
             + (largura - 1).to_bytes(3, "little") + (altura - 1).to_bytes(3, "little"))
    return b"RIFF" + len(corpo).to_bytes(4, "little") + corpo


@pytest.mark.parametrize("conteudo", [
    _webp_vp8x(13000, 13000),
    _webp_vp8x(4097, 1),
    _imagem("WEBP", tamanho=(4097, 1)),               # com perda (VP8) gerado pelo Pillow
], ids=["vp8x-13000", "vp8x-4097", "vp8-4097"])
def test_webp_grande_recusado_antes_do_image_open(cliente, escola_completa, monkeypatch, conteudo):
    escola_id = escola_completa["escola"].id
    eventos = _espiar_decodificacao(monkeypatch)
    resposta = _enviar(cliente, escola_id, conteudo, nome="logo.webp", tipo_mime="image/webp")
    assert resposta.status_code == 400
    assert "4096" in resposta.json()["detail"]
    assert eventos == []                            # nem o Image.open (que alocaria o canvas)


@pytest.mark.parametrize("modo, opcoes", [
    ("RGB", {}),                                    # com perda: bloco VP8
    ("RGB", {"lossless": True}),                    # sem perda: bloco VP8L
    ("RGBA", {}),                                   # com alfa: bloco VP8X
], ids=["vp8", "vp8l", "vp8x"])
def test_cabecalho_webp_lido_igual_ao_pillow(modo, opcoes):
    from app.routers.admin import _dimensoes_webp
    for tamanho in [(1, 1), (37, 1000), (4096, 3), (16383, 2)]:
        buffer = io.BytesIO()
        Image.new(modo, tamanho, 100).save(buffer, format="WEBP", **opcoes)
        assert _dimensoes_webp(buffer.getvalue()) == tamanho == Image.open(buffer).size
    assert _dimensoes_webp(_imagem("PNG")) is None
    assert _dimensoes_webp(b"RIFF") is None


def test_bomba_recusada_pelo_pillow_recebe_a_mensagem_de_tamanho(cliente, escola_completa, monkeypatch):
    """Acima de 2 × MAX_IMAGE_PIXELS o próprio Image.open levanta DecompressionBombError:
    a mensagem é a de 'grande demais', não a de formato."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)       # 16×16 = 256 > 2 × 100
    resposta = _enviar(cliente, escola_completa["escola"].id, _imagem("PNG"))
    assert resposta.status_code == 400
    assert "grande demais" in resposta.json()["detail"]


def test_perfil_icc_do_envio_nao_vai_para_o_png(cliente, escola_completa):
    import base64

    escola_id = escola_completa["escola"].id
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), 128).save(buffer, format="JPEG", icc_profile=b"\0" * 200_000)
    resposta = _enviar(cliente, escola_id, buffer.getvalue(), nome="logo.jpg", tipo_mime="image/jpeg")
    assert resposta.status_code == 200, resposta.text
    png = base64.b64decode(_brasao(cliente, escola_id).split(",", 1)[1])
    assert b"iCCP" not in png
    assert len(png) < 5_000


def test_leitura_limitada_ao_teto(cliente, escola_completa, monkeypatch):
    """O handler lê no máximo 3 MB + 1 do arquivo — não o arquivo inteiro na memória.
    A leitura é a SÍNCRONA (``arquivo.file.read``): a rota é ``def`` e roda numa
    thread do pool, fora do event loop (UPLOADS-1)."""
    import tempfile

    from app.routers import admin

    tamanhos = []
    ler = tempfile.SpooledTemporaryFile.read

    def espiao(self, *args):
        tamanhos.append(args[0] if args else -1)
        return ler(self, *args)

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "read", espiao)
    resposta = _enviar(cliente, escola_completa["escola"].id, b"\x89PNG" + b"0" * (admin._LOGO_MAX_BYTES + 10))
    assert resposta.status_code == 413
    assert tamanhos == [admin._LOGO_MAX_BYTES + 1]


@pytest.mark.parametrize("tamanho", [(4096, 1), (1, 4096)])
def test_limite_de_dimensoes_inclusivo(cliente, escola_completa, tamanho):
    escola_id = escola_completa["escola"].id
    resposta = _enviar(cliente, escola_id, _imagem("PNG", tamanho=tamanho, modo="L"))
    assert resposta.status_code == 200, resposta.text
