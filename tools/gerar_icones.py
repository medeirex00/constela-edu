"""Gera TODOS os ativos de identidade visual do Constela Edu, sem dependências.

Com a logo oficial em identidade/logo-oficial.png (o caso normal), aplica-a
em todos os destinos. Sem ela, desenha um provisório (quadrado azul #1B2A4A
com "C" branco). Escreve:
  * apps/desktop/src-tauri/icons/  → PNG/ICO/ICNS (empacotador do Tauri)
  * apps/web/public/               → logo.png, favicon.png, apple-touch-icon.png
  * apps/mobile/assets/            → icone.png, adaptive-icon.png, splash.png

PARA USAR A LOGO OFICIAL: salve-a como `identidade/logo-oficial.png`
(quadrada, fundo transparente ou sólido, mínimo 1024x1024) e rode este
script de novo — ele passa a usar a logo em vez do desenho gerado.

Uso:  python tools/gerar_icones.py
"""
from __future__ import annotations

import shutil
import struct
import zlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "apps" / "desktop" / "src-tauri" / "icons"
DESTINO_WEB = RAIZ / "apps" / "web" / "public"
DESTINO_MOBILE = RAIZ / "apps" / "mobile" / "assets"
LOGO_OFICIAL = RAIZ / "identidade" / "logo-oficial.png"

INDIGO = (27, 42, 74, 255)  # azul profundo da marca (#1B2A4A)
BRANCO = (255, 255, 255, 255)

# "C" em uma grade 5x7 (1 = pixel aceso)
LETRA = [
    "01110",
    "10001",
    "10000",
    "10000",
    "10000",
    "10001",
    "01110",
]


def desenhar(tamanho: int) -> bytes:
    """RGBA do ícone: fundo índigo, cantos arredondados e S branco."""
    pixels = bytearray()
    raio = tamanho // 8
    escala = max(1, tamanho // 12)
    largura_s = 5 * escala
    altura_s = 7 * escala
    origem_x = (tamanho - largura_s) // 2
    origem_y = (tamanho - altura_s) // 2

    for y in range(tamanho):
        for x in range(tamanho):
            # Cantos arredondados: fora do raio vira transparente
            dx = min(x, tamanho - 1 - x)
            dy = min(y, tamanho - 1 - y)
            if dx < raio and dy < raio:
                if (dx - raio) ** 2 + (dy - raio) ** 2 > raio ** 2:
                    pixels += bytes((0, 0, 0, 0))
                    continue

            cor = INDIGO
            if origem_x <= x < origem_x + largura_s and origem_y <= y < origem_y + altura_s:
                coluna = (x - origem_x) // escala
                linha = (y - origem_y) // escala
                if LETRA[linha][coluna] == "1":
                    cor = BRANCO
            pixels += bytes(cor)
    return bytes(pixels)


def png(tamanho: int) -> bytes:
    rgba = desenhar(tamanho)
    linhas = b"".join(
        b"\x00" + rgba[y * tamanho * 4:(y + 1) * tamanho * 4]
        for y in range(tamanho)
    )

    def chunk(tipo: bytes, dados: bytes) -> bytes:
        return (struct.pack(">I", len(dados)) + tipo + dados
                + struct.pack(">I", zlib.crc32(tipo + dados)))

    ihdr = struct.pack(">IIBBBBB", tamanho, tamanho, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(linhas, 9))
            + chunk(b"IEND", b""))


def ico(pngs: dict[int, bytes]) -> bytes:
    """ICO com entradas PNG (suportado desde o Windows Vista)."""
    tamanhos = sorted(pngs)
    cabecalho = struct.pack("<HHH", 0, 1, len(tamanhos))
    entradas = b""
    dados = b""
    offset = len(cabecalho) + 16 * len(tamanhos)
    for tamanho in tamanhos:
        corpo = pngs[tamanho]
        dimensao = 0 if tamanho >= 256 else tamanho
        entradas += struct.pack("<BBBBHHII", dimensao, dimensao, 0, 0, 1, 32,
                                len(corpo), offset)
        dados += corpo
        offset += len(corpo)
    return cabecalho + entradas + dados


def icns(pngs: dict[int, bytes]) -> bytes:
    """ICNS moderno: blocos PNG (ic07=128, ic08=256, ic09=512)."""
    tipos = {128: b"ic07", 256: b"ic08", 512: b"ic09"}
    blocos = b""
    for tamanho, tipo in tipos.items():
        if tamanho in pngs:
            corpo = pngs[tamanho]
            blocos += tipo + struct.pack(">I", len(corpo) + 8) + corpo
    return b"icns" + struct.pack(">I", len(blocos) + 8) + blocos


def _gerar_desktop(pngs: dict[int, bytes]) -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    (DESTINO / "32x32.png").write_bytes(pngs[32])
    (DESTINO / "128x128.png").write_bytes(pngs[128])
    (DESTINO / "128x128@2x.png").write_bytes(pngs[256])
    (DESTINO / "icon.png").write_bytes(pngs[512])
    (DESTINO / "icon.ico").write_bytes(ico({32: pngs[32], 128: pngs[128], 256: pngs[256]}))
    (DESTINO / "icon.icns").write_bytes(icns(pngs))


def _gerar_web_e_mobile(pngs: dict[int, bytes]) -> None:
    DESTINO_WEB.mkdir(parents=True, exist_ok=True)
    DESTINO_MOBILE.mkdir(parents=True, exist_ok=True)
    if LOGO_OFICIAL.exists():
        # Logo oficial: browsers e Expo redimensionam sozinhos
        for destino in (
            DESTINO_WEB / "logo.png",
            DESTINO_WEB / "favicon.png",
            DESTINO_WEB / "apple-touch-icon.png",
            DESTINO_MOBILE / "icone.png",
            DESTINO_MOBILE / "adaptive-icon.png",
            DESTINO_MOBILE / "splash.png",
        ):
            shutil.copyfile(LOGO_OFICIAL, destino)
        print(f"Logo oficial aplicada a partir de {LOGO_OFICIAL}")
    else:
        (DESTINO_WEB / "logo.png").write_bytes(pngs[512])
        (DESTINO_WEB / "favicon.png").write_bytes(pngs[128])
        (DESTINO_WEB / "apple-touch-icon.png").write_bytes(pngs[256])
        (DESTINO_MOBILE / "icone.png").write_bytes(pngs[1024])
        (DESTINO_MOBILE / "adaptive-icon.png").write_bytes(pngs[1024])
        (DESTINO_MOBILE / "splash.png").write_bytes(pngs[512])
        print("Logo oficial não encontrada em identidade/logo-oficial.png — "
              "usando a marca gerada (C índigo).")


def main() -> None:
    pngs = {tamanho: png(tamanho) for tamanho in (32, 128, 256, 512, 1024)}
    if LOGO_OFICIAL.exists():
        try:
            from PIL import Image  # opcional, só para redimensionar a logo oficial

            imagem = Image.open(LOGO_OFICIAL).convert("RGBA")
            import io
            for tamanho in pngs:
                buffer = io.BytesIO()
                imagem.resize((tamanho, tamanho)).save(buffer, format="PNG")
                pngs[tamanho] = buffer.getvalue()
        except ImportError:
            print("AVISO: instale pillow (pip install pillow) para gerar os "
                  "ícones do desktop a partir da logo oficial; por enquanto "
                  "o desktop mantém a marca gerada.")
    _gerar_desktop(pngs)
    _gerar_web_e_mobile(pngs)
    print("Identidade visual atualizada (desktop, web e mobile).")


if __name__ == "__main__":
    main()
